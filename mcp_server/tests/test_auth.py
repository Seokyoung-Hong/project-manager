import json

import pytest

from mcp_server import auth as auth_mod
from mcp_server.auth import (
    NO_TOKEN_MSG,
    TokenMiddleware,
    current_token,
    extract_from_scope,
    require_token,
)
from mcp_server.server import security_settings

TOKEN = "pm_abcdefghijklmnopqrstuvwxyz"


def test_extract_from_path():
    token, path = extract_from_scope({"path": f"/u/{TOKEN}/mcp", "headers": []})
    assert token == TOKEN
    assert path == "/mcp"


def test_extract_from_header():
    token, path = extract_from_scope(
        {"path": "/mcp", "headers": [(b"authorization", f"Bearer {TOKEN}".encode())]}
    )
    assert token == TOKEN
    assert path == "/mcp"


def test_no_token():
    assert extract_from_scope({"path": "/mcp", "headers": []}) == (None, "/mcp")


def test_require_token_raises():
    tok = current_token.set(None)
    try:
        with pytest.raises(PermissionError):
            require_token()
    finally:
        current_token.reset(tok)


async def test_middleware_rewrites_path_and_sets_token():
    seen = {}

    async def inner(scope, receive, send):
        seen["path"] = scope["path"]
        seen["token"] = current_token.get()

    app = TokenMiddleware(inner)
    await app(
        {"type": "http", "path": f"/u/{TOKEN}/mcp", "headers": []},
        None,
        None,
    )
    assert seen["path"] == "/mcp"
    assert seen["token"] == TOKEN
    assert current_token.get() is None


async def _call(path, headers=()):
    """미들웨어를 한 번 돌리고 보낸 ASGI 메시지를 돌려준다."""
    sent = []

    async def inner(scope, receive, send):
        raise AssertionError("토큰 없이 통과했다")

    async def send(msg):
        sent.append(msg)

    await TokenMiddleware(inner)(
        {"type": "http", "path": path, "headers": list(headers)}, None, send
    )
    return sent


async def test_middleware_rejects_missing_token(monkeypatch):
    monkeypatch.setattr(auth_mod, "AUTH_SERVER_URL", "")
    sent = await _call("/mcp")
    assert sent[0]["status"] == 401
    assert dict(sent[0]["headers"])[b"www-authenticate"] == b'Bearer realm="udally"'
    assert sent[1]["body"].decode() == NO_TOKEN_MSG


async def test_401_points_at_the_metadata_when_oauth_is_on(monkeypatch):
    """resource_metadata가 없으면 클라이언트는 로그인 화면으로 갈 길을 못 찾는다."""
    monkeypatch.setattr(auth_mod, "AUTH_SERVER_URL", "https://project.example.test")
    sent = await _call("/mcp", [(b"host", b"mcp.example.test"), (b"x-forwarded-proto", b"https")])
    assert sent[0]["status"] == 401
    assert dict(sent[0]["headers"])[b"www-authenticate"] == (
        b'Bearer realm="udally", resource_metadata='
        b'"https://mcp.example.test/.well-known/oauth-protected-resource"'
    )


@pytest.mark.parametrize(
    "path",
    ["/.well-known/oauth-protected-resource", "/.well-known/oauth-protected-resource/mcp"],
)
async def test_protected_resource_metadata_needs_no_token(monkeypatch, path):
    monkeypatch.setattr(auth_mod, "AUTH_SERVER_URL", "https://project.example.test")
    sent = await _call(path, [(b"host", b"mcp.example.test"), (b"x-forwarded-proto", b"https")])
    assert sent[0]["status"] == 200
    body = json.loads(sent[1]["body"])
    assert body["resource"] == "https://mcp.example.test/mcp"
    assert body["authorization_servers"] == ["https://project.example.test"]


async def test_metadata_is_not_served_when_oauth_is_off(monkeypatch):
    """AUTH_SERVER_URL이 없으면 광고하지 않는다 — 빈 인가 서버 목록을 주면 더 헷갈린다."""
    monkeypatch.setattr(auth_mod, "AUTH_SERVER_URL", "")
    sent = await _call("/.well-known/oauth-protected-resource")
    assert sent[0]["status"] == 401


def test_security_settings_keeps_loopback_and_adds_proxy_host():
    s = security_settings(" mcp.example.com , 10.0.0.2:8081 ")
    assert "127.0.0.1:*" in s.allowed_hosts
    assert "mcp.example.com" in s.allowed_hosts and "10.0.0.2:8081" in s.allowed_hosts
    assert "https://mcp.example.com" in s.allowed_origins


def test_security_settings_empty_is_loopback_only():
    assert security_settings("").allowed_hosts == [
        "127.0.0.1",
        "127.0.0.1:*",
        "localhost",
        "localhost:*",
    ]
