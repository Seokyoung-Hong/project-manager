"""2026-10-03 전체 검토에서 고친 권한·AI 정책·잠금 구멍의 회귀 테스트."""

import pytest
from django.utils import timezone

from accounts.models import ApiToken
from common.errors import ServiceError
from orgs.services import set_org_settings
from projects.models import Project
from projects.services import archive_project
from tasks.services import transition, update_task

pytestmark = pytest.mark.django_db


def _h(raw):
    return {"Authorization": f"Bearer {raw}"}


@pytest.fixture
def ai_admin(admin):
    return ApiToken.issue(admin, "Claude", "write")[1]  # for_ai 기본값 True


def test_member_cannot_make_themselves_project_owner(client, write_token, project, member):
    r = client.patch(
        f"/api/projects/{project.pk}",
        data={"version": project.version, "owner_ids": [member.pk]},
        content_type="application/json",
        headers=_h(write_token),
    )
    assert r.status_code == 400
    assert "owners" in r.json()["detail"]
    assert member not in project.owners.all()


def test_ai_disabled_blocks_team_and_project_writes(client, org, admin, ai_admin):
    set_org_settings(org, {"ai.enabled": False}, admin)
    teams = client.post(
        f"/api/orgs/{org.pk}/teams",
        data={"name": "AI팀"},
        content_type="application/json",
        headers=_h(ai_admin),
    )
    assert teams.status_code == 400 and "ai" in teams.json()["detail"]
    invite = client.post(
        f"/api/orgs/{org.pk}/invites",
        data={"days": 7},
        content_type="application/json",
        headers=_h(ai_admin),
    )
    assert invite.status_code == 400 and "ai" in invite.json()["detail"]
    proj = client.post(
        "/api/projects",
        data={"org_id": org.pk, "name": "AI 프로젝트", "owner_ids": [admin.pk]},
        content_type="application/json",
        headers=_h(ai_admin),
    )
    assert proj.status_code == 400 and "ai" in proj.json()["detail"]


def test_session_with_x_source_ai_is_treated_as_ai(client, org, admin, project):
    """WebMCP는 세션 쿠키로 /api를 부른다. X-Source: ai가 붙으면 AI 정책이 걸려야 한다."""
    set_org_settings(org, {"ai.enabled": False}, admin)
    client.force_login(admin)
    body = {"project_id": project.pk, "title": "브라우저 AI가 만든 태스크", "no_due_reason": "미정"}
    denied = client.post(
        "/api/tasks", data=body, content_type="application/json", headers={"X-Source": "ai"}
    )
    assert denied.status_code == 400
    human = client.post("/api/tasks", data=body, content_type="application/json")
    assert human.status_code == 201


def test_priority_cap_not_rechecked_when_priority_unchanged(org, admin, member, task):
    set_org_settings(org, {"task.priority_cap": 7}, admin)
    update_task(task, {"priority": 9}, actor=admin, source="web", expected_version=task.version)
    task.refresh_from_db()
    # 일반 멤버가 기한만 미뤄도 중요도 9 때문에 막히면 안 된다.
    update_task(
        task,
        {"due_date": task.due_date + timezone.timedelta(days=1)},
        actor=member,
        source="web",
        expected_version=task.version,
        reason="검토 일정 조정",
    )
    with pytest.raises(ServiceError):
        update_task(
            task, {"priority": 10}, actor=member, source="web", expected_version=task.version + 1
        )


def test_archive_bumps_db_version_not_stale_memory(project, admin):
    stale = Project.objects.get(pk=project.pk)  # version 1을 들고 있는 오래된 객체
    Project.objects.filter(pk=project.pk).update(version=5)
    archive_project(stale, actor=admin)
    assert Project.objects.get(pk=project.pk).version == 6


def test_cannot_reopen_task_in_archived_project(project, task, admin):
    transition(
        task, "cancelled", actor=admin, source="web", expected_version=task.version, reason="정리"
    )
    archive_project(project, actor=admin)
    task.refresh_from_db()
    with pytest.raises(ServiceError):
        transition(
            task, "todo", actor=admin, source="web", expected_version=task.version, reason="다시"
        )


def test_checklist_only_patch_checks_version(client, write_token, task):
    r = client.patch(
        f"/api/tasks/{task.pk}",
        data={"version": task.version + 5, "checklist": []},
        content_type="application/json",
        headers=_h(write_token),
    )
    assert r.status_code == 409


def test_signup_next_must_stay_on_site(client):
    r = client.post(
        "/signup?next=https://evil.example/",
        {
            "username": "new1",
            "display_name": "새 사람",
            "password1": "pw12345678",
            "password2": "pw12345678",
        },
    )
    assert r.status_code == 302
    assert "evil.example" not in r.headers["Location"]


@pytest.mark.parametrize("for_ai,source", [(True, "web"), (False, "mcp")])
def test_discord_control_preflight_blocks_ai_without_blocking_reads(
    client, org, admin, for_ai, source
):
    set_org_settings(org, {"ai.enabled": False}, admin)
    raw = ApiToken.issue(admin, "control", "write", for_ai=for_ai)[1]
    headers = {**_h(raw), "X-Source": source}
    response = client.post(f"/api/orgs/{org.pk}/discord-control-check", headers=headers)
    assert response.status_code == 400 and "ai" in response.json()["detail"]
    assert client.get(f"/api/orgs/{org.pk}", headers=headers).status_code == 200


def test_discord_control_preflight_requires_admin_and_write_token(client, org, admin, member):
    admin_raw = ApiToken.issue(admin, "control", "write")[1]
    response = client.post(f"/api/orgs/{org.pk}/discord-control-check", headers=_h(admin_raw))
    assert response.status_code == 200 and response.json() == {"ok": True}
    for user, scope, expected in [(member, "write", 400), (admin, "read", 403)]:
        raw = ApiToken.issue(user, "control", scope)[1]
        assert (
            client.post(f"/api/orgs/{org.pk}/discord-control-check", headers=_h(raw)).status_code
            == expected
        )
