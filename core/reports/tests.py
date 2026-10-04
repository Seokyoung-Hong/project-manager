from datetime import datetime, timedelta

import pytest

from common.dates import KST, last_week_start, today_kst, week_bounds
from reports.services import org_status, weekly
from tasks.models import ChangeLog
from tasks.services import create_task, transition

pytestmark = pytest.mark.django_db

WEEKLY_KEYS = {
    "org",
    "period_start",
    "period_end",
    "today",
    "completed",
    "reopened",
    "due_this_week",
    "overdue",
    "blocked",
    "by_project",
    "counts",
    "members",
}
COUNT_KEYS = {
    "completed",
    "reopened",
    "due_this_week",
    "overdue",
    "blocked",
    "open",
    "review",
    "no_due",
}


def test_weekly_counts_completed_once_per_task(org, task, member):
    t = transition(task, "done", actor=member, source="web", expected_version=1)
    t = transition(t, "todo", actor=member, source="web", expected_version=t.version)
    t = transition(t, "done", actor=member, source="web", expected_version=t.version)
    ws = last_week_start()
    moved = datetime.combine(ws + timedelta(days=2), datetime.min.time(), tzinfo=KST).replace(
        hour=12
    )
    ChangeLog.objects.filter(target_type="task", target_id=t.pk, field="status").update(
        created_at=moved
    )
    data = weekly(org, ws)
    assert data["counts"]["completed"] == 1
    assert data["counts"]["reopened"] == 1
    assert data["completed"][0]["id"] == t.pk


def test_weekly_rejects_non_monday(org):
    monday, _ = week_bounds()
    with pytest.raises(ValueError):
        weekly(org, monday + timedelta(days=1))


def test_weekly_shape(org, project, task):
    data = weekly(org, last_week_start())
    assert set(data) == WEEKLY_KEYS
    assert set(data["counts"]) == COUNT_KEYS
    assert "status" in data["by_project"][0]["project"]


def test_org_status_counts(project, member, admin):
    today = today_kst()
    create_task(
        project=project,
        title="어제",
        actor=member,
        source="web",
        due_date=today - timedelta(days=1),
    )
    create_task(project=project, title="오늘", actor=member, source="web", due_date=today)
    create_task(project=project, title="미정", actor=member, source="web", no_due_reason="미정")
    blocked = create_task(project=project, title="막힘", actor=member, source="web", due_date=today)
    transition(
        blocked,
        "blocked",
        actor=member,
        source="web",
        reason="서류",
        expected_version=blocked.version,
    )
    st = org_status(project.org)
    assert st["counts"]["open"] == 4
    assert st["counts"]["overdue"] == 1
    assert st["counts"]["no_due"] == 1
    assert st["counts"]["blocked"] == 1
    assert st["counts"]["due_this_week"] >= 1
    assert len(st["by_project"][0]["owners"]) == 1
    assert "status" in st["by_project"][0]
    assert st["by_assignee"][0]["blocked"] == 1
