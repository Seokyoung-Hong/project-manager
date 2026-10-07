"""운영 콘솔 O1: 사용자·접근 화면, 정지·재설정 링크·운영자 권한·토큰 폐기·잠금 해제(IMPL-PLAN-10 §6.2·6.3)."""

import logging
import re

import pytest

from accounts.models import ApiToken, User
from common.logging import SecretFilter
from ops.models import OpsAuditLog

pytestmark = pytest.mark.django_db
PW = "pw12345678"
REASON = "본인 확인 후 처리"


@pytest.fixture
def staff(db):
    return User.objects.create_user("staff1", password=PW, display_name="운영자", is_staff=True)


@pytest.fixture
def root(db):
    return User.objects.create_user(
        "root1", password=PW, display_name="최고", is_staff=True, is_superuser=True
    )


def _act(client, user, action, **data):
    return client.post(f"/ops/users/{user.pk}/{action}", data)


def _login(client, username="member1", password=PW):
    return client.post("/login", {"username": username, "password": password})


def test_user_pages_are_ops_only(client, member, staff):
    client.force_login(member)
    for url in ("/ops/users", f"/ops/users/{member.pk}", "/ops/access"):
        assert client.get(url).status_code == 404
    client.force_login(staff)
    body = client.get("/ops/users?q=팀").content.decode()
    assert "member1" in body and "staff1" not in body
    assert "member1" not in client.get("/ops/users?state=suspended").content.decode()


def test_suspend_blocks_login_api_and_session_then_reactivate(client, member, staff):
    _, raw = ApiToken.issue(member, "자동화")
    member_client = client.__class__()
    member_client.force_login(member)
    client.force_login(staff)
    # 사유 4자·재입력 불일치는 아무것도 바꾸지 않고 기록도 없다.
    _act(client, member, "suspend", reason="짧은사유", confirm="member1")
    _act(client, member, "suspend", reason=REASON, confirm="member")
    assert User.objects.get(pk=member.pk).is_active and not OpsAuditLog.objects.exists()

    r = _act(client, member, "suspend", reason=REASON, confirm="member1")
    assert r.status_code == 302 and r.headers["Location"] == f"/ops/users/{member.pk}"
    assert OpsAuditLog.objects.get().action == "user.suspend"
    assert member_client.get("/today").status_code == 302  # 세션이 익명이 된다
    assert (
        client.__class__().get("/api/me", headers={"Authorization": f"Bearer {raw}"}).status_code
        == 401
    )
    assert (
        "_auth_user_id"
        not in client.__class__()
        .post("/login", {"username": "member1", "password": PW})
        .wsgi_request.session
    )

    _act(client, member, "reactivate", reason=REASON)
    assert (
        client.__class__().get("/api/me", headers={"Authorization": f"Bearer {raw}"}).status_code
        == 200
    )
    assert OpsAuditLog.objects.count() == 2


def test_staff_target_needs_superuser_and_grant_is_superuser_only(client, staff, root, member):
    client.force_login(staff)
    other = User.objects.create_user("staff2", password=PW, is_staff=True)
    _act(client, other, "suspend", reason=REASON, confirm="staff2")
    assert User.objects.get(pk=other.pk).is_active
    assert client.get(f"/ops/users/{member.pk}/grant-staff").status_code == 404
    assert _act(client, member, "grant-staff", reason=REASON, confirm="member1").status_code == 404
    assert "운영자 권한 부여" not in client.get(f"/ops/users/{member.pk}").content.decode()
    assert client.get(f"/ops/users/{member.pk}/nope").status_code == 404

    client.force_login(root)
    _act(client, member, "grant-staff", reason=REASON, confirm="member1")
    assert User.objects.get(pk=member.pk).is_staff
    _act(client, root, "revoke-staff", reason=REASON, confirm="root1")  # 자기 회수 거부
    assert User.objects.get(pk=root.pk).is_staff
    _act(client, member, "revoke-staff", reason=REASON, confirm="member1")
    assert not User.objects.get(pk=member.pk).is_staff
    assert OpsAuditLog.objects.count() == 2


