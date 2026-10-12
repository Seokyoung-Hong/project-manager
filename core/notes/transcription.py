"""전사 작업(IMPL-PLAN-10-transcribe-menu). 전사문은 녹음을 글로 옮긴 원문이고, 회의록 본문과 따로 둔다.

실행은 Node 음성 서비스가 한다: 회의 종료 뒤 자동 전사(kind=auto)와, 화면에서 요청한 다시 전사(kind=retry)를
`claim`으로 가져간다. core는 상태·진행·취소 신호·예상 시간만 계산한다.
"""

import statistics
from datetime import timedelta

from django.db import transaction
from django.db.models import Exists, OuterRef
from django.utils import timezone

from common.errors import ServiceError
from orgs import settings as org_settings
from orgs.services import require_admin

from .models import TranscriptionJob, VoiceRecording

UPLOAD_SPEAKER = "올린 녹음"  # 올린 녹음 전사문의 화자 표기(화자 하나)

MIN_SEGMENT_MS = 1500  # discord_gateway/src/transcribe.mjs MIN_SEGMENT_MS
NODE_CONCURRENCY = 3  # transcribe.mjs CONCURRENCY
SEGMENT_OVERHEAD_S = 0.4  # 구간마다 변환·HTTP 고정비(추정)
DEFAULT_RTF = {"openai": 0.08}  # 로컬은 실측·서버 값이 없으면 "계산 중"
STALE_AFTER = timedelta(minutes=10)
MAX_SEGMENTS = 20000
OPENAI_MODEL = "whisper-1"

NO_SEGMENTS = "이 회의는 다시 전사를 지원하기 전에 녹음되어 다시 전사할 수 없습니다."
EXPIRED = "보관 기간이 지나 다시 전사할 수 없습니다."
NO_TRACKS = "참여자별 녹음이 없어 다시 전사할 수 없습니다."
NO_AUDIO = "녹음 파일이 없어 전사할 수 없습니다. 녹음 파일을 올려 주세요."
NO_ENGINE = "전사 수단이 없습니다. 조직 관리자에게 전사 서버나 조직 OpenAI 키 설정을 요청해 주세요."


def model_name(model: str, info: dict | None = None) -> str:
    """모델 이름. 제작자·계열은 서버가 준 값(display_name > owned_by·family + id)만 쓴다 — id로 추정하지 않는다."""
    info = info or {}
    name = str(info.get("display_name") or "").strip()
    if name:
        return name
    family = str(info.get("family") or "").strip()
    owner = str(info.get("owned_by") or "").strip()
    if owner and (owner in model or owner in family):
        owner = ""  # id·계열에 이미 들어 있다(Systran/…)
    return " ".join(x for x in (owner, family, model) if x) or "기본값(whisper-1)"


def model_label(engine: str, model: str, info: dict | None = None) -> str:
    """사용자에게 보이는 모델 이름 + 수단."""
    if engine == "openai":
        return f"OpenAI Whisper({model or OPENAI_MODEL}) · OpenAI API"
    return f"{model_name(model, info)} · 로컬 서버"


def speech_ms(segments: list) -> tuple[int, int]:
    """(전사할 음성 길이 ms, 구간 수). Node와 같이 1.5초 미만 구간은 뺀다."""
    todo = [int(g.get("duration_ms") or 0) for g in segments or []]
    todo = [d for d in todo if d >= MIN_SEGMENT_MS]
    return sum(todo), len(todo)


def clean_segments(rows) -> list[dict]:
    out = []
    for g in (rows or [])[:MAX_SEGMENTS]:
        try:
            out.append(
                {
                    "seq": int(g["seq"]),
                    "user_id": str(g["user_id"]),
                    "start_ms": max(0, int(g["start_ms"])),
                    "duration_ms": max(0, int(g["duration_ms"])),
                }
            )
        except (KeyError, TypeError, ValueError):
            continue
    return out


# ---------- 예상 시간(계획 §3) ----------


def parallel(engine: str, info: dict | None = None) -> int:
    if engine == "openai":
        return NODE_CONCURRENCY
    try:
        server = int((info or {}).get("concurrency") or 1)
    except (TypeError, ValueError):
        server = 1
    return max(1, min(NODE_CONCURRENCY, server))


