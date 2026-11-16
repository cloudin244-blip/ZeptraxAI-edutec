"""
Project selections (/api/portal/project-sets): a list of projects from which each student picks exactly one.

The super admin creates a selection for all students, chosen programs or chosen universities, and adds projects to
it (one by one, or a whole project bank at once). A student sees the projects with their briefs and difficulty,
chooses one, and that choice is final. If the selection has a time limit (e.g. 6 hours), the student's deadline is
counted from the moment they choose; an optional closing date stops new choices and caps every deadline.
Submissions and marking then work exactly like other projects (_projects.py).
"""
import json
import re
import time
import uuid

import _db_router as core
import _projects as projects

STUDENT = "student"
UNIVERSITY_ADMIN = "university_admin"
DIFFICULTIES = ("Easy", "Medium", "Hard")
SUBMIT_GRACE_SECONDS = 120  # network slack for a submission sent right at the deadline


def ok(body, status=200):
    return {"status": status, "body": body}


def error(status, message):
    return {"status": status, "body": {"error": message}}


# ---------------------------------------------------------------- helpers used by _projects.py

def assigned(project_set, user):
    if not project_set or project_set.get("status") != "published" or user.get("role") != STUDENT:
        return False
    audience, targets = project_set.get("audience", "all_students"), project_set.get("targets") or []
    if audience == "programs":
        return user.get("program_slug") in targets
    if audience == "universities":
        return user.get("university_id") in targets
    return True


def get_set(db, set_id):
    return db["ProjectSet"].find_one({"id": set_id}) if set_id else None


def selection(db, set_id, user_id):
    return db["ProjectSelection"].find_one({"set_id": set_id, "user_id": user_id})


def closed(project_set):
    return bool(project_set.get("due_date")) and time.time() > project_set["due_date"]


def deadline_for(project_set, chosen_at):
    limits = []
    if project_set.get("time_limit_hours"):
        limits.append(chosen_at + float(project_set["time_limit_hours"]) * 3600)
    if project_set.get("due_date"):
        limits.append(project_set["due_date"])
    return min(limits) if limits else None


def past_deadline(chosen):
    return bool(chosen.get("deadline")) and time.time() > chosen["deadline"] + SUBMIT_GRACE_SECONDS


def visible_to_university(project_set, university_id):
    return project_set.get("audience") != "universities" or university_id in (project_set.get("targets") or [])


def option_view(p):
    return {"id": p["id"], "title": p["title"], "category": p.get("category", ""), "difficulty": p.get("difficulty", ""),
            "description": p.get("description", ""), "requirements": p.get("requirements", ""),
            "rubric": p.get("rubric") or [], "total_marks": projects.total(p)}


def set_view(project_set):
    return {"id": project_set["id"], "title": project_set["title"], "description": project_set.get("description", ""),
            "audience": project_set.get("audience", "all_students"), "targets": project_set.get("targets") or [],
            "time_limit_hours": project_set.get("time_limit_hours"), "due_date": project_set.get("due_date"),
            "status": project_set.get("status", "draft"), "created_at": project_set.get("created_at")}


def for_student(db, user):
    """Selections assigned to a student: the options if they haven't chosen, otherwise their chosen project"""
    out = []
    for s in db["ProjectSet"].find({"status": "published"}).sort("created_at", -1):
        if not assigned(s, user):
            continue
        view = set_view(s)
        view["closed"] = closed(s)
        chosen = selection(db, s["id"], user["id"])
        if chosen:
            view["chosen"] = {"project_id": chosen["project_id"], "chosen_at": chosen["chosen_at"], "deadline": chosen.get("deadline")}
        else:
            view["options"] = [option_view(p) for p in db["PortalProject"].find({"set_id": s["id"], "status": "published"}).sort("order", 1)]
        out.append(view)
    return out


# ---------------------------------------------------------------- students

