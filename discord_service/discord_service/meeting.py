"""회의 명령(`/회의시작`·`/회의종료`·`/회의진행자`·`/회의받기`)과 넘겨받기 버튼. IMPL-PLAN-9-parallel §4.

음성은 별도 Node 서비스(discord-voice, 내부 HTTP 8082)가 맡는다. 여기는 명령·버튼 UI와 core·Node
호출뿐이다. 계정 연결 확인은 기존 명령처럼 core가 한다(미연결이면 core의 404 문구를 그대로 보인다).
"""

import asyncio
import logging
import time

import discord
import httpx
from discord import app_commands

from .commands import BUSY, TOO_FAST, _detail, _error_reply, too_fast
from .messages import (
    MEETING_HOST_REJECTED,
    MEETING_HOST_REQUESTED,
    MEETING_NONE,
    MEETING_NOT_CONFIGURED,
    MEETING_POST_FAILED,
    MEETING_STARTED,
    MEETING_STOPPED,
    MEETING_VOICE_DOWN,
    MEETING_VOICE_MISCONFIGURED,
)

log = logging.getLogger(__name__)

HOST_BUTTON = "meeting-host:"  # custom_id = meeting-host:{recording_id}:{request_id}:{1|0}
START_TIMEOUT = (
    50  # Node가 core 호출 + Ready 대기(30초)까지 마치고 답한다 — defer 뒤라 3초 규칙과 무관
)
TIMEOUT = 10
NO_MENTION = discord.AllowedMentions.none()
USER_MENTION = discord.AllowedMentions(users=True, roles=False, everyone=False)


class Voice:
    """Node 음성 서비스 호출. 요청마다 클라이언트를 연다(드물게 부르고 수명 관리가 필요 없다)."""

    def __init__(self, url: str, secret: str, transport=None):
        self.url, self.secret, self.transport = url, secret, transport

    @property
    def ready(self) -> bool:
        return bool(self.url and self.secret)

    async def call(self, method: str, path: str, body=None, timeout=TIMEOUT) -> httpx.Response:
        async with httpx.AsyncClient(
            base_url=self.url,
            headers={"Authorization": f"Bearer {self.secret}"},
            timeout=timeout,
            transport=self.transport,
        ) as c:
            return await c.request(method, path, json=body)


def voice_from(cfg) -> Voice:
    return Voice(getattr(cfg, "voice_url", ""), getattr(cfg, "voice_secret", ""))


class Refused(Exception):
    """사용자에게 그대로 보일 거절 문구."""


async def node(voice: Voice, method: str, path: str, body=None, timeout=TIMEOUT) -> dict:
    try:
        r = await voice.call(method, path, body, timeout)
    except httpx.HTTPError as e:
        log.warning("음성 서비스 호출 실패 %s %s: %s", method, path, e)
        raise Refused(MEETING_VOICE_DOWN) from e
    if r.is_success:
        return r.json()
    if r.status_code == 401:  # VOICE_CONTROL_SECRET이 양쪽에서 다르다. Node 문장은 운영자용이다
        log.error(
            "음성 서비스가 인증을 거절했습니다(VOICE_CONTROL_SECRET 확인): %s %s", method, path
        )
        raise Refused(MEETING_VOICE_MISCONFIGURED)
    # Node 오류는 항상 {detail: 문장}(400·404·409·502, core의 403·400·404 전달)이다
    raise Refused(_detail(r) or _error_reply(r))


async def core_call(fn, *args) -> dict:
    """회의 거절은 403도 detail에 이유가 있다(예: 지금 진행자만…). 그래서 detail을 먼저 보인다."""
    try:
        return await asyncio.to_thread(fn, *args)
    except httpx.HTTPStatusError as e:
        raise Refused(_detail(e.response) or _error_reply(e.response)) from e
    except httpx.HTTPError as e:
        log.warning("core 호출 실패: %s", e)
        raise Refused(BUSY) from e


async def current(voice: Voice, guild_id) -> dict:
    meeting = (await node(voice, "GET", f"/guilds/{guild_id}/meeting")).get("meeting")
    if not meeting:
        raise Refused(MEETING_NONE)
    return meeting


async def post(client, channel_id, text: str, mentions=NO_MENTION, view=None):
    """음성 채널의 텍스트 채팅에 올린다. 실패(discord.HTTPException)는 부른 쪽이 정한다."""
    cid = int(channel_id)
    ch = client.get_channel(cid) or await client.fetch_channel(cid)
    kw = {"view": view} if view is not None else {}
    await ch.send(text, allowed_mentions=mentions, **kw)


async def tell_host(voice: Voice, recording_id, discord_user_id: str):
    """새 진행자를 Node에 알린다(진행자 퇴장 감시 대상). 실패해도 core의 넘김은 이미 끝났다."""
    if not voice.ready:
        return
    try:
        await node(
            voice, "POST", f"/meetings/{recording_id}/host", {"discord_user_id": discord_user_id}
        )
    except Refused as e:
        log.warning("음성 서비스에 진행자 변경을 못 알렸습니다(recording=%s): %s", recording_id, e)


async def reply(interaction, text: str):
    await interaction.followup.send(text, ephemeral=True, allowed_mentions=NO_MENTION)


