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
        "audience": assessment.get("audience", "all_students"), "university_ids": assessment.get("university_ids") or [],
        "show_score_to_students": assessment.get("show_score_to_students", True),
        "attempts": db["AssessmentAttempt"].count_documents({"assessment_id": assessment["id"]}),
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
        questions.append({"id": q["id"], "number": q["order"], "section": q.get("section", ""), "text": q["text"], "code": q.get("code", ""),
                          "options": q["options"], "answer": q["answer"], "review": q.get("review", "")})
    return ok({"assessment": summary(db, assessment), "questions": questions})


# ---------------------------------------------------------------- authoring (super admin)

def body_dict(body):
    try:
        data = json.loads(body) if body else {}
    except ValueError:
        return None
    return data if isinstance(data, dict) else None


def clean(value, limit):
    return str(value or "").strip()[:limit]


def number(value, low, high, label, allow_float=False):
    try:
        n = float(value) if allow_float else int(value)
    except (TypeError, ValueError):
        raise ValueError(f"{label} must be a number")
    if not low <= n <= high:
        raise ValueError(f"{label} must be between {low} and {high}")
    return n


def test_settings(db, data, creating):
    out = {}
    try:
        if "title" in data or creating:
            out["title"] = clean(data.get("title"), 150)
            if not out["title"]:
                raise ValueError("Title is required")
        if "description" in data:
            out["description"] = clean(data.get("description"), 1000)
        if "duration_minutes" in data or creating:
            out["duration_minutes"] = number(data.get("duration_minutes", 60), 1, 600, "Duration (minutes)")
        if "marks_per_question" in data or creating:
            out["marks_per_question"] = number(data.get("marks_per_question", 1), 0.5, 100, "Marks per question", True)
        if "negative_marks" in data or creating:
            out["negative_marks"] = number(data.get("negative_marks", 0), 0, 100, "Negative marks", True)
    except ValueError as e:
        return None, str(e)
    for flag in ("required", "show_score_to_students"):
        if flag in data:
            out[flag] = bool(data[flag])
    if "audience" in data:
        if data["audience"] not in ("all_students", "universities"):
            return None, "Audience must be all students or chosen universities"
        out["audience"] = data["audience"]
    if "university_ids" in data:
        ids = [u for u in (data.get("university_ids") or []) if isinstance(u, str)]
        known = {u["id"] for u in db["University"].find({"id": {"$in": ids}}, {"id": 1})}
        out["university_ids"] = [u for u in ids if u in known]
    if "status" in data:
        if data["status"] not in ("draft", "published"):
            return None, "Status must be draft or published"
        out["status"] = data["status"]
    return out, None


def create_test(db, user, body):
    data = body_dict(body)
    if data is None:
        return error(400, "Invalid data")
    values, problem = test_settings(db, data, creating=True)
    if problem:
        return error(400, problem)
    doc = {"id": str(uuid.uuid4()), "status": "draft", "required": False, "audience": "all_students", "university_ids": [],
           "show_score_to_students": True, "description": "", "created_by": user.get("email"), "created_at": time.time(), **values}
    doc["status"] = "draft"  # new tests start as drafts until they have questions
    db["Assessment"].insert_one(doc)
    return ok({"assessment": summary(db, doc)}, 201)


def update_test(db, user, assessment_id, body):
    assessment = db["Assessment"].find_one({"id": assessment_id})
    if not assessment:
        return error(404, "Test not found")
    data = body_dict(body)
    if data is None:
        return error(400, "Invalid data")
    values, problem = test_settings(db, data, creating=False)
    if problem:
        return error(400, problem)
    if values.get("status") == "published" and not db["AssessmentQuestion"].count_documents({"assessment_id": assessment_id}):
        return error(400, "Add at least one question before publishing")
    if values.get("audience") == "universities" and not values.get("university_ids", assessment.get("university_ids")):
        return error(400, "Choose at least one university")
    started = db["AssessmentAttempt"].count_documents({"assessment_id": assessment_id})
    if started and any(k in values for k in ("marks_per_question", "negative_marks")):
        return error(409, "Students have already taken this test, so its marking can't change.")
    db["Assessment"].update_one({"id": assessment_id}, {"$set": {**values, "updated_by": user.get("email"), "updated_date": time.time()}})
    return ok({"assessment": summary(db, db["Assessment"].find_one({"id": assessment_id}))})


def delete_test(db, assessment_id):
    if db["AssessmentAttempt"].count_documents({"assessment_id": assessment_id}):
        return error(409, "Students have taken this test, so it can't be deleted. Unpublish it instead.")
    if not db["Assessment"].delete_one({"id": assessment_id}).deleted_count:
        return error(404, "Test not found")
    db["AssessmentQuestion"].delete_many({"assessment_id": assessment_id})
    return ok({"deleted": True})


