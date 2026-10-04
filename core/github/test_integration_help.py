"""연동 실패의 사실 구분과 PM 작업을 반복하지 않는 복구 경계."""

import pytest
from django.test import Client

from github.client import GitHubError
from github.models import GitHubIdentity, GitHubInstallation, GitHubTeamLink, RepoConnection
from github.test_writes import _identity
from orgs.models import Invite, TeamMembership

pytestmark = pytest.mark.django_db


@pytest.fixture
def installed(gh, org, admin, member):
    GitHubInstallation.objects.create(
        org=org, installation_id=99, account_login="acme", installed_by=admin
    )
    _identity(admin, "admin-gh")
    _identity(member, "member-gh")
    return org


def test_oauth_missing_state_does_not_exchange_code(client, gh, admin, monkeypatch):
    client.force_login(admin)
    monkeypatch.setattr(
        "github.client.exchange_code", lambda _: pytest.fail("state 검증 전 외부 호출 금지")
    )
    response = client.get("/settings/github/callback?code=secret-code")
    assert response.status_code == 302
    assert client.session["integration_problems"]["oauth"]["stage"] == "콜백 상태 검증 실패"
    body = client.get("/help/integrations").content.decode()
    assert "secret-code" not in body
    assert "질문 프롬프트 복사" in body


def test_oauth_connected_but_repo_sync_failed(client, gh, admin, monkeypatch):
    client.force_login(admin)
    session = client.session
    session["gh_oauth_state"] = "valid-state"
    session.save()
    monkeypatch.setattr("github.client.exchange_code", lambda _: {"access_token": "secret-token"})
    monkeypatch.setattr("github.client.request", lambda *_: {"id": 1234, "login": "connected-user"})
    monkeypatch.setattr("github.services._store_tokens", lambda *_: None)

    def fail(*_):
        raise GitHubError(403, "secret-token")

    monkeypatch.setattr("github.services.sync_repos", fail)
    response = client.get(
        "/settings/github/callback?state=valid-state&code=secret-code", follow=True
    )
    body = response.content.decode()
    assert "계정은 연결됐지만 저장소 목록" in body
    assert admin.github.login == "connected-user"
    help_body = client.get("/help/integrations").content.decode()
    assert "HTTP 403" in help_body
    assert "secret-token" not in help_body and "secret-code" not in help_body


@pytest.mark.parametrize("mode", ["empty", "error"])
def test_repo_choices_success_empty_is_not_error(
    client, installed, project, admin, monkeypatch, mode
):
    client.force_login(admin)
    monkeypatch.setattr("github.client.installation_token", lambda _: "private-token")

    def response(*args, **kwargs):
        if mode == "error":
            raise GitHubError(403, "private-token")
        return {"repositories": []}

    monkeypatch.setattr("github.client.request", response)
    body = client.get(f"/projects/{project.pk}/repo").content.decode()
    assert ("조회는 성공했지만 앱에 보이는 저장소가 없습니다" in body) == (mode == "empty")
    assert ("저장소 후보 조회에 실패했습니다" in body) == (mode == "error")
    assert "private-token" not in body


def test_issue_sync_failure_records_status_and_preserves_tasks(
    client, installed, project, admin, monkeypatch
):
    conn = RepoConnection.objects.create(
        project=project, full_name="acme/repo", url="u", created_by=admin
    )
    client.force_login(admin)

    def fail(*_):
        raise GitHubError(0, "private details")

    GitHubIdentity.objects.filter(user=admin).update(repos=[conn.full_name])
    monkeypatch.setattr("github.services.sync_issues", fail)
    before = project.tasks.count()
    assert client.post(f"/projects/{project.pk}/issues/sync").status_code == 302
    assert project.tasks.count() == before
    diagnostic = client.session["integration_problems"]["issues"]
    assert diagnostic["status"] == "네트워크 연결 실패"
    assert conn.full_name in diagnostic["target"]


def _queue_member_failure(client, installed, team, admin, member, monkeypatch):
    GitHubTeamLink.objects.create(team=team, github_team_id=7, slug="old-name")
    client.force_login(admin)

    def fail(*_, **kwargs):
        raise GitHubError(403, "private details")

    monkeypatch.setattr("github.writes.set_gh_team_member", fail)
    assert client.post(f"/teams/{team.pk}/members", {"user": member.pk}).status_code == 302
    assert TeamMembership.objects.filter(team=team, user=member).exists()
    return client.session["github_write_retries"][0]


