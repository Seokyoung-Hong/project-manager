"""연결할 때 받는 국외 이전 동의: 동의 없이 연결 불가, 동의 후 연결, 철회하면 연결 해제."""

from datetime import timedelta

import pytest
from django.core.management import call_command
from django.utils import timezone

from accounts.models import ApiToken, Consent
from accounts.services import give_consent, link_discord, missing_consents, withdraw
from github.conftest import gh  # noqa: F401
from github.models import GitHubIdentity
from github.test_login import _callback
from web.tests import _pkce, _register

pytestmark = pytest.mark.django_db


@pytest.fixture
def logged(client, admin):
    client.force_login(admin)
    return client


def _active(user, target):
    return Consent.objects.filter(user=user, target=target, withdrawn_at__isnull=True).first()


def test_consent_page_shows_the_legal_notice(logged):
    body = logged.get("/settings/consents/ai").content.decode()
    for text in ("OpenAI, L.L.C.", "Anthropic, PBC", "미국", "보유 기간", "거부할 수 있습니다"):
        assert text in body
    assert logged.get("/settings/consents/nope").status_code == 404


# ---------- Discord ----------


def test_discord_code_needs_consent_then_withdraw_unlinks(logged, admin):
    r = logged.post("/settings/profile/discord")
    assert r["Location"].startswith("/settings/consents/discord?")
    admin.refresh_from_db()
    assert admin.discord_link_code is None

    r = logged.post("/settings/consents/discord", {"next": "/settings/profile"})
    assert r["Location"] == "/settings/profile"
    assert _active(admin, "discord").version == "v1"
    logged.post("/settings/profile/discord")
    admin.refresh_from_db()
    link_discord(admin.discord_link_code, "222")
    admin.refresh_from_db()
    assert admin.discord_user_id == "222"

    logged.post("/settings/consents/discord/withdraw")
    admin.refresh_from_db()
    assert admin.discord_user_id is None
    assert _active(admin, "discord") is None
    assert Consent.objects.get(user=admin, target="discord").withdrawn_at  # 기록은 남는다


# ---------- GitHub ----------


def test_github_connect_needs_consent_then_withdraw_unlinks(gh, logged, admin):  # noqa: F811
    r = logged.get("/settings/github")
    assert r["Location"].startswith("/settings/consents/github?")
    logged.post("/settings/consents/github", {"next": "/settings/github"})
    assert "github.com/login/oauth/authorize" in logged.get("/settings/github")["Location"]

    GitHubIdentity.objects.create(user=admin, github_id=7, login="a")
    logged.post("/settings/consents/github/withdraw")
    assert not GitHubIdentity.objects.filter(user=admin).exists()
    assert _active(admin, "github") is None


def test_github_signup_needs_consent(gh, client, monkeypatch):  # noqa: F811
    _callback(client, monkeypatch, {"id": 900, "login": "octo"})
    page = client.get("/login/github/confirm").content.decode()
    assert "GitHub, Inc." in page
    r = client.post("/login/github/confirm", {"age_ok": "1"})
    assert "국외 이전에 동의하지 않으면" in r.content.decode()
    assert not GitHubIdentity.objects.exists()
    client.post("/login/github/confirm", {"age_ok": "1", "consent_ok": "1"})
    user = GitHubIdentity.objects.get(github_id=900).user
    assert _active(user, "github")


# ---------- AI ----------


def test_ai_token_needs_consent_person_token_does_not(logged, admin):
    r = logged.post("/settings/tokens", {"name": "ai", "scope": "read", "purpose": "ai"})
    assert r["Location"].startswith("/settings/consents/ai?")
    assert not admin.tokens.exists()
    person = {"name": "p", "scope": "read", "purpose": "person", "person_ack": "on"}
    logged.post("/settings/tokens", person)
    assert admin.tokens.filter(for_ai=False).count() == 1  # 자기 스크립트용은 국외 이전이 아니다

    give_consent(admin, "ai")
    logged.post("/settings/tokens", {"name": "ai", "scope": "read", "purpose": "ai"})
    assert admin.tokens.filter(for_ai=True).count() == 1


