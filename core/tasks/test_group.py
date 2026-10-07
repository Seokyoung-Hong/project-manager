"""IMPL-PLAN-12 G1: 상위·하위 태스크(한 겹) — 규칙·불변식·이동·완료 제안·열람·집계."""

import importlib
from datetime import timedelta

import pytest
from django.apps import apps
from django.db import connection
from django.test.utils import CaptureQueriesContext

from accounts.models import User
from common.dates import today_kst
from common.errors import ConflictError, ServiceError
from orgs.models import OrgMembership
from orgs.services import add_team_member, create_team
from projects.services import create_project, project_stats_bulk
from reports.services import org_status
from tasks import services as ts
from tasks.models import ChangeLog, ChecklistItem, Notice, Task, TaskProject

pytestmark = pytest.mark.django_db


def _t(project, actor, title="일", **kw):
    kw.setdefault("due_date", today_kst() + timedelta(days=5))
    return ts.create_task(project=project, title=title, actor=actor, source="web", **kw)


def _sub(group, actor, title="하위", **kw):
    return _t(group.project, actor, title, group=group, **kw)


def _close(task, actor, status="done"):
    task.refresh_from_db()
    return ts.transition(task, status, actor=actor, source="web", expected_version=task.version)


def _put(task, group, actor):
    task.refresh_from_db()
    return ts.set_group(task, group, actor=actor, expected_version=task.version)


def _user(org, name):
    u = User.objects.create_user(
        f"g{User.objects.count()}", password="pw12345678", display_name=name
    )
    OrgMembership.objects.create(org=org, user=u, role="member")
    return u


# ---------- 넣기·떼어내기 ----------


def test_set_group_and_ungroup_logs(project, member):
    top, t = _t(project, member, "상위"), _t(project, member)
    _put(t, top, member)
    assert t.group_id == top.pk and t.version == 2
    assert ChangeLog.objects.get(target_id=t.pk, field="group").new_value == top.number
    _put(t, None, member)
    assert t.group_id is None
    log = ChangeLog.objects.filter(target_id=t.pk, field="group").last()
    assert (log.old_value, log.new_value) == (top.number, "")


def test_set_group_refusals(org, project, member, admin):
    top = _t(project, member, "상위")
    sub = _sub(top, member)
    plain = _t(project, member)
    cases = [
        (top, top, "자기 자신"),
        (plain, sub, ts.ONE_LEVEL),  # 하위의 하위
        (top, plain, ts.ONE_LEVEL),  # 하위가 있는 태스크를 하위로
    ]
    for task, group, msg in cases:
        with pytest.raises(ServiceError) as e:
            _put(task, group, member)
        assert msg in e.value.errors["group"]
    other = create_project(org=org, name="다른", actor=admin)
    with pytest.raises(ServiceError) as e:
        _put(_t(other, member), top, member)
    assert "같은 프로젝트" in e.value.errors["group"]
    closed = _t(project, member)
    _close(closed, member, "cancelled")
    with pytest.raises(ServiceError) as e:
        _put(plain, closed, member)
    assert "완료·취소된" in e.value.errors["group"]
    tpl = _t(project, member)
    ts.set_template(tpl, True, actor=member)
    for task, group in ((plain, tpl), (tpl, top)):
        with pytest.raises(ServiceError):
            _put(task, group, member)
    plain.refresh_from_db()
    assert plain.group_id is None


def test_set_group_permission_and_version(org, project, member, admin, outsider):
    top, t = _t(project, member, "상위"), _t(project, member)
    with pytest.raises(ServiceError):
        ts.set_group(t, top, actor=outsider, expected_version=t.version)
    team = create_team(org=org, name="비밀", actor=admin)
    secret = create_project(
        org=org, name="비공개", actor=admin, owners=[admin], teams=[team], visibility="teams"
    )
    hidden = _t(secret, admin)
    with pytest.raises(ServiceError):  # 두 태스크를 모두 볼 수 있어야 한다
        ts.set_group(hidden, top, actor=member, expected_version=hidden.version)
    with pytest.raises(ConflictError):
        ts.set_group(t, top, actor=member, expected_version=t.version + 5)


def test_db_constraints(project, member):
    from django.db import IntegrityError, transaction

    t = _t(project, member)
    with pytest.raises(IntegrityError), transaction.atomic():
        Task.objects.filter(pk=t.pk).update(group=t)
    top = _t(project, member, "상위")
    with pytest.raises(IntegrityError), transaction.atomic():
        Task.objects.filter(pk=t.pk).update(group=top, is_template=True, status="todo")


# ---------- 하위 만들기 ----------


