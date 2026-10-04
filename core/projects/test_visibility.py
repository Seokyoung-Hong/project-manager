"""IMPL-PLAN-7 F: 프로젝트 공개 범위(`Project.visibility`). 노출 경로별 회귀 테스트."""

from datetime import timedelta

import pytest
from django.core.files.uploadedfile import SimpleUploadedFile
from django.utils import timezone

from accounts.models import ApiToken, User
from common.dates import last_week_start, today_kst
from common.errors import ServiceError
from notes.services import create_note, visible_notes
from orgs.models import OrgMembership
from projects.docs import create_doc
from projects.services import (
    can_view_project,
    create_project,
    set_visibility,
    update_project,
    visible_projects,
)
from reports.services import org_status, weekly
from tasks import attachments as at
from tasks import work_requests as wr
from tasks.services import create_task, visible_tasks

pytestmark = pytest.mark.django_db
HX = {"HX-Request": "true"}
PNG = b"\x89PNG\r\n\x1a\n" + b"0" * 64


@pytest.fixture(autouse=True)
def _media(settings, tmp_path):
    settings.MEDIA_ROOT = tmp_path


@pytest.fixture
def other(org):
    """담당 팀이 아닌 일반 멤버(Discord 연결됨)."""
    u = User.objects.create_user(
        "other1",
        password="pw12345678",
        display_name="다른멤버",
        discord_user_id="222",
        discord_linked_at=timezone.now(),
    )
    OrgMembership.objects.create(org=org, user=u, role="member")
    return u


@pytest.fixture
def owner(org):
    """프로젝트 관리자지만 담당 팀은 아닌 멤버."""
    u = User.objects.create_user("owner1", password="pw12345678", display_name="플젝관리자")
    OrgMembership.objects.create(org=org, user=u, role="member")
    return u


@pytest.fixture
def secret(org, admin, owner, team):
    return create_project(
        org=org, name="비밀기획", actor=admin, owners=[owner], teams=[team], visibility="teams"
    )


@pytest.fixture
def secret_task(secret, member):
    return create_task(
        project=secret,
        title="극비태스크",
        actor=member,
        source="web",
        due_date=today_kst() + timedelta(days=1),
    )


def _login(client, username):
    client.login(username=username, password="pw12345678")
    return client


def _bearer(user, scope="write"):
    _, raw = ApiToken.issue(user, "t", scope, for_ai=False)
    return {"Authorization": f"Bearer {raw}"}


# ---------- 규칙 ----------


def test_visible_projects_rule(org, admin, member, other, owner, project, secret):
    assert set(visible_projects(other, org)) == {project}
    for u in (admin, member, owner):
        assert set(visible_projects(u, org)) == {project, secret}
        assert can_view_project(u, secret)
    assert not can_view_project(other, secret)


def test_outsider_sees_nothing(outsider, project):
    assert not visible_projects(outsider).exists()
    assert not can_view_project(outsider, project)


def test_only_admin_sets_visibility(org, admin, owner, member, project, secret):
    with pytest.raises(ServiceError):
        create_project(org=org, name="x", actor=member, visibility="teams")
    with pytest.raises(ServiceError):
        set_visibility(project, "teams", actor=owner)
    # 비공개 프로젝트의 담당 팀 = View 권한이라 프로젝트 관리자도 못 바꾼다.
    with pytest.raises(ServiceError):
        update_project(secret, {"teams": []}, actor=owner, expected_version=secret.version)
    p = set_visibility(project, "teams", actor=admin)
    assert p.visibility == "teams"
    assert p.version == 2


def test_assignee_must_see_project(secret, member, other):
    with pytest.raises(ServiceError) as e:
        create_task(
            project=secret,
            title="t",
            actor=member,
            assignee=other,
            source="web",
            due_date=today_kst(),
        )
    assert "볼 수 없는" in e.value.errors["assignee"]


