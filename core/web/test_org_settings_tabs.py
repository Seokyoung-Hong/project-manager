"""IMPL-PLAN-14 B 갈래: 설정 셸·탭 이동·권한·내 정보·옛 주소·조직 메뉴."""

import pytest
from django.test import override_settings

from accounts.models import User
from orgs.member_info import admin_save, set_definition
from orgs.models import Organization, OrgMembership
from orgs.services import set_locks, set_org_settings
from orgs.settings import LOCKED, SPECS

pytestmark = pytest.mark.django_db

PHONE = {"label": "연락처", "kind": "text", "required": True}
HIDDEN = "notify.team_channel_weekly"


def _m(org, user):
    return OrgMembership.objects.select_related("org", "user").get(org=org, user=user)


def _fid(org):
    org.refresh_from_db()
    return org.member_fields["fields"][0]["id"]


def _url(org, tab=None):
    return f"/orgs/{org.pk}/settings" + (f"?tab={tab}" if tab else "")


def test_member_sees_only_my_info(client, org, admin, member):
    set_org_settings(org, {"task.default_priority": 8}, admin)
    client.force_login(member)
    body = client.get(_url(org)).content.decode()
    assert f'action="/orgs/{org.pk}/member-info"' in body and 'name="real_name"' in body
    # 관리자 탭 링크·설정 값·이력이 없다(숨김이 아니라 응답에 없음)
    assert "?tab=work" not in body and "?tab=members" not in body and "?tab=org" not in body
    assert "setting-task.default_priority" not in body and "정책 변경 이력" not in body
    # 모르는 탭은 내 정보
    assert 'name="real_name"' in client.get(_url(org, "nope")).content.decode()


def test_member_admin_tab_redirects_and_post_403(client, org, admin, member):
    client.force_login(member)
    for tab in ("members", "work", "notify", "ai", "meeting", "integrations", "org"):
        r = client.get(_url(org, tab))
        assert r.status_code == 302 and r.url == _url(org, "me"), tab
        r = client.post(_url(org, tab), {"task.default_priority": "1"})
        assert r.status_code == 403, tab
    org.refresh_from_db()
    assert "task.default_priority" not in (org.settings or {})


def test_tab_save_keeps_other_tabs_values_locks_and_hidden(client, org, admin):
    set_org_settings(org, {"notify.review_nudge_days": 3, "task.default_priority": 8}, admin)
    notify_lock = next(
        k for k in ("notify.review_nudge_days", "notify.send_hour") if SPECS[k].overridable
    )
    set_locks(org, [notify_lock, "task.default_priority"], admin)
    Organization.objects.filter(pk=org.pk).update(
        settings={**Organization.objects.get(pk=org.pk).settings, HIDDEN: True}
    )
    client.force_login(admin)
    r = client.post(
        _url(org, "work"),
        {"task.default_priority": "3", "unlock__task.default_priority": "on"},
    )
    assert r.status_code == 302 and r.url == _url(org, "work")
    org.refresh_from_db()
    s = org.settings
    assert s["task.default_priority"] == 3 and "task.default_priority" not in s[LOCKED]
    assert s["notify.review_nudge_days"] == 3 and notify_lock in s[LOCKED] and s[HIDDEN] is True
    # 알림 탭 저장도 숨김 키 때문에 실패하지 않는다(tab_keys가 숨김을 거름)
    r = client.post(_url(org, "notify"), {"notify.review_nudge_days": "4"}, follow=True)
    org.refresh_from_db()
    assert org.settings["notify.review_nudge_days"] == 4 and org.settings[HIDDEN] is True
    assert "알림 설정을 저장했습니다" in r.content.decode()
    assert org.settings["task.default_priority"] == 3


def test_section_save_only_that_section(client, org, admin):
    set_org_settings(org, {"task.default_priority": 8}, admin)
    client.force_login(admin)
    r = client.post(_url(org, "members") + "&section=invites", {"org.invite_days": "3"})
    assert r.url == _url(org, "members") + "#settings-members-invites"
    org.refresh_from_db()
    assert org.settings["org.invite_days"] == 3 and org.settings["task.default_priority"] == 8
    # 키 없는 탭·전사 섹션은 이 폼으로 저장하지 않는다
    assert client.post(_url(org, "integrations")).status_code in (302, 404)
    assert client.post(_url(org, "meeting") + "&section=stt").status_code == 404
    assert client.post(_url(org, "me")).status_code == 404


def test_old_member_info_get_and_post(client, org, admin, member):
    set_definition(org, admin, fields=[PHONE])
    fid = _fid(org)
    client.force_login(member)
    r = client.get(f"/orgs/{org.pk}/member-info")
    assert r.status_code == 302 and r.url == _url(org, "me")
    # 옛 폼(v-*만): 실명·조직 표시 이름은 그대로, 막혀 있다 풀리면 조직 현황으로
    r = client.post(f"/orgs/{org.pk}/member-info", {f"v-{fid}": "010"})
    assert r.status_code == 302 and r.url == f"/orgs/{org.pk}"
    m = _m(org, member)
    assert m.info == {fid: "010"} and m.user.real_name == "김팀원"
    # 다시 저장하면 내 정보로
    r = client.post(f"/orgs/{org.pk}/member-info", {f"v-{fid}": "011", "nickname": "백엔드"})
    assert r.url == _url(org, "me")
    m.refresh_from_db()
    assert m.nickname == "백엔드" and m.info == {fid: "011"}


