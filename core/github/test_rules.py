"""GitHub 웹훅 규칙·화면 테스트. 보안 경계는 tests.py에 있다(여기서는 건드리지 않는다).

실제 GitHub는 부르지 않는다. `client.request`·`installation_token`은 monkeypatch한다.
"""

import re
from pathlib import Path

import pytest
from django.utils import timezone

from github import client as gh_client
from github import services as ghs
from github.conftest import signed
from github.models import (
    GitEvent,
    GitHubIdentity,
    GitHubInstallation,
    RepoConnection,
    RepoIssue,
    TaskGitLink,
)
from projects.services import create_project
from tasks.models import ChangeLog
from tasks.services import checklist_add, create_task

pytestmark = pytest.mark.django_db


@pytest.fixture
def conn(gh, project, admin):
    return RepoConnection.objects.create(
        project=project, url="https://github.com/o/r.git", full_name="o/r", created_by=admin
    )


def _status_log(task):
    return (
        ChangeLog.objects.filter(target_type="task", target_id=task.pk, field="status")
        .order_by("-id")
        .first()
    )


# ---------- 중복·다중 프로젝트 ----------


def test_event_dedupe_by_delivery(gh, client, conn):
    payload = {"repository": {"full_name": "o/r"}, "ref": "refs/heads/other", "commits": []}
    signed(client, payload, "push", "dup-1")
    signed(client, payload, "push", "dup-1")
    assert GitEvent.objects.filter(delivery_id__startswith="dup-1:").count() == 1


def test_same_repo_two_projects(gh, client, conn, org, admin):
    project2 = create_project(org=org, name="P2", actor=admin, owners=[admin], status="active")
    conn2 = RepoConnection.objects.create(
        project=project2, url="https://github.com/o/r.git", full_name="o/r", created_by=admin
    )
    payload = {"repository": {"full_name": "o/r"}, "ref": "refs/heads/x", "commits": []}
    signed(client, payload, "push", "two-proj")
    assert GitEvent.objects.filter(connection=conn).count() == 1
    assert GitEvent.objects.filter(connection=conn2).count() == 1


# ---------- 브랜치 규칙 ----------


def test_branch_rule_sets_doing(gh, client, conn, task):
    # GitHub의 create 이벤트는 ref에 접두어 없는 브랜치 이름을 준다("refs/heads/"는 push 전용).
    branch = f"feat/TASK-{task.pk}-x"
    payload = {
        "repository": {"full_name": "o/r"},
        "ref": branch,
        "ref_type": "branch",
        "sender": {"id": 1, "login": "dev"},
    }
    r = signed(client, payload, "create", "branch-1")
    assert r.status_code == 200
    task.refresh_from_db()
    assert task.status == "doing"
    assert task.git.branch == branch


def test_branch_rule_without_due_records_reason(gh, client, conn, project, admin):
    task = create_task(
        project=project, title="기한 없음", actor=admin, source="web", no_due_reason="아직 없음"
    )
    branch = f"TASK-{task.pk}"
    payload = {
        "repository": {"full_name": "o/r"},
        "ref": branch,
        "ref_type": "branch",
        "sender": {"id": 2, "login": "dev"},
    }
    signed(client, payload, "create", "branch-2")
    task.refresh_from_db()
    assert task.status == "todo"
    assert task.git.branch == branch
    event = GitEvent.objects.get(delivery_id=f"branch-2:{conn.pk}")
    assert "기한" in event.result


# ---------- 커밋 규칙 ----------


def test_commit_rule_checks_item(gh, client, conn, task, admin):
    checklist_add(task, "항목1", actor=admin)
    checklist_add(task, "항목2", actor=admin)
    payload = {
        "repository": {"full_name": "o/r"},
        "ref": "refs/heads/feat/x",
        "commits": [
            {
                "id": "abc123",
                "message": f"TASK-{task.pk}:2 fix",
                "timestamp": "2026-09-01T00:00:00Z",
            }
        ],
        "sender": {"id": 5, "login": "dev"},
    }
    signed(client, payload, "push", "commit-1")
    items = list(task.checklist.all())
    assert items[0].is_done is False
    assert items[1].is_done is True
    assert task.git.commits[0]["sha"] == "abc123"


