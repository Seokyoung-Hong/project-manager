from django.contrib import messages
from django.contrib.auth.decorators import login_required
from django.shortcuts import redirect, render
from django.urls import reverse
from django.views.decorators.http import require_POST

from common.errors import ConflictError, ServiceError
from orgs import settings as S
from projects.models import Project
from projects.services import (
    SPEC_MAX,
    archive_project,
    create_project,
    fetch_spec,
    parse_spec,
    project_stats,
    require_level,
    restore_project,
    set_api_spec,
    set_governance_extra,
    set_project_settings,
    spec_view,
    update_project,
)
from tasks import services as ts
from tasks.models import Task

from ..forms import LinkForm, ProjectForm, TaskInlineForm
from .common import (
    CONFLICT_MSG,
    apply_service_error,
    can_admin,
    current_org,
    dialog,
    hx_redirect,
    new_idem,
    org_or_404,
    project_or_404,
    rows_for,
)

BOARD_OPEN = ["todo", "doing", "review", "blocked", "paused"]
# ponytail: 완료 열은 최근 20건만 보여 준다. 전부 보려면 목록 보기의 '완료·취소 포함'을 쓴다.
DONE_ON_BOARD = 20


def board_context(request, project, include_closed: bool) -> dict:
    """보드 부분 렌더 context. 목록 보기와 달리 완료를 항상 실어 온다."""
    labels = dict(Task.STATUSES)
    codes = BOARD_OPEN + ["done"] + (["cancelled"] if include_closed else [])
    base = project.tasks.select_related("project", "assignee")
    open_tasks = sorted(base.filter(status__in=Task.OPEN), key=ts.by_due)
    done_tasks = list(base.filter(status="done").order_by("-completed_at", "-id")[:DONE_ON_BOARD])
    extra = list(base.filter(status="cancelled").order_by("-id")) if include_closed else []
    rows = rows_for(request.user, open_tasks + done_tasks + extra, "board")
    return {
        "project": project,
        "include_closed": include_closed,
        "columns": [(c, labels[c], [r for r in rows if r["task"].status == c]) for c in codes],
    }


@login_required
def project_index(request):
    """헤더의 '프로젝트'. 마지막으로 본 프로젝트 → 조직의 첫 프로젝트 → 빈 화면."""
    org = current_org(request)
    if org is None:
        return redirect("org_list")
    pid = request.session.get("project_id")
    project = None
    if pid:
        project = Project.objects.filter(pk=pid, org=org, is_archived=False).first()
    if project is None:
        project = org.projects.filter(is_archived=False).order_by("name").first()
    if project is None:
        return render(
            request,
            "projects/empty.html",
            {"org": org, "is_admin": can_admin(request.user, org)},
        )
    return redirect("project_detail", project_id=project.pk)


def _checked_ids(form, field: str) -> set[int]:
    """체크된 pk 집합. bound form의 value()는 raw 문자열이라 int()가 터질 수 있다."""
    ids = set()
    for x in form[field].value() or []:
        pk = getattr(x, "pk", x)
        try:
            ids.add(int(pk))
        except (TypeError, ValueError):
            continue
    return ids


def _dialog(request, form, org, project=None):
    """프로젝트 생성·수정 모달 부분 템플릿."""
    return dialog(
        request,
        "projects/_dialog.html",
        {
            "form": form,
            "org": org,
            "project": project,
            "members": org.members.filter(is_active=True).order_by("display_name"),
            "teams": org.teams.order_by("name"),
            "checked_owner_ids": _checked_ids(form, "owners"),
            "checked_team_ids": _checked_ids(form, "teams"),
            "status_options": [
                (code, label, Project.STATUS_DESC[code]) for code, label in Project.STATUSES
            ],
            "status_value": form["status"].value() or "preparing",
        },
    )


@login_required
def project_new(request):
    org = org_or_404(request.user, request.GET.get("org") or request.POST.get("org"))
    form = ProjectForm(request.POST or None, org=org)
    if request.method == "POST" and form.is_valid():
        d = form.cleaned_data
        try:
            p = create_project(
                org=org,
                name=d["name"],
                purpose=d["purpose"],
                owners=list(d["owners"]),
                teams=list(d["teams"]),
                status=d["status"],
                actor=request.user,
                source="web",
            )
            request.session["org_id"] = org.pk
            return hx_redirect(request, reverse("project_detail", args=[p.pk]))
        except ServiceError as e:
            apply_service_error(form, e)
    return _dialog(request, form, org)


