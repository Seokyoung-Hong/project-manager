"""HTTP JSON access to the same registered tools as the MCP transport."""

import json

import httpx
from mcp.server.fastmcp.exceptions import ToolError

from .auth import require_token
from .core_client import CORE_URL
from .permissions import NEEDS
from .server import mcp

MAX_BODY = 1024 * 1024


async def _reply(send, status: int, data):
    body = json.dumps(data, ensure_ascii=False, default=str).encode("utf-8")
    await send({
        "type": "http.response.start",
        "status": status,
        "headers": [
            (b"content-type", b"application/json; charset=utf-8"),
            (b"cache-control", b"no-store"),
        ],
    })
    await send({"type": "http.response.body", "body": body})


async def _body(receive):
    chunks = bytearray()
    while True:
        message = await receive()
        if message["type"] != "http.request":
            raise ValueError("요청 본문을 읽을 수 없습니다.")
        chunks.extend(message.get("body", b""))
        if len(chunks) > MAX_BODY:
            raise ValueError("요청 본문이 너무 큽니다.")
        if not message.get("more_body", False):
            break
    try:
        data = json.loads(chunks)
    except (ValueError, UnicodeDecodeError) as exc:
        raise ValueError("JSON 본문이 필요합니다.") from exc
    if not isinstance(data, dict):
        raise ValueError("JSON 객체가 필요합니다.")
    return data


async def _profile():
    async with httpx.AsyncClient(base_url=CORE_URL, timeout=20) as client:
        response = await client.get(
            "/api/me", headers={"Authorization": f"Bearer {require_token()}"}
        )
    if response.status_code == 401:
        return None
    response.raise_for_status()
    return response.json()


def _allowed(name, profile):
    need = NEEDS.get(name)
    if need is None:
        return False
    if need == "read":
        return True
    if profile.get("token_scope") != "write":
        return False
    return need != "admin" or any(org.get("role") == "admin" for org in profile.get("orgs", []))


class ToolRelay:
    """Serve /mcp/relay/tools while passing MCP requests to FastMCP."""

    def __init__(self, mcp_app):
        self.mcp_app = mcp_app

    async def __call__(self, scope, receive, send):
        if scope["type"] != "http" or not scope.get("path", "").startswith("/mcp/relay/"):
            return await self.mcp_app(scope, receive, send)

        path = scope["path"]
        method = scope.get("method", "GET")
        if path == "/mcp/relay/tools" and method == "GET":
            name = None
        elif path.startswith("/mcp/relay/tools/") and method == "POST":
            name = path.removeprefix("/mcp/relay/tools/")
            if not name or "/" in name:
                return await _reply(send, 404, {"detail": "도구를 찾을 수 없습니다."})
        else:
            return await _reply(send, 404, {"detail": "경로를 찾을 수 없습니다."})

        try:
            profile = await _profile()
        except (httpx.HTTPError, ValueError):
            return await _reply(send, 502, {"detail": "인증 서버에 연결할 수 없습니다."})
        if profile is None:
            return await _reply(send, 401, {"detail": "토큰이 유효하지 않습니다."})

        if name is None:
            tools = await mcp.list_tools()
            return await _reply(send, 200, {
                "tools": [tool.model_dump(by_alias=True, exclude_none=True) for tool in tools
                          if _allowed(tool.name, profile)]
            })
        if name not in NEEDS:
            return await _reply(send, 404, {"detail": "도구를 찾을 수 없습니다."})
        if not _allowed(name, profile):
            return await _reply(send, 403, {"detail": "이 토큰으로는 이 도구를 사용할 수 없습니다."})
        try:
            arguments = await _body(receive)
        except ValueError as exc:
            return await _reply(send, 400, {"detail": str(exc)})
        try:
            result = await mcp._tool_manager.call_tool(name, arguments)
        except ToolError as exc:
            return await _reply(send, 422, {"detail": str(exc)})
        return await _reply(send, 200, {"result": result})
