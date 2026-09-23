"""슬래시 명령 정의·자동완성·응답.

`import discord`는 절대 임포트다(site-packages). 판단은 전부 core가 한다 — 여기는
commands.py의 문구와 CoreClient를 재사용하고, 파싱만 Discord에 맡긴다.

지켜야 하는 것 셋:
1. CoreClient는 동기 httpx다. 반드시 `asyncio.to_thread`로 감싼다(하트비트가 굶는다).
2. 인터랙션은 3초 안에 응답해야 한다. 핸들러는 먼저 `defer(ephemeral=True)`, 끝나면 followup.
3. 자동완성은 defer할 수 없다. 30초 TTL 캐시로 core 호출을 타자마다가 아니라 30초에 한 번으로 줄인다.

답장은 전부 ephemeral이다. 길드 채널은 공유 공간이고 `/오늘`의 결과는 그 사람의 업무 목록이다.
"""

import asyncio
import logging
import time

import discord
import httpx
from discord import app_commands
from discord.app_commands import Choice

from .channels import NOT_A_MANAGER, can_manage_channels, link_channel
from .commands import (
    BAD_DATE,
    TOO_FAST,
    create_reply,
    done_reply,
    extend_reply,
    guarded,
    link_reply,
    note_reply,
    parse_date,
    set_org_channel_reply,
    status_reply,
    today_reply,
    too_fast,
    unlink_reply,
    update_reply,
)
from .core_client import CoreClient
from .discord import chunk
from .messages import SLASH_HELP, STATUS

log = logging.getLogger(__name__)

CACHE_TTL = 30
AUTOCOMPLETE_TIMEOUT = 2.5  # 3초 안에 반환해야 한다. 넘기면 빈 목록(fail closed)
MAX_CHOICES = 25  # Discord 상한. 상위 25개만 주고 더 입력하면 필터가 좁혀진다
NO_MENTION = discord.AllowedMentions.none()
STATUS_CHOICES = [Choice(name=label, value=code) for code, label in STATUS.items()]
NOT_CONNECTED = "이 서버는 아직 조직에 연결되지 않았습니다."

# 자동완성 캐시. (discord_user_id, 종류) → (만료 시각, 목록). 미연결·비멤버도 빈 목록으로
# 캐시해 타자마다 404를 받으러 가지 않는다.
# ponytail: 프로세스 메모리 dict, 봇이 여러 대가 되면 각자 캐시를 갖는다(문제 없음).
Cache = dict[tuple[str, str], tuple[float, list[dict]]]


async def cached(core: CoreClient, cache: Cache, uid: str, kind: str) -> list[dict]:
    """kind = projects | teams | members | mytasks. 실패는 전부 빈 목록 — 오류를 목록에 넣지 않는다."""
    now = time.monotonic()
    hit = cache.get((uid, kind))
    if hit and hit[0] > now:
        return hit[1]
    try:
        items = await asyncio.wait_for(
            asyncio.to_thread(getattr(core, kind), uid), timeout=AUTOCOMPLETE_TIMEOUT
        )
    except httpx.HTTPStatusError:
        items = []  # 미연결(404)·비멤버. 같은 사람이 계속 타자해도 30초에 한 번만 묻는다
    except Exception as e:  # noqa: BLE001
        log.warning("자동완성 조회 실패(%s): %s", kind, e)
        return []  # 일시 장애는 캐시하지 않는다
    cache[(uid, kind)] = (now + CACHE_TTL, items)
    return items


def choices(items: list[dict], current: str, label) -> list[Choice[int]]:
    """부분 일치(대소문자 무시)로 걸러 상위 25개. 사람은 label을 보고 봇은 id를 받는다."""
    q = (current or "").strip().lower()
    out = []
    for i in items:
        name = label(i)
        if q in name.lower():
            out.append(Choice(name=name[:100], value=i["id"]))
        if len(out) == MAX_CHOICES:
            break
    return out


def task_label(t: dict) -> str:
    return f"{t['number']} {t['title']}"


# --- 문자열 인자를 검사한 뒤 commands.py의 문구로 넘기는 얇은 함수들 (스레드에서 돈다) ---


