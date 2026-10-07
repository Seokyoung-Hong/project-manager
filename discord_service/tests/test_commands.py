"""DM 평문 명령. 파싱과 문구만 검사한다 — 판단은 core의 services가 한다."""

from conftest import FakeCore, make_core, task

from discord_service.commands import NEED_NUMBER, handle, task_number
from discord_service.messages import HELP

DID = "111"
UNLINKED_DETAIL = "연결되지 않은 Discord 계정입니다. 웹 설정 → 프로필에서 연결 코드를 받으세요."


def _fake():
    return FakeCore([task(1, "2026-09-12"), task(12, "2026-09-12")])


def test_task_number_accepts_both_forms():
    assert task_number("12") == 12
    assert task_number("TASK-12") == 12
    assert task_number("task-12") == 12
    assert task_number("열두") is None
    assert task_number("") is None


def test_done_hits_the_same_call_either_way():
    fake = _fake()
    core = make_core(fake)
    first = handle(core, DID, "완료 12")
    fake.tasks[12]["status"] = "todo"  # 두 번째도 같은 경로를 타도록 되돌린다
    second = handle(core, DID, "완료 TASK-12")
    assert fake.paths() == ["tasks/12/done", "tasks/12/done"]
    assert fake.calls[0][1] == {"discord_user_id": DID}
    assert "TASK-12" in first and "완료로 바꿨습니다" in first
    assert second == first


def test_extend_splits_date_and_reason():
    fake = _fake()
    reply = handle(make_core(fake), DID, "연장 12 2026-09-20 QA 지연")
    assert fake.paths() == ["tasks/12/extend"]
    assert fake.calls[0][1] == {
        "discord_user_id": DID,
        "due_date": "2026-09-20",
        "reason": "QA 지연",
    }
    assert "2026-09-20" in reply


def test_extend_rejects_bad_date():
    fake = _fake()
    assert "2026-09-20" in handle(make_core(fake), DID, "연장 12 9월20일 사유")
    assert fake.calls == []


def test_today_renders_the_view():
    fake = _fake()
    reply = handle(make_core(fake), DID, "오늘")
    assert fake.paths() == ["today"]
    assert "2026-09-09" in reply
    assert "TASK-12" in reply
    assert "오늘 완료 1건" in reply


def test_link_sends_the_code():
    fake = _fake()
    reply = handle(make_core(fake), DID, "연결 A3F19C2D")
    assert fake.calls == [("link", {"code": "A3F19C2D", "discord_user_id": DID})]
    assert reply.startswith("홍길동 계정과 연결했습니다.")


def test_unlink_is_the_opt_out():
    fake = _fake()
    reply = handle(make_core(fake), DID, "연결해제")
    assert fake.paths() == ["unlink"]
    assert "DM도 멈춥니다" in reply


def test_unknown_text_gets_help():
    fake = _fake()
    assert handle(make_core(fake), DID, "안녕하세요?") == HELP
    assert handle(make_core(fake), DID, "도움") == HELP
    assert handle(make_core(fake), DID, "") == HELP
    assert fake.calls == []


def test_missing_number_is_guided():
    fake = _fake()
    assert handle(make_core(fake), DID, "완료") == NEED_NUMBER
    assert handle(make_core(fake), DID, "완료 열두개") == NEED_NUMBER
    assert fake.calls == []


def test_unlinked_account_is_told_to_link():
    """404는 쓰기 전에 막힌다. 태스크는 그대로다."""
    fake = _fake()
    fake.bot_status, fake.bot_detail = 404, UNLINKED_DETAIL
    reply = handle(make_core(fake), DID, "완료 12")
    assert reply == UNLINKED_DETAIL
    assert "연결" in reply
    assert fake.writes == []
    assert fake.tasks[12]["status"] == "todo"


def test_missing_detail_falls_back_to_link_hint():
    fake = _fake()
    fake.bot_status, fake.bot_detail = 404, ""
    assert "`연결`" in handle(make_core(fake), DID, "완료 12")


def test_conflict_is_not_retried():
    fake = _fake()
    fake.bot_status = 409
    reply = handle(make_core(fake), DID, "완료 12")
    assert reply == "방금 다른 곳에서 변경되었습니다. 다시 보내 주세요."
    assert len(fake.calls) == 1


def test_service_error_detail_is_passed_through():
    fake = _fake()
    fake.bot_status = 400
    fake.bot_detail = {"due_date": "현재 목표일보다 뒤의 날짜를 선택하세요."}
    reply = handle(make_core(fake), DID, "연장 12 2026-09-10 사유")
    assert reply == "현재 목표일보다 뒤의 날짜를 선택하세요."


def test_rate_limited_reply():
    fake = _fake()
    fake.bot_status = 429
    assert handle(make_core(fake), DID, "오늘") == "요청이 많습니다. 1분 뒤 다시 보내 주세요."


def test_forbidden_reply():
    fake = _fake()
    fake.bot_status = 403
    assert handle(make_core(fake), DID, "완료 12") == "권한이 없습니다."


def test_server_error_is_generic():
    fake = _fake()
    fake.bot_status = 500
    assert handle(make_core(fake), DID, "완료 12").startswith("지금은 처리할 수 없습니다")


def test_create_reply_adds_split_hint_only_when_core_flags_it():
    from discord_service.commands import SPLIT_HINT, create_reply

    class Core:
        def __init__(self, flag):
            self.flag = flag

        def create_task(self, did, fields):
            return {"task": task(3, "2026-09-12"), "multi_assignee": self.flag}

    assert create_reply(Core(True), DID, {}).endswith("\n" + SPLIT_HINT)
    assert SPLIT_HINT not in create_reply(Core(False), DID, {})
    assert "[사람별로 나누기]" in SPLIT_HINT


def test_task_line_shows_group_and_linked_projects():
    from discord_service.messages import task_line, team_task_line

    t = task(5, "2026-09-12") | {
        "group_id": 3,
        "linked_projects": [{"name": "홍보"}, {"name": "행사"}],
    }
    line = task_line(t)
    assert "할 일 5 ↳ TASK-3" in line and "\n  ↔ 홍보, 행사\n  http://pm/tasks/5" in line
    assert "↳ TASK-3" in team_task_line(t)
    plain = task_line(task(5, "2026-09-12"))
    assert "↳" not in plain and "↔" not in plain
