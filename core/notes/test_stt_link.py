"""IMPL-PLAN-11-local-stt-link: 내 PC를 전사 서버로 — 기기 인증·heartbeat·배정·넘기기·권한 한도·화면.

전사문은 녹음 원문이고 회의록 본문과 따로 저장된다 — PC 전사가 회의록 본문을 바꾸지 않는다.
"""

import json
import uuid
from datetime import timedelta

import pytest
from cryptography.fernet import Fernet
from django.core.files.base import ContentFile
from django.utils import timezone

from accounts.models import ApiToken, User
from notes import stt_link
from notes import transcription as tx
from notes.models import SttDeviceCode, SttServer, TranscriptionJob, VoiceTrack
from notes.services import DRAFT_BODY, start_recording
from orgs.models import OrgMembership
from orgs.services import set_org_settings

pytestmark = pytest.mark.django_db
TURBO = "Systran/faster-whisper-large-v3-turbo"
MODELS = [
    {
        "id": TURBO,
        "display_name": "OpenAI Whisper large-v3-turbo",
        "status": "ready",
        "fits": True,
        "device": "cuda",
    },
    {"id": "small", "status": "not_downloaded", "fits": True},
    {"id": "huge", "status": "not_downloaded", "fits": False},
]
SEGS = [
    {"seq": 1, "user_id": "h", "start_ms": 0, "duration_ms": 60_000},
    {"seq": 2, "user_id": "a", "start_ms": 70_000, "duration_ms": 120_000},
]


@pytest.fixture(autouse=True)
def _env(settings, tmp_path):
    settings.CREDENTIAL_KEY = Fernet.generate_key().decode()
    settings.MEDIA_ROOT = tmp_path


def _api(client, method, url, data=None, token=None):
    headers = {"Authorization": f"Bearer {token}"} if token else {}
    return getattr(client, method)(
        url,
        data=json.dumps(data) if data is not None else None,
        content_type="application/json",
        headers=headers,
    )


@pytest.fixture
def bot(client):
    u = User.objects.create_user("discord-bot", password="pw12345678", display_name="봇")
    raw = ApiToken.issue(u, "봇", "bot")[1]
    return lambda m, url, data=None: _api(client, m, "/api/integrations/discord" + url, data, raw)


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


@pytest.fixture
def other(org):
    u = User.objects.create_user("other2", password="pw12345678", display_name="다른팀원")
    OrgMembership.objects.create(org=org, user=u, role="member")
    return u


def _link(client, user, machine_id=None, name="내 데스크톱"):
    """PC connect → 사람이 허용 → PC가 토큰을 받는다. (server, 토큰 원문)."""
    r = _api(
        client,
        "post",
        "/api/integrations/stt/device",
        {"name": name, "machine_id": machine_id or str(uuid.uuid4()), "version": "0.1.0"},
    )
    assert r.status_code == 200, r.content
    d = r.json()
    stt_link.approve(stt_link.find_code(d["user_code"].lower().replace("-", "")), user, name)
    r = _api(
        client, "post", "/api/integrations/stt/device/token", {"device_code": d["device_code"]}
    )
    assert r.status_code == 200, r.content
    return SttServer.objects.get(pk=r.json()["server_id"]), r.json()["access_token"]


def _beat(client, token, job_id=None, models=MODELS, **extra):
    SttServer.objects.filter(token__key_hash=ApiToken._hash(token)).update(last_seen_at=None)
    return _api(
        client,
        "post",
        "/api/integrations/stt/heartbeat",
        {"version": "0.1.0", "job_id": job_id, "concurrency": 2, "models": models, **extra},
        token,
    )


def _pc(client, user):
    server, token = _link(client, user)
    assert _beat(client, token).status_code == 200
    server.refresh_from_db()
    stt_link.set_pull(server, TURBO)  # 준비된 모델이면 바로 자동 전사 모델
    return server, token


def _tracks(rec, *uids):
    for uid in uids:
        VoiceTrack.objects.create(
            recording=rec,
            discord_user_id=uid,
            audio=ContentFile(b"ogg", name="t.ogg"),
            audio_size=3,
        )


def _meeting(org, host, bot, *, names_first=False):
    rec = start_recording(org=org, actor=host, guild_id="g1", voice_channel_id="v1")
    assert bot("patch", f"/meetings/{rec.pk}", {"status": "transcribing"}).status_code == 200
    stt = bot("get", f"/meetings/{rec.pk}/names").json()["stt"] if names_first else None
    return rec, stt


def _draft(bot, rec, engine="none", md=""):
    r = bot(
        "patch",
        f"/meetings/{rec.pk}",
        {"status": "draft", "transcript_md": md, "stats": {"engine": engine}, "segments": SEGS},
    )
    assert r.status_code == 200, r.content
    rec.refresh_from_db()


# ---------- 기기 인증 ----------


