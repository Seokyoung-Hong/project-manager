"""IMPL-PLAN-10-transcribe-menu: 전사 작업(자동·다시 전사)·취소 신호·예상 시간·전사 메뉴 화면.

전사문은 녹음 원문이고 회의록 본문과 따로 저장된다 — 다시 전사가 회의록 본문을 바꾸지 않는다.
"""

import json
from datetime import timedelta

import pytest
from cryptography.fernet import Fernet
from django.core.files.base import ContentFile
from django.utils import timezone

from accounts.models import ApiToken, User
from notes import transcription as tx
from notes.models import TranscriptionJob, VoiceTrack
from notes.services import DRAFT_BODY, start_recording, update_recording
from orgs.services import set_org_settings

pytestmark = pytest.mark.django_db
SEGS = [
    {"seq": 1, "user_id": "h", "start_ms": 0, "duration_ms": 60_000, "file": "seg/1.ogg"},
    {"seq": 2, "user_id": "a", "start_ms": 61_000, "duration_ms": 1000},  # 1.5초 미만: 전사 안 함
    {"seq": 3, "user_id": "a", "start_ms": 70_000, "duration_ms": 120_000},
]


@pytest.fixture(autouse=True)
def _env(settings, tmp_path):
    settings.CREDENTIAL_KEY = Fernet.generate_key().decode()
    settings.MEDIA_ROOT = tmp_path


@pytest.fixture
def bot(client):
    u = User.objects.create_user("discord-bot", password="pw12345678", display_name="봇")
    raw = ApiToken.issue(u, "봇", "bot")[1]

    def call(method, url, data=None):
        return getattr(client, method)(
            "/api/integrations/discord" + url,
            data=json.dumps(data) if data is not None else None,
            content_type="application/json",
            headers={"Authorization": f"Bearer {raw}"},
        )

    return call


@pytest.fixture
def enabled(org, admin):
    org.discord_guild_id = "g1"
    org.save()
    set_org_settings(
        org,
        {
            "meeting.recording_enabled": True,
            "meeting.stt_url": "http://172.30.1.50:8000",
            "meeting.stt_model": "large-v3",
            "meeting.openai_api_key": "sk-org",
        },
        admin,
    )
    org.refresh_from_db()
    return org


def _drafted(org, host, bot):
    rec = start_recording(org=org, actor=host, guild_id="g1", voice_channel_id="v1")
    r = bot("patch", f"/meetings/{rec.pk}", {"status": "transcribing", "end_reason": "empty"})
    assert r.status_code == 200, r.content
    job_id = r.json()["job_id"]
    r = bot(
        "patch",
        f"/meetings/{rec.pk}",
        {
            "status": "draft",
            "transcript_md": "[00:00:00] 홍길동: 첫 전사",
            "stats": {"engine": "local"},
            "segments": SEGS,
        },
    )
    assert r.status_code == 200, r.content
    rec.refresh_from_db()
    VoiceTrack.objects.create(
        recording=rec, discord_user_id="h", audio=ContentFile(b"ogg", name="t.ogg"), audio_size=3
    )
    return rec, job_id


def test_auto_job_follows_meeting_and_keeps_note_body_separate(enabled, member, bot):
    rec, job_id = _drafted(enabled, member, bot)
    job = TranscriptionJob.objects.get(pk=job_id)
    assert (job.kind, job.status, job.engine, job.model) == ("auto", "done", "local", "large-v3")
    assert job.transcript_md == "[00:00:00] 홍길동: 첫 전사"
    assert rec.transcript_md == job.transcript_md and rec.transcript_job_id == job.pk
    # 회의록 본문은 정리용 틀뿐, 전사문이 들어가지 않는다
    assert rec.note.body_md == DRAFT_BODY.format(id=rec.note_id)
    assert "첫 전사" not in rec.note.body_md
    assert rec.segments[0] == {"seq": 1, "user_id": "h", "start_ms": 0, "duration_ms": 60000}


def test_progress_report_returns_cancel_signal(enabled, admin, member, bot):
    rec = start_recording(org=enabled, actor=member, guild_id="g1", voice_channel_id="v1")
    job_id = bot("patch", f"/meetings/{rec.pk}", {"status": "transcribing"}).json()["job_id"]
    r = bot("patch", f"/transcriptions/{job_id}", {"done_ms": 1000, "audio_ms": 9000})
    assert r.json() == {"status": "running", "cancel": False}
    tx.cancel(TranscriptionJob.objects.get(pk=job_id), admin)
    r = bot("patch", f"/transcriptions/{job_id}", {"done_ms": 2000})
    assert r.json() == {"status": "cancelling", "cancel": True}
    assert bot("patch", f"/transcriptions/{job_id}", {"status": "cancelled"}).json()["status"] == (
        "cancelled"
    )
    # 취소된 자동 작업 뒤의 draft PATCH는 작업을 되살리지 않는다
    update_recording(
        rec, status="draft", transcript_md="", stats={"engine": "local", "cancelled": True}
    )
    assert TranscriptionJob.objects.get(pk=job_id).status == "cancelled"


