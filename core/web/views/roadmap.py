from datetime import date

from django.contrib import messages
from django.contrib.auth.decorators import login_required
from django.shortcuts import get_object_or_404, redirect, render
from django.urls import reverse
from django.views.decorators.http import require_POST

from common.errors import ServiceError
from github import writes
from orgs import services as osv
from projects.models import Milestone, ProjectDependency
from projects.services import (
    create_dependency,
    create_milestone,
    delete_dependency,
    delete_milestone,
    update_milestone,
    visible_projects,
)
from projects.services import (
    roadmap as roadmap_data,
)
from reports.services import org_status

from .common import can_admin, dialog, hx_redirect, org_or_404, project_or_404


@login_required
def capacity(request, org_id):
    org = org_or_404(request.user, org_id)
    st = org_status(org, viewer=request.user)
    c = st["counts"]
    rows = st["capacity"]

    team_id = request.GET.get("team", "")
    if team_id.isdecimal():
        rows = [r for r in rows if any(t["id"] == int(team_id) for t in r["teams"])]

    picked = [t.strip() for t in request.GET.get("tags", "").split(",") if t.strip()]
    all_tags = sorted({t for r in st["capacity"] for t in r["tags"]})
    # 고른 태그를 "전부" 가진 사람이 후보다. 하나라도 가진 사람이 아니다.
    candidates = [r for r in st["capacity"] if set(picked) <= set(r["tags"])] if picked else []

    return render(
        request,
        "orgs/capacity.html",
        {
            "org": org,
            "tab": "capacity",
            "is_admin": can_admin(request.user, org),
            "tiles": [
                ("진행 중", c["doing"], False),
                ("검토 대기", c["review"], False),
                ("막힘", c["blocked"], True),
                ("기한 초과", c["overdue"], True),
                ("1인 평균 진행", c["avg_doing"], False),
            ],
            "rows": rows,
            "teams": osv.visible_teams(request.user, org),
            "team_id": team_id,
            "all_tags": all_tags,
            "picked": picked,
            "candidates": candidates,
            "me_url": reverse("me"),
        },
    )


@login_required
def roadmap(request, org_id):
    org = org_or_404(request.user, org_id)
    data = roadmap_data(org, viewer=request.user)
    return render(
        request,
        "orgs/roadmap.html",
        {
            "org": org,
            "tab": "roadmap",
            "is_admin": can_admin(request.user, org),
            "months": data["months"],
            "today_pct": data["today_pct"],
            "rows": data["rows"],
            "deps": data["deps"],
            "hidden": data["hidden"],
            "projects": visible_projects(request.user, org)
            .filter(is_archived=False)
            .order_by("name"),
        },
    )


def _parse_date(raw: str) -> date | None:
    try:
        return date.fromisoformat(raw) if raw else None
    except ValueError:
        return None


def _push_to_github(request, ms):
    """대화상자의 "GitHub에도 반영" 체크(§3.9). 저장소가 있고 누른 사람이 GitHub를 연결했을 때만.
    PM 저장은 이미 끝났다 — GitHub 실패는 경고로만 보여 준다."""
    if request.POST.get("github") != "on":
        return
    if getattr(ms.project, "repo", None) is None or getattr(request.user, "github", None) is None:
        return
    fn = writes.update_gh_milestone if ms.gh_number else writes.create_gh_milestone
    warning = writes.try_write(fn, ms, actor=request.user)
    if warning:
        messages.warning(request, warning)


