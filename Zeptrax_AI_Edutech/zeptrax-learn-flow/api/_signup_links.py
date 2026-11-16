"""
Shareable signup links (/api/portal/invite-links and /api/portal/join).

One link can be shared with a whole class (WhatsApp group, email, notice board). Each student opens it,
fills in their own details and gets an account. The link decides the university (or lets the student pick
one), optionally fixes the branch and batch, and names the test students are sent to after signing up.
Unlike the single-use invitations in _portal.py, the link itself is not secret, so it is stored as-is and
can be copied again later; admins control it with an expiry date, an optional signup limit and revoke.
"""
import re
import secrets
import time
import uuid

import _db_router as core
import _portal as portal

DAY = 24 * 60 * 60
MAX_LINK_USES = 100_000
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

def active_universities(db):
    return core.cached("active_universities", 60, lambda: [
        {"id": u["id"], "name": u["name"], "code": u["code"]}
        for u in db["University"].find({"status": {"$ne": "inactive"}}, {"id": 1, "name": 1, "code": 1}).sort("name", 1)
    ])


def find_link(db, code):
    if not isinstance(code, str) or not CODE.fullmatch(code.strip()):
        return None
    return db["InviteLink"].find_one({"code": code.strip()})


def link_problem(link, now=None):
    now = now or time.time()
    if not link or link.get("revoked"):
        return "This signup link is not valid. Ask your coordinator for the current link."
    if link["expires_at"] <= now:
        return "This signup link has expired. Ask your coordinator for a new one."
    if link.get("max_uses") and link.get("uses", 0) >= link["max_uses"]:
        return "This signup link has reached its limit. Ask your coordinator for a new one."
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
    problem = link_problem(link)
    if problem:
        return ok({"valid": False, "reason": problem})
    university = None
    if link.get("university_id"):
        uni = db["University"].find_one({"id": link["university_id"]}, {"id": 1, "name": 1, "code": 1, "status": 1})
        if not uni or uni.get("status") == "inactive":
            return ok({"valid": False, "reason": "This university is not active on the portal."})
        university = {"id": uni["id"], "name": uni["name"], "code": uni["code"]}
    return ok({
        "valid": True,
        "university": university,
        "universities": None if university else active_universities(db),
        "department": link.get("department", ""),
        "batch": link.get("batch", ""),
        "label": link.get("label", ""),
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
    problem = link_problem(link)
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

    university_id = link.get("university_id") or data.get("university_id")
    university = db["University"].find_one({"id": university_id}) if isinstance(university_id, str) else None
    if not university:
        return error(400, "Choose your university")
    if university.get("status") == "inactive":
        return error(400, "This university is not active on the portal.")
    program_slug, problem = portal.check_program(db, data.get("program_slug"), required=True)
    if problem:
        return error(400, problem)

    existing = db["User"].find_one({"email": email})
    if existing:
        # Same student pressing "Create account" twice (or retrying after a dropped connection): sign them in
        if existing.get("invite_link_id") == link["id"] and core.check_password(existing, password):
            return signed_up(db, existing, link)
        return error(409, "An account with this email already exists. Log in instead.")

    limit = university.get("max_students")
    if limit and db["User"].count_documents({"university_id": university["id"], "role": portal.STUDENT}) >= limit:
        return error(400, f"{university['name']} has reached its student limit on the portal. Contact your coordinator.")

    # A limited link is claimed atomically so it can't be used more often than allowed, even by
    # simultaneous signups. Unlimited links aren't written to, so a whole class can join at once.
    now = time.time()
    if link.get("max_uses"):
        claimed = db["InviteLink"].find_one_and_update(
            {"id": link["id"], "revoked": {"$ne": True}, "expires_at": {"$gt": now}, "uses": {"$lt": link["max_uses"]}},
            {"$inc": {"uses": 1}},
        )
        if not claimed:
            return error(400, "This signup link has reached its limit. Ask your coordinator for a new one.")

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
        "created_at": now,
    }
    try:
        db["User"].insert_one(user)
    except core.DuplicateKeyError:
        release(db, link)
        return error(409, "An account with this email already exists. Log in instead.")
    except Exception:
        release(db, link)
        raise
    return signed_up(db, user, link)


def release(db, link):
    if link.get("max_uses"):
        db["InviteLink"].update_one({"id": link["id"]}, {"$inc": {"uses": -1}})


def signed_up(db, user, link):
    me = portal.get_me(db, user)["body"]["user"]
    return ok({"access_token": user["token"], "user": me, "next_test_id": next_test(db, user, link.get("assessment_id"))})


# ---------------------------------------------------------------- staff and university admins

def new_code(university_code):
    return f"{university_code or 'ALL'}-{secrets.token_urlsafe(8)}"


def create(db, user, body):
    data = portal.parse_body(body)
    if data is None:
        return error(400, "Invalid request")
    requested = data.get("university_id") or None
    university_id, problem = portal.scope_university(db, user, requested)
    if problem:
        return problem
    university = None
    if university_id:
        university = db["University"].find_one({"id": university_id})
        if university.get("status") == "inactive":
            return error(400, "This university is inactive")
    elif not portal.is_staff(user):
        return error(403, "Choose a university")  # only staff may create links where students pick their university

    assessment_id = data.get("assessment_id") or None
    if assessment_id:
        assessment = db["Assessment"].find_one({"id": assessment_id}, {"id": 1, "status": 1})
        if not assessment or (not portal.is_staff(user) and assessment.get("status") != "published"):
            return error(400, "Choose a test from the list")

    max_uses = data.get("max_uses")
    if max_uses in (None, "", 0, "0"):
        max_uses = None
    else:
        try:
            max_uses = int(max_uses)
        except (TypeError, ValueError):
            return error(400, "Signup limit must be a number")
        if not 1 <= max_uses <= MAX_LINK_USES:
            return error(400, f"Signup limit must be between 1 and {MAX_LINK_USES}")
    expires_days = portal.parse_int(data.get("expires_days"), 30, 1, 365)

    now = time.time()
    link = {
        "id": str(uuid.uuid4()),
        "code": new_code(university and university["code"]),
        "university_id": university_id,
        "department": portal.clean(data.get("department"), 80),
        "batch": portal.clean(data.get("batch"), 40),
        "label": portal.clean(data.get("label"), 80),
        "assessment_id": assessment_id,
        "max_uses": max_uses,
        "uses": 0,
        "expires_at": now + expires_days * DAY,
        "revoked": False,
        "created_by": user.get("email"),
        "created_at": now,
    }
    db["InviteLink"].insert_one(link)
    return ok({"link": view(db, link, {}, {})}, 201)


def view(db, link, names, signups):
    test = test_summary(db, link.get("assessment_id"))
    now = time.time()
    status = "revoked" if link.get("revoked") else "expired" if link["expires_at"] <= now else \
        "full" if link.get("max_uses") and link.get("uses", 0) >= link["max_uses"] else "active"
    return {
        "id": link["id"], "code": link["code"], "label": link.get("label", ""),
        "university_id": link.get("university_id"),
        "university_name": names.get(link.get("university_id"), "") if link.get("university_id") else "Student chooses",
        "department": link.get("department", ""), "batch": link.get("batch", ""),
        "test": test, "max_uses": link.get("max_uses"), "signups": signups.get(link["id"], 0),
        "expires_at": link["expires_at"], "created_by": link.get("created_by"), "created_at": link["created_at"],
        "status": status,
    }


def list_links(db, user, query_params):
    university_id, problem = portal.scope_university(db, user, portal.query(query_params, "university_id"))
    if problem:
        return problem
    filt = {"university_id": university_id} if university_id else {}
    links = list(db["InviteLink"].find(filt).sort("created_at", -1).limit(200))
    names = {u["id"]: u["name"] for u in db["University"].find({}, {"id": 1, "name": 1})}
    signups = {}
    if links:
        for row in db["User"].aggregate([
            {"$match": {"invite_link_id": {"$in": [l["id"] for l in links]}}},
            {"$group": {"_id": "$invite_link_id", "n": {"$sum": 1}}},
        ]):
            signups[row["_id"]] = row["n"]
    return ok({"links": [view(db, l, names, signups) for l in links]})


def revoke(db, user, link_id):
    link = db["InviteLink"].find_one({"id": link_id})
    if not link:
        return error(404, "Signup link not found")
    if link.get("university_id"):
        _, problem = portal.scope_university(db, user, link["university_id"])
        if problem:
            return problem
    elif not portal.is_staff(user):
        return error(403, "Not allowed")
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
