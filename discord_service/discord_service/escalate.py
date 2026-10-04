"""막힘·검토 대기가 오래 머문 태스크를 프로젝트 관리자에게 알린다 (§4.5 `notify.blocked_escalate_days`
·`notify.review_nudge_days`). 프로젝트 관리자가 0명이면 조직 관리자가 대신 받는다.

중복 방지는 새 표를 만들지 않고 notify.py와 같은 `sent` 표를 쓴다(task_id=0, kind=조합 키).
"""

import logging
from collections import defaultdict
from datetime import date, datetime

from .core_client import CoreClient
from .discord import Bot, DmBlocked, UnknownResult
from .messages import alert_line, display_name
from .store import Store

log = logging.getLogger(__name__)

BLOCKED = "blocked"
REVIEW = "review"
LABEL = {BLOCKED: "막힘", REVIEW: "검토 대기"}


def _days_since(iso_value: str | None, today: date) -> int | None:
    """`stopped_at`은 날짜 또는 날짜시각 ISO 문자열일 수 있다. 못 읽으면 대상에서 뺀다."""
    if not iso_value:
        return None
    try:
        d = datetime.fromisoformat(iso_value).date()
    except ValueError:
        return None
    return (today - d).days


def run_escalations(
    core: CoreClient,
    bot: Bot,
    store: Store,
    org_id: int,
    today: date,
    *,
    blocked_days: int = 0,
    review_days: int = 0,
) -> dict:
    """`blocked_days`·`review_days`는 0이면 끄기(§4.5 기본값과 같다).

    하루 1건·프로젝트별 묶음: (프로젝트, 종류) 하나당 오늘 DM 한 통이다. 관리자가 여럿이면
    각자에게 같은 내용을 보낸다 — "하루 1건"은 프로젝트당이지 사람당이 아니다.
    """
    result = {"sent": 0, "failed": 0, "skipped": 0}
    if not blocked_days and not review_days:
        return result
    day = today.isoformat()
    by_project: dict[int, dict[str, list[dict]]] = defaultdict(lambda: {BLOCKED: [], REVIEW: []})
    for t in core.open_tasks(org_id):
        age = _days_since(t.get("stopped_at"), today)
        if age is None:
            continue
        if blocked_days and t["status"] == BLOCKED and age >= blocked_days:
            by_project[t["project"]["id"]][BLOCKED].append(t)
        if review_days and t["status"] == REVIEW and age >= review_days:
            by_project[t["project"]["id"]][REVIEW].append(t)

    for project_id, groups in by_project.items():
        for kind, items in groups.items():
            if not items:
                continue
            key = f"{org_id}:escalate:{kind}:{project_id}"
            if not store.claim(0, key, day):
                result["skipped"] += 1
                continue
            recipients = core.project_owners(project_id) or core.org_admins(org_id)
            if not recipients:
                store.release(0, key, day)  # 보낼 사람이 없다. 관리자가 생기면 다시 시도한다
                continue
            text = _message(kind, items[0]["project"]["name"], items, today)
            ok = True
            for r in recipients:
                did = r.get("discord_user_id")
                if not did:
                    continue
                try:
                    bot.send_dm(did, text)
                    result["sent"] += 1
                except (DmBlocked, UnknownResult) as e:
                    ok = False
                    log.warning("에스컬레이션 DM 실패: %s: %s", did, e)
                except Exception as e:  # noqa: BLE001
                    ok = False
                    result["failed"] += 1
                    log.error("에스컬레이션 DM 실패: %s: %s", did, e)
            store.mark(0, key, day, "sent" if ok else "failed")
    return result


def _message(kind: str, project_name: str, items: list[dict], today: date) -> str:
    label = LABEL[kind]
    day = today.isoformat()
    head = f"⏰ **{project_name}** · {label} {len(items)}건이 오래 머물러 있습니다. 확인해 주세요."
    lines = [
        alert_line(t, day, who=display_name) + f" · {_days_since(t['stopped_at'], today)}일째"
        for t in items
    ]
    return head + "\n" + "\n".join(lines)
