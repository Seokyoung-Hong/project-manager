"""봇에게 온 DM과 슬래시 명령을 받는 상주 프로세스.

`import discord`는 절대 임포트라 site-packages의 discord.py를 가리킨다
(같은 패키지의 `discord_service/discord.py`가 아니다 — 패키지 디렉터리는 sys.path에 없다).

인텐트는 `DIRECT_MESSAGES`(1<<12)와 `GUILDS`(1<<0) 둘, 모두 비특권이다. 봇에게 온 DM의 본문은
MESSAGE_CONTENT 특권 인텐트 없이도 전달된다(문서 명시 예외). 길드 인텐트는 채널을 만들 길드
캐시 때문이다. 특권 인텐트는 `DISCORD_MEMBERS_INTENT=1`일 때 `GUILD_MEMBERS` 하나만 켠다(채널 감시·자동 관리용,
포털에서 먼저 켜야 한다). MESSAGE_CONTENT는 켜지 않는다. 슬래시 명령(인터랙션)도 게이트웨이로 온다 —
공개 엔드포인트도 서명 검증도 없다.
"""

import asyncio
import logging
import os
import time
from dataclasses import replace

import discord
from discord import app_commands

from .commands import RATE, handle, too_fast  # noqa: F401  (RATE·too_fast는 기존 import 경로 유지)
from .control import start_control_server
from .core_client import CoreClient
from .discord import chunk
from .slash import register
from .store import Store
from .watch import Watcher

log = logging.getLogger(__name__)


def run(cfg, core: CoreClient):
    """게이트웨이에 접속한다. 포털에서 멤버 인텐트가 꺼져 있으면(4014) 인텐트 없이 다시 접속한다.

    죽었다 재시작을 반복하면 알림·명령이 모두 멈춘다. 감시·자동 관리만 끄고 나머지는 계속 동작하게 하며,
    core에 "인텐트 꺼짐"을 보고해 웹에 보이게 한다(watch.Watcher의 guild-report).
    """
    try:
        _run(cfg, core)
    except discord.PrivilegedIntentsRequired:
        if not cfg.members_intent:
            raise
        log.error(
            "Server Members Intent가 포털에서 꺼져 있습니다. 멤버 인텐트 없이 다시 접속합니다"
            "(채널 감시·자동 관리 꺼짐). 포털에서 켠 뒤 재기동해 주세요."
        )
        _run(replace(cfg, members_intent=False), core, intent_denied=True)


def _run(cfg, core: CoreClient, intent_denied: bool = False):
    intents = discord.Intents.none()
    intents.dm_messages = True
    intents.guilds = True
    intents.members = cfg.members_intent
    client = discord.Client(intents=intents)
    # 자동 관리가 넣은 덮어쓰기 기록(grants). 발송 프로세스의 파일과 별개의 파일(compose의 discord-bot 볼륨)이다.
    store = Store(cfg.db_path)
    watcher = Watcher(client, core, store, cfg.members_intent, intent_denied=intent_denied)
    seen: dict[str, list[float]] = {}

    tree = app_commands.CommandTree(client)
    # 다중 조직(§8.4): 바인딩된 길드 전부에 등록한다. 길드가 늘면 다음 기동에 반영된다
    # (길드 범위 동기화라 매 기동마다 core.orgs()를 한 번만 읽는다 — 실시간으로 새 길드를
    # 잡으려면 주기적 재동기화가 필요한데, 조직 연결은 자주 있는 일이 아니라 배보다 배꼽이
    # 크다. 재배포·재기동으로 충분하다).
    try:
        orgs = core.orgs()
    except Exception:  # noqa: BLE001
        orgs = []
        log.exception("조직 목록을 못 읽어 슬래시 명령을 등록하지 않습니다 (DM 명령만 동작)")
    guilds = [discord.Object(id=int(o["guild_id"])) for o in orgs if o.get("guild_id")]
    if guilds:
        for guild in guilds:
            register(tree, guild, cfg, core, seen, store)
    else:
        log.warning("바인딩된 Discord 서버가 없어 슬래시 명령을 등록하지 않습니다 (DM 명령만 동작)")

    async def setup_hook():
        # 길드 범위 동기화는 즉시 반영된다(전역은 최대 1시간). on_ready는 재접속마다 다시
        # 불리므로 거기서 하면 매번 API를 때린다.
        for guild in guilds:
            await tree.sync(guild=guild)
        # MCP와 같은 내부 Compose 네트워크 전용. Discord 봇 토큰은 이 컨테이너 밖으로 나가지 않는다.
        port = int(os.environ.get("DISCORD_CONTROL_PORT", "8081"))
        client.control_runner = await start_control_server(
            client,
            cfg.core_url,
            port,
            core_token=cfg.core_token,
            members_intent=cfg.members_intent,
            store=store,
        )
        client.watch_task = asyncio.create_task(watcher.run())

    client.setup_hook = setup_hook

    @client.event
    async def on_ready():
        log.info("discord 봇 접속: %s", client.user)

    # 채널·역할·멤버가 바뀌면 그 길드를 바로 다시 본다(5분 주기와 별개).
    @client.event
    async def on_guild_channel_update(before, after):
        watcher.trigger(after.guild.id)

    @client.event
    async def on_guild_role_update(before, after):
        watcher.trigger(after.guild.id)

    if cfg.members_intent:

        @client.event
        async def on_member_update(before, after):
            watcher.trigger(after.guild.id)

        @client.event
        async def on_member_join(member):
            watcher.trigger(member.guild.id)

    @client.event
    async def on_message(message):
        if message.author.bot or message.guild is not None:
            return  # 자기 메시지 루프 방지 + DM만 받는다
        uid = str(message.author.id)
        if too_fast(seen, uid, time.monotonic()):
            log.warning("발신자 한도 초과로 무시: %s", uid)
            return
        # CoreClient는 동기 httpx다. 이벤트 루프에서 그대로 부르면 하트비트가 굶어
        # 게이트웨이가 연결을 끊는다.
        reply = await asyncio.to_thread(handle, core, uid, message.content)
        for part in chunk(reply):
            await message.channel.send(part, allowed_mentions=discord.AllowedMentions.none())

    # 재접속·하트비트·RESUME·close code 처리는 라이브러리가 맡는다.
    client.run(cfg.bot_token, log_handler=None)