def test_create_subtask_forces_project_and_copies_links(org, project, member, admin):
    other = create_project(org=org, name="다른", actor=admin)
    top = _t(project, member, "상위")
    ts.link_project(top, other, actor=member)
    with pytest.raises(ServiceError) as e:
        _t(other, member, group=top)
    assert "project_id" in e.value.errors
    sub = _sub(top, member)
    assert sub.project_id == project.pk and sub.group_id == top.pk
    assert list(TaskProject.objects.filter(task=sub).values_list("project_id", "status")) == [
        (other.pk, "active")
    ]
    assert ChangeLog.objects.get(target_id=sub.pk, field="group").new_value == top.number
    with pytest.raises(ServiceError) as e:
        _sub(sub, member)
    assert e.value.errors["group"] == ts.ONE_LEVEL


# ---------- 상태 불변식 · 완료 제안 ----------


def test_invariant_closed_group_has_no_open_subtask(project, member):
    top = _t(project, member, "상위")
    a, b = _sub(top, member, "가"), _sub(top, member, "나")
    for status in ("done", "cancelled"):
        with pytest.raises(ServiceError) as e:
            _close(top, member, status)
        assert "하위 태스크 2건이 아직 열려 있습니다" in e.value.errors["status"]
    _close(a, member)
    _close(b, member, "cancelled")
    _close(top, member)
    with pytest.raises(ServiceError) as e:
        _close(a, member, "todo")  # 닫힌 상위의 하위 재개
    assert f"상위 {top.number}이 완료·취소 상태입니다" in e.value.errors["status"]
    _close(top, member, "todo")  # 상위 재개는 된다
    _close(a, member, "todo")


def test_last_subtask_closed_suggests_done_once(project, member):
    top = _t(project, member, "행사 준비")
    subs = [_sub(top, member, str(i)) for i in range(3)]
    _close(subs[2], member, "cancelled")  # 취소는 분모에서 빠진다
    _close(subs[0], member)
    assert ts.subtask_progress(top) == (1, 2) and not Notice.objects.exists()
    assert not ts.group_done_suggested(top)
    _close(subs[1], member)
    n = Notice.objects.get()
    assert n.user == member and top.number in n.text
    assert "상위를 완료로 표시해 주세요" in n.text
    top.refresh_from_db()
    assert top.status == "todo" and ts.group_done_suggested(top)  # 자동 완료하지 않는다


def test_suggest_on_github_merge_actor_none(project, member):
    top = _t(project, member, "상위")
    sub = _sub(top, member)
    sub.refresh_from_db()
    ts.transition(sub, "done", actor=None, source="gh", expected_version=sub.version)
    assert Notice.objects.filter(user=member).count() == 1


# ---------- 옮기기 ----------


def test_move_group_moves_subtasks(org, project, member, admin):
    other = create_project(org=org, name="다른", actor=admin)
    top = _t(project, member, "상위")
    ts.link_project(top, other, actor=member)
    subs = [_sub(top, member, "가"), _sub(top, member, "나")]
    top.refresh_from_db()
    ts.update_task(
        top, {"project": other}, actor=member, source="web", expected_version=top.version
    )
    for s in subs:
        s.refresh_from_db()
        assert s.project_id == other.pk
        assert not TaskProject.objects.filter(task=s, project=other).exists()  # 주 ≠ 연결
        assert ChangeLog.objects.filter(
            target_id=s.pk, field="project", note="상위와 함께"
        ).exists()
    with pytest.raises(ServiceError) as e:  # 하위 단독 옮기기
        ts.update_task(
            subs[0],
            {"project": project},
            actor=member,
            source="web",
            expected_version=subs[0].version,
        )
    assert e.value.errors["project"] == ts.SUB_SAME_PROJECT


def test_move_refused_when_sub_assignee_cannot_see(org, project, member, admin):
    team = create_team(org=org, name="비밀", actor=admin)
    secret = create_project(
        org=org, name="비공개", actor=admin, owners=[admin], teams=[team], visibility="teams"
    )
    top = _t(project, admin, "상위")
    sub = _sub(top, admin, assignee=member)
    sub.refresh_from_db()
    assert sub.assignee == member
    with pytest.raises(ServiceError) as e:
        ts.update_task(
            top, {"project": secret}, actor=admin, source="web", expected_version=top.version
        )
    assert sub.number in e.value.errors["project"]
    sub.refresh_from_db()
    top.refresh_from_db()
    assert sub.project_id == top.project_id == project.pk


# ---------- 템플릿 · 복제 · 삭제 ----------