def test_device_flow_pending_denied_once_and_relink_revokes(client, member):
    mid = str(uuid.uuid4())
    d = _api(
        client, "post", "/api/integrations/stt/device", {"name": "PC", "machine_id": mid}
    ).json()
    assert (
        len(d["user_code"]) == 9 and d["verification_uri"].endswith("/link") and d["interval"] == 5
    )
    assert set(d["user_code"].replace("-", "")) <= set(stt_link.ALPHABET)
    assert SttDeviceCode.objects.get().code_hash != d["device_code"]  # 해시만 저장
    token = lambda: _api(  # noqa: E731
        client, "post", "/api/integrations/stt/device/token", {"device_code": d["device_code"]}
    )
    assert token().json() == {"error": "authorization_pending"}
    stt_link.deny(stt_link.find_code(d["user_code"]))
    assert token().json() == {"error": "access_denied"}

    server, raw1 = _link(client, member, mid)
    assert server.token.scope == "stt" and server.token.for_ai is False
    server2, raw2 = _link(client, member, mid, name="새 이름")
    assert server2.pk == server.pk and server2.name == "새 이름"  # 같은 기기 = 같은 행
    assert ApiToken.authenticate(raw1) is None and ApiToken.authenticate(raw2) is not None
    # 승인 뒤 첫 조회 때 한 번만 발급
    code = SttDeviceCode.objects.filter(used_at__isnull=False).first()
    assert stt_link.poll_token("nope") == (None, "expired_token")
    SttDeviceCode.objects.filter(pk=code.pk).update(used_at=None, expires_at=timezone.now())
    assert stt_link.poll_token("x")[1] == "expired_token"


def test_device_limits_servers_and_pending_eviction(client, member, monkeypatch):
    for _ in range(stt_link.MAX_SERVERS):
        _link(client, member)
    d = stt_link.start_device(name="6", machine_id=str(uuid.uuid4()), version="", device={})
    with pytest.raises(Exception, match="5대"):
        stt_link.approve(stt_link.find_code(d["user_code"]), member, "6")
    monkeypatch.setattr(stt_link, "MAX_PENDING", 3)
    codes = [
        stt_link.start_device(name="x", machine_id=str(uuid.uuid4()), version="", device={})
        for _ in range(4)
    ]
    assert stt_link.find_code(codes[0]["user_code"]) is None  # 가장 오래된 대기 코드부터 밀려남
    assert stt_link.find_code(codes[-1]["user_code"]) is not None
    r = _api(
        client,
        "post",
        "/api/integrations/stt/device",
        {"machine_id": str(uuid.uuid4()), "device": {"x": "y" * 40000}},
    )
    assert r.status_code == 422


def test_link_page_never_prefills_and_locks_and_notifies(client, member, org):
    from tasks.models import Notice

    client.force_login(member)
    d = stt_link.start_device(name="PC", machine_id=str(uuid.uuid4()), version="0.1", device={})
    page = client.get("/link?code=" + d["user_code"]).content.decode()
    assert 'name="code" value=""' in page  # 주소의 코드로 칸을 채우지 않는다
    r = client.post("/link", {"step": "lookup", "code": d["user_code"].lower()})
    assert "직접 PC에서" in r.content.decode() and d["user_code"] in r.content.decode()
    r = client.post("/link", {"step": "approve", "code": d["user_code"], "name": "거실 PC"})
    assert "연결했습니다" in r.content.decode()
    assert SttDeviceCode.objects.get().approved_by == member
    assert Notice.objects.filter(user=member, text__contains="거실 PC").exists()
    for _ in range(5):
        client.post("/link", {"step": "lookup", "code": "ZZZZ-ZZZZ"})
    d2 = stt_link.start_device(name="PC", machine_id=str(uuid.uuid4()), version="", device={})
    r = client.post("/link", {"step": "lookup", "code": d2["user_code"]})
    assert r.status_code == 429  # 맞는 코드도 잠금 중에는 안 받는다


# ---------- 토큰 범위 · heartbeat ----------


def test_stt_token_scope_and_heartbeat_limits(client, member, bot):
    server, token = _link(client, member)
    assert _api(client, "get", "/api/tasks", token=token).status_code == 403
    assert _api(client, "get", "/api/integrations/discord/orgs", token=token).status_code == 403
    member_raw = ApiToken.issue(member, "w", "write")[1]
    assert _beat(client, member_raw).status_code == 403  # 다른 범위 토큰은 PC 경로에 못 들어온다
    r = _beat(client, token)
    assert r.status_code == 200 and r.json() == {"poll_s": 5, "pull": None, "job": None}
    server.refresh_from_db()
    assert server.models == MODELS and server.concurrency == 2 and tx.online(server)
    assert _beat(client, token, models=[{"id": "x", "pad": "y" * 40000}]).status_code == 422
    assert _beat(client, token, version="0.0.0").status_code == 200
    # [모델 적용] 받지 않은 모델 → 다음 heartbeat의 pull, 받은 뒤 ready면 기본 모델로
    stt_link.set_pull(server, "small")
    assert _beat(client, token).json()["pull"] == "small"
    ready = [{**m, "status": "ready"} if m["id"] == "small" else m for m in MODELS]
    assert _beat(client, token, models=ready).json()["pull"] is None
    server.refresh_from_db()
    assert server.default_model == "small" and server.pull_model == ""
    with pytest.raises(Exception, match="쓸 수 있는 모델"):
        stt_link.set_pull(server, "huge")  # fits=false
    assert _api(client, "delete", "/api/integrations/stt/self", token=token).json() == {"ok": True}
    assert not SttServer.objects.exists() and _beat(client, token).status_code == 401


