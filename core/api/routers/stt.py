"""내 PC 전사 서버가 부르는 곳(IMPL-PLAN-11-local-stt-link §6.1).

기기 인증 두 개(`/device`, `/device/token`)만 인증이 없다. 나머지는 라우터 auth가 `SttTokenAuth` 하나라
세션·읽기·쓰기·봇 토큰이 들어오지 못하고, stt 토큰은 TokenAuth 가드로 이 경로 밖에서 막힌다(두 겹).
PC는 자기에게 배정된 작업만 보고, 받을 수 있는 것은 진행 숫자·구간 결과(rows)·세부 정보·오류 코드뿐이다.
"""

from django.http import FileResponse, Http404, JsonResponse
from ninja import Router
from ninja.errors import HttpError

from api.auth import SttTokenAuth
from api.schemas import (
    SttAiReportIn,
    SttDeviceIn,
    SttDeviceTokenIn,
    SttHeartbeatIn,
    SttJobReportIn,
)
from assist import pc as assist_pc
from assist.models import AiJob
from notes import services as notes_svc
from notes import stt_link
from notes import transcription as tx
from notes.models import TranscriptionJob

# 처리량 제한은 두지 않는다: heartbeat는 서버당 5초 주기이고 1초보다 잦으면 저장하지 않는다(stt_link.MIN_INTERVAL).
# 사용자별 60/m 기본 제한을 쓰면 서버 5대 + 내려받기·진행 보고가 정상 사용에서 걸린다.
router = Router(tags=["stt"], auth=SttTokenAuth(), throttle=[])

# PC가 보낼 수 있는 오류 코드. 목록 밖이면 pc_error로 바꾼다.
# 계획서 목록 + udally-stt link.py가 실제로 보내는 값. out_of_memory는 PC가 구간 실패로 보고하지만 와도 받는다.
PC_ERRORS = {
    "model_not_ready",
    "download_failed",
    "decode_failed",
    "audio_unavailable",
    "out_of_memory",
    "transcript_too_large",
    "pc_error",
}
ROW_TEXT_MAX = 2000  # 구간 하나의 전사 글자 수 상한
PC_ERROR_ALIASES = {"no_audio": "audio_unavailable"}  # 같은 뜻의 다른 이름
MIN_VERSION_TEXT = "전사 서버 프로그램이 오래되었습니다. 설치 명령을 다시 실행해 업데이트해 주세요."  # COPY:pc_update_needed


def _too_big(*values) -> bool:
    return any(stt_link.json_size(v) > stt_link.MAX_JSON for v in values)


def _detail(status: int, detail: str):
    return JsonResponse(
        {"detail": detail}, status=status, json_dumps_params={"ensure_ascii": False}
    )


@router.post("/device", auth=None, response=dict)
def device(request, payload: SttDeviceIn):
    """기기 인증 시작. 사람은 verification_uri를 직접 열고 PC 화면의 user_code를 입력한다(코드가 든 주소는 없다)."""
    if _too_big(payload.device):
        return _detail(422, "장치 정보가 너무 큽니다.")
    return stt_link.start_device(
        name=payload.name,
        machine_id=str(payload.machine_id),
        version=payload.version,
        device=payload.device,
    )


@router.post("/device/token", auth=None, response=dict)
def device_token(request, payload: SttDeviceTokenIn):
    """5초마다 묻는다. 400 {error: authorization_pending | access_denied | expired_token}."""
    out, error = stt_link.poll_token(payload.device_code)
    if error:
        return JsonResponse({"error": error}, status=400)
    return out


@router.post("/heartbeat", response=dict)
def heartbeat(request, payload: SttHeartbeatIn):
    if _too_big(payload.models) or _too_big(payload.device):
        return _detail(422, "모델 목록이나 장치 정보가 너무 큽니다.")
    if not stt_link.version_ok(payload.version):
        return _detail(426, MIN_VERSION_TEXT)
    return stt_link.heartbeat(request.stt_server, payload.dict())


@router.delete("/self", response=dict)
def unlink_self(request):
    """PC가 스스로 끊는다(제거 스크립트). 웹 [끊기]와 같은 정리."""
    stt_link.unlink(request.stt_server)
    return {"ok": True}


def _my_job(request, job_id: int):
    job = (
        TranscriptionJob.objects.select_related("recording__note__org")
        .filter(pk=job_id, server=request.stt_server)
        .first()
    )
    if job is None:
        raise HttpError(404, "전사 작업을 찾을 수 없습니다.")
    return job


