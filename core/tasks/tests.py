import time
from datetime import timedelta

import pytest
from django.db import IntegrityError, transaction

from common.dates import today_kst, week_bounds
from common.errors import ConflictError, ServiceError
from orgs.services import create_org
from projects.services import archive_project, create_project
from reports.services import weekly
from tasks import services as ts
from tasks.models import ChangeLog, Link, Task
from tasks.services import (
    add_link,
    checklist_add,
    checklist_delete,
    checklist_move,
    checklist_toggle,
    create_task,
    extend_due,
    me_view,
    replace_checklist,
    search,
    today_add,
    today_exclude,
    today_flag,
    today_membership,
    today_move,
    today_restore_excluded,
    today_set_auto_pull,
    today_view,
    transition,
    update_task,
    update_text,
)

pytestmark = pytest.mark.django_db


def _logs(task, field=None):
    qs = ChangeLog.objects.filter(target_type="task", target_id=task.pk)
    return qs.filter(field=field) if field else qs


def test_create_defaults_assignee_to_actor(project, member):
    t = create_task(
        project=project,
        title="새 일",
        actor=member,
        source="web",
        due_date=today_kst() + timedelta(days=1),
    )
    assert t.assignee == member
    assert t.priority == 5
    assert _logs(t, "created").count() == 1


def test_create_requires_title_and_reason_without_due(project, member):
    with pytest.raises(ServiceError) as e:
        create_task(project=project, title="", actor=member, source="web", no_due_reason="x")
    assert "title" in e.value.errors
    with pytest.raises(ServiceError) as e:
        create_task(project=project, title="제목", actor=member, source="web")
    assert "no_due_reason" in e.value.errors


def test_create_rejects_non_member_assignee(project, member, outsider):
    with pytest.raises(ServiceError) as e:
        create_task(
            project=project,
            title="제목",
            actor=member,
            source="web",
            assignee=outsider,
            due_date=today_kst(),
        )
    assert "assignee" in e.value.errors


def test_create_in_archived_project_rejected(org, admin, member):
    p = create_project(org=org, name="보관용", actor=admin)
    archive_project(p, actor=admin)
    with pytest.raises(ServiceError) as e:
        create_task(project=p, title="제목", actor=member, source="web", due_date=today_kst())
    assert "project" in e.value.errors


def test_priority_range_1_to_10(project, member):
    for bad in (0, 11):
        with pytest.raises(ServiceError) as e:
            create_task(
                project=project,
                title="제목",
                actor=member,
                source="web",
                due_date=today_kst(),
                priority=bad,
            )
        assert "priority" in e.value.errors
    with pytest.raises(IntegrityError), transaction.atomic():
        Task.objects.create(
            project=project, title="x", assignee=member, created_by=member, priority=11
        )


def test_db_constraint_doing_requires_due(project, member):
    with pytest.raises(IntegrityError), transaction.atomic():
        Task.objects.create(
            project=project,
            title="x",
            assignee=member,
            created_by=member,
            status="doing",
            due_date=None,
        )


def test_db_constraint_blocked_requires_reason(project, member):
    with pytest.raises(IntegrityError), transaction.atomic():
        Task.objects.create(
            project=project,
            title="x",
            assignee=member,
            created_by=member,
            status="blocked",
            stop_reason="",
        )


def test_transition_flow_records_completed_at_and_log(task, member):
    t = transition(task, "doing", actor=member, source="web", expected_version=1)
    t = transition(t, "done", actor=member, source="web", expected_version=2)
    assert t.completed_at is not None
    assert t.version == 3
    logs = list(_logs(t, "status"))
    assert len(logs) == 2
    assert logs[-1].old_value == "doing" and logs[-1].new_value == "done"


def test_transition_to_doing_requires_due(project, member):
    t = create_task(
        project=project, title="기한 없음", actor=member, source="web", no_due_reason="미정"
    )
    with pytest.raises(ServiceError) as e:
        transition(t, "doing", actor=member, source="web", expected_version=t.version)
    assert e.value.errors["due_date"] == ts.NO_DUE_FOR_DOING


