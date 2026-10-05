"""IMPL-PLAN-8 G1: PR 상태 확장·리뷰 상태·리뷰어 ↔ 검토자·재개 = 신규 태스크.

실제 GitHub는 부르지 않는다. 웹훅은 서명해 core 엔드포인트로 보낸다.
"""

import pytest

from accounts.models import User
from github.conftest import signed
from github.models import GitEvent, GitHubIdentity, RepoConnection, RepoIssue, TaskGitLink
from orgs.models import OrgMembership
from tasks.models import ChangeLog, Notice, Task, WorkRequest
from tasks.services import checklist_add, transition

pytestmark = pytest.mark.django_db


@pytest.fixture
def conn(gh, project, admin):
    return RepoConnection.objects.create(
        project=project, url="https://github.com/o/r.git", full_name="o/r", created_by=admin
    )


@pytest.fixture
def reviewer(org):
    u = User.objects.create_user("rev1", password="pw12345678", display_name="리뷰어")
    OrgMembership.objects.create(org=org, user=u, role="member")
    GitHubIdentity.objects.create(user=u, github_id=501, login="rev")
    return u


def _pr(task, action, *, number=12, draft=False, merged=False, sha="a" * 40, **extra):
    payload = {
        "action": action,
        "repository": {"full_name": "o/r"},
        "sender": {"id": 999, "login": "dev"},
        "pull_request": {
            "number": number,
            "title": f"TASK-{task.pk} 고침",
            "body": "",
            "draft": draft,
            "merged": merged,
            "html_url": f"https://github.com/o/r/pull/{number}",
            "head": {"ref": "feat/x", "sha": sha},
            "created_at": "2026-10-01T00:00:00Z",
        },
    }
    payload.update(extra)
    return payload


def _review(state, *, action="submitted", login="rev", number=12, rid=None, at="2026-10-02"):
    _review.n = getattr(_review, "n", 0) + 1
    return {
        "action": action,
        "repository": {"full_name": "o/r"},
        "sender": {"id": 501, "login": login},
        "pull_request": {"number": number},
        "review": {
            "id": rid or _review.n,
            "state": state,
            "user": {"login": login},
            "submitted_at": f"{at}T00:00:00Z",
        },
    }


def _send(client, payload, event="pull_request", delivery=None):
    _send.n = getattr(_send, "n", 0) + 1
    r = signed(client, payload, event, delivery or f"g1-{_send.n}")
    assert r.status_code == 200
    return GitEvent.objects.order_by("-id").first()


def _review_state(task, client):
    _send(client, _pr(task, "opened"))
    task.refresh_from_db()
    assert task.status == "review"


# ---------- PR 상태 ----------


def test_opened_draft_goes_doing_and_ready_for_review_goes_review(client, conn, task):
    _send(client, _pr(task, "opened", draft=True))
    task.refresh_from_db()
    link = task.git
    assert task.status == "doing" and link.pr_draft and link.review_requested_at is None
    assert link.pr_opened_at is not None and link.head_sha == "a" * 40

    _send(client, _pr(task, "ready_for_review"))
    task.refresh_from_db()
    link.refresh_from_db()
    assert task.status == "review" and not link.pr_draft and link.review_requested_at


def test_opened_non_draft_stamps_review_request(client, conn, task):
    _review_state(task, client)
    assert task.git.review_requested_at is not None


def test_converted_to_draft_moves_review_back_to_doing(client, conn, task):
    _review_state(task, client)
    _send(client, _pr(task, "converted_to_draft", draft=True))
    task.refresh_from_db()
    assert task.status == "doing" and task.git.pr_draft


