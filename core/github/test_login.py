"""GitHub로 로그인·가입."""

import pytest

from accounts.models import User
from github import client as gh_client
from github.models import GitHubIdentity

pytestmark = pytest.mark.django_db


def _callback(client, monkeypatch, gh_user: dict, nxt: str = "", emails=()):
    def fake_request(method, path, token, **k):
        if path == "/user/emails":
            return list(emails)
        return dict(gh_user)

    monkeypatch.setattr(gh_client, "exchange_code", lambda code: {"access_token": "t"})
    monkeypatch.setattr(gh_client, "request", fake_request)
    r = client.get("/login/github" + (f"?next={nxt}" if nxt else ""))
    assert r.status_code == 302 and "github.com/login/oauth/authorize" in r["Location"]
    state = client.session["gh_oauth_state"]
    return client.get(f"/settings/github/callback?code=x&state={state}")


def test_new_github_account_signs_up(gh, client, monkeypatch):
    primary = [{"email": "o@x.kr", "primary": True, "verified": True}]
    r = _callback(client, monkeypatch, {"id": 900, "login": "octo", "name": "옥토"}, emails=primary)
    user = GitHubIdentity.objects.get(github_id=900).user
    assert user.username == "octo" and user.display_name == "옥토" and user.email == "o@x.kr"
    assert not user.has_usable_password()
    assert r["Location"] == "/orgs"
    assert int(client.session["_auth_user_id"]) == user.pk


def test_same_username_asks_before_signup(gh, client, monkeypatch):
    User.objects.create_user(username="octo", password="pw-12345678")  # GitHub 미연결 기존 계정
    r = _callback(client, monkeypatch, {"id": 900, "login": "octo"})
    assert r["Location"] == "/login/github/confirm"
    assert not GitHubIdentity.objects.exists() and "_auth_user_id" not in client.session
    page = client.get("/login/github/confirm").content.decode()
    assert "GitHub와 연결되지 않은 계정이 존재합니다" in page
    r = client.post("/login/github/confirm")
    assert r["Location"] == "/orgs"
    assert GitHubIdentity.objects.get(github_id=900).user.username == "octo-gh"
    assert client.post("/login/github/confirm")["Location"] == "/login"  # 한 번만 쓴다


def test_same_email_asks_before_signup(gh, client, monkeypatch):
    User.objects.create_user(username="someone", email="O@x.kr", password="pw-12345678")
    r = _callback(client, monkeypatch, {"id": 900, "login": "octo", "email": "o@x.kr"})
    assert r["Location"] == "/login/github/confirm"


def test_linked_lookalike_does_not_ask(gh, client, monkeypatch):
    other = User.objects.create_user(username="octo", password="pw-12345678")
    GitHubIdentity.objects.create(user=other, github_id=1, login="someone-else")
    r = _callback(client, monkeypatch, {"id": 900, "login": "octo"})
    assert r["Location"] == "/orgs"  # 이미 GitHub에 연결된 계정은 혼동 대상이 아니다


def test_linked_github_account_logs_in(gh, client, monkeypatch, member):
    GitHubIdentity.objects.create(user=member, github_id=901, login="old")
    r = _callback(client, monkeypatch, {"id": 901, "login": "new"}, nxt="/join/abc")
    assert r["Location"] == "/join/abc"
    assert int(client.session["_auth_user_id"]) == member.pk
    assert GitHubIdentity.objects.get(github_id=901).login == "new"
    assert not User.objects.filter(username="new").exists()  # 새 사용자를 만들지 않았다


def test_inactive_user_cannot_log_in(gh, client, monkeypatch, member):
    member.is_active = False
    member.save()
    GitHubIdentity.objects.create(user=member, github_id=902, login="m")
    r = _callback(client, monkeypatch, {"id": 902, "login": "m"})
    assert r["Location"] == "/login"
    assert "_auth_user_id" not in client.session


def test_external_next_is_ignored(gh, client, monkeypatch):
    r = _callback(client, monkeypatch, {"id": 903, "login": "x"}, nxt="https://evil.example")
    assert r["Location"] == "/orgs"


def test_login_button_hidden_when_github_off(client, settings):
    settings.GITHUB_ENABLED = False
    assert "GitHub로 로그인" not in client.get("/login").content.decode()
    assert client.get("/login/github").status_code == 404
