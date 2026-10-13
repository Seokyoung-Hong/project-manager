"""IMPL-PLAN-13 갈래 E — 가입·프로필 실명, 조직 표시 이름 편집, 실명으로 표시 옵션, 관리자 구성원 목록 실명."""

from accounts.models import User
from orgs.models import OrgMembership
from orgs.names import display_for
from tasks.models import ChangeLog

PW = "verysecret123"


def _signup(client, **extra):
    data = {"username": "newbie", "display_name": "새사람", "password1": PW, "password2": PW}
    return client.post("/signup", {**data, "age_ok": "on", **extra})


def test_signup_requires_valid_real_name(client, db):
    r = _signup(client)
    assert r.status_code == 200 and "실명을 입력해 주세요." in r.content.decode()
    r = _signup(client, real_name="김1")
    assert r.status_code == 200 and "외의 기호와 숫자는 사용할 수 없습니다" in r.content.decode()
    assert not User.objects.filter(username="newbie").exists()
    assert _signup(client, real_name="  김  새사람 ").status_code == 302
    assert User.objects.get(username="newbie").real_name == "김 새사람"


def test_gate_profile_saves_and_returns_to_next(client, org, member):
    User.objects.filter(pk=member.pk).update(real_name="")
    client.force_login(member)
    nxt = f"/orgs/{org.pk}"
    page = client.get(f"/settings/profile?next={nxt}").content.decode()
    assert "이전 화면으로 이동합니다" in page and f'value="{nxt}"' in page
    assert "이전 화면으로 이동합니다" not in client.get("/settings/profile").content.decode()
    r = client.post(
        "/settings/profile", {"real_name": "김팀원", "display_name": "팀원", "next": nxt}
    )
    assert r.status_code == 302 and r["Location"] == nxt
    # 외부 주소는 무시하고 프로필로
    r = client.post(
        "/settings/profile",
        {"real_name": "김팀원", "display_name": "팀원", "next": "https://evil.example/"},
    )
    assert r["Location"] == "/settings/profile"


def test_profile_candidates_pick_and_clear(client, member):
    member.real_name = ""
    member.settings = {"real_name_candidates": ["김가", "김나"]}
    member.save()
    client.force_login(member)
    page = client.get("/settings/profile").content.decode()
    # 후보 버튼은 별도 폼(pick-real-name)을 제출한다 — 본 폼의 빈 실명 칸 HTML 검증에 막히지 않는다
    assert 'form="pick-real-name" name="real_name" value="김나"' in page
    assert (
        "{#" not in page
        and 'id="pick-real-name"' in page
        and 'name="display_name" value="팀원"' in page
    )
    # 후보 폼이 실제로 보내는 값 그대로
    client.post("/settings/profile", {"real_name": "김나", "display_name": "팀원", "next": ""})
    member.refresh_from_db()
    assert member.real_name == "김나" and "real_name_candidates" not in member.settings


def test_profile_real_name_change_shows_in_real_name_org(client, org, admin, member):
    client.force_login(admin)
    client.post(f"/orgs/{org.pk}/member-fields", {"show_real_name": "on"})
    assert ChangeLog.objects.filter(
        target_id=org.pk, field="member_fields", new_value__contains="실명 표시: 켜짐"
    ).exists()
    client.force_login(member)
    client.post("/settings/profile", {"real_name": "이바뀜", "display_name": "팀원"})
    member.refresh_from_db()
    assert display_for(member, org) == "이바뀜"


def test_admin_member_list_shows_real_name_and_edits_nickname(client, org, admin, member, outsider):
    OrgMembership.objects.create(org=org, user=outsider, role="member")
    User.objects.filter(pk=outsider.pk).update(real_name="")
    client.force_login(admin)
    # 화면(실명 열람·실명 표시 조직의 칸 없음)은 설정 → 구성원 관리로 옮겼다 — web/test_org_members.py
    m = OrgMembership.objects.get(org=org, user=member)
    client.post(f"/orgs/memberships/{m.pk}/nickname", {"nickname": "백엔드 팀원"})
    m.refresh_from_db()
    assert m.nickname == "백엔드 팀원" and display_for(member, org) == "백엔드 팀원"
    # 실명으로 표시 조직: 저장은 거절
    client.post(f"/orgs/{org.pk}/member-fields", {"show_real_name": "on"})
    client.post(f"/orgs/memberships/{m.pk}/nickname", {"nickname": "다른 이름"})
    m.refresh_from_db()
    assert m.nickname == "백엔드 팀원"


def test_member_screens_hide_real_name_and_self_nickname(client, org, admin, member):
    client.force_login(member)
    # 일반 구성원 화면(팀 목록)에는 관리자 실명이 안 나온다
    assert "김관리" not in client.get(f"/orgs/{org.pk}/teams").content.decode()
    # 내 정보: 본인 실명은 본인이 고치는 칸(D1), 관리자 실명은 없다
    page = client.get(f"/orgs/{org.pk}/settings?tab=me").content.decode()
    assert 'name="nickname"' in page and 'value="김팀원"' in page and "김관리" not in page
    m = OrgMembership.objects.get(org=org, user=member)
    r = client.post(
        f"/orgs/memberships/{m.pk}/nickname",
        {"nickname": "백엔드 김", "next": f"/orgs/{org.pk}/settings?tab=me"},
    )
    assert r["Location"] == f"/orgs/{org.pk}/settings?tab=me"
    m.refresh_from_db()
    assert m.nickname == "백엔드 김"
    # 남의 표시 이름은 못 바꾼다
    am = OrgMembership.objects.get(org=org, user=admin)
    client.post(f"/orgs/memberships/{am.pk}/nickname", {"nickname": "가짜"})
    am.refresh_from_db()
    assert am.nickname == ""
