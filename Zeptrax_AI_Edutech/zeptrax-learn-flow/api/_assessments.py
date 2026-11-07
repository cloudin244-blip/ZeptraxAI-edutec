"""
Assessments (exams) for the university portal, served under /api/portal/assessments and /api/portal/attempts.

Students get one attempt per assessment. The server owns the clock (deadline), shuffles questions and options
per attempt, never sends correct answers to students, and scores the attempt itself. Staff see every result and
the answer key; university admins see their own university's results.
"""
import json
import random
import re
import time
import uuid

import _db_router as core

GRACE_SECONDS = 15  # network slack after the deadline for the last answer / submit
_rng = random.SystemRandom()


def ok(body, status=200):
    return {"status": status, "body": body}


def error(status, message):
    return {"status": status, "body": {"error": message}}


def is_staff(user):
    return core.is_admin(user)


def assigned_to(assessment, user):
    if assessment.get("status") != "published" or user.get("role") != "student":
        return False
    audience = assessment.get("audience", "all_students")
    return audience == "all_students" or user.get("university_id") in (assessment.get("university_ids") or [])


def total_marks(db, assessment):
    return db["AssessmentQuestion"].count_documents({"assessment_id": assessment["id"]}) * assessment.get("marks_per_question", 1)


def finalize(db, attempt, now=None):
    """Score an attempt server-side and mark it submitted (idempotent)"""
    if attempt.get("status") == "submitted":
        return attempt
    assessment = db["Assessment"].find_one({"id": attempt["assessment_id"]})
    per_q = assessment.get("marks_per_question", 1)
    negative = assessment.get("negative_marks", 0)
    answers = attempt.get("answers", {})
    correct = wrong = 0
    for q in db["AssessmentQuestion"].find({"assessment_id": assessment["id"]}, {"id": 1, "answer": 1}):
        chosen = answers.get(q["id"])
        if chosen is None:
            continue
        if chosen == q["answer"]:
            correct += 1
        else:
            wrong += 1
    now = now or time.time()
    result = {
        "status": "submitted",
        "submitted_at": min(now, attempt["deadline"] + GRACE_SECONDS),
        "auto_submitted": now > attempt["deadline"] + GRACE_SECONDS,
        "correct": correct,
        "wrong": wrong,
        "answered": correct + wrong,
        "score": max(0, correct * per_q - wrong * negative),
        "total_marks": total_marks(db, assessment),
    }
    # Only the first finalize wins if two requests race
    db["AssessmentAttempt"].update_one({"id": attempt["id"], "status": "in_progress"}, {"$set": result})
    return db["AssessmentAttempt"].find_one({"id": attempt["id"]})


def expire_if_overdue(db, attempt):
    if attempt and attempt.get("status") == "in_progress" and time.time() > attempt["deadline"] + GRACE_SECONDS:
        return finalize(db, attempt)
    return attempt


def result_view(assessment, attempt):
    view = {"status": attempt["status"], "submitted_at": attempt.get("submitted_at"), "auto_submitted": attempt.get("auto_submitted", False)}
    if assessment.get("show_score_to_students", True):
        view.update({k: attempt.get(k) for k in ("score", "total_marks", "correct", "answered")})
    return view


def summary(db, assessment):
    return {
        "id": assessment["id"], "title": assessment["title"], "description": assessment.get("description", ""),
        "duration_minutes": assessment["duration_minutes"], "marks_per_question": assessment.get("marks_per_question", 1),
        "negative_marks": assessment.get("negative_marks", 0), "required": assessment.get("required", False),
        "question_count": db["AssessmentQuestion"].count_documents({"assessment_id": assessment["id"]}),
        "total_marks": total_marks(db, assessment), "status": assessment.get("status"),
    }


# ---------------------------------------------------------------- students

def list_for_student(db, user):
    items = []
    for a in db["Assessment"].find({"status": "published"}).sort("created_at", 1):
        if not assigned_to(a, user):
            continue
        attempt = expire_if_overdue(db, db["AssessmentAttempt"].find_one({"assessment_id": a["id"], "user_id": user["id"]}))
        item = summary(db, a)
        if not attempt:
            item["attempt"] = {"status": "not_started"}
        elif attempt["status"] == "in_progress":
            item["attempt"] = {"status": "in_progress", "deadline": attempt["deadline"]}
        else:
            item["attempt"] = result_view(a, attempt)
        items.append(item)
    return ok({"assessments": items, "server_time": time.time()})


