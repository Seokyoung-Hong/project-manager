"""팀·프로젝트 채널 생성. 흐름은 IMPL-PLAN-3 §7.

1. 인가(Discord 권한 → PM 관리자)   2. 중복 확인   3. 비공개로 생성   4. core에 되적기   5. 답장
4가 실패하면 3을 되돌린다 — 채널만 생기고 연결이 없으면 다음 호출이 또 만들어 중복이 쌓인다.
core는 채널을 만들지 않는다. 봇이 만들고 결과 id만 적는다.

기존 채널 연결은 `connect_existing`이 맡는다: 채널을 보는 사람을 core에 보내 권한 밖 인원을 확인받고,
있거나 확인할 수 없으면 `권한밖허용` 없이는 연결하지 않는다(IMPL-PLAN-5 B5).
"""

import asyncio
import logging

import discord
import httpx

from .commands import _error_reply
from .core_client import CoreClient
from .watch import GRANT, viewers_of

log = logging.getLogger(__name__)

NO_PERMISSION = "봇에게 채널 관리 권한이 없습니다. 서버 설정에서 Manage Channels를 주세요."
NOT_A_MANAGER = "Discord 서버에서 채널 관리 권한이 있어야 합니다."
NOT_A_ROLE_MANAGER = "비공개 채널 생성과 자동 관리에는 Discord 서버에서 역할 관리(Manage Roles) 권한도 있어야 합니다."
KIND = {
    "team": ("팀", "teams", "set_team_channel"),
    "project": ("프로젝트", "projects", "set_project_channel"),
}


SHOW_NAMES = 15


def outsiders_reply(res: dict) -> str:
    """연결을 거절한 이유와 다시 실행하는 방법. 비공개(ephemeral) 답이다."""
    if res.get("unknown"):
        return (
            "채널을 볼 수 있는 사람을 확인할 수 없습니다(서버 멤버 인텐트가 꺼져 있습니다). "
            "그래도 연결하려면 `권한밖허용:True`로 다시 실행해 주세요."
        )
    people = res["outsiders"]
    names = ", ".join(p["name"] or p["id"] for p in people[:SHOW_NAMES])
    more = f" 외 {len(people) - SHOW_NAMES}명" if len(people) > SHOW_NAMES else ""
    return (
        f"권한 밖 {len(people)}명이 이 채널을 볼 수 있습니다: {names}{more}\n"
        "이 인원을 허용하고 연결하려면 `권한밖허용:True`로 다시 실행해 주세요."
    )


async def private_overwrites(guild, grant_ids) -> dict:
    """@everyone은 보기 거부, 봇과 허용 집합의 연결 계정만 허용. 서버에 없는 사람은 건너뛴다."""
    ow = {guild.default_role: discord.PermissionOverwrite(view_channel=False)}
    ow[guild.me] = discord.PermissionOverwrite(**GRANT)
    for uid in grant_ids:
        member = guild.get_member(int(uid))
        if member is None:  # 멤버 인텐트가 꺼져 있으면 캐시에 없을 수 있다
            try:
                member = await guild.fetch_member(int(uid))
            except discord.HTTPException:
                continue
        if not member.bot:
            ow[member] = discord.PermissionOverwrite(**GRANT)
    return ow


def record_grants(store, guild, channel, overwrites: dict) -> None:
    """생성 때 넣은 멤버 덮어쓰기를 봇이 넣은 것으로 기록한다(허용 집합에서 빠지면 조정이 그것만 지운다)."""
    if store is None:
        return
    for target in overwrites:
        if target is not guild.default_role and target is not guild.me:
            store.add_grant(str(channel.id), str(target.id))


