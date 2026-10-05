from datetime import date, timedelta

from django.conf import settings
from django.contrib import messages
from django.contrib.auth.decorators import login_required
from django.db.models import Count
from django.shortcuts import redirect, render
from django.urls import reverse
from django.views.decorators.http import require_POST

from common.dates import today_kst
from common.errors import ConflictError, ServiceError
from github import services as gh_services
from github.client import GitHubError
from orgs.settings import GROUPS, effective, locked_keys, specs_for
from orgs.settings import display as org_display
from projects.models import Project
from projects.services import (
    SPEC_MAX,
    archive_project,
    create_project,
    delete_project,
    fetch_spec,
    is_owner,
    parse_spec,
    project_stats,
    restore_project,
    set_api_spec,
    set_governance_extra,
    set_project_settings,
    set_visibility,
    spec_view,
    update_project,
    visible_projects,
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
    week_days,
)

BOARD_OPEN = ["todo", "doing", "review", "blocked", "paused"]
SHELF_PAGE = 10


def shelf_context(request, project, params=None) -> dict:
    """결과 선반(완료·취소 기록) context. 정확한 전체 건수 + 기간·검색 필터 + 10건씩 더 보기."""
    p = params if params is not None else request.GET
    status = p.get("shelf") if p.get("shelf") in Task.CLOSED else "done"
    period = p.get("period") if p.get("period") in {c for c, _, _ in ts.SHELF_PERIODS} else "all"
    q = (p.get("q") or "").strip()[:100]
    try:
        page = max(1, int(p.get("page", 1)))
    except ValueError:
        page = 1
    totals = dict(
        ts.visible_tasks(request.user)
        .filter(project=project, is_template=False, status__in=Task.CLOSED)
        .order_by()
        .values_list("status")
        .annotate(n=Count("id"))
    )
    qs = ts.closed_tasks(request.user, project, status, period=period, q=q)
    matched = qs.count()
    start = (page - 1) * SHELF_PAGE
    shown = start + SHELF_PAGE
    return {
        "project": project,
        "shelf": status,
        "shelf_label": dict(Task.STATUSES)[status],
        "shelf_totals": [(c, dict(Task.STATUSES)[c], totals.get(c, 0)) for c in Task.CLOSED],
        "shelf_period": period,
        "shelf_periods": ts.SHELF_PERIODS,
        "shelf_q": q,
        "shelf_rows": rows_for(request.user, qs[start:shown], "board"),
        "shelf_matched": matched,
        "shelf_shown": min(shown, matched),
        "shelf_more": max(0, matched - shown),
        "shelf_next": page + 1,
        "shelf_page": page,
    }


def board_context(request, project) -> dict:
    """보드 부분 렌더 context. 보드는 미완료 열만, 완료·취소는 결과 선반이 맡는다."""
    labels = dict(Task.STATUSES)
    base = ts.visible_tasks(request.user).filter(
        project=project, is_template=False, status__in=Task.OPEN
    )
    rows = rows_for(request.user, sorted(base, key=ts.by_due), "board")
    return {
        "project": project,
        "columns": [(c, labels[c], [r for r in rows if r["task"].status == c]) for c in BOARD_OPEN],
        **shelf_context(request, project, {}),
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
        project = visible_projects(request.user, org).filter(pk=pid, is_archived=False).first()
    if project is None:
        project = (
            visible_projects(request.user, org).filter(is_archived=False).order_by("name").first()
        )
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
    # 저장소 입력은 생성 대화상자에서, 내 GitHub 계정이 연결돼 있을 때만 보인다.
    repo_input = (
        project is None
        and settings.GITHUB_ENABLED
        and getattr(request.user, "github", None) is not None
    )
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
            "can_set_visibility": can_admin(request.user, org),
            "visibility_options": Project.VISIBILITIES,
            "visibility_value": form["visibility"].value() or "org",
            "repo_input": repo_input,
            "org_repos": gh_services.installation_repos(org, request.user) if repo_input else [],
        },
    )