@login_required
def project_edit(request, project_id):
    project = project_or_404(request.user, project_id)
    initial = {
        "name": project.name,
        "purpose": project.purpose,
        "status": project.status,
        "owners": list(project.owners.all()),
        "teams": list(project.teams.all()),
        "version": project.version,
    }
    form = ProjectForm(request.POST or None, org=project.org, initial=initial)
    if request.method == "POST" and form.is_valid():
        d = form.cleaned_data
        changes = {
            "name": d["name"],
            "purpose": d["purpose"],
            "owners": list(d["owners"]),
            "teams": list(d["teams"]),
            "status": d["status"],
        }
        try:
            update_project(
                project,
                changes,
                actor=request.user,
                source="web",
                expected_version=d["version"] or 0,
            )
            return hx_redirect(request, reverse("project_detail", args=[project.pk]))
        except ServiceError as e:
            apply_service_error(form, e)
        except ConflictError:
            form.add_error(None, CONFLICT_MSG)
    return _dialog(request, form, project.org, project)


@login_required
def project_detail(request, project_id):
    project = project_or_404(request.user, project_id)
    request.session["org_id"] = project.org_id
    request.session["project_id"] = project.pk
    # 개인 설정 > 프로젝트 설정(조직 덮어쓰기 포함) > 목록. 명시 파라미터가 있으면 그것.
    default_view = (
        "board"
        if S.effective("user.board_default", user=request.user)
        else S.effective("project.default_view", project=project)
    )
    view = "board" if request.GET.get("view", default_view) == "board" else "list"
    include_closed = request.GET.get("include_closed") == "1"
    if request.GET.get("part") == "board":
        return render(
            request, "projects/_board.html", board_context(request, project, include_closed)
        )
    ctx = {
        "project": project,
        "owners": list(project.owners.all()),
        "links": project.links.all(),
        "stats": project_stats(project),
        "view": view,
        "include_closed": include_closed,
        "form_open": request.GET.get("new") == "1",
        "is_admin": can_admin(request.user, project.org),
        "link_form": LinkForm(),
        "tab": "tasks",
        "form": TaskInlineForm(
            org=project.org,
            project=project,
            initial={"assignee": request.user.pk, "idem": new_idem()},
        ),
    }
    if view == "board":
        ctx.update(board_context(request, project, include_closed))
    else:
        qs = project.tasks.select_related("project", "assignee")
        if not include_closed:
            qs = qs.filter(status__in=Task.OPEN)
        ctx["rows"] = rows_for(request.user, sorted(qs, key=ts.by_due))
    return render(request, "projects/detail.html", ctx)


@login_required
@require_POST
def task_create(request, project_id):
    """인라인 태스크 폼. 성공하면 프로젝트 화면으로 돌아가며 #task-{id}로 패널을 연다."""
    project = project_or_404(request.user, project_id)
    form = TaskInlineForm(request.POST, org=project.org)
    if form.is_valid():
        d = form.cleaned_data
        try:
            task = ts.create_task(
                project=project,
                title=d["title"],
                actor=request.user,
                source="web",
                assignee=d["assignee"],
                priority=d["priority"],
                due_date=d["due_date"],
                no_due_reason=d["no_due_reason"],
                idempotency_key=d["idem"] or None,
            )
            return hx_redirect(
                request, reverse("project_detail", args=[project.pk]) + f"#task-{task.pk}"
            )
        except ServiceError as e:
            apply_service_error(form, e)
    return render(
        request,
        "projects/_task_form.html",
        {"form": form, "project": project, "form_open": True},
    )


@login_required
@require_POST
def project_archive(request, project_id):
    project = project_or_404(request.user, project_id)
    try:
        archive_project(project, actor=request.user, source="web")
        messages.success(request, "프로젝트를 보관했습니다.")
    except ServiceError as e:
        msg = e.errors.get("tasks")
        messages.error(
            request,
            f"미완료 태스크가 있어 보관할 수 없습니다: {msg}"
            if msg
            else " ".join(e.errors.values()),
        )
    return redirect("project_detail", project_id=project.pk)