def test_done_again_is_noop(task, member):
    t = transition(task, "done", actor=member, source="web", expected_version=1)
    before_count = _logs(t).count()
    completed, version = t.completed_at, t.version
    t = transition(t, "done", actor=member, source="web", expected_version=t.version)
    assert t.completed_at == completed
    assert t.version == version
    assert _logs(t).count() == before_count


def test_reopen_clears_completed_at_reason_optional(task, member):
    t = transition(task, "done", actor=member, source="web", expected_version=1)
    old_completed = t.completed_at
    t = transition(t, "todo", actor=member, source="web", expected_version=t.version)
    assert t.completed_at is None
    row = _logs(t, "completed_at").last()
    assert row is not None
    assert row.old_value == old_completed.isoformat()
    t = transition(t, "done", actor=member, source="web", expected_version=t.version)
    t = transition(
        t, "todo", actor=member, source="web", reason="다시 확인", expected_version=t.version
    )
    assert _logs(t, "status").last().note == "다시 확인"


def test_reopen_then_done_sets_new_completed_at(task, member):
    t = transition(task, "done", actor=member, source="web", expected_version=1)
    first = t.completed_at
    t = transition(t, "todo", actor=member, source="web", expected_version=t.version)
    t = transition(t, "done", actor=member, source="web", expected_version=t.version)
    assert t.completed_at > first


def test_closed_can_only_reopen_to_todo_or_doing(task, member):
    t = transition(task, "done", actor=member, source="web", expected_version=1)
    with pytest.raises(ServiceError) as e:
        transition(t, "review", actor=member, source="web", expected_version=t.version)
    assert "status" in e.value.errors
    t = transition(t, "todo", actor=member, source="web", expected_version=t.version)
    t = transition(t, "cancelled", actor=member, source="web", expected_version=t.version)
    with pytest.raises(ServiceError) as e:
        transition(t, "paused", actor=member, source="web", expected_version=t.version)
    assert "status" in e.value.errors


def test_cancel_is_not_completion(task, member, org):
    t = transition(task, "cancelled", actor=member, source="web", expected_version=1)
    assert t.completed_at is None
    monday, _ = week_bounds()
    assert weekly(org, monday)["counts"]["completed"] == 0


def test_transition_blocked_requires_reason_paused_optional(task, member):
    t = transition(task, "doing", actor=member, source="web", expected_version=1)
    with pytest.raises(ServiceError) as e:
        transition(t, "blocked", actor=member, source="web", expected_version=t.version)
    assert "stop_reason" in e.value.errors
    t = transition(
        t, "blocked", actor=member, source="web", reason="서류 대기", expected_version=t.version
    )
    assert t.status == "blocked"
    assert t.stop_reason == "서류 대기"
    assert t.stopped_at is not None

    t2 = create_task(
        project=t.project, title="다른 일", actor=member, source="web", no_due_reason="미정"
    )
    t2 = transition(t2, "paused", actor=member, source="web", expected_version=t2.version)
    assert t2.stop_reason == ""
    assert t2.stopped_at is not None


def test_blocked_to_paused_keeps_reason(task, member):
    t = transition(task, "blocked", actor=member, source="web", reason="A", expected_version=1)
    t = transition(t, "paused", actor=member, source="web", expected_version=t.version)
    assert t.stop_reason == "A"


def test_leaving_stopped_clears_reason_and_logs(task, member):
    t = transition(task, "blocked", actor=member, source="web", reason="A", expected_version=1)
    t = transition(t, "doing", actor=member, source="web", expected_version=t.version)
    assert t.stop_reason == ""
    assert t.stopped_at is None
    row = _logs(t, "stop_reason").last()
    assert row.old_value == "A" and row.new_value == ""
    assert row.note == "상태 변경으로 해제"


def test_done_from_blocked_clears_stop_reason(task, member):
    t = transition(task, "blocked", actor=member, source="web", reason="A", expected_version=1)
    t = transition(t, "done", actor=member, source="web", expected_version=t.version)
    assert t.stop_reason == ""
    assert t.completed_at is not None


