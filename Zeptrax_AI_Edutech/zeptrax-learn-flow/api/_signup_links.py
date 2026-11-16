"""
University signup links (/api/portal/invite-links and /api/portal/join).

Each link belongs to one university and is shared with its students (WhatsApp group, email, notice board).
Every student opens the same link, fills in their own details and gets an account in that university. How
many students can join is the university's student limit (set on the Universities page), not a number of
links: nothing is generated per student. A link can also fix the branch and batch and names the test
students are sent to after signing up. The link itself is not secret, so it is stored as-is and can be
copied again later; admins control it with an expiry date and can turn it off.
"""
import re
import secrets
import time
import uuid

import _db_router as core
import _portal as portal

DAY = 24 * 60 * 60
CODE = re.compile(r"[A-Za-z0-9_-]{6,40}")
PHONE = re.compile(r"\+?\d{10,15}")
YEAR = re.compile(r"20\d\d")

# Shown as suggestions on the signup form; students may type anything else
DEGREES = ["B.Tech", "B.E.", "M.Tech", "BCA", "MCA", "B.Sc", "M.Sc", "BBA", "MBA", "B.Com", "Diploma", "Other"]


def ok(body, status=200):
    return {"status": status, "body": body}


def error(status, message):
    return {"status": status, "body": {"error": message}}


# ---------------------------------------------------------------- helpers

def find_link(db, code):
    if not isinstance(code, str) or not CODE.fullmatch(code.strip()):
        return None
    return db["InviteLink"].find_one({"code": code.strip()})


def link_university(db, link):
    """(university document, problem message) for a link that students are using"""
    if not link or link.get("revoked"):
        return None, "This signup link is not valid. Ask your coordinator for the current link."
    if link["expires_at"] <= time.time():
        return None, "This signup link has expired. Ask your coordinator for a new one."
    university = db["University"].find_one({"id": link.get("university_id")}) if link.get("university_id") else None
    if not university or university.get("status") == "inactive":
        return None, "This university is not active on the portal."
    return university, None


def university_full(db, university):
    limit = university.get("max_students")
    if limit and db["User"].count_documents({"university_id": university["id"], "role": portal.STUDENT}) >= limit:
        return f"{university['name']} has reached its student limit on the portal. Contact your coordinator."
    return None


def test_summary(db, assessment_id):
    if not assessment_id:
        return None
    a = db["Assessment"].find_one({"id": assessment_id}, {"id": 1, "title": 1, "duration_minutes": 1, "status": 1})
    return {"id": a["id"], "title": a["title"], "duration_minutes": a.get("duration_minutes"), "status": a.get("status")} if a else None


def next_test(db, user, preferred_id):
    """The test a newly registered student is sent to: the link's test if it's assigned to them,
    otherwise their first required test, otherwise any test assigned to them."""
    import _assessments
    tests = [a for a in _assessments.published_assessments(db) if _assessments.assigned_to(a, user)]
    for a in tests:
        if a["id"] == preferred_id:
            return a["id"]
    for a in tests:
        if a.get("required"):
            return a["id"]
    return tests[0]["id"] if tests else None


# ---------------------------------------------------------------- public: students

def validate(db, body):
    data = portal.parse_body(body) or {}
    link = find_link(db, data.get("code"))
    university, problem = link_university(db, link)
    problem = problem or university_full(db, university)
    if problem:
        return ok({"valid": False, "reason": problem})
    return ok({
        "valid": True,
        "university": {"id": university["id"], "name": university["name"], "code": university["code"]},
        "department": link.get("department", ""),
        "batch": link.get("batch", ""),
        "test": test_summary(db, link.get("assessment_id")),
        "degrees": DEGREES,
        "expires_at": link["expires_at"],
    })


def join(db, body, headers):
    data = portal.parse_body(body)
    if data is None:
        return error(400, "Invalid signup data")
    if core.rate_limited(f"join:{core.client_ip(headers)}", core.SIGNUPS_PER_IP, 10 * 60):
        return core.too_many()

    link = find_link(db, data.get("code"))
    university, problem = link_university(db, link)
    if problem:
        return error(400, problem)

    # ---- the student's details
    email = core.normalize_email(data.get("email"))
    password = data.get("password")
    full_name = portal.clean(data.get("full_name"), 120)
    phone = re.sub(r"[\s()-]", "", str(data.get("phone") or ""))
    degree = portal.clean(data.get("degree"), 60)
    department = link.get("department") or portal.clean(data.get("department"), 80)
    graduation_year = portal.clean(data.get("graduation_year"), 4)
    registration_number = portal.clean(data.get("registration_number"), 60)

    if not full_name:
        return error(400, "Enter your full name")
    if not re.fullmatch(r"[^@\s]+@[^@\s]+\.[^@\s]+", email):
        return error(400, "Enter a valid email address")
    if not PHONE.fullmatch(phone):
        return error(400, "Enter a valid phone number with 10 to 15 digits, e.g. +91 98765 43210")
    if not degree:
        return error(400, "Enter your degree, e.g. B.Tech")
    if not department:
        return error(400, "Enter your branch, e.g. Computer Science")
    if not YEAR.fullmatch(graduation_year):
        return error(400, "Graduation year must look like 2027")
    if not registration_number:
        return error(400, "Enter your university registration / roll number")
    if not isinstance(password, str) or len(password) < 8:
        return error(400, "Password must be at least 8 characters")
    program_slug, problem = portal.check_program(db, data.get("program_slug"), required=True)
    if problem:
        return error(400, problem)

    existing = db["User"].find_one({"email": email})
    if existing:
        # Same student pressing "Create account" twice (or retrying after a dropped connection): sign them in
        if existing.get("invite_link_id") == link["id"] and core.check_password(existing, password):
            return signed_up(db, existing, link)
        return error(409, "An account with this email already exists. Log in instead.")

    problem = university_full(db, university)
    if problem:
        return error(400, problem)

    user = {
        "id": str(uuid.uuid4()),
        "email": email,
        "password_hash": core.hash_password(password),
        "full_name": full_name,
        "name": full_name,
        "phone": phone,
        "role": portal.STUDENT,
        "university_id": university["id"],
        "degree": degree,
        "department": department,
        "batch": link.get("batch", ""),
        "graduation_year": graduation_year,
        "registration_number": registration_number,
        "program_slug": program_slug,
        "invite_link_id": link["id"],
        "token": uuid.uuid4().hex,
        "verified": True,
        "status": "active",
        "created_at": time.time(),
    }
    try:
        db["User"].insert_one(user)
    except core.DuplicateKeyError:
        return error(409, "An account with this email already exists. Log in instead.")
    return signed_up(db, user, link)