@login_required
@require_POST
def project_restore(request, project_id):
    project = project_or_404(request.user, project_id)
    try:
        restore_project(project, actor=request.user, source="web")
    except ServiceError as e:
        messages.error(request, " ".join(e.errors.values()))
    return redirect("project_detail", project_id=project.pk)


@login_required
@require_POST
def link_add(request, project_id):
    project = project_or_404(request.user, project_id)
    form = LinkForm(request.POST)
    if form.is_valid():
        d = form.cleaned_data
        try:
            ts.add_link(
                actor=request.user,
                project=project,
                title=d["title"],
                url=d["url"],
                kind=d["kind"],
            )
        except ServiceError as e:
            messages.error(request, " ".join(e.errors.values()))
    else:
        messages.error(request, "링크 입력이 올바르지 않습니다.")
    return redirect("project_detail", project_id=project.pk)


@login_required
def project_api(request, project_id):
    project = project_or_404(request.user, project_id)
    error = None
    if request.method == "POST":
        try:
            upload = request.FILES.get("file")
            if upload:
                if not upload.name.lower().endswith(".json"):
                    raise ServiceError({"spec": ".json 파일만 올릴 수 있습니다."})
                spec = parse_spec(upload.read(SPEC_MAX + 1), source=upload.name)
                source = upload.name
            else:
                source = request.POST.get("url", "")
                spec = fetch_spec(source)
            set_api_spec(project, spec, source_url=source, actor=request.user)
            return redirect("project_api", project_id=project.pk)
        except ServiceError as e:
            error = " ".join(e.errors.values())

    obj = getattr(project, "api_spec", None)
    q = request.GET.get("q", "")
    ctx = {
        "project": project,
        "tab": "api",
        "q": q,
        "error": error,
        "spec_obj": obj,
        "api": spec_view(obj.spec, q) if obj else None,
    }
    if request.GET.get("part") == "endpoints":
        return render(request, "projects/_endpoints.html", ctx)
    return render(request, "projects/api.html", ctx)


def _can_edit_settings(user, project) -> bool:
    try:
        require_level(
            user, project, S.effective("project.settings_by", org=project.org), "settings"
        )
        return True
    except ServiceError:
        return False


@login_required
def project_settings(request, project_id):
    """프로젝트 설정. 조직이 덮어쓰기를 허락한 항목만 여기서 고친다(§7.2)."""
    from tasks.models import ChangeLog

    from .orgs import _settings_form

    project = project_or_404(request.user, project_id)
    can_edit = _can_edit_settings(request.user, project)
    errors = {}
    if request.method == "POST" and can_edit:
        raw = _settings_form(request.POST, "org", overridable_only=True)
        data = {k: v for k, v in raw.items() if request.POST.get(f"use:{k}") == "own"}
        try:
            set_project_settings(project, data, actor=request.user)
            set_governance_extra(
                project, request.POST.get("governance_extra", ""), actor=request.user
            )
            messages.success(request, "설정을 저장했습니다.")
            return redirect("project_settings", project_id=project.pk)
        except ServiceError as e:
            errors = e.errors
    locked = S.locked_keys(project.org)
    groups = []
    for code, label in S.GROUPS:
        items = []
        for spec in S.specs("org", code):
            if not spec.overridable:
                continue
            org_val = S.effective(spec.key, org=project.org)
            own = spec.key in project.settings
            items.append(
                {
                    "spec": spec,
                    "org_text": S.display(spec, org_val),
                    "own": own,
                    "value": project.settings.get(spec.key, org_val),
                    "locked": spec.key in locked,
                }
            )
        if items:
            groups.append({"code": code, "label": label, "items": items})
    history = (
        ChangeLog.objects.filter(
            target_type="project", target_id=project.pk, field__in=S.SPECS.keys()
        )
        .select_related("actor")
        .order_by("-created_at")[:10]
    )
    return render(
        request,
        "projects/settings.html",
        {
            "project": project,
            "groups": groups,
            "labels": {k: s.label for k, s in S.SPECS.items()},
            "history": history,
            "can_edit": can_edit,
            "errors": errors,
            "governance_extra": project.governance_extra,
            "tab": "settings",
        },
    )
