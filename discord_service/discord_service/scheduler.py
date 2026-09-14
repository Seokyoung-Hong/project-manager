import logging
import time
from datetime import datetime

from .channels_post import run_channel_posts
from .config import Config
from .core_client import CoreClient, setting
from .discord import Bot
from .escalate import run_escalations
from .notify import run_deadlines
from .store import Store
from .weekly import last_monday, run_weekly

log = logging.getLogger(__name__)

# 놓아준 자리를 다시 훑을 기회. 하루 1회 문턱을 무한히 열어 주면 core가 아픈 동안 매 분
# 전체 스캔을 반복해 처리량 제한(60/m)을 스스로 태운다.
RETRY_SWEEPS = 3
CHANNEL_POST_BUCKET_MIN = 5


def _reopen_today(store: Store, hour_kind: str, day: str) -> bool:
    """놓아준 알림이 있을 때 그날 문턱을 다시 연다. 하루 RETRY_SWEEPS번까지.

    중복 발송 걱정은 없다 — 이미 보낸 묶음은 `sent` 행이 막는다. 다시 여는 것은
    '아직 안 보낸 묶음만' 다시 훑겠다는 뜻이다.
    """
    for n in range(1, RETRY_SWEEPS + 1):
        if store.claim_daily(f"{hour_kind}-retry-{n}", day):
            store.release_daily(hour_kind, day)
            return True
    return False


def _run_deadlines_job(cfg, core, bot, store, org_id, today, now, org_hour, st):
    day = today.isoformat()
    hour_kind = f"deadline-{now.hour}"
    if not store.claim_daily(hour_kind, day):
        return None
    try:
        r = run_deadlines(core, bot, store, org_id, today, now.hour, org_hour, st)
        # 발송 실패는 예외로 올라오지 않고 결과에 세어진다(DM 거부·채널 열기 실패·재확인 실패).
        # /ops에 ok로 보이면 아무도 모른다. 미연결(unlinked)·자발적 opted_out은 실패가 아니다.
        retry_later = r["open_failed"] + r["recheck_failed"]
        ok = r["failed"] == 0 and retry_later == 0
        # 놓아준 자리는 그날 문턱을 다시 열어야 실제로 재시도된다. release()만으로는
        # claim_daily가 이미 소비돼 그날 다시 안 돈다(= 그 사람은 알림을 못 받는다).
        if retry_later:
            r["reopened"] = _reopen_today(store, hour_kind, day)
        store.record_run("deadline", ok, str(r))
        core.report_status(ok, {"job": "deadline", **r})
        return {"job": "deadline", **r}
    except Exception as e:  # noqa: BLE001
        store.release_daily(hour_kind, day)  # 다음 tick에 다시 시도
        store.record_run("deadline", False, str(e))
        core.report_status(False, {"job": "deadline", "error": str(e)})
        log.exception("deadline job failed")
        return None


def _run_weekly_job(cfg, core, bot, store, org_id, today, now, st):
    weekly_weekday = setting(st, "notify.weekly_weekday", cfg.weekly_weekday)
    weekly_hour = setting(st, "notify.weekly_hour", cfg.weekly_hour)
    if now.weekday() != weekly_weekday or now.hour < weekly_hour:
        return None
    ws = last_monday(today)
    if store.weekly_sent(ws.isoformat()):
        return None
    try:
        r = run_weekly(core, bot, store, org_id, ws, cfg.llm_provider, st=st)
        store.record_run("weekly", r["status"] == "sent", str(r))
        core.report_status(r["status"] == "sent", {"job": "weekly", **r})
        return {"job": "weekly", **r}
    except Exception as e:  # noqa: BLE001
        store.record_run("weekly", False, str(e))
        core.report_status(False, {"job": "weekly", "error": str(e)})
        log.exception("weekly job failed")
        return None


def _run_escalate_job(core, bot, store, org_id, today, now, org_hour, st):
    day = today.isoformat()
    if now.hour < org_hour or not store.claim_daily("escalate", day):
        return None
    try:
        r = run_escalations(core, bot, store, org_id, today, st)
        store.record_run("escalate", r["failed"] == 0, str(r))
        return {"job": "escalate", **r}
    except Exception as e:  # noqa: BLE001
        store.release_daily("escalate", day)
        store.record_run("escalate", False, str(e))
        log.exception("escalate job failed")
        return None


def _run_channel_posts_job(core, bot, store, org_id, now, st):
    bucket = now.replace(
        minute=now.minute - now.minute % CHANNEL_POST_BUCKET_MIN, second=0, microsecond=0
    )
    if not store.claim_daily("chpost", bucket.isoformat()):
        return None
    try:
        r = run_channel_posts(core, bot, store, org_id, st)
        store.record_run("chpost", r["failed"] == 0, str(r))
        return {"job": "chpost", **r}
    except Exception as e:  # noqa: BLE001
        log.exception("channel post job failed: %s", e)
        return None


def tick(cfg: Config, core: CoreClient, bot: Bot, store: Store, now: datetime) -> list[dict]:
    """1분마다 호출. 실행한 작업 결과 목록."""
    results = []
    today = now.date()
    st = core.org_settings(cfg.org_id)  # 5분 캐시라 매 틱 불러도 싸다
    org_hour = setting(st, "notify.send_hour", cfg.send_hour)
    quiet_weekend = st.get("notify.quiet_weekend", False)

    if not (quiet_weekend and now.weekday() >= 5):
        # ponytail: 사람별 시각을 미리 계산하지 않고 매시 훑는다 — run_deadlines 안의
        # 개인별 시각 게이트가 실제 발송 여부를 정하므로 여기서 최소 시각을 구하는 건
        # 절약되는 HTTP 호출값보다 비싸다.
        r = _run_deadlines_job(cfg, core, bot, store, cfg.org_id, today, now, org_hour, st)
        if r:
            results.append(r)

    r = _run_weekly_job(cfg, core, bot, store, cfg.org_id, today, now, st)
    if r:
        results.append(r)

    r = _run_escalate_job(core, bot, store, cfg.org_id, today, now, org_hour, st)
    if r:
        results.append(r)

    r = _run_channel_posts_job(core, bot, store, cfg.org_id, now, st)
    if r:
        results.append(r)

    return results


def loop(cfg: Config):
    # ponytail: 단일 프로세스 전제. 복제 수를 늘리면 SQLite 파일을 공유하지 못하므로 1개만 띄운다.
    core = CoreClient(cfg.core_url, cfg.core_token)
    store = Store(cfg.db_path)
    bot = Bot(cfg.bot_token, cfg.channel_id, store)
    log.info("discord_service 시작 (org=%s, send_hour=%s)", cfg.org_id, cfg.send_hour)
    while True:
        try:
            tick(cfg, core, bot, store, datetime.now(cfg.tz))
        except Exception:  # noqa: BLE001
            log.exception("tick failed")
        time.sleep(60)
