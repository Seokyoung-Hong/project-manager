"""V2-08 표에서 test_writes.py에 없는 나머지: 웹훅 방향, 뷰 단의 동작, 초대 옵션.

`client.request`는 monkeypatch로 막는다. 실제 GitHub는 부르지 않는다.
"""

import pytest
from django.utils import timezone

from github.conftest import signed
from github.models import (
    GitHubInstallation,
    GitHubTeamLink,
    RepoConnection,
    TaskGitLink,
)
from github.test_writes import _identity
from orgs.models import Team, TeamMembership
from tasks.services import transition

pytestmark = pytest.mark.django_db

HX = {"HX-Request": "true"}


@pytest.fixture
def calls(monkeypatch):
    """client.request가 받은 (method, path, token, body)를 모은다."""
    seen = []

    def fake(method, path, token, *, body=None, **kw):
        seen.append({"method": method, "path": path, "token": token, "body": body})
        if method == "POST" and path.endswith("/teams"):
            return {"id": 55, "slug": "backend", "name": "backend"}
        return {}

    monkeypatch.setattr("github.client.request", fake)

    def boom(iid):
        raise AssertionError("쓰기에 설치 토큰을 썼다")

    monkeypatch.setattr("github.client.installation_token", boom)
    return seen


@pytest.fixture
def installed(gh, org, admin):
    GitHubInstallation.objects.create(
        org=org, installation_id=99, account_login="acme", installed_by=admin
    )
    _identity(admin, "admin-gh")
    org.refresh_from_db()
    admin.refresh_from_db()
    return org


@pytest.fixture
def as_admin(client, admin):
    client.login(username="admin1", password="pw12345678")
    return client


# ---------- 초대 폼의 GitHub 초대 체크 ----------


def test_invite_to_org_optional(installed, admin, as_admin, calls):
    """체크 안 하면 GitHub를 부르지 않는다."""
    r = as_admin.post(f"/orgs/{installed.pk}/invites", {"days": 7})
    assert r.status_code == 302
    assert calls == []


def test_invite_to_org_when_checked(installed, admin, as_admin, calls):
    r = as_admin.post(
        f"/orgs/{installed.pk}/invites",
        {"days": 7, "gh_invite": "on", "gh_login": "new-hire"},
    )
    assert r.status_code == 302
    assert calls and calls[0]["method"] == "PUT"
    assert calls[0]["path"].endswith("/memberships/new-hire")


# ---------- 팀 이름 변경 동기화 ----------


def test_team_create_syncs_when_linked(installed, admin, team, as_admin, calls):
    """연결된 팀만 이름 변경이 GitHub에 반영된다."""
    GitHubTeamLink.objects.create(team=team, github_team_id=1, slug="backend")
    r = as_admin.post(f"/teams/{team.pk}/edit", {"name": "백엔드팀", "purpose": ""}, headers=HX)
    assert r.status_code == 204
    assert calls and calls[0]["method"] == "PATCH"
    assert calls[0]["path"].endswith("/teams/backend")


def test_team_rename_skips_unlinked(installed, admin, team, as_admin, calls):
    r = as_admin.post(f"/teams/{team.pk}/edit", {"name": "새이름", "purpose": ""}, headers=HX)
    assert r.status_code == 204
    assert calls == []


# ---------- 팀 멤버 추가/제거 동기화 ----------


def test_team_member_add_skips_unlinked_user(
    installed, admin, org, outsider, team, as_admin, calls
):
    """GitHub 미연결 멤버를 넣어도 PM에만 들어간다."""
    from orgs.models import OrgMembership

    OrgMembership.objects.create(org=org, user=outsider, role="member")
    GitHubTeamLink.objects.create(team=team, github_team_id=1, slug="backend")
    r = as_admin.post(f"/teams/{team.pk}/members", {"user": outsider.pk})
    assert r.status_code == 302
    assert team.members.filter(pk=outsider.pk).exists()
    assert calls == []  # outsider는 GitHub 미연결