# ---------- Discord 자동 전사 ----------


def test_auto_job_goes_to_host_pc_and_pc_transcribes(client, enabled, member, bot):
    server, token = _pc(client, member)
    rec, _ = _meeting(enabled, member, bot)
    job = rec.jobs.get()
    assert (job.kind, job.status, job.engine, job.server_id) == ("auto", "queued", "pc", server.pk)
    assert job.model == TURBO and job.stats["label"] == "내 PC · OpenAI Whisper large-v3-turbo"
    stt = bot("get", f"/meetings/{rec.pk}/names").json()["stt"]
    assert stt["url"] == "" and stt["openai_api_key"] == ""  # Node는 녹음만 올린다
    assert _beat(client, token).json()["job"] is None  # draft 전에는 못 가져간다
    _draft(bot, rec)
    assert tx.claim() is None  # Node는 PC 작업을 안 가져간다
    _tracks(rec, "h")
    assert _beat(client, token).json()["job"] is None  # 화자 a의 트랙이 아직 없다
    _tracks(rec, "a")
    got = _beat(client, token).json()["job"]
    assert got["id"] == job.pk and got["source"] == "discord" and got["tracks"] == ["h", "a"]
    assert "names" not in got and "stt" not in got
    r = _api(client, "get", f"/api/integrations/stt/jobs/{job.pk}/tracks/h", token=token)
    assert r.status_code == 200 and b"".join(r.streaming_content) == b"ogg"
    assert _beat(client, token, job_id=job.pk).json()["job"] is None  # 하나씩
    rows = [
        {"seq": 2, "user_id": "a", "start_ms": 70_000, "text": "둘째"},
        {"seq": 1, "user_id": "h", "start_ms": 0, "failed": True},
        {"seq": 3, "user_id": "zz", "start_ms": 1, "text": "없는 화자"},
    ]
    patch = f"/api/integrations/stt/jobs/{job.pk}"
    assert _api(client, "patch", patch, {"done_ms": 1000, "engine": "x"}, token).json() == {
        "status": "running",
        "cancel": False,
    }
    r = _api(client, "patch", patch, {"status": "done", "rows": rows}, token)
    assert r.json()["status"] == "done"
    job.refresh_from_db()
    rec.refresh_from_db()
    assert job.engine == "pc" and rec.transcript_job_id == job.pk
    assert rec.transcript_md.splitlines()[0].endswith(f"{tx.TRANSCRIBE_FAILED}")
    assert "둘째" in rec.transcript_md and "없는 화자" not in rec.transcript_md
    assert rec.note.body_md == DRAFT_BODY.format(id=rec.note_id)  # 회의록 본문은 그대로
    assert _api(client, "patch", patch, {"status": "done"}, token).status_code == 409


def test_auto_without_pc_or_keep_zero_stays_on_node(client, enabled, admin, member, bot):
    rec, _ = _meeting(enabled, member, bot)
    assert rec.jobs.get().status == "running"  # PC 없음 → 지금처럼 Node 즉시 전사
    server, token = _pc(client, member)
    set_org_settings(enabled, {**enabled.settings, "meeting.audio_keep_days": 0}, admin)
    rec2 = start_recording(org=enabled, actor=member, guild_id="g1", voice_channel_id="v2")
    rec2.status = "recording"
    assert tx.auto_server(rec2) is None  # 보관 0일이면 PC로 보내지 않는다


