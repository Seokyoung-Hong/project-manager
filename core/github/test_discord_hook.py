"""GitHub 알림 웹훅 → Discord 채널 자동 설정(IMPL-PLAN-8 §10-2, G5′).

고정하는 것: 설정·이벤트 수정·해제 흐름, 권한이 없을 때 버튼 대신 이유, 웹훅 토큰 비노출, 실행자 권한 거부.
"""

import json
import logging
from datetime import timedelta

import pytest
from django.core.cache import cache
from django.utils import timezone

from accounts.models import ApiToken, User
from common.errors import ServiceError
from common.logging import SecretFilter
from github import hooks
from github.crypto import encrypt
from github.models import GitHubIdentity, GitHubInstallation, RepoConnection
from orgs.channels import MANAGE_WEBHOOKS
from orgs.models import DiscordMemberPermission

pytestmark = pytest.mark.django_db

DC = "/api/integrations/discord"
WEBHOOK_TOKEN = "s3cr3t-Webhook_Token-abcdefghijklmnop"


@pytest.fixture
def gh_calls(monkeypatch):
    seen = type("Calls", (list,), {})()
    state = {"admin": True, "app_perm": "write", "fail_create": None}

    def fake(method, path, token, *, body=None, **kw):
        seen.append({"method": method, "path": path, "token": token, "body": body})
        if path.startswith("/app/installations/"):
            return {"permissions": {"repository_hooks": state["app_perm"]}, "events": []}
        if method == "GET" and path == "/repos/o/r":
            return {"permissions": {"admin": state["admin"]}}
        if method == "POST" and path == "/repos/o/r/hooks":
            if state["fail_create"]:
                raise state["fail_create"]
            return {"id": 42}
        return {}

    monkeypatch.setattr("github.client.request", fake)
    monkeypatch.setattr("github.client.app_jwt", lambda: "app-jwt")
    seen.state = state
    cache.clear()
    return seen


@pytest.fixture
def ready(gh, org, admin, project, gh_calls):
    """설정할 수 있는 상태: 길드·프로젝트 채널·봇 권한·실행자 Discord 권한·GitHub 연결·저장소."""
    org.discord_guild_id = "9001"
    org.discord_bot_permissions = MANAGE_WEBHOOKS
    org.save()
    project.discord_channel_id = "555"
    project.save()
    admin.discord_user_id, admin.discord_linked_at = "222", timezone.now()
    admin.save()
    DiscordMemberPermission.objects.create(
        org=org, user=admin, permissions=MANAGE_WEBHOOKS, reported_at=timezone.now()
    )
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
    RepoConnection.objects.create(
        project=project, url="https://github.com/o/r", full_name="o/r", created_by=admin
    )
    admin.refresh_from_db()
    project.refresh_from_db()
    return project


@pytest.fixture
def bot_auth(db):
    bot = User.objects.create_user("discord-bot", password="pw12345678", display_name="봇")
    _, raw = ApiToken.issue(bot, "봇", "bot")
    return {"Authorization": f"Bearer {raw}"}


def _hook(project):
    return RepoConnection.objects.get(project=project).discord_hook


def test_setup_then_bot_creates_and_github_registers_with_user_token(
    ready, admin, client, bot_auth, gh_calls
):
    hooks.request_setup(ready, ["push", "issues"], actor=admin)
    assert _hook(ready)["state"] == "pending"

    jobs = client.get(f"{DC}/github-hooks", headers=bot_auth).json()
    assert jobs == [
        {"project_id": ready.pk, "action": "create", "channel_id": "555", "webhook_id": ""}
    ]
    r = client.post(
        f"{DC}/github-hooks/{ready.pk}/created",
        json.dumps({"webhook_id": "777", "webhook_token": WEBHOOK_TOKEN}),
        content_type="application/json",
        headers=bot_auth,
    )
    assert r.json() == {"ok": True, "delete_webhook": False}
    assert WEBHOOK_TOKEN not in r.content.decode()

    post = next(c for c in gh_calls if c["method"] == "POST")
    assert post["token"] == "ghu_admin"  # 누른 사람의 사용자 토큰
    assert post["body"]["config"] == {
        "url": f"https://discord.com/api/webhooks/777/{WEBHOOK_TOKEN}/github",
        "content_type": "json",
    }
    assert post["body"]["events"] == ["push", "issues"]
    hook = _hook(ready)
    assert hook["state"] == "active" and hook["hook_id"] == 42 and hook["webhook_id"] == "777"
    assert WEBHOOK_TOKEN not in json.dumps(hook)  # 토큰은 저장하지 않는다
    assert client.get(f"{DC}/github-hooks", headers=bot_auth).json() == []