def test_visible_tasks_notes_requests(org, admin, other, member, secret, secret_task):
    assert secret_task not in visible_tasks(other)
    assert secret_task in visible_tasks(member)
    note = create_note(org=org, actor=member, title="비밀회의", project=secret)
    assert note not in visible_notes(other)
    assert note in visible_notes(member)
    with pytest.raises(ServiceError):
        create_note(org=org, actor=other, project=secret)
    req = wr.create_request(
        org=org, kind="work", title="부탁", to_user=admin, actor=other, source="web"
    )
    assert secret not in wr.projects_for(req, other)
    assert secret in wr.projects_for(req, admin)


# ---------- 웹 ----------


def test_web_paths_hide_private_project(client, org, other, project, secret, secret_task):
    c = _login(client, "other1")
    assert c.get(f"/projects/{secret.pk}").status_code == 404
    assert c.get(f"/tasks/{secret_task.pk}").status_code == 404
    assert c.get(f"/projects/{secret.pk}/docs").status_code == 404
    for url in (
        f"/orgs/{org.pk}",
        f"/projects/{project.pk}",
        "/me",
        "/search?q=극비",
        f"/orgs/{org.pk}/capacity",
        f"/orgs/{org.pk}/roadmap",
    ):
        body = c.get(url).content.decode()
        assert "비밀기획" not in body and "극비태스크" not in body, url


def test_web_member_sees_private_project_with_badge(client, member, secret, secret_task):
    c = _login(client, "member1")
    r = c.get(f"/projects/{secret.pk}")
    assert r.status_code == 200 and "🔒" in r.content.decode()
    assert "극비태스크" in c.get("/search?q=극비").content.decode()


def test_project_dialog_visibility_admin_only(client, admin, project):
    body = _login(client, "member1").get(f"/projects/{project.pk}/edit", headers=HX)
    assert "공개 범위" not in body.content.decode()
    client.logout()
    c = _login(client, "admin1")
    assert "공개 범위" in c.get(f"/projects/{project.pk}/edit", headers=HX).content.decode()
    r = c.post(
        f"/projects/{project.pk}/edit",
        {
            "name": project.name,
            "status": project.status,
            "owners": [admin.pk],
            "visibility": "teams",
            "version": project.version,
        },
        headers=HX,
    )
    assert r.status_code == 204
    project.refresh_from_db()
    assert project.visibility == "teams"


def test_team_screen_grants_private_projects(client, org, admin, other, secret):
    from orgs.services import add_team_member, create_team

    design = create_team(org=org, name="디자인", actor=admin)
    add_team_member(design, other, admin)
    c = _login(client, "admin1")
    assert "이 팀이 볼 수 있는 비공개 프로젝트" in c.get(f"/teams/{design.pk}").content.decode()
    c.post(f"/teams/{design.pk}/visible-projects", {"projects": [secret.pk]})
    assert can_view_project(other, secret)
    c.post(f"/teams/{design.pk}/visible-projects", {})
    assert not can_view_project(other, secret)
    client.logout()
    r = _login(client, "other1").post(
        f"/teams/{design.pk}/visible-projects", {"projects": [secret.pk]}
    )
    assert r.status_code == 404
    assert not can_view_project(other, secret)


# ---------- API (MCP·스킬도 이 API를 쓴다) ----------


def test_api_paths_hide_private_project(client, org, other, secret, secret_task):
    h = _bearer(other)
    assert client.get(f"/api/projects/{secret.pk}", headers=h).status_code == 404
    assert secret.pk not in [p["id"] for p in client.get("/api/projects", headers=h).json()]
    assert client.get(f"/api/tasks/{secret_task.pk}", headers=h).status_code == 404
    assert client.get(f"/api/tasks?project={secret.pk}", headers=h).json()["items"] == []
    r = client.get(f"/api/orgs/{org.pk}/tasks?project={secret.pk}", headers=h)
    assert r.status_code == 404
    org_body = client.get(f"/api/orgs/{org.pk}", headers=h).json()
    assert secret.pk not in [p["id"] for p in org_body["projects"]]
    status = client.get(f"/api/orgs/{org.pk}/status", headers=h).json()
    assert secret.pk not in [p["id"] for p in status["by_project"]]
    r = client.post(
        "/api/tasks",
        {"project_id": secret.pk, "title": "x", "due_date": today_kst().isoformat()},
        content_type="application/json",
        headers=h,
    )
    assert r.status_code == 404


