"""IMPL-PLAN-8 G0: status_since·목록 annotate·알림 관문·디스패치 골격·앱 권한 점검."""

import pytest
from django.core.cache import cache
from django.db import connection
from django.test.utils import CaptureQueriesContext
from django.utils import timezone

from github import client as gh_client
from github import notify
from github import services as ghs
from github.client import GitHubError
from github.conftest import signed
from github.models import GitEvent, GitHubInstallation, RepoConnection, TaskGitLink
from tasks.brief import task_brief
from tasks.models import Notice
from tasks.services import create_task, transition

pytestmark = pytest.mark.django_db


@pytest.fixture
def conn(gh, project, admin):
    return RepoConnection.objects.create(
        project=project, url="https://github.com/o/r.git", full_name="o/r", created_by=admin
    )


# ---------- status_since ----------


def test_transition_stamps_status_since_only_on_real_change(task, member):
    assert task.status_since is None
    transition(task, "review", actor=member, source="web", expected_version=task.version)
    first = task.status_since
    assert first is not None
    transition(task, "review", actor=member, source="web", expected_version=task.version)
    task.refresh_from_db()
    assert task.status_since == first  # 같은 상태 재요청은 아무것도 바꾸지 않는다
    assert task_brief(task)["status_since"] == first.isoformat()
    assert task_brief(task)["review_requested_at"] is None  # annotate 안 된 경로


def test_org_tasks_annotates_review_requested_at_without_n_plus_1(
    api, org, project, member, task, conn
):
    at = timezone.now()
    TaskGitLink.objects.create(task=task, connection=conn, review_requested_at=at)
    url = f"/api/orgs/{org.pk}/tasks"
    with CaptureQueriesContext(connection) as one:
        r = api.get(url)
    item = r.json()["items"][0]
    assert item["review_requested_at"] is not None
    assert "status_since" in item
    for i in range(3):
        create_task(
            project=project, title=f"t{i}", actor=member, source="web", due_date=task.due_date
        )
    with CaptureQueriesContext(connection) as four:
        r = api.get(url)
    assert len(r.json()["items"]) == 4
    assert len(four) == len(one)


# ---------- 알림 관문 ----------


def test_channel_is_off_by_default_and_needs_kind_and_channel(conn, project, org, task):
    notify.channel(conn, "pr_opened", "🔀 PR #1 열림", task)
    assert not Notice.objects.exists()  # 기본 꺼짐
    org.settings = {"notify.github_channel_events": ["pr_opened"]}
    org.save()
    project.refresh_from_db()
    notify.channel(conn, "pr_opened", "🔀 PR #1 열림", task)
    assert not Notice.objects.exists()  # 채널 없음
    project.discord_channel_id = "c-1"
    project.save()
    conn.refresh_from_db()
    notify.channel(conn, "pr_merged", "병합", task)
    assert not Notice.objects.exists()  # 고르지 않은 종류
    notify.channel(conn, "pr_opened", "🔀 PR #1 열림", task, extra="https://x/pull/1")
    n = Notice.objects.get()
    assert n.channel_id == "c-1" and n.user is None
    assert "🔀 PR #1 열림" in n.text and task.number in n.text and "https://x/pull/1" in n.text


def test_dm_gates_org_user_and_visibility(org, project, task, member, outsider):
    notify.dm(task, member, "✏️ PR #1 변경 요청")
    assert Notice.objects.filter(user=member).count() == 1  # 기본 켬

    notify.dm(task, outsider, "x")  # 조직 밖
    notify.dm(task, None, "x")
    assert Notice.objects.count() == 1

    member.settings = {"user.notify_dm": False}
    member.save()
    notify.dm(task, member, "x")
    assert Notice.objects.count() == 1

    member.settings = {}
    member.save()
    org.settings = {"notify.github_dm": False}
    org.save()
    task.project.org.refresh_from_db()
    notify.dm(task, member, "x")
    assert Notice.objects.count() == 1

    org.settings = {}
    org.save()
    task.project.org.refresh_from_db()
    task.project.visibility = "teams"  # 담당 팀이 없으니 팀원은 못 본다
    task.project.save()
    notify.dm(task, member, "x")
    assert Notice.objects.count() == 1


# ---------- 디스패치 골격 ----------


@pytest.mark.parametrize("event", ["check_suite", "status", "milestone", "release"])
def test_new_events_are_dispatched_and_recorded_as_ignored(gh, client, conn, event):
    payload = {"repository": {"full_name": "o/r"}, "action": "x", "sender": {"login": "dev"}}
    r = signed(client, payload, event, f"g0-{event}")
    assert r.status_code == 200
    ev = GitEvent.objects.get(connection=conn)
    assert ev.kind == event and ev.result == "무시"


def test_unsupported_event_stays_202(gh, client, conn):
    r = signed(client, {"repository": {"full_name": "o/r"}}, "fork", "g0-fork")
    assert r.status_code == 202
    assert not GitEvent.objects.exists()


def test_occurred_at_reads_new_event_timestamps():
    ts = "2026-10-01T01:02:03Z"
    assert ghs._occurred_at("pull_request_review", {"review": {"submitted_at": ts}}).day == 1
    assert ghs._occurred_at("status", {"updated_at": ts}).day == 1
    assert ghs._occurred_at("release", {"release": {"published_at": ts}}).day == 1


# ---------- 앱 권한 점검 ----------


@pytest.fixture
def inst(gh, org, admin):
    cache.clear()
    return GitHubInstallation.objects.create(
        org=org, installation_id=77, account_login="o", installed_by=admin
    )


def test_app_capabilities_reports_missing_and_caches(inst, org, monkeypatch):
    calls = []

    def fake(method, path, token, **kw):
        calls.append(path)
        return {
            "permissions": {"pull_requests": "read", "issues": "write", "contents": "write"},
            "events": ["pull_request", "pull_request_review", "milestone"],
        }

    monkeypatch.setattr(gh_client, "app_jwt", lambda: "jwt")
    monkeypatch.setattr(gh_client, "request", fake)
    caps = ghs.app_capabilities(org)
    assert caps["review"] == {"ok": True, "missing": []}
    assert caps["milestone"]["ok"] is True
    assert caps["ci"]["missing"] == ["Checks 읽기 권한", "check_suite 구독"]
    assert caps["release"]["missing"] == ["release 구독"]
    assert ghs.app_capabilities(org) == caps
    assert calls == ["/app/installations/77"]  # 두 번째는 캐시

    # 재승인 완료 이벤트가 캐시를 비운다
    ghs._installation_event(
        "installation", {"action": "new_permissions_accepted", "installation": {"id": 77}}
    )
    ghs.app_capabilities(org)
    assert len(calls) == 2


def test_app_capabilities_none_without_install_or_on_error(gh, org, inst, monkeypatch):
    monkeypatch.setattr(gh_client, "app_jwt", lambda: "jwt")

    def boom(*a, **kw):
        raise GitHubError(500, "x")

    monkeypatch.setattr(gh_client, "request", boom)
    assert ghs.app_capabilities(org) is None
    inst.delete()
    assert ghs.app_capabilities(org) is None
