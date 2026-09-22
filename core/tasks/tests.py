from datetime import date, timedelta

import pytest
from django.db import IntegrityError, transaction
from django.utils import timezone

from common.dates import today_kst, week_bounds
from common.errors import ConflictError, ServiceError
from orgs.services import create_org
from projects.services import archive_project, create_project
from reports.services import weekly
from tasks import services as ts
from tasks.models import ChangeLog, ChecklistItem, Link, Task
from tasks.services import (
    add_link,
    checklist_add,
    checklist_delete,
    checklist_move,
    checklist_toggle,
    create_task,
    delete_task,
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


def _set(org, **settings):
    org.settings = settings
    org.save(update_fields=["settings"])


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
    sunday_is_today = today_kst() == week_bounds()[1]
    expected = ["기한 초과", "오늘 마감"]
    if not sunday_is_today:
        expected.append("이번 주 마감")
    expected.extend(["그 이후", "기한 미정"])
    assert titles == expected
    counts = {g["title"]: g["count"] for g in v["groups"]}
    assert counts["오늘 마감"] == (2 if sunday_is_today else 1)
    assert all(count == 1 for title, count in counts.items() if title != "오늘 마감")
    overdue = v["groups"][0]
    assert overdue["projects"][0]["project"] == project
    assert "total" in overdue["projects"][0] and "done" in overdue["projects"][0]


def test_me_view_omits_empty_week_group_on_sunday(project, member, monkeypatch):
    sunday = date(2026, 9, 20)
    monkeypatch.setattr(ts, "today_kst", lambda: sunday)
    monkeypatch.setattr(ts, "overdue_before", lambda org: sunday)
    create_task(
        project=project,
        title="일요일 마감 A",
        actor=member,
        source="web",
        due_date=sunday,
    )
    create_task(
        project=project,
        title="일요일 마감 B",
        actor=member,
        source="web",
        due_date=sunday,
    )
    create_task(
        project=project,
        title="다음 주 마감",
        actor=member,
        source="web",
        due_date=sunday + timedelta(days=3),
    )

    groups = me_view(member)["groups"]
    assert [g["title"] for g in groups] == ["오늘 마감", "그 이후"]
    assert groups[0]["count"] == 2


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
    # Windows의 시계 해상도(~16ms)로는 연속 두 번의 수정이 같은 updated_at을 받을 수 있다.
    # "최근 수정순"을 검사하려면 시각이 실제로 달라야 하므로 여기서 못 박는다.
    now = timezone.now()
    for i, t in enumerate((yesterday, today, week, none, nxt)):
        Task.objects.filter(pk=t.pk).update(updated_at=now + timedelta(seconds=i))

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


# ---------- IMPL-PLAN-4 §4.1 태스크 규칙 ----------


def test_priority_cap_blocks_member_allows_owner(project, member, admin, org):
    """project.owners=[admin]이므로 admin은 프로젝트 관리자다."""
    _set(org, **{"task.priority_cap": 5})
    with pytest.raises(ServiceError) as e:
        create_task(
            project=project,
            title="상한 초과",
            actor=member,
            source="web",
            due_date=today_kst(),
            priority=8,
        )
    assert "priority" in e.value.errors
    t = create_task(
        project=project,
        title="관리자는 됨",
        actor=admin,
        source="web",
        due_date=today_kst(),
        priority=8,
    )
    assert t.priority == 8


def test_priority_cap_default_off(project, member):
    t = create_task(
        project=project,
        title="기본값",
        actor=member,
        source="web",
        due_date=today_kst(),
        priority=10,
    )
    assert t.priority == 10


def test_due_required_blocks_no_due_reason(project, member, org):
    _set(org, **{"task.due_required": True})
    with pytest.raises(ServiceError) as e:
        create_task(
            project=project, title="기한 필수", actor=member, source="web", no_due_reason="미정"
        )
    assert "due_date" in e.value.errors


def test_ai_priority_cap_blocks_mcp_only(project, member, org):
    _set(org, **{"ai.priority_cap": 6})
    with pytest.raises(ServiceError) as e:
        create_task(
            project=project,
            title="AI 상한",
            actor=member,
            source="mcp",
            due_date=today_kst(),
            priority=9,
        )
    assert "priority" in e.value.errors
    t = create_task(
        project=project,
        title="웹은 통과",
        actor=member,
        source="web",
        due_date=today_kst(),
        priority=9,
    )
    assert t.priority == 9


def test_require_done_when(project, member, org):
    _set(org, **{"task.require_done_when": True})
    with pytest.raises(ServiceError) as e:
        create_task(
            project=project, title="완료조건 필요", actor=member, source="web", due_date=today_kst()
        )
    assert "done_when" in e.value.errors
    t = create_task(
        project=project,
        title="완료조건 있음",
        actor=member,
        source="web",
        due_date=today_kst(),
        done_when="다 됐다",
    )
    assert t.done_when == "다 됐다"


def test_default_priority_from_settings(project, member, org):
    _set(org, **{"task.default_priority": 3})
    t = create_task(
        project=project, title="기본 중요도", actor=member, source="web", due_date=today_kst()
    )
    assert t.priority == 3


def test_doing_limit_block_mode(project, member, org):
    _set(org, **{"task.doing_limit": 1, "task.doing_limit_mode": "block"})
    a = create_task(project=project, title="a", actor=member, source="web", due_date=today_kst())
    b = create_task(project=project, title="b", actor=member, source="web", due_date=today_kst())
    transition(a, "doing", actor=member, source="web", expected_version=1)
    with pytest.raises(ServiceError) as e:
        transition(b, "doing", actor=member, source="web", expected_version=1)
    assert "status" in e.value.errors


def test_doing_limit_warn_mode_does_not_block(project, member, org):
    _set(org, **{"task.doing_limit": 1, "task.doing_limit_mode": "warn"})
    a = create_task(project=project, title="a", actor=member, source="web", due_date=today_kst())
    b = create_task(project=project, title="b", actor=member, source="web", due_date=today_kst())
    transition(a, "doing", actor=member, source="web", expected_version=1)
    t = transition(b, "doing", actor=member, source="web", expected_version=1)
    assert t.status == "doing"


def test_review_required(task, member, org):
    _set(org, **{"task.review_required": True})
    t = transition(task, "doing", actor=member, source="web", expected_version=1)
    with pytest.raises(ServiceError) as e:
        transition(t, "done", actor=member, source="web", expected_version=t.version)
    assert "status" in e.value.errors
    t = transition(t, "review", actor=member, source="web", expected_version=t.version)
    t = transition(t, "done", actor=member, source="web", expected_version=t.version)
    assert t.status == "done"


def test_self_review_off_blocks_own_review(task, member, admin, org):
    _set(org, **{"task.review_required": True, "task.self_review": False})
    t = transition(task, "doing", actor=member, source="web", expected_version=1)
    t = transition(t, "review", actor=member, source="web", expected_version=t.version)
    with pytest.raises(ServiceError) as e:
        transition(t, "done", actor=member, source="web", expected_version=t.version)
    assert "status" in e.value.errors
    t = transition(t, "done", actor=admin, source="web", expected_version=t.version)
    assert t.status == "done"


def test_reopen_reason_required(task, member, org):
    _set(org, **{"task.reopen_reason_required": True})
    t = transition(task, "done", actor=member, source="web", expected_version=1)
    with pytest.raises(ServiceError) as e:
        transition(t, "todo", actor=member, source="web", expected_version=t.version)
    assert "reason" in e.value.errors
    t = transition(
        t, "todo", actor=member, source="web", reason="다시 봐야 함", expected_version=t.version
    )
    assert t.status == "todo"


def test_cancel_reason_required(task, member, org):
    _set(org, **{"task.cancel_reason_required": True})
    with pytest.raises(ServiceError) as e:
        transition(task, "cancelled", actor=member, source="web", expected_version=1)
    assert "reason" in e.value.errors
    t = transition(
        task, "cancelled", actor=member, source="web", reason="필요 없어짐", expected_version=1
    )
    assert t.status == "cancelled"


def test_assignee_change_reason_required(task, member, admin, org):
    _set(org, **{"task.assignee_change_reason": True})
    with pytest.raises(ServiceError) as e:
        update_task(task, {"assignee": admin}, actor=member, source="web", expected_version=1)
    assert "reason" in e.value.errors
    t = update_task(
        task, {"assignee": admin}, actor=member, source="web", reason="휴가", expected_version=1
    )
    assert t.assignee == admin
    assert _logs(t, "assignee").last().note == "휴가"


def test_due_change_reason_required(task, member, org):
    _set(org, **{"task.due_change_reason": True})
    new_due = today_kst() + timedelta(days=1)
    with pytest.raises(ServiceError) as e:
        update_task(task, {"due_date": new_due}, actor=member, source="web", expected_version=1)
    assert "reason" in e.value.errors
    t = update_task(
        task,
        {"due_date": new_due},
        actor=member,
        source="web",
        reason="일정 조정",
        expected_version=1,
    )
    assert t.due_date == new_due


def test_overdue_grace_days_delays_counts(project, member, org):
    create_task(
        project=project,
        title="살짝 지남",
        actor=member,
        source="web",
        due_date=today_kst() - timedelta(days=2),
    )
    assert today_view(member)["counts"]["overdue"] == 1
    _set(org, **{"task.overdue_grace_days": 3})
    assert today_view(member)["counts"]["overdue"] == 0


# ---------- IMPL-PLAN-4 §4.4 AI 정책 (source == "mcp"에만) ----------


def test_ai_create_task_deny_blocks_mcp_only(project, member, org):
    _set(org, **{"ai.create_task": "deny"})
    with pytest.raises(ServiceError):
        create_task(
            project=project, title="AI 생성", actor=member, source="mcp", due_date=today_kst()
        )
    t = create_task(
        project=project, title="웹 생성", actor=member, source="web", due_date=today_kst()
    )
    assert t.title == "웹 생성"


def test_ai_edit_text_deny_blocks_update_text_and_checklist(task, member, org):
    _set(org, **{"ai.edit_text": "deny"})
    with pytest.raises(ServiceError):
        update_text(task, "notes", "메모", actor=member, source="mcp")
    t = update_text(task, "notes", "메모", actor=member, source="web")
    assert t.notes == "메모"
    with pytest.raises(ServiceError):
        replace_checklist(task, [{"text": "a"}], actor=member, source="mcp")
    items = replace_checklist(task, [{"text": "a"}], actor=member, source="web")
    assert len(items) == 1


def test_ai_change_assignee_deny(task, member, admin, org):
    _set(org, **{"ai.change_assignee": "deny"})
    with pytest.raises(ServiceError):
        update_task(task, {"assignee": admin}, actor=member, source="mcp", expected_version=1)
    t = update_task(task, {"assignee": admin}, actor=member, source="web", expected_version=1)
    assert t.assignee == admin


def test_ai_change_due_deny_update_task_and_extend_due(task, member, org):
    _set(org, **{"ai.change_due": "deny"})
    new_due = today_kst() + timedelta(days=1)
    with pytest.raises(ServiceError):
        update_task(task, {"due_date": new_due}, actor=member, source="mcp", expected_version=1)
    t = update_task(task, {"due_date": new_due}, actor=member, source="web", expected_version=1)
    assert t.due_date == new_due
    with pytest.raises(ServiceError):
        extend_due(
            t,
            new_due + timedelta(days=1),
            "사유",
            actor=member,
            source="mcp",
            expected_version=t.version,
        )
    t = extend_due(
        t,
        new_due + timedelta(days=1),
        "사유",
        actor=member,
        source="web",
        expected_version=t.version,
    )
    assert t.due_date == new_due + timedelta(days=1)


def test_ai_change_priority_deny(task, member, org):
    _set(org, **{"ai.change_priority": "deny"})
    with pytest.raises(ServiceError):
        update_task(task, {"priority": 8}, actor=member, source="mcp", expected_version=1)
    t = update_task(task, {"priority": 8}, actor=member, source="web", expected_version=1)
    assert t.priority == 8


def test_ai_transition_open_deny(task, member, org):
    _set(org, **{"ai.transition_open": "deny"})
    with pytest.raises(ServiceError):
        transition(task, "doing", actor=member, source="mcp", expected_version=1)
    t = transition(task, "doing", actor=member, source="web", expected_version=1)
    assert t.status == "doing"


def test_ai_close_task_deny(task, member, org):
    _set(org, **{"ai.close_task": "deny"})
    with pytest.raises(ServiceError):
        transition(task, "done", actor=member, source="mcp", expected_version=1)
    t = transition(task, "done", actor=member, source="web", expected_version=1)
    assert t.status == "done"


def test_ai_reopen_task_deny(task, member, org):
    _set(org, **{"ai.reopen_task": "deny"})
    t = transition(task, "done", actor=member, source="web", expected_version=1)
    with pytest.raises(ServiceError):
        transition(t, "todo", actor=member, source="mcp", expected_version=t.version)
    t = transition(t, "todo", actor=member, source="web", expected_version=t.version)
    assert t.status == "todo"


def test_ai_enabled_off_blocks_all_mcp_writes(project, member, org):
    _set(org, **{"ai.enabled": False})
    with pytest.raises(ServiceError):
        create_task(
            project=project, title="AI 꺼짐", actor=member, source="mcp", due_date=today_kst()
        )
    t = create_task(
        project=project, title="웹은 됨", actor=member, source="web", due_date=today_kst()
    )
    assert t.title == "웹은 됨"


def test_ai_denied_never_fires_for_non_mcp_source_or_actor_none(project, member, org):
    """모든 ai.*가 deny·꺼짐이어도 mcp가 아닌 source는 절대 걸리지 않는다. GitHub 웹훅(actor=None)도."""
    _set(
        org,
        **{
            "ai.enabled": False,
            "ai.create_task": "deny",
            "ai.edit_text": "deny",
            "ai.change_assignee": "deny",
            "ai.change_due": "deny",
            "ai.change_priority": "deny",
            "ai.transition_open": "deny",
            "ai.close_task": "deny",
            "ai.reopen_task": "deny",
        },
    )
    for src in ("web", "dc", "api", "gh"):
        t = create_task(
            project=project, title=f"{src} 통과", actor=member, source=src, due_date=today_kst()
        )
        assert t.title == f"{src} 통과"
    t2 = transition(t, "doing", actor=None, source="gh", expected_version=t.version)
    assert t2.status == "doing"


def test_delete_task_member_blocked_admin_allowed_and_logged(task, member, admin, org):
    with pytest.raises(ServiceError):
        delete_task(task, actor=member)
    number, title, task_id = task.number, task.title, task.pk
    delete_task(task, actor=admin)
    assert not Task.objects.filter(pk=task_id).exists()
    log = ChangeLog.objects.get(target_type="org", target_id=org.pk, field="delete")
    assert number in log.new_value and title in log.new_value
    assert log.actor == admin


def test_delete_task_removes_checklist_and_links(task, admin):
    item = checklist_add(task, "체크", actor=admin)
    link = add_link(actor=admin, task=task, title="문서", url="https://example.com")
    delete_task(task, actor=admin)
    assert not ChecklistItem.objects.filter(pk=item.pk).exists()
    assert not Link.objects.filter(pk=link.pk).exists()


def test_delete_task_ai_delete_default_deny_then_allow(task, admin, org):
    with pytest.raises(ServiceError):
        delete_task(task, actor=admin, source="mcp")  # 기본값(deny)
    _set(org, **{"ai.delete": "allow"})
    delete_task(task, actor=admin, source="mcp")
    assert not Task.objects.filter(pk=task.pk).exists()


def test_default_settings_regression_full_lifecycle(project, member, admin):
    """설정을 전혀 건드리지 않은 조직은 이번 라운드로 기존 흐름이 그대로 통과한다."""
    t = create_task(
        project=project,
        title="기본값 회귀",
        actor=member,
        source="web",
        due_date=today_kst(),
        priority=10,
    )
    assert t.priority == 10
    t = transition(t, "doing", actor=member, source="web", expected_version=t.version)
    t = transition(t, "done", actor=member, source="web", expected_version=t.version)
    assert t.status == "done"
    t = transition(t, "todo", actor=member, source="web", expected_version=t.version)
    assert t.status == "todo"
    t = update_task(t, {"assignee": admin}, actor=member, source="web", expected_version=t.version)
    assert t.assignee == admin
