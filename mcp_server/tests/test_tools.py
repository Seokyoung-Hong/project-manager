import json

import pytest

from mcp_server import server as s
from mcp_server.auth import current_token
from mcp_server.core_client import CoreError

TOOL_NAMES = {
    "get_guide",
    "list_orgs",
    "list_org_repos",
    "connect_repo",
    "delete_team",
    "delete_project",
    "delete_task",
    "list_projects",
    "get_project",
    "get_org",
    "list_discord_channels",
    "plan_project_channel_assignments",
    "assign_project_channel",
    "unlink_project_channel",
    "create_project_channel",
    "update_project",
    "create_project",
    "get_project_api_spec",
    "set_project_api_spec",
    "get_project_repo",
    "list_tasks",
    "get_task",
    "get_task_github",
    "get_task_history",
    "create_task",
    "update_task",
    "transition_task",
    "extend_task",
    "append_note",
    "get_org_status",
    "get_weekly_report_data",
    "list_members",
    "get_governance",
    "get_settings",
    "update_org_settings",
    "get_project_settings",
    "update_project_settings",
    "get_my_settings",
    "update_my_settings",
    "create_invite",
    "revoke_invite",
    "update_governance",
    "get_today",
    "add_today",
    "exclude_today",
    "restore_excluded_today",
    "reorder_today",
    "set_today_auto_pull",
    "list_teams",
    "create_team",
    "add_team_member",
    "remove_team_member",
    "set_project_teams",
    "list_docs",
    "get_doc",
    "create_doc",
    "update_doc",
    "search",
    "fetch",
}


def fn(name):
    """@mcp.tool()이 FunctionTool을 돌려주면 .fn으로 원함수를 꺼낸다."""
    obj = getattr(s, name)
    return getattr(obj, "fn", obj)


def last_body(fake):
    return json.loads(fake.calls[-1][3])


def test_list_orgs_sends_bearer_and_source(fake_core, with_token):
    out = fn("list_orgs")()
    assert out["orgs"][0]["name"] == "산돌이"
    headers = fake_core.calls[-1][2]
    assert headers["authorization"] == "Bearer pm_good"
    assert headers["x-source"] == "mcp"


def test_tool_without_token_fails(fake_core):
    with pytest.raises(PermissionError):
        fn("list_orgs")()


def test_bad_token_message(fake_core):
    tok = current_token.set("pm_bad")
    try:
        with pytest.raises(CoreError) as e:
            fn("list_orgs")()
        assert "유효하지 않습니다" in str(e.value)
    finally:
        current_token.reset(tok)


def test_transition_done_matches_api(fake_core, with_token):
    out = fn("transition_task")(1, "done", version=1)
    assert out["status"] == "done"
    assert out["version"] == 2
    assert last_body(fake_core) == {"status": "done", "version": 1, "reason": ""}


def test_transition_blocked_needs_reason(fake_core, with_token):
    with pytest.raises(CoreError) as e:
        fn("transition_task")(1, "blocked", version=1)
    assert "막힘 사유" in str(e.value)
    out = fn("transition_task")(1, "blocked", version=1, stop_reason="서류")
    assert out["status"] == "blocked"
    assert out["stop_reason"] == "서류"
    # core에는 예전 이름(reason)으로 간다. 오류가 말하는 stop_reason과 도구 인자 이름은 같아야 한다.
    assert last_body(fake_core)["reason"] == "서류"


def test_404_keeps_core_message(fake_core, with_token):
    with pytest.raises(CoreError) as e:
        fn("create_task")(project_id=999, title="x", due_date="2026-09-20")
    assert str(e.value) == "프로젝트를 찾을 수 없습니다."
    with pytest.raises(CoreError) as e:
        fn("add_team_member")(team_id=1, user_id=999)
    assert str(e.value) == "사용자를 찾을 수 없습니다."


def test_404_without_json_falls_back(fake_core, with_token):
    with pytest.raises(CoreError) as e:
        fn("get_project")(404)
    assert str(e.value) == "대상을 찾을 수 없습니다."


def test_update_conflict_message(fake_core, with_token):
    with pytest.raises(CoreError) as e:
        fn("update_task")(1, version=99, priority=8)
    msg = str(e.value)
    assert "먼저 수정했습니다" in msg
    assert "version=1" in msg


def test_update_clear_due(fake_core, with_token):
    fn("update_task")(1, version=1, clear_due_date=True, no_due_reason="미정")
    body = last_body(fake_core)
    assert body["due_date"] is None
    assert body["no_due_reason"] == "미정"


def test_update_clear_assignee(fake_core, with_token):
    fn("update_task")(1, version=1, clear_assignee=True)
    assert last_body(fake_core) == {"version": 1, "assignee_id": None}


def test_list_tasks_forwards_incremental_and_archived_filters(fake_core, with_token):
    fn("list_tasks")(updated_since="2026-09-22T12:00:00+09:00", include_archived=True)
    _, path, _, _ = fake_core.calls[-1]
    assert "updated_since=2026-09-22T12%3A00%3A00%2B09%3A00" in path
    assert "include_archived=True" in path