def test_retry_only_github_not_pm_and_uses_current_actor(
    client, installed, team, admin, member, monkeypatch
):
    row = _queue_member_failure(client, installed, team, admin, member, monkeypatch)
    monkeypatch.setattr("github.client.paginate", lambda *_: iter([{"id": 7, "slug": "new-name"}]))

    def absent(*args, **kwargs):
        raise GitHubError(404, "not found")

    monkeypatch.setattr("github.client.request", absent)
    calls = []
    monkeypatch.setattr(
        "github.writes.set_gh_team_member", lambda *args, **kwargs: calls.append((args, kwargs))
    )
    before = TeamMembership.objects.count()
    assert client.get(f"/help/integrations/github/retry/{row['id']}").status_code == 405
    assert (
        client.post(
            f"/help/integrations/github/retry/{row['id']}", {"login": "attacker"}
        ).status_code
        == 302
    )
    assert TeamMembership.objects.count() == before
    assert len(calls) == 1
    assert calls[0][0][2] == "member-gh"
    assert calls[0][1] == {"actor": admin, "add": True}
    assert client.session["github_write_retries"] == []


def test_retry_cancels_stale_pm_membership(client, installed, team, admin, member, monkeypatch):
    row = _queue_member_failure(client, installed, team, admin, member, monkeypatch)
    TeamMembership.objects.filter(team=team, user=member).delete()
    monkeypatch.setattr(
        "github.client.paginate", lambda *_: pytest.fail("stale 작업 외부 호출 금지")
    )
    assert client.post(f"/help/integrations/github/retry/{row['id']}").status_code == 302
    assert client.session["github_write_retries"] == []


def test_retry_denies_member_even_with_session_record(
    client, installed, team, admin, member, monkeypatch
):
    row = _queue_member_failure(client, installed, team, admin, member, monkeypatch)
    client.force_login(member)
    session = client.session
    session["github_write_retries"] = [row]
    session.save()
    assert client.post(f"/help/integrations/github/retry/{row['id']}").status_code == 404
    assert (
        f"/help/integrations/github/retry/{row['id']}"
        not in client.get("/help/integrations").content.decode()
    )


def test_retry_requires_csrf(client, installed, team, admin, member, monkeypatch):
    row = _queue_member_failure(client, installed, team, admin, member, monkeypatch)
    strict_client = Client(enforce_csrf_checks=True)
    strict_client.cookies = client.cookies
    assert strict_client.post(f"/help/integrations/github/retry/{row['id']}").status_code == 403


def test_invite_retry_does_not_create_another_pm_invite(client, installed, org, admin, monkeypatch):
    client.force_login(admin)

    def fail(*_, **kwargs):
        raise GitHubError(403, "private details")

    monkeypatch.setattr("github.writes.invite_to_org", fail)
    client.post(f"/orgs/{org.pk}/invites", {"days": 7, "gh_invite": "on", "gh_login": "octocat"})
    row = client.session["github_write_retries"][0]
    before = Invite.objects.count()
    monkeypatch.setattr("github.client.request", lambda *_: {"state": "pending", "role": "admin"})
    client.post(f"/help/integrations/github/retry/{row['id']}")
    assert Invite.objects.count() == before
    assert client.session["github_write_retries"] == []


def test_help_page_renders_topics_and_safe_prompt(client, gh, admin):
    from github.test_issues_view import _save_review_page

    client.force_login(admin)
    session = client.session
    session["integration_problems"] = {
        "issues": {
            "stage": "이슈 동기화",
            "status": "HTTP 403",
            "target": "acme/repo",
            "at": "2026-10-04T12:00:00Z",
        }
    }
    session.save()
    response = client.get("/help/integrations")
    assert response.status_code == 200
    for key in ("oauth", "repositories", "issues", "writes", "discord"):
        assert f'id="{key}"' in response.content.decode()
    _save_review_page("integration-help", response.content.decode())


def test_reconcile_preserves_maintainer_role(installed, team, admin, member, monkeypatch):
    from github import writes

    TeamMembership.objects.get_or_create(team=team, user=member)
    GitHubTeamLink.objects.create(team=team, github_team_id=7, slug="backend")
    calls = []

    def existing(method, path, token, **kwargs):
        calls.append(method)
        return {"state": "active", "role": "maintainer"}

    monkeypatch.setattr("github.client.request", existing)
    assert writes.reconcile_team(team, actor=admin) == (1, [])
    assert calls == ["GET"]


def test_reconcile_failure_queues_only_failed_members(
    client, installed, team, admin, member, monkeypatch
):
    TeamMembership.objects.get_or_create(team=team, user=member)
    GitHubTeamLink.objects.create(team=team, github_team_id=7, slug="backend")
    client.force_login(admin)

    def fail(*_, **kwargs):
        raise GitHubError(403, "private details")

    monkeypatch.setattr("github.writes.set_gh_team_member", fail)
    client.post(f"/teams/{team.pk}/github/reconcile")
    queue = client.session["github_write_retries"]
    assert len(queue) == 1 and queue[0]["user_id"] == member.pk
