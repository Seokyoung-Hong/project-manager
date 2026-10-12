"""내 PC를 전사 서버로 연결하기(IMPL-PLAN-11-local-stt-link): 기기 인증 · heartbeat · 끊기.

들어오는 연결이 없다. PC가 5초마다 heartbeat로 모델 목록을 올리고 명령(모델 받기)·작업을 받는다.
작업 배정·넘기기 규칙은 notes.transcription(claim_for·sweep·release_pc_job)에 있다.
"""

import hashlib
import json
import secrets
from datetime import timedelta

from django.conf import settings
from django.db import IntegrityError, transaction
from django.utils import timezone

from accounts.models import ApiToken, User
from common.errors import ServiceError

from . import transcription as tx
from .models import SttDeviceCode, SttServer, TranscriptionJob

ALPHABET = "BCDFGHJKLMNPQRSTVWXZ"  # RFC 8628 §6.1: 모음·헷갈리는 글자를 뺀 20자
CODE_TTL = timedelta(minutes=10)
POLL_S = 5
MAX_PENDING = 200  # 미승인 대기 코드 상한. 넘으면 가장 오래된 것부터 지운다
MAX_SERVERS = 5  # 사람당 서버
MAX_JSON = 32 * 1024  # heartbeat models·device 각각
SAVE_EVERY = timedelta(seconds=10)  # 바뀐 것이 없으면 이 간격으로만 last_seen_at을 쓴다
MIN_INTERVAL = timedelta(seconds=1)  # 이보다 잦은 heartbeat는 응답만 하고 저장하지 않는다
MIN_VERSION = "0.0.0"  # 이보다 낮은 PC는 426(업데이트 안내)
LINK_PATH = "/link"

# 사용자 문구 — 임시(docs/drafts/local-stt-link-copy.md)
TOO_MANY_SERVERS = (
    f"전사 서버는 한 사람당 {MAX_SERVERS}대까지 연결할 수 있습니다. "
    "쓰지 않는 서버를 끊은 뒤 다시 허용해 주세요."  # COPY:too_many_servers
)
LINK_APPROVED_NOTICE = (
    "내 PC 전사 서버 '{name}'을(를) 연결했습니다. 직접 연결한 PC가 아니라면 "
    "내 PC 연결 화면에서 바로 끊어 주세요."  # COPY:link_approved_notice
)


def _hash(raw: str) -> str:
    return hashlib.sha256(raw.encode()).hexdigest()


def json_size(value) -> int:
    return len(json.dumps(value, ensure_ascii=False, separators=(",", ":")).encode())


def normalize_code(raw: str) -> str:
    """대소문자·하이픈·공백 무시. 8자가 아니면 ""."""
    s = "".join(c for c in (raw or "").upper() if c.isalnum())
    return f"{s[:4]}-{s[4:]}" if len(s) == 8 else ""


def _version_tuple(v: str) -> tuple:
    out = []
    for part in str(v or "").lstrip("v").split("."):
        digits = "".join(c for c in part if c.isdigit())
        out.append(int(digits) if digits else 0)
    return tuple(out)


def version_ok(v: str) -> bool:
    return _version_tuple(v) >= _version_tuple(MIN_VERSION)


# ---------- 기기 인증(§3) ----------


def _pending():
    return SttDeviceCode.objects.filter(used_at__isnull=True, denied=False)


