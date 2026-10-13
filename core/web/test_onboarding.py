"""첫 진입·동의·연결 흐름(디자인 검토 a-onboarding). 동작이 바뀐 곳마다 하나씩."""

import pytest

from accounts.models import User
from accounts.services import give_consent, has_consent, last_admin_orgs
from github.conftest import gh  # noqa: F401
from orgs.models import Invite, OrgMembership
from orgs.services import create_org
from projects.models import Project
from tasks.models import Task

pytestmark = pytest.mark.django_db


@pytest.fixture
def lonely(db):
    return User.objects.create_user(
        "lonely", password="pw12345678", display_name="혼자", real_name="실명"
    )


# ---------- A1: 조직이 없으면 조직 목록으로 ----------


def test_login_and_root_send_orgless_user_to_org_list(client, lonely):
    r = client.post("/login", {"username": "lonely", "password": "pw12345678"})
    assert r["Location"] == "/orgs"
    assert client.get("/")["Location"] == "/orgs"


def test_login_with_org_still_goes_to_today(client, org, admin):
    r = client.post("/login", {"username": "admin1", "password": "pw12345678"})
    assert r["Location"] == "/today"


# ---------- A2: 갓 만든 조직의 시작하기 카드 ----------


def test_new_org_shows_getting_started_until_tasks_exist(client, admin, member):
    org = create_org("새 조직", "", admin)
    client.force_login(admin)
    body = client.get(f"/orgs/{org.pk}").content.decode()
    assert "시작하기" in body and "첫 프로젝트 만들기" in body
    OrgMembership.objects.create(org=org, user=member, role="member")
    client.force_login(member)  # 관리자가 아니면 보이지 않는다(초대·연결은 관리자 일)
    assert "시작하기" not in client.get(f"/orgs/{org.pk}").content.decode()
    project = Project.objects.create(org=org, name="p", created_by=admin)
    Task.objects.create(project=project, title="t", created_by=admin, assignee=admin)
    client.force_login(admin)
    assert "시작하기" not in client.get(f"/orgs/{org.pk}").content.decode()


# ---------- A3: 철회·해제·폐기는 확인을 받는다 ----------


def test_consent_withdraw_confirms_with_token_count(client, admin):
    client.force_login(admin)
    give_consent(admin, "ai")
    admin.tokens.model.issue(admin, "a", for_ai=True)
    admin.tokens.model.issue(admin, "b", for_ai=True)
    body = client.get("/settings/consents").content.decode()
    assert "data-confirm=" in body and "2개가 폐기됩니다" in body
    assert "동의 철회하고 연결 끊기" in body
    tokens = client.get("/settings/tokens").content.decode()
    assert tokens.count('data-confirm-ok="토큰 폐기"') == 2  # 토큰마다 폐기 확인


# ---------- B1·B2: 가치 먼저, 동의하면 하던 일을 마저 ----------


def test_consent_page_leads_with_value_and_back_goes_to_next(client, admin):
    client.force_login(admin)
    body = client.get("/settings/consents/discord?next=/settings/profile").content.decode()
    assert body.index("DM으로 받고") < body.index("Discord Inc.")
    assert 'href="/settings/profile">연결하지 않고 돌아가기' in body


def test_discord_code_is_issued_right_after_consent(client, admin):
    client.force_login(admin)
    r = client.post("/settings/profile/discord")
    assert r["Location"].startswith("/settings/consents/discord?")
    client.post("/settings/consents/discord", {"next": "/settings/profile"})
    admin.refresh_from_db()
    assert admin.discord_link_code  # [연결 코드 받기]를 다시 누르지 않아도 된다
    assert f"연결 {admin.discord_link_code}" in client.get("/settings/profile").content.decode()


def test_ai_token_is_issued_right_after_consent_with_same_name(client, admin):
    client.force_login(admin)
    client.post("/settings/tokens", {"name": "내 Claude", "scope": "write", "purpose": "ai"})
    assert not admin.tokens.exists()
    client.post("/settings/consents/ai", {"next": "/settings/tokens"})
    t = admin.tokens.get()
    assert (t.name, t.scope, t.for_ai) == ("내 Claude", "write", True)
    assert "새 토큰" in client.get("/settings/tokens").content.decode()


