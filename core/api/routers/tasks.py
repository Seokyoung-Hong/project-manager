from datetime import date

from django.db.models import F
from django.utils.dateparse import parse_datetime
from ninja import Router
from ninja.errors import HttpError

from accounts.models import User
from common.errors import ServiceError
from github import client as github_client
from github.models import RepoIssue, TaskGitLink
from github.services import can_view_repo, user_token
from github.client import GitHubError
from orgs.services import orgs_of
from projects.models import Project
from tasks.brief import task_brief
from tasks.models import ChangeLog, Task
from tasks.services import (
    create_task,
    delete_task,
    extend_due,
    replace_checklist,
    transition,
    update_task,
    visible_tasks,
)

from ..context import clamp_page, ctx, idem_key, task_or_404
from ..schemas import (
    ChangeLogOut,
    ConflictOut,
    ErrorOut,
    ExtendIn,
    TaskCreateIn,
    TaskListOut,
    TaskOut,
    TaskPatchIn,
    TransitionIn,
)
from ..serialize import changelog_out, task_out

router = Router(tags=["tasks"])


@router.get("", response=TaskListOut)
def list_tasks(
    request,
    org: int | None = None,
    project: int | None = None,
    assignee: int | None = None,
    status: str | None = None,
    due_from: date | None = None,
    due_to: date | None = None,
    q: str | None = None,
    updated_since: str | None = None,
    include_archived: bool = False,
    limit: int = 50,
    offset: int = 0,
):
    qs = visible_tasks(request.auth)
    if org is not None:
        qs = qs.filter(project__org_id=org)
    if project is not None:
        qs = qs.filter(project_id=project)
    if assignee is not None:
        qs = qs.filter(assignee_id=assignee)
    if status:
        values = [s.strip() for s in status.split(",") if s.strip()]
        bad = [s for s in values if s not in dict(Task.STATUSES)]
        if bad:
            raise HttpError(
                400,
                f"알 수 없는 상태: {', '.join(bad)}. 가능한 값: {', '.join(dict(Task.STATUSES))}",
            )
        qs = qs.filter(status__in=values)
    if due_from:
        qs = qs.filter(due_date__gte=due_from)
    if due_to:
        qs = qs.filter(due_date__lte=due_to)
    if q:
        qs = qs.filter(title__icontains=q)
    if updated_since:
        # 채널 게시가 이전 틱 이후 바뀐 것만 받아 상태를 비교한다. 상태를 가리지 않는다 —
        # 방금 done으로 넘어간 것도 봐야 '완료' 사건을 만들 수 있다.
        moment = parse_datetime(updated_since)
        if moment is None:
            raise HttpError(400, "updated_since는 ISO 8601 시각이어야 합니다.")
        qs = qs.filter(updated_at__gt=moment)
    if not include_archived:
        qs = qs.filter(project__is_archived=False)
    limit, offset = clamp_page(limit, offset)
    # nulls_last를 명시해야 SQLite(기한 미정이 앞)와 Postgres(뒤)가 같아지고, by_due()와도 맞는다.
    qs = qs.order_by(F("due_date").asc(nulls_last=True), "id")
    total = qs.count()
    return {
        "items": [task_brief(t) for t in qs[offset : offset + limit]],
        "total": total,
        "limit": limit,
        "offset": offset,
    }


@router.get("/{task_id}", response=TaskOut)
def get_task(request, task_id: int):
    return task_out(task_or_404(request, task_id))


