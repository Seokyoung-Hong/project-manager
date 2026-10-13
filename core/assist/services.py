"""AI 자동완성 공개 함수(IMPL-PLAN-12 §5·§7·§10). 뷰(C·B)는 이 모듈만 부른다.

오류: 권한·대상 없음은 Http404, 입력·정책 거부는 ServiceError({"assist": 오류 코드 또는 문구}),
처리량 초과는 RateLimited(뷰가 429).
"""

from datetime import timedelta

from django.http import Http404
from django.utils import timezone

from common.errors import ServiceError
from orgs.settings import effective

MAX_ACTIVE = 2  # 사람별 동시 활성 작업
MAX_PER_HOUR = 120  # 사람별 시간당(모든 경로 합)
QUEUED_TTL = timedelta(minutes=5)  # 아무도 안 집으면 no_worker
KEEP_DAYS = 7  # 끝난 작업 보관


class RateLimited(ServiceError):
    """사람별 동시 2·시간당 120(§5.2). 뷰가 429로 돌려준다."""


def ai_on(user, org) -> bool:
    """이 조직 내용으로 AI 자동완성을 쓸 수 있는가 — 조직 스위치 `assist.enabled`(§5.1-0).

    버튼을 그릴지(컨텍스트 프로세서)와 작업을 만들지 둘 다 이 판정 하나를 쓴다.
    구성원 여부·대상 열람 권한은 호출자가 따로 본다(§10).
    """
    if org is None or not getattr(user, "is_authenticated", False):
        return False
    return bool(effective("assist.enabled", org=org))


def create_job(user, org, *, field: str, target: str, user_input: str = "", options=None):
    """작업 하나를 queued로 만든다(§4). field = 칸 키 또는 모드(assist.fields), target = "task:12" 꼴.

    스위치·대상 열람 권한·처리량·plan()이 빈 목록인지 보고, 통과하면 AiJob을 돌려준다.
    """
    from orgs.services import is_member

    from . import context, fields
    from .models import AiJob
    from .sources import org_capped, plan

    if org is None or not is_member(user, org):
        raise Http404
    if not ai_on(user, org):
        raise ServiceError({"assist": "org_disabled"})
    kind = fields.kind_of(field)
    if kind is None:
        raise ServiceError(
            {
                "assist": "이 칸은 AI 자동완성을 지원하지 않습니다. AI로 쓰기 버튼이 있는 칸에서 요청해 주세요."
            }
        )  # COPY:assist_bad_field
    ttype, obj = context.resolve_target(user, target)
    if ttype not in fields.targets_of(field):
        raise ServiceError(
            {
                "assist": "이 칸은 AI 자동완성을 지원하지 않습니다. AI로 쓰기 버튼이 있는 칸에서 요청해 주세요."
            }
        )  # COPY:assist_bad_field
    oid = context.org_id_of(ttype, obj)
    if oid is not None and oid != org.pk:
        raise Http404
    options = options if isinstance(options, dict) else {}
    if field == "meeting.minutes" and not (
        obj.kind == "meeting" and context.transcript_of(obj).strip()
    ):
        raise ServiceError(
            {
                "assist": "전사문이 없어 회의록을 작성할 수 없습니다. 전사를 완료한 뒤 다시 요청해 주세요."
            }
        )  # COPY:assist_no_transcript
    if field == "extract.meeting" and obj.kind != "meeting":
        raise Http404
    if field == "doc.template":
        from projects.docs import get_visible_doc

        tid = options.get("template_id")
        tpl = get_visible_doc(user, tid) if isinstance(tid, int) else None
        if tpl is None or not tpl.is_template or tpl.org_id != org.pk:
            raise ServiceError(
                {
                    "assist": "사용 가능한 템플릿이 선택되지 않았습니다. 이 조직에서 접근할 수 있는 템플릿을 선택해 주세요."
                }
            )  # COPY:assist_pick_template
        options = {"template_id": tid}
    now = timezone.now()
    mine = AiJob.objects.filter(user=user)
    if mine.filter(status__in=AiJob.ACTIVE).count() >= MAX_ACTIVE:
        raise RateLimited(
            {
                "assist": "동시에 처리할 수 있는 AI 작업 수를 넘었습니다. 진행 중인 작업이 끝난 뒤 다시 요청해 주세요."
            }
        )  # COPY:assist_busy
    if mine.filter(created_at__gte=now - timedelta(hours=1)).count() >= MAX_PER_HOUR:
        raise RateLimited(
            {"assist": "최근 1시간의 AI 요청 한도를 넘었습니다. 잠시 후 다시 요청해 주세요."}
        )  # COPY:assist_rate
    attempts = plan(user, org)
    if not attempts:
        raise ServiceError({"assist": "rate" if org_capped(user, org) else "no_source"})
    a = attempts[0]
    return AiJob.objects.create(
        user=user,
        org=org,
        kind=kind,
        field=field,
        target_type=ttype,
        target_id=obj.pk,
        user_input=(user_input or "")[: AiJob.MAX_INPUT],
        options=options,
        route=a.route,
        source=a.source,
        server=a.server,
    )