def test_concurrent_consent_resume_issues_token_once(client, admin):
    """같은 세션의 동의 POST 두 개가 재개 정보를 함께 읽어도 토큰은 하나만 나온다(코드 검토 중-1)."""
    client.force_login(admin)
    client.post("/settings/tokens", {"name": "내 Claude", "scope": "write", "purpose": "ai"})
    stale = dict(client.session)  # 두 번째 요청이 먼저 읽어 둔 세션
    client.post("/settings/consents/ai", {"next": "/settings/tokens"})
    session = client.session
    session.update({k: v for k, v in stale.items() if k == "consent_resume"})
    session.save()
    client.post("/settings/consents/ai", {"next": "/settings/tokens"})
    assert admin.tokens.count() == 1


def test_expired_consent_resume_does_not_issue(client, admin):
    client.force_login(admin)
    client.post("/settings/tokens", {"name": "x", "scope": "read", "purpose": "ai"})
    session = client.session
    session["consent_resume"] = {**session["consent_resume"], "at": 0}
    session.save()
    client.post("/settings/consents/ai", {"next": "/settings/tokens"})
    assert not admin.tokens.exists()


def test_consent_from_elsewhere_does_not_replay_old_action(client, admin):
    client.force_login(admin)
    client.post("/settings/tokens", {"name": "x", "scope": "read", "purpose": "ai"})
    client.post("/settings/consents/ai", {"next": ""})  # 동의 목록에서 따로 동의
    assert not admin.tokens.exists()
    assert has_consent(admin, "ai")


# ---------- B4: 탈퇴 차단 사유를 먼저 ----------


def test_last_admin_sees_block_before_typing(client, org, admin, member):
    assert last_admin_orgs(admin) == [org]
    assert last_admin_orgs(member) == []
    client.force_login(admin)
    body = client.get("/settings/account").content.decode()
    assert "마지막 관리자라 아직 탈퇴할 수 없습니다" in body and " disabled>" in body
    OrgMembership.objects.filter(org=org, user=member).update(role="admin")
    assert " disabled>" not in client.get("/settings/account").content.decode()


# ---------- B6: 조직 GitHub 탭에서 계정 연결 → 앱 설치로 이어짐 ----------


def test_github_connect_remembers_next(gh, client, admin):  # noqa: F811
    client.force_login(admin)
    give_consent(admin, "github")
    client.get("/settings/github?next=/orgs/1/github/install")
    assert client.session["gh_connect_next"] == "/orgs/1/github/install"
    client.get("/settings/github?next=https://evil.example/")
    assert (
        client.session["gh_connect_next"] == ""
    )  # 외부 주소는 받지 않고, 이전 목적지도 남기지 않는다


def test_cancelled_github_connect_does_not_leak_next(gh, client, admin):  # noqa: F811
    """조직 A에서 시작하고 취소한 뒤 프로필에서 새로 연결하면 프로필로 돌아온다(코드 검토 중-2)."""
    client.force_login(admin)
    give_consent(admin, "github")
    client.get("/settings/github?next=/orgs/1/github/install")
    client.get("/settings/github")  # 취소하고 프로필에서 다시 시작
    assert client.session["gh_connect_next"] == ""
    client.get("/settings/github?next=/orgs/1/github/install")
    client.get("/settings/github/callback?error=access_denied&state=wrong")  # GitHub에서 취소
    assert "gh_connect_next" not in client.session


def test_github_connect_keeps_next_through_consent(gh, client, admin):  # noqa: F811
    client.force_login(admin)
    r = client.get("/settings/github?next=/orgs/1/github/install")
    assert r["Location"].startswith("/settings/consents/github?")
    back = client.post(
        "/settings/consents/github", {"next": "/settings/github?next=/orgs/1/github/install"}
    )["Location"]
    client.get(back)
    assert client.session["gh_connect_next"] == "/orgs/1/github/install"


# ---------- B7: 앱이 없으면 GitHub 초대 체크박스를 숨긴다 ----------


def test_invite_form_hides_github_option_without_install(gh, client, admin):  # noqa: F811
    org = create_org("새 조직", "", admin)
    client.force_login(admin)
    body = client.get(f"/orgs/{org.pk}/teams").content.decode()
    assert "GitHub 조직에도 초대" not in body
    assert "가입한 뒤 바로 이 조직에 참여합니다" in body
    assert not Invite.objects.exists()
