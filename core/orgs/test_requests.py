"""AI의 조직 설정·거버넌스 변경 요청. 올리는 건 AI 토큰, 허용은 관리자의 로그인 세션만."""

from datetime import timedelta

import pytest
from django.utils import timezone

from accounts.models import ApiToken
from orgs.models import ChangeRequest
from orgs.services import set_org_settings
from tasks.models import ChangeLog


def _h(raw):
    return {"Authorization": f"Bearer {raw}"}


@pytest.fixture
def ai_admin(admin):
    return ApiToken.issue(admin, "Claude", "write")[1]


def _put_settings(client, org, raw, data, reason="팀 합의대로 AI의 태스크 생성을 막습니다"):
    return client.put(
        f"/api/orgs/{org.pk}/settings?reason={reason}",
        data=data,
        content_type="application/json",
        headers=_h(raw),
    )


def _put_governance(client, org, raw, text, reason="회의에서 정한 규칙을 반영합니다"):
    return client.put(
        f"/api/orgs/{org.pk}/governance?reason={reason}",
        data={"text": text},
        content_type="application/json",
        headers=_h(raw),
    )


def _as_admin(client):
    client.login(username="admin1", password="pw12345678")
    return client


def test_ai_policy_change_waits_for_a_person(client, admin, org, ai_admin):
    r = _put_settings(client, org, ai_admin, {"ai.create_task": "deny"})
    assert r.status_code == 202
    body = r.json()
    page = f"/orgs/{org.pk}/requests/{body['request_id']}"
    assert body["status"] == "pending" and body["approve_url"].endswith(page)
    org.refresh_from_db()
    assert org.settings == {}

    # AI가 가진 토큰으로는 허용 화면에 들어오지 못한다.
    r = client.post(page, {"action": "approve"}, headers=_h(ai_admin))
    assert r.status_code == 302 and "/login" in r.headers["Location"]
    org.refresh_from_db()
    assert org.settings == {}

    _as_admin(client)
    html = client.get(page).content.decode()
    assert "AI 정책" in html and "허용하고 반영" in html
    client.post(page, {"action": "approve"})
    org.refresh_from_db()
    assert org.settings == {"ai.create_task": "deny"}
    req = ChangeRequest.objects.get()
    assert req.status == "approved" and req.reviewed_by == admin
    assert ChangeLog.objects.filter(
        target_type="org", target_id=org.pk, field="ai.create_task"
    ).exists()

    # 설정 화면에서 대기 목록이 사라지고, 같은 요청을 두 번 허용하지 못한다.
    assert page not in client.get(f"/orgs/{org.pk}/settings").content.decode()
    client.post(page, {"action": "reject"})
    assert ChangeRequest.objects.get().status == "approved"


def test_governance_request_can_be_rejected(client, admin, org, ai_admin):
    r = _put_governance(client, org, ai_admin, "# 새 규칙")
    assert r.status_code == 202
    page = f"/orgs/{org.pk}/requests/{r.json()['request_id']}"
    _as_admin(client)
    assert page in client.get(f"/orgs/{org.pk}/governance").content.decode()
    assert "+# 새 규칙" in client.get(page).content.decode()
    client.post(page, {"action": "reject", "reason": "아직 합의 전"})
    org.refresh_from_db()
    assert org.governance == ""
    req = ChangeRequest.objects.get()
    assert req.status == "rejected" and req.reject_reason == "아직 합의 전"


def test_member_cannot_review(client, org, member, ai_admin):
    page = f"/orgs/{org.pk}/requests/{_put_governance(client, org, ai_admin, '# x').json()['request_id']}"
    client.login(username="member1", password="pw12345678")
    client.post(page, {"action": "approve"})
    org.refresh_from_db()
    assert org.governance == "" and ChangeRequest.objects.get().status == "pending"


def test_only_an_admins_ai_can_ask(client, org, member):
    raw = ApiToken.issue(member, "Claude", "write")[1]
    assert _put_governance(client, org, raw, "# x").status_code == 400
    assert _put_settings(client, org, raw, {"ai.create_task": "deny"}).status_code == 400
    assert not ChangeRequest.objects.exists()


def test_invalid_or_empty_request_is_refused_at_once(client, org, ai_admin):
    assert _put_settings(client, org, ai_admin, {"ai.create_task": "maybe"}).status_code == 400
    assert _put_governance(client, org, ai_admin, "").status_code == 400  # 지금도 기본안이다
    assert not ChangeRequest.objects.exists()


def test_stale_request_does_not_overwrite_a_later_change(client, admin, org, ai_admin):
    page = f"/orgs/{org.pk}/requests/{_put_settings(client, org, ai_admin, {'ai.create_task': 'deny'}).json()['request_id']}"
    set_org_settings(org, {"task.default_priority": 3}, admin)  # 요청 뒤에 사람이 먼저 바꿨다
    _as_admin(client).post(page, {"action": "approve"})
    org.refresh_from_db()
    assert org.settings == {"task.default_priority": 3}
    assert ChangeRequest.objects.get().status == "stale"


