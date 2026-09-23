"""팀·프로젝트 채널 생성. 흐름은 IMPL-PLAN-3 §7.

1. 인가(Discord 권한 → PM 관리자)   2. 중복 확인   3. 생성   4. core에 되적기   5. 답장
4가 실패하면 3을 되돌린다 — 채널만 생기고 연결이 없으면 다음 호출이 또 만들어 중복이 쌓인다.
core는 채널을 만들지 않는다. 봇이 만들고 결과 id만 적는다.
"""

import asyncio
import logging

import discord
import httpx

from .commands import _error_reply
from .core_client import CoreClient

log = logging.getLogger(__name__)

NO_PERMISSION = "봇에게 채널 관리 권한이 없습니다. 서버 설정에서 Manage Channels를 주세요."
NOT_A_MANAGER = "Discord 서버에서 채널 관리 권한이 있어야 합니다."
KIND = {
    "team": ("팀", "teams", "set_team_channel"),
    "project": ("프로젝트", "projects", "set_project_channel"),
}


def can_manage_channels(user) -> bool:
    """부른 사람 본인이 길드에서 Manage Channels를 가졌는가. 못 알아내면 False(fail closed).

    길드 인터랙션의 user는 역할이 실린 Member라 `guilds` 인텐트만으로 풀린다(멤버 인텐트 불필요).
    """
    try:
        return bool(user.guild_permissions.manage_channels)
    except AttributeError:
        return False


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
) -> str:
    # 가장 먼저, core를 부르기 전에 본다. 이 검사가 없으면 봇이 권한을 대신 빌려주는 꼴이 된다 —
    # Discord에서 채널을 못 만드는 PM 관리자가 봇을 통해 만들게 되고, 봇은 그 사람이 이미 가진
    # Discord 권한보다 더 주면 안 된다.
    if not can_manage_channels(user):
        return NOT_A_MANAGER
    label, list_method, set_method = KIND[kind]
    listing = getattr(core, list_method)
    save = getattr(core, set_method)
    try:
        item = next((i for i in await asyncio.to_thread(listing, uid) if i["id"] == item_id), None)
        if item is None:
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
                    category_name, reason=f"산돌이: {label} 채널"
                )
                category = created_category
            except discord.Forbidden:
                return "봇에게 카테고리 관리 권한이 없습니다."
            except discord.HTTPException as e:
                log.warning("카테고리 생성 실패: %s", e)
                return "카테고리를 만들지 못했습니다. 잠시 뒤 다시 시도해 주세요."

    try:
        channel = await guild.create_text_channel(
            item["name"], category=category, topic=f"{site_name} · {label} {item['name']}"
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

    try:
        await asyncio.to_thread(save, uid, item_id, str(channel.id))
    except Exception as e:  # noqa: BLE001
        log.warning("채널 되적기 실패, 되돌린다: %s", e)
        reply = _error_reply(e.response) if isinstance(e, httpx.HTTPStatusError) else None
        reply = reply or "연결을 저장하지 못했습니다."
        try:
            await channel.delete(reason="산돌이: 연결 저장 실패로 되돌림")
            if created_category and not created_category.channels:
                await created_category.delete(reason="연결 실패로 빈 카테고리 되돌림")
        except discord.HTTPException:
            return f"{reply} 만든 <#{channel.id}> 채널을 지우지도 못했습니다 — 직접 지워 주세요."
        return f"{reply} 만든 채널은 되돌렸습니다."

    return f"<#{channel.id}> 채널을 만들고 {item['name']} {label}에 연결했습니다."
