"""설정 레지스트리·서비스·강제 지점 (IMPL-PLAN-4 0단계)."""

from datetime import timedelta

import pytest

from common.dates import today_kst
from common.errors import ServiceError
from orgs import settings as S
from orgs.services import create_invite, join_by_token, set_org_settings
from projects.services import create_project, set_project_settings
from tasks.models import ChangeLog
from tasks.services import create_task, transition, update_task

pytestmark = pytest.mark.django_db


# ---- 레지스트리 ----


def test_clean_rejects_unknown_type_and_range():
    with pytest.raises(ServiceError) as e:
        S.clean("org", {"nope": 1, "task.priority_cap": 11, "task.review_required": "x"})
    assert set(e.value.errors) == {"nope", "task.priority_cap"}
    with pytest.raises(ServiceError):
        S.clean("org", {"user.start_page": "me"})  # 층이 다르다


def test_clean_drops_defaults_and_coerces_form_values():
    out = S.clean(
        "org",
        {
            "task.priority_cap": "7",
            "task.default_priority": "5",  # 기본값 → 지워진다
            "task.review_required": "1",
            "notify.send_hour": "",  # None 기본
            "notify.deadline_kinds": ["d1", "d3", "d1"],
        },
    )
    assert out == {
        "task.priority_cap": 7,
        "task.review_required": True,
        "notify.deadline_kinds": ["d3", "d1"],
    }


def test_effective_order_project_over_org_unless_locked(org, project):
    key = "task.priority_cap"
    assert S.effective(key, org=org) == 0
    org.settings = {key: 7}
    project.settings = {key: 9}
    assert S.effective(key, project=project) == 9
    org.settings[S.LOCKED] = [key]
    assert S.effective(key, project=project) == 7
    # 덮어쓰기 불가 키는 프로젝트 값을 보지 않는다
    project.settings["project.create_by"] = "admin"
    assert S.effective("project.create_by", project=project) == "member"


# ---- 서비스 ----


def test_set_org_settings_admin_only_and_logged(org, admin, member):
    with pytest.raises(ServiceError):
        set_org_settings(org, {"task.priority_cap": 7}, member)
    set_org_settings(org, {"task.priority_cap": 7}, admin, locked=["task.priority_cap"])
    org.refresh_from_db()
    assert org.settings == {"task.priority_cap": 7, S.LOCKED: ["task.priority_cap"]}
    logs = ChangeLog.objects.filter(target_type="org", target_id=org.pk)
    assert {(row.field, row.old_value, row.new_value) for row in logs} == {
        ("task.priority_cap", "", "7"),
        (S.LOCKED, "", '["task.priority_cap"]'),
    }
    with pytest.raises(ServiceError):
        set_org_settings(org, {}, admin, locked=["project.create_by"])  # 잠글 수 없는 키


def test_project_settings_respect_lock_and_level(org, admin, member, project):
    with pytest.raises(ServiceError):
        set_project_settings(project, {"task.review_required": True}, actor=member)
    set_project_settings(project, {"task.review_required": True}, actor=admin)
    project.refresh_from_db()
    assert project.settings == {"task.review_required": True}
    set_org_settings(org, {}, admin, locked=["task.review_required"])
    with pytest.raises(ServiceError):
        set_project_settings(project, {"task.review_required": True}, actor=admin)
    with pytest.raises(ServiceError):
        set_project_settings(project, {"project.create_by": "admin"}, actor=admin)


# ---- 강제 지점 3개 ----


def test_priority_cap_blocks_member_not_owner(org, admin, member, project):
    set_org_settings(org, {"task.priority_cap": 7}, admin)
    due = today_kst() + timedelta(days=1)
    with pytest.raises(ServiceError) as e:
        create_task(
            project=project, title="x", actor=member, source="web", priority=8, due_date=due
        )
    assert "priority" in e.value.errors
    t = create_task(project=project, title="x", actor=admin, source="web", priority=8, due_date=due)
    assert t.priority == 8
    t2 = create_task(project=project, title="y", actor=member, source="web", due_date=due)
    with pytest.raises(ServiceError):
        update_task(t2, {"priority": 9}, actor=member, source="web", expected_version=1)
    update_task(t2, {"priority": 7}, actor=member, source="web", expected_version=1)


def test_review_required_blocks_done_from_doing(org, admin, task):
    set_org_settings(org, {"task.review_required": True}, admin)
    with pytest.raises(ServiceError) as e:
        transition(task, "done", actor=admin, source="web", expected_version=task.version)
    assert "status" in e.value.errors
    transition(task, "review", actor=admin, source="web", expected_version=task.version)
    task.refresh_from_db()
    transition(task, "done", actor=admin, source="web", expected_version=task.version)


def test_project_create_by_admin(org, admin, member):
    set_org_settings(org, {"project.create_by": "admin"}, admin)
    with pytest.raises(ServiceError):
        create_project(org=org, name="p", actor=member)
    create_project(org=org, name="p", actor=admin)


def test_invite_defaults_from_settings(org, admin, outsider):
    set_org_settings(org, {"org.invite_days": 3, "org.invite_max_uses": 1}, admin)
    inv = create_invite(org, admin)
    assert inv.max_uses == 1
    join_by_token(outsider, inv.token)
    inv.refresh_from_db()
    assert not inv.is_usable


# ---- API · 화면 ----


def test_settings_api_get_and_put(api, client, org, admin, member):
    r = api.get(f"/api/orgs/{org.pk}/settings")
    assert r.status_code == 200 and r.json()["values"] == {}
    r = api.put(f"/api/orgs/{org.pk}/settings", {"values": {"task.priority_cap": 7}})
    assert r.status_code == 400  # member 토큰
    client.force_login(admin)
    r = client.put(
        f"/api/orgs/{org.pk}/settings",
        {"values": {"task.priority_cap": 7}, "locked": ["task.priority_cap"]},
        content_type="application/json",
    )
    assert r.status_code == 200
    assert r.json()["values"] == {"task.priority_cap": 7}
    assert r.json()["locked"] == ["task.priority_cap"]


def test_settings_page_member_reads_admin_writes(client, org, admin, member):
    client.force_login(member)
    r = client.get(f"/orgs/{org.pk}/settings")
    assert r.status_code == 200 and "조직 관리자만" in r.content.decode()
    r = client.post(f"/orgs/{org.pk}/settings", {"task.priority_cap": "7"})
    org.refresh_from_db()
    assert org.settings == {}
    client.force_login(admin)
    r = client.post(
        f"/orgs/{org.pk}/settings",
        {"task.priority_cap": "7", "task.self_review": "0", "lock:task.priority_cap": "1"},
    )
    assert r.status_code == 302
    org.refresh_from_db()
    assert org.settings["task.priority_cap"] == 7
    assert org.settings["task.self_review"] is False
    # 체크하지 않은 잠금 후보는 잠긴다
    assert "task.priority_cap" not in org.settings[S.LOCKED]
    assert "task.review_required" in org.settings[S.LOCKED]
