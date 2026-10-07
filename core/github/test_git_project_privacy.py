"""Sol 검토 R7: 연동 프로젝트 선택기·GitHub 블록이 못 보는 연결 프로젝트·저장소를 드러내지 않는다."""

import pytest

from accounts.models import ApiToken, User
from github.models import GitHubIdentity, RepoConnection, TaskGitLink
from orgs.models import OrgMembership
from projects.services import create_project
from tasks import services as ts
from tasks.models import ChangeLog

pytestmark = pytest.mark.django_db


@pytest.fixture
def hidden(gh, org, admin, project, task):
    """공개 주 프로젝트(o/r) 태스크에 비공개 프로젝트 Q(secret/repo)를 확정 연결하고 Q를 연동 프로젝트로."""
    RepoConnection.objects.create(project=project, url="u", full_name="o/r", created_by=admin)
    q = create_project(org=org, name="비밀Q", actor=admin, visibility="teams")
    RepoConnection.objects.create(project=q, url="u2", full_name="secret/repo", created_by=admin)
    ts.link_project(task, q, actor=admin)  # 주가 공개라 확대 없음 → 바로 확정
    task.refresh_from_db()
    task = ts.update_task(
        task, {"git_project": q}, actor=admin, source="web", expected_version=task.version
    )
    u = User.objects.create_user("u1", password="pw12345678", display_name="유")
    OrgMembership.objects.create(org=org, user=u, role="member")
    # U는 GitHub에서 두 저장소를 모두 볼 수 있어도 PM에서 Q를 못 본다.
    GitHubIdentity.objects.create(
        user=u,
        github_id=99,
        login="u",
        repos=["o/r", "secret/repo"],
    )
    # 연동 저장소에 이미 작업(브랜치)이 이어져 있다.
    TaskGitLink.objects.create(task=task, connection=q.repo, branch="feat/secret")
    return task, q, u


def test_panel_hides_unseen_project_and_repo(client, hidden):
    task, q, u = hidden
    client.force_login(u)
    html = client.get(f"/tasks/{task.pk}").content.decode()
    assert "비밀Q" not in html and "secret/repo" not in html
    assert [p.pk for p in ts.git_project_choices(task, u)] == [task.project_id]


def test_api_hides_unseen_git_project_id(client, hidden):
    task, q, u = hidden
    _, raw = ApiToken.issue(u, "t", "read", for_ai=False)
    h = {"Authorization": f"Bearer {raw}"}
    body = client.get(f"/api/tasks/{task.pk}", headers=h).json()
    assert body["git_project_id"] is None and body["linked_projects"] == []
    assert ChangeLog.objects.filter(target_id=task.pk, new_value=str(q.pk)).exists()
    hist = client.get(f"/api/tasks/{task.pk}/history", headers=h).json()
    assert all(
        str(q.pk) not in (h["old_value"], h["new_value"])
        for h in hist
        if h["field"] in ("projects", "git_project")
    )
    gh = client.get(f"/api/tasks/{task.pk}/github", headers=h).json()
    assert "secret/repo" not in str(gh)
