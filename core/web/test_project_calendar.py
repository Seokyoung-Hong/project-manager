from datetime import date

import pytest
from django.urls import reverse

from projects.models import Milestone
from tasks import services as ts

pytestmark = pytest.mark.django_db


@pytest.fixture
def logged(client, member):
    client.login(username="member1", password="pw12345678")
    return client


@pytest.fixture
def cal_data(project, member, admin):
    t = ts.create_task(
        project=project,
        title="카드뉴스 게시",
        actor=member,
        source="web",
        due_date=date(2031, 3, 10),
    )
    Milestone.objects.create(
        project=project, name="3월 캠페인 마감", target_date=date(2031, 3, 20), created_by=admin
    )
    return t


def test_calendar_view_200_with_due_and_milestone(logged, project, cal_data):
    r = logged.get(
        reverse("project_detail", args=[project.pk]), {"view": "calendar", "month": "2031-03"}
    )
    assert r.status_code == 200
    html = r.content.decode()
    assert "2031년 3월" in html and "카드뉴스 게시" in html and "3월 캠페인 마감" in html
    assert f"/tasks/{cal_data.pk}" in html


def test_calendar_month_navigation(logged, project, cal_data):
    r = logged.get(reverse("project_calendar", args=[project.pk]), {"month": "2031-04"})
    html = r.content.decode()
    assert "2031년 4월" in html and "카드뉴스 게시" not in html
    assert "month=2031-03" in html and "month=2031-05" in html
    r = logged.get(reverse("project_calendar", args=[project.pk]), {"month": "2031-12"})
    assert "month=2032-01" in r.content.decode()


def test_calendar_closed_task_dimmed(logged, project, cal_data):
    cal_data.status = "cancelled"
    cal_data.save(update_fields=["status"])
    html = logged.get(
        reverse("project_calendar", args=[project.pk]), {"month": "2031-03"}
    ).content.decode()
    assert "pcal-task t12 closed" in html


def test_calendar_bad_month_falls_back(logged, project):
    assert (
        logged.get(reverse("project_calendar", args=[project.pk]), {"month": "zzz"}).status_code
        == 200
    )


def test_calendar_outsider_404(client, outsider, project):
    client.login(username="outsider", password="pw12345678")
    assert client.get(reverse("project_calendar", args=[project.pk])).status_code == 404
    assert (
        client.get(reverse("project_detail", args=[project.pk]), {"view": "calendar"}).status_code
        == 404
    )


def test_default_view_calendar(logged, project):
    project.org.settings = {**(project.org.settings or {}), "project.default_view": "calendar"}
    project.org.save()
    html = logged.get(reverse("project_detail", args=[project.pk])).content.decode()
    assert 'id="project-calendar"' in html