def test_api_docs_hidden(client, member, other, secret):
    doc = create_doc(project=secret, actor=member, title="비밀문서")
    h = _bearer(other)
    assert client.get(f"/api/project-docs/{doc.pk}", headers=h).status_code == 404
    rows = client.get("/api/project-docs", headers=h).json()["items"]
    assert doc.pk not in [d["id"] for d in rows]
    assert client.get(f"/api/project-docs/{doc.pk}", headers=_bearer(member)).status_code == 200


def test_api_visibility_field(client, admin, member, project):
    got = client.get(f"/api/projects/{project.pk}", headers=_bearer(member)).json()
    assert got["visibility"] == "org"
    body = {"version": project.version, "visibility": "teams"}
    r = client.patch(
        f"/api/projects/{project.pk}",
        body,
        content_type="application/json",
        headers=_bearer(member),
    )
    assert r.status_code == 400
    r = client.patch(
        f"/api/projects/{project.pk}", body, content_type="application/json", headers=_bearer(admin)
    )
    assert r.status_code == 200 and r.json()["visibility"] == "teams"


# ---------- 첨부 ----------


def test_attachments_follow_visibility(client, member, other, secret_task):
    att = at.add_attachment(
        actor=member, task=secret_task, upload=SimpleUploadedFile("a.png", PNG, "image/png")
    )
    assert at.can_download(member, att)
    assert not at.can_download(other, att)
    with pytest.raises(ServiceError):
        at.add_attachment(
            actor=other, task=secret_task, upload=SimpleUploadedFile("b.png", PNG, "image/png")
        )
    h = _bearer(other)
    assert client.get(f"/api/attachments/{att.pk}/download", headers=h).status_code == 404
    assert client.get(f"/api/tasks/{secret_task.pk}/attachments", headers=h).status_code == 404
    assert _login(client, "other1").get(f"/attachments/{att.pk}/a.png").status_code == 404


# ---------- 보고서·Discord ----------


def _names(data):
    return [r["project"]["name"] for r in data["by_project"]]


def test_weekly_and_status_exclude_private_without_viewer(org, admin, other, secret, secret_task):
    ws = last_week_start()
    assert "비밀기획" not in _names(weekly(org, ws))
    assert "비밀기획" not in _names(weekly(org, ws, viewer=other))
    assert "비밀기획" in _names(weekly(org, ws, viewer=admin))
    assert weekly(org, ws)["counts"]["open"] == 0
    assert "비밀기획" not in [p["name"] for p in org_status(org)["by_project"]]
    assert org_status(org, viewer=admin)["counts"]["open"] == 1


def test_api_weekly_bot_token_excludes_private(client, org, admin, secret, secret_task):
    url = f"/api/reports/weekly?org={org.pk}&week_start={last_week_start().isoformat()}"
    assert "비밀기획" not in _names(client.get(url, headers=_bearer(admin, "bot")).json())
    assert "비밀기획" in _names(client.get(url, headers=_bearer(admin)).json())


def test_discord_project_autocomplete(client, admin, member, other, secret):
    h = _bearer(admin, "bot")

    def ids(did):
        r = client.post(
            "/api/integrations/discord/projects",
            {"discord_user_id": did},
            content_type="application/json",
            headers=h,
        )
        return [p["id"] for p in r.json()]

    assert secret.pk in ids("111")
    assert secret.pk not in ids("222")


def test_deadline_dm_skips_assignee_who_lost_access(org, admin, secret, secret_task):
    from orgs.discord import deadline_alerts

    assert secret_task.pk in [t.pk for t, _ in deadline_alerts(org, today_kst())]
    update_project(secret, {"teams": []}, actor=admin, expected_version=secret.version)
    assert secret_task.pk not in [t.pk for t, _ in deadline_alerts(org, today_kst())]