def test_pc_gone_after_draft_hands_off_to_node(client, enabled, admin, member, bot):
    server, token = _pc(client, member)
    rec, _ = _meeting(enabled, member, bot, names_first=True)
    _draft(bot, rec)
    job = rec.jobs.get()
    SttServer.objects.filter(pk=server.pk).update(
        last_seen_at=timezone.now() - timedelta(minutes=3)
    )
    got = tx.claim()  # Node claim이 점검하고 넘겨받은 작업을 가져간다
    assert got.pk == job.pk and got.engine == "local" and got.server_id is None
    assert got.stats["handoff"] is True
    # 넘겨받은 작업은 조직 수단 한도에 세지 않는다
    assert tx.org_used(rec) is False
    # 조직 수단도 없으면 no_engine
    enabled.settings = {"meeting.recording_enabled": True}  # 서버 주소·키 모두 없음
    enabled.save()
    rec2, _ = _meeting(enabled, member, bot)
    SttServer.objects.filter(pk=server.pk).update(last_seen_at=timezone.now())
    rec2.jobs.all().delete()
    tx.start_auto_job(rec2)
    _draft(bot, rec2)
    SttServer.objects.filter(pk=server.pk).update(
        last_seen_at=timezone.now() - timedelta(minutes=3)
    )
    tx.sweep()
    assert rec2.jobs.get().error == "no_engine"


def test_pc_gone_while_transcribing_runs_once(client, enabled, member, bot):
    server, token = _pc(client, member)
    old = timezone.now() - timedelta(minutes=3)
    # names 전에 꺼짐 → PC 작업 취소, Node가 조직 stt로 바로 전사 → draft 때 끝난 자동 작업 1건
    rec, _ = _meeting(enabled, member, bot)
    SttServer.objects.filter(pk=server.pk).update(last_seen_at=old)
    tx.sweep()
    assert rec.jobs.get().error == "pc_offline"
    assert bot("get", f"/meetings/{rec.pk}/names").json()["stt"]["url"]  # 조직 stt
    _draft(bot, rec, engine="local", md="[00:00:00] 팀원: 노드 전사")
    done = rec.jobs.exclude(engine="pc").get()
    assert done.status == "done" and rec.transcript_md.endswith("노드 전사")
    # names 뒤에 꺼짐(stt를 비워 줬다) → draft 때 조직 수단 대기 1건
    SttServer.objects.filter(pk=server.pk).update(last_seen_at=timezone.now())
    rec2, stt = _meeting(enabled, member, bot, names_first=True)
    assert stt["url"] == ""
    SttServer.objects.filter(pk=server.pk).update(last_seen_at=old)
    tx.sweep()
    _draft(bot, rec2)
    queued = rec2.jobs.get(status="queued")
    assert queued.engine == "local" and queued.server_id is None and queued.kind == "auto"
    assert rec2.jobs.filter(status__in=TranscriptionJob.ACTIVE).count() == 1


# ---------- 다시 전사 · 되돌리기 ----------


def _drafted_with_tracks(client, org, host, bot):
    rec, _ = _meeting(org, host, bot)
    _draft(bot, rec, engine="local", md="[00:00:00] 팀원: 첫 전사")
    _tracks(rec, "h", "a")
    return rec


@pytest.mark.parametrize("path", ["gone", "restart", "node", "unlink"])
def test_requeue_paths_never_break_queued_uniqueness(client, enabled, admin, member, bot, path):
    rec = _drafted_with_tracks(client, enabled, member, bot)
    server, token = _pc(client, member)
    if path == "node":  # Node가 가져간 작업에도 같은 규칙
        pc_job = tx.request_retry(rec, engine="openai", model="", actor=admin)
        assert tx.claim().pk == pc_job.pk
    else:
        pc_job = tx.request_retry(rec, engine="pc", model=TURBO, actor=member, server=server)
        assert _beat(client, token).json()["job"]["id"] == pc_job.pk
    tx.request_retry(
        rec, engine="openai", model="", actor=admin
    )  # → 돌던 작업 cancelling + 새 대기
    pc_job.refresh_from_db()
    assert pc_job.status == "cancelling"
    if path == "gone":
        SttServer.objects.filter(pk=server.pk).update(
            last_seen_at=timezone.now() - timedelta(minutes=3)
        )
        tx.sweep()
    elif path == "restart":
        _beat(client, token)  # job_id 없음 = PC가 다시 켜짐
    elif path == "node":
        tx.requeue()
    else:
        stt_link.unlink(server)
    pc_job.refresh_from_db()
    assert pc_job.status == "cancelled"
    assert rec.jobs.filter(status="queued").count() == 1


def test_pc_restart_requeues_and_node_requeue_covers_upload(client, enabled, admin, member, bot):
    rec = _drafted_with_tracks(client, enabled, member, bot)
    server, token = _pc(client, member)
    job = tx.request_retry(rec, engine="pc", model=TURBO, actor=member, server=server)
    _beat(client, token)
    got = _beat(client, token).json()["job"]  # 재시작: 되돌린 뒤 같은 heartbeat에서 다시 배정
    assert got["id"] == job.pk
    job.refresh_from_db()
    assert job.status == "running"
    # 다른 서버(남의 PC) 토큰으로는 내려받기·보고가 404
    other_server, other_token = _pc(client, admin)
    for m, url in (("get", f"/jobs/{job.pk}/tracks/h"), ("patch", f"/jobs/{job.pk}")):
        r = _api(
            client, m, "/api/integrations/stt" + url, {} if m == "patch" else None, other_token
        )
        assert r.status_code == 404
    # 볼 수 없는 녹음이 되면 404(그 사이 조직에서 빠졌다)
    OrgMembership.objects.filter(user=member).delete()
    r = _api(client, "get", f"/api/integrations/stt/jobs/{job.pk}/tracks/h", token=token)
    assert r.status_code == 404
    # Node requeue: 올린 녹음(kind=upload)도 가져갔던 것이면 되돌린다
    j2 = TranscriptionJob.objects.create(
        recording=rec, kind="upload", status="queued", engine="openai", model="whisper-1"
    )
    job.status = "cancelled"
    job.save()
    assert tx.claim().pk == j2.pk
    assert tx.requeue() == 1
    j2.refresh_from_db()
    assert j2.status == "queued"