def test_synchronize_resets_ci_and_starts_new_review_round(client, conn, task, reviewer):
    _review_state(task, client)
    _send(client, _review("changes_requested"), "pull_request_review")
    link = TaskGitLink.objects.get(task=task)
    link.ci_checks, link.ci_state = {"suite:1": "failure"}, "failure"
    link.save()
    before = link.review_requested_at

    _send(client, _pr(task, "synchronize", sha="b" * 40))
    link.refresh_from_db()
    assert link.head_sha == "b" * 40 and link.ci_checks == {} and link.ci_state == ""
    assert link.reviewed_at is None and link.review_requested_at > before
    task.refresh_from_db()
    assert task.status == "doing"  # 상태는 그대로


def test_open_task_reopened_goes_back_to_review(client, conn, task):
    _review_state(task, client)
    _send(client, _pr(task, "closed"))
    task.refresh_from_db()
    assert task.status == "review" and task.git.pr_state == "closed"
    transition(task, "doing", actor=None, source="gh", expected_version=task.version)
    ev = _send(client, _pr(task, "reopened"))
    task.refresh_from_db()
    assert task.status == "review" and task.git.pr_state == "open"
    assert ev.result == "검토 대기"


def test_unknown_pr_action_is_ignored(client, conn, task):
    ev = _send(client, _pr(task, "labeled"))
    assert ev.result == "무시"


# ---------- 리뷰 요청 ↔ 검토자 ----------


def test_review_requested_sets_reviewer_and_dms(client, conn, task, reviewer):
    reviewer.discord_user_id, reviewer.discord_linked_at = "222", task.created_at
    reviewer.save()
    ev = _send(client, _pr(task, "review_requested", requested_reviewer={"id": 501}))
    task.refresh_from_db()
    assert task.reviewer == reviewer and ev.result == "검토자 리뷰어"
    assert task.git.review_requested_at is not None
    assert Notice.objects.filter(user=reviewer, text__contains="리뷰 요청").exists()

    ev = _send(client, _pr(task, "review_request_removed", requested_reviewer={"id": 501}))
    task.refresh_from_db()
    assert task.reviewer is None and ev.result == "검토자 해제"


def test_review_requested_rejects_reviewer_who_cannot_see_project(
    client, conn, task, project, reviewer
):
    project.visibility = "teams"  # 담당 팀이 없으니 리뷰어는 못 본다
    project.save()
    ev = _send(client, _pr(task, "review_requested", requested_reviewer={"id": 501}))
    task.refresh_from_db()
    assert task.reviewer is None and ev.result and ev.result != "검토자 리뷰어"


def test_team_reviewer_and_unknown_login_are_only_recorded(client, conn, task, reviewer):
    ev = _send(client, _pr(task, "review_requested", requested_team={"id": 1}))
    assert ev.result == "팀 리뷰어 무시"
    ev = _send(client, _pr(task, "review_requested", requested_reviewer={"id": 77}))
    assert ev.result == "PM 사용자 아님"


def test_review_rule_off_records_only(client, conn, task, reviewer):
    conn.rule_review = False
    conn.save()
    ev = _send(client, _pr(task, "review_requested", requested_reviewer={"id": 501}))
    task.refresh_from_db()
    assert task.reviewer is None and ev.result == "규칙 꺼짐"


# ---------- 리뷰 상태 ----------


def test_review_states_recompute(client, conn, task, member):
    _review_state(task, client)
    _send(client, _review("approved", login="a"), "pull_request_review")
    link = TaskGitLink.objects.get(task=task)
    assert link.review_state == "approved" and link.reviewed_at is not None
    assert Notice.objects.filter(user=member, text__contains="승인").exists()

    _send(client, _review("commented", login="a"), "pull_request_review")
    link.refresh_from_db()
    assert link.review_states == {"a": "approved"}  # 코멘트는 승인을 지우지 않는다

    _send(client, _review("changes_requested", login="b"), "pull_request_review")
    link.refresh_from_db()
    task.refresh_from_db()
    assert link.review_state == "changes_requested" and task.status == "doing"
    log = ChangeLog.objects.filter(target_id=task.pk, field="status").order_by("-id").first()
    assert log.note == "PR #12 변경 요청" and log.external_actor == "b"

    rid = link.reviews["b"]["id"]
    _send(
        client, _review("dismissed", action="dismissed", login="b", rid=rid), "pull_request_review"
    )
    link.refresh_from_db()
    assert link.review_states == {"a": "approved"} and link.review_state == "approved"


