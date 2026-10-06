"""채널 생성 흐름: 인가 → 중복 확인 → 생성 → 되적기 → 답장. 되적기 실패는 생성을 되돌린다."""

import asyncio
from types import SimpleNamespace

import discord
import pytest
from conftest import FakeCore, make_core, org

from discord_service.channels import NO_PERMISSION, NOT_A_MANAGER, can_manage_channels, link_channel

DID = "111"


def member(manage_channels=True):
    """길드 인터랙션의 user: 역할 권한이 실린 Member (guilds 인텐트만으로 온다)."""
    return SimpleNamespace(
        id=int(DID),
        guild_permissions=discord.Permissions(manage_channels=manage_channels, manage_roles=True),
    )


def _forbidden():
    resp = SimpleNamespace(status=403, reason="Forbidden")
    return discord.Forbidden(resp, {"message": "Missing Permissions", "code": 50013})


class FakeChannel:
    def __init__(self, guild, cid, name, category, topic):
        self.guild, self.id, self.name, self.category, self.topic = (
            guild,
            cid,
            name,
            category,
            topic,
        )
        self.delete_fails = False

    async def delete(self, *, reason=None):
        if self.delete_fails:
            raise discord.HTTPException(SimpleNamespace(status=500, reason="x"), "x")
        del self.guild.channels[self.id]


class Obj:
    """오버라이드 딕셔너리의 키가 되려면 해시 가능해야 한다(SimpleNamespace는 아니다)."""

    def __init__(self, **kw):
        self.__dict__.update(kw)


class FakeGuild:
    def __init__(self, categories=(), forbidden=False):
        self.id = 1
        self.default_role = Obj(name="@everyone")
        self.me = Obj(id=9, bot=True)
        self.members = {111: Obj(id=111, bot=False)}
        self.channels: dict[int, FakeChannel] = {}
        self.categories = [SimpleNamespace(name=c) for c in categories]
        self.forbidden = forbidden
        self.next_id = 5000
        self.created: list[FakeChannel] = []

    def get_channel(self, cid: int):
        return self.channels.get(cid)

    def get_member(self, uid):
        return self.members.get(uid)

    async def create_text_channel(
        self, name, *, category=None, topic=None, overwrites=None, reason=None
    ):
        if self.forbidden:
            raise _forbidden()
        ch = FakeChannel(self, self.next_id, name, category, topic)
        ch.overwrites = overwrites
        self.next_id += 1
        self.channels[ch.id] = ch
        self.created.append(ch)
        return ch


def run(coro):
    return asyncio.run(coro)


def _link(guild, fake, kind="team", item_id=1, category=None, uid=DID, user=None):
    user = member() if user is None else user
    return run(link_channel(guild, user, make_core(fake), uid, kind, item_id, category, "유달리"))


@pytest.fixture
def fake():
    return FakeCore([], orgs=[org(guild_id="1")])


def test_item_of_an_org_bound_to_another_guild_is_not_found(fake):
    """다른 길드에 묶인 조직의 팀·프로젝트는 이 길드에서 연결하지 않습니다."""
    fake.orgs_data = [org(guild_id="999")]
    g = FakeGuild()
    assert _link(g, fake) == "팀을(를) 찾을 수 없습니다."
    assert g.created == [] and fake.paths() == ["teams"]


def test_creates_links_and_replies(fake):
    g = FakeGuild()
    reply = _link(g, fake)
    ch = g.created[0]
    assert (ch.name, ch.topic, ch.category) == ("백엔드", "유달리 · 팀 백엔드", None)
    assert fake.channels["team"] == str(ch.id)
    assert reply == f"<#{ch.id}> 비공개 채널을 만들고 백엔드 팀에 연결했습니다."
    # 인가 선확인(같은 값 되쓰기) → 허용 집합 조회 → 생성 → 연결 확인(created)
    assert fake.paths() == ["teams", "teams/1/channel", "channel-check"]
    assert fake.calls[1][1]["channel_id"] == ""
    assert fake.calls[2][1]["created"] is True and fake.calls[2][1]["managed"] is True
    # 비공개: @everyone은 보기 거부, 봇과 허용 집합의 연결 계정만 허용
    ow = ch.overwrites
    assert ow[g.default_role].pair()[1].view_channel is True  # deny에 view_channel
    assert ow[g.me].view_channel is True and ow[g.members[111]].send_messages is True
    assert len(ow) == 3