# ---------- Sol 교차 검토 반려 4건(라운드 7) ----------


def test_idempotency_key_cannot_replay_task_after_losing_access(
    client, admin, member, project, secret
):
    h = {**_bearer(member), "Idempotency-Key": "k-1"}
    body = {"project_id": secret.pk, "title": "극비키태스크", "due_date": today_kst().isoformat()}
    r = client.post("/api/tasks", body, content_type="application/json", headers=h)
    assert r.status_code == 201
    update_project(secret, {"teams": []}, actor=admin, expected_version=secret.version)
    body["project_id"] = project.pk
    r = client.post("/api/tasks", body, content_type="application/json", headers=h)
    assert r.status_code == 400
    assert "극비키태스크" not in r.content.decode()


def test_idempotency_key_bound_to_target_project(member, project, secret):
    kw = {"title": "a", "actor": member, "source": "api", "due_date": today_kst()}
    first = create_task(project=secret, idempotency_key="k-2", **kw)
    assert create_task(project=secret, idempotency_key="k-2", **kw) == first
    with pytest.raises(ServiceError):
        create_task(project=project, idempotency_key="k-2", **kw)


def test_series_hides_child_moved_to_private_project(client, admin, member, other, project, secret):
    from tasks.services import duplicate_task, update_task

    root = create_task(
        project=project, title="공개뿌리", actor=member, source="web", due_date=today_kst()
    )
    child = duplicate_task(root, actor=member, source="web", title="숨은회차", due_date=today_kst())
    update_task(
        child, {"project": secret}, actor=admin, source="web", expected_version=child.version
    )
    assert "숨은회차" not in _login(client, "other1").get(f"/tasks/{root.pk}").content.decode()
    client.logout()  # 세션 인증이 Bearer보다 먼저 잡힌다
    got = client.get(f"/api/tasks/{root.pk}", headers=_bearer(other)).json()
    assert got["children_count"] == 0
    got = client.get(f"/api/tasks/{root.pk}", headers=_bearer(member)).json()
    assert got["children_count"] == 1


def test_docs_unlinked_when_task_moves_out(
    client, admin, member, other, project, secret, secret_task
):
    from projects.docs import link_task
    from tasks.services import update_task

    doc = create_doc(project=secret, actor=member, title="비밀문서제목")
    link_task(doc, secret_task, member)
    update_task(
        secret_task,
        {"project": project},
        actor=admin,
        source="web",
        expected_version=secret_task.version,
    )
    r = client.get(f"/api/tasks/{secret_task.pk}", headers=_bearer(other))
    assert r.json()["docs"] == [] and "비밀문서제목" not in r.content.decode()
    body = _login(client, "other1").get(f"/tasks/{secret_task.pk}").content.decode()
    assert "비밀문서제목" not in body


def test_private_team_details_hidden_in_project_out(client, org, admin, member, other, project):
    from orgs.services import add_team_member, create_team

    hr = create_team(org=org, name="인사", purpose="연봉협상", actor=admin, is_private=True)
    add_team_member(hr, member, admin)
    update_project(project, {"teams": [hr]}, actor=admin, expected_version=project.version)

    def team_of(user, url):
        data = client.get(url, headers=_bearer(user)).json()
        rows = data if isinstance(data, list) else data.get("projects", [data])
        return next(x for x in rows if x["id"] == project.pk)["teams"][0]

    for url in (f"/api/projects/{project.pk}", "/api/projects", f"/api/orgs/{org.pk}"):
        t = team_of(other, url)
        assert t["name"] == "인사" and t["purpose"] is None and t["member_count"] is None, url
        t = team_of(member, url)
        assert t["purpose"] == "연봉협상" and t["member_count"] == 1, url
    rows = client.get(f"/api/orgs/{org.pk}/teams", headers=_bearer(other)).json()
    assert next(r for r in rows if r["id"] == hr.pk)["purpose"] is None