def _download_rec(request, job_id: int):
    """내려받기 관문: 내 작업 · 가져간 running · 주인이 지금도 볼 수 있음 · 보관 기간 안."""
    job = _my_job(request, job_id)
    if job.claimed_at is None or job.status not in TranscriptionJob.RUNNING:
        raise HttpError(409, "전사 중인 작업이 아닙니다.")
    rec = job.recording
    if notes_svc.get_visible_note(request.stt_server.owner, rec.note_id) is None:
        raise HttpError(404, "전사 작업을 찾을 수 없습니다.")
    if notes_svc.audio_expired(rec):
        raise HttpError(410, notes_svc.AUDIO_EXPIRED)
    return rec


def _open(field):
    try:
        return field.open("rb")
    except FileNotFoundError:
        raise HttpError(404, "녹음 파일을 찾을 수 없습니다.") from None


@router.get("/jobs/{int:job_id}/tracks/{discord_user_id}")
def job_track(request, job_id: int, discord_user_id: str):
    rec = _download_rec(request, job_id)
    track = rec.tracks.filter(discord_user_id=discord_user_id).exclude(audio="").first()
    if track is None:
        raise HttpError(404, "참여자별 녹음을 찾을 수 없습니다.")
    return FileResponse(_open(track.audio), content_type="audio/ogg")


@router.get("/jobs/{int:job_id}/audio")
def job_audio(request, job_id: int):
    rec = _download_rec(request, job_id)
    if not rec.audio:
        raise HttpError(404, "녹음 파일을 찾을 수 없습니다.")
    r = FileResponse(_open(rec.audio), content_type="application/octet-stream")
    r["X-Audio-Ext"] = rec.audio.name.rsplit(".", 1)[-1]
    return r


@router.patch("/jobs/{int:job_id}", response=dict)
def job_report(request, job_id: int, payload: SttJobReportIn):
    """진행·결과 보고. 응답 cancel이 true면 PC는 멈추고 cancelled를 보낸다."""
    job = _my_job(request, job_id)
    if job.status not in TranscriptionJob.RUNNING:
        raise HttpError(409, "이미 끝난 전사 작업입니다.")
    if payload.stats is not None and _too_big(payload.stats):
        return _detail(422, "세부 정보가 너무 큽니다.")
    data = payload.dict(exclude={"rows"})
    error = PC_ERROR_ALIASES.get(data["error"], data["error"])
    data["error"] = error if not error or error in PC_ERRORS else "pc_error"
    if payload.status == "done":
        rec = job.recording
        rows = [r.dict() for r in payload.rows or []]
        cut = sum(1 for r in rows if len(r["text"]) > ROW_TEXT_MAX)
        for r in rows:
            r["text"] = r["text"][:ROW_TEXT_MAX]
        if cut:
            data["stats"] = {**(data.get("stats") or {}), "truncated": cut}
        if rec.source == "upload":
            names = {r["user_id"]: tx.UPLOAD_SPEAKER for r in rows}
        else:
            speakers = {str(g.get("user_id")) for g in rec.segments or []}
            rows = [r for r in rows if r["user_id"] in speakers]  # 작업 구간에 없는 화자는 버린다
            names = {n["discord_user_id"]: n["display_name"] for n in notes_svc.speaker_names(rec)}
        data["transcript_md"] = tx.format_transcript(rows, names)
        if len(data["transcript_md"].encode()) > notes_svc.MAX_BODY:
            return _detail(413, "전사문이 용량 한도 256KB를 넘었습니다.")
    try:
        job = tx.report(job.pk, data, server=request.stt_server, claimed_at=job.claimed_at)
    except tx.StaleClaim:
        raise HttpError(409, "이 PC가 맡은 작업이 아닙니다.") from None
    return {"status": job.status, "cancel": job.status == "cancelling"}


@router.patch("/ai-jobs/{int:job_id}", response=dict)
def ai_job_report(request, job_id: int, payload: SttAiReportIn):
    """AI 작업 결과(IMPL-PLAN-12 §6.2). 끝날 때 한 번. 이 PC 주인이 요청한 작업만(§5.3-3)."""
    if len(payload.content.encode()) > AiJob.MAX_RESULT:
        return _detail(413, "AI 결과가 용량 한도 256KB를 넘었습니다.")
    if payload.usage is not None and _too_big(payload.usage):
        return _detail(422, "사용량 정보가 너무 큽니다.")
    try:
        job = assist_pc.report(job_id, request.stt_server, payload.dict())
    except Http404:
        raise HttpError(404, "AI 작업을 찾을 수 없습니다.") from None
    except assist_pc.Finished:
        raise HttpError(409, "이미 끝난 AI 작업입니다.") from None
    return {"status": job.status}
