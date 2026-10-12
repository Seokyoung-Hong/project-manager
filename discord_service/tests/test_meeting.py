"""회의 명령·넘겨받기 버튼. Node 음성 서비스와 core는 MockTransport 가짜, Discord는 SimpleNamespace 가짜."""

import asyncio
import json
from types import SimpleNamespace

import discord
import httpx
from conftest import FakeCore, make_core
from discord import app_commands

from discord_service import meeting, slash
from discord_service.messages import (
    MEETING_HOST_REJECTED,
    MEETING_HOST_REQUESTED,
    MEETING_NONE,
    MEETING_NOT_CONFIGURED,
    MEETING_STARTED,
    MEETING_STOPPED,
    MEETING_VOICE_DOWN,
    MEETING_VOICE_MISCONFIGURED,
)

GUILD = discord.Object(id=1)
HOST, OTHER, VC = "111", "222", "777"
NOTICE = "회의 진행자가 홍길동님에서 팀원님으로 바뀌었습니다."
PARTS = [{"discord_user_id": OTHER, "discord_name": "팀원", "joined_at": "t", "left_at": None}]


class FakeNode:
    def __init__(self, meeting=True, status=200, detail="x"):
        self.meeting = (
            {"recording_id": 5, "voice_channel_id": VC, "participants": PARTS} if meeting else None
        )
        self.status, self.detail = status, detail
        self.calls: list[tuple[str, str, dict | None, str]] = []
        self.timeouts: list = []

    def handler(self, request: httpx.Request) -> httpx.Response:
        body = json.loads(request.content) if request.content else None
        self.calls.append(
            (request.method, request.url.path, body, request.headers.get("Authorization"))
        )
        self.timeouts.append(request.extensions["timeout"]["read"])
        if request.method == "GET":
            return httpx.Response(200, json={"meeting": self.meeting})
        if self.status != 200:
            return httpx.Response(self.status, json={"detail": self.detail})
        return httpx.Response(201 if request.url.path == "/meetings" else 200, json={"ok": True})


def down(request):
    raise httpx.ConnectError("refused")


class MeetingCore(FakeCore):
    """core 회의 경로 셋. `answer_status`로 버튼 응답의 거절을 흉내 낸다."""

    def __init__(self):
        super().__init__([])
        self.answer_status = 200

    def _bot(self, cmd, body):
        self.calls.append((cmd, body))
        if cmd == "meetings/5/host":
            return httpx.Response(200, json={"id": 5, "channel_notice": NOTICE})
        if cmd == "meetings/5/host-requests":
            texts = {"approve_label": "승인", "reject_label": "거절", "mention": f"<@{HOST}> 님…"}
            return httpx.Response(200, json={"request": {"id": 3}, "texts": texts})
        if cmd == "meetings/5/host-requests/3":
            if self.answer_status == 403:
                detail = {
                    "meeting": "지금 회의 진행자만 넘겨받기 요청을 승인하거나 거절할 수 있습니다."
                }
                return httpx.Response(403, json={"detail": detail})
            req = {"id": 3, "requester_discord_user_id": OTHER}
            texts = (
                {"channel_notice": NOTICE}
                if body["approve"]
                else {"requester_notice": "홍길동님이 넘겨받기 요청을 거절했습니다."}
            )
            return httpx.Response(200, json={"request": req, "texts": texts})
        return super()._bot(cmd, body)


class FakeChannel:
    def __init__(self, fail=False):
        self.sent: list[tuple[str, object]] = []
        self.fail = fail

    async def send(self, content, *, allowed_mentions=None, view=None):
        if self.fail:
            raise discord.HTTPException(SimpleNamespace(status=403, reason="x"), "no")
        self.sent.append((content, view))


class FakeUser:
    def __init__(self, blocked=False):
        self.dms: list[str] = []
        self.blocked = blocked

    async def send(self, content, **_):
        if self.blocked:
            raise discord.Forbidden(SimpleNamespace(status=403, reason="x"), "dm closed")
        self.dms.append(content)


class FakeInteraction:
    def __init__(self, uid=HOST, data=None, channel=None, dm_blocked=False):
        self.user = SimpleNamespace(id=int(uid))
        self.guild_id = 1
        self.type = (
            discord.InteractionType.component
            if data
            else discord.InteractionType.application_command
        )
        self.data = data
        self.channel = channel or FakeChannel()
        self.requester = FakeUser(dm_blocked)
        self.client = SimpleNamespace(
            get_channel=lambda cid: self.channel if str(cid) == VC else None,
            fetch_user=self._fetch_user,
        )
        self.edited = []
        self.message = SimpleNamespace(edit=self._edit)
        self.deferred = None
        self.sent: list[tuple[str, bool]] = []
        self.response = SimpleNamespace(defer=self._defer)
        self.followup = SimpleNamespace(send=self._followup)

    async def _fetch_user(self, uid):
        assert str(uid) == OTHER
        return self.requester

    async def _edit(self, **kw):
        self.edited.append(kw)

    async def _defer(self, *, ephemeral=False, thinking=False):
        assert self.deferred is None
        self.deferred = ephemeral

    async def _followup(self, content, *, ephemeral=False, **_):
        assert self.deferred is not None
        self.sent.append((content, ephemeral))

    @property
    def reply(self):
        assert all(eph for _, eph in self.sent), "답은 전부 ephemeral"
        return "".join(c for c, _ in self.sent)


