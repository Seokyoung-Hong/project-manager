from datetime import date

from django.conf import settings
from django.db.models import F
from django.utils.dateparse import parse_datetime
from ninja import Router
from ninja.errors import HttpError

from accounts.models import User
from common.errors import ConflictError, ServiceError
from github import client as github_client
from github import writes as gh_writes
from github.client import GitHubError
from github.models import RepoIssue, TaskGitLink
from github.services import can_view_repo, continuation, repo_state, user_token
from orgs.services import ai_denied
from orgs.settings import effective
from projects.services import visible_projects
from tasks.brief import task_brief
from tasks.models import ChangeLog, Task
from tasks.services import (
    create_task,
    delete_task,
    duplicate_task,
    extend_due,
    replace_checklist,
    set_template,
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
    TaskDuplicateIn,
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
    include_templates: bool = False,
    parent: int | None = None,
    limit: int = 50,
    offset: int = 0,
):
    qs = visible_tasks(request.auth)
    if not include_templates:
        qs = qs.filter(is_template=False)
    if parent is not None:
        qs = qs.filter(parent_id=parent)
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
    # 검토 독촉이 PR 리뷰 요청 시각을 쓴다. LEFT JOIN 한 번이라 N+1이 없다.
    qs = qs.annotate(review_requested_at=F("git__review_requested_at"))
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
    return task_out(task_or_404(request, task_id), request.auth)


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
            "updated_at": (live_issue or {}).get("updated_at")
            or (issue.updated_at if issue else None),
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
            "draft": link.pr_draft,
            "head_sha": link.head_sha,
            "review_state": link.review_state,
            "reviews": link.review_states,
            "ci_state": link.ci_state,
            "ci_url": link.ci_url,
        }
        if link.pr_number
        else None,
        "commits": link.commits,
        "continued_by": _continued_by(task),
    }


def _continued_by(task):
    """재개(PR·이슈 reopened)로 이 태스크를 이어받은 가장 최근 새 태스크. 없으면 None."""
    new = continuation(task)["by"]
    return {"id": new.pk, "number": new.number, "status": new.status} if new else None


@router.post("/{task_id}/github/issue", response={201: dict, 400: ErrorOut})
def create_task_issue(request, task_id: int):
    """태스크로 GitHub 이슈를 만들고 잇는다. 웹 패널의 '이슈 만들기'와 같은 함수, 같은 조건이다.

    이슈는 호출한 사람의 GitHub 권한으로 만든다. AI는 `ai.create_task`가 막혀 있으면 못 만든다.
    """
    if not settings.GITHUB_ENABLED:
        raise HttpError(404, "GitHub 연동이 꺼져 있습니다.")
    task = task_or_404(request, task_id)
    org = task.project.org
    if ctx(request)["source"] == "mcp" and (
        not effective("ai.enabled", org=org) or effective("ai.create_task", org=org) == "deny"
    ):
        raise ServiceError({"github": ai_denied("GitHub 이슈 생성")})
    state = repo_state(request.auth, task.project)["state"]
    if state != "ok":
        raise ServiceError(
            {
                "github": {
                    "none": "프로젝트에 연결된 저장소가 없습니다.",
                    "unlinked": "GitHub 계정을 먼저 연결해야 합니다.",
                    "denied": "이 저장소에 접근할 권한이 없습니다.",
                }[state]
            }
        )
    if TaskGitLink.objects.filter(task=task).exclude(issue_number=None).exists():
        raise ServiceError({"github": "이미 이슈가 연결된 태스크입니다."})
    try:
        data = gh_writes.create_issue(task, actor=request.auth)
    except GitHubError as e:
        raise HttpError(502, e.message) from e
    full_name = task.project.repo.full_name
    return 201, {
        "number": data["number"],
        "title": data["title"],
        "url": f"https://github.com/{full_name}/issues/{data['number']}",
    }


@router.get("/{task_id}/history", response=list[ChangeLogOut])
def history(request, task_id: int):
    task = task_or_404(request, task_id)
    logs = ChangeLog.objects.filter(target_type="task", target_id=task.pk).select_related("actor")
    return [changelog_out(log) for log in logs]


@router.post("", response={201: TaskOut, 400: ErrorOut})
def create_task_ep(request, payload: TaskCreateIn):
    project = visible_projects(request.auth).filter(pk=payload.project_id).first()
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
        replace_checklist(
            task, [i.dict() for i in payload.checklist], actor=c["actor"], source=c["source"]
        )
    return 201, task_out(task, request.auth)


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
    template = data.pop("is_template", None)
    if "assignee_id" in data:
        aid = data.pop("assignee_id")
        data["assignee"] = User.objects.filter(pk=aid).first() if aid else None
    if "reviewer_id" in data:
        rid = data.pop("reviewer_id")
        data["reviewer"] = User.objects.filter(pk=rid).first() if rid else None
        if rid and data["reviewer"] is None:
            raise HttpError(400, "검토자를 찾을 수 없습니다.")
    if "project_id" in data:
        pid = data.pop("project_id")
        data["project"] = visible_projects(request.auth).filter(pk=pid).first()
        if data["project"] is None:
            raise HttpError(404, "프로젝트를 찾을 수 없습니다.")
    if data:
        task = update_task(task, data, expected_version=version, **c)
    if checklist is not None:
        # 체크리스트만 바꿀 때도 version은 본다. 안 그러면 오래된 화면이 남의 수정을 통째로 덮는다.
        if not data and task.version != version:
            raise ConflictError(task)
        replace_checklist(task, checklist, actor=c["actor"], source=c["source"])
    if template is not None:
        if not data and checklist is None and task.version != version:
            raise ConflictError(task)
        task = set_template(task, template, **c)
    return task_out(task, request.auth)


@router.post("/{task_id}/duplicate", response={201: TaskOut, 400: ErrorOut})
def duplicate_ep(request, task_id: int, payload: TaskDuplicateIn):
    """복제·회차 만들기. 체크리스트(미완료)·링크·문서 연결을 복사하고 계열(parent_id)로 묶는다."""
    task = task_or_404(request, task_id)
    assignee = None
    if payload.assignee_id:
        assignee = User.objects.filter(pk=payload.assignee_id).first()
        if assignee is None:
            raise HttpError(400, "담당자를 찾을 수 없습니다.")
    new = duplicate_task(
        task,
        title=payload.title,
        due_date=payload.due_date,
        no_due_reason=payload.no_due_reason,
        assignee=assignee,
        idempotency_key=idem_key(request),
        **ctx(request),
    )
    return 201, task_out(new, request.auth)


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
    return task_out(task, request.auth)


@router.post("/{task_id}/extend", response={200: TaskOut, 400: ErrorOut, 409: ConflictOut})
def extend_ep(request, task_id: int, payload: ExtendIn):
    task = task_or_404(request, task_id)
    task = extend_due(
        task, payload.due_date, payload.reason, expected_version=payload.version, **ctx(request)
    )
    return task_out(task, request.auth)
