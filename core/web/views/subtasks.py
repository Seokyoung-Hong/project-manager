"""상위·하위 태스크 화면(IMPL-PLAN-12 §5.2). 규칙은 tasks.services에 있고 여기는 부르기만 한다.

패널 구역(tasks/_subtasks.html)은 HTMX로 패널 전체를 다시 그린다(tasks/_projects.html과 같은 방식).
"""

from datetime import date

from django.contrib.auth.decorators import login_required
from django.db.models import Exists, OuterRef
from django.views.decorators.http import require_POST

from common.errors import ConflictError, ServiceError
from orgs.settings import effective
from tasks import services as ts
from tasks.models import Task

from .common import CONFLICT_MSG, task_or_404, trigger, version_of


def panel_ctx(user, task) -> dict:
    """_panel_ctx가 합치는 상위·하위 칸 context. 템플릿은 상위·하위가 될 수 없으므로 비운다."""
    if task.is_template:
        return {"sub": None}
    view = ts.subtask_view(user, task)
    view["can_add"] = task.is_open and not task.group_id
    view["show"] = not task.group_id and (
        view["total"] or view["subtasks"] or view["hidden"] or view["can_add"]
    )
    view["due_warn"] = ts.due_after_group(task) and view["group"] is not None
    if view["can_add"]:
        view["candidates"] = (
            ts.visible_tasks(user)  # 연결 열람자에게 주 프로젝트의 못 보는 태스크를 내지 않는다(S1)
            .filter(
                project_id=task.project_id,
                status__in=Task.OPEN,
                is_template=False,
                group__isnull=True,
            )
            .exclude(pk=task.pk)
            .exclude(Exists(Task.objects.filter(group_id=OuterRef("pk"))))
            .order_by("title")[:50]
        )
        view["need_done_when"] = effective(
            "task.require_done_when", org=task.project.org, project=task.project
        )
    return {"sub": view}


def _panel(request, task, **extra):
    from .tasks import _panel as render_panel

    task.refresh_from_db()
    return trigger(render_panel(request, task, **extra), "task-changed", task)


def _error(e) -> str:
    return " ".join(e.errors.values())


@login_required
@require_POST
def create(request, task_id):
    """상위 패널의 '하위 만들기'. 담당자 기본값은 상위 담당자(폼이 미리 고른다)."""
    group = task_or_404(request.user, task_id)
    p = request.POST
    assignee = group.project.org.members.filter(pk=p.get("assignee") or 0, is_active=True).first()
    try:
        due = date.fromisoformat(p["due_date"]) if p.get("due_date") else None
    except ValueError:
        due = None
    try:
        ts.create_task(
            project=group.project,
            group=group,
            title=p.get("title", ""),
            actor=request.user,
            source="web",
            assignee=assignee,
            due_date=due,
            no_due_reason="" if due else "기한 미정",
            done_when=p.get("done_when", ""),
        )
    except ServiceError as e:
        return _panel(request, group, error=_error(e))
    return _panel(request, group, sub_msg="하위 태스크를 만들었습니다.")


@login_required
@require_POST
def put(request, task_id):
    """기존 태스크 넣기 — 고른 태스크를 이 태스크의 하위로."""
    group = task_or_404(request.user, task_id)
    child = ts.get_visible_task(request.user, int(request.POST.get("task") or 0))
    if child is None:
        return _panel(request, group, error="그 태스크를 넣을 수 없습니다.")
    try:
        ts.set_group(child, group, actor=request.user, expected_version=child.version)
    except ServiceError as e:
        return _panel(request, group, error=_error(e))
    except ConflictError:
        return _panel(request, group, error=CONFLICT_MSG)
    return _panel(request, group, sub_msg=f"{child.number}을 하위로 넣었습니다.")


@login_required
@require_POST
def ungroup(request, task_id):
    """떼어내기. 하위 패널과 상위 패널 양쪽에서 부른다 — 응답은 'back'이 가리키는 패널."""
    task = task_or_404(request.user, task_id)
    back = task_or_404(request.user, int(request.POST.get("back") or task.pk))
    try:
        ts.set_group(task, None, actor=request.user, expected_version=version_of(request))
    except ServiceError as e:
        return _panel(request, back, error=_error(e))
    except ConflictError:
        return _panel(request, back, error=CONFLICT_MSG)
    return _panel(request, back, sub_msg="떼어냈습니다.")