def test_project_channel_uses_the_project_endpoints(fake):
    g = FakeGuild()
    reply = _link(g, fake, kind="project")
    assert g.created[0].name == "학식 API"
    assert fake.channels["project"] == str(g.created[0].id)
    assert "학식 API 프로젝트에 연결했습니다" in reply
    assert "projects/1/channel" in fake.paths() and "channel-check" in fake.paths()


def test_invoker_without_manage_channels_is_refused_before_core(fake):
    """봇이 권한을 대신 빌려주지 않는다. 이 거절은 core 왕복 없이 끝난다."""
    g = FakeGuild()
    assert _link(g, fake, user=member(manage_channels=False)) == NOT_A_MANAGER
    assert fake.calls == [] and g.created == []
    # DM 문맥·멤버 객체 없음 → 권한을 못 알아내면 거절(fail closed)
    assert _link(g, fake, user=SimpleNamespace(id=1)) == NOT_A_MANAGER
    assert _link(g, fake, user=SimpleNamespace()) == NOT_A_MANAGER
    assert can_manage_channels(discord.Object(id=1)) is False
    assert fake.calls == []
    # 봇 쪽 권한 부족은 다른 문구다 — 고치는 사람이 다르다
    assert _link(FakeGuild(forbidden=True), fake) == NO_PERMISSION


def test_non_admin_is_refused_before_anything_is_created(fake):
    fake.admin = False
    g = FakeGuild()
    assert _link(g, fake) == "조직 관리자만 할 수 있습니다."
    assert g.created == []


def test_unlinked_or_unknown_item_creates_nothing(fake):
    g = FakeGuild()
    assert _link(g, fake, item_id=99) == "팀을(를) 찾을 수 없습니다."
    fake.bot_status, fake.bot_detail = 404, "연결되지 않은 Discord 계정입니다."
    assert _link(g, fake, uid="424242") == "연결되지 않은 Discord 계정입니다."
    assert g.created == []


def test_second_call_does_not_create_a_duplicate(fake):
    g = FakeGuild()
    _link(g, fake)
    reply = _link(g, fake)
    assert len(g.created) == 1
    assert reply == f"백엔드 팀에는 이미 <#{g.created[0].id}> 채널이 연결되어 있습니다."


def test_deleted_channel_is_recreated(fake):
    g = FakeGuild()
    _link(g, fake)
    old = g.created[0].id
    del g.channels[old]  # 사람이 Discord에서 지웠다
    _link(g, fake)
    assert len(g.created) == 2
    assert fake.channels["team"] == str(g.created[1].id) != str(old)


def test_category_is_looked_up_by_name(fake):
    g = FakeGuild(categories=["팀"])
    assert _link(g, fake, category="없는것").startswith(
        "'없는것' 카테고리를 찾을 수 없습니다. 기존 카테고리를 선택하거나"
    )
    assert g.created == []
    _link(g, fake, category="팀")
    assert g.created[0].category.name == "팀"


def test_forbidden_becomes_a_permission_hint(fake):
    assert _link(FakeGuild(forbidden=True), fake) == NO_PERMISSION
    assert fake.channels["team"] == ""


def test_failed_writeback_rolls_the_channel_back(fake):
    fake.channel_save_fail = True
    g = FakeGuild()
    reply = _link(g, fake)
    assert len(g.created) == 1 and g.channels == {}  # 만들었다가 지웠다
    assert reply.endswith("만든 채널은 되돌렸습니다.")
    assert fake.channels["team"] == ""


def test_failed_rollback_is_reported_not_swallowed(fake, monkeypatch):
    fake.channel_save_fail = True
    g = FakeGuild()
    orig = g.create_text_channel

    async def create(*a, **kw):
        ch = await orig(*a, **kw)
        ch.delete_fails = True
        return ch

    g.create_text_channel = create
    reply = _link(g, fake)
    assert "직접 지워 주세요" in reply and f"<#{g.created[0].id}>" in reply
    assert g.created[0].id in g.channels
