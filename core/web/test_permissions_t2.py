"""T2: 웹 뷰의 상태 변경(POST) 경로와 권한 검사.

같은 요청 목록으로 다섯 가지를 본다.
- 정상: 권한자가 보내면 상태가 바뀐다(요청 본문이 맞는지 확인 — 거부 테스트가 헛돌지 않게).
- 비로그인: /login으로 보내고 아무것도 바꾸지 않는다.
- 조직 밖: 404, 변화 없음.
- 비공개 프로젝트를 못 보는 멤버: 404, 변화 없음.
- 관리자 전용 동작(멤버·팀·초대)은 일반 멤버가 보내도 변화가 없다.
"""

from datetime import timedelta
from types import SimpleNamespace

import pytest
from django.test import Client

from accounts.models import User
from common.dates import today_kst
from notes.models import MeetingNote
from notes.services import create_note
from orgs.models import Invite, OrgMembership, Team, TeamMembership
from orgs.services import create_team
from projects.docs import create_doc
from projects.models import Milestone, Project, ProjectDependency, ProjectDoc
from projects.services import (
    archive_project,
    create_dependency,
    create_milestone,
    create_project,
)
from tasks import services as ts
from tasks.models import ChecklistItem, Link, Task, TodayItem

pytestmark = pytest.mark.django_db
PW = "pw12345678"


# ---------- 픽스처 ----------


@pytest.fixture
def other(org):
    """담당 팀이 아닌 일반 멤버."""
    u = User.objects.create_user("other1", password=PW, display_name="다른멤버")
    OrgMembership.objects.create(org=org, user=u, role="member")
    return u


@pytest.fixture
def secret(org, admin, team):
    """담당 팀(team)만 보는 비공개 프로젝트."""
    return create_project(
        org=org, name="비밀기획", actor=admin, owners=[admin], teams=[team], visibility="teams"
    )


def _scope(org, admin, member, project, other_project):
    task = ts.create_task(
        project=project,
        title="범위 태스크",
        actor=member,
        source="web",
        due_date=today_kst() + timedelta(days=3),
    )
    return SimpleNamespace(
        project=project,
        task=task,
        item=ts.checklist_add(task, "항목", actor=admin),
        tlink=ts.add_link(actor=admin, task=task, title="t", url="https://e.com/t"),
        plink=ts.add_link(actor=admin, project=project, title="p", url="https://e.com/p"),
        doc=create_doc(project=project, actor=admin, title="문서", body_md="x"),
        note=create_note(org=org, actor=admin, project=project, title="노트"),
        ms=create_milestone(
            project=project,
            name="M1",
            target_date=today_kst() + timedelta(days=30),
            actor=admin,
        ),
        dep=create_dependency(from_project=project, to_project=other_project, actor=admin),
    )


@pytest.fixture
def pub(org, admin, member, project):
    """공개 프로젝트에 붙은 여러 객체."""
    other_p = create_project(org=org, name="상대", actor=admin, owners=[admin], status="active")
    return _scope(org, admin, member, project, other_p)


@pytest.fixture
def sec(org, admin, member, secret, project):
    return _scope(org, admin, member, secret, project)


@pytest.fixture
def invite(org, admin):
    return Invite.objects.create(org=org, created_by=admin)


def _as(username):
    c = Client()
    assert c.login(username=username, password=PW)
    return c


def _state():
    """거부된 요청 뒤에도 그대로여야 하는 값들의 스냅샷."""
    q = lambda qs, *f: list(qs.order_by("pk").values_list("pk", *f))  # noqa: E731
    return {
        "projects": q(Project.objects, "is_archived", "name", "version"),
        "tasks": q(
            Task.objects, "status", "title", "priority", "due_date", "assignee_id", "version"
        ),
        "checklist": q(ChecklistItem.objects, "is_done", "text"),
        "links": q(Link.objects, "title"),
        "docs": q(ProjectDoc.objects, "version", "body_md"),
        "doc_tasks": list(ProjectDoc.tasks.through.objects.values_list("pk")),
        "note_tasks": list(MeetingNote.tasks.through.objects.values_list("pk")),
        "today": q(TodayItem.objects, "excluded"),
        "notes": q(MeetingNote.objects, "version", "body_md"),
        "ms": q(Milestone.objects, "name", "status"),
        "deps": q(ProjectDependency.objects),
        "members": q(OrgMembership.objects, "role", "tags"),
        "teams": q(Team.objects, "name", "is_private"),
        "tm": q(TeamMembership.objects, "user_id", "is_lead"),
        "invites": q(Invite.objects, "revoked_at"),
    }


