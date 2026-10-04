from datetime import timedelta

import pytest
from django.utils import timezone

from accounts.models import User
from accounts.services import (
    issue_link_code,
    link_discord,
    set_user_settings,
    unlink_discord,
    user_by_discord_id,
)
from common.errors import ServiceError

pytestmark = pytest.mark.django_db


def test_display_name_truncated_from_long_username():
    """username 150자를 display_name(50자)에 그대로 복사하면 Postgres에서 DataError."""
    u = User.objects.create_user("a" * 120, password="pw12345678")
    assert len(u.display_name) == 50


# ---------- Discord 계정 연결 ----------


def _expire(user):
    User.objects.filter(pk=user.pk).update(
        discord_link_expires_at=timezone.now() - timedelta(seconds=1)
    )


def test_link_discord_fills_the_pair_and_clears_the_code(admin):
    """코드(웹 세션)와 snowflake(게이트웨이)가 만나야 연결된다. 코드는 재사용 불가로 비운다."""
    code = issue_link_code(admin)
    assert len(code) == 8 and code == code.upper()

    linked = link_discord(code, "222")
    assert linked.pk == admin.pk
    admin.refresh_from_db()
    assert admin.discord_user_id == "222"
    assert admin.discord_linked_at is not None
    # ""로 비우면 두 번째 사용자가 unique 제약에 걸린다. 반드시 None이어야 한다.
    assert admin.discord_link_code is None
    assert admin.discord_link_expires_at is None
    assert user_by_discord_id("222") == admin


def test_expired_code_changes_nothing(admin):
    code = issue_link_code(admin)
    _expire(admin)
    with pytest.raises(ServiceError):
        link_discord(code, "222")
    admin.refresh_from_db()
    assert admin.discord_user_id is None
    assert admin.discord_linked_at is None
    assert admin.discord_link_code == code  # 실패는 코드를 태우지 않는다


def test_code_is_single_use(admin, outsider):
    code = issue_link_code(admin)
    link_discord(code, "222")
    with pytest.raises(ServiceError):
        link_discord(code, "333")
    outsider.refresh_from_db()
    assert outsider.discord_user_id is None
    assert user_by_discord_id("333") is None


def test_non_numeric_snowflake_rejected(admin):
    """snowflake는 10진 정수 문자열이다. 사람이 타이핑한 값이 들어오는 경로를 막는다."""
    code = issue_link_code(admin)
    for bad in ("", "  ", "abc", "<@222>", "222 333", "2.22"):
        with pytest.raises(ServiceError):
            link_discord(code, bad)
    admin.refresh_from_db()
    assert admin.discord_user_id is None
    assert admin.discord_link_code == code


def test_link_takes_the_snowflake_from_the_previous_holder(admin, outsider):
    """코드와 snowflake가 둘 다 증명된 이 순간, 남의 행에 남아 있는 값이 틀린 것이다.

    선점당해 영구히 잠기는 경로가 없어야 admin을 readonly로 둘 수 있다.
    """
    User.objects.filter(pk=outsider.pk).update(
        discord_user_id="222", discord_linked_at=timezone.now()
    )
    link_discord(issue_link_code(admin), "222")

    outsider.refresh_from_db()
    admin.refresh_from_db()
    assert outsider.discord_user_id is None
    assert outsider.discord_linked_at is None
    assert admin.discord_user_id == "222"
    assert user_by_discord_id("222") == admin


def test_unlink_then_link_again(admin):
    link_discord(issue_link_code(admin), "222")
    unlink_discord(admin)
    admin.refresh_from_db()
    assert admin.discord_user_id is None
    assert user_by_discord_id("222") is None

    link_discord(issue_link_code(admin), "222")
    assert user_by_discord_id("222") == admin


# ---------- 개인 설정 ----------


def test_set_user_settings_cleans_and_strips_default(admin):
    set_user_settings(admin, {"user.notify_dm": False})
    admin.refresh_from_db()
    assert admin.settings == {"user.notify_dm": False}

    set_user_settings(admin, {"user.notify_dm": True})  # 기본값으로 되돌리면 지워진다
    admin.refresh_from_db()
    assert admin.settings == {}

    with pytest.raises(ServiceError):
        set_user_settings(admin, {"no.such.key": 1})


