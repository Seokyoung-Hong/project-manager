"""운영 콘솔 교차 검토(docs/review-2026-10-04/P-sol-review-ops.md) 결함 5건의 회귀 테스트."""

import importlib
import re
import sys
import types
from datetime import timedelta
from pathlib import Path
from types import SimpleNamespace

import pytest
from django.core.management import call_command
from django.core.management.base import CommandError
from django.db import DatabaseError, connection, transaction

from accounts.models import ApiToken, User
from api.models import IntegrationStatus, clean_detail
from ops import services
from ops.models import OpsAuditLog
from web.views.ops_audit import _cell

pytestmark = pytest.mark.django_db
CORE = Path(__file__).resolve().parents[1]
TOKEN = "cxyz12-0123456789abcdef0123456789abcdef"


# ---- 1. Gunicorn 접속 로그 ----


def _entrypoint_flag(name: str) -> str:
    text = (CORE / "entrypoint.sh").read_text(encoding="utf-8")
    return re.search(rf"--{name}[ =](\S+)", text).group(1)


@pytest.fixture
def gunicorn_config(monkeypatch):
    """Gunicorn은 POSIX 전용 모듈을 import한다. CI(Linux)에서는 그대로, Windows 개발 PC에서만 흉내 낸다."""
    if sys.platform == "win32":
        for name in ("grp", "pwd", "fcntl"):
            monkeypatch.setitem(sys.modules, name, sys.modules.get(name) or types.ModuleType(name))
        monkeypatch.setattr("os.geteuid", lambda: 0, raising=False)
        monkeypatch.setattr("os.getegid", lambda: 0, raising=False)
    return importlib.import_module("gunicorn.config").Config


def test_gunicorn_access_log_masks_reset_token(capsys, gunicorn_config):
    """entrypoint.sh와 같은 설정(--access-logfile -, --logger-class)으로 실제 Gunicorn 로거를 만든다."""
    cfg = gunicorn_config()
    cfg.set("accesslog", _entrypoint_flag("access-logfile"))
    cfg.set("errorlog", _entrypoint_flag("error-logfile"))
    cfg.set("logger_class", _entrypoint_flag("logger-class"))
    log = cfg.logger_class(cfg)
    environ = {
        "REQUEST_METHOD": "GET",
        "RAW_URI": f"/reset/Mg/{TOKEN}",
        "PATH_INFO": f"/reset/Mg/{TOKEN}",
        "SERVER_PROTOCOL": "HTTP/1.1",
        "REMOTE_ADDR": "10.0.0.1",
        "HTTP_REFERER": f"https://udally.sio2.kr/reset/Mg/{TOKEN}",
    }
    resp = SimpleNamespace(status="302 Found", sent=0, headers=[])
    req = SimpleNamespace(headers=[("Referer", environ["HTTP_REFERER"])])
    capsys.readouterr()
    log.access(resp, req, environ, timedelta(milliseconds=3))
    log.error("bad request for /reset/Mg/%s", TOKEN)
    out = capsys.readouterr()
    text = out.out + out.err
    assert '"GET [redacted] HTTP/1.1" 302' in text  # 로그 줄 자체는 남는다(Referer까지 가림)
    assert "0123456789abcdef" not in text
    # 토큰 없는 폼 주소는 그대로 보인다(운영 추적용)
    log.access(resp, req, {**environ, "RAW_URI": "/reset/Mg/set-password"}, timedelta(0))
    assert "/reset/Mg/set-password" in capsys.readouterr().out


# ---- 2. 감사 기록 덮어쓰기 ----


@pytest.mark.skipif(connection.vendor != "sqlite", reason="SQLite 트리거 검사")
def test_sqlite_insert_or_replace_cannot_overwrite_audit():
    row = services.audit(None, "backup.record", reason="original")
    cols = [f.column for f in OpsAuditLog._meta.concrete_fields]
    select = ", ".join("'tampered'" if c == "reason" else c for c in cols)
    sql = f"INSERT OR REPLACE INTO ops_opsauditlog ({', '.join(cols)}) SELECT {select} FROM ops_opsauditlog WHERE id = %s"
    with pytest.raises(DatabaseError), transaction.atomic():
        connection.cursor().execute(sql, [row.pk])
    row.refresh_from_db()
    assert row.reason == "original"
    services.audit(None, "backup.record")  # 새 행 삽입은 그대로 된다
    assert OpsAuditLog.objects.count() == 2


