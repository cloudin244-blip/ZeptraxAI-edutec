"""
Final-year projects for the university portal, under /api/portal/projects and /api/portal/submissions.

The super admin creates projects (brief, requirements, marking rubric, due date) for all students, chosen
Masters programs or chosen universities. Students submit links (repository, demo, documents, video) and notes;
they can update their submission until the due date or until it is marked. Zeptrax staff mark submissions
against the rubric; university admins follow their own university's submissions.
"""
import json
import re
import time
import uuid

import _db_router as core

STUDENT = "student"
UNIVERSITY_ADMIN = "university_admin"
DEFAULT_RUBRIC = [
    {"criterion": "Problem understanding", "max_marks": 10},
    {"criterion": "Technical implementation", "max_marks": 25},
    {"criterion": "Code quality", "max_marks": 15},
    {"criterion": "Innovation", "max_marks": 10},
    {"criterion": "Architecture & design", "max_marks": 10},
    {"criterion": "Working demonstration", "max_marks": 15},
    {"criterion": "Documentation", "max_marks": 5},
    {"criterion": "Presentation & viva", "max_marks": 10},
]
LINK_FIELDS = ("repo_url", "demo_url", "docs_url", "video_url")


def ok(body, status=200):
    return {"status": status, "body": body}


def error(status, message):
    return {"status": status, "body": {"error": message}}


def body_dict(body):
    try:
        data = json.loads(body) if body else {}
    except ValueError:
        return None
    return data if isinstance(data, dict) else None


def clean(value, limit):
    return str(value or "").strip()[:limit]


def is_staff(user):
    return core.is_admin(user)


def assigned_to(project, user):
    if project.get("status") != "published" or user.get("role") != STUDENT:
        return False
    audience, targets = project.get("audience", "all_students"), project.get("targets") or []
    if audience == "programs":
        return user.get("program_slug") in targets
    if audience == "universities":
        return user.get("university_id") in targets
    return True


def student_filter(project, university_id=None):
    filt = {"role": STUDENT}
    audience, targets = project.get("audience", "all_students"), project.get("targets") or []
    if audience == "programs":
        filt["program_slug"] = {"$in": targets}
    elif audience == "universities":
        filt["university_id"] = {"$in": targets}
    if university_id:
        if audience == "universities" and university_id not in targets:
            filt["university_id"] = "__none__"
        else:
            filt["university_id"] = university_id
    return filt


def total(project):
    return sum(r["max_marks"] for r in project.get("rubric") or [])


def project_view(db, project):
    titles = {p["slug"]: p["title"] for p in db["CatalogProgram"].find({}, {"slug": 1, "title": 1})}
    unis = {u["id"]: u["name"] for u in db["University"].find({}, {"id": 1, "name": 1})}
    names = titles if project.get("audience") == "programs" else unis
    return {
        "id": project["id"], "title": project["title"], "category": project.get("category", ""),
        "description": project.get("description", ""), "requirements": project.get("requirements", ""),
        "rubric": project.get("rubric") or [], "total_marks": total(project), "due_date": project.get("due_date"),
        "audience": project.get("audience", "all_students"), "targets": project.get("targets") or [],
        "target_names": [names.get(t, t) for t in project.get("targets") or []],
        "status": project.get("status", "draft"), "created_at": project.get("created_at"),
    }


def submission_view(sub, include_feedback=True):
    if not sub:
        return None
    view = {k: sub.get(k, "") for k in LINK_FIELDS + ("notes",)}
    view.update({"id": sub["id"], "status": sub.get("status", "submitted"), "submitted_at": sub.get("submitted_at"),
                 "updated_at": sub.get("updated_at")})
    if include_feedback and sub.get("evaluation"):
        view["evaluation"] = sub["evaluation"]
    return view


def overdue(project):
    return bool(project.get("due_date")) and time.time() > project["due_date"]


# ---------------------------------------------------------------- listing

