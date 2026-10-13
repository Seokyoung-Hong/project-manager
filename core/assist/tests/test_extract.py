"""태스크 후보: 검증·만들기·이슈 연결(IMPL-PLAN-12 §7.4·§11.2)."""

import json
from datetime import date

import pytest
from django.http import Http404

from assist import extract, prompts
from assist.context import visible_issue
from assist.models import AiJob
from common.errors import ServiceError
from github.models import GitHubIdentity, RepoConnection, RepoIssue, TaskGitLink
from github.services import import_issue
from notes.models import VoiceRecording
from projects.docs import create_doc


def test_validate_and_parse():
    raw = (
        "<think>생각</think>\n```json\n"
        + json.dumps(
            {
                "tasks": [
                    {
                        "title": " 첫\n일 ",
                        "due": "2026-13-01",
                        "assignee": 3,
                        "evidence": "e" * 500,
                    },
                    {"title": "둘", "due": "2020-01-01"},
                    {"title": "셋", "due": "2026-11-02", "description": "\x00설명"},
                    "쓰레기",
                ]
            }
        )
        + "\n```\n끝"
    )
    job = AiJob(kind="extract", field="extract.issue")
    rows = json.loads(prompts.parse_output(job, raw, earliest=date(2025, 10, 13)))["tasks"]
    assert [r["title"] for r in rows] == ["첫 일", "둘", "셋"]
    assert (
        rows[0]["due"] is None and rows[0]["assignee"] is None and len(rows[0]["evidence"]) == 300
    )
    assert rows[1]["due"] is None  # 1년보다 이르다
    assert rows[2]["due"] == "2026-11-02" and rows[2]["description"] == "설명"
    with pytest.raises(ValueError):
        prompts.parse_output(job, '{"tasks": [{"title": ""}]}')
    with pytest.raises(ValueError):
        prompts.parse_output(job, "후보 없음")


def _job(user, org, target_type, target_id, tasks):
    return AiJob.objects.create(
        user=user,
        org=org,
        kind="extract",
        field="extract.meeting" if target_type == "doc" else "extract.issue",
        target_type=target_type,
        target_id=target_id,
        status="done",
        result=json.dumps({"tasks": tasks}),
    )


def test_create_from_meeting(org, member, admin, project):
    d = create_doc(org=org, actor=member, kind="meeting", project=project)
    VoiceRecording.objects.create(
        note=d, guild_id="g", voice_channel_id="v", started_by=member, host=member
    )
    job = _job(member, org, "doc", d.pk, [{"title": "가"}, {"title": "나"}])
    rows = [
        {"index": 0, "title": "가 고침", "assignee_id": admin.pk, "due": "2030-01-02"},
        {"index": 1, "title": ""},
        {"index": 7, "title": "없는 후보"},
    ]
    out = extract.create_from_candidates(job, rows, member)
    (i0, t0, e0), (i1, t1, e1), (i7, t7, e7) = out
    assert t0.title == "가 고침" and t0.project == project and str(t0.due_date) == "2030-01-02"
    assert t0 in d.tasks.all() and e0 == ""
    assert t1 is None and e1 and t7 is None and e7
    again = extract.create_from_candidates(job, rows[:1], member)  # idempotency
    assert again[0][1].pk == t0.pk
    with pytest.raises(Http404):
        extract.create_from_candidates(job, rows, admin)  # 남의 작업


def test_not_ready(org, member):
    job = AiJob.objects.create(user=member, org=org, kind="extract", field="extract.issue")
    with pytest.raises(ServiceError):
        extract.create_from_candidates(job, [], member)


@pytest.fixture
def issue(project, admin, member):
    conn = RepoConnection.objects.create(
        project=project, url="https://github.com/o/r", full_name="o/r", created_by=admin
    )
    GitHubIdentity.objects.create(user=member, github_id=1, login="m", repos=["o/r"])
    return RepoIssue.objects.create(connection=conn, number=5, title="큰 이슈", body="본문")


def test_visible_issue_needs_repo_access(issue, member, admin):
    assert visible_issue(member, issue.pk) == issue
    with pytest.raises(Http404):
        visible_issue(admin, issue.pk)  # GitHub 저장소 권한 없음


def test_issue_first_linked_rest_subtasks(org, member, issue):
    job = _job(member, org, "issue", issue.pk, [{"title": "a"}, {"title": "b"}, {"title": "c"}])
    rows = [{"index": i, "title": t} for i, t in enumerate("abc")]
    out = extract.create_from_candidates(job, rows, member)
    first, *rest = [t for _, t, _ in out]
    issue.refresh_from_db()
    assert issue.task == first and TaskGitLink.objects.get(task=first).issue_number == 5
    assert all(t.group_id == first.pk for t in rest)
    assert TaskGitLink.objects.filter(issue_number=5).count() == 1


def test_issue_already_imported_all_under(org, member, issue):
    imported = import_issue(issue, member)
    job = _job(member, org, "issue", issue.pk, [{"title": "a"}, {"title": "b"}])
    out = extract.create_from_candidates(
        job, [{"index": 0, "title": "a"}, {"index": 1, "title": "b"}], member
    )
    assert all(t.group_id == imported.pk for _, t, _ in out)
