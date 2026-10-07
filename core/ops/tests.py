"""운영 콘솔 기반(IMPL-PLAN-10 O0): 감사 기록 append-only, 금지 키, 접근 데코레이터, Django 관리 화면 가드·스위치."""

import importlib
from types import SimpleNamespace

import pytest
from django.db import DatabaseError, connection, transaction
from django.test import override_settings
from django.urls import clear_url_caches

from accounts.admin import ApiTokenAdmin
from accounts.models import ApiToken, User
from common.errors import ServiceError
from ops import services
from ops.models import OpsAuditLog

pytestmark = pytest.mark.django_db
PW = "pw12345678"


def _req(user):
    return SimpleNamespace(user=user, META={"REMOTE_ADDR": "10.0.0.1"})


@pytest.fixture
def staff(db):
    return User.objects.create_user("staff1", password=PW, display_name="운영자", is_staff=True)


@pytest.fixture
def root(db):
    return User.objects.create_user(
        "root1", password=PW, display_name="최고", is_staff=True, is_superuser=True
    )


# ---- 감사 기록 ----


def test_audit_is_append_only():
    row = services.audit(None, "backup.record", target_type="backup", target_label="backup")
    assert (row.actor, row.actor_username, row.ip) == (None, "system", "")
    with pytest.raises(RuntimeError):
        row.save()
    with pytest.raises(RuntimeError):
        row.delete()
    # Python을 우회하는 QuerySet·raw SQL도 DB 트리거가 막는다.
    for attempt in (
        lambda: OpsAuditLog.objects.filter(pk=row.pk).update(reason="x"),
        lambda: OpsAuditLog.objects.filter(pk=row.pk).delete(),
        lambda: connection.cursor().execute("DELETE FROM ops_opsauditlog"),
    ):
        with pytest.raises(DatabaseError), transaction.atomic():
            attempt()
    row.refresh_from_db()
    assert row.reason == "" and OpsAuditLog.objects.count() == 1


def test_postgres_trigger_sql_blocks_update_and_delete():
    """운영 DB(Postgres) 트리거는 테스트 DB(SQLite)에서 돌지 않으므로 SQL 문자열을 검사한다."""
    mig = importlib.import_module("ops.migrations.0001_initial")
    up = " ".join(mig.POSTGRES_UP)
    assert "BEFORE UPDATE OR DELETE ON ops_opsauditlog" in up
    assert "FOR EACH ROW EXECUTE FUNCTION ops_audit_block()" in up
    assert "RAISE EXCEPTION" in up


@pytest.mark.parametrize(
    "detail",
    [{"token": "pm_x"}, {"password": "x"}, {"key_hash": "x"}, {"after": {"reset_link": "/r"}}],
)
def test_audit_rejects_forbidden_detail_keys(detail):
    with pytest.raises(ValueError):
        services.audit(None, "user.unlock", detail=detail)
    assert not OpsAuditLog.objects.exists()


# ---- 접근 데코레이터 ----


def test_ops_required_hides_console(client, member, staff):
    assert client.get("/ops").status_code == 302  # 비로그인 → 로그인
    client.force_login(member)
    for url in ("/ops", "/ops/system", "/ops/design", "/ops/unlock", "/ops/export.json"):
        assert client.get(url).status_code == 404, url
    client.force_login(staff)
    body = client.get("/ops").content.decode()
    assert "운영 콘솔 메뉴" in body and "설정 메뉴" not in body and "빠른 추가" not in body
    assert client.get("/ops/system").status_code == 200


def test_export_is_superuser_only_with_reason_and_confirm(client, staff, root):
    client.force_login(staff)
    assert client.get("/ops/export.json").status_code == 404
    assert "JSON 내보내기" not in client.get("/ops/system").content.decode()
    client.force_login(root)
    assert "<code>export</code>" in client.get("/ops/export.json").content.decode()
    for data in ({"confirm": "export"}, {"reason": "점검용 내보내기", "confirm": "exp"}):
        r = client.post("/ops/export.json", data)
        assert r.status_code == 302 and r.headers["Location"] == "/ops/system"
    assert not OpsAuditLog.objects.exists()
    r = client.post("/ops/export.json", {"reason": "점검용 내보내기", "confirm": "export"})
    assert r.status_code == 200 and r["Content-Type"] == "application/json"
    log = OpsAuditLog.objects.get()
    assert (log.action, log.actor, log.reason) == ("export.json", root, "점검용 내보내기")


def test_settings_tabs_have_no_ops_items(client, root):
    client.force_login(root)
    body = client.get("/settings/profile").content.decode()
    assert "운영 상태" not in body and "디자인 시스템" not in body
    assert "운영 콘솔" in body  # 아바타 메뉴에만 남는다


# ---- 변경 규칙(services) ----


