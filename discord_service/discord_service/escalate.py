import logging
from collections import defaultdict
from datetime import date, datetime

from .core_client import CoreClient
from .discord import Bot
from .messages import escalate_message
from .store import Store

log = logging.getLogger(__name__)


def _age_days(iso_dt: str | None, today: date) -> int:
    if not iso_dt:
        return 0
    dt = datetime.fromisoformat(iso_dt.replace("Z", "+00:00"))
    return (today - dt.date()).days


def run_escalations(
    core: CoreClient, bot: Bot, store: Store, org_id: int, today: date, st: dict
) -> dict:
    """`blocked_escalate_days`·`review_nudge_days`. 프로젝트별로 묶어 관리자에게 하루 1건.

    중복 방지는 새 표를 만들지 않고 notify와 같은 `sent` 표를 `(0, key, day)`로 쓴다.
    """
    result = {"sent": 0, "failed": 0, "no_owner": 0}
    day = today.isoformat()

    jobs = [
        ("blocked", "notify.blocked_escalate_days", core.blocked_tasks, "stopped_at"),
        ("review", "notify.review_nudge_days", core.review_tasks, "updated_at"),
    ]
    members_by_id = None
    for kind, setting_key, fetch, age_field in jobs:
        threshold = st.get(setting_key, 0)
        if not threshold:
            continue
        tasks = [t for t in fetch(org_id) if _age_days(t.get(age_field), today) >= threshold]
        if not tasks:
            continue
        by_project: dict[int, list[dict]] = defaultdict(list)
        for t in tasks:
            proj = t.get("project") or {}
            if proj.get("id"):
                by_project[proj["id"]].append(t)

        if members_by_id is None:
            members_by_id = {m["id"]: m for m in core.org_members(org_id)}

        for project_id, ptasks in by_project.items():
            project = core.project(project_id)
            owners = (project or {}).get("owners") or []
            if not owners:
                result["no_owner"] += 1
                continue
            for owner in owners:
                personal = members_by_id.get(owner.get("id"), {}).get("notify") or {}
                if personal.get("dm") is False:
                    continue
                did = owner.get("discord_user_id")
                if not did:
                    continue
                key = f"esc:{kind}:{project_id}:{owner['id']}"
                if not store.claim(0, key, day):
                    continue
                try:
                    bot.send_dm(did, escalate_message(kind, project.get("name", ""), ptasks))
                    store.mark(0, key, day, "sent")
                    result["sent"] += 1
                except Exception as e:  # noqa: BLE001
                    store.mark(0, key, day, "failed", str(e))
                    result["failed"] += 1
                    log.error("에스컬레이션 발송 실패: %s: %s", key, e)
    return result