@router.get("/{task_id}/github", response=dict)
def get_task_github(request, task_id: int):
    """GitHub 작업 연결과 동기화된 이슈 본문. GitHub 저장소 권한도 확인한다."""
    task = task_or_404(request, task_id)
    link = TaskGitLink.objects.filter(task=task).select_related("connection").first()
    if link is None:
        return {"linked": False}
    conn = link.connection
    if not can_view_repo(request.auth, conn.full_name):
        raise HttpError(403, "이 GitHub 저장소를 볼 권한이 없습니다.")
    issue = None
    if link.issue_number:
        issue = RepoIssue.objects.filter(connection=conn, number=link.issue_number).first()
    issue_data = None
    if link.issue_number:
        # 캐시 갱신 웹훅이 늦었거나 이슈가 PM에서 막 만들어진 경우도 즉시 읽을 수 있게
        # 연결한 사용자의 GitHub 권한으로 최신 본문을 요청한다. 실패하면 저장된 스냅샷을 쓴다.
        live_issue = None
        try:
            token = user_token(request.auth.github)
            live_issue = github_client.request(
                "GET", f"/repos/{conn.full_name}/issues/{link.issue_number}", token
            )
        except (GitHubError, ServiceError):
            pass
        issue_data = {
            "number": link.issue_number,
            "title": (live_issue or {}).get("title", link.issue_title),
            "state": (live_issue or {}).get("state", link.issue_state),
            "url": f"https://github.com/{conn.full_name}/issues/{link.issue_number}",
            "body": (live_issue or {}).get("body", issue.body if issue else ""),
            "labels": (
                [label["name"] for label in live_issue.get("labels", [])]
                if live_issue
                else (issue.labels if issue else [])
            ),
            "author_login": ((live_issue or {}).get("user") or {}).get(
                "login", issue.author_login if issue else ""
            ),
            "assignee_login": ((live_issue or {}).get("assignee") or {}).get(
                "login", issue.assignee_login if issue else ""
            ),
            "updated_at": (live_issue or {}).get("updated_at") or (
                issue.updated_at if issue else None
            ),
            "source": "github" if live_issue else "cache",
        }
    return {
        "linked": True,
        "repository": conn.full_name,
        "repository_url": conn.url,
        "issue": issue_data,
        "branch": link.branch,
        "pull_request": {
            "number": link.pr_number,
            "title": link.pr_title,
            "state": link.pr_state,
            "url": (
                f"https://github.com/{conn.full_name}/pull/{link.pr_number}"
                if link.pr_number
                else ""
            ),
            "merged_at": link.merged_at,
        }
        if link.pr_number
        else None,
        "commits": link.commits,
    }


@router.get("/{task_id}/history", response=list[ChangeLogOut])
def history(request, task_id: int):
    task = task_or_404(request, task_id)
    logs = ChangeLog.objects.filter(target_type="task", target_id=task.pk).select_related("actor")
    return [changelog_out(log) for log in logs]


@router.post("", response={201: TaskOut, 400: ErrorOut})
def create_task_ep(request, payload: TaskCreateIn):
    project = Project.objects.filter(pk=payload.project_id, org__in=orgs_of(request.auth)).first()
    if project is None:
        raise HttpError(404, "프로젝트를 찾을 수 없습니다.")
    assignee = None
    if payload.assignee_id:
        assignee = User.objects.filter(pk=payload.assignee_id).first()
        if assignee is None:
            raise HttpError(400, "담당자를 찾을 수 없습니다.")
    c = ctx(request)
    task = create_task(
        project=project,
        title=payload.title,
        assignee=assignee,
        description=payload.description,
        done_when=payload.done_when,
        next_action=payload.next_action,
        priority=payload.priority,
        due_date=payload.due_date,
        no_due_reason=payload.no_due_reason,
        idempotency_key=idem_key(request),
        **c,
    )
    if payload.checklist is not None and not task.checklist.exists():
        replace_checklist(task, [i.dict() for i in payload.checklist], actor=c["actor"])
    return 201, task_out(task)


@router.delete("/{task_id}", response={204: None, 400: ErrorOut})
def delete_task_ep(request, task_id: int):
    """조직 관리자만. 체크리스트·링크가 함께 사라진다."""
    task = task_or_404(request, task_id)
    c = ctx(request)
    delete_task(task, actor=c["actor"], source=c["source"])
    return 204, None


@router.patch("/{task_id}", response={200: TaskOut, 400: ErrorOut, 409: ConflictOut})
def patch_task(request, task_id: int, payload: TaskPatchIn):
    task = task_or_404(request, task_id)
    c = ctx(request)
    data = payload.dict(exclude_unset=True)
    version = data.pop("version")
    checklist = data.pop("checklist", None)
    if "assignee_id" in data:
        aid = data.pop("assignee_id")
        data["assignee"] = User.objects.filter(pk=aid).first() if aid else None
    if "project_id" in data:
        pid = data.pop("project_id")
        data["project"] = Project.objects.filter(pk=pid, org__in=orgs_of(request.auth)).first()
        if data["project"] is None:
            raise HttpError(404, "프로젝트를 찾을 수 없습니다.")
    if data:
        task = update_task(task, data, expected_version=version, **c)
    if checklist is not None:
        replace_checklist(task, checklist, actor=c["actor"])
    return task_out(task)


@router.post("/{task_id}/transition", response={200: TaskOut, 400: ErrorOut, 409: ConflictOut})
def transition_ep(request, task_id: int, payload: TransitionIn):
    task = task_or_404(request, task_id)
    task = transition(
        task,
        payload.status,
        reason=payload.reason,
        expected_version=payload.version,
        **ctx(request),
    )
    return task_out(task)


@router.post("/{task_id}/extend", response={200: TaskOut, 400: ErrorOut, 409: ConflictOut})
def extend_ep(request, task_id: int, payload: ExtendIn):
    task = task_or_404(request, task_id)
    task = extend_due(
        task, payload.due_date, payload.reason, expected_version=payload.version, **ctx(request)
    )
    return task_out(task)