def test_update_stop_reason_rules(task, member):
    t = transition(task, "paused", actor=member, source="web", expected_version=1)
    t = update_task(t, {"stop_reason": "B"}, actor=member, source="web", expected_version=t.version)
    assert t.stop_reason == "B"
    assert _logs(t, "stop_reason").exists()

    todo = create_task(
        project=t.project, title="todo", actor=member, source="web", no_due_reason="미정"
    )
    with pytest.raises(ServiceError) as e:
        update_task(
            todo, {"stop_reason": "x"}, actor=member, source="web", expected_version=todo.version
        )
    assert "stop_reason" in e.value.errors

    b = transition(t, "blocked", actor=member, source="web", reason="C", expected_version=t.version)
    with pytest.raises(ServiceError) as e:
        update_task(b, {"stop_reason": ""}, actor=member, source="web", expected_version=b.version)
    assert "stop_reason" in e.value.errors


def test_optimistic_lock_conflict(task, member):
    update_task(task, {"priority": 8}, actor=member, source="web", expected_version=1)
    with pytest.raises(ConflictError) as e:
        update_task(task, {"priority": 9}, actor=member, source="web", expected_version=1)
    assert e.value.latest.version == 2
    assert e.value.latest.priority == 8


def test_update_text_does_not_bump_version(task, member):
    before = _logs(task).count()
    t = update_text(task, "notes", "메모", actor=member)
    assert t.notes == "메모"
    assert t.version == 1
    assert _logs(t).count() == before
    t = update_task(
        t,
        {"title": "새 제목", "description": "d"},
        actor=member,
        source="web",
        expected_version=999,
    )
    assert t.version == 1
    assert t.title == "새 제목"


def test_update_text_title_required(task, member):
    with pytest.raises(ServiceError) as e:
        update_text(task, "title", "  ", actor=member)
    assert "title" in e.value.errors
    with pytest.raises(ServiceError) as e:
        update_text(task, "status", "x", actor=member)
    assert "status" in e.value.errors


def test_update_logs_tracked_fields_only(task, member):
    update_task(
        task,
        {"next_action": "다음", "priority": 9, "due_date": today_kst() + timedelta(days=9)},
        actor=member,
        source="web",
        expected_version=1,
    )
    assert _logs(task, "priority").exists()
    assert _logs(task, "due_date").exists()
    assert not _logs(task, "next_action").exists()


def test_move_to_other_org_project_rejected(task, member):
    other_org = create_org("다른 조직", "", member)
    other = create_project(org=other_org, name="다른 프로젝트", actor=member)
    with pytest.raises(ServiceError) as e:
        update_task(task, {"project": other}, actor=member, source="web", expected_version=1)
    assert "project" in e.value.errors


def test_extend_due_rules(task, member):
    today = today_kst()
    with pytest.raises(ServiceError) as e:
        extend_due(
            task, today + timedelta(days=2), "x", actor=member, source="web", expected_version=1
        )
    assert "due_date" in e.value.errors
    with pytest.raises(ServiceError) as e:
        extend_due(
            task, today + timedelta(days=5), "", actor=member, source="web", expected_version=1
        )
    assert "reason" in e.value.errors
    notes_before = task.notes
    t = extend_due(
        task, today + timedelta(days=5), "회의", actor=member, source="web", expected_version=1
    )
    assert t.due_date == today + timedelta(days=5)
    assert t.version == 2
    assert _logs(t, "due_date").last().note == "연장: 회의"
    assert t.notes == notes_before


def test_extend_sets_due_when_none(project, member):
    t = create_task(project=project, title="미정", actor=member, source="web", no_due_reason="미정")
    t = extend_due(
        t,
        today_kst() + timedelta(days=1),
        "일정 확정",
        actor=member,
        source="web",
        expected_version=t.version,
    )
    assert t.due_date == today_kst() + timedelta(days=1)
    assert t.no_due_reason == ""
    assert _logs(t, "due_date").last().note.startswith("목표일 지정: ")


def test_extend_closed_rejected(task, member):
    t = transition(task, "done", actor=member, source="web", expected_version=1)
    with pytest.raises(ServiceError) as e:
        extend_due(
            t,
            today_kst() + timedelta(days=9),
            "x",
            actor=member,
            source="web",
            expected_version=t.version,
        )
    assert "due_date" in e.value.errors


