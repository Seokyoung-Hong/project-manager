"""산돌이 PM core API를 부르는 표준 라이브러리 스크립트. 스킬이 모두 이것 하나를 쓴다.

    pm.py GET /api/tasks status=doing q=메뉴       쿼리는 key=value
    pm.py POST /api/tasks -  < body.json          본문은 표준입력(-) 또는 인자 JSON
    pm.py POST /api/tasks '{"title": "..."}' --key 요청ID   재시도해도 한 번만 만든다
    pm.py spec [경로 일부]                          OpenAPI에서 엔드포인트와 스키마 찾기

토큰은 SANDOL_PM_TOKEN, 주소는 SANDOL_PM_URL(기본 https://project.sio2.kr)에서 읽는다.
모든 요청에 X-Source: ai 를 붙인다. 조직의 AI 정책(ai.*)이 이 헤더로 걸린다.
"""

import json
import os
import sys
from urllib.error import HTTPError, URLError
from urllib.parse import urlencode
from urllib.request import Request, urlopen

METHODS = {"GET", "POST", "PATCH", "PUT", "DELETE"}
USAGE = "usage: pm.py METHOD /api/... [key=value ...|JSON|-] [--key ID]  |  pm.py spec [경로 일부]"


def call(method, path, query=None, body=None, key=None):
    token = os.environ.get("SANDOL_PM_TOKEN")
    if not token:
        raise SystemExit("SANDOL_PM_TOKEN이 설정되어 있지 않습니다. /settings/tokens에서 발급한 토큰을 이 기기의 환경 변수로 넣어 주세요.")
    if not path.startswith("/api/"):
        raise SystemExit("경로는 /api/ 로 시작해야 합니다.")
    base = os.environ.get("SANDOL_PM_URL", "https://project.sio2.kr").rstrip("/")
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


def spec(needle=""):
    doc = call("GET", "/api/openapi.json")
    paths = {p: ops for p, ops in doc["paths"].items() if needle in p}
    if not needle:
        return [f"{m.upper()} {p}  {op.get('summary', '')}" for p, ops in paths.items() for m, op in ops.items()]
    # 찾은 경로의 요청·응답이 참조하는 스키마를 따라가 함께 돌려준다.
    schemas, todo = {}, [json.dumps(paths)]
    while todo:
        for ref in {s.split('"')[0] for s in todo.pop().split('"#/components/schemas/')[1:]}:
            if ref not in schemas:
                schemas[ref] = doc["components"]["schemas"][ref]
                todo.append(json.dumps(schemas[ref]))
    return {"paths": paths, "schemas": schemas}


def main(argv):
    for stream in (sys.stdin, sys.stdout):
        stream.reconfigure(encoding="utf-8")
    key = None
    if "--key" in argv:
        i = argv.index("--key")
        key = argv[i + 1] if i + 1 < len(argv) else None
        argv = argv[:i] + argv[i + 2:]
    if argv[:1] == ["spec"]:
        result = spec(argv[1] if len(argv) > 1 else "")
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
