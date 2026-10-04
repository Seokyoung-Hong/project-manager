"""채널 감시·조정·기존 채널 연결·MCP 제어 서버의 권한 검사(IMPL-PLAN-5 B). Discord API에는 닿지 않는다."""

import asyncio
import json
from types import SimpleNamespace

import discord
import httpx
from aiohttp.test_utils import TestClient, TestServer
from conftest import FakeCore, make_core

from discord_service import control
from discord_service.channels import NOT_A_MANAGER, NOT_A_ROLE_MANAGER, connect_existing
from discord_service.config import Config
from discord_service.store import Store
from discord_service.watch import GRANT, Watcher, reconcile

DID = "111"


def run(coro):
    return asyncio.run(coro)


class M:
    def __init__(self, uid, name="멤버", bot=False, perms=0):
        self.id, self.display_name, self.bot = uid, name, bot
        self.guild_permissions = discord.Permissions(perms)


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
    perms = discord.Permissions(manage_channels=ok, manage_roles=True)
    return SimpleNamespace(id=int(DID), guild_permissions=perms)


def connect(fake, guild, ch, **kw):
    kw.setdefault("members_intent", True)
    return run(connect_existing(guild, manager(), make_core(fake), DID, "team", 1, ch, **kw))


def test_connect_without_outsiders_links():
    g = FakeGuild([M(111), M(5, bot=True)])
    ch = g.add(FakeText(10, g, viewers=[111, 5]))
    fake = FakeCore([], orgs=[{"org_id": 1, "guild_id": "1"}])
    assert "연결했습니다" in connect(fake, g, ch)
    body = fake.calls[-1][1]
    assert body["viewers"] == [{"id": "111", "name": "멤버"}]  # 봇 계정은 제외한다
    assert fake.channels["team"] == "10"


def test_outsiders_are_refused_privately_with_names_and_retry_hint():
    g = FakeGuild([M(111), M(222, "외부인")])
    ch = g.add(FakeText(10, g, viewers=[111, 222]))
    fake = FakeCore([], orgs=[{"org_id": 1, "guild_id": "1"}])
    reply = connect(fake, g, ch)
    assert "권한 밖 1명" in reply and "외부인" in reply and "권한밖허용:True" in reply
    assert fake.channels["team"] == ""
    assert "연결했습니다" in connect(fake, g, ch, allow_outsiders=True, managed=True)
    assert fake.calls[-1][1]["allow_outsiders"] is True and fake.calls[-1][1]["managed"] is True


def test_intent_off_is_unknown_and_needs_the_allow_option():
    g = FakeGuild([M(111)])
    ch = g.add(FakeText(10, g, viewers=[111]))
    fake = FakeCore([], orgs=[{"org_id": 1, "guild_id": "1"}])
    reply = connect(fake, g, ch, members_intent=False)
    assert "확인할 수 없습니다" in reply and "권한밖허용:True" in reply
    assert fake.calls[-1][1]["viewers"] is None and fake.channels["team"] == ""
    assert "연결했습니다" in connect(fake, g, ch, members_intent=False, allow_outsiders=True)


def test_connect_requires_manage_channels_before_core():
    g = FakeGuild([M(111)])
    ch = g.add(FakeText(10, g))
    fake = FakeCore([], orgs=[{"org_id": 1, "guild_id": "1"}])
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
    fake = FakeCore([], orgs=[{"org_id": 1, "guild_id": "1"}])
    fake.targets = [target(allowed=("111", "333"), grant=("111", "444"))]
    [res] = run(watcher(fake, tmp_path, guild=g).scan())
    [report] = fake.alert_reports
    assert report["guild_id"] == "1"
    [ch] = report["channels"]
    assert ch["outsiders"] == [{"id": "222", "name": "외부인"}]  # 봇·허용된 사람 제외
    assert ch["missing"] == [{"id": "111", "name": "멤버"}, {"id": "444", "name": "접근없음"}]
    assert fake.guild_reports == [
        {"guild_id": "1", "permissions": 268504080, "watching": True, "intent_denied": False}
    ]
    assert res["added"] == 0


def test_scan_with_intent_off_only_reports_permissions(tmp_path):
    g = FakeGuild([M(222)], perms=3088)
    g.add(FakeText(10, g, viewers=[222]))
    fake = FakeCore([], orgs=[{"org_id": 1, "guild_id": "1"}])
    fake.targets = [target()]
    run(watcher(fake, tmp_path, intent=False, guild=g).scan())
    assert fake.alert_reports == []  # 감시·조정 건너뜀
    assert fake.guild_reports == [
        {"guild_id": "1", "permissions": 3088, "watching": False, "intent_denied": False}
    ]