def test_oauth_allow_needs_consent(client, logged, admin):
    _, challenge = _pkce()
    params = {
        "response_type": "code",
        "client_id": _register(client),
        "redirect_uri": "https://claude.ai/api/mcp/auth_callback",
        "code_challenge": challenge,
        "code_challenge_method": "S256",
    }
    assert "Anthropic, PBC" in logged.get("/oauth/authorize", params).content.decode()
    r = logged.post("/oauth/authorize", {**params, "decision": "allow"})
    assert "error=access_denied" in r["Location"] and _active(admin, "ai") is None
    r = logged.post("/oauth/authorize", {**params, "decision": "allow", "consent": "1"})
    assert "code=" in r["Location"] and _active(admin, "ai")
    # 동의한 뒤에는 고지를 다시 보이지 않는다
    assert "Anthropic, PBC" not in logged.get("/oauth/authorize", params).content.decode()


def test_ai_withdraw_revokes_ai_tokens_only(logged, admin):
    give_consent(admin, "ai")
    ai, _ = ApiToken.issue(admin, "커넥터", expires_at=timezone.now() + timezone.timedelta(days=1))
    person, _ = ApiToken.issue(admin, "스크립트", for_ai=False)
    logged.post("/settings/consents/ai/withdraw")
    ai.refresh_from_db()
    person.refresh_from_db()
    assert ai.revoked_at and not person.revoked_at


# ---------- 기존 사용자 ----------


def test_existing_connection_is_kept_and_flagged(client, member):
    """동의 화면 전에 연결한 사람은 끊지 않는다. 로그인 때 알리고 목록에 '동의 필요'로 보인다."""
    assert missing_consents(member) == ["discord"]
    r = client.post("/login", {"username": "member1", "password": "pw12345678"}, follow=True)
    assert "국외 이전 동의가 필요합니다" in r.content.decode()
    member.refresh_from_db()
    assert member.discord_user_id == "111"
    assert "동의 필요" in client.get("/settings/consents").content.decode()


# ---------- 탈퇴·GitHub 전용 계정 ----------


def test_account_withdrawal_withdraws_consents_and_purge_keeps_them_a_year(member):
    give_consent(member, "discord")
    withdraw(member, "pw12345678")
    row = Consent.objects.get(user=member)
    assert row.withdrawn_at
    call_command("purge_expired")
    assert Consent.objects.filter(pk=row.pk).exists()  # 1년 안에는 남는다
    Consent.objects.filter(pk=row.pk).update(withdrawn_at=timezone.now() - timedelta(days=366))
    call_command("purge_expired")
    assert not Consent.objects.filter(pk=row.pk).exists()


def test_purge_keeps_withdrawn_consents_of_active_users(admin):
    give_consent(admin, "ai")
    Consent.objects.filter(user=admin).update(withdrawn_at=timezone.now() - timedelta(days=400))
    call_command("purge_expired")
    assert Consent.objects.filter(user=admin).exists()


def test_github_only_account_cannot_withdraw_github_consent(logged, admin):
    admin.set_unusable_password()
    admin.save()
    logged.force_login(admin)  # 비밀번호가 바뀌면 세션이 끊긴다
    give_consent(admin, "github")
    GitHubIdentity.objects.create(user=admin, github_id=8, login="only")
    page = logged.get("/settings/consents").content.decode()
    assert "비밀번호를 먼저 설정하거나" in page and 'href="/settings/account"' in page
    r = logged.post("/settings/consents/github/withdraw", follow=True)
    assert "비밀번호를 먼저 설정하거나" in r.content.decode()
    assert GitHubIdentity.objects.filter(user=admin).exists() and _active(admin, "github")
