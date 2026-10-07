from django.core.management.base import BaseCommand, CommandError
from django.db import transaction
from django.utils import timezone

from api.models import IntegrationStatus, clean_detail
from ops.services import audit


class Command(BaseCommand):
    help = "backup.sh·restore-test.sh의 결과를 IntegrationStatus에 남긴다."

    def add_arguments(self, p):
        p.add_argument("--job", default="backup", choices=["backup", "restore-test"])
        p.add_argument("--ok", action="store_true")
        p.add_argument("--fail", action="store_true")
        # "stamp=20261007-041500 files=4 bytes=123456". 허용 키(api.models.DETAIL_KEYS)만 남는다.
        p.add_argument("--detail", default="")

    def handle(self, *a, job, ok, fail, detail, **kw):
        if ok == fail:
            raise CommandError("--ok 또는 --fail 하나를 주세요.")
        try:
            # 상태와 감사 기록은 함께 남거나 함께 남지 않는다.
            with transaction.atomic():
                self._record(job, ok, detail)
        except Exception as e:
            # 예외 문구에는 DB 주소 같은 값이 섞일 수 있어 종류만 알린다.
            raise CommandError(
                f"백업 결과({job})를 기록하지 못했습니다: {type(e).__name__}. "
                "백업 파일 자체와는 별개이니 core 상태를 확인해 주세요."
            ) from None

    def _record(self, job, ok, detail):
        now = timezone.now()
        row = IntegrationStatus.objects.select_for_update().filter(name=job).first()
        d = dict(row.detail) if row else {}
        d.update(dict(kv.split("=", 1) for kv in detail.split() if "=" in kv))
        d["last_ok_at" if ok else "last_fail_at"] = now.isoformat()  # 반대쪽 시각은 보존
        IntegrationStatus.objects.update_or_create(
            name=job, defaults={"last_run_at": now, "ok": ok, "detail": clean_detail(job, d)}
        )
        audit(None, "backup.record", target_type="backup", target_label=job, detail={"ok": ok})
