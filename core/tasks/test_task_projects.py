"""IMPL-PLAN-11 §3(P1a): 태스크 다중 프로젝트 연결 · 열람 = 주 ∪ 확정 연결 · 열람 확대 = 관리자 승인."""

from datetime import timedelta

import pytest
from django.core.files.uploadedfile import SimpleUploadedFile
from django.utils import timezone

from accounts.models import ApiToken, User
from common.errors import Forbidden, ServiceError
from orgs.models import OrgMembership
from orgs.services import add_team_member, create_team
from projects.services import create_project
from reports.services import org_status, weekly
from tasks import attachments as at
from tasks import services as ts
from tasks.models import ChangeLog, Notice, TaskProject

pytestmark = pytest.mark.django_db


def _user(org, name, role="member"):
    u = User.objects.create_user(
        name,
        password="pw12345678",
        display_name=name,
        discord_user_id=f"9{User.objects.count()}",
        discord_linked_at=timezone.now(),
    )
    OrgMembership.objects.create(org=org, user=u, role=role)
    return u


@pytest.fixture
def w(org, admin, member):
    """비공개 주 프로젝트(secret: 팀원 member, 관리자 owner) + 공개 프로젝트(public) + 바깥 멤버(other)."""
    owner = _user(org, "owner")
    other = _user(org, "other")
    team = create_team(org=org, name="비밀팀", actor=admin)
    add_team_member(team, member, admin)
    secret = create_project(
        org=org, name="비공개", actor=admin, owners=[owner], teams=[team], visibility="teams"
    )
    public = create_project(org=org, name="공개", actor=admin)
    task = ts.create_task(
        project=secret, title="Swagger 노출 문제", actor=member, source="web", no_due_reason="-"
    )

    class W:
        pass

    for k, v in dict(owner=owner, other=other, secret=secret, public=public, task=task).items():
        setattr(W, k, v)
    return W


def _visible(user, task):
    return ts.visible_tasks(user).filter(pk=task.pk).exists()


# ---------- 열람 확대 판정 ----------


def test_widening_counts_only_new_viewers(w, member, admin):
    assert [u.pk for u in ts.widening(w.task, w.public)] == [w.other.pk]
    # 공개 주 프로젝트는 이미 조직 전원이 보므로 확대가 없다.
    t2 = ts.create_task(
        project=w.public, title="공개 일", actor=admin, source="web", no_due_reason="-"
    )
    assert ts.widening(t2, w.secret) == []


def test_link_without_confirm_is_refused(w, member):
    with pytest.raises(ts.WideningRequired) as e:
        ts.link_project(w.task, w.public, actor=member)
    assert "열람자" in e.value.errors["confirm"] and "1명" in e.value.errors["confirm"]
    assert not TaskProject.objects.exists()


def test_pending_link_does_not_widen(w, member, admin):
    since = timezone.now() - timedelta(seconds=1)
    link = ts.link_project(w.task, w.public, actor=member, confirm_widening=True)
    assert link.status == "pending" and link.widened
    assert not _visible(w.other, w.task)
    assert not ts.can_view_task(w.other, w.task)
    assert w.task not in list(ts.search(w.other, "Swagger"))
    from web.views import events

    assert w.task.pk not in [
        pk for pk, _ in events._changed_since(w.task.project.org, since, w.other)
    ]
    assert ChangeLog.objects.filter(
        target_id=w.task.pk, field="projects", note__contains="승인 요청"
    ).exists()
    # 승인자(조직 관리자·비공개 주 프로젝트 관리자)에게 알림.
    assert set(Notice.objects.values_list("user_id", flat=True)) >= {w.owner.pk}
    # 같은 요청을 다시 보내면 그 연결을 돌려준다(멱등).
    assert ts.link_project(w.task, w.public, actor=member, confirm_widening=True).pk == link.pk


