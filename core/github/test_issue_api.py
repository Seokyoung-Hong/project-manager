"""이슈 만들기·가져오기의 API 통로. 스킬(AI)이 이 길로 태스크와 이슈를 잇는다."""

from datetime import timedelta

import pytest
from django.utils import timezone

from github import services as gh_services
from github.crypto import encrypt
from github.models import GitHubIdentity, RepoConnection, RepoIssue, TaskGitLink

pytestmark = pytest.mark.django_db


@pytest.fixture
def repo(gh, project, member, monkeypatch):
    """저장소가 이어져 있고, member가 GitHub를 연결했고 그 저장소를 볼 수 있다."""
    GitHubIdentity.objects.create(
        user=member,
        github_id=1,
        login="member-gh",
        token_enc=encrypt("ghu_member"),
        token_expires_at=timezone.now() + timedelta(hours=1),
    )
    member.refresh_from_db()
    monkeypatch.setattr(gh_services, "can_view_repo", lambda actor, full_name: True)
    conn = RepoConnection.objects.create(project=project, url="u", full_name="o/r", created_by=member)
    project.refresh_from_db()
    return conn


@pytest.fixture
def github_posts(monkeypatch):
    seen = []

    def fake(method, path, token, *, body=None, **kw):
        seen.append({"method": method, "path": path, "token": token, "body": body})
        return {"number": 7, "title": body["title"]} if method == "POST" else {}

    monkeypatch.setattr("github.client.request", fake)
    return seen


def _h(token, **extra):
    return {"Authorization": f"Bearer {token}", **extra}


def test_create_issue_links_task(client, repo, task, write_token, github_posts):
    r = client.post(f"/api/tasks/{task.pk}/github/issue", headers=_h(write_token))
    assert r.status_code == 201, r.content
    assert r.json()["url"] == "https://github.com/o/r/issues/7"
    assert TaskGitLink.objects.get(task=task).issue_number == 7
    assert github_posts[0]["token"] == "ghu_member"

    again = client.post(f"/api/tasks/{task.pk}/github/issue", headers=_h(write_token))
    assert again.status_code == 400
    assert len(github_posts) == 1


def test_ai_header_counts_as_ai(client, repo, task, write_token, github_posts):
    """스킬이 보내는 X-Source: ai도 MCP와 같이 AI 정책에 걸린다."""
    task.project.org.settings = {"ai.create_task": "deny"}
    task.project.org.save(update_fields=["settings"])
    r = client.post(f"/api/tasks/{task.pk}/github/issue", headers=_h(write_token, **{"X-Source": "ai"}))
    assert r.status_code == 400
    assert "AI" in r.content.decode()
    assert github_posts == []


def test_create_issue_without_repo_says_why(client, gh, task, write_token):
    r = client.post(f"/api/tasks/{task.pk}/github/issue", headers=_h(write_token))
    assert r.status_code == 400
    assert "저장소" in r.json()["detail"]["github"]


def test_list_and_import_issue(client, repo, member, write_token):
    RepoIssue.objects.create(connection=repo, number=3, title="학식 메뉴 누락", body="본문")
    r = client.get(f"/api/projects/{repo.project_id}/issues?imported=false", headers=_h(write_token))
    assert [i["number"] for i in r.json()] == [3]

    first = client.post(f"/api/projects/{repo.project_id}/issues/3/import", headers=_h(write_token))
    assert first.status_code == 201, first.content
    again = client.post(f"/api/projects/{repo.project_id}/issues/3/import", headers=_h(write_token))
    assert again.status_code == 200
    assert again.json()["id"] == first.json()["id"]
    left = client.get(f"/api/projects/{repo.project_id}/issues?imported=false", headers=_h(write_token))
    assert left.json() == []


def test_openapi_readable_with_token(client, read_token):
    assert client.get("/api/openapi.json").status_code == 302
    r = client.get("/api/openapi.json", headers=_h(read_token))
    assert r.status_code == 200
    assert "/api/tasks/{task_id}/github/issue" in r.json()["paths"]
