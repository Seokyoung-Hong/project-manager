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
                reason="유달리: 채널 자동 관리",
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
                    member, overwrite=None, reason="유달리: 채널 자동 관리"
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
        self,
        client: discord.Client,
        core: CoreClient,
        store: Store,
        members_intent: bool,
        intent_denied: bool = False,
    ):
        self.client, self.core, self.store, self.intent = client, core, store, members_intent
        self.intent_denied = intent_denied  # 포털이 멤버 인텐트를 거부해 인텐트 없이 접속했다
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
        org_of: dict[str, int] = {}
        try:  # 대상이 하나도 없는 조직도 서버 권한 보고는 해야 한다(웹의 서버 연결 해제 판정)
            org_of = {
                o["guild_id"]: o["org_id"]
                for o in await asyncio.to_thread(self.core.orgs)
                if o.get("guild_id")
            }
        except Exception:  # noqa: BLE001
            log.warning("조직 목록을 못 읽었다, 대상이 있는 서버만 검사한다")
        by_guild: dict[str, list[dict]] = {g: [] for g in org_of}
        for t in targets:
            if t.get("guild_id"):
                by_guild.setdefault(t["guild_id"], []).append(t)
                org_of.setdefault(t["guild_id"], t["org_id"])
        results = []
        for guild_id, items in by_guild.items():
            if only is not None and guild_id not in only:
                continue
            guild = self.client.get_guild(int(guild_id))
            if guild is None:
                continue
            results.append(await self.scan_guild(guild, items, org_of.get(guild_id)))
        return results

    async def report_member_permissions(self, guild: discord.Guild, org_id: int) -> None:
        """Discord를 연결한 PM 사용자들의 서버 권한 비트를 core에 올린다.

        core는 Discord를 부르지 않으므로 웹의 관리 동작(자동 관리·허용·서버 연결 해제)은 이 값으로 그 사람의
        서버 권한을 판정한다. 관리자는 discord.py가 전체 비트로 계산해 준다. 보고가 없으면 core가 거절한다.
        """
        members = await asyncio.to_thread(self.core.org_members, org_id)
        out = []
        for m in members:
            if not m.get("discord_user_id"):
                continue
            member = guild.get_member(int(m["discord_user_id"]))
            if member is not None:
                out.append(
                    {
                        "discord_user_id": str(member.id),
                        "permissions": member.guild_permissions.value,
                    }
                )
        if out:
            await asyncio.to_thread(self.core.member_permissions, str(guild.id), out)

    @staticmethod
    def merge_by_channel(items: list[dict]) -> dict[str, dict]:
        """같은 채널을 여러 대상이 쓰는 옛 데이터는 허용 집합을 합쳐 한 번만 처리한다(엇갈린 조정·경고 방지)."""
        merged: dict[str, dict] = {}
        for t in items:
            cid = t["channel_id"]
            if not cid:
                continue
            m = merged.setdefault(
                cid, {"channel_id": cid, "managed": False, "allowed_ids": set(), "grant_ids": set()}
            )
            m["managed"] = m["managed"] or t["managed"]
            m["allowed_ids"] |= set(t["allowed_ids"])
            m["grant_ids"] |= set(t["grant_ids"])
        return merged

    async def scan_guild(
        self, guild: discord.Guild, items: list[dict], org_id: int | None = None
    ) -> dict:
        gid = str(guild.id)
        # 권한은 인텐트와 무관하게 보고한다 — 웹이 "권한 갱신 필요"를 띄우는 근거다.
        await asyncio.to_thread(
            self.core.guild_report,
            gid,
            guild.me.guild_permissions.value,
            self.intent,
            self.intent_denied,
        )
        if not self.intent:
            return {"guild_id": gid, "skipped": "members intent off"}
        if org_id is not None:
            await self.report_member_permissions(guild, org_id)
        channels, summary = [], {"guild_id": gid, "added": 0, "removed": 0}
        merged = self.merge_by_channel(items)
        for cid, t in merged.items():
            channel = guild.get_channel(int(cid))
            if not isinstance(channel, discord.TextChannel):
                continue
            if t["managed"]:
                r = await reconcile(guild, channel, sorted(t["grant_ids"]), self.store)
                summary["added"] += r["added"]
                summary["removed"] += r["removed"]
            viewers = viewers_of(guild, channel)
            seen = {v["id"] for v in viewers}
            entry = {
                "channel_id": cid,
                "outsiders": [v for v in viewers if v["id"] not in t["allowed_ids"]],
            }
            if not t["managed"]:  # 자동 관리가 꺼진 채널은 못 보는 팀원을 안내만 한다
                entry["missing"] = [
                    {"id": i, "name": m.display_name if (m := guild.get_member(int(i))) else i}
                    for i in sorted(t["grant_ids"])
                    if i not in seen
                ]
            channels.append(entry)
        # 연결이 끊기거나 다른 채널로 바뀐 옛 채널: 봇이 넣은 멤버 덮어쓰기만 지운다
        for cid in self.store.grant_channels() - set(merged):
            channel = guild.get_channel(int(cid))
            if isinstance(channel, discord.TextChannel):
                r = await reconcile(guild, channel, [], self.store)
                summary["removed"] += r["removed"]
        if channels:
            await asyncio.to_thread(self.core.channel_alerts, gid, channels)
        summary["at"] = time.time()
        return summary
