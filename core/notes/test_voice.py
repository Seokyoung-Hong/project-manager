"""IMPL-PLAN-9 M2: 음성 회의록 core(모델·가시성·봇 API·회의록 사용자 API·meeting.* 설정)."""

import json

import pytest
from cryptography.fernet import Fernet
from django.utils import timezone

from accounts.models import ApiToken, User
from notes.models import MeetingNote, VoiceRecording
from notes.services import create_note, start_recording, visible_notes
from orgs.models import OrgMembership
from orgs.services import create_team, set_org_settings
from orgs.settings import validate_stt_url
from projects.services import create_project, set_visibility
from tasks.models import ChangeLog, Notice

KEY = "sk-local-평문-키-1234"


@pytest.fixture(autouse=True)
def _cred(settings):
    settings.CREDENTIAL_KEY = Fernet.generate_key().decode()


@pytest.fixture
def linked_admin(admin):
    admin.discord_user_id = "222"
    admin.discord_linked_at = timezone.now()
    admin.save()
    return admin


@pytest.fixture
def other(org):
    u = User.objects.create_user(
        "other1",
        password="pw12345678",
        display_name="다른팀원",
        discord_user_id="333",
        discord_linked_at=timezone.now(),
    )
    OrgMembership.objects.create(org=org, user=u, role="member")
    return u


@pytest.fixture
def bot(client, db):
    u = User.objects.create_user("discord-bot", password="pw12345678", display_name="봇")
    _, raw = ApiToken.issue(u, "봇", "bot")

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
    set_org_settings(org, {"meeting.recording_enabled": True}, admin)
    org.refresh_from_db()
    return org


def _rec(org, starter, **kw):
    return start_recording(org=org, actor=starter, guild_id="g1", voice_channel_id="v1", **kw)


def _token(user, *, ai: bool):
    return ApiToken.issue(user, "t", "write", for_ai=ai)[1]


def _h(raw):
    return {"Authorization": f"Bearer {raw}"}


# ---------- 가시성 ----------


def test_draft_visible_only_to_starter_and_admin(enabled, member, other, admin):
    rec = _rec(enabled, member)
    note = rec.note
    assert note.status == "draft" and note.source == "voice"
    assert note in visible_notes(member)
    assert note in visible_notes(admin)
    assert note not in visible_notes(other)


def test_participant_does_not_see_draft(enabled, member, other, bot):
    """참여자로 들어가도 초안은 진행자·관리자만 본다."""
    rec = _rec(enabled, member)
    r = bot(
        "patch",
        f"/meetings/{rec.pk}",
        {"participants": [{"discord_user_id": "333", "discord_name": "닉"}]},
    )
    assert r.status_code == 200, r.content
    assert rec.note not in visible_notes(other)


def test_final_note_follows_project_and_private_team(org, admin, member, other):
    hidden = create_project(org=org, name="비공개", actor=admin, owners=[admin])
    set_visibility(hidden, "teams", actor=admin)
    pnote = create_note(org=org, actor=admin, project=hidden)
    team = create_team(org=org, name="비밀팀", actor=admin)
    team.is_private = True
    team.save()
    tnote = create_note(org=org, actor=admin)
    MeetingNote.objects.filter(pk=tnote.pk).update(team=team)
    assert pnote not in visible_notes(member) and pnote in visible_notes(admin)
    assert tnote not in visible_notes(member) and tnote in visible_notes(admin)


def test_web_list_hides_draft_from_other_member(client, enabled, member, other):
    rec = _rec(enabled, member, title="비밀 회의")
    client.force_login(other)
    assert "비밀 회의" not in client.get(f"/orgs/{enabled.pk}/notes").content.decode()
    assert (
        client.post(f"/notes/{rec.note_id}/save", {"field": "title", "value": "x"}).status_code
        == 404
    )


# ---------- 봇 API ----------


def test_bot_api_requires_bot_token(client, enabled, member, write_token):
    r = client.post(
        "/api/integrations/discord/meetings/check",
        {"discord_user_id": "111", "guild_id": "g1"},
        content_type="application/json",
        headers=_h(write_token),
    )
    assert r.status_code == 403


