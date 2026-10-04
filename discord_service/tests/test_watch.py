"""채널 감시·조정·기존 채널 연결·MCP 제어 서버의 권한 검사(IMPL-PLAN-5 B). Discord API에는 닿지 않는다."""

import asyncio
import json
from types import SimpleNamespace

import discord
import httpx
from aiohttp.test_utils import TestClient, TestServer
from conftest import FakeCore, make_core

from discord_service import control
from discord_service.channels import NOT_A_MANAGER, connect_existing
from discord_service.config import Config
from discord_service.store import Store
from discord_service.watch import GRANT, Watcher, reconcile

DID = "111"


def run(coro):
    return asyncio.run(coro)


class M:
    def __init__(self, uid, name="멤버", bot=False):
        self.id, self.display_name, self.bot = uid, name, bot


class FakeText(discord.TextChannel):
    """TextChannel처럼 보이는 가짜. 덮어쓰기는 id → PermissionOverwrite로만 든다."""

    def __init__(self, cid, guild, viewers=()):
        self.id, self.guild = cid, guild
        self.viewers = set(viewers)
        self.ow: dict[int, discord.PermissionOverwrite] = {}
        self.edits: list[tuple[int, object]] = []

    def permissions_for(self, member):
        return SimpleNamespace(view_channel=member.id in self.viewers)

    def overwrites_for(self, member):
        return self.ow.get(member.id, discord.PermissionOverwrite())

    async def set_permissions(self, target, *, overwrite, reason=None):
        self.edits.append((target.id, overwrite))
        if overwrite is None:
            self.ow.pop(target.id, None)
        else:
            self.ow[target.id] = overwrite


class FakeGuild:
    def __init__(self, members, perms=268504080):
        self.id = 1
        self.members = list(members)
        self.channels: dict[int, FakeText] = {}
        self.me = SimpleNamespace(guild_permissions=discord.Permissions(perms))

    def get_member(self, uid):
        return next((m for m in self.members if m.id == uid), None)

    def get_channel(self, cid):
        return self.channels.get(cid)

    def add(self, ch):
        self.channels[ch.id] = ch
        return ch


def granted():
    return discord.PermissionOverwrite(**GRANT)


# ---------- 기존 채널 연결 ----------


def manager(ok=True):
    return SimpleNamespace(id=int(DID), guild_permissions=discord.Permissions(manage_channels=ok))


def connect(fake, guild, ch, **kw):
    kw.setdefault("members_intent", True)
    return run(connect_existing(guild, manager(), make_core(fake), DID, "team", 1, ch, **kw))


def test_connect_without_outsiders_links():
    g = FakeGuild([M(111), M(5, bot=True)])
    ch = g.add(FakeText(10, g, viewers=[111, 5]))
    fake = FakeCore([])
    assert "연결했습니다" in connect(fake, g, ch)
    body = fake.calls[-1][1]
    assert body["viewers"] == [{"id": "111", "name": "멤버"}]  # 봇 계정은 제외한다
    assert fake.channels["team"] == "10"


def test_outsiders_are_refused_privately_with_names_and_retry_hint():
    g = FakeGuild([M(111), M(222, "외부인")])
    ch = g.add(FakeText(10, g, viewers=[111, 222]))
    fake = FakeCore([])
    reply = connect(fake, g, ch)
    assert "권한 밖 1명" in reply and "외부인" in reply and "권한밖허용:True" in reply
    assert fake.channels["team"] == ""
    assert "연결했습니다" in connect(fake, g, ch, allow_outsiders=True, managed=True)
    assert fake.calls[-1][1]["allow_outsiders"] is True and fake.calls[-1][1]["managed"] is True


def test_intent_off_is_unknown_and_needs_the_allow_option():
    g = FakeGuild([M(111)])
    ch = g.add(FakeText(10, g, viewers=[111]))
    fake = FakeCore([])
    reply = connect(fake, g, ch, members_intent=False)
    assert "확인할 수 없습니다" in reply and "권한밖허용:True" in reply
    assert fake.calls[-1][1]["viewers"] is None and fake.channels["team"] == ""
    assert "연결했습니다" in connect(fake, g, ch, members_intent=False, allow_outsiders=True)


def test_connect_requires_manage_channels_before_core():
    g = FakeGuild([M(111)])
    ch = g.add(FakeText(10, g))
    fake = FakeCore([])
    reply = run(
        connect_existing(
            g, manager(False), make_core(fake), DID, "team", 1, ch, members_intent=True
        )
    )
    assert reply == NOT_A_MANAGER and fake.calls == []


# ---------- 자동 관리 조정 ----------


def test_reconcile_adds_only_view_send_history_and_records(tmp_path):
    store = Store(str(tmp_path / "s.sqlite"))
    g = FakeGuild([M(111), M(222)])
    ch = g.add(FakeText(10, g))
    assert run(reconcile(g, ch, ["111", "999"], store)) == {
        "added": 1,
        "removed": 0,
    }  # 999는 서버에 없다
    assert ch.ow[111].pair() == granted().pair()
    assert store.grants("10") == {"111"}
    assert run(reconcile(g, ch, ["111"], store)) == {"added": 0, "removed": 0}  # 멱등
    assert len(ch.edits) == 1


