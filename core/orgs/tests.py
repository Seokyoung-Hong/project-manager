import pytest
from django.utils import timezone

from accounts.models import ApiToken, User
from common.errors import ServiceError

from .models import OrgMembership
from .services import (
    add_team_member,
    change_role,
    create_invite,
    create_org,
    create_team,
    delete_team,
    is_admin,
    is_member,
    join_by_token,
    remove_member,
    remove_team_member,
    revoke_invite,
    set_locks,
    set_org_settings,
    set_tags,
    teams_of,
)

pytestmark = pytest.mark.django_db


def test_create_org_makes_creator_admin(org, admin):
    assert is_admin(admin, org)


def test_join_by_token_creates_membership_and_counts(org, admin, outsider):
    invite = create_invite(org, admin)
    join_by_token(outsider, invite.token)
    invite.refresh_from_db()
    assert is_member(outsider, org)
    assert invite.use_count == 1
    join_by_token(outsider, invite.token)
    invite.refresh_from_db()
    assert invite.use_count == 1


def test_join_expired_or_revoked_invite_rejected(org, admin, outsider):
    expired = create_invite(org, admin)
    expired.expires_at = timezone.now() - timezone.timedelta(days=1)
    expired.save(update_fields=["expires_at"])
    with pytest.raises(ServiceError):
        join_by_token(outsider, expired.token)

    revoked = create_invite(org, admin)
    revoke_invite(revoked, admin)
    with pytest.raises(ServiceError):
        join_by_token(outsider, revoked.token)


def test_member_cannot_create_invite(org, member):
    with pytest.raises(ServiceError):
        create_invite(org, member)


def test_cannot_demote_last_admin(org, admin):
    membership = OrgMembership.objects.get(org=org, user=admin)
    with pytest.raises(ServiceError):
        change_role(membership, "member", admin)


def test_outsider_cannot_see_org_data_via_api(client, org, project, task, outsider):
    _, raw = ApiToken.issue(outsider, "o", "read")
    h = {"Authorization": f"Bearer {raw}"}
    assert client.get(f"/api/orgs/{org.pk}", headers=h).status_code == 404
    assert client.get("/api/tasks", headers=h).json()["total"] == 0
    assert client.get("/api/projects", headers=h).json() == []


def test_outsider_cannot_open_project_page(client, project, outsider):
    client.login(username="outsider", password="pw12345678")
    assert client.get(f"/projects/{project.pk}").status_code == 404


def test_join_page_names_org_before_login_then_joins(client, org, admin, outsider):
    invite = create_invite(org, admin)
    # 로그인 전에도 어느 조직 초대인지는 보여 준다 — 맨몸 로그인 화면은 링크의 뜻을 잃는다
    r = client.get(f"/join/{invite.token}")
    assert r.status_code == 200
    assert org.name in r.content.decode()
    # 로그인 전 POST로는 참여되지 않는다
    assert client.post(f"/join/{invite.token}").status_code == 200
    assert not OrgMembership.objects.filter(org=org, user=outsider).exists()
    client.login(username="outsider", password="pw12345678")
    r = client.post(f"/join/{invite.token}")
    assert r.status_code == 302
    assert r.headers["Location"] == "/today"
    assert OrgMembership.objects.filter(org=org, user=outsider).exists()


# ---------- 팀 ----------


def test_team_member_must_be_org_member(org, admin, outsider):
    t = create_team(org=org, name="프론트엔드", actor=admin)
    with pytest.raises(ServiceError):
        add_team_member(t, outsider, admin)


def test_user_in_multiple_teams(team, org, admin, member):
    other = create_team(org=org, name="프론트엔드", actor=admin)
    add_team_member(other, member, admin)
    names = set(teams_of(member, org).values_list("name", flat=True))
    assert names == {team.name, other.name}


def test_team_name_unique_per_org(org, admin):
    create_team(org=org, name="디자인", actor=admin)
    with pytest.raises(ServiceError):
        create_team(org=org, name="디자인", actor=admin)
    other_org = create_org("다른 조직", "", admin)
    create_team(org=other_org, name="디자인", actor=admin)  # 다른 조직에는 된다


