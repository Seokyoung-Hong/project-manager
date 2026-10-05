"""IMPL-PLAN-8 G4: 마일스톤 동기화(§3.9)·릴리스(§3.10). 이슈 양방향 동기화는 §10-1로 하지 않는다."""

from datetime import date, timedelta

import pytest
from django.utils import timezone

from common.dates import today_kst
from github.conftest import signed
from github.crypto import encrypt
from github.models import GitEvent, GitHubIdentity, GitRelease, RepoConnection
from github.sync import releases_for
from projects.models import Milestone
from projects.services import create_milestone, create_project
from tasks.models import Notice

pytestmark = pytest.mark.django_db


@pytest.fixture
def conn(gh, project, admin):
    return RepoConnection.objects.create(
        project=project, url="https://github.com/o/r.git", full_name="o/r", created_by=admin
    )


def _ms_payload(action, number=3, title="v1.0", due="2026-11-30T07:00:00Z", state="open"):
    return {
        "action": action,
        "repository": {"full_name": "o/r"},
        "milestone": {"number": number, "title": title, "due_on": due, "state": state},
        "sender": {"id": 1, "login": "someone"},
    }


def _last(conn):
    return GitEvent.objects.filter(connection=conn).order_by("-id").first().result


# ---------- 마일스톤 GH→PM ----------


def test_milestone_created_edited_closed_deleted(client, conn, project):
    signed(client, _ms_payload("created"), "milestone", "m1")
    ms = Milestone.objects.get(project=project, gh_number=3)
    assert (ms.name, ms.target_date, ms.status) == ("v1.0", date(2026, 11, 30), "planned")
    assert _last(conn) == "생성"

    signed(client, _ms_payload("edited", title="v1.0.0", due=None), "milestone", "m2")
    ms.refresh_from_db()
    assert ms.name == "v1.0.0" and ms.target_date == date(2026, 11, 30)  # due 없으면 유지

    signed(client, _ms_payload("closed", title="v1.0.0", state="closed"), "milestone", "m3")
    ms.refresh_from_db()
    assert ms.status == "done"
    signed(client, _ms_payload("opened", title="v1.0.0"), "milestone", "m4")
    ms.refresh_from_db()
    assert ms.status == "active"  # 다시 열리면 done → active

    signed(client, _ms_payload("deleted"), "milestone", "m5")
    ms.refresh_from_db()
    assert ms.gh_number is None  # PM 행은 남긴다


def test_new_milestone_without_due_is_rejected(client, conn, project):
    signed(client, _ms_payload("created", due=None), "milestone", "m1")
    assert not Milestone.objects.exists()
    assert "목표일" in _last(conn)


def test_same_repo_two_projects_two_rows(client, conn, org, admin):
    other = create_project(org=org, name="둘째", actor=admin, owners=[admin], status="active")
    RepoConnection.objects.create(
        project=other, url="https://github.com/o/r", full_name="o/r", created_by=admin
    )
    signed(client, _ms_payload("created"), "milestone", "m1")
    assert Milestone.objects.filter(gh_number=3).count() == 2


def test_rule_milestone_off_records_only(client, conn):
    conn.rule_milestone = False
    conn.save()
    signed(client, _ms_payload("created"), "milestone", "m1")
    assert not Milestone.objects.exists()
    assert _last(conn) == "기록만"


# ---------- 마일스톤 PM→GH ----------


@pytest.fixture
def calls(monkeypatch):
    seen = []

    def fake(method, path, token, *, body=None, **kw):
        seen.append({"method": method, "path": path, "token": token, "body": body})
        return {"number": 9} if method == "POST" else {}

    def boom(iid):
        raise AssertionError("쓰기에 설치 토큰을 썼다")

    monkeypatch.setattr("github.client.request", fake)
    monkeypatch.setattr("github.client.installation_token", boom)
    return seen


def _link_github(user):
    GitHubIdentity.objects.create(
        user=user,
        github_id=4242,
        login="admin-gh",
        token_enc=encrypt("ghu_user"),
        token_expires_at=timezone.now() + timedelta(hours=1),
    )


