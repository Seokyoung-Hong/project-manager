import logging
from collections import defaultdict
from datetime import date

from .core_client import CoreClient
from .discord import Bot, ChannelOpenFailed, DmBlocked, RetryExhausted, UnknownResult
from .messages import deadline_message, dm_blocked_message
from .store import Store

log = logging.getLogger(__name__)
OPEN = ("todo", "doing", "paused", "blocked", "review")
KINDS = ("d3", "d1", "d0", "overdue")


def _still_due(fresh: dict, listed: dict) -> bool:
    """발송 직전 재확인. 목록을 받은 뒤 완료·기한 변경·담당 변경이 있었으면 보내지 않는다.

    종류(d3·d1·d0·overdue)는 core가 알림 설정을 적용해 정한 값이라 여기서 다시 계산하지 않는다.
    """
    return (
        fresh["status"] in OPEN
        and fresh.get("due_date") == listed.get("due_date")
        and (fresh.get("assignee") or {}).get("id") == (listed.get("assignee") or {}).get("id")
    )


def run_deadlines(
    core: CoreClient,
    bot: Bot,
    store: Store,
    org_id: int,
    today: date,
    *,
    hour: int | None = None,
    org_hour: int | None = None,
    channel_id: str | None = None,
    notify: dict[str, dict] | None = None,
) -> dict:
    """조직 하나, 하루 한 묶음(또는 시각 한 묶음). 담당자별 개인 DM으로 보낸다.

    한 사람이 하루에 받는 DM은 종류당 1건, 최대 4건이다(D-3·D-1·당일·기한 초과).
    태스크마다 한 통씩 보내면 아침에 DM 폭탄이 되고 Discord Developer Policy의
    '원치 않는 반복 DM'에 걸린다.

    `hour`가 주어지면(다중 조직 스케줄러가 시각별로 부른다) 그 시각이 자기 시각인 사람만
    추린다 — 개인 설정 `user.notify_hour`가 있으면 그 시각, 없으면 `org_hour`(조직 설정
    `notify.send_hour`, 그것도 없으면 config 기본값). `hour=None`이면(단발 CLI·기존 호출)
    시각을 가리지 않고 전원을 훑는다.

    `notify`는 `discord_user_id -> {"notify_dm": bool, "notify_hour": int|None}`(§4.6). 없는
    사람·빈 dict는 "켜져 있고 조직 시각을 따른다"로 본다(설정 이전과 동작이 같다).
    `notify_dm=False`인 사람은 자리를 잡지 않고 건너뛰되 실패가 아니라 `opted_out`으로 센다
    — 본인이 끈 것이라 /ops를 빨갛게 만들 일이 아니다.

    조직·개인 알림 종류, 초과 반복, 주말 쉬기, 초과 유예는 core가 `deadlines` 목록을 만들 때
    적용한다(거르는 곳은 core 한 곳이다). 여기서는 사람별·시각별로 나눠 보내기만 한다.
    """
    notify = notify or {}
    today_s = today.isoformat()
    result = {
        "sent": 0,
        "skipped": 0,
        "failed": 0,
        "unknown": 0,
        "unlinked": 0,
        "opted_out": 0,
        # 자리를 놓아준 것들. 하루 1회 문턱(claim_daily)을 다시 열어야 실제로 재시도된다.
        "open_failed": 0,
        "recheck_failed": 0,
        "send_retry": 0,  # 429·5xx 3회 실패. 그날 영구 누락되지 않게 놓아준다
    }
    unlinked_names: list[str] = []
    candidates = core.deadlines(org_id, today_s)

    # (종류, 담당자) 로 묶는다. 담당자는 태스크당 한 명이다.
    grouped: dict[tuple[str, int], list[dict]] = defaultdict(list)
    for t in candidates:
        kind = t.get("alert_kind")
        assignee = t.get("assignee") or {}
        if kind and assignee.get("id"):
            grouped[(kind, assignee["id"])].append(t)

    for kind in KINDS:
        for uid in sorted(u for (k, u) in grouped if k == kind):
            tasks = grouped[(kind, uid)]
            assignee = tasks[0]["assignee"]
            did = assignee.get("discord_user_id")
            if not did:
                # 자리를 잡지 않는다. 나중에 연결하면 그 다음 알림부터 정상으로 받는다.
                result["unlinked"] += 1
                name = assignee.get("display_name") or str(uid)
                if name not in unlinked_names:
                    unlinked_names.append(name)
                log.warning("Discord 미연결이라 DM을 못 보낸다: %s", assignee.get("display_name"))
                continue
            pref = notify.get(did) or {}
            if pref.get("notify_dm") is False:
                result["opted_out"] += 1
                continue
            if hour is not None and _effective_hour(pref, org_hour, hour) != hour:
                continue  # 이 사람 시각이 아니다. 그 시각 틱에서 다시 훑는다
            key = f"{org_id}:{kind}:{uid}"
            if not store.claim(0, key, today_s):
                result["skipped"] += 1
                continue
            try:
                fresh = [core.task(t["id"]) for t in tasks]  # 발송 직전 재확인 (A09, A10)
            except Exception as e:  # noqa: BLE001
                # 자리를 잡아 둔 채 나가면 그 알림은 영구히 안 나간다. 놓아준다.
                # skipped(이미 보냄·더 이상 해당 없음)와 섞으면 손실이 안 보이므로 따로 센다 —
                # 이 숫자가 0이 아니면 scheduler가 그날 문턱을 다시 열고 /ops를 빨강으로 만든다.
                store.release(0, key, today_s)
                result["recheck_failed"] += 1
                log.warning("재확인 실패, 이 틱 뒤에 다시 훑는다: %s: %s", key, e)
                continue
            live = [f for f, t in zip(fresh, tasks, strict=True) if f and _still_due(f, t)]
            if not live:
                store.release(0, key, today_s)
                result["skipped"] += 1
                continue
            live.sort(key=lambda x: (x["due_date"], x["id"]))
            _send_dm(
                bot,
                store,
                did,
                deadline_message(kind, live, today_s),
                key,
                today_s,
                result,
                org_id,
                channel_id,
            )

    result["unlinked_names"] = unlinked_names
    return result


