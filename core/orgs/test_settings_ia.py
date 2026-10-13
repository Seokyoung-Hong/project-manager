"""IMPL-PLAN-14 A0 계약: 탭 키 목록, 탭별 부분 저장(only=), 구성원 정보 서비스(save_me·admin_save·set_definition)."""

import pytest

from common.errors import ServiceError
from tasks.models import ChangeLog

from .member_info import admin_save, empty_counts, missing, save_me, set_definition
from .models import Organization, OrgMembership
from .names import display_for
from .services import add_pending_member, create_org, set_locks, set_org_settings
from .settings import ADMIN_TABS, LOCKED, ORG_TABS, SPECS, enforced, tab_keys

pytestmark = pytest.mark.django_db

HIDDEN = "notify.team_channel_weekly"
PHONE = {"label": "연락처", "kind": "text", "required": True}
MBTI = {"label": "MBTI", "kind": "choice", "choices": ["INTJ", "ENFP"]}


def _m(org, user):
    return OrgMembership.objects.select_related("org", "user").get(org=org, user=user)


def _fids(org):
    org.refresh_from_db()
    return [f["id"] for f in org.member_fields["fields"]]


# ---------- 탭 키 ----------


def test_org_tabs_cover_org_scope_exactly_once():
    keys = [k for _, _, secs in ORG_TABS for _, _, ks in secs for k in ks]
    org_scope = [k for k, s in SPECS.items() if s.scope == "org"]
    assert len(keys) == len(set(keys)) == len(org_scope) == 77
    assert set(keys) == set(org_scope)
    assert [t for t, _, _ in ORG_TABS][1:] == list(ADMIN_TABS) and ORG_TABS[0][0] == "me"


def test_tab_keys_skip_hidden():
    union = {k for t, _, _ in ORG_TABS for k in tab_keys(t)}
    assert len(union) == 76 and HIDDEN not in union
    assert HIDDEN not in tab_keys("notify", "weekly")
    assert tab_keys("members", "invites") == ("org.invite_days", "org.invite_max_uses")
    assert tab_keys("me") == () and tab_keys("nope") == () and tab_keys("work", "nope") == ()


# ---------- 부분 저장 ----------


def test_only_save_keeps_other_tabs_locks_and_hidden(org, admin):
    set_org_settings(org, {"task.default_priority": 8, "notify.review_nudge_days": 3}, admin)
    set_locks(org, ["task.default_priority", "meeting.glossary"], admin)
    # 숨김 키 값이 저장돼 있던 조직(옛 데이터) — clean()은 이 키를 거절한다
    Organization.objects.filter(pk=org.pk).update(
        settings={**Organization.objects.get(pk=org.pk).settings, HIDDEN: True}
    )
    org.refresh_from_db()
    before = ChangeLog.objects.count()

    # 알림 탭 저장: tab_keys가 숨김을 거르므로 성공해야 한다(회귀)
    stale = Organization.objects.get(pk=org.pk)
    new = set_org_settings(stale, {"notify.review_nudge_days": 5}, admin, only=tab_keys("notify"))
    assert new is not stale and new.settings["notify.review_nudge_days"] == 5
    s = Organization.objects.get(pk=org.pk).settings
    assert s["task.default_priority"] == 8  # 다른 탭 값
    assert s[HIDDEN] is True  # 숨김 키 값
    assert s[LOCKED] == ["meeting.glossary", "task.default_priority"]  # 잠금
    assert list(ChangeLog.objects.order_by("pk")[before:].values_list("field", flat=True)) == [
        "notify.review_nudge_days"
    ]

    # 잠금도 탭 키만: work 탭에서 잠금을 풀어도 meeting 잠금은 남는다
    new = set_org_settings(new, {"task.default_priority": 8}, admin, only=tab_keys("work"))
    new = set_locks(new, [], admin, only=tab_keys("work"))
    assert new.settings[LOCKED] == ["meeting.glossary"]
    assert new.settings["notify.review_nudge_days"] == 5

    # only 안인데 data에 없는 키는 기본값(키 없음), data의 only 밖 키는 무시
    new = set_org_settings(new, {"task.priority_cap": 7}, admin, only=tab_keys("work"))
    assert "task.default_priority" not in new.settings and "task.priority_cap" in new.settings
    new = set_org_settings(new, {"org.invite_days": 30}, admin, only=tab_keys("work"))
    assert "org.invite_days" not in new.settings


def test_only_save_requires_admin_and_validates(org, admin, member):
    with pytest.raises(ServiceError):
        set_org_settings(org, {"task.default_priority": 8}, member, only=tab_keys("work"))
    with pytest.raises(ServiceError):
        set_locks(org, [], member, only=tab_keys("work"))
    with pytest.raises(ServiceError):
        set_org_settings(org, {"task.default_priority": "x"}, admin, only=tab_keys("work"))


def test_only_none_is_full_replace(org, admin):
    set_org_settings(org, {"task.default_priority": 8}, admin)
    set_org_settings(org, {"notify.review_nudge_days": 3}, admin)
    assert "task.default_priority" not in Organization.objects.get(pk=org.pk).settings


