"""설정 → 구성원 관리 탭(IMPL-PLAN-14 §8, C 갈래).

설정 셸(B)과 member_profile 경로(B의 web/urls.py)가 붙기 전에도 돌도록, 이 모듈이 시험용 urlconf를 겸한다:
web.urls 전체 + member_profile + 탭 본문만 그리는 시험 화면. 통합 뒤엔 시험 화면 대신 settings?tab=members로 바꿔도 된다.
"""

import pytest
from django.shortcuts import render
from django.urls import path

from accounts.models import User
from orgs import member_info
from orgs.member_info import set_definition
from orgs.models import Invite, OrgMembership
from orgs.services import add_pending_member, create_org
from tasks.models import ChangeLog
from web import urls as web_urls

from .views.common import org_or_404
from .views.org_members import member_profile, members_ctx


def _members_page(request, org_id):
    org = org_or_404(request.user, org_id)
    return render(
        request,
        "orgs/settings/_members.html",
        {"org": org, **members_ctx(request, org, request.GET.get("member"))},
    )


urlpatterns = [
    path("t/orgs/<int:org_id>/members", _members_page),
    path("orgs/memberships/<int:membership_id>/profile", member_profile, name="member_profile"),
    *web_urls.urlpatterns,
]

pytestmark = [pytest.mark.django_db, pytest.mark.urls(__name__)]

PHONE = {"label": "연락처", "kind": "text", "required": False, "help": "", "choices": []}
YEAR = {"label": "학년", "kind": "choice", "required": True, "choices": ["1", "2"]}


def _m(org, user):
    return OrgMembership.objects.select_related("org", "user").get(org=org, user=user)


def _fid(org, label):
    org.refresh_from_db()
    return next(f["id"] for f in org.member_fields["fields"] if f["label"] == label)


def _page(client, org, member=None):
    url = f"/t/orgs/{org.pk}/members" + (f"?member={member}" if member else "")
    return client.get(url)


def test_list_and_panel_admin_only(client, org, admin, member, outsider):
    m = _m(org, member)
    client.force_login(admin)
    body = _page(client, org).content.decode()
    assert f"?tab=members&amp;member={m.pk}" in body and 'aria-label="구성원 패널"' not in body
    body = _page(client, org, m.pk).content.decode()
    assert 'aria-label="구성원 패널"' in body and f"/orgs/memberships/{m.pk}/profile" in body
    # 다른 조직 구성원은 404
    other = create_org("다른 조직", "", outsider)
    om = _m(other, outsider)
    assert _page(client, org, om.pk).status_code == 404
    assert _page(client, org, "x").status_code == 404
    # 비관리자는 탭 맥락 자체를 못 만든다
    client.force_login(member)
    assert _page(client, org).status_code == 403


def test_panel_save_only_org_values(client, org, admin, member):
    set_definition(org, admin, fields=[PHONE])
    pid = _fid(org, "연락처")
    m = _m(org, member)
    before = User.objects.get(pk=member.pk)
    client.force_login(admin)
    r = client.post(
        f"/orgs/memberships/{m.pk}/profile",
        {
            "nickname": "백엔드 김",
            f"v-{pid}": "010-1234",
            "real_name": "바꿈",
            "display_name": "바꿈",
            "username": "hacked",
        },
    )
    assert r.status_code == 302 and r["Location"].endswith(f"?tab=members&member={m.pk}")
    m.refresh_from_db()
    after = User.objects.get(pk=member.pk)
    assert m.nickname == "백엔드 김" and m.info == {pid: "010-1234"}
    assert (after.real_name, after.display_name, after.username) == (
        before.real_name,
        before.display_name,
        before.username,
    )
    # 감사 이력: 항목 이름만, 값 없음
    log = ChangeLog.objects.get(target_type="org", target_id=org.pk, field="member_info")
    assert "연락처" in log.new_value and "010-1234" not in log.new_value + log.old_value


def test_panel_post_forbidden_and_other_org(client, org, admin, member, outsider):
    m = _m(org, admin)
    client.force_login(member)
    assert client.post(f"/orgs/memberships/{m.pk}/profile", {"nickname": "x"}).status_code == 403
    other = create_org("다른 조직", "", outsider)
    om = _m(other, outsider)
    client.force_login(admin)
    assert client.post(f"/orgs/memberships/{om.pk}/profile", {"nickname": "x"}).status_code == 404
    om.refresh_from_db()
    assert om.nickname != "x"