def test_reconcile_leaves_human_overwrites_and_removes_only_its_own(tmp_path):
    store = Store(str(tmp_path / "s.sqlite"))
    g = FakeGuild([M(111), M(222), M(333)])
    ch = g.add(FakeText(10, g))
    ch.ow[222] = discord.PermissionOverwrite(view_channel=False)  # 사람이 막아 둔 멤버
    ch.ow[333] = discord.PermissionOverwrite(
        view_channel=True, manage_messages=True
    )  # 사람이 넣은 것
    run(reconcile(g, ch, ["111", "222"], store))
    assert ch.ow[222].view_channel is False and store.grants("10") == {
        "111"
    }  # 사람 것은 불변·기록 안 함
    # 허용 집합에서 111이 빠지면 봇이 넣은 것만 지운다. 333(사람)은 처음부터 대상이 아니다
    assert run(reconcile(g, ch, [], store)) == {"added": 0, "removed": 1}
    assert 111 not in ch.ow and 222 in ch.ow and 333 in ch.ow
    assert store.grants("10") == set()


def test_reconcile_does_not_remove_an_overwrite_a_human_changed(tmp_path):
    store = Store(str(tmp_path / "s.sqlite"))
    g = FakeGuild([M(111)])
    ch = g.add(FakeText(10, g))
    run(reconcile(g, ch, ["111"], store))
    ch.ow[111] = discord.PermissionOverwrite(
        view_channel=True, send_messages=True, manage_messages=True
    )
    assert run(reconcile(g, ch, [], store)) == {"added": 0, "removed": 0}
    assert 111 in ch.ow and store.grants("10") == set()  # 이제 사람의 것이다


# ---------- 감시 ----------


def target(channel_id="10", managed=False, allowed=("111",), grant=("111",)):
    return {
        "org_id": 1, "guild_id": "1", "kind": "team", "id": 1, "name": "백엔드",
        "channel_id": channel_id, "managed": managed,
        "allowed_ids": list(allowed), "grant_ids": list(grant),
    }  # fmt: skip


def watcher(fake, tmp_path, intent=True, guild=None):
    client = SimpleNamespace(get_guild=lambda gid: guild)
    return Watcher(client, make_core(fake), Store(str(tmp_path / "w.sqlite")), intent)


def test_scan_reports_outsiders_without_bots_or_allowed_and_missing_members(tmp_path):
    g = FakeGuild([M(111), M(222, "외부인"), M(333, "허용됨"), M(5, bot=True), M(444, "접근없음")])
    g.add(FakeText(10, g, viewers=[222, 333, 5]))
    fake = FakeCore([])
    fake.targets = [target(allowed=("111", "333"), grant=("111", "444"))]
    [res] = run(watcher(fake, tmp_path, guild=g).scan())
    [report] = fake.alert_reports
    assert report["guild_id"] == "1"
    [ch] = report["channels"]
    assert ch["outsiders"] == [{"id": "222", "name": "외부인"}]  # 봇·허용된 사람 제외
    assert ch["missing"] == [{"id": "111", "name": "멤버"}, {"id": "444", "name": "접근없음"}]
    assert fake.guild_reports == [{"guild_id": "1", "permissions": 268504080, "watching": True}]
    assert res["added"] == 0


def test_scan_with_intent_off_only_reports_permissions(tmp_path):
    g = FakeGuild([M(222)], perms=3088)
    g.add(FakeText(10, g, viewers=[222]))
    fake = FakeCore([])
    fake.targets = [target()]
    run(watcher(fake, tmp_path, intent=False, guild=g).scan())
    assert fake.alert_reports == []  # 감시·조정 건너뜀
    assert fake.guild_reports == [{"guild_id": "1", "permissions": 3088, "watching": False}]


def test_scan_reconciles_managed_channels_only(tmp_path):
    g = FakeGuild([M(111), M(222)])
    managed = g.add(FakeText(10, g))
    plain = g.add(FakeText(11, g))
    fake = FakeCore([])
    fake.targets = [target("10", managed=True), {**target("11"), "id": 2}]
    run(watcher(fake, tmp_path, guild=g).scan())
    assert 111 in managed.ow and plain.ow == {}
    [report] = fake.alert_reports
    by = {c["channel_id"]: c for c in report["channels"]}
    assert "missing" not in by["10"] and "missing" in by["11"]


def test_trigger_collects_guilds(tmp_path):
    w = watcher(FakeCore([]), tmp_path)
    w.trigger(1)
    w.trigger("1")
    assert w.pending == {"1"}


def test_members_intent_flag_from_env(monkeypatch):
    monkeypatch.setenv("CORE_URL", "http://core")
    monkeypatch.setenv("CORE_TOKEN", "t")
    monkeypatch.setenv("DISCORD_BOT_TOKEN", "b")
    monkeypatch.setattr(
        "discord_service.config.ZoneInfo", lambda key: None
    )  # 윈도에는 tzdata가 없다
    assert Config.from_env().members_intent is False
    monkeypatch.setenv("DISCORD_MEMBERS_INTENT", "1")
    assert Config.from_env().members_intent is True