def test_commit_rule_unmatched_records_not_linked(gh, client, conn):
    payload = {
        "repository": {"full_name": "o/r"},
        "ref": "refs/heads/misc",
        "commits": [
            {"id": "zzz", "message": "no task number here", "timestamp": "2026-09-01T00:00:00Z"}
        ],
    }
    signed(client, payload, "push", "commit-2")
    event = GitEvent.objects.get(delivery_id=f"commit-2:{conn.pk}")
    assert event.result == "연결 안 됨"


def test_commits_capped_at_100(gh, client, conn, task):
    link = TaskGitLink.objects.create(
        task=task,
        connection=conn,
        commits=[{"sha": f"s{i}", "message": "m", "item": None, "at": ""} for i in range(100)],
    )
    payload = {
        "repository": {"full_name": "o/r"},
        "ref": "refs/heads/x",
        "commits": [
            {
                "id": "new-sha",
                "message": f"TASK-{task.pk} more",
                "timestamp": "2026-09-01T00:00:00Z",
            }
        ],
    }
    signed(client, payload, "push", "cap-1")
    link.refresh_from_db()
    assert len(link.commits) == 100
    assert link.commits[0]["sha"] == "s1"
    assert link.commits[-1]["sha"] == "new-sha"


# ---------- PR 규칙 ----------


def test_pr_open_sets_review(gh, client, conn, task):
    payload = {
        "action": "opened",
        "repository": {"full_name": "o/r"},
        "pull_request": {
            "number": 10,
            "title": f"TASK-{task.pk} fix",
            "body": "",
            "head": {"ref": "feat/x"},
            "updated_at": "2026-09-01T00:00:00Z",
            "merged": False,
        },
        "sender": {"id": 1, "login": "dev"},
    }
    signed(client, payload, "pull_request", "pr-1")
    task.refresh_from_db()
    assert task.status == "review"
    assert task.git.pr_number == 10


def test_pr_merge_sets_done(gh, client, conn, task):
    payload = {
        "action": "closed",
        "repository": {"full_name": "o/r"},
        "pull_request": {
            "number": 11,
            "title": f"TASK-{task.pk} fix",
            "body": "",
            "head": {"ref": "feat/x"},
            "updated_at": "2026-09-01T00:00:00Z",
            "merged": True,
            "merged_at": "2026-09-01T01:00:00Z",
        },
        "sender": {"id": 1, "login": "dev"},
    }
    signed(client, payload, "pull_request", "pr-2")
    task.refresh_from_db()
    assert task.status == "done"
    assert task.git.pr_state == "merged"


def test_rules_off_do_nothing(gh, client, conn, task):
    conn.rule_branch = False
    conn.save(update_fields=["rule_branch"])
    payload = {
        "repository": {"full_name": "o/r"},
        "ref": f"refs/heads/TASK-{task.pk}",
        "ref_type": "branch",
    }
    signed(client, payload, "create", "rule-off-1")
    task.refresh_from_db()
    assert task.status == "todo"
    event = GitEvent.objects.get(delivery_id=f"rule-off-1:{conn.pk}")
    assert event.result == "규칙 꺼짐"


# ---------- 이슈 가져오기 ----------


def test_unassigned_issue_is_not_imported(gh, client, conn, admin):
    """배정 없는 이슈는 auto_import가 켜져 있어도 태스크가 되지 않는다.

    이슈는 저장소를 볼 수 있는 누구나 열 수 있다. 배정을 문턱으로 두지 않으면 공개 저장소에서
    이슈만 열어도 PM에 태스크가 쌓인다.
    """
    conn.auto_import = True
    conn.import_label = ""
    conn.save(update_fields=["auto_import", "import_label"])
    payload = {
        "action": "opened",
        "repository": {"full_name": "o/r"},
        "issue": {"number": 42, "title": "새 이슈", "body": "설명", "labels": [], "assignee": None},
        "sender": {"id": 1, "login": "dev"},
    }
    r = signed(client, payload, "issues", "issue-1")
    assert r.status_code == 200
    issue = RepoIssue.objects.get(connection=conn, number=42)
    assert issue.task is None  # 기록만 남는다
    assert (
        GitEvent.objects.get(delivery_id__startswith="issue-1").result
        == "담당자 미배정 · 가져오지 않음"
    )