def expire_if_stale(job) -> bool:
    """queued로 5분 넘게 아무도 안 집었으면 failed(no_worker)(§4.3). 워커 sweep과 조회가 같이 쓴다.

    다음 항목으로 넘길 때 워커가 claimed_at을 그 시각으로 찍으므로, 5분은 마지막으로 queued가 된 때부터 센다.
    """
    from .models import AiJob

    since = job.claimed_at or job.created_at
    if job.status != "queued" or since > timezone.now() - QUEUED_TTL:
        return False
    now = timezone.now()
    n = AiJob.objects.filter(pk=job.pk, status="queued", claimed_at=job.claimed_at).update(
        status="failed", error="no_worker", finished_at=now
    )
    if n:
        job.status, job.error, job.finished_at = "failed", "no_worker", now
    return bool(n)


def get_job(user, job_id: int):
    """요청자 본인 작업만(아니면 Http404). 오래 안 집힌 queued는 여기서도 no_worker로 정리한다(§4.3)."""
    from .models import AiJob

    job = AiJob.objects.filter(pk=job_id, user=user).select_related("source").first()
    if job is None:
        raise Http404
    expire_if_stale(job)
    return job


def cancel_job(user, job_id: int):
    """queued는 바로 cancelled, running(PC 포함)은 cancelling. 끝난 작업은 그대로 돌려준다."""
    from .models import AiJob

    job = get_job(user, job_id)
    now = timezone.now()
    if AiJob.objects.filter(pk=job.pk, status="queued").update(
        status="cancelled", error="cancelled", finished_at=now
    ):
        job.refresh_from_db()
    elif AiJob.objects.filter(pk=job.pk, status="running").update(status="cancelling"):
        job.refresh_from_db()
    return job


def apply_job(user, job_id: int, *, version: int | None = None, mode: str = "replace"):
    """문서·회의록 결과를 본문에 적용(§7.3). update_doc(..., expected_version=version, force_new=True).

    충돌이면 ConflictError가 그대로 올라간다. 칸(field) 작업은 브라우저가 칸에 넣으므로 부르지 않는다.
    mode: "replace"(본문 바꾸기) | "append"(본문 뒤에 붙이기). doc.continue는 늘 뒤에 붙인다.
    """
    from projects.docs import get_visible_doc, update_doc

    from .models import AiJob

    if mode not in ("replace", "append"):
        raise ServiceError(
            {
                "mode": "적용 방식이 선택되지 않았습니다. 내용을 바꾸거나 뒤에 추가하는 방식을 선택해 주세요."
            }
        )  # COPY:assist_apply_mode
    job = get_job(user, job_id)
    if job.kind not in ("doc", "meeting") or job.status != "done":
        raise ServiceError(
            {"assist": "적용할 AI 결과가 없습니다. AI로 쓰기를 다시 요청해 주세요."}
        )  # COPY:assist_nothing_to_apply
    doc = get_visible_doc(user, job.target_id)
    if doc is None:
        raise Http404
    body = job.result
    if job.field == "doc.continue" or mode == "append":
        body = f"{doc.body_md.rstrip()}\n\n{job.result}" if doc.body_md.strip() else job.result
    doc = update_doc(
        doc,
        "body_md",
        body,
        actor=user,
        expected_version=doc.version if version is None else version,
        source="web",
        force_new=True,
    )
    AiJob.objects.filter(pk=job.pk).update(applied_at=timezone.now())
    return doc


def today_org_count(user, org) -> int:
    """오늘 이 조직에서 이 사람이 조직 AI로 실제 실행한 작업 수("오늘 조직 AI n/30", §5.2)."""
    from .sources import org_count

    return org_count(user, org)


def purge_old_jobs() -> int:
    """끝난 작업 7일 뒤 삭제(purge_expired가 하루 한 번)."""
    from .models import AiJob

    cutoff = timezone.now() - timedelta(days=KEEP_DAYS)
    return AiJob.objects.filter(finished_at__lt=cutoff).delete()[0]