def paper(db, assessment, attempt):
    """Questions in this attempt's order, options in this attempt's order, without correct answers"""
    questions = {q["id"]: q for q in db["AssessmentQuestion"].find({"assessment_id": assessment["id"]})}
    out = []
    for number, qid in enumerate(attempt["question_order"], 1):
        q = questions[qid]
        perm = attempt["option_orders"][qid]
        out.append({"id": qid, "number": number, "section": q.get("section", ""), "text": q["text"],
                    "code": q.get("code", ""), "options": [q["options"][i] for i in perm]})
    shown = {}
    for qid, original in attempt.get("answers", {}).items():
        if original is not None:
            shown[qid] = attempt["option_orders"][qid].index(original)
    return ok({
        "attempt_id": attempt["id"], "assessment": summary(db, assessment), "deadline": attempt["deadline"],
        "server_time": time.time(), "questions": out, "answers": shown, "tab_switches": attempt.get("tab_switches", 0),
    })


def start(db, user, assessment_id):
    assessment = db["Assessment"].find_one({"id": assessment_id})
    if not assessment or not assigned_to(assessment, user):
        return error(404, "This test isn't available to you.")
    attempt = expire_if_overdue(db, db["AssessmentAttempt"].find_one({"assessment_id": assessment_id, "user_id": user["id"]}))
    if attempt and attempt["status"] == "submitted":
        return ok({"submitted": True, "result": result_view(assessment, attempt)})
    if not attempt:
        qids = [q["id"] for q in db["AssessmentQuestion"].find({"assessment_id": assessment_id}, {"id": 1, "options": 1})]
        if not qids:
            return error(400, "This test has no questions yet.")
        option_orders = {}
        for q in db["AssessmentQuestion"].find({"assessment_id": assessment_id}, {"id": 1, "options": 1}):
            perm = list(range(len(q["options"])))
            _rng.shuffle(perm)
            option_orders[q["id"]] = perm
        _rng.shuffle(qids)
        now = time.time()
        attempt = {
            "id": str(uuid.uuid4()), "assessment_id": assessment_id, "user_id": user["id"],
            "university_id": user.get("university_id"), "status": "in_progress",
            "started_at": now, "deadline": now + assessment["duration_minutes"] * 60,
            "question_order": qids, "option_orders": option_orders, "answers": {}, "tab_switches": 0,
        }
        try:
            db["AssessmentAttempt"].insert_one(attempt)
        except Exception:
            # Two tabs pressed Start together: the unique index lets only one attempt exist
            attempt = db["AssessmentAttempt"].find_one({"assessment_id": assessment_id, "user_id": user["id"]})
    return paper(db, assessment, attempt)


def own_attempt(db, user, attempt_id):
    attempt = db["AssessmentAttempt"].find_one({"id": attempt_id})
    if not attempt or attempt["user_id"] != user["id"]:
        return None, error(404, "Attempt not found")
    return attempt, None


def save_answer(db, user, attempt_id, body):
    attempt, problem = own_attempt(db, user, attempt_id)
    if problem:
        return problem
    try:
        data = json.loads(body) if body else {}
    except ValueError:
        data = {}
    if not isinstance(data, dict):
        return error(400, "Invalid answer")
    qid, shown = data.get("question_id"), data.get("option")
    if attempt["status"] != "in_progress" or time.time() > attempt["deadline"] + GRACE_SECONDS:
        expire_if_overdue(db, attempt)
        return error(409, "Time is up — your answers have been submitted.")
    if qid not in attempt["option_orders"]:
        return error(400, "Unknown question")
    perm = attempt["option_orders"][qid]
    if shown is None:
        original = None
    elif isinstance(shown, int) and 0 <= shown < len(perm):
        original = perm[shown]
    else:
        return error(400, "Unknown option")
    db["AssessmentAttempt"].update_one({"id": attempt_id, "status": "in_progress"}, {"$set": {f"answers.{qid}": original}})
    return ok({"saved": True})


def submit(db, user, attempt_id):
    attempt, problem = own_attempt(db, user, attempt_id)
    if problem:
        return problem
    attempt = finalize(db, attempt)
    assessment = db["Assessment"].find_one({"id": attempt["assessment_id"]})
    return ok({"result": result_view(assessment, attempt)})


def record_event(db, user, attempt_id, body):
    attempt, problem = own_attempt(db, user, attempt_id)
    if problem:
        return problem
    if attempt["status"] == "in_progress":
        db["AssessmentAttempt"].update_one({"id": attempt_id}, {"$inc": {"tab_switches": 1}, "$push": {"events": {"type": "tab_hidden", "at": time.time()}}})
    return ok({"tab_switches": attempt.get("tab_switches", 0) + 1})


# ---------------------------------------------------------------- staff and university admins

