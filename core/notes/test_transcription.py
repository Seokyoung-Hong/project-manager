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
from web.test_integrations_move import frag

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
    u = User.objects.create_user(
        "discord-bot", password="pw12345678", display_name="봇", real_name="실명"
    )
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
def other_member(org):
    from orgs.models import OrgMembership

    u = User.objects.create_user(
        "other2", password="pw12345678", display_name="다른팀원", real_name="실명"
    )
    OrgMembership.objects.create(org=org, user=u, role="member")
    return u


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
    # 멤버도 조직 수단으로 지시할 수 있다(IMPL-PLAN-11-local-stt-link §8) — 막는 것은 보관 기간
    with pytest.raises(Exception, match="보관 기간"):
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


def test_transcribe_menu_server_view_admin_only_and_save_keeps_other_settings(
    client, enabled, admin, member, bot
):
    _drafted(enabled, member, bot)
    # 구성원도 전사 메뉴를 연다(IMPL-PLAN-11-local-stt-link §6.2). 전사 서버 보기는 관리자만
    client.force_login(member)
    page = client.get(f"/orgs/{enabled.pk}/transcribe").content.decode()
    assert "large-v3 · 로컬 서버" in page and "?view=server" not in page
    server = client.get(f"/orgs/{enabled.pk}/transcribe?view=server").content.decode()
    assert "setting-meeting.stt_model" not in server  # 비관리자는 작업 목록
    assert client.post(f"/orgs/{enabled.pk}/transcribe/server", {}).status_code == 302
    enabled.refresh_from_db()
    assert enabled.settings["meeting.stt_url"] == "http://172.30.1.50:8000"
    client.force_login(admin)
    page = client.get(f"/orgs/{enabled.pk}/transcribe").content.decode()
    assert "끝남 · 최근 7일" in page and "large-v3 · 로컬 서버" in page
    old = client.get(f"/orgs/{enabled.pk}/transcribe?view=server")
    assert (
        old.status_code == 302 and old["Location"] == f"/orgs/{enabled.pk}/settings?tab=meeting#stt"
    )
    server = frag("stt", admin, enabled)
    assert '<select id="setting-meeting.stt_model"' in server and 'hx-trigger="load"' in server
    settings_page = client.get(f"/orgs/{enabled.pk}/settings?tab=meeting").content.decode()
    assert '<section id="stt"' in settings_page  # 회의·전사 탭 안 전사 섹션(독립 폼)

    r = client.post(
        f"/orgs/{enabled.pk}/transcribe/server",
        {
            "meeting.stt_url": "http://172.30.1.51:8000",
            "meeting.stt_model": "small",
            "meeting.stt_timeout_s": "60",
            "meeting.member_pc": "on",
            "meeting.transcribe_level": "admin",
        },
    )
    assert r.status_code == 302
    enabled.refresh_from_db()
    s = enabled.settings
    assert s.get("meeting.member_pc", True) is True and s["meeting.transcribe_level"] == "admin"
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


# ---------- 올린 녹음(IMPL-PLAN-10-transcribe-menu §12) ----------
MP3 = b"ID3\x04\x00\x00\x00\x00\x00\x00" + bytes(100)


def _upload(client, note, data=MP3, name="회의.mp3"):
    from django.core.files.uploadedfile import SimpleUploadedFile

    return client.post(f"/notes/{note.pk}/audio/upload", {"file": SimpleUploadedFile(name, data)})


@pytest.mark.parametrize(
    ("name", "data"),
    [
        ("a.mp3", MP3),
        ("a.mp3", b"\xff\xfb\x90\x00" + bytes(20)),
        ("a.m4a", b"\x00\x00\x00\x20ftypM4A " + bytes(20)),
        ("a.wav", b"RIFF\x00\x00\x00\x00WAVEfmt " + bytes(20)),
        ("a.OGG", b"OggS" + bytes(20)),
        ("a.opus", b"OggS" + bytes(20)),
        ("a.webm", bytes.fromhex("1a45dfa3") + bytes(20)),
    ],
)
def test_upload_accepts_types_by_extension_and_magic(client, enabled, member, name, data):
    from notes.services import create_note

    note = create_note(org=enabled, actor=member, title="대면 회의")
    client.force_login(member)
    assert _upload(client, note, data, name).status_code == 302
    rec = note.recording
    assert rec.source == "upload" and rec.status == "draft" and rec.audio_size == len(data)
    assert rec.audio.name.endswith("." + name.rsplit(".", 1)[1].lower())
    assert rec.host_id == member.pk and rec.audio_expires_at is not None
    assert rec.note.body_md == ""  # 회의록 본문은 그대로


