"""봇에게 온 DM과 슬래시 명령을 받는 상주 프로세스.

`import discord`는 절대 임포트라 site-packages의 discord.py를 가리킨다
(같은 패키지의 `discord_service/discord.py`가 아니다 — 패키지 디렉터리는 sys.path에 없다).

인텐트는 `DIRECT_MESSAGES`(1<<12)와 `GUILDS`(1<<0) 둘, 모두 비특권이다. 봇에게 온 DM의 본문은
MESSAGE_CONTENT 특권 인텐트 없이도 전달된다(문서 명시 예외). 길드 인텐트는 채널을 만들 길드
캐시 때문이다. 특권 인텐트는 켜지 않는다. 슬래시 명령(인터랙션)도 게이트웨이로 온다 —
공개 엔드포인트도 서명 검증도 없다.
"""

import asyncio
import logging
import os
import time

import discord
from discord import app_commands

from .commands import RATE, handle, too_fast  # noqa: F401  (RATE·too_fast는 기존 import 경로 유지)
from .core_client import CoreClient
from .control import start_control_server
from .discord import chunk
from .slash import register

log = logging.getLogger(__name__)


def run(cfg, core: CoreClient):
    intents = discord.Intents.none()
    intents.dm_messages = True
    intents.guilds = True
    client = discord.Client(intents=intents)
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
            register(tree, guild, cfg, core, seen)
    else:
        log.warning("바인딩된 Discord 서버가 없어 슬래시 명령을 등록하지 않습니다 (DM 명령만 동작)")

    async def setup_hook():
        # 길드 범위 동기화는 즉시 반영된다(전역은 최대 1시간). on_ready는 재접속마다 다시
        # 불리므로 거기서 하면 매번 API를 때린다.
        for guild in guilds:
            await tree.sync(guild=guild)
        # MCP와 같은 내부 Compose 네트워크 전용. Discord 봇 토큰은 이 컨테이너 밖으로 나가지 않는다.
        port = int(os.environ.get("DISCORD_CONTROL_PORT", "8081"))
        client.control_runner = await start_control_server(client, cfg.core_url, port)

    client.setup_hook = setup_hook

    @client.event
    async def on_ready():
        log.info("discord 봇 접속: %s", client.user)

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
