"""
Exam proctoring: what happens when the exam page reports unusual behaviour.

The browser reports what it sees (tab switches, leaving full screen, the camera seeing a phone or a second
person, ...). The decision is made here, on the server, so a student can't avoid it by editing the page:

- warning events are counted; at the test's warning limit the attempt is submitted and marked as malpractice;
- a phone or another person on camera submits the attempt immediately and marks it as malpractice;
- a camera snapshot sent with an event is kept as evidence (a few per attempt) for staff to review.

Camera-based detection can be wrong, so staff can review the evidence and clear a malpractice flag.
"""
import json
import re
import time

import _db_router as core

# Counted towards the warning limit
WARNINGS = {
    "tab_hidden": "left the test tab",
    "window_blur": "switched to another window or app",
    "fullscreen_exit": "left full screen",
    "no_person": "was not visible on camera",
    "camera_off": "turned the camera off",
}
# End the test straight away
FATAL = {
    "phone_detected": "A mobile phone was detected on camera",
    "multiple_people": "Another person was detected on camera",
}
# Recorded only
INFO = {"proctor_unavailable", "fullscreen_unavailable"}

DEFAULT_WARNING_LIMIT = 3
MAX_EVIDENCE = 6
SNAPSHOT = re.compile(r"data:image/jpeg;base64,[A-Za-z0-9+/=]{100,300000}")


def ok(body, status=200):
    return {"status": status, "body": body}


def error(status, message):
    return {"status": status, "body": {"error": message}}


def settings(assessment):
    return assessment.get("proctoring", True), int(assessment.get("warning_limit") or DEFAULT_WARNING_LIMIT)


def record_event(db, user, attempt_id, body):
    import _assessments as exams
    try:
        data = json.loads(body) if body else {}
    except ValueError:
        data = {}
    kind = data.get("type") if isinstance(data, dict) else None
    if kind not in WARNINGS and kind not in FATAL and kind not in INFO:
        return error(400, "Unknown event")

    attempt = db["AssessmentAttempt"].find_one({"id": attempt_id}, {"question_order": 0, "option_orders": 0, "answers": 0, "events": 0})
    if not attempt or attempt["user_id"] != user["id"]:
        return error(404, "Attempt not found")
    assessment = db["Assessment"].find_one({"id": attempt["assessment_id"]})
    if attempt["status"] != "in_progress" or time.time() > attempt["deadline"] + exams.GRACE_SECONDS:
        final = exams.expire_if_overdue(db, db["AssessmentAttempt"].find_one({"id": attempt_id}))
        return ok({"terminated": True, "result": exams.result_view(assessment, final)})

    now = time.time()
    update = {"$push": {"events": {"$each": [{"type": kind, "at": now}], "$slice": -200}}}
    inc = {}
    if kind in WARNINGS:
        inc["warnings"] = 1
    if kind in ("tab_hidden", "window_blur"):
        inc["tab_switches"] = 1
    if inc:
        update["$inc"] = inc
    after = db["AssessmentAttempt"].find_one_and_update(
        {"id": attempt_id, "status": "in_progress"}, update, return_document=True,
        projection={"warnings": 1, "tab_switches": 1})
    if not after:  # submitted in the meantime
        final = db["AssessmentAttempt"].find_one({"id": attempt_id})
        return ok({"terminated": True, "result": exams.result_view(assessment, final)})

    snapshot = data.get("snapshot")
    if isinstance(snapshot, str) and SNAPSHOT.fullmatch(snapshot) and kind not in INFO:
        if db["ProctorEvidence"].count_documents({"attempt_id": attempt_id}) < MAX_EVIDENCE:
            db["ProctorEvidence"].insert_one({"attempt_id": attempt_id, "user_id": user["id"], "type": kind,
                                              "at": now, "image": snapshot})

    proctoring, limit = settings(assessment)
    warnings = after.get("warnings", 0)
    reason = None
    if proctoring and kind in FATAL:
        reason = FATAL[kind]
    elif proctoring and kind in WARNINGS and warnings >= limit:
        reason = f"{warnings} proctoring warnings (last: the student {WARNINGS[kind]})"
    if reason:
        final = exams.finalize(db, db["AssessmentAttempt"].find_one({"id": attempt_id}), malpractice=reason)
        return ok({"terminated": True, "reason": reason, "result": exams.result_view(assessment, final)})
    return ok({"terminated": False, "warnings": warnings, "warning_limit": limit if proctoring else None,
               "tab_switches": after.get("tab_switches", 0)})


# ---------------------------------------------------------------- staff and university admins

def managed_attempt(db, user, attempt_id):
    attempt = db["AssessmentAttempt"].find_one({"id": attempt_id}, {"question_order": 0, "option_orders": 0, "answers": 0})
    if not attempt:
        return None, error(404, "Attempt not found")
    if not core.is_admin(user) and not (user.get("role") == "university_admin" and attempt.get("university_id") == user.get("university_id")):
        return None, error(403, "Not allowed")
    return attempt, None


def evidence(db, user, attempt_id):
    attempt, problem = managed_attempt(db, user, attempt_id)
    if problem:
        return problem
    student = db["User"].find_one({"id": attempt["user_id"]}, {"full_name": 1, "name": 1, "email": 1}) or {}
    snapshots = [{"type": e["type"], "at": e["at"], "image": e["image"]}
                 for e in db["ProctorEvidence"].find({"attempt_id": attempt_id}).sort("at", 1)]
    return ok({
        "student": {"name": student.get("full_name") or student.get("name") or "", "email": student.get("email", "")},
        "malpractice": attempt.get("malpractice", False), "malpractice_reason": attempt.get("malpractice_reason", ""),
        "malpractice_cleared": attempt.get("malpractice_cleared"),
        "warnings": attempt.get("warnings", 0), "tab_switches": attempt.get("tab_switches", 0),
        "events": attempt.get("events", []), "snapshots": snapshots,
    })


def clear(db, user, attempt_id, body):
    if not core.is_admin(user):
        return error(403, "Only Zeptrax staff can clear a malpractice flag")
    attempt, problem = managed_attempt(db, user, attempt_id)
    if problem:
        return problem
    if not attempt.get("malpractice"):
        return error(400, "This attempt isn't marked as malpractice")
    try:
        note = str((json.loads(body) if body else {}).get("note") or "")[:500]
    except (ValueError, AttributeError):
        note = ""
    db["AssessmentAttempt"].update_one({"id": attempt_id}, {"$set": {
        "malpractice": False,
        "malpractice_cleared": {"by": user.get("email"), "at": time.time(), "reason": attempt.get("malpractice_reason", ""), "note": note},
    }})
    return ok({"cleared": True})


def handle(db, method, path, body_data, user):
    match = re.fullmatch(r"/attempts/([\w-]+)/(event|evidence|clear-malpractice)", path)
    if not match:
        return None
    attempt_id, action = match.groups()
    if action == "event" and method == "POST":
        return record_event(db, user, attempt_id, body_data)
    if action == "evidence" and method == "GET":
        return evidence(db, user, attempt_id)
    if action == "clear-malpractice" and method == "POST":
        return clear(db, user, attempt_id, body_data)
    return error(405, "Not allowed")