# ---------- 프로젝트·태스크에 매인 요청 ----------

SCOPED = {
    "task_create": (
        lambda s: f"/projects/{s.project.pk}/tasks",
        {"title": "새 일", "assignee": "ME", "priority": "5", "due_date": "2030-01-02"},
    ),
    "project_link_add": (
        lambda s: f"/projects/{s.project.pk}/links",
        {"title": "새링크", "url": "https://e.com/n", "kind": "doc"},
    ),
    "project_archive": (lambda s: f"/projects/{s.project.pk}/archive", {"cancel_open": "1"}),
    "doc_new": (lambda s: f"/projects/{s.project.pk}/docs/new", {"title": "새문서"}),
    "doc_save": (
        lambda s: f"/docs/{s.doc.pk}/save",
        {"field": "title", "value": "바뀜", "version": "1"},
    ),
    "doc_delete": (lambda s: f"/docs/{s.doc.pk}/delete", {}),
    "task_status": (lambda s: f"/tasks/{s.task.pk}/status", {"status": "doing", "version": "V"}),
    "task_text": (lambda s: f"/tasks/{s.task.pk}/text/title", {"value": "바뀐 제목"}),
    "task_priority": (lambda s: f"/tasks/{s.task.pk}/priority", {"priority": "9", "version": "V"}),
    "task_extend": (
        lambda s: f"/tasks/{s.task.pk}/extend",
        {
            "due_date": (today_kst() + timedelta(days=9)).isoformat(),
            "reason": "사유",
            "version": "V",
        },
    ),
    "task_duplicate": (
        lambda s: f"/tasks/{s.task.pk}/duplicate",
        {"title": "복제본", "due_date": "2030-01-02"},
    ),
    "task_delete": (lambda s: f"/tasks/{s.task.pk}/delete", {}),
    "checklist_add": (lambda s: f"/tasks/{s.task.pk}/checklist", {"text": "새 항목"}),
    "checklist_toggle": (lambda s: f"/tasks/checklist/{s.item.pk}/toggle", {}),
    "checklist_delete": (lambda s: f"/tasks/checklist/{s.item.pk}/delete", {}),
    "task_link_add": (
        lambda s: f"/tasks/{s.task.pk}/links",
        {"title": "새링크", "url": "https://e.com/n", "kind": "doc"},
    ),
    "link_delete_task": (lambda s: f"/tasks/links/{s.tlink.pk}/delete", {}),
    "link_delete_project": (lambda s: f"/tasks/links/{s.plink.pk}/delete", {}),
    "task_doc_link": (lambda s: f"/tasks/{s.task.pk}/docs/link", {"doc": "DOC"}),
    "task_note_link": (lambda s: f"/tasks/{s.task.pk}/notes", {"note": "NOTE"}),
    "note_save": (
        lambda s: f"/notes/{s.note.pk}/save",
        {"field": "title", "value": "바뀜", "version": "1"},
    ),
    "note_delete": (lambda s: f"/notes/{s.note.pk}/delete", {}),
    "milestone_edit": (
        lambda s: f"/milestones/{s.ms.pk}/edit",
        {
            "name": "바뀐마일스톤",
            "target_date": (today_kst() + timedelta(days=40)).isoformat(),
            "status": "planned",
        },
    ),
    "milestone_delete": (lambda s: f"/milestones/{s.ms.pk}/delete", {}),
    "dependency_delete": (lambda s: f"/dependencies/{s.dep.pk}/delete", {}),
    "today_add": (lambda s: f"/today/add/{s.task.pk}", {}),
}
NAMES = list(SCOPED)


def _req(name, s):
    make, data = SCOPED[name]
    data = dict(data)
    if data.get("doc") == "DOC":
        data["doc"] = s.doc.pk
    if data.get("note") == "NOTE":
        data["note"] = s.note.pk
    if data.get("version") == "V":
        data["version"] = s.task.version
    if data.get("assignee") == "ME":
        data["assignee"] = s.task.assignee_id
    return make(s), data


@pytest.mark.parametrize("name", NAMES)
def test_authorized_request_changes_state(name, admin, pub):
    before = _state()
    url, data = _req(name, pub)
    r = _as("admin1").post(url, data)
    assert r.status_code in (200, 204, 302), (name, r.status_code)
    assert _state() != before, f"{name}: 관리자 요청이 상태를 바꾸지 못했다"


@pytest.mark.parametrize("name", NAMES)
def test_anonymous_goes_to_login(name, pub):
    before = _state()
    url, data = _req(name, pub)
    r = Client().post(url, data)
    assert r.status_code == 302 and r["Location"].startswith("/login"), (name, r.status_code)
    assert _state() == before


