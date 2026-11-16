import os
import json
import re
import uuid
import time
import hmac
import hashlib
import secrets
import urllib.parse
import smtplib
import ssl
from email.message import EmailMessage

from pathlib import Path

def load_dotenv():
    start_dir = Path(__file__).resolve().parent
    # api/ -> zeptrax-learn-flow/ -> Zeptrax_AI_Edutech/ -> repo root (where .env lives locally)
    for path in [Path("."), start_dir, *list(start_dir.parents)[:3]]:
        env_file = path / ".env"
        if env_file.exists():
            try:
                with env_file.open("r", encoding="utf-8") as f:
                    for line in f:
                        line = line.strip()
                        if line and not line.startswith("#") and "=" in line:
                            k, v = line.split("=", 1)
                            os.environ[k.strip()] = v.strip().strip('"').strip("'")
                break
            except Exception as e:
                print(f"[db_router] Error loading .env from {env_file}: {e}")

load_dotenv()

try:
    from pymongo.errors import PyMongoError, DuplicateKeyError
except ImportError:  # pymongo missing: the API serves static fallbacks only
    class PyMongoError(Exception):
        pass

    class DuplicateKeyError(PyMongoError):
        pass

# Bump when INDEXES changes: each new server instance then builds the indexes once
INDEX_VERSION = 4

# (collection, keys, options). Lookups that run on every request or every exam answer must be indexed,
# otherwise each one scans the whole collection and the database falls over under exam-day load.
INDEXES = [
    ("User", "email", {"unique": True}),
    ("User", "token", {}),
    ("User", "id", {}),
    ("User", "university_id", {}),
    ("User", [("role", 1), ("university_id", 1), ("created_at", -1)], {}),
    ("User", "invite_link_id", {"sparse": True}),
    ("Student", "id", {"unique": True}),
    ("Course", "id", {"unique": True}),
    ("Enrollment", "id", {"unique": True}),
    ("Enrollment", "student_id", {}),
    ("Enrollment", "student_email", {}),
    ("Certificate", "certificate_code", {}),
    ("University", "id", {"unique": True}),
    ("University", "code", {"unique": True}),
    ("Invitation", "token_hash", {"unique": True}),
    ("Invitation", "campaign_id", {}),
    ("Invitation", [("university_id", 1), ("role", 1), ("used_at", 1), ("expires_at", 1)], {}),
    ("InvitationCampaign", "id", {}),
    ("InvitationCampaign", [("university_id", 1), ("created_at", -1)], {}),
    ("InviteLink", "id", {"unique": True}),
    ("InviteLink", "code", {"unique": True}),
    ("InviteLink", [("university_id", 1), ("created_at", -1)], {}),
    ("Assessment", "id", {}),
    ("Assessment", [("status", 1), ("created_at", 1)], {}),
    ("AssessmentQuestion", "assessment_id", {}),
    ("AssessmentQuestion", "id", {}),
    ("AssessmentAttempt", [("assessment_id", 1), ("user_id", 1)], {"unique": True}),
    ("AssessmentAttempt", "id", {}),
    ("ProctorEvidence", [("attempt_id", 1), ("at", 1)], {}),
    ("AssessmentAttempt", [("assessment_id", 1), ("university_id", 1), ("status", 1)], {}),
    ("CatalogProgram", "slug", {"unique": True}),  # same as scripts/seed_catalog.py
    ("CatalogProgram", [("visible", 1), ("order", 1)], {}),
    ("PortalProject", "id", {}),
    ("ProjectSubmission", [("project_id", 1), ("user_id", 1)], {"unique": True}),
    ("ProjectSubmission", "id", {}),
    # Short-lived documents removed by MongoDB itself once `expires_at` passes
    ("RateLimit", "expires_at", {"expireAfterSeconds": 0}),
    ("AuditLog", "expires_at", {"expireAfterSeconds": 0, "sparse": True}),
]


def ensure_indexes(database, force=False):
    """Create INDEXES once per INDEX_VERSION. A new server instance only pays one small read for this."""
    meta = database["_meta"]
    if not force:
        marker = meta.find_one({"_id": "indexes"})
        if marker and marker.get("version", 0) >= INDEX_VERSION:
            return
    failures = 0
    for collection, keys, options in INDEXES:
        try:
            database[collection].create_index(keys, **options)
        except Exception as idx_err:  # e.g. old duplicate data blocks a unique index; the rest still get built
            failures += 1
            print(f"[MongoDB] Index {collection}.{keys} not created: {idx_err}")
    if not failures:
        meta.update_one({"_id": "indexes"}, {"$set": {"version": INDEX_VERSION, "built_at": time.time()}}, upsert=True)
    print(f"[MongoDB] Indexes checked (version {INDEX_VERSION}, {failures} failed).")


def _connect():
    mongo_uri = os.environ.get("MONGODB_URI")
    if not mongo_uri:
        print("[MongoDB] Warning: MONGODB_URI env variable is not set. Using local mock fallbacks.")
        return None
    from pymongo import MongoClient
    try:
        import certifi
        tls_options = {"tlsCAFile": certifi.where()}
    except ImportError:
        tls_options = {}
    # Many short-lived serverless instances share one Atlas cluster: keep each instance's pool small so the
    # cluster's connection limit isn't exhausted, and fail fast (the client retries) instead of hanging.
    client = MongoClient(
        mongo_uri,
        maxPoolSize=int(os.environ.get("MONGO_MAX_POOL_SIZE") or 20),
        minPoolSize=0,
        maxIdleTimeMS=60_000,
        serverSelectionTimeoutMS=5_000,
        connectTimeoutMS=5_000,
        socketTimeoutMS=20_000,
        waitQueueTimeoutMS=8_000,
        retryWrites=True,
        retryReads=True,
        appname="zeptrax-edutech",
        **tls_options,
    )
    database = client[os.environ.get("MONGODB_DB") or "zeptrax_db"]
    try:
        ensure_indexes(database)
    except Exception as idx_err:
        print(f"[MongoDB] Index check skipped: {idx_err}")
    return database