def run(coro):
    return asyncio.run(coro)


def voice(node=None, secret="s3cret", handler=None):
    transport = httpx.MockTransport(handler or (node.handler if node else down))
    return meeting.Voice("http://voice", secret, transport)


def tree_for(core, v):
    tree = app_commands.CommandTree(discord.Client(intents=discord.Intents.none()))
    cfg = SimpleNamespace(site_name="유달리", members_intent=False)
    slash.register(tree, GUILD, cfg, make_core(core), {}, voice=v)
    return tree


def call(name, *args, core=None, v=None, interaction=None, **kw):
    i = interaction or FakeInteraction()
    cmd = tree_for(core or MeetingCore(), v).get_command(name, guild=GUILD)
    run(cmd.callback(i, *args, **kw))
    return i


# --- /회의시작 ---


def test_start_posts_to_node_with_bearer_and_long_timeout():
    node = FakeNode()
    i = call("회의시작", v=voice(node), project=2, title="주간 회의")
    assert i.deferred is True and i.reply == MEETING_STARTED
    method, path, body, auth = node.calls[0]
    assert (method, path, auth) == ("POST", "/meetings", "Bearer s3cret")
    assert body == {
        "guild_id": "1",
        "discord_user_id": HOST,
        "project_id": 2,
        "team_id": None,
        "title": "주간 회의",
    }
    assert node.timeouts == [meeting.START_TIMEOUT]


def test_start_shows_node_refusal_verbatim():
    node = FakeNode(status=409, detail="음성 채널에 들어간 뒤 /회의시작 을 입력해 주세요.")
    assert call("회의시작", v=voice(node)).reply == node.detail


def test_start_unlinked_user_sees_core_link_hint():
    """기존 명령과 같은 흐름: core(Node가 그대로 전달)의 404 문구를 그대로 보인다."""
    node = FakeNode(
        status=404,
        detail="연결되지 않은 Discord 계정입니다. 웹 설정 → 프로필에서 연결 코드를 받으세요.",
    )
    assert call("회의시작", v=voice(node)).reply == node.detail


def test_node_down_and_not_configured():
    assert call("회의시작", v=voice()).reply == MEETING_VOICE_DOWN
    for name in ("회의시작", "회의종료", "회의받기"):
        node = FakeNode()
        assert call(name, v=voice(node, secret="")).reply == MEETING_NOT_CONFIGURED
        assert node.calls == []
    # cfg에 음성 설정이 없어도 등록·기동은 된다(거절만 한다)
    tree = app_commands.CommandTree(discord.Client(intents=discord.Intents.none()))
    slash.register(tree, GUILD, SimpleNamespace(site_name="x", members_intent=False), None, {})
    i = FakeInteraction()
    run(tree.get_command("회의종료", guild=GUILD).callback(i))
    assert i.reply == MEETING_NOT_CONFIGURED


# --- /회의종료 ---


def test_stop_finds_the_meeting_then_stops_it():
    node = FakeNode()
    assert call("회의종료", v=voice(node)).reply == MEETING_STOPPED
    assert [(m, p) for m, p, *_ in node.calls] == [
        ("GET", "/guilds/1/meeting"),
        ("POST", "/meetings/5/stop"),
    ]
    assert node.calls[1][2] == {"discord_user_id": HOST}
    assert node.timeouts == [meeting.TIMEOUT, meeting.TIMEOUT]


def test_stop_without_meeting_and_refusal_and_down():
    node = FakeNode(meeting=False)
    assert call("회의종료", v=voice(node)).reply == MEETING_NONE
    assert len(node.calls) == 1
    node = FakeNode(status=403, detail="진행자나 조직 관리자만 회의를 종료할 수 있습니다.")
    assert call("회의종료", v=voice(node)).reply == node.detail
    assert call("회의종료", v=voice()).reply == MEETING_VOICE_DOWN


# --- /회의진행자 ---


