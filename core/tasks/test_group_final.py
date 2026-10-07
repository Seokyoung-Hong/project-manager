"""Fable 최종 검토(S-fable-final-r11-12) S1·S2·S3·S6·0012 RunPython 재현."""

import importlib
from datetime import timedelta

import pytest
from django.apps import apps

from accounts.models import ApiToken, User
from common.dates import today_kst
from common.errors import ServiceError
from orgs.models import OrgMembership
from orgs.services import add_team_member, create_team
from projects.models import Project
from projects.services import create_project
from tasks import services as ts
from tasks.models import ChangeLog, Notice, Task

pytestmark = pytest.mark.django_db


def _t(project, actor, title="일", **kw):
    kw.setdefault("due_date", today_kst() + timedelta(days=5))
    return ts.create_task(project=project, title=title, actor=actor, source="web", **kw)


def _go(task, status, actor):
    fresh = Task.objects.get(pk=task.pk)
    return ts.transition(fresh, status, actor=actor, source="web", expected_version=fresh.version)


@pytest.fixture
def world(org, admin, member):
    """비공개 프로젝트(팀원만) · 공개 프로젝트 · 공개만 보는 바깥 사람."""
    viewer = User.objects.create_user("vw", password="pw12345678", display_name="바깥")
    OrgMembership.objects.create(org=org, user=viewer, role="member")
    team = create_team(org=org, name="비밀", actor=admin)
    add_team_member(team, member, admin)
    secret = create_project(
        org=org, name="비밀 프로젝트", actor=admin, owners=[admin], teams=[team], visibility="teams"
    )
    public = create_project(org=org, name="공개", actor=admin)
    return secret, public, viewer


def _link(task, project, member, admin):
    ts.approve_link(
        ts.link_project(task, project, actor=member, confirm_widening=True), actor=admin
    )


def test_s1_put_candidates_only_visible(client, world, member, admin):
    secret, public, viewer = world
    shared = _t(secret, member, "공유된 일")
    _link(shared, public, member, admin)
    _t(secret, member, "비밀 후보 제목")
    client.force_login(viewer)
    html = client.get(f"/tasks/{shared.pk}/panel").content.decode()
    assert "기존 태스크 넣기" not in html or "비밀 후보 제목" not in html
    assert "비밀 후보 제목" not in html


def test_s2_moved_project_hidden_in_history(client, world, member, admin):
    secret, public, viewer = world
    t = _t(secret, member, "옮길 일")
    t.refresh_from_db()
    ts.update_task(t, {"project": public}, actor=admin, source="web", expected_version=t.version)
    assert ChangeLog.objects.filter(target_id=t.pk, field="project", old_value=str(secret.pk))
    client.force_login(viewer)
    html = client.get(f"/tasks/{t.pk}/panel").content.decode()
    assert "비밀 프로젝트" not in html and ts.HIDDEN_PROJECT in html
    _, raw = ApiToken.issue(viewer, "t", "read", for_ai=False)
    hist = client.get(
        f"/api/tasks/{t.pk}/history", headers={"Authorization": f"Bearer {raw}"}
    ).json()
    row = next(h for h in hist if h["field"] == "project")
    assert row["old_value"] == ts.HIDDEN_PROJECT and row["new_value"] == str(public.pk)


def test_s3_suggest_dm_needs_assignee_view(org, admin, member):
    p = create_project(org=org, name="바뀔 프로젝트", actor=admin, owners=[admin])
    top = _t(p, admin, "상위", assignee=member)
    top.refresh_from_db()
    assert top.assignee == member
    sub = _t(p, admin, group=top)
    Project.objects.filter(pk=p.pk).update(visibility="teams")  # 담당자가 더는 못 본다
    _go(sub, "done", admin)
    assert not Notice.objects.filter(
        user=member, text__contains="하위 태스크가 모두 끝났습니다"
    ).exists()


def test_s6_reopen_refusal_hides_group_number(world, member, admin):
    secret, public, viewer = world
    top = _t(secret, member, "비밀 상위")
    sub = _t(secret, member, group=top)
    _link(sub, public, member, admin)
    _go(sub, "done", member)
    _go(top, "done", member)
    with pytest.raises(ServiceError) as e:
        _go(sub, "todo", viewer)
    assert top.number not in e.value.errors["status"]
    with pytest.raises(ServiceError) as e:
        _go(sub, "todo", member)
    assert top.number in e.value.errors["status"]


def test_0012_runpython_skips_closed_origin(project, member):
    mig = importlib.import_module("tasks.migrations.0012_task_group")
    top = _t(project, member, "닫힌 원본")
    old = _t(project, member, "사람")
    Task.objects.filter(pk=old.pk).update(parent=top)
    _go(top, "done", member)
    ChangeLog.objects.create(
        target_type="task", target_id=top.pk, field="split", new_value=old.number, source="web"
    )
    mig.split_to_subtasks(apps, None)
    assert not Task.objects.filter(group=top).exists()  # 닫힌 상위 아래 열린 하위를 만들지 않는다