def test_template_duplicate_delete(project, member, admin):
    top = _t(project, member, "상위")
    sub = _sub(top, member)
    for t in (top, sub):
        with pytest.raises(ServiceError):
            ts.set_template(t, True, actor=member)
    copy = ts.duplicate_task(top, actor=member, source="web", due_date=top.due_date)
    assert copy.parent_id == top.pk and not copy.subtasks.exists()  # 하위는 복사하지 않는다
    ts.delete_task(top, actor=admin)
    sub.refresh_from_db()
    assert sub.group_id is None
    assert ChangeLog.objects.filter(target_id=sub.pk, field="group", note="상위 삭제").exists()


def test_archive_cancels_subtasks_first(project, member, admin):
    from projects.services import archive_project

    top = _t(project, member, "상위")
    _sub(top, member)
    archive_project(project, actor=admin, cancel_open=True)
    assert set(Task.objects.values_list("status", flat=True)) == {"cancelled"}


# ---------- 열람 ----------


@pytest.fixture
def split_view(org, admin, member):
    """비공개 프로젝트의 상위·하위, 공개 프로젝트, 공개만 보는 사람."""
    team = create_team(org=org, name="비밀", actor=admin)
    add_team_member(team, member, admin)
    secret = create_project(
        org=org, name="비공개", actor=admin, owners=[admin], teams=[team], visibility="teams"
    )
    public = create_project(org=org, name="공개", actor=admin)
    return secret, public, _user(org, "바깥")


def _link(task, project, member, admin):
    ts.approve_link(
        ts.link_project(task, project, actor=member, confirm_widening=True), actor=admin
    )


def test_view_sub_only_hides_group(split_view, member, admin):
    secret, public, viewer = split_view
    top = _t(secret, member, "비밀 상위")
    sub = _sub(top, member)
    _link(sub, public, member, admin)
    v = ts.subtask_view(viewer, sub)
    assert v["group"] is None  # 번호·제목을 내지 않는다
    assert ts.subtask_view(member, sub)["group"] == top


def test_view_group_only_hides_subtasks(split_view, member, admin):
    secret, public, viewer = split_view
    top = _t(secret, member, "상위")
    sub = _sub(top, member, due_date=today_kst() + timedelta(days=9))
    _close(sub, member)
    _link(top, public, member, admin)
    v = ts.subtask_view(viewer, top)
    assert v["subtasks"] == [] and v["hidden"] == 1
    assert (v["done"], v["total"]) == (1, 1) and v["suggest_done"]
    mine = ts.subtask_view(member, top)
    assert [s.pk for s in mine["subtasks"]] == [sub.pk] and mine["hidden"] == 0
    assert mine["subtasks"][0].due_after_group  # 하위 기한 > 상위 기한 → 경고


# ---------- 집계: 잎만 센다 ----------


def test_aggregates_count_leaves_only(org, project, member):
    top = _t(project, member, "상위")
    for i in range(3):
        _sub(top, member, str(i))
    lonely = _t(project, member, "하위 없는 상위")  # 하위가 없으면 센다
    assert lonely.pk
    stats = project_stats_bulk([project])[project.pk]
    assert stats["open"] == 4 and stats["total"] == 4
    assert ts.tasks_visible_in(org, member).count() == 4
    assert ts.tasks_visible_in(org).count() == 4  # 봇(viewer None)
    assert org_status(org, viewer=member)["counts"]["open"] == 4
    assert top in ts.tasks_of(project)  # 목록에는 둘 다 보인다


def test_stats_query_count_does_not_grow(org, project, member):
    def count():
        with CaptureQueriesContext(connection) as q:
            project_stats_bulk([project])
        return len(q)

    top = _t(project, member, "상위")
    _sub(top, member)
    before = count()
    for i in range(3):
        _sub(_t(project, member, f"상위{i}"), member)
    assert count() == before


# ---------- S1 안전망 마이그레이션 ----------


def test_runpython_converts_old_split(project, member):
    mig = importlib.import_module("tasks.migrations.0013_task_group_data")
    top = _t(project, member, "원본")
    olds = [_t(project, member, f"사람{i}") for i in range(2)]
    Task.objects.filter(pk__in=[o.pk for o in olds]).update(parent=top)
    for o in olds:
        ChecklistItem.objects.create(task=top, text=f"{o.number} {o.title}", position=o.pk)
    ChangeLog.objects.create(
        target_type="task",
        target_id=top.pk,
        field="split",
        new_value=",".join(o.number for o in olds),
        source="web",
    )
    for _ in range(2):  # 멱등
        mig.split_to_subtasks(apps, None)
    assert set(Task.objects.filter(group=top).values_list("pk", flat=True)) == {o.pk for o in olds}
    assert not Task.objects.filter(parent=top).exists()
    assert not top.checklist.exists()
