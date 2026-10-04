"""Private MCP bridge to the Discord gateway bot.

The MCP container has no Discord secret. This service uses the bot's gateway cache, but
requires and forwards the caller's ProjectManager bearer token for every read or write.
"""

import discord
import httpx
from aiohttp import web

from .channels import can_manage_channels, outsiders_reply, private_overwrites
from .watch import viewers_of


def _token(request: web.Request) -> str:
    value = request.headers.get("Authorization", "")
    if not value.startswith("Bearer ") or not value[7:].strip():
        raise web.HTTPUnauthorized(text="ProjectManager bearer token이 필요합니다.")
    return value[7:].strip()


def _http(request: web.Request) -> httpx.AsyncClient:
    return httpx.AsyncClient(
        base_url=request.app["core_url"], timeout=10, transport=request.app.get("transport")
    )


async def _org(request: web.Request, org_id: int, token: str) -> dict:
    async with _http(request) as http:
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


async def _manager(request: web.Request, guild: discord.Guild, token: str) -> str:
    """토큰 주인의 Discord 계정이 이 서버에서 Manage Channels를 가졌는지 본다. 모르면 거절한다(fail closed).

    이 검사가 없으면 PM 관리자이지만 Discord 권한은 없는 사람이 MCP(AI)를 통해 봇의 권한을 빌려 쓴다.
    캐시(`get_member`)는 쓰지 않는다 — 역할이 바뀐 직후의 오래된 값으로 통과시키지 않으려고 매번 조회한다.
    """
    async with _http(request) as http:
        response = await http.get("/api/me", headers={"Authorization": f"Bearer {token}"})
    did = response.json().get("discord_user_id") if response.status_code == 200 else None
    if not did:
        raise web.HTTPForbidden(text="Discord 계정을 연결한 사용자만 채널을 관리할 수 있습니다.")
    try:
        member = await guild.fetch_member(int(did))
    except (discord.HTTPException, ValueError):
        raise web.HTTPForbidden(text="Discord 서버에서 사용자의 권한을 확인할 수 없습니다.") from None
    if not can_manage_channels(member):
        raise web.HTTPForbidden(text="Discord 서버에서 채널 관리 권한이 있어야 합니다.")
    return str(did)


async def _bot_post(request: web.Request, path: str, body: dict) -> httpx.Response:
    """봇 토큰으로 core의 봇 전용 API를 부른다. 행위자는 body의 discord_user_id다."""
    if not request.app.get("core_token"):
        raise web.HTTPServiceUnavailable(text="봇에 CORE_TOKEN이 설정되지 않았습니다.")
    async with _http(request) as http:
        return await http.post(
            f"/api/integrations/discord{path}",
            json=body,
            headers={"Authorization": f"Bearer {request.app['core_token']}"},
        )


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
    did = await _manager(request, guild, token)
    channel_id = str(body.get("channel_id", "")).strip()
    if not channel_id:  # 연결 해제는 확인할 것이 없다
        async with _http(request) as http:
            response = await http.put(
                f"/api/projects/{project['id']}/discord-channel",
                json={"channel_id": ""},
                headers={"Authorization": f"Bearer {token}", "X-Source": "mcp"},
            )
        if response.status_code >= 400:
            raise web.HTTPBadRequest(text=response.text[:1000])
        return web.json_response(response.json())
    channel = guild.get_channel(int(channel_id))
    if not isinstance(channel, discord.TextChannel):
        raise web.HTTPBadRequest(text="연결할 텍스트 채널 ID가 이 Discord 서버에 없습니다.")
    # 권한 밖 인원 확인을 거쳐서만 연결한다. 확인할 수 없으면(viewers=None) 허용 옵션 없이는 거절한다.
    viewers = viewers_of(guild, channel) if request.app["members_intent"] else None
    response = await _bot_post(
        request,
        "/channel-check",
        {
            "discord_user_id": did,
            "kind": "project",
            "target_id": project["id"],
            "channel_id": str(channel.id),
            "viewers": viewers,
            "allow_outsiders": bool(body.get("allow_outsiders")),
            "managed": body.get("managed"),
        },
    )
    if response.status_code >= 400:
        raise web.HTTPBadRequest(text=response.text[:1000])
    result = response.json()
    if not result["linked"]:
        result["message"] = outsiders_reply(result).replace(
            "`권한밖허용:True`로 다시 실행해", "사용자에게 확인받은 뒤 allow_outsiders=true로 다시 호출해"
        )
    return web.json_response(
        {
            **result,
            "id": project["id"],
            "discord_channel_id": str(channel.id) if result["linked"] else "",
        }
    )


