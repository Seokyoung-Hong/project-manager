"""전사 작업(IMPL-PLAN-10-transcribe-menu). 전사문은 녹음을 글로 옮긴 원문이고, 회의록 본문과 따로 둔다.

실행은 Node 음성 서비스가 한다: 회의 종료 뒤 자동 전사(kind=auto)와, 화면에서 요청한 다시 전사(kind=retry)를
`claim`으로 가져간다. core는 상태·진행·취소 신호·예상 시간만 계산한다.

내 PC 전사(IMPL-PLAN-11-local-stt-link): `server`가 있는 작업(engine="pc")은 그 PC만 `claim_for`로 가져간다.
PC가 꺼지면(`gone`) 자동 작업은 조직 수단으로 넘긴다. 백그라운드 실행기가 없어 점검(`sweep`)은
Node `claim()`과 PC heartbeat가 부를 때 게으르게 한다.
"""

import statistics
from datetime import timedelta

from django.db import transaction
from django.db.models import Exists, OuterRef, Q
from django.utils import timezone

from common.errors import ServiceError
from orgs import settings as org_settings
from orgs.services import is_admin

from .models import SttServer, TranscriptionJob, VoiceRecording

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
TRANSCRIBE_FAILED = "[전사 실패]"  # discord_gateway/src/texts.mjs TRANSCRIBE_FAILED

# 사용자 문구 — 임시(최종 문구는 docs/drafts/local-stt-link-copy.md에서 Sol이 정한다)
PC_DISABLED_BY_ORG = (
    "이 조직은 멤버 PC로 전사하지 않도록 설정되어 있습니다."  # COPY:pc_disabled_by_org
)
PC_OFFLINE = (
    "고른 PC가 꺼져 있습니다. PC에서 전사 서버를 켠 뒤 다시 시도해 주세요."  # COPY:pc_offline
)
PC_NOT_MINE = "내 PC 전사 서버만 고를 수 있습니다."  # COPY:pc_not_mine
PC_NO_MODEL = "내 PC에 준비된 모델을 골라 주세요."  # COPY:pc_no_model
ORG_STT_NO_PERMISSION = "조직 전사 수단은 조직 관리자만 쓸 수 있습니다. 내 PC를 연결해 전사해 주세요."  # COPY:org_stt_no_permission
ORG_STT_ALREADY_USED = (
    "이 녹음은 이미 조직 전사 수단으로 전사했습니다. "
    "내 PC로 전사하거나 조직 관리자에게 요청해 주세요."  # COPY:org_stt_already_used
)
NO_ACCESS = "이 녹음을 볼 수 있는 사람만 전사할 수 있습니다."  # COPY:no_access

# 켜짐 판정(§7.1). heartbeat 5초 × 3번 = 켜짐, 2분 = 자동 작업을 넘기는 기준, 사람이 고른 PC는 하루 기다린다.
ONLINE_FOR = timedelta(seconds=15)
GONE_AFTER = timedelta(minutes=2)
PC_WAIT = timedelta(hours=24)
PC_RELEASE = ("pc_offline", "pc_unlinked", "pc_disabled")  # PC 작업을 놓은 이유(error)

STATUS_LABELS = {"downloading": "받는 중", "not_downloaded": "받지 않음"}
INFO_KEYS = (
    "display_name",
    "family",
    "owned_by",
    "fits",
    "device",
    "compute_type",
    "rtf",
    "concurrency",
)


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
    if engine == "pc":
        return f"내 PC · {model_name(model, info)}"  # COPY:pc_model_label
    if engine == "openai":
        return f"OpenAI Whisper({model or OPENAI_MODEL}) · OpenAI API"
    return f"{model_name(model, info)} · 로컬 서버"


def pc_label(server, model: str, info: dict | None = None, *, many: bool = False) -> str:
    """내 PC 선택지·작업 표시. 예: "내 PC · OpenAI Whisper large-v3-turbo". 서버가 여러 대면 서버 이름을 넣는다."""
    who = f"내 PC({server.name})" if many else "내 PC"  # COPY:pc_model_label
    return f"{who} · {model_name(model, info)}"