@transaction.atomic
def start_device(*, name: str, machine_id: str, version: str, device: dict) -> dict:
    now = timezone.now()
    _pending().filter(machine_id=machine_id, approved_by__isnull=True).delete()
    waiting = _pending().filter(approved_by__isnull=True).order_by("created_at", "id")
    over = waiting.count() - MAX_PENDING + 1
    if over > 0:  # 발급 폭주가 정상 사용자를 막지 않게 거절하지 않고 오래된 것부터 밀어낸다
        SttDeviceCode.objects.filter(
            pk__in=list(waiting.values_list("pk", flat=True)[:over])
        ).delete()
    raw = secrets.token_urlsafe(32)
    for _ in range(10):
        user_code = "".join(secrets.choice(ALPHABET) for _ in range(8))
        user_code = f"{user_code[:4]}-{user_code[4:]}"
        try:
            with transaction.atomic():
                SttDeviceCode.objects.create(
                    code_hash=_hash(raw),
                    user_code=user_code,
                    name=(name or "").strip()[:50] or "내 PC",
                    machine_id=machine_id,
                    version=(version or "")[:20],
                    device=device or {},
                    expires_at=now + CODE_TTL,
                )
            break
        except IntegrityError:  # 대기 코드끼리 겹쳤다 — 다시 뽑는다
            continue
    else:
        raise ServiceError({"device": "코드를 만들지 못했습니다. 잠시 뒤 다시 시도해 주세요."})
    return {
        "device_code": raw,
        "user_code": user_code,
        "verification_uri": settings.SITE_URL + LINK_PATH,
        "expires_in": int(CODE_TTL.total_seconds()),
        "interval": POLL_S,
    }


def find_code(raw: str):
    """사람이 /link에 입력한 코드 → 아직 승인·거절되지 않은 살아 있는 대기 코드."""
    code = normalize_code(raw)
    if not code:
        return None
    return (
        _pending()
        .filter(user_code=code, approved_by__isnull=True, expires_at__gt=timezone.now())
        .first()
    )


@transaction.atomic
def approve(code: SttDeviceCode, user, name: str) -> None:
    code = SttDeviceCode.objects.select_for_update().get(pk=code.pk)
    if code.approved_by_id or code.denied or code.used_at or code.expires_at <= timezone.now():
        raise ServiceError({"code": "코드가 만료되었습니다. PC에서 다시 연결해 주세요."})
    # 같은 사람의 허용을 줄 세운다(동시에 허용해도 상한을 넘지 않게).
    User.objects.select_for_update().filter(pk=user.pk).first()
    machines = set(
        SttServer.objects.filter(owner=user).values_list("machine_id", flat=True)
    ) | set(  # 허용했지만 PC가 아직 토큰을 안 가져간 코드도 자리를 차지한다
        _pending()
        .filter(approved_by=user, expires_at__gt=timezone.now())
        .values_list("machine_id", flat=True)
    )
    machines.discard(code.machine_id)
    if len(machines) >= MAX_SERVERS:
        raise ServiceError({"code": TOO_MANY_SERVERS})
    code.approved_by = user
    code.name = (name or "").strip()[:50] or code.name
    code.save(update_fields=["approved_by", "name"])
    _notify(user, LINK_APPROVED_NOTICE.format(name=code.name))


def deny(code: SttDeviceCode) -> None:
    SttDeviceCode.objects.filter(pk=code.pk, approved_by__isnull=True).update(denied=True)


def _notify(user, text: str) -> None:
    """허용 직후 DM — 모르는 연결을 알아채게. 알림 경로가 조직 단위라 사용자의 첫 조직으로 보낸다."""
    from django.urls import reverse

    from orgs.services import orgs_of
    from tasks.work_requests import notify

    org = orgs_of(user).first()
    if org is not None:
        notify(org, f"{text} <{settings.SITE_URL}{reverse('settings_stt')}>", user=user)


@transaction.atomic
def poll_token(device_code: str) -> tuple[dict | None, str]:
    """PC가 5초마다 묻는다. (토큰 응답, "") 또는 (None, 오류 코드). 토큰은 승인 뒤 첫 조회 때 한 번만 만든다."""
    code = (
        SttDeviceCode.objects.select_for_update().filter(code_hash=_hash(device_code or "")).first()
    )
    now = timezone.now()
    if code is None or code.used_at is not None:
        return None, "expired_token"
    if code.denied:
        return None, "access_denied"
    if code.expires_at <= now:
        return None, "expired_token"
    if code.approved_by_id is None:
        return None, "authorization_pending"
    user = code.approved_by
    server = SttServer.objects.select_for_update().filter(owner=user, machine_id=code.machine_id)
    server = server.first() or SttServer(owner=user, machine_id=code.machine_id)
    old = server.token
    token, raw = ApiToken.issue(user, f"전사 서버 · {code.name}", scope="stt", for_ai=False)
    server.name, server.version, server.device = code.name, code.version, code.device
    server.token = token
    server.save()
    if old is not None:
        old.revoke()  # 같은 기기를 다시 연결하면 이전 토큰은 폐기
    code.used_at = now
    code.save(update_fields=["used_at"])
    return {"access_token": raw, "server_id": server.pk, "name": server.name}, ""


