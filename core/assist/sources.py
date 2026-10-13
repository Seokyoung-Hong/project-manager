"""사용 순서 결정(IMPL-PLAN-12 §5.1·§5.2)."""

from dataclasses import dataclass

from django.db.models import Q
from django.utils import timezone


@dataclass(frozen=True)
class Attempt:
    """시도할 항목 하나. route = direct | pc | org. 키는 실행 직전에 복호화한다(여기 담지 않는다)."""

    route: str
    source: object = None  # AiSource | None(조직 AI 행이 없어 맨 뒤에 붙인 조직 AI)
    server: object = None  # route=pc일 때 SttServer

    @property
    def key(self) -> tuple:
        """tried와 맞대 보는 열쇠."""
        return (self.route, getattr(self.source, "pk", None))


def org_count(user, org, *, skip_job_id=None) -> int:
    """오늘(KST) 이 조직에서 이 사람이 조직 AI로 실행한(또는 실행 대기 중인) 작업 수.

    tried에 남은 지난 시도가 아니라 지금 route=org인 작업만 센다. 집히지 않고 끝난(no_worker·취소) 것은 빼다.
    """
    from common.dates import kst_day_range, today_kst

    from .models import AiJob

    start, _ = kst_day_range(today_kst())
    qs = AiJob.objects.filter(user=user, org=org, route="org", created_at__gte=start).exclude(
        Q(claimed_at__isnull=True) & Q(status__in=("failed", "cancelled"))
    )
    if skip_job_id:
        qs = qs.exclude(pk=skip_job_id)
    return qs.count()


def org_usable(user, org, *, skip_job_id=None, ignore_limit=False) -> bool:
    """조직 AI를 이 사람이 지금 쓸 수 있는가: 주소·모델, org_level, 멤버 하루 한도(관리자 예외)."""
    from orgs.services import is_admin, is_member
    from orgs.settings import effective

    if not (effective("assist.org_url", org=org) and effective("assist.org_model", org=org)):
        return False
    if not is_member(user, org):
        return False
    admin = is_admin(user, org)
    if effective("assist.org_level", org=org) == "admin" and not admin:
        return False
    limit = effective("assist.org_daily_limit", org=org)
    return (
        admin or ignore_limit or not limit or org_count(user, org, skip_job_id=skip_job_id) < limit
    )


def org_capped(user, org) -> bool:
    """조직 AI가 하루 한도에만 막혔는가(오류 코드 rate)."""
    return org_usable(user, org, ignore_limit=True) and not org_usable(user, org)


def _plan(user, org, *, skip_job_id=None) -> list[Attempt]:
    from notes.transcription import online

    from .models import AiSource
    from .services import ai_on

    if not ai_on(user, org):
        return []
    rows = list(AiSource.objects.filter(user=user).select_related("server"))
    if not any(r.kind == "org" for r in rows):
        rows.append(None)  # 조직 AI 행이 없으면 맨 뒤 → 기본이 개인 우선
    out = []
    for r in rows:
        if r is None or r.kind == "org":
            if (r is None or r.enabled) and org_usable(user, org, skip_job_id=skip_job_id):
                out.append(Attempt("org", r))
        elif not r.enabled or not r.base_url:
            continue
        elif r.route == "pc":
            s = r.server  # PC를 끊으면 NULL, 남의 PC면 불변식 1 위반 → 뺀다
            if s is not None and s.owner_id == user.pk and online(s, timezone.now()):
                out.append(Attempt("pc", r, s))
        elif r.route == "direct":
            out.append(Attempt("direct", r))
    return out


def plan(user, org) -> list[Attempt]:
    """사용자 AiSource(enabled) position 순 + 조직 AI. 스위치가 꺼져 있으면 빈 목록."""
    return _plan(user, org)


def next_attempt(job) -> Attempt | None:
    """tried에 없는 첫 항목. 실행 시점의 권한·스위치·한도로 다시 계산한다(§10.2). 이 작업 자신은 한도에서 뺀다."""
    done = {(t.get("route"), t.get("source_id")) for t in job.tried or []}
    for a in _plan(job.user, job.org, skip_job_id=job.pk):
        if a.key not in done:
            return a
    return None
