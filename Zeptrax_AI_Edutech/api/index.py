from http.server import BaseHTTPRequestHandler
from urllib.parse import urlparse
import urllib.request
import urllib.error
from pathlib import Path
import os
import json
import re
import uuid
import time

try:
    from Zeptrax_AI_Edutech.db_router import handle_db_request
except ImportError:
    try:
        from db_router import handle_db_request
    except ImportError:
        handle_db_request = None

def load_dotenv():
    # Try to find .env file in the root or parent directories
    for path in [Path("."), Path(__file__).resolve().parent, Path(__file__).resolve().parent.parent]:
        env_file = path / ".env"
        if env_file.exists():
            try:
                with env_file.open("r", encoding="utf-8") as f:
                    for line in f:
                        line = line.strip()
                        if line and not line.startswith("#") and "=" in line:
                            k, v = line.split("=", 1)
                            os.environ[k.strip()] = v.strip().strip('"').strip("'")
            except Exception as e:
                print(f"Error loading .env file from {env_file}: {e}")

def clean_api_key(key):
    if not key:
        return key
    first_line = key.split('\n')[0].split('\r')[0].strip()
    first_word = first_line.split(' ')[0].strip()
    return first_word.strip('"').strip("'")


def call_gemini(prompt, schema=None, api_key=None):
    api_key = clean_api_key(api_key)
    url = f"https://generativelanguage.googleapis.com/v1beta/models/gemini-3.5-flash:generateContent?key={api_key}"
    payload = {
        "contents": [{
            "parts": [{
                "text": prompt
            }]
        }]
    }
    if schema:
        payload["generationConfig"] = {
            "responseMimeType": "application/json",
            "responseSchema": schema
        }
        
    req = urllib.request.Request(
        url,
        data=json.dumps(payload).encode("utf-8"),
        headers={"Content-Type": "application/json"},
        method="POST"
    )
    
    try:
        with urllib.request.urlopen(req) as response:
            res_data = response.read().decode("utf-8")
            res_json = json.loads(res_data)
            text_response = res_json["candidates"][0]["content"]["parts"][0]["text"]
            try:
                return json.loads(text_response)
            except Exception:
                return {"response": text_response}
    except urllib.error.HTTPError as e:
        error_info = e.read().decode('utf-8')
        print(f"Gemini API HTTP Error: {e.code} - {error_info}")
        raise Exception(f"Gemini API Error: {error_info}")
    except Exception as e:
        print(f"Error calling Gemini API: {e}")
        raise


def call_openai(prompt, schema=None, api_key=None):
    api_key = clean_api_key(api_key)
    url = "https://api.openai.com/v1/chat/completions"
    payload = {
        "model": "gpt-4o-mini",
        "messages": [
            {"role": "user", "content": prompt}
        ]
    }
    if schema:
        payload["response_format"] = {
            "type": "json_object"
        }
        
    req = urllib.request.Request(
        url,
        data=json.dumps(payload).encode("utf-8"),
        headers={
            "Content-Type": "application/json",
            "Authorization": f"Bearer {api_key}"
        },
        method="POST"
    )
    
    try:
        with urllib.request.urlopen(req) as response:
            res_data = response.read().decode("utf-8")
            res_json = json.loads(res_data)
            text_response = res_json["choices"][0]["message"]["content"]
            try:
                return json.loads(text_response)
            except Exception:
                return {"response": text_response}
    except urllib.error.HTTPError as e:
        error_info = e.read().decode('utf-8')
        print(f"OpenAI API HTTP Error: {e.code} - {error_info}")
        raise Exception(f"OpenAI API Error: {error_info}")
    except Exception as e:
        print(f"Error calling OpenAI API: {e}")
        raise

HERE = Path(__file__).resolve().parent

