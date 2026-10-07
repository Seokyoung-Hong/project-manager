"""태스크 연결 프로젝트 화면(IMPL-PLAN-11 §3.4·3.6, 결정 2-1). 규칙은 tasks.services에 있고 여기는 부르기만 한다.

패널 구역(tasks/_projects.html)은 HTMX로 패널 전체를 다시 그리고, 요청함의 승인 대기 탭은 일반 폼 POST 뒤
그 탭으로 돌아간다.
"""

from django.contrib import messages
from django.contrib.auth.decorators import login_required
from django.http import Http404
from django.shortcuts import redirect
from django.urls import reverse
from django.views.decorators.http import require_POST

from common.errors import ServiceError
from projects.services import visible_projects
from tasks import services as ts
from tasks.models import TaskProject

from .common import task_or_404


def panel_ctx(user, task) -> dict:
    """_panel_ctx가 합치는 연결 칸 context."""
    linked = ts.linked_projects(task, user)
    taken = {
        task.project_id,
        *(TaskProject.objects.filter(task=task).values_list("project_id", flat=True)),
    }
    choices = (
        visible_projects(user, task.project.org)
        .filter(is_archived=False)
        .exclude(pk__in=taken)
        .order_by("name")
    )
    return {
        "linked_projects": linked,
        "has_active_links": any(lp["status"] == "active" for lp in linked),
        "can_approve_links": ts.can_approve_widening(user, task),
        "link_choices": choices,
    }


def _panel(request, task, **extra):
    from .tasks import _panel as render_panel

    return render_panel(request, task, **extra)


def _approvers_text(task) -> str:
    if task.project.visibility != "org":
        return f"'{task.project.name}' 프로젝트 관리자 또는 조직 관리자"
    return "조직 관리자"


@login_required
@require_POST
def link(request, task_id):
    task = task_or_404(request.user, task_id)
    project = (
        visible_projects(request.user, task.project.org)
        .filter(pk=request.POST.get("project") or 0)
        .first()
    )
    if project is None:
        return _panel(request, task, error="그 프로젝트에 연결할 수 없습니다.")
    try:
        ts.link_project(
            task,
            project,
            actor=request.user,
            source="web",
            confirm_widening=request.POST.get("confirm") == "1",
        )
    except ts.WideningRequired as e:
        # 경고 문구 + 승인 요청 버튼을 같은 칸에 띄운다. 아직 아무것도 만들지 않았다.
        widening = {
            "message": e.errors["confirm"],
            "project_id": project.pk,
            "approvers": _approvers_text(task),
        }
        return _panel(request, task, widening=widening)
    except ServiceError as e:
        return _panel(request, task, error=" ".join(e.errors.values()))
    task.refresh_from_db()
    return _panel(request, task)


@login_required
@require_POST
def unlink(request, task_id, project_id):
    task = task_or_404(request.user, task_id)
    project = visible_projects(request.user, task.project.org).filter(pk=project_id).first()
    if project is None:
        raise Http404
    try:
        task = ts.unlink_project(task, project, actor=request.user, source="web")
    except ServiceError as e:
        return _panel(request, task, error=" ".join(e.errors.values()))
    return _panel(request, task)


def _decide(request, task_id, project_id, approve: bool):
    task = task_or_404(request.user, task_id)
    link = (
        TaskProject.objects.filter(task=task, project_id=project_id)
        .select_related("project", "created_by", "task__project__org")
        .first()
    )
    if link is None:
        raise Http404
    try:
        if approve:
            ts.approve_link(link, actor=request.user, source="web")
        else:
            ts.reject_link(
                link, actor=request.user, source="web", reason=request.POST.get("reason", "")
            )
        error = None
    except ServiceError as e:
        error = " ".join(e.errors.values())
    if request.headers.get("HX-Request"):
        task.refresh_from_db()
        return _panel(request, task, error=error)
    if error:
        messages.error(request, error)
    else:
        messages.success(
            request,
            f"{task.number}의 '{link.project.name}' 연결을 {'승인' if approve else '거절'}했습니다.",
        )
    return redirect(reverse("request_index") + "?tab=links")


@login_required
@require_POST
def approve(request, task_id, project_id):
    return _decide(request, task_id, project_id, True)


@login_required
@require_POST
def reject(request, task_id, project_id):
    return _decide(request, task_id, project_id, False)
