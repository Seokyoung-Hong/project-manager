"""조직별 구성원 정보: 정의·입력, 웹·API 차단과 예외, 여러 조직 화면에서 막힌 조직 빼기."""

import pytest

from common.errors import ServiceError
from tasks.models import ChangeLog

from .member_info import missing, rows, save, set_definition
from .models import OrgMembership
from .services import create_invite, create_org, usable_orgs

pytestmark = pytest.mark.django_db

PHONE = {"label": "연락처", "kind": "text", "required": True, "help": "", "choices": []}
NOTE = {"label": "메모", "kind": "long", "required": False}


def _m(org, user):
    return OrgMembership.objects.select_related("org").get(org=org, user=user)


def _fid(org, label):
    org.refresh_from_db()
    return next(f["id"] for f in org.member_fields["fields"] if f["label"] == label)


def test_definition_and_input(org, admin, member):
    with pytest.raises(ServiceError):
        set_definition(org, True, [PHONE], member)  # 관리자만
    with pytest.raises(ServiceError):
        set_definition(org, True, [{"label": "역할", "kind": "choice"}], admin)  # 선택지 없음
    set_definition(
        org,
        True,
        [PHONE, {"label": "역할", "kind": "choice", "choices": ["가", "나"]}],
        admin,
    )
    log = ChangeLog.objects.get(target_type="org", target_id=org.pk, field="member_fields")
    assert "실명으로 표시 켬" in log.new_value and "연락처 (필수)" in log.new_value
    pid, rid = _fid(org, "연락처"), _fid(org, "역할")
    m = _m(org, member)
    assert missing(m)
    with pytest.raises(ServiceError) as e:
        save(m, {pid: "", rid: "다"})
    assert set(e.value.errors) == {pid, rid}
    save(m, {pid: "010", rid: "가"})
    assert not missing(_m(org, member))
    # 라벨을 바꿔도 값은 id로 남고, 지운 항목 값은 화면에 안 나온다
    org.refresh_from_db()
    fields = org.member_fields["fields"]
    set_definition(org, True, [{**fields[0], "label": "전화"}], admin)
    assert [(r["label"], r["value"]) for r in rows(_m(org, member))] == [("전화", "010")]


def test_web_block_and_exceptions(client, org, admin, member):
    set_definition(org, False, [PHONE], admin)
    client.force_login(member)
    url = f"/orgs/{org.pk}/member-info"
    r = client.get("/projects")  # 세션의 현재 조직으로 정하는 화면
    assert r.status_code == 302 and r["Location"] == url
    r = client.get(f"/orgs/{org.pk}", headers={"HX-Request": "true"})
    assert r.status_code == 204 and r["HX-Redirect"] == url
    for path in (url, "/orgs", "/settings/profile"):
        r = client.get(path)
        assert r.status_code in (200, 302) and r.get("Location") != url
    # 다른 조직은 막히지 않는다
    other = create_org("다른 조직", "", member)
    assert client.get(f"/orgs/{other.pk}").status_code == 200
    # 입력하면 풀린다
    r = client.post(url, {f"v-{_fid(org, '연락처')}": "010"})
    assert r.status_code == 302 and client.get(f"/orgs/{org.pk}").status_code == 200


def test_admin_is_target_but_can_open_settings(client, org, admin):
    client.force_login(admin)
    r = client.post(
        f"/orgs/{org.pk}/member-fields",
        {
            "show_real_name": "on",
            "f0-label": "연락처",
            "f0-kind": "text",
            "f0-required": "on",
            "f0-order": "1",
        },
    )
    assert r.status_code == 302
    assert client.get(f"/orgs/{org.pk}/settings").status_code == 200
    assert client.get(f"/orgs/{org.pk}/teams")["Location"] == f"/orgs/{org.pk}/member-info"


def test_api_403_and_other_org(client, api, org, admin, member, project, task):
    assert api.get(f"/api/tasks/{task.pk}").status_code == 200
    # 필수를 새로 넣으면 기존 구성원도 다음 요청부터 막힌다
    set_definition(org, False, [PHONE], admin)
    for r in (
        api.get(f"/api/tasks/{task.pk}"),
        api.get(f"/api/orgs/{org.pk}/members"),
        api.get(f"/api/tasks?project={project.pk}"),
        api.post("/api/tasks", {"project_id": project.pk, "title": "새 일"}),
    ):
        assert r.status_code == 403
        body = r.json()
        assert body["error"] == "profile_required"
        assert body["url"].endswith(f"/orgs/{org.pk}/member-info") and body["url"] in body["detail"]
    assert api.get("/api/me").status_code == 200  # 조직을 정할 수 없는 요청은 그대로
    other = create_org("다른 조직", "", member)
    assert api.get(f"/api/orgs/{other.pk}").status_code == 200
    save(_m(org, member), {_fid(org, "연락처"): "010"})
    assert api.get(f"/api/tasks/{task.pk}").status_code == 200


def test_optional_only_does_not_block(client, api, org, admin, member, task):
    set_definition(org, False, [NOTE], admin)
    client.force_login(member)
    assert client.get("/today").status_code == 200
    assert api.get(f"/api/tasks/{task.pk}").status_code == 200


