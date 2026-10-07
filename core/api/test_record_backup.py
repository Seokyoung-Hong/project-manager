from pathlib import Path

import pytest
from django.core.management import call_command
from django.core.management.base import CommandError

from api.models import IntegrationStatus
from ops.models import OpsAuditLog

pytestmark = pytest.mark.django_db
ROOT = Path(__file__).resolve().parents[2]


def test_ok_then_fail_keeps_last_ok_at():
    call_command("record_backup", "--ok", "--detail", "stamp=1 files=4 bytes=99")
    ok_at = IntegrationStatus.objects.get(name="backup").detail["last_ok_at"]
    call_command("record_backup", "--fail", "--detail", "stamp=2")
    row = IntegrationStatus.objects.get(name="backup")
    assert row.ok is False
    assert row.detail["last_ok_at"] == ok_at
    assert row.detail["last_fail_at"]
    assert (row.detail["stamp"], row.detail["bytes"]) == ("2", "99")


@pytest.mark.parametrize("args", [[], ["--ok", "--fail"]])
def test_needs_exactly_one_flag(args):
    with pytest.raises(CommandError):
        call_command("record_backup", *args)


def test_restore_test_job_and_audit():
    call_command("record_backup", "--job", "restore-test", "--ok")
    assert IntegrationStatus.objects.get(name="restore-test").ok is True
    assert not IntegrationStatus.objects.filter(name="backup").exists()
    log = OpsAuditLog.objects.get(action="backup.record")
    assert (log.actor_username, log.target_label) == ("system", "restore-test")


def test_scripts_report():
    b = (ROOT / "scripts/backup.sh").read_text(encoding="utf-8")
    r = (ROOT / "scripts/restore-test.sh").read_text(encoding="utf-8")
    assert "record_backup" in b and "trap" in b and "ERR" in b
    assert "record_backup" in r and "restore-test" in r
