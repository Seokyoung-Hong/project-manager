"""AI 워커(IMPL-PLAN-12 §4.1·§4.3). purge 컨테이너의 run_periodic이 start()를 한 번 부른다.

PC 작업(route="pc")은 집지 않는다 — heartbeat 경로(assist.pc)가 맡는다. route=""(PC가 실패를 보고해
되돌린 작업)는 집어서 tried를 보고 다음 항목으로 넘긴다.
사람별 동시 2개는 작업을 만들 때 막으므로(services.MAX_ACTIVE) 워커가 따로 세지 않는다.

상태 갱신은 모두 조건부 update(status·claimed_at이 집을 때 그대로일 때만)다. sweep이 먼저 넘겼거나
취소된 작업에 늦게 온 결과는 버려진다. 로그에는 작업 번호와 오류 코드만 남긴다(키·본문 금지, §11.4).
"""

import json
import logging
import threading
import time
from concurrent.futures import ThreadPoolExecutor
from datetime import timedelta

from django.conf import settings
from django.db import close_old_connections, transaction
from django.http import Http404
from django.utils import timezone

from . import copilot, extract, prompts
from .net import NetError, chat

log = logging.getLogger("assist")

TICK = 1
SWEEP_EVERY = 10
GRACE = timedelta(seconds=60)  # running 시간 초과 = claimed_at + timeout_s + 60초
MAX_REASONING_TOKENS = 16000  # 추론이 예산을 다 썼을 때 그 요청 한 번만 늘리는 max_tokens 상한
MAX_BUDGET_RETRIES = 3  # 작업 하나에서 예산을 늘려 다시 묻는 횟수(긴 회의록 조각마다 늘어나지 않게)

_busy = {}  # 풀에서 도는 작업 id → 긴 작업(문서·회의록·후보)인가
_busy_lock = threading.Lock()
_started = False


def start() -> None:
    """데몬 스레드 1개(배정 루프 1초 틱, 10초마다 sweep) + ThreadPoolExecutor(settings.ASSIST_WORKERS).

    ASSIST_WORKERS=0이면 아무것도 띄우지 않는다(되돌리기, §4.5).
    """
    global _started
    n = int(getattr(settings, "ASSIST_WORKERS", 0) or 0)
    if n <= 0 or _started:
        return
    _started = True
    pool = ThreadPoolExecutor(n, thread_name_prefix="assist")
    threading.Thread(target=_loop, args=(pool, n), name="assist-loop", daemon=True).start()


def _loop(pool, n):
    last_sweep = 0.0
    while True:
        try:
            if time.monotonic() - last_sweep >= SWEEP_EVERY:
                last_sweep = time.monotonic()
                sweep()
            with _busy_lock:
                free = n - len(_busy)
                # 짧은 칸 작업용으로 1개를 남긴다(긴 회의록이 풀을 다 잡지 않게). 워커가 1개면 예약 없음.
                long_free = free if n == 1 else max(0, n - 1 - sum(_busy.values()))
            for job_id, is_long in claim(free, long_free):
                with _busy_lock:
                    _busy[job_id] = is_long
                pool.submit(_run_in_pool, job_id)
        except Exception as e:  # noqa: BLE001 — 루프를 살린다
            log.error("assist loop %s", type(e).__name__)
        finally:
            close_old_connections()
        time.sleep(TICK)


def _run_in_pool(job_id):
    try:
        run(job_id)
    except Exception as e:  # noqa: BLE001
        log.error("assist job %s %s", job_id, type(e).__name__)
    finally:
        with _busy_lock:
            _busy.pop(job_id, None)
        close_old_connections()


def claim(limit: int, long_limit: int | None = None) -> list[tuple[int, bool]]:
    """queued(route direct·org·"") 작업을 짧은 칸 먼저 limit개 집어 running으로. Postgres는 SKIP LOCKED.

    긴 작업(칸이 아닌 것)은 long_limit개까지만 — 나머지 자리는 칸 작업 몫. (id, 긴 작업인가) 목록.
    """
    from .models import AiJob

    if limit <= 0:
        return []
    long_limit = limit if long_limit is None else long_limit
    now = timezone.now()
    with transaction.atomic():
        queued = AiJob.objects.select_for_update(skip_locked=True).filter(
            status="queued", route__in=("direct", "org", "")
        )
        short = list(
            queued.filter(kind="field").order_by("created_at").values_list("pk", flat=True)[:limit]
        )
        n_long = min(limit - len(short), long_limit)
        long = (
            list(
                queued.exclude(kind="field")
                .order_by("created_at")
                .values_list("pk", flat=True)[:n_long]
            )
            if n_long > 0
            else []
        )
        ids = short + long
        if ids:
            AiJob.objects.filter(pk__in=ids, status="queued").update(
                status="running", claimed_at=now
            )
    return [(i, False) for i in short] + [(i, True) for i in long]


