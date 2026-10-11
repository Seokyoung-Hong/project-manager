from datetime import timedelta

from django.core.management.base import BaseCommand
from django.db import connection, transaction
from django.utils import timezone

from ops.models import OpsAuditLog

SQLITE_NO_DELETE = """CREATE TRIGGER ops_audit_no_delete BEFORE DELETE ON ops_opsauditlog
    BEGIN SELECT RAISE(ABORT, 'ops_opsauditlog is append-only'); END"""


class Command(BaseCommand):
    help = "운영자 감사 기록 중 보관 기간(기본 365일)이 지난 행을 지운다. 감사 기록을 지우는 유일한 경로."

    def add_arguments(self, p):
        p.add_argument("--days", type=int, default=365)

    def handle(self, *a, days, **kw):
        cutoff = timezone.now() - timedelta(days=days)
        with transaction.atomic(), connection.cursor() as cur:
            if connection.vendor == "postgresql":
                cur.execute("SELECT set_config('ops.purge', 'on', true)")  # 이 트랜잭션에서만
            else:
                cur.execute("DROP TRIGGER ops_audit_no_delete")
            n = OpsAuditLog.objects.filter(created_at__lt=cutoff).delete()[0]
            if connection.vendor != "postgresql":
                cur.execute(SQLITE_NO_DELETE)
        self.stdout.write(f"감사 기록 {n}건 삭제 ({cutoff:%Y-%m-%d} 이전)")