def test_events_update_and_remove_both_sides(ready, admin, client, bot_auth, gh_calls):
    hooks.request_setup(ready, ["push"], actor=admin)
    hooks.on_created(ready.pk, "777", WEBHOOK_TOKEN)

    hooks.update_events(ready, ["push", "release"], actor=admin)
    patch = next(c for c in gh_calls if c["method"] == "PATCH")
    assert patch["path"] == "/repos/o/r/hooks/42" and patch["body"]["events"] == ["push", "release"]

    hooks.remove(ready, actor=admin)
    assert any(c["method"] == "DELETE" and c["path"] == "/repos/o/r/hooks/42" for c in gh_calls)
    assert _hook(ready)["state"] == "removing"
    jobs = client.get(f"{DC}/github-hooks", headers=bot_auth).json()
    assert jobs[0]["action"] == "delete" and jobs[0]["webhook_id"] == "777"
    client.post(f"{DC}/github-hooks/{ready.pk}/removed", headers=bot_auth)
    assert _hook(ready) == {}


def test_github_refusal_becomes_visible_error_and_bot_deletes_webhook(ready, admin, gh_calls):
    from github.client import GitHubError

    hooks.request_setup(ready, ["push"], actor=admin)
    gh_calls.state["fail_create"] = GitHubError(404, "Not Found")
    assert hooks.on_created(ready.pk, "777", WEBHOOK_TOKEN) == {
        "ok": False,
        "delete_webhook": True,
    }
    hook = _hook(ready)
    assert hook["state"] == "error" and "Webhooks" in hook["error"]
    hooks.request_setup(ready, ["push"], actor=admin)  # 실패 뒤 다시 시도할 수 있다
    assert _hook(ready)["state"] == "pending"


def test_bot_failure_and_cancelled_pending(ready, admin):
    hooks.request_setup(ready, ["push"], actor=admin)
    hooks.on_failed(ready.pk, 'HTTP 403: {"message": "Missing Permissions", "code": 50013}')
    assert "웹후크 관리" in _hook(ready)["error"]
    hooks.request_setup(ready, ["push"], actor=admin)
    hooks.remove(ready, actor=admin)  # pending 취소
    assert _hook(ready) == {}
    assert hooks.on_created(ready.pk, "777", WEBHOOK_TOKEN)["delete_webhook"] is True


def test_invalid_webhook_values_from_bot_are_rejected(ready, admin, gh_calls):
    hooks.request_setup(ready, ["push"], actor=admin)
    assert hooks.on_created(ready.pk, "777/../x", WEBHOOK_TOKEN)["ok"] is False
    assert not any(c["method"] == "POST" for c in gh_calls)


def test_not_repo_admin_is_refused_with_fix(ready, admin, gh_calls):
    gh_calls.state["admin"] = False
    with pytest.raises(ServiceError) as e:
        hooks.request_setup(ready, ["push"], actor=admin)
    assert "admin" in " ".join(e.value.errors.values())
    assert _hook(ready) == {}


