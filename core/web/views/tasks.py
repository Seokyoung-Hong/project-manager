import json
from datetime import date, timedelta

from django.contrib import messages
from django.contrib.auth.decorators import login_required
from django.db.models import Q
from django.http import Http404, HttpResponse, JsonResponse
from django.shortcuts import get_object_or_404, redirect, render
from django.urls import reverse
from django.views.decorators.http import require_POST

from common.dates import today_kst
from common.errors import ConflictError, ServiceError
from github.services import continuation, pr_compare_url, repo_state, sync_issues_if_stale
from github.writes import default_branch_name
from notes.services import visible_notes
from projects.services import visible_projects
from tasks import services as ts
from tasks.attachments import attachments_of
from tasks.models import ChangeLog, ChecklistItem, Link
from tasks.work_requests import pending_assignee

from ..forms import LinkForm
from .common import (
    CONFLICT_MSG,
    can_admin,
    dialog,
    due_class,
    due_full,
    due_label,
    history_rows,
    hx_redirect,
    new_idem,
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
    issues = []
    if rs["state"] == "ok" and not (link and link.issue_number):
        sync_issues_if_stale(rs["conn"])
        issues = rs["conn"].issues.filter(state="open", task__isnull=True)[:50]
    reviews = list(link.review_states.values()) if link else []
    return {
        "gh": {
            **rs,
            "link": link,
            "approved": reviews.count("approved"),
            "changes": reviews.count("changes_requested"),
            **{f"continued_{k}": v for k, v in continuation(task).items()},
            "issues": issues,
            "pr_url": pr_compare_url(link) if link and link.branch else None,
            "default_branch_name": default_branch_name(task) if rs["state"] == "ok" else "",
        },
        # 접힌 GitHub 블록의 한 줄 요약. 펼치지 않아도 연결 상태를 알 수 있어야 한다.
        "gh_summary": _git_summary(rs, link),
    }


def _git_summary(rs, link) -> str:
    if rs["state"] == "none":
        return "저장소 미연결"
    if rs["state"] == "unlinked":
        return "GitHub 계정 미연결"
    if rs["state"] == "denied":
        return "접근 권한 없음"
    if link is None:
        return "이슈·브랜치 없음"
    parts = [f"이슈 #{link.issue_number}" if link.issue_number else "이슈 없음"]
    parts.append(link.branch or "브랜치 없음")
    return " · ".join(parts)


def _panel_ctx(request, task, **extra):
    logs = (
        ChangeLog.objects.filter(target_type="task", target_id=task.pk)
        .select_related("actor")
        .order_by("-created_at", "-id")
    )
    checklist = list(task.checklist.all())
    ctx = {
        "task": task,
        "is_admin": can_admin(request.user, task.project.org),
        "checklist": checklist,
        "checklist_done": sum(1 for i in checklist if i.is_done),
        "links": task.links.all(),
        "link_form": LinkForm(dev_tools=task.project.dev_tools),
        "notes": visible_notes(request.user).filter(tasks=task),
        "org_notes": visible_notes(request.user).filter(org=task.project.org),
        # _refs.html은 패널 최초 렌더(_panel_ctx)와 조각 갱신(_refs) 양쪽에서 쓰인다.
        # 한쪽에만 넣으면 새로고침 전에는 문서가 보이지 않는다.
        "docs": task.docs.filter(kind="doc", project_id=task.project_id),
        "project_docs": task.project.docs.filter(kind="doc", is_template=False).exclude(tasks=task),
        "attachments": attachments_of(task),
        # 패널이 프로젝트·담당자까지 맡으므로 고를 대상을 함께 싣는다
        "org_projects": visible_projects(request.user, task.project.org)
        .filter(is_archived=False)
        .order_by("name"),
        "org_members": task.project.org.members.filter(is_active=True).order_by("display_name"),
        "pending_assignee": pending_assignee(task),
        "history": history_rows(logs),
        "priorities": range(10, 0, -1),
        "due_label": due_label(task),
        "due_class": due_class(task),  # 초과 유예(task.overdue_grace_days)를 본 판정이다
        "due_full": due_full(task),
        "extend_min": task.due_date + timedelta(days=1) if task.due_date else today_kst(),
        "desc_rows": max(2, -(-len(task.description) // 40)),
        "stop_draft": task.stop_reason,
        "block_pending": request.GET.get("block") == "1",
        # 검토자·관리자에게 보이는 "반려" 버튼이 ?reject=1로 사유 상자를 연다.
        "reject_pending": "doing"
        if request.GET.get("reject") == "1" and ts.can_reject(request.user, task)
        else "",
        "can_reject": task.status == "review"
        and request.user.pk != task.assignee_id
        and ts.can_reject(request.user, task),
        "series": _series(request.user, task),
        "focus_notes": request.GET.get("focus") == "notes",
        "full_page": False,
        "error": None,
        "stop_error": None,
        "extend_error": None,
        "extend_open": False,
    }
    if task.project.dev_tools:  # 비개발 프로젝트는 GitHub 조회(repo_state)를 하지 않는다
        ctx.update(_git_ctx(request, task))
    ctx.update(extra)
    return ctx


def _series(user, task) -> list:
    """같은 계열(뿌리 + 회차·변형) 중 user가 볼 수 있는 것. 계열이 없으면 빈 목록.

    회차는 다른(비공개) 프로젝트로 옮겨질 수 있어 뿌리·회차 모두 visible_tasks로 거른다.
    """
    root = task.parent or task
    visible = ts.visible_tasks(user)
    rows = list(visible.filter(Q(pk=root.pk) | Q(parent=root)).order_by("id"))
    return rows if len(rows) > 1 else []


@login_required
def task_duplicate(request, task_id):
    """복제·회차 만들기 대화상자. 같은 끝점이 원본·템플릿·완료된 회차를 모두 받는다."""
    task = task_or_404(request.user, task_id)
    ctx = {
        "task": task,
        "members": task.project.org.members.filter(is_active=True).order_by("display_name"),
        "title": task.title,
        "due_date": "",
        "no_due_reason": "",
        "assignee_id": task.assignee_id,
        "error": None,
    }
    if request.method == "POST":
        p = request.POST
        assignee = task.project.org.members.filter(pk=p.get("assignee") or 0).first()
        try:
            due = date.fromisoformat(p["due_date"]) if p.get("due_date") else None
        except ValueError:
            due = None
        try:
            new = ts.duplicate_task(
                task,
                actor=request.user,
                source="web",
                title=(p.get("title") or "").strip() or None,
                due_date=due,
                no_due_reason=p.get("no_due_reason", ""),
                assignee=assignee,
                idempotency_key=p.get("idem") or None,
            )
        except ServiceError as e:
            ctx.update(
                title=p.get("title", ""),
                due_date=p.get("due_date", ""),
                no_due_reason=p.get("no_due_reason", ""),
                assignee_id=int(p["assignee"]) if (p.get("assignee") or "").isdecimal() else None,
                error=" ".join(e.errors.values()),
            )
        else:
            return hx_redirect(request, reverse("task_detail", args=[new.pk]))
    ctx["idem"] = request.POST.get("idem") or new_idem()
    return dialog(request, "tasks/_duplicate.html", ctx)


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

        ctx = board_context(request, task.project)
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
@require_POST
def task_delete(request, task_id):
    """조직 관리자만(서비스가 검사). 체크리스트·링크가 함께 사라진다. 되돌릴 수 없어 확인을 거친다."""
    task = task_or_404(request.user, task_id)
    try:
        ts.delete_task(task, actor=request.user, source="web")
    except ServiceError as e:
        messages.error(request, " ".join(e.errors.values()))
        return redirect("task_detail", task_id=task.pk)
    messages.success(request, "태스크를 삭제했습니다.")
    return redirect("today")


@login_required
def task_row(request, task_id):
    return render_row(request, task_or_404(request.user, task_id))


@login_required
@require_POST
def task_meta(request, task_id):
    """패널의 프로젝트·담당자·기한 미정 사유 인라인 수정.

    편집 화면(/tasks/{id}/edit)이 하던 일을 패널이 그대로 맡는다. 표면마다 고칠 수 있는
    필드가 다르면 사용자는 "어디서 고쳐야 저장되나"를 학습해야 한다.
    """
    task = task_or_404(request.user, task_id)
    org = task.project.org
    changes = {}
    if (pid := request.POST.get("project")) is not None:
        project = visible_projects(request.user, org).filter(pk=pid or 0, is_archived=False).first()
        if project is None:
            return _panel(request, task, error="그 프로젝트로 옮길 수 없습니다.")
        changes["project"] = project
    if (uid := request.POST.get("assignee")) is not None:
        user = org.members.filter(pk=uid or 0, is_active=True).first()
        if user is None:
            return _panel(request, task, error="그 사람에게 맡길 수 없습니다.")
        changes["assignee"] = user
    if (reason := request.POST.get("no_due_reason")) is not None:
        changes["no_due_reason"] = reason
    if (rid := request.POST.get("reviewer")) is not None:
        reviewer = org.members.filter(pk=rid, is_active=True).first() if rid else None
        if rid and reviewer is None:
            return _panel(request, task, error="그 사람을 검토자로 정할 수 없습니다.")
        changes["reviewer"] = reviewer
    if (tpl := request.POST.get("is_template")) is not None:
        try:
            task = ts.set_template(task, tpl == "1", actor=request.user, source="web")
        except ServiceError as e:
            return _panel(request, task, error=" ".join(e.errors.values()))
        return trigger(_panel(request, task), "task-changed", task)
    if not changes:
        return _panel(request, task)
    try:
        task = ts.update_task(
            task,
            changes,
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
        if origin == "panel" and "reason" in e.errors and task.status == "review":
            # 반려 사유가 필요하다 — 막힘 사유와 같은 입력 상자를 연다(_stop.html).
            return _panel(
                request,
                task,
                reject_pending=request.POST.get("status", ""),
                stop_draft=request.POST.get("reason", ""),
                stop_error=e.errors["reason"],
            )
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
        return JsonResponse(
            {"error": " ".join(e.errors.values())},
            status=400,
            json_dumps_params={"ensure_ascii": False},
        )
    # saved는 "자동 저장됨" 표시, task-changed는 목록·오늘 화면의 행이 새 제목으로 다시 그리게 한다.
    r = HttpResponse(status=204)
    r["HX-Trigger"] = json.dumps({"saved": {}, "task-changed": {"id": task.pk}})
    return r


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


def _refs(request, task, error=None, link_form=None):
    return render(
        request,
        "tasks/_refs.html",
        {
            "task": task,
            "links": task.links.all(),
            "link_form": link_form
            if link_form is not None
            else LinkForm(dev_tools=task.project.dev_tools),
            "notes": visible_notes(request.user).filter(tasks=task),
            "org_notes": visible_notes(request.user).filter(org=task.project.org),
            "docs": task.docs.filter(kind="doc", project_id=task.project_id),
            # 이미 걸린 문서는 후보에서 뺀다 — 같은 것을 두 번 걸 이유가 없다
            "project_docs": task.project.docs.filter(kind="doc", is_template=False).exclude(
                tasks=task
            ),
            "attachments": attachments_of(task),
            "is_admin": can_admin(request.user, task.project.org),
            "error": error,
            "link_open": bool(error),
        },
    )


@login_required
@require_POST
def link_add(request, task_id):
    task = task_or_404(request.user, task_id)
    form = LinkForm(request.POST, dev_tools=task.project.dev_tools)
    if not form.is_valid():
        return _refs(request, task, error="표시된 입력 오류를 고쳐 주세요.", link_form=form)
    d = form.cleaned_data
    try:
        ts.add_link(actor=request.user, task=task, title=d["title"], url=d["url"], kind=d["kind"])
    except ServiceError as e:
        return _refs(request, task, error=" ".join(e.errors.values()), link_form=form)
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
