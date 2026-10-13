"""IMPL-PLAN-13 갈래 A: 표시 이름 규칙(names), 조직 표시 이름 서비스, 실명 검증, 실명 관문(웹·API)."""

import pytest
from django.template import Context, Template

from accounts.models import ApiToken, User
from accounts.services import clean_real_name, withdraw
from common.errors import Forbidden, ServiceError
from tasks.models import ChangeLog

from . import names
from .member_info import definition, set_definition
from .models import OrgMembership
from .services import add_pending_member, create_personal_invite, set_nickname

pytestmark = pytest.mark.django_db


def _m(org, user):
    return OrgMembership.objects.select_related("org", "user").get(org=org, user=user)


def _show(org, on: bool):
    org.member_fields = {"show_real_name": on, "fields": []}
    org.save(update_fields=["member_fields"])


@pytest.mark.parametrize(
    "show, real, nick, expected",
    [
        (False, "김팀원", "", "팀원"),
        (False, "김팀원", "별명", "별명"),
        (False, "", "별명", "별명"),
        (True, "김팀원", "별명", "김팀원"),  # 실명으로 표시: 별명은 무시(지우지 않는다)
        (True, "", "별명", "별명"),  # 실명이 아직 없으면 평소 규칙
        (True, "", "", "팀원"),
    ],
)
def test_display_rules(org, member, show, real, nick, expected):
    User.objects.filter(pk=member.pk).update(real_name=real)
    OrgMembership.objects.filter(org=org, user=member).update(nickname=nick)
    _show(org, show)
    member.refresh_from_db()
    assert names.display_for(member, org) == expected
    assert names.display_for(member, org.pk) == expected  # id도 받는다


def test_display_without_org_or_membership(org, member, outsider):
    OrgMembership.objects.filter(org=org, user=member).update(nickname="별명")
    assert names.display_for(None, org) == ""
    assert names.display_for(member) == "팀원"  # 조직 없는 자리 = 계정 표시 이름
    assert names.display_for(outsider, org) == "외부인"  # 구성원 아님(떠난 사람)
    withdraw(member, "pw12345678")
    member.refresh_from_db()
    assert names.display_for(member, org) == "탈퇴한 사용자" and member.real_name == ""


def test_legacy_definition_shape_still_reads(org, member):
    """0014 이전 모양(real_name: required)도 실명으로 표시로 읽는다 — 마이그레이션 전후에 안 깨진다."""
    org.member_fields = {"real_name": "required", "fields": []}
    org.save(update_fields=["member_fields"])
    assert definition(org) == {"show_real_name": True, "fields": []}
    assert names.display_for(member, org) == "김팀원"
    assert definition({"real_name": "optional"})["show_real_name"] is False
    assert org.member_info_on is False  # 탭·열은 추가 항목이 있을 때만


def test_request_cache_one_query_and_forget(org, admin, django_assert_num_queries):
    users = [admin] + [
        User.objects.create_user(f"u{i}", display_name=f"사람{i:02d}", real_name="실명")
        for i in range(30)
    ]
    for u in users[1:]:
        OrgMembership.objects.create(org=org, user=u)
    token = names._cache.set({})
    try:
        with django_assert_num_queries(1):
            got = [names.display_for(u, org) for u in users]
        assert got[1:] == [f"사람{i:02d}" for i in range(30)]
        assert [u.pk for u in names.sort_by_name(users[1:], org)] == [u.pk for u in users[1:]]
        set_nickname(_m(org, users[1]), "가나다", users[1])  # forget을 부른다
        assert names.display_for(users[1], org) == "가나다"
    finally:
        names._cache.reset(token)


def test_template_filter(org, member):
    OrgMembership.objects.filter(org=org, user=member).update(nickname="별명")
    t = Template("{% load names %}{{ u|name_in:org }}/{{ u|name_in:no_org }}")
    assert t.render(Context({"u": member, "org": org, "no_org": None})) == "별명/팀원"


def test_set_nickname_permissions(org, admin, member, outsider):
    m = _m(org, member)
    set_nickname(m, "  철수  ", member)  # 본인
    assert _m(org, member).nickname == "철수"
    set_nickname(m, "영희", admin, source="dc")  # 관리자
    log = ChangeLog.objects.filter(target_type="org", field="nickname").latest("pk")
    assert (log.old_value, log.new_value, log.source) == (
        f"철수({member.pk})",
        f"영희({member.pk})",
        "dc",
    )
    with pytest.raises(Forbidden):
        set_nickname(_m(org, admin), "x", member)  # 다른 구성원
    with pytest.raises(Forbidden):
        set_nickname(m, "x", outsider)
    with pytest.raises(ServiceError) as e:
        set_nickname(m, "user@1", member)
    assert "nickname" in e.value.errors
    set_nickname(m, "", member)  # 비우면 계정 표시 이름
    assert names.display_for(member, org) == "팀원"
    set_definition(org, True, [], admin)
    with pytest.raises(ServiceError):
        set_nickname(_m(org, member), "철수", member)  # 실명으로 표시 조직은 아무도 못 바꾼다
    with pytest.raises(ServiceError):
        set_nickname(_m(org, member), "철수", admin)