def _milestone_dialog(request, org, ms=None, errors=None):
    if request.method == "POST":
        values = {
            "project": request.POST.get("project", ""),
            "name": request.POST.get("name", ""),
            "start_date": request.POST.get("start_date", ""),
            "target_date": request.POST.get("target_date", ""),
            "status": request.POST.get("status", "planned"),
        }
    elif ms:
        values = {
            "project": str(ms.project_id),
            "name": ms.name,
            "start_date": ms.start_date.isoformat() if ms.start_date else "",
            "target_date": ms.target_date.isoformat(),
            "status": ms.status,
        }
    else:
        values = {
            "project": "",
            "name": "",
            "start_date": "",
            "target_date": "",
            "status": "planned",
        }
    return dialog(
        request,
        "orgs/_milestone_dialog.html",
        {
            "org": org,
            "ms": ms,
            "projects": visible_projects(request.user, org)
            .filter(is_archived=False)
            .order_by("name"),
            "statuses": Milestone.STATUSES,
            "values": values,
            "errors": errors or {},
        },
    )


@login_required
def milestone_new(request, org_id):
    org = org_or_404(request.user, org_id)
    if request.method == "POST":
        project = get_object_or_404(
            visible_projects(request.user, org), pk=request.POST.get("project") or 0
        )
        try:
            ms = create_milestone(
                project=project,
                name=request.POST.get("name", ""),
                target_date=_parse_date(request.POST.get("target_date", "")),
                start_date=_parse_date(request.POST.get("start_date", "")),
                status=request.POST.get("status", "planned"),
                actor=request.user,
            )
            _push_to_github(request, ms)
            # 대화상자는 hx-target="#dialog"다. 302를 돌려주면 로드맵 전체가 대화상자 안에 끼워진다.
            return hx_redirect(request, reverse("org_roadmap", args=[org.pk]))
        except ServiceError as e:
            return _milestone_dialog(request, org, errors=e.errors)
    return _milestone_dialog(request, org)


@login_required
def milestone_edit(request, milestone_id):
    ms = get_object_or_404(Milestone.objects.select_related("project__org"), pk=milestone_id)
    org = org_or_404(request.user, ms.project.org_id)
    project_or_404(request.user, ms.project_id)
    if request.method == "POST":
        try:
            update_milestone(
                ms,
                {
                    "name": request.POST.get("name", ""),
                    "target_date": _parse_date(request.POST.get("target_date", "")),
                    "start_date": _parse_date(request.POST.get("start_date", "")),
                    "status": request.POST.get("status", "planned"),
                },
                actor=request.user,
            )
            _push_to_github(request, ms)
            return hx_redirect(request, reverse("org_roadmap", args=[org.pk]))
        except ServiceError as e:
            return _milestone_dialog(request, org, ms=ms, errors=e.errors)
    return _milestone_dialog(request, org, ms=ms)


@login_required
@require_POST
def milestone_delete(request, milestone_id):
    ms = get_object_or_404(Milestone.objects.select_related("project__org"), pk=milestone_id)
    org_id = ms.project.org_id
    project_or_404(request.user, ms.project_id)
    delete_milestone(ms, request.user)
    return hx_redirect(request, reverse("org_roadmap", args=[org_id]))


@login_required
@require_POST
def dependency_add(request, org_id):
    org = org_or_404(request.user, org_id)
    from_project = get_object_or_404(
        visible_projects(request.user, org), pk=request.POST.get("from_project") or 0
    )
    to_project = get_object_or_404(
        visible_projects(request.user, org), pk=request.POST.get("to_project") or 0
    )
    try:
        create_dependency(
            from_project=from_project,
            to_project=to_project,
            actor=request.user,
            note=request.POST.get("note", ""),
            is_blocking=request.POST.get("is_blocking") == "on",
        )
    except ServiceError as e:
        messages.error(request, " ".join(e.errors.values()))
    return redirect("org_roadmap", org_id=org.pk)


@login_required
@require_POST
def dependency_delete(request, dependency_id):
    dep = get_object_or_404(
        ProjectDependency.objects.select_related("from_project__org"), pk=dependency_id
    )
    org_id = dep.from_project.org_id
    project_or_404(request.user, dep.from_project_id)
    project_or_404(request.user, dep.to_project_id)
    delete_dependency(dep, request.user)
    return redirect("org_roadmap", org_id=org_id)