@pytest.mark.parametrize(
    ("name", "data", "why"),
    [
        ("a.txt", MP3, "형식은"),
        ("a.mp3", b"OggS" + bytes(20), ".mp3 녹음 형식이 아닙니다"),
        ("a.wav", b"RIFF" + bytes(20), ".wav 녹음 형식이 아닙니다"),
        ("a.ogg", b"Og", ".ogg 녹음 형식이 아닙니다"),
    ],
)
def test_upload_rejects_bad_files(client, enabled, member, name, data, why):
    from notes.services import create_note

    note = create_note(org=enabled, actor=member)
    client.force_login(member)
    r = _upload(client, note, data, name)
    assert why in [m.message for m in r.wsgi_request._messages][0]
    note.refresh_from_db()
    assert not hasattr(note, "recording")


def test_upload_size_limit(enabled, member, monkeypatch):
    from django.core.files.uploadedfile import SimpleUploadedFile

    from notes import services
    from notes.services import create_note

    note = create_note(org=enabled, actor=member)
    monkeypatch.setattr(services, "AUDIO_MAX_BYTES", 50)
    with pytest.raises(Exception, match="300MB"):
        services.upload_audio(note, SimpleUploadedFile("a.mp3", MP3), member)


def test_upload_permission_and_discord_recording(client, enabled, admin, member, other_member, bot):
    from notes.services import create_note

    # 다른 사람 초안(Discord 회의) — 진행자·관리자가 아니면 못 올리고, 진행자도 Discord 녹음에는 못 올린다
    rec, _ = _drafted(enabled, member, bot)
    client.force_login(member)
    r = _upload(client, rec.note)
    assert "Discord 회의 녹음" in [m.message for m in r.wsgi_request._messages][0]
    # 확정 회의록은 조직 구성원이면 올릴 수 있다(회의록 고치기 규칙과 같다)
    note = create_note(org=enabled, actor=admin)
    client.force_login(other_member)
    assert _upload(client, note).status_code == 302
    note.refresh_from_db()
    assert note.recording.source == "upload"


def test_upload_transcribe_queue_claim_and_menu(client, enabled, admin, member, bot):
    from notes.services import create_note

    note = create_note(org=enabled, actor=member, title="대면 회의")
    client.force_login(member)
    _upload(client, note)
    page = client.get(f"/orgs/{enabled.pk}/notes?note={note.pk}").content.decode()
    assert "전사 시작" in page and 'accept=".mp3,.m4a,.wav,.ogg,.opus,.webm"' in page
    client.post(f"/notes/{note.pk}/transcribe")
    job = TranscriptionJob.objects.get()
    assert (job.kind, job.status, job.engine, job.model, job.audio_ms) == (
        "upload",
        "queued",
        "local",
        "large-v3",
        0,
    )
    assert tx.remaining_s(job) is None  # 길이를 모른다 → 계산 중
    client.post(f"/notes/{note.pk}/transcribe")
    assert TranscriptionJob.objects.count() == 1  # 대기 중이면 또 넣지 않는다
    # 녹음 파일을 바꾸려 해도 전사 중이면 막는다
    r = _upload(client, note)
    assert "전사 중에는" in [m.message for m in r.wsgi_request._messages][-1]

    out = bot("post", "/transcriptions/claim").json()
    assert out["source"] == "upload" and out["speaker"] == "올린 녹음"
    assert out["segments"] == [] and out["tracks"] == []
    r = bot("get", f"/meetings/{note.recording.pk}/audio")
    assert r.status_code == 200 and b"".join(r.streaming_content) == MP3
    assert r["X-Audio-Ext"] == "mp3"
    bot(
        "patch",
        f"/transcriptions/{job.pk}",
        {"audio_ms": 9000, "done_ms": 3000, "segments_total": 3},
    )
    bot(
        "patch",
        f"/transcriptions/{job.pk}",
        {"status": "done", "transcript_md": "[00:00:01] 올린 녹음: 안녕", "done_ms": 9000},
    )
    note.refresh_from_db()
    assert note.recording.transcript_md == "[00:00:01] 올린 녹음: 안녕"
    assert "안녕" not in note.body_md

    # 전사 메뉴: 목록·패널·다른 모델로 다시 전사가 올린 녹음에도
    client.force_login(admin)
    menu = client.get(f"/orgs/{enabled.pk}/transcribe").content.decode()
    assert "대면 회의" in menu and "올린 녹음 전사" in menu
    panel = client.get(
        f"/orgs/{enabled.pk}/transcribe/recordings/{note.recording.pk}/panel"
    ).content.decode()
    assert "올린 녹음" in panel and 'value="openai|whisper-1"' in panel
    retry = tx.request_retry(note.recording, engine="openai", model="whisper-1", actor=admin)
    assert retry.kind == "retry" and retry.status == "queued"
    assert tx.claim().pk == retry.pk