class handler(BaseHTTPRequestHandler):
    def do_GET(self):
        parsed = urlparse(self.path)
        query_params = urllib.parse.parse_qs(parsed.query)
        
        # Intercept Social Logins (Google, GitHub, Facebook, LinkedIn)
        social_match = re.match(r"^/api/apps/auth(?:/([^/]+))?/login$", parsed.path)
        if social_match:
            from_url_list = query_params.get("from_url", [])
            from_url = from_url_list[0] if from_url_list else "/"
            
            # Generate or fetch a mock/registered token
            mock_token = "4756938a25abc81883c3619b5cc8abcd"
            
            # If MongoDB is connected, let's find or create a mock user for this provider
            if handle_db_request:
                try:
                    from db_router import db as database
                    if database is not None:
                        provider = social_match.group(1) or "google"
                        email = f"social_{provider}@zeptrax.in"
                        user = database["User"].find_one({"email": email})
                        if user:
                            mock_token = user.get("token", mock_token)
                        else:
                            mock_token = uuid.uuid4().hex
                            new_user = {
                                "id": str(uuid.uuid4()),
                                "email": email,
                                "name": f"{provider.capitalize()} User",
                                "role": "user",
                                "token": mock_token,
                                "created_at": time.time(),
                                "app_id": query_params.get("app_id", ["6a58811b763e4b993e2b1bed"])[0]
                            }
                            database["User"].insert_one(new_user)
                except Exception as db_err:
                    print(f"Error in social login database check: {db_err}")
            
            # Parse from_url and append access_token
            parsed_from = urlparse(from_url)
            sep = "&" if parsed_from.query else "?"
            redirect_url = f"{from_url}{sep}access_token={mock_token}"
            
            self.send_response(302)
            self.send_header("Location", redirect_url)
            self.send_header("Access-Control-Allow-Origin", "*")
            self.end_headers()
            return

        if handle_db_request:
            db_response = handle_db_request("GET", parsed.path, query_params, None, self.headers)
            if db_response is not None:
                self.send_response(db_response["status"])
                self.send_header("Content-Type", "application/json")
                self.send_header("Access-Control-Allow-Origin", "*")
                self.send_header("Access-Control-Allow-Methods", "POST, GET, OPTIONS, PUT, DELETE, PATCH")
                self.send_header("Access-Control-Allow-Headers", "Content-Type, Authorization")
                self.end_headers()
                self.wfile.write(json.dumps(db_response["body"]).encode('utf-8'))
                return
        
        # File fallback: Try to serve static mock files from disk
        path_str = parsed.path.lstrip("/")
        
        # Build list of potential roots where the frontend build files are stored
        search_roots = [
            HERE.parent,
            HERE.parent / "Zeptrax_AI_Edutech",
            HERE.parent / "Zeptrax_AI_Edutech" / "zeptrax-learn-flow",
            HERE.parent / "zeptrax-learn-flow",
            HERE
        ]
        
        candidates = []
        for root in search_roots:
            candidates.append(root / path_str)
            candidates.append(root / f"{path_str}.html")
            candidates.append(root / f"{path_str}.json")
            if "api/" in path_str:
                alt = path_str.replace("api/", "static-api/")
                candidates.append(root / alt)
                candidates.append(root / f"{alt}.html")
                candidates.append(root / f"{alt}.json")
                
                alt2 = path_str.replace("api/", "")
                candidates.append(root / alt2)
                candidates.append(root / f"{alt2}.html")
                candidates.append(root / f"{alt2}.json")

        for candidate in candidates:
            if candidate.exists() and candidate.is_file():
                self.send_response(200)
                if candidate.suffix == ".json":
                    self.send_header("Content-Type", "application/json")
                else:
                    self.send_header("Content-Type", "text/html; charset=utf-8")
                self.send_header("Access-Control-Allow-Origin", "*")
                self.send_header("Access-Control-Allow-Methods", "POST, GET, OPTIONS, PUT, DELETE, PATCH")
                self.send_header("Access-Control-Allow-Headers", "Content-Type, Authorization")
                self.end_headers()
                with candidate.open("rb") as f:
                    self.wfile.write(f.read())
                return

        self.send_response(200)
        self.send_header('Content-type', 'application/json')
        self.send_header("Access-Control-Allow-Origin", "*")
        self.send_header("Access-Control-Allow-Methods", "POST, GET, OPTIONS, PUT, DELETE, PATCH")
        self.send_header("Access-Control-Allow-Headers", "Content-Type, Authorization")
        self.end_headers()
        self.wfile.write(json.dumps({
            "status": "AI backend handler is active",
            "path": self.path,
            "headers": dict(self.headers)
        }).encode('utf-8'))

    def do_OPTIONS(self):
        self.send_response(204)
        self.send_header("Access-Control-Allow-Origin", "*")
        self.send_header("Access-Control-Allow-Methods", "POST, GET, OPTIONS, PUT, DELETE, PATCH")
        self.send_header("Access-Control-Allow-Headers", "Content-Type, Authorization")
        self.end_headers()

    def do_POST(self):
        parsed = urlparse(self.path)
        parsed_path = parsed.path
        if parsed_path.endswith("/integration-endpoints/Core/InvokeLLM"):
            try:
                content_length = int(self.headers.get('Content-Length', 0))
                post_data = self.rfile.read(content_length)
                req_json = json.loads(post_data.decode('utf-8'))
                prompt = req_json.get("prompt", "")
                schema = req_json.get("response_json_schema")
                
                # Load environment variables
                load_dotenv()
                
                gemini_key = os.environ.get("GEMINI_API_KEY")
                openai_key = os.environ.get("OPENAI_API_KEY")
                
                response_data = None
                if gemini_key:
                    response_data = call_gemini(prompt, schema, gemini_key)
                elif openai_key:
                    response_data = call_openai(prompt, schema, openai_key)
                else:
                    response_data = {
                        "response": "Connection successful, but GEMINI_API_KEY or OPENAI_API_KEY is not configured on the server environment. Please set it to activate the AI agent."
                    }
                
                self.send_response(200)
                self.send_header("Content-Type", "application/json")
                self.send_header("Access-Control-Allow-Origin", "*")
                self.send_header("Access-Control-Allow-Methods", "POST, GET, OPTIONS, PUT, DELETE, PATCH")
                self.send_header("Access-Control-Allow-Headers", "Content-Type, Authorization")
                self.end_headers()
                self.wfile.write(json.dumps(response_data).encode('utf-8'))
                return
            except Exception as e:
                self.send_response(200)
                self.send_header("Content-Type", "application/json")
                self.send_header("Access-Control-Allow-Origin", "*")
                self.send_header("Access-Control-Allow-Methods", "POST, GET, OPTIONS, PUT, DELETE, PATCH")
                self.send_header("Access-Control-Allow-Headers", "Content-Type, Authorization")
                self.end_headers()
                self.wfile.write(json.dumps({"response": f"Server Error: {str(e)}"}).encode('utf-8'))
                return

        # Handle dynamic DB POST requests
        content_length = int(self.headers.get('Content-Length', 0))
        body_data = self.rfile.read(content_length).decode('utf-8') if content_length > 0 else ""
        query_params = urllib.parse.parse_qs(parsed.query)
        if handle_db_request:
            db_response = handle_db_request("POST", parsed.path, query_params, body_data, self.headers)
            if db_response is not None:
                self.send_response(db_response["status"])
                self.send_header("Content-Type", "application/json")
                self.send_header("Access-Control-Allow-Origin", "*")
                self.send_header("Access-Control-Allow-Methods", "POST, GET, OPTIONS, PUT, DELETE, PATCH")
                self.send_header("Access-Control-Allow-Headers", "Content-Type, Authorization")
                self.end_headers()
                self.wfile.write(json.dumps(db_response["body"]).encode('utf-8'))
                return

        # File fallback for POST: Try to serve static mock files from disk
        path_str = parsed.path.lstrip("/")
        
        # Build list of potential roots where the frontend build files are stored
        search_roots = [
            HERE.parent,
            HERE.parent / "Zeptrax_AI_Edutech",
            HERE.parent / "Zeptrax_AI_Edutech" / "zeptrax-learn-flow",
            HERE.parent / "zeptrax-learn-flow",
            HERE
        ]
        
        candidates = []
        for root in search_roots:
            candidates.append(root / path_str)
            candidates.append(root / f"{path_str}.html")
            candidates.append(root / f"{path_str}.json")
            if "api/" in path_str:
                alt = path_str.replace("api/", "static-api/")
                candidates.append(root / alt)
                candidates.append(root / f"{alt}.html")
                candidates.append(root / f"{alt}.json")
                
                alt2 = path_str.replace("api/", "")
                candidates.append(root / alt2)
                candidates.append(root / f"{alt2}.html")
                candidates.append(root / f"{alt2}.json")

        for candidate in candidates:
            if candidate.exists() and candidate.is_file():
                self.send_response(200)
                if candidate.suffix == ".json":
                    self.send_header("Content-Type", "application/json")
                else:
                    self.send_header("Content-Type", "text/html; charset=utf-8")
                self.send_header("Access-Control-Allow-Origin", "*")
                self.send_header("Access-Control-Allow-Methods", "POST, GET, OPTIONS, PUT, DELETE, PATCH")
                self.send_header("Access-Control-Allow-Headers", "Content-Type, Authorization")
                self.end_headers()
                with candidate.open("rb") as f:
                    self.wfile.write(f.read())
                return

        # Default fallback for other posts
        self.send_response(200)
        self.send_header("Content-Type", "application/json")
        self.send_header("Access-Control-Allow-Origin", "*")
        self.send_header("Access-Control-Allow-Methods", "POST, GET, OPTIONS, PUT, DELETE, PATCH")
        self.send_header("Access-Control-Allow-Headers", "Content-Type, Authorization")
        self.end_headers()
        self.wfile.write(b'{"ok": true}')

    def do_PUT(self):
        content_length = int(self.headers.get('Content-Length', 0))
        body_data = self.rfile.read(content_length).decode('utf-8') if content_length > 0 else ""
        parsed = urlparse(self.path)
        query_params = urllib.parse.parse_qs(parsed.query)
        if handle_db_request:
            db_response = handle_db_request("PUT", parsed.path, query_params, body_data, self.headers)
            if db_response is not None:
                self.send_response(db_response["status"])
                self.send_header("Content-Type", "application/json")
                self.send_header("Access-Control-Allow-Origin", "*")
                self.send_header("Access-Control-Allow-Methods", "POST, GET, OPTIONS, PUT, DELETE, PATCH")
                self.send_header("Access-Control-Allow-Headers", "Content-Type, Authorization")
                self.end_headers()
                self.wfile.write(json.dumps(db_response["body"]).encode('utf-8'))
                return
        self.send_response(404)
        self.end_headers()

    def do_DELETE(self):
        content_length = int(self.headers.get('Content-Length', 0))
        body_data = self.rfile.read(content_length).decode('utf-8') if content_length > 0 else ""
        parsed = urlparse(self.path)
        query_params = urllib.parse.parse_qs(parsed.query)
        if handle_db_request:
            db_response = handle_db_request("DELETE", parsed.path, query_params, body_data, self.headers)
            if db_response is not None:
                self.send_response(db_response["status"])
                self.send_header("Content-Type", "application/json")
                self.send_header("Access-Control-Allow-Origin", "*")
                self.send_header("Access-Control-Allow-Methods", "POST, GET, OPTIONS, PUT, DELETE, PATCH")
                self.send_header("Access-Control-Allow-Headers", "Content-Type, Authorization")
                self.end_headers()
                self.wfile.write(json.dumps(db_response["body"]).encode('utf-8'))
                return
        self.send_response(404)
        self.end_headers()

    def do_PATCH(self):
        content_length = int(self.headers.get('Content-Length', 0))
        body_data = self.rfile.read(content_length).decode('utf-8') if content_length > 0 else ""
        parsed = urlparse(self.path)
        query_params = urllib.parse.parse_qs(parsed.query)
        if handle_db_request:
            db_response = handle_db_request("PATCH", parsed.path, query_params, body_data, self.headers)
            if db_response is not None:
                self.send_response(db_response["status"])
                self.send_header("Content-Type", "application/json")
                self.send_header("Access-Control-Allow-Origin", "*")
                self.send_header("Access-Control-Allow-Methods", "POST, GET, OPTIONS, PUT, DELETE, PATCH")
                self.send_header("Access-Control-Allow-Headers", "Content-Type, Authorization")
                self.end_headers()
                self.wfile.write(json.dumps(db_response["body"]).encode('utf-8'))
                return
        self.send_response(404)
        self.end_headers()