def list_for_managers(db, user):
    university_id = None if is_staff(user) else user.get("university_id")
    items = []
    for a in db["Assessment"].find({}).sort("created_at", 1):
        if not is_staff(user) and a.get("status") != "published":
            continue
        student_filter = {"role": "student"}
        if a.get("audience") == "all_students":
            if university_id:
                student_filter["university_id"] = university_id
        else:
            allowed = a.get("university_ids") or []
            student_filter["university_id"] = (university_id if university_id in allowed else "__none__") if university_id else {"$in": allowed}
        attempts = {"assessment_id": a["id"], **({"university_id": university_id} if university_id else {})}
        submitted = list(db["AssessmentAttempt"].find({**attempts, "status": "submitted"}, {"score": 1}))
        item = summary(db, a)
        item.update({
            "assigned": db["User"].count_documents(student_filter),
            "started": db["AssessmentAttempt"].count_documents(attempts),
            "submitted": len(submitted),
            "average_score": round(sum(x.get("score", 0) for x in submitted) / len(submitted), 1) if submitted else None,
        })
        items.append(item)
    return ok({"assessments": items})


def results(db, user, assessment_id, query_params):
    assessment = db["Assessment"].find_one({"id": assessment_id})
    if not assessment:
        return error(404, "Test not found")
    requested = (query_params or {}).get("university_id", [None])[0]
    if is_staff(user):
        university_id = requested or None
    else:
        university_id = user.get("university_id")
        if requested and requested != university_id:
            return error(403, "You can only see your own university's results")
    student_filter = {"role": "student", **({"university_id": university_id} if university_id else {})}
    names = {u["id"]: u["name"] for u in db["University"].find({}, {"id": 1, "name": 1})}
    attempts = {a["user_id"]: expire_if_overdue(db, a) for a in db["AssessmentAttempt"].find({"assessment_id": assessment_id})}
    rows = []
    for s in db["User"].find(student_filter):
        if assessment.get("audience") != "all_students" and s.get("university_id") not in (assessment.get("university_ids") or []):
            continue
        a = attempts.get(s["id"])
        rows.append({
            "id": s["id"], "full_name": s.get("full_name") or s.get("name") or "", "email": s.get("email", ""),
            "university_name": names.get(s.get("university_id"), ""), "department": s.get("department", ""), "batch": s.get("batch", ""),
            "status": a["status"] if a else "not_started",
            "score": a.get("score") if a else None, "correct": a.get("correct") if a else None, "answered": a.get("answered") if a else None,
            "started_at": a.get("started_at") if a else None, "submitted_at": a.get("submitted_at") if a else None,
            "auto_submitted": a.get("auto_submitted", False) if a else False, "tab_switches": a.get("tab_switches", 0) if a else 0,
        })
    rows.sort(key=lambda r: (r["status"] != "submitted", -(r["score"] or 0), r["full_name"].lower()))
    return ok({"assessment": summary(db, assessment), "results": rows})


def answer_key(db, user, assessment_id):
    if not is_staff(user):
        return error(403, "Only Zeptrax staff can see the answer key")
    assessment = db["Assessment"].find_one({"id": assessment_id})
    if not assessment:
        return error(404, "Test not found")
    questions = []
    for q in db["AssessmentQuestion"].find({"assessment_id": assessment_id}).sort("order", 1):
        questions.append({"number": q["order"], "section": q.get("section", ""), "text": q["text"], "code": q.get("code", ""),
                          "options": q["options"], "answer": q["answer"], "review": q.get("review", "")})
    return ok({"assessment": summary(db, assessment), "questions": questions})


# ---------------------------------------------------------------- router (paths below /api/portal)

def handle(db, method, path, query_params, body_data, user):
    if path == "/assessments" and method == "GET":
        if user.get("role") == "student":
            return list_for_student(db, user)
        if is_staff(user) or user.get("role") == "university_admin":
            return list_for_managers(db, user)
        return ok({"assessments": []})

    match = re.fullmatch(r"/assessments/([\w-]+)/(start|results|key)", path)
    if match:
        assessment_id, action = match.groups()
        if action == "start" and method == "POST":
            if user.get("role") != "student":
                return error(403, "Only students can take tests. Staff can review the questions in the answer key.")
            return start(db, user, assessment_id)
        if action == "results" and method == "GET" and (is_staff(user) or user.get("role") == "university_admin"):
            return results(db, user, assessment_id, query_params)
        if action == "key" and method == "GET":
            return answer_key(db, user, assessment_id)
        return error(403, "Not allowed")

    match = re.fullmatch(r"/attempts/([\w-]+)/(answer|submit|event)", path)
    if match:
        attempt_id, action = match.groups()
        if action == "answer" and method == "PUT":
            return save_answer(db, user, attempt_id, body_data)
        if action == "submit" and method == "POST":
            return submit(db, user, attempt_id)
        if action == "event" and method == "POST":
            return record_event(db, user, attempt_id, body_data)
    return None  # not an assessment route
