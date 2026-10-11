from datetime import timedelta

import pytest
from django.core.management import call_command
from django.utils import timezone

from accounts.models import ApiToken, LoginLock, OAuthClient, OAuthCode, User

pytestmark = pytest.mark.django_db


def test_purge_expired_removes_only_expired_and_survives_failure(monkeypatch):
    u = User.objects.create_user("p1", password="pw12345678")
    now = timezone.now()
    old, future = now - timedelta(days=2), now + timedelta(days=1)
    ApiToken.issue(u, "old", expires_at=old)
    ApiToken.issue(u, "live", expires_at=future)
    client = OAuthClient.register("c", ["https://x/cb"])
    for h in ("a", "b"):
        OAuthCode.objects.create(
            code_hash=h, client=client, user=u, redirect_uri="x", code_challenge="c"
        )
    OAuthCode.objects.filter(code_hash="a").update(created_at=old)
    for k, locked in (("old", None), ("fresh", None), ("locked", future)):
        LoginLock.objects.create(kind="login", key=k, window_started_at=now, locked_until=locked)
    LoginLock.objects.filter(key__in=["old", "locked"]).update(updated_at=old)

    # 세션 정리가 터져도 나머지는 돌고, 끝에 실패를 알린다.
    real = call_command

    def fake(name, *a, **k):
        if name == "clearsessions":
            raise RuntimeError("boom")
        return real(name, *a, **k)

    monkeypatch.setattr("ops.management.commands.purge_expired.call_command", fake)
    with pytest.raises(SystemExit):
        real("purge_expired")

    assert list(ApiToken.objects.values_list("name", flat=True)) == ["live"]
    assert list(OAuthCode.objects.values_list("code_hash", flat=True)) == ["b"]
    assert sorted(LoginLock.objects.values_list("key", flat=True)) == ["fresh", "locked"]


def test_session_cookie_age_is_14_days(settings):
    assert settings.SESSION_COOKIE_AGE == 14 * 24 * 3600