def test_retry_claim_report_done_and_use_previous(client, enabled, admin, member, bot):
    rec, auto_id = _drafted(enabled, member, bot)
    client.force_login(admin)
    r = client.post(
        f"/orgs/{enabled.pk}/transcribe/recordings/{rec.pk}/retry",
        {"choice": "openai|whisper-1"},
    )
    assert r.status_code == 200 and r["HX-Trigger"] == "transcribe-list"
    job = TranscriptionJob.objects.get(kind="retry")
    assert (job.status, job.engine, job.audio_ms, job.segments_total) == (
        "queued",
        "openai",
        180_000,
        2,
    )
    assert job.stats["label"] == "OpenAI Whisper(whisper-1) · OpenAI API"

    out = bot("post", "/transcriptions/claim").json()
    assert out["job"] == {
        "id": job.pk,
        "recording_id": rec.pk,
        "engine": "openai",
        "model": "whisper-1",
    }
    assert out["stt"]["url"] == "" and out["stt"]["openai_api_key"] == "sk-org"  # 고른 수단만
    assert out["tracks"] == ["h"] and len(out["segments"]) == 3
    assert bot("post", "/transcriptions/claim").json() == {"job": None}

    r = bot(
        "patch",
        f"/transcriptions/{job.pk}",
        {"status": "done", "transcript_md": "[00:00:00] 홍길동: 새 전사", "done_ms": 180_000},
    )
    assert r.json()["status"] == "done"
    rec.refresh_from_db()
    assert rec.transcript_md == "[00:00:00] 홍길동: 새 전사" and rec.transcript_job_id == job.pk
    assert "새 전사" not in rec.note.body_md
    job.refresh_from_db()
    assert job.measured_rtf is not None

    r = client.post(f"/orgs/{enabled.pk}/transcribe/jobs/{auto_id}/use")
    assert r.status_code == 200
    rec.refresh_from_db()
    assert rec.transcript_md == "[00:00:00] 홍길동: 첫 전사" and rec.transcript_job_id == auto_id


def test_retry_while_running_cancels_running_and_waits(enabled, admin, member, bot):
    rec, _ = _drafted(enabled, member, bot)
    first = tx.request_retry(rec, engine="local", model="large-v3", actor=admin)
    assert tx.claim().pk == first.pk
    second = tx.request_retry(rec, engine="openai", model="whisper-1", actor=admin)
    first.refresh_from_db()
    assert first.status == "cancelling" and second.status == "queued"
    assert tx.claim() is None  # 같은 회의 작업이 아직 멈추는 중
    tx.report(first.pk, {"status": "cancelled"})
    assert tx.claim().pk == second.pk


def test_retry_blocked_without_segments_or_after_expiry(enabled, admin, member, bot):
    rec, _ = _drafted(enabled, member, bot)
    rec.segments = []
    rec.save()
    with pytest.raises(Exception, match="다시 전사를 지원하기 전"):
        tx.request_retry(rec, engine="openai", model="", actor=admin)
    rec.segments = SEGS
    rec.audio_expires_at = timezone.now() - timedelta(days=1)
    rec.save()
    assert tx.retry_block(rec) == tx.EXPIRED
    with pytest.raises(Exception, match="조직 관리자"):
        tx.request_retry(rec, engine="openai", model="", actor=member)


def test_requeue_and_track_download(enabled, admin, member, bot):
    rec, _ = _drafted(enabled, member, bot)
    job = tx.request_retry(rec, engine="local", model="large-v3", actor=admin)
    tx.claim()
    assert bot("post", "/transcriptions/requeue").json() == {"requeued": 1}
    job.refresh_from_db()
    assert job.status == "queued"
    r = bot("get", f"/meetings/{rec.pk}/tracks/h")
    assert r.status_code == 200 and b"".join(r.streaming_content) == b"ogg"
    assert bot("get", f"/meetings/{rec.pk}/tracks/zz").status_code == 404


