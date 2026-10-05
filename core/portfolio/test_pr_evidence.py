"""포트폴리오 PR 근거(G7): 병합 PR만, 번호·주소·병합일만, 저장소 권한·비공개 프로젝트 규칙."""

import pytest
from django.utils import timezone

from github.models import GitHubIdentity, RepoConnection, TaskGitLink
from portfolio import drafts, sources
from portfolio.test_coverage_t1 import hide, rec

pytestmark = pytest.mark.django_db

TITLE = "비밀 PR 제목 xyz"


@pytest.fixture
def link(project, task, member):
    conn = RepoConnection.objects.create(
        project=project, url="u", full_name="o/r", created_by=member
    )
    GitHubIdentity.objects.create(user=member, github_id=1, login="m", repos=["o/r"])
    return TaskGitLink.objects.create(
        task=task,
        connection=conn,
        pr_number=12,
        pr_title=TITLE,
        branch="secret-branch",
        pr_state="merged",
        merged_at=timezone.now(),
    )


def item(user):
    return sources.list_portfolio_sources(user)["items"][0]


def test_only_merged_pr_attached(task, member, link):
    rec(task, member)
    assert item(member)["pr"]["url"] == "https://github.com/o/r/pull/12"
    for state in ("open", "closed"):
        TaskGitLink.objects.filter(pk=link.pk).update(pr_state=state)
        assert item(member)["pr"] is None


def test_no_pr_without_repo_access(task, member, link):
    rec(task, member)
    GitHubIdentity.objects.filter(user=member).update(repos=[])
    member.refresh_from_db()
    member.__dict__.pop("github", None)
    assert item(member)["pr"] is None


def test_private_project_still_excluded(task, project, member, link):
    rec(task, member)
    hide(project)
    assert sources.list_portfolio_sources(member)["total"] == 0


def test_no_title_or_branch_leaks(task, member, link):
    rec(task, member)
    dump = str(item(member))
    assert TITLE not in dump and "secret-branch" not in dump


def test_snapshot_survives_unlink_and_markdown_line(task, org, member, link):
    r = rec(task, member)
    d = drafts.create_draft(member, org_id=org.pk, title="t", body_md="본문", source_ids=[r.pk])
    assert d.sources.get().pr_url.endswith("/pull/12")
    link.delete()
    md = drafts.export_markdown(member, d.pk)
    assert "근거: PR #12" in md and "병합) https://github.com/o/r/pull/12" in md
    assert TITLE not in md and "secret-branch" not in md


def test_no_pr_no_section(task, org, member):
    r = rec(task, member)
    d = drafts.create_draft(member, org_id=org.pk, title="t", body_md="본문", source_ids=[r.pk])
    assert "근거 PR" not in drafts.export_markdown(member, d.pk)
