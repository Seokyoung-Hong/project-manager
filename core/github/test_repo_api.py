"""저장소 연결의 API 통로. MCP(AI)도 이 길로 들어온다 — 막는 규칙은 services 안에 있다."""

import pytest

from github import services as gh_services

pytestmark = pytest.mark.django_db


@pytest.fixture
def repos(monkeypatch):
    """설치 저장소 목록을 가짜로. GitHub을 부르지 않는다."""

    def fake(org):
        return [
            {
                "full_name": "teamSANDOL/sandol-api",
                "clone_url": "https://github.com/teamSANDOL/sandol-api.git",
                "private": False,
            },
        ]

    monkeypatch.setattr(gh_services, "installation_repos", fake)


@pytest.fixture
def viewable(monkeypatch):
    monkeypatch.setattr(gh_services, "can_view_repo", lambda actor, full_name: True)


def _auth(token):
    return {"Authorization": f"Bearer {token}"}


def test_org_repos_lists_choices(client, gh, org, write_token, repos):
    r = client.get(f"/api/orgs/{org.pk}/repos", headers=_auth(write_token))
    assert r.status_code == 200
    assert r.json()[0]["full_name"] == "teamSANDOL/sandol-api"


def test_connect_and_read_back(client, gh, project, member, write_token, viewable):
    project.owners.add(member)
    r = client.post(
        f"/api/projects/{project.pk}/repo",
        {"url": "https://github.com/teamSANDOL/sandol-api"},
        content_type="application/json",
        headers=_auth(write_token),
    )
    assert r.status_code == 200, r.content
    assert r.json()["full_name"] == "teamSANDOL/sandol-api"
    got = client.get(f"/api/projects/{project.pk}/repo", headers=_auth(write_token))
    assert got.json()["connected"] is True


def test_ai_gate_blocks_mcp_when_org_says_no(
    client, gh, org, project, member, write_token, viewable
):
    project.owners.add(member)
    org.settings = {"ai.manage_repo": "deny"}
    org.save(update_fields=["settings"])
    r = client.post(
        f"/api/projects/{project.pk}/repo",
        {"url": "https://github.com/teamSANDOL/sandol-api"},
        content_type="application/json",
        headers={**_auth(write_token), "X-Source": "mcp"},
    )
    assert r.status_code == 400
    assert "AI" in r.content.decode()
    assert not hasattr(project, "repo") or project.repo is None


def test_person_token_without_the_header_is_not_ai(
    client, gh, project, member, write_token, viewable
):
    """`ai.*`는 사람용 토큰(write_token)에는 걸리지 않는다. AI용 토큰은 헤더가 없어도 걸린다."""
    project.owners.add(member)
    project.org.settings = {"ai.manage_repo": "deny"}
    project.org.save(update_fields=["settings"])
    r = client.post(
        f"/api/projects/{project.pk}/repo",
        {"url": "https://github.com/teamSANDOL/sandol-api"},
        content_type="application/json",
        headers=_auth(write_token),
    )
    assert r.status_code == 200


def test_connect_warns_when_repo_is_shared(
    client, gh, org, admin, project, member, write_token, viewable
):
    from github.models import RepoConnection
    from projects.services import create_project

    p2 = create_project(org=org, name="옆 프로젝트", actor=admin, owners=[admin], status="active")
    RepoConnection.objects.create(
        project=p2, url="x", full_name="teamSANDOL/sandol-api", created_by=admin
    )
    project.owners.add(member)
    r = client.post(
        f"/api/projects/{project.pk}/repo",
        {"url": "https://github.com/teamSANDOL/sandol-api"},
        content_type="application/json",
        headers=_auth(write_token),
    )
    assert r.status_code == 200, r.content
    assert "옆 프로젝트" in r.json()["warning"]  # 막지 않고 경고만
