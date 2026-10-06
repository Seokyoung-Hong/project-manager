"""슬래시 명령용 봇 엔드포인트(IMPL-PLAN-3). 행위자는 항상 연결된 사람이고 봇 토큰은 경로일 뿐이다."""

from datetime import timedelta

import pytest
from django.core.cache import cache

from accounts.models import ApiToken, User
from common.dates import today_kst
from common.errors import ServiceError
from orgs.models import OrgMembership
from orgs.services import set_team_channel
from projects.services import set_project_channel
from tasks.models import ChangeLog
from tasks.services import create_task

DC = "/api/integrations/discord"
BODY = {"discord_user_id": "111"}  # member 픽스처

pytestmark = pytest.mark.django_db


@pytest.fixture(autouse=True)
def _fresh_throttle():
    """UserRateThrottle(60/m)은 locmem 캐시에 user pk로 센다. SQLite는 pk 시퀀스를 되돌리므로
    이 파일의 봇 계정(pk 1)이 뒤에 도는 api/tests.py의 member(pk 1)와 같은 통을 쓴다."""
    cache.clear()
    yield
    cache.clear()


@pytest.fixture
def bot_token(db):
    bot = User.objects.create_user("discord-bot", password="pw12345678", display_name="유달리 봇")
    _, raw = ApiToken.issue(bot, "봇", "bot")
    return raw


@pytest.fixture
def post(client, bot_token):
    def _post(path, body=None):
        return client.post(
            f"{DC}{path}",
            data={**BODY, **(body or {})},
            content_type="application/json",
            headers={"Authorization": f"Bearer {bot_token}"},
        )

    return _post


# ---------- 서비스 ----------


def test_channel_services_require_admin_and_clear_on_empty(team, project, admin, member):
    with pytest.raises(ServiceError):
        set_team_channel(team, "123", member)
    with pytest.raises(ServiceError):
        set_project_channel(project, "123", member)
    # 새 채널은 권한 밖 확인(orgs.channels.connect)을 거쳐야 한다 — 직접 적으면 거절한다
    with pytest.raises(ServiceError):
        set_team_channel(team, "123", admin)
    assert set_team_channel(team, " 123 ", admin, checked=True).discord_channel_id == "123"
    assert set_project_channel(project, "456", admin, checked=True).discord_channel_id == "456"
    assert set_team_channel(team, "", admin).discord_channel_id == ""
    assert set_project_channel(project, "", admin).discord_channel_id == ""


# ---------- 자동완성 목록 ----------


def test_lists_follow_the_actor_scope(post, org, team, project, task, member, outsider):
    assert [p["name"] for p in post("/projects").json()] == ["학식 API"]
    assert [t["name"] for t in post("/teams").json()] == ["백엔드"]
    assert [m["display_name"] for m in post("/members").json()] == ["관리자", "팀원"]
    mine = post("/mytasks").json()
    assert [t["number"] for t in mine] == [task.number]
    # 조직에서 빠지면 전부 빈 목록이다(자동완성은 fail closed).
    OrgMembership.objects.filter(org=org, user=member).delete()
    assert post("/projects").json() == []
    assert post("/teams").json() == []
    assert post("/mytasks").json() == []


def test_mytasks_is_only_my_open_tasks_by_due(post, project, member, admin, task):
    create_task(project=project, title="남의 일", actor=admin, source="web", no_due_reason="미정")
    soon = create_task(
        project=project,
        title="급한 일",
        actor=member,
        source="web",
        due_date=today_kst() + timedelta(days=1),
    )
    undated = create_task(
        project=project, title="기한 없음", actor=member, source="web", no_due_reason="미정"
    )
    assert [t["id"] for t in post("/mytasks").json()] == [soon.pk, task.pk, undated.pk]


def test_unlinked_actor_gets_404_on_lists(post):
    r = post("/projects", {"discord_user_id": "424242"})
    assert r.status_code == 404
    assert "연결" in r.json()["detail"]


# ---------- 태스크 생성·편집 ----------


def test_create_task_passes_core_validation_through(post, project, member):
    r = post("/tasks", {"project_id": project.pk, "title": "새 일"})
    assert r.status_code == 400
    assert r.json()["detail"]["no_due_reason"] == "기한이 없으면 사유를 입력하세요."
    r = post("/tasks", {"project_id": project.pk, "title": "새 일", "no_due_reason": "미정"})
    assert r.status_code == 200
    t = r.json()["task"]
    assert t["assignee"]["id"] == member.pk  # 담당자 생략 → 본인
    log = ChangeLog.objects.get(target_type="task", target_id=t["id"], field="created")
    assert (log.actor_id, log.source) == (member.pk, "dc")


