"""IMPL-PLAN-11 §2: [사람별로 나누기] 대화상자."""

from django.contrib import messages
from django.contrib.auth.decorators import login_required
from django.urls import reverse

from common.errors import ServiceError
from tasks import split as sp

from .common import dialog, hx_redirect, new_idem, task_or_404


@login_required
def task_split(request, task_id):
    task = task_or_404(request.user, task_id)
    members = list(task.project.org.members.filter(is_active=True).order_by("display_name"))
    picked = {u.pk for u in sp.task_split_candidates(task)}
    roles = {}
    pattern = "{title} — {name}"
    error = None
    if request.method == "POST":
        p = request.POST
        picked = {int(i) for i in p.getlist("assignee") if i.isdecimal()}
        roles = {u.pk: p.get(f"role_{u.pk}", "") for u in members}
        pattern = p.get("title_pattern") or pattern
        try:
            made = sp.split_by_assignees(
                task,
                [u for u in members if u.pk in picked],
                actor=request.user,
                source="web",
                roles=roles,
                title_pattern=pattern,
                idempotency_key=p.get("idem") or None,
            )
        except ServiceError as e:
            error = " ".join(e.errors.values())
        else:
            messages.success(request, f"{len(made)}건으로 나눴습니다.")
            return hx_redirect(request, reverse("task_detail", args=[task.pk]))
    rows = [{"user": u, "checked": u.pk in picked, "role": roles.get(u.pk, "")} for u in members]
    ctx = {
        "task": task,
        "rows": rows,
        "pattern": pattern,
        "error": error,
        "idem": request.POST.get("idem") or new_idem(),
    }
    return dialog(request, "tasks/_split.html", ctx)
