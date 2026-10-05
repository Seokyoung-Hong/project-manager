"""IMPL-PLAN-8 G9: GitHub 확장의 화면. 서비스는 앞 단계가 고정했고, 여기서는 화면이 그 값을 그리는지와
규칙 체크박스 저장(REPO_SETTING_FIELDS), 저장소 해제 때 Discord 알림 훅 정리를 고정한다."""

from datetime import timedelta

import pytest
from django.core.cache import cache
from django.utils import timezone

from github.crypto import encrypt
from github.models import (
    GitHubIdentity,
    GitHubInstallation,
    GitRelease,
    RepoConnection,
    TaskGitLink,
)
from projects.services import create_milestone
from tasks.models import ChangeLog
from tasks.services import create_task

pytestmark = pytest.mark.django_db


@pytest.fixture
def calls(monkeypatch):
    seen = []

    def fake(method, path, token, *, body=None, **kw):
        seen.append((method, path))
        if path.startswith("/app/installations/") and "access_tokens" not in path:
            return {
                "permissions": {"checks": "read", "repository_hooks": "write"},
                "events": ["check_suite"],
            }
        if "access_tokens" in path:
            return {"token": "inst", "expires_at": "2099-01-01T00:00:00Z"}
        return {}

    monkeypatch.setattr("github.client.request", fake)
    monkeypatch.setattr("github.client.app_jwt", lambda: "app-jwt")
    cache.clear()
    return seen


@pytest.fixture
def conn(gh, org, admin, project, calls):
    GitHubInstallation.objects.create(
        org=org, installation_id=99, account_login="o", installed_by=admin
    )
    GitHubIdentity.objects.create(
        user=admin,
        github_id=1,
        login="admin-gh",
        token_enc=encrypt("ghu_admin"),
        token_expires_at=timezone.now() + timedelta(hours=1),
        repos=["o/r"],
        repos_checked_at=timezone.now(),
    )
    return RepoConnection.objects.create(
        project=project, url="https://github.com/o/r", full_name="o/r", created_by=admin
    )


@pytest.fixture
def as_admin(client, admin):
    client.force_login(admin)
    return client


def test_repo_settings_saves_review_and_milestone_rules(as_admin, conn, project, monkeypatch):
    monkeypatch.setattr("web.views.github._repo_teams", lambda c: {"teams": [], "status": "ok"})
    monkeypatch.setattr("github.services.sync_issues_if_stale", lambda c: None)
    body = as_admin.get(f"/projects/{project.pk}/repo").content.decode()
    assert 'name="rule_review"' in body and 'name="rule_milestone"' in body
    assert 'name="rule_sync"' not in body  # §10-1: 이슈 양방향 동기화 없음
    as_admin.post(f"/projects/{project.pk}/repo/settings", {"rule_review": "on"})
    conn.refresh_from_db()
    assert conn.rule_review is True and conn.rule_milestone is False
    as_admin.post(f"/projects/{project.pk}/repo/settings", {"rule_milestone": "on"})
    conn.refresh_from_db()
    assert conn.rule_review is False and conn.rule_milestone is True
    settings_body = as_admin.get(f"/projects/{project.pk}/settings").content.decode()
    assert 'name="rule_review"' in settings_body and 'name="rule_milestone"' in settings_body


def test_panel_shows_draft_ci_reviews_and_continuation(as_admin, conn, project, admin, monkeypatch):
    monkeypatch.setattr("web.views.tasks.sync_issues_if_stale", lambda c: None)
    old = create_task(
        project=project, title="원 작업", actor=admin, source="web", no_due_reason="테스트"
    )
    new = create_task(
        project=project, title="이어진 작업", actor=admin, source="web", no_due_reason="테스트"
    )
    TaskGitLink.objects.create(
        task=new,
        connection=conn,
        pr_number=34,
        pr_state="open",
        pr_draft=True,
        ci_state="failure",
        ci_url="https://github.com/o/r/commit/abc/checks",
        reviews={"kim": "approved", "lee": "changes_requested", "park": "approved"},
    )
    ChangeLog.objects.create(
        target_type="task", target_id=old.pk, field="reopened_as", new_value=new.number, source="gh"
    )
    body = as_admin.get(f"/tasks/{new.pk}/panel").content.decode()
    assert "pr-draft" in body and "Draft" in body
    assert 'class="ci ci-failure" href="https://github.com/o/r/commit/abc/checks"' in body
    assert "리뷰 승인 2 · 변경 요청 1" in body
    assert f"{old.number}</a>에서 이어진 작업" in body
    old_body = as_admin.get(f"/tasks/{old.pk}/panel").content.decode()
    assert f"{new.number}</a>로 이어졌습니다" in old_body


def test_org_github_shows_capability_table(as_admin, conn, org, monkeypatch):
    body = as_admin.get(f"/orgs/{org.pk}/github").content.decode()
    assert "앱 권한 · 이벤트 점검" in body
    assert "CI 배지 · Checks" in body and "Commit statuses 읽기 권한" in body  # statuses 권한 없음
    assert "꺼진 기능이 있습니다" in body
    monkeypatch.setattr("github.services.app_capabilities", lambda o: None)
    assert "확인 불가" in as_admin.get(f"/orgs/{org.pk}/github").content.decode()


def test_disconnect_removes_github_hook_first(as_admin, conn, project, calls, monkeypatch):
    conn.discord_hook = {"state": "active", "hook_id": 42, "webhook_id": "777", "channel_id": "555"}
    conn.save()
    org = project.org
    org.discord_guild_id = "9001"
    org.save()
    calls.clear()
    # 실행자 Discord 권한 검사(require_discord)는 G5′ 테스트가 고정했다. 여기서는 정리 순서만 본다.
    monkeypatch.setattr("github.hooks._require", lambda actor, project: None)
    r = as_admin.post(f"/projects/{project.pk}/repo/disconnect", follow=True)
    assert ("DELETE", "/repos/o/r/hooks/42") in calls
    assert not RepoConnection.objects.filter(project=project).exists()
    assert "Discord 알림 웹훅도 지웠습니다" in r.content.decode()


def test_milestone_dialog_offers_github_checkbox_only_when_linked(
    as_admin, client, conn, org, member
):
    assert 'name="github"' in as_admin.get(f"/orgs/{org.pk}/milestones/new").content.decode()
    client.force_login(member)
    assert 'name="github"' not in client.get(f"/orgs/{org.pk}/milestones/new").content.decode()


def test_release_chip_on_roadmap_and_strip_on_shelf(as_admin, conn, org, project, admin):
    ms = create_milestone(
        project=project,
        name="v1.0",
        target_date=timezone.localdate() + timedelta(days=10),
        actor=admin,
    )
    GitRelease.objects.create(
        connection=conn,
        tag="v1.0",
        url="https://github.com/o/r/releases/v1.0",
        published_at=timezone.now(),
        milestone=ms,
    )
    road = as_admin.get(f"/orgs/{org.pk}/roadmap").content.decode()
    assert 'class="release-chip"' in road and "완료로 표시" in road
    shelf = as_admin.get(f"/projects/{project.pk}?part=shelf").content.decode()
    assert 'class="release-strip"' in shelf and "v1.0" in shelf
