import re

from django.db import models

# 통합별로 저장·표시해도 되는 detail 키. 집계(건수·시각·식별자)만 둔다 — 오류 문구·이름 목록·
# 중첩 값은 업무 내용이나 자격증명을 실을 수 있어 받지 않는다(IMPL-PLAN-10 §5.3).
_COUNTS = (
    "sent",
    "skipped",
    "failed",
    "unknown",
    "unlinked",
    "opted_out",
    "open_failed",
    "recheck_failed",
    "send_retry",
    "reopened",
)
_TIMES = ("last_ok_at", "last_fail_at")
DETAIL_KEYS = {
    "discord": {"job", "org_id", "hour", "status", "period_start", "source", *_COUNTS},
    "backup": {"stamp", "files", "bytes", "offsite", *_TIMES},
    "restore-test": {"dump", "tasks", "users", *_TIMES},
}
_SAFE_TEXT = re.compile(r"[A-Za-z0-9_.:+\-]{1,40}")


def clean_detail(name: str, detail) -> dict:
    """허용 키의 스칼라 값만 남긴다. 글은 짧은 식별자 꼴(공백 없음, 40자 이하)만."""
    keys = DETAIL_KEYS.get(name, set())
    out = {}
    for k, v in detail.items() if isinstance(detail, dict) else ():
        if k not in keys:
            continue
        if isinstance(v, bool | int) or (isinstance(v, str) and _SAFE_TEXT.fullmatch(v)):
            out[k] = v
    return out


class IntegrationStatus(models.Model):
    name = models.CharField(max_length=20, unique=True)
    last_run_at = models.DateTimeField()
    ok = models.BooleanField()
    detail = models.JSONField(default=dict, blank=True)  # clean_detail을 거친 값만 저장한다
    updated_at = models.DateTimeField(auto_now=True)

    def __str__(self):
        return f"{self.name}: {'ok' if self.ok else 'fail'}"
