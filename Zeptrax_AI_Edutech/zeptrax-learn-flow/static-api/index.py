from http.server import BaseHTTPRequestHandler
from urllib.parse import urlparse
import urllib.request
import urllib.error
from pathlib import Path
import os
import json

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


# Tried in order; later models are used when earlier ones are overloaded
GEMINI_MODELS = ["gemini-3.5-flash-lite", "gemini-3.5-flash", "gemini-2.5-flash"]


def call_gemini(prompt, schema=None, api_key=None):
    api_key = clean_api_key(api_key)
    last_error = None
    for model in GEMINI_MODELS:
        url = f"https://generativelanguage.googleapis.com/v1beta/models/{model}:generateContent?key={api_key}"
        payload = {
            "contents": [{
                "parts": [{
                    "text": prompt
                }]
            }]
        }
        # Minimal thinking keeps chat replies fast (~3s instead of 10-20s)
        if model.startswith("gemini-2.5"):
            payload["generationConfig"] = {"thinkingConfig": {"thinkingBudget": 0}}
        else:
            payload["generationConfig"] = {"thinkingConfig": {"thinkingLevel": "minimal"}}
        if schema:
            payload["generationConfig"]["responseMimeType"] = "application/json"
            payload["generationConfig"]["responseSchema"] = schema

        req = urllib.request.Request(
            url,
            data=json.dumps(payload).encode("utf-8"),
            headers={"Content-Type": "application/json"},
            method="POST"
        )

        try:
            with urllib.request.urlopen(req, timeout=10) as response:
                res_json = json.loads(response.read().decode("utf-8"))
            text_response = res_json["candidates"][0]["content"]["parts"][0]["text"]
            try:
                return json.loads(text_response)
            except Exception:
                return {"response": text_response}
        except urllib.error.HTTPError as e:
            error_info = e.read().decode('utf-8')
            print(f"Gemini API HTTP Error ({model}): {e.code} - {error_info}")
            if e.code not in (429, 500, 503, 504):
                raise Exception(f"Gemini API Error: {error_info}")
            last_error = e
        except Exception as e:
            print(f"Error calling Gemini API ({model}): {e}")
            last_error = e
    raise Exception(f"All Gemini models unavailable: {last_error}")


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

class handler(BaseHTTPRequestHandler):
    def do_GET(self):
        self.send_response(200)
        self.send_header('Content-type', 'application/json')
        self.send_header("Access-Control-Allow-Origin", "*")
        self.send_header("Access-Control-Allow-Methods", "POST, GET, OPTIONS")
        self.send_header("Access-Control-Allow-Headers", "Content-Type, Authorization")
        self.end_headers()
        self.wfile.write(b'{"status": "AI backend handler is active"}')

    def do_OPTIONS(self):
        self.send_response(204)
        self.send_header("Access-Control-Allow-Origin", "*")
        self.send_header("Access-Control-Allow-Methods", "POST, GET, OPTIONS")
        self.send_header("Access-Control-Allow-Headers", "Content-Type, Authorization")
        self.end_headers()

    def do_POST(self):
        parsed_path = urlparse(self.path).path
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
                self.send_header("Access-Control-Allow-Methods", "POST, GET, OPTIONS")
                self.send_header("Access-Control-Allow-Headers", "Content-Type, Authorization")
                self.end_headers()
                self.wfile.write(json.dumps(response_data).encode('utf-8'))
                return
            except Exception as e:
                print(f"InvokeLLM error: {e}")
                self.send_response(200)
                self.send_header("Content-Type", "application/json")
                self.send_header("Access-Control-Allow-Origin", "*")
                self.send_header("Access-Control-Allow-Methods", "POST, GET, OPTIONS, PUT, DELETE, PATCH")
                self.send_header("Access-Control-Allow-Headers", "Content-Type, Authorization")
                self.end_headers()
                self.wfile.write(json.dumps({"response": "Zep AI is busy right now. Please try again in a moment, or WhatsApp us at +91-8368544821."}).encode('utf-8'))
                return

        # Default fallback for other posts
        self.send_response(200)
        self.send_header("Content-Type", "application/json")
        self.send_header("Access-Control-Allow-Origin", "*")
        self.end_headers()
        self.wfile.write(b'{"ok": true}')
