from datetime import date, timedelta

from django.contrib.auth.decorators import login_required
from django.http import Http404, HttpResponse
from django.shortcuts import get_object_or_404, redirect, render
from django.views.decorators.http import require_POST

from common.dates import today_kst
from common.errors import ConflictError, ServiceError
from github.services import pr_compare_url, repo_state
from github.writes import default_branch_name
from orgs import settings as S
from tasks import services as ts
from tasks.models import ChangeLog, ChecklistItem, Link

from ..forms import LinkForm, TaskForm
from .common import (
    CONFLICT_MSG,
    apply_service_error,
    due_full,
    due_label,
    history_rows,
    project_or_404,
    render_row,
    task_or_404,
    trigger,
    version_of,
)


def _git_ctx(request, task) -> dict:
    """패널 GitHub 블록의 context. repo_state()가 상태를, pr_compare_url()이 PR 열기 링크를 준다."""
    rs = repo_state(request.user, task.project)
    link = getattr(task, "git", None)
    issues = rs["conn"].issues.all()[:50] if rs["state"] == "ok" else []
    return {
        "gh": {
            **rs,
            "link": link,
            "issues": issues,
            "pr_url": pr_compare_url(link) if link and link.branch else None,
            "default_branch_name": default_branch_name(task) if rs["state"] == "ok" else "",
        }
    }


