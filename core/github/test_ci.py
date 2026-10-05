"""IMPL-PLAN-8 G2: CI 집계·sha/브랜치 매칭·실패 알림."""

import pytest

from github.conftest import signed
from github.models import GitEvent, RepoConnection, TaskGitLink
from tasks.models import Notice
from tasks.services import transition

pytestmark = pytest.mark.django_db

SHA = "a" * 40
TS = "2026-10-05T00:00:00Z"


@pytest.fixture
def link(gh, project, admin, task, member):
    conn = RepoConnection.objects.create(
        project=project, url="https://github.com/o/r.git", full_name="o/r", created_by=admin
    )
    task.assignee = member
    task.save()
    return TaskGitLink.objects.create(
        task=task, connection=conn, branch="feat/x", pr_number=12, head_sha=SHA
    )


def suite(client, action, sid=1, sha=SHA, conclusion=None, branch="feat/x", d="d"):
    p = {
        "repository": {"full_name": "o/r"},
        "action": action,
        "sender": {"login": "dev"},
        "check_suite": {
            "id": sid,
            "head_sha": sha,
            "head_branch": branch,
            "conclusion": conclusion,
            "updated_at": TS,
        },
    }
    return signed(client, p, "check_suite", d)


def status(client, state, ctx="ci", sha=SHA, branches=(), d="s"):
    p = {
        "repository": {"full_name": "o/r"},
        "sender": {"login": "dev"},
        "sha": sha,
        "state": state,
        "context": ctx,
        "target_url": "https://ci/1",
        "branches": [{"name": b} for b in branches],
        "updated_at": TS,
    }
    return signed(client, p, "status", d)


def test_suite_flow_and_failure_alert_once(client, link):
    suite(client, "requested", d="1")
    link.refresh_from_db()
    assert link.ci_state == "pending" and link.ci_url.endswith(f"/commit/{SHA}/checks")
    suite(client, "completed", conclusion="success", d="2")
    link.refresh_from_db()
    assert link.ci_state == "success" and not Notice.objects.exists()
    suite(client, "completed", sid=2, conclusion="timed_out", d="3")
    link.refresh_from_db()
    assert link.ci_state == "failure"
    assert Notice.objects.filter(user=link.task.assignee).count() == 1
    suite(client, "completed", sid=3, conclusion="failure", d="4")  # 이미 failure → 재알림 없음
    assert Notice.objects.count() == 1
    assert GitEvent.objects.filter(kind="check").count() == 4


def test_status_aggregates_and_matches_by_branch(client, link):
    link.head_sha, link.pr_number = "", None
    link.save()
    status(client, "success", ctx="a", branches=["feat/x"], d="1")
    link.refresh_from_db()
    assert link.ci_state == "success" and link.head_sha == SHA
    status(client, "error", ctx="b", branches=["feat/x"], d="2")
    link.refresh_from_db()
    assert link.ci_state == "failure" and link.ci_url == "https://ci/1"
    status(client, "success", ctx="b", branches=["feat/x"], d="3")
    link.refresh_from_db()
    assert link.ci_state == "success"


def test_rerun_failure_realerts_and_new_sha_after_synchronize(client, link):
    suite(client, "completed", conclusion="failure", d="1")
    suite(client, "rerequested", d="2")
    suite(client, "completed", conclusion="failure", d="3")
    assert Notice.objects.count() == 2  # failure→pending→failure
    link.refresh_from_db()
    link.head_sha, link.ci_checks, link.ci_state = "b" * 40, {}, ""  # synchronize
    link.save()
    suite(client, "completed", sid=9, sha="b" * 40, conclusion="failure", d="4")
    assert Notice.objects.count() == 3


def test_stale_sha_with_pr_is_ignored(client, link):
    suite(client, "completed", sha="c" * 40, conclusion="failure", d="1")
    link.refresh_from_db()
    assert link.ci_state == "" and not Notice.objects.exists()
    assert GitEvent.objects.get().result == "무시"


def test_closed_task_gets_badge_without_alert(client, link, member):
    transition(link.task, "done", actor=member, source="web", expected_version=link.task.version)
    suite(client, "completed", conclusion="failure")
    link.refresh_from_db()
    assert link.ci_state == "failure" and not Notice.objects.exists()


def test_channel_alert_when_enabled(client, link, org, project):
    org.settings = {"notify.github_channel_events": ["ci_failed"]}
    org.save()
    project.discord_channel_id = "c-1"
    project.save()
    status(client, "failure")
    assert Notice.objects.filter(channel_id="c-1").count() == 1


def test_no_ci_events_leaves_state_empty(client, link):
    pr = {"number": 12, "updated_at": TS}
    p = {"repository": {"full_name": "o/r"}, "action": "opened", "sender": {"login": "d"}}
    signed(client, {**p, "pull_request": pr}, "pull_request", "p1")
    link.refresh_from_db()
    assert link.ci_state == "" and link.ci_checks == {} and not Notice.objects.exists()