def test_scan_reconciles_managed_channels_only(tmp_path):
    g = FakeGuild([M(111), M(222)])
    managed = g.add(FakeText(10, g))
    plain = g.add(FakeText(11, g))
    fake = FakeCore([], orgs=[{"org_id": 1, "guild_id": "1"}])
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
        if path == "/api/orgs/1/discord-control-check":
            assert request.headers["Authorization"] == "Bearer pm_user"
            assert request.headers["X-Source"] == "mcp"
            return httpx.Response(200, json={"ok": True})
        if path == "/api/me":
            return httpx.Response(200, json={"discord_user_id": me_did})
        if path.endswith("/channel-check"):
            body = json.loads(request.content)
            viewers, created = body.get("viewers"), body.get("created", False)
            outs = [v for v in (viewers or []) if v["id"] != "111"]
            unknown = viewers is None and not created
            ok = created or (not (outs or unknown)) or body.get("allow_outsiders")
            return httpx.Response(200, json={"linked": ok, "unknown": unknown, "outsiders": outs})
        if path == "/api/integrations/discord/projects/1/channel":
            return httpx.Response(200, json={"id": 1, "discord_channel_id": ""})
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


def call(guild, path, body, *, me_did="111", intent=True, admin=True, preflight=None):
    handler, calls = core_handler(me_did, admin)
    original_handler = handler

    def checked_handler(request):
        if preflight is not None and request.url.path.endswith("/discord-control-check"):
            return preflight(request)
        return original_handler(request)

    client = SimpleNamespace(get_guild=lambda gid: guild)
    app = control.make_app(
        client, "http://core", core_token="bot", members_intent=intent,
        transport=httpx.MockTransport(checked_handler),
    )  # fmt: skip

    async def go():
        async with TestClient(TestServer(app)) as c:
            r = await c.post(path, json=body, headers={"Authorization": "Bearer pm_user"})
            return r.status, await r.text()

    status, text = run(go())
    return status, text, calls


def with_manage(ok, roles=True):
    perms = discord.Permissions(manage_channels=ok, manage_roles=roles)
    return SimpleNamespace(id=111, guild_permissions=perms)


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


# ---------- 결함 수정 ----------


def test_connect_sends_the_guild_id_and_managed_needs_manage_roles():
    g = FakeGuild([M(111)])
    ch = g.add(FakeText(10, g, viewers=[111]))
    fake = FakeCore([], orgs=[{"org_id": 1, "guild_id": "1"}])
    connect(fake, g, ch)
    assert fake.calls[-1][1]["guild_id"] == "1"
    no_roles = SimpleNamespace(
        id=111, guild_permissions=discord.Permissions(manage_channels=True, manage_roles=False)
    )
    reply = run(
        connect_existing(
            g, no_roles, make_core(fake), DID, "team", 1, ch, managed=True, members_intent=True
        )
    )
    assert reply == NOT_A_ROLE_MANAGER
    n = len(fake.calls)
    # 자동 관리 없이 연결하는 것은 Manage Roles가 없어도 된다
    run(connect_existing(g, no_roles, make_core(fake), DID, "team", 1, ch, members_intent=True))
    assert len(fake.calls) > n


def test_scan_merges_duplicate_channels_once(tmp_path):
    g = FakeGuild([M(111), M(222, "외부인"), M(333, "프로젝트팀")])
    ch = g.add(FakeText(10, g, viewers=[222, 333]))
    fake = FakeCore([], orgs=[{"org_id": 1, "guild_id": "1"}])
    fake.targets = [
        target("10", managed=True, allowed=("111",), grant=("111",)),
        {**target("10", managed=False, allowed=("333",), grant=("333",)), "kind": "project"},
    ]
    run(watcher(fake, tmp_path, guild=g).scan())
    [report] = fake.alert_reports
    [entry] = report["channels"]  # 채널 단위로 한 번만
    assert entry["outsiders"] == [{"id": "222", "name": "외부인"}]  # 333은 합집합 덕에 권한 안
    assert {e[0] for e in ch.edits} == {111, 333}  # 두 대상의 계정이 한 번의 조정에 모인다


def test_unlinked_channel_loses_only_the_bots_overwrites(tmp_path):
    store = Store(str(tmp_path / "s.sqlite"))
    g = FakeGuild([M(111), M(222)])
    old = g.add(FakeText(10, g))
    new = g.add(FakeText(11, g))
    run(reconcile(g, old, ["111"], store))
    old.ow[222] = discord.PermissionOverwrite(view_channel=True)  # 사람이 넣은 것
    fake = FakeCore([], orgs=[{"org_id": 1, "guild_id": "1"}])
    fake.targets = [target("11", managed=True)]  # 팀이 다른 채널로 바뀌었다
    w = Watcher(SimpleNamespace(get_guild=lambda gid: g), make_core(fake), store, True)
    run(w.scan())
    assert 111 not in old.ow and 222 in old.ow  # 봇이 넣은 것만 지운다
    assert store.grants("10") == set() and 111 in new.ow