def _extend(core, uid, number, due, reason):
    d = parse_date(due)
    return BAD_DATE if d is None else extend_reply(core, uid, number, d, reason)


def _create(core, uid, project, title, due, no_due_reason, priority, assignee):
    fields = {"project_id": project, "title": title}
    if due is not None:
        d = parse_date(due)
        if d is None:
            return BAD_DATE
        fields["due_date"] = d.isoformat()
    if no_due_reason is not None:
        fields["no_due_reason"] = no_due_reason
    if priority is not None:
        fields["priority"] = priority
    if assignee is not None:
        fields["assignee_id"] = assignee
    return create_reply(core, uid, fields)


def _update(core, uid, number, title, due, priority, assignee, next_action):
    changes = {}
    if title is not None:
        changes["title"] = title
    if due is not None:
        d = parse_date(due)
        if d is None:
            return BAD_DATE
        changes["due_date"] = d.isoformat()
    if priority is not None:
        changes["priority"] = priority
    if assignee is not None:
        changes["assignee_id"] = assignee
    if next_action is not None:
        changes["next_action"] = next_action
    return update_reply(core, uid, number, changes)


def register(tree: app_commands.CommandTree, guild, cfg, core: CoreClient, seen: dict):
    """명령을 길드 범위로 등록한다. 동기화(tree.sync)는 listener의 setup_hook이 한다."""
    cache: Cache = {}

    async def send(interaction: discord.Interaction, reply: str):
        for part in chunk(reply):
            await interaction.followup.send(part, ephemeral=True, allowed_mentions=NO_MENTION)

    async def respond(interaction: discord.Interaction, fn, *args):
        await interaction.response.defer(ephemeral=True)
        uid = str(interaction.user.id)
        if too_fast(seen, uid, time.monotonic()):
            reply = TOO_FAST
        else:
            reply = await asyncio.to_thread(guarded, fn, core, uid, *args)
        await send(interaction, reply)

    # --- 자동완성. 인가는 core가 한다(같은 discord_user_id 경로). 실패는 빈 목록 ---

    async def ac_task(interaction: discord.Interaction, current: str):
        items = await cached(core, cache, str(interaction.user.id), "mytasks")
        return choices(items, current, task_label)

    async def ac_project(interaction: discord.Interaction, current: str):
        items = await cached(core, cache, str(interaction.user.id), "projects")
        return choices(items, current, lambda p: p["name"])

    async def ac_team(interaction: discord.Interaction, current: str):
        items = await cached(core, cache, str(interaction.user.id), "teams")
        return choices(items, current, lambda t: t["name"])

    async def ac_member(interaction: discord.Interaction, current: str):
        items = await cached(core, cache, str(interaction.user.id), "members")
        return choices(items, current, lambda m: m["display_name"])

    # --- A단계: 기존 DM 명령의 이식 ---

    @tree.command(name="오늘", description="오늘 할 일 (나에게만 보입니다)", guild=guild)
    async def today(interaction: discord.Interaction):
        await respond(interaction, today_reply)

    @tree.command(name="완료", description="태스크를 완료로 바꿉니다", guild=guild)
    @app_commands.rename(number="번호")
    @app_commands.describe(number="태스크 (입력하면 내 미완료 목록이 뜹니다)")
    @app_commands.autocomplete(number=ac_task)
    async def done(interaction: discord.Interaction, number: int):
        await respond(interaction, done_reply, number)

    @tree.command(name="연장", description="목표일을 미루고 사유를 남깁니다", guild=guild)
    @app_commands.rename(number="번호", due="기한", reason="사유")
    @app_commands.describe(number="태스크", due="새 목표일 YYYY-MM-DD", reason="연장 사유")
    @app_commands.autocomplete(number=ac_task)
    async def extend(interaction: discord.Interaction, number: int, due: str, reason: str):
        await respond(interaction, _extend, number, due, reason)

    @tree.command(name="연결", description="웹에서 받은 코드로 계정을 연결합니다", guild=guild)
    @app_commands.rename(code="코드")
    @app_commands.describe(code="웹 설정 → 프로필 → [Discord 연결]에서 받은 코드")
    async def link(interaction: discord.Interaction, code: str):
        await respond(interaction, link_reply, code)

    @tree.command(name="연결해제", description="연결을 끊습니다 (DM 알림도 멈춥니다)", guild=guild)
    async def unlink(interaction: discord.Interaction):
        await respond(interaction, unlink_reply)

    @tree.command(name="도움", description="쓸 수 있는 명령", guild=guild)
    async def help_(interaction: discord.Interaction):
        await interaction.response.send_message(SLASH_HELP, ephemeral=True)

    # --- B단계: 태스크 생성·편집 ---

    @tree.command(name="태스크만들기", description="태스크를 만듭니다", guild=guild)
    @app_commands.rename(
        project="프로젝트",
        title="제목",
        due="기한",
        no_due_reason="기한미정사유",
        priority="중요도",
        assignee="담당자",
    )
    @app_commands.describe(
        project="프로젝트 (입력하면 목록이 뜹니다)",
        title="제목",
        due="YYYY-MM-DD (없으면 기한미정사유가 필요합니다)",
        no_due_reason="기한을 아직 못 정한 이유",
        priority="1~10 (기본 5)",
        assignee="담당자 (생략하면 나)",
    )
    @app_commands.autocomplete(project=ac_project, assignee=ac_member)
    async def create(
        interaction: discord.Interaction,
        project: int,
        title: str,
        due: str | None = None,
        no_due_reason: str | None = None,
        priority: app_commands.Range[int, 1, 10] | None = None,
        assignee: int | None = None,
    ):
        await respond(interaction, _create, project, title, due, no_due_reason, priority, assignee)

    @tree.command(name="태스크수정", description="제목·기한·중요도·담당자·다음 행동", guild=guild)
    @app_commands.rename(
        number="번호",
        title="제목",
        due="기한",
        priority="중요도",
        assignee="담당자",
        next_action="다음행동",
    )
    @app_commands.describe(number="태스크", due="YYYY-MM-DD", priority="1~10")
    @app_commands.autocomplete(number=ac_task, assignee=ac_member)
    async def update(
        interaction: discord.Interaction,
        number: int,
        title: str | None = None,
        due: str | None = None,
        priority: app_commands.Range[int, 1, 10] | None = None,
        assignee: int | None = None,
        next_action: str | None = None,
    ):
        await respond(interaction, _update, number, title, due, priority, assignee, next_action)

    @tree.command(name="메모", description="진행 메모에 한 줄 덧붙입니다", guild=guild)
    @app_commands.rename(number="번호", text="내용")
    @app_commands.autocomplete(number=ac_task)
    async def note(interaction: discord.Interaction, number: int, text: str):
        await respond(interaction, note_reply, number, text)

    @tree.command(name="상태", description="태스크 상태를 바꿉니다", guild=guild)
    @app_commands.rename(number="번호", status="상태", reason="사유")
    @app_commands.describe(reason="막힘은 필수, 일시정지·재개는 선택")
    @app_commands.choices(status=STATUS_CHOICES)
    @app_commands.autocomplete(number=ac_task)
    async def status(
        interaction: discord.Interaction, number: int, status: Choice[str], reason: str = ""
    ):
        await respond(interaction, status_reply, number, status.value, reason)

    # --- C단계: 채널 생성 (조직 관리자) ---

    async def channel_cmd(
        interaction: discord.Interaction, kind: str, item_id: int, category,
        create_category: bool = False, selected: discord.TextChannel | None = None,
    ):
        await interaction.response.defer(ephemeral=True)
        uid = str(interaction.user.id)
        if too_fast(seen, uid, time.monotonic()):
            reply = TOO_FAST
        elif interaction.guild is None:
            reply = "서버 채널에서 실행해 주세요."
        elif selected is not None:
            if not can_manage_channels(interaction.user):
                reply = NOT_A_MANAGER
            elif selected.guild.id != interaction.guild.id:
                reply = "현재 Discord 서버의 채널만 연결할 수 있습니다."
            elif kind != "project":
                reply = "기존 채널 선택은 프로젝트 채널에만 지원합니다."
            else:
                try:
                    projects = await asyncio.to_thread(core.projects, uid)
                    project = next((p for p in projects if p["id"] == item_id), None)
                    if project is None:
                        reply = "프로젝트를 찾을 수 없습니다."
                    else:
                        await asyncio.to_thread(core.set_project_channel, uid, item_id, str(selected.id))
                        reply = f"<#{selected.id}> 채널을 {project['name']} 프로젝트에 연결했습니다."
                except httpx.HTTPStatusError as e:
                    reply = _error_reply(e.response)
                except httpx.HTTPError as e:
                    log.warning("기존 채널 연결 실패: %s", e)
                    reply = "채널을 연결하지 못했습니다. 잠시 뒤 다시 시도해 주세요."
        else:
            reply = await link_channel(
                interaction.guild,
                interaction.user,
                core,
                uid,
                kind,
                item_id,
                category,
                cfg.site_name,
                create_category,
            )
        await send(interaction, reply)

    @tree.command(
        name="팀채널", description="팀 채널을 만들고 연결합니다 (조직 관리자)", guild=guild
    )
    @app_commands.guild_only()
    @app_commands.rename(team="팀", category="기존카테고리")
    @app_commands.describe(team="팀 (입력하면 목록이 뜹니다)", category="넣을 기존 카테고리")
    @app_commands.autocomplete(team=ac_team)
    async def team_channel(
        interaction: discord.Interaction, team: int, category: discord.CategoryChannel | None = None,
        create_category: bool = False,
    ):
        await channel_cmd(interaction, "team", team, category, create_category)

    @tree.command(
        name="프로젝트채널",
        description="프로젝트 채널을 만들고 연결합니다 (조직 관리자)",
        guild=guild,
    )
    @app_commands.guild_only()
    @app_commands.rename(project="프로젝트", category="기존카테고리", create_category="새카테고리만들기", selected="기존채널")
    @app_commands.describe(
        project="프로젝트 (입력하면 목록이 뜹니다)", category="넣을 기존 카테고리",
        create_category="카테고리가 없을 때 같은 이름으로 새 카테고리를 만듭니다",
        selected="기존 텍스트 채널을 선택하면 새 채널 대신 연결합니다",
    )
    @app_commands.autocomplete(project=ac_project)
    async def project_channel(
        interaction: discord.Interaction, project: int, category: discord.CategoryChannel | None = None,
        create_category: bool = False, selected: discord.TextChannel | None = None,
    ):
        await channel_cmd(interaction, "project", project, category, create_category, selected)

    # --- §8.4: 조직 알림 채널 지정 ---

    @tree.command(
        name="알림채널",
        description="이 채널을 이 서버 조직의 알림 채널로 지정합니다 (PM 조직 관리자)",
        guild=guild,
    )
    @app_commands.guild_only()
    async def alert_channel(interaction: discord.Interaction):
        await interaction.response.defer(ephemeral=True)
        uid = str(interaction.user.id)
        if too_fast(seen, uid, time.monotonic()):
            reply = TOO_FAST
        elif interaction.guild is None:
            reply = "서버 채널에서 실행해 주세요."
        elif not can_manage_channels(interaction.user):
            reply = NOT_A_MANAGER
        else:
            # 등록 자체가 바인딩된 길드로 좁혀 있지만(listener.run), 기동 뒤 바인딩이 풀렸을
            # 수도 있으니 부르는 시점에 한 번 더 본다 — 값싸고(캐시 없이 한 번) 정직하다.
            try:
                orgs = await asyncio.to_thread(core.orgs)
            except httpx.HTTPError:
                orgs = []
            if not any(str(o.get("guild_id")) == str(interaction.guild.id) for o in orgs):
                reply = NOT_CONNECTED
            else:
                reply = await asyncio.to_thread(
                    guarded,
                    set_org_channel_reply,
                    core,
                    uid,
                    str(interaction.guild.id),
                    str(interaction.channel.id),
                )
        await send(interaction, reply)

    return cache