@login_required
def project_new(request):
    org = org_or_404(request.user, request.GET.get("org") or request.POST.get("org"))
    form = ProjectForm(
        request.POST or None,
        org=org,
        initial={"dev_tools": effective("project.dev_tools", org=org)},
    )
    if request.method == "POST" and form.is_valid():
        d = form.cleaned_data
        repo_url = d["repo_url"].strip() if settings.GITHUB_ENABLED else ""
        try:
            p = create_project(
                org=org,
                name=d["name"],
                purpose=d["purpose"],
                owners=list(d["owners"]),
                teams=list(d["teams"]),
                status=d["status"],
                # 저장소를 입력했으면 개발 도구를 켠다(저장소가 있으면 끌 수 없다).
                dev_tools=d["dev_tools"] or bool(repo_url),
                visibility=d["visibility"] or "org",
                actor=request.user,
                source="web",
            )
            request.session["org_id"] = org.pk
            if repo_url:
                try:
                    gh_services.connect_repo(
                        project=p,
                        url=repo_url,
                        actor=request.user,
                        source="web",
                        confirm_shared=False,
                    )
                except (ServiceError, GitHubError) as e:
                    # 프로젝트는 이미 만들어졌다. 저장소 탭에서 다시 연결하게 한다.
                    detail = " ".join(e.errors.values()) if isinstance(e, ServiceError) else str(e)
                    messages.warning(
                        request, f"프로젝트를 만들었지만 저장소는 연결하지 못했습니다: {detail}"
                    )
                    return hx_redirect(request, reverse("project_repo", args=[p.pk]))
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
        "visibility": project.visibility,
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
            if d["visibility"] and d["visibility"] != project.visibility:
                set_visibility(project, d["visibility"], actor=request.user, source="web")
            return hx_redirect(request, reverse("project_detail", args=[project.pk]))
        except ServiceError as e:
            apply_service_error(form, e)
        except ConflictError:
            form.add_error(None, CONFLICT_MSG)
    return _dialog(request, form, project.org, project)


def calendar_context(request, project) -> dict:
    """월간 달력. ?month=YYYY-MM. 태스크 기한(완료·취소는 흐리게) + 마일스톤 목표일."""
    raw = request.GET.get("month", "")
    try:
        month = date.fromisoformat(f"{raw}-01") if raw else today_kst().replace(day=1)
    except ValueError:
        month = today_kst().replace(day=1)
    cells = week_days(month)
    last = cells[-1]
    tasks, miles = {}, {}
    for t in project.tasks.filter(due_date__range=(month, last)).select_related("assignee"):
        tasks.setdefault(t.due_date, []).append(t)
    for m in project.milestones.filter(target_date__range=(month, last)):
        miles.setdefault(m.target_date, []).append(m)
    for v in tasks.values():
        v.sort(key=lambda t: (t.status not in Task.OPEN, t.priority, t.pk))
    while len(cells) % 7:
        cells.append(None)
    prev_m = (month - timedelta(days=1)).replace(day=1)
    next_m = (last + timedelta(days=1)).replace(day=1) if last < date.max else month
    this_m = today_kst().replace(day=1)
    return {
        "cal_title": f"{month.year}년 {month.month}월",
        "cal_prev": f"{prev_m:%Y-%m}",
        "cal_next": f"{next_m:%Y-%m}",
        "cal_this": f"{this_m:%Y-%m}" if month != this_m else "",
        "cal_today": today_kst(),
        "open_statuses": Task.OPEN,
        "cal_cells": [
            {"d": d, "tasks": tasks.get(d, []), "miles": miles.get(d, [])} if d else None
            for d in cells
        ],
    }


@login_required
def project_calendar(request, project_id):
    """달력 조각(HTMX 월 이동)."""
    project = project_or_404(request.user, project_id)
    ctx = {"project": project, "view": "calendar", **calendar_context(request, project)}
    return render(request, "projects/calendar.html", ctx)


@login_required
def project_detail(request, project_id, *, link_form=None):
    project = project_or_404(request.user, project_id)
    request.session["org_id"] = project.org_id
    request.session["project_id"] = project.pk
    view = request.GET.get("view")
    if view not in ("list", "board", "calendar"):
        view = effective("project.default_view", org=project.org, project=project)
    include_closed = request.GET.get("include_closed") == "1"
    if request.GET.get("part") == "board":
        return render(request, "projects/_board.html", board_context(request, project))
    if request.GET.get("part") == "shelf":
        # 2쪽부터는 더 보기: 행과 다음 '더 보기'만 이어 붙인다.
        ctx = shelf_context(request, project)
        tpl = "projects/_shelf_page.html" if ctx["shelf_page"] > 1 else "projects/_shelf.html"
        return render(request, tpl, ctx)
    ctx = {
        "project": project,
        "owners": list(project.owners.all()),
        "links": project.links.all(),
        "stats": project_stats(project),
        "view": view,
        "include_closed": include_closed,
        "form_open": request.GET.get("new") == "1",
        "is_admin": can_admin(request.user, project.org),
        "link_form": link_form if link_form is not None else LinkForm(dev_tools=project.dev_tools),
        "link_open": link_form is not None,
        "tab": "tasks",
        "form": TaskInlineForm(
            org=project.org,
            project=project,
            initial={"assignee": request.user.pk, "priority": 5, "idem": new_idem()},
        ),
    }
    # 템플릿은 목록·보드에서 빼고 "템플릿 N" 접이 목록으로만 보인다.
    templates = list(project.tasks.filter(is_template=True).select_related("project", "assignee"))
    ctx["template_rows"] = rows_for(request.user, templates) if templates else []
    if view == "board":
        ctx.update(board_context(request, project))
    elif view == "calendar":
        ctx.update(calendar_context(request, project))
    else:
        qs = project.tasks.filter(is_template=False).select_related("project", "assignee")
        if not include_closed:
            qs = qs.filter(status__in=Task.OPEN)
        ctx["rows"] = rows_for(request.user, sorted(qs, key=ts.by_due))
    return render(request, "projects/detail.html", ctx)