def test_check_denied_when_recording_disabled(org, member, bot):
    org.discord_guild_id = "g1"
    org.save()
    r = bot("post", "/meetings/check", {"discord_user_id": "111", "guild_id": "g1"})
    assert r.status_code == 403
    assert "회의 녹음" in r.json()["detail"]["meeting"]


def test_check_denies_invisible_project(enabled, admin, member, bot):
    hidden = create_project(org=enabled, name="비공개", actor=admin, owners=[admin])
    set_visibility(hidden, "teams", actor=admin)
    r = bot(
        "post",
        "/meetings/check",
        {"discord_user_id": "111", "guild_id": "g1", "project_id": hidden.pk},
    )
    assert r.status_code == 400


def test_start_stop_draft_flow(enabled, member, other, bot):
    r = bot(
        "post",
        "/meetings",
        {"discord_user_id": "111", "guild_id": "g1", "voice_channel_id": "v1", "title": "주간"},
    )
    assert r.status_code == 200, r.content
    data = r.json()
    assert data["status"] == "recording" and data["max_minutes"] == 180 and data["keep_days"] == 7
    rid = data["id"]
    # 길드당 하나
    again = bot(
        "post", "/meetings", {"discord_user_id": "111", "guild_id": "g1", "voice_channel_id": "v2"}
    )
    assert again.status_code == 400
    # /회의종료는 진행자·관리자만
    r = bot(
        "patch",
        f"/meetings/{rid}",
        {"status": "transcribing", "end_reason": "command", "discord_user_id": "333"},
    )
    assert r.status_code == 403
    r = bot(
        "patch",
        f"/meetings/{rid}",
        {"status": "transcribing", "end_reason": "command", "discord_user_id": "111"},
    )
    assert r.status_code == 200 and r.json()["audio_expires_at"]
    note = MeetingNote.objects.get(pk=data["note_id"])
    assert note.status == "draft"


def test_status_never_goes_backward(enabled, member, bot):
    rec = _rec(enabled, member)
    assert bot("patch", f"/meetings/{rec.pk}", {"status": "transcribing"}).status_code == 200
    assert bot("patch", f"/meetings/{rec.pk}", {"status": "draft"}).status_code == 200
    r = bot("patch", f"/meetings/{rec.pk}", {"status": "transcribing"})
    assert r.status_code == 400


def test_transcript_upload_fills_template_and_notifies(enabled, member, bot):
    rec = _rec(enabled, member)
    bot("patch", f"/meetings/{rec.pk}", {"status": "transcribing"})
    r = bot(
        "patch",
        f"/meetings/{rec.pk}",
        {
            "status": "draft",
            "transcript_md": "[00:00:12] 팀원: 안녕하세요",
            "stats": {"engines": [{"engine": "local", "segments": 3, "failed": 0}]},
        },
    )
    assert r.status_code == 200
    rec.refresh_from_db()
    assert rec.transcript_md.startswith("[00:00:12]")
    # 전사 원문은 body_md에 넣지 않는다(v2 §4.1). 화면·API가 transcript_md를 따로 낸다
    assert "## 요약" in rec.note.body_md and "안녕하세요" not in rec.note.body_md
    assert Notice.objects.filter(user=member, text__contains="회의록 초안").exists()


HOST_LEFT = (
    "회의 진행자가 나가서 회의를 종료하였습니다. 새 회의를 시작하려면 /회의시작 을 눌러 주세요."
)


def test_host_left_returns_channel_notice(enabled, member, bot):
    rec = _rec(enabled, member)
    check = bot("post", "/meetings/check", {"discord_user_id": "111", "guild_id": "g1"}).json()
    assert check["leave_grace_s"] == 10
    r = bot(
        "patch",
        f"/meetings/{rec.pk}",
        {"status": "transcribing", "end_reason": "host_left", "discord_user_id": "111"},
    )
    assert r.json()["channel_notice"] == HOST_LEFT
    assert r.json()["host"]["discord_user_id"] == "111"


def _host_to(bot, rec, by, target, parts):
    return bot(
        "post",
        f"/meetings/{rec.pk}/host",
        {"discord_user_id": by, "target_discord_user_id": target, "participants": parts},
    )


