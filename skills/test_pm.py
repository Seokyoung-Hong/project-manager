"""pm.py 점검. 가짜 서버를 띄워 요청 모양(헤더·쿼리·본문·재시도 키)과 spec 요약을 본다.

    python skills/test_pm.py
"""

import json
import os
import subprocess
import sys
import threading
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path

PM = Path(__file__).parent / "pm" / "scripts" / "pm.py"
SPEC = {
    "paths": {
        "/api/tasks": {"post": {"summary": "Create", "requestBody": {"$ref": "#/components/schemas/TaskCreateIn"}}},
        "/api/me": {"get": {"summary": "Me"}},
    },
    "components": {"schemas": {
        "TaskCreateIn": {"properties": {"checklist": {"$ref": "#/components/schemas/ChecklistIn"}}},
        "ChecklistIn": {"properties": {"text": {"type": "string"}}},
        "Unused": {},
    }},
}
seen = []


class Fake(BaseHTTPRequestHandler):
    def _reply(self):
        n = int(self.headers.get("Content-Length") or 0)
        seen.append({"method": self.command, "path": self.path, "headers": dict(self.headers),
                     "body": json.loads(self.rfile.read(n)) if n else None})
        out = SPEC if self.path == "/api/openapi.json" else {"ok": True}
        data = json.dumps(out).encode()
        self.send_response(409 if self.path == "/api/conflict" else 200)
        self.send_header("Content-Length", str(len(data)))
        self.end_headers()
        self.wfile.write(data)

    do_GET = do_POST = do_PATCH = _reply

    def log_message(self, *a):
        pass


def run(*args, stdin=""):
    env = {**os.environ, "SANDOL_PM_TOKEN": "tok", "SANDOL_PM_URL": f"http://127.0.0.1:{server.server_port}"}
    return subprocess.run([sys.executable, str(PM), *args], input=stdin, capture_output=True,
                          text=True, encoding="utf-8", env=env)


server = ThreadingHTTPServer(("127.0.0.1", 0), Fake)
threading.Thread(target=server.serve_forever, daemon=True).start()

r = run("GET", "/api/tasks", "status=doing", "q=메뉴")
assert r.returncode == 0, r.stderr
req = seen.pop()
assert req["path"].startswith("/api/tasks?status=doing&q=")
assert req["headers"]["Authorization"] == "Bearer tok" and req["headers"]["X-Source"] == "ai"

r = run("POST", "/api/tasks", "-", "--key", "req-1", stdin='{"title": "학식"}')
assert r.returncode == 0, r.stderr
req = seen.pop()
assert req["body"] == {"title": "학식"} and req["headers"]["Idempotency-Key"] == "req-1"

r = run("PATCH", "/api/tasks/3", '{"version": 2}')
assert seen.pop()["body"] == {"version": 2}

r = run("POST", "/api/conflict", "{}")
assert r.returncode != 0 and "HTTP 409" in r.stderr

assert run("GET", "/elsewhere").returncode != 0  # /api/ 밖으로는 토큰을 보내지 않는다

r = run("spec")
assert "POST /api/tasks  Create" in r.stdout
r = run("spec", "/api/tasks")
assert set(json.loads(r.stdout)["schemas"]) == {"TaskCreateIn", "ChecklistIn"}

server.shutdown()
print("ok")