def choose(db, user, set_id, body):
    if user.get("role") != STUDENT:
        return error(403, "Only students choose projects")
    project_set = get_set(db, set_id)
    if not assigned(project_set, user):
        return error(404, "Project selection not found")
    if closed(project_set):
        return error(409, "This project selection has closed.")
    data = projects.body_dict(body) or {}
    project = db["PortalProject"].find_one({"id": data.get("project_id"), "set_id": set_id, "status": "published"})
    if not project:
        return error(400, "Choose a project from the list")
    now = time.time()
    doc = {"id": str(uuid.uuid4()), "set_id": set_id, "user_id": user["id"], "university_id": user.get("university_id"),
           "project_id": project["id"], "chosen_at": now, "deadline": deadline_for(project_set, now)}
    try:
        db["ProjectSelection"].insert_one(doc)
    except core.DuplicateKeyError:
        return error(409, "You have already chosen your project.")
    return ok({"project_id": project["id"], "deadline": doc["deadline"]})


# ---------------------------------------------------------------- staff and university admins

def set_values(db, data, creating):
    out = {}
    if "title" in data or creating:
        out["title"] = projects.clean(data.get("title"), 150)
        if not out["title"]:
            return None, "Title is required"
    if "description" in data:
        out["description"] = projects.clean(data.get("description"), 3000)
    if "time_limit_hours" in data:
        raw = data.get("time_limit_hours")
        if raw in (None, "", 0, "0"):
            out["time_limit_hours"] = None
        else:
            try:
                out["time_limit_hours"] = float(raw)
            except (TypeError, ValueError):
                return None, "Time limit must be a number of hours"
            if not 0.5 <= out["time_limit_hours"] <= 24 * 60:
                return None, "Time limit must be between 0.5 hours and 60 days"
    if "due_date" in data:
        try:
            out["due_date"] = float(data["due_date"]) if data.get("due_date") not in (None, "") else None
        except (TypeError, ValueError):
            return None, "Closing date is not valid"
    # Audience and status: the same rules as single projects
    shared, problem = projects.project_values(db, {k: data[k] for k in ("audience", "targets", "status") if k in data}
                                             | ({"title": "x"} if creating else {}), creating=False)
    if problem:
        return None, problem
    if creating and "audience" not in data:
        return None, "Choose who the selection is for"
    out.update({k: shared[k] for k in ("audience", "targets", "status") if k in shared})
    return out, None


def manager_scope(user):
    """None for staff (everything), the admin's university id, or False when not allowed"""
    if projects.is_staff(user):
        return None
    if user.get("role") == UNIVERSITY_ADMIN and user.get("university_id"):
        return user["university_id"]
    return False


def counts_by(db, collection, match, field):
    return {r["_id"]: r["n"] for r in db[collection].aggregate([{"$match": match}, {"$group": {"_id": f"${field}", "n": {"$sum": 1}}}])}


def list_sets(db, user):
    scope = manager_scope(user)
    if scope is False:
        return error(403, "Not allowed")
    filt = {} if scope is None else {"status": "published"}
    out = []
    for s in db["ProjectSet"].find(filt).sort("created_at", -1):
        if scope and not visible_to_university(s, scope):
            continue
        uni = {"university_id": scope} if scope else {}
        view = set_view(s)
        view["projects"] = db["PortalProject"].count_documents({"set_id": s["id"]})
        view["chosen"] = db["ProjectSelection"].count_documents({"set_id": s["id"], **uni})
        out.append(view)
    return ok({"sets": out})


def get_set_detail(db, user, set_id):
    scope = manager_scope(user)
    project_set = get_set(db, set_id)
    if scope is False or not project_set or (scope and (project_set.get("status") != "published" or not visible_to_university(project_set, scope))):
        return error(404, "Project selection not found")
    uni = {"university_id": scope} if scope else {}
    chosen = counts_by(db, "ProjectSelection", {"set_id": set_id, **uni}, "project_id")
    ids = [p["id"] for p in db["PortalProject"].find({"set_id": set_id}, {"id": 1})]
    submitted = counts_by(db, "ProjectSubmission", {"project_id": {"$in": ids}, **uni}, "project_id")
    evaluated = counts_by(db, "ProjectSubmission", {"project_id": {"$in": ids}, "status": "evaluated", **uni}, "project_id")
    items = []
    for p in db["PortalProject"].find({"set_id": set_id}).sort("order", 1):
        items.append({**option_view(p), "status": p.get("status", "draft"), "chosen": chosen.get(p["id"], 0),
                      "submitted": submitted.get(p["id"], 0), "evaluated": evaluated.get(p["id"], 0)})
    view = set_view(project_set)
    if scope:
        view["targets"] = [t for t in view["targets"] if t == scope]
    return ok({"set": view, "projects": items, "total_chosen": sum(chosen.values())})