def signed_up(db, user, link):
    me = portal.get_me(db, user)["body"]["user"]
    return ok({"access_token": user["token"], "user": me, "next_test_id": next_test(db, user, link.get("assessment_id"))})


# ---------------------------------------------------------------- staff and university admins

def create(db, user, body):
    data = portal.parse_body(body)
    if data is None:
        return error(400, "Invalid request")
    university_id, problem = portal.scope_university(db, user, data.get("university_id") or None)
    if problem:
        return problem
    if not university_id:
        return error(400, "Choose a university")
    university = db["University"].find_one({"id": university_id})
    if university.get("status") == "inactive":
        return error(400, "This university is inactive")

    assessment_id = data.get("assessment_id") or None
    if assessment_id:
        assessment = db["Assessment"].find_one({"id": assessment_id}, {"id": 1, "status": 1})
        if not assessment or (not portal.is_staff(user) and assessment.get("status") != "published"):
            return error(400, "Choose a test from the list")

    now = time.time()
    link = {
        "id": str(uuid.uuid4()),
        "code": f"{university['code']}-{secrets.token_urlsafe(8)}",
        "university_id": university_id,
        "department": portal.clean(data.get("department"), 80),
        "batch": portal.clean(data.get("batch"), 40),
        "label": portal.clean(data.get("label"), 80),
        "assessment_id": assessment_id,
        "expires_at": now + portal.parse_int(data.get("expires_days"), 30, 1, 365) * DAY,
        "revoked": False,
        "created_by": user.get("email"),
        "created_at": now,
    }
    db["InviteLink"].insert_one(link)
    return ok({"link": view(db, link, {link["university_id"]: university}, {}, {})}, 201)


def view(db, link, universities, signups, enrolled):
    uni = universities.get(link.get("university_id")) or {}
    now = time.time()
    status = "revoked" if link.get("revoked") else "expired" if link["expires_at"] <= now else "active"
    return {
        "id": link["id"], "code": link["code"], "label": link.get("label", ""),
        "university_id": link.get("university_id"), "university_name": uni.get("name", ""),
        "university_students": enrolled.get(link.get("university_id"), 0), "university_limit": uni.get("max_students"),
        "department": link.get("department", ""), "batch": link.get("batch", ""),
        "test": test_summary(db, link.get("assessment_id")), "signups": signups.get(link["id"], 0),
        "expires_at": link["expires_at"], "created_by": link.get("created_by"), "created_at": link["created_at"],
        "status": status,
    }


def counts(db, match, field):
    return {row["_id"]: row["n"] for row in db["User"].aggregate([
        {"$match": match}, {"$group": {"_id": f"${field}", "n": {"$sum": 1}}}])}


def list_links(db, user, query_params):
    university_id, problem = portal.scope_university(db, user, portal.query(query_params, "university_id"))
    if problem:
        return problem
    filt = {"university_id": university_id} if university_id else {}
    links = list(db["InviteLink"].find(filt).sort("created_at", -1).limit(200))
    universities = {u["id"]: u for u in db["University"].find({}, {"id": 1, "name": 1, "max_students": 1})}
    signups, enrolled = {}, {}
    if links:
        signups = counts(db, {"invite_link_id": {"$in": [l["id"] for l in links]}}, "invite_link_id")
        enrolled = counts(db, {"role": portal.STUDENT, "university_id": {"$in": list({l["university_id"] for l in links})}}, "university_id")
    return ok({"links": [view(db, l, universities, signups, enrolled) for l in links]})


def revoke(db, user, link_id):
    link = db["InviteLink"].find_one({"id": link_id})
    if not link:
        return error(404, "Signup link not found")
    _, problem = portal.scope_university(db, user, link.get("university_id"))
    if problem:
        return problem
    db["InviteLink"].update_one({"id": link_id}, {"$set": {"revoked": True, "revoked_by": user.get("email"), "revoked_at": time.time()}})
    return ok({"revoked": True})


# ---------------------------------------------------------------- router (paths below /api/portal)

def handle_public(db, method, path, body_data, headers):
    if path == "/join/validate" and method == "POST":
        return validate(db, body_data)
    if path == "/join" and method == "POST":
        return join(db, body_data, headers)
    return None


def handle_managers(db, method, path, query_params, body_data, user):
    if path == "/invite-links" and method == "GET":
        return list_links(db, user, query_params)
    if path == "/invite-links" and method == "POST":
        return create(db, user, body_data)
    match = re.fullmatch(r"/invite-links/([\w-]+)/revoke", path)
    if match and method == "POST":
        return revoke(db, user, match.group(1))
    return None