PARTS = [
    {"discord_user_id": "111", "discord_name": "a"},
    {"discord_user_id": "333", "discord_name": "b"},
    {"discord_user_id": "555", "discord_name": "손님"},
]


def test_only_host_can_hand_over(enabled, member, other, bot):
    rec = _rec(enabled, member)
    assert _host_to(bot, rec, "333", "111", PARTS).status_code == 403  # 진행자가 아니다
    assert _host_to(bot, rec, "111", "555", PARTS).status_code == 400  # 계정 미연결
    gone = [*PARTS[:1], {**PARTS[1], "left_at": "2026-10-06T10:00:00"}]
    assert _host_to(bot, rec, "111", "333", gone).status_code == 400  # 채널에 없다
    r = _host_to(bot, rec, "111", "333", PARTS)
    assert r.status_code == 200, r.content
    assert r.json()["channel_notice"] == "회의 진행자가 팀원님에서 다른팀원님으로 바뀌었습니다."
    rec.refresh_from_db()
    assert rec.host == other and rec.started_by == member
    assert [(c["from_user_id"], c["to_user_id"]) for c in rec.host_changes] == [
        (member.pk, other.pk)
    ]
    # 이전 진행자는 다시 넘길 수 없다
    assert _host_to(bot, rec, "111", "111", PARTS).status_code == 403


def test_permissions_follow_host(client, enabled, member, other, bot):
    rec = _rec(enabled, member)
    _host_to(bot, rec, "111", "333", PARTS)
    assert rec.note not in visible_notes(member)  # 이전 진행자(처음 시작한 사람)는 권한 없음
    assert rec.note in visible_notes(other)
    old = client.get(f"/api/notes/{rec.note_id}", headers=_h(_token(member, ai=False)))
    assert old.status_code == 404
    patch = client.patch(
        f"/api/notes/{rec.note_id}",
        {"version": 1, "title": "새 제목"},
        content_type="application/json",
        headers=_h(_token(other, ai=False)),
    )
    assert patch.status_code == 200
    # 종료도 지금 진행자만
    stop = {"status": "transcribing", "end_reason": "command"}
    assert (
        bot("patch", f"/meetings/{rec.pk}", {**stop, "discord_user_id": "111"}).status_code == 403
    )
    assert (
        bot("patch", f"/meetings/{rec.pk}", {**stop, "discord_user_id": "333"}).status_code == 200
    )


def test_old_host_leaving_does_not_end_meeting(enabled, member, other, bot):
    rec = _rec(enabled, member)
    _host_to(bot, rec, "111", "333", PARTS)
    left = {"status": "transcribing", "end_reason": "host_left"}
    r = bot("patch", f"/meetings/{rec.pk}", {**left, "discord_user_id": "111"})
    assert r.status_code == 400
    rec.refresh_from_db()
    assert rec.status == "recording"
    r = bot("patch", f"/meetings/{rec.pk}", {**left, "discord_user_id": "333"})
    assert r.status_code == 200 and r.json()["channel_notice"] == HOST_LEFT


def test_participants_map_to_pm_accounts(client, enabled, member, linked_admin, bot):
    """연결한 조직 멤버는 PM 이름·참석자, 미연결·외부인은 'Discord 닉네임 (계정 없음)'."""
    User.objects.create_user(
        "stranger", password="pw12345678", discord_user_id="999", discord_linked_at=timezone.now()
    )
    rec = _rec(enabled, member)
    parts = [
        {"discord_user_id": "111", "discord_name": "멤버닉"},
        {"discord_user_id": "999", "discord_name": "외부닉"},
        {"discord_user_id": "555", "discord_name": "손님"},
    ]
    assert bot("patch", f"/meetings/{rec.pk}", {"participants": parts}).status_code == 200
    rec.refresh_from_db()
    assert [p["display_name"] for p in rec.participants] == [
        "팀원",
        "외부닉 (계정 없음)",
        "손님 (계정 없음)",
    ]
    assert list(rec.note.attendees.all()) == [member]
    names = {
        n["discord_user_id"]: n for n in bot("get", f"/meetings/{rec.pk}/names").json()["names"]
    }
    assert names["111"]["display_name"] == "팀원" and names["111"]["user_id"] == member.pk
    assert names["555"] == {
        "discord_user_id": "555",
        "user_id": None,
        "display_name": "손님 (계정 없음)",
    }
    assert names["222"]["display_name"] == "관리자"  # 아직 참가 전인 연결 멤버
    got = client.get(f"/api/notes/{rec.note_id}", headers=_h(_token(member, ai=False))).json()
    assert got["attendees"] == [{"id": member.pk, "display_name": "팀원"}]