def test_upload_audio_download_keeps_extension(client, enabled, member):
    from notes.services import create_note

    note = create_note(org=enabled, actor=member)
    client.force_login(member)
    _upload(client, note, b"RIFF\x00\x00\x00\x00WAVEfmt " + bytes(20), "a.wav")
    r = client.get(f"/notes/{note.pk}/audio")
    assert r.status_code == 200 and r["Content-Type"] == "audio/wav"
    assert ".wav" in r["Content-Disposition"]


def test_panel_offers_audio_and_track_downloads(client, enabled, admin, member, bot, monkeypatch):
    rec, _ = _drafted(enabled, member, bot)
    rec.audio = ContentFile(b"ogg", name="m.ogg")
    rec.audio_size = 3
    rec.save()
    monkeypatch.setattr("web.views.transcribe.stt_models", lambda org, url: ([], "", None))
    client.force_login(admin)
    body = client.get(f"/orgs/{enabled.pk}/transcribe/recordings/{rec.pk}/panel").content.decode()
    assert f'href="/notes/{rec.note.pk}/audio"' in body
    assert f'href="/notes/{rec.note.pk}/tracks/h"' in body
    assert f'href="/notes/{rec.note.pk}/tracks.zip"' in body


def test_tracks_zip_names_permission_and_expiry(client, enabled, admin, member, other_member, bot):
    import io
    import zipfile

    rec, _ = _drafted(enabled, member, bot)  # 트랙 h 하나
    VoiceTrack.objects.create(
        recording=rec, discord_user_id="a", audio=ContentFile(b"ogg2", name="t.ogg"), audio_size=4
    )
    # 두 참여자 이름이 같으면 -2로 구분한다
    rec.participants = [
        {"discord_user_id": "h", "display_name": "홍길동"},
        {"discord_user_id": "a", "display_name": "홍길동"},
    ]
    rec.save()
    url = f"/notes/{rec.note_id}/tracks.zip"
    client.force_login(member)
    r = client.get(url)
    assert r.status_code == 200 and r["X-Content-Type-Options"] == "nosniff"
    assert (
        f"회의록-{rec.note_id}-" in r["Content-Disposition"]
        or "filename*" in r["Content-Disposition"]
    )
    zf = zipfile.ZipFile(io.BytesIO(b"".join(r.streaming_content)))
    names = zf.namelist()
    assert names == [f"회의록-{rec.note_id}-홍길동.ogg", f"회의록-{rec.note_id}-홍길동-2.ogg"]
    assert zf.read(names[1]) == b"ogg2" and zf.infolist()[0].compress_type == zipfile.ZIP_STORED
    client.force_login(other_member)  # 초안은 진행자·관리자만
    assert client.get(url).status_code == 404
    rec.audio_expires_at = timezone.now() - timedelta(days=1)
    rec.save()
    client.force_login(member)
    assert client.get(url).status_code == 404
    rec.audio_expires_at = None
    rec.save()
    rec.tracks.all().delete()
    assert client.get(url).status_code == 404
