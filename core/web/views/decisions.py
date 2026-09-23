"""Browser views for reviewing task-scoped AI collaboration records."""

from django.contrib import messages
from django.contrib.auth.decorators import login_required
from django.shortcuts import redirect, render
from django.views.decorators.http import require_GET, require_POST

from common.errors import ServiceError
from tasks import decision_services as ds

from .common import task_or_404


def _decision_panel(request, task, *, error=""):
    page, total = ds.list_records(task, actor=request.user, limit=100)
    records = list(page)
    replacing = {record.supersedes_id: record for record in records if record.supersedes_id}
    return render(
        request,
        "tasks/_decisions.html",
        {
            "task": task,
            "decision_records": records,
            "decision_rows": [(record, replacing.get(record.pk)) for record in records],
            "decision_total": total,
            "decision_error": error,
            "decision_actor_id": request.user.pk,
        },
    )


def _service_error(exc):
    return " ".join(exc.errors.values()) or "의사결정 기록을 처리하지 못했습니다."


def _action_response(request, task, *, error="", success=""):
    if request.headers.get("HX-Request"):
        return _decision_panel(request, task, error=error)
    if error:
        messages.error(request, error)
    elif success:
        messages.success(request, success)
    return redirect("task_detail", task_id=task.pk)


@login_required
@require_GET
def task_decisions(request, task_id):
    """Render the HTMX-compatible decision-record section for a visible task."""
    task = task_or_404(request.user, task_id)
    return _decision_panel(request, task)


@login_required
@require_POST
def decision_confirm(request, task_id, record_id):
    task = task_or_404(request.user, task_id)
    try:
        ds.confirm_record(task, record_id, actor=request.user, source="web")
    except ServiceError as exc:
        return _action_response(request, task, error=_service_error(exc))
    return _action_response(request, task, success="의사결정 기록을 확인했습니다.")


@login_required
@require_POST
def decision_reject(request, task_id, record_id):
    task = task_or_404(request.user, task_id)
    try:
        ds.reject_record(
            task,
            record_id,
            actor=request.user,
            source="web",
            reason=request.POST.get("reason", "").strip(),
        )
    except ServiceError as exc:
        return _action_response(request, task, error=_service_error(exc))
    return _action_response(request, task, success="의사결정 기록을 제외했습니다.")


@login_required
@require_POST
def decision_supersede(request, task_id, record_id):
    """Append a correction linked to the prior record; never edit history in place."""
    task = task_or_404(request.user, task_id)
    try:
        ds.create_record(
            task,
            actor=request.user,
            source="web",
            kind="user_input",
            input_type=request.POST.get("input_type", "implementation_instruction").strip(),
            status="captured",
            evidence_basis="explicit_instruction",
            summary=request.POST.get("summary", "").strip(),
            question_summary=request.POST.get("question_summary", "").strip(),
            reason_summary=request.POST.get("reason_summary", "").strip(),
            alternatives=[
                line.strip()
                for line in request.POST.get("alternatives", "").splitlines()
                if line.strip()
            ],
            impact_summary=request.POST.get("impact_summary", "").strip(),
            supersedes_id=record_id,
        )
    except ServiceError as exc:
        return _action_response(request, task, error=_service_error(exc))
    return _action_response(request, task, success="정정 기록을 추가했습니다.")
