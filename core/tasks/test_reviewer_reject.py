"""지정 검토자 반려 권한(사용자 결정 2026-10-05). 검토 대기 → 진행 중·시작 전."""

import pytest

from accounts.models import ApiToken, User
from common.errors import ServiceError
from orgs.models import OrgMembership
from orgs.services import add_team_member, set_org_settings
from projects.services import create_project, update_project
from tasks.services import transition, update_task

pytestmark = pytest.mark.django_db
HX = {"HX-Request": "true"}


def _user(org, name):
    u = User.objects.create_user(name, password="pw12345678", display_name=name)
    OrgMembership.objects.create(org=org, user=u, role="member")
    return u


@pytest.fixture
def rv(org):
    return _user(org, "rv1")


@pytest.fixture
def bystander(org):
    return _user(org, "by1")


def _to_review(task, actor, reviewer, admin):
    task = update_task(
        task, {"reviewer": reviewer}, actor=admin, source="web", expected_version=task.version
    )
    return transition(task, "review", actor=actor, source="web", expected_version=task.version)


def test_reviewer_rejects_with_reason(org, admin, member, rv, task):
    set_org_settings(org, {"task.reject_reason_required": True}, admin)
    task = _to_review(task, member, rv, admin)
    with pytest.raises(ServiceError) as e:
        transition(task, "doing", actor=rv, source="web", expected_version=task.version)
    assert "reason" in e.value.errors
    task = transition(
        task, "doing", actor=rv, source="web", reason="시안 수정", expected_version=task.version
    )
    assert task.status == "doing"


def test_bystander_cannot_reject(admin, member, rv, bystander, task):
    task = _to_review(task, member, rv, admin)
    with pytest.raises(ServiceError) as e:
        transition(task, "todo", actor=bystander, source="web", expected_version=task.version)
    assert "반려" in e.value.errors["status"]
    # 관리자 예외와 담당자 철회는 그대로
    task = transition(task, "doing", actor=admin, source="web", expected_version=task.version)
    assert task.status == "doing"


def test_reviewer_who_cant_see_private_project_rejected(org, admin, member, team, rv):
    add_team_member(team, rv, admin)
    secret = create_project(org=org, name="비밀", actor=admin, teams=[team], visibility="teams")
    from datetime import timedelta

    from common.dates import today_kst
    from tasks.services import create_task

    t = create_task(
        project=secret,
        title="t",
        actor=member,
        source="web",
        due_date=today_kst() + timedelta(days=1),
    )
    t = _to_review(t, member, rv, admin)
    update_project(secret, {"teams": []}, actor=admin, expected_version=secret.version)
    with pytest.raises(ServiceError):
        transition(t, "doing", actor=rv, source="web", reason="x", expected_version=t.version)


def test_reviewer_sees_reject_button_and_api(client, admin, member, rv, task):
    task = _to_review(task, member, rv, admin)
    client.login(username="rv1", password="pw12345678")
    body = client.get(f"/tasks/{task.pk}/panel", headers=HX).content.decode()
    assert "반려</button>" in body
    body = client.get(f"/tasks/{task.pk}/panel?reject=1", headers=HX).content.decode()
    assert "반려 사유" in body
    client.logout()
    _, raw = ApiToken.issue(rv, "t", "write", for_ai=False)
    r = client.post(
        f"/api/tasks/{task.pk}/transition",
        {"status": "doing", "version": task.version, "reason": "보완"},
        content_type="application/json",
        headers={"Authorization": f"Bearer {raw}"},
    )
    assert r.status_code == 200 and r.json()["status"] == "doing"