async def create_project_channel(request: web.Request) -> web.Response:
    token = _token(request)
    body = await request.json()
    org = await _org(request, int(body["org_id"]), token)
    project = _project(org, int(request.match_info["project_id"]))
    guild = _guild(request, org["discord_guild_id"])
    did = await _manager(request, guild, token)
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
        # 비공개로 만든다: 허용 집합(PM 데이터)의 Discord 연결 계정과 봇만 본다.
        async with _http(request) as http:
            listing = await http.get(
                "/api/integrations/discord/channels",
                headers={"Authorization": f"Bearer {request.app.get('core_token', '')}"},
            )
        listing.raise_for_status()
        mine = next(
            (t for t in listing.json() if t["kind"] == "project" and t["id"] == project["id"]), None
        )
        channel = await guild.create_text_channel(
            name,
            category=category,
            topic=f"ProjectManager · {project['name']}",
            overwrites=await private_overwrites(guild, mine["grant_ids"] if mine else []),
            reason="ProjectManager 프로젝트 채널(비공개)",
        )
    except httpx.HTTPError:
        if created_category:
            await created_category.delete(reason="채널 생성 실패로 빈 카테고리 되돌림")
        raise web.HTTPServiceUnavailable(
            text="허용 집합을 core에서 읽지 못해 비공개 채널을 만들 수 없습니다."
        ) from None
    except discord.Forbidden:
        if created_category:
            await created_category.delete(reason="채널 생성 실패로 빈 카테고리 되돌림")
        raise web.HTTPForbidden(text="봇에게 텍스트 채널 생성 권한이 없습니다.") from None
    except discord.HTTPException as exc:
        if created_category:
            await created_category.delete(reason="채널 생성 실패로 빈 카테고리 되돌림")
        raise web.HTTPBadRequest(text=f"Discord가 채널 생성을 거부했습니다: {exc}") from None

    response = await _bot_post(
        request,
        "/channel-check",
        {
            "discord_user_id": did,
            "kind": "project",
            "target_id": project["id"],
            "channel_id": str(channel.id),
            "created": True,
        },
    )
    if response.status_code >= 400:
        await channel.delete(reason="ProjectManager 연결 저장 실패로 되돌림")
        if created_category and not created_category.channels:
            await created_category.delete(reason="연결 실패로 빈 카테고리 되돌림")
        raise web.HTTPBadRequest(text=response.text[:1000])
    return web.json_response(
        {
            "id": project["id"],
            "name": project["name"],
            "discord_channel_id": str(channel.id),
            "linked": True,
            "private": True,
            "category_id": str(category.id) if category else None,
        }
    )


def make_app(
    client: discord.Client,
    core_url: str,
    *,
    core_token: str = "",
    members_intent: bool = False,
    transport=None,
) -> web.Application:
    app = web.Application(client_max_size=16 * 1024)
    app["client"] = client
    app["core_url"] = core_url.rstrip("/")
    app["core_token"] = core_token  # 연결 확인(봇 전용 API)에만 쓴다. 호출자 토큰과 섞지 않는다
    app["members_intent"] = members_intent
    app["transport"] = transport  # 테스트용
    app.router.add_get("/orgs/{org_id}/channels", list_channels)
    app.router.add_post("/projects/{project_id}/assign", assign_channel)
    app.router.add_post("/orgs/{org_id}/projects/{project_id}/channels", create_project_channel)
    return app


async def start_control_server(
    client: discord.Client,
    core_url: str,
    port: int,
    *,
    core_token: str = "",
    members_intent: bool = False,
) -> web.AppRunner:
    app = make_app(client, core_url, core_token=core_token, members_intent=members_intent)
    runner = web.AppRunner(app, access_log=None)

    await runner.setup()
    site = web.TCPSite(runner, "0.0.0.0", port)
    await site.start()
    return runner
