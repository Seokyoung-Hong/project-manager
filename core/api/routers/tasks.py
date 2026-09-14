from datetime import date

from django.db.models import F
from ninja import Router
from ninja.errors import HttpError

from accounts.models import User
from orgs.services import orgs_of
from projects.models import Project
from tasks.brief import task_brief
from tasks.models import ChangeLog, Task
from tasks.services import (
    create_task,
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


@router.patch("/{task_id}", response={200: TaskOut, 400: ErrorOut, 409: ConflictOut})
def patch_task(request, task_id: int, payload: TaskPatchIn):
    task = task_or_404(request, task_id)
    c = ctx(request)
    data = payload.dict(exclude_unset=True)
    version = data.pop("version")
    reason = data.pop("reason", "")
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
        task = update_task(task, data, expected_version=version, reason=reason, **c)
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
