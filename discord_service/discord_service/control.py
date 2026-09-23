"""Private MCP bridge to the Discord gateway bot.

The MCP container has no Discord secret. This service uses the bot's gateway cache, but
requires and forwards the caller's ProjectManager bearer token for every read or write.
"""

import httpx
from aiohttp import web
import discord


def _token(request: web.Request) -> str:
    value = request.headers.get("Authorization", "")
    if not value.startswith("Bearer ") or not value[7:].strip():
        raise web.HTTPUnauthorized(text="ProjectManager bearer token이 필요합니다.")
    return value[7:].strip()


async def _org(request: web.Request, org_id: int, token: str) -> dict:
    core_url = request.app["core_url"]
    async with httpx.AsyncClient(base_url=core_url, timeout=10) as http:
        response = await http.get(f"/api/orgs/{org_id}", headers={"Authorization": f"Bearer {token}"})
    if response.status_code == 401:
        raise web.HTTPUnauthorized(text="ProjectManager 토큰이 유효하지 않습니다.")
    if response.status_code >= 400:
        raise web.HTTPForbidden(text="조직을 읽을 수 없습니다.")
    data = response.json()
    if data.get("role") != "admin":
        raise web.HTTPForbidden(text="Discord 채널 관리는 조직 관리자만 할 수 있습니다.")
    if not data.get("discord_guild_id"):
        raise web.HTTPConflict(text="이 조직은 Discord 서버에 연결되지 않았습니다.")
    return data


def _guild(request: web.Request, guild_id: str) -> discord.Guild:
    guild = request.app["client"].get_guild(int(guild_id))
    if guild is None:
        raise web.HTTPServiceUnavailable(text="연결된 Discord 서버가 봇 캐시에 없습니다.")
    return guild


def _project(org: dict, project_id: int) -> dict:
    project = next((p for p in org["projects"] if p["id"] == project_id), None)
    if project is None:
        raise web.HTTPNotFound(text="조직에서 프로젝트를 찾을 수 없습니다.")
    return project


async def list_channels(request: web.Request) -> web.Response:
    token = _token(request)
    org = await _org(request, int(request.match_info["org_id"]), token)
    guild = _guild(request, org["discord_guild_id"])
    channels = [
        {"id": str(c.id), "name": c.name, "category_id": str(c.category_id) if c.category_id else None,
         "category_name": c.category.name if c.category else None, "type": "text"}
        for c in guild.text_channels
    ]
    categories = [{"id": str(c.id), "name": c.name} for c in guild.categories]
    projects = [
        {"id": p["id"], "name": p["name"], "purpose": p.get("purpose", ""),
         "discord_channel_id": p.get("discord_channel_id") or ""}
        for p in org["projects"]
    ]
    by_name_all: dict[str, list[str]] = {}
    for channel in channels:
        by_name_all.setdefault(channel["name"], []).append(channel["id"])
    by_name: dict[str, str] = {}
    for name, ids in by_name_all.items():
        if len(ids) == 1:
            by_name[name] = ids[0]
            continue
        for channel in channels:
            if channel["id"] not in ids:
                continue
            label = f"{name} [{channel['category_name'] or '카테고리 없음'}]"
            if label in by_name:
                label = f"{label} #{channel['id']}"
            by_name[label] = channel["id"]
    return web.json_response({"guild_id": str(guild.id), "channels": channels,
                              "channels_by_name": by_name, "channels_by_name_all": by_name_all,
                              "categories": categories, "projects": projects})


