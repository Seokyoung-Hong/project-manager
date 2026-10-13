"""내 PC 거쳐 보내기(IMPL-PLAN-12 §5.3·§6.2·§6.3).

소유자 불변식: 배정은 AiJob.server == server AND AiJob.user == server.owner인 작업만, 보고도 같은 조건.
PC를 끊으면 AiJob.server가 NULL(SET_NULL)이 되어 어느 PC에도 배정되지 않는다(정리는 worker.sweep).
"""

import functools
import json
import logging
from pathlib import Path

from django.conf import settings
from django.db import transaction
from django.http import Http404
from django.utils import timezone

from github.crypto import decrypt

from . import extract, prompts
from .models import AiJob, AiSource

log = logging.getLogger(__name__)

# PC가 보낼 수 있는 오류 코드(assist.models.ERROR_CODES 중 PC 쪽). 목록 밖이면 pc_error.
PC_ERRORS = {
    "connect_failed",
    "timeout",
    "http_4xx",
    "http_5xx",
    "auth_failed",
    "model_not_found",
    "bad_output",
    "too_large",
    "blocked_address",
    "pc_error",
    "codex_missing",
    "codex_auth",
    "codex_link_update",
}
LIVE = ("running", "cancelling")


@functools.cache
def _tested_codex() -> frozenset:
    data = json.loads(Path(__file__).with_name("codex_versions.json").read_text(encoding="utf-8"))
    return frozenset(v for v, r in data.items() if r.get("ok"))


def codex_versions() -> list[str]:
    """udally-link가 Codex 작업을 받아도 되는 Codex CLI 버전(정확히 일치).
    codex_versions.json = udally-link scripts/codex-matrix(Docker)로 도구 경계를 시험해 통과한 버전,
    ASSIST_CODEX_VERSIONS = 운영자가 .env로 덧붙이는 버전."""
    return sorted(_tested_codex() | set(settings.ASSIST_CODEX_VERSIONS))


_ENC = "enc:"


class Finished(Exception):
    """이미 끝난 작업에 온 보고. 라우터가 409로 돌려준다."""


def on_heartbeat(server, data: dict) -> dict:
    """notes.stt_link.heartbeat() 끝에서 부른다: out.update(on_heartbeat(server, data)).

    data에 ai=1이고 ai_job_id가 비면 {"ai_job": {id, url, model, api_key, messages, max_tokens,
    temperature, response_format, timeout_s}}, 보고한 ai_job_id가 cancelling이면 {"ai_cancel": True}.
    배정은 server.owner_id == job.user_id인 작업만(불변식 2). ai=1이면 늘 codex_versions(받아도 되는 Codex 버전)를 준다.
    """
    if not data.get("ai"):
        return {}  # 옛 PC(능력 표시 없음)는 전사만
    return {"codex_versions": codex_versions(), **_assign(server, data)}


def _assign(server, data: dict) -> dict:
    current = data.get("ai_job_id")
    # PC가 잊은 작업(재시작 등): 하던 것과 다른 진행 중 작업은 놓아준다.
    for pk in (
        AiJob.objects.filter(server=server, status__in=LIVE)
        .exclude(pk=current)
        .values_list("pk", flat=True)
    ):
        _release(pk, server, "pc_error")
    if current:
        live = AiJob.objects.filter(pk=current, server=server, status="running").exists()
        return {} if live else {"ai_cancel": True}  # 취소 중이거나 더는 이 PC 작업이 아님
    job = claim(server, codex=data.get("codex"))
    return {"ai_job": job} if job else {}


def claim(server, codex: int | None = None) -> dict | None:
    """대기 중인 PC 작업 하나를 running으로 바꾸고 PC에 줄 내용을 돌려준다(불변식 2).

    배정 직전에 조직 스위치·이 공급원이 지금 실행 순서에 있는지(켜짐·권한·한도)를 다시 본다(§10.2) —
    대기 중에 스위치나 개인 AI를 끄면 PC로 내용이 나가지 않는다.
    Codex 작업은 heartbeat에 codex=1(Codex CLI 있음)을 보낸 PC에만 준다. codex 칸이 없으면 Codex를 모르는
    옛 udally-link(codex_link_update), 0이면 Codex 미설치(codex_missing)로 다음 AI로 넘긴다.
    """
    from .services import ai_on
    from .sources import _plan

    mine = AiJob.objects.filter(status="queued", route="pc", server=server, user_id=server.owner_id)
    for pk in mine.order_by("created_at", "id").values_list("pk", flat=True)[:5]:
        with transaction.atomic():
            job = (
                mine.select_for_update(skip_locked=True, of=("self",))
                .select_related("source", "user")
                .filter(pk=pk)
                .first()
            )
            if job is None:
                continue
            if not ai_on(job.user, job.org):
                _finish(job, "failed", error="org_disabled")
                continue
            now = {a.key: a for a in _plan(job.user, job.org, skip_job_id=job.pk)}
            attempt = now.get(("pc", job.source_id))
            if attempt is None:
                _fall_through(job, "no_source")  # 그 사이 끈 공급원·권한·PC 바뀜 → 다음 AI
                continue
            if attempt.server is None or attempt.server.pk != server.pk:
                # 공급원의 PC를 바꿨다: 옛 PC에는 주지 않고 되돌려 워커가 지금 PC로 다시 배정한다
                job.status, job.route, job.server, job.claimed_at = "queued", "", None, None
                job.save(update_fields=["status", "route", "server", "claimed_at"])
                continue
            if job.source.is_codex and not codex:
                _fall_through(job, "codex_link_update" if codex is None else "codex_missing")
                continue
            try:
                payload = _payload(job)
            except Exception as e:  # 권한 회수·대상 삭제 등 — 조립 실패는 다른 항목으로도 안 된다
                log.warning("assist pc build failed job=%s err=%s", job.pk, type(e).__name__)
                _finish(job, "failed", error="pc_error")
                continue
            job.status, job.claimed_at = "running", timezone.now()
            job.save(update_fields=["status", "claimed_at"])
            return payload
    return None