def purge_codes() -> int:
    """만료된 기기 코드 정리(purge_expired)."""
    return SttDeviceCode.objects.filter(expires_at__lt=timezone.now() - CODE_TTL).delete()[0]


# ---------- heartbeat(§6.1) ----------


def job_payload(job) -> dict:
    """PC에 주는 작업. 이름·참여자·조직 키·서버 주소는 주지 않는다(전사문 조립은 core가 한다)."""
    from .services import meeting_glossary

    rec = job.recording
    return {
        "id": job.pk,
        "recording_id": rec.pk,
        "model": job.model,
        "source": rec.source,
        "segments": rec.segments if rec.source == "discord" else [],
        "tracks": list(rec.tracks.exclude(audio="").values_list("discord_user_id", flat=True)),
        "glossary": meeting_glossary(rec, viewer=job.server.owner),  # PC 주인이 못 보는 용어는 빼고
        "language": "ko",
    }


def heartbeat(server: SttServer, data: dict) -> dict:
    """① 저장(바뀌었거나 10초 지났을 때) ② [모델 적용] 끝났는지 ③ 재시작 되돌리기 ④ 배정."""
    now = timezone.now()
    out = {"poll_s": POLL_S, "pull": server.pull_model or None, "job": None}
    if server.last_seen_at and now - server.last_seen_at < MIN_INTERVAL:
        return out  # 쓰기 폭주 방지: 응답만
    fields = {
        "version": str(data.get("version") or "")[:20],
        "concurrency": max(1, min(32, int(data.get("concurrency") or 1))),
        "device": data.get("device") or {},
        "models": data.get("models") or [],
    }
    changed = [k for k, v in fields.items() if getattr(server, k) != v]
    for k in changed:
        setattr(server, k, fields[k])
    if server.pull_model and tx.ready_model(server, server.pull_model):
        server.default_model, server.pull_model = server.pull_model, ""
        changed += ["default_model", "pull_model"]
    if changed or not server.last_seen_at or now - server.last_seen_at >= SAVE_EVERY:
        server.last_seen_at = now
        server.save(update_fields=[*changed, "last_seen_at"])
    out["pull"] = server.pull_model or None
    tx.sweep(now)  # 이 서버의 응답을 저장한 뒤에 점검한다(자기 작업을 꺼짐으로 보지 않게)
    job_id = data.get("job_id")
    for job in server.jobs.filter(status__in=TranscriptionJob.RUNNING):
        if job.pk != job_id:
            tx.requeue_or_cancel(job.pk)  # PC가 다시 켜져 하던 작업을 잊었다 — 처음부터
    if not job_id:
        job = tx.claim_for(server)
        if job is not None:
            out["job"] = job_payload(job)
    return out


# ---------- 끊기(§3·§7.4) ----------


@transaction.atomic
def unlink(server: SttServer) -> None:
    """토큰 폐기 + 활성 작업 정리 + 행 삭제. 웹 [끊기]와 PC의 DELETE /self가 같이 쓴다."""
    for job in server.jobs.filter(status__in=TranscriptionJob.ACTIVE):
        tx.release_pc_job(job, "pc_unlinked")
    if server.token is not None:
        server.token.revoke()
    server.delete()


def set_pull(server: SttServer, model: str) -> None:
    """[모델 적용]: 다음 heartbeat 응답으로 받기 명령을 보낸다. 맞지 않는 모델(fits=false)은 고를 수 없다."""
    item = next((m for m in tx.parse_models(server.models) if m["id"] == model), None)
    if item is None or not item["fits"]:
        raise ServiceError(
            {"model": "이 PC에서 쓸 수 있는 모델을 골라 주세요."}
        )  # COPY:pull_not_fits
    if item["status"] == "ready":
        server.default_model, server.pull_model = model, ""
    else:
        server.pull_model = model
    server.save(update_fields=["default_model", "pull_model"])
