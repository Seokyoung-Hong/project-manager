from datetime import timedelta

import pytest

from accounts.models import ApiToken, User
from accounts.services import issue_link_code
from api.models import IntegrationStatus
from common.dates import last_week_start, today_kst, week_bounds
from orgs.models import OrgMembership
from orgs.services import create_org, set_org_settings
from projects.services import create_project
from tasks.models import ChangeLog
from tasks.services import create_task

pytestmark = pytest.mark.django_db


def _h(raw):
    return {"Authorization": f"Bearer {raw}"}


def test_me(api, org):
    r = api.get("/api/me")
    assert r.status_code == 200
    body = r.json()
    assert body["orgs"][0]["role"] == "member"
    assert body["auto_pull_days"] == 5


def test_unauthenticated_401(client, member):
    assert client.get("/api/me").status_code == 401


def test_revoked_token_401(client, member):
    token, raw = ApiToken.issue(member, "t", "read")
    token.revoke()
    assert client.get("/api/me", headers=_h(raw)).status_code == 401


def test_read_token_cannot_write(client, read_token, task, org):
    body = {"status": "done", "version": task.version}
    r = client.post(
        f"/api/tasks/{task.pk}/transition",
        data=body,
        content_type="application/json",
        headers=_h(read_token),
    )
    assert r.status_code == 403
    assert client.get(f"/api/tasks/{task.pk}", headers=_h(read_token)).status_code == 200


def test_read_token_can_report_integration_status(client, read_token, member):
    r = client.post(
        "/api/integrations/discord/status",
        data={"ok": True, "detail": {}},
        content_type="application/json",
        headers=_h(read_token),
    )
    assert r.status_code == 204
    assert IntegrationStatus.objects.count() == 1


def test_list_tasks_filters_and_paging(api, project, member, org):
    for i in range(3):
        create_task(
            project=project,
            title=f"t{i}",
            actor=member,
            source="web",
            due_date=today_kst() + timedelta(days=i + 1),
        )
    r = api.get(f"/api/tasks?org={org.pk}&status=todo&limit=2&offset=0")
    assert r.json()["total"] == 3
    assert len(r.json()["items"]) == 2
    r = api.get("/api/tasks?status=bogus")
    assert r.status_code == 400 and "todo, doing" in r.json()["detail"]
    assert api.get("/api/tasks?status=blocked").json()["total"] == 0


def test_create_task_defaults_and_idempotency(api, project, member):
    body = {
        "project_id": project.pk,
        "title": "새 일",
        "due_date": (today_kst() + timedelta(days=2)).isoformat(),
    }
    h = {"Idempotency-Key": "k1"}
    r1 = api.post("/api/tasks", body, headers=h)
    r2 = api.post("/api/tasks", body, headers=h)
    assert r1.status_code == r2.status_code == 201
    assert r1.json()["id"] == r2.json()["id"]
    assert r1.json()["assignee"]["id"] == member.pk
    assert r1.json()["priority"] == 5


def test_create_task_validation(api, project):
    r = api.post("/api/tasks", {"project_id": project.pk, "title": "", "no_due_reason": "x"})
    assert r.status_code == 400
    assert "title" in r.json()["detail"]
    r = api.post("/api/tasks", {"project_id": project.pk, "title": "t", "priority": 11})
    assert r.status_code == 422


def test_patch_conflict_409_with_latest(api, task):
    assert api.patch(f"/api/tasks/{task.pk}", {"version": 1, "priority": 8}).status_code == 200
    r = api.patch(f"/api/tasks/{task.pk}", {"version": 1, "priority": 9})
    assert r.status_code == 409
    assert r.json()["latest"]["priority"] == 8
    assert r.json()["latest"]["version"] == 2


def test_patch_notes_no_version_bump(api, task):
    r = api.patch(f"/api/tasks/{task.pk}", {"version": 99, "notes": "메모"})
    assert r.status_code == 200
    assert r.json()["notes"] == "메모"
    assert r.json()["version"] == 1