def question_values(data):
    options = data.get("options")
    if not isinstance(options, list):
        return None, "Options are required"
    options = [clean(o, 500) for o in options]
    if not 2 <= len(options) <= 6 or any(not o for o in options):
        return None, "Give between 2 and 6 options, none empty"
    if len(set(options)) != len(options):
        return None, "Options must all be different"
    answer = data.get("answer")
    if not isinstance(answer, int) or not 0 <= answer < len(options):
        return None, "Mark which option is correct"
    text = clean(data.get("text"), 2000)
    if not text:
        return None, "Question text is required"
    return {"text": text, "code": str(data.get("code") or "")[:4000].rstrip(), "section": clean(data.get("section"), 60),
            "options": options, "answer": answer, "review": clean(data.get("review"), 1000)}, None


def questions_locked(db, assessment_id):
    if db["AssessmentAttempt"].count_documents({"assessment_id": assessment_id}):
        return error(409, "Students have already started this test, so its questions are locked.")
    return None


def save_question(db, assessment_id, body, question_id=None):
    if not db["Assessment"].find_one({"id": assessment_id}):
        return error(404, "Test not found")
    locked = questions_locked(db, assessment_id)
    if locked:
        return locked
    data = body_dict(body)
    if data is None:
        return error(400, "Invalid data")
    values, problem = question_values(data)
    if problem:
        return error(400, problem)
    coll = db["AssessmentQuestion"]
    if question_id:
        if not coll.update_one({"id": question_id, "assessment_id": assessment_id}, {"$set": values}).matched_count:
            return error(404, "Question not found")
    else:
        last = list(coll.find({"assessment_id": assessment_id}, {"order": 1}).sort("order", -1).limit(1))
        question_id = str(uuid.uuid4())
        coll.insert_one({"id": question_id, "assessment_id": assessment_id, "order": (last[0]["order"] + 1) if last else 1, **values})
    return answer_key(db, {"role": "super_admin"}, assessment_id)


def delete_question(db, assessment_id, question_id):
    locked = questions_locked(db, assessment_id)
    if locked:
        return locked
    if not db["AssessmentQuestion"].delete_one({"id": question_id, "assessment_id": assessment_id}).deleted_count:
        return error(404, "Question not found")
    for i, q in enumerate(db["AssessmentQuestion"].find({"assessment_id": assessment_id}).sort("order", 1), 1):
        db["AssessmentQuestion"].update_one({"id": q["id"]}, {"$set": {"order": i}})
    assessment = db["Assessment"].find_one({"id": assessment_id})
    if assessment and assessment.get("status") == "published" and not db["AssessmentQuestion"].count_documents({"assessment_id": assessment_id}):
        db["Assessment"].update_one({"id": assessment_id}, {"$set": {"status": "draft"}})
    return answer_key(db, {"role": "super_admin"}, assessment_id)


def reorder_questions(db, assessment_id, body):
    locked = questions_locked(db, assessment_id)
    if locked:
        return locked
    ids = (body_dict(body) or {}).get("ids")
    current = [q["id"] for q in db["AssessmentQuestion"].find({"assessment_id": assessment_id}, {"id": 1})]
    if not isinstance(ids, list) or sorted(ids) != sorted(current):
        return error(400, "The question list changed. Reload and try again.")
    for i, qid in enumerate(ids, 1):
        db["AssessmentQuestion"].update_one({"id": qid}, {"$set": {"order": i}})
    return answer_key(db, {"role": "super_admin"}, assessment_id)


def authoring(db, method, path, body, user):
    """Super-admin routes: POST /assessments, PUT/DELETE /assessments/{id}, question CRUD and reorder"""
    if path == "/assessments" and method == "POST":
        return create_test(db, user, body)
    match = re.fullmatch(r"/assessments/([\w-]+)", path)
    if match and method == "PUT":
        return update_test(db, user, match.group(1), body)
    if match and method == "DELETE":
        return delete_test(db, match.group(1))
    match = re.fullmatch(r"/assessments/([\w-]+)/questions(?:/([\w-]+))?", path)
    if match:
        assessment_id, item = match.groups()
        if item is None and method == "POST":
            return save_question(db, assessment_id, body)
        if item == "reorder" and method == "POST":
            return reorder_questions(db, assessment_id, body)
        if item and method == "PUT":
            return save_question(db, assessment_id, body, item)
        if item and method == "DELETE":
            return delete_question(db, assessment_id, item)
    return None


# ---------------------------------------------------------------- router (paths below /api/portal)

def handle(db, method, path, query_params, body_data, user):
    if method != "GET" and (path == "/assessments" or re.fullmatch(r"/assessments/[\w-]+(/questions(/[\w-]+)?)?", path)):
        if not core.is_super_admin(user):
            return error(403, "Only the super admin can create or edit tests")
        routed = authoring(db, method, path, body_data, user)
        if routed is not None:
            return routed
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