def test_issue_closed_closes_task(gh, client, conn, task):
    issue = RepoIssue.objects.create(connection=conn, number=7, title="t", state="open")
    issue.task = task
    issue.save(update_fields=["task"])
    payload = {
        "action": "closed",
        "repository": {"full_name": "o/r"},
        "issue": {"number": 7, "title": "t", "labels": [], "assignee": None},
        "sender": {"id": 1, "login": "dev"},
    }
    signed(client, payload, "issues", "issue-2")
    task.refresh_from_db()
    assert task.status == "done"


def test_import_actor_fallback(gh, client, conn, admin, member, project):
    """배정된 멤버가 있으면 행위자는 sender → 프로젝트 첫 관리자 → 그 멤버 순으로 정해진다."""
    conn.auto_import = True
    conn.import_label = ""
    conn.save(update_fields=["auto_import", "import_label"])
    GitHubIdentity.objects.create(user=member, github_id=42, login="member-gh")
    payload = {
        "action": "opened",
        "repository": {"full_name": "o/r"},
        "issue": {
            "number": 55,
            "title": "폴백",
            "body": "",
            "labels": [],
            "assignee": {"login": "member-gh"},
        },
        "sender": {"id": 1234, "login": "outsider-dev"},
    }
    signed(client, payload, "issues", "fallback-1")
    issue = RepoIssue.objects.get(connection=conn, number=55)
    assert issue.task is not None
    assert issue.task.created_by_id == admin.pk  # sender 매핑 안 됨 → 프로젝트 첫 관리자
    assert issue.task.assignee_id == member.pk

    project.owners.clear()
    payload["issue"]["number"] = 56
    signed(client, payload, "issues", "fallback-2")
    issue2 = RepoIssue.objects.get(connection=conn, number=56)
    assert issue2.task is not None  # 관리자가 없어도 배정된 멤버가 행위자가 되어 막히지 않는다
    assert issue2.task.created_by_id == member.pk


def test_import_assignee_from_issue(gh, client, conn, admin, member):
    conn.auto_import = True
    conn.import_label = ""
    conn.save(update_fields=["auto_import", "import_label"])
    GitHubIdentity.objects.create(user=member, github_id=42, login="member-gh")
    payload = {
        "action": "opened",
        "repository": {"full_name": "o/r"},
        "issue": {
            "number": 70,
            "title": "담당자",
            "body": "",
            "labels": [],
            "assignee": {"login": "member-gh"},
        },
        "sender": {"id": 1, "login": "dev"},
    }
    signed(client, payload, "issues", "assignee-1")
    issue = RepoIssue.objects.get(connection=conn, number=70)
    assert issue.task.assignee_id == member.pk


def test_sync_issues_skips_prs(gh, conn, admin, org, monkeypatch):
    GitHubInstallation.objects.create(
        org=org, installation_id=555, account_login="o", installed_by=admin
    )
    monkeypatch.setattr(gh_client, "installation_token", lambda iid: "tok")
    monkeypatch.setattr(
        gh_client,
        "request",
        lambda method, path, token, **kw: [
            {"number": 1, "title": "이슈", "labels": [], "assignee": None},
            {"number": 2, "title": "PR", "pull_request": {}, "labels": [], "assignee": None},
        ],
    )
    n = ghs.sync_issues(conn)
    assert n == 1
    assert RepoIssue.objects.filter(connection=conn, number=1).exists()
    assert not RepoIssue.objects.filter(connection=conn, number=2).exists()


# ---------- 행위자 매핑 ----------


