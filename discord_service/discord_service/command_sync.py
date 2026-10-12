"""새로 연결된 Discord 서버에 재시작 없이 슬래시 명령을 등록한다."""

import asyncio
import logging

import discord

log = logging.getLogger(__name__)
INTERVAL = 60


class GuildCommandSync:
    def __init__(self, tree, core, register):
        self.tree, self.core, self.register = tree, core, register
        self.registered: set[int] = set()
        self.synced: set[int] = set()
        self.lock = asyncio.Lock()
        self.wake = asyncio.Event()

    def trigger(self):
        self.wake.set()

    async def refresh(self):
        async with self.lock:
            try:
                orgs = await asyncio.to_thread(self.core.orgs)
            except Exception:  # noqa: BLE001
                log.exception("명령 동기화: 조직 목록 조회 실패, 다음 점검에서 재시도합니다")
                return
            guild_ids = set()
            for org in orgs:
                if not org.get("guild_id"):
                    continue
                try:
                    guild_ids.add(int(org["guild_id"]))
                except (ValueError, TypeError):
                    log.warning("명령 동기화: 잘못된 Discord 서버 ID를 건너뜁니다")
            # 연결을 해제했다 다시 연결하면 동기화한다. 다른 앱의 명령은 건드리지 않는다.
            self.synced.intersection_update(guild_ids)
            for guild_id in sorted(guild_ids - self.synced):
                guild = discord.Object(id=guild_id)
                if guild_id not in self.registered:
                    try:
                        self.register(guild)
                    except Exception:  # noqa: BLE001
                        self.tree.clear_commands(guild=guild)
                        log.exception("슬래시 명령 로컬 등록 실패(guild=%s)", guild_id)
                        continue
                    self.registered.add(guild_id)
                try:
                    commands = await self.tree.sync(guild=guild)
                except Exception:  # noqa: BLE001
                    log.exception(
                        "슬래시 명령 동기화 실패, 다음 점검에서 재시도(guild=%s)", guild_id
                    )
                    continue
                self.synced.add(guild_id)
                log.info(
                    "슬래시 명령 동기화 완료(guild=%s commands=%s)", guild_id, len(commands or [])
                )

    async def run(self, client):
        await client.wait_until_ready()
        while True:
            self.wake.clear()
            await self.refresh()
            try:
                await asyncio.wait_for(self.wake.wait(), INTERVAL)
            except TimeoutError:
                pass
