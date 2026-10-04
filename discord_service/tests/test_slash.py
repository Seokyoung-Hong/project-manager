"""슬래시 명령 핸들러. 인터랙션을 가짜로 만들어 부른다 — Discord API에는 닿지 않는다.

검사하는 것: defer→followup 순서, 전부 ephemeral, DM 명령과 같은 core 호출·같은 문구,
자동완성의 인가(fail closed)·캐시·25개 상한.
"""

import asyncio
from types import SimpleNamespace

import discord
import httpx
from conftest import FakeCore, make_core, org, task
from discord import app_commands
from discord.app_commands import Choice

from discord_service import slash
from discord_service.commands import BAD_DATE, RATE, TOO_FAST, handle
from discord_service.messages import SLASH_HELP

DID = "111"
GUILD = discord.Object(id=1)
UNLINKED_DETAIL = "연결되지 않은 Discord 계정입니다. 웹 설정 → 프로필에서 연결 코드를 받으세요."


class FakeInteraction:
    def __init__(self, uid=DID, guild=None, channel_id=555):
        self.user = SimpleNamespace(id=int(uid))
        if guild is not None:  # 길드 인터랙션의 user는 권한이 실린 Member
            self.user.guild_permissions = discord.Permissions(manage_channels=True)
        self.guild = guild
        self.channel = SimpleNamespace(id=channel_id)
        self.deferred: bool | None = None  # defer(ephemeral=?) 값
        self.sent: list[tuple[str, bool]] = []  # (본문, ephemeral)
        self.response = SimpleNamespace(defer=self._defer, send_message=self._direct)
        self.followup = SimpleNamespace(send=self._followup)

    async def _defer(self, *, ephemeral=False):
        assert self.deferred is None, "defer는 한 번만"
        self.deferred = ephemeral

    async def _direct(self, content, *, ephemeral=False, **_):
        assert self.deferred is None, "defer 뒤에는 followup만 쓸 수 있다"
        self.sent.append((content, ephemeral))

    async def _followup(self, content, *, ephemeral=False, **_):
        assert self.deferred is not None, "followup 전에 defer해야 한다(3초 규칙)"
        self.sent.append((content, ephemeral))

    @property
    def reply(self) -> str:
        return "".join(c for c, _ in self.sent)


def _tree(fake: FakeCore, seen=None):
    client = discord.Client(intents=discord.Intents.none())
    tree = app_commands.CommandTree(client)
    cfg = SimpleNamespace(site_name="산돌이 업무", guild_id="1")
    slash.register(tree, GUILD, cfg, make_core(fake), {} if seen is None else seen)
    return tree


def _cmd(tree, name):
    return tree.get_command(name, guild=GUILD)


def _ac(tree, name, param):
    """Discord가 부르는 자동완성 콜백. 공개 Parameter는 bool만 주므로 내부 _params에서 꺼낸다."""
    p = next(p for p in _cmd(tree, name)._params.values() if p.display_name == param)
    return p.autocomplete


def run(coro):
    return asyncio.run(coro)


def _fake():
    return FakeCore([task(1, "2026-09-12"), task(12, "2026-09-12")])


def test_all_commands_are_guild_scoped_with_the_shared_vocabulary():
    tree = _tree(_fake())
    names = {c.name for c in tree.get_commands(guild=GUILD)}
    assert names == {
        "오늘",
        "완료",
        "연장",
        "연결",
        "연결해제",
        "도움",
        "태스크만들기",
        "태스크수정",
        "메모",
        "상태",
        "팀채널",
        "프로젝트채널",
        "알림채널",
        "요청",
        "요청수락",
        "요청거절",
        "요청완료",
        "요청목록",
    }
    assert tree.get_commands(guild=None) == []
    vocab = {"번호", "프로젝트", "팀", "담당자", "기한", "기한미정사유", "중요도", "상태", "사유"}
    vocab |= {"내용", "제목", "다음행동", "카테고리", "코드", "종류", "대상", "메모"}
    vocab |= {"기존카테고리", "새카테고리만들기", "기존채널"}
    for c in tree.get_commands(guild=GUILD):
        for p in c.parameters:
            assert p.display_name in vocab, (c.name, p.display_name)
    # 고정 집합은 Choice, 중요도는 Range — Discord가 먼저 막는다
    status = next(p for p in _cmd(tree, "상태").parameters if p.display_name == "상태")
    assert [ch.value for ch in status.choices] == [
        "todo",
        "doing",
        "paused",
        "blocked",
        "review",
        "done",
        "cancelled",
    ]
    pr = next(p for p in _cmd(tree, "태스크만들기").parameters if p.display_name == "중요도")
    assert (pr.min_value, pr.max_value, pr.required) == (1, 10, False)


