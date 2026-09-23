"""Build source-aware, permission-checked context for a task's pull request."""

from urllib.parse import urlparse

from common.errors import ServiceError
from orgs.services import is_member
from tasks.decision_services import effective_records
from tasks.models import Link, TaskDecisionRecord

from .models import RepoIssue
from .services import can_view_repo

_INPUT_LABELS = dict(TaskDecisionRecord.INPUT_TYPES)
_STATUS_LABELS = dict(TaskDecisionRecord.STATUSES)
_KIND_LABELS = dict(TaskDecisionRecord.KINDS)
_SOURCE_LABELS = dict(TaskDecisionRecord.SOURCES)


def _iso(value):
    return value.isoformat() if value else None


def _linked_issue_from_url(url):
    """Accept only a canonical github.com owner/repo/issues/N link."""
    parsed = urlparse(url)
    if parsed.scheme != "https" or parsed.hostname != "github.com":
        return None
    parts = [part for part in parsed.path.split("/") if part]
    if len(parts) != 4 or parts[2] != "issues" or not parts[3].isdigit():
        return None
    return f"{parts[0]}/{parts[1]}", int(parts[3])


def _record_payload(record):
    """Return only source summaries and provenance, never verbatim session text."""
    return {
        "id": record.pk,
        "kind": record.kind,
        "kind_label": _KIND_LABELS.get(record.kind),
        "input_type": record.input_type,
        "input_type_label": _INPUT_LABELS.get(record.input_type),
        "status": record.status,
        "status_label": _STATUS_LABELS.get(record.status, "기록됨"),
        "question_summary": record.question_summary,
        "summary": record.summary,
        "reason_summary": record.reason_summary,
        "alternatives": record.alternatives or [],
        "impact_summary": record.impact_summary,
        "evidence_basis": record.evidence_basis,
        "source": record.source,
        "source_label": _SOURCE_LABELS.get(record.source),
        "client_name": record.client_name,
        "subject_user_id": record.subject_user_id,
        "confirmed_by_id": record.confirmed_by_id,
        "supersedes_id": record.supersedes_id,
        "created_at": _iso(record.created_at),
        "confirmed_at": _iso(record.confirmed_at),
        "source_time": _iso(record.source_time),
    }


def build_pr_context(task, *, actor):
    """Build serializable PR context from effective records and a linked issue.

    Organization membership controls task and decision visibility. GitHub issue,
    repository, branch, and PR metadata are returned only after ``can_view_repo``
    grants the actor access to the repository. A code PR context requires a real
    linked issue; no issue number is inferred from the task ID or title.
    """
    if actor is None or not is_member(actor, task.project.org):
        raise ServiceError({"org": "이 조직의 멤버가 아닙니다."})

    git_link = getattr(task, "git", None)
    project_repo = getattr(task.project, "repo", None)
    repo = git_link.connection if git_link is not None else project_repo

    # Resolve the issue reference before exposing any repository metadata.
    issue_number = git_link.issue_number if git_link is not None else None
    issue_repo_name = repo.full_name if repo is not None else ""
    issue_title = git_link.issue_title if git_link is not None else ""
    issue_state = git_link.issue_state if git_link is not None else ""

    if issue_number is None:
        cached_issue = (
            RepoIssue.objects.filter(task=task)
            .select_related("connection")
            .order_by("-number", "-id")
            .first()
        )
        if cached_issue is not None:
            issue_number = cached_issue.number
            issue_repo_name = cached_issue.connection.full_name
            issue_title = cached_issue.title
            issue_state = cached_issue.state
            repo = cached_issue.connection

    if issue_number is None:
        for link in Link.objects.filter(task=task, kind="issue").order_by("id"):
            parsed = _linked_issue_from_url(link.url)
            if parsed is None:
                continue
            issue_repo_name, issue_number = parsed
            issue_title = link.title
            # A manual link proves the reference, but does not prove cached GitHub
            # state. Keep the state blank and do not fabricate repository metadata.
            break

    if issue_number is None or not issue_repo_name:
        raise ServiceError(
            {"issue": "PR 맥락을 만들기 전에 이 태스크에 GitHub 이슈를 연결해 주세요."}
        )
    if not can_view_repo(actor, issue_repo_name):
        raise ServiceError({"repository": "이 저장소를 볼 수 있는 GitHub 권한이 없습니다."})

    # TaskGitLink normally belongs to the project's repository. Reject inconsistent
    # references rather than mixing an issue from one repository with another repo's
    # branch or pull-request metadata.
    if repo is not None and repo.full_name != issue_repo_name:
        raise ServiceError({"issue": "연결된 이슈와 태스크 저장소가 일치하지 않습니다."})

    issue_url = f"https://github.com/{issue_repo_name}/issues/{issue_number}"
    cached_issue = None
    if repo is not None:
        cached_issue = RepoIssue.objects.filter(
            connection=repo, number=issue_number
        ).first()
    if cached_issue is not None:
        issue_title = issue_title or cached_issue.title
        issue_state = issue_state or cached_issue.state

    records = list(effective_records(task, actor=actor))
    user_inputs = [_record_payload(record) for record in records if record.kind == "user_input"]
    ai_judgments = [_record_payload(record) for record in records if record.kind == "ai_judgment"]

    repository = None
    if repo is not None:
        repository = {"full_name": repo.full_name, "url": f"https://github.com/{repo.full_name}"}

    git = None
    if git_link is not None:
        git = {
            "branch": git_link.branch,
            "pull_request": {
                "number": git_link.pr_number,
                "title": git_link.pr_title,
                "state": git_link.pr_state,
            }
            if git_link.pr_number
            else None,
        }

    return {
        "task": {
            "id": task.pk,
            "number": task.number,
            "title": task.title,
            "project_id": task.project_id,
            "project_name": task.project.name,
        },
        "repository": repository,
        "issue": {
            "number": issue_number,
            "title": issue_title,
            "state": issue_state,
            "url": issue_url,
        },
        "git": git,
        "decisions": {
            "user_inputs": user_inputs,
            "ai_judgments": ai_judgments,
            "timeline": sorted(
                user_inputs + ai_judgments,
                key=lambda item: (item["created_at"] or "", item["id"]),
            ),
        },
        "pr_suggestion": {
            "title": f"{task.title} ({task.number})",
            "body": f"Closes #{issue_number}\n\n{task.number}",
        },
    }
