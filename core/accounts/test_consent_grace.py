"""동의 화면 전에 연결한 사람의 30일 유예와 그 뒤의 정지(DECISIONS 3차 3번)."""

from datetime import timedelta

import pytest
from django.utils import timezone

from accounts.models import ApiToken
from accounts.services import consent_active, give_consent
from common.errors import ServiceError
from github.conftest import gh  # noqa: F401
from github.models import GitHubIdentity
from github.services import user_token
from github.test_login import _callback
from tasks.models import Notice

pytestmark = pytest.mark.django_db

DC = "/api/integrations/discord"
TODAY = timezone.localdate()
NONE, DURING, AFTER = None, TODAY - timedelta(days=10), TODAY - timedelta(days=30)


@pytest.fixture
def grace(settings):
    def set_start(start):
        settings.CONSENT_GRACE_START = start

    return set_start


@pytest.mark.parametrize("target", ["github", "discord", "ai"])
@pytest.mark.parametrize(
    "start,consented,ok",
    [
        (NONE, False, True),
        (NONE, True, True),
        (DURING, False, True),
        (DURING, True, True),
        (AFTER, False, False),
        (AFTER, True, True),
    ],
)
def test_consent_active_matrix(grace, member, target, start, consented, ok):
    grace(start)
    if consented:
        give_consent(member, target)
    assert consent_active(member, target) is ok


def test_login_notice_shows_days_left_then_paused(grace, client, member):
    grace(DURING)
    r = client.post("/login", {"username": "member1", "password": "pw12345678"}, follow=True)
    assert "남은 기간 20일" in r.content.decode()
    client.logout()
    grace(AFTER)
    r = client.post("/login", {"username": "member1", "password": "pw12345678"}, follow=True)
    assert "동의하지 않은 연결은 멈춰 있습니다" in r.content.decode()


# ---------- AI ----------


def test_ai_token_refused_after_grace_until_consent(grace, client, member):
    _, ai = ApiToken.issue(member, "커넥터", "read")
    _, person = ApiToken.issue(member, "스크립트", "read", for_ai=False)
    get = lambda raw: client.get("/api/me", HTTP_AUTHORIZATION=f"Bearer {raw}")  # noqa: E731
    grace(DURING)
    assert get(ai).status_code == 200
    grace(AFTER)
    r = get(ai)
    assert r.status_code == 403 and "/settings/consents/ai" in r.json()["detail"]
    assert get(person).status_code == 200  # 사람용은 국외 이전이 아니다
    give_consent(member, "ai")
    assert get(ai).status_code == 200  # 동의하면 바로 풀린다


# ---------- Discord ----------


@pytest.fixture
def bot_token(db):
    from accounts.models import User

    bot = User.objects.create_user("discord-bot", password="pw12345678")
    return ApiToken.issue(bot, "봇", "bot")[1]


def test_discord_commands_and_dm_stop_after_grace(grace, client, member, org, bot_token):
    h = {"HTTP_AUTHORIZATION": f"Bearer {bot_token}"}
    today = lambda: client.post(  # noqa: E731
        f"{DC}/today", {"discord_user_id": "111"}, content_type="application/json", **h
    )
    Notice.objects.create(org=org, user=member, text="알림")
    dm_ids = lambda: (  # noqa: E731
        [n["discord_user_id"] for n in client.get(f"{DC}/notices", **h).json()],
        {
            m["id"]: m["discord_user_id"]
            for m in client.get(f"{DC}/orgs/{org.pk}/members", **h).json()
        }[member.pk],
    )
    grace(DURING)
    assert today().status_code == 200 and dm_ids() == (["111"], "111")
    grace(AFTER)
    r = today()
    assert r.status_code == 403 and "/settings/consents/discord" in r.json()["detail"]
    assert dm_ids() == ([None], None)  # 봇은 미연결로 보고 DM을 보내지 않는다
    member.refresh_from_db()
    assert member.discord_user_id == "111"  # 연결 정보는 그대로다
    give_consent(member, "discord")
    assert today().status_code == 200 and dm_ids() == (["111"], "111")


# ---------- GitHub ----------


def test_github_token_calls_stop_after_grace(grace, gh, member, monkeypatch):  # noqa: F811
    identity = GitHubIdentity.objects.create(
        user=member, github_id=5, login="m", token_expires_at=timezone.now() + timedelta(hours=1)
    )
    monkeypatch.setattr("github.services.decrypt", lambda v: "tok")
    grace(DURING)
    assert user_token(identity) == "tok"
    grace(AFTER)
    with pytest.raises(ServiceError) as e:
        user_token(identity)
    assert "/settings/consents/github" in e.value.errors["github"]
    give_consent(member, "github")
    assert user_token(identity) == "tok"


def test_github_login_after_grace_lands_on_consent(grace, gh, client, member, monkeypatch):  # noqa: F811
    member.set_unusable_password()  # GitHub로만 가입한 사람도 갇히지 않는다
    member.save()
    GitHubIdentity.objects.create(user=member, github_id=900, login="octo")
    grace(AFTER)
    r = _callback(client, monkeypatch, {"id": 900, "login": "octo"})
    assert int(client.session["_auth_user_id"]) == member.pk
    assert r["Location"].startswith("/settings/consents/github?")
    r = client.post("/settings/consents/github", {"next": "/today"})
    assert r["Location"] == "/today" and consent_active(member, "github")