def test_glossary_only_from_starter_visible_material(enabled, admin, member, bot):
    from projects.docs import create_doc
    from tasks.services import create_task

    open_p = create_project(org=enabled, name="학식API 개편", actor=admin, owners=[admin])
    secret = create_project(org=enabled, name="비밀프로젝트 오메가", actor=admin, owners=[admin])
    set_visibility(secret, "teams", actor=admin)
    for title in ("결제모듈 연동", "결제모듈 장애 대응"):
        create_task(project=open_p, title=title, actor=admin, source="web", no_due_reason="테스트")
    for title in ("기밀코드 분석", "기밀코드 이관"):
        create_task(project=secret, title=title, actor=admin, source="web", no_due_reason="테스트")
    create_doc(project=secret, actor=admin, title="오메가 설계서")
    team = create_team(org=enabled, name="비밀팀", actor=admin)
    team.is_private = True
    team.save()
    for _ in range(2):
        n = create_note(org=enabled, actor=admin, title="극비회의 안건")
        MeetingNote.objects.filter(pk=n.pk).update(team=team)
    r = bot(
        "post",
        "/meetings",
        {"discord_user_id": "111", "guild_id": "g1", "voice_channel_id": "v1"},
    )
    glossary = r.json()["glossary"]
    assert (
        "팀원" in glossary and "결제모듈" in glossary and "학식" in glossary and "API" in glossary
    )
    for leaked in ("오메가", "기밀코드", "극비회의", "비밀프로젝트"):
        assert leaked not in glossary
    # 관리자가 시작하면 비공개 자료도 들어간다(같은 함수, 다른 진행자)
    from notes.services import meeting_glossary

    rec = VoiceRecording.objects.get(pk=r.json()["id"])
    rec.started_by = admin
    assert "기밀코드" in meeting_glossary(rec)


def test_glossary_fits_prompt_budget(enabled, admin, member):
    from notes.services import PROMPT_TOKENS, _cost, meeting_glossary
    from tasks.services import create_task

    p = create_project(org=enabled, name="큰프로젝트", actor=admin, owners=[admin])
    for i in range(60):
        for _ in range(2):
            create_task(
                project=p,
                title=f"용어{i:03d}가나다라 처리",
                actor=admin,
                source="web",
                no_due_reason="테스트",
            )
    g = meeting_glossary(_rec(enabled, member))
    assert g and sum(_cost(t) + 1 for t in g.split(", ")) <= PROMPT_TOKENS


# ---------- 회의록 사용자 API ----------


def test_list_and_transcript(client, enabled, member, other):
    rec = _rec(enabled, member)
    rec.transcript_md = "[00:00:01] 팀원: 전사"
    rec.save()
    mine = client.get(
        f"/api/orgs/{enabled.pk}/notes?status=draft", headers=_h(_token(member, ai=True))
    )
    assert [n["id"] for n in mine.json()["items"]] == [rec.note_id]
    theirs = client.get(f"/api/orgs/{enabled.pk}/notes", headers=_h(_token(other, ai=True)))
    assert theirs.json()["items"] == []
    one = client.get(f"/api/notes/{rec.note_id}?transcript=1", headers=_h(_token(member, ai=True)))
    assert one.json()["recording"]["transcript_md"] == "[00:00:01] 팀원: 전사"
    plain = client.get(f"/api/notes/{rec.note_id}", headers=_h(_token(member, ai=True)))
    assert "transcript_md" not in plain.json()["recording"]
    assert (
        client.get(f"/api/notes/{rec.note_id}", headers=_h(_token(other, ai=True))).status_code
        == 404
    )