def test_cancel_running_pc_job_and_gone_cancel_is_immediate(client, enabled, admin, member, bot):
    rec = _drafted_with_tracks(client, enabled, member, bot)
    server, token = _pc(client, member)
    job = tx.request_retry(rec, engine="pc", model=TURBO, actor=member, server=server)
    _beat(client, token)
    tx.cancel(job, member)  # 서버 주인
    r = _api(client, "patch", f"/api/integrations/stt/jobs/{job.pk}", {"done_ms": 1}, token)
    assert r.json() == {"status": "cancelling", "cancel": True}
    _api(client, "patch", f"/api/integrations/stt/jobs/{job.pk}", {"status": "cancelled"}, token)
    job2 = tx.request_retry(rec, engine="pc", model=TURBO, actor=member, server=server)
    _beat(client, token)
    SttServer.objects.filter(pk=server.pk).update(
        last_seen_at=timezone.now() - timedelta(minutes=3)
    )
    job2.refresh_from_db()
    assert tx.cancel(job2, admin).status == "cancelled"


# ---------- 권한 · 한도(§8) ----------


def test_org_limit_once_per_recording(client, enabled, admin, member, other, bot):
    rec = _drafted_with_tracks(client, enabled, member, bot)
    rec.note.status = "final"  # other도 볼 수 있게 확정
    rec.note.save()
    assert tx.org_used(rec) is False  # 자동 전사만 있었다
    first = tx.request_retry(rec, engine="openai", model="", actor=member)
    tx.cancel(first, member)  # 시작 전 취소는 세지 않는다
    assert tx.org_used(rec) is False
    j = tx.request_retry(rec, engine="openai", model="", actor=member)
    tx.claim()
    with pytest.raises(Exception, match="이미 조직 전사 수단"):
        tx.request_retry(rec, engine="openai", model="", actor=other)
    with pytest.raises(Exception, match="이미 조직 전사 수단"):
        tx.request_retry(rec, engine="openai", model="", actor=member)
    assert tx.request_retry(rec, engine="openai", model="", actor=admin)  # 관리자 예외
    with pytest.raises(Exception, match="권한"):
        tx.cancel(j, other)  # 요청자·관리자만
    set_org_settings(enabled, {**enabled.settings, "meeting.transcribe_level": "admin"}, admin)
    rec2 = _drafted_with_tracks(client, enabled, member, bot)
    with pytest.raises(Exception, match="조직 관리자만"):
        tx.request_retry(rec2, engine="openai", model="", actor=member)
    # 내 PC는 한도 없음, 남의 PC는 못 고른다
    server, token = _pc(client, member)
    tx.request_retry(rec2, engine="pc", model=TURBO, actor=member, server=server)
    tx.request_retry(rec2, engine="pc", model=TURBO, actor=member, server=server)
    with pytest.raises(Exception, match="내 PC"):
        tx.request_retry(rec, engine="pc", model=TURBO, actor=other, server=server)


def test_member_pc_off_hides_options_and_cancels_queued(client, enabled, admin, member, bot):
    rec = _drafted_with_tracks(client, enabled, member, bot)
    server, token = _pc(client, member)
    job = tx.request_retry(rec, engine="pc", model=TURBO, actor=member, server=server)
    set_org_settings(enabled, {**enabled.settings, "meeting.member_pc": False}, admin)
    assert _beat(client, token).json()["job"] is None
    job.refresh_from_db()
    assert (job.status, job.error) == ("cancelled", "pc_disabled")
    with pytest.raises(Exception, match="멤버 PC"):
        tx.request_retry(rec, engine="pc", model=TURBO, actor=member, server=server)


def test_format_transcript_matches_node():
    # discord_gateway formatTranscript와 같은 출력(정렬: start_ms, seq · 빈 text 제외 · 실패 문구)
    rows = [
        {"seq": 2, "user_id": "b", "start_ms": 3_723_000, "text": "끝"},
        {"seq": 1, "user_id": "a", "start_ms": 0, "text": "시작"},
        {"seq": 3, "user_id": "c", "start_ms": 5000, "failed": True},
        {"seq": 4, "user_id": "a", "start_ms": 6000, "text": ""},
    ]
    assert tx.format_transcript(rows, {"a": "홍길동"}) == (
        "[00:00:00] 홍길동: 시작\n[00:00:05] c: [전사 실패]\n[01:02:03] b: 끝"
    )