def parse_models(items) -> list[dict]:
    """/v1/models data 배열 → [{id, status, label, error, name, fits, info}].

    조직 서버 조회(web.views.orgs.stt_models)와 PC heartbeat 저장본이 같이 쓴다.
    status가 없는 서버(일반 OpenAI 호환)는 ready로 본다. 형식이 틀린 항목은 건너뛴다.
    """
    out = []
    for m in items or []:
        if not (isinstance(m, dict) and m.get("id")):
            continue
        status = str(m.get("status") or "ready")
        label = STATUS_LABELS.get(status, "")
        if status == "downloading" and isinstance(m.get("progress"), int | float):
            label += f" {round(m['progress'] * 100)}%"
        info = {k: m[k] for k in INFO_KEYS if m.get(k) not in (None, "")}
        if info.get("fits") is False:
            label = "이 서버에서 쓸 수 없음"
        mid = str(m["id"])[:200]
        out.append(
            {
                "id": mid,
                "status": status,
                "label": label,
                "error": str(m.get("error") or "")[:200],
                "name": model_name(mid, info),
                "fits": info.get("fits") is not False,
                "info": info,
            }
        )
    return out


def ready_model(server, model: str) -> dict | None:
    """서버의 모델 중 받아 두었고 이 PC에 맞는 것."""
    for m in parse_models(server.models):
        if m["id"] == model and m["status"] == "ready" and m["fits"]:
            return m
    return None


def online(server, now=None) -> bool:
    now = now or timezone.now()
    return bool(server and server.last_seen_at and server.last_seen_at > now - ONLINE_FOR)


def gone(server, now=None) -> bool:
    now = now or timezone.now()
    return server is None or server.last_seen_at is None or server.last_seen_at < now - GONE_AFTER


def member_pc(org) -> bool:
    return bool(org_settings.effective("meeting.member_pc", org=org))


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


def _job_stats(org, engine: str, model: str, info: dict | None, server=None) -> dict:
    """작업 생성 때 남기는 세부 정보. 표시 이름(label)은 생성 시점 값이라 서버를 지워도 기록이 읽힌다."""
    p_info = {**(info or {})}
    if server is not None:
        p_info.setdefault("concurrency", server.concurrency)
    stats = {
        "prior_rtf": prior_rtf(org, engine, model, p_info),
        "label": pc_label(server, model, info) if server else model_label(engine, model, info),
    }
    stats.update(
        {k: p_info[k] for k in ("device", "compute_type", "rtf", "concurrency") if k in p_info}
    )
    return stats


# ---------- Node 쪽(봇 API) ----------


def _org_engine(org) -> tuple[str, str]:
    if org_settings.effective("meeting.stt_url", org=org):
        return "local", org_settings.effective("meeting.stt_model", org=org) or OPENAI_MODEL
    if org_settings.secret_value("meeting.openai_api_key", org):
        return "openai", OPENAI_MODEL
    return "", ""


def auto_server(rec):
    """자동 전사를 맡길 진행자 PC(§7.3-1). 켜져 있고 마지막 [모델 적용] 모델이 준비된 것 중 가장 최근 응답."""
    org = rec.note.org
    if not member_pc(org) or org_settings.effective("meeting.audio_keep_days", org=org) <= 0:
        return None  # 보관 0일이면 Node가 녹음을 지운 뒤라 PC가 받을 수 없다
    now = timezone.now()
    for server in SttServer.objects.filter(owner_id=rec.host_id).order_by("-last_seen_at"):
        if (
            online(server, now)
            and server.default_model
            and ready_model(server, server.default_model)
        ):
            return server
    return None


