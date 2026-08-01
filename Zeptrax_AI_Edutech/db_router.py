import os
import json
import re
import uuid
import time
import urllib.parse

from pathlib import Path

def load_dotenv():
    start_dir = Path(__file__).resolve().parent
    for path in [Path("."), start_dir, start_dir.parent, start_dir.parent.parent]:
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
        client = MongoClient(mongo_uri, serverSelectionTimeoutMS=5000, tlsAllowInvalidCertificates=True)
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
    user = db["User"].find_one({"token": token})
    return serialize_doc(user)

def handle_db_request(method, path, query_params, body_data, headers):
    """
    Core dynamic router that intercepts base44 entity CRUD and auth endpoints 
    and handles them in MongoDB collections.
    """
    if db is None:
        return None  # Database not initialized; fallback to static file mocks

    # Normalize path (remove leading /api if present)
    normalized = path
    if normalized.startswith("/api"):
        normalized = normalized[4:]

    # --- 1. AUTHENTICATION ENDPOINTS ---
    
    # POST /apps/<appId>/auth/register
    match = re.match(r"^/apps/([^/]+)/auth/register$", normalized)
    if match and method == "POST":
        app_id = match.group(1)
        try:
            user_data = json.loads(body_data) if body_data else {}
            email = user_data.get("email")
            if not email:
                return {"status": 400, "body": {"error": "Email is required"}}
                
            # Check if user already exists
            existing_user = db["User"].find_one({"email": email})
            if existing_user:
                return {"status": 400, "body": {"error": "User already exists"}}
                
            user_id = str(uuid.uuid4())
            token = uuid.uuid4().hex
            
            new_user = {
                "id": user_id,
                "email": email,
                "password": user_data.get("password", ""),  # In production, hash this
                "name": user_data.get("name", "Student"),
                "role": user_data.get("role", "user"),
                "token": token,
                "created_at": time.time(),
                "app_id": app_id
            }
            db["User"].insert_one(new_user)
            user_response = serialize_doc(new_user)
            # Remove password before returning
            user_response.pop("password", None)
            
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
            email = login_data.get("email")
            password = login_data.get("password")
            
            user = db["User"].find_one({"email": email})
            if not user or user.get("password") != password:
                return {"status": 401, "body": {"error": "Invalid email or password"}}
                
            # If user has no token, generate one
            token = user.get("token")
            if not token:
                token = uuid.uuid4().hex
                db["User"].update_one({"_id": user["_id"]}, {"$set": {"token": token}})
                user["token"] = token
                
            user_response = serialize_doc(user)
            user_response.pop("password", None)
            
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
            email = otp_data.get("email")
            user = db["User"].find_one({"email": email})
            if not user:
                return {"status": 404, "body": {"error": "User not found"}}
                
            token = user.get("token")
            if not token:
                token = uuid.uuid4().hex
                db["User"].update_one({"_id": user["_id"]}, {"$set": {"token": token}})
                user["token"] = token
                
            user_response = serialize_doc(user)
            user_response.pop("password", None)
            
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
                return {"status": 200, "body": user}
                
            elif method == "PUT":
                user = get_authorized_user(headers)
                if not user:
                    return {"status": 401, "body": {"error": "Authentication required"}}
                try:
                    update_data = json.loads(body_data) if body_data else {}
                    # Avoid updating the immutable fields
                    update_data.pop("_id", None)
                    update_data.pop("id", None)
                    update_data.pop("email", None)
                    update_data.pop("token", None)
                    
                    db["User"].update_one({"id": user["id"]}, {"$set": update_data})
                    updated_user = db["User"].find_one({"id": user["id"]})
                    return {"status": 200, "body": serialize_doc(updated_user)}
                except Exception as e:
                    return {"status": 500, "body": {"error": str(e)}}

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
                return {"status": 200, "body": serialize_doc(doc)}
                
            # List or filter documents
            else:
                filter_dict = {}
                q_param = query_params.get("q")
                if q_param:
                    try:
                        filter_dict = json.loads(q_param[0])
                    except Exception as e:
                        print(f"Error parsing filter: {e}")
                
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
                    
                results = list(cursor)
                return {"status": 200, "body": serialize_doc(results)}
                
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