def test_actor_mapping_from_sender(gh, client, conn, task, member):
    GitHubIdentity.objects.create(user=member, github_id=555, login="minu")
    payload = {
        "repository": {"full_name": "o/r"},
        "ref": f"refs/heads/TASK-{task.pk}",
        "ref_type": "branch",
        "sender": {"id": 555, "login": "minu"},
    }
    signed(client, payload, "create", "actor-1")
    log = _status_log(task)
    assert log.actor_id == member.pk


def test_external_actor_when_unmapped(gh, client, conn, task):
    payload = {
        "repository": {"full_name": "o/r"},
        "ref": f"refs/heads/TASK-{task.pk}",
        "ref_type": "branch",
        "sender": {"id": 999, "login": "ghost"},
    }
    signed(client, payload, "create", "actor-2")
    log = _status_log(task)
    assert log.actor is None
    assert log.external_actor == "ghost"


def test_backfill_actor_on_connect(gh, conn, member):
    ChangeLog.objects.create(
        target_type="task",
        target_id=0,
        field="status",
        old_value="review",
        new_value="done",
        actor=None,
        source="gh",
        external_actor="minu-choi",
    )
    event = GitEvent.objects.create(
        connection=conn,
        delivery_id="bf-1:1",
        occurred_at=timezone.now(),
        kind="push",
        actor_login="minu-choi",
        summary="x",
    )
    identity = GitHubIdentity.objects.create(user=member, github_id=777, login="minu-choi")
    ghs.backfill_actor(identity)
    log = ChangeLog.objects.get(source="gh", external_actor="")
    assert log.actor_id == member.pk
    event.refresh_from_db()
    assert event.actor_user_id == member.pk


def test_event_occurred_at_from_payload(gh, client, conn):
    payload = {
        "repository": {"full_name": "o/r"},
        "ref": "refs/heads/x",
        "head_commit": {"timestamp": "2026-01-02T03:04:05Z"},
        "commits": [{"id": "a1", "message": "no ref", "timestamp": "2026-01-02T03:04:05Z"}],
    }
    signed(client, payload, "push", "occurred-1")
    event = GitEvent.objects.get(delivery_id=f"occurred-1:{conn.pk}")
    assert event.occurred_at.isoformat() == "2026-01-02T03:04:05+00:00"


# ---------- 연결 해제 ----------


@pytest.fixture
def linked(gh, client, conn, task, member):
    """저장소를 볼 수 있는 팀원으로 로그인하고, 네 단계가 모두 채워진 링크를 만든다."""
    GitHubIdentity.objects.create(user=member, github_id=321, login="m", repos=["o/r"])
    client.login(username="member1", password="pw12345678")
    issue = RepoIssue.objects.create(connection=conn, number=7, title="이슈", task=task)
    link = TaskGitLink.objects.create(
        task=task,
        connection=conn,
        issue_number=7,
        issue_title="이슈",
        issue_state="open",
        branch="feature-x",
        pr_number=9,
        pr_state="open",
    )
    return link, issue


@pytest.mark.parametrize(
    ("what", "gone", "kept"),
    [
        ("issue", "issue_number", "branch"),
        ("branch", "branch", "issue_number"),
        ("pr", "pr_number", "branch"),
    ],
)
def test_unlink_one_step_keeps_the_rest(linked, client, task, what, gone, kept):
    link, _ = linked
    r = client.post(f"/tasks/{task.pk}/git/unlink", {"what": what})
    assert r.status_code == 200
    link.refresh_from_db()
    assert not getattr(link, gone)
    assert getattr(link, kept)


def test_unlink_issue_frees_it_for_reuse(linked, client, task):
    """이슈를 끊으면 RepoIssue.task도 풀린다 — 그러지 않으면 다시 연결할 수 없다."""
    _, issue = linked
    client.post(f"/tasks/{task.pk}/git/unlink", {"what": "issue"})
    issue.refresh_from_db()
    assert issue.task_id is None
    body = client.post(f"/tasks/{task.pk}/git/issue", {"number": 7}).content.decode()
    assert "#7" in body
    issue.refresh_from_db()
    assert issue.task_id == task.pk


