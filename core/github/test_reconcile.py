"""R4: 화면 대신 5분 보정(github_reconcile)과 웹훅이 GitHub를 맞춘다."""

import io

import pytest
from django.core.management import call_command
from django.utils import timezone

from github import client as gh_client
from github import services as ghs
from github.conftest import signed
from github.models import GitHubIdentity, GitHubInstallation, RepoConnection
from ops.management.commands import run_periodic
from orgs.services import create_org
from projects.services import create_project

OLD_ISSUES = lambda: timezone.now() - ghs.ISSUE_TTL * 2  # noqa: E731
OLD_REPOS = lambda: timezone.now() - ghs.REPO_TTL * 2  # noqa: E731


@pytest.fixture
def inst(gh, org, admin):
    return GitHubInstallation.objects.create(
        org=org, installation_id=700, account_login="o", installed_by=admin
    )


def _conn(project, admin, name, synced_at):
    return RepoConnection.objects.create(
        project=project,
        url=f"https://github.com/{name}",
        full_name=name,
        created_by=admin,
        issues_synced_at=synced_at,
    )


def test_reconcile_issues_stale_only_and_survives_failure(inst, org, admin, monkeypatch):
    p1 = create_project(org=org, name="일", actor=admin)
    p2 = create_project(org=org, name="이", actor=admin)
    p3 = create_project(org=org, name="삼", actor=admin)
    bad = _conn(p1, admin, "o/bad", None)
    _conn(p2, admin, "o/stale", OLD_ISSUES())
    _conn(p3, admin, "o/fresh", timezone.now())
    # 설치 없는 조직의 연결은 대상이 아니다
    other = create_org("남", "", admin)
    _conn(create_project(org=other, name="남", actor=admin), admin, "x/none", None)
    calls = []

    def fake(conn):
        calls.append(conn.full_name)
        if conn.pk == bad.pk:
            raise gh_client.GitHubError(502, "장애")

    monkeypatch.setattr(ghs, "sync_issues", fake)
    done = ghs.reconcile()
    assert sorted(calls) == ["o/bad", "o/stale"]
    assert done == {"issues": 1, "repos": 0, "failed": 1}


def test_reconcile_repos_stale_identities(inst, admin, member, monkeypatch):
    GitHubIdentity.objects.create(user=admin, github_id=1, login="a", repos_checked_at=OLD_REPOS())
    GitHubIdentity.objects.create(
        user=member, github_id=2, login="m", repos_checked_at=timezone.now()
    )
    seen = []
    monkeypatch.setattr(ghs, "sync_repos", lambda i: seen.append(i.login))
    out = io.StringIO()
    call_command("github_reconcile", stdout=out)
    assert seen == ["a"]
    assert "권한 1" in out.getvalue()


def test_reconcile_off_without_github(settings, admin, monkeypatch):
    settings.GITHUB_ENABLED = False
    GitHubIdentity.objects.create(user=admin, github_id=1, login="a")
    monkeypatch.setattr(ghs, "sync_repos", lambda i: pytest.fail("부르면 안 된다"))
    assert ghs.reconcile() == {"issues": 0, "repos": 0, "failed": 0}


def test_membership_webhook_resyncs_member_now(inst, client, member, monkeypatch):
    GitHubIdentity.objects.create(
        user=member, github_id=42, login="m", repos_checked_at=timezone.now()
    )
    seen = []
    monkeypatch.setattr(ghs, "sync_repos", lambda i: seen.append(i.github_id))
    payload = {
        "action": "added",
        "team": {"id": 9},
        "member": {"id": 42},
        "installation": {"id": 700},
    }
    signed(client, payload, "membership", "mem-1")
    assert seen == [42]


def test_membership_webhook_failure_leaves_it_to_reconcile(inst, client, member, monkeypatch):
    ident = GitHubIdentity.objects.create(
        user=member, github_id=42, login="m", repos_checked_at=timezone.now()
    )

    def fail(i):
        raise gh_client.GitHubError(502, "장애")

    monkeypatch.setattr(ghs, "sync_repos", fail)
    signed(client, {"action": "removed", "team": {"id": 9}, "member": {"id": 42}}, "membership")
    ident.refresh_from_db()
    assert ident.repos_checked_at is None