async def connect_existing(
    guild,
    user,
    core: CoreClient,
    uid: str,
    kind: str,
    item_id: int,
    channel,
    *,
    allow_outsiders: bool = False,
    managed: bool | None = None,
    members_intent: bool = False,
) -> str:
    """기존 채널을 연결한다. 권한 밖 인원이 있거나 확인 불가면 허용 옵션 없이는 거절한다."""
    if not can_manage_channels(user):
        return NOT_A_MANAGER
    if managed is not None and not can_manage(user, "managed"):  # 켜기·끄기 모두
        return NOT_A_ROLE_MANAGER
    if channel.guild.id != guild.id:
        return "현재 Discord 서버의 채널만 연결할 수 있습니다."
    label, list_method, _ = KIND[kind]
    try:
        item = next(
            (
                i
                for i in await asyncio.to_thread(getattr(core, list_method), uid)
                if i["id"] == item_id
            ),
            None,
        )
        if item is None or item.get("org_id") not in await guild_org_ids(core, guild.id):
            return f"{label}을(를) 찾을 수 없습니다."
        viewers = viewers_of(guild, channel) if members_intent else None
        res = await asyncio.to_thread(
            core.channel_check,
            uid,
            kind,
            item_id,
            str(channel.id),
            viewers,
            allow_outsiders,
            managed,
            False,
            str(guild.id),
        )
    except httpx.HTTPStatusError as e:
        return _error_reply(e.response)
    except httpx.HTTPError as e:
        log.warning("기존 채널 연결 실패: %s", e)
        return "채널을 연결하지 못했습니다. 잠시 뒤 다시 시도해 주세요."
    if not res["linked"]:
        return outsiders_reply(res)
    reply = f"<#{channel.id}> 채널을 {item['name']} {label}에 연결했습니다."
    if res["outsiders"]:
        reply += f" 권한 밖 {len(res['outsiders'])}명을 허용으로 기록했습니다."
    elif res["unknown"]:
        reply += " 채널을 보는 사람은 확인하지 못했습니다."
    return reply


# 기능별 필요 Discord 서버 권한. 슬래시는 interaction.user, MCP는 fetch_member로 조회한 멤버로 판정한다
# (웹은 core의 orgs.channels.NEEDS와 같은 기준을 봇 보고값으로 판정한다). 모르면 거절(fail closed).
NEEDS = {
    "channel": ("manage_channels",),  # 채널 연결·생성·해제, /알림채널
    "managed": (
        "manage_channels",
        "manage_roles",
    ),  # 자동 관리 켜기·끄기. 비공개 생성도 멤버 덮어쓰기라 같다
}


def can_manage(user, feature: str) -> bool:
    try:
        perms = user.guild_permissions
        return all(getattr(perms, name) for name in NEEDS[feature])
    except AttributeError:
        return False


def can_manage_roles(user) -> bool:
    """멤버 덮어쓰기를 넣는 일(비공개 생성·자동 관리)은 Manage Roles가 있어야 한다. 모르면 False."""
    try:
        return bool(user.guild_permissions.manage_roles)
    except AttributeError:
        return False


def can_manage_channels(user) -> bool:
    """부른 사람 본인이 길드에서 Manage Channels를 가졌는가. 못 알아내면 False(fail closed).

    길드 인터랙션의 user는 역할이 실린 Member라 `guilds` 인텐트만으로 풀린다(멤버 인텐트 불필요).
    """
    try:
        return bool(user.guild_permissions.manage_channels)
    except AttributeError:
        return False


async def guild_org_ids(core: CoreClient, guild_id) -> set:
    """이 길드에 묶인 조직 id. control.py·`/알림채널`과 같은 같은-길드 기준입니다."""
    orgs = await asyncio.to_thread(core.orgs)
    return {o["org_id"] for o in orgs if str(o.get("guild_id")) == str(guild_id)}