def test_late_older_review_does_not_override_newer_approval(client, conn, task):
    """같은 리뷰어의 10/5 승인 뒤에 10/4 변경 요청이 늦게 도착해도 승인이 남는다."""
    _review_state(task, client)
    _send(client, _review("approved", rid=20, at="2026-10-05"), "pull_request_review")
    ev = _send(client, _review("changes_requested", rid=10, at="2026-10-04"), "pull_request_review")
    link = TaskGitLink.objects.get(task=task)
    task.refresh_from_db()
    assert ev.result == "오래된 리뷰 무시"
    assert link.review_states == {"rev": "approved"} and link.review_state == "approved"
    assert task.status == "review"
    # 옛 리뷰의 철회도 새 승인을 지우지 않는다
    _send(client, _review("dismissed", action="dismissed", rid=10), "pull_request_review")
    link.refresh_from_db()
    assert link.review_state == "approved"


def test_pr_link_survives_title_without_task_number(client, conn, task):
    """이미 이어진 PR은 제목에서 TASK 번호를 지워도 링크로 찾는다."""
    _review_state(task, client)
    renamed = _pr(task, "edited")
    renamed["pull_request"].update(title="리팩터링", head={"ref": "misc", "sha": "c" * 40})
    _send(client, renamed)
    assert TaskGitLink.objects.get(task=task).pr_title == "리팩터링"
    merged = _pr(task, "closed", merged=True, merged_at="2026-10-04T00:00:00Z")
    merged["pull_request"].update(title="리팩터링", head={"ref": "misc", "sha": "c" * 40})
    _send(client, merged)
    task.refresh_from_db()
    assert task.status == "done"


def test_changes_requested_with_rule_off_records_only(client, conn, task):
    _review_state(task, client)
    conn.rule_review = False
    conn.save()
    ev = _send(client, _review("changes_requested"), "pull_request_review")
    task.refresh_from_db()
    assert task.status == "review" and ev.result == "규칙 꺼짐"
    assert TaskGitLink.objects.get(task=task).review_state == "changes_requested"


def test_review_on_unlinked_pr(client, conn):
    ev = _send(client, _review("approved", number=99), "pull_request_review")
    assert ev.result == "연결 안 됨"


# ---------- 재개 = 신규 태스크 ----------


def _merged(client, task):
    _review_state(task, client)
    _send(client, _pr(task, "closed", merged=True, merged_at="2026-10-03T00:00:00Z"))
    task.refresh_from_db()
    assert task.status == "done"


def test_pr_reopened_on_closed_task_creates_new_task(
    client, conn, task, member, admin, org, project
):
    checklist_add(task, "테스트 쓰기", actor=member)
    item = task.checklist.get()
    item.is_done = True
    item.save()
    org.settings = {"notify.github_channel_events": ["reopened"]}
    org.save()
    project.discord_channel_id = "c-1"
    project.save()
    _merged(client, task)
    before = Notice.objects.filter(user=member).count()

    ev = _send(client, _pr(task, "reopened"), delivery="re-1")
    new = Task.objects.exclude(pk=task.pk).get()
    assert ev.task == new and ev.result == f"{new.number} 생성"
    assert new.parent == task and new.assignee == member and new.status == "review"
    assert list(new.checklist.values_list("is_done", flat=True)) == [False]
    link = new.git
    assert link.pr_number == 12 and link.pr_state == "open" and link.branch == "feat/x"
    task.refresh_from_db()
    assert task.status == "done" and task.git.pr_state == "merged"  # 원 태스크는 그대로
    assert ChangeLog.objects.filter(target_id=task.pk, field="reopened_as").exists()
    # 원 담당자에게 담당 요청(행위자 = 프로젝트 관리자)
    req = WorkRequest.objects.get(kind="assign", task=new)
    assert req.to_user == member and req.requested_by == admin and req.status == "pending"
    # 담당 지정 알림 없이 담당 요청 한 통만 간다
    assert Notice.objects.filter(user=member).count() == before + 1
    assert Notice.objects.filter(channel_id="c-1", text__contains="재개").exists()

    # 같은 delivery 재전송은 웹훅 단계에서 버려진다
    signed(client, _pr(task, "reopened"), "pull_request", "re-1")
    # 다른 delivery로 또 와도 열린 이어받은 태스크가 있으니 새로 만들지 않는다
    _send(client, _pr(task, "reopened"), delivery="re-2")
    assert Task.objects.count() == 2

    # 이후 PR 사건은 이어받은 태스크로 간다
    _send(client, _pr(task, "closed", merged=True, merged_at="2026-10-04T00:00:00Z"))
    new.refresh_from_db()
    assert new.status == "done"