@pytest.mark.parametrize("name", NAMES)
def test_other_org_gets_404_and_nothing_changes(name, outsider, pub):
    before = _state()
    url, data = _req(name, pub)
    r = _as("outsider").post(url, data)
    assert r.status_code == 404, (name, r.status_code)
    assert _state() == before


@pytest.mark.parametrize("name", NAMES)
def test_hidden_project_is_404_for_non_team_member(name, other, sec):
    before = _state()
    url, data = _req(name, sec)
    r = _as("other1").post(url, data)
    assert r.status_code == 404, (name, r.status_code)
    assert _state() == before


@pytest.mark.parametrize("name", NAMES)
def test_hidden_project_is_404_for_other_org(name, outsider, sec):
    before = _state()
    url, data = _req(name, sec)
    assert _as("outsider").post(url, data).status_code == 404
    assert _state() == before


def test_team_member_can_use_hidden_project(member, sec):
    """같은 요청이 담당 팀원에게는 통한다 — 위 404가 경로 오류가 아니라 권한임을 보인다."""
    url, data = _req("checklist_add", sec)
    assert _as("member1").post(url, data).status_code in (200, 204, 302)
    assert sec.task.checklist.count() == 2


# ---------- 프로젝트 보관·복원·삭제 ----------


def test_archive_restore_delete_lifecycle(project):
    c = _as("admin1")
    assert c.post(f"/projects/{project.pk}/archive").status_code == 302
    project.refresh_from_db()
    assert project.is_archived
    assert c.post(f"/projects/{project.pk}/restore").status_code == 302
    project.refresh_from_db()
    assert not project.is_archived
    c.post(f"/projects/{project.pk}/delete")  # 보관 전에는 거부
    assert Project.objects.filter(pk=project.pk).exists()
    c.post(f"/projects/{project.pk}/archive")
    r = c.post(f"/projects/{project.pk}/delete")
    assert r["Location"] == "/projects"
    assert not Project.objects.filter(pk=project.pk).exists()


def test_archive_with_open_tasks_needs_cancel_open(project, task):
    c = _as("admin1")
    c.post(f"/projects/{project.pk}/archive")
    project.refresh_from_db()
    assert not project.is_archived
    c.post(f"/projects/{project.pk}/archive", {"cancel_open": "1"})
    project.refresh_from_db()
    task.refresh_from_db()
    assert project.is_archived and task.status == "cancelled"


def test_only_admin_deletes_project(project, member, other, outsider, admin):
    archive_project(project, actor=admin, source="web", cancel_open=True)
    for who in ("member1", "other1"):
        _as(who).post(f"/projects/{project.pk}/delete")
        assert Project.objects.filter(pk=project.pk).exists(), who
    assert _as("outsider").post(f"/projects/{project.pk}/delete").status_code == 404
    assert Project.objects.filter(pk=project.pk).exists()


@pytest.mark.parametrize("act", ["restore", "delete"])
def test_archived_hidden_project_is_404_for_non_team(secret, other, admin, act):
    archive_project(secret, actor=admin, source="web", cancel_open=True)
    assert _as("other1").post(f"/projects/{secret.pk}/{act}").status_code == 404
    secret.refresh_from_db()
    assert secret.is_archived


@pytest.mark.parametrize("act", ["restore", "delete"])
def test_archived_project_other_org_is_404(project, outsider, admin, act):
    archive_project(project, actor=admin, source="web", cancel_open=True)
    assert _as("outsider").post(f"/projects/{project.pk}/{act}").status_code == 404
    assert Project.objects.get(pk=project.pk).is_archived


# ---------- 관리자 전용 동작 ----------


def _admin_requests(org, team, member, admin, invite):
    mm = OrgMembership.objects.get(org=org, user=member)
    return {
        "invite_create": (f"/orgs/{org.pk}/invites", {"days": "7"}),
        "invite_revoke": (f"/orgs/invites/{invite.pk}/revoke", {}),
        "member_role": (f"/orgs/memberships/{mm.pk}/role", {"role": "admin"}),
        "member_remove": (f"/orgs/memberships/{mm.pk}/remove", {}),
        "member_tags": (f"/orgs/memberships/{mm.pk}/tags", {"tags": "백엔드,AI"}),
        "team_new": (f"/orgs/{org.pk}/teams/new", {"name": "새팀", "purpose": "목적"}),
        "team_edit": (f"/teams/{team.pk}/edit", {"name": "개명", "purpose": "목적"}),
        "team_delete": (f"/teams/{team.pk}/delete", {}),
        "team_member_add": (f"/teams/{team.pk}/members", {"user": admin.pk}),
        "team_member_remove": (f"/teams/{team.pk}/members/{member.pk}/remove", {}),
        "team_lead": (f"/teams/{team.pk}/members/{member.pk}/lead", {"lead": "1"}),
        "team_visible_projects": (f"/teams/{team.pk}/visible-projects", {"projects": []}),
    }