def test_patch_version_conflict(client, enabled, member):
    rec = _rec(enabled, member)
    h = _h(_token(member, ai=False))
    ok = client.patch(
        f"/api/notes/{rec.note_id}",
        {"version": 1, "body_md": "## 요약\n정리"},
        content_type="application/json",
        headers=h,
    )
    assert ok.status_code == 200 and ok.json()["version"] == 2
    stale = client.patch(
        f"/api/notes/{rec.note_id}",
        {"version": 1, "title": "x"},
        content_type="application/json",
        headers=h,
    )
    assert stale.status_code == 409
    assert stale.json()["latest"]["version"] == 2


def test_mcp_edit_follows_ai_edit_text(client, enabled, admin, member):
    rec = _rec(enabled, member)
    h = _h(_token(member, ai=True))
    body = {"version": 1, "body_md": "AI 정리"}
    assert (
        client.patch(
            f"/api/notes/{rec.note_id}", body, content_type="application/json", headers=h
        ).status_code
        == 200
    )
    set_org_settings(enabled, {"meeting.recording_enabled": True, "ai.edit_text": "deny"}, admin)
    r = client.patch(
        f"/api/notes/{rec.note_id}",
        {"version": 2, "body_md": "다시"},
        content_type="application/json",
        headers=h,
    )
    assert r.status_code == 403


def test_finalize_forbidden_for_mcp_and_allowed_for_human(
    client, enabled, admin, member, other, project
):
    rec = _rec(enabled, member)
    rec.status = "draft"
    rec.save()
    url = f"/api/notes/{rec.note_id}/finalize"
    r = client.post(
        url,
        {"project_id": project.pk},
        content_type="application/json",
        headers=_h(_token(member, ai=True)),
    )
    assert r.status_code == 403
    r = client.post(
        url,
        {"project_id": project.pk},
        content_type="application/json",
        headers=_h(_token(member, ai=False)),
    )
    assert r.status_code == 200 and r.json()["status"] == "final"
    rec.refresh_from_db()
    assert rec.status == "done"
    assert rec.note in visible_notes(other)


def test_finalize_blocked_while_recording(client, enabled, member):
    rec = _rec(enabled, member)
    r = client.post(
        f"/api/notes/{rec.note_id}/finalize",
        {},
        content_type="application/json",
        headers=_h(_token(member, ai=False)),
    )
    assert r.status_code == 400


# ---------- 설정: URL 규칙·키 암호화 ----------


@pytest.mark.parametrize(
    "url,ok",
    [
        ("", True),
        ("http://172.30.1.50:8000", True),
        ("http://192.168.0.10", True),
        ("http://10.1.2.3:9000/v1", True),
        ("https://stt.example.com", True),
        ("http://stt.example.com", False),
        ("http://8.8.8.8", False),
        ("http://localhost:8000", False),
        ("https://localhost", False),
        ("http://127.0.0.1:8000", False),
        ("http://169.254.169.254", False),
        ("https://169.254.169.254", False),
        ("http://web:8000", False),
        ("https://db", False),
        ("ftp://10.0.0.1", False),
        ("http://172.32.0.1", False),
    ],
)
def test_stt_url_rules(url, ok):
    assert (validate_stt_url(url) == "") is ok


def test_stt_url_rejected_on_save(client, enabled, admin):
    _, raw = ApiToken.issue(admin, "t", "write", for_ai=False)
    r = client.put(
        f"/api/orgs/{enabled.pk}/settings",
        {"meeting.recording_enabled": True, "meeting.stt_url": "http://web:8000"},
        content_type="application/json",
        headers=_h(raw),
    )
    assert r.status_code == 400


