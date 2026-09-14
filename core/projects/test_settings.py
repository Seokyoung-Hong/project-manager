"""프로젝트·조직 권한 규칙 + 프로젝트 설정 화면·API (IMPL-PLAN-4 1단계, B/C/D/E)."""

from datetime import timedelta

import pytest
from cryptography.fernet import Fernet

from common.dates import today_kst
from common.errors import ServiceError
from github.models import RepoConnection
from orgs.services import (
    add_team_member,
    create_team,
    remove_team_member,
    set_org_settings,
    set_tags,
)
from projects.services import (
    archive_project,
    create_milestone,
    create_project,
    is_owner,
    restore_project,
    update_project,
)

pytestmark = pytest.mark.django_db


# ---- A: 프로젝트 규칙 ----


def test_edit_by_blocks_member_when_owner(org, admin, member, project):
    set_org_settings(org, {"project.edit_by": "owner"}, admin)
    with pytest.raises(ServiceError):
        update_project(project, {"purpose": "x"}, actor=member, expected_version=project.version)
    update_project(project, {"purpose": "x"}, actor=admin, expected_version=project.version)


def test_status_by_blocks_member_when_owner(org, admin, member, project):
    set_org_settings(org, {"project.status_by": "owner"}, admin)
    with pytest.raises(ServiceError):
        update_project(
            project, {"status": "on_hold"}, actor=member, expected_version=project.version
        )
    update_project(project, {"status": "on_hold"}, actor=admin, expected_version=project.version)


def test_owners_change_always_needs_owner_level(org, admin, member, project):
    """멤버는 조직 설정을 아무리 풀어도 관리자 지정을 못 한다(고정 규칙)."""
    set_org_settings(org, {"project.edit_by": "member", "project.status_by": "member"}, admin)
    with pytest.raises(ServiceError):
        update_project(
            project, {"owners": [member]}, actor=member, expected_version=project.version
        )
    update_project(project, {"owners": [member]}, actor=admin, expected_version=project.version)
    assert is_owner(member, project)


def test_archive_by_owner_lets_project_owner_archive(org, admin, member, project):
    set_org_settings(org, {"project.archive_by": "owner"}, admin)
    update_project(project, {"owners": [member]}, actor=admin, expected_version=project.version)
    project.refresh_from_db()
    p = archive_project(project, actor=member)
    assert p.is_archived
    p = restore_project(p, actor=member)
    assert not p.is_archived


def test_roadmap_by_blocks_member_when_owner(org, admin, member, project):
    set_org_settings(org, {"project.roadmap_by": "owner"}, admin)
    due = today_kst() + timedelta(days=1)
    with pytest.raises(ServiceError):
        create_milestone(project=project, name="m", target_date=due, actor=member)
    ms = create_milestone(project=project, name="m", target_date=due, actor=admin)
    assert ms.pk


def test_owner_required_blocks_emptying_owners(org, admin, project):
    set_org_settings(org, {"project.owner_required": True}, admin)
    with pytest.raises(ServiceError) as e:
        update_project(project, {"owners": []}, actor=admin, expected_version=project.version)
    assert "owners" in e.value.errors


def test_owner_required_blocks_create_without_owners(org, admin):
    set_org_settings(org, {"project.owner_required": True}, admin)
    with pytest.raises(ServiceError):
        create_project(org=org, name="관리자없음", actor=admin)
    create_project(org=org, name="관리자있음", actor=admin, owners=[admin])


def test_require_level_message_has_no_marker(org, member, project):
    with pytest.raises(ServiceError) as e:
        update_project(project, {"owners": []}, actor=member, expected_version=project.version)
    assert "[설정]" not in next(iter(e.value.errors.values()))


# ---- B: 조직 운영 ----


def test_tags_by_self_lets_member_edit_own_tags(org, admin, member):
    from orgs.models import OrgMembership

    membership = OrgMembership.objects.get(org=org, user=member)
    with pytest.raises(ServiceError):
        set_tags(membership, ["a"], member)
    set_org_settings(org, {"org.tags_by": "self"}, admin)
    membership = OrgMembership.objects.get(org=org, user=member)  # org 인스턴스 갱신
    set_tags(membership, ["a", "b"], member)
    membership.refresh_from_db()
    assert membership.tags == ["a", "b"]


def test_team_join_self_lets_member_join_and_leave(org, admin, member):
    team = create_team(org=org, name="백엔드", actor=admin)
    with pytest.raises(ServiceError):
        add_team_member(team, member, member)
    set_org_settings(org, {"org.team_join_self": True}, admin)
    add_team_member(team, member, member)
    assert team.members.filter(pk=member.pk).exists()
    remove_team_member(team, member, member)
    assert not team.members.filter(pk=member.pk).exists()


