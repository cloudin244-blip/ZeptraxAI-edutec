"""
University portal API (/api/portal/...): universities, invitation tokens, invite-only registration,
student profiles and university-scoped student lists.

Roles: Zeptrax staff (admin / super_admin) manage everything; a university_admin only sees their own
university; a student only sees their own profile.
"""
import hashlib
import json
import re
import secrets
import time
import uuid

import _db_router as core

STUDENT = "student"
UNIVERSITY_ADMIN = "university_admin"
INVITE_ROLES = (STUDENT, UNIVERSITY_ADMIN)

PROFILE_FIELDS = {
    "full_name": 120,
    "phone": 30,
    "registration_number": 60,
    "graduation_year": 4,
    "skills": 500,
    "github": 200,
    "linkedin": 200,
}
MAX_BULK_INVITATIONS = 1000
DAY = 24 * 60 * 60


def ok(body, status=200):
    return {"status": status, "body": body}


def error(status, message):
    return {"status": status, "body": {"error": message}}


def parse_body(body_data):
    try:
        data = json.loads(body_data) if body_data else {}
    except Exception:
        return None
    return data if isinstance(data, dict) else None


def query(query_params, name):
    value = (query_params or {}).get(name)
    return value[0].strip() if value and isinstance(value[0], str) and value[0].strip() else None


def clean(value, limit):
    if value is None:
        return ""
    return re.sub(r"\s+", " ", str(value)).strip()[:limit]


def token_hash(token):
    return hashlib.sha256(token.encode("utf-8")).hexdigest()


def new_token(code):
    return f"ZP-{code}-{secrets.token_urlsafe(12)}"


def is_staff(user):
    return core.is_admin(user)


def profile_completion(user):
    return round(100 * sum(1 for f in PROFILE_FIELDS if user.get(f)) / len(PROFILE_FIELDS))


def university_summary(db, university_id):
    uni = db["University"].find_one({"id": university_id}) if university_id else None
    return {"id": uni["id"], "name": uni["name"], "code": uni["code"]} if uni else None


def scope_university(db, user, requested_id):
    """University the request may act on: staff choose (None = all), university admins get their own"""
    if is_staff(user):
        if requested_id and not db["University"].find_one({"id": requested_id}):
            return None, error(404, "University not found")
        return requested_id, None
    if user.get("role") == UNIVERSITY_ADMIN and user.get("university_id"):
        if requested_id and requested_id != user["university_id"]:
            return None, error(403, "You can only manage your own university")
        return user["university_id"], None
    return None, error(403, "Not allowed")


def pending_filter(now):
    return {"used_at": None, "revoked": {"$ne": True}, "expires_at": {"$gt": now}}


# ---------------------------------------------------------------- me / profile

def get_me(db, user):
    me = core.public_user(core.serialize_doc(user))
    me.pop("_id", None)
    me["university"] = university_summary(db, user.get("university_id"))
    me["profile_completion"] = profile_completion(user)
    me["portal_role"] = "staff" if is_staff(user) else user.get("role") or "user"
    return ok({"user": me})


def update_profile(db, user, body):
    data = parse_body(body)
    if data is None:
        return error(400, "Invalid profile data")
    updates = {}
    for field, limit in PROFILE_FIELDS.items():
        if field in data:
            updates[field] = clean(data[field], limit)
    year = updates.get("graduation_year")
    if year and not re.fullmatch(r"20\d\d", year):
        return error(400, "Graduation year must look like 2027")
    for field in ("github", "linkedin"):
        if updates.get(field) and not updates[field].startswith(("https://", "http://")):
            return error(400, f"{field.title()} must be a full link starting with https://")
    if "full_name" in updates:
        if not updates["full_name"]:
            return error(400, "Full name is required")
        updates["name"] = updates["full_name"]
    if updates:
        updates["updated_date"] = time.time()
        db["User"].update_one({"id": user["id"]}, {"$set": updates})
    return get_me(db, db["User"].find_one({"id": user["id"]}))


# ---------------------------------------------------------------- invitations

def validate_invitation(db, body):
    data = parse_body(body) or {}
    token = data.get("token")
    if not isinstance(token, str) or not token.strip():
        return ok({"valid": False, "reason": "Missing invitation code"})
    inv = db["Invitation"].find_one({"token_hash": token_hash(token.strip())})
    reason = invitation_problem(db, inv)
    if reason:
        return ok({"valid": False, "reason": reason})
    return ok({
        "valid": True,
        "role": inv["role"],
        "university": university_summary(db, inv["university_id"]),
        "department": inv.get("department", ""),
        "batch": inv.get("batch", ""),
        "expires_at": inv["expires_at"],
    })


