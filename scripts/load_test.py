"""
Exam-day load test: many simulated students sign up through a signup link, start the test, answer every
question and submit, all at the same time. Reports latency percentiles and errors per API call.

It CREATES REAL ACCOUNTS (emails @loadtest.invalid) in whatever database the target uses, so run it against a
staging deployment whose MONGODB_DB points to a separate database, never against production data.

    python scripts/load_test.py --base-url https://staging.example.com --code SRMAP-AbC123xyz \
        --students 500 --concurrency 100 --i-understand-this-creates-accounts

Standard library only (no install needed).
"""
import argparse
import json
import random
import statistics
import threading
import time
import urllib.error
import urllib.request
import uuid
from collections import defaultdict
from concurrent.futures import ThreadPoolExecutor

lock = threading.Lock()
timings = defaultdict(list)
statuses = defaultdict(lambda: defaultdict(int))


def call(base, method, path, body=None, token=None, label=None, retries=3):
    """One API call with the same retry policy as the portal (retry 429/502/503/504 and network errors)"""
    label = label or path
    data = json.dumps(body).encode() if body is not None else None
    headers = {"Content-Type": "application/json"}
    if token:
        headers["Authorization"] = f"Bearer {token}"
    for attempt in range(retries + 1):
        started = time.perf_counter()
        status, payload = 0, {}
        try:
            req = urllib.request.Request(base + path, data=data, method=method, headers=headers)
            with urllib.request.urlopen(req, timeout=30) as r:
                status, payload = r.status, json.loads(r.read() or b"{}")
        except urllib.error.HTTPError as e:
            status = e.code
            try:
                payload = json.loads(e.read() or b"{}")
            except ValueError:
                payload = {}
        except Exception as e:  # timeout / connection refused
            payload = {"error": str(e)}
        elapsed = time.perf_counter() - started
        with lock:
            timings[label].append(elapsed)
            statuses[label][status] += 1
        if status in (0, 429, 502, 503, 504) and attempt < retries:
            time.sleep(min(8, 0.5 * 2 ** attempt) * (0.5 + random.random()))
            continue
        return status, payload


def program_slugs(base):
    """Signup requires a Masters program whenever the catalog has any; pick from the visible ones"""
    status, catalog = call(base, "GET", "/api/catalog", label="catalog")
    return [p["slug"] for p in (catalog.get("programs") or []) if p.get("slug")] if status == 200 else []


def student(base, code, n, run, think, programs):
    email = f"student{n}-{run}@loadtest.invalid"
    st, link = call(base, "POST", "/api/portal/join/validate", {"code": code}, label="join/validate")
    if st != 200 or not link.get("valid"):
        return f"validate failed: {st} {link}"
    body = {
        "code": code, "full_name": f"Load Test {n}", "email": email, "phone": f"+9190000{n:05d}"[:13],
        "password": "loadtest-password", "degree": "B.Tech", "department": link.get("department") or "CSE",
        "graduation_year": "2027", "registration_number": f"LT{run}{n}",
    }
    if not link.get("university"):
        body["university_id"] = link["universities"][0]["id"]
    if programs:
        body["program_slug"] = random.choice(programs)
    st, joined = call(base, "POST", "/api/portal/join", body, label="join")
    if st != 200:
        return f"join failed: {st} {joined}"
    token, test_id = joined["access_token"], joined.get("next_test_id")
    call(base, "GET", "/api/portal/me", token=token, label="me")
    call(base, "GET", "/api/portal/assessments", token=token, label="assessments")
    if not test_id:
        return "no test to take"
    st, paper = call(base, "POST", f"/api/portal/assessments/{test_id}/start", {}, token, label="start")
    if st != 200 or "questions" not in paper:
        return f"start failed: {st} {paper}"
    for q in paper["questions"]:
        if think:
            time.sleep(random.uniform(0, think))
        st, _ = call(base, "PUT", f"/api/portal/attempts/{paper['attempt_id']}/answer",
                     {"question_id": q["id"], "option": random.randrange(len(q["options"]))}, token, label="answer")
        if st != 200:
            return f"answer failed: {st}"
    st, result = call(base, "POST", f"/api/portal/attempts/{paper['attempt_id']}/submit", {}, token, label="submit")
    return None if st == 200 else f"submit failed: {st} {result}"


def pct(values, p):
    values = sorted(values)
    return values[min(len(values) - 1, int(round(p / 100 * (len(values) - 1))))]


def main():
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--base-url", required=True, help="e.g. https://staging.example.com (no trailing slash)")
    ap.add_argument("--code", required=True, help="signup link code (the part after ?code=)")
    ap.add_argument("--students", type=int, default=100)
    ap.add_argument("--concurrency", type=int, default=50, help="students active at the same time")
    ap.add_argument("--think", type=float, default=0, help="max seconds a student waits before each answer")
    ap.add_argument("--i-understand-this-creates-accounts", action="store_true", dest="confirmed")
    args = ap.parse_args()
    if not args.confirmed:
        ap.error("this creates real accounts; pass --i-understand-this-creates-accounts and target a staging database")
    base = args.base_url.rstrip("/")
    run = uuid.uuid4().hex[:6]

    print(f"{args.students} students, {args.concurrency} at a time, against {base} (run {run})")
    programs = program_slugs(base)
    started = time.perf_counter()
    failures = []
    with ThreadPoolExecutor(max_workers=args.concurrency) as pool:
        for problem in pool.map(lambda n: student(base, args.code, n, run, args.think, programs), range(args.students)):
            if problem:
                failures.append(problem)
    wall = time.perf_counter() - started

    total = sum(len(v) for v in timings.values())
    print(f"\n{total} requests in {wall:.1f}s = {total / wall:.0f} req/s; "
          f"{args.students - len(failures)}/{args.students} students finished the test\n")
    print(f"{'call':<16}{'count':>7}{'p50 ms':>9}{'p95 ms':>9}{'p99 ms':>9}{'max ms':>9}  statuses")
    for label, values in timings.items():
        ms = [v * 1000 for v in values]
        codes = ", ".join(f"{k}:{v}" for k, v in sorted(statuses[label].items()))
        print(f"{label:<16}{len(ms):>7}{statistics.median(ms):>9.0f}{pct(ms, 95):>9.0f}{pct(ms, 99):>9.0f}{max(ms):>9.0f}  {codes}")
    if failures:
        print(f"\n{len(failures)} students failed. First few:")
        for f in failures[:5]:
            print("  ", f)


if __name__ == "__main__":
    main()