def _payload(job) -> dict:
    """§8.3 생성 파라미터는 워커와 같은 prompts.spec_of."""
    src = job.source
    if src is None or not src.base_url:
        raise ValueError("no source")
    spec = prompts.spec_of(job)
    raw = src.api_key or ""
    out = {
        "id": job.pk,
        "url": src.base_url,
        "model": src.model,
        "api_key": decrypt(raw[len(_ENC) :]) if raw.startswith(_ENC) else "",
        "messages": prompts.build_messages(job, job.user),
        "max_tokens": spec.max_tokens,
        "temperature": spec.temperature,
        "response_format": {"type": "json_object"} if spec.want_json else None,
        "reasoning_effort": "none",  # 추론 모델이 max_tokens를 추론에 다 쓰지 않게(워커와 같다)
        "timeout_s": spec.timeout_s,
    }
    if src.is_codex:
        # PC의 Codex CLI(사용자 구독)로 실행. 키·주소 없음, 에이전트 기동이 느려 시간 상한을 넉넉히.
        out.update(backend="codex", url="", api_key="", timeout_s=timeout_s(job))
    return out


def timeout_s(job) -> int:
    """PC에 주는 시간 상한. Codex는 에이전트 기동이 느려 넉넉히. worker.sweep이 이것 + 여유로 정체를 정리한다."""
    t = prompts.spec_of(job).timeout_s
    return max(t, 180) if job.source and job.source.is_codex else t


def _verify(job, content: str) -> str:
    """워커와 같은 검증(§11.2)·후보 사후 처리. 형식 오류·대상 못 봄은 ValueError."""
    earliest = extract.earliest_due(job, job.user) if job.kind == "extract" else None
    result = prompts.parse_output(job, content, earliest=earliest)
    if job.kind == "extract":
        tasks = extract.postprocess(job, job.user, json.loads(result)["tasks"])
        result = json.dumps({"tasks": tasks}, ensure_ascii=False)
    if len(result.encode()) > AiJob.MAX_RESULT:
        raise ValueError("too_large")
    return result


def report(job_id: int, server, data: dict):
    """PATCH /api/integrations/stt/ai-jobs/{id}. data = SttAiReportIn.dict().

    job.server == server이고 그 주인 == 요청자일 때만(아니면 Http404), 끝난 작업이면 Finished(409).
    """
    with transaction.atomic():
        job = (
            AiJob.objects.select_for_update(of=("self",))
            .filter(pk=job_id, server=server, user_id=server.owner_id)
            .first()
        )
        if job is None:
            raise Http404
        if job.status not in LIVE:
            raise Finished
        status = data.get("status")
        if job.status == "cancelling" or status == "cancelled":
            _finish(job, "cancelled", error="cancelled")
        elif status == "done":
            try:
                result = _verify(job, data.get("content") or "")
            except Http404:
                _finish(job, "failed", error="no_source")  # 대상을 이제 볼 수 없다
                return job
            except ValueError as e:
                # ponytail: PC엔 재질문 없이 다음 항목으로. 재질문이 필요하면 PC 페이로드에 이전 답을 실어 다시 배정.
                _fall_through(job, "too_large" if str(e) == "too_large" else "bad_output")
                return job
            job.result, job.usage = result, data.get("usage") or {}
            _finish(job, "done")
            if job.source_id:
                AiSource.objects.filter(pk=job.source_id).update(
                    last_ok_at=job.finished_at, last_error=""
                )
        else:
            code = data.get("error") or ""
            _fall_through(job, code if code in PC_ERRORS else "pc_error")
        return job


def _release(pk: int, server, code: str) -> None:
    """PC가 놓친 작업: 취소 중이면 취소로 끝내고, 아니면 다음 항목으로 넘긴다."""
    with transaction.atomic():
        job = (
            AiJob.objects.select_for_update(of=("self",))
            .filter(pk=pk, server=server, status__in=LIVE)
            .first()
        )
        if job is None:
            return
        if job.status == "cancelling":
            _finish(job, "cancelled", error="cancelled")
        else:
            _fall_through(job, code)


def _fall_through(job, code: str) -> None:
    """PC 시도 실패 → tried에 남기고 다시 queued(route 빈 값). 다음 항목은 워커(A)가 tried를 보고 고른다(§4)."""
    job.tried = [*job.tried, {"route": "pc", "source_id": job.source_id, "error": code}]
    if job.source_id:
        AiSource.objects.filter(pk=job.source_id).update(last_error=code)
    job.status, job.route, job.server, job.claimed_at, job.error = "queued", "", None, None, code
    job.save(update_fields=["tried", "status", "route", "server", "claimed_at", "error"])


def _finish(job, status: str, *, error: str = "") -> None:
    job.status, job.error, job.finished_at = status, error, timezone.now()
    job.save(update_fields=["status", "error", "finished_at", "result", "usage"])