def invitation_problem(db, inv):
    if not inv or inv.get("revoked"):
        return "This invitation link is not valid."
    if inv.get("used_at"):
        return "This invitation has already been used. Log in instead."
    if inv["expires_at"] <= time.time():
        return "This invitation has expired. Ask your university coordinator for a new one."
    uni = db["University"].find_one({"id": inv["university_id"]})
    if not uni or uni.get("status") == "inactive":
        return "This university is not active on the portal."
    return None


def register(db, body):
    data = parse_body(body)
    if data is None:
        return error(400, "Invalid registration data")
    token = data.get("token") if isinstance(data.get("token"), str) else ""
    email = core.normalize_email(data.get("email"))
    password = data.get("password")
    full_name = clean(data.get("full_name"), PROFILE_FIELDS["full_name"])
    if not re.fullmatch(r"[^@\s]+@[^@\s]+\.[^@\s]+", email):
        return error(400, "Enter a valid email address")
    if not isinstance(password, str) or len(password) < 8:
        return error(400, "Password must be at least 8 characters")
    if not full_name:
        return error(400, "Full name is required")

    hashed = token_hash(token.strip()) if token.strip() else ""
    inv = db["Invitation"].find_one({"token_hash": hashed}) if hashed else None
    problem = invitation_problem(db, inv)
    if problem:
        return error(400, problem)
    if db["User"].find_one({"email": email}):
        return error(409, "An account with this email already exists. Log in instead.")

    now = time.time()
    # Claim the invitation atomically so it can only be used once
    claimed = db["Invitation"].find_one_and_update(
        {"token_hash": hashed, **pending_filter(now)},
        {"$set": {"used_at": now, "used_by_email": email}},
    )
    if not claimed:
        return error(400, "This invitation has already been used. Log in instead.")

    # Role, university, department and batch come from the invitation, never from the request
    user = {
        "id": str(uuid.uuid4()),
        "email": email,
        "password_hash": core.hash_password(password),
        "full_name": full_name,
        "name": full_name,
        "role": claimed["role"],
        "university_id": claimed["university_id"],
        "department": claimed.get("department", ""),
        "batch": claimed.get("batch", ""),
        "invitation_id": claimed["id"],
        "token": uuid.uuid4().hex,
        "verified": True,
        "status": "active",
        "created_at": now,
    }
    try:
        db["User"].insert_one(user)
    except Exception:
        db["Invitation"].update_one({"id": claimed["id"]}, {"$set": {"used_at": None}, "$unset": {"used_by_email": ""}})
        return error(409, "An account with this email already exists. Log in instead.")
    db["Invitation"].update_one({"id": claimed["id"]}, {"$set": {"used_by": user["id"]}})
    me = get_me(db, user)["body"]["user"]
    return ok({"access_token": user["token"], "user": me})


def create_invitations(db, creator, university, role, count, expires_days, department="", batch=""):
    now = time.time()
    campaign = {
        "id": str(uuid.uuid4()),
        "university_id": university["id"],
        "role": role,
        "department": department,
        "batch": batch,
        "count": count,
        "expires_at": now + expires_days * DAY,
        "created_by": creator.get("email"),
        "created_at": now,
    }
    tokens, docs = [], []
    for _ in range(count):
        token = new_token(university["code"])
        tokens.append(token)
        docs.append({
            "id": str(uuid.uuid4()),
            "campaign_id": campaign["id"],
            "token_hash": token_hash(token),
            "university_id": university["id"],
            "role": role,
            "department": department,
            "batch": batch,
            "expires_at": campaign["expires_at"],
            "used_at": None,
            "created_at": now,
        })
    db["InvitationCampaign"].insert_one(campaign)
    db["Invitation"].insert_many(docs)
    campaign = core.serialize_doc(campaign)
    campaign.pop("_id", None)
    # Plain tokens are returned only here; the database keeps hashes
    return ok({"campaign": campaign, "tokens": tokens}, 201)


def parse_int(value, default, low, high):
    try:
        value = int(value)
    except (TypeError, ValueError):
        return default
    return max(low, min(high, value))


def bulk_student_invitations(db, user, body):
    data = parse_body(body)
    if data is None:
        return error(400, "Invalid request")
    university_id, problem = scope_university(db, user, data.get("university_id"))
    if problem:
        return problem
    if not university_id:
        return error(400, "Choose a university")
    university = db["University"].find_one({"id": university_id})
    if university.get("status") == "inactive":
        return error(400, "This university is inactive")
    try:
        count = int(data.get("count"))
    except (TypeError, ValueError):
        return error(400, "Number of students must be a number")
    if not 1 <= count <= MAX_BULK_INVITATIONS:
        return error(400, f"Number of students must be between 1 and {MAX_BULK_INVITATIONS}")
    expires_days = parse_int(data.get("expires_days"), 15, 1, 90)

    limit = university.get("max_students")
    if limit:
        now = time.time()
        registered = db["User"].count_documents({"university_id": university_id, "role": STUDENT})
        pending = db["Invitation"].count_documents({"university_id": university_id, "role": STUDENT, **pending_filter(now)})
        available = limit - registered - pending
        if count > available:
            return error(400, f"{university['name']} can onboard {limit} students: {registered} registered and {pending} invitations pending, so at most {max(available, 0)} more invitations can be created.")

    return create_invitations(db, user, university, STUDENT, count, expires_days,
                              clean(data.get("department"), 80), clean(data.get("batch"), 40))