def test_patch_checklist_replaces(api, task):
    r = api.patch(f"/api/tasks/{task.pk}", {"version": 1, "checklist": [{"text": "x"}]})
    assert r.json()["checklist_total"] == 1


def test_patch_assignee_with_reason_setting(api, task, org, admin):
    """task.assignee_change_reason이 켜지면 reason 없이는 400, 있으면 통과."""
    set_org_settings(org, {"task.assignee_change_reason": True}, admin)
    r = api.patch(f"/api/tasks/{task.pk}", {"version": 1, "assignee_id": admin.pk})
    assert r.status_code == 400
    assert "reason" in r.json()["detail"]
    r = api.patch(
        f"/api/tasks/{task.pk}",
        {"version": 1, "assignee_id": admin.pk, "reason": "인수인계"},
    )
    assert r.status_code == 200
    assert r.json()["assignee"]["id"] == admin.pk


def test_transition_done_via_api_matches_web(api, task):
    assert (
        api.post(f"/api/tasks/{task.pk}/transition", {"status": "doing", "version": 1}).status_code
        == 200
    )
    r = api.post(f"/api/tasks/{task.pk}/transition", {"status": "done", "version": 2})
    assert r.status_code == 200
    assert r.json()["completed_at"] is not None
    assert r.json()["stop_reason"] == ""
    history = api.get(f"/api/tasks/{task.pk}/history").json()
    assert history[-1]["source"] == "api"


def test_transition_blocked_via_api(api, task):
    r = api.post(f"/api/tasks/{task.pk}/transition", {"status": "blocked", "version": 1})
    assert r.status_code == 400
    assert "stop_reason" in r.json()["detail"]
    r = api.post(
        f"/api/tasks/{task.pk}/transition",
        {"status": "blocked", "reason": "서류", "version": 1},
    )
    assert r.status_code == 200
    assert r.json()["stop_reason"] == "서류"


def test_extend_endpoint(api, task):
    new = (today_kst() + timedelta(days=5)).isoformat()
    r = api.post(f"/api/tasks/{task.pk}/extend", {"due_date": new, "reason": "회의", "version": 1})
    assert r.status_code == 200
    assert r.json()["due_date"] == new
    assert r.json()["version"] == 2
    r = api.post(
        f"/api/tasks/{task.pk}/extend",
        {
            "due_date": (today_kst() + timedelta(days=1)).isoformat(),
            "reason": "x",
            "version": 2,
        },
    )
    assert r.status_code == 400
    assert "due_date" in r.json()["detail"]


def test_source_mcp_header_recorded(api, task):
    api.post(
        f"/api/tasks/{task.pk}/transition",
        {"status": "doing", "version": 1},
        headers={"X-Source": "mcp"},
    )
    history = api.get(f"/api/tasks/{task.pk}/history").json()
    assert history[-1]["source"] == "mcp"


def test_today_endpoints(api, task):
    body = api.get("/api/today").json()
    assert len(body["items"]) == 1
    assert body["items"][0]["auto_pulled"] is True

    body = api.delete(f"/api/today/{task.pk}").json()
    assert body["items"] == []
    assert body["counts"]["excluded"] == 1

    body = api.delete("/api/today/excluded").json()
    assert len(body["items"]) == 1

    body = api.post("/api/today", {"task_id": task.pk}).json()
    assert body["items"][0]["auto_pulled"] is False

    assert api.patch("/api/today/order", {"task_ids": [task.pk]}).status_code == 200
    assert api.patch("/api/today/settings", {"auto_pull_days": 4}).status_code == 400
    r = api.patch("/api/today/settings", {"auto_pull_days": 0})
    assert r.status_code == 200
    assert r.json()["auto_pull_days"] == 0


def test_project_owners_via_api(api, org, member, admin):
    r = api.post(
        "/api/projects",
        {"org_id": org.pk, "name": "챗봇", "owner_ids": [member.pk, admin.pk]},
    )
    assert r.status_code == 201
    pid = r.json()["id"]
    assert len(r.json()["owners"]) == 2
    r = api.patch(f"/api/projects/{pid}", {"version": 1, "owner_ids": []})
    assert r.json()["owners"] == []
    assert api.patch(f"/api/projects/{pid}", {"version": 2, "owner_ids": [9999]}).status_code == 400