def test_idempotent_create(project, member):
    kw = dict(
        project=project,
        title="중복 방지",
        actor=member,
        source="web",
        due_date=today_kst(),
        idempotency_key="k1",
    )
    a = create_task(**kw)
    b = create_task(**kw)
    assert a.pk == b.pk
    assert Task.objects.count() == 1


def test_checklist_replace_and_done_does_not_complete_task(task, member):
    items = replace_checklist(
        task, [{"text": "a", "is_done": True}, {"text": "b", "is_done": True}], actor=member
    )
    task.refresh_from_db()
    assert len(items) == 2
    assert task.status == "todo"
    assert task.version == 1


def test_checklist_add_toggle_move_delete(task, member):
    a = checklist_add(task, "a", actor=member)
    checklist_add(task, "b", actor=member)
    c = checklist_add(task, "c", actor=member)
    checklist_toggle(a, actor=member)
    assert a.is_done
    checklist_move(c, "up", actor=member)
    assert [i.text for i in task.checklist.all()] == ["a", "c", "b"]
    checklist_delete(c, actor=member)
    assert task.checklist.count() == 2


def test_today_add_does_not_touch_task(task, member):
    before = (task.status, task.due_date, task.priority, task.version, _logs(task).count())
    today_add(member, task)
    task.refresh_from_db()
    assert (task.status, task.due_date, task.priority, task.version, _logs(task).count()) == before


def test_today_is_private_and_not_carried(task, member, admin):
    today_set_auto_pull(member, 0)
    today_add(member, task)
    assert today_view(admin)["items"] == []
    assert today_view(member, day=today_kst() + timedelta(days=1))["items"] == []


@pytest.fixture
def three(project, member):
    today = today_kst()
    near = create_task(
        project=project,
        title="가까움",
        actor=member,
        source="web",
        due_date=today + timedelta(days=3),
    )
    far = create_task(
        project=project,
        title="멀다",
        actor=member,
        source="web",
        due_date=today + timedelta(days=10),
    )
    none = create_task(
        project=project, title="기한 없음", actor=member, source="web", no_due_reason="미정"
    )
    return near, far, none


def test_today_auto_pull_and_exclude(three, member):
    near, far, _none = three
    v = today_view(member)
    assert [t.pk for t in v["items"]] == [near.pk]
    assert v["items"][0].auto_pulled is True
    assert v["counts"]["auto_pulled"] == 1

    today_exclude(member, near)
    v = today_view(member)
    assert v["items"] == []
    assert v["counts"]["excluded"] == 1

    today_restore_excluded(member)
    assert len(today_view(member)["items"]) == 1

    today_add(member, far)
    v = today_view(member)
    assert [t.pk for t in v["items"]] == [far.pk, near.pk]


def test_today_flag(three, member, admin):
    near, far, none = three
    today_add(member, far)
    m = today_membership(member)
    assert today_flag(near, m) == "auto"
    assert today_flag(far, m) == "manual"
    assert today_flag(none, m) == ""
    assert today_flag(near, today_membership(admin)) == ""


def test_today_settings(three, member):
    with pytest.raises(ServiceError) as e:
        today_set_auto_pull(member, 4)
    assert "auto_pull_days" in e.value.errors
    today_set_auto_pull(member, 0)
    assert today_view(member)["counts"]["auto_pulled"] == 0


def test_today_move_and_reorder(three, member):
    near, far, _none = three
    today_set_auto_pull(member, 0)
    today_add(member, near)
    today_add(member, far)
    assert [t.pk for t in today_view(member)["items"]] == [near.pk, far.pk]
    today_move(member, far, "up")
    assert [t.pk for t in today_view(member)["items"]] == [far.pk, near.pk]


def test_today_focus_is_first_open_and_closed_last(three, member):
    near, far, _none = three
    today_add(member, far)
    transition(far, "done", actor=member, source="web", expected_version=far.version)
    v = today_view(member)
    assert [t.pk for t in v["items"]] == [near.pk, far.pk]
    assert v["focus"].pk == near.pk