def test_expired_request_cannot_be_approved(client, org, ai_admin):
    _put_governance(client, org, ai_admin, "# x")
    ChangeRequest.objects.update(expires_at=timezone.now() - timedelta(minutes=1))
    req = ChangeRequest.objects.get()
    _as_admin(client).post(f"/orgs/{org.pk}/requests/{req.pk}", {"action": "approve"})
    org.refresh_from_db()
    assert org.governance == ""
    assert "만료" in client.get(f"/orgs/{org.pk}/requests/{req.pk}").content.decode()


def test_ai_disabled_org_takes_no_requests_or_writes(client, admin, org, ai_admin):
    set_org_settings(org, {"ai.enabled": False}, admin)
    assert (
        _put_settings(
            client, org, ai_admin, {"ai.enabled": False, "ai.create_task": "deny"}
        ).status_code
        == 400
    )
    assert (
        _put_settings(
            client, org, ai_admin, {"ai.enabled": False, "task.default_priority": 3}
        ).status_code
        == 400
    )
    assert _put_governance(client, org, ai_admin, "# x").status_code == 400
    assert not ChangeRequest.objects.exists()


def test_governance_same_as_default_is_not_a_change(client, org, ai_admin):
    """웹에서 기본안을 그대로 저장한 조직에 빈 본문을 보내면 적용되는 글은 같다 — 빈 비교 화면을 만들지 않는다."""
    from orgs.governance import DEFAULT_GOVERNANCE

    org.governance = DEFAULT_GOVERNANCE.strip()
    org.save(update_fields=["governance"])
    assert _put_governance(client, org, ai_admin, "").status_code == 400
    assert not ChangeRequest.objects.exists()


def test_invisible_characters_are_shown(client, org, ai_admin):
    page = f"/orgs/{org.pk}/requests/{_put_governance(client, org, ai_admin, '# 규칙​').json()['request_id']}"
    assert "U+200B" in _as_admin(client).get(page).content.decode()


def test_other_orgs_admin_cannot_open_the_request(client, org, ai_admin, outsider):
    from orgs.services import create_org

    other = create_org("다른 조직", "", outsider)
    req_id = _put_governance(client, org, ai_admin, "# x").json()["request_id"]
    client.login(username="outsider", password="pw12345678")
    assert client.get(f"/orgs/{other.pk}/requests/{req_id}").status_code == 404
    assert (
        client.post(f"/orgs/{org.pk}/requests/{req_id}", {"action": "approve"}).status_code == 404
    )
    assert ChangeRequest.objects.get().status == "pending"


def test_approve_needs_csrf(org, ai_admin):
    from django.test import Client

    c = Client(enforce_csrf_checks=True)
    req_id = _put_governance(c, org, ai_admin, "# x").json()["request_id"]
    _as_admin(c)
    assert c.post(f"/orgs/{org.pk}/requests/{req_id}", {"action": "approve"}).status_code == 403
    assert ChangeRequest.objects.get().status == "pending"


def test_history_links_the_ai_request(client, admin, org, ai_admin):
    req_id = _put_settings(client, org, ai_admin, {"ai.create_task": "deny"}).json()["request_id"]
    _as_admin(client).post(f"/orgs/{org.pk}/requests/{req_id}", {"action": "approve"})
    log = ChangeLog.objects.get(target_type="org", field="ai.create_task")
    assert log.actor == admin and log.note == f"AI 요청 #{req_id} 허용" and log.token is not None


def test_reason_is_required_and_shown(client, org, ai_admin):
    assert _put_governance(client, org, ai_admin, "# x", reason="").status_code == 400
    assert _put_governance(client, org, ai_admin, "# x", reason="가" * 501).status_code == 400
    assert not ChangeRequest.objects.exists()
    req_id = _put_governance(client, org, ai_admin, "# 새 규칙" + chr(10) * 2 + "- 한 줄").json()[
        "request_id"
    ]
    html = _as_admin(client).get(f"/orgs/{org.pk}/requests/{req_id}").content.decode()
    assert "회의에서 정한 규칙을 반영합니다" in html
    assert "허용하면 적용될 전체 글" in html and "- 한 줄" in html
    assert (
        "회의에서 정한 규칙을 반영합니다"
        in client.get(f"/orgs/{org.pk}/governance").content.decode()
    )


def test_locked_items_are_shown_by_name(client, org, ai_admin):
    from orgs.settings import SPECS

    key = next(k for k, s in SPECS.items() if s.overridable)
    req_id = _put_settings(
        client, org, ai_admin, {"_locked": [key], "ai.create_task": "deny"}
    ).json()["request_id"]
    html = _as_admin(client).get(f"/orgs/{org.pk}/requests/{req_id}").content.decode()
    assert SPECS[key].label in html and key not in html