def prior_rtf(org, engine: str, model: str, info: dict | None = None) -> float | None:
    """동시 처리를 반영한 처리 배수 사전값: 최근 실측 5건 중앙값 → 서버 rtf ÷ p → 기본값 ÷ p → 없음."""
    measured = list(
        TranscriptionJob.objects.filter(
            recording__note__org=org,
            engine=engine,
            model=model,
            status="done",
            measured_rtf__isnull=False,
        )
        .order_by("-finished_at")
        .values_list("measured_rtf", flat=True)[:5]
    )
    if measured:
        return statistics.median(measured)
    p = parallel(engine, info)
    rtf = (info or {}).get("rtf")
    if isinstance(rtf, int | float) and rtf > 0:
        return rtf / p
    base = DEFAULT_RTF.get(engine)
    return base / p if base else None


def estimate_s(audio_ms: int, segments: int, rtf: float | None, p: int) -> float | None:
    if rtf is None:
        return None
    return audio_ms / 1000 * rtf + segments * SEGMENT_OVERHEAD_S / p


def remaining_s(job, now=None) -> float | None:
    """진행 중이면 관측 속도와 사전값을 섞어, 아니면 사전값으로. 모르면 None("계산 중")."""
    now = now or timezone.now()
    a, d = job.audio_ms, min(job.done_ms, job.audio_ms)
    r0 = job.stats.get("prior_rtf") if isinstance(job.stats, dict) else None
    p = parallel(job.engine, job.stats if isinstance(job.stats, dict) else None)
    if a <= 0:
        return None  # 올린 녹음은 Node가 구간을 나누기 전까지 길이를 모른다
    if job.status == "queued" or not job.started_at or d <= 0:
        return estimate_s(a, job.segments_total, r0, p)
    r_obs = max(0.0, (now - job.started_at).total_seconds()) / (d / 1000)
    w = min(1.0, d / max(a * 0.3, 60000))
    r = r_obs if r0 is None else w * r_obs + (1 - w) * r0
    return (a - d) / 1000 * r


def eta_text(seconds: float | None) -> str:
    if seconds is None:
        return "예상 시간 계산 중"
    if seconds < 60:
        return "1분 안에 끝남"
    return f"약 {int(-(-seconds // 60))}분"


# ---------- Node 쪽(봇 API) ----------


def _org_engine(org) -> tuple[str, str]:
    if org_settings.effective("meeting.stt_url", org=org):
        return "local", org_settings.effective("meeting.stt_model", org=org) or OPENAI_MODEL
    if org_settings.secret_value("meeting.openai_api_key", org):
        return "openai", OPENAI_MODEL
    return "", ""


def start_auto_job(rec) -> TranscriptionJob:
    """회의 종료(transcribing) 때. Node는 대기열 없이 바로 전사하므로 running으로 만든다."""
    job = rec.jobs.filter(kind="auto", status__in=TranscriptionJob.RUNNING).first()
    if job:
        return job
    engine, model = _org_engine(rec.note.org)
    now = timezone.now()
    return TranscriptionJob.objects.create(
        recording=rec,
        kind="auto",
        status="running",
        engine=engine,
        model=model,
        started_at=now,
        progress_at=now,
        stats={"prior_rtf": prior_rtf(rec.note.org, engine, model)} if engine else {},
    )


def active_job(rec):
    return rec.jobs.filter(status__in=TranscriptionJob.ACTIVE).order_by("created_at").first()


def _finish(job, status: str, *, transcript_md: str | None = None, stats=None, error: str = ""):
    now = timezone.now()
    job.status = status
    job.finished_at = now
    job.error = error[:40]
    if stats:
        job.stats = {**(job.stats or {}), **stats}
    if transcript_md is not None:
        job.transcript_md = transcript_md
    if status == "done" and job.started_at and job.audio_ms:
        job.measured_rtf = (now - job.started_at).total_seconds() / (job.audio_ms / 1000)
    job.save()
    if status == "done":
        rec = job.recording
        rec.transcript_md = job.transcript_md
        rec.transcript_job = job
        rec.save(update_fields=["transcript_md", "transcript_job"])


def finish_auto_job(rec, *, transcript_md: str | None, stats: dict | None):
    """기존 draft PATCH(전사문·통계)로 자동 작업을 마친다. 취소된 작업이면 그대로 둔다."""
    job = rec.jobs.filter(kind="auto", status__in=TranscriptionJob.RUNNING).first()
    if job is None:
        return
    stats = stats or {}
    if stats.get("engine") == "none":
        _finish(job, "failed", stats=stats, error="no_engine")
    elif stats.get("cancelled"):
        _finish(job, "cancelled", stats=stats)
    else:
        _finish(job, "done", transcript_md=transcript_md or "", stats=stats)