def test_unlink_all_removes_link_and_panel_shows_it(linked, client, task):
    r = client.post(f"/tasks/{task.pk}/git/unlink", {"what": "all"})
    assert not TaskGitLink.objects.filter(task=task).exists()
    body = r.content.decode()
    assert "feature-x" not in body  # 지운 링크가 캐시로 다시 그려지지 않는다
    assert "이슈 선택" in body


# ---------- 이슈 조회 ----------


def _fake_issue_api(monkeypatch, org, admin, items):
    GitHubInstallation.objects.get_or_create(
        installation_id=555, defaults={"org": org, "account_login": "o", "installed_by": admin}
    )
    calls = []
    monkeypatch.setattr(gh_client, "installation_token", lambda iid: "tok")

    def request(method, path, token, **kw):
        calls.append(path)
        return items

    monkeypatch.setattr(gh_client, "request", request)
    return calls


def test_sync_issues_omits_empty_label_filter(gh, conn, admin, org, monkeypatch):
    """labels=를 빈 값으로 보내면 GitHub가 "라벨 없는 이슈"로 읽어 목록이 비어 버린다."""
    calls = _fake_issue_api(
        monkeypatch, org, admin, [{"number": 1, "title": "이슈", "labels": [], "assignee": None}]
    )
    conn.import_label = ""
    conn.save(update_fields=["import_label"])
    ghs.sync_issues(conn)
    assert "labels=" not in calls[0]


def test_stale_issues_synced_on_view_and_webhook_pauses_it(gh, conn, admin, org, monkeypatch):
    """서버가 알아서 맞춘다. 웹훅이 오면 그 시각으로 갱신되어 폴링하지 않는다."""
    calls = _fake_issue_api(
        monkeypatch, org, admin, [{"number": 1, "title": "이슈", "labels": [], "assignee": None}]
    )
    ghs.sync_issues_if_stale(conn)
    assert len(calls) == 1
    conn.refresh_from_db()
    ghs.sync_issues_if_stale(conn)
    assert len(calls) == 1  # TTL 안이면 다시 묻지 않는다
    conn.issues_synced_at = timezone.now() - ghs.ISSUE_TTL * 2
    conn.save(update_fields=["issues_synced_at"])
    ghs.sync_issues_if_stale(conn)
    assert len(calls) == 2


def test_webhook_marks_issues_fresh(gh, client, conn):
    payload = {
        "action": "opened",
        "repository": {"full_name": "o/r"},
        "issue": {"number": 3, "title": "웹훅", "body": "", "labels": [], "state": "open"},
        "sender": {"id": 1, "login": "dev"},
    }
    signed(client, payload, "issues", "fresh-1")
    conn.refresh_from_db()
    assert conn.issues_synced_at is not None


def test_issue_state_follows_payload_not_action(gh, client, conn):
    """labeled·edited 같은 action이 닫힌 이슈를 열린 것으로 되돌리면 안 된다."""
    RepoIssue.objects.create(connection=conn, number=4, title="닫힘", state="closed")
    payload = {
        "action": "labeled",
        "repository": {"full_name": "o/r"},
        "issue": {"number": 4, "title": "닫힘", "body": "", "labels": [], "state": "closed"},
        "sender": {"id": 1, "login": "dev"},
    }
    signed(client, payload, "issues", "state-1")
    assert RepoIssue.objects.get(connection=conn, number=4).state == "closed"


def test_viewer_lists_only_open_unclaimed_issues(gh, client, conn, task, member, project):
    GitHubIdentity.objects.create(user=member, github_id=321, login="m", repos=["o/r"])
    client.login(username="member1", password="pw12345678")
    conn.issues_synced_at = timezone.now()  # 폴링이 끼어들지 않게
    conn.save(update_fields=["issues_synced_at"])
    RepoIssue.objects.create(connection=conn, number=11, title="열린이슈", state="open")
    RepoIssue.objects.create(connection=conn, number=12, title="닫힌이슈", state="closed")
    RepoIssue.objects.create(
        connection=conn, number=13, title="가져온이슈", state="open", task=task
    )
    body = client.get(f"/tasks/{task.pk}").content.decode()
    assert "열린이슈" in body
    assert "닫힌이슈" not in body
    assert "가져온이슈" not in body
    tab = client.get(f"/projects/{project.pk}/repo").content.decode()
    assert "열린이슈" in tab
    assert "닫힌이슈" not in tab