# ---------- 상태 바꾸기 ----------


def _finish(job, token, status_from=("running",), **fields) -> bool:
    """조건부 갱신. 그 사이 cancelling이 됐으면 cancelled로 닫는다."""
    from .models import AiJob

    now = timezone.now()
    n = AiJob.objects.filter(pk=job.pk, status__in=status_from, claimed_at=token).update(**fields)
    if not n:
        AiJob.objects.filter(pk=job.pk, status="cancelling", claimed_at=token).update(
            status="cancelled", error="cancelled", finished_at=now
        )
    return bool(n)


def _mark_source(source, code=""):
    from .models import AiSource

    if source is None:
        return
    if code:
        AiSource.objects.filter(pk=source.pk).update(last_error=code)
    else:
        AiSource.objects.filter(pk=source.pk).update(last_ok_at=timezone.now(), last_error="")


def _fail(job, token, code, status_from=("running",)):
    log.info("assist job %s failed %s", job.pk, code)
    _finish(job, token, status_from, status="failed", error=code, finished_at=timezone.now())


def advance(job, token, code=None, status_from=("running",), budget_retries=0):
    """지금 항목을 tried에 남기고 다음 항목으로 다시 queued. 없으면 failed(마지막 오류 코드).

    code=None은 이미 tried에 남은 작업(PC가 보고해 route=""로 되돌린 작업)을 넘길 때.
    """
    from .sources import next_attempt

    tried = list(job.tried or [])
    if code and job.route:
        row = {"route": job.route, "source_id": job.source_id, "error": code}
        if budget_retries:
            row["budget_retries"] = budget_retries  # 작업 전체 누계(다음 AI도 이어서 센다)
        tried.append(row)
        if job.route != "org":
            _mark_source(job.source, code)
    job.tried = tried
    last = code or (tried[-1]["error"] if tried else "") or "no_source"
    nxt = next_attempt(job)
    if nxt is None:
        _finish(
            job,
            token,
            status_from,
            status="failed",
            error=last,
            tried=tried,
            finished_at=timezone.now(),
        )
        return None
    _finish(
        job,
        token,
        status_from,
        status="queued",
        route=nxt.route,
        source=nxt.source,
        server=nxt.server,
        tried=tried,
        claimed_at=timezone.now(),
        error="",
    )
    return nxt


# ---------- 실행 ----------


def _endpoint(job, route):
    """(주소, 키, 모델, 조직 AI 여부). 키는 여기서만 복호화한다."""
    from orgs.settings import effective, secret_value

    from . import oauth

    if route == "org":
        return (
            effective("assist.org_url", org=job.org),
            secret_value("assist.org_api_key", job.org),
            effective("assist.org_model", org=job.org),
            True,
        )
    s = job.source
    if s.is_copilot:  # 요청자 자신의 GitHub 토큰(_plan이 user=job.user 행만 고른다)
        return s.base_url, copilot.token_for(job.user), s.model, False
    key = oauth.source_key(s)  # HF OAuth면 만료 전에 갱신
    return s.base_url, key, s.model, False


def _cancelled(job) -> bool:
    from .models import AiJob

    return AiJob.objects.filter(pk=job.pk, status="cancelling").exists()


