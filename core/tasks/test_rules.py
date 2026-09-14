"""task.* 설정 강제 (IMPL-PLAN-4 1단계, 태스크 규칙). 경로마다 테스트 하나."""

from datetime import timedelta

import pytest

from common.dates import today_kst
from common.errors import ServiceError
from orgs.services import set_org_settings
from tasks.models import ChangeLog
from tasks.services import (
    create_task,
    doing_over_limit,
    me_view,
    today_view,
    transition,
    update_task,
)

pytestmark = pytest.mark.django_db


def test_require_done_when(org, project, member, admin):
    set_org_settings(org, {"task.require_done_when": True}, admin)
    with pytest.raises(ServiceError) as e:
        create_task(
            project=project,
            title="x",
            actor=member,
            source="web",
            due_date=today_kst() + timedelta(days=1),
        )
    assert "done_when" in e.value.errors
    t = create_task(
        project=project,
        title="x",
        actor=member,
        source="web",
        due_date=today_kst() + timedelta(days=1),
        done_when="다 됐다고 부를 조건",
    )
    assert t.done_when == "다 됐다고 부를 조건"


def test_due_required_blocks_no_due_reason_workaround(org, project, member, admin):
    set_org_settings(org, {"task.due_required": True}, admin)
    with pytest.raises(ServiceError) as e:
        create_task(project=project, title="x", actor=member, source="web", no_due_reason="사유")
    assert "due_date" in e.value.errors
    t = create_task(
        project=project,
        title="x",
        actor=member,
        source="web",
        due_date=today_kst() + timedelta(days=1),
    )
    assert t.due_date is not None


def test_doing_limit_block_mode(org, project, member, admin, task):
    set_org_settings(org, {"task.doing_limit": 1, "task.doing_limit_mode": "block"}, admin)
    transition(task, "doing", actor=member, source="web", expected_version=task.version)
    t2 = create_task(
        project=project,
        title="두 번째",
        actor=member,
        source="web",
        due_date=today_kst() + timedelta(days=2),
    )
    with pytest.raises(ServiceError) as e:
        transition(t2, "doing", actor=member, source="web", expected_version=t2.version)
    assert "status" in e.value.errors


def test_doing_limit_warn_mode_does_not_block_and_shows_in_today_view(
    org, project, member, admin, task
):
    set_org_settings(org, {"task.doing_limit": 1, "task.doing_limit_mode": "warn"}, admin)
    task = transition(task, "doing", actor=member, source="web", expected_version=task.version)
    t2 = create_task(
        project=project,
        title="두 번째",
        actor=member,
        source="web",
        due_date=today_kst() + timedelta(days=2),
    )
    t2 = transition(t2, "doing", actor=member, source="web", expected_version=t2.version)
    assert t2.status == "doing"
    assert doing_over_limit(member, org) == (2, 1)
    v = today_view(member)
    assert v["doing_warn"] == (2, 1)


def test_review_required_and_self_review(org, project, member, admin, task):
    set_org_settings(org, {"task.review_required": True, "task.self_review": False}, admin)
    t = transition(task, "doing", actor=member, source="web", expected_version=task.version)
    with pytest.raises(ServiceError):
        transition(t, "done", actor=member, source="web", expected_version=t.version)
    t = transition(t, "review", actor=member, source="web", expected_version=t.version)
    with pytest.raises(ServiceError) as e:
        transition(t, "done", actor=member, source="web", expected_version=t.version)
    assert "status" in e.value.errors
    t = transition(t, "done", actor=admin, source="web", expected_version=t.version)
    assert t.status == "done"


def test_reopen_reason_required(org, project, member, admin, task):
    set_org_settings(org, {"task.reopen_reason_required": True}, admin)
    t = transition(task, "doing", actor=member, source="web", expected_version=task.version)
    t = transition(t, "done", actor=member, source="web", expected_version=t.version)
    with pytest.raises(ServiceError) as e:
        transition(t, "todo", actor=member, source="web", expected_version=t.version)
    assert "reason" in e.value.errors
    t = transition(
        t, "todo", actor=member, source="web", reason="다시 시작", expected_version=t.version
    )
    assert t.status == "todo"


def test_cancel_reason_required(org, project, member, admin, task):
    set_org_settings(org, {"task.cancel_reason_required": True}, admin)
    with pytest.raises(ServiceError) as e:
        transition(task, "cancelled", actor=member, source="web", expected_version=task.version)
    assert "reason" in e.value.errors
    t = transition(
        task,
        "cancelled",
        actor=member,
        source="web",
        reason="취소함",
        expected_version=task.version,
    )
    assert t.status == "cancelled"


def test_assignee_and_due_change_reason(org, project, member, admin, task):
    set_org_settings(
        org, {"task.assignee_change_reason": True, "task.due_change_reason": True}, admin
    )
    with pytest.raises(ServiceError) as e:
        update_task(
            task, {"assignee": admin}, actor=member, source="web", expected_version=task.version
        )
    assert "reason" in e.value.errors
    t = update_task(
        task,
        {"assignee": admin},
        actor=member,
        source="web",
        expected_version=task.version,
        reason="인수인계",
    )
    assert t.assignee == admin
    with pytest.raises(ServiceError):
        update_task(
            t,
            {"due_date": today_kst() + timedelta(days=10)},
            actor=member,
            source="web",
            expected_version=t.version,
        )
    t = update_task(
        t,
        {"due_date": today_kst() + timedelta(days=10)},
        actor=member,
        source="web",
        expected_version=t.version,
        reason="일정 변경",
    )
    log = ChangeLog.objects.filter(target_type="task", target_id=t.pk, field="due_date").latest(
        "id"
    )
    assert log.note == "일정 변경"


def test_overdue_grace_days_shifts_me_view_overdue_group(org, project, member, admin, task):
    task.due_date = today_kst() - timedelta(days=2)
    task.save(update_fields=["due_date"])
    v = me_view(member)
    overdue_group = next(g for g in v["groups"] if g["title"] == "기한 초과")
    assert task in overdue_group["tasks"]

    set_org_settings(org, {"task.overdue_grace_days": 5}, admin)
    v = me_view(member)
    overdue_group = next(g for g in v["groups"] if g["title"] == "기한 초과")
    assert task not in overdue_group["tasks"]


def test_default_due_days_and_priority_set_form_initial(org, project, admin):
    from web.forms import TaskInlineForm

    set_org_settings(org, {"task.default_due_days": 3, "task.default_priority": 8}, admin)
    form = TaskInlineForm(org=org, project=project)
    assert form.fields["priority"].initial == 8
    assert form.fields["due_date"].initial is not None
    assert form.fields["due_date"].initial > today_kst()
    # bound(제출) 폼에는 초기값을 강요하지 않는다
    bound = TaskInlineForm({"title": "x"}, org=org, project=project)
    assert bound.fields["due_date"].initial is None


def test_empty_settings_keep_old_behaviour(org, project, member, task):
    """설정을 하나도 안 건드리면 기존 동작 그대로: 검토 없이 완료, 사유 없이 취소·재개."""
    t = transition(task, "doing", actor=member, source="web", expected_version=task.version)
    t = transition(t, "done", actor=member, source="web", expected_version=t.version)
    assert t.status == "done"
    t = transition(t, "todo", actor=member, source="web", expected_version=t.version)
    assert t.status == "todo"
    t2 = create_task(project=project, title="y", actor=member, source="web", no_due_reason="사유")
    t2 = transition(t2, "cancelled", actor=member, source="web", expected_version=t2.version)
    assert t2.status == "cancelled"
