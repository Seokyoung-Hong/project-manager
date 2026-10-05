"""IMPL-PLAN-8 G8: /github·/repo 응답 필드, continued_by, 앱 권한 점검 API."""

import pytest
from django.utils import timezone

from accounts.models import ApiToken
from github import services as gh_services
from github.models import GitRelease, RepoConnection, TaskGitLink
from tasks.models import ChangeLog, Task

pytestmark = pytest.mark.django_db


def _h(raw):
    return {"Authorization": f"Bearer {raw}"}


@pytest.fixture
def conn(gh, project, admin, monkeypatch):
    monkeypatch.setattr("api.routers.tasks.can_view_repo", lambda actor, full_name: True)
    monkeypatch.setattr("github.sync.repo_state", lambda u, p: {"state": "ok"})
    return RepoConnection.objects.create(
        project=project, url="https://github.com/o/r", full_name="o/r", created_by=admin
    )


def test_task_github_pr_fields_and_continued_by(client, conn, task, member, write_token):
    TaskGitLink.objects.create(
        task=task,
        connection=conn,
        pr_number=3,
        pr_state="open",
        pr_draft=True,
        head_sha="a" * 40,
        review_state="changes_requested",
        reviews={"rev": "changes_requested"},
        ci_state="failure",
        ci_url="https://ci/1",
    )
    r = client.get(f"/api/tasks/{task.pk}/github", headers=_h(write_token)).json()
    pr = r["pull_request"]
    assert pr["draft"] and pr["ci_state"] == "failure" and pr["ci_url"] == "https://ci/1"
    assert pr["review_state"] == "changes_requested" and pr["head_sha"] == "a" * 40
    assert pr["reviews"] == {"rev": "changes_requested"} and r["continued_by"] is None

    new = Task.objects.create(
        project=task.project, title="이어", created_by=member, assignee=member, parent=task
    )
    ChangeLog.objects.create(
        target_type="task",
        target_id=task.pk,
        field="reopened_as",
        new_value=new.number,
        actor=member,
        source="gh",
    )
    r = client.get(f"/api/tasks/{task.pk}/github", headers=_h(write_token)).json()
    assert r["continued_by"] == {"id": new.pk, "number": new.number, "status": new.status}


def test_repo_rules_and_releases(client, conn, project, write_token):
    GitRelease.objects.create(
        connection=conn, tag="v1", url="https://x", published_at=timezone.now()
    )
    r = client.get(f"/api/projects/{project.pk}/repo", headers=_h(write_token)).json()
    assert r["rule_review"] and r["rule_milestone"] and "rule_sync" not in r
    assert r["releases"][0]["tag"] == "v1"


def test_org_capabilities_admin_only(client, gh, org, admin, write_token, monkeypatch):
    caps = {"ci": {"ok": True, "missing": []}}
    monkeypatch.setattr(gh_services, "app_capabilities", lambda o: caps)
    url = f"/api/orgs/{org.pk}/github/capabilities"
    assert client.get(url, headers=_h(write_token)).status_code == 400
    _, raw = ApiToken.issue(admin, "a", "write", for_ai=False)
    assert client.get(url, headers=_h(raw)).json() == {"capabilities": caps}