@pytest.mark.parametrize("raw", ["", "   ", "김1", "a@b", "<b>", "a/b", "a:b", "#x", "a\\b", "😀", "가\x00", "...", "가" * 51])  # fmt: skip
def test_clean_real_name_rejects(raw):
    with pytest.raises(ServiceError):
        clean_real_name(raw)


def test_clean_real_name_accepts():
    assert clean_real_name("  홍   길동 ") == "홍 길동"
    assert clean_real_name("김") == "김"
    assert clean_real_name("Jean-Luc O'Neil") == "Jean-Luc O'Neil"
    assert clean_real_name("마이클·조던") == "마이클·조던"
    assert clean_real_name("", required=False) == ""


# ---- 실명 관문 ----


def _no_real_name(user):
    User.objects.filter(pk=user.pk).update(real_name="")


def test_web_gate_sends_to_profile_with_next(client, org, member):
    _no_real_name(member)
    client.force_login(member)
    for path in (f"/orgs/{org.pk}", "/today", "/settings/tokens", "/orgs"):
        r = client.get(path)
        assert r.status_code == 302 and r["Location"].startswith("/settings/profile?next="), path
    assert client.get("/today?x=1")["Location"] == "/settings/profile?next=/today%3Fx%3D1"
    r = client.get(f"/orgs/{org.pk}", headers={"HX-Request": "true"})
    assert r.status_code == 204 and r["HX-Redirect"] == "/settings/profile"
    for path in ("/settings/profile", "/privacy", "/terms", "/settings/consents", "/settings/account"):  # fmt: skip
        assert client.get(path).status_code == 200, path
    User.objects.filter(pk=member.pk).update(real_name="김팀원")
    assert client.get(f"/orgs/{org.pk}").status_code == 200


def test_web_gate_does_not_read_user_on_rt(client, member, monkeypatch):
    """/rt/(SSE)·/api/는 경로로 먼저 거른다 — request.user를 읽지 않는다."""
    from django.contrib.auth import middleware

    _no_real_name(member)
    client.force_login(member)
    called = []
    real = middleware.get_user
    monkeypatch.setattr(middleware, "get_user", lambda r: called.append(r.path) or real(r))
    client.get("/rt/poll?since=0")
    assert "/rt/poll" not in called
    client.get("/today")
    assert "/today" in called  # 가로채기가 실제로 동작한다


def test_api_gate(client, api, org, member, task):
    _no_real_name(member)
    r = api.get(f"/api/tasks/{task.pk}")
    assert r.status_code == 403
    body = r.json()
    assert body["error"] == "real_name_required" and body["url"].endswith("/settings/profile")
    assert body["url"] in body["detail"]
    assert api.get("/api/me").status_code == 200  # 스킬이 안내를 띄우려면 읽어야 한다
    # 봇 경로(/api/integrations/)는 막지 않는다
    bot = User.objects.create_user("discord-bot", display_name="봇", real_name="봇")
    _, raw = ApiToken.issue(bot, "봇", "bot")
    r = client.post(
        f"/api/integrations/discord/tasks/{task.pk}/done",
        {"discord_user_id": "111"},
        content_type="application/json",
        headers={"Authorization": f"Bearer {raw}"},
    )
    assert r.status_code != 403
    # 세션(웹 브라우저) API도 같다
    client.force_login(member)
    assert client.get(f"/api/tasks/{task.pk}").json()["error"] == "real_name_required"


def test_claimed_and_github_accounts_hit_gate(client, org, admin):
    """가입 전 구성원 인계(GitHub 포함)·새 GitHub 가입은 실명이 비어 첫 화면에서 관문에 걸린다."""
    from github.services import login_with_github

    pending = add_pending_member(org, admin, "김신입")
    invite = create_personal_invite(pending, admin)
    identity, _ = login_with_github({"id": 777, "login": "kimgh"}, {}, claim=invite.token)
    new, _ = login_with_github({"id": 778, "login": "newgh", "name": "새사람"}, {})
    for user in (identity.user, new.user):
        assert user.real_name == ""  # GitHub name으로 미리 채우지 않는다
        client.force_login(user)
        assert client.get(f"/orgs/{org.pk}")["Location"].startswith("/settings/profile")
