"""저장소 연결 화면의 자동완성: 조직 설치가 볼 수 있는 저장소를 입력창 datalist로 보여 준다.

`client.request`는 monkeypatch로 막는다. 실제 GitHub는 부르지 않는다.
"""

import pytest
from django.utils import timezone

from github.models import GitHubIdentity, GitHubInstallation, RepoConnection, RepoIssue
from github.services import installation_repos
from github.test_writes import _identity

pytestmark = pytest.mark.django_db


@pytest.fixture
def installed(gh, org, admin):
    GitHubInstallation.objects.create(
        org=org, installation_id=99, account_login="acme", installed_by=admin
    )
    identity = _identity(admin, "admin-gh")
    # 목록은 이 사람의 GitHub 접근 목록과 교집합이다. 요청 중 재조회로 비지 않게 시각도 채운다.
    identity.repos = ["teamSANDOL/sandol-api", "teamSANDOL/web"]
    identity.repos_checked_at = timezone.now()
    identity.save(update_fields=["repos", "repos_checked_at"])
    org.refresh_from_db()
    admin.refresh_from_db()
    return org


@pytest.fixture
def as_admin(client, admin):
    client.login(username="admin1", password="pw12345678")
    return client


def _fake_repos(monkeypatch, repos):
    monkeypatch.setattr("github.client.installation_token", lambda iid: "tok")
    monkeypatch.setattr(
        "github.client.request",
        # 저장소 목록만 돌려준다. 연결 직후의 이슈 조회(목록 API)에는 빈 목록이 가야 한다.
        lambda method, path, token, **kw: (
            {"repositories": repos} if path.startswith("/installation/repositories") else []
        ),
    )


# ---------- services.installation_repos ----------


def test_no_installation_returns_empty(gh, org, admin):
    assert installation_repos(org, admin) == []


def test_github_error_returns_empty(gh, installed, org, admin, monkeypatch):
    from github.client import GitHubError

    monkeypatch.setattr("github.client.installation_token", lambda iid: "tok")

    def boom(method, path, token, **kw):
        raise GitHubError(403, "설치 권한 없음")

    monkeypatch.setattr("github.client.request", boom)
    assert installation_repos(org, admin) == []


def test_lists_repos_from_installation(gh, installed, org, admin, monkeypatch):
    _fake_repos(
        monkeypatch,
        [
            {
                "full_name": "teamSANDOL/sandol-api",
                "clone_url": "https://github.com/teamSANDOL/sandol-api.git",
                "private": True,
            },
            {
                "full_name": "teamSANDOL/web",
                "clone_url": "https://github.com/teamSANDOL/web.git",
                "private": False,
            },
        ],
    )
    repos = installation_repos(org, admin)
    assert [r["full_name"] for r in repos] == ["teamSANDOL/sandol-api", "teamSANDOL/web"]
    assert repos[0]["private"] is True
    assert repos[1]["clone_url"] == "https://github.com/teamSANDOL/web.git"


def test_lists_only_repos_the_user_can_see(gh, installed, org, admin, member, monkeypatch):
    """설치 토큰은 설치 범위 전부를 본다. GitHub 권한 없는 저장소 이름은 내보내지 않는다."""
    _fake_repos(
        monkeypatch,
        [
            {"full_name": "teamSANDOL/sandol-api", "clone_url": "", "private": True},
            {"full_name": "teamSANDOL/secret", "clone_url": "", "private": True},
        ],
    )
    assert [r["full_name"] for r in installation_repos(org, admin)] == ["teamSANDOL/sandol-api"]
    assert installation_repos(org, member) == []  # GitHub 미연결 멤버


# ---------- 화면 ----------


def test_page_ok_without_installation(client, gh, org, project, admin, as_admin):
    """설치가 없어도 화면은 200이고 입력창은 그대로 있다(datalist는 없다)."""
    r = as_admin.get(f"/projects/{project.pk}/repo")
    assert r.status_code == 200
    body = r.content.decode()
    assert 'name="url"' in body
    assert "org-repos" not in body


def test_datalist_shows_repo_names(client, gh, installed, project, as_admin, monkeypatch):
    _fake_repos(
        monkeypatch,
        [
            {
                "full_name": "teamSANDOL/sandol-api",
                "clone_url": "https://github.com/teamSANDOL/sandol-api.git",
                "private": False,
            }
        ],
    )
    body = as_admin.get(f"/projects/{project.pk}/repo").content.decode()
    assert 'list="org-repos"' in body
    assert "teamSANDOL/sandol-api" in body
    assert "https://github.com/teamSANDOL/sandol-api.git" in body