def test_suspend_rules(staff, root, member):
    with pytest.raises(ServiceError):  # 사유 4자
        services.suspend_user(_req(staff), member, "짧은사유", "member1")
    with pytest.raises(ServiceError):  # 대상 재입력 불일치
        services.suspend_user(_req(staff), member, "스팸 신고 확인", "member")
    with pytest.raises(ServiceError):  # 자기 자신
        services.suspend_user(_req(staff), staff, "스팸 신고 확인", "staff1")
    other = User.objects.create_user("staff2", password=PW, is_staff=True)
    with pytest.raises(ServiceError):  # 운영자 대상은 최고 운영자만
        services.suspend_user(_req(staff), other, "스팸 신고 확인", "staff2")
    assert not OpsAuditLog.objects.exists()
    member.refresh_from_db()
    assert member.is_active

    services.suspend_user(_req(staff), member, "스팸 신고 확인", "member1")
    services.suspend_user(_req(root), other, "퇴사 처리 확인", "staff2")
    member.refresh_from_db()
    assert not member.is_active
    log = OpsAuditLog.objects.filter(target_id=member.pk).get()
    assert log.action == "user.suspend" and log.ip == "10.0.0.1"
    assert log.detail == {"before": {"is_active": True}, "after": {"is_active": False}}
    services.reactivate_user(_req(staff), member, "오신고로 복구")
    member.refresh_from_db()
    assert member.is_active and OpsAuditLog.objects.count() == 3


def test_staff_grant_and_revoke_rules(staff, root, member):
    with pytest.raises(ServiceError):  # 서비스 운영자는 부여 못 한다
        services.grant_staff(_req(staff), member, "운영 인력 충원", "member1")
    services.grant_staff(_req(root), member, "운영 인력 충원", "member1")
    assert User.objects.get(pk=member.pk).is_staff
    with pytest.raises(ServiceError):  # 자기 회수
        services.revoke_staff(_req(root), root, "권한 정리 작업", "root1")
    other_root = User.objects.create_user("root2", password=PW, is_staff=True, is_superuser=True)
    with pytest.raises(ServiceError):  # 최고 운영자 회수
        services.revoke_staff(_req(root), other_root, "권한 정리 작업", "root2")
    services.revoke_staff(_req(root), staff, "권한 정리 작업", "staff1")
    assert not User.objects.get(pk=staff.pk).is_staff
    assert list(OpsAuditLog.objects.values_list("action", flat=True)) == [
        "user.revoke_staff",
        "user.grant_staff",
    ]


def test_revoke_token_needs_prefix_and_skips_bot(staff, member):
    token, raw = ApiToken.issue(member, "내 봇 연동")
    bot, _ = ApiToken.issue(member, "봇", scope="bot")
    with pytest.raises(ServiceError):
        services.revoke_token(_req(staff), token, "유출 신고 확인", "pm_x")
    with pytest.raises(ServiceError):
        services.revoke_token(_req(staff), bot, "유출 신고 확인", bot.prefix[3:])
    services.revoke_token(_req(staff), token, "유출 신고 확인", token.prefix[3:])
    assert ApiToken.authenticate(raw) is None
    log = OpsAuditLog.objects.get()
    assert log.target_label == token.prefix[3:] + "…"
    assert raw not in str(log.detail) and "내 봇 연동" not in log.target_label


# ---- Django 관리 화면 ----


def test_admin_is_superuser_only_and_logged(client, staff, root):
    client.force_login(staff)
    r = client.get("/admin/", follow=True)
    body = r.content.decode()
    assert r.status_code == 200 and "/admin/orgs/organization/" not in body
    log = OpsAuditLog.objects.get()
    assert (log.action, log.target_label, log.detail) == (
        "admin.access",
        "/admin/",
        {"method": "GET", "allowed": False},
    )
    client.force_login(root)
    r = client.get("/admin/")
    assert r.status_code == 200 and "/admin/orgs/organization/" in r.content.decode()
    assert OpsAuditLog.objects.first().detail == {"method": "GET", "allowed": True}
    client.get("/admin/jsi18n/")
    assert OpsAuditLog.objects.count() == 2


def test_admin_switch_off_is_404(client, root):
    import config.urls

    client.force_login(root)
    try:
        with override_settings(DJANGO_ADMIN_ENABLED=False):
            importlib.reload(config.urls)
            clear_url_caches()
            assert client.get("/admin/").status_code == 404
            assert client.get("/ops").status_code == 200
    finally:
        importlib.reload(config.urls)
        clear_url_caches()
    assert client.get("/admin/").status_code == 200


def test_admin_cannot_change_token_owner_or_scope():
    assert {"user", "scope", "expires_at"} <= set(ApiTokenAdmin.readonly_fields)
