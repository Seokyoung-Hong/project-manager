"""GitHub 쓰기의 경계 테스트.

고정하는 것은 셋이다. 쓰기가 전부 사용자 토큰으로 나가는가, GitHub가 거부해도 PM 변경이
살아 있는가, 하지 않기로 한 것(저장소 권한 부여·GitHub 팀 삭제)이 들어오지 않았는가.
"""

import subprocess
from datetime import timedelta
from pathlib import Path

import pytest
from django.utils import timezone

from common.errors import ServiceError
from github import services, writes
from github.client import GitHubError
from github.crypto import encrypt
from github.models import (
    GitHubIdentity,
    GitHubInstallation,
    GitHubTeamLink,
    RepoConnection,
    TaskGitLink,
)

pytestmark = pytest.mark.django_db


@pytest.fixture
def calls(monkeypatch):
    """client.request가 받은 (method, path, token, body)를 모은다."""
    seen = []

    def fake(method, path, token, *, body=None, **kw):
        seen.append({"method": method, "path": path, "token": token, "body": body})
        if path.endswith("/issues") and method == "POST":
            return {"number": 7, "title": "t"}
        if method == "GET" and path.startswith("/repos/") and path.count("/") == 3:
            return {"default_branch": "main"}
        if "git/ref/heads" in path:
            return {"object": {"sha": "abc123"}}
        if method == "POST" and path.endswith("/teams"):
            return {"id": 55, "slug": "backend", "name": "backend"}
        return {}

    monkeypatch.setattr("github.client.request", fake)

    # 설치 토큰을 부르면 즉시 터지게 해 둔다. 쓰기 경로가 이것을 쓰면 안 된다.
    def boom(iid):
        raise AssertionError("쓰기에 설치 토큰을 썼다")

    monkeypatch.setattr("github.client.installation_token", boom)
    return seen


def _identity(user, login, token="ghu_user"):
    identity = GitHubIdentity.objects.create(
        user=user,
        github_id=abs(hash(login)) % 10**8,
        login=login,
        token_enc=encrypt(token),
        token_expires_at=timezone.now() + timedelta(hours=1),
    )
    user.refresh_from_db()
    return identity


@pytest.fixture
def installed(gh, org, admin):
    GitHubInstallation.objects.create(
        org=org, installation_id=99, account_login="acme", installed_by=admin
    )
    _identity(admin, "admin-gh")
    org.refresh_from_db()
    return org


# ---------- 사용자 토큰 ----------


def test_writes_use_actor_token(installed, admin, calls):
    """모든 쓰기가 설치 토큰이 아니라 그 사람 토큰을 쓴다."""
    writes.invite_to_org(installed, "someone", actor=admin)
    writes.remove_from_org(installed, "someone", actor=admin)
    assert calls, "호출이 없다"
    assert {c["token"] for c in calls} == {"ghu_user"}
    assert [c["method"] for c in calls] == ["PUT", "DELETE"]


def test_write_without_identity_raises(installed, member, calls):
    """GitHub 미연결 사용자가 부르면 ServiceError. GitHub를 부르지 않는다."""
    with pytest.raises(ServiceError):
        writes.invite_to_org(installed, "x", actor=member)
    assert calls == []


def test_write_without_installation_raises(gh, org, admin, calls):
    _identity(admin, "admin-gh")
    with pytest.raises(ServiceError):
        writes.invite_to_org(org, "x", actor=admin)
    assert calls == []


# ---------- 실패해도 PM은 남는다 ----------


def test_try_write_reports_github_error(installed, admin, monkeypatch):
    def deny(*a, **kw):
        raise GitHubError(403, "You must be a team maintainer")

    warning = writes.try_write(deny)
    assert "403" in warning and "PM에만 적용됐습니다" in warning


def test_write_failure_keeps_pm_change(installed, admin, team, monkeypatch):
    """GitHub가 403이어도 PM 팀 멤버십은 남고 경고만 생긴다."""
    from orgs.models import TeamMembership

    link = GitHubTeamLink.objects.create(team=team, github_team_id=1, slug="backend")

    def deny(method, path, token, *, body=None, **kw):
        raise GitHubError(403, "nope")

    monkeypatch.setattr("github.client.request", deny)
    before = TeamMembership.objects.filter(team=team).count()
    warning = writes.try_write(
        writes.set_gh_team_member, link, team.org, "admin-gh", actor=admin, add=True
    )
    assert warning
    assert TeamMembership.objects.filter(team=team).count() == before