@pytest.fixture
def five(project, member):
    today = today_kst()
    _, sunday = week_bounds(today)
    made = [
        create_task(
            project=project,
            title="어제",
            actor=member,
            source="web",
            due_date=today - timedelta(days=1),
        ),
        create_task(project=project, title="오늘", actor=member, source="web", due_date=today),
        create_task(project=project, title="이번 주", actor=member, source="web", due_date=sunday),
        create_task(
            project=project,
            title="다음 주",
            actor=member,
            source="web",
            due_date=sunday + timedelta(days=3),
        ),
        create_task(
            project=project, title="미정", actor=member, source="web", no_due_reason="미정"
        ),
    ]
    return made


def test_me_view_groups_by_due(five, member, project):
    v = me_view(member)
    titles = [g["title"] for g in v["groups"]]
    assert titles == ["기한 초과", "오늘 마감", "이번 주 마감", "그 이후", "기한 미정"]
    sunday_is_today = today_kst() == week_bounds()[1]
    for g in v["groups"]:
        if sunday_is_today and g["title"] in ("오늘 마감", "이번 주 마감"):
            continue
        assert g["count"] == 1
    overdue = v["groups"][0]
    assert overdue["projects"][0]["project"] == project
    assert "total" in overdue["projects"][0] and "done" in overdue["projects"][0]


def test_me_view_filters(five, member, project):
    v = me_view(member, due="overdue")
    assert len(v["groups"]) == 1 and v["groups"][0]["count"] == 1
    assert sum(g["count"] for g in me_view(member, priority="high")["groups"]) == 0
    assert sum(g["count"] for g in me_view(member, status="blocked")["groups"]) == 0
    v = me_view(member, group="project")
    assert len(v["groups"]) == 1
    assert v["groups"][0]["title"] == project.name
    assert v["groups"][0]["flat"] is True
    v = me_view(member, status="done_today")
    assert v["completion"] is True
    assert v["groups"][0]["title"] == "오늘 완료"


def test_me_view_ungrouped_is_one_flat_list(five, member, project):
    grouped = [t for g in me_view(member)["groups"] for t in g["tasks"]]
    v = me_view(member, group="none")
    assert len(v["groups"]) == 1
    g = v["groups"][0]
    assert g["title"] == "미완료" and g["flat"] is True
    # 기한별 묶음을 이어 붙인 순서 그대로여야 토글해도 행이 안 섞인다
    assert g["tasks"] == grouped
    assert sum(x["count"] for x in me_view(member, group="none", due="overdue")["groups"]) == 1
    v = me_view(member, group="none", priority="high")
    assert [x["title"] for x in v["groups"]] == ["결과 없음"]


def test_me_view_sort_orders_inside_groups(five, member):
    yesterday, today, week, nxt, none = five
    for t, p in ((none, 9), (nxt, 8)):
        update_task(t, {"priority": p}, actor=member, source="web", expected_version=t.version)
        # Windows 시계 해상도(~15ms) 안에서 두 갱신이 같은 updated_at을 받으면 pk 역순으로 떨어진다
        time.sleep(0.02)

    def order(**kw):
        return [t.title for g in me_view(member, **kw)["groups"] for t in g["tasks"]]

    by_due = ["어제", "오늘", "이번 주", "다음 주", "미정"]
    assert order() == by_due
    assert order(sort="nonsense") == by_due
    by_pri = ["미정", "다음 주", "어제", "오늘", "이번 주"]
    assert order(group="none", sort="priority") == by_pri
    assert order(group="none", sort="updated") == ["다음 주", "미정", "이번 주", "오늘", "어제"]
    # 묶어도 하위 목록이 같은 순서여야 한다
    v = me_view(member, group="status", sort="priority")
    assert [t.title for t in v["groups"][0]["projects"][0]["tasks"]] == by_pri
    assert order(sort="priority")[:2] == ["어제", "오늘"]  # 기한별 묶음 안에서 중요도순


def test_me_view_member_scope(five, admin, member):
    v = me_view(admin, member=0)
    assert v["read_only"] is True
    assert "보기 전용" in v["hint"]
    assert sum(g["count"] for g in v["groups"]) == len(five)
    assert me_view(admin, member=member)["title"] == "팀원의 태스크"
    mine = me_view(admin)
    assert mine["title"] == "내 태스크"
    assert sum(g["count"] for g in mine["groups"]) == 0