def test_today_defers_ephemeral_then_answers_ephemeral():
    fake = _fake()
    i = FakeInteraction()
    run(_cmd(_tree(fake), "오늘").callback(i))
    assert i.deferred is True
    assert all(eph for _, eph in i.sent)
    assert fake.calls == [("today", {"discord_user_id": DID})]
    assert "TASK-12" in i.reply
    # DM 명령과 같은 문구
    assert i.reply == handle(make_core(_fake()), DID, "오늘")


def test_done_is_the_same_call_as_the_dm_command():
    fake = _fake()
    i = FakeInteraction()
    run(_cmd(_tree(fake), "완료").callback(i, number=12))
    assert fake.paths() == ["tasks/12/done"]
    assert fake.calls[0][1] == {"discord_user_id": DID}
    assert i.reply == "**TASK-12** 할 일 12 — 시작 전 → 완료로 바꿨습니다."


def test_extend_checks_the_date_before_calling_core():
    fake = _fake()
    tree = _tree(fake)
    i = FakeInteraction()
    run(_cmd(tree, "연장").callback(i, number=12, due="9월20일", reason="x"))
    assert (i.reply, fake.calls) == (BAD_DATE, [])
    i = FakeInteraction()
    run(_cmd(tree, "연장").callback(i, number=12, due="2026-09-20", reason="QA 지연"))
    assert fake.calls == [
        ("tasks/12/extend", {"discord_user_id": DID, "due_date": "2026-09-20", "reason": "QA 지연"})
    ]
    assert "2026-09-20" in i.reply


def test_link_unlink_help():
    fake = _fake()
    tree = _tree(fake)
    i = FakeInteraction()
    run(_cmd(tree, "연결").callback(i, code="A3F19C2D"))
    assert fake.calls == [("link", {"code": "A3F19C2D", "discord_user_id": DID})]
    assert i.reply.startswith("홍길동 계정과 연결했습니다.")
    i = FakeInteraction()
    run(_cmd(tree, "연결해제").callback(i))
    assert fake.paths()[-1] == "unlink" and "DM도 멈춥니다" in i.reply
    i = FakeInteraction()
    run(_cmd(tree, "도움").callback(i))
    assert i.sent == [(SLASH_HELP, True)]
    assert len(fake.calls) == 2  # 도움은 core를 부르지 않는다


def test_unlinked_user_in_a_guild_gets_the_link_hint_privately():
    fake = _fake()
    fake.bot_status, fake.bot_detail = 404, UNLINKED_DETAIL
    i = FakeInteraction(uid="424242")
    run(_cmd(_tree(fake), "완료").callback(i, number=12))
    assert i.sent == [(UNLINKED_DETAIL, True)]
    assert fake.writes == []


def test_rate_limit_is_shared_with_dm_and_answers_instead_of_ignoring():
    fake = _fake()
    seen = {}
    tree = _tree(fake, seen)
    for _ in range(RATE):
        run(_cmd(tree, "오늘").callback(FakeInteraction()))
    i = FakeInteraction()
    run(_cmd(tree, "오늘").callback(i))
    assert i.sent == [(TOO_FAST, True)]
    assert len(fake.calls) == RATE
    assert len(seen[DID]) == RATE + 1


# --- B단계 ---


def test_create_without_due_shows_the_core_message_verbatim():
    fake = _fake()
    i = FakeInteraction()
    run(_cmd(_tree(fake), "태스크만들기").callback(i, project=1, title="새 일"))
    assert i.reply == "기한이 없으면 사유를 입력하세요."
    assert fake.writes == []


