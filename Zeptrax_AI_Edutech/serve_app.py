from http.server import ThreadingHTTPServer, SimpleHTTPRequestHandler
from urllib.parse import urlparse
import urllib.request
import urllib.error
from pathlib import Path
import posixpath
import os
import json

try:
    from db_router import handle_db_request
except ImportError:
    try:
        from Zeptrax_AI_Edutech.db_router import handle_db_request
    except ImportError:
        handle_db_request = None

ROOT = Path(__file__).resolve().parent / "zeptrax-learn-flow"
if not ROOT.exists():
    ROOT = Path(__file__).resolve().parent / "zeptrax-learn-flow.base44.app"


def load_dotenv():
    # Try to find .env file in the current directory or parent directory
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
    url = f"https://generativelanguage.googleapis.com/v1beta/models/gemini-2.5-flash:generateContent?key={api_key}"
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


class AppHandler(SimpleHTTPRequestHandler):
    def __init__(self, *args, **kwargs):
        super().__init__(*args, directory=str(ROOT), **kwargs)

    def do_GET(self):
        parsed = urlparse(self.path)
        query_params = urllib.parse.parse_qs(parsed.query)
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
        self._serve_file()

    def do_HEAD(self):
        self._serve_file(head_only=True)

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
                self.send_response(500)
                self.send_header("Content-Type", "application/json")
                self.send_header("Access-Control-Allow-Origin", "*")
                self.end_headers()
                self.wfile.write(json.dumps({"error": str(e)}).encode('utf-8'))
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


    def _serve_file(self, head_only=False):
        parsed_path = urlparse(self.path).path
        if parsed_path in ("", "/"):
            parsed_path = "/index.html"

        safe_path = self._resolve_candidate(parsed_path)
        if not safe_path:
            if parsed_path.startswith("/api/"):
                self.send_error(404, "Not Found")
                return
            safe_path = "index.html"

        full_path = ROOT / safe_path.lstrip("/")
        if not full_path.exists() or not full_path.is_file():
            if parsed_path.startswith("/api/"):
                self.send_error(404, "Not Found")
                return
            full_path = ROOT / "index.html"

        ctype = self.guess_type(str(full_path))
        self.send_response(200)
        self.send_header("Content-type", ctype)
        self.send_header("Cache-Control", "no-cache")
        self.end_headers()
        if head_only:
            return
        with full_path.open("rb") as fh:
            self.wfile.write(fh.read())

    def _resolve_candidate(self, parsed_path):
        candidates = []
        normalized = posixpath.normpath(parsed_path)
        if normalized == ".":
            normalized = "/"

        candidates.append(normalized)
        if not normalized.endswith("/") and "." not in posixpath.basename(normalized):
            candidates.append(normalized + ".html")
        if normalized.endswith("/") or not normalized.startswith("/api/"):
            candidates.append(normalized + "/index.html")
        else:
            candidates.append(normalized + "/index.html")

        for candidate in candidates:
            if candidate == "/":
                candidate = "/index.html"
            if candidate.startswith("/"):
                candidate = candidate[1:]
            full_path = (ROOT / candidate).resolve()
            try:
                full_path.relative_to(ROOT.resolve())
            except ValueError:
                continue
            if full_path.exists() and full_path.is_file():
                return str(full_path.relative_to(ROOT.resolve())).replace('\\', '/')

        if parsed_path.endswith("/"):
            return None

        html_candidate = parsed_path + ".html"
        if html_candidate.startswith("/"):
            html_candidate = html_candidate[1:]
        full_path = (ROOT / html_candidate).resolve()
        try:
            full_path.relative_to(ROOT.resolve())
        except ValueError:
            return None
        if full_path.exists() and full_path.is_file():
            return str(full_path.relative_to(ROOT.resolve())).replace('\\', '/')

        return None


if __name__ == "__main__":
    port = int(os.environ.get("PORT", "8000"))
    server = ThreadingHTTPServer(("0.0.0.0", port), AppHandler)
    print(f"Serving {ROOT} at http://localhost:{port}")
    server.serve_forever()