def fail_active(rec):
    for job in rec.jobs.filter(status__in=TranscriptionJob.ACTIVE):
        _finish(job, "failed", error="meeting_failed")


@transaction.atomic
def report(job_id: int, data: dict) -> TranscriptionJob:
    """Node 진행·결과 보고. 응답의 cancel(= status cancelling)을 보고 Node가 멈춘다."""
    job = TranscriptionJob.objects.select_for_update().select_related("recording").get(pk=job_id)
    for key in ("done_ms", "segments_done", "segments_total", "segments_failed", "audio_ms"):
        if data.get(key) is not None:
            setattr(job, key, max(0, int(data[key])))
    for key in ("engine", "model"):
        if data.get(key):
            setattr(job, key, str(data[key])[:200])
    job.progress_at = timezone.now()
    status = data.get("status")
    if job.status in TranscriptionJob.RUNNING and status in ("done", "failed", "cancelled"):
        _finish(
            job,
            status,
            transcript_md=data.get("transcript_md"),
            stats=data.get("stats"),
            error=str(data.get("error") or ""),
        )
    else:
        if data.get("stats"):
            job.stats = {**(job.stats or {}), **data["stats"]}
        job.save()
    return job


def _retry_payload(job) -> dict:
    rec = job.recording
    return {
        "job": {"id": job.pk, "recording_id": rec.pk, "engine": job.engine, "model": job.model},
        # upload: 녹음 파일 하나를 받아 무음 기준으로 구간을 나눈다(segments·tracks 없음)
        "source": rec.source,
        "speaker": UPLOAD_SPEAKER if rec.source == "upload" else "",
        "segments": rec.segments,
        "tracks": list(rec.tracks.exclude(audio="").values_list("discord_user_id", flat=True)),
        "participants": rec.participants,
    }


@transaction.atomic
def claim():
    """가장 오래된 대기 작업 하나를 running으로. 같은 회의에 아직 돌고 있는 작업이 있으면 건너뛴다."""
    busy = TranscriptionJob.objects.filter(
        recording=OuterRef("recording"), status__in=TranscriptionJob.RUNNING
    )
    job = (
        TranscriptionJob.objects.select_for_update(skip_locked=True)
        .filter(status="queued")
        .exclude(Exists(busy))
        .order_by("created_at", "id")
        .first()
    )
    if job is None:
        return None
    now = timezone.now()
    job.status, job.started_at, job.progress_at = "running", now, now
    job.save(update_fields=["status", "started_at", "progress_at"])
    return job


@transaction.atomic
def requeue() -> int:
    """Node 기동 때: 하던 다시 전사를 대기로 되돌린다(취소 중이던 것은 취소로). 자동 작업은 Node가 이어 간다."""
    n = 0
    for job in TranscriptionJob.objects.select_for_update().filter(
        kind="retry", status__in=TranscriptionJob.RUNNING
    ):
        if job.status == "cancelling" or job.recording.jobs.filter(status="queued").exists():
            _finish(job, "cancelled")
        else:
            job.status, job.done_ms, job.segments_done, job.segments_failed = "queued", 0, 0, 0
            job.save()
        n += 1
    return n


# ---------- 화면(조직 관리자) ----------


def retry_block(rec) -> str:
    """다시 전사를 못 하는 이유. 할 수 있으면 ""."""
    from .services import audio_expired

    if audio_expired(rec):
        return EXPIRED
    if rec.source == "upload":
        return "" if rec.audio else NO_AUDIO
    if not rec.segments:
        return NO_SEGMENTS
    if not rec.tracks.exclude(audio="").exists():
        return NO_TRACKS
    return ""


@transaction.atomic
def request_retry(rec, *, engine: str, model: str, actor, info: dict | None = None):
    """다시 전사 요청(전사 메뉴, 조직 관리자). 돌고 있는 작업은 취소 중으로, 대기 작업은 새 요청으로 바꾼다."""
    rec = VoiceRecording.objects.select_for_update().select_related("note__org").get(pk=rec.pk)
    require_admin(actor, rec.note.org)
    kind = "upload" if rec.source == "upload" and not rec.jobs.exists() else "retry"
    return _enqueue(rec, engine=engine, model=model, actor=actor, info=info, kind=kind)


