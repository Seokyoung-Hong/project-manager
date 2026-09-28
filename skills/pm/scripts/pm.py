"""산돌이 PM core API를 부르는 표준 라이브러리 스크립트. 스킬이 모두 이것 하나를 쓴다.

    pm.py GET /api/tasks status=doing q=메뉴       쿼리는 key=value
    pm.py POST /api/tasks -  < body.json          본문은 표준입력(-) 또는 인자 JSON
    pm.py POST /api/tasks '{"title": "..."}' --key 요청ID   재시도해도 한 번만 만든다
    pm.py spec [경로 일부]                          OpenAPI에서 엔드포인트와 스키마 찾기
    pm.py apidoc 프로젝트ID [경로 일부]              프로젝트 API 문서에서 엔드포인트와 스키마 찾기
    pm.py apidoc 프로젝트ID put 파일|URL             프로젝트 API 문서 올리기(URL은 이 컴퓨터가 받는다)
    pm.py login | logout                          브라우저 OAuth로 토큰 받기 / 지우기

토큰은 환경 변수 SANDOL_PM_TOKEN, 없으면 `pm.py login`이 저장한 ~/.config/sandol-pm/token.json에서 읽는다.
주소는 SANDOL_PM_URL(기본 https://project.sio2.kr). 저장한 토큰은 받은 주소로만 보낸다.
모든 요청에 X-Source: ai 를 붙인다. 조직의 AI 정책(ai.*)이 이 헤더로 걸린다.
"""

import base64
import hashlib
import json
import os
import re
import secrets
import socket
import sys
import webbrowser
from http.server import BaseHTTPRequestHandler, HTTPServer
from pathlib import Path
from urllib.error import HTTPError, URLError
from urllib.parse import parse_qs, urlencode, urlparse
from urllib.request import Request, urlopen

METHODS = {"GET", "POST", "PATCH", "PUT", "DELETE"}
USAGE = (
    "usage: pm.py METHOD /api/... [key=value ...|JSON|-] [--key ID]  |  pm.py spec [경로 일부]  |  "
    "pm.py apidoc 프로젝트ID [경로 일부 | put 파일|URL]  |  pm.py login|logout"
)
TOKEN_FILE = Path.home() / ".config" / "sandol-pm" / "token.json"


def _base():
    return os.environ.get("SANDOL_PM_URL", "https://project.sio2.kr").rstrip("/")


