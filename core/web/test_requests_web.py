import pytest
from django.test import Client

from orgs.models import TeamMembership
from tasks.models import Task, WorkRequest
from tasks.work_requests import create_request, request_assign

pytestmark = pytest.mark.django_db


@pytest.fixture
def logged(client, member):
    client.login(username="member1", password="pw12345678")
    return client


@pytest.fixture
def admin_client(admin):
    c = Client()  # logged와 같은 client를 쓰면 세션이 덮어씌워진다
    c.login(username="admin1", password="pw12345678")
    return c


@pytest.fixture
def req_to_team(org, team, admin):
    return create_request(
        org=org, kind="work", title="로그인 개선", actor=admin, source="web", team=team
    )


def test_pages_ok(logged, req_to_team):
    assert logged.get("/requests").status_code == 200
    assert logged.get("/requests?tab=sent").status_code == 200
    assert logged.get("/requests/new").status_code == 200
    body = logged.get(f"/requests/{req_to_team.pk}").content.decode()
    assert "수락" in body and "거절" in body
    assert "로그인 개선" in logged.get("/requests").content.decode()


def test_detail_404_for_outsider(client, outsider, req_to_team):
    client.login(username="outsider", password="pw12345678")
    assert client.get(f"/requests/{req_to_team.pk}").status_code == 404
    assert client.post(f"/requests/{req_to_team.pk}/decline").status_code == 404
    assert client.get("/requests/99999").status_code == 404


def test_new_request_creates(logged, org, admin):
    r = logged.post(
        "/requests/new",
        {
            "org": org.pk,
            "kind": "general",
            "target": "user",
            "user": admin.pk,
            "title": "검토 부탁",
            "body": "봐 주세요",
        },
    )
    req = WorkRequest.objects.get(title="검토 부탁")
    assert r.status_code == 302 and r["Location"] == f"/requests/{req.pk}"
    assert req.source == "web" and req.to_user == admin


def test_new_request_error_shown(logged, org):
    r = logged.post(
        "/requests/new", {"org": org.pk, "kind": "general", "target": "team", "title": ""}
    )
    assert r.status_code == 200 and "제목을 입력하세요" in r.content.decode()


def test_accept_work_creates_task(logged, req_to_team, project, member):
    r = logged.post(f"/requests/{req_to_team.pk}/accept", {"project": project.pk, "note": "네"})
    assert r.status_code == 302
    req_to_team.refresh_from_db()
    assert req_to_team.status == "accepted" and req_to_team.task.assignee == member
    assert Task.objects.filter(pk=req_to_team.task_id, project=project).exists()
    assert (
        f"/tasks/{req_to_team.task_id}"
        in logged.get(f"/requests/{req_to_team.pk}").content.decode()
    )


def test_accept_work_without_project_fails(logged, req_to_team):
    logged.post(f"/requests/{req_to_team.pk}/accept", {})
    req_to_team.refresh_from_db()
    assert req_to_team.status == "pending"


def test_decline(logged, req_to_team):
    logged.post(f"/requests/{req_to_team.pk}/decline", {"note": "바쁨"})
    req_to_team.refresh_from_db()
    assert req_to_team.status == "declined" and req_to_team.response_note == "바쁨"


def test_cancel_only_requester(logged, admin_client, req_to_team):
    logged.post(f"/requests/{req_to_team.pk}/cancel")
    req_to_team.refresh_from_db()
    assert req_to_team.status == "pending"
    admin_client.post(f"/requests/{req_to_team.pk}/cancel")
    req_to_team.refresh_from_db()
    assert req_to_team.status == "cancelled"


def test_complete_general(logged, org, team, admin):
    req = create_request(
        org=org, kind="general", title="확인", actor=admin, source="web", team=team
    )
    logged.post(f"/requests/{req.pk}/accept")
    assert "완료" in logged.get(f"/requests/{req.pk}").content.decode()
    logged.post(f"/requests/{req.pk}/complete")
    req.refresh_from_db()
    assert req.status == "done"


def test_nav_badge_and_panel_pending(logged, req_to_team, task, admin):
    assert 'class="badge danger">1<' in logged.get("/requests").content.decode()
    request_assign(task, admin, task.assignee, "web")
    assert "님 수락 대기" in logged.get(f"/tasks/{task.pk}").content.decode()


def test_team_lead_permission(logged, admin_client, team, member):
    url = f"/teams/{team.pk}/members/{member.pk}/lead"
    assert logged.post(url, {"lead": "1"}).status_code in (302, 404)
    assert not TeamMembership.objects.get(team=team, user=member).is_lead
    r = admin_client.post(url, {"lead": "1"})
    assert r.status_code == 302
    assert TeamMembership.objects.get(team=team, user=member).is_lead
    assert "팀장" in admin_client.get(f"/teams/{team.pk}").content.decode()
    admin_client.post(url, {"lead": "0"})
    assert not TeamMembership.objects.get(team=team, user=member).is_lead


# ---------- 팀원용 팀 화면 ----------


def test_member_sees_team_list_and_detail_with_lead(client, org, team, admin, member):
    from orgs.services import set_team_lead

    set_team_lead(team, member, True, admin)
    client.login(username="member1", password="pw12345678")
    body = client.get(f"/orgs/{org.pk}/teams").content.decode()
    assert team.name in body and "팀원" in body and "초대" not in body
    body = client.get(f"/teams/{team.pk}").content.decode()
    assert "팀장" in body
    assert "팀장 지정" not in body and "삭제" not in body  # 관리 버튼 없음
    assert (
        client.post(f"/teams/{team.pk}/members/{member.pk}/lead", {"lead": "0"}).status_code == 404
    )


def test_member_can_request_other_team_from_team_page(client, org, admin, member):
    from orgs.services import create_team

    other = create_team(org=org, name="디자인", actor=admin)
    client.login(username="member1", password="pw12345678")
    body = client.get(f"/teams/{other.pk}").content.decode()
    assert "이 팀에 요청 보내기" in body
    form = client.get(f"/requests/new?org={org.pk}&target=team&team={other.pk}").content.decode()
    assert f'value="{other.pk}" selected' in form


def test_outsider_cannot_see_team(client, team, outsider):
    client.login(username="outsider", password="pw12345678")
    assert client.get(f"/teams/{team.pk}").status_code == 404