@pytest.mark.parametrize(
    "event,payload",
    [
        ("team", {"action": "added_to_repository", "team": {"id": 9}}),
        ("installation", {"action": "suspend"}),
        ("installation_repositories", {"action": "added"}),
    ],
)
def test_org_wide_webhooks_mark_only_that_orgs_members(
    inst, client, admin, member, outsider, event, payload
):
    now = timezone.now()
    inside = GitHubIdentity.objects.create(
        user=member, github_id=2, login="m", repos_checked_at=now
    )
    elsewhere = GitHubIdentity.objects.create(
        user=outsider, github_id=3, login="x", repos_checked_at=now
    )
    signed(client, {**payload, "installation": {"id": 700}}, event, f"d-{event}")
    inside.refresh_from_db()
    elsewhere.refresh_from_db()
    assert inside.repos_checked_at is None  # 다음 보정(5분 안)에 다시 묻는다
    assert elsewhere.repos_checked_at == now


def test_run_periodic_keeps_going_and_respects_interval(db, monkeypatch):
    ran = []

    def fake(name):
        ran.append(name)
        if name == "github_reconcile":
            raise RuntimeError("죽지 않는다")

    monkeypatch.setattr(run_periodic, "call_command", fake)
    err = io.StringIO()
    last = {}
    run_periodic.run_due(last, 1000.0, err)
    assert ran == ["github_reconcile", "purge_expired"]
    assert "github_reconcile 실패" in err.getvalue()
    run_periodic.run_due(last, 1000.0 + 299, err)
    assert len(ran) == 2
    run_periodic.run_due(last, 1000.0 + 300, err)
    assert ran[-1] == "github_reconcile" and len(ran) == 3


def test_reconcile_recovers_missed_close(inst, org, admin, member, monkeypatch):
    """닫기 웹훅을 놓쳤다: 보정이 이슈·연결 상태를 닫고 규칙대로 태스크를 완료한다(한 번만)."""
    from datetime import timedelta

    from common.dates import today_kst
    from github.models import RepoIssue, TaskGitLink
    from tasks.services import create_task

    p = create_project(org=org, name="일", actor=admin)
    conn = _conn(p, admin, "o/r", OLD_ISSUES())
    task = create_task(
        project=p,
        title="이슈",
        actor=member,
        source="web",
        due_date=today_kst() + timedelta(days=3),
    )
    RepoIssue.objects.create(connection=conn, number=5, title="이슈", task=task)
    TaskGitLink.objects.create(task=task, connection=conn, issue_number=5, issue_state="open")
    monkeypatch.setattr(gh_client, "installation_token", lambda _: "t")
    monkeypatch.setattr(gh_client, "paginate", lambda *_: iter([]))  # 열린 이슈 없음 = #5는 닫혔다

    assert ghs.reconcile()["issues"] == 1
    task.refresh_from_db()
    assert task.status == "done"
    assert RepoIssue.objects.get(number=5).state == "closed"
    assert TaskGitLink.objects.get(task=task).issue_state == "closed"


def test_issue_webhook_does_not_reset_reconcile_clock(inst, org, admin):
    """다른 이슈 웹훅이 계속 와도 전체 보정 시각은 그대로다 — 놓친 이슈가 보정에서 빠지지 않는다."""
    p = create_project(org=org, name="일", actor=admin)
    old = OLD_ISSUES()
    conn = _conn(p, admin, "o/r", old)
    payload = {
        "action": "edited",
        "issue": {"number": 9, "title": "무관", "state": "open", "user": {"login": "x"}},
        "repository": {"full_name": "o/r"},
        "sender": {"login": "x"},
    }
    ghs._on_issues(conn, "d-1", payload)
    conn.refresh_from_db()
    assert conn.issues_synced_at == old