def test_enforced_hides_server_urls(org, admin):
    set_org_settings(
        org, {"meeting.stt_url": "http://10.0.0.5:8000", "task.default_priority": 8}, admin
    )
    keys = {r["key"] for r in enforced(org)}
    assert "task.default_priority" in keys and "meeting.stt_url" not in keys


# ---------- 구성원 정보 정의 ----------


def test_set_definition_partial_and_legacy_call(org, admin, member):
    with pytest.raises(ServiceError):
        set_definition(org, member, fields=[PHONE])
    set_definition(org, admin, show_real_name=False, fields=[PHONE])
    set_definition(org, admin, show_real_name=True)
    org.refresh_from_db()
    assert org.member_fields["show_real_name"] is True
    assert [f["label"] for f in org.member_fields["fields"]] == ["연락처"]
    set_definition(org, admin, fields=[PHONE, MBTI])
    org.refresh_from_db()
    assert org.member_fields["show_real_name"] is True
    assert [f["label"] for f in org.member_fields["fields"]] == ["연락처", "MBTI"]


# ---------- 내 정보 저장 ----------


def test_save_me_atomic_and_none_keeps(org, admin, member):
    set_definition(org, admin, fields=[PHONE, MBTI])
    pid, mid = _fids(org)
    m = _m(org, member)
    with pytest.raises(ServiceError) as e:
        save_me(m, real_name="", nickname="1234", values={pid: "", mid: "XXXX"})
    assert set(e.value.errors) == {"real_name", "nickname", pid, mid}
    with pytest.raises(ServiceError):  # 실명만 틀려도 나머지를 쓰지 않는다
        save_me(m, real_name="", nickname="석영", values={pid: "010"})
    m = _m(org, member)
    assert m.user.real_name == "김팀원" and m.nickname == "" and m.info == {}

    save_me(m, real_name="홍석영", nickname="석영", values={pid: "010", mid: "INTJ"})
    m = _m(org, member)
    assert (m.user.real_name, m.nickname, m.info) == ("홍석영", "석영", {pid: "010", mid: "INTJ"})
    assert not missing(m)
    save_me(m, values={pid: "011"})  # 안 보낸 실명·표시 이름은 그대로
    m = _m(org, member)
    assert (m.user.real_name, m.nickname, m.info) == ("홍석영", "석영", {pid: "011"})


def test_save_me_real_name_org_rejects_nickname_change(org, admin, member):
    set_definition(org, admin, show_real_name=True)
    m = _m(org, member)
    with pytest.raises(ServiceError) as e:
        save_me(m, nickname="딴이름")
    assert set(e.value.errors) == {"nickname"}
    save_me(m, nickname="", real_name="이팀원")  # 그대로인 값은 통과
    assert display_for(_m(org, member).user, org) == "이팀원"  # 실명 바꾸면 바로 반영


# ---------- 관리자 대리 수정 ----------


def test_admin_save_permissions_and_history(org, admin, member, outsider):
    set_definition(org, admin, fields=[PHONE, MBTI])
    pid, mid = _fids(org)
    m = _m(org, member)
    with pytest.raises(ServiceError):
        admin_save(m, member, values={pid: "010"})  # 비관리자
    other = create_org("다른 조직", "", outsider)
    with pytest.raises(ServiceError):
        admin_save(m, outsider, values={pid: "010"})  # 다른 조직 관리자
    assert other.pk  # 다른 조직 관리자라도 이 조직 멤버십은 못 고친다
    with pytest.raises(ServiceError):
        admin_save(m, admin, values={mid: "XXXX"})  # 선택지 검사는 한다

    admin_save(m, admin, values={mid: "ENFP"})  # 필수(연락처) 비움 허용
    assert missing(_m(org, member))
    log = ChangeLog.objects.get(target_type="org", target_id=org.pk, field="member_info")
    assert log.new_value == f"팀원({member.pk}): MBTI" and "ENFP" not in log.new_value
    assert log.actor == admin

    admin_save(_m(org, member), admin, nickname="석영", values={pid: "010-1234", mid: "ENFP"})
    m = _m(org, member)
    assert not missing(m) and m.nickname == "석영" and m.user.real_name == "김팀원"
    logs = ChangeLog.objects.filter(target_type="org", target_id=org.pk, field="member_info")
    assert logs.count() == 2 and "010-1234" not in logs.last().new_value
    assert ChangeLog.objects.filter(field="nickname", target_id=org.pk).count() == 1

    admin_save(m, admin, values={pid: "010-1234", mid: "ENFP"})  # 바뀐 것 없음 → 이력 없음
    assert logs.count() == 2


def test_empty_counts_skips_pending(org, admin, member):
    set_definition(org, admin, fields=[PHONE, MBTI])
    pid, mid = _fids(org)
    add_pending_member(org, admin, "가입전")
    save_me(_m(org, member), values={pid: "010"})
    assert empty_counts(org) == {
        pid: 1,
        mid: 2,
    }  # 관리자 1(둘 다 빔), 팀원 1(MBTI 빔), 가입 전 제외