def create_set(db, user, body):
    data = projects.body_dict(body)
    if data is None:
        return error(400, "Invalid data")
    values, problem = set_values(db, data, creating=True)
    if problem:
        return error(400, problem)
    doc = {"id": str(uuid.uuid4()), "status": "draft", "description": "", "time_limit_hours": None, "due_date": None,
           "created_by": user.get("email"), "created_at": time.time(), **values}
    db["ProjectSet"].insert_one(doc)
    return ok({"set": set_view(doc)}, 201)


def update_set(db, user, set_id, body):
    if not get_set(db, set_id):
        return error(404, "Project selection not found")
    data = projects.body_dict(body)
    if data is None:
        return error(400, "Invalid data")
    values, problem = set_values(db, data, creating=False)
    if problem:
        return error(400, problem)
    if values.get("status") == "published" and not db["PortalProject"].count_documents({"set_id": set_id, "status": "published"}):
        return error(400, "Add at least one published project before publishing the selection")
    db["ProjectSet"].update_one({"id": set_id}, {"$set": {**values, "updated_by": user.get("email"), "updated_date": time.time()}})
    return ok({"set": set_view(get_set(db, set_id))})


def delete_set(db, set_id):
    if db["ProjectSelection"].count_documents({"set_id": set_id}):
        return error(409, "Students have already chosen projects from this selection, so it can't be deleted. Unpublish it instead.")
    if not db["ProjectSet"].delete_one({"id": set_id}).deleted_count:
        return error(404, "Project selection not found")
    db["PortalProject"].delete_many({"set_id": set_id})
    return ok({"deleted": True})


def add_projects(db, user, set_id, body):
    """Add many projects at once (e.g. a ready-made project bank). Titles already in the selection are skipped."""
    if not get_set(db, set_id):
        return error(404, "Project selection not found")
    data = projects.body_dict(body) or {}
    items = data.get("projects")
    if not isinstance(items, list) or not 1 <= len(items) <= 200:
        return error(400, "Send between 1 and 200 projects")
    existing = {p["title"].lower() for p in db["PortalProject"].find({"set_id": set_id}, {"title": 1})}
    order = db["PortalProject"].count_documents({"set_id": set_id})
    docs = []
    for item in items:
        if not isinstance(item, dict):
            return error(400, "Each project needs a title")
        values, problem = projects.project_values(db, {**item, "audience": "all_students", "status": "published"}, creating=True)
        if problem:
            return error(400, f"{item.get('title') or 'A project'}: {problem}")
        difficulty = item.get("difficulty") or ""
        if difficulty and difficulty not in DIFFICULTIES:
            return error(400, f"{values['title']}: difficulty must be Easy, Medium or Hard")
        if values["title"].lower() in existing:
            continue
        existing.add(values["title"].lower())
        order += 1
        docs.append({"id": str(uuid.uuid4()), "category": "", "description": "", "requirements": "", "due_date": None,
                     **values, "difficulty": difficulty, "set_id": set_id, "order": order,
                     "created_by": user.get("email"), "created_at": time.time()})
    if docs:
        db["PortalProject"].insert_many(docs)
    return ok({"added": len(docs), "skipped": len(items) - len(docs)}, 201)


def handle(db, method, path, body, user):
    if path == "/project-sets":
        if method == "GET":
            return list_sets(db, user)
        if method == "POST":
            return create_set(db, user, body) if core.is_super_admin(user) else error(403, "Only the super admin can create project selections")
    match = re.fullmatch(r"/project-sets/([\w-]+)(?:/(choose|projects))?", path)
    if not match:
        return None
    set_id, action = match.groups()
    if action == "choose" and method == "POST":
        return choose(db, user, set_id, body)
    if action is None and method == "GET":
        return get_set_detail(db, user, set_id)
    if not core.is_super_admin(user):
        return error(403, "Only the super admin can change project selections")
    if action is None and method == "PUT":
        return update_set(db, user, set_id, body)
    if action is None and method == "DELETE":
        return delete_set(db, set_id)
    if action == "projects" and method == "POST":
        return add_projects(db, user, set_id, body)
    return error(405, "Not allowed")