def test_team_member_add_syncs_linked_user(installed, admin, member, team, as_admin, calls):
    """GitHub 연결된 사람은 팀에 넣으면 GitHub 팀 멤버십도 생긴다."""
    _identity(member, "member-gh")
    GitHubTeamLink.objects.create(team=team, github_team_id=1, slug="backend")
    team.members.remove(member)
    r = as_admin.post(f"/teams/{team.pk}/members", {"user": member.pk})
    assert r.status_code == 302
    assert calls and calls[0]["method"] == "PUT"
    assert calls[0]["path"].endswith("/teams/backend/memberships/member-gh")


# ---------- 연결 해제·팀 삭제는 GitHub 팀을 남긴다 ----------


def test_unlink_keeps_github_team(installed, admin, team, as_admin, calls):
    GitHubTeamLink.objects.create(team=team, github_team_id=1, slug="backend")
    r = as_admin.post(f"/teams/{team.pk}/github/unlink")
    assert r.status_code == 302
    assert not GitHubTeamLink.objects.filter(team=team).exists()
    assert calls == []  # DELETE를 부르지 않는다


def test_delete_team_keeps_github_team(installed, admin, team, as_admin, calls):
    GitHubTeamLink.objects.create(team=team, github_team_id=1, slug="backend")
    team_id = team.pk
    r = as_admin.post(f"/teams/{team_id}/delete")
    assert r.status_code == 302
    assert not Team.objects.filter(pk=team_id).exists()
    assert not [c for c in calls if c["method"] == "DELETE"]


# ---------- 웹훅: membership ----------


def test_membership_webhook_adds_pm_member(gh, client, org, admin, team):
    """GitHub에서 팀에 넣으면 그 사람이 조직 멤버일 때 PM 팀에도 들어온다."""
    GitHubTeamLink.objects.create(team=team, github_team_id=42, slug="backend")
    _identity(admin, "admin-gh")
    admin.refresh_from_db()
    payload = {
        "action": "added",
        "team": {"id": 42, "slug": "backend"},
        "member": {"id": admin.github.github_id},
        "sender": {},
        "organization": {},
    }
    r = signed(client, payload, "membership", "m-1")
    assert r.status_code in (200, 202)
    assert TeamMembership.objects.filter(team=team, user=admin).exists()


def test_membership_webhook_ignores_non_org_member(gh, client, org, outsider, team):
    """조직 멤버가 아니면 무시한다."""
    GitHubTeamLink.objects.create(team=team, github_team_id=42, slug="backend")
    _identity(outsider, "outsider-gh")
    outsider.refresh_from_db()
    payload = {
        "action": "added",
        "team": {"id": 42, "slug": "backend"},
        "member": {"id": outsider.github.github_id},
        "sender": {},
        "organization": {},
    }
    r = signed(client, payload, "membership", "m-2")
    assert r.status_code in (200, 202)
    assert not TeamMembership.objects.filter(team=team, user=outsider).exists()


def test_membership_webhook_removes_pm_member(gh, client, org, admin, team):
    GitHubTeamLink.objects.create(team=team, github_team_id=42, slug="backend")
    _identity(admin, "admin-gh")
    admin.refresh_from_db()
    TeamMembership.objects.get_or_create(team=team, user=admin)
    payload = {
        "action": "removed",
        "team": {"id": 42, "slug": "backend"},
        "member": {"id": admin.github.github_id},
        "sender": {},
        "organization": {},
    }
    r = signed(client, payload, "membership", "m-3")
    assert r.status_code in (200, 202)
    assert not TeamMembership.objects.filter(team=team, user=admin).exists()


# ---------- 웹훅: team ----------


