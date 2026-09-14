"""ai.* 정책 — source="mcp" 에만 걸린다 (IMPL-PLAN-4 §4.4, 2단계)."""

from datetime import timedelta

import pytest

from common.dates import today_kst
from common.errors import ServiceError
from orgs.services import add_team_member, create_team, set_org_settings
from tasks.services import create_task, extend_due, replace_checklist, transition, update_task

pytestmark = pytest.mark.django_db


def _due(n=3):
    return today_kst() + timedelta(days=n)


def test_ai_priority_cap_default_7_blocks_only_mcp(project, admin):
    with pytest.raises(ServiceError) as e:
        create_task(
            project=project, title="x", actor=admin, source="mcp", priority=8, due_date=_due()
        )
    assert "priority" in e.value.errors
    create_task(project=project, title="x", actor=admin, source="web", priority=8, due_date=_due())
    create_task(project=project, title="y", actor=admin, source="mcp", priority=7, due_date=_due())


@pytest.mark.parametrize("source", ["web", "api", "dc"])
def test_deny_does_not_touch_humans(org, admin, member, project, source):
    set_org_settings(org, {"ai.create_task": "deny", "ai.close_task": "deny"}, admin)
    t = create_task(project=project, title="x", actor=member, source=source, due_date=_due())
    transition(t, "done", actor=member, source=source, expected_version=t.version)


def test_each_action_denied_for_mcp(org, admin, member, project):
    t = create_task(project=project, title="x", actor=member, source="web", due_date=_due())
    keys = {
        "ai.create_task": lambda: create_task(
            project=project, title="n", actor=member, source="mcp", due_date=_due()
        ),
        "ai.edit_text": lambda: update_task(
            t, {"title": "z"}, actor=member, source="mcp", expected_version=t.version
        ),
        "ai.change_assignee": lambda: update_task(
            t, {"assignee": admin}, actor=member, source="mcp", expected_version=t.version
        ),
        "ai.change_due": lambda: extend_due(
            t, _due(9), "r", actor=member, source="mcp", expected_version=t.version
        ),
        "ai.change_priority": lambda: update_task(
            t, {"priority": 3}, actor=member, source="mcp", expected_version=t.version
        ),
        "ai.transition_open": lambda: transition(
            t, "doing", actor=member, source="mcp", expected_version=t.version
        ),
        "ai.close_task": lambda: transition(
            t, "done", actor=member, source="mcp", expected_version=t.version
        ),
        "ai.manage_teams": lambda: create_team(org=org, name="t", actor=admin, source="mcp"),
    }
    for key, call in keys.items():
        set_org_settings(org, {key: "deny"}, admin)
        t.refresh_from_db()
        with pytest.raises(ServiceError, match="AI"):
            call()
    set_org_settings(org, {}, admin)
    t.refresh_from_db()
    update_task(t, {"title": "z"}, actor=member, source="mcp", expected_version=t.version)


def test_reopen_and_checklist_and_enabled_off(org, admin, member, project):
    t = create_task(project=project, title="x", actor=member, source="web", due_date=_due())
    transition(t, "done", actor=member, source="web", expected_version=t.version)
    t.refresh_from_db()
    set_org_settings(org, {"ai.reopen_task": "deny"}, admin)
    with pytest.raises(ServiceError):
        transition(t, "todo", actor=member, source="mcp", expected_version=t.version)
    set_org_settings(org, {"ai.enabled": False}, admin)
    t.refresh_from_db()  # 캐시된 project.org 인스턴스 갱신
    with pytest.raises(ServiceError):
        replace_checklist(t, [{"text": "a"}], actor=member, source="mcp")
    replace_checklist(t, [{"text": "a"}], actor=member, source="web")
    team = create_team(org=org, name="t", actor=admin)
    with pytest.raises(ServiceError):
        add_team_member(team, member, admin, source="mcp")


def test_api_x_source_header_is_the_switch(api, org, admin, task):
    set_org_settings(org, {"ai.close_task": "deny"}, admin)
    body = {"status": "done", "version": task.version}
    r = api.post(f"/api/tasks/{task.pk}/transition", body, headers={"X-Source": "mcp"})
    assert r.status_code == 400 and "AI" in r.json()["detail"]["status"]
    r = api.post(f"/api/tasks/{task.pk}/transition", body)
    assert r.status_code == 200
