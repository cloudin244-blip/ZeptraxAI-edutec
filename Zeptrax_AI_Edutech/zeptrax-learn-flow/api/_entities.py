"""
Generic entity API used by the main website: /api/apps/<app>/entities/<Entity>[/<id>].

Only the collections in RULES are reachable, each with explicit rules for who may read and change it.
Everything else (portal data, exams, camera evidence, signup links, rate limits, internal collections) is
refused here: it has its own API with its own checks. Students use the University Portal only, so they can
read public website content but can't change anything through this API.
"""
import json
import re
import time
import uuid

import _db_router as core

PUBLIC, AUTH, OWN, ADMIN, SUPER, NOBODY = "public", "auth", "own", "admin", "super", "nobody"

# read: who may list/get. create/update/delete: who may change. Non-admins may only change `fields`.
RULES = {
    "Course": {"read": PUBLIC, "create": SUPER, "update": SUPER, "delete": SUPER},
    "CourseModule": {"read": PUBLIC, "create": SUPER, "update": SUPER, "delete": SUPER},
    "Project": {"read": PUBLIC, "create": SUPER, "update": SUPER, "delete": SUPER},
    "TeamMember": {"read": PUBLIC, "create": ADMIN, "update": ADMIN, "delete": ADMIN},
    "Review": {"read": PUBLIC, "create": ADMIN, "update": ADMIN, "delete": ADMIN},
    "Document": {"read": PUBLIC, "create": ADMIN, "update": ADMIN, "delete": ADMIN},
    "BlogPost": {"read": PUBLIC, "create": AUTH, "update": AUTH, "delete": ADMIN, "fields": {"views"}},
    "CommunityPost": {"read": PUBLIC, "create": AUTH, "update": AUTH, "delete": ADMIN, "fields": {"likes_count", "liked_by", "comments"}},
    "LiveClassSlot": {"read": AUTH, "create": AUTH, "update": AUTH, "delete": ADMIN, "fields": {"booked_students", "booked_count", "status"}},
    "Enrollment": {"read": OWN, "create": AUTH, "update": OWN, "delete": OWN,
                   "fields": {"completed_modules", "progress_percent", "last_module_id", "status", "certificate_issued", "certificate_release_status"}},
    "Referral": {"read": OWN, "create": ADMIN, "update": ADMIN, "delete": ADMIN},
    "Certificate": {"read": "by_code", "create": ADMIN, "update": ADMIN, "delete": ADMIN},
    "AuditLog": {"read": ADMIN, "create": PUBLIC, "update": NOBODY, "delete": ADMIN},
    "EmailLog": {"read": ADMIN, "create": ADMIN, "update": ADMIN, "delete": ADMIN},
    "AdminInvitation": {"read": ADMIN, "create": ADMIN, "update": ADMIN, "delete": ADMIN},
    "User": {"read": ADMIN, "create": NOBODY, "update": ADMIN, "delete": SUPER},
}

# Values a student may set on their own enrollment (they can't release their own certificate)
ENROLLMENT_VALUES = {"status": {"active", "completed"}, "certificate_issued": {False}, "certificate_release_status": {"pending"}}

USER_NEVER = {"_id", "id", "token", "password", "password_hash", "otp_hash", "otp_expires_at", "otp_attempts", "otp_sent_at"}
ROLES = {"user", "student", "university_admin", "admin", "super_admin"}
SORT = re.compile(r"-?[A-Za-z0-9_.]{1,64}")
MAX_LIST = 500
MAX_DOC_BYTES = 50_000
FORBIDDEN_OPERATORS = {"$where", "$function", "$accumulator", "$expr"}


def ok(body, status=200):
    return {"status": status, "body": body}


def error(status, message):
    return {"status": status, "body": {"error": message}}


def allowed(level, requester):
    if level == PUBLIC:
        return True
    if level in (AUTH, OWN):
        return bool(requester)
    if level == ADMIN:
        return core.is_admin(requester)
    if level == SUPER:
        return core.is_super_admin(requester)
    return False


def owner_filter(entity, requester):
    if entity == "Enrollment":
        return {"$or": [{"student_id": requester.get("id")}, {"student_email": requester.get("email")}]}
    if entity == "Referral":
        return {"referrer_id": requester.get("id")}
    return None


def owns(entity, doc, requester):
    if entity == "Enrollment":
        return doc.get("student_id") == requester.get("id") or (doc.get("student_email") and doc.get("student_email") == requester.get("email"))
    if entity == "Referral":
        return doc.get("referrer_id") == requester.get("id")
    return False


def plain_filter(value):
    """Non-admin filters: field equality on simple values only (no operators, no nested queries)"""
    if not isinstance(value, dict):
        return None
    for key, v in value.items():
        if not isinstance(key, str) or key.startswith("$") or not re.fullmatch(r"[A-Za-z0-9_.]{1,64}", key):
            return None
        if not (v is None or isinstance(v, (str, int, float, bool))):
            return None
    return value


