import pytest

from mcp_server import permissions as perm
from mcp_server import server as s
from mcp_server.auth import current_token


@pytest.fixture(autouse=True)
def _clear_cache():
    """단계 판정은 60초 캐시된다 — 테스트끼리 섞이지 않게 매번 비운다."""
    perm._cache.clear()
    yield
    perm._cache.clear()


async def _names(token):
    tok = current_token.set(token)
    try:
        return {t.name for t in await s.mcp.list_tools()}
    finally:
        current_token.reset(tok)


WRITE_TOOLS = {n for n, need in perm.NEEDS.items() if need == "write"}
ADMIN_TOOLS = {n for n, need in perm.NEEDS.items() if need == "admin"}
READ_TOOLS = {n for n, need in perm.NEEDS.items() if need == "read"}


def test_needs_table_covers_every_tool():
    assert set(perm.NEEDS) == {
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
    assert ADMIN_TOOLS == {
        "create_team",
        "add_team_member",
        "remove_team_member",
        "delete_team",
        "delete_project",
        "delete_task",
        "create_invite",
        "revoke_invite",
        "update_governance",
        "update_org_settings",
    }


async def test_read_token_hides_write_and_admin_tools(fake_core):
    names = await _names("pm_read")
    assert names == READ_TOOLS
    assert not (names & WRITE_TOOLS)
    assert not (names & ADMIN_TOOLS)


async def test_non_admin_write_token_hides_only_admin_tools(fake_core):
    names = await _names("pm_good")  # member, 쓰기 가능
    assert names == READ_TOOLS | WRITE_TOOLS
    assert not (names & ADMIN_TOOLS)


async def test_admin_write_token_sees_everything(fake_core):
    names = await _names("pm_admin")
    assert names == set(perm.NEEDS)


async def test_no_token_shows_read_only():
    names = await _names(None)
    assert names == READ_TOOLS


async def test_dead_core_falls_back_to_read_only(fake_core, monkeypatch):
    def boom(self, path, **params):
        raise ConnectionError("core가 응답하지 않습니다")

    monkeypatch.setattr("mcp_server.core_client.Core.get", boom)
    names = await _names("pm_admin")
    assert names == READ_TOOLS


def test_levels_are_cached_for_60_seconds(fake_core, monkeypatch):
    calls = {"n": 0}
    real_probe = perm._probe

    def counted(token):
        calls["n"] += 1
        return real_probe(token)

    monkeypatch.setattr(perm, "_probe", counted)
    perm.levels_for("pm_admin")
    perm.levels_for("pm_admin")
    assert calls["n"] == 1