def test_pr_reopened_by_assignee_sends_no_assign_request(client, conn, task, member):
    GitHubIdentity.objects.create(user=member, github_id=999, login="dev")
    _merged(client, task)
    _send(client, _pr(task, "reopened"))
    new = Task.objects.exclude(pk=task.pk).get()
    assert new.assignee == member and not WorkRequest.objects.filter(task=new).exists()


def test_reopen_rule_off_and_archived_project(client, conn, task, project):
    _merged(client, task)
    conn.rule_pr = False
    conn.save()
    ev = _send(client, _pr(task, "reopened"))
    assert ev.result == "규칙 꺼짐" and Task.objects.count() == 1

    conn.rule_pr = True
    conn.save()
    project.is_archived = True
    project.save()
    ev = _send(client, _pr(task, "reopened"))
    assert ev.result.startswith("실패") and Task.objects.count() == 1


def test_issue_reopened_on_closed_task_creates_new_task(client, conn, task, member):
    RepoIssue.objects.create(connection=conn, number=5, title="버그", task=task)
    TaskGitLink.objects.create(task=task, connection=conn, issue_number=5, issue_state="open")
    issue = {"number": 5, "title": "버그", "state": "closed"}
    base = {"repository": {"full_name": "o/r"}, "sender": {"id": 999, "login": "dev"}}
    _send(client, {**base, "action": "closed", "issue": issue}, "issues")
    task.refresh_from_db()
    assert task.status == "done"

    ev = _send(
        client, {**base, "action": "reopened", "issue": {**issue, "state": "open"}}, "issues"
    )
    new = Task.objects.exclude(pk=task.pk).get()
    assert ev.result == f"{new.number} 생성" and new.status == "todo"
    assert RepoIssue.objects.get(number=5).task == new
    assert new.git.issue_number == 5 and new.git.issue_state == "open"


def test_reopen_locks_original_task_row(client, conn, task, monkeypatch):
    """동시 reopen 방지: 열린 재개 링크를 보기 전에 원 태스크 행을 잠근다(SQLite는 FOR UPDATE를
    지원하지 않아 실제 교차 실행 대신 잠금 호출 순서를 고정한다)."""
    _merged(client, task)
    calls = []
    real = Task.objects.select_for_update
    real_filter = TaskGitLink.objects.filter

    def spy_lock(*a, **kw):
        calls.append("lock")
        return real(*a, **kw)

    def spy_filter(*a, **kw):
        if "task__status__in" in kw:
            calls.append("existing")
        return real_filter(*a, **kw)

    monkeypatch.setattr(Task.objects, "select_for_update", spy_lock)
    monkeypatch.setattr(TaskGitLink.objects, "filter", spy_filter)
    _send(client, _pr(task, "reopened"))
    assert calls[:2] == ["lock", "existing"]
    assert Task.objects.count() == 2
