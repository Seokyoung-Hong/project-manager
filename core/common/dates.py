from datetime import date, datetime, timedelta
from zoneinfo import ZoneInfo

from django.utils import timezone

KST = ZoneInfo("Asia/Seoul")


def now_kst():
    return timezone.now().astimezone(KST)


def today_kst() -> date:
    return now_kst().date()


def week_bounds(d: date | None = None) -> tuple[date, date]:
    """(이번 주 월요일, 이번 주 일요일)"""
    d = d or today_kst()
    monday = d - timedelta(days=d.weekday())
    return monday, monday + timedelta(days=6)


def last_week_start(d: date | None = None) -> date:
    """직전 주 월요일"""
    monday, _ = week_bounds(d)
    return monday - timedelta(days=7)


def kst_day_range(day: date):
    """day 00:00 KST 부터 다음날 00:00 KST 까지의 aware datetime 쌍"""
    start = datetime.combine(day, datetime.min.time(), tzinfo=KST)
    return start, start + timedelta(days=1)


def kst_week_range(week_start: date):
    """week_start 00:00 KST 부터 7일 뒤 00:00 KST 까지"""
    start = datetime.combine(week_start, datetime.min.time(), tzinfo=KST)
    return start, start + timedelta(days=7)


def fmt_md(d: date | None) -> str:
    """'9월 9일'. None이면 빈 문자열."""
    return f"{d.month}월 {d.day}일" if d else ""


def overdue_before(org, project=None) -> date:
    """`task.overdue_grace_days` 유예를 적용한 초과 기준일.

    `due_date`가 이 날짜보다 이르면 초과다. 화면 배지·집계·알림이 전부 이 함수 하나로
    판정을 맞춘다 — `Task.is_overdue`(사실)는 그대로 두고 여기서만 유예를 더한다.
    유예는 프로젝트가 덮어쓸 수 있으므로(Discord 마감 알림과 같은 기준) 프로젝트를 알면 넘긴다.
    설정은 이미 읽어 둔 JSON 필드만 보므로 쿼리를 내지 않는다.
    """
    from orgs.settings import effective  # 순환 임포트를 피하려 함수 안에서만 물어본다.

    grace = effective("task.overdue_grace_days", org=org, project=project)
    return today_kst() - timedelta(days=grace)


def overdue_q(projects, *, due="due_date", project_id="project_id"):
    """SQL 필터용 초과 조건: 프로젝트마다 자기 유예 기준일보다 기한이 이르다.

    projects는 org를 함께 읽어 둔 Project 목록이다(`select_related("org")`). 기준일이 같은
    프로젝트끼리 묶어 `project_id IN (...) AND due < 기준일`을 OR로 잇는다 — 보통 한두 덩이다.
    """
    from django.db.models import Q

    by_day: dict[date, list[int]] = {}
    for p in projects:
        by_day.setdefault(overdue_before(p.org, p), []).append(p.pk)
    q = Q(**{f"{due}__lt": date.min})  # 프로젝트가 없으면 아무것도 초과가 아니다
    for day, ids in by_day.items():
        q |= Q(**{f"{project_id}__in": ids, f"{due}__lt": day})
    return q
