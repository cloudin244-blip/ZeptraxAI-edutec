import os
import json
import re
import uuid
import time
import hmac
import hashlib
import secrets
import urllib.parse

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

# Global MongoDB Client & DB connection
db = None
try:
    # Read MongoDB URI from environment
    mongo_uri = os.environ.get("MONGODB_URI")
    if mongo_uri:
        from pymongo import MongoClient
        try:
            import certifi
            tls_options = {"tlsCAFile": certifi.where()}
        except ImportError:
            tls_options = {}
        client = MongoClient(mongo_uri, serverSelectionTimeoutMS=5000, **tls_options)
        db = client["zeptrax_db"]
        # Ping check
        client.admin.command('ping')
        print("[MongoDB] Connected successfully to zeptrax_db.")

        # Build performance indexes for high-traffic scalability
        try:
            db["User"].create_index("email", unique=True)
            db["User"].create_index("token")
            db["Student"].create_index("id", unique=True)
            db["Course"].create_index("id", unique=True)
            db["Enrollment"].create_index("id", unique=True)
            db["University"].create_index("id", unique=True)
            db["University"].create_index("code", unique=True)
            db["Invitation"].create_index("token_hash", unique=True)
            db["Invitation"].create_index("campaign_id")
            db["User"].create_index("university_id")
            print("[MongoDB] Performance indexes built/verified successfully.")
        except Exception as idx_err:
            print(f"[MongoDB] Index creation warning: {idx_err}")
    else:
        print("[MongoDB] Warning: MONGODB_URI env variable is not set. Using local mock fallbacks.")
except Exception as e:
    print(f"[MongoDB] Error initializing database: {e}")
    db = None

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
SUPER_ADMIN_EMAIL = os.environ.get("SUPER_ADMIN_EMAIL", "mydata193@gmail.com").strip().lower()

# Collections only admins may read through the generic entity endpoints
ADMIN_ONLY_READ = {"User", "AdminInvitation", "EmailLog", "AuditLog", "StudentProfile",
                   "University", "InvitationCampaign", "Invitation"}

# Collections only admins may change through the generic entity endpoints
ADMIN_ONLY_WRITE = {"User", "StudentProfile", "University", "InvitationCampaign", "Invitation",
                    "AdminInvitation", "Certificate", "Course", "CourseModule", "Document",
                    "EmailLog", "Project", "TeamMember", "Review"}

# Collections anyone (even logged out) may add to through the generic entity endpoints
ANONYMOUS_CREATE_OK = {"AuditLog"}

# User fields that only the backend sets
PROTECTED_USER_FIELDS = ("_id", "id", "email", "token", "role", "verified", "password", "password_hash",
                         "university_id", "department", "batch", "invitation_id")

PBKDF2_ITERATIONS = 200_000

# No OTP email is sent yet, so verify-otp only signs in brand-new accounts within this window
OTP_WINDOW_SECONDS = 30 * 60

UNAVAILABLE = {"status": 503, "body": {"error": "Student records are temporarily unavailable. Please try again later."}}


def public_user(user):
    """User document without secrets (password, session token)"""
    if not user:
        return user
    user = dict(user)
    user.pop("password", None)
    user.pop("password_hash", None)
    user.pop("token", None)
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
    user = apply_bootstrap_role(db["User"].find_one({"token": token}))
    if user and user.get("status") == "inactive":
        return None
    return serialize_doc(user)

def handle_db_request(method, path, query_params, body_data, headers):
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
        return partner_universities()
    if normalized == "/admin/students" and method == "GET":
        return admin_students(headers)
    if normalized == "/admin/students/university" and method == "PUT":
        return set_student_university(headers, body_data)

    # University portal: /api/portal/...
    if path.startswith("/api/portal/"):
        if db is None:
            return UNAVAILABLE
        import _portal
        return _portal.handle(db, method, normalized[len("/portal"):], query_params, body_data, get_authorized_user(headers))

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
            user_response = public_user(serialize_doc(new_user))

            return {
                "status": 200,
                "body": {
                    "access_token": token,
                    "user": user_response
                }
            }
        except Exception as e:
            return {"status": 500, "body": {"error": str(e)}}

    # POST /apps/<appId>/auth/login
    match = re.match(r"^/apps/([^/]+)/auth/login$", normalized)
    if match and method == "POST":
        try:
            login_data = json.loads(body_data) if body_data else {}
            email = normalize_email(login_data.get("email"))
            password = login_data.get("password")

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

            # No OTP is emailed yet, so this must not hand out tokens for existing accounts
            if user.get("verified") is not False or time.time() - user.get("created_at", 0) > OTP_WINDOW_SECONDS:
                message = "Verification expired. Please log in with your email and password."
                return {"status": 401, "body": {"error": message, "message": message}}
            db["User"].update_one({"_id": user["_id"]}, {"$set": {"verified": True}})

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
            return {"status": 500, "body": {"error": str(e)}}

    # --- 2. LOG & ANALYTICS ENDPOINTS ---

    # POST /app-logs/<appId>/log-user-in-app/home
    match = re.match(r"^/app-logs/([^/]+)/log-user-in-app/home$", normalized)
    if match and method == "POST":
        try:
            log_data = json.loads(body_data) if body_data else {}
            log_data["timestamp"] = time.time()
            log_data["app_id"] = match.group(1)
            log_data["type"] = "home_visit"
            db["AuditLog"].insert_one(log_data)
            return {"status": 200, "body": {"ok": True}}
        except Exception as e:
            return {"status": 500, "body": {"error": str(e)}}

    # POST /apps/<appId>/analytics/track/batch
    match = re.match(r"^/apps/([^/]+)/analytics/track/batch$", normalized)
    if match and method == "POST":
        try:
            batch_data = json.loads(body_data) if body_data else {}
            batch_data["timestamp"] = time.time()
            batch_data["app_id"] = match.group(1)
            db["AuditLog"].insert_one(batch_data)
            return {"status": 200, "body": {"ok": True}}
        except Exception as e:
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
                    updated_user = db["User"].find_one({"id": user["id"]})
                    return {"status": 200, "body": public_user(serialize_doc(updated_user))}
                except Exception as e:
                    return {"status": 500, "body": {"error": str(e)}}

        # ACCESS CONTROL
        requester = get_authorized_user(headers)
        admin = is_admin(requester)
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
                    return {"status": 500, "body": {"error": str(e)}}

    return None  # Path did not match any database endpoints