# ---- C: 저장소 규칙 권한 ----


@pytest.fixture
def gh(settings):
    settings.GITHUB_ENABLED = True
    settings.CREDENTIAL_KEY = Fernet.generate_key().decode()
    return settings


@pytest.fixture
def conn(gh, project, admin):
    return RepoConnection.objects.create(
        project=project, url="https://github.com/o/r.git", full_name="o/r", created_by=admin
    )


def test_repo_settings_refuses_plain_member(client, gh, conn, project, member):
    """rule_issue는 기본 True. 체크박스를 안 보내면 성공 시 False가 된다 — 거부되면 그대로 남는다."""
    client.force_login(member)
    r = client.post(f"/projects/{project.pk}/repo/settings", {}, follow=True)
    assert r.status_code == 200
    conn.refresh_from_db()
    assert conn.rule_issue is True  # 저장 안 됨, 안내만


def test_repo_disconnect_refuses_plain_member(client, gh, conn, project, member):
    client.force_login(member)
    client.post(f"/projects/{project.pk}/repo/disconnect", follow=True)
    assert RepoConnection.objects.filter(pk=conn.pk).exists()


def test_repo_settings_allows_admin(client, gh, conn, project, admin):
    client.force_login(admin)
    client.post(f"/projects/{project.pk}/repo/settings", {}, follow=True)
    conn.refresh_from_db()
    assert conn.rule_issue is False


# ---- D: 프로젝트 설정 화면 ----


def test_project_settings_page_member_reads_owner_writes(client, org, admin, member, project):
    client.force_login(member)
    r = client.get(f"/projects/{project.pk}/settings")
    assert r.status_code == 200
    assert "프로젝트 관리자만" in r.content.decode()
    r = client.post(
        f"/projects/{project.pk}/settings",
        {"use:task.priority_cap": "own", "task.priority_cap": "6"},
    )
    project.refresh_from_db()
    assert project.settings == {}  # 멤버는 못 바꾼다

    client.force_login(admin)
    r = client.post(
        f"/projects/{project.pk}/settings",
        {"use:task.priority_cap": "own", "task.priority_cap": "6", "governance_extra": "추가 규칙"},
    )
    assert r.status_code == 302
    project.refresh_from_db()
    assert project.settings == {"task.priority_cap": 6}
    assert project.governance_extra == "추가 규칙"


def test_project_settings_page_rejects_locked_key(client, org, admin, project):
    set_org_settings(org, {}, admin, locked=["task.priority_cap"])
    client.force_login(admin)
    r = client.post(
        f"/projects/{project.pk}/settings",
        {"use:task.priority_cap": "own", "task.priority_cap": "6"},
    )
    assert r.status_code == 200  # 오류로 다시 그림
    project.refresh_from_db()
    assert project.settings == {}


# ---- E: API ----


def test_project_settings_api_get_put(api, client, org, admin, project):
    r = api.get(f"/api/projects/{project.pk}/settings")
    assert r.status_code == 200
    body = r.json()
    assert body["values"] == {}
    assert body["effective"]["task.priority_cap"] == 0

    r = api.put(f"/api/projects/{project.pk}/settings", {"values": {"task.priority_cap": 8}})
    assert r.status_code == 400  # write 토큰의 주인은 member, 관리자가 아니다

    client.force_login(admin)
    r = client.put(
        f"/api/projects/{project.pk}/settings",
        {"values": {"task.priority_cap": 8}},
        content_type="application/json",
    )
    assert r.status_code == 200
    assert r.json()["values"] == {"task.priority_cap": 8}
    assert r.json()["effective"]["task.priority_cap"] == 8


def test_project_governance_extra_api(client, admin, project):
    client.force_login(admin)
    r = client.get(f"/api/projects/{project.pk}/governance-extra")
    assert r.status_code == 200 and r.json()["text"] == ""
    r = client.put(
        f"/api/projects/{project.pk}/governance-extra",
        {"text": "프로젝트 전용 규칙"},
        content_type="application/json",
    )
    assert r.status_code == 200
    assert r.json()["text"] == "프로젝트 전용 규칙"


def test_org_governance_api_enforced_and_project_text(client, org, admin, project):
    set_org_settings(org, {"task.priority_cap": 7}, admin)
    from projects.services import set_governance_extra

    set_governance_extra(project, "프로젝트 문단", actor=admin)
    client.force_login(admin)
    r = client.get(f"/api/orgs/{org.pk}/governance")
    assert r.status_code == 200
    assert any(e["key"] == "task.priority_cap" for e in r.json()["enforced"])
    r = client.get(f"/api/orgs/{org.pk}/governance?project_id={project.pk}")
    assert "프로젝트 문단" in r.json()["text"]