def test_create_task_in_foreign_project_is_404(post, member, outsider):
    from orgs.services import create_org
    from projects.services import create_project

    other = create_org("남의 조직", "", outsider)
    p = create_project(org=other, name="B", actor=outsider, owners=[outsider], status="active")
    assert (
        post("/tasks", {"project_id": p.pk, "title": "x", "no_due_reason": "y"}).status_code == 404
    )


def test_update_task_changes_only_what_was_sent(post, task, admin):
    r = post(f"/tasks/{task.pk}/update", {"priority": 8, "assignee_id": admin.pk, "제목": "무시"})
    assert r.status_code == 200
    t = r.json()["task"]
    # 팀원이 남에게 넘기면 바로 바뀌지 않고 받는 사람의 수락을 기다린다.
    assert (t["priority"], t["assignee"]["id"], t["title"]) == (8, task.assignee_id, task.title)
    assert t["pending_assignee"]["id"] == admin.pk
    assert t["version"] == 2
    r = post(f"/tasks/{task.pk}/update", {"title": "새 제목", "next_action": "다음"})
    assert (r.json()["task"]["title"], r.json()["task"]["version"]) == ("새 제목", 2)
    assert post(f"/tasks/{task.pk}/update", {}).status_code == 200


def test_update_task_unknown_assignee_is_400(post, task):
    assert post(f"/tasks/{task.pk}/update", {"assignee_id": 9999}).status_code == 400


def test_note_appends_a_line(post, task):
    assert post(f"/tasks/{task.pk}/note", {"text": "첫 메모"}).json()["task"]["notes"] == "첫 메모"
    r = post(f"/tasks/{task.pk}/note", {"text": " 둘째 "})
    assert r.json()["task"]["notes"] == "첫 메모\n둘째"
    assert r.json()["task"]["version"] == 1  # 부속 텍스트는 version을 올리지 않는다
    assert post(f"/tasks/{task.pk}/note", {"text": "  "}).status_code == 400


def test_status_transition_with_reason(post, task, member):
    r = post(f"/tasks/{task.pk}/status", {"status": "blocked"})
    assert r.status_code == 400
    assert r.json()["detail"]["stop_reason"] == "막힘 사유를 입력하세요."
    r = post(f"/tasks/{task.pk}/status", {"status": "blocked", "reason": "API 대기"})
    assert r.status_code == 200
    assert r.json()["was"] == "시작 전"
    assert r.json()["task"]["stop_reason"] == "API 대기"
    log = ChangeLog.objects.get(target_id=task.pk, field="status")
    assert (log.actor_id, log.source, log.note) == (member.pk, "dc", "API 대기")


# ---------- 채널 되적기 ----------


def test_channel_save_is_admin_only(post, team, project, org, member, admin):
    r = post(f"/teams/{team.pk}/channel", {"channel_id": "5551"})
    assert r.status_code == 400
    assert r.json()["detail"]["org"] == "조직 관리자만 할 수 있습니다."
    assert post(f"/projects/{project.pk}/channel", {"channel_id": "5552"}).status_code == 400
    team.refresh_from_db()
    project.refresh_from_db()
    assert (team.discord_channel_id, project.discord_channel_id) == ("", "")

    OrgMembership.objects.filter(org=org, user=member).update(role="admin")
    org.discord_guild_id = "9001"
    org.save(update_fields=["discord_guild_id"])
    # 관리자여도 이 경로로는 새 채널을 못 적는다(권한 밖 확인 우회 방지). 같은 값 쓰기·해제만 된다
    r = post(f"/teams/{team.pk}/channel", {"channel_id": "5551"})
    assert r.status_code == 400
    assert post(f"/teams/{team.pk}/channel", {}).json()["discord_channel_id"] == ""
    r = post(
        "/channel-check",
        {
            "kind": "team",
            "guild_id": "9001",
            "target_id": team.pk,
            "channel_id": "5551",
            "created": True,
        },
    )
    assert r.json()["linked"] is True
    r = post(f"/teams/{team.pk}/channel", {"channel_id": "5551"})
    assert r.json() == {"id": team.pk, "name": "백엔드", "discord_channel_id": "5551"}
    # 빈 문자열은 연결 해제
    assert post(f"/projects/{project.pk}/channel", {}).json()["discord_channel_id"] == ""