def test_create_sends_only_the_given_fields():
    fake = _fake()
    tree = _tree(fake)
    i = FakeInteraction()
    run(
        _cmd(tree, "태스크만들기").callback(
            i, project=1, title="새 일", due="2026-09-20", priority=8, assignee=2
        )
    )
    assert fake.writes == [
        (
            "tasks",
            {
                "discord_user_id": DID,
                "project_id": 1,
                "title": "새 일",
                "due_date": "2026-09-20",
                "priority": 8,
                "assignee_id": 2,
            },
        )
    ]
    assert "TASK-100" in i.reply and "2026-09-20" in i.reply
    i = FakeInteraction()
    run(_cmd(tree, "태스크만들기").callback(i, project=1, title="x", due="어제"))
    assert i.reply == BAD_DATE


def test_update_note_status():
    fake = _fake()
    tree = _tree(fake)
    i = FakeInteraction()
    run(_cmd(tree, "태스크수정").callback(i, number=12))
    assert (i.reply, fake.calls) == ("바꿀 항목을 하나 이상 넣어 주세요.", [])
    i = FakeInteraction()
    run(_cmd(tree, "태스크수정").callback(i, number=12, priority=9, next_action="배포"))
    assert fake.calls[-1] == (
        "tasks/12/update",
        {"discord_user_id": DID, "priority": 9, "next_action": "배포"},
    )
    assert "수정했습니다" in i.reply
    i = FakeInteraction()
    run(_cmd(tree, "메모").callback(i, number=12, text="첫 메모"))
    assert fake.calls[-1] == ("tasks/12/note", {"discord_user_id": DID, "text": "첫 메모"})
    i = FakeInteraction()
    run(
        _cmd(tree, "상태").callback(
            i, number=12, status=Choice(name="막힘", value="blocked"), reason="API 대기"
        )
    )
    assert fake.calls[-1] == (
        "tasks/12/status",
        {"discord_user_id": DID, "status": "blocked", "reason": "API 대기"},
    )
    assert i.reply == "**TASK-12** 할 일 12 — 시작 전 → 막힘(으)로 바꿨습니다."
    assert all(eph for x in (i,) for _, eph in x.sent)


# --- 자동완성 ---


def test_task_autocomplete_shows_label_and_submits_id():
    fake = _fake()
    tree = _tree(fake)
    got = run(_ac(tree, "완료", "번호")(FakeInteraction(), ""))
    assert [(c.name, c.value) for c in got] == [("TASK-1 할 일 1", 1), ("TASK-12 할 일 12", 12)]
    got = run(_ac(tree, "메모", "번호")(FakeInteraction(), "12"))
    assert [c.value for c in got] == [12]
    got = run(_ac(tree, "상태", "번호")(FakeInteraction(), "할 일 1"))  # 부분 일치
    assert [c.value for c in got] == [1, 12]
    assert fake.paths() == ["mytasks"]  # 타자 세 번에 core 호출은 한 번(캐시)


def test_other_autocompletes_use_their_own_lists():
    tree = _tree(_fake())
    assert [
        c.name for c in run(_ac(tree, "태스크만들기", "프로젝트")(FakeInteraction(), "산"))
    ] == ["산돌이 봇"]
    assert [c.value for c in run(_ac(tree, "팀채널", "팀")(FakeInteraction(), ""))] == [1]
    assert [c.name for c in run(_ac(tree, "태스크수정", "담당자")(FakeInteraction(), "팀"))] == [
        "팀원"
    ]


def test_autocomplete_fails_closed_and_does_not_hammer_core():
    fake = _fake()
    fake.bot_status, fake.bot_detail = 404, UNLINKED_DETAIL
    tree = _tree(fake)
    for text in ("", "ㅎ", "할", "할 "):
        assert run(_ac(tree, "완료", "번호")(FakeInteraction(uid="424242"), text)) == []
    assert len(fake.calls) == 1  # 미연결도 30초에 한 번만 묻는다