def test_real_name_org_hides_and_rejects_nickname(client, org, admin, member):
    m = _m(org, member)
    set_definition(org, admin, show_real_name=True)
    client.force_login(admin)
    body = _page(client, org, m.pk).content.decode()
    assert 'name="nickname"' not in body
    client.post(f"/orgs/memberships/{m.pk}/profile", {"nickname": "다른 이름"})
    m.refresh_from_db()
    assert m.nickname != "다른 이름"


def test_panel_admin_can_leave_required_empty_and_unblock(client, org, admin, member):
    set_definition(org, admin, fields=[YEAR])
    yid = _fid(org, "학년")
    member_info.save(
        _m(org, admin), {yid: "1"}
    )  # 관리자 본인이 막혀 있으면 패널 저장도 관문에 걸린다(§6)
    m = _m(org, member)
    assert member_info.missing(m)
    client.force_login(admin)
    r = client.post(f"/orgs/memberships/{m.pk}/profile", {f"v-{yid}": ""}, follow=False)
    assert r.status_code == 302
    client.post(f"/orgs/memberships/{m.pk}/profile", {f"v-{yid}": "2"})
    assert not member_info.missing(_m(org, member))


def test_fields_editor_cards_preview_and_impact(client, org, admin, member, monkeypatch):
    set_definition(org, admin, fields=[PHONE])
    client.force_login(admin)
    body = _page(client, org).content.decode()
    assert 'class="field-card' in body and "member-fields-table" not in body
    assert "구성원에게 보이는 모습" in body and "disabled" in body
    assert "예: 학번" in body and "예: 가능한 시간" in body  # 형식별 설명·예시
    # 관리자·구성원 둘 다 비워 둠
    assert "지금 2명이 비워 두었습니다" in body
    # 필수 아닌 항목: 차단 경고(impact-on)와 중립 정보(impact-off)를 함께 그리고 CSS가 필수 체크로 고른다
    assert "impact-on" in body and "필수가 아니라 조직 사용에는 영향이 없습니다" in body
    assert "지금 0명이 입력했습니다" in body
    assert "member-fields.js" in body and "data-field-preview" in body  # 편집 중 초안 미리보기
    assert 'data-label="역할"' in body and 'class="names-effect"' in body
    assert 'data-confirm-if="[data-was-optional]:checked"' in body
    assert 'name="part" value="fields"' in body and 'name="part" value="names"' in body

    def boom(org):
        raise RuntimeError

    monkeypatch.setattr(member_info, "empty_counts", boom)
    r = _page(client, org)
    assert r.status_code == 200 and "비워 두었습니다" not in r.content.decode()


def test_pending_and_invites_moved_here(client, org, admin):
    pending = add_pending_member(org, admin, "김신입")
    client.force_login(admin)
    body = _page(client, org).content.decode()
    assert "가입 전" in body and "초대 링크가 없습니다." in body
    assert "GitHub 조직에도 초대" not in body  # 앱 설치 없는 조직
    assert f"/orgs/{org.pk}/settings?tab=members&amp;section=invites" in body
    assert "초대 링크 만료(일)" in body and "팀 자율 참여" in body
    client.post(f"/orgs/memberships/{pending.pk}/invite")
    invite = Invite.objects.get(for_user=pending.user)
    body = _page(client, org, pending.pk).content.decode()
    assert invite.path in body
    assert "초대 링크가 없습니다." in body  # 사람별 링크는 조직 초대 링크 표에 섞이지 않는다
    assert "가입한 뒤 바로 이 조직에 참여합니다" in body


def test_real_name_shown_to_admin_in_list(client, org, admin, member, outsider):
    OrgMembership.objects.create(org=org, user=outsider, role="member")
    User.objects.filter(pk=outsider.pk).update(real_name="")
    client.force_login(admin)
    body = _page(client, org).content.decode()
    assert "김팀원" in body and "실명 미입력" in body
    assert "연결됨" in body  # member 픽스처는 Discord 연결이 끝난 상태다


def test_teams_screen_has_no_member_table(client, org, admin):
    client.force_login(admin)
    body = client.get(f"/orgs/{org.pk}/teams").content.decode()
    assert "member-table" not in body and "#member-info" not in body
    assert "초대 링크 만들기" not in body
    assert f"/orgs/{org.pk}/settings?tab=members#settings-members-names" in body