def safe_admin_filter(value):
    """Admin filters may use operators, but nothing that runs code"""
    if isinstance(value, dict):
        return all(k not in FORBIDDEN_OPERATORS and safe_admin_filter(v) for k, v in value.items())
    if isinstance(value, list):
        return all(safe_admin_filter(v) for v in value)
    return True


def parse(body, default):
    if not body:
        return default
    if len(body) > MAX_DOC_BYTES * 20:
        return None
    try:
        return json.loads(body)
    except ValueError:
        return None


# ---------------------------------------------------------------- the signed-in user (/entities/User/me)

PROFILE_NEVER = USER_NEVER | set(core.PROTECTED_USER_FIELDS) | {"status", "created_at", "app_id", "phone",
                                                                "registration_number", "graduation_year", "degree"}


def me(db, method, body, requester):
    if not requester:
        return {"status": 401, "body": {"message": "Authentication required to view users",
                                        "detail": "You must be logged in to perform this operation."}}
    if method == "GET":
        return ok(core.public_user(requester))
    if method != "PUT":
        return error(405, "Not allowed")
    if requester.get("role") == "student":
        return error(403, "Update your details on your profile in the University Portal.")
    data = parse(body, {})
    if not isinstance(data, dict) or len(json.dumps(data)) > MAX_DOC_BYTES:
        return error(400, "Invalid profile data")
    updates = {k: v for k, v in data.items() if k not in PROFILE_NEVER and not k.startswith("$") and "." not in k}
    if updates:
        db["User"].update_one({"id": requester["id"]}, {"$set": updates})
        core.forget_user(requester.get("token"))
    return ok(core.public_user(core.serialize_doc(db["User"].find_one({"id": requester["id"]}))))


# ---------------------------------------------------------------- router

def handle(db, method, entity, item_id, query_params, body, headers):
    requester = core.get_authorized_user(headers)
    if entity == "User" and item_id == "me":
        return me(db, method, body, requester)
    rules = RULES.get(entity)
    if not rules:
        return error(404, "Not found")
    collection = db[entity]
    admin = core.is_admin(requester)
    student = bool(requester) and requester.get("role") == "student"

    if method == "GET":
        return read(collection, entity, rules, item_id, query_params, requester, admin)

    action = {"POST": "create", "PUT": "update", "PATCH": "update", "DELETE": "delete"}.get(method)
    if not action:
        return error(405, "Not allowed")
    if student:
        return error(403, "Students use the University Portal.")
    if not allowed(rules[action], requester):
        return error(401 if not requester else 403, "Authentication required" if not requester else "Not allowed")
    bulk = item_id in (None, "bulk", "update-many") and action != "create" or item_id == "bulk" or method == "PATCH"
    if bulk and not core.is_super_admin(requester):
        return error(403, "Only the super admin can change many records at once")

    if action == "create":
        return create(db, collection, entity, item_id, body, requester, admin, headers)
    if action == "update":
        return update(collection, entity, rules, item_id, method, body, requester, admin)
    return delete(collection, entity, rules, item_id, body, requester, admin)


def read(collection, entity, rules, item_id, query_params, requester, admin):
    level = rules["read"]
    if level == "by_code":
        if admin:
            level = ADMIN
        else:
            # Anyone may verify one certificate by its exact code
            filt = parse((query_params.get("q") or [""])[0], {})
            code = filt.get("certificate_code") if isinstance(filt, dict) else None
            if item_id or not isinstance(code, str) or not code.strip() or len(filt) != 1:
                return error(403, "Admin access required")
            return ok(core.serialize_doc(list(collection.find({"certificate_code": code.strip()}).limit(1))))
    if not admin and not allowed(level, requester):
        return error(401 if not requester else 403, "Authentication required" if not requester else "Admin access required")
    own = owner_filter(entity, requester) if level == OWN and not admin else None

    if item_id and item_id not in ("bulk", "update-many"):
        doc = collection.find_one({"id": item_id})
        if not doc or (own is not None and not owns(entity, doc, requester)):
            return error(404, f"Item {item_id} not found in {entity}")
        doc = core.serialize_doc(doc)
        return ok(core.public_user(doc) if entity == "User" else doc)

    raw = (query_params.get("q") or [None])[0]
    filt = parse(raw, {}) if raw else {}
    if admin:
        if not isinstance(filt, dict) or not safe_admin_filter(filt):
            return error(400, "Invalid filter")
    else:
        filt = plain_filter(filt)
        if filt is None:
            return error(400, "Invalid filter")
    if own is not None:
        filt = {"$and": [filt, own]} if filt else own

    cursor = collection.find(filt)
    sort = (query_params.get("sort") or ["-created_date"])[0]
    if SORT.fullmatch(sort or ""):
        cursor = cursor.sort(sort.lstrip("-"), -1 if sort.startswith("-") else 1)
    try:
        limit = int((query_params.get("limit") or [MAX_LIST])[0])
        skip = int((query_params.get("skip") or [0])[0])
    except ValueError:
        limit, skip = MAX_LIST, 0
    cursor = cursor.skip(max(0, skip)).limit(min(limit, MAX_LIST) if limit > 0 else MAX_LIST)
    results = core.serialize_doc(list(cursor))
    if entity == "User":
        results = [core.public_user(u) for u in results]
    return ok(results)