def test_team_deleted_webhook_keeps_pm_team(gh, client, org, team):
    GitHubTeamLink.objects.create(team=team, github_team_id=42, slug="backend")
    payload = {"action": "deleted", "team": {"id": 42}, "organization": {}}
    r = signed(client, payload, "team", "t-1")
    assert r.status_code in (200, 202)
    assert not GitHubTeamLink.objects.filter(team=team).exists()
    assert Team.objects.filter(pk=team.pk).exists()


def test_team_edited_webhook_updates_slug(gh, client, org, team):
    GitHubTeamLink.objects.create(team=team, github_team_id=42, slug="old-slug", name="old")
    payload = {
        "action": "edited",
        "team": {"id": 42, "slug": "new-slug", "name": "새 이름"},
        "organization": {},
    }
    r = signed(client, payload, "team", "t-2")
    assert r.status_code in (200, 202)
    link = GitHubTeamLink.objects.get(team=team)
    assert link.slug == "new-slug"
    assert link.name == "새 이름"


# ---------- 태스크 패널: 이슈 닫기 버튼 ----------


@pytest.fixture
def repo_ready(installed, admin, task):
    """저장소 연결 + 접근 권한 + 열린 이슈가 연결된 태스크."""
    conn = RepoConnection.objects.create(
        project=task.project, url="u", full_name="o/r", created_by=admin
    )
    identity = admin.github
    identity.repos = ["o/r"]
    identity.repos_checked_at = timezone.now()  # refresh_github_access의 재확인을 막는다
    identity.save(update_fields=["repos", "repos_checked_at"])
    link = TaskGitLink.objects.create(
        task=task, connection=conn, issue_number=7, issue_state="open"
    )
    return task, link


def test_close_issue_button_only_when_done_and_open(installed, as_admin, repo_ready):
    task, link = repo_ready
    body = as_admin.get(f"/tasks/{task.pk}/panel").content.decode()
    assert "이슈 #7 닫기" not in body  # 아직 완료가 아니다

    transition(task, "done", actor=task.assignee, source="web", expected_version=task.version)
    body = as_admin.get(f"/tasks/{task.pk}/panel").content.decode()
    assert "이슈 #7 닫기" in body


def test_close_issue_view_explains_refusal(installed, as_admin, repo_ready, calls):
    """완료 전·이미 닫힘은 404 대신 패널에 이유를 적는다. 거부할 때는 GitHub를 부르지 않는다.

    패널은 HTMX가 갈아 끼우므로 404는 설명 없이 패널만 깨뜨린다.
    """
    task, link = repo_ready
    r = as_admin.post(f"/tasks/{task.pk}/git/issue/close")
    assert r.status_code == 200
    assert "태스크를 완료하기 전에는 이슈를 닫을 수 없습니다." in r.content.decode()
    assert calls == []

    transition(task, "done", actor=task.assignee, source="web", expected_version=task.version)
    r = as_admin.post(f"/tasks/{task.pk}/git/issue/close")
    assert r.status_code == 200
    link.refresh_from_db()
    assert link.issue_state == "closed"
    assert [c["method"] for c in calls] == ["PATCH"]

    r = as_admin.post(f"/tasks/{task.pk}/git/issue/close")
    assert r.status_code == 200
    assert "이미 닫힌 이슈입니다." in r.content.decode()
    assert len(calls) == 1  # 두 번째 거부에도 GitHub 쓰기는 없다


def test_link_rejects_github_team_used_by_another_team(gh, client, org, admin, team):
    """이미 다른 PM 팀에 연결된 GitHub 팀 id면 unique 충돌(500) 대신 안내만 한다."""
    other = Team.objects.create(org=org, name="프론트", created_by=admin)
    GitHubTeamLink.objects.create(team=other, github_team_id=55, slug="fe", name="fe")
    client.force_login(admin)
    r = client.post(f"/teams/{team.pk}/github/link", {"gh_team": "55:fe:fe"})
    assert r.status_code == 302
    assert not GitHubTeamLink.objects.filter(team=team).exists()