def test_datalist_marks_repo_already_connected_elsewhere(
    client, gh, installed, project, org, admin, as_admin, monkeypatch
):
    from projects.services import create_project

    other = create_project(
        org=org, name="다른 프로젝트", actor=admin, owners=[admin], status="active"
    )
    RepoConnection.objects.create(
        project=other,
        url="https://github.com/teamSANDOL/sandol-api.git",
        full_name="teamSANDOL/sandol-api",
        created_by=admin,
    )
    _fake_repos(
        monkeypatch,
        [
            {
                "full_name": "teamSANDOL/sandol-api",
                "clone_url": "https://github.com/teamSANDOL/sandol-api.git",
                "private": False,
            }
        ],
    )
    body = as_admin.get(f"/projects/{project.pk}/repo").content.decode()
    assert "이미 연결됨" in body
    assert "다른 프로젝트" in body


def test_direct_url_entry_still_works(client, gh, installed, project, admin, as_admin, monkeypatch):
    """목록이 있어도 사람이 직접 URL을 넣어 연결하는 길은 그대로 남는다."""
    admin.github.repos = ["teamSANDOL/sandol-api"]
    admin.github.save(update_fields=["repos"])
    _fake_repos(
        monkeypatch,
        [
            {
                "full_name": "teamSANDOL/other",
                "clone_url": "https://github.com/teamSANDOL/other.git",
                "private": False,
            }
        ],
    )
    r = as_admin.post(
        f"/projects/{project.pk}/repo",
        {"url": "https://github.com/teamSANDOL/sandol-api.git"},
    )
    assert r.status_code == 302
    conn = RepoConnection.objects.get(project=project)
    assert conn.full_name == "teamSANDOL/sandol-api"


# ---------- 프로젝트 이슈 뷰어 ----------


@pytest.fixture
def conn(project, admin):
    # 이슈 화면은 그 저장소를 GitHub에서 볼 수 있는 사람에게만 열린다.
    GitHubIdentity.objects.create(
        user=admin, github_id=777, login="admin-gh", repos=["teamSANDOL/sandol-api"]
    )
    return RepoConnection.objects.create(
        project=project,
        url="https://github.com/teamSANDOL/sandol-api.git",
        full_name="teamSANDOL/sandol-api",
        created_by=admin,
    )


@pytest.fixture
def issue(conn):
    return RepoIssue.objects.create(connection=conn, number=7, title="학식 API가 500을 낸다")


def test_project_issues_shows_only_this_project(client, gh, conn, issue, as_admin, project):
    """다른 프로젝트(다른 저장소)의 이슈는 섞여 보이지 않는다."""
    from projects.services import create_project

    other_project = create_project(
        org=project.org,
        name="다른 프로젝트",
        actor=project.created_by,
        owners=[project.created_by],
        status="active",
    )
    other_conn = RepoConnection.objects.create(
        project=other_project,
        url="https://github.com/teamSANDOL/other.git",
        full_name="teamSANDOL/other",
        created_by=project.created_by,
    )
    RepoIssue.objects.create(connection=other_conn, number=9, title="다른 저장소 이슈")

    body = as_admin.get(f"/projects/{project.pk}/issues").content.decode()
    assert "#7" in body and issue.title in body
    assert "#9" not in body and "다른 저장소 이슈" not in body


def test_project_issues_without_repo_is_404(client, gh, project, as_admin):
    assert as_admin.get(f"/projects/{project.pk}/issues").status_code == 404


def test_project_issue_import(client, gh, conn, issue, as_admin, admin):
    r = as_admin.post(
        f"/projects/{conn.project.pk}/issues/{issue.pk}/import", {"back": "state=todo"}
    )
    assert r.status_code == 302
    issue.refresh_from_db()
    assert issue.task is not None
    assert issue.task.assignee == admin


def test_connect_survives_unexpected_sync_error(
    client, gh, installed, project, admin, as_admin, monkeypatch
):
    """연결 직후 이슈 동기화가 뜻밖의 예외를 내도 연결은 저장되고 500이 나지 않는다."""
    admin.github.repos = ["teamSANDOL/sandol-api"]
    admin.github.save(update_fields=["repos"])

    def boom(iid):
        raise RuntimeError("예상 밖")

    monkeypatch.setattr("github.client.installation_token", boom)
    r = as_admin.post(
        f"/projects/{project.pk}/repo", {"url": "https://github.com/teamSANDOL/sandol-api.git"}
    )
    assert r.status_code == 302
    assert RepoConnection.objects.filter(project=project).exists()
