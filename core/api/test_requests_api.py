"""요청 REST API. 권한·AI 정책·멱등성·목록 필터."""

import pytest

from accounts.models import ApiToken
from orgs.services import create_org, set_org_settings
from tasks import work_requests as wr

pytestmark = pytest.mark.django_db


def _ai(member):
    return {"Authorization": f"Bearer {ApiToken.issue(member, 'ai', 'write')[1]}"}


def _to_member(admin, org, kind="general"):
    return wr.create_request(
        org=org,
        kind=kind,
        title="로그 확인",
        actor=admin,
        source="web",
        to_user=_user(org, "member1"),
    )


def _user(org, username):
    return org.members.get(username=username)


@pytest.fixture
def req(admin, org, member):
    """관리자가 팀원에게 보낸 일반 요청."""
    return _to_member(admin, org)


def test_list_box_and_status_filters(api, req, admin, org, team):
    assert api.get("/api/requests").json()["total"] == 1  # 기본은 받은 것
    assert api.get("/api/requests?box=sent").json()["total"] == 0
    assert api.get("/api/requests?box=all&status=done").json()["total"] == 0
    assert api.get(f"/api/requests?org={org.pk + 99}").json()["total"] == 0
    assert api.get("/api/requests?box=x").status_code == 400
    assert api.get("/api/requests?status=bogus").status_code == 400
    item = api.get("/api/requests").json()["items"][0]
    assert item["id"] == req.pk and item["status"] == "pending"


def test_detail_flags_and_404_for_others(api, req, client, outsider):
    d = api.get(f"/api/requests/{req.pk}").json()
    assert d["can_answer"] and not d["can_cancel"] and not d["can_complete"]
    _, raw = ApiToken.issue(outsider, "o", "read", for_ai=False)
    r = client.get(f"/api/requests/{req.pk}", headers={"Authorization": f"Bearer {raw}"})
    assert r.status_code == 404


def test_create_201_and_idempotent(api, admin, org):
    body = {"org_id": org.pk, "kind": "general", "title": "점검", "to_user_id": admin.pk}
    h = {"Idempotency-Key": "k1"}
    first = api.post("/api/requests", body, headers=h)
    assert first.status_code == 201
    again = api.post("/api/requests", body, headers=h)
    assert again.json()["id"] == first.json()["id"]
    assert api.get("/api/requests?box=sent").json()["total"] == 1


def test_create_to_team(api, org, team):
    r = api.post("/api/requests", {"org_id": org.pk, "title": "배포", "team_id": team.pk})
    assert r.status_code == 201 and r.json()["team"]["id"] == team.pk


def test_other_org_ids_are_400_not_found(api, member, admin, org, team, project):
    other = create_org("다른 조직", "", admin)
    assert (
        api.post(
            "/api/requests", {"org_id": other.pk, "title": "x", "to_user_id": admin.pk}
        ).status_code
        == 400
    )
    r = api.post("/api/requests", {"org_id": org.pk, "title": "x", "team_id": 9999})
    assert r.status_code == 400 and "찾을 수 없습니다" in r.json()["detail"]
    r = api.post("/api/requests", {"org_id": other.pk, "title": "x", "team_id": team.pk})
    assert r.status_code == 400


def test_accept_work_request_makes_task(api, admin, org, member, project):
    work = _to_member(admin, org, kind="work")
    r = api.post(f"/api/requests/{work.pk}/accept", {"project_id": project.pk})
    assert r.status_code == 200 and r.json()["status"] == "accepted"
    assert r.json()["task"]["assignee"]["id"] == member.pk
    bad = _to_member(admin, org, kind="work")
    assert api.post(f"/api/requests/{bad.pk}/accept", {"project_id": 9999}).status_code == 400


def test_decline_complete_cancel(api, req, admin, org, client):
    assert api.post(f"/api/requests/{req.pk}/done").status_code == 400  # 아직 수락 전
    assert api.post(f"/api/requests/{req.pk}/accept").json()["status"] == "accepted"
    assert api.get(f"/api/requests/{req.pk}").json()["can_complete"]
    assert api.post(f"/api/requests/{req.pk}/done", {"note": "끝"}).json()["status"] == "done"

    other = _to_member(admin, org)
    assert (
        api.post(f"/api/requests/{other.pk}/decline", {"note": "바쁨"}).json()["status"]
        == "declined"
    )

    mine = api.post(
        "/api/requests", {"org_id": org.pk, "title": "t", "to_user_id": admin.pk}
    ).json()
    assert api.get(f"/api/requests/{mine['id']}").json()["can_cancel"]
    assert api.post(f"/api/requests/{mine['id']}/cancel").json()["status"] == "cancelled"


def test_only_receiver_can_answer(api, admin, org, member):
    mine = wr.create_request(
        org=org, kind="general", title="t", actor=member, source="web", to_user=admin
    )
    assert api.post(f"/api/requests/{mine.pk}/accept").status_code == 400
    assert api.post(f"/api/requests/{mine.pk}/decline").status_code == 400


def test_ai_token_cannot_answer_by_default(client, req, member, admin, org):
    h = _ai(member)
    r = client.post(
        f"/api/requests/{req.pk}/accept", data={}, content_type="application/json", headers=h
    )
    assert r.status_code == 400 and "AI" in str(r.json()["detail"])
    set_org_settings(org, {"ai.answer_request": "allow"}, admin)
    r = client.post(
        f"/api/requests/{req.pk}/accept", data={}, content_type="application/json", headers=h
    )
    assert r.status_code == 200


def test_ai_create_and_cancel_follow_create_request(client, member, admin, org):
    h = _ai(member)
    body = {"org_id": org.pk, "kind": "general", "title": "t", "to_user_id": admin.pk}
    post = lambda url, data: client.post(url, data=data, content_type="application/json", headers=h)  # noqa: E731
    made = post("/api/requests", body)
    assert made.status_code == 201
    set_org_settings(org, {"ai.create_request": "deny"}, admin)
    assert post("/api/requests", body).status_code == 400
    assert post(f"/api/requests/{made.json()['id']}/cancel", {}).status_code == 400


def test_idempotency_key_used_for_a_task_is_rejected_without_side_effects(api, org, admin, project):
    from tasks.models import Notice, WorkRequest

    h = {"Idempotency-Key": "k-1"}
    r = api.post(
        "/api/tasks", {"project_id": project.pk, "title": "t", "no_due_reason": "x"}, headers=h
    )
    assert r.status_code == 201
    before = (WorkRequest.objects.count(), Notice.objects.count())
    r = api.post(
        "/api/requests",
        {"org_id": org.pk, "title": "x", "kind": "general", "to_user_id": admin.pk},
        headers=h,
    )
    assert r.status_code == 400
    assert (WorkRequest.objects.count(), Notice.objects.count()) == before


def test_browser_ai_with_session_is_held_to_ai_policy(client, admin, org, member):
    """WebMCP는 세션 쿠키로 부르고 X-Source: ai를 붙인다. 수락은 기본 막힘."""
    req = wr.create_request(
        org=org, kind="general", title="x", actor=admin, source="web", to_user=member
    )
    client.login(username="member1", password="pw12345678")
    r = client.post(
        f"/api/requests/{req.pk}/accept",
        {},
        content_type="application/json",
        headers={"X-Source": "ai"},
    )
    assert r.status_code == 400
    r = client.post(f"/api/requests/{req.pk}/accept", {}, content_type="application/json")
    assert r.status_code == 200  # 같은 사람이 직접 하면 된다