def test_me_save_is_atomic_and_keeps_input(client, org, admin, member):
    set_definition(org, admin, fields=[PHONE])
    fid = _fid(org)
    client.force_login(member)
    r = client.post(
        f"/orgs/{org.pk}/member-info",
        {"real_name": "김1", "nickname": "새이름", f"v-{fid}": ""},
    )
    body = r.content.decode()
    # 리다이렉트 없이 같은 탭을 다시 그리고, 입력을 보존하고, 아무것도 쓰지 않는다
    assert r.status_code == 200 and 'value="새이름"' in body and 'value="김1"' in body
    assert "외의 기호와 숫자는 사용할 수 없습니다" in body and "연락처을(를) 입력해 주세요." in body
    m = _m(org, member)
    assert m.user.real_name == "김팀원" and m.nickname == "" and not m.info
    client.post(
        f"/orgs/{org.pk}/member-info",
        {"real_name": "김새팀원", "nickname": "새이름", f"v-{fid}": "010"},
    )
    m = _m(org, member)
    assert m.user.real_name == "김새팀원" and m.nickname == "새이름" and m.info == {fid: "010"}


def test_me_hides_nickname_when_real_name_shown(client, org, admin, member):
    set_definition(org, admin, show_real_name=True)
    client.force_login(member)
    body = client.get(_url(org, "me")).content.decode()
    assert 'name="nickname"' not in body and "실명으로 표시합니다" in body
    assert "이 조직에서 표시되는 이름: <strong>김팀원</strong>" in body
    client.post(f"/orgs/{org.pk}/member-info", {"real_name": "김팀원", "nickname": "몰래"})
    assert _m(org, member).nickname == ""


def test_missing_real_name_goes_to_profile(client, org, member):
    User.objects.filter(pk=member.pk).update(real_name="")
    client.force_login(member)
    r = client.get(_url(org, "me"))
    assert r.status_code == 302 and r.url.startswith("/settings/profile")


@override_settings(GITHUB_ENABLED=True)
def test_blocked_admin_opens_members_but_not_integrations(client, org, admin):
    set_definition(org, admin, fields=[PHONE])
    client.force_login(admin)
    assert client.get(_url(org, "members")).status_code == 200
    r = client.get(_url(org, "integrations"))
    assert r.status_code == 302 and r.url == _url(org, "me")
    admin_save(_m(org, admin), admin, values={_fid(org): "010"})
    body = client.get(_url(org, "integrations")).content.decode()
    assert 'id="github"' in body


@override_settings(GITHUB_ENABLED=False, DISCORD_CLIENT_ID="")
def test_integrations_tab_hidden_when_off(client, org, admin):
    client.force_login(admin)
    assert "?tab=integrations" not in client.get(_url(org, "work")).content.decode()
    assert client.get(_url(org, "integrations")).url == _url(org, "me")


def test_history_shows_admin_member_info_edit(client, org, admin, member):
    set_definition(org, admin, fields=[{**PHONE, "required": False}])
    admin_save(_m(org, member), admin, values={_fid(org): "010"})
    client.force_login(admin)
    body = client.get(_url(org, "org")).content.decode()
    assert "구성원 정보 수정" in body and "010" not in body
    assert 'id="settings-org-danger"' in body


def test_org_menu_and_shell_links(client, org, admin, member):
    client.force_login(member)
    body = client.get(f"/orgs/{org.pk}").content.decode()
    assert f'href="/orgs/{org.pk}/settings"' in body
    for gone in ("/github", "/discord", "/member-info"):
        assert f"/orgs/{org.pk}{gone}" not in body
    client.force_login(admin)
    body = client.get(_url(org, "work")).content.decode()
    for tab in ("me", "members", "work", "notify", "ai", "meeting", "org"):
        assert f"?tab={tab}" in body
    assert 'class="settings-shell in-tab"' in body
    # 탭 없는 주소 = 모바일 설정 목록 화면
    assert 'class="settings-shell"' in client.get(_url(org)).content.decode()


def test_stt_save_keeps_other_tabs_and_hidden_key(client, org, admin, monkeypatch):
    """전사 서버 저장은 전사 키만 바꾼다 — 요청 전에 읽은 낡은 조직 객체로도 다른 탭 값을 되돌리지 않고,
    저장돼 있던 숨김 키 때문에 실패하지 않는다."""
    from web.views import transcribe

    stale = Organization.objects.get(pk=org.pk)
    set_org_settings(org, {"task.default_priority": 3}, admin)  # 그 사이 다른 탭 저장
    Organization.objects.filter(pk=org.pk).update(
        settings={**Organization.objects.get(pk=org.pk).settings, HIDDEN: True}
    )
    monkeypatch.setattr(transcribe, "_admin_org", lambda request, org_id: (stale, None))
    client.force_login(admin)
    client.post(f"/orgs/{org.pk}/transcribe/server", {"meeting.stt_timeout_s": "60"})
    org.refresh_from_db()
    assert org.settings["meeting.stt_timeout_s"] == 60
    assert org.settings["task.default_priority"] == 3 and org.settings[HIDDEN] is True


def test_member_fields_unknown_part_400(client, org, admin):
    client.force_login(admin)
    assert client.post(f"/orgs/{org.pk}/member-fields", {"part": "x"}).status_code == 400


def test_nickname_checks_latest_real_name_policy(org, admin, member):
    """요청 전에 읽은 멤버십(낡은 정의)으로도 그 사이 켜진 '실명으로 표시'를 지킨다 — 본인·관리자·옛 경로."""
    from common.errors import ServiceError
    from orgs.member_info import save_me
    from orgs.services import set_nickname

    stale = [_m(org, member) for _ in range(3)]
    set_definition(org, admin, show_real_name=True)
    for call in (
        lambda: save_me(stale[0], nickname="몰래"),
        lambda: admin_save(stale[1], admin, nickname="몰래"),
        lambda: set_nickname(stale[2], "몰래", member),
    ):
        with pytest.raises(ServiceError):
            call()
    assert _m(org, member).nickname == ""