# ---------- 권한 필터 · UI ----------


def test_can_view_repo_filters_panel(gh, client, conn, task, member):
    client.login(username="member1", password="pw12345678")
    GitHubIdentity.objects.create(user=member, github_id=321, login="m", repos=[])
    TaskGitLink.objects.create(task=task, connection=conn, branch="secret-branch")
    body = client.get(f"/tasks/{task.pk}").content.decode()
    assert "저장소 접근 권한 없음" in body
    assert "secret-branch" not in body


def test_github_disabled_hides_ui(settings, client, org, project, admin):
    settings.GITHUB_ENABLED = False
    client.login(username="admin1", password="pw12345678")
    r = client.get(f"/orgs/{org.pk}/teams")
    assert r.status_code == 200
    assert f'/orgs/{org.pk}/github"' not in r.content.decode()
    r2 = client.get(f"/projects/{project.pk}")
    assert r2.status_code == 200
    assert "저장소 연결" not in r2.content.decode()
    assert client.get(f"/orgs/{org.pk}/github").status_code == 404
    assert client.get("/settings/github").status_code == 404


def test_installation_token_read_only():
    """installation_token()으로 받은 토큰은 GET 요청에만 쓴다."""
    root = Path(__file__).resolve().parent.parent
    write_re = re.compile(r'client\.request\(\s*"(POST|PUT|PATCH|DELETE)"')
    violations = []
    for path in root.rglob("*.py"):
        posix = path.as_posix()
        if "/.venv/" in posix or "/migrations/" in posix or path.name == "test_rules.py":
            continue
        lines = path.read_text(encoding="utf-8").splitlines()
        for i, line in enumerate(lines):
            if "installation_token(" in line and "def installation_token" not in line:
                window = "\n".join(lines[i : i + 6])
                if write_re.search(window):
                    violations.append(f"{path}:{i + 1}")
    assert violations == [], violations


def test_sync_issues_reads_every_page(gh, conn, admin, org, monkeypatch):
    """100건을 넘으면 다음 페이지도 읽는다. 한 페이지만 읽으면 나머지가 닫힌 것으로 찍혔다."""
    GitHubInstallation.objects.create(
        org=org, installation_id=556, account_login="o", installed_by=admin
    )
    monkeypatch.setattr(gh_client, "installation_token", lambda iid: "tok")
    pages = {
        "1": [
            {"number": n, "title": f"이슈 {n}", "labels": [], "assignee": None}
            for n in range(1, 101)
        ],
        "2": [{"number": 101, "title": "101번째", "labels": [], "assignee": None}],
    }

    def fake(method, path, token, **kw):
        return pages.get(path.rsplit("page=", 1)[1], [])

    monkeypatch.setattr(gh_client, "request", fake)
    assert ghs.sync_issues(conn) == 101
    assert RepoIssue.objects.filter(connection=conn, number=101, state="open").exists()


def test_sync_issues_keeps_issues_without_the_import_label(gh, conn, admin, org, monkeypatch):
    """라벨 필터는 자동 가져오기 문턱일 뿐이다. 웹훅으로 담긴 이슈를 조회에서 지우면 안 된다."""
    conn.import_label = "task"
    conn.save(update_fields=["import_label"])
    GitHubInstallation.objects.create(
        org=org, installation_id=557, account_login="o", installed_by=admin
    )
    RepoIssue.objects.create(connection=conn, number=9, title="라벨 없는 이슈")
    monkeypatch.setattr(gh_client, "installation_token", lambda iid: "tok")
    asked = []

    def fake(method, path, token, **kw):
        asked.append(path)
        return [{"number": 9, "title": "라벨 없는 이슈", "labels": [], "assignee": None}]

    monkeypatch.setattr(gh_client, "request", fake)
    ghs.sync_issues(conn)
    assert not any("labels=" in p for p in asked)
    assert RepoIssue.objects.get(connection=conn, number=9).state == "open"