def admin_invitation(db, user, body):
    if not is_staff(user):
        return error(403, "Only Zeptrax staff can invite university admins")
    data = parse_body(body)
    if data is None:
        return error(400, "Invalid request")
    university = db["University"].find_one({"id": data.get("university_id")})
    if not university:
        return error(404, "University not found")
    expires_days = parse_int(data.get("expires_days"), 7, 1, 30)
    return create_invitations(db, user, university, UNIVERSITY_ADMIN, 1, expires_days)


def list_campaigns(db, user, query_params):
    university_id, problem = scope_university(db, user, query(query_params, "university_id"))
    if problem:
        return problem
    filt = {"university_id": university_id} if university_id else {}
    if not is_staff(user):
        filt["role"] = STUDENT  # university admins don't see admin invitations
    now = time.time()
    names = {u["id"]: u["name"] for u in db["University"].find({}, {"id": 1, "name": 1})}
    campaigns = []
    for c in db["InvitationCampaign"].find(filt).sort("created_at", -1).limit(200):
        base = {"campaign_id": c["id"]}
        used = db["Invitation"].count_documents({**base, "used_at": {"$ne": None}})
        revoked = db["Invitation"].count_documents({**base, "used_at": None, "revoked": True})
        pending = db["Invitation"].count_documents({**base, **pending_filter(now)})
        campaigns.append({
            "id": c["id"], "university_id": c["university_id"], "university_name": names.get(c["university_id"], ""),
            "role": c["role"], "department": c.get("department", ""), "batch": c.get("batch", ""),
            "count": c["count"], "used": used, "pending": pending,
            "expired": c["count"] - used - pending - revoked, "revoked": revoked,
            "expires_at": c["expires_at"], "created_by": c.get("created_by"), "created_at": c["created_at"],
        })
    return ok({"campaigns": campaigns})


def revoke_campaign(db, user, campaign_id):
    campaign = db["InvitationCampaign"].find_one({"id": campaign_id})
    if not campaign:
        return error(404, "Invitation batch not found")
    _, problem = scope_university(db, user, campaign["university_id"])
    if problem:
        return problem
    if campaign["role"] != STUDENT and not is_staff(user):
        return error(403, "Not allowed")
    result = db["Invitation"].update_many({"campaign_id": campaign_id, "used_at": None}, {"$set": {"revoked": True}})
    return ok({"revoked": result.modified_count})


# ---------------------------------------------------------------- universities

def list_universities(db, user):
    if not is_staff(user):
        return error(403, "Only Zeptrax staff can manage universities")
    now = time.time()
    result = []
    for u in db["University"].find({}).sort("name", 1):
        result.append({
            "id": u["id"], "name": u["name"], "code": u["code"], "status": u.get("status", "active"),
            "max_students": u.get("max_students"), "created_at": u.get("created_at"),
            "students": db["User"].count_documents({"university_id": u["id"], "role": STUDENT}),
            "admins": db["User"].count_documents({"university_id": u["id"], "role": UNIVERSITY_ADMIN}),
            "pending_invitations": db["Invitation"].count_documents({"university_id": u["id"], "role": STUDENT, **pending_filter(now)}),
        })
    return ok({"universities": result})


def save_university(db, user, body, university_id=None):
    if not is_staff(user):
        return error(403, "Only Zeptrax staff can manage universities")
    data = parse_body(body)
    if data is None:
        return error(400, "Invalid request")
    updates = {}
    if "name" in data or not university_id:
        name = clean(data.get("name"), 120)
        if not name:
            return error(400, "University name is required")
        updates["name"] = name
    if "max_students" in data:
        raw = data.get("max_students")
        if raw in (None, "", 0, "0"):
            updates["max_students"] = None
        else:
            try:
                updates["max_students"] = int(raw)
            except (TypeError, ValueError):
                return error(400, "Student limit must be a number")
            if not 1 <= updates["max_students"] <= 100000:
                return error(400, "Student limit must be between 1 and 100000")
    if "status" in data:
        if data["status"] not in ("active", "inactive"):
            return error(400, "Status must be active or inactive")
        updates["status"] = data["status"]

    if university_id:
        if not db["University"].find_one({"id": university_id}):
            return error(404, "University not found")
        db["University"].update_one({"id": university_id}, {"$set": {**updates, "updated_date": time.time()}})
        uni = db["University"].find_one({"id": university_id})
    else:
        code = clean(data.get("code"), 8).upper()
        if not re.fullmatch(r"[A-Z0-9]{2,8}", code):
            return error(400, "Short code must be 2 to 8 letters or digits, e.g. MEW")
        if db["University"].find_one({"code": code}):
            return error(409, f"A university with code {code} already exists")
        uni = {"id": str(uuid.uuid4()), "code": code, "status": "active", "max_students": None,
               "created_by": user.get("email"), "created_at": time.time(), **updates}
        db["University"].insert_one(uni)
    uni = core.serialize_doc(uni)
    uni.pop("_id", None)
    return ok({"university": uni}, 200 if university_id else 201)