def test_search_by_number_title_project(task, member):
    for q in (task.number, "메뉴", "학식"):
        assert task in list(search(member, q))
    transition(task, "done", actor=member, source="web", expected_version=task.version)
    assert list(search(member, "메뉴")) == []
    assert task in list(search(member, "메뉴", include_closed=True))


def test_link_exactly_one_target(task, member, project):
    with pytest.raises(ServiceError):
        add_link(actor=member, title="t", url="https://e.com")
    with pytest.raises(IntegrityError), transaction.atomic():
        Link.objects.create(
            project=project, task=task, title="t", url="https://e.com", created_by=member
        )


def test_no_due_reason_truncated_to_column_length(project, member):
    """no_due_reason은 varchar(200)이다. 자르지 않으면 Postgres에서 DataError로 500이 된다."""
    long_reason = "미" * 250
    t = create_task(
        project=project, title="기한 미정", actor=member, source="web", no_due_reason=long_reason
    )
    assert len(t.no_due_reason) == 200
    t = update_task(
        t,
        {"no_due_reason": "정" * 250},
        actor=member,
        source="web",
        expected_version=t.version,
    )
    assert len(t.no_due_reason) == 200


def test_today_view_is_scoped_to_org_membership(task, member, project):
    """조직에서 빠지면 담당으로 남은 태스크도 오늘 화면에서 보이지 않는다 (A01)."""
    from orgs.models import OrgMembership

    v = today_view(member)
    assert [t.pk for t in v["items"]] == [task.pk]

    OrgMembership.objects.filter(org=project.org, user=member).delete()
    v = today_view(member)
    assert v["items"] == []
    assert v["focus"] is None
    assert v["counts"]["my_open"] == 0
    assert v["counts"]["due_today"] == 0
    assert v["counts"]["done_7d"] == 0
    assert list(ts.visible_tasks(member)) == []


def test_today_view_manual_item_also_scoped(task, member, project):
    """직접 담은 항목(TodayItem)도 조직 범위를 따른다. auto 분기만 막으면 새어 나간다."""
    from orgs.models import OrgMembership

    today_set_auto_pull(member, 0)  # auto 분기를 끄고 manual 분기만 남긴다
    today_add(member, task)
    assert [t.pk for t in today_view(member)["items"]] == [task.pk]

    OrgMembership.objects.filter(org=project.org, user=member).delete()
    v = today_view(member)
    assert v["items"] == []
    assert v["focus"] is None
    assert today_membership(member)["manual"] == set()


def test_assignee_is_required(task, member):
    """A03: 담당자 없이는 저장되지 않는다. 오류 항목이 assignee로 표시된다."""
    with pytest.raises(ServiceError) as e:
        update_task(task, {"assignee": None}, actor=member, source="web", expected_version=1)
    assert "assignee" in e.value.errors
    task.refresh_from_db()
    assert task.assignee == member


def test_removed_member_does_not_freeze_their_tasks(task, project, member, admin, outsider):
    """멤버 관리 화면에서 담당자를 제거해도 그 태스크의 다른 항목은 고칠 수 있어야 한다.

    담당자를 새로 지정하는 것은 그대로 조직의 활성 멤버만 된다.
    """
    from orgs.models import OrgMembership
    from orgs.services import remove_member

    remove_member(OrgMembership.objects.get(org=project.org, user=member), admin)

    t = update_task(task, {"priority": 9}, actor=admin, source="web", expected_version=task.version)
    assert t.priority == 9
    t = update_task(
        t,
        {"due_date": today_kst() + timedelta(days=9)},
        actor=admin,
        source="web",
        expected_version=t.version,
    )
    assert t.assignee == member  # 담당자는 그대로 남는다(누가 하던 일인지 잃지 않는다)

    with pytest.raises(ServiceError) as e:
        update_task(
            t, {"assignee": outsider}, actor=admin, source="web", expected_version=t.version
        )
    assert "assignee" in e.value.errors
    t = update_task(t, {"assignee": admin}, actor=admin, source="web", expected_version=t.version)
    assert t.assignee == admin