def test_weekly_endpoint(api, org):
    r = api.get(f"/api/reports/weekly?org={org.pk}")
    assert r.status_code == 200
    assert r.json()["period_start"] == last_week_start().isoformat()
    tuesday = week_bounds()[0] + timedelta(days=1)
    assert (
        api.get(f"/api/reports/weekly?org={org.pk}&week_start={tuesday.isoformat()}").status_code
        == 400
    )


def test_org_status_endpoint(api, org):
    r = api.get(f"/api/orgs/{org.pk}/status")
    assert r.status_code == 200
    assert "counts" in r.json()


def test_invite_admin_only(client, api, org, admin):
    assert api.post(f"/api/orgs/{org.pk}/invites", {"days": 7}).status_code == 400
    _, raw = ApiToken.issue(admin, "a", "write")
    r = client.post(
        f"/api/orgs/{org.pk}/invites",
        data={"days": 7},
        content_type="application/json",
        headers=_h(raw),
    )
    assert r.status_code == 201
    assert "/join/" in r.json()["url"]


def test_bearer_write_passes_csrf(write_token, task, db):
    """Bearer 토큰 쓰기 요청은 CSRF 검사에 걸리지 않는다 (MCP·Discord 경로)."""
    from django.test import Client

    strict = Client(enforce_csrf_checks=True)
    r = strict.post(
        f"/api/tasks/{task.pk}/transition",
        data={"status": "review", "version": 1},
        content_type="application/json",
        headers=_h(write_token),
    )
    assert r.status_code == 200


def test_session_write_still_needs_csrf(client, member, task):
    """세션 쿠키로 들어온 쓰기 요청은 CSRF 토큰이 없으면 거부된다."""
    from django.test import Client

    strict = Client(enforce_csrf_checks=True)
    strict.login(username="member1", password="pw12345678")
    r = strict.post(
        f"/api/tasks/{task.pk}/transition",
        data={"status": "review", "version": 1},
        content_type="application/json",
    )
    assert r.status_code == 403


def test_malformed_date_filter_returns_422_not_500(api, task):
    """due_from/due_to는 date로 선언돼 있어야 한다. str이면 ORM에서 ValidationError -> 500."""
    r = api.get("/api/tasks?due_from=abc")
    assert r.status_code == 422
    assert api.get(f"/api/tasks?due_from={today_kst().isoformat()}").status_code == 200


def test_null_due_date_sorts_last_on_both_backends(api, project, member):
    """order_by에 nulls_last를 명시해야 SQLite와 Postgres 순서가 같다."""
    create_task(
        project=project,
        title="dated",
        actor=member,
        source="web",
        due_date=today_kst() + timedelta(days=1),
    )
    create_task(project=project, title="undated", actor=member, source="web", no_due_reason="미정")
    titles = [t["title"] for t in api.get("/api/tasks?limit=10").json()["items"]]
    assert titles.index("undated") > titles.index("dated")


# ---------- Discord 봇 명령 (POST /api/integrations/discord/...) ----------

DC = "/api/integrations/discord"
BODY = {"discord_user_id": "111"}  # member 픽스처가 들고 있는 snowflake


def _post(client, raw, url, body=None):
    return client.post(url, data=body or {}, content_type="application/json", headers=_h(raw))


@pytest.fixture
def bot(db):
    """봇 계정. 이 경로에서 봇의 팀 범위는 쓰이지 않는다 — 행위자는 항상 연결된 사람이다."""
    return User.objects.create_user("discord-bot", password="pw12345678", display_name="산돌이 봇")


@pytest.fixture
def bot_token(bot):
    _, raw = ApiToken.issue(bot, "봇", "bot")
    return raw