def _ask(ep, messages, spec, state, *, want_json, max_tokens=None):
    """한 번 묻고 (내용, usage). json_object를 400으로 거부하면 그 항목에선 없이 다시 묻는다(§11.2)."""
    url, key, model, org = ep
    if url == copilot.URL:  # JSON 강제 옵션 없음 — 형식은 프롬프트와 parse_output 재질문이 맞춘다
        return copilot.chat(messages, token=key, model=model, timeout_s=spec.timeout_s)
    payload = {
        "model": model,
        "messages": messages,
        "temperature": spec.temperature,
        "max_tokens": max_tokens or spec.max_tokens,
        "stream": False,
    }
    if want_json and not state.get("no_format"):
        payload["response_format"] = {"type": "json_object"}
    # 추론 모델(qwen3.5·gemma4 등)은 끄지 않으면 max_tokens를 추론에 다 써 content가 빈다.
    # 끌 수 없는 모델(OpenRouter의 추론 필수 등)은 400 → "low" → 그래도 400이면 뺀다(None).
    effort = state.get("effort", "none")
    if effort:
        payload["reasoning_effort"] = effort
    try:
        resp = chat(url, payload, api_key=key, org=org, timeout_s=spec.timeout_s)
    except NetError as e:
        if (
            getattr(e, "status", None) == 400
        ):  # 모르는 선택 항목을 거부하는 서버: 하나씩 낮추거나 빼고 다시
            if "reasoning_effort" in payload:
                state["effort"] = "low" if effort == "none" else None
                return _ask(ep, messages, spec, state, want_json=want_json, max_tokens=max_tokens)
            if "response_format" in payload:
                state["no_format"] = True
                return _ask(ep, messages, spec, state, want_json=want_json, max_tokens=max_tokens)
        raise
    try:
        choice = resp["choices"][0]
        msg = choice["message"]
        content = msg.get("content")
    except (KeyError, IndexError, TypeError, AttributeError):
        raise NetError("bad_output") from None
    usage = resp.get("usage") if isinstance(resp.get("usage"), dict) else {}
    for k, v in usage.items():
        if isinstance(v, int):
            state["usage"][k] = state["usage"].get(k, 0) + v
    empty = content is None or (isinstance(content, str) and not content.strip())
    thought = msg.get("reasoning") or msg.get("reasoning_content")
    if empty and thought and (content is None or choice.get("finish_reason") == "length"):
        # 추론이 출력 예산을 다 썼다: 이 요청만 예산을 늘리고 추론을 낮춰 한 번 더(다음 요청은 원래 예산).
        # 늘린 요청도 비었거나 작업당 횟수를 넘으면 reasoning_budget.
        if max_tokens or state.get("budget_retries", 0) >= MAX_BUDGET_RETRIES:
            raise NetError("reasoning_budget")
        state["budget_retries"] = state.get("budget_retries", 0) + 1
        if state.get("effort", "none") is not None:
            state["effort"] = "low"
        bigger = min(max(spec.max_tokens * 4, 8000), MAX_REASONING_TOKENS)
        return _ask(ep, messages, spec, state, want_json=want_json, max_tokens=bigger)
    if not isinstance(content, str):
        raise NetError("bad_output")
    return content


def execute(job, route) -> tuple[str, dict]:
    """메시지 조립(요청자 권한) → 호출 → 검증(한 번 재질문) → 후보 사후 처리. 실패는 NetError."""
    user = job.user
    spec = prompts.spec_of(job)
    ep = _endpoint(job, route)
    # 예산 늘림 횟수는 작업 전체에서 센다: 앞선 AI들에서 쓴 횟수(tried 누계)부터 이어서.
    prior = max((t.get("budget_retries", 0) for t in (job.tried or [])), default=0)
    state = {"usage": {}, "budget_retries": prior}
    try:
        return _execute(job, route, user, spec, ep, state)
    except NetError as e:
        e.budget_retries = state["budget_retries"]
        raise


def _execute(job, route, user, spec, ep, state) -> tuple[str, dict]:
    transcript = None
    long = prompts.long_text(job, user)
    if long:
        parts, pct = prompts.chunks(long)
        sums = []
        for i, part in enumerate(parts, 1):
            if _cancelled(job):
                raise NetError("cancelled")
            sums.append(
                prompts.clean_text(
                    _ask(
                        ep,
                        prompts.chunk_messages(part, i, len(parts)),
                        spec,
                        state,
                        want_json=False,
                    ),
                    4000,
                )
            )
        transcript = "\n\n".join(sums)
        if pct < 100:
            state["usage"]["input_pct"] = pct  # 미리보기 "앞부분 n%만 반영"
    messages = prompts.build_messages(job, user, transcript)
    earliest = extract.earliest_due(job, user) if job.kind == "extract" else None
    if _cancelled(job):
        raise NetError("cancelled")
    content = _ask(ep, messages, spec, state, want_json=spec.want_json)
    try:
        result = prompts.parse_output(job, content, earliest=earliest)
    except ValueError as e:
        messages = messages + [
            {"role": "assistant", "content": content[:4000]},
            {
                "role": "user",
                "content": f"형식이 맞지 않습니다({e}). 요청한 형식으로만 다시 답해 주세요.",
            },
        ]
        content = _ask(ep, messages, spec, state, want_json=spec.want_json)
        try:
            result = prompts.parse_output(job, content, earliest=earliest)
        except ValueError:
            raise NetError("bad_output") from None
    if job.kind == "extract":
        tasks = extract.postprocess(job, user, json.loads(result)["tasks"])
        result = json.dumps({"tasks": tasks}, ensure_ascii=False)
    return result, state["usage"]