def test_cross_org_views_hide_blocked_org(client, api, org, admin, member, project, task):
    """오늘·내 태스크·검색·/api/today·/api/tasks·/api/me는 막지 않고 막힌 조직의 것만 빼고 안내한다."""
    from projects.docs import visible_docs
    from projects.services import create_project, visible_projects
    from tasks.services import create_task, visible_tasks
    from web.realtime.hub import allowed

    other = create_org("다른 조직", "", member)
    op = create_project(org=other, name="다른 일", actor=member, owners=[member], status="active")
    ot = create_task(
        project=op,
        title="다른 조직 할 일",
        actor=member,
        source="web",
        assignee=member,
        due_date=task.due_date,
    )
    task.assignee = member
    task.save()
    set_definition(org, False, [PHONE], admin)

    assert list(usable_orgs(member)) == [other]
    assert set(visible_projects(member)) == {op}
    assert set(visible_tasks(member)) == {ot}
    assert not visible_docs(member).filter(org=org).exists()

    client.force_login(member)
    for path in ("/today", "/me", "/search?q=할"):
        r = client.get(path)
        assert r.status_code == 200, path
        html = r.content.decode()
        assert "산돌이 조직은 구성원 정보를 입력해야 볼 수 있습니다." in html
        assert f"/orgs/{org.pk}/member-info" in html and task.title not in html

    for path in ("/api/today", "/api/tasks", "/api/me"):
        body = api.get(path).json()
        assert body["blocked_orgs"][0]["org_id"] == org.pk, path
        assert body["blocked_orgs"][0]["url"].endswith(f"/orgs/{org.pk}/member-info")
    items = api.get("/api/tasks").json()["items"]
    assert [t["id"] for t in items] == [ot.pk]

    # 실시간 구독도 막힌 조직의 키를 뺀다
    keys = {f"O:{org.pk}", f"O:{other.pk}", f"T:{task.pk}", f"P:{project.pk}", f"T:{ot.pk}"}
    assert allowed(member.pk, keys) == {f"O:{other.pk}", f"T:{ot.pk}"}

    save(_m(org, member), {_fid(org, "연락처"): "010"})
    assert api.get("/api/tasks").json()["blocked_orgs"] == []


def test_web_paths_use_target_org(client, org, admin, member):
    """세션 조직이 아니라 대상 객체(초대·구성원·마일스톤)의 조직으로 판단한다."""
    from projects.models import Milestone
    from projects.services import create_project

    other = create_org("다른 조직", "", admin)
    set_definition(org, False, [PHONE], admin)
    client.force_login(admin)
    client.get(f"/orgs/{other.pk}")  # 세션 조직 = 막히지 않은 다른 조직
    url = f"/orgs/{org.pk}/member-info"
    inv = create_invite(org, admin)
    m = _m(org, member)
    p = create_project(org=org, name="학식", actor=admin, owners=[admin], status="active")
    ms = Milestone.objects.create(project=p, name="1차", target_date="2026-12-01", created_by=admin)
    assert client.post(f"/orgs/invites/{inv.pk}/revoke")["Location"] == url
    assert client.post(f"/orgs/memberships/{m.pk}/tags", {"tags": "a"})["Location"] == url
    assert client.get(f"/milestones/{ms.pk}/edit")["Location"] == url


def test_discord_lists_and_notices(client, api, org, admin, member, project, task, team):
    """Discord 실행자 안내, 목록 API 헤더, 팀 열람, 알림 수신자 제외."""
    import json

    from accounts.models import ApiToken, User
    from orgs.services import visible_teams
    from tasks.models import Notice
    from tasks.work_requests import notify

    bot = User.objects.create_user("discord-bot", password="pw12345678", display_name="봇")
    _, raw = ApiToken.issue(bot, "봇", "bot")
    bh = {"Authorization": f"Bearer {raw}"}
    set_definition(org, False, [PHONE], admin)

    r = client.post(
        f"/api/integrations/discord/tasks/{task.pk}/done",
        {"discord_user_id": "111"},
        content_type="application/json",
        headers=bh,
    )
    assert r.status_code == 403 and r.json()["error"] == "profile_required"
    assert r.json()["detail"].endswith(f"/orgs/{org.pk}/member-info")

    r = api.get("/api/projects")
    assert r.status_code == 200 and r.json() == []
    blocked = json.loads(r["X-Blocked-Orgs"])
    assert blocked[0]["org_id"] == org.pk and blocked[0]["url"].endswith("/member-info")

    assert not visible_teams(member).exists()

    save(_m(org, admin), {_fid(org, "연락처"): "010"})  # 관리자는 입력을 마쳤다
    members = client.get(f"/api/integrations/discord/orgs/{org.pk}/members", headers=bh).json()
    assert [m["id"] for m in members] == [admin.pk]
    notify(org, "알림", user=member)
    assert not Notice.objects.filter(user=member).exists()

    save(_m(org, member), {_fid(org, "연락처"): "010"})
    assert "X-Blocked-Orgs" not in api.get("/api/projects")