@login_required
@require_POST
def task_create(request, project_id):
    """인라인 태스크 폼. 성공하면 프로젝트 화면으로 돌아가며 #task-{id}로 패널을 연다."""
    project = project_or_404(request.user, project_id)
    form = TaskInlineForm(request.POST, org=project.org, project=project)
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
                done_when=d["done_when"],
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
    cancel_open = request.POST.get("cancel_open") == "1"
    try:
        archive_project(project, actor=request.user, source="web", cancel_open=cancel_open)
        messages.success(
            request,
            "미완료 태스크를 취소하고 프로젝트를 보관했습니다."
            if cancel_open
            else "프로젝트를 보관했습니다.",
        )
    except ServiceError as e:
        msg = e.errors.get("tasks")
        messages.error(
            request,
            f"미완료 태스크가 있어 보관할 수 없습니다: {msg}. "
            f"함께 취소하고 보관하려면 [미완료까지 취소하고 보관]을 쓰세요."
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
def project_delete(request, project_id):
    """조직 관리자만(서비스가 검사). 보관된 프로젝트만 지울 수 있다. 되돌릴 수 없다."""
    project = project_or_404(request.user, project_id)
    try:
        delete_project(project, actor=request.user, source="web")
    except ServiceError as e:
        messages.error(request, " ".join(e.errors.values()))
        return redirect("project_detail", project_id=project.pk)
    messages.success(request, "프로젝트를 삭제했습니다.")
    return redirect("project_index")


@login_required
@require_POST
def link_add(request, project_id):
    project = project_or_404(request.user, project_id)
    form = LinkForm(request.POST, dev_tools=project.dev_tools)
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
            apply_service_error(form, e)
            return project_detail(request, project_id, link_form=form)
    else:
        return project_detail(request, project_id, link_form=form)
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


def _can_edit_project_settings(user, project) -> bool:
    if can_admin(user, project.org):
        return True
    level = effective("project.settings_by", org=project.org)
    if level == "admin":
        return False
    if level == "owner":
        return is_owner(user, project)
    return True


@login_required
def project_settings(request, project_id):
    """프로젝트 설정. 저장소 규칙·거버넌스 추가 문단을 같은 화면에 둔다. IMPL-PLAN-4 §7."""
    from .orgs import _settings_from_post

    project = project_or_404(request.user, project_id)
    editable = _can_edit_project_settings(request.user, project)
    locked = locked_keys(project.org)
    specs = specs_for("project")
    if request.method == "POST" and editable:
        try:
            if request.POST.get("action") == "governance_extra":
                set_governance_extra(
                    project, request.POST.get("governance_extra", ""), actor=request.user
                )
                messages.success(request, "프로젝트 거버넌스를 저장했습니다.")
            else:
                data = _settings_from_post(request.POST, [s for s in specs if s.key not in locked])
                set_project_settings(project, data, actor=request.user, source="web")
                messages.success(request, "프로젝트 설정을 저장했습니다.")
        except ServiceError as e:
            messages.error(request, " ".join(e.errors.values()))
        return redirect("project_settings", project_id=project.pk)
    groups = []
    for code, label in GROUPS:
        rows = [
            {
                "spec": s,
                "value": effective(s.key, org=project.org, project=project),
                "display": org_display(s.key, effective(s.key, org=project.org, project=project)),
                "locked": s.key in locked,
                "can_edit": editable and s.key not in locked,
                "show_override": False,
            }
            for s in specs
            if s.group == code
        ]
        if rows:
            groups.append(("화면 기본값" if code == "project" else label, rows))
    repo_state = None
    if settings.GITHUB_ENABLED:
        from github import services as gh_services

        repo_state = gh_services.repo_state(request.user, project)
    return render(
        request,
        "projects/settings.html",
        {
            "project": project,
            "tab": "settings",
            "editable": editable,
            "is_admin": can_admin(request.user, project.org),
            "groups": groups,
            "governance_extra": project.governance_extra,
            "repo_state": repo_state,
            "open_task_count": project.tasks.filter(status__in=Task.OPEN).count(),
        },
    )