def list_projects(db, user):
    if user.get("role") == STUDENT:
        items = []
        for p in db["PortalProject"].find({"status": "published"}).sort("created_at", -1):
            if assigned_to(p, user):
                view = project_view(db, p)
                view["submission"] = submission_view(db["ProjectSubmission"].find_one({"project_id": p["id"], "user_id": user["id"]}))
                view["overdue"] = overdue(p)
                items.append(view)
        return ok({"projects": items})
    if not (is_staff(user) or user.get("role") == UNIVERSITY_ADMIN):
        return ok({"projects": []})
    university_id = None if is_staff(user) else user.get("university_id")
    items = []
    for p in db["PortalProject"].find({} if is_staff(user) else {"status": "published"}).sort("created_at", -1):
        view = project_view(db, p)
        subs = {"project_id": p["id"], **({"university_id": university_id} if university_id else {})}
        view.update({
            "assigned": db["User"].count_documents(student_filter(p, university_id)),
            "submitted": db["ProjectSubmission"].count_documents(subs),
            "evaluated": db["ProjectSubmission"].count_documents({**subs, "status": "evaluated"}),
        })
        items.append(view)
    return ok({"projects": items})


def get_project(db, user, project_id):
    project = db["PortalProject"].find_one({"id": project_id})
    if not project:
        return error(404, "Project not found")
    if user.get("role") == STUDENT:
        if not assigned_to(project, user):
            return error(404, "Project not found")
        view = project_view(db, project)
        view["submission"] = submission_view(db["ProjectSubmission"].find_one({"project_id": project_id, "user_id": user["id"]}))
        view["overdue"] = overdue(project)
        return ok({"project": view})
    if is_staff(user) or (user.get("role") == UNIVERSITY_ADMIN and project.get("status") == "published"):
        return ok({"project": project_view(db, project)})
    return error(403, "Not allowed")


def list_submissions(db, user, project_id):
    project = db["PortalProject"].find_one({"id": project_id})
    if not project:
        return error(404, "Project not found")
    if is_staff(user):
        university_id = None
    elif user.get("role") == UNIVERSITY_ADMIN and project.get("status") == "published":
        university_id = user.get("university_id")
    else:
        return error(403, "Not allowed")
    unis = {u["id"]: u["name"] for u in db["University"].find({}, {"id": 1, "name": 1})}
    titles = {p["slug"]: p["title"] for p in db["CatalogProgram"].find({}, {"slug": 1, "title": 1})}
    subs = {s["user_id"]: s for s in db["ProjectSubmission"].find({"project_id": project_id})}
    rows = []
    for st in db["User"].find(student_filter(project, university_id)):
        sub = subs.get(st["id"])
        rows.append({
            "student": {"id": st["id"], "full_name": st.get("full_name") or st.get("name") or "", "email": st.get("email", ""),
                        "university_name": unis.get(st.get("university_id"), ""), "department": st.get("department", ""),
                        "batch": st.get("batch", ""), "program_title": titles.get(st.get("program_slug"), "")},
            "submission": submission_view(sub),
        })
    rows.sort(key=lambda r: (r["submission"] is None, (r["submission"] or {}).get("status") == "evaluated", r["student"]["full_name"].lower()))
    return ok({"project": project_view(db, project), "rows": rows})


# ---------------------------------------------------------------- students submit