def run(job_id: int) -> None:
    """집은 작업 하나. 실행 직전에 스위치·권한·순서를 다시 본다(§10.2)."""
    from .models import AiJob
    from .services import ai_on
    from .sources import _plan

    job = (
        AiJob.objects.select_related("user", "org", "source")
        .filter(pk=job_id, status="running")
        .first()
    )
    if job is None:
        return
    token = job.claimed_at
    if not ai_on(job.user, job.org):
        return _fail(job, token, "org_disabled")
    if not job.route:  # PC가 실패를 보고해 되돌린 작업
        advance(job, token)
        return
    keys = {a.key for a in _plan(job.user, job.org, skip_job_id=job.pk)}
    if (job.route, job.source_id) not in keys:
        advance(job, token, "no_source")  # 그 사이 끈 항목·권한·한도
        return
    try:
        result, usage = execute(job, job.route)
    except Http404:
        return _fail(job, token, "no_source")  # 대상을 이제 볼 수 없다
    except NetError as e:
        if e.code == "cancelled":
            return _finish(
                job,
                token,
                ("running",),
                status="cancelled",
                error="cancelled",
                finished_at=timezone.now(),
            )
        log.info("assist job %s %s %s", job.pk, job.route, e.code)
        advance(job, token, e.code, budget_retries=getattr(e, "budget_retries", 0))
        return
    if len(result.encode()) > AiJob.MAX_RESULT:
        advance(job, token, "too_large")
        return
    if job.route != "org":
        _mark_source(job.source)
    _finish(
        job, token, status="done", result=result, usage=usage, error="", finished_at=timezone.now()
    )


def sweep() -> None:
    """정체 정리(§4.3): running 시간 초과·PC 15초 무응답 → 다음 항목, queued 5분 → failed(no_worker)."""
    from notes.transcription import online

    from .models import AiJob
    from .pc import timeout_s as pc_timeout
    from .services import expire_if_stale

    now = timezone.now()
    from .codex_login import sweep as codex_login_sweep

    codex_login_sweep(now)  # 만료 기기 코드를 DB에서 비운다
    for job in AiJob.objects.filter(status="queued").exclude(route="pc"):
        expire_if_stale(job)
    running = (
        AiJob.objects.filter(
            status__in=("running", "cancelling"), claimed_at__lt=now - timedelta(seconds=30)
        )
        .exclude(route="pc")
        .select_related("user", "org", "source")
    )
    for job in running:
        if job.claimed_at + timedelta(seconds=prompts.spec_of(job).timeout_s) + GRACE > now:
            continue
        if job.status == "cancelling":
            _finish(
                job,
                job.claimed_at,
                ("cancelling",),
                status="cancelled",
                error="cancelled",
                finished_at=now,
            )
        else:
            advance(job, job.claimed_at, "timeout")
    pcs = AiJob.objects.filter(route="pc", status__in=AiJob.ACTIVE).select_related(
        "user", "org", "source", "server"
    )
    for job in pcs:
        if job.server is None:
            code = "pc_unlinked"
        elif not online(job.server, now):
            code = "pc_offline"
        elif (
            job.status != "queued"
            and job.claimed_at + timedelta(seconds=pc_timeout(job)) + GRACE < now
        ):
            code = "timeout"  # 켜져 있는 PC가 결과를 끝내 안 보냄 — 슬롯·내용을 붙잡지 않게
        else:
            if job.status == "queued":
                expire_if_stale(job)
            continue
        if job.status == "cancelling":
            _finish(
                job,
                job.claimed_at,
                ("cancelling",),
                status="cancelled",
                error="cancelled",
                finished_at=now,
            )
        else:
            advance(job, job.claimed_at, code, status_from=(job.status,))