# ---------- MCP 제어 서버 ----------


def core_handler(me_did="111", admin=True, linked=None):
    calls = []

    def handler(request: httpx.Request) -> httpx.Response:
        path = request.url.path
        calls.append((request.method, path, request.content))
        if path == "/api/orgs/1":
            return httpx.Response(
                200,
                json={
                    "role": "admin" if admin else "member",
                    "discord_guild_id": "1",
                    "projects": [{"id": 1, "name": "학식 API"}],
                },
            )
        if path == "/api/me":
            return httpx.Response(200, json={"discord_user_id": me_did})
        if path.endswith("/channel-check"):
            body = json.loads(request.content)
            viewers, created = body.get("viewers"), body.get("created", False)
            outs = [v for v in (viewers or []) if v["id"] != "111"]
            unknown = viewers is None and not created
            ok = created or (not (outs or unknown)) or body.get("allow_outsiders")
            return httpx.Response(200, json={"linked": ok, "unknown": unknown, "outsiders": outs})
        if path == "/api/integrations/discord/channels":
            return httpx.Response(200, json=[{"kind": "project", "id": 1, "grant_ids": ["111"]}])
        return httpx.Response(404)

    return handler, calls


class CtlGuild(FakeGuild):
    def __init__(self, members, fetch=None, **kw):
        super().__init__(members, **kw)
        self.fetch = fetch

    async def fetch_member(self, uid):
        if self.fetch is None:
            raise discord.HTTPException(SimpleNamespace(status=404, reason="x"), "x")
        return self.fetch


def call(guild, path, body, *, me_did="111", intent=True, admin=True):
    handler, calls = core_handler(me_did, admin)
    client = SimpleNamespace(get_guild=lambda gid: guild)
    app = control.make_app(
        client, "http://core", core_token="bot", members_intent=intent,
        transport=httpx.MockTransport(handler),
    )  # fmt: skip

    async def go():
        async with TestClient(TestServer(app)) as c:
            r = await c.post(path, json=body, headers={"Authorization": "Bearer pm_user"})
            return r.status, await r.text()

    status, text = run(go())
    return status, text, calls


def with_manage(ok):
    return SimpleNamespace(id=111, guild_permissions=discord.Permissions(manage_channels=ok))


def test_control_refuses_without_manage_channels_and_changes_nothing():
    for fetch, me in ((with_manage(False), "111"), (None, "111"), (with_manage(True), None)):
        g = CtlGuild([M(111)], fetch=fetch)
        ch = g.add(FakeText(10, g, viewers=[111]))
        status, _, calls = call(
            g, "/projects/1/assign", {"org_id": 1, "channel_id": str(ch.id)}, me_did=me
        )
        assert status == 403
        assert not any(p.endswith("/channel-check") or m == "PUT" for m, p, _ in calls)
        status, _, calls = call(
            g, "/orgs/1/projects/1/channels", {"org_id": 1, "channel_name": "x"}, me_did=me
        )
        assert status == 403 and g.channels == {10: ch}


def test_control_assign_checks_outsiders_and_requires_explicit_allow():
    g = CtlGuild([M(111), M(222, "외부인")], fetch=with_manage(True))
    ch = g.add(FakeText(10, g, viewers=[111, 222]))
    body = {"org_id": 1, "channel_id": "10"}
    status, text, _ = call(g, "/projects/1/assign", body)
    data = json.loads(text)
    assert status == 200 and data["linked"] is False and data["outsiders"][0]["name"] == "외부인"
    assert "allow_outsiders=true" in data["message"]
    status, text, calls = call(g, "/projects/1/assign", {**body, "allow_outsiders": True})
    assert json.loads(text)["linked"] is True
    # 인텐트가 꺼져 있으면 확인 불가 — 허용 옵션이 없으면 거절한다
    status, text, _ = call(g, "/projects/1/assign", body, intent=False)
    assert json.loads(text)["unknown"] is True and json.loads(text)["linked"] is False
    assert ch.edits == []


def test_control_create_makes_a_private_channel_for_the_allowed_set():
    g = CtlGuild([M(111)], fetch=with_manage(True))
    created = {}

    async def create_text_channel(name, *, category=None, topic=None, overwrites=None, reason=None):
        created["overwrites"] = overwrites
        ch = FakeText(77, g)
        g.add(ch)
        return ch

    g.create_text_channel = create_text_channel
    # overwrites 딕셔너리 키가 해시 가능해야 한다
    g.default_role = type("R", (), {})()
    g.me = type("Me", (), {"id": 9, "bot": True})()
    status, text, calls = call(
        g, "/orgs/1/projects/1/channels", {"org_id": 1, "channel_name": "학식"}
    )
    assert status == 200 and json.loads(text)["private"] is True
    ow = created["overwrites"]
    assert ow[g.default_role].pair()[1].view_channel is True  # @everyone 보기 거부
    assert {getattr(k, "id", None) for k in ow} == {None, 9, 111}
    sent = next(json.loads(b) for m, p, b in calls if p.endswith("/channel-check"))
    assert sent["created"] is True