def test_api_key_encrypted_masked_everywhere(client, enabled, admin, member, bot):
    _, raw = ApiToken.issue(admin, "t", "write", for_ai=False)
    h = _h(raw)
    url = f"/api/orgs/{enabled.pk}/settings"
    payload = {
        "meeting.recording_enabled": True,
        "meeting.stt_url": "http://172.30.1.50:8000",
        "meeting.stt_api_key": KEY,
    }
    r = client.put(url, payload, content_type="application/json", headers=h)
    assert r.status_code == 200, r.content
    assert KEY not in r.content.decode()
    assert r.json()["values"]["meeting.stt_api_key"] == "설정됨"
    enabled.refresh_from_db()
    stored = enabled.settings["meeting.stt_api_key"]
    assert stored.startswith("enc:") and KEY not in json.dumps(enabled.settings)
    # 이력·봇 /orgs·웹 화면·내보내기에도 평문·암호문이 없다
    log = ChangeLog.objects.get(target_type="org", field="meeting.stt_api_key")
    assert (log.old_value, log.new_value) == ("미설정", "설정됨")
    orgs = bot("get", "/orgs").content.decode()
    assert KEY not in orgs and stored not in orgs
    client.force_login(admin)
    page = client.get(f"/orgs/{enabled.pk}/settings").content.decode()
    assert KEY not in page and stored not in page
    admin.is_staff = admin.is_superuser = True
    admin.save()
    export = client.post(
        "/ops/export.json", {"reason": "비밀값 점검 내보내기", "confirm": "export"}
    ).content.decode()
    assert KEY not in export and stored[4:] not in export
    # GET 값을 그대로 되돌려 PUT해도 유지된다
    values = client.get(url, headers=h).json()["values"]
    client.put(url, values, content_type="application/json", headers=h)
    enabled.refresh_from_db()
    assert enabled.settings["meeting.stt_api_key"] == stored
    # 봇 API만 평문을 받는다
    check = bot("post", "/meetings/check", {"discord_user_id": "111", "guild_id": "g1"}).json()
    assert check["stt"] == {
        "url": "http://172.30.1.50:8000",
        "model": "",
        "timeout_s": 120,
        "api_key": KEY,
    }
    # False는 지운다
    client.put(
        url, {**payload, "meeting.stt_api_key": False}, content_type="application/json", headers=h
    )
    enabled.refresh_from_db()
    assert "meeting.stt_api_key" not in enabled.settings


def test_web_form_blank_keeps_key_and_clear_removes(client, enabled, admin):
    set_org_settings(
        enabled, {"meeting.recording_enabled": True, "meeting.stt_api_key": KEY}, admin
    )
    enabled.refresh_from_db()
    stored = enabled.settings["meeting.stt_api_key"]
    client.force_login(admin)
    form = {"meeting.recording_enabled": "on", "meeting.stt_api_key": ""}
    client.post(f"/orgs/{enabled.pk}/settings", form)
    enabled.refresh_from_db()
    assert enabled.settings["meeting.stt_api_key"] == stored
    client.post(f"/orgs/{enabled.pk}/settings", {**form, "clear__meeting.stt_api_key": "on"})
    enabled.refresh_from_db()
    assert "meeting.stt_api_key" not in enabled.settings


def test_key_needs_credential_key(settings, enabled, admin):
    from common.errors import ServiceError

    settings.CREDENTIAL_KEY = ""
    with pytest.raises(ServiceError):
        set_org_settings(enabled, {"meeting.stt_api_key": KEY}, admin)


def test_ai_change_request_never_stores_plaintext_key(client, enabled, admin):
    from orgs.models import ChangeRequest

    _, raw = ApiToken.issue(admin, "ai", "write")  # AI용
    r = client.put(
        f"/api/orgs/{enabled.pk}/settings?reason=test",
        {"meeting.recording_enabled": True, "ai.create_task": "deny", "meeting.stt_api_key": KEY},
        content_type="application/json",
        headers=_h(raw),
    )
    assert r.status_code == 202, r.content
    assert KEY not in json.dumps(ChangeRequest.objects.get().proposed, ensure_ascii=False)


def test_web_note_shows_host_and_participants(client, enabled, member, other, bot):
    rec = _rec(enabled, member, title="웹 회의")
    bot("patch", f"/meetings/{rec.pk}", {"participants": PARTS})
    client.force_login(member)
    page = client.get(f"/orgs/{enabled.pk}/notes?note={rec.note_id}").content.decode()
    assert "진행자" in page and "참여자" in page and "다른팀원" in page


# ---------- /회의받기 (넘겨받기 요청) ----------


def _ask(bot, rec, who, parts=PARTS):
    return bot(
        "post",
        f"/meetings/{rec.pk}/host-requests",
        {"discord_user_id": who, "participants": parts},
    )


def _answer(bot, rec, req_id, who, approve):
    return bot(
        "post",
        f"/meetings/{rec.pk}/host-requests/{req_id}",
        {"discord_user_id": who, "approve": approve},
    )


