from http.server import ThreadingHTTPServer, SimpleHTTPRequestHandler
from urllib.parse import urlparse
from pathlib import Path
import posixpath
import os
import json

ROOT = Path(__file__).resolve().parent / "zeptrax-learn-flow.base44.app"


class AppHandler(SimpleHTTPRequestHandler):
    def __init__(self, *args, **kwargs):
        super().__init__(*args, directory=str(ROOT), **kwargs)

    def do_GET(self):
        self._serve_file()

    def do_HEAD(self):
        self._serve_file(head_only=True)

    def do_POST(self):
        self.send_response(200)
        self.send_header("Content-Type", "application/json")
        self.end_headers()
        self.wfile.write(b'{"ok": true}')

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