def test_remove_org_member_clears_team_memberships(org, team, admin, member):
    membership = OrgMembership.objects.get(org=org, user=member)
    remove_member(membership, admin)
    assert member not in team.members.all()


def test_delete_team_keeps_members_and_projects(org, team, project, admin, member):
    delete_team(team, actor=admin)
    assert is_member(member, org)
    assert project.pk is not None


def test_team_does_not_limit_visibility(org, project, admin, member, task):
    """어느 팀에도 속하지 않은 조직 멤버가 모든 프로젝트의 태스크를 본다."""
    from tasks.services import visible_tasks

    assert visible_tasks(member).filter(pk=task.pk).exists()


def test_project_teams_must_be_same_org(org, team, admin):
    from projects.services import create_project

    other_org = create_org("다른 조직", "", admin)
    other_team = create_team(org=other_org, name="백엔드", actor=admin)
    with pytest.raises(ServiceError):
        create_project(org=org, name="테스트", actor=admin, owners=[admin], teams=[other_team])


def test_project_teams_logged(org, team, project, admin):
    from projects.services import update_project
    from tasks.models import ChangeLog

    update_project(
        project, {"teams": [team]}, actor=admin, source="web", expected_version=project.version
    )
    assert ChangeLog.objects.filter(
        target_type="project", target_id=project.pk, field="teams"
    ).exists()


def test_org_status_counts_and_capacity(org, project, admin, member, task):
    from reports.services import org_status

    st = org_status(org)
    assert "doing" in st["counts"]
    assert "done" in st["counts"]
    assert "avg_doing" in st["counts"]
    admin_row = next(c for c in st["capacity"] if c["user"]["id"] == admin.pk)
    assert admin_row["open"] == 0


def test_capacity_verdict_thresholds(org, project, admin, member):
    from datetime import timedelta

    from common.dates import today_kst
    from reports.services import org_status
    from tasks.services import create_task, transition

    for i in range(4):
        t = create_task(
            project=project,
            title=f"태스크 {i}",
            actor=admin,
            source="web",
            assignee=member,
            due_date=today_kst() + timedelta(days=3),
        )
        transition(t, "doing", actor=admin, source="web", expected_version=t.version)
    st = org_status(org)
    row = next(c for c in st["capacity"] if c["user"]["id"] == member.pk)
    assert row["verdict"] == "과부하"


def test_set_tags_admin_only_and_cleans(org, admin, member):
    membership = OrgMembership.objects.get(org=org, user=member)
    with pytest.raises(ServiceError):
        set_tags(membership, ["파이썬"], member)
    set_tags(membership, [" 파이썬 ", "파이썬", "", "장고"] + [f"t{i}" for i in range(10)], admin)
    membership.refresh_from_db()
    assert membership.tags[:2] == ["파이썬", "장고"]
    assert len(membership.tags) == 10


def test_team_endpoints_in_api(client, org, team, admin):
    _, raw = ApiToken.issue(admin, "a", "read")
    h = {"Authorization": f"Bearer {raw}"}
    r = client.get(f"/api/orgs/{org.pk}/teams", headers=h)
    assert r.status_code == 200
    names = [t["name"] for t in r.json()]
    assert team.name in names


def test_remove_team_member_only_removes_team(org, team, admin, member):
    remove_team_member(team, member, admin)
    assert member not in team.members.all()
    assert is_member(member, org)


# ---------- 거버넌스 ----------


def test_governance_defaults_and_override(org, admin, member):
    from .governance import DEFAULT_GOVERNANCE, governance_text
    from .services import set_governance

    assert governance_text(org) == DEFAULT_GOVERNANCE
    set_governance(org, "# 우리 규칙\n- 기한은 금요일", admin)
    org.refresh_from_db()
    assert governance_text(org).startswith("# 우리 규칙")
    # 비우면 기본안으로 되돌아간다.
    set_governance(org, "  ", admin)
    org.refresh_from_db()
    assert governance_text(org) == DEFAULT_GOVERNANCE
    with pytest.raises(ServiceError):
        set_governance(org, "x", member)
    with pytest.raises(ServiceError):
        set_governance(org, "x" * 20001, admin)


