import logging
import time
from datetime import datetime, timedelta

from .channels_post import run_channel_events
from .config import Config
from .core_client import CoreClient
from .discord import Bot
from .escalate import run_escalations
from .notify import run_deadlines
from .store import Store
from .weekly import last_monday, run_weekly

log = logging.getLogger(__name__)

# 놓아준 자리를 다시 훑을 기회. 하루 1회 문턱을 무한히 열어 주면 core가 아픈 동안 매 분
# 전체 스캔을 반복해 처리량 제한(60/m)을 스스로 태운다.
RETRY_SWEEPS = 3
ORG_CACHE_TTL = 300  # 5분(§8.4). 조직 목록(길드·채널·설정)은 이 주기로만 다시 읽는다.


class TickCache:
    """틱 사이에 들고 다니는 상태. `loop()`가 하나 만들어 계속 넘긴다.

    단발 호출(CLI `once`, 테스트)은 넘기지 않으면 매번 새로 만들어진다 — 캐시가 안 걸릴
    뿐 동작은 같다(느릴 뿐 틀리지 않는다).
    """

    def __init__(self):
        self._orgs: list[dict] = []
        self._orgs_at = 0.0
        self._members: dict[int, tuple[float, list[dict]]] = {}

    def orgs(self, core: CoreClient) -> list[dict]:
        now = time.monotonic()
        if now - self._orgs_at > ORG_CACHE_TTL:
            self._orgs = core.orgs()
            self._orgs_at = now
        return self._orgs

    def members(self, core: CoreClient, org_id: int) -> list[dict]:
        now = time.monotonic()
        hit = self._members.get(org_id)
        if hit and hit[0] > now:
            return hit[1]
        val = core.org_members(org_id)
        self._members[org_id] = (now + ORG_CACHE_TTL, val)
        return val


def _setting(settings: dict, key: str, default):
    v = settings.get(key)
    return default if v is None else v


def _reopen(store: Store, org_id: int, kind: str, day: str) -> bool:
    """놓아준 알림이 있을 때 그 (조직, 시각 묶음) 문턱을 다시 연다. 하루 RETRY_SWEEPS번까지.

    중복 발송 걱정은 없다 — 이미 보낸 묶음은 `sent` 행이 막는다. 다시 여는 것은
    '아직 안 보낸 묶음만' 다시 훑겠다는 뜻이다.
    """
    for n in range(1, RETRY_SWEEPS + 1):
        if store.claim_daily(org_id, f"{kind}-retry-{n}", day):
            store.release_daily(org_id, kind, day)
            return True
    return False


def _needed_hours(cfg: Config, settings: dict, members: list[dict]) -> set[int]:
    org_hour = int(_setting(settings, "notify.send_hour", cfg.send_hour))
    hours = {org_hour}
    hours |= {h for h in (m.get("notify_hour") for m in members) if isinstance(h, int) and h >= 0}
    return hours


def _run_deadline_job(cfg, core, bot, store, org, today, day, now, results):
    org_id, settings = org["org_id"], org.get("settings") or {}
    channel_id = org.get("channel_id") or ""
    org_hour = int(_setting(settings, "notify.send_hour", cfg.send_hour))
    members = org.get("_members", [])
    notify_map = {
        m["discord_user_id"]: {
            "notify_dm": m.get("notify_dm", True),
            "notify_hour": m.get("notify_hour"),
        }
        for m in members
        if m.get("discord_user_id")
    }
    # 사람마다 시각이 다를 수 있다(§4.6 user.notify_hour). 필요한 시각마다 따로 묶어 부른다 —
    # 틱이 60초라 시각별로 부르는 비용이 감당된다. 조직이 시각을 하나도 안 건드리면 이 집합은
    # {org_hour} 하나라 기존(단일 시각) 동작과 같다.
    for h in sorted(_needed_hours(cfg, settings, members)):
        if now.hour < h:
            continue  # 아직 그 시각 전이다
        kind = f"deadline-{h}"
        if not store.claim_daily(org_id, kind, day):
            continue  # 오늘 그 시각 묶음은 이미 처리했다(또는 재시도 대기 중)
        try:
            r = run_deadlines(
                core,
                bot,
                store,
                org_id,
                today,
                hour=h,
                org_hour=org_hour,
                channel_id=channel_id,
                notify=notify_map,
            )
            retry_later = r["open_failed"] + r["recheck_failed"]
            ok = r["failed"] == 0 and retry_later == 0
            if retry_later:
                r["reopened"] = _reopen(store, org_id, kind, day)
            store.record_run("deadline", ok, str(r))
            core.report_status(ok, {"job": "deadline", "org_id": org_id, "hour": h, **r})
            results.append({"job": "deadline", "org_id": org_id, "hour": h, **r})
        except Exception as e:  # noqa: BLE001
            store.release_daily(org_id, kind, day)  # 다음 tick에 다시 시도
            store.record_run("deadline", False, str(e))
            core.report_status(False, {"job": "deadline", "org_id": org_id, "error": str(e)})
            log.exception("deadline job failed (org=%s)", org_id)


