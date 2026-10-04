"""프로젝트 Discord 채널에 사건을 올린다 (§4.5 `notify.project_channel_events`).

채널은 **프로젝트마다** 다르다(`/프로젝트채널`로 연결한 그 채널) — 조직 알림 채널이 아니다.
`t["project"]["discord_channel_id"]`가 비어 있으면(채널 미연결) 그 태스크의 사건은 올리지 않는다.

사건 감지는 `ChangeLog`가 아니라 폴링 차이다 — 이전 조회 이후 `updated_at`이 바뀐 태스크를
받아, 이 서비스가 기억해 둔 지난 상태와 비교한다(`store.seen_status`). 멘션은 넣지 않는다
(마감 DM과 같은 원칙: 채널은 공유 공간이다). 개인정보는 담당자 표시 이름까지만 — 링크·메모·
사유는 올리지 않는다.

# ponytail: 5분이 아니라 매 틱(60초)마다 부르고, `since`에 여유를 둬 경계를 놓치지 않는다
# (scheduler가 준다). core 호출이 늘지만 조직당 한 번이라 감당된다. 부하가 실제로 문제가
# 되면 scheduler에 "이 작업은 5분에 한 번" 문턱을 하나 더 두면 된다 — 지금은 그 문턱 자체가
# 과한 조기 최적화다.
# ponytail: milestone_due는 태스크가 아니라 마일스톤을 다루므로(별도 목록·별도 core 호출이
# 필요하다) 이번 라운드에서는 만들지 않는다. `notify.project_channel_events`에 그 값이
# 들어 있어도 조용히 무시한다.
"""

import logging
from datetime import datetime

from .core_client import CoreClient
from .discord import Bot
from .store import Store

log = logging.getLogger(__name__)

CREATED, DONE, BLOCKED, OVERDUE_DAILY = "created", "done", "blocked", "overdue_daily"
EVENTS = (CREATED, DONE, BLOCKED, OVERDUE_DAILY)
LABEL = {CREATED: "새 태스크", DONE: "완료", BLOCKED: "막힘", OVERDUE_DAILY: "기한 초과"}


def _created_since(t: dict, since: str) -> bool:
    """처음 보는 태스크가 정말 이 창 안에서 만들어졌는가. 재기동·store 초기화 뒤 처음 보는 옛
    태스크를 '새 태스크'로 올리지 않게 합니다. created_at이 없으면 옛 동작(새 태스크)을 따릅니다."""
    c = t.get("created_at")
    return not c or datetime.fromisoformat(c) >= datetime.fromisoformat(since)


def _display(t: dict) -> str:
    a = t.get("assignee") or {}
    return a.get("display_name") or "담당자 없음"


def run_channel_events(
    core: CoreClient,
    bot: Bot,
    store: Store,
    org_id: int,
    today_iso: str,
    since: str,
    *,
    events: set[str] | None = None,
) -> dict:
    """`events`는 조직 설정 `notify.project_channel_events`(빈 집합이면 아무것도 안 한다).

    프로젝트별 게시 여부는 이 함수가 정하지 않는다 — 태스크의 `project.discord_channel_id`가
    있으면 올리고 없으면 건너뛴다(채널이 연결된 프로젝트만, §4.5).
    """
    result = {"posted": 0, "skipped": 0, "failed": 0}
    events = set(EVENTS) if events is None else events
    if not events:
        return result

    for t in core.updated_tasks(org_id, since):
        prev = store.seen_status(org_id, t["id"])
        store.mark_seen(org_id, t["id"], t["status"])
        kind = None
        if prev is None and _created_since(t, since):
            kind = CREATED
        elif t["status"] == "done" and prev != "done":
            kind = DONE
        elif t["status"] == "blocked" and prev != "blocked":
            kind = BLOCKED
        if kind and kind in events:
            _post(bot, store, org_id, kind, t, today_iso, result)

    if OVERDUE_DAILY in events:
        for t in core.open_tasks(org_id):
            if t.get("due_date") and t["due_date"] < today_iso:
                _post(bot, store, org_id, OVERDUE_DAILY, t, today_iso, result)
    return result


def _post(bot: Bot, store: Store, org_id: int, kind: str, t: dict, day: str, result: dict):
    channel_id = (t.get("project") or {}).get("discord_channel_id")
    if not channel_id:
        return  # 채널이 연결되지 않은 프로젝트다. 조용히 넘긴다(오류가 아니다)
    # (task_id=0, kind, day)로 하루 한 번만 — 같은 사건을 여러 틱이 겹쳐 봐도 한 번만 올라간다.
    key = f"{org_id}:chan:{kind}:{t['id']}"
    if not store.claim(0, key, day):
        result["skipped"] += 1
        return
    text = f"• {LABEL[kind]} · **{t['number']}** {t['title']} — {_display(t)}"
    try:
        bot.send_channel(text, channel_id)
        store.mark(0, key, day, "sent")
        result["posted"] += 1
    except Exception as e:  # noqa: BLE001
        store.mark(0, key, day, "failed", str(e))
        result["failed"] += 1
        log.warning("채널 게시 실패: %s: %s", key, e)