def test_channel_save_outside_my_orgs_is_404(post, outsider):
    from orgs.services import create_org, create_team

    other = create_org("남의 조직", "", outsider)
    t = create_team(org=other, name="외부팀", actor=outsider)
    assert post(f"/teams/{t.pk}/channel", {"channel_id": "1"}).status_code == 404
    assert post("/teams/9999/channel", {"channel_id": "1"}).status_code == 404


def test_slash_endpoints_need_the_bot_scope(client, task, team, write_token):
    h = {"Authorization": f"Bearer {write_token}"}
    for path in ("/projects", "/mytasks", f"/tasks/{task.pk}/note", f"/teams/{team.pk}/channel"):
        r = client.post(f"{DC}{path}", data=BODY, content_type="application/json", headers=h)
        assert r.status_code == 403


# ---------- 요청 ----------


def test_request_in_team_channel_goes_to_that_team(post, client, bot_token, team, admin, project):
    team.discord_channel_id = "555"
    team.save()
    # member(111)가 자기 팀 채널에서 /요청. 받는 쪽도 그 팀이다.
    r = post("/requests", {"title": "결제 오류 확인", "channel_id": "555"})
    assert r.status_code == 200
    req = r.json()["request"]
    assert (req["team"]["id"], req["status"], req["kind"]) == (team.pk, "pending", "work")

    r = post(f"/requests/{req['id']}/projects")
    assert [p["id"] for p in r.json()] == [project.pk]
    r = post(f"/requests/{req['id']}/accept")
    assert r.status_code == 400  # 프로젝트 필수
    r = post(f"/requests/{req['id']}/accept", {"project_id": project.pk})
    assert r.status_code == 200
    assert r.json()["task"]["assignee"]["id"] == r.json()["request"]["requested_by"]["id"]


def test_request_due_date_is_saved(post, team):
    team.discord_channel_id = "555"
    team.save()
    due = (today_kst() + timedelta(days=7)).isoformat()
    r = post("/requests", {"title": "시안", "channel_id": "555", "due_date": due})
    assert r.status_code == 200 and str(r.json()["request"]["due_date"]) == due


def test_open_tasks_list_carries_reviewer(client, org, task, admin):
    task.reviewer = admin
    task.save(update_fields=["reviewer"])
    _, raw = ApiToken.issue(admin, "t", "read", for_ai=False)
    h = {"Authorization": f"Bearer {raw}"}
    items = client.get(f"/api/orgs/{org.pk}/tasks", headers=h).json()["items"]
    assert items[0]["reviewer"]["id"] == admin.pk  # 검토 독촉이 검토자에게 먼저 보낸다


def test_request_without_team_channel_is_400(post, member):
    assert post("/requests", {"title": "x", "channel_id": "nope"}).status_code == 400


def test_request_to_person_and_notices(post, client, bot_token, admin, member, org):
    admin.discord_user_id, admin.discord_linked_at = "999", member.discord_linked_at
    admin.save()
    r = post("/requests", {"title": "리뷰", "kind": "general", "to_user_id": admin.pk})
    rid = r.json()["request"]["id"]
    h = {"Authorization": f"Bearer {bot_token}"}
    notes = client.get(f"{DC}/notices", headers=h).json()
    assert [n["discord_user_id"] for n in notes] == ["999"]
    r = client.post(
        f"{DC}/notices/ack", {"ids": [notes[0]["id"]]}, content_type="application/json", headers=h
    )
    assert r.json() == {"acked": 1}
    assert client.get(f"{DC}/notices", headers=h).json() == []

    # admin이 수락하고 완료한다. member는 받는 사람이 아니라 답하지 못한다.
    assert post(f"/requests/{rid}/accept").status_code == 400
    admin_post = {"discord_user_id": "999"}
    assert post(f"/requests/{rid}/accept", admin_post).status_code == 200
    mine = post("/requests/mine", admin_post).json()
    assert [x["id"] for x in mine["received"]] == [rid]
    assert post(f"/requests/{rid}/done", admin_post).json()["request"]["status"] == "done"