def register(tree, guild, core, seen: dict, voice: Voice, ac_project, ac_team):
    async def run(interaction: discord.Interaction, body):
        await interaction.response.defer(ephemeral=True)
        uid = str(interaction.user.id)
        if too_fast(seen, uid, time.monotonic()):
            text = TOO_FAST
        elif not voice.ready:
            text = MEETING_NOT_CONFIGURED
        else:
            try:
                text = await body(uid, str(interaction.guild_id))
            except Refused as e:
                text = str(e)
        await reply(interaction, text)

    @tree.command(
        name="회의시작", description="지금 있는 음성 채널에서 회의를 시작합니다", guild=guild
    )
    @app_commands.guild_only()
    @app_commands.rename(project="프로젝트", team="팀", title="제목")
    @app_commands.describe(project="회의록을 둘 프로젝트 (선택)", team="회의록을 둘 팀 (선택)")
    @app_commands.autocomplete(project=ac_project, team=ac_team)
    async def start(
        interaction: discord.Interaction,
        project: int | None = None,
        team: int | None = None,
        title: str = "",
    ):
        async def body(uid, gid):
            payload = {
                "guild_id": gid,
                "discord_user_id": uid,
                "project_id": project,
                "team_id": team,
                "title": title,
            }
            await node(voice, "POST", "/meetings", payload, START_TIMEOUT)
            return MEETING_STARTED

        await run(interaction, body)

    @tree.command(name="회의종료", description="진행 중인 회의를 종료합니다", guild=guild)
    @app_commands.guild_only()
    async def stop(interaction: discord.Interaction):
        async def body(uid, gid):
            m = await current(voice, gid)
            await node(
                voice, "POST", f"/meetings/{m['recording_id']}/stop", {"discord_user_id": uid}
            )
            return MEETING_STOPPED

        await run(interaction, body)

    @tree.command(
        name="회의진행자", description="회의 진행자를 다른 참여자에게 넘깁니다", guild=guild
    )
    @app_commands.guild_only()
    @app_commands.rename(target="참여자")
    @app_commands.describe(target="같은 음성 채널에 있는 참여자")
    async def host(interaction: discord.Interaction, target: discord.Member):
        async def body(uid, gid):
            m = await current(voice, gid)
            rid, to = m["recording_id"], str(target.id)
            out = await core_call(core.meeting_host, uid, rid, to, m.get("participants"))
            notice = out["channel_notice"]
            try:
                await post(interaction.client, m["voice_channel_id"], notice)
            except (discord.HTTPException, ValueError) as e:
                log.warning("진행자 변경 고지 실패: %s", e)
            await tell_host(voice, rid, to)
            return notice

        await run(interaction, body)

    @tree.command(
        name="회의받기", description="회의 진행자에게 넘겨받기 요청을 보냅니다", guild=guild
    )
    @app_commands.guild_only()
    async def take(interaction: discord.Interaction):
        async def body(uid, gid):
            m = await current(voice, gid)
            rid = m["recording_id"]
            out = await core_call(core.meeting_host_request, uid, rid, m.get("participants"))
            texts, req_id = out["texts"], out["request"]["id"]
            view = discord.ui.View(timeout=None)
            for flag, label, style in (
                (1, texts["approve_label"], discord.ButtonStyle.success),
                (0, texts["reject_label"], discord.ButtonStyle.secondary),
            ):
                cid = f"{HOST_BUTTON}{rid}:{req_id}:{flag}"
                view.add_item(discord.ui.Button(label=label, style=style, custom_id=cid))
            try:
                await post(
                    interaction.client, m["voice_channel_id"], texts["mention"], USER_MENTION, view
                )
            except (discord.HTTPException, ValueError) as e:
                log.warning("넘겨받기 요청 게시 실패: %s", e)
                raise Refused(MEETING_POST_FAILED) from e
            finally:
                view.stop()  # 클릭은 on_interaction이 받는다(재시작 뒤에도 같은 길)
            return MEETING_HOST_REQUESTED

        await run(interaction, body)


def is_host_button(interaction) -> bool:
    data = getattr(interaction, "data", None) or {}
    return interaction.type == discord.InteractionType.component and str(
        data.get("custom_id", "")
    ).startswith(HOST_BUTTON)


async def on_host_button(interaction, core, voice: Voice):
    """[승인]·[거절]. 답은 전부 누른 사람에게만(ephemeral) — 403(진행자 아님)도 그렇다."""
    try:
        _, rid, req_id, flag = interaction.data["custom_id"].split(":")
        rid, req_id, approve = int(rid), int(req_id), flag == "1"
    except (KeyError, ValueError):
        return
    await interaction.response.defer(ephemeral=True, thinking=True)
    uid = str(interaction.user.id)
    try:
        out = await core_call(core.meeting_host_answer, uid, rid, req_id, approve)
    except Refused as e:
        await reply(interaction, str(e))
        return
    texts, req = out.get("texts") or {}, out.get("request") or {}
    try:
        await interaction.message.edit(view=None)  # 응답한 요청의 버튼을 치운다
    except (discord.HTTPException, AttributeError) as e:
        log.warning("넘겨받기 버튼 제거 실패: %s", e)
    if approve:
        notice = texts.get("channel_notice", "")
        try:
            await interaction.channel.send(notice, allowed_mentions=NO_MENTION)
        except discord.HTTPException as e:
            log.warning("진행자 변경 고지 실패: %s", e)
        await tell_host(voice, rid, req.get("requester_discord_user_id", ""))
        await reply(interaction, notice)
        return
    notice = texts.get("requester_notice", "")
    requester = req.get("requester_discord_user_id")
    try:
        user = await interaction.client.fetch_user(int(requester))
        await user.send(notice, allowed_mentions=NO_MENTION)
    except (discord.HTTPException, TypeError, ValueError):
        # DM이 막혔으면 채널에 요청자를 언급해 알린다
        try:
            await interaction.channel.send(
                f"<@{requester}> {notice}", allowed_mentions=USER_MENTION
            )
        except discord.HTTPException as e:
            log.warning("거절 알림 실패: %s", e)
    await reply(interaction, MEETING_HOST_REJECTED)
