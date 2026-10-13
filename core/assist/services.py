"""AI 자동완성 공개 함수(IMPL-PLAN-12 §5·§7·§10). 뷰(C·B)는 이 모듈만 부른다.

A0는 시그니처만 고정했다. ai_on 외 몸체는 A 갈래가 채운다.
오류: 권한·대상 없음은 Http404, 입력·정책 거부는 ServiceError({"assist": 오류 코드 또는 문구}),
처리량 초과는 RateLimited(뷰가 429).
"""

from common.errors import ServiceError
from orgs.settings import effective


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
    raise NotImplementedError


def get_job(user, job_id: int):
    """요청자 본인 작업만(아니면 Http404). 오래 안 집힌 queued는 여기서도 no_worker로 정리한다(§4.3)."""
    raise NotImplementedError


def cancel_job(user, job_id: int):
    """queued는 바로 cancelled, running(PC 포함)은 cancelling. 끝난 작업은 그대로 돌려준다."""
    raise NotImplementedError


def apply_job(user, job_id: int, *, version: int | None = None):
    """문서·회의록 결과를 본문에 적용(§7.3). update_doc(..., expected_version=version, force_new=True).

    충돌이면 ConflictError가 그대로 올라간다. 칸(field) 작업은 브라우저가 칸에 넣으므로 부르지 않는다.
    """
    raise NotImplementedError


def today_org_count(user, org) -> int:
    """오늘 이 조직에서 이 사람이 조직 AI로 실제 실행한 작업 수("오늘 조직 AI n/30", §5.2)."""
    raise NotImplementedError