def test_reset_link_is_shown_once_not_logged_and_single_use(client, member, staff, settings):
    client.force_login(staff)
    _act(client, member, "reset-link", reason=REASON, confirm="member1")
    body = client.get(f"/ops/users/{member.pk}").content.decode()
    link = re.search(r"http://testserver(/reset/[^<\s]+)", body).group(1)
    assert "/reset/" not in client.get(f"/ops/users/{member.pk}").content.decode()  # 한 번만
    log = OpsAuditLog.objects.get()
    assert log.action == "user.reset_link" and link.split("/")[-1] not in str(log.__dict__)

    anon = client.__class__()
    r = anon.get(link)  # 토큰을 세션으로 옮기고 토큰 없는 주소로 보낸다
    assert r.status_code == 302 and r.headers["Location"].endswith("/set-password")
    r = anon.post(
        r.headers["Location"], {"new_password1": "newpass-4321x", "new_password2": "newpass-4321x"}
    )
    assert r.status_code == 302 and r.headers["Location"] == "/login"
    assert "_auth_user_id" not in anon.session  # 자동 로그인하지 않는다
    assert _login(anon, password="newpass-4321x").status_code == 302

    again = client.__class__()
    r = again.get(again.get(link).headers["Location"])
    assert "링크가 만료되었거나 이미 사용되었습니다." in r.content.decode()


def test_reset_link_expires(client, member, staff, settings):
    client.force_login(staff)
    _act(client, member, "reset-link", reason=REASON, confirm="member1")
    link = re.search(r"/reset/[^<\s]+", client.get(f"/ops/users/{member.pk}").content.decode())[0]
    settings.PASSWORD_RESET_TIMEOUT = -1
    anon = client.__class__()
    r = anon.get(anon.get(link).headers["Location"])
    assert "링크가 만료되었거나 이미 사용되었습니다." in r.content.decode()


def test_secret_filter_masks_reset_link():
    rec = logging.LogRecord(
        "x", logging.INFO, "", 0, "GET /reset/Mg/cxyz12-0123456789abcdef0123456789abcdef", (), None
    )
    SecretFilter().filter(rec)
    assert "0123456789abcdef" not in rec.msg


def test_revoke_other_token_needs_prefix(client, member, staff):
    token, raw = ApiToken.issue(member, "비밀 이름표")
    client.force_login(staff)
    page = client.get("/ops/access").content.decode()
    assert token.prefix[3:] in page and "비밀 이름표" not in page
    assert token.prefix[3:] in client.get(f"/ops/access/tokens/{token.pk}/revoke").content.decode()
    client.post(f"/ops/access/tokens/{token.pk}/revoke", {"reason": REASON, "confirm": "x"})
    assert ApiToken.authenticate(raw) is not None
    r = client.post(
        f"/ops/access/tokens/{token.pk}/revoke", {"reason": REASON, "confirm": token.prefix[3:]}
    )
    assert r.headers["Location"] == "/ops/access" and ApiToken.authenticate(raw) is None
    assert OpsAuditLog.objects.get().action == "token.revoke"


def test_ops_lists_and_releases_locks(client, member, admin):
    """O0 이전 /ops에 있던 잠금 표가 접근 화면으로 옮겼다. 해제는 사유 필수·감사 기록."""
    for _ in range(5):
        _login(client, username="admin1", password="wrong")
    User.objects.filter(pk=member.pk).update(is_staff=True, is_superuser=True)
    client.force_login(member)
    body = client.get("/ops/access").content.decode()
    assert "로그인 잠금" in body and "admin1" in body
    assert "admin1" not in client.get("/ops/system").content.decode()
    assert "사유" in client.get("/ops/unlock?key=admin1").content.decode()  # GET은 대화상자만
    client.post("/ops/unlock", {"key": "admin1"})
    assert "admin1" in client.get("/ops/access").content.decode()
    r = client.post("/ops/unlock", {"key": "admin1", "reason": "본인 확인 후 해제"})
    assert r.status_code == 302 and r.headers["Location"] == "/ops/access"
    assert "admin1" not in client.get("/ops/access").content.decode()
    assert OpsAuditLog.objects.get().action == "user.unlock"
    client.post("/logout")
    assert _login(client, username="admin1").status_code == 302


def test_user_detail_shows_no_work_content(client, member, staff, task):
    member.settings = {"user.start_page": "비밀설정값"}
    member.save(update_fields=["settings"])
    client.force_login(staff)
    for url in (f"/ops/users/{member.pk}", "/ops/users", "/ops/access"):
        body = client.get(url).content.decode()
        assert task.title not in body and "비밀설정값" not in body