def start_auto_job(rec) -> TranscriptionJob:
    """회의 종료(transcribing) 때. Node는 대기열 없이 바로 전사하므로 running으로 만든다.

    진행자 PC가 켜져 있으면 그 PC에 queued로 맡긴다 — Node는 names의 stt가 비어 녹음만 올리고(§7.3),
    PC는 draft 뒤 입력이 다 올라오면 가져간다.
    """
    job = rec.jobs.filter(kind="auto", status__in=TranscriptionJob.ACTIVE).first()
    if job:
        return job
    org = rec.note.org
    server = auto_server(rec)
    if server is not None:
        info = (ready_model(server, server.default_model) or {}).get("info")
        return TranscriptionJob.objects.create(
            recording=rec,
            kind="auto",
            status="queued",
            engine="pc",
            model=server.default_model,
            server=server,
            requested_by=rec.host,
            stats=_job_stats(org, "pc", server.default_model, info, server),
        )
    engine, model = _org_engine(org)
    now = timezone.now()
    return TranscriptionJob.objects.create(
        recording=rec,
        kind="auto",
        status="running",
        engine=engine,
        model=model,
        started_at=now,
        progress_at=now,
        stats={"prior_rtf": prior_rtf(org, engine, model)} if engine else {},
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
    """기존 draft PATCH(전사문·통계)로 자동 작업을 마친다. 자동 작업을 닫는 유일한 자리다(§7.3-4).

    - Node가 바로 전사한 running 자동 작업 → 지금처럼 닫는다.
    - PC 자동 작업이 대기 중 → 구간 길이를 채우고 PC를 기다린다(말한 구간이 없으면 바로 끝).
    - PC 자동 작업이 transcribing 중에 놓였다 → Node가 빈 stt로 건너뛰었으면 조직 수단 대기열로,
      조직 stt로 이미 전사했으면 그 결과를 끝난 작업으로 남긴다. 어느 쪽이든 전사는 한 번이다.
    """
    stats = stats or {}
    job = rec.jobs.filter(kind="auto", status__in=TranscriptionJob.RUNNING).first()
    if job is None:
        _finish_pc_auto(rec, transcript_md, stats)
    elif stats.get("engine") == "none":
        _finish(job, "failed", stats=stats, error="no_engine")
    elif stats.get("cancelled"):
        _finish(job, "cancelled", stats=stats)
    else:
        _finish(job, "done", transcript_md=transcript_md or "", stats=stats)


def _finish_pc_auto(rec, transcript_md, stats):
    pc = rec.jobs.filter(kind="auto", engine="pc", status="queued").first()
    if pc is not None:
        pc.audio_ms, pc.segments_total = speech_ms(rec.segments)
        pc.save(update_fields=["audio_ms", "segments_total"])
        if not pc.segments_total:
            _finish(pc, "done", transcript_md="")  # 말한 구간이 없다
        return
    last = rec.jobs.filter(kind="auto").order_by("-created_at", "-id").first()
    if not (
        last is not None
        and last.engine == "pc"
        and last.status == "cancelled"
        and last.error in PC_RELEASE
    ):
        return
    org = rec.note.org
    engine, model = _org_engine(org)
    if not last.stats.get("stt_withheld"):
        # Node가 조직 stt를 받아 이미 전사했다 — 그 결과가 곧 자동 전사다
        done = TranscriptionJob.objects.create(
            recording=rec,
            kind="auto",
            status="running",
            engine=engine,
            model=model,
            stats={"handoff": True},
        )
        if stats.get("engine") == "none":
            _finish(done, "failed", stats=stats, error="no_engine")
        else:
            _finish(done, "done", transcript_md=transcript_md or "", stats=stats)
        return
    if not engine:
        TranscriptionJob.objects.create(
            recording=rec,
            kind="auto",
            status="failed",
            error="no_engine",
            finished_at=timezone.now(),
            stats={"handoff": True},
        )
        return
    a, n = speech_ms(rec.segments)
    TranscriptionJob.objects.create(
        recording=rec,
        kind="auto",
        status="queued",
        engine=engine,
        model=model,
        audio_ms=a,
        segments_total=n,
        stats={**_job_stats(org, engine, model, None), "handoff": True},
    )


def pc_auto_waiting(rec) -> bool:
    """draft 알림 문구용: 진행자 PC가 자동 전사를 맡고 있는가."""
    return rec.jobs.filter(kind="auto", engine="pc", status__in=TranscriptionJob.ACTIVE).exists()


def withhold_stt(rec) -> bool:
    """Node가 names를 부를 때: 진행자 PC 자동 작업이 살아 있으면 stt를 비워 Node가 녹음만 올리게 한다(§7.3-3)."""
    job = rec.jobs.filter(kind="auto", engine="pc", status__in=TranscriptionJob.ACTIVE).first()
    if job is None:
        return False
    if not job.stats.get("stt_withheld"):
        job.stats = {**job.stats, "stt_withheld": True}
        job.save(update_fields=["stats"])
    return True


def fail_active(rec):
    for job in rec.jobs.filter(status__in=TranscriptionJob.ACTIVE):
        _finish(job, "failed", error="meeting_failed")


@transaction.atomic
def report(job_id: int, data: dict) -> TranscriptionJob:
    """Node·PC 진행·결과 보고. 응답의 cancel(= status cancelling)을 보고 작업자가 멈춘다.
    PC 경로는 engine·model을 넘기지 않는다(api.routers.stt)."""
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


def _busy():
    return TranscriptionJob.objects.filter(
        recording=OuterRef("recording"), status__in=TranscriptionJob.RUNNING
    )


def _start(job):
    now = timezone.now()
    job.status, job.started_at, job.progress_at, job.claimed_at = "running", now, now, now
    job.save(update_fields=["status", "started_at", "progress_at", "claimed_at"])
    return job


def claim():
    """Node: 서버가 정해지지 않은 가장 오래된 대기 작업 하나를 running으로. 같은 회의에 돌고 있는 작업이 있으면 건너뛴다."""
    sweep()
    with transaction.atomic():
        job = (
            TranscriptionJob.objects.select_for_update(skip_locked=True)
            .filter(status="queued", server__isnull=True)
            .exclude(engine="pc")
            .exclude(Exists(_busy()))
            .order_by("created_at", "id")
            .first()
        )
        return _start(job) if job else None


def inputs_ready(rec) -> bool:
    """PC가 가져가도 되는가: 올린 녹음은 파일, Discord는 구간에 나온 모든 화자의 트랙이 올라왔을 때(§4).
    (retry_block은 트랙이 하나라도 있으면 통과라서 쓰지 않는다 — 일부 화자만 전사된다.)"""
    if rec.source == "upload":
        return bool(rec.audio)
    speakers = {str(g.get("user_id")) for g in rec.segments or []}
    tracks = set(rec.tracks.exclude(audio="").values_list("discord_user_id", flat=True))
    return speakers <= tracks


def claim_for(server):
    """PC: 이 서버에 배정된 대기 작업 하나. 녹음이 draft·done이고 입력이 다 올라왔고 주인이 지금도 볼 수 있을 때만."""
    from .services import audio_expired, get_visible_note

    with transaction.atomic():
        jobs = list(
            TranscriptionJob.objects.select_for_update(skip_locked=True)
            .filter(status="queued", server=server)
            .exclude(Exists(_busy()))
            .order_by("created_at", "id")
        )
        for job in jobs:
            rec = VoiceRecording.objects.select_related("note__org").get(pk=job.recording_id)
            if not member_pc(rec.note.org):
                release_pc_job(job, "pc_disabled")
            elif rec.status not in ("draft", "done") or not inputs_ready(rec):
                continue
            elif get_visible_note(server.owner, rec.note_id) is None:
                _finish(job, "failed", error="no_access")
            elif audio_expired(rec):
                _finish(job, "failed", error="expired")
            else:
                return _start(job)
    return None


def requeue_or_cancel(job_id: int, **fields) -> TranscriptionJob | None:
    """작업을 다시 대기로(§7.6). running → queued로 바꾸는 모든 경로가 이것만 쓴다.

    녹음당 대기는 하나뿐이라(uniq_transcription_queued) 취소 중이었거나 같은 녹음에 다른 대기 작업이 있으면
    취소로 끝낸다. 녹음 행을 먼저 잠근다(request_retry와 같은 순서).
    """
    with transaction.atomic():
        rec_ids = TranscriptionJob.objects.filter(pk=job_id).values("recording_id")
        list(VoiceRecording.objects.select_for_update().filter(pk__in=rec_ids))
        job = TranscriptionJob.objects.select_for_update().filter(pk=job_id).first()
        if job is None or job.status not in TranscriptionJob.ACTIVE:
            return job
        others = job.recording.jobs.filter(status="queued").exclude(pk=job.pk).exists()
        if job.status == "cancelling" or others:
            _finish(job, "cancelled")
            return job
        for k, v in fields.items():
            setattr(job, k, v)
        job.status = "queued"
        job.done_ms = job.segments_done = job.segments_failed = 0
        job.started_at = job.progress_at = job.claimed_at = None
        job.save()
        return job


def _handoff(job):
    """PC 자동 작업을 조직 수단으로 넘긴다(§7.3-6-나). 조직 수단도 없으면 실패(no_engine).
    넘긴 작업은 `stats.handoff`로 표시해 조직 수단 시도 한도에서 뺀다."""
    org = job.recording.note.org
    engine, model = _org_engine(org)
    if not engine:
        _finish(job, "failed", error="no_engine")
        return
    requeue_or_cancel(
        job.pk,
        server=None,
        engine=engine,
        model=model,
        stats={**_job_stats(org, engine, model, None), "handoff": True},
    )


def release_pc_job(job, reason: str):
    """PC가 맡은 작업을 놓는다(꺼짐·끊기·조직에서 끔).

    자동 작업: 회의가 draft 전이면 취소만 한다(Node 기본 경로가 받는다 — 넘기면 Node 즉시 전사와 겹친다).
    draft 뒤면 조직 수단으로 넘긴다. 사람이 고른 작업은 취소한다.
    """
    rec = VoiceRecording.objects.get(pk=job.recording_id)
    if job.kind == "auto" and rec.status in ("draft", "done"):
        _handoff(job)
    else:
        _finish(job, "cancelled", error=reason)


def sweep(now=None) -> None:
    """PC 작업 점검(게으르게, §7.3-6·§7.2). 백그라운드 실행기가 없어 Node claim·PC heartbeat가 부른다."""
    now = now or timezone.now()
    jobs = TranscriptionJob.objects.filter(
        engine="pc", status__in=TranscriptionJob.ACTIVE
    ).select_related("server", "recording__note__org")
    for job in jobs:
        if not gone(job.server, now):
            continue
        if job.kind == "auto":
            release_pc_job(job, "pc_offline")
        elif job.server is None or job.created_at < now - PC_WAIT:
            _finish(job, "cancelled", error="pc_offline")
        elif job.status in TranscriptionJob.RUNNING:
            requeue_or_cancel(job.pk)  # 사람이 고른 PC를 계속 기다린다


def requeue() -> int:
    """Node 기동 때: Node가 가져갔던 작업(다시 전사·올린 녹음·넘겨받은 자동 작업)을 대기로 되돌린다.
    취소 중이던 것은 취소로. Node가 바로 전사하던 자동 작업(가져간 적 없음)은 Node가 이어 간다."""
    ids = list(
        TranscriptionJob.objects.filter(server__isnull=True, status__in=TranscriptionJob.RUNNING)
        .exclude(engine="pc")
        .filter(Q(claimed_at__isnull=False) | Q(kind="retry"))
        .values_list("pk", flat=True)
    )
    for pk in ids:
        requeue_or_cancel(pk)
    return len(ids)


# ---------- 화면(권한 §8) ----------


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


def can_use_org_stt(user, org) -> bool:
    """조직 자원(조직 서버 주소·OpenAI 키)으로 전사를 지시할 수 있는가(§8)."""
    return is_admin(user, org) or (
        org_settings.effective("meeting.transcribe_level", org=org) == "member"
    )


def org_used(rec) -> bool:
    """녹음당 1회 한도(사용자 결정 9): 사람이 조직 수단으로 시작한 전사가 이미 있는가(누가 했든).
    자동 전사·넘겨받은 작업·가져가기 전에 취소된 작업은 세지 않는다."""
    for job in rec.jobs.filter(engine__in=("local", "openai")).exclude(kind="auto"):
        if (job.stats or {}).get("handoff"):
            continue
        if job.status == "cancelled" and job.claimed_at is None and job.started_at is None:
            continue
        return True
    return False


def org_block(rec, actor) -> str:
    """조직 수단을 고를 수 없는 이유(멤버). 고를 수 있으면 ""."""
    org = rec.note.org
    if not can_use_org_stt(actor, org):
        return ORG_STT_NO_PERMISSION
    if not is_admin(actor, org) and org_used(rec):
        return ORG_STT_ALREADY_USED
    return ""


def check_request(rec, actor, engine: str, server=None) -> None:
    """전사 지시 권한·한도(§8). 웹 전사 메뉴와 회의록 [전사 시작]이 같이 부른다."""
    from .services import get_visible_note

    org = rec.note.org
    if get_visible_note(actor, rec.note_id) is None:
        raise ServiceError({"job": NO_ACCESS})
    if engine == "pc":
        if server is None or server.owner_id != actor.pk:
            raise ServiceError({"engine": PC_NOT_MINE})
        if not member_pc(org):
            raise ServiceError({"engine": PC_DISABLED_BY_ORG})
        if not online(server):
            raise ServiceError({"engine": PC_OFFLINE})
        return
    if engine not in ("local", "openai"):
        raise ServiceError({"engine": "전사 수단을 골라 주세요."})
    if why := org_block(rec, actor):
        raise ServiceError({"engine": why})


@transaction.atomic
def request_retry(rec, *, engine: str, model: str, actor, info: dict | None = None, server=None):
    """다시 전사 요청(전사 메뉴). 돌고 있는 작업은 취소 중으로, 대기 작업은 새 요청으로 바꾼다."""
    rec = VoiceRecording.objects.select_for_update().select_related("note__org").get(pk=rec.pk)
    check_request(rec, actor, engine, server)
    kind = "upload" if rec.source == "upload" and not rec.jobs.exists() else "retry"
    return _enqueue(
        rec, engine=engine, model=model, actor=actor, info=info, kind=kind, server=server
    )


@transaction.atomic
def request_upload(rec, *, actor, engine: str = "", model: str = "", info=None, server=None):
    """올린 녹음 [전사 시작]. 수단을 고르지 않으면 조직 기본 수단·모델로 대기열에 넣는다."""
    rec = VoiceRecording.objects.select_for_update().select_related("note__org").get(pk=rec.pk)
    if rec.source != "upload":
        raise ServiceError({"job": "올린 녹음만 여기서 전사할 수 있습니다."})
    if rec.jobs.filter(status__in=TranscriptionJob.ACTIVE).exists():
        raise ServiceError({"job": "이미 전사 대기 중이거나 전사 중입니다."})
    if not engine:
        engine, model = _org_engine(rec.note.org)
        if not engine:
            raise ServiceError({"engine": NO_ENGINE})
    check_request(rec, actor, engine, server)
    return _enqueue(
        rec, engine=engine, model=model, actor=actor, info=info, kind="upload", server=server
    )


def _enqueue(rec, *, engine: str, model: str, actor, info, kind: str, server=None):
    org = rec.note.org
    if rec.status not in ("draft", "done"):
        raise ServiceError({"job": "회의 전사가 끝난 뒤 다시 전사해 주세요."})
    if why := retry_block(rec):
        raise ServiceError({"job": why})
    if engine == "pc":
        if server is None or not ready_model(server, model):
            raise ServiceError({"engine": PC_NO_MODEL})
    elif engine not in ("local", "openai"):
        raise ServiceError({"engine": "전사 수단을 골라 주세요."})
    elif engine == "local" and not org_settings.effective("meeting.stt_url", org=org):
        raise ServiceError(
            {"engine": "로컬 전사 서버 주소가 없습니다. 전사 서버 보기에서 주소를 저장해 주세요."}
        )
    elif engine == "openai" and not org_settings.secret_value("meeting.openai_api_key", org):
        raise ServiceError(
            {"engine": "조직 OpenAI 키가 없습니다. 전사 서버 보기에서 키를 저장해 주세요."}
        )
    model = (model or "").strip()[:200] or OPENAI_MODEL
    for old in rec.jobs.filter(status="queued"):
        _finish(old, "cancelled")
    rec.jobs.filter(status="running").update(status="cancelling")
    a, n = speech_ms(rec.segments)
    return TranscriptionJob.objects.create(
        recording=rec,
        kind=kind,
        status="queued",
        engine=engine,
        model=model,
        server=server if engine == "pc" else None,
        requested_by=actor,
        audio_ms=a,
        segments_total=n,
        stats=_job_stats(org, engine, model, info, server if engine == "pc" else None),
    )


def can_cancel(job, actor) -> bool:
    """§8: 관리자, 조직 수단은 요청자, 내 PC는 서버 주인."""
    if is_admin(actor, job.recording.note.org):
        return True
    if job.engine == "pc":
        return job.server is not None and job.server.owner_id == actor.pk
    return job.requested_by_id is not None and job.requested_by_id == actor.pk


def can_use(job, actor) -> bool:
    """[현재 전사문으로 지정]: 관리자 또는 회의록 편집 권한."""
    from common.errors import Forbidden

    from .services import _check_edit

    note = job.recording.note
    if is_admin(actor, note.org):
        return True
    try:
        _check_edit(note, actor, "web")
    except (ServiceError, Forbidden):
        return False
    return True


@transaction.atomic
def cancel(job, actor) -> TranscriptionJob:
    job = (
        TranscriptionJob.objects.select_for_update(of=("self",))
        .select_related("recording__note__org", "server")
        .get(pk=job.pk)
    )
    if not can_cancel(job, actor):
        raise ServiceError({"job": "이 전사를 취소할 권한이 없습니다."})
    if job.status == "queued" or (job.status in TranscriptionJob.RUNNING and is_stale(job)):
        _finish(job, "cancelled")  # 응답 없는 작업은 작업자를 기다리지 않는다
    elif job.status == "running":
        job.status = "cancelling"
        job.save(update_fields=["status"])
    return job


@transaction.atomic
def use(job, actor) -> None:
    """이 시도의 전사문을 현재 전사문으로 지정한다. 회의록 본문은 바꾸지 않는다."""
    if not can_use(job, actor):
        raise ServiceError({"job": "현재 전사문을 지정할 권한이 없습니다."})
    if job.status != "done":
        raise ServiceError({"job": "끝난 전사 작업만 현재 전사문으로 지정할 수 있습니다."})
    rec = job.recording
    rec.transcript_md, rec.transcript_job = job.transcript_md, job
    rec.save(update_fields=["transcript_md", "transcript_job"])


def is_stale(job, now=None) -> bool:
    now = now or timezone.now()
    if job.status not in TranscriptionJob.RUNNING:
        return False
    if job.engine == "pc" and gone(job.server, now):
        return True  # PC가 응답이 없으면 취소를 기다리지 않는다(§7.4)
    seen = job.progress_at or job.started_at
    return seen is not None and now - seen > STALE_AFTER


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


def format_transcript(rows, names: dict) -> str:
    """PC가 올린 구간 결과 → 전사문. Node `formatTranscript`(transcribe.mjs)의 Python 판."""

    def stamp(ms):
        s = int(ms) // 1000
        return f"{s // 3600:02d}:{s % 3600 // 60:02d}:{s % 60:02d}"

    rows = sorted(
        (r for r in rows if r.get("failed") or r.get("text")),
        key=lambda r: (r["start_ms"], r["seq"]),
    )
    return "\n".join(
        f"[{stamp(r['start_ms'])}] {names.get(r['user_id'], r['user_id'])}: "
        f"{TRANSCRIBE_FAILED if r.get('failed') else r['text']}"
        for r in rows
    )
