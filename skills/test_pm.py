"""pm.py 점검. 가짜 서버를 띄워 요청 모양(헤더·쿼리·본문·재시도 키)과 spec 요약을 본다.

    python skills/test_pm.py
"""

import importlib.util
import json
import os
import subprocess
import sys
import tempfile
import threading
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from urllib.parse import parse_qs, urlencode, urlparse
from urllib.request import urlopen

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
# 프로젝트 API 문서는 받은 그대로라 Swagger 2(#/definitions/)와 끊긴 참조가 섞여 있을 수 있다.
PROJECT_SPEC = {
    "paths": {
        "/pets": {"parameters": [], "get": {"summary": "List", "responses": {"200": {"$ref": "#/definitions/Pet"}}}},
        "/gone": {"get": {"responses": {"200": {"$ref": "#/definitions/Missing"}}}},
    },
    "definitions": {"Pet": {"properties": {"tag": {"$ref": "#/definitions/Tag"}}}, "Tag": {}},
}
seen = []


def _parse(raw):
    try:
        return json.loads(raw)
    except ValueError:
        return parse_qs(raw.decode())


class Fake(BaseHTTPRequestHandler):
    def _reply(self):
        n = int(self.headers.get("Content-Length") or 0)
        seen.append({"method": self.command, "path": self.path, "headers": dict(self.headers),
                     "body": _parse(self.rfile.read(n)) if n else None})
        if self.path.startswith("/oauth/authorize"):
            # 사람이 허용을 누른 셈 치고 콜백으로 돌려보낸다.
            q = parse_qs(urlparse(self.path).query)
            assert q["code_challenge_method"] == ["S256"]
            self.send_response(302)
            self.send_header("Location", q["redirect_uri"][0] + "?" + urlencode({"code": "c1", "state": q["state"][0]}))
            self.end_headers()
            return
        out = {
            "/api/openapi.json": SPEC,
            "/api/projects/5/api-spec": {"source_url": "a.json", "fetched_at": "t", "spec": PROJECT_SPEC},
            "/oauth/register": {"client_id": "cid"},
            "/oauth/token": {"access_token": "oauth-tok", "scope": "read"},
        }.get(self.path, {"ok": True})
        data = json.dumps(out).encode()
        self.send_response(409 if self.path == "/api/conflict" else 200)
        self.send_header("Content-Length", str(len(data)))
        self.end_headers()
        self.wfile.write(data)

    do_GET = do_POST = do_PATCH = do_PUT = _reply

    def log_message(self, *a):
        pass


def run(*args, stdin=""):
    env = {**os.environ, "UDALLY_TOKEN": "tok", "UDALLY_URL": f"http://127.0.0.1:{server.server_port}"}
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

r = run("apidoc", "5")
assert "GET /pets  List" in json.loads(r.stdout)["endpoints"], r.stderr
r = run("apidoc", "5", "/pets")
assert set(json.loads(r.stdout)["endpoints"]["schemas"]) == {"Pet", "Tag"}
assert run("apidoc", "5", "/gone").returncode == 0  # 끊긴 참조는 건너뛴다
with tempfile.TemporaryDirectory() as tmp:
    f = Path(tmp) / "openapi.json"
    f.write_text(json.dumps(PROJECT_SPEC), encoding="utf-8")
    r = run("apidoc", "5", "put", str(f))
    assert r.returncode == 0, r.stderr
    req = seen.pop()
    assert req["method"] == "PUT" and req["body"] == {"spec": PROJECT_SPEC, "source_url": "openapi.json"}
    r = run("apidoc", "5", "put", f"http://127.0.0.1:{server.server_port}/api/projects/5/api-spec")
    assert r.returncode == 0, r.stderr
    assert "Authorization" not in seen[-2]["headers"]  # 스펙 주소에는 토큰을 보내지 않는다

# Git Bash가 바꿔 넘긴 인자를 되돌린다. 셸 밖(PowerShell 등)에서는 손대지 않는다.
spec_ = importlib.util.spec_from_file_location("pm", PM)
pm = importlib.util.module_from_spec(spec_)
spec_.loader.exec_module(pm)
pm._msys_root = lambda: "C:/Program Files/Git"
os.environ["MSYSTEM"] = "MINGW64"
assert pm._unmangle(["GET", "C:/Program Files/Git/api/me", "q=C:/Program Files/Git/foo", "C:/specs/a.json"]) == [
    "GET", "/api/me", "q=/foo", "C:/specs/a.json"]
os.environ.pop("MSYSTEM")
assert pm._unmangle(["C:/Program Files/Git/api/me"]) == ["C:/Program Files/Git/api/me"]

# OAuth 로그인: 브라우저 대신 스레드가 인가 주소를 열고, 저장한 토큰은 받은 주소로만 쓴다.
with tempfile.TemporaryDirectory() as tmp:
    pm.TOKEN_FILE = Path(tmp) / "token.json"
    os.environ.pop("UDALLY_TOKEN", None)
    os.environ["UDALLY_URL"] = f"http://127.0.0.1:{server.server_port}"
    pm.webbrowser.open = lambda url: threading.Thread(target=urlopen, args=(url,)).start()
    assert pm.login()["scope"] == "read"
    token_req = next(r for r in reversed(seen) if r["path"] == "/oauth/token")
    assert token_req["headers"]["Content-Type"] == "application/x-www-form-urlencoded"
    pm.call("GET", "/api/me")
    assert seen.pop()["headers"]["Authorization"] == "Bearer oauth-tok"
    os.environ["UDALLY_URL"] = "http://127.0.0.1:1"
    try:
        pm.call("GET", "/api/me")
        raise AssertionError("다른 주소로 저장한 토큰을 보냈다")
    except SystemExit as e:
        assert "로그인" in str(e)
    pm.logout()
    assert not pm.TOKEN_FILE.exists()

# 상위·하위 태스크: 낡은 안내(core에 관계가 없다, 설명 첫 줄 상위: TASK-N)가 남지 않았다.
for name in ("pm", "pm-split"):
    doc = (Path(__file__).parent / name / "SKILL.md").read_text(encoding="utf-8")
    assert "core에는 상위·하위 태스크 관계가 없다" not in doc and "첫 줄에 `상위: TASK-N`(" not in doc
assert "group_id" in (Path(__file__).parent / "pm" / "SKILL.md").read_text(encoding="utf-8")

server.shutdown()
print("ok")