def test_overwrites_given_at_creation_are_recorded(tmp_path):
    from test_channels import FakeGuild as CreateGuild
    from test_channels import member as manager_member

    from discord_service.channels import link_channel

    store = Store(str(tmp_path / "s.sqlite"))
    g = CreateGuild()
    fake = FakeCore([], orgs=[{"org_id": 1, "guild_id": "1"}])
    run(
        link_channel(
            g, manager_member(), make_core(fake), DID, "team", 1, None, "산돌이", store=store
        )
    )
    [created] = g.created
    assert store.grants(str(created.id)) == {"111"}  # 봇·@everyone은 기록하지 않는다


def test_create_requires_manage_roles():
    from test_channels import FakeGuild as CreateGuild
    from test_channels import member as manager_member

    from discord_service.channels import link_channel

    g = CreateGuild()
    fake = FakeCore([], orgs=[{"org_id": 1, "guild_id": "1"}])
    user = manager_member()
    user.guild_permissions = discord.Permissions(manage_channels=True, manage_roles=False)
    reply = run(link_channel(g, user, make_core(fake), DID, "team", 1, None, "산돌이"))
    assert reply == NOT_A_ROLE_MANAGER and fake.calls == [] and g.created == []


def test_control_requires_manage_roles_for_create_and_managed_assign():
    g = CtlGuild([M(111)], fetch=with_manage(True, roles=False))
    ch = g.add(FakeText(10, g, viewers=[111]))
    status, _, _ = call(g, "/orgs/1/projects/1/channels", {"org_id": 1, "channel_name": "x"})
    assert status == 403
    status, _, _ = call(g, "/projects/1/assign", {"org_id": 1, "channel_id": "10", "managed": True})
    assert status == 403
    status, text, calls = call(g, "/projects/1/assign", {"org_id": 1, "channel_id": "10"})
    assert status == 200 and json.loads(text)["linked"] is True
    sent = next(json.loads(b) for m, p, b in calls if p.endswith("/channel-check"))
    assert sent["guild_id"] == "1" and ch.edits == []


def test_watcher_reports_a_denied_intent(tmp_path):
    g = FakeGuild([M(111)])
    fake = FakeCore([], orgs=[{"org_id": 1, "guild_id": "1"}])
    fake.targets = [target()]
    store = Store(str(tmp_path / "w.sqlite"))
    client = SimpleNamespace(get_guild=lambda gid: g)
    run(Watcher(client, make_core(fake), store, False, intent_denied=True).scan())
    assert fake.guild_reports[0]["intent_denied"] is True


def test_listener_retries_without_members_intent_when_the_portal_denies_it(monkeypatch):
    from dataclasses import replace

    from discord_service import listener

    cfg = Config(
        core_url="c", core_token="t", bot_token="b", tz=None, llm_provider="", db_path="x",
        site_name="s", members_intent=True,
    )  # fmt: skip
    calls = []

    def fake_run(c, core, intent_denied=False):
        calls.append((c.members_intent, intent_denied))
        if c.members_intent:
            raise discord.PrivilegedIntentsRequired(None)

    monkeypatch.setattr(listener, "_run", fake_run)
    listener.run(cfg, None)
    assert calls == [(True, False), (False, True)]
    calls.clear()
    listener.run(replace(cfg, members_intent=False), None)  # 꺼 둔 것은 그대로 한 번만
    assert calls == [(False, False)]


# ---------- 모든 Discord 관리 기능은 실행자의 서버 권한을 확인한다 ----------


def test_can_manage_table_and_fail_closed():
    from discord_service.channels import NEEDS, can_manage

    assert NEEDS["channel"] == ("manage_channels",)
    assert NEEDS["managed"] == ("manage_channels", "manage_roles")
    both = SimpleNamespace(
        guild_permissions=discord.Permissions(manage_channels=True, manage_roles=True)
    )
    only_ch = SimpleNamespace(guild_permissions=discord.Permissions(manage_channels=True))
    assert can_manage(both, "managed") and can_manage(only_ch, "channel")
    assert not can_manage(only_ch, "managed")
    assert not can_manage(SimpleNamespace(), "channel")  # 권한을 못 알아내면 거절