ADMIN_NAMES = [
    "invite_create", "invite_revoke", "member_role", "member_remove", "member_tags",
    "team_new", "team_edit", "team_delete", "team_member_add", "team_member_remove",
    "team_lead", "team_visible_projects",
]  # fmt: skip


@pytest.fixture
def reqs(org, team, member, admin, invite):
    return _admin_requests(org, team, member, admin, invite)


@pytest.mark.parametrize("name", ADMIN_NAMES)
def test_admin_only_action_works_for_admin(name, reqs, secret):
    before = _state()
    url, data = reqs[name]
    r = _as("admin1").post(url, data)
    assert r.status_code in (200, 204, 302), (name, r.status_code)
    assert _state() != before, name


@pytest.mark.parametrize("name", ADMIN_NAMES)
@pytest.mark.parametrize("who", ["member1", "other1"])
def test_plain_member_cannot_do_admin_only_action(name, who, reqs, other):
    before = _state()
    url, data = reqs[name]
    r = _as(who).post(url, data)
    assert r.status_code in (302, 403, 404), (name, r.status_code)
    assert _state() == before, f"{name}: 일반 멤버({who})가 관리자 전용 동작을 해냈다"


@pytest.mark.parametrize("name", ADMIN_NAMES)
def test_other_org_cannot_do_admin_only_action(name, reqs, outsider):
    before = _state()
    url, data = reqs[name]
    assert _as("outsider").post(url, data).status_code == 404, name
    assert _state() == before


@pytest.mark.parametrize("name", ADMIN_NAMES)
def test_anonymous_admin_action_goes_to_login(name, reqs):
    before = _state()
    url, data = reqs[name]
    r = Client().post(url, data)
    assert r.status_code == 302 and r["Location"].startswith("/login")
    assert _state() == before


def test_last_admin_cannot_be_demoted_or_removed(org, admin):
    am = OrgMembership.objects.get(org=org, user=admin)
    c = _as("admin1")
    c.post(f"/orgs/memberships/{am.pk}/role", {"role": "member"})
    c.post(f"/orgs/memberships/{am.pk}/remove")
    am.refresh_from_db()
    assert am.role == "admin"


def test_member_role_and_remove_normal_path(org, member):
    mm = OrgMembership.objects.get(org=org, user=member)
    c = _as("admin1")
    c.post(f"/orgs/memberships/{mm.pk}/role", {"role": "admin"})
    mm.refresh_from_db()
    assert mm.role == "admin"
    c.post(f"/orgs/memberships/{mm.pk}/remove")
    assert not OrgMembership.objects.filter(pk=mm.pk).exists()


def test_invite_revoke_normal_path(admin, invite):
    _as("admin1").post(f"/orgs/invites/{invite.pk}/revoke")
    invite.refresh_from_db()
    assert invite.revoked_at is not None


# ---------- 마일스톤·의존성 생성 ----------


def test_dependency_and_milestone_create_via_web(org, admin, project):
    other_p = create_project(org=org, name="상대", actor=admin, owners=[admin], status="active")
    c = _as("admin1")
    c.post(
        f"/orgs/{org.pk}/dependencies",
        {"from_project": project.pk, "to_project": other_p.pk, "note": "선행"},
    )
    assert ProjectDependency.objects.filter(from_project=project, to_project=other_p).exists()
    c.post(
        f"/orgs/{org.pk}/milestones/new",
        {
            "project": project.pk,
            "name": "출시",
            "target_date": (today_kst() + timedelta(days=20)).isoformat(),
            "status": "planned",
        },
    )
    assert Milestone.objects.filter(project=project, name="출시").exists()


def test_dependency_and_milestone_create_hide_secret_project(org, other, secret, project):
    c = _as("other1")
    before = _state()
    dep = f"/orgs/{org.pk}/dependencies"
    assert c.post(dep, {"from_project": secret.pk, "to_project": project.pk}).status_code == 404
    assert c.post(dep, {"from_project": project.pk, "to_project": secret.pk}).status_code == 404
    r = c.post(
        f"/orgs/{org.pk}/milestones/new",
        {
            "project": secret.pk,
            "name": "침투",
            "target_date": (today_kst() + timedelta(days=20)).isoformat(),
        },
    )
    assert r.status_code == 404
    assert _state() == before