def submit(db, user, project_id, body):
    if user.get("role") != STUDENT:
        return error(403, "Only students submit projects")
    project = db["PortalProject"].find_one({"id": project_id})
    if not project or not assigned_to(project, user):
        return error(404, "Project not found")
    existing = db["ProjectSubmission"].find_one({"project_id": project_id, "user_id": user["id"]})
    if existing and existing.get("status") == "evaluated":
        return error(409, "Your project has been marked, so it can't be changed.")
    if overdue(project):
        return error(409, "The due date has passed, so submissions are closed.")
    data = body_dict(body)
    if data is None:
        return error(400, "Invalid data")
    values = {k: clean(data.get(k), 500) for k in LINK_FIELDS}
    values["notes"] = clean(data.get("notes"), 3000)
    if not values["repo_url"]:
        return error(400, "Add the link to your code repository (e.g. GitHub)")
    for k in LINK_FIELDS:
        if values[k] and not re.match(r"https?://[^\s]+\.[^\s]+", values[k]):
            return error(400, "Links must be full addresses starting with https://")
    now = time.time()
    if existing:
        db["ProjectSubmission"].update_one({"id": existing["id"]}, {"$set": {**values, "updated_at": now}})
        sub_id = existing["id"]
    else:
        sub_id = str(uuid.uuid4())
        db["ProjectSubmission"].insert_one({"id": sub_id, "project_id": project_id, "user_id": user["id"],
                                            "university_id": user.get("university_id"), "status": "submitted",
                                            "submitted_at": now, "updated_at": now, **values})
    return ok({"submission": submission_view(db["ProjectSubmission"].find_one({"id": sub_id}))})


# ---------------------------------------------------------------- staff: create, edit, mark

def project_values(db, data, creating):
    out = {}
    if "title" in data or creating:
        out["title"] = clean(data.get("title"), 150)
        if not out["title"]:
            return None, "Title is required"
    for field, limit in (("category", 80), ("description", 4000), ("requirements", 4000)):
        if field in data:
            out[field] = clean(data.get(field), limit)
    if "due_date" in data:
        due = data.get("due_date")
        if due in (None, ""):
            out["due_date"] = None
        else:
            try:
                out["due_date"] = float(due)
            except (TypeError, ValueError):
                return None, "Due date is not valid"
    if "rubric" in data or creating:
        rubric = data.get("rubric") if "rubric" in data else DEFAULT_RUBRIC
        if not isinstance(rubric, list) or not rubric:
            return None, "Add at least one marking criterion"
        cleaned = []
        for r in rubric:
            name = clean((r or {}).get("criterion"), 80)
            try:
                marks = int((r or {}).get("max_marks"))
            except (TypeError, ValueError):
                return None, "Each criterion needs a number of marks"
            if not name or not 1 <= marks <= 100:
                return None, "Each criterion needs a name and 1–100 marks"
            cleaned.append({"criterion": name, "max_marks": marks})
        if len({c["criterion"].lower() for c in cleaned}) != len(cleaned):
            return None, "Criterion names must be different"
        out["rubric"] = cleaned
    if "audience" in data or creating:
        audience = data.get("audience", "all_students")
        if audience not in ("all_students", "programs", "universities"):
            return None, "Choose who the project is for"
        targets = [t for t in (data.get("targets") or []) if isinstance(t, str)]
        if audience == "programs":
            known = {p["slug"] for p in db["CatalogProgram"].find({"slug": {"$in": targets}}, {"slug": 1})}
            targets = [t for t in targets if t in known]
        elif audience == "universities":
            known = {u["id"] for u in db["University"].find({"id": {"$in": targets}}, {"id": 1})}
            targets = [t for t in targets if t in known]
        else:
            targets = []
        if audience != "all_students" and not targets:
            return None, "Choose at least one " + ("program" if audience == "programs" else "university")
        out["audience"], out["targets"] = audience, targets
    if "status" in data:
        if data["status"] not in ("draft", "published"):
            return None, "Status must be draft or published"
        out["status"] = data["status"]
    return out, None


def create_project(db, user, body):
    data = body_dict(body)
    if data is None:
        return error(400, "Invalid data")
    values, problem = project_values(db, data, creating=True)
    if problem:
        return error(400, problem)
    doc = {"id": str(uuid.uuid4()), "status": "draft", "category": "", "description": "", "requirements": "", "due_date": None,
           "created_by": user.get("email"), "created_at": time.time(), **values}
    db["PortalProject"].insert_one(doc)
    return ok({"project": project_view(db, doc)}, 201)