# ---------------------------------------------------------------- students & overview

def list_students(db, user, query_params):
    university_id, problem = scope_university(db, user, query(query_params, "university_id"))
    if problem:
        return problem
    filt = {"role": STUDENT}
    if university_id:
        filt["university_id"] = university_id
    for field in ("department", "batch"):
        value = query(query_params, field)
        if value:
            filt[field] = value
    names = {u["id"]: u["name"] for u in db["University"].find({}, {"id": 1, "name": 1})}
    students = []
    for s in db["User"].find(filt).sort("created_at", -1).limit(5000):
        students.append({
            "id": s["id"], "full_name": s.get("full_name") or s.get("name") or "", "email": s.get("email", ""),
            "university_id": s.get("university_id"), "university_name": names.get(s.get("university_id"), ""),
            "department": s.get("department", ""), "batch": s.get("batch", ""),
            "registration_number": s.get("registration_number", ""), "graduation_year": s.get("graduation_year", ""),
            "phone": s.get("phone", ""), "status": s.get("status", "active"),
            "profile_completion": profile_completion(s), "created_at": s.get("created_at"),
        })
    return ok({"students": students})


def overview(db, user):
    now = time.time()
    if is_staff(user):
        return ok({
            "universities": db["University"].count_documents({}),
            "students": db["User"].count_documents({"role": STUDENT}),
            "university_admins": db["User"].count_documents({"role": UNIVERSITY_ADMIN}),
            "pending_invitations": db["Invitation"].count_documents({"role": STUDENT, **pending_filter(now)}),
        })
    if user.get("role") == UNIVERSITY_ADMIN:
        uid = user.get("university_id")
        uni = db["University"].find_one({"id": uid}) or {}
        return ok({
            "university": university_summary(db, uid),
            "max_students": uni.get("max_students"),
            "students": db["User"].count_documents({"university_id": uid, "role": STUDENT}),
            "pending_invitations": db["Invitation"].count_documents({"university_id": uid, "role": STUDENT, **pending_filter(now)}),
            "profiles_complete": db["User"].count_documents({"university_id": uid, "role": STUDENT, **{f: {"$nin": [None, ""]} for f in PROFILE_FIELDS}}),
        })
    return error(403, "Not allowed")


# ---------------------------------------------------------------- router

def handle(db, method, path, query_params, body_data, user):
    path = path.rstrip("/") or "/"

    # Public
    if path == "/invitations/validate" and method == "POST":
        return validate_invitation(db, body_data)
    if path == "/register" and method == "POST":
        return register(db, body_data)

    if not user:
        return error(401, "Please log in")

    if path == "/me" and method == "GET":
        return get_me(db, user)
    if path == "/me/profile" and method == "PUT":
        return update_profile(db, user, body_data)

    import _assessments
    routed = _assessments.handle(db, method, path, query_params, body_data, user)
    if routed is not None:
        return routed

    # Staff and university admins only below
    if not (is_staff(user) or user.get("role") == UNIVERSITY_ADMIN):
        return error(403, "Not allowed")

    if path == "/overview" and method == "GET":
        return overview(db, user)
    if path == "/universities" and method == "GET":
        return list_universities(db, user)
    if path == "/universities" and method == "POST":
        return save_university(db, user, body_data)
    match = re.fullmatch(r"/universities/([\w-]+)", path)
    if match and method == "PUT":
        return save_university(db, user, body_data, match.group(1))
    if path == "/admin-invitations" and method == "POST":
        return admin_invitation(db, user, body_data)
    if path == "/invitations/bulk" and method == "POST":
        return bulk_student_invitations(db, user, body_data)
    if path == "/campaigns" and method == "GET":
        return list_campaigns(db, user, query_params)
    match = re.fullmatch(r"/campaigns/([\w-]+)/revoke", path)
    if match and method == "POST":
        return revoke_campaign(db, user, match.group(1))
    if path == "/students" and method == "GET":
        return list_students(db, user, query_params)
    return error(404, "Not found")