def _run_weekly_job(cfg, core, bot, store, org, today, now, results):
    org_id, settings = org["org_id"], org.get("settings") or {}
    channel_id = org.get("channel_id") or ""
    weekday = int(_setting(settings, "notify.weekly_weekday", cfg.weekly_weekday))
    hour = int(_setting(settings, "notify.weekly_hour", cfg.weekly_hour))
    enabled = bool(_setting(settings, "notify.weekly_enabled", True))
    if now.weekday() != weekday or now.hour < hour:
        return
    ws = last_monday(today)
    if store.weekly_sent(org_id, ws.isoformat()):
        return
    try:
        r = run_weekly(
            core, bot, store, org_id, ws, cfg.llm_provider, enabled=enabled, channel_id=channel_id
        )
        store.record_run("weekly", r["status"] == "sent", str(r))
        core.report_status(r["status"] == "sent", {"job": "weekly", "org_id": org_id, **r})
        results.append({"job": "weekly", "org_id": org_id, **r})
    except Exception as e:  # noqa: BLE001
        store.record_run("weekly", False, str(e))
        core.report_status(False, {"job": "weekly", "org_id": org_id, "error": str(e)})
        log.exception("weekly job failed (org=%s)", org_id)


def _run_escalate_job(cfg, core, bot, store, org, today, day, now, results):
    org_id, settings = org["org_id"], org.get("settings") or {}
    blocked_days = int(_setting(settings, "notify.blocked_escalate_days", 0))
    review_days = int(_setting(settings, "notify.review_nudge_days", 0))
    if not blocked_days and not review_days:
        return
    org_hour = int(_setting(settings, "notify.send_hour", cfg.send_hour))
    if now.hour < org_hour or not store.claim_daily(org_id, "escalate", day):
        return
    try:
        r = run_escalations(
            core, bot, store, org_id, today, blocked_days=blocked_days, review_days=review_days
        )
        results.append({"job": "escalate", "org_id": org_id, **r})
    except Exception:  # noqa: BLE001
        store.release_daily(org_id, "escalate", day)
        log.exception("escalate job failed (org=%s)", org_id)


def _run_channels_job(core, bot, store, org, day, since, results):
    org_id, settings = org["org_id"], org.get("settings") or {}
    events = set(_setting(settings, "notify.project_channel_events", []))
    if not events:
        return
    try:
        r = run_channel_events(core, bot, store, org_id, day, since, events=events)
        results.append({"job": "channels", "org_id": org_id, **r})
    except Exception:  # noqa: BLE001
        log.exception("channels_post job failed (org=%s)", org_id)


def deliver_notices(core: CoreClient, bot: Bot) -> int:
    """core 발송함의 알림을 보낸다. 실패해도 ack한다 — 안 하면 같은 알림이 매 틱 되풀이된다."""
    try:
        notices = core.notices()
    except Exception:  # noqa: BLE001
        log.warning("알림 발송함을 못 읽었다, 이번 틱은 건너뛴다")
        return 0
    for n in notices:
        try:
            if n.get("discord_user_id"):
                bot.send_dm(n["discord_user_id"], n["text"])
            elif n.get("channel_id"):
                bot.send_channel(n["text"], n["channel_id"])
            # 둘 다 없으면 받을 사람이 그새 연결을 끊었다. 기본 채널로 새면 안 되므로 버린다.
        except Exception:  # noqa: BLE001
            log.exception("알림 발송 실패(id=%s), ack하고 넘어간다", n.get("id"))
    if notices:
        try:
            core.ack_notices([n["id"] for n in notices])
        except Exception:  # noqa: BLE001
            log.exception("알림 ack 실패, 다음 틱에 다시 보낸다")
    return len(notices)


def tick(
    cfg: Config,
    core: CoreClient,
    bot: Bot,
    store: Store,
    now: datetime,
    *,
    cache: TickCache | None = None,
) -> list[dict]:
    """1분마다 호출. 봇에 바인딩된 조직마다 마감·주간·에스컬레이션·채널 게시를 돈다."""
    cache = cache or TickCache()
    results: list[dict] = []
    today = now.date()
    day = today.isoformat()
    # channels_post의 폴링 창. 60초 틱에 여유를 조금 둬 경계에서 사건을 놓치지 않는다.
    since = (now - timedelta(seconds=90)).isoformat()

    deliver_notices(core, bot)  # 조직 목록이 안 읽혀도 요청 알림은 나간다
    try:
        orgs = cache.orgs(core)
    except Exception:  # noqa: BLE001
        log.exception("조직 목록을 못 읽었다, 이번 틱은 건너뛴다")
        return results

    for org in orgs:
        org_id = org["org_id"]
        try:
            members = cache.members(core, org_id)
        except Exception:  # noqa: BLE001
            members = []
            log.warning("조직 멤버 알림 설정을 못 읽었다(org=%s), 조직 기본값으로 진행", org_id)
        org["_members"] = members
        _run_deadline_job(cfg, core, bot, store, org, today, day, now, results)
        _run_weekly_job(cfg, core, bot, store, org, today, now, results)
        _run_escalate_job(cfg, core, bot, store, org, today, day, now, results)
        _run_channels_job(core, bot, store, org, day, since, results)
    return results


def loop(cfg: Config):
    # ponytail: 단일 프로세스 전제. 복제 수를 늘리면 SQLite 파일을 공유하지 못하므로 1개만 띄운다.
    core = CoreClient(cfg.core_url, cfg.core_token)
    store = Store(cfg.db_path)
    bot = Bot(cfg.bot_token, store=store)
    cache = TickCache()
    log.info("discord_service 시작 (다중 조직, 기본 알림 시각=%s시)", cfg.send_hour)
    while True:
        try:
            tick(cfg, core, bot, store, datetime.now(cfg.tz), cache=cache)
        except Exception:  # noqa: BLE001
            log.exception("tick failed")
        time.sleep(60)