def test_done_needs_the_bot_scope(client, task, member, read_token, write_token, bot_token):
    """라우터 인증이 BotTokenAuth 하나라서 세션·읽기·쓰기 토큰은 이 경로에 들어오지 못한다."""
    url = f"{DC}/tasks/{task.pk}/done"

    # 세션 쿠키에는 Authorization 헤더가 없다. HttpBearer는 자격증명 자체가 없다고 보고
    # 401을 준다(403이 아니다 — 범위를 볼 기회조차 없다).
    client.login(username="member1", password="pw12345678")
    assert client.post(url, data=BODY, content_type="application/json").status_code == 401
    client.logout()

    # 토큰은 인증되지만 범위가 bot이 아니다 → BotTokenAuth가 403.
    assert _post(client, read_token, url, BODY).status_code == 403
    assert _post(client, write_token, url, BODY).status_code == 403
    task.refresh_from_db()
    assert task.status == "todo"

    assert _post(client, bot_token, url, BODY).status_code == 200


def test_bot_token_cannot_write_outside_integrations(client, bot, bot_token, org, project):
    """bot 범위는 /api/integrations/ 안에서만 쓴다. 그 밖의 쓰기는 읽기 전용과 똑같이 막힌다."""
    OrgMembership.objects.create(org=org, user=bot, role="member")
    r = _post(
        client,
        bot_token,
        "/api/tasks",
        {"project_id": project.pk, "title": "봇이 만든 일", "no_due_reason": "미정"},
    )
    assert r.status_code == 403
    assert client.get("/api/me", headers=_h(bot_token)).status_code == 200  # 읽기는 된다


def test_done_logs_the_human_as_actor_and_the_bot_token(client, task, member, bot, bot_token):
    """봇은 자기 이름으로 일하지 않는다. 이력은 사람·Discord·봇 토큰 세 값을 같이 남긴다."""
    r = _post(client, bot_token, f"{DC}/tasks/{task.pk}/done", BODY)
    assert r.status_code == 200
    assert r.json()["was"] == "시작 전"
    assert r.json()["task"]["status"] == "done"

    log = ChangeLog.objects.get(target_id=task.pk, field="status")
    assert log.source == "dc"
    assert log.get_source_display() == "Discord"
    assert log.actor == member
    assert log.token is not None and log.token.user == bot


def test_unknown_or_unproven_snowflake_is_404(client, task, outsider, bot_token):
    """연결 시각이 없는 행(마이그레이션이 비운 손입력 값)도 모르는 계정과 같이 막힌다."""
    User.objects.filter(pk=outsider.pk).update(discord_user_id="999")
    for did in ("999", "424242"):
        r = _post(client, bot_token, f"{DC}/tasks/{task.pk}/done", {"discord_user_id": did})
        assert r.status_code == 404
        assert "연결" in r.json()["detail"]
    task.refresh_from_db()
    assert task.status == "todo"
    assert not ChangeLog.objects.filter(field="status").exists()


def test_scope_follows_the_actor_not_the_bot(client, bot, bot_token, org, task, member):
    """봇이 볼 수 있는 태스크가 아니라 그 사람이 볼 수 있는 태스크만 움직인다."""
    OrgMembership.objects.create(org=org, user=bot, role="member")  # 봇은 조직 A
    OrgMembership.objects.filter(org=org, user=member).delete()  # 사람은 조직 B로 옮긴다
    org_b = create_org("남의 조직", "", member)
    project_b = create_project(org=org_b, name="B", actor=member, owners=[member], status="active")
    mine = create_task(
        project=project_b,
        title="내 일",
        actor=member,
        source="web",
        due_date=today_kst() + timedelta(days=1),
    )

    items = _post(client, bot_token, f"{DC}/today", BODY).json()["items"]
    assert [i["id"] for i in items] == [mine.pk]

    # 조직 A 태스크는 봇의 GET에는 보이지만 행위자 범위에서는 없는 것이다.
    assert client.get(f"/api/tasks/{task.pk}", headers=_h(bot_token)).status_code == 200
    assert _post(client, bot_token, f"{DC}/tasks/{task.pk}/done", BODY).status_code == 404
    assert _post(client, bot_token, f"{DC}/tasks/{mine.pk}/done", BODY).status_code == 200