def test_governance_api_read_and_write(client, org, admin, member):
    _, raw = ApiToken.issue(admin, "a", "write", for_ai=False)
    _, member_raw = ApiToken.issue(member, "m", "write", for_ai=False)
    h = {"Authorization": f"Bearer {raw}"}
    r = client.get(f"/api/orgs/{org.pk}/governance", headers=h)
    assert r.status_code == 200 and r.json()["is_default"] is True
    r = client.put(
        f"/api/orgs/{org.pk}/governance",
        data={"text": "# 우리 규칙"},
        content_type="application/json",
        headers=h,
    )
    assert r.status_code == 200 and r.json() == {"text": "# 우리 규칙", "is_default": False}
    # 멤버는 읽을 수 있고 고칠 수 없다.
    mh = {"Authorization": f"Bearer {member_raw}"}
    assert client.get(f"/api/orgs/{org.pk}/governance", headers=mh).json()["text"] == "# 우리 규칙"
    r = client.put(
        f"/api/orgs/{org.pk}/governance",
        data={"text": "x"},
        content_type="application/json",
        headers=mh,
    )
    assert r.status_code == 400


def test_team_write_api(client, org, admin, member):
    _, raw = ApiToken.issue(admin, "a", "write")
    h = {"Authorization": f"Bearer {raw}"}
    r = client.post(
        f"/api/orgs/{org.pk}/teams",
        data={"name": "백엔드"},
        content_type="application/json",
        headers=h,
    )
    assert r.status_code == 201
    team_id = r.json()["id"]
    r = client.post(
        f"/api/orgs/teams/{team_id}/members",
        data={"user_id": member.pk},
        content_type="application/json",
        headers=h,
    )
    assert r.status_code == 200 and r.json()["member_count"] == 1
    r = client.delete(f"/api/orgs/teams/{team_id}/members/{member.pk}", headers=h)
    assert r.status_code == 200 and r.json()["member_count"] == 0


# ---------- 설정 ----------


def test_settings_clean_rejects_unknown_key_range_and_type_strips_default(org):
    from .settings import clean

    with pytest.raises(ServiceError):
        clean("org", {"no.such.key": 1})
    with pytest.raises(ServiceError):
        clean("org", {"task.default_priority": 99})  # 범위 밖
    with pytest.raises(ServiceError):
        clean("org", {"task.require_done_when": "그런셈"})  # 형 불일치
    assert clean("org", {"task.default_priority": 5}) == {}  # 기본값과 같으면 지워진다


def test_settings_effective_locked_override_default_order(org, project, admin):
    from .settings import effective

    assert effective("task.default_priority", org=org, project=project) == 5  # 기본값
    set_org_settings(org, {"task.default_priority": 8}, admin)
    org.refresh_from_db()
    assert effective("task.default_priority", org=org, project=project) == 8  # 조직 값

    project.settings = {"task.default_priority": 3}
    project.save(update_fields=["settings"])
    assert effective("task.default_priority", org=org, project=project) == 3  # 프로젝트가 덮어쓴다

    set_locks(org, ["task.default_priority"], admin)
    org.refresh_from_db()
    assert effective("task.default_priority", org=org, project=project) == 8  # 잠기면 다시 조직 값


def test_set_org_settings_logs_changelog_and_requires_admin(org, admin, member):
    from tasks.models import ChangeLog

    with pytest.raises(ServiceError):
        set_org_settings(org, {"org.invite_days": 14}, member)

    set_org_settings(org, {"org.invite_days": 14}, admin)
    org.refresh_from_db()
    assert org.settings == {"org.invite_days": 14}
    log = ChangeLog.objects.get(target_type="org", target_id=org.pk, field="org.invite_days")
    assert log.old_value == "7" and log.new_value == "14" and log.actor == admin