def test_turning_automanage_on_or_off_needs_manage_roles_but_plain_connect_does_not():
    g = FakeGuild([M(111)])
    ch = g.add(FakeText(10, g, viewers=[111]))
    fake = FakeCore([], orgs=[{"org_id": 1, "guild_id": "1"}])
    no_roles = SimpleNamespace(
        id=111, guild_permissions=discord.Permissions(manage_channels=True, manage_roles=False)
    )
    for managed in (True, False):  # 끄기도 같은 권한
        reply = run(
            connect_existing(
                g,
                no_roles,
                make_core(fake),
                DID,
                "team",
                1,
                ch,
                managed=managed,
                members_intent=True,
            )
        )
        assert reply == NOT_A_ROLE_MANAGER
    assert fake.calls == []


def test_scan_reports_linked_members_server_permissions(tmp_path):
    admin_bits = (1 << 4) | (1 << 28)
    g = FakeGuild([M(111, perms=admin_bits), M(222, perms=1 << 4), M(333)])
    g.add(FakeText(10, g))
    fake = FakeCore([], orgs=[{"org_id": 1, "guild_id": "1"}])
    fake.orgs_data = [
        {"org_id": 1, "name": "산돌이", "guild_id": "1", "channel_id": "", "settings": {}}
    ]
    fake.org_members_data[1] = [
        {"discord_user_id": "111"},
        {"discord_user_id": "222"},
        {"discord_user_id": None},  # 연결 안 한 사람
        {"discord_user_id": "999"},  # 서버에 없다
    ]
    fake.targets = [target()]
    run(watcher(fake, tmp_path, guild=g).scan())
    [(_, body)] = [c for c in fake.calls if c[0] == "member-permissions"]
    assert body["guild_id"] == "1"
    assert body["members"] == [
        {"discord_user_id": "111", "permissions": admin_bits},
        {"discord_user_id": "222", "permissions": 1 << 4},
    ]


def test_orgs_without_targets_still_report_and_intent_off_reports_nothing(tmp_path):
    g = FakeGuild([M(111, perms=1 << 5)])
    fake = FakeCore([], orgs=[{"org_id": 1, "guild_id": "1"}])
    fake.orgs_data = [
        {"org_id": 1, "name": "산돌이", "guild_id": "1", "channel_id": "", "settings": {}}
    ]
    fake.org_members_data[1] = [{"discord_user_id": "111"}]
    fake.targets = []  # 팀·프로젝트가 아직 없다
    run(watcher(fake, tmp_path, guild=g).scan())
    assert [c for c in fake.calls if c[0] == "member-permissions"]
    fake.calls.clear()
    run(watcher(fake, tmp_path, intent=False, guild=g).scan())
    assert not [c for c in fake.calls if c[0] == "member-permissions"]  # 인텐트 꺼짐 = 보고 없음


def test_control_unlink_needs_manage_channels_and_goes_through_the_bot_api():
    g = CtlGuild([M(111)], fetch=with_manage(False))
    status, _, calls = call(g, "/projects/1/assign", {"org_id": 1, "channel_id": ""})
    assert status == 403 and not any("/channel" in p for _, p, _ in calls)
    g = CtlGuild([M(111)], fetch=with_manage(True, roles=False))
    status, _, calls = call(g, "/projects/1/assign", {"org_id": 1, "channel_id": ""})
    assert status == 200
    [(method, path, body)] = [c for c in calls if c[1].endswith("/projects/1/channel")]
    assert method == "POST" and json.loads(body) == {"discord_user_id": "111", "channel_id": ""}
    assert not any(m == "PUT" for m, _, _ in calls)  # 사용자 토큰의 REST 해제 경로를 쓰지 않는다


def test_control_preflight_fails_closed_before_discord_mutations():
    def timeout(request):
        raise httpx.ConnectError("private upstream", request=request)

    responses = [
        lambda request: httpx.Response(400, json={"detail": "private policy"}),
        lambda request: httpx.Response(200, json={"ok": False}),
        lambda request: httpx.Response(200, json=[]),
        lambda request: httpx.Response(200, text="invalid json"),
        timeout,
    ]
    for reject in responses:
        for path, body in [
            ("/projects/1/assign", {"org_id": 1, "channel_id": "10"}),
            ("/projects/1/assign", {"org_id": 1, "channel_id": ""}),
            ("/orgs/1/projects/1/channels", {"org_id": 1, "channel_name": "new"}),
        ]:
            guild = CtlGuild([M(111)], fetch=with_manage(True, roles=True))
            existing = guild.add(FakeText(10, guild, viewers=[111]))
            status, text, calls = call(guild, path, body, preflight=reject)
            assert status in (403, 503)
            assert "private" not in text
            assert guild.channels == {10: existing}
            assert not any(p.endswith("/channel-check") or m == "PUT" for m, p, _ in calls)