def test_approve_then_visible_everywhere(w, member, admin, settings, tmp_path):
    settings.MEDIA_ROOT = tmp_path
    att = at.add_attachment(
        actor=member, task=w.task, upload=SimpleUploadedFile("a.png", b"\x89PNG" + b"0" * 32)
    )
    link = ts.link_project(w.task, w.public, actor=member, confirm_widening=True)
    assert not at.can_download(w.other, att)
    ts.approve_link(link, actor=w.owner)
    link.refresh_from_db()
    assert link.status == "active" and link.decided_by == w.owner
    assert _visible(w.other, w.task)
    assert w.task in list(ts.search(w.other, "Swagger"))
    assert at.can_download(w.other, att)
    assert w.task in list(ts.tasks_of(w.public))
    assert ChangeLog.objects.filter(target_id=w.task.pk, note="열람 확대 승인").exists()
    assert Notice.objects.filter(user=member, text__contains="승인했습니다").exists()
    # 연결로 보는 사람도 태스크를 다룰 수 있다(담당자 지정 포함).
    t = ts.update_task(
        w.task,
        {"assignee": w.other},
        actor=admin,
        source="web",
        expected_version=w.task.version,
    )
    assert t.assignee == w.other
    # 해제하면 다시 안 보인다.
    ts.unlink_project(w.task, w.public, actor=member)
    assert not _visible(w.other, w.task)


def test_reject_deletes_and_logs(w, member, admin):
    link = ts.link_project(w.task, w.public, actor=member, confirm_widening=True)
    ts.reject_link(link, actor=admin, reason="공개 불가")
    assert not TaskProject.objects.exists()
    assert ChangeLog.objects.filter(note="열람 확대 거절: 공개 불가").exists()
    assert Notice.objects.filter(user=member, text__contains="거절").exists()


def test_approver_rules(w, member, admin):
    link = ts.link_project(w.task, w.public, actor=member, confirm_widening=True)
    with pytest.raises(Forbidden):
        ts.approve_link(link, actor=member)  # 요청자·팀원은 승인 못 한다
    with pytest.raises(Forbidden):
        ts.approve_link(link, actor=admin, source="mcp")  # AI는 승인 못 한다
    assert ts.can_approve_widening(w.owner, w.task) and ts.can_approve_widening(admin, w.task)
    # 주 프로젝트가 공개면 조직 관리자만.
    t2 = ts.create_task(project=w.public, title="x", actor=admin, source="web", no_due_reason="-")
    w.public.owners.add(w.owner)
    assert not ts.can_approve_widening(w.owner, t2) and ts.can_approve_widening(admin, t2)


def test_no_widening_link_is_active_and_hides_private_name(w, member, admin):
    t2 = ts.create_task(
        project=w.public, title="공개 일", actor=member, source="web", no_due_reason="-"
    )
    link = ts.link_project(t2, w.secret, actor=member)
    assert link.status == "active" and not link.widened
    assert ts.linked_projects(t2, member) == [
        {"id": w.secret.pk, "name": "비공개", "status": "active"}
    ]
    assert ts.linked_projects(t2, w.other) == []  # 못 보는 연결은 이름·개수 모두 숨김


def test_link_guards(w, member, admin, org):
    with pytest.raises(ServiceError):
        ts.link_project(w.task, w.secret, actor=member)  # 주 = 연결
    from orgs.services import create_org

    other_org = create_org("다른", "", admin)
    foreign = create_project(org=other_org, name="남의", actor=admin)
    with pytest.raises(ServiceError):
        ts.link_project(w.task, foreign, actor=member)
    with pytest.raises(ServiceError):
        ts.link_project(w.task, w.public, actor=w.other, confirm_widening=True)  # 태스크를 못 본다


def test_move_primary_into_link_and_duplicate(w, member, admin):
    link = ts.link_project(w.task, w.public, actor=member, confirm_widening=True)
    ts.approve_link(link, actor=admin)
    w.task.refresh_from_db()
    dup = ts.duplicate_task(w.task, actor=member, source="web", no_due_reason="-")
    assert list(dup.project_links.values_list("project_id", "status")) == [(w.public.pk, "active")]
    t = ts.update_task(
        w.task, {"project": w.public}, actor=admin, source="web", expected_version=w.task.version
    )
    assert t.project == w.public and not t.project_links.exists()


def test_create_with_links_rolls_back_without_confirm(w, member):
    n = w.secret.tasks.count()
    with pytest.raises(ts.WideningRequired):
        ts.create_task(
            project=w.secret,
            title="새 일",
            actor=member,
            source="web",
            no_due_reason="-",
            linked_project_ids=[w.public.pk],
        )
    assert w.secret.tasks.count() == n
    t = ts.create_task(
        project=w.secret,
        title="새 일",
        actor=member,
        source="web",
        no_due_reason="-",
        linked_project_ids=[w.public.pk],
        confirm_widening=True,
    )
    assert t.project_links.get().status == "pending"


