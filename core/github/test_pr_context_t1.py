"""PR 컨텍스트(T1): 접근 권한, 이슈 해석 순서, 결정 기록 노출 범위, 오류 경로."""

import pytest

from common.errors import ServiceError
from github.models import GitHubIdentity, RepoConnection, RepoIssue, TaskGitLink
from github.pr_context import _linked_issue_from_url, build_pr_context
from projects.models import Project
from tasks.models import Link, TaskDecisionRecord

pytestmark = pytest.mark.django_db


@pytest.fixture
def conn(project, admin):
    return RepoConnection.objects.create(
        project=project, url="u", full_name="o/r", created_by=admin
    )


@pytest.fixture
def gh_member(member):
    """o/r만 볼 수 있는 GitHub 연결."""
    return GitHubIdentity.objects.create(user=member, github_id=1, login="m", repos=["o/r"])


def git_link(task, conn, **kw):
    kw.setdefault("issue_number", 7)
    kw.setdefault("issue_title", "로그인 버그")
    kw.setdefault("issue_state", "open")
    return TaskGitLink.objects.create(task=task, connection=conn, **kw)


def decision(task, user, **kw):
    kw.setdefault("kind", "user_input")
    if kw["kind"] == "user_input":
        kw.update(
            input_type=kw.get("input_type", "requirement"),
            evidence_basis=kw.get("evidence_basis", "explicit_reply"),
            subject_user=user,
        )
        kw.setdefault("status", "captured")
    else:
        kw.setdefault("status", "recorded")
    return TaskDecisionRecord.objects.create(
        task=task, summary=kw.pop("summary", "요지"), recorded_by=user, source="web", **kw
    )


def errors(task, actor):
    with pytest.raises(ServiceError) as e:
        build_pr_context(task, actor=actor)
    return e.value.errors


# ---------- _linked_issue_from_url ----------


@pytest.mark.parametrize(
    "url,expected",
    [
        ("https://github.com/o/r/issues/12", ("o/r", 12)),
        ("https://github.com/o/r/issues/12/", ("o/r", 12)),
        ("http://github.com/o/r/issues/12", None),
        ("https://gitlab.com/o/r/issues/12", None),
        ("https://github.com.evil.io/o/r/issues/12", None),
        ("https://github.com/o/r/pull/12", None),
        ("https://github.com/o/r/issues/abc", None),
        ("https://github.com/o/r/issues", None),
        ("https://github.com/o/r/issues/12/comments", None),
        ("https://github.com/o/issues/12", None),
        ("", None),
    ],
)
def test_linked_issue_url_parsing(url, expected):
    assert _linked_issue_from_url(url) == expected


# ---------- 접근 검사 ----------


def test_non_member_and_anonymous_are_refused(task, git_link_task, outsider):
    assert "org" in errors(task, outsider)
    assert "org" in errors(task, None)


@pytest.fixture
def git_link_task(task, conn):
    return git_link(task, conn)


def test_no_issue_anywhere_is_an_error(task, member):
    assert "issue" in errors(task, member)


def test_no_github_identity_or_repo_access_hides_everything(task, git_link_task, member, admin):
    # GitHub 미연결
    assert "repository" in errors(task, member)
    # 연결은 했지만 다른 저장소만 볼 수 있음
    GitHubIdentity.objects.create(user=member, github_id=2, login="m", repos=["o/other"])
    assert "repository" in errors(task, member)


def test_repo_access_is_per_actor(task, git_link_task, member, admin, gh_member):
    assert build_pr_context(task, actor=member)["repository"]["full_name"] == "o/r"
    assert "repository" in errors(task, admin)  # 조직 관리자라도 GitHub 권한이 없으면 안 된다


# ---------- 정상 경로 ----------


def test_full_context_from_git_link(task, conn, member, gh_member):
    git_link(task, conn, branch="feat/login", pr_number=9, pr_title="로그인 수정", pr_state="open")
    out = build_pr_context(task, actor=member)
    assert out["task"]["id"] == task.pk and out["task"]["number"] == task.number
    assert out["repository"] == {"full_name": "o/r", "url": "https://github.com/o/r"}
    assert out["issue"] == {
        "number": 7,
        "title": "로그인 버그",
        "state": "open",
        "url": "https://github.com/o/r/issues/7",
    }
    assert out["git"]["branch"] == "feat/login"
    assert out["git"]["pull_request"] == {"number": 9, "title": "로그인 수정", "state": "open"}
    assert out["pr_suggestion"]["body"] == f"Closes #7\n\n{task.number}"
    assert out["pr_suggestion"]["title"] == f"{task.title} ({task.number})"


def test_git_link_without_pr_has_null_pull_request(task, conn, member, gh_member):
    git_link(task, conn)
    out = build_pr_context(task, actor=member)
    assert out["git"]["pull_request"] is None


def test_issue_number_is_not_inferred_from_task(task, conn, member, gh_member):
    git_link(task, conn, issue_number=None, issue_title="", issue_state="")
    assert "issue" in errors(task, member)


def test_blank_git_link_title_falls_back_to_cached_issue(task, conn, member, gh_member):
    git_link(task, conn, issue_title="", issue_state="")
    RepoIssue.objects.create(connection=conn, number=7, title="캐시 제목", state="closed")
    out = build_pr_context(task, actor=member)["issue"]
    assert (out["title"], out["state"]) == ("캐시 제목", "closed")


def test_cached_repo_issue_used_when_git_link_has_no_issue(task, conn, member, gh_member):
    git_link(task, conn, issue_number=None, issue_title="", issue_state="")
    RepoIssue.objects.create(connection=conn, number=3, title="낮은 번호", task=task)
    RepoIssue.objects.create(connection=conn, number=5, title="높은 번호", task=task)
    out = build_pr_context(task, actor=member)
    assert out["issue"]["number"] == 5 and out["issue"]["title"] == "높은 번호"