def _effective_hour(pref: dict, org_hour: int | None, fallback: int) -> int:
    h = pref.get("notify_hour")
    if h is None or h < 0:
        return org_hour if org_hour is not None else fallback
    return h


def _send_dm(bot, store, did, text, key, day, result, org_id, channel_id):
    try:
        bot.send_dm(did, text)
        store.mark(0, key, day, "sent")
        result["sent"] += 1
    except ChannelOpenFailed as e:
        # 아직 아무것도 보내지 않았다. 자리를 놓아준다(scheduler가 그날 문턱을 다시 연다).
        store.release(0, key, day)
        result["open_failed"] += 1
        log.warning("DM 채널을 열지 못했다, 다음 실행에서 재시도: %s: %s", key, e)
    except DmBlocked as e:
        # 영구 실패다. 자리를 남겨 다음 틱에 다시 시도하지 않는다(403은 invalid-request 예산을 태운다).
        store.mark(0, key, day, "failed", str(e))
        result["failed"] += 1
        log.error("DM 거부: %s %s", key, e)
        _notify_channel_once(bot, store, did, day, org_id, channel_id)
    except RetryExhausted as e:
        store.release(0, key, day)
        result["send_retry"] += 1
        log.warning("일시 장애로 발송 실패, 다음 틱에 재시도: %s: %s", key, e)
    except UnknownResult as e:
        store.mark(0, key, day, "unknown", str(e))
        result["unknown"] += 1
        log.warning("발송 결과 불명확: %s", key)
    except Exception as e:  # noqa: BLE001
        store.mark(0, key, day, "failed", str(e))
        result["failed"] += 1
        log.error("발송 실패: %s: %s", key, e)


def _notify_channel_once(bot, store, did, day, org_id, channel_id):
    """DM이 막힌 사람에게는 조직 채널로 하루 한 번만 알린다. 태스크 내용은 넣지 않는다."""
    key = f"{org_id}:dmblocked:{did}"
    if not store.claim(0, key, day):
        return
    try:
        bot.send_channel(dm_blocked_message({"discord_user_id": did}), channel_id)
        store.mark(0, key, day, "sent")
    except Exception as e:  # noqa: BLE001
        store.mark(0, key, day, "failed", str(e))
        log.error("DM 거부 통보 실패: %s", e)