async def assign_channel(request: web.Request) -> web.Response:
    token = _token(request)
    body = await request.json()
    org = await _org(request, int(body["org_id"]), token)
    project = _project(org, int(request.match_info["project_id"]))
    guild = _guild(request, org["discord_guild_id"])
    channel_id = str(body.get("channel_id", "")).strip()
    if channel_id:
        channel = guild.get_channel(int(channel_id))
        if not isinstance(channel, discord.TextChannel):
            raise web.HTTPBadRequest(text="연결할 텍스트 채널 ID가 이 Discord 서버에 없습니다.")
    async with httpx.AsyncClient(base_url=request.app["core_url"], timeout=10) as http:
        response = await http.put(
            f"/api/projects/{project['id']}/discord-channel",
            json={"channel_id": str(channel.id) if channel_id else ""},
            headers={"Authorization": f"Bearer {token}", "X-Source": "mcp"},
        )
    if response.status_code >= 400:
        raise web.HTTPBadRequest(text=response.text[:1000])
    return web.json_response(response.json())


async def create_project_channel(request: web.Request) -> web.Response:
    token = _token(request)
    body = await request.json()
    org = await _org(request, int(body["org_id"]), token)
    project = _project(org, int(request.match_info["project_id"]))
    guild = _guild(request, org["discord_guild_id"])
    name = str(body.get("channel_name", "")).strip()
    if not name or len(name) > 100:
        raise web.HTTPBadRequest(text="채널 이름은 1~100자여야 합니다.")
    category = None
    created_category = None
    category_id = body.get("category_id")
    new_category_name = str(body.get("new_category_name", "")).strip()
    if category_id and new_category_name:
        raise web.HTTPBadRequest(text="기존 카테고리 또는 새 카테고리 중 하나만 지정하세요.")
    if category_id:
        category = guild.get_channel(int(category_id))
        if not isinstance(category, discord.CategoryChannel):
            raise web.HTTPBadRequest(text="선택한 카테고리가 이 서버에 없습니다.")
    elif new_category_name:
        if len(new_category_name) > 100:
            raise web.HTTPBadRequest(text="카테고리 이름은 100자 이하여야 합니다.")
        category = discord.utils.get(guild.categories, name=new_category_name)
        if category is None:
            try:
                category = await guild.create_category(new_category_name, reason="ProjectManager 프로젝트 채널")
                created_category = category
            except discord.Forbidden:
                raise web.HTTPForbidden(text="봇에게 카테고리 생성 권한이 없습니다.") from None
    try:
        channel = await guild.create_text_channel(
            name, category=category, topic=f"ProjectManager · {project['name']}"
        )
    except discord.Forbidden:
        if created_category:
            await created_category.delete(reason="채널 생성 실패로 빈 카테고리 되돌림")
        raise web.HTTPForbidden(text="봇에게 텍스트 채널 생성 권한이 없습니다.") from None
    except discord.HTTPException as exc:
        if created_category:
            await created_category.delete(reason="채널 생성 실패로 빈 카테고리 되돌림")
        raise web.HTTPBadRequest(text=f"Discord가 채널 생성을 거부했습니다: {exc}") from None

    async with httpx.AsyncClient(base_url=request.app["core_url"], timeout=10) as http:
        response = await http.put(
            f"/api/projects/{project['id']}/discord-channel",
            json={"channel_id": str(channel.id)},
            headers={"Authorization": f"Bearer {token}", "X-Source": "mcp"},
        )
    if response.status_code >= 400:
        await channel.delete(reason="ProjectManager 연결 저장 실패로 되돌림")
        if created_category and not created_category.channels:
            await created_category.delete(reason="연결 실패로 빈 카테고리 되돌림")
        raise web.HTTPBadRequest(text=response.text[:1000])
    return web.json_response({**response.json(), "category_id": str(category.id) if category else None})


async def start_control_server(client: discord.Client, core_url: str, port: int) -> web.AppRunner:
    app = web.Application(client_max_size=16 * 1024)
    app["client"] = client
    app["core_url"] = core_url.rstrip("/")
    app.router.add_get("/orgs/{org_id}/channels", list_channels)
    app.router.add_post("/projects/{project_id}/assign", assign_channel)
    app.router.add_post("/orgs/{org_id}/projects/{project_id}/channels", create_project_channel)
    runner = web.AppRunner(app, access_log=None)

    await runner.setup()
    site = web.TCPSite(runner, "0.0.0.0", port)
    await site.start()
    return runner
