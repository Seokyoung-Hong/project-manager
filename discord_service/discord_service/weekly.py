import json
import logging
from datetime import date, timedelta

from .core_client import CoreClient
from .discord import Bot, UnknownResult
from .store import Store
from .summarize import summarize

log = logging.getLogger(__name__)


def last_monday(today: date) -> date:
    this_monday = today - timedelta(days=today.weekday())
    return this_monday - timedelta(days=7)


def _post_team_channels(core: CoreClient, bot: Bot, org_id: int, data: dict, summary: str) -> None:
    """팀 담당 프로젝트가 이번 보고에 있는 팀에게만, 팀 채널에도 게시한다."""
    teams = core.org_teams(org_id)
    if not teams:
        return
    reported_project_ids = {bp["project"]["id"] for bp in data.get("by_project", [])}
    team_project_ids: dict[int, set[int]] = {}
    for p in core.org_projects(org_id):
        for t in p.get("teams", []):
            team_project_ids.setdefault(t["id"], set()).add(p["id"])
    for team in teams:
        channel_id = team.get("discord_channel_id")
        if not channel_id:
            continue
        if team_project_ids.get(team["id"], set()) & reported_project_ids:
            try:
                bot.send_channel_to(channel_id, summary)
            except Exception as e:  # noqa: BLE001
                log.error("팀 채널 주간 보고 실패: %s: %s", team["id"], e)


def run_weekly(
    core: CoreClient,
    bot: Bot,
    store: Store,
    org_id: int,
    week_start: date,
    provider: str,
    force: bool = False,
    st: dict | None = None,
) -> dict:
    ws = week_start.isoformat()
    if not force and store.weekly_sent(ws):
        return {"status": "skipped", "period_start": ws}
    data = core.weekly(org_id, ws)
    summary, source = summarize(data, provider)
    try:
        bot.send_channel(summary)
        status = "sent"
    except UnknownResult:
        status = "unknown"
    except Exception as e:  # noqa: BLE001
        log.error("주간 보고 발송 실패: %s", e)
        status = "failed"
    if status == "sent" and (st or {}).get("notify.team_channel_weekly"):
        _post_team_channels(core, bot, org_id, data, summary)
    store.save_weekly(ws, json.dumps(data, ensure_ascii=False), summary, source, status)
    return {"status": status, "period_start": ws, "source": source}