def test_host_request_approve(enabled, member, other, bot):
    rec = _rec(enabled, member)
    r = _ask(bot, rec, "333")
    assert r.status_code == 200, r.content
    body = r.json()
    assert body["texts"]["mention"].startswith("<@111> 님, 다른팀원님이 넘겨받기 요청을")
    assert (body["texts"]["approve_label"], body["texts"]["reject_label"]) == ("승인", "거절")
    rid = body["request"]["id"]
    ok = _answer(bot, rec, rid, "111", True)
    assert ok.status_code == 200, ok.content
    assert ok.json()["texts"]["channel_notice"] == (
        "회의 진행자가 팀원님에서 다른팀원님으로 바뀌었습니다."
    )
    rec.refresh_from_db()
    assert rec.host == other and rec.host_requests[0]["status"] == "approved"
    assert len(rec.host_changes) == 1
    assert _answer(bot, rec, rid, "111", True).status_code == 400  # 이미 응답


def test_host_request_reject_and_only_host_answers(enabled, member, other, linked_admin, bot):
    rec = _rec(enabled, member)
    parts = [*PARTS, {"discord_user_id": "222", "discord_name": "관"}]
    rid = _ask(bot, rec, "333", parts).json()["request"]["id"]
    for who in ("333", "222"):  # 요청자 본인·관리자도 진행자가 아니면 못 누른다
        r = _answer(bot, rec, rid, who, True)
        assert r.status_code == 403
        assert r.json()["detail"]["meeting"].startswith("지금 회의 진행자만")
    r = _answer(bot, rec, rid, "111", False)
    assert r.json()["texts"]["requester_notice"] == "팀원님이 넘겨받기 요청을 거절했습니다."
    rec.refresh_from_db()
    assert rec.host == member and rec.host_requests[0]["status"] == "rejected"


def test_host_request_expires(enabled, member, other, bot):
    rec = _rec(enabled, member)
    rid = _ask(bot, rec, "333").json()["request"]["id"]
    rec.refresh_from_db()
    rec.host_requests[0]["expires_at"] = "2000-01-01T00:00:00+00:00"
    rec.save()
    r = _answer(bot, rec, rid, "111", True)
    assert r.status_code == 400 and "2분 안에 응답이 없어" in r.json()["detail"]["meeting"]
    rec.refresh_from_db()
    assert rec.host == member and rec.host_requests[0]["status"] == "expired"
    assert _ask(bot, rec, "333").status_code == 200  # 만료된 뒤에는 새로 요청할 수 있다


def test_host_request_one_pending_and_not_by_host(enabled, member, other, linked_admin, bot):
    rec = _rec(enabled, member)
    parts = [*PARTS, {"discord_user_id": "222", "discord_name": "관"}]
    assert _ask(bot, rec, "111", parts).status_code == 400  # 진행자 본인
    assert _ask(bot, rec, "555", parts).status_code == 400  # 계정 미연결
    assert _ask(bot, rec, "333", parts).status_code == 200
    r = _ask(bot, rec, "222", parts)
    assert r.status_code == 400 and "이미 대기 중인" in r.json()["detail"]["meeting"]


def test_host_request_cancelled_on_host_change_and_end(enabled, member, other, linked_admin, bot):
    parts = [*PARTS, {"discord_user_id": "222", "discord_name": "관"}]
    rec = _rec(enabled, member)
    rid = _ask(bot, rec, "222", parts).json()["request"]["id"]
    _host_to(bot, rec, "111", "333", parts)  # 진행자 변경
    r = _answer(bot, rec, rid, "333", True)
    assert r.status_code == 400 and "취소되었습니다" in r.json()["detail"]["meeting"]
    rec.refresh_from_db()
    assert rec.host_requests[0]["status"] == "cancelled"
    rid2 = _ask(bot, rec, "222", parts).json()["request"]["id"]
    bot("patch", f"/meetings/{rec.pk}", {"status": "transcribing"})  # 회의 종료
    rec.refresh_from_db()
    assert rec.host_requests[-1]["status"] == "cancelled"
    assert _answer(bot, rec, rid2, "333", True).status_code == 400