def test_create_invite_uses_org_settings_for_days_and_max_uses(org, admin):
    set_org_settings(org, {"org.invite_days": 3, "org.invite_max_uses": 2}, admin)
    org.refresh_from_db()
    invite = create_invite(org, admin)
    assert invite.max_uses == 2
    assert 2 <= (invite.expires_at - timezone.now()).days <= 3


def test_join_by_token_blocked_once_max_uses_reached(org, admin, outsider):
    set_org_settings(org, {"org.invite_max_uses": 1}, admin)
    org.refresh_from_db()
    invite = create_invite(org, admin)
    join_by_token(outsider, invite.token)
    other = User.objects.create_user("outsider2", password="pw12345678")
    with pytest.raises(ServiceError):
        join_by_token(other, invite.token)


def test_set_tags_self_allowed_when_org_settings_permit(org, admin, member):
    membership = OrgMembership.objects.get(org=org, user=member)
    with pytest.raises(ServiceError):
        set_tags(membership, ["파이썬"], member)  # 기본은 관리자만
    set_org_settings(org, {"org.tags_by": "self"}, admin)
    membership.refresh_from_db()  # membership.org의 캐시된 settings도 새로 읽는다
    set_tags(membership, ["파이썬"], member)
    membership.refresh_from_db()
    assert membership.tags == ["파이썬"]


def test_team_join_self_allows_member_to_join_and_leave_without_admin(org, team, admin, outsider):
    OrgMembership.objects.create(org=org, user=outsider, role="member")
    with pytest.raises(ServiceError):
        add_team_member(team, outsider, outsider)
    set_org_settings(org, {"org.team_join_self": True}, admin)
    org.refresh_from_db()
    add_team_member(team, outsider, outsider)
    assert outsider in team.members.all()
    remove_team_member(team, outsider, outsider)
    assert outsider not in team.members.all()


def test_ai_source_denied_when_manage_teams_is_off(org, admin):
    set_org_settings(org, {"ai.manage_teams": "deny"}, admin)
    org.refresh_from_db()
    with pytest.raises(ServiceError):
        create_team(org=org, name="AI팀", actor=admin, source="mcp")
    create_team(org=org, name="AI팀", actor=admin, source="web")  # 웹은 막히지 않는다


def test_delete_team_member_blocked_admin_allowed_and_logged(org, team, admin, member):
    from tasks.models import ChangeLog

    with pytest.raises(ServiceError):
        delete_team(team, actor=member)
    team_id, name = team.pk, team.name
    delete_team(team, actor=admin)
    log = ChangeLog.objects.get(target_type="org", target_id=org.pk, field="delete")
    assert name in log.new_value and str(team_id) in log.new_value
    assert log.actor == admin


def test_delete_team_ai_delete_default_deny_then_allow(org, admin):
    t = create_team(org=org, name="AI삭제", actor=admin)
    with pytest.raises(ServiceError):
        delete_team(t, actor=admin, source="mcp")  # 기본값(deny)에서 막힌다
    set_org_settings(org, {"ai.delete": "allow"}, admin)
    org.refresh_from_db()
    delete_team(t, actor=admin, source="mcp")
    assert not org.teams.filter(pk=t.pk).exists()


def test_member_sees_permission_error_instead_of_404(client, org, member):
    """관리자 전용 동작을 일반 멤버가 POST하면 오류 메시지를 볼 수 있는 곳으로 보낸다.

    팀 화면은 관리자 전용이라 거기로 보내면 메시지가 404에 묻힌다.
    """
    client.force_login(member)
    r = client.post(f"/orgs/{org.pk}/invites", {})
    assert r.status_code == 302
    assert r.url == f"/orgs/{org.pk}"
    assert client.get(r.url).status_code == 200  # 메시지를 실제로 볼 수 있다
    assert org.invites.count() == 0