def test_dependency_delete_needs_both_projects_visible(other, admin, secret, project):
    dep = create_dependency(from_project=project, to_project=secret, actor=admin)
    assert _as("other1").post(f"/dependencies/{dep.pk}/delete").status_code == 404
    assert ProjectDependency.objects.filter(pk=dep.pk).exists()


# ---------- 비공개 팀 ----------


def test_private_team_detail_is_404_for_non_member(org, admin, other):
    t = create_team(org=org, name="비밀팀", actor=admin, is_private=True)
    assert _as("other1").get(f"/teams/{t.pk}").status_code == 404
    assert _as("admin1").get(f"/teams/{t.pk}").status_code == 200


@pytest.mark.parametrize(
    "path,data",
    [
        ("delete", {}),
        ("edit", {"name": "탈취", "purpose": "x"}),
        ("members", {"user": "ME"}),
        ("visible-projects", {}),
    ],
)
def test_private_team_posts_by_non_member_change_nothing(org, admin, other, path, data):
    t = create_team(org=org, name="비밀팀", actor=admin, is_private=True)
    data = {k: (other.pk if v == "ME" else v) for k, v in data.items()}
    before = _state()
    r = _as("other1").post(f"/teams/{t.pk}/{path}", data)
    assert r.status_code in (302, 403, 404)
    assert _state() == before


def test_private_team_posts_by_other_org_are_404(org, admin, outsider):
    t = create_team(org=org, name="비밀팀", actor=admin, is_private=True)
    for path in ("delete", "edit", "members", "visible-projects"):
        assert _as("outsider").post(f"/teams/{t.pk}/{path}").status_code == 404, path
    assert Team.objects.filter(pk=t.pk).exists()


# ---------- 오늘 목록(개인 상태) ----------


def test_today_exclude_and_move_hidden_task_404(other, sec):
    c = _as("other1")
    assert c.post(f"/today/exclude/{sec.task.pk}").status_code == 404
    assert c.post(f"/today/move/{sec.task.pk}/up").status_code == 404


# ---------- CSRF ----------


def _csrf_client():
    c = Client(enforce_csrf_checks=True)
    assert c.login(username="admin1", password=PW)
    return c


@pytest.mark.parametrize(
    "name", ["task_status", "checklist_add", "project_archive", "doc_delete", "milestone_delete"]
)
def test_csrf_required_on_state_changing_posts(name, admin, pub):
    before = _state()
    url, data = _req(name, pub)
    assert _csrf_client().post(url, data).status_code == 403
    assert _state() == before


@pytest.mark.parametrize("name", ["member_role", "member_remove", "invite_revoke", "team_delete"])
def test_csrf_required_on_admin_actions(name, reqs):
    before = _state()
    url, data = reqs[name]
    assert _csrf_client().post(url, data).status_code == 403
    assert _state() == before


def test_state_changing_paths_reject_get(admin, pub):
    before = _state()
    c = _as("admin1")
    for name in ("project_archive", "task_delete", "checklist_delete", "doc_delete"):
        url, _ = _req(name, pub)
        assert c.get(url).status_code == 405, name
    assert _state() == before


# ---------- 개인 토큰·결정 기록 ----------


def test_token_revoke_only_own_token(member, other):
    from accounts.models import ApiToken

    tok, _ = ApiToken.issue(member, "t", "write", for_ai=False)
    assert _as("other1").post(f"/settings/tokens/{tok.pk}/revoke").status_code == 404
    assert _as("admin1").post(f"/settings/tokens/{tok.pk}/revoke").status_code == 404
    tok.refresh_from_db()
    assert tok.revoked_at is None
    assert Client().post(f"/settings/tokens/{tok.pk}/revoke").status_code == 302
    _as("member1").post(f"/settings/tokens/{tok.pk}/revoke")
    tok.refresh_from_db()
    assert tok.revoked_at is not None


@pytest.mark.parametrize("act", ["confirm", "reject", "supersede"])
def test_decision_actions_on_hidden_task_are_404(act, other, outsider, sec):
    for who in ("other1", "outsider"):
        r = _as(who).post(f"/tasks/{sec.task.pk}/decisions/1/{act}", {"summary": "침투"})
        assert r.status_code == 404, (who, act)
    assert Client().post(f"/tasks/{sec.task.pk}/decisions/1/{act}").status_code == 302