# ---------- 화면 ----------


def test_install_script_redirects_to_configured_base(client, settings):
    settings.STT_SCRIPT_BASE = "https://raw.githubusercontent.com/acct/udally-stt/abc123"
    r = client.get("/stt/install.ps1")
    assert r.status_code == 302
    assert (
        r["Location"]
        == "https://raw.githubusercontent.com/acct/udally-stt/abc123/scripts/install.ps1"
    )
    assert client.get("/stt/evil.ps1").status_code == 404


def test_settings_page_pull_unlink_and_panel_options(client, enabled, admin, member, bot):
    rec = _drafted_with_tracks(client, enabled, member, bot)
    server, token = _pc(client, member)
    client.force_login(member)
    page = client.get("/settings/stt").content.decode()
    assert "내 데스크톱" in page and "/stt/install.ps1 | iex" in page and "켜짐" in page
    r = client.post(f"/settings/stt/{server.pk}/pull", {"model": "small"})
    assert "받는 중" in r.content.decode() and 'hx-trigger="every 3s"' in r.content.decode()
    assert (
        "전사 서버" not in client.get("/settings/tokens").content.decode().split("API 토큰</h2>")[1]
    )
    body = client.get(f"/orgs/{enabled.pk}/transcribe/recordings/{rec.pk}/panel").content.decode()
    assert f'value="pc|{server.pk}|{TURBO}"' in body
    assert "내 PC · OpenAI Whisper large-v3-turbo" in body and "large-turbo" not in body
    SttServer.objects.filter(pk=server.pk).update(
        last_seen_at=timezone.now() - timedelta(minutes=1)
    )
    body = client.get(f"/orgs/{enabled.pk}/transcribe/recordings/{rec.pk}/panel").content.decode()
    assert "내 PC · 꺼져 있음" in body and f"pc|{server.pk}|" not in body
    r = client.post(f"/settings/stt/{server.pk}/unlink")
    assert r.status_code == 302 and not SttServer.objects.exists()
    client.force_login(admin)
    assert client.post(f"/settings/stt/{server.pk}/unlink").status_code == 404


# ---------- Sol 교차 리뷰 반영 ----------


def test_pc_glossary_only_has_terms_the_pc_owner_can_see(client, enabled, admin, member, bot):
    """관리자가 시작한 회의를 멤버 PC로 전사할 때, 멤버가 못 보는 팀 전용 프로젝트명이 PC로 나가지 않는다."""
    from projects.services import create_project, set_visibility

    secret = create_project(org=enabled, name="비밀프로젝트 오메가", actor=admin, owners=[admin])
    set_visibility(secret, "teams", actor=admin)
    create_project(org=enabled, name="학식개편 프로젝트", actor=admin, owners=[admin])
    rec = _drafted_with_tracks(client, enabled, admin, bot)
    rec.note.status = "final"
    rec.note.save()
    server, token = _pc(client, member)
    tx.request_retry(rec, engine="pc", model=TURBO, actor=member, server=server)
    glossary = _beat(client, token).json()["job"]["glossary"]
    from notes.services import meeting_glossary

    assert "비밀프로젝트" in meeting_glossary(rec)  # 시작자(관리자)는 본다
    assert "학식개편" in glossary and "비밀프로젝트" not in glossary


def test_stale_pc_cannot_finish_job_handed_to_node(client, enabled, member, bot, monkeypatch):
    """PATCH 소유권 확인 뒤 작업이 넘어가 Node가 가져갔으면, 이전 PC의 결과는 409이고 아무것도 덮지 않는다."""
    from api.routers import stt as stt_router

    server, token = _pc(client, member)
    rec, _ = _meeting(enabled, member, bot)
    _draft(bot, rec, engine="none")
    _tracks(rec, "h", "a")
    job = TranscriptionJob.objects.get(pk=_beat(client, token).json()["job"]["id"])
    real = stt_router._my_job

    def racing(request, job_id):
        got = real(request, job_id)
        tx._handoff(TranscriptionJob.objects.get(pk=job_id))  # 그 사이 PC가 꺼진 것으로 보고 넘김
        assert tx.claim().pk == job_id  # Node가 가져감
        return got

    monkeypatch.setattr(stt_router, "_my_job", racing)
    rows = [{"seq": 1, "user_id": "h", "start_ms": 0, "text": "이전 PC 결과"}]
    r = _api(
        client,
        "patch",
        f"/api/integrations/stt/jobs/{job.pk}",
        {"status": "done", "rows": rows},
        token,
    )
    assert r.status_code == 409
    job.refresh_from_db()
    rec.refresh_from_db()
    assert job.status == "running" and job.server_id is None and job.transcript_md == ""
    assert "이전 PC 결과" not in rec.transcript_md