def test_aggregates_count_once_per_org_and_include_links(w, member, admin, org):
    link = ts.link_project(w.task, w.public, actor=member, confirm_widening=True)
    ts.approve_link(link, actor=admin)
    s = org_status(org, viewer=admin)
    assert s["counts"]["open"] == 1  # 태스크당 한 번
    by = {p["id"]: p for p in s["by_project"]}
    assert by[w.secret.pk]["open"] == 1 and by[w.public.pk]["open"] == 1  # 프로젝트별은 연결 포함
    # 봇(viewer None)은 공개 프로젝트에 확정 연결된 비공개 태스크도 센다.
    assert org_status(org)["counts"]["open"] == 1
    today = timezone.localdate()
    rep = weekly(org, today - timedelta(days=today.weekday()), viewer=w.other)
    assert rep["counts"]["open"] == 1
    assert {p["project"]["id"]: p["open"] for p in rep["by_project"]}[w.public.pk] == 1


# ---------- API·MCP 경로 ----------


def _api(client, user, for_ai=False):
    _, raw = ApiToken.issue(user, "t", "write", for_ai=for_ai)
    h = {"Authorization": f"Bearer {raw}"}

    def call(method, url, data=None):
        return getattr(client, method)(url, data=data, content_type="application/json", headers=h)

    return call


def test_api_link_flow(client, w, member, admin):
    call = _api(client, member)
    url = f"/api/tasks/{w.task.pk}/projects"
    r = call("post", url, {"project_id": w.public.pk})
    assert r.status_code == 400
    body = r.json()
    assert body["error"] == "visibility_widening" and body["widening_count"] == 1
    assert body["widening"][0]["id"] == w.other.pk
    r = call("post", url, {"project_id": w.public.pk, "confirm_visibility_widening": True})
    assert r.status_code == 201 and r.json()["status"] == "pending"
    assert call("post", f"{url}/{w.public.pk}/approve").status_code == 403  # 요청자는 승인 못 한다
    ai = _api(client, admin, for_ai=True)
    assert ai("post", f"{url}/{w.public.pk}/approve").status_code == 403  # AI 토큰은 승인 못 한다
    other = _api(client, w.other)
    assert other("get", f"/api/tasks/{w.task.pk}").status_code == 404
    assert _api(client, admin)("post", f"{url}/{w.public.pk}/approve").status_code == 200
    assert other("get", f"/api/tasks/{w.task.pk}").status_code == 200
    items = other("get", f"/api/tasks?project={w.public.pk}").json()["items"]
    assert [t["id"] for t in items] == [w.task.pk]
    assert other("get", f"/api/tasks?project={w.public.pk}&primary_only=true").json()["items"] == []
    got = call("get", f"/api/tasks/{w.task.pk}").json()
    assert got["linked_projects"] == [{"id": w.public.pk, "name": "공개", "status": "active"}]
    assert got["git_project_id"] is None
    assert call("delete", f"{url}/{w.public.pk}").status_code == 204
    assert other("get", f"/api/tasks/{w.task.pk}").status_code == 404


def test_api_create_with_links_needs_confirm(client, w, member):
    call = _api(client, member, for_ai=True)  # MCP가 보내는 것과 같은 AI 토큰
    body = {
        "project_id": w.secret.pk,
        "title": "새 일",
        "no_due_reason": "-",
        "linked_project_ids": [w.public.pk],
    }
    r = call("post", "/api/tasks", body)
    assert r.status_code == 400 and r.json()["error"] == "visibility_widening"
    r = call("post", "/api/tasks", {**body, "confirm_visibility_widening": True})
    assert r.status_code == 201
    assert r.json()["linked_projects"] == [{"id": w.public.pk, "name": "공개", "status": "pending"}]


def test_api_reject(client, w, member, admin):
    ts.link_project(w.task, w.public, actor=member, confirm_widening=True)
    r = _api(client, admin)(
        "post", f"/api/tasks/{w.task.pk}/projects/{w.public.pk}/reject", {"reason": "안 됨"}
    )
    assert r.status_code == 204 and not TaskProject.objects.exists()