def test_append_note_appends_with_version(fake_core, with_token):
    fn("append_note")(1, "첫 메모")
    body = last_body(fake_core)
    assert body["notes"] == "첫 메모"
    assert body["version"] == 1

    fn("append_note")(1, "둘째")
    body = last_body(fake_core)
    assert body["notes"] == "첫 메모\n둘째"
    assert body["version"] == 2

    with pytest.raises(CoreError):
        fn("append_note")(1, "   ")


def test_create_task_idempotency_header(fake_core, with_token):
    fn("create_task")(1, "새 일", due_date="2026-09-20", request_id="r1")
    method, path, headers, content = fake_core.calls[-1]
    assert headers["idempotency-key"] == "r1"
    assert json.loads(content)["priority"] == 5


def test_search_fetch_shape(fake_core, with_token):
    results = fn("search")("메뉴")["results"]
    assert {"id", "title", "url"} <= set(results[0])
    doc = fn("fetch")("1")
    assert {"id", "title", "text", "url", "metadata"} <= set(doc)
    assert "진행 메모" in doc["text"]

    # 검색 결과에는 프로젝트 문서도 섞인다. 문서 id는 "doc-"으로 시작한다.
    doc_hit = next(r for r in results if r["id"].startswith("doc-"))
    assert "설계 결정" in doc_hit["title"]
    fetched = fn("fetch")(doc_hit["id"])
    assert "메뉴 누락을 줄인다" in fetched["text"]
    assert fetched["metadata"]["project_id"] == 1


def test_doc_write_tools(fake_core, with_token):
    made = fn("create_doc")(project_id=1, title="설계 결정", body_md="# 배경")
    assert made["title"] == "설계 결정" and made["updated_source"] == "mcp"

    fixed = fn("update_doc")(doc_id=7, version=2, body_md="고친 본문")
    assert fixed["body_md"] == "고친 본문" and fixed["version"] == 3

    # version이 어긋나면 core가 409를 준다 — 도구는 그 오류를 그대로 올린다
    with pytest.raises(CoreError):
        fn("update_doc")(doc_id=7, version=99, body_md="x")


def test_doc_tools(fake_core, with_token):
    items = fn("list_docs")(project_id=1)["items"]
    assert items[0]["title"] == "설계 결정"
    assert "body_md" not in items[0]  # 목록에 본문을 싣지 않는다
    assert fn("get_doc")(7)["body_md"].startswith("# 배경")


async def test_tool_names_registered(fake_core):
    """도구가 전부 등록돼 있다는 사실 자체는 그대로다.
    pm_admin은 admin+write 토큰이라 목록 필터를 통과해도 전부 보인다(필터가 실제로
    무엇을 거르는지는 test_permissions.py에서 검증한다)."""
    tok = current_token.set("pm_admin")
    try:
        tools = await s.mcp.list_tools()
    finally:
        current_token.reset(tok)
    assert {t.name for t in tools} == TOOL_NAMES
    assert len(TOOL_NAMES) == 59


def test_governance_tool(fake_core, with_token):
    out = fn("get_governance")(1)
    assert out["is_default"] is True and out["text"]


def test_settings_tool_is_read_only(fake_core, with_token):
    out = fn("get_settings")(1)
    assert out["values"]["task.default_priority"] == 5
    assert out["locked"] == []
    assert any(s["key"] == "task.default_priority" for s in out["specs"])
    assert not hasattr(s, "set_settings")
    assert not hasattr(s, "update_settings")


def test_list_org_repos(fake_core, with_token):
    rows = s.list_org_repos(1)
    assert rows[0]["full_name"] == "teamSANDOL/sandol-api"


def test_connect_repo(fake_core, with_token):
    got = s.connect_repo(1, "https://github.com/teamSANDOL/sandol-api")
    assert got["connected"] is True


def test_connect_repo_relays_the_refusal(fake_core, with_token):
    """조직이 막아 두면 도구는 그 문구를 그대로 돌려준다 — 우회하지 않는다."""
    with pytest.raises(Exception) as e:
        s.connect_repo(2, "https://github.com/teamSANDOL/sandol-api")
    assert "저장소 연결" in str(e.value)


def test_get_guide_returns_the_skill_document_without_frontmatter(with_token):
    """가이드는 스킬 파일 하나에서만 온다. 사본을 두면 한쪽만 고쳐진다."""
    from mcp_server.server import GUIDE, get_guide

    assert get_guide() == GUIDE
    assert GUIDE.startswith("# 산돌이 PM 사용법")
    assert "name: sandol-pm" not in GUIDE  # 머리말은 스킬 형식이라 떼고 낸다
    assert "get_governance" in GUIDE


def test_guide_is_listed_for_a_read_only_token():
    """읽기 토큰에도 보여야 한다 — 사용법을 못 읽으면 나머지 도구도 못 쓴다."""
    from mcp_server import permissions

    assert "get_guide" in permissions.NEEDS
    assert permissions.NEEDS["get_guide"] == "read"