def test_eta_prior_then_observed():
    now = timezone.now()
    job = TranscriptionJob(
        engine="local",
        audio_ms=600_000,
        segments_total=10,
        status="queued",
        stats={"prior_rtf": 0.2},
    )
    assert tx.remaining_s(job, now) == pytest.approx(600 * 0.2 + 10 * 0.4)
    # 전체의 30%(180초) 처리 뒤에는 관측 속도만: 180초 음성에 90초 → 남은 420초 × 0.5
    job.status, job.started_at, job.done_ms = "running", now - timedelta(seconds=90), 180_000
    assert tx.remaining_s(job, now) == pytest.approx(420 * 0.5)
    job.stats = {}
    job.done_ms = 0
    assert tx.remaining_s(job, now) is None  # 로컬 실측·서버 값 없음
    assert tx.eta_text(None) == "예상 시간 계산 중"
    assert tx.eta_text(30) == "1분 안에 끝남" and tx.eta_text(61) == "약 2분"


def test_prior_rtf_order(enabled):
    assert tx.prior_rtf(enabled, "local", "m", {"rtf": 0.3, "concurrency": 2}) == pytest.approx(
        0.15
    )
    assert tx.prior_rtf(enabled, "local", "m", {}) is None
    assert tx.prior_rtf(enabled, "openai", "whisper-1") == pytest.approx(0.08 / 3)


def test_model_label_uses_server_fields_only():
    assert tx.model_label(
        "local", "large-v3-turbo", {"display_name": "OpenAI Whisper large-v3-turbo"}
    ) == ("OpenAI Whisper large-v3-turbo · 로컬 서버")
    assert tx.model_label(
        "local", "large-v3-turbo", {"family": "Whisper", "owned_by": "OpenAI"}
    ) == ("OpenAI Whisper large-v3-turbo · 로컬 서버")
    assert tx.model_label("local", "Systran/faster-whisper-small", {"owned_by": "Systran"}) == (
        "Systran/faster-whisper-small · 로컬 서버"
    )
    assert tx.model_label("local", "large-turbo") == "large-turbo · 로컬 서버"  # 추정하지 않는다
    assert tx.model_label("openai", "whisper-1") == "OpenAI Whisper(whisper-1) · OpenAI API"


def test_transcribe_menu_admin_only_and_server_save_keeps_other_settings(
    client, enabled, admin, member, bot
):
    _drafted(enabled, member, bot)
    client.force_login(member)
    assert client.get(f"/orgs/{enabled.pk}/transcribe").status_code == 302
    client.force_login(admin)
    page = client.get(f"/orgs/{enabled.pk}/transcribe").content.decode()
    assert "끝남 · 최근 7일" in page and "large-v3 · 로컬 서버" in page
    server = client.get(f"/orgs/{enabled.pk}/transcribe?view=server").content.decode()
    assert '<select id="setting-meeting.stt_model"' in server and 'hx-trigger="load"' in server
    settings_page = client.get(f"/orgs/{enabled.pk}/settings").content.decode()
    assert "setting-meeting.stt_url" not in settings_page and "전사</a> 메뉴" in settings_page

    r = client.post(
        f"/orgs/{enabled.pk}/transcribe/server",
        {
            "meeting.stt_url": "http://172.30.1.51:8000",
            "meeting.stt_model": "small",
            "meeting.stt_timeout_s": "60",
        },
    )
    assert r.status_code == 302
    enabled.refresh_from_db()
    s = enabled.settings
    assert s["meeting.stt_url"] == "http://172.30.1.51:8000" and s["meeting.stt_model"] == "small"
    assert s["meeting.recording_enabled"] is True and s["meeting.openai_api_key"]  # 그대로
    # 조직 설정 저장은 전사 서버 값을 지우지 않는다
    client.post(f"/orgs/{enabled.pk}/settings", {"meeting.recording_enabled": "on"})
    enabled.refresh_from_db()
    assert (
        enabled.settings["meeting.stt_model"] == "small"
        and enabled.settings["meeting.openai_api_key"]
    )


def test_panel_lists_options_without_server_and_shows_history(
    client, enabled, admin, member, bot, monkeypatch
):
    rec, _ = _drafted(enabled, member, bot)
    monkeypatch.setattr(
        "web.views.transcribe.stt_models", lambda org, url: ([], "서버에 접속할 수 없습니다.", None)
    )
    client.force_login(admin)
    body = client.get(f"/orgs/{enabled.pk}/transcribe/recordings/{rec.pk}/panel").content.decode()
    assert 'value="openai|whisper-1"' in body and "OpenAI Whisper(whisper-1) · OpenAI API" in body
    assert "모델 목록을 불러오지 못했습니다" in body
    assert "현재 전사문" in body and "회의록 본문은 바뀌지 않습니다" in body
