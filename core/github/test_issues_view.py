"""조직 이슈 뷰어: 연결된 저장소 전부의 열린 이슈를 한 화면에서 보고 내 태스크로 가져간다."""

import pytest

from github.models import GitHubIdentity, RepoConnection, RepoIssue, TaskGitLink
from github.services import import_issue, org_issues

pytestmark = pytest.mark.django_db


@pytest.fixture
def conn(project):
    return RepoConnection.objects.create(
        project=project,
        url="https://github.com/teamSANDOL/sandol-api.git",
        full_name="teamSANDOL/sandol-api",
        created_by=project.created_by,
    )


@pytest.fixture
def issue(conn):
    return RepoIssue.objects.create(
        connection=conn,
        number=7,
        title="학식 API가 500을 낸다",
        body="재현 경로: /meal 을 두 번 부르면",
        author_login="someone",
        labels=["bug"],
    )


# ---------- 조회 ----------


def test_org_issues_only_open_and_only_this_org(org, conn, issue):
    RepoIssue.objects.create(connection=conn, number=8, title="닫힌 것", state="closed")
    assert [i.number for i in org_issues(org)] == [7]


def test_filter_by_imported(org, conn, issue, member):
    assert list(org_issues(org, imported=False)) == [issue]
    assert list(org_issues(org, imported=True)) == []
    import_issue(issue, member)
    assert list(org_issues(org, imported=False)) == []
    assert list(org_issues(org, imported=True)) == [issue]


def test_search_matches_title_and_body(org, conn, issue):
    assert list(org_issues(org, query="학식")) == [issue]
    assert list(org_issues(org, query="재현")) == [issue]
    assert list(org_issues(org, query="없는말")) == []


# ---------- 가져오기 ----------


def test_import_makes_it_my_task_with_body_and_link(conn, issue, member):
    task = import_issue(issue, member)
    issue.refresh_from_db()
    assert issue.task == task
    assert task.assignee == member
    assert task.project == conn.project
    assert task.title == issue.title
    assert "재현 경로" in task.description
    assert task.no_due_reason  # GitHub 이슈에는 기한이 없다
    link = TaskGitLink.objects.get(task=task)
    assert link.issue_number == 7
    assert link.connection == conn


def test_import_twice_returns_the_same_task(issue, member, admin):
    first = import_issue(issue, member)
    again = import_issue(issue, admin)
    assert first == again
    assert again.assignee == member  # 먼저 가져간 사람 것이다


# ---------- 화면 ----------


def test_page_lists_and_imports(client, gh, org, conn, issue, member):
    GitHubIdentity.objects.create(
        user=member, github_id=321, login="m", repos=["teamSANDOL/sandol-api"]
    )
    client.force_login(member)
    body = client.get(f"/orgs/{org.pk}/issues").content.decode()
    assert "#7" in body and issue.title in body and "내 태스크로 가져오기" in body

    r = client.post(f"/orgs/{org.pk}/issues/{issue.pk}/import", {"back": "state=todo"})
    assert r.status_code == 302
    issue.refresh_from_db()
    assert issue.task is not None
    assert issue.task.assignee == member

    body = client.get(f"/orgs/{org.pk}/issues?state=done").content.decode()
    assert issue.task.number in body


def test_page_needs_membership_and_github(client, gh, org, conn, issue, outsider, member, settings):
    client.force_login(outsider)
    assert client.get(f"/orgs/{org.pk}/issues").status_code == 404
    client.force_login(member)
    settings.GITHUB_ENABLED = False
    assert client.get(f"/orgs/{org.pk}/issues").status_code == 404


def test_import_rejects_other_orgs_issue(client, gh, org, conn, issue, outsider):
    client.force_login(outsider)
    r = client.post(f"/orgs/{org.pk}/issues/{issue.pk}/import")
    assert r.status_code == 404
    issue.refresh_from_db()
    assert issue.task is None


def test_member_who_cannot_see_repo_gets_no_issues(client, gh, org, conn, issue, member):
    """조직 멤버라도 GitHub에서 그 저장소를 볼 수 없으면 이슈가 보이지 않고 가져올 수도 없다."""
    GitHubIdentity.objects.create(user=member, github_id=321, login="m", repos=["o/other"])
    client.force_login(member)
    body = client.get(f"/orgs/{org.pk}/issues").content.decode()
    assert issue.title not in body
    r = client.post(f"/orgs/{org.pk}/issues/{issue.pk}/import")
    assert r.status_code == 404
    project_id = conn.project.pk
    assert client.get(f"/projects/{project_id}/issues").status_code == 403
    issue.refresh_from_db()
    assert issue.task is None
