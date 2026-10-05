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


def _created(project, webhook_id="777"):
    """봇이 지금 세대(job)로 보고한다."""
    return hooks.on_created(project.pk, _hook(project)["job"], webhook_id, WEBHOOK_TOKEN)


def test_setup_then_bot_creates_and_github_registers_with_user_token(
    ready, admin, client, bot_auth, gh_calls
):
    hooks.request_setup(ready, ["push", "issues"], actor=admin)
    assert _hook(ready)["state"] == "pending"

    jobs = client.get(f"{DC}/github-hooks", headers=bot_auth).json()
    job = _hook(ready)["job"]
    assert jobs == [
        {
            "project_id": ready.pk,
            "action": "create",
            "job": job,
            "channel_id": "555",
            "webhook_id": "",
        }
    ]
    r = client.post(
        f"{DC}/github-hooks/{ready.pk}/created",
        json.dumps({"job": job, "webhook_id": "777", "webhook_token": WEBHOOK_TOKEN}),
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
    _created(ready)

    hooks.update_events(ready, ["push", "release"], actor=admin)
    patch = next(c for c in gh_calls if c["method"] == "PATCH")
    assert patch["path"] == "/repos/o/r/hooks/42" and patch["body"]["events"] == ["push", "release"]

    hooks.remove(ready, actor=admin)
    assert any(c["method"] == "DELETE" and c["path"] == "/repos/o/r/hooks/42" for c in gh_calls)
    assert _hook(ready)["state"] == "removing"
    jobs = client.get(f"{DC}/github-hooks", headers=bot_auth).json()
    assert jobs[0]["action"] == "delete" and jobs[0]["webhook_id"] == "777"
    client.post(
        f"{DC}/github-hooks/{ready.pk}/removed",
        json.dumps({"webhook_id": "777"}),
        content_type="application/json",
        headers=bot_auth,
    )
    assert _hook(ready) == {}


def _delete_jobs():
    return [j["webhook_id"] for j in hooks.pending_jobs() if j["action"] == "delete"]


def test_github_refusal_becomes_visible_error_and_webhook_goes_to_cleanup(ready, admin, gh_calls):
    from github.client import GitHubError

    hooks.request_setup(ready, ["push"], actor=admin)
    gh_calls.state["fail_create"] = GitHubError(404, "Not Found")
    assert _created(ready) == {"ok": False, "delete_webhook": False}
    hook = _hook(ready)
    assert hook["state"] == "error" and "Webhooks" in hook["error"]
    assert _delete_jobs() == ["777"]  # 봇이 다음 틱에 Discord 웹훅을 지운다
    hooks.on_removed(ready.pk, "777")
    assert _delete_jobs() == []
    hooks.request_setup(ready, ["push"], actor=admin)  # 실패 뒤 다시 시도할 수 있다
    assert _hook(ready)["state"] == "pending"


def test_bot_failure_and_cancelled_pending(ready, admin):
    hooks.request_setup(ready, ["push"], actor=admin)
    job = _hook(ready)["job"]
    hooks.on_failed(ready.pk, "other-job", "HTTP 403")  # 다른 세대의 실패 보고는 무시
    assert _hook(ready)["state"] == "pending"
    hooks.on_failed(ready.pk, job, 'HTTP 403: {"message": "Missing Permissions", "code": 50013}')
    assert "웹후크 관리" in _hook(ready)["error"]
    hooks.request_setup(ready, ["push"], actor=admin)
    job = _hook(ready)["job"]
    hooks.remove(ready, actor=admin)  # pending 취소
    assert _hook(ready) == {}
    assert hooks.on_created(ready.pk, job, "777", WEBHOOK_TOKEN)["ok"] is False
    assert _hook(ready)["cleanup"][0]["webhook_id"] == "777"
    assert _delete_jobs() == ["777"]


def test_invalid_webhook_values_from_bot_are_rejected(ready, admin, gh_calls):
    hooks.request_setup(ready, ["push"], actor=admin)
    job = _hook(ready)["job"]
    assert hooks.on_created(ready.pk, job, "777/../x", WEBHOOK_TOKEN)["ok"] is False
    assert hooks.on_created(ready.pk, job, "777", "bad token/..")["ok"] is False
    assert not any(c["method"] == "POST" for c in gh_calls)


# ---------- Sol 검토 결함 5·6: 세대·경합·응답 유실 ----------


def test_cancel_during_github_post_is_not_revived_and_both_hooks_are_cleaned(
    ready, admin, gh_calls, monkeypatch
):
    hooks.request_setup(ready, ["push"], actor=admin)
    real = hooks.client.request

    def cancel_midway(method, path, token, **kw):
        if method == "POST":
            hooks.remove(ready, actor=admin)  # GitHub 등록 진행 중 취소
        return real(method, path, token, **kw)

    monkeypatch.setattr(hooks.client, "request", cancel_midway)
    assert _created(ready)["ok"] is False
    hook = _hook(ready)
    assert hook.get("state") is None  # 되살아나지 않는다
    assert hook["cleanup"] == [{"webhook_id": "777", "hook_id": 42, "by": admin.pk}]
    # 보상: 다음 틱에 GitHub 훅을 지우고 Discord 웹훅 삭제를 봇에 준다
    assert _delete_jobs() == ["777"]
    assert any(c["method"] == "DELETE" and c["path"] == "/repos/o/r/hooks/42" for c in gh_calls)
    hooks.on_removed(ready.pk, "777")
    assert _hook(ready) == {}


def test_cleanup_survives_github_delete_failure_and_retries(ready, admin, gh_calls, monkeypatch):
    from github.client import GitHubError

    hooks.request_setup(ready, ["push"], actor=admin)
    job = _hook(ready)["job"]
    real = hooks.client.request
    state = {"fail": True}

    def flaky(method, path, token, **kw):
        if method == "POST":
            hooks.remove(ready, actor=admin)
        if method == "DELETE" and state["fail"]:
            raise GitHubError(502, "Bad Gateway")
        return real(method, path, token, **kw)

    monkeypatch.setattr(hooks.client, "request", flaky)
    hooks.on_created(ready.pk, job, "777", WEBHOOK_TOKEN)
    assert _delete_jobs() == []  # GitHub 쪽이 남아 있으면 Discord도 아직 지우지 않는다
    assert _hook(ready)["cleanup"][0]["hook_id"] == 42
    state["fail"] = False
    assert _delete_jobs() == ["777"]


def test_stale_callback_after_cancel_and_resetup_is_ignored(ready, admin, gh_calls):
    hooks.request_setup(ready, ["push"], actor=admin)
    old_job = _hook(ready)["job"]
    hooks.remove(ready, actor=admin)
    hooks.request_setup(ready, ["push"], actor=admin)
    new_job = _hook(ready)["job"]
    assert new_job != old_job
    assert hooks.on_created(ready.pk, old_job, "666", WEBHOOK_TOKEN)["ok"] is False
    hook = _hook(ready)
    assert hook["state"] == "pending" and hook["job"] == new_job
    assert not any(c["method"] == "POST" for c in gh_calls)
    assert _delete_jobs() == ["666"]
    assert hooks.on_created(ready.pk, new_job, "777", WEBHOOK_TOKEN)["ok"] is True


def test_repeated_report_after_lost_response_is_idempotent(ready, admin, gh_calls):
    hooks.request_setup(ready, ["push"], actor=admin)
    first = _created(ready)
    again = _created(ready)  # 봇이 응답을 못 받아 같은 job으로 다시 보고
    assert first == again == {"ok": True, "delete_webhook": False}
    assert sum(c["method"] == "POST" for c in gh_calls) == 1
    assert _hook(ready)["state"] == "active" and _delete_jobs() == []


def test_disconnect_during_registration_compensates_immediately(
    ready, admin, gh_calls, monkeypatch
):
    hooks.request_setup(ready, ["push"], actor=admin)
    real = hooks.client.request

    def drop_conn(method, path, token, **kw):
        out = real(method, path, token, **kw)
        if method == "POST":
            RepoConnection.objects.filter(project=ready).delete()
        return out

    monkeypatch.setattr(hooks.client, "request", drop_conn)
    assert _created(ready) == {"ok": False, "delete_webhook": True}
    assert any(c["method"] == "DELETE" and c["path"] == "/repos/o/r/hooks/42" for c in gh_calls)


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
    _created(ready)
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
    _created(ready)
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
