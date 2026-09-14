from django.contrib.auth.decorators import login_required
from django.http import Http404
from django.shortcuts import render

from accounts.models import User
from orgs.services import orgs_of
from projects.models import Project
from tasks import services as ts
from tasks.services import today_membership

from .common import project_or_404, row_ctx


@login_required
def me(request):
    g = request.GET
    member, member_id = None, request.user.pk
    raw = g.get("member", "")
    if raw == "0":
        member, member_id = 0, 0
    elif raw.isdecimal() and int(raw) != request.user.pk:
        member = (
            User.objects.filter(
                pk=int(raw), is_active=True, org_memberships__org__in=orgs_of(request.user)
            )
            .distinct()
            .first()
        )
        if member is None:
            raise Http404
        member_id = member.pk
    project = (
        project_or_404(request.user, g["project"]) if g.get("project", "").isdecimal() else None
    )
    # "none"은 눌린 버튼을 다시 눌러 묶음을 푼 상태. 파라미터 없음(첫 방문)과 오타는 기한별
    from orgs import settings as S

    group = g.get("group", S.effective("user.me_group", user=request.user))
    if group != "none" and group not in dict(ts.GROUP_OPTIONS):
        group = "due"
    sort = g.get("sort", S.effective("user.me_sort", user=request.user))
    if sort not in dict(ts.SORT_OPTIONS):
        sort = "due"
    f = {
        "due": g.get("due", ""),
        "project": g.get("project", ""),
        "status": g.get("status", ""),
        "priority": g.get("priority", ""),
    }
    view = ts.me_view(
        request.user,
        member=member,
        group=group,
        sort=sort,
        due=f["due"],
        project=project,
        status=f["status"],
        priority=f["priority"],
    )
    opts = "ro,notoday" if member is not None else "noassignee"
    m = today_membership(request.user)
    for grp in view["groups"]:
        grp["rows"] = [row_ctx(request.user, t, opts, m) for t in grp["tasks"]]
        for p in grp["projects"]:
            p["rows"] = [row_ctx(request.user, t, opts, m) for t in p["tasks"]]
            p["count_label"] = f"완료 {p['done']}/{p['total']}"
    return render(
        request,
        "me.html",
        {
            "view": view,
            "groups": view["groups"],
            "group": group,
            "sort": sort,
            "f": f,
            "has_filter": any(f.values()),
            "member_id": member_id,
            "members": User.objects.filter(
                is_active=True, org_memberships__org__in=orgs_of(request.user)
            )
            .distinct()
            .order_by("display_name"),
            "projects": Project.objects.filter(
                org__in=orgs_of(request.user), is_archived=False
            ).order_by("name"),
            "due_options": ts.DUE_FILTERS,
            "status_options": ts.STATUS_FILTERS,
            "priority_options": ts.PRIORITY_FILTERS,
            "group_options": ts.GROUP_OPTIONS,
            "sort_options": ts.SORT_OPTIONS,
        },
    )