def _panel_ctx(request, task, **extra):
    logs = (
        ChangeLog.objects.filter(target_type="task", target_id=task.pk)
        .select_related("actor")
        .order_by("-created_at", "-id")
    )
    checklist = list(task.checklist.all())
    ctx = {
        "task": task,
        "checklist": checklist,
        "checklist_done": sum(1 for i in checklist if i.is_done),
        "links": task.links.all(),
        "link_form": LinkForm(),
        "notes": task.meeting_notes.all(),
        "org_notes": task.project.org.notes.all(),
        "history": history_rows(logs),
        "priorities": range(10, 0, -1),
        "due_label": due_label(task),
        "due_full": due_full(task),
        "extend_min": task.due_date + timedelta(days=1) if task.due_date else today_kst(),
        "desc_rows": max(2, -(-len(task.description) // 40)),
        "stop_draft": task.stop_reason,
        "block_pending": request.GET.get("block") == "1",
        "focus_notes": request.GET.get("focus") == "notes",
        "full_page": False,
        "error": None,
        "stop_error": None,
        "extend_error": None,
        "extend_open": False,
    }
    ctx.update(_git_ctx(request, task))
    ctx.update(extra)
    return ctx


def _panel(request, task, **extra):
    return render(request, "tasks/_panel.html", _panel_ctx(request, task, **extra))


def _respond(request, task, origin, error=None):
    """origin: 'row'(기본) | 'panel' | 'head'(오늘 화면 지금 할 일 카드) | 'board'."""
    if origin == "panel":
        return _panel(request, task, error=error)
    if origin == "head":
        from .today import head

        return head(request, error=error)
    if origin == "board":
        from .projects import board_context

        ctx = board_context(request, task.project, request.POST.get("include_closed") == "1")
        ctx["error"] = error
        return render(request, "projects/_board.html", ctx)
    return render_row(request, task, error=error)


@login_required
def task_detail(request, task_id):
    task = task_or_404(request.user, task_id)
    return render(request, "tasks/detail.html", _panel_ctx(request, task, full_page=True))


@login_required
def task_panel(request, task_id):
    return _panel(request, task_or_404(request.user, task_id))


@login_required
def task_row(request, task_id):
    return render_row(request, task_or_404(request.user, task_id))


@login_required
def task_edit(request, task_id):
    task = task_or_404(request.user, task_id)
    initial = {
        "project": task.project,
        "title": task.title,
        "assignee": task.assignee,
        "priority": task.priority,
        "due_date": task.due_date,
        "no_due_reason": task.no_due_reason,
        "description": task.description,
        "done_when": task.done_when,
        "next_action": task.next_action,
        "version": task.version,
    }
    reason_required = S.effective(
        "task.assignee_change_reason", project=task.project
    ) or S.effective("task.due_change_reason", project=task.project)
    form = TaskForm(
        request.POST or None, org=task.project.org, initial=initial, reason_required=reason_required
    )
    if request.method == "POST" and form.is_valid():
        d = form.cleaned_data
        changes = {
            k: d[k]
            for k in (
                "project",
                "title",
                "assignee",
                "priority",
                "due_date",
                "no_due_reason",
                "description",
                "done_when",
                "next_action",
            )
        }
        try:
            ts.update_task(
                task,
                changes,
                actor=request.user,
                source="web",
                expected_version=d["version"],
                reason=d.get("reason", ""),
            )
            return redirect("task_detail", task_id=task.pk)
        except ServiceError as e:
            apply_service_error(form, e)
        except ConflictError:
            form.add_error(None, CONFLICT_MSG)
    return render(request, "tasks/edit.html", {"form": form, "task": task})


@login_required
@require_POST
def task_status(request, task_id):
    task = task_or_404(request.user, task_id)
    origin = request.POST.get("from", "row")
    try:
        task = ts.transition(
            task,
            request.POST.get("status", ""),
            actor=request.user,
            source="web",
            reason=request.POST.get("reason", ""),
            expected_version=version_of(request),
        )
    except ServiceError as e:
        return _respond(request, task, origin, error=" ".join(e.errors.values()))
    except ConflictError as e:
        return _respond(request, e.latest, origin, error=CONFLICT_MSG)
    event = "task-changed" if origin == "panel" else "task-updated"
    return trigger(_respond(request, task, origin), event, task)


@login_required
@require_POST
def task_text(request, task_id, field):
    """자동 저장. 성공 204 + HX-Trigger: saved. 실패 400(본문은 메시지)."""
    task = task_or_404(request.user, task_id)
    try:
        ts.update_text(task, field, request.POST.get("value", ""), actor=request.user)
    except ServiceError as e:
        return HttpResponse(" ".join(e.errors.values()), status=400)
    return trigger(HttpResponse(status=204), "saved")


@login_required
@require_POST
def task_priority(request, task_id):
    task = task_or_404(request.user, task_id)
    try:
        priority = int(request.POST.get("priority", "0"))
    except ValueError:
        priority = 0
    try:
        task = ts.update_task(
            task,
            {"priority": priority},
            actor=request.user,
            source="web",
            expected_version=version_of(request),
        )
    except ServiceError as e:
        return _panel(request, task, error=" ".join(e.errors.values()))
    except ConflictError as e:
        return _panel(request, e.latest, error=CONFLICT_MSG)
    return trigger(_panel(request, task), "task-changed", task)


@login_required
@require_POST
def task_extend(request, task_id):
    task = task_or_404(request.user, task_id)
    raw = request.POST.get("due_date", "")
    try:
        new_date = date.fromisoformat(raw) if raw else None
    except ValueError:
        new_date = None
    try:
        task = ts.extend_due(
            task,
            new_date,
            request.POST.get("reason", ""),
            actor=request.user,
            source="web",
            expected_version=version_of(request),
        )
    except ServiceError as e:
        return _panel(request, task, extend_open=True, extend_error=" ".join(e.errors.values()))
    except ConflictError as e:
        return _panel(request, e.latest, error=CONFLICT_MSG)
    return trigger(_panel(request, task), "task-changed", task)


@login_required
@require_POST
def task_stop_reason(request, task_id):
    """confirm_block=1이면 '막힘으로 변경'(transition), 아니면 이미 멈춘 태스크의 사유 저장(update_task)."""
    task = task_or_404(request.user, task_id)
    reason = request.POST.get("reason", "")
    pending = request.POST.get("confirm_block") == "1"
    try:
        if pending:
            task = ts.transition(
                task,
                "blocked",
                actor=request.user,
                source="web",
                reason=reason,
                expected_version=version_of(request),
            )
        else:
            task = ts.update_task(
                task,
                {"stop_reason": reason},
                actor=request.user,
                source="web",
                expected_version=version_of(request),
            )
    except ServiceError as e:
        return _panel(
            request,
            task,
            block_pending=pending,
            stop_draft=reason,
            stop_error=" ".join(e.errors.values()),
        )
    except ConflictError as e:
        return _panel(request, e.latest, error=CONFLICT_MSG)
    return trigger(_panel(request, task), "task-changed", task)


def _checklist(request, task, error=None):
    checklist = list(task.checklist.all())
    return render(
        request,
        "tasks/_checklist.html",
        {
            "task": task,
            "checklist": checklist,
            "checklist_done": sum(1 for i in checklist if i.is_done),
            "error": error,
        },
    )


@login_required
@require_POST
def checklist_add(request, task_id):
    task = task_or_404(request.user, task_id)
    try:
        ts.checklist_add(task, request.POST.get("text", ""), actor=request.user)
    except ServiceError as e:
        return _checklist(request, task, error=" ".join(e.errors.values()))
    return trigger(_checklist(request, task), "task-changed", task)


@login_required
@require_POST
def checklist_action(request, item_id, action):
    item = get_object_or_404(ChecklistItem, pk=item_id)
    task = task_or_404(request.user, item.task_id)
    if action == "toggle":
        ts.checklist_toggle(item, actor=request.user)
    elif action == "delete":
        ts.checklist_delete(item, actor=request.user)
    elif action in ("up", "down"):
        ts.checklist_move(item, action, actor=request.user)
    else:
        raise Http404
    return trigger(_checklist(request, task), "task-changed", task)


def _refs(request, task, error=None):
    return render(
        request,
        "tasks/_refs.html",
        {
            "task": task,
            "links": task.links.all(),
            "link_form": LinkForm(),
            "notes": task.meeting_notes.all(),
            "org_notes": task.project.org.notes.all(),
            "error": error,
            "link_open": bool(error),
        },
    )


@login_required
@require_POST
def link_add(request, task_id):
    task = task_or_404(request.user, task_id)
    form = LinkForm(request.POST)
    if not form.is_valid():
        return _refs(request, task, error="링크 입력이 올바르지 않습니다.")
    d = form.cleaned_data
    try:
        ts.add_link(actor=request.user, task=task, title=d["title"], url=d["url"], kind=d["kind"])
    except ServiceError as e:
        return _refs(request, task, error=" ".join(e.errors.values()))
    return _refs(request, task)


@login_required
@require_POST
def link_delete(request, link_id):
    link = get_object_or_404(Link, pk=link_id)
    if link.task_id:
        task = task_or_404(request.user, link.task_id)
        ts.delete_link(link, actor=request.user)
        return _refs(request, task)
    project_or_404(request.user, link.project_id)
    ts.delete_link(link, actor=request.user)
    return redirect("project_detail", project_id=link.project_id)
