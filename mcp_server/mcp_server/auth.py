import json
import os
import re
from contextvars import ContextVar

current_token: ContextVar[str | None] = ContextVar("current_token", default=None)

_PATH_RE = re.compile(r"^/u/([A-Za-z0-9_\-]{20,})(/.*)?$")

# core(인가 서버)의 공개 주소. 비어 있으면 OAuth를 광고하지 않는다 — 클라이언트가 있지도
# 않은 메타데이터를 찾아 헤매는 것보다 "토큰을 넣으라"는 401 하나가 낫다.
AUTH_SERVER_URL = os.environ.get("AUTH_SERVER_URL", "").rstrip("/")
PRM_PATH = "/.well-known/oauth-protected-resource"


def extract_from_scope(scope) -> tuple[str | None, str]:
    """ASGI scope에서 (토큰, 새 경로)를 얻는다.
    1) /u/<token>/mcp 형태면 토큰을 꺼내고 경로를 /mcp 로 바꾼다.
    2) 아니면 Authorization: Bearer 헤더를 본다.
    """
    path = scope.get("path", "")
    m = _PATH_RE.match(path)
    if m:
        return m.group(1), m.group(2) or "/"
    headers = {k.decode().lower(): v.decode() for k, v in scope.get("headers", [])}
    auth = headers.get("authorization", "")
    if auth.lower().startswith("bearer "):
        return auth[7:].strip(), path
    return None, path


def public_base(scope) -> str:
    """이 서버의 공개 주소. 앞단 프록시가 TLS를 끝내므로 scope["scheme"]은 http다 —
    X-Forwarded-Proto를 먼저 본다. Host는 프록시가 원래 도메인 그대로 넘긴다."""
    headers = {k.decode().lower(): v.decode() for k, v in scope.get("headers", [])}
    proto = headers.get("x-forwarded-proto", scope.get("scheme", "http")).split(",")[0].strip()
    return f"{proto}://{headers.get('host', '')}"


NO_TOKEN_MSG = (
    "인증 토큰이 없습니다. 유달리 설정 → API 토큰에서 발급한 개인 비밀 URL"
    "(.../u/<TOKEN>/mcp)로 연결하거나 Authorization: Bearer <TOKEN> 헤더를 보내세요."
)
OAUTH_MSG = "인증이 필요합니다. 클라이언트가 OAuth를 지원하면 '연결'을 눌러 로그인하세요."


async def _json(send, body: dict, status: int = 200):
    raw = json.dumps(body, ensure_ascii=False).encode()
    await send(
        {
            "type": "http.response.start",
            "status": status,
            "headers": [(b"content-type", b"application/json; charset=utf-8")],
        }
    )
    await send({"type": "http.response.body", "body": raw})


async def _unauthorized(send, scope):
    challenge = 'Bearer realm="udally"'
    if AUTH_SERVER_URL:
        # RFC 9728. 이 한 줄이 클라이언트를 로그인 화면으로 보낸다.
        challenge += f', resource_metadata="{public_base(scope)}{PRM_PATH}"'
    body = (OAUTH_MSG if AUTH_SERVER_URL else NO_TOKEN_MSG).encode()
    await send(
        {
            "type": "http.response.start",
            "status": 401,
            "headers": [
                (b"content-type", b"text/plain; charset=utf-8"),
                (b"www-authenticate", challenge.encode()),
            ],
        }
    )
    await send({"type": "http.response.body", "body": body})


class TokenMiddleware:
    """토큰을 contextvar에 넣고, /u/<token>/... 경로를 /... 로 바꿔 넘긴다.
    토큰이 없으면 여기서 401로 끊는다. 보호 자원 메타데이터만 토큰 없이 답한다."""

    def __init__(self, app):
        self.app = app

    async def __call__(self, scope, receive, send):
        if scope["type"] != "http":
            return await self.app(scope, receive, send)
        # 클라이언트는 /mcp 뒤를 붙여 묻기도 한다(.../oauth-protected-resource/mcp).
        if AUTH_SERVER_URL and scope.get("path", "").startswith(PRM_PATH):
            base = public_base(scope)
            return await _json(
                send,
                {
                    "resource": f"{base}/mcp",
                    "authorization_servers": [AUTH_SERVER_URL],
                    "bearer_methods_supported": ["header"],
                    "scopes_supported": ["read", "write"],
                },
            )
        token, new_path = extract_from_scope(scope)
        if not token:
            # 그냥 통과시키면 initialize·tools/list는 성공하고 호출만 전부 거부된다 —
            # 커넥터에는 "연결됨"으로 보이는데 아무것도 못 한다. 붙는 순간 실패시켜야
            # 클라이언트가 OAuth를 시작하거나 사람이 URL을 고친다.
            return await _unauthorized(send, scope)
        # 원래 경로(/u/<TOKEN>/mcp)는 접근 로그에 남으면 토큰 유출이라 __main__에서 access_log=False로 끕니다.
        scope = dict(scope)
        scope["path"] = new_path
        scope["raw_path"] = new_path.encode()
        reset = current_token.set(token)
        try:
            return await self.app(scope, receive, send)
        finally:
            current_token.reset(reset)


def require_token() -> str:
    t = current_token.get()
    if not t:
        raise PermissionError(NO_TOKEN_MSG)
    return t