def test_dialog_checkbox_creates_on_github_and_echo_is_noop(
    client, conn, org, project, admin, calls
):
    _link_github(admin)
    client.force_login(admin)
    target = today_kst() + timedelta(days=20)
    data = {
        "project": project.pk,
        "name": "v2",
        "target_date": target.isoformat(),
        "status": "planned",
    }
    client.post(f"/orgs/{org.pk}/milestones/new", {**data, "github": "on"})
    ms = Milestone.objects.get(name="v2")
    assert ms.gh_number == 9
    assert calls[-1]["method"] == "POST" and calls[-1]["token"] == "ghu_user"
    assert calls[-1]["body"]["due_on"].startswith(target.isoformat())

    # 되돌아온 created 웹훅은 같은 값이라 아무것도 바꾸지 않는다
    signed(
        client,
        _ms_payload("created", number=9, title="v2", due=calls[-1]["body"]["due_on"]),
        "milestone",
        "e1",
    )
    assert Milestone.objects.filter(project=project).count() == 1
    assert _last(conn) == "변경 없음"

    # 편집은 PATCH
    client.post(f"/milestones/{ms.pk}/edit", {**data, "status": "done", "github": "on"})
    assert calls[-1]["method"] == "PATCH" and calls[-1]["path"].endswith("/milestones/9")
    assert calls[-1]["body"]["state"] == "closed"


def test_dialog_without_checkbox_does_not_call_github(client, conn, org, project, admin, calls):
    _link_github(admin)
    client.force_login(admin)
    data = {
        "project": project.pk,
        "name": "v3",
        "target_date": (today_kst() + timedelta(days=5)).isoformat(),
    }
    client.post(f"/orgs/{org.pk}/milestones/new", data)
    assert calls == [] and Milestone.objects.get(name="v3").gh_number is None


def test_webhook_before_gh_number_saved_adopts_same_name_row(client, conn, project, admin):
    ms = create_milestone(project=project, name="v4", target_date=date(2026, 12, 1), actor=admin)
    signed(
        client,
        _ms_payload("created", number=11, title="V4", due="2026-12-01T12:00:00Z"),
        "milestone",
        "m1",
    )
    ms.refresh_from_db()
    assert ms.gh_number == 11 and Milestone.objects.count() == 1


# ---------- 릴리스 ----------


def _rel_payload(action, tag="v1.0", name="첫 릴리스", draft=False):
    return {
        "action": action,
        "repository": {"full_name": "o/r"},
        "release": {
            "tag_name": tag,
            "name": name,
            "html_url": f"https://github.com/o/r/releases/tag/{tag}",
            "draft": draft,
            "prerelease": False,
            "published_at": "2026-10-05T01:00:00Z",
        },
        "sender": {"id": 1, "login": "someone"},
    }


def test_release_published_links_milestone_and_posts_channel(client, conn, org, project, admin):
    ms = create_milestone(project=project, name="V1.0", target_date=date(2026, 12, 1), actor=admin)
    org.settings = {"notify.github_channel_events": ["release"]}
    org.save()
    project.discord_channel_id = "c-1"
    project.save()
    signed(client, _rel_payload("published"), "release", "r1")
    rel = GitRelease.objects.get(connection=conn, tag="v1.0")
    assert rel.milestone == ms
    ms.refresh_from_db()
    assert ms.status == "planned"  # 완료는 제안만
    notice = Notice.objects.get()
    assert "🔖 릴리스 v1.0 발행" in notice.text and "완료로 표시" in notice.text

    signed(client, _rel_payload("edited", name="고친 이름"), "release", "r2")
    assert GitRelease.objects.get().name == "고친 이름"
    assert Notice.objects.count() == 1  # edited는 알리지 않는다

    signed(client, _rel_payload("deleted"), "release", "r3")
    assert not GitRelease.objects.exists()


def test_draft_release_ignored(client, conn):
    signed(client, _rel_payload("published", draft=True), "release", "r1")
    assert not GitRelease.objects.exists()


def test_releases_for_needs_repo_access(conn, admin, member):
    GitRelease.objects.create(connection=conn, tag="v1", url="u", published_at=timezone.now())
    assert releases_for(conn.project, member) == []  # GitHub 미연결
    _link_github(admin)
    admin.github.repos = ["o/r"]
    admin.github.save()
    admin.refresh_from_db()
    assert [r.tag for r in releases_for(conn.project, admin)] == ["v1"]