def test_user_by_discord_id_needs_a_proven_active_link(admin):
    """검증되지 않은 값과 비활성 계정은 명령 경로에 들어올 수 없다."""
    # 마이그레이션이 비우기 전의 손입력 값 같은 반쪽 행: 연결 시각이 없다.
    unproven = User.objects.create_user("typed", password="pw12345678", discord_user_id="444")
    assert unproven.discord_linked_at is None
    assert user_by_discord_id("444") is None

    link_discord(issue_link_code(admin), "222")
    User.objects.filter(pk=admin.pk).update(is_active=False)
    assert user_by_discord_id("222") is None


# ---------- 인증·시도 제한·외부 식별자 (IMPL-PLAN-7 §4.5) ----------


def _req(ip="10.0.0.1", xff=None):
    from django.test import RequestFactory

    extra = {"REMOTE_ADDR": ip}
    if xff:
        extra["HTTP_X_FORWARDED_FOR"] = xff
    return RequestFactory().post("/login", **extra)


def test_client_ip_takes_the_rightmost_forwarded_value():
    from accounts.auth import client_ip

    assert client_ip(_req(xff="a, b")) == "b"  # 왼쪽 a는 클라이언트가 지어낼 수 있다
    assert client_ip(_req(ip="10.0.0.9")) == "10.0.0.9"


def test_success_clears_the_user_counter(admin):
    from accounts.auth import authenticate_password
    from accounts.models import LoginLock

    for _ in range(4):
        assert authenticate_password(_req(), "Admin1", "wrong") is None  # 대소문자 무관하게 센다
    assert LoginLock.objects.get(kind="user", key="admin1").failures == 4
    assert authenticate_password(_req(), "admin1", "pw12345678") == admin
    assert not LoginLock.objects.filter(kind="user").exists()
    assert LoginLock.objects.get(kind="ip").failures == 4  # IP 카운터는 성공으로 지우지 않는다


def test_unknown_username_is_counted_and_locked(db):
    from accounts.auth import LockedOut, authenticate_password

    for _ in range(5):
        authenticate_password(_req(), "ghost", "x")
    with pytest.raises(LockedOut) as e:
        authenticate_password(_req(), "ghost", "x")
    assert e.value.retry_after_minutes == 15


def test_window_resets_after_fifteen_minutes(admin):
    from accounts.auth import authenticate_password
    from accounts.models import LoginLock

    for _ in range(4):
        authenticate_password(_req(), "admin1", "wrong")
    LoginLock.objects.update(window_started_at=timezone.now() - timedelta(minutes=16))
    authenticate_password(_req(), "admin1", "wrong")
    lock = LoginLock.objects.get(kind="user")
    assert lock.failures == 1 and lock.locked_until is None


def test_ip_locks_after_thirty_failures_across_usernames(admin):
    from accounts.auth import LockedOut, authenticate_password

    for i in range(30):
        authenticate_password(_req(xff="1.2.3.4"), f"u{i}", "x")
    with pytest.raises(LockedOut) as e:
        authenticate_password(_req(xff="1.2.3.4"), "admin1", "pw12345678")
    assert e.value.retry_after_minutes == 60
    assert authenticate_password(_req(xff="5.6.7.8"), "admin1", "pw12345678") == admin


def test_unlock_login_command_deletes_rows(admin):
    from django.core.management import call_command

    from accounts.auth import LockedOut, authenticate_password
    from accounts.models import LoginLock

    for _ in range(5):
        authenticate_password(_req(), "admin1", "wrong")
    with pytest.raises(LockedOut):
        authenticate_password(_req(), "admin1", "pw12345678")
    call_command("unlock_login", "ADMIN1")
    assert not LoginLock.objects.filter(kind="user").exists()
    assert authenticate_password(_req(), "admin1", "pw12345678") == admin


def test_identity_resolves_both_providers(member, admin):
    from accounts import identity
    from github.models import GitHubIdentity

    GitHubIdentity.objects.create(user=admin, github_id=42, login="octo")
    assert identity.resolve("github", "42") == admin
    assert identity.resolve("github", "nope") is None
    assert identity.resolve("discord", "111") == member
    assert identity.resolve("discord", "") is None
    assert identity.identities(admin) == {"github": "@octo"}
    assert identity.identities(member) == {"discord": "111"}
    User.objects.filter(pk=admin.pk).update(is_active=False)
    assert identity.resolve("github", "42") is None
    with pytest.raises(ValueError):
        identity.resolve("oidc", "x")