def update_project(db, user, project_id, body):
    project = db["PortalProject"].find_one({"id": project_id})
    if not project:
        return error(404, "Project not found")
    data = body_dict(body)
    if data is None:
        return error(400, "Invalid data")
    values, problem = project_values(db, data, creating=False)
    if problem:
        return error(400, problem)
    if "rubric" in values and db["ProjectSubmission"].count_documents({"project_id": project_id, "status": "evaluated"}) and values["rubric"] != project.get("rubric"):
        return error(409, "Some submissions are already marked, so the rubric can't change.")
    db["PortalProject"].update_one({"id": project_id}, {"$set": {**values, "updated_by": user.get("email"), "updated_date": time.time()}})
    return ok({"project": project_view(db, db["PortalProject"].find_one({"id": project_id}))})


def delete_project(db, project_id):
    if db["ProjectSubmission"].count_documents({"project_id": project_id}):
        return error(409, "Students have submitted work for this project, so it can't be deleted. Unpublish it instead.")
    if not db["PortalProject"].delete_one({"id": project_id}).deleted_count:
        return error(404, "Project not found")
    return ok({"deleted": True})


def evaluate(db, user, submission_id, body):
    if not is_staff(user):
        return error(403, "Only Zeptrax staff can mark projects")
    sub = db["ProjectSubmission"].find_one({"id": submission_id})
    if not sub:
        return error(404, "Submission not found")
    project = db["PortalProject"].find_one({"id": sub["project_id"]})
    data = body_dict(body)
    if data is None:
        return error(400, "Invalid data")
    given = data.get("scores") or {}
    scores = {}
    for r in project.get("rubric") or []:
        try:
            mark = float(given.get(r["criterion"]))
        except (TypeError, ValueError):
            return error(400, f"Enter marks for “{r['criterion']}”")
        if not 0 <= mark <= r["max_marks"]:
            return error(400, f"“{r['criterion']}” must be between 0 and {r['max_marks']}")
        scores[r["criterion"]] = mark
    evaluation = {"scores": scores, "total": round(sum(scores.values()), 2), "out_of": total(project),
                  "feedback": clean(data.get("feedback"), 3000), "evaluated_by": user.get("email"), "evaluated_at": time.time()}
    db["ProjectSubmission"].update_one({"id": submission_id}, {"$set": {"status": "evaluated", "evaluation": evaluation}})
    return ok({"submission": submission_view(db["ProjectSubmission"].find_one({"id": submission_id}))})


def reopen(db, user, submission_id):
    """Staff: clear the mark so the student can update the submission again"""
    if not is_staff(user):
        return error(403, "Only Zeptrax staff can reopen submissions")
    if not db["ProjectSubmission"].update_one({"id": submission_id}, {"$set": {"status": "submitted"}, "$unset": {"evaluation": ""}}).matched_count:
        return error(404, "Submission not found")
    return ok({"reopened": True})


# ---------------------------------------------------------------- router (paths below /api/portal)

def handle(db, method, path, body, user):
    if path == "/projects":
        if method == "GET":
            return list_projects(db, user)
        if method == "POST":
            return create_project(db, user, body) if core.is_super_admin(user) else error(403, "Only the super admin can create projects")
    match = re.fullmatch(r"/projects/([\w-]+)(?:/(submission|submissions))?", path)
    if match:
        project_id, sub = match.groups()
        if sub is None and method == "GET":
            return get_project(db, user, project_id)
        if sub is None and method in ("PUT", "DELETE"):
            if not core.is_super_admin(user):
                return error(403, "Only the super admin can change projects")
            return update_project(db, user, project_id, body) if method == "PUT" else delete_project(db, project_id)
        if sub == "submission" and method == "PUT":
            return submit(db, user, project_id, body)
        if sub == "submissions" and method == "GET":
            return list_submissions(db, user, project_id)
    match = re.fullmatch(r"/submissions/([\w-]+)/(evaluation|reopen)", path)
    if match:
        submission_id, action = match.groups()
        if action == "evaluation" and method == "PUT":
            return evaluate(db, user, submission_id, body)
        if action == "reopen" and method == "POST":
            return reopen(db, user, submission_id)
    return None  # not a project route