def test_the_same_done_twice_leaves_one_history_row(client, task, bot_token):
    """같은 상태 재요청은 _apply 전에 조기 반환된다 — 중복 `완료`는 무해하고 이력도 한 줄."""
    url = f"{DC}/tasks/{task.pk}/done"
    assert _post(client, bot_token, url, BODY).status_code == 200
    r = _post(client, bot_token, url, BODY)
    assert r.status_code == 200
    assert r.json()["was"] == "완료"
    assert ChangeLog.objects.filter(target_id=task.pk, field="status").count() == 1


def test_extend_not_past_the_current_due_date_is_400(client, task, bot_token):
    """이중 연장이 구조적으로 불가능하다. 같은 날짜 재전송은 서비스 문구를 그대로 전달한다."""
    url = f"{DC}/tasks/{task.pk}/extend"
    body = {**BODY, "due_date": task.due_date.isoformat(), "reason": "QA 지연"}
    r = _post(client, bot_token, url, body)
    assert r.status_code == 400
    assert r.json()["detail"]["due_date"] == "현재 목표일보다 뒤의 날짜를 선택하세요."
    task.refresh_from_db()
    assert task.version == 1

    new = (task.due_date + timedelta(days=2)).isoformat()
    r = _post(client, bot_token, url, {**BODY, "due_date": new, "reason": "QA 지연"})
    assert r.status_code == 200
    assert r.json()["task"]["due_date"] == new


def test_link_and_unlink_need_the_bot_scope(client, admin, read_token, write_token, bot_token):
    code = issue_link_code(admin)
    body = {"code": code, "discord_user_id": "222"}
    for raw in (read_token, write_token):
        assert _post(client, raw, f"{DC}/link", body).status_code == 403
        assert _post(client, raw, f"{DC}/unlink", BODY).status_code == 403
    admin.refresh_from_db()
    assert admin.discord_user_id is None

    r = _post(client, bot_token, f"{DC}/link", body)
    assert r.status_code == 200
    assert r.json() == {"display_name": "관리자"}
    assert _post(client, bot_token, f"{DC}/unlink", {"discord_user_id": "222"}).json() == {
        "unlinked": True
    }
    assert _post(client, bot_token, f"{DC}/unlink", {"discord_user_id": "222"}).json() == {
        "unlinked": False
    }


def test_throttle_bucket_is_per_user_not_per_display_name(rf, member, outsider):
    """처리량 제한 키가 display_name이면 남과 같은 이름으로 바꿔 그 사람 몫을 갉아먹는다."""
    from accounts.models import User
    from api.api import UserRateThrottle

    User.objects.filter(pk=outsider.pk).update(display_name=member.display_name)
    outsider.refresh_from_db()
    assert str(member) == str(outsider)

    t = UserRateThrottle("60/m")
    keys = []
    for u in (member, outsider):
        r = rf.get("/api/me")
        r.auth = u
        keys.append(t.get_cache_key(r))
    assert keys[0] != keys[1]
    assert str(member.pk) in keys[0]


def test_api_spec_put_endpoint(client, write_token, read_token, project):
    from projects.tests import SAMPLE_SPEC

    body = {"spec": SAMPLE_SPEC, "source_url": "openapi.json"}
    r = client.put(
        f"/api/projects/{project.pk}/api-spec",
        data=body,
        content_type="application/json",
        headers={"Authorization": f"Bearer {write_token}"},
    )
    assert r.status_code == 200

    r = client.get(
        f"/api/projects/{project.pk}/api-spec", headers={"Authorization": f"Bearer {read_token}"}
    )
    assert r.status_code == 200
    assert r.json()["spec"]["info"]["title"] == "학식 API"

    r = client.put(
        f"/api/projects/{project.pk}/api-spec",
        data=body,
        content_type="application/json",
        headers={"Authorization": f"Bearer {read_token}"},
    )
    assert r.status_code == 403
