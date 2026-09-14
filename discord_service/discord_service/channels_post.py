import logging

from .core_client import CoreClient
from .discord import Bot
from .messages import channel_event_message
from .store import Store

log = logging.getLogger(__name__)
# ponytail: created·done·blocked만 지금 다룬다. overdue_daily·milestone_due는 폴링 차이로
# 감지하기 애매한 사건(하루 경과·날짜 근접)이라 다음 라운드로 미룬다 — 실시간이 필요해지면
# core에 아웃바운드 웹훅을 만드는 편이 이 폴링 방식보다 낫다(IMPL-PLAN-4 §8.3).
SKIPPED_EVENTS = ("overdue_daily", "milestone_due")


def run_channel_posts(core: CoreClient, bot: Bot, store: Store, org_id: int, st: dict) -> dict:
    """5분마다. 이전 틱 이후 상태가 바뀐 태스크를 채널에 올린다(폴링 차이, ChangeLog 아님)."""
    result = {"posted": 0, "failed": 0}
    events = set(st.get("notify.project_channel_events") or [])
    if not events:
        return result

    for project in core.org_projects(org_id):
        channel_id = project.get("discord_channel_id")
        if not channel_id:
            continue
        tasks = core.tasks_by_status(
            org_id, "todo,doing,paused,blocked,review,done", project_id=project["id"]
        )
        for t in tasks:
            prev = store.seen_status(t["id"])
            status = t["status"]
            event = None
            if prev is None and "created" in events:
                event = "created"
            elif prev is not None and prev != status:
                if status == "done" and "done" in events:
                    event = "done"
                elif status == "blocked" and "blocked" in events:
                    event = "blocked"
            store.set_seen(t["id"], status)
            if event is None:
                continue
            try:
                bot.send_channel_to(channel_id, channel_event_message(event, t))
                result["posted"] += 1
            except Exception as e:  # noqa: BLE001
                result["failed"] += 1
                log.error("채널 게시 실패: %s: %s", t.get("number"), e)
    return result