# Global MongoDB connection, reused by every request this server instance handles
db = None
try:
    db = _connect()
except Exception as e:
    print(f"[MongoDB] Error initializing database: {e}")
    db = None


# ---------------------------------------------------------------- small in-process caches

_cache = {}


def cached(key, ttl, compute, keep=None):
    """Value of compute(), reused for `ttl` seconds within this server instance (only if keep(value))"""
    hit = _cache.get(key)
    now = time.monotonic()
    if hit and hit[0] > now:
        return hit[1]
    value = compute()
    if keep and not keep(value):
        return value
    if len(_cache) > 5000:
        _cache.clear()
    _cache[key] = (now + ttl, value)
    return value


def ok_response(response):
    return isinstance(response, dict) and response.get("status", 200) == 200


def uncache(prefix):
    for key in [k for k in _cache if k.startswith(prefix)]:
        _cache.pop(key, None)


# ---------------------------------------------------------------- rate limiting

def client_ip(headers):
    for name in ("x-real-ip", "x-forwarded-for", "x-vercel-forwarded-for"):
        for key, val in (headers or {}).items():
            if key.lower() == name and val:
                return val.split(",")[0].strip()
    return "unknown"


def rate_limited(key, limit, window_seconds):
    """True once `key` has been seen more than `limit` times in the current window.
    Counted in MongoDB so every server instance shares the count. Fails open if the database hiccups."""
    if db is None:
        return False
    from datetime import datetime, timezone
    bucket = int(time.time() // window_seconds)
    try:
        doc = db["RateLimit"].find_one_and_update(
            {"_id": f"{key}:{bucket}"},
            {"$inc": {"n": 1}, "$setOnInsert": {
                "expires_at": datetime.fromtimestamp((bucket + 1) * window_seconds + 60, tz=timezone.utc)}},
            upsert=True,
            return_document=True,
        )
        return bool(doc) and doc.get("n", 0) > limit
    except PyMongoError as e:
        print(f"[rate_limit] {e}")
        return False


def too_many(message="Too many attempts. Please wait a few minutes and try again."):
    return {"status": 429, "body": {"error": message}, "headers": {"Retry-After": "60"}}

def serialize_doc(doc):
    """Recursively serializes MongoDB documents (converts ObjectId to string)"""
    if doc is None:
        return None
    if isinstance(doc, list):
        return [serialize_doc(d) for d in doc]
    if isinstance(doc, dict):
        doc = dict(doc)
        if "_id" in doc:
            doc["_id"] = str(doc["_id"])
        return doc
    return doc

# Bootstrap only: this account is given the super_admin role in the database when it registers or logs in.
# Override with the SUPER_ADMIN_EMAIL environment variable.
SUPER_ADMIN_EMAIL = os.environ.get("SUPER_ADMIN_EMAIL", "cloudin244@gmail.com").strip().lower()

# Collections only admins may read through the generic entity endpoints
ADMIN_ONLY_READ = {"User", "AdminInvitation", "EmailLog", "AuditLog", "StudentProfile",
                   "University", "InvitationCampaign", "Invitation",
                   "Assessment", "AssessmentQuestion", "AssessmentAttempt",
                   "CatalogProgram", "CatalogFreeCourse", "PortalProject", "ProjectSubmission"}

# Collections only admins may change through the generic entity endpoints
ADMIN_ONLY_WRITE = {"User", "StudentProfile", "University", "InvitationCampaign", "Invitation",
                    "Assessment", "AssessmentQuestion", "AssessmentAttempt", "PortalProject", "ProjectSubmission",
                    "AdminInvitation", "Certificate", "Course", "CourseModule", "Document",
                    "EmailLog", "Project", "TeamMember", "Review"}

# Website content only the super admin may change (courses, their modules and the website catalog)
SUPER_ADMIN_ONLY_WRITE = {"Course", "CourseModule", "CatalogProgram", "CatalogFreeCourse", "Project"}

# Collections anyone (even logged out) may add to through the generic entity endpoints
ANONYMOUS_CREATE_OK = {"AuditLog"}

# User fields that only the backend sets
PROTECTED_USER_FIELDS = ("_id", "id", "email", "token", "role", "verified", "password", "password_hash",
                         "university_id", "department", "batch", "invitation_id",
                         "otp_hash", "otp_expires_at", "otp_attempts", "otp_sent_at",
                         "program_slug")  # set through the portal, which checks it against the catalog

PBKDF2_ITERATIONS = 200_000

# Without email settings no code can be sent, so verify-otp only signs in brand-new accounts within this window
OTP_WINDOW_SECONDS = 30 * 60

# Emailed verification codes (used once SMTP_HOST, SMTP_USER and SMTP_PASSWORD are set)
OTP_TTL_SECONDS = 10 * 60
OTP_MAX_ATTEMPTS = 5
OTP_RESEND_SECONDS = 60

# Abuse limits. Students on one campus often share a single public IP, so per-IP limits are generous.
LOGIN_ATTEMPTS_PER_EMAIL = int(os.environ.get("LOGIN_ATTEMPTS_PER_EMAIL") or 20)   # per 15 minutes
SIGNUPS_PER_IP = int(os.environ.get("SIGNUPS_PER_IP") or 600)                       # per 10 minutes

BUSY_MESSAGE = "The server is busy right now. Please try again in a few seconds."

# CDN caching for public responses that are the same for every visitor
PUBLIC_CACHE = {"Cache-Control": "public, max-age=60, s-maxage=120, stale-while-revalidate=600"}


def analytics_expiry():
    from datetime import datetime, timedelta, timezone
    return datetime.now(timezone.utc) + timedelta(days=30)


UNAVAILABLE = {"status": 503, "body": {"error": "Student records are temporarily unavailable. Please try again later."}}


def public_user(user):
    """User document without secrets (password, session token)"""
    if not user:
        return user
    user = dict(user)
    user.pop("password", None)
    user.pop("password_hash", None)
    user.pop("token", None)
    for field in ("otp_hash", "otp_expires_at", "otp_attempts", "otp_sent_at"):
        user.pop(field, None)
    return user


def is_admin(user):
    """Zeptrax staff: platform admins and the super admin"""
    return bool(user) and user.get("role") in ("admin", "super_admin")


def is_super_admin(user):
    return bool(user) and user.get("role") == "super_admin"


def normalize_email(email):
    return email.strip().lower() if isinstance(email, str) else ""


def hash_password(password):
    salt = secrets.token_hex(16)
    digest = hashlib.pbkdf2_hmac("sha256", password.encode("utf-8"), bytes.fromhex(salt), PBKDF2_ITERATIONS)
    return f"pbkdf2_sha256${PBKDF2_ITERATIONS}${salt}${digest.hex()}"


def check_password(user, password):
    """True if `password` matches; accepts legacy plain-text passwords so they can be upgraded"""
    if not isinstance(password, str) or not user:
        return False
    stored = user.get("password_hash")
    if stored:
        try:
            _, iterations, salt, expected = stored.split("$")
            digest = hashlib.pbkdf2_hmac("sha256", password.encode("utf-8"), bytes.fromhex(salt), int(iterations))
            return hmac.compare_digest(digest.hex(), expected)
        except Exception:
            return False
    legacy = user.get("password")
    return isinstance(legacy, str) and legacy != "" and hmac.compare_digest(legacy.encode(), password.encode())


def email_configured():
    return all(os.environ.get(k) for k in ("SMTP_HOST", "SMTP_USER", "SMTP_PASSWORD"))


def send_email(to, subject, text, html=None):
    """Send through any SMTP provider (Gmail app password, Resend, SES, ...) configured by environment variables"""
    host = os.environ["SMTP_HOST"]
    port = int(os.environ.get("SMTP_PORT") or 587)
    user = os.environ["SMTP_USER"]
    msg = EmailMessage()
    msg["From"] = os.environ.get("MAIL_FROM") or f"ZeptraAI Edutech <{user}>"
    msg["To"] = to
    msg["Subject"] = subject
    msg.set_content(text)
    if html:
        msg.add_alternative(html, subtype="html")
    try:
        import certifi
        context = ssl.create_default_context(cafile=certifi.where())
    except ImportError:
        context = ssl.create_default_context()
    if port == 465:
        server = smtplib.SMTP_SSL(host, port, context=context, timeout=15)
    else:
        server = smtplib.SMTP(host, port, timeout=15)
        server.starttls(context=context)
    with server:
        server.login(user, os.environ["SMTP_PASSWORD"])
        server.send_message(msg)


def otp_digest(user, code):
    return hashlib.sha256(f"{user['id']}:{code}".encode("utf-8")).hexdigest()


def issue_otp(user):
    """Email a fresh 6-digit code; only its hash is stored. Returns an error message or None."""
    code = f"{secrets.randbelow(10 ** 6):06d}"
    now = time.time()
    db["User"].update_one({"_id": user["_id"]}, {"$set": {
        "otp_hash": otp_digest(user, code), "otp_expires_at": now + OTP_TTL_SECONDS,
        "otp_attempts": 0, "otp_sent_at": now,
    }})
    minutes = OTP_TTL_SECONDS // 60
    text = (f"Your ZeptraAI verification code is {code}\n\n"
            f"It expires in {minutes} minutes. If you didn't create a ZeptraAI account, you can ignore this email.")
    html = (f'<div style="font-family:Arial,sans-serif;max-width:480px;margin:auto;padding:24px;color:#0f172a">'
            f'<h2 style="margin:0 0 8px">Verify your email</h2>'
            f'<p style="margin:0 0 16px;color:#475569">Enter this code on ZeptraAI Edutech to finish creating your account:</p>'
            f'<p style="font-size:32px;font-weight:bold;letter-spacing:8px;margin:0 0 16px">{code}</p>'
            f'<p style="margin:0;color:#64748b;font-size:13px">It expires in {minutes} minutes. '
            f"If you didn't create a ZeptraAI account, you can ignore this email.</p></div>")
    try:
        send_email(user["email"], f"{code} is your ZeptraAI verification code", text, html)
        return None
    except Exception as e:
        print(f"[email] sending verification code to {user['email']} failed: {e}")
        return "We couldn't send the verification email. Please try again in a minute."


def apply_bootstrap_role(user):
    """Give the configured super-admin account its role in the database"""
    if user and normalize_email(user.get("email")) == SUPER_ADMIN_EMAIL and user.get("role") != "super_admin":
        db["User"].update_one({"_id": user["_id"]}, {"$set": {"role": "super_admin"}})
        user["role"] = "super_admin"
    return user


def display_name(name):
    """Readable student name; an email-only name becomes its local part"""
    name = (name or "").strip()
    if "@" in name:
        name = re.sub(r"[._\-]+", " ", name.split("@", 1)[0]).strip().title()
    return name or "Student"


def clean_university(value):
    """University name with single spaces, or '' to clear it"""
    if not isinstance(value, str):
        return ""
    return re.sub(r"\s+", " ", value).strip()[:120]


def collect_students():
    """One entry per student from enrollments and released certificates; `key` matches StudentProfile ids"""
    course_titles = {c.get("id"): c.get("title") or c.get("name") for c in db["Course"].find({}, {"id": 1, "title": 1, "name": 1})}
    user_names = {u.get("id"): u.get("full_name") or u.get("name") for u in db["User"].find({}, {"id": 1, "full_name": 1, "name": 1})}
    universities = {p.get("id"): p.get("university") for p in db["StudentProfile"].find({}, {"id": 1, "university": 1})}

    students = {}
    email_keys = {}
    for e in db["Enrollment"].find({}, {"id": 1, "student_id": 1, "student_email": 1, "student_name": 1, "course_id": 1, "progress_percent": 1, "status": 1}):
        email = (e.get("student_email") or "").lower()
        key = e.get("student_id") or email or e.get("id")
        if email:
            email_keys[email] = key
        account_name = user_names.get(e.get("student_id"))
        if account_name in (None, "", "Student"):
            account_name = None
        student = students.setdefault(key, {"key": key, "name": display_name(account_name or e.get("student_name")), "email": e.get("student_email") or "", "courses": [], "certificates": []})
        student["courses"].append({
            "title": course_titles.get(e.get("course_id")) or "Course",
            "progress": max(0, min(100, int(e.get("progress_percent") or 0))),
            "status": e.get("status") or "active",
        })

    for c in db["Certificate"].find({}, {"student_id": 1, "student_email": 1, "student_name": 1, "course_title": 1, "release_status": 1}):
        if c.get("release_status") not in (None, "released"):
            continue
        email = (c.get("student_email") or "").lower()
        key = c.get("student_id") if c.get("student_id") in students else email_keys.get(email, email or c.get("student_name"))
        student = students.setdefault(key, {"key": key, "name": display_name(c.get("student_name")), "email": c.get("student_email") or "", "courses": [], "certificates": []})
        student["certificates"].append(c.get("course_title") or "Certificate")

    result = []
    for s in students.values():
        progress = [c["progress"] for c in s["courses"]]
        s["avg_progress"] = round(sum(progress) / len(progress)) if progress else 100
        s["university"] = universities.get(s["key"]) or ""
        result.append(s)
    result.sort(key=lambda s: (-len(s["certificates"]), -s["avg_progress"], s["name"].lower()))
    return result


def partner_universities():
    """Public: universities our students come from, with student counts. No student details."""
    if db is None:
        return UNAVAILABLE
    try:
        groups = {}
        counted = set()

        def add(name, key):
            if name and key not in counted:
                counted.add(key)
                group = groups.setdefault(name.lower(), {"name": name, "students": 0})
                group["students"] += 1

        for s in collect_students():
            add(s["university"], s["key"])
        # Students who joined through a university invitation on the portal
        active = {u["id"]: u["name"] for u in db["University"].find({"status": {"$ne": "inactive"}}, {"id": 1, "name": 1})}
        for u in db["User"].find({"role": "student", "university_id": {"$in": list(active)}}, {"id": 1, "university_id": 1}):
            add(active[u["university_id"]], u["id"])
        result = sorted(groups.values(), key=lambda g: (-g["students"], g["name"].lower()))
        return {"status": 200, "body": {"universities": result}}
    except Exception as e:
        print(f"[partner_universities] {e}")
        return {"status": 500, "body": {"error": "Could not load universities"}}


def admin_students(headers):
    """Admins only: full student list with email, progress, certificates and university"""
    if db is None:
        return UNAVAILABLE
    if not is_admin(get_authorized_user(headers)):
        return {"status": 403, "body": {"error": "Admin access required"}}
    try:
        return {"status": 200, "body": {"students": collect_students()}}
    except Exception as e:
        print(f"[admin_students] {e}")
        return {"status": 500, "body": {"error": "Could not load student records"}}


def set_student_university(headers, body_data):
    """Admins only: set or clear one student's university"""
    if db is None:
        return UNAVAILABLE
    admin = get_authorized_user(headers)
    if not is_admin(admin):
        return {"status": 403, "body": {"error": "Admin access required"}}
    try:
        data = json.loads(body_data) if body_data else {}
    except Exception:
        data = {}
    key = data.get("key") if isinstance(data, dict) else None
    if not isinstance(key, str) or not key.strip():
        return {"status": 400, "body": {"error": "Student key is required"}}
    university = clean_university(data.get("university"))
    if university:
        db["StudentProfile"].update_one(
            {"id": key},
            {"$set": {"id": key, "university": university, "updated_by": admin.get("email"), "updated_date": time.time()}},
            upsert=True,
        )
    else:
        db["StudentProfile"].delete_one({"id": key})
    return {"status": 200, "body": {"key": key, "university": university}}


def get_authorized_user(headers):
    """Helper to authenticate user using Authorization Bearer token from header"""
    if db is None:
        return None

    auth_header = None
    for key, val in headers.items():
        if key.lower() == "authorization":
            auth_header = val
            break

    if not auth_header or not auth_header.startswith("Bearer "):
        return None

    token = auth_header.split(" ", 1)[1].strip()
    if not token:
        return None
    # Every API call authenticates; during an exam that is one lookup per saved answer, so a signed-in
    # user is reused for a few seconds. forget_user() drops it after the user's own record changes.
    user = cached(f"user:{token}", USER_CACHE_SECONDS, lambda: _load_user(token))
    return dict(user) if user else None


USER_CACHE_SECONDS = 15


def _load_user(token):
    user = apply_bootstrap_role(db["User"].find_one({"token": token}))
    if user and user.get("status") == "inactive":
        return None
    return serialize_doc(user)


def forget_user(token):
    if token:
        _cache.pop(f"user:{token}", None)

def _handle_db_request(method, path, query_params, body_data, headers):
    """
    Core dynamic router that intercepts base44 entity CRUD and auth endpoints
    and handles them in MongoDB collections.
    """
    # Normalize path (remove leading /api if present)
    normalized = path
    if normalized.startswith("/api"):
        normalized = normalized[4:]

    # Partner page: public university list; full student list and university edits for admins only
    if normalized == "/partner/universities" and method == "GET":
        response = cached("partner_universities", 120, partner_universities, ok_response)
        return {**response, "headers": PUBLIC_CACHE} if response["status"] == 200 else response
    if normalized == "/admin/students" and method == "GET":
        return admin_students(headers)
    if normalized == "/admin/students/university" and method == "PUT":
        return set_student_university(headers, body_data)

    # Website catalog (programs and free courses), public read
    if path.rstrip("/") == "/api/catalog" and method == "GET":
        import _catalog
        response = cached("public_catalog", 30, lambda: _catalog.public_catalog(db), ok_response)
        return {**response, "headers": PUBLIC_CACHE} if response.get("status") == 200 else response

    # University portal: /api/portal/...
    if path.startswith("/api/portal/"):
        if db is None:
            return UNAVAILABLE
        import _portal
        return _portal.handle(db, method, normalized[len("/portal"):], query_params, body_data, get_authorized_user(headers), headers)

    if db is None:
        return None  # Database not initialized; fallback to static file mocks

    # --- 1. AUTHENTICATION ENDPOINTS ---

    # POST /apps/<appId>/auth/register
    match = re.match(r"^/apps/([^/]+)/auth/register$", normalized)
    if match and method == "POST":
        app_id = match.group(1)
        try:
            user_data = json.loads(body_data) if body_data else {}
            email = normalize_email(user_data.get("email"))
            if not email:
                return {"status": 400, "body": {"error": "Email is required"}}
            if rate_limited(f"register:{client_ip(headers)}", SIGNUPS_PER_IP, 10 * 60):
                return too_many()
            password = user_data.get("password")
            if not isinstance(password, str) or len(password) < 6:
                return {"status": 400, "body": {"error": "Password must be at least 6 characters"}}

            # Check if user already exists
            existing_user = db["User"].find_one({"email": email})
            if existing_user:
                return {"status": 400, "body": {"error": "User already exists"}}

            user_id = str(uuid.uuid4())
            token = uuid.uuid4().hex

            new_user = {
                "id": user_id,
                "email": email,
                "password_hash": hash_password(password),
                "name": user_data.get("name", "Student"),
                "role": "super_admin" if email == SUPER_ADMIN_EMAIL else "user",  # never trust a client-supplied role
                "token": token,
                "verified": False,
                "created_at": time.time(),
                "app_id": app_id
            }
            db["User"].insert_one(new_user)
            if email_configured():
                issue_otp(new_user)  # a failed send can be retried with "Resend code"
            user_response = public_user(serialize_doc(new_user))

            return {
                "status": 200,
                "body": {
                    "access_token": token,
                    "user": user_response
                }
            }
        except Exception as e:
            if isinstance(e, PyMongoError):
                raise
            return {"status": 500, "body": {"error": str(e)}}

    # POST /apps/<appId>/auth/login
    match = re.match(r"^/apps/([^/]+)/auth/login$", normalized)
    if match and method == "POST":
        try:
            login_data = json.loads(body_data) if body_data else {}
            email = normalize_email(login_data.get("email"))
            password = login_data.get("password")

            if email and rate_limited(f"login:{email}", LOGIN_ATTEMPTS_PER_EMAIL, 15 * 60):
                return too_many("Too many sign-in attempts for this email. Please wait 15 minutes and try again.")
            user = db["User"].find_one({"email": email}) if email else None
            if not user or not check_password(user, password) or user.get("status") == "inactive":
                return {"status": 401, "body": {"error": "Invalid email or password"}}
            if not user.get("password_hash"):
                # Upgrade a legacy plain-text password on first successful login
                db["User"].update_one({"_id": user["_id"]}, {"$set": {"password_hash": hash_password(password)}, "$unset": {"password": ""}})
            apply_bootstrap_role(user)

            # If user has no token, generate one
            token = user.get("token")
            if not token:
                token = uuid.uuid4().hex
                db["User"].update_one({"_id": user["_id"]}, {"$set": {"token": token}})
                user["token"] = token

            user_response = public_user(serialize_doc(user))


            return {
                "status": 200,
                "body": {
                    "access_token": token,
                    "user": user_response
                }
            }
        except Exception as e:
            if isinstance(e, PyMongoError):
                raise
            return {"status": 500, "body": {"error": str(e)}}

    # POST /apps/<appId>/auth/verify-otp
    match = re.match(r"^/apps/([^/]+)/auth/verify-otp$", normalized)
    if match and method == "POST":
        try:
            otp_data = json.loads(body_data) if body_data else {}
            email = normalize_email(otp_data.get("email"))
            user = db["User"].find_one({"email": email}) if email else None
            if not user:
                return {"status": 404, "body": {"error": "User not found"}}

            if user.get("verified") is not False:
                message = "This email is already verified. Please log in with your email and password."
                return {"status": 401, "body": {"error": message, "message": message}}
            if email_configured():
                code = re.sub(r"\s+", "", str(otp_data.get("otp_code") or ""))
                if not user.get("otp_hash") or time.time() > user.get("otp_expires_at", 0):
                    message = "This code has expired. Tap Resend code to get a new one."
                    return {"status": 400, "body": {"error": message, "message": message}}
                if user.get("otp_attempts", 0) >= OTP_MAX_ATTEMPTS:
                    message = "Too many wrong codes. Tap Resend code to get a new one."
                    return {"status": 429, "body": {"error": message, "message": message}}
                if not hmac.compare_digest(otp_digest(user, code), user["otp_hash"]):
                    db["User"].update_one({"_id": user["_id"]}, {"$inc": {"otp_attempts": 1}})
                    message = "That code isn't right. Check the latest email from ZeptraAI and try again."
                    return {"status": 400, "body": {"error": message, "message": message}}
            elif time.time() - user.get("created_at", 0) > OTP_WINDOW_SECONDS:
                # No email service: brand-new accounts only, so this can't be used to take over existing ones
                message = "Verification expired. Please log in with your email and password."
                return {"status": 401, "body": {"error": message, "message": message}}
            db["User"].update_one({"_id": user["_id"]}, {"$set": {"verified": True},
                                                         "$unset": {"otp_hash": "", "otp_expires_at": "", "otp_attempts": "", "otp_sent_at": ""}})

            token = user.get("token")
            if not token:
                token = uuid.uuid4().hex
                db["User"].update_one({"_id": user["_id"]}, {"$set": {"token": token}})
                user["token"] = token

            user_response = public_user(serialize_doc(user))


            return {
                "status": 200,
                "body": {
                    "access_token": token,
                    "user": user_response
                }
            }
        except Exception as e:
            if isinstance(e, PyMongoError):
                raise
            return {"status": 500, "body": {"error": str(e)}}

    # POST /apps/<appId>/auth/resend-otp
    match = re.match(r"^/apps/([^/]+)/auth/resend-otp$", normalized)
    if match and method == "POST":
        data = json.loads(body_data) if body_data else {}
        email = normalize_email(data.get("email") if isinstance(data, dict) else None)
        user = db["User"].find_one({"email": email}) if email else None
        if not email_configured():
            message = "Email verification isn't available yet. Enter any 6 digits within 30 minutes of signing up, or log in with your password."
            return {"status": 503, "body": {"error": message, "message": message}}
        # Same reply whether or not the account exists, so this can't be used to discover emails
        if user and user.get("verified") is False:
            wait = OTP_RESEND_SECONDS - (time.time() - user.get("otp_sent_at", 0))
            if wait > 0:
                message = f"Please wait {int(wait) + 1} seconds before asking for another code."
                return {"status": 429, "body": {"error": message, "message": message}}
            problem = issue_otp(user)
            if problem:
                return {"status": 502, "body": {"error": problem, "message": problem}}
        return {"status": 200, "body": {"ok": True}}

    # --- 2. LOG & ANALYTICS ENDPOINTS ---

    # POST /app-logs/<appId>/log-user-in-app/home
    match = re.match(r"^/app-logs/([^/]+)/log-user-in-app/home$", normalized)
    if match and method == "POST":
        try:
            log_data = json.loads(body_data) if body_data else {}
            if not isinstance(log_data, dict):
                log_data = {"events": log_data}
            log_data["timestamp"] = time.time()
            log_data["app_id"] = match.group(1)
            log_data["type"] = "home_visit"
            log_data["expires_at"] = analytics_expiry()
            db["AuditLog"].insert_one(log_data)
            return {"status": 200, "body": {"ok": True}}
        except Exception as e:
            if isinstance(e, PyMongoError):
                raise
            return {"status": 500, "body": {"error": str(e)}}

    # POST /apps/<appId>/analytics/track/batch
    match = re.match(r"^/apps/([^/]+)/analytics/track/batch$", normalized)
    if match and method == "POST":
        try:
            batch_data = json.loads(body_data) if body_data else {}
            if not isinstance(batch_data, dict):
                batch_data = {"events": batch_data}
            batch_data["timestamp"] = time.time()
            batch_data["app_id"] = match.group(1)
            batch_data["expires_at"] = analytics_expiry()
            db["AuditLog"].insert_one(batch_data)
            return {"status": 200, "body": {"ok": True}}
        except Exception as e:
            if isinstance(e, PyMongoError):
                raise
            return {"status": 500, "body": {"error": str(e)}}

    # --- 3. ENTITY ENDPOINTS ---

    # Regex pattern matching /apps/<appId>/entities/<entity> or /apps/<appId>/entities/<entity>/<itemId>
    match = re.match(r"^/apps/([^/]+)/entities/([^/]+)(?:/([^/]+))?$", normalized)
    if match:
        app_id = match.group(1)
        entity = match.group(2)
        item_id = match.group(3)

        collection = db[entity]

        # SPECIAL CASE: GET /entities/User/me
        if entity == "User" and item_id == "me":
            if method == "GET":
                user = get_authorized_user(headers)
                if not user:
                    return {
                        "status": 401,
                        "body": {
                            "message": "Authentication required to view users",
                            "detail": "You must be logged in to perform this operation."
                        }
                    }
                return {"status": 200, "body": public_user(user)}

            elif method == "PUT":
                user = get_authorized_user(headers)
                if not user:
                    return {"status": 401, "body": {"error": "Authentication required"}}
                try:
                    update_data = json.loads(body_data) if body_data else {}
                    # Avoid updating the immutable fields
                    if not isinstance(update_data, dict):
                        return {"status": 400, "body": {"error": "Invalid profile data"}}
                    for field in PROTECTED_USER_FIELDS:  # users must not promote themselves or change identity
                        update_data.pop(field, None)

                    db["User"].update_one({"id": user["id"]}, {"$set": update_data})
                    forget_user(user.get("token"))
                    updated_user = db["User"].find_one({"id": user["id"]})
                    return {"status": 200, "body": public_user(serialize_doc(updated_user))}
                except Exception as e:
                    if isinstance(e, PyMongoError):
                        raise
                    return {"status": 500, "body": {"error": str(e)}}

        # ACCESS CONTROL
        requester = get_authorized_user(headers)
        admin = is_admin(requester)
        if method != "GET" and entity in SUPER_ADMIN_ONLY_WRITE and not is_super_admin(requester):
            return {"status": 403, "body": {"error": "Only the super admin can change courses and the website catalog"}}
        if not admin:
            if method == "GET" and entity in ADMIN_ONLY_READ:
                return {"status": 403, "body": {"error": "Admin access required"}}
            if method != "GET" and entity in ADMIN_ONLY_WRITE:
                return {"status": 403, "body": {"error": "Admin access required"}}
            if method == "GET" and entity == "Enrollment" and not requester:
                return {"status": 401, "body": {"error": "Authentication required"}}
            # Bulk delete / update-many can wipe whole collections
            if (method == "DELETE" and (not item_id or item_id in ("bulk", "update-many"))) or method == "PATCH":
                return {"status": 403, "body": {"error": "Admin access required"}}
            if method == "PUT" and item_id in (None, "bulk", "update-many"):
                return {"status": 403, "body": {"error": "Admin access required"}}
            if method != "GET" and not requester and not (method == "POST" and entity in ANONYMOUS_CREATE_OK):
                return {"status": 401, "body": {"error": "Authentication required"}}
            if method in ("PUT", "DELETE") and entity == "Enrollment" and item_id and item_id not in ("bulk", "update-many"):
                existing = collection.find_one({"id": item_id})
                if existing and existing.get("student_id") != requester.get("id") and existing.get("student_email") != requester.get("email"):
                    return {"status": 403, "body": {"error": "You can only change your own enrollments"}}
        # Students only ever see their own enrollments
        own_enrollments = None
        if entity == "Enrollment" and not admin and requester:
            own_enrollments = {"$or": [{"student_id": requester.get("id")}, {"student_email": requester.get("email")}]}

        # GENERAL CRUD OPERATIONS FOR ENTITIES

        # A. GET requests (List / Filter / Retrieve)
        if method == "GET":
            # Retrieve single document by ID
            if item_id and item_id not in ("bulk", "update-many"):
                doc = collection.find_one({"id": item_id})
                if not doc:
                    doc = collection.find_one({"_id": item_id})  # Fallback to ObjectId string
                if not doc:
                    return {"status": 404, "body": {"error": f"Item {item_id} not found in {entity}"}}
                if own_enrollments and doc.get("student_id") != requester.get("id") and doc.get("student_email") != requester.get("email"):
                    return {"status": 404, "body": {"error": f"Item {item_id} not found in {entity}"}}
                doc = serialize_doc(doc)
                return {"status": 200, "body": public_user(doc) if entity == "User" else doc}

            # List or filter documents
            else:
                filter_dict = {}
                q_param = query_params.get("q")
                if q_param:
                    try:
                        filter_dict = json.loads(q_param[0])
                    except Exception as e:
                        print(f"Error parsing filter: {e}")

                # Anyone may verify a certificate by its code; full certificate lists are admin-only
                if entity == "Certificate" and not admin and not (isinstance(filter_dict, dict) and filter_dict.get("certificate_code")):
                    return {"status": 403, "body": {"error": "Admin access required"}}
                if own_enrollments:
                    filter_dict = {"$and": [filter_dict, own_enrollments]} if filter_dict else own_enrollments

                # Setup sorting
                sort_list = []
                sort_param = query_params.get("sort")
                if sort_param:
                    sort_field = sort_param[0]
                    direction = 1
                    if sort_field.startswith("-"):
                        direction = -1
                        sort_field = sort_field[1:]
                    sort_list.append((sort_field, direction))
                else:
                    sort_list.append(("created_date", -1)) # Default sort

                # Setup pagination
                limit_val = 0
                limit_param = query_params.get("limit")
                if limit_param:
                    try:
                        limit_val = int(limit_param[0])
                    except ValueError:
                        pass

                skip_val = 0
                skip_param = query_params.get("skip")
                if skip_param:
                    try:
                        skip_val = int(skip_param[0])
                    except ValueError:
                        pass

                cursor = collection.find(filter_dict)
                if sort_list:
                    # Ignore sorting if default field is missing in first query schema
                    try:
                        cursor = cursor.sort(sort_list)
                    except Exception:
                        pass
                if skip_val:
                    cursor = cursor.skip(skip_val)
                if limit_val:
                    cursor = cursor.limit(limit_val)

                results = serialize_doc(list(cursor))
                if entity == "User":
                    results = [public_user(u) for u in results]
                return {"status": 200, "body": results}

        # B. POST requests (Create / Bulk Create)
        elif method == "POST":
            # Bulk insertion
            if item_id == "bulk":
                try:
                    docs = json.loads(body_data) if body_data else []
                    if not isinstance(docs, list):
                        docs = [docs]
                    inserted_docs = []
                    for doc in docs:
                        if not isinstance(doc, dict):
                            continue
                        if "id" not in doc:
                            doc["id"] = str(uuid.uuid4())
                        if "created_date" not in doc:
                            doc["created_date"] = time.time()
                        collection.insert_one(doc)
                        inserted_docs.append(serialize_doc(doc))
                    return {"status": 200, "body": inserted_docs}
                except Exception as e:
                    if isinstance(e, PyMongoError):
                        raise
                    return {"status": 500, "body": {"error": str(e)}}

            # Single insertion
            else:
                try:
                    doc = json.loads(body_data) if body_data else {}
                    if "id" not in doc:
                        doc["id"] = str(uuid.uuid4())
                    if "created_date" not in doc:
                        doc["created_date"] = time.time()
                    collection.insert_one(doc)
                    return {"status": 200, "body": serialize_doc(doc)}
                except Exception as e:
                    if isinstance(e, PyMongoError):
                        raise
                    return {"status": 500, "body": {"error": str(e)}}

        # C. PUT requests (Update / Bulk Update)
        elif method == "PUT":
            # Bulk update
            if item_id == "bulk":
                try:
                    updates = json.loads(body_data) if body_data else []
                    updated_docs = []
                    for item in updates:
                        if not isinstance(item, dict) or "id" not in item:
                            continue
                        doc_id = item["id"]
                        item.pop("_id", None)
                        collection.update_one({"id": doc_id}, {"$set": item})
                        updated = collection.find_one({"id": doc_id})
                        if updated:
                            updated_docs.append(serialize_doc(updated))
                    return {"status": 200, "body": updated_docs}
                except Exception as e:
                    if isinstance(e, PyMongoError):
                        raise
                    return {"status": 500, "body": {"error": str(e)}}

            # Single update
            elif item_id:
                try:
                    update_data = json.loads(body_data) if body_data else {}
                    update_data.pop("_id", None)
                    update_data.pop("id", None)
                    collection.update_one({"id": item_id}, {"$set": update_data})
                    updated = collection.find_one({"id": item_id})
                    if not updated:
                        return {"status": 404, "body": {"error": f"Item {item_id} not found in {entity}"}}
                    return {"status": 200, "body": serialize_doc(updated)}
                except Exception as e:
                    if isinstance(e, PyMongoError):
                        raise
                    return {"status": 500, "body": {"error": str(e)}}

        # D. DELETE requests (Delete Single / Delete Many)
        elif method == "DELETE":
            # Delete single item
            if item_id and item_id not in ("bulk", "update-many"):
                res = collection.delete_one({"id": item_id})
                if res.deleted_count == 0:
                    collection.delete_one({"_id": item_id})
                return {"status": 200, "body": {"ok": True}}

            # Delete multiple matching filter (body data has ids or query filter)
            else:
                try:
                    delete_filter = {}
                    if body_data:
                        body_json = json.loads(body_data)
                        if isinstance(body_json, list):
                            delete_filter = {"id": {"$in": body_json}}
                        elif isinstance(body_json, dict):
                            delete_filter = body_json
                    collection.delete_many(delete_filter)
                    return {"status": 200, "body": {"ok": True}}
                except Exception as e:
                    if isinstance(e, PyMongoError):
                        raise
                    return {"status": 500, "body": {"error": str(e)}}

        # E. PATCH requests (Update Many)
        elif method == "PATCH":
            if item_id == "update-many":
                try:
                    patch_data = json.loads(body_data) if body_data else {}
                    filter_q = patch_data.get("query", {})
                    update_val = patch_data.get("data", {})
                    update_val.pop("_id", None)
                    update_val.pop("id", None)

                    collection.update_many(filter_q, {"$set": update_val})
                    return {"status": 200, "body": {"ok": True}}
                except Exception as e:
                    if isinstance(e, PyMongoError):
                        raise
                    return {"status": 500, "body": {"error": str(e)}}

    return None  # Path did not match any database endpoints


def handle_db_request(method, path, query_params, body_data, headers):
    try:
        response = _handle_db_request(method, path, query_params, body_data, headers)
    except PyMongoError as e:
        print(f"[db] {method} {path}: {e}")
        response = {"status": 503, "body": {"error": BUSY_MESSAGE}, "headers": {"Retry-After": "3"}}
    body = response.get("body") if response else None
    if response and response.get("status", 200) >= 400 and isinstance(body, dict) and body.get("error") and not body.get("message"):
        body["message"] = body["error"]  # the main site's SDK displays `message`
    return response