def test_reconcile_adds_all_linked_members(installed, admin, member, team, calls):
    """[GitHub에 반영]이 연결된 사람만 넣고, 미연결은 경고로 남긴다."""
    from orgs.services import add_team_member

    add_team_member(team, admin, admin)
    add_team_member(team, member, admin)  # member는 GitHub 미연결
    GitHubTeamLink.objects.create(team=team, github_team_id=2, slug="backend")
    team.refresh_from_db()
    done, warns = writes.reconcile_team(team, actor=admin)
    assert done == 1
    assert any("GitHub 미연결" in w for w in warns)
    assert all(c["token"] == "ghu_user" for c in calls)


# ---------- 이슈와 브랜치 ----------


def test_create_issue_sets_link(installed, admin, task, calls):
    RepoConnection.objects.create(project=task.project, url="u", full_name="o/r", created_by=admin)
    task.project.refresh_from_db()
    writes.create_issue(task, actor=admin)
    link = TaskGitLink.objects.get(task=task)
    assert link.issue_number == 7
    assert link.issue_state == "open"
    post = [c for c in calls if c["method"] == "POST"][0]
    assert post["path"] == "/repos/o/r/issues"
    assert post["token"] == "ghu_user"
    assert task.number in post["body"]["title"]


def test_create_branch_uses_default_branch_sha(installed, admin, task, calls):
    RepoConnection.objects.create(project=task.project, url="u", full_name="o/r", created_by=admin)
    task.project.refresh_from_db()
    writes.create_branch(task, "feat/x", actor=admin)
    post = [c for c in calls if c["method"] == "POST"][0]
    assert post["body"] == {"ref": "refs/heads/feat/x", "sha": "abc123"}
    assert TaskGitLink.objects.get(task=task).branch == "feat/x"


def test_default_branch_name_round_trips(installed, admin, task, calls):
    """기본 이름은 create_branch를 통과하고, 그 이름만으로 다시 태스크를 찾을 수 있어야 한다."""
    conn = RepoConnection.objects.create(
        project=task.project, url="u", full_name="o/r", created_by=admin
    )
    task.project.refresh_from_db()
    task.title = "만료 토큰으로 로그인하면 재로그인 안내"
    task.save(update_fields=["title"])
    name = writes.default_branch_name(task)
    assert name.endswith(f"({task.number})")
    writes.create_branch(task, name, actor=admin)
    assert services._find_task(conn, name)[0] == task

    task.title = "!!!"
    assert writes.default_branch_name(task) == f"feat/{task.number}"


@pytest.mark.parametrize("name", ["", "  ", "a b", "../evil", "trailing/", "/"])
def test_create_branch_rejects_bad_name(installed, admin, task, calls, name):
    RepoConnection.objects.create(project=task.project, url="u", full_name="o/r", created_by=admin)
    task.project.refresh_from_db()
    with pytest.raises(ServiceError):
        writes.create_branch(task, name, actor=admin)
    assert not [c for c in calls if c["method"] == "POST"]


# ---------- 하지 않기로 한 것 ----------


def _grep(pattern: str) -> list[str]:
    root = Path(__file__).resolve().parent.parent
    out = subprocess.run(
        ["git", "grep", "-nE", pattern, "--", "github/", "web/"],
        cwd=root,
        capture_output=True,
        text=True,
        encoding="utf-8",
        errors="replace",  # Windows 기본 코덱(cp949)이 한글 줄에서 터진다
    ).stdout.splitlines()
    return [line for line in out if "test_" not in line.split(":")[0]]


def test_no_repo_permission_writes():
    """팀에 저장소 권한을 주는 API를 부르는 코드가 없다.

    그 API는 저장소 Administration 쓰기를 요구하고, 그 권한에는 저장소 삭제까지 딸려 온다.
    """
    hits = _grep(r"teams/[^\"']*/repos")
    assert hits == [], hits


def test_no_github_team_delete():
    """GitHub 팀을 지우는 코드가 없다. PM 팀을 지워도 GitHub 팀은 남긴다."""
    hits = _grep(r"\"DELETE\"[^)]*teams/")
    assert hits == [], hits


def test_no_installation_token_in_writes():
    """쓰기 모듈이 설치 토큰을 쓰지 않는다. 설치 토큰은 읽기 전용이다.

    주석과 문서 문자열은 빼고 실제 코드만 본다(AST로 걷는다).
    """
    import ast

    src = (Path(__file__).resolve().parent / "writes.py").read_text(encoding="utf-8")
    tree = ast.parse(src)
    used = {n.attr for n in ast.walk(tree) if isinstance(n, ast.Attribute)}
    used |= {n.id for n in ast.walk(tree) if isinstance(n, ast.Name)}
    assert "installation_token" not in used