def test_autocomplete_timeout_and_transport_errors_give_empty_uncached(monkeypatch):
    class Slow:
        calls = 0

        def mytasks(self, uid):
            Slow.calls += 1
            import time

            time.sleep(0.05)
            return [task(1, None)]

    monkeypatch.setattr(slash, "AUTOCOMPLETE_TIMEOUT", 0.001)
    cache = {}
    assert run(slash.cached(Slow(), cache, DID, "mytasks")) == []
    assert cache == {}

    class Down:
        def mytasks(self, uid):
            raise httpx.ConnectError("down")

    assert run(slash.cached(Down(), cache, DID, "mytasks")) == []
    assert cache == {}  # 일시 장애는 캐시하지 않는다 — 복구되면 바로 다시 뜬다


def test_autocomplete_caps_at_25_selectable_choices():
    fake = FakeCore([task(i, None) for i in range(1, 41)])
    got = run(_ac(_tree(fake), "완료", "번호")(FakeInteraction(), ""))
    assert len(got) == 25
    assert all(isinstance(c.value, int) for c in got)  # 안내용 가짜 항목 없음
    got = run(_ac(_tree(fake), "완료", "번호")(FakeInteraction(), "TASK-3"))
    assert [c.value for c in got] == [3, 30, 31, 32, 33, 34, 35, 36, 37, 38, 39]


def test_channel_commands_are_guild_only_and_check_the_invoker_first():
    tree = _tree(_fake())
    for name in ("팀채널", "프로젝트채널"):
        assert _cmd(tree, name).guild_only is True
    fake = _fake()
    tree = _tree(fake)
    i = FakeInteraction(guild=SimpleNamespace(categories=[], get_channel=lambda _: None))
    i.user.guild_permissions = discord.Permissions.none()
    run(_cmd(tree, "팀채널").callback(i, team=1))
    assert i.sent == [("Discord 서버에서 채널 관리 권한이 있어야 합니다.", True)]
    assert fake.calls == []
    i = FakeInteraction()  # DM: guild 없음 → 등록상 불가능하지만 코드도 거절한다
    run(_cmd(tree, "팀채널").callback(i, team=1))
    assert i.sent == [("서버 채널에서 실행해 주세요.", True)]
    assert fake.calls == []


def test_alert_channel_requires_manage_channels_before_calling_core():
    fake = _fake()
    tree = _tree(fake)
    i = FakeInteraction(guild=SimpleNamespace(id=1))
    i.user.guild_permissions = discord.Permissions.none()
    run(_cmd(tree, "알림채널").callback(i))
    assert i.sent == [("Discord 서버에서 채널 관리 권한이 있어야 합니다.", True)]
    assert fake.calls == []


def test_alert_channel_refuses_when_guild_is_unbound():
    fake = _fake()
    fake.orgs_data = [org(1, guild_id="999999")]  # GUILD(id=1)과 다른 길드에만 바인딩됨
    tree = _tree(fake)
    i = FakeInteraction(guild=SimpleNamespace(id=1))
    run(_cmd(tree, "알림채널").callback(i))
    assert i.sent == [("이 서버는 아직 조직에 연결되지 않았습니다.", True)]
    assert fake.calls == []


def test_alert_channel_saves_the_invoking_channel():
    fake = _fake()
    fake.orgs_data = [org(1, guild_id="1")]
    tree = _tree(fake)
    i = FakeInteraction(guild=SimpleNamespace(id=1), channel_id=777)
    run(_cmd(tree, "알림채널").callback(i))
    assert fake.calls == [
        ("orgs/channel", {"discord_user_id": DID, "guild_id": "1", "channel_id": "777"})
    ]
    assert i.reply == "이 채널(<#777>)을 이 서버 조직의 알림 채널로 저장했습니다."


def test_alert_channel_relays_core_refusal_for_non_org_admin():
    fake = _fake()
    fake.orgs_data = [org(1, guild_id="1")]
    fake.admin = False
    tree = _tree(fake)
    i = FakeInteraction(guild=SimpleNamespace(id=1))
    run(_cmd(tree, "알림채널").callback(i))
    assert i.reply == "조직 관리자만 할 수 있습니다."


def test_dm_commands_still_work_unchanged():
    fake = _fake()
    assert "완료로 바꿨습니다" in handle(make_core(fake), DID, "완료 12")
    assert fake.paths() == ["tasks/12/done"]
