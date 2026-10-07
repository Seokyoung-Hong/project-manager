"""IMPL-PLAN-11 P2: 연결 프로젝트 화면(패널 칸·요청함 승인 탭·프로젝트 화면 표시·집계·이력)."""

from datetime import timedelta

import pytest
from django.utils import timezone

from accounts.models import User
from common.dates import today_kst
from orgs.models import OrgMembership
from orgs.services import add_team_member, create_team
from projects.services import create_project, project_stats
from tasks import services as ts
from tasks.models import TaskProject

pytestmark = pytest.mark.django_db
HX = {"HX-Request": "true"}


@pytest.fixture
def w(org, admin, member):
    other = User.objects.create_user(
        "other",
        password="pw12345678",
        display_name="바깥",
        discord_user_id="7",
        discord_linked_at=timezone.now(),
    )
    OrgMembership.objects.create(org=org, user=other, role="member")
    team = create_team(org=org, name="비밀팀", actor=admin)
    add_team_member(team, member, admin)
    secret = create_project(org=org, name="비공개", actor=admin, teams=[team], visibility="teams")
    public = create_project(org=org, name="공개", actor=admin)
    task = ts.create_task(
        project=secret,
        title="Swagger 노출",
        actor=member,
        source="web",
        due_date=today_kst() + timedelta(days=2),
    )
    return type("W", (), dict(other=other, secret=secret, public=public, task=task))


def test_panel_link_shows_warning_then_requests_approval(client, w, member):
    client.force_login(member)
    url = f"/tasks/{w.task.pk}/projects"
    r = client.post(url, {"project": w.public.pk}, headers=HX)
    body = r.content.decode()
    assert "⚠" in body and "열람자" in body and "승인 요청 보내기" in body
    assert not TaskProject.objects.exists()
    r = client.post(url, {"project": w.public.pk, "confirm": "1"}, headers=HX)
    assert "승인 대기" in r.content.decode()
    assert TaskProject.objects.get().status == "pending"


def test_requests_tab_and_approve(client, w, member, admin):
    ts.link_project(w.task, w.public, actor=member, confirm_widening=True)
    client.force_login(member)
    assert "연결 승인" not in client.get("/requests").content.decode()  # 승인자가 아니면 탭이 없다
    client.force_login(admin)
    body = client.get("/requests?tab=links").content.decode()
    assert "Swagger 노출" in body and "공개" in body
    r = client.post(f"/tasks/{w.task.pk}/projects/{w.public.pk}/approve")
    assert r.status_code == 302 and r["Location"].endswith("tab=links")
    assert TaskProject.objects.get().status == "active"
    # 승인 뒤 바깥 멤버도 공개 프로젝트 보드·목록·달력에서 본다.
    client.force_login(w.other)
    for view in ("board", "list", "calendar"):
        body = client.get(f"/projects/{w.public.pk}?view={view}").content.decode()
        assert "Swagger 노출" in body, view
    assert "↔" in client.get(f"/projects/{w.public.pk}?view=list").content.decode()


def test_member_cannot_approve_in_panel(client, w, member):
    ts.link_project(w.task, w.public, actor=member, confirm_widening=True)
    client.force_login(member)
    r = client.post(f"/tasks/{w.task.pk}/projects/{w.public.pk}/approve", headers=HX)
    assert "관리자" in r.content.decode()
    assert TaskProject.objects.get().status == "pending"


def test_stats_include_links_and_history_label(client, w, member, admin):
    link = ts.link_project(w.task, w.public, actor=member, confirm_widening=True)
    ts.approve_link(link, actor=admin)
    assert project_stats(w.public)["open"] == 1 and project_stats(w.secret)["open"] == 1
    client.force_login(admin)
    body = client.get(f"/tasks/{w.task.pk}/panel", headers=HX).content.decode()
    assert "연결 프로젝트" in body and "열람 확대 승인" in body
    org_page = client.get(f"/orgs/{w.task.project.org_id}").content.decode()
    assert "조직 합계에는 한 번만" in org_page


def test_channel_notice_goes_to_primary(gh_settings, w, admin, member):
    from github import notify
    from github.models import RepoConnection
    from tasks.models import Notice

    org = w.secret.org
    org.settings = {"notify.github_channel_events": ["pr_merged"]}
    org.save(update_fields=["settings"])
    w.secret.discord_channel_id = "111"
    w.secret.save(update_fields=["discord_channel_id"])
    w.public.discord_channel_id = "222"
    w.public.save(update_fields=["discord_channel_id"])
    conn = RepoConnection.objects.create(
        project=w.public, url="u", full_name="o/r", created_by=admin
    )
    notify.channel(conn, "pr_merged", "머지", w.task)
    assert list(Notice.objects.values_list("channel_id", flat=True)) == ["111"]


@pytest.fixture
def gh_settings(settings):
    settings.GITHUB_ENABLED = True
    return settings