@transaction.atomic
def request_upload(rec, *, actor):
    """올린 녹음 [전사] — 회의록을 고칠 수 있는 사람. 조직 기본 수단·모델로 대기열에 넣는다."""
    from .services import _check_edit

    rec = VoiceRecording.objects.select_for_update().select_related("note__org").get(pk=rec.pk)
    _check_edit(rec.note, actor, "web")
    if rec.source != "upload":
        raise ServiceError({"job": "올린 녹음만 여기서 전사할 수 있습니다."})
    if rec.jobs.filter(status__in=TranscriptionJob.ACTIVE).exists():
        raise ServiceError({"job": "이미 전사 대기 중이거나 전사 중입니다."})
    engine, model = _org_engine(rec.note.org)
    if not engine:
        raise ServiceError({"engine": NO_ENGINE})
    return _enqueue(rec, engine=engine, model=model, actor=actor, info=None, kind="upload")


def _enqueue(rec, *, engine: str, model: str, actor, info, kind: str):
    org = rec.note.org
    if rec.status not in ("draft", "done"):
        raise ServiceError({"job": "회의 전사가 끝난 뒤 다시 전사해 주세요."})
    if why := retry_block(rec):
        raise ServiceError({"job": why})
    if engine not in ("local", "openai"):
        raise ServiceError({"engine": "전사 수단을 골라 주세요."})
    if engine == "local" and not org_settings.effective("meeting.stt_url", org=org):
        raise ServiceError(
            {"engine": "로컬 전사 서버 주소가 없습니다. 전사 서버 보기에서 주소를 저장해 주세요."}
        )
    if engine == "openai" and not org_settings.secret_value("meeting.openai_api_key", org):
        raise ServiceError(
            {"engine": "조직 OpenAI 키가 없습니다. 전사 서버 보기에서 키를 저장해 주세요."}
        )
    model = (model or "").strip()[:200] or OPENAI_MODEL
    for old in rec.jobs.filter(status="queued"):
        _finish(old, "cancelled")
    rec.jobs.filter(status="running").update(status="cancelling")
    a, n = speech_ms(rec.segments)
    stats = {
        "prior_rtf": prior_rtf(org, engine, model, info),
        "label": model_label(engine, model, info),
    }
    if info:
        stats.update(
            {k: info[k] for k in ("device", "compute_type", "rtf", "concurrency") if k in info}
        )
    return TranscriptionJob.objects.create(
        recording=rec,
        kind=kind,
        status="queued",
        engine=engine,
        model=model,
        requested_by=actor,
        audio_ms=a,
        segments_total=n,
        stats=stats,
    )


@transaction.atomic
def cancel(job, actor) -> TranscriptionJob:
    job = (
        TranscriptionJob.objects.select_for_update()
        .select_related("recording__note__org")
        .get(pk=job.pk)
    )
    require_admin(actor, job.recording.note.org)
    if job.status == "queued" or (job.status in TranscriptionJob.RUNNING and is_stale(job)):
        _finish(job, "cancelled")  # 응답 없는 작업은 Node를 기다리지 않는다
    elif job.status == "running":
        job.status = "cancelling"
        job.save(update_fields=["status"])
    return job


@transaction.atomic
def use(job, actor) -> None:
    """이 시도의 전사문을 현재 전사문으로 지정한다. 회의록 본문은 바꾸지 않는다."""
    require_admin(actor, job.recording.note.org)
    if job.status != "done":
        raise ServiceError({"job": "끝난 전사 작업만 현재 전사문으로 지정할 수 있습니다."})
    rec = job.recording
    rec.transcript_md, rec.transcript_job = job.transcript_md, job
    rec.save(update_fields=["transcript_md", "transcript_job"])


def is_stale(job, now=None) -> bool:
    now = now or timezone.now()
    seen = job.progress_at or job.started_at
    return job.status in TranscriptionJob.RUNNING and seen is not None and now - seen > STALE_AFTER


def queue_eta(jobs) -> dict:
    """작업 id → (남은 초, 시작까지 초). 대기 작업은 앞선 작업들의 남은 시간을 더한다."""
    now = timezone.now()
    out, ahead = {}, 0.0
    for job in sorted(jobs, key=lambda j: (j.status == "queued", j.created_at, j.pk)):
        left = remaining_s(job, now)
        if job.status == "queued":
            out[job.pk] = (left, ahead)
        else:
            out[job.pk] = (left, 0.0)
        ahead += left or 0.0
    return out