def test_requeued_then_cancelled_org_job_still_counts(client, enabled, member, other, bot):
    """가져가 실행한 조직 전사가 Node 재시작으로 대기로 돌아간 뒤 취소돼도 시작 전 취소가 아니다."""
    rec = _drafted_with_tracks(client, enabled, member, bot)
    rec.note.status = "final"
    rec.note.save()
    job = tx.request_retry(rec, engine="openai", model="", actor=member)
    assert tx.claim().pk == job.pk
    assert tx.requeue() == 1
    job.refresh_from_db()
    assert job.status == "queued"
    tx.cancel(job, member)
    assert tx.org_used(rec) is True
    with pytest.raises(Exception, match="이미 조직 전사 수단"):
        tx.request_retry(rec, engine="openai", model="", actor=other)


def test_backfill_marks_pre_deploy_running_jobs_claimed(enabled, member):
    """배포 전 Node가 가져가 돌던 다시 전사·올린 녹음 작업은 claimed_at이 비어 있다 — 백필 뒤 재시작 복구에 걸린다."""
    import importlib

    from django.apps import apps

    rec = start_recording(org=enabled, actor=member, guild_id="g1", voice_channel_id="v1")
    rec.status = "draft"
    rec.save()
    t = timezone.now() - timedelta(minutes=5)
    up = TranscriptionJob.objects.create(
        recording=rec, kind="upload", status="running", engine="openai", started_at=t
    )
    auto = TranscriptionJob.objects.create(
        recording=rec, kind="auto", status="done", engine="local", started_at=t
    )
    old = TranscriptionJob.objects.create(
        recording=rec, kind="retry", status="cancelled", engine="openai", started_at=t
    )
    mod = importlib.import_module("notes.migrations.0012_backfill_claimed_at")
    mod.backfill(apps, None)
    for j in (up, auto, old):
        j.refresh_from_db()
    assert up.claimed_at == t and up.first_claimed_at == t
    assert auto.claimed_at is None  # Node가 바로 전사하던 자동 작업은 가져간 적이 없다
    assert old.first_claimed_at == t  # 실행했던 작업은 한도에 센다
    assert tx.requeue() == 1


def test_approved_but_unclaimed_codes_count_toward_server_limit(member):
    codes = [
        stt_link.start_device(name=str(i), machine_id=str(uuid.uuid4()), version="", device={})
        for i in range(stt_link.MAX_SERVERS + 1)
    ]
    for d in codes[:-1]:
        stt_link.approve(stt_link.find_code(d["user_code"]), member, "pc")
    with pytest.raises(Exception, match="5대"):
        stt_link.approve(stt_link.find_code(codes[-1]["user_code"]), member, "pc")
    for d in codes[:-1]:
        assert stt_link.poll_token(d["device_code"])[1] == ""
    assert SttServer.objects.filter(owner=member).count() == stt_link.MAX_SERVERS


ON_PG = "postgres" in __import__("os").environ.get("DATABASE_URL", "")


def _for_update_tables(queries) -> list[str]:
    import re

    return [
        re.search(r'FROM "(\w+)"', q["sql"]).group(1) for q in queries if "FOR UPDATE" in q["sql"]
    ]


@pytest.mark.skipif(not ON_PG, reason="FOR UPDATE는 Postgres에서만 질의에 나온다")
def test_lock_order_is_recording_then_job(client, enabled, admin, member, bot):
    """교착 방지: 작업 행을 잠그는 경로는 모두 녹음 행을 먼저 잠근다(request_retry와 같은 순서)."""
    from django.db import connection
    from django.test.utils import CaptureQueriesContext

    rec = _drafted_with_tracks(client, enabled, member, bot)
    server, token = _pc(client, member)
    job = tx.request_retry(rec, engine="pc", model=TURBO, actor=member, server=server)
    set_org_settings(enabled, {**enabled.settings, "meeting.member_pc": False}, admin)
    calls = [
        lambda: tx.report(job.pk, {"done_ms": 1}),
        lambda: tx.claim_for(server),
        lambda: tx.cancel(job, admin),
        lambda: tx.requeue_or_cancel(job.pk),
    ]
    for call in calls:
        with CaptureQueriesContext(connection) as q:
            call()
        tables = _for_update_tables(q.captured_queries)
        if "notes_transcriptionjob" in tables:
            assert tables[0] == "notes_voicerecording", tables