def _token(base):
    if os.environ.get("SANDOL_PM_TOKEN"):
        return os.environ["SANDOL_PM_TOKEN"]
    try:
        saved = json.loads(TOKEN_FILE.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        saved = {}
    if saved.get("url") == base and saved.get("token"):
        return saved["token"]
    raise SystemExit("로그인이 필요합니다. 사용자가 `python pm.py login`을 실행해 브라우저에서 허용해 주세요.")


def login():
    """OAuth 2.1 + PKCE, 루프백 리다이렉트. core가 MCP 커넥터에 쓰는 인가 서버를 그대로 쓴다."""
    base, got = _base(), {}

    class Callback(BaseHTTPRequestHandler):
        def do_GET(self):
            got.update({k: v[0] for k, v in parse_qs(urlparse(self.path).query).items()})
            self.send_response(200)
            self.send_header("Content-Type", "text/html; charset=utf-8")
            self.end_headers()
            # 브라우저는 스크립트가 열지 않은 탭의 window.close()를 막을 수 있다. 그때는 문구가 남는다.
            self.wfile.write(
                "<!doctype html><meta charset=utf-8><title>산돌이 PM</title>"
                "<p>산돌이 PM 로그인이 끝났습니다. 창이 자동으로 닫히지 않으면 닫아 주세요.</p>"
                "<script>setTimeout(() => window.close(), 300)</script>".encode()
            )

        def log_message(self, *a):
            pass

    server = HTTPServer(("127.0.0.1", 0), Callback)
    server.timeout = 300
    redirect = f"http://127.0.0.1:{server.server_port}/callback"
    client = _post(f"{base}/oauth/register", json.dumps(
        {"client_name": f"산돌이 PM 스킬 ({socket.gethostname()})", "redirect_uris": [redirect]}
    ).encode(), "application/json")
    verifier, state = secrets.token_urlsafe(48), secrets.token_urlsafe(16)
    challenge = base64.urlsafe_b64encode(hashlib.sha256(verifier.encode()).digest()).rstrip(b"=").decode()
    url = f"{base}/oauth/authorize?" + urlencode({
        "response_type": "code", "client_id": client["client_id"], "redirect_uri": redirect,
        "state": state, "code_challenge": challenge, "code_challenge_method": "S256",
    })
    print(f"브라우저에서 로그인하고 허용해 주세요. 창이 열리지 않으면 이 주소를 여세요:\n{url}", file=sys.stderr)
    webbrowser.open(url)
    server.handle_request()  # 콜백 한 번만 받는다(5분 제한)
    server.server_close()
    if got.get("state") != state or "code" not in got:
        raise SystemExit(f"로그인하지 못했습니다: {got.get('error', '응답 없음')}")
    tok = _post(f"{base}/oauth/token", urlencode({
        "grant_type": "authorization_code", "code": got["code"], "client_id": client["client_id"],
        "redirect_uri": redirect, "code_verifier": verifier,
    }).encode(), "application/x-www-form-urlencoded")
    TOKEN_FILE.parent.mkdir(parents=True, exist_ok=True)
    TOKEN_FILE.write_text(json.dumps({"url": base, "token": tok["access_token"], "scope": tok["scope"]}), encoding="utf-8")
    TOKEN_FILE.chmod(0o600)
    return {"logged_in": base, "scope": tok["scope"], "saved": str(TOKEN_FILE)}


def logout():
    TOKEN_FILE.unlink(missing_ok=True)
    return {"logged_out": True, "note": "서버의 토큰은 남아 있습니다. /settings/tokens에서 폐기하세요."}


def _post(url, data, content_type):
    try:
        with urlopen(Request(url, data=data, headers={"Content-Type": content_type}, method="POST"), timeout=30) as r:
            return json.load(r)
    except HTTPError as e:
        raise SystemExit(f"HTTP {e.code}: {e.read().decode('utf-8', errors='replace')}")
    except URLError as e:
        raise SystemExit(f"연결 실패: {e.reason}")


def call(method, path, query=None, body=None, key=None):
    if not path.startswith("/api/"):
        raise SystemExit("경로는 /api/ 로 시작해야 합니다.")
    base = _base()
    token = _token(base)
    url = base + path + ("?" + urlencode(query) if query else "")
    headers = {"Authorization": f"Bearer {token}", "X-Source": "ai", "Accept": "application/json"}
    data = None
    if body is not None:
        data = json.dumps(body, ensure_ascii=False).encode("utf-8")
        headers["Content-Type"] = "application/json"
    if key:
        headers["Idempotency-Key"] = key
    try:
        with urlopen(Request(url, data=data, headers=headers, method=method), timeout=30) as r:
            raw = r.read()
            return json.loads(raw) if raw else None
    except HTTPError as e:
        raise SystemExit(f"HTTP {e.code}: {e.read().decode('utf-8', errors='replace')}")
    except URLError as e:
        raise SystemExit(f"연결 실패: {e.reason}")


def summarize(doc, needle=""):
    """OpenAPI 문서에서 경로 일부가 맞는 엔드포인트만 뽑는다. 없으면 한 줄씩 목록."""
    paths = {p: ops for p, ops in doc.get("paths", {}).items() if needle in p}
    if not needle:
        return [
            f"{m.upper()} {p}  {op.get('summary', '')}"
            for p, ops in paths.items() for m, op in ops.items() if isinstance(op, dict)
        ]
    # 찾은 경로가 참조하는 스키마를 따라가 함께 돌려준다. #/definitions/(Swagger 2)도 같은 방식으로 푼다.
    schemas, todo = {}, [json.dumps(paths)]
    while todo:
        for ref in set(re.findall(r'"\$ref": "#/([^"]+)"', todo.pop())):
            name = ref.rsplit("/", 1)[-1]
            if name in schemas:
                continue
            node = doc
            for part in ref.split("/"):
                node = node.get(part) if isinstance(node, dict) else None
            if node is not None:  # 받은 문서 그대로라 끊긴 참조가 있을 수 있다
                schemas[name] = node
                todo.append(json.dumps(node))
    return {"paths": paths, "schemas": schemas}


def spec(needle=""):
    return summarize(call("GET", "/api/openapi.json"), needle)


def apidoc(project, args):
    path = f"/api/projects/{int(project)}/api-spec"
    if args[:1] != ["put"]:
        got = call("GET", path)
        return {"source_url": got["source_url"], "fetched_at": got["fetched_at"],
                "endpoints": summarize(got["spec"], args[0] if args else "")}
    if len(args) != 2:
        raise SystemExit(USAGE)
    src = args[1]
    try:
        if src.startswith(("http://", "https://")):
            # 이 컴퓨터가 받는다. 로컬 개발 서버의 스펙도 올릴 수 있다. 토큰은 보내지 않는다.
            with urlopen(Request(src, headers={"Accept": "application/json"}), timeout=30) as r:
                doc = json.load(r)
        else:
            doc = json.loads(Path(src).read_text(encoding="utf-8"))
    except (OSError, ValueError) as e:
        raise SystemExit(f"{src}를 JSON으로 읽지 못했습니다: {e}")
    return call("PUT", path, body={"spec": doc, "source_url": src if "://" in src else Path(src).name})


def main(argv):
    for stream in (sys.stdin, sys.stdout, sys.stderr):
        stream.reconfigure(encoding="utf-8")
    key = None
    if "--key" in argv:
        i = argv.index("--key")
        key = argv[i + 1] if i + 1 < len(argv) else None
        argv = argv[:i] + argv[i + 2:]
    if argv[:1] in (["login"], ["logout"]):
        result = login() if argv[0] == "login" else logout()
    elif argv[:1] == ["spec"]:
        result = spec(argv[1] if len(argv) > 1 else "")
    elif argv[:1] == ["apidoc"] and len(argv) >= 2 and argv[1].isdigit():
        result = apidoc(argv[1], argv[2:])
    elif len(argv) >= 2 and argv[0].upper() in METHODS:
        method, path, rest = argv[0].upper(), argv[1], argv[2:]
        query, body = {}, None
        for arg in rest:
            if arg == "-":
                body = json.load(sys.stdin)
            elif arg.lstrip().startswith(("{", "[")):
                body = json.loads(arg)
            elif "=" in arg:
                k, v = arg.split("=", 1)
                query[k] = v
            else:
                raise SystemExit(USAGE)
        if body is not None and method == "GET":
            raise SystemExit("GET에는 본문을 보낼 수 없습니다. key=value로 넘겨 주세요.")
        result = call(method, path, query, body, key)
    else:
        raise SystemExit(USAGE)
    print(json.dumps(result, ensure_ascii=False, indent=2, default=str))


if __name__ == "__main__":
    main(sys.argv[1:])
