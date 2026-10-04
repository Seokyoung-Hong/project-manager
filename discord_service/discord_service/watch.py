"""채널 감시와 자동 관리 조정. IMPL-PLAN-5 B.

게이트웨이 프로세스(listener) 안에서 돈다 — 길드 캐시와 멤버 인텐트가 거기 있다. 판단은 core가 한다:
봇은 "누가 채널을 보는가"와 "허용 집합 중 누가 못 보는가"만 계산해 올린다. 권한 밖 인원을 쫓아내지 않는다.

자동 관리(조정)는 허용 집합의 연결 계정에게 **멤버 덮어쓰기** 하나(VIEW·SEND·READ_HISTORY)만 넣는다.
역할·@everyone·사람이 넣은 덮어쓰기는 건드리지 않고, 봇이 넣은 것만 store(grants)에 적어 두었다가
허용 집합에서 빠지면 그것만 지운다. 그 밖의 권한은 주지 않는다.
"""

import asyncio
import logging
import time

import discord

from .core_client import CoreClient
from .store import Store

log = logging.getLogger(__name__)

INTERVAL = 300  # 5분. 이벤트가 오면 바로 다시 본다
DEBOUNCE = 10  # 이벤트가 몰리면(멤버 변경 연쇄) 한 번에 묶는다
GRANT = {"view_channel": True, "send_messages": True, "read_message_history": True}


def viewers_of(guild: discord.Guild, channel) -> list[dict]:
    """채널을 볼 수 있는 사람(봇 제외). 멤버 캐시가 있어야 정확하다 — 멤버 인텐트가 켜진 경우에만 부른다."""
    return [
        {"id": str(m.id), "name": m.display_name}
        for m in guild.members
        if not m.bot and channel.permissions_for(m).view_channel
    ]


def _grant_pair():
    return discord.PermissionOverwrite(**GRANT).pair()


async def reconcile(guild: discord.Guild, channel, grant_ids: list[str], store: Store) -> dict:
    """자동 관리 채널의 멤버 덮어쓰기를 허용 집합에 맞춘다. 돌려주는 값은 넣은 수·지운 수."""
    cid, want = str(channel.id), {str(i) for i in grant_ids}
    mine = store.grants(cid)
    added = removed = 0
    for uid in sorted(want - mine):
        member = guild.get_member(int(uid))
        if member is None or member.bot:
            continue  # 서버에 없다. 들어오면 GUILD_MEMBER_ADD가 다시 검사한다
        if channel.overwrites_for(member).pair() != discord.PermissionOverwrite().pair():
            continue  # 이미 사람이 정한 덮어쓰기가 있다. 건드리지 않고 기록도 하지 않는다
        try:
            await channel.set_permissions(
                member,
                overwrite=discord.PermissionOverwrite(**GRANT),
                reason="산돌이: 채널 자동 관리",
            )
        except discord.HTTPException as e:
            log.warning("덮어쓰기 추가 실패(channel=%s user=%s): %s", cid, uid, e)
            continue
        store.add_grant(cid, uid)
        added += 1
    for uid in sorted(mine - want):
        member = guild.get_member(int(uid))
        # 봇이 넣은 모양 그대로일 때만 지운다. 사람이 고쳤다면 그건 이제 사람의 것이다.
        # ponytail: 서버를 떠난 사람의 덮어쓰기는 못 지운다(Member 객체가 없다). 기록만 버린다.
        if member is not None and channel.overwrites_for(member).pair() == _grant_pair():
            try:
                await channel.set_permissions(
                    member, overwrite=None, reason="산돌이: 채널 자동 관리"
                )
            except discord.HTTPException as e:
                log.warning("덮어쓰기 제거 실패(channel=%s user=%s): %s", cid, uid, e)
                continue
            removed += 1
        store.drop_grant(cid, uid)
    return {"added": added, "removed": removed}


class Watcher:
    """5분마다, 그리고 게이트웨이 이벤트가 오면 해당 길드를 다시 검사한다."""

    def __init__(
        self, client: discord.Client, core: CoreClient, store: Store, members_intent: bool
    ):
        self.client, self.core, self.store, self.intent = client, core, store, members_intent
        self.pending: set[str] = set()
        self.wake = asyncio.Event()

    def trigger(self, guild_id) -> None:
        self.pending.add(str(guild_id))
        self.wake.set()

    async def run(self) -> None:
        await self.client.wait_until_ready()
        woke = False
        while True:
            guilds = set(self.pending) if woke else None  # None = 전부
            self.pending.clear()
            self.wake.clear()
            try:
                await self.scan(guilds)
            except Exception:  # noqa: BLE001
                log.exception("채널 감시 실패")
            try:
                await asyncio.wait_for(self.wake.wait(), INTERVAL)
                woke = True
                await asyncio.sleep(DEBOUNCE)
            except TimeoutError:
                woke = False

    async def scan(self, only: set[str] | None = None) -> list[dict]:
        targets = await asyncio.to_thread(self.core.channel_targets)
        by_guild: dict[str, list[dict]] = {}
        for t in targets:
            if t.get("guild_id") and (only is None or t["guild_id"] in only):
                by_guild.setdefault(t["guild_id"], []).append(t)
        results = []
        for guild_id, items in by_guild.items():
            guild = self.client.get_guild(int(guild_id))
            if guild is None:
                continue
            results.append(await self.scan_guild(guild, items))
        return results

    async def scan_guild(self, guild: discord.Guild, items: list[dict]) -> dict:
        gid = str(guild.id)
        # 권한은 인텐트와 무관하게 보고한다 — 웹이 "권한 갱신 필요"를 띄우는 근거다.
        await asyncio.to_thread(
            self.core.guild_report, gid, guild.me.guild_permissions.value, self.intent
        )
        if not self.intent:
            return {"guild_id": gid, "skipped": "members intent off"}
        channels, summary = [], {"guild_id": gid, "added": 0, "removed": 0}
        for t in items:
            channel = guild.get_channel(int(t["channel_id"])) if t["channel_id"] else None
            if not isinstance(channel, discord.TextChannel):
                continue
            if t["managed"]:
                r = await reconcile(guild, channel, t["grant_ids"], self.store)
                summary["added"] += r["added"]
                summary["removed"] += r["removed"]
            viewers = viewers_of(guild, channel)
            allowed, seen = set(t["allowed_ids"]), {v["id"] for v in viewers}
            entry = {
                "channel_id": t["channel_id"],
                "outsiders": [v for v in viewers if v["id"] not in allowed],
            }
            if not t["managed"]:  # 자동 관리가 꺼진 채널은 못 보는 팀원을 안내만 한다
                entry["missing"] = [
                    {"id": i, "name": m.display_name if (m := guild.get_member(int(i))) else i}
                    for i in t["grant_ids"]
                    if i not in seen
                ]
            channels.append(entry)
        if channels:
            await asyncio.to_thread(self.core.channel_alerts, gid, channels)
        summary["at"] = time.time()
        return summary