@pytest.mark.parametrize(
    "breaks, text",
    [
        ("channel", "Discord 프로젝트 채널이 없습니다"),
        ("bot", "Manage Webhooks"),
        ("app", "Webhooks 쓰기 권한"),
        ("github", "GitHub 계정이 연결되어 있지 않습니다"),
        ("discord_perm", "Discord 권한 확인 정보가 없습니다"),
    ],
)
def test_blockers_show_reason_instead_of_button(ready, admin, gh_calls, breaks, text, client):
    if breaks == "channel":
        ready.discord_channel_id = ""
        ready.save()
    elif breaks == "bot":
        ready.org.discord_bot_permissions = 1 << 4
        ready.org.save()
    elif breaks == "app":
        gh_calls.state["app_perm"] = "read"
    elif breaks == "github":
        GitHubIdentity.objects.filter(user=admin).delete()
        admin.refresh_from_db()
    elif breaks == "discord_perm":
        DiscordMemberPermission.objects.all().delete()
    ready.refresh_from_db()
    assert any(text in b["reason"] for b in hooks.blockers(admin, ready))
    with pytest.raises(ServiceError):
        hooks.request_setup(ready, ["push"], actor=admin)


def test_executor_permissions_are_checked(ready, admin, member):
    # PM: 프로젝트 설정 등급(기본 프로젝트 관리자) 밖이면 거절
    with pytest.raises(ServiceError):
        hooks.request_setup(ready, ["push"], actor=member)
    hooks.request_setup(ready, ["push"], actor=admin)
    hooks.on_created(ready.pk, "777", WEBHOOK_TOKEN)
    with pytest.raises(ServiceError):
        hooks.remove(ready, actor=member)
    # Discord: 실행자의 서버 권한에 웹후크 관리가 없으면 거절(fail closed)
    DiscordMemberPermission.objects.update(permissions=1 << 4)
    with pytest.raises(ServiceError) as e:
        hooks.remove(ready, actor=admin)
    assert "웹후크 관리" in " ".join(e.value.errors.values())
    DiscordMemberPermission.objects.update(reported_at=timezone.now() - timedelta(hours=1))
    with pytest.raises(ServiceError):
        hooks.update_events(ready, ["push"], actor=admin)
    assert _hook(ready)["state"] == "active"


def test_page_shows_button_then_masked_status(ready, admin, client, monkeypatch):
    monkeypatch.setattr("github.services.sync_issues_if_stale", lambda conn: None)
    monkeypatch.setattr("web.views.github._repo_teams", lambda conn: {"teams": [], "status": "ok"})
    client.force_login(admin)
    html = client.get(f"/projects/{ready.pk}/repo").content.decode()
    assert "GitHub 알림을 Discord 채널로 받기" in html

    r = client.post(
        f"/projects/{ready.pk}/repo/discord-hook", {"action": "setup", "events": ["push"]}
    )
    assert r.status_code == 302 and _hook(ready)["state"] == "pending"
    hooks.on_created(ready.pk, "777", WEBHOOK_TOKEN)
    html = client.get(f"/projects/{ready.pk}/repo").content.decode()
    assert "https://discord.com/api/webhooks/777/****/github" in html
    assert WEBHOOK_TOKEN not in html


def test_page_shows_reason_instead_of_button(ready, admin, client, monkeypatch):
    monkeypatch.setattr("github.services.sync_issues_if_stale", lambda conn: None)
    monkeypatch.setattr("web.views.github._repo_teams", lambda conn: {"teams": [], "status": "ok"})
    ready.org.discord_bot_permissions = 0
    ready.org.save()
    client.force_login(admin)
    html = client.get(f"/projects/{ready.pk}/repo").content.decode()
    assert "Manage Webhooks" in html
    assert "GitHub 알림을 Discord 채널로 받기" not in html


def test_webhook_url_is_masked_in_logs_and_errors():
    url = f"https://discord.com/api/webhooks/777/{WEBHOOK_TOKEN}/github"
    record = logging.LogRecord("x", logging.INFO, "", 0, "posting to %s", (url,), None)
    SecretFilter().filter(record)
    assert WEBHOOK_TOKEN not in record.getMessage()
    assert WEBHOOK_TOKEN not in hooks.mask(url)
