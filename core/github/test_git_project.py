"""IMPL-PLAN-11 P1b(§3.3, 결정 1-2): 연결 프로젝트가 있는 태스크는 사용자가 고른 연동 프로젝트만 따른다."""

import pytest

from common.errors import ServiceError
from github import services as ghs
from github import writes
from github.conftest import signed
from github.models import GitEvent, RepoConnection, TaskGitLink
from projects.docs import create_doc, link_task
from projects.services import create_project
from tasks import services as ts
from tasks.models import ChangeLog

pytestmark = pytest.mark.django_db


@pytest.fixture
def two(gh, org, admin, project, task):
    """project(저장소 o/r) + other(저장소 o/s). task는 project가 주이고 other에 확정 연결된다."""
    conn = RepoConnection.objects.create(
        project=project, url="https://github.com/o/r.git", full_name="o/r", created_by=admin
    )
    other = create_project(org=org, name="연결", actor=admin, owners=[admin], status="active")
    conn2 = RepoConnection.objects.create(
        project=other, url="https://github.com/o/s.git", full_name="o/s", created_by=admin
    )
    ts.link_project(task, other, actor=admin)
    task.refresh_from_db()
    return conn, conn2, other


def _branch(client, repo, task, delivery):
    payload = {
        "repository": {"full_name": repo},
        "ref": f"feat/TASK-{task.pk}",
        "ref_type": "branch",
        "sender": {"id": 1, "login": "dev"},
    }
    return signed(client, payload, "create", delivery)


def test_no_links_keeps_primary(gh, client, admin, project, task):
    RepoConnection.objects.create(project=project, url="u", full_name="o/r", created_by=admin)
    assert ts.effective_git_project(task) == project
    _branch(client, "o/r", task, "b0")
    task.refresh_from_db()
    assert task.status == "doing"


def test_linked_unselected_ignores_every_repo(client, task, two):
    conn, conn2, other = two
    assert ts.effective_git_project(task) is None
    _branch(client, "o/r", task, "b1")
    _branch(client, "o/s", task, "b2")
    task.refresh_from_db()
    assert task.status == "todo" and not TaskGitLink.objects.filter(task=task).exists()
    assert GitEvent.objects.get(delivery_id=f"b1:{conn.pk}").task is None  # 미매칭으로 남는다
    assert ghs.task_repo_state(task.assignee, task)["state"] == "unselected"
    with pytest.raises(ServiceError):
        writes.create_branch(task, "feat/x", actor=task.assignee)


def test_selected_repo_only(client, admin, task, two):
    conn, conn2, other = two
    t = ts.update_task(
        task, {"git_project": other}, actor=admin, source="web", expected_version=task.version
    )
    assert ts.effective_git_project(t) == other
    assert ChangeLog.objects.filter(target_id=t.pk, field="git_project").exists()
    _branch(client, "o/r", t, "b3")
    t.refresh_from_db()
    assert t.status == "todo"
    _branch(client, "o/s", t, "b4")
    t.refresh_from_db()
    assert t.status == "doing" and t.git.connection == conn2
    # 손 연결도 연동 프로젝트 저장소의 이벤트만.
    ev = GitEvent.objects.get(delivery_id=f"b3:{conn.pk}")
    with pytest.raises(ServiceError):
        ghs.link_event(ev, t, actor=admin)


def test_choice_must_be_primary_or_link_with_repo(admin, org, task, two):
    stray = create_project(org=org, name="무관", actor=admin)
    with pytest.raises(ServiceError):
        ts.update_task(
            task, {"git_project": stray}, actor=admin, source="web", expected_version=task.version
        )
    alone = ts.create_task(
        project=task.project, title="연결 없음", actor=admin, source="web", no_due_reason="-"
    )
    with pytest.raises(ServiceError):  # 연결이 없으면 고르지 않는다(주 프로젝트를 따른다)
        ts.update_task(
            alone,
            {"git_project": task.project},
            actor=admin,
            source="web",
            expected_version=alone.version,
        )


def test_unlink_and_disconnect_turn_off(admin, task, two):
    conn, conn2, other = two
    t = ts.update_task(
        task, {"git_project": other}, actor=admin, source="web", expected_version=task.version
    )
    ts.unlink_project(t, other, actor=admin)
    t.refresh_from_db()
    assert t.git_project_id is None
    assert ts.effective_git_project(t) == t.project  # 연결 0개 → 다시 주 프로젝트
    ts.link_project(t, other, actor=admin)
    t.refresh_from_db()
    t = ts.update_task(
        t, {"git_project": other}, actor=admin, source="web", expected_version=t.version
    )
    ghs.disconnect_repo(project=other, actor=admin)
    t.refresh_from_db()
    assert t.git_project_id is None


def test_first_link_keeps_running_github_work(admin, org, project, task, gh):
    RepoConnection.objects.create(project=project, url="u", full_name="o/r", created_by=admin)
    project.refresh_from_db()
    TaskGitLink.objects.create(task=task, connection=project.repo, branch="feat/x")
    other = create_project(org=org, name="연결", actor=admin)
    ts.link_project(task, other, actor=admin)
    task.refresh_from_db()
    assert task.git_project == project  # 진행 중 작업은 주 프로젝트로 자동 지정


def test_api_and_web_select(client, admin, task, two):
    from accounts.models import ApiToken

    conn, conn2, other = two
    _, raw = ApiToken.issue(admin, "t", "write", for_ai=False)
    r = client.patch(
        f"/api/tasks/{task.pk}",
        {"version": task.version, "git_project_id": other.pk},
        content_type="application/json",
        headers={"Authorization": f"Bearer {raw}"},
    )
    assert r.status_code == 200 and r.json()["git_project_id"] == other.pk
    task.refresh_from_db()
    client.force_login(admin)
    r = client.post(
        f"/tasks/{task.pk}/git/project",
        {"project": "", "version": task.version},
        headers={"HX-Request": "true"},
    )
    assert r.status_code == 200 and "연동 프로젝트를 선택하세요" in r.content.decode()
    task.refresh_from_db()
    assert task.git_project_id is None


def test_move_keeps_org_and_team_docs(admin, org, project, task):
    """옮길 때 끊는 것은 열람 범위 밖 프로젝트 문서뿐이다. 조직·팀 문서(project 없음)는 남는다."""
    pdoc = create_doc(project=project, title="프로젝트 문서", actor=admin)
    link_task(pdoc, task, admin)
    odoc = create_doc(org=org, title="조직 문서", actor=admin)
    link_task(odoc, task, admin)
    dest = create_project(org=org, name="옮길 곳", actor=admin)
    ts.link_project(task, dest, actor=admin)
    task.refresh_from_db()
    t = ts.update_task(
        task, {"project": dest}, actor=admin, source="web", expected_version=task.version
    )
    assert set(t.docs.values_list("pk", flat=True)) == {odoc.pk}