def test_cached_issue_without_git_link_uses_its_connection(task, conn, member, gh_member):
    RepoIssue.objects.create(connection=conn, number=4, title="캐시만", task=task)
    out = build_pr_context(task, actor=member)
    assert out["issue"]["number"] == 4 and out["git"] is None
    assert out["repository"]["full_name"] == "o/r"


def test_manual_issue_link_gives_reference_only(task, member, admin):
    GitHubIdentity.objects.create(user=member, github_id=3, login="m", repos=["x/y"])
    Link.objects.create(
        task=task,
        kind="issue",
        title="수동 이슈",
        url="https://github.com/x/y/issues/21",
        created_by=member,
    )
    out = build_pr_context(task, actor=member)
    assert out["repository"] is None and out["git"] is None
    assert out["issue"] == {
        "number": 21,
        "title": "수동 이슈",
        "state": "",
        "url": "https://github.com/x/y/issues/21",
    }


def test_manual_link_skips_invalid_urls_and_takes_first_valid(task, member):
    GitHubIdentity.objects.create(user=member, github_id=3, login="m", repos=["x/y"])
    for i, url in enumerate(
        [
            "https://example.com/x/y/issues/1",
            "https://github.com/x/y/pull/2",
            "https://github.com/x/y/issues/30",
            "https://github.com/x/y/issues/31",
        ]
    ):
        Link.objects.create(task=task, kind="issue", title=f"l{i}", url=url, created_by=member)
    Link.objects.create(  # 이슈 종류가 아닌 링크는 무시한다
        task=task,
        kind="doc",
        title="문서",
        url="https://github.com/x/y/issues/99",
        created_by=member,
    )
    assert build_pr_context(task, actor=member)["issue"]["number"] == 30


def test_manual_link_to_unviewable_repo_is_refused(task, member):
    Link.objects.create(
        task=task,
        kind="issue",
        title="비공개",
        url="https://github.com/x/y/issues/1",
        created_by=member,
    )
    assert "repository" in errors(task, member)  # GitHub 미연결


def test_manual_link_repo_must_match_project_repo(task, conn, member):
    GitHubIdentity.objects.create(user=member, github_id=3, login="m", repos=["o/r", "x/y"])
    Link.objects.create(
        task=task,
        kind="issue",
        title="다른 저장소",
        url="https://github.com/x/y/issues/1",
        created_by=member,
    )
    assert "issue" in errors(task, member)  # 프로젝트 저장소(o/r)와 불일치


def test_manual_link_matching_project_repo_uses_cached_metadata(task, conn, member, gh_member):
    RepoIssue.objects.create(connection=conn, number=8, title="캐시 제목", state="closed")
    Link.objects.create(
        task=task, kind="issue", title="", url="https://github.com/o/r/issues/8", created_by=member
    )
    out = build_pr_context(task, actor=member)
    assert out["issue"]["title"] == "캐시 제목" and out["issue"]["state"] == "closed"
    assert out["repository"]["full_name"] == "o/r"


# ---------- 결정 기록 ----------


def test_decisions_only_effective_records_in_timeline_order(task, conn, member, admin, gh_member):
    git_link(task, conn)
    cap = decision(task, member, summary="수집됨")
    decision(task, member, summary="제안", evidence_basis="inferred", status="proposed")
    decision(task, member, summary="제외", status="rejected")
    decision(task, member, summary="대체됨", status="superseded")
    ai = decision(task, admin, kind="ai_judgment", summary="AI 판단", input_type=None)
    d = build_pr_context(task, actor=member)["decisions"]
    assert [i["id"] for i in d["user_inputs"]] == [cap.pk]
    assert [i["id"] for i in d["ai_judgments"]] == [ai.pk]
    assert [i["id"] for i in d["timeline"]] == [cap.pk, ai.pk]
    assert d["ai_judgments"][0]["kind_label"] == "AI 작업 판단"
    assert d["user_inputs"][0]["status_label"] == "세션에서 수집"
    assert d["user_inputs"][0]["input_type_label"] == "요구·제약"
    assert d["user_inputs"][0]["source_label"] == "웹"


def test_decisions_never_include_verbatim_text(task, conn, member, gh_member):
    git_link(task, conn)
    decision(task, member, verbatim_text="원문 대화 내용")
    out = build_pr_context(task, actor=member)
    assert "verbatim" not in str(out) and "원문 대화" not in str(out)


def test_empty_decisions_are_empty_lists(task, conn, member, gh_member):
    git_link(task, conn)
    d = build_pr_context(task, actor=member)["decisions"]
    assert d == {"user_inputs": [], "ai_judgments": [], "timeline": []}


# ---------- API ----------


def test_api_pr_context_ok(api, task, conn, member, gh_member):
    git_link(task, conn)
    r = api.get(f"/api/tasks/{task.pk}/pr-context")
    assert r.status_code == 200 and r.json()["issue"]["number"] == 7


def test_api_pr_context_errors(api, client, task, conn, outsider):
    assert api.get(f"/api/tasks/{task.pk}/pr-context").status_code == 400  # 이슈 없음
    git_link(task, conn)
    assert api.get(f"/api/tasks/{task.pk}/pr-context").status_code == 400  # GitHub 권한 없음
    assert api.get("/api/tasks/999999/pr-context").status_code == 404
    assert client.get(f"/api/tasks/{task.pk}/pr-context").status_code == 401


def test_api_pr_context_private_project_task_is_404(api, project, task, conn, member, gh_member):
    git_link(task, conn)
    Project.objects.filter(pk=project.pk).update(visibility="teams")
    assert api.get(f"/api/tasks/{task.pk}/pr-context").status_code == 404