async def link_channel(
    guild,
    user,
    core: CoreClient,
    uid: str,
    kind: str,
    item_id: int,
    category_name,
    site_name: str,
    create_category: bool = False,
    store=None,
) -> str:
    # 가장 먼저, core를 부르기 전에 본다. 이 검사가 없으면 봇이 권한을 대신 빌려주는 꼴이 된다 —
    # Discord에서 채널을 못 만드는 PM 관리자가 봇을 통해 만들게 되고, 봇은 그 사람이 이미 가진
    # Discord 권한보다 더 주면 안 된다.
    if not can_manage_channels(user):
        return NOT_A_MANAGER
    if not can_manage_roles(user):  # 비공개 채널의 멤버 덮어쓰기는 Manage Roles가 필요하다
        return NOT_A_ROLE_MANAGER
    label, list_method, set_method = KIND[kind]
    listing = getattr(core, list_method)
    save = getattr(core, set_method)
    try:
        item = next((i for i in await asyncio.to_thread(listing, uid) if i["id"] == item_id), None)
        # 다른 길드에 묶인 조직의 것은 없는 것으로 다룹니다(조직 간 누출 방지).
        if item is None or item.get("org_id") not in await guild_org_ids(core, guild.id):
            return f"{label}을(를) 찾을 수 없습니다."
        # 인가 선확인: 같은 값을 다시 적는 무해한 쓰기다. 관리자가 아니면 여기서 400으로 끝나고
        # 채널은 아예 만들어지지 않는다(별도 '관리자인가' 엔드포인트를 두지 않는다).
        await asyncio.to_thread(save, uid, item_id, item["discord_channel_id"])
    except httpx.HTTPStatusError as e:
        return _error_reply(e.response)
    except httpx.HTTPError as e:
        log.warning("core 호출 실패: %s", e)
        return "지금은 처리할 수 없습니다. 잠시 뒤 다시 보내 주세요."

    existing = item["discord_channel_id"]
    if existing and guild.get_channel(int(existing)) is not None:
        return f"{item['name']} {label}에는 이미 <#{existing}> 채널이 연결되어 있습니다."
    # 없으면 Discord에서 지워진 것이다. 새로 만들고 덮어쓴다.

    category = None
    created_category = None
    if category_name:
        category = (
            category_name
            if isinstance(category_name, discord.CategoryChannel)
            else discord.utils.get(guild.categories, name=category_name)
        )
        if category is None:
            if not create_category:
                return f"'{category_name}' 카테고리를 찾을 수 없습니다. 기존 카테고리를 선택하거나 새 카테고리 만들기를 지정해 주세요."
            try:
                created_category = await guild.create_category(
                    category_name, reason=f"유달리: {label} 채널"
                )
                category = created_category
            except discord.Forbidden:
                return "봇에게 카테고리 관리 권한이 없습니다."
            except discord.HTTPException as e:
                log.warning("카테고리 생성 실패: %s", e)
                return "카테고리를 만들지 못했습니다. 잠시 뒤 다시 시도해 주세요."

    try:
        # 비공개로 만든다: 허용 집합(PM 데이터)의 Discord 연결 계정과 봇만 본다.
        targets = await asyncio.to_thread(core.channel_targets)
        mine = next((t for t in targets if t["kind"] == kind and t["id"] == item_id), None)
        overwrites = await private_overwrites(guild, mine["grant_ids"] if mine else [])
        channel = await guild.create_text_channel(
            item["name"],
            category=category,
            topic=f"{site_name} · {label} {item['name']}",
            overwrites=overwrites,
            reason=f"유달리: {label} 채널(비공개)",
        )
    except discord.Forbidden:
        if created_category:
            await created_category.delete(reason="채널 생성 실패로 빈 카테고리 되돌림")
        return NO_PERMISSION
    except discord.HTTPException as e:
        if created_category:
            await created_category.delete(reason="채널 생성 실패로 빈 카테고리 되돌림")
        log.warning("채널 생성 실패: %s", e)
        return "채널을 만들지 못했습니다. 잠시 뒤 다시 시도해 주세요."
    except httpx.HTTPError as e:  # 허용 집합을 core에서 못 읽었다. 공개로 만들 수는 없다
        if created_category:
            await created_category.delete(reason="채널 생성 실패로 빈 카테고리 되돌림")
        log.warning("허용 집합 조회 실패: %s", e)
        return "지금은 처리할 수 없습니다. 잠시 뒤 다시 보내 주세요."

    try:
        await asyncio.to_thread(
            core.channel_check,
            uid,
            kind,
            item_id,
            str(channel.id),
            None,
            False,
            True,
            True,
            str(guild.id),
        )
    except Exception as e:  # noqa: BLE001
        log.warning("채널 되적기 실패, 되돌린다: %s", e)
        reply = _error_reply(e.response) if isinstance(e, httpx.HTTPStatusError) else None
        reply = reply or "연결을 저장하지 못했습니다."
        try:
            await channel.delete(reason="유달리: 연결 저장 실패로 되돌림")
            if created_category and not created_category.channels:
                await created_category.delete(reason="연결 실패로 빈 카테고리 되돌림")
        except discord.HTTPException:
            return f"{reply} 만든 <#{channel.id}> 채널을 지우지도 못했습니다 — 직접 지워 주세요."
        return f"{reply} 만든 채널은 되돌렸습니다."

    record_grants(store, guild, channel, overwrites)
    return f"<#{channel.id}> 비공개 채널을 만들고 {item['name']} {label}에 연결했습니다."