@pytest.mark.django_db(transaction=True)
@pytest.mark.skipif(not ON_PG, reason="실제 행 잠금 교착은 Postgres에서만")
def test_no_deadlock_between_pc_claim_and_org_retry(enabled, admin, member):
    """한 쪽은 녹음→작업(조직 다시 전사 순서), 다른 쪽은 PC 배정(멤버 PC 꺼짐 → 작업 놓기). 교착 없이 끝난다."""
    import threading
    import time

    from django.db import connection, transaction

    from notes.models import VoiceRecording

    rec = start_recording(org=enabled, actor=member, guild_id="g1", voice_channel_id="v1")
    rec.status, rec.segments = "draft", SEGS
    rec.save()
    _tracks(rec, "h", "a")
    server = SttServer.objects.create(
        owner=member, name="pc", machine_id="m", models=MODELS, last_seen_at=timezone.now()
    )
    job = TranscriptionJob.objects.create(
        recording=rec, kind="retry", status="queued", engine="pc", model=TURBO, server=server
    )
    set_org_settings(enabled, {**enabled.settings, "meeting.member_pc": False}, admin)
    locked, errors = threading.Event(), []

    def org_retry():
        try:
            with transaction.atomic():
                list(VoiceRecording.objects.select_for_update().filter(pk=rec.pk))
                locked.set()
                time.sleep(0.5)
                TranscriptionJob.objects.filter(pk=job.pk).update(model="x")
        except Exception as e:  # noqa: BLE001
            errors.append(e)
        finally:
            connection.close()

    def pc_claim():
        locked.wait()
        try:
            tx.claim_for(server)
        except Exception as e:  # noqa: BLE001
            errors.append(e)
        finally:
            connection.close()

    threads = [threading.Thread(target=org_retry), threading.Thread(target=pc_claim)]
    for t in threads:
        t.start()
    for t in threads:
        t.join(20)
    assert errors == []
    job.refresh_from_db()
    assert job.status == "cancelled" and job.error == "pc_disabled"


# ---------- udally-stt link.py 계약(967e4ec) ----------


def _upload_job(client, org, member, server):
    from notes.models import VoiceRecording
    from notes.services import create_note

    note = create_note(org=org, actor=member, title="올린 회의")
    rec = VoiceRecording.objects.create(
        note=note,
        source="upload",
        status="draft",
        guild_id="",
        voice_channel_id="",
        started_by=member,
        host=member,
        audio=ContentFile(b"mp3", name="a.mp3"),
        audio_size=3,
    )
    return tx.request_upload(rec, actor=member, engine="pc", model=TURBO, server=server)


def test_pc_upload_rows_with_upload_user_id_are_kept(client, enabled, member, bot):
    """link.py는 올린 녹음 행의 user_id를 "upload"로 보낸다(Node와 같음) — 버리지 않고 '올린 녹음' 화자로."""
    server, token = _pc(client, member)
    job = _upload_job(client, enabled, member, server)
    got = _beat(client, token).json()["job"]
    assert got["id"] == job.pk and got["source"] == "upload" and got["segments"] == []
    r = _api(client, "get", f"/api/integrations/stt/jobs/{job.pk}/audio", token=token)
    assert r.status_code == 200 and r["X-Audio-Ext"] == "mp3"
    rows = [
        {"seq": 1, "user_id": "upload", "start_ms": 0, "text": "첫 구간"},
        {"seq": 2, "user_id": "upload", "start_ms": 5000, "failed": True},
    ]
    stats = {"device": None, "compute_type": None, "elapsed_ms": 10}
    patch = {"status": "done", "rows": rows, "stats": stats}
    r = _api(client, "patch", f"/api/integrations/stt/jobs/{job.pk}", patch, token)
    assert r.status_code == 200, r.content
    job.refresh_from_db()
    assert (
        job.transcript_md
        == f"[00:00:00] {tx.UPLOAD_SPEAKER}: 첫 구간\n[00:00:05] {tx.UPLOAD_SPEAKER}: [전사 실패]"
    )


@pytest.mark.parametrize(
    ("sent", "kept"),
    [
        ("audio_unavailable", "audio_unavailable"),
        ("no_audio", "audio_unavailable"),
        ("transcript_too_large", "transcript_too_large"),
        ("pc_error", "pc_error"),
        ("out_of_memory", "out_of_memory"),
        ("model_not_ready", "model_not_ready"),
        ("weird", "pc_error"),
    ],
)
def test_pc_error_codes_from_link_py(client, enabled, member, bot, sent, kept):
    server, token = _pc(client, member)
    job = _upload_job(client, enabled, member, server)
    _beat(client, token)
    body = {
        "status": "failed",
        "rows": None,
        "error": sent,
    }  # link.py는 실패 때 rows를 null로 보낸다
    r = _api(client, "patch", f"/api/integrations/stt/jobs/{job.pk}", body, token)
    assert r.status_code == 200, r.content
    job.refresh_from_db()
    assert (job.status, job.error) == ("failed", kept)
    assert tx.ERROR_LABELS[kept]
