from django.core.management.base import BaseCommand, CommandError
from django.utils import timezone

from api.models import IntegrationStatus
from ops.services import audit


class Command(BaseCommand):
    help = "backup.sh·restore-test.sh의 결과를 IntegrationStatus에 남긴다."

    def add_arguments(self, p):
        p.add_argument("--job", default="backup", choices=["backup", "restore-test"])
        p.add_argument("--ok", action="store_true")
        p.add_argument("--fail", action="store_true")
        p.add_argument("--detail", default="")  # "stamp=20261007-041500 files=4 bytes=123456"

    def handle(self, *a, job, ok, fail, detail, **kw):
        if ok == fail:
            raise CommandError("--ok 또는 --fail 하나를 주세요.")
        now = timezone.now()
        row = IntegrationStatus.objects.filter(name=job).first()
        d = dict(row.detail) if row else {}
        d.update(dict(kv.split("=", 1) for kv in detail.split() if "=" in kv))
        d["last_ok_at" if ok else "last_fail_at"] = now.isoformat()  # 반대쪽 시각은 보존
        IntegrationStatus.objects.update_or_create(
            name=job, defaults={"last_run_at": now, "ok": ok, "detail": d}
        )
        audit(None, "backup.record", target_type="backup", target_label=job, detail={"ok": ok})