def clean_doc(doc):
    return {k: v for k, v in doc.items() if isinstance(k, str) and not k.startswith("$") and "." not in k and k != "_id"}


def create(db, collection, entity, item_id, body, requester, admin, headers):
    if entity == "AuditLog" and core.rate_limited(f"auditlog:{core.client_ip(headers)}", 300, 10 * 60):
        return core.too_many()
    data = parse(body, {})
    docs = data if item_id == "bulk" and isinstance(data, list) else [data]
    out = []
    for doc in docs:
        if not isinstance(doc, dict) or len(json.dumps(doc)) > MAX_DOC_BYTES:
            return error(400, "Invalid data")
        doc = clean_doc(doc)
        doc["id"] = doc.get("id") if admin and isinstance(doc.get("id"), str) else str(uuid.uuid4())
        doc.setdefault("created_date", time.time())
        if entity == "Enrollment" and not admin:
            # People can only enroll themselves
            doc.update({"student_id": requester["id"], "student_email": requester.get("email"),
                        "status": "active", "progress_percent": 0, "completed_modules": []})
            doc.pop("certificate_issued", None)
            doc.pop("certificate_release_status", None)
        if entity in ("BlogPost", "CommunityPost") and not admin:
            doc["author_id"] = requester["id"]
        if entity == "AuditLog":
            doc["expires_at"] = core.analytics_expiry()
        collection.insert_one(doc)
        out.append(core.serialize_doc(doc))
    return ok(out if item_id == "bulk" else out[0])


def update(collection, entity, rules, item_id, method, body, requester, admin):
    data = parse(body, {})
    if method == "PATCH":  # update-many (super admin)
        if entity == "User" or not isinstance(data, dict) or not isinstance(data.get("query"), dict) or not data["query"]:
            return error(400, "Give a non-empty query")
        values = clean_doc(data.get("data") or {})
        values.pop("id", None)
        collection.update_many(data["query"], {"$set": values})
        return ok({"ok": True})
    items = data if item_id == "bulk" and isinstance(data, list) else [dict(data, id=item_id)] if isinstance(data, dict) else None
    if items is None:
        return error(400, "Invalid data")
    updated = []
    for item in items:
        if not isinstance(item, dict) or not isinstance(item.get("id"), str):
            continue
        doc_id = item["id"]
        values = clean_doc(item)
        values.pop("id", None)
        if not admin:
            values = {k: v for k, v in values.items() if k in rules.get("fields", set())}
            if rules["update"] == OWN:
                existing = collection.find_one({"id": doc_id})
                if not existing or not owns(entity, existing, requester):
                    return error(403, "You can only change your own records")
            if entity == "Enrollment":
                for field, choices in ENROLLMENT_VALUES.items():
                    if field in values and values[field] not in choices:
                        values.pop(field)
        if entity == "User":
            for field in USER_NEVER:
                values.pop(field, None)
            if "role" in values and (not core.is_super_admin(requester) or values["role"] not in ROLES):
                return error(403, "Only the super admin can change roles")
            if "email" in values:
                return error(400, "Emails can't be changed here")
        if values:
            collection.update_one({"id": doc_id}, {"$set": values})
            if entity == "User":
                core.uncache("user:")
        doc = collection.find_one({"id": doc_id})
        if not doc and item_id != "bulk":
            return error(404, f"Item {doc_id} not found in {entity}")
        if doc:
            doc = core.serialize_doc(doc)
            updated.append(core.public_user(doc) if entity == "User" else doc)
    return ok(updated if item_id == "bulk" else updated[0])


def delete(collection, entity, rules, item_id, body, requester, admin):
    if item_id and item_id not in ("bulk", "update-many"):
        if rules["delete"] == OWN and not admin:
            existing = collection.find_one({"id": item_id})
            if not existing or not owns(entity, existing, requester):
                return error(403, "You can only remove your own records")
        collection.delete_one({"id": item_id})
        if entity == "User":
            core.uncache("user:")
        return ok({"ok": True})
    data = parse(body, None)  # delete many (super admin)
    if isinstance(data, list) and data:
        collection.delete_many({"id": {"$in": [i for i in data if isinstance(i, str)]}})
    elif isinstance(data, dict) and data and safe_admin_filter(data) and entity != "User":
        collection.delete_many(data)
    else:
        return error(400, "Say which records to delete")
    return ok({"ok": True})