def test_postgres_trigger_blocks_truncate():
    mig = importlib.import_module("ops.migrations.0001_initial")
    up = " ".join(mig.POSTGRES_UP)
    assert "BEFORE TRUNCATE ON ops_opsauditlog" in up and "FOR EACH STATEMENT" in up
    assert any("ops_audit_no_truncate" in s for s in mig.POSTGRES_DOWN)
    assert "BEFORE INSERT ON ops_opsauditlog" in " ".join(mig.SQLITE_UP)


# ---- 3. record_backup 원자성 ----


def test_record_backup_is_atomic_and_error_has_no_secret(monkeypatch):
    def boom(*a, **kw):
        raise RuntimeError("postgres://pm:SECRETPW@db/pm")

    monkeypatch.setattr("api.management.commands.record_backup.audit", boom)
    with pytest.raises(CommandError) as e:
        call_command("record_backup", "--ok", "--detail", "stamp=1")
    assert "SECRETPW" not in str(e.value) and "RuntimeError" in str(e.value)
    assert not IntegrationStatus.objects.exists()


def test_record_backup_keeps_only_allowed_detail_keys():
    call_command("record_backup", "--ok", "--detail", "stamp=1 token=pm_abc note=x files=3")
    d = IntegrationStatus.objects.get(name="backup").detail
    assert set(d) == {"stamp", "files", "last_ok_at"}


# ---- 4. 통합 detail ----


def test_status_detail_is_allowlisted_on_store_and_screen(client, admin):
    bot, raw = ApiToken.issue(admin, "봇", scope="bot")
    r = client.post(
        "/api/integrations/discord/status",
        {
            "ok": False,
            "detail": {
                "job": "weekly",
                "sent": 3,
                "error": "PRIVATE_TASK_BODY",
                "token": "SECRET_TOKEN",
                "unlinked_names": ["홍길동"],
                "status": "업무 문구가 섞인 글",
            },
        },
        content_type="application/json",
        headers={"Authorization": f"Bearer {raw}"},
    )
    assert r.status_code == 204
    assert IntegrationStatus.objects.get(name="discord").detail == {"job": "weekly", "sent": 3}
    # 예전에 저장된(걸러지지 않은) 행도 화면에서는 허용 키만 그린다.
    IntegrationStatus.objects.create(
        name="backup",
        last_run_at=bot.created_at,
        ok=True,
        detail={"stamp": "1", "error": "PRIVATE_TASK_BODY", "nested": {"token": "SECRET_TOKEN"}},
    )
    staff = User.objects.create_user("staff9", password="pw12345678", is_staff=True)
    client.force_login(staff)
    body = client.get("/ops/system").content.decode()
    assert "job: weekly" in body and "sent: 3" in body
    for s in ("PRIVATE_TASK_BODY", "SECRET_TOKEN", "홍길동", "업무 문구", "nested"):
        assert s not in body


def test_clean_detail_rejects_nested_and_free_text():
    assert clean_detail("discord", {"sent": 1, "job": {"x": 1}, "source": "a b"}) == {"sent": 1}
    assert clean_detail("mcp", {"sent": 1}) == {}


# ---- 5. CSV 수식 ----


@pytest.mark.parametrize(
    "value", ["=1+1", " =1+1", "\t=1+1", "\r=1+1", "\n=1+1", " \t@SUM(A1)", "\tplain", "\rx"]
)
def test_csv_cell_neutralizes_formulas(value):
    assert _cell(value) == "'" + value


@pytest.mark.parametrize("value", ["plain", "a=b", "", None, "1-2"])
def test_csv_cell_keeps_plain_text(value):
    assert _cell(value) == ("" if value is None else value)