def test_host_transfer_calls_core_then_notices_channel_then_tells_node():
    node, core = FakeNode(), MeetingCore()
    i = call("회의진행자", core=core, v=voice(node), target=SimpleNamespace(id=int(OTHER)))
    assert core.calls == [
        (
            "meetings/5/host",
            {"discord_user_id": HOST, "target_discord_user_id": OTHER, "participants": PARTS},
        )
    ]
    assert i.channel.sent == [(NOTICE, None)]
    assert node.calls[-1][:3] == ("POST", "/meetings/5/host", {"discord_user_id": OTHER})
    assert i.reply == NOTICE


def test_host_transfer_refusal_and_no_meeting_and_down():
    core = FakeCore([])  # bot_status로 거절을 흉내 낸다
    core.bot_status, core.bot_detail = 403, {"meeting": "지금 진행자만 진행자를 넘길 수 있습니다."}
    node = FakeNode()
    i = call("회의진행자", core=core, v=voice(node), target=SimpleNamespace(id=2))
    assert i.reply == "지금 진행자만 진행자를 넘길 수 있습니다."
    assert i.channel.sent == [] and len(node.calls) == 1  # Node에는 GET만
    i = call("회의진행자", v=voice(FakeNode(meeting=False)), target=SimpleNamespace(id=2))
    assert i.reply == MEETING_NONE
    i = call("회의진행자", v=voice(), target=SimpleNamespace(id=2))
    assert i.reply == MEETING_VOICE_DOWN


# --- /회의받기 + 버튼 ---


def test_take_posts_mention_with_two_buttons_in_voice_chat():
    core = MeetingCore()
    i = call("회의받기", core=core, v=voice(FakeNode()), interaction=FakeInteraction(uid=OTHER))
    assert core.calls == [
        ("meetings/5/host-requests", {"discord_user_id": OTHER, "participants": PARTS})
    ]
    ((text, view),) = i.channel.sent
    assert text == f"<@{HOST}> 님…"
    assert [(b.label, b.custom_id) for b in view.children] == [
        ("승인", "meeting-host:5:3:1"),
        ("거절", "meeting-host:5:3:0"),
    ]
    assert i.reply == MEETING_HOST_REQUESTED


def test_take_channel_post_failure_is_reported():
    i = FakeInteraction(uid=OTHER, channel=FakeChannel(fail=True))
    i = call("회의받기", v=voice(FakeNode()), interaction=i)
    assert "올리지 못했습니다" in i.reply


def press(flag, core, node=None, **kw):
    data = {"custom_id": f"meeting-host:5:3:{flag}", "component_type": 2}
    i = FakeInteraction(data=data, **kw)
    assert meeting.is_host_button(i)
    run(meeting.on_host_button(i, make_core(core), voice(node or FakeNode())))
    return i


def test_button_approve_notices_channel_tells_node_and_removes_buttons():
    core, node = MeetingCore(), FakeNode()
    i = press(1, core, node)
    assert core.calls == [
        ("meetings/5/host-requests/3", {"discord_user_id": HOST, "approve": True})
    ]
    assert i.channel.sent == [(NOTICE, None)]
    assert node.calls[-1][:3] == ("POST", "/meetings/5/host", {"discord_user_id": OTHER})
    assert i.edited == [{"view": None}]
    assert i.reply == NOTICE


def test_button_reject_dms_requester_or_falls_back_to_channel():
    i = press(0, MeetingCore())
    assert i.requester.dms == ["홍길동님이 넘겨받기 요청을 거절했습니다."]
    assert i.channel.sent == [] and i.reply == MEETING_HOST_REJECTED
    i = press(0, MeetingCore(), dm_blocked=True)
    assert i.channel.sent == [(f"<@{OTHER}> 홍길동님이 넘겨받기 요청을 거절했습니다.", None)]


def test_button_403_is_shown_only_to_presser():
    core = MeetingCore()
    core.answer_status = 403
    node = FakeNode()
    i = press(1, core, node, uid=OTHER)
    assert i.deferred is True  # ephemeral
    assert i.reply == "지금 회의 진행자만 넘겨받기 요청을 승인하거나 거절할 수 있습니다."
    assert i.channel.sent == [] and i.edited == [] and node.calls == []


def test_other_components_are_not_ours():
    i = FakeInteraction(data={"custom_id": "something-else"})
    assert not meeting.is_host_button(i)
    assert not meeting.is_host_button(FakeInteraction())


def test_node_error_statuses_show_detail_except_401(caplog):
    for status in (400, 404, 409, 502, 403):
        node = FakeNode(status=status, detail=f"문장 {status}")
        assert call("회의시작", v=voice(node)).reply == f"문장 {status}"
    node = FakeNode(status=401, detail="unauthorized")
    with caplog.at_level("ERROR"):
        assert call("회의종료", v=voice(node)).reply == MEETING_VOICE_MISCONFIGURED
    assert "VOICE_CONTROL_SECRET" in caplog.text
