from datetime import date

from django.contrib import messages
from django.contrib.auth.decorators import login_required
from django.db.models import Case, IntegerField, Value, When
from django.http import Http404
from django.shortcuts import redirect, render
from django.views.decorators.http import require_POST

from common.errors import ServiceError
from orgs.models import Team
from orgs.services import orgs_of
from projects.services import visible_projects
from tasks import work_requests as wr

from .common import current_org, org_or_404

KINDS = [("work", "작업 요청"), ("general", "일반 요청")]


def _pending_first(qs):
    rank = Case(
        When(status="pending", then=Value(0)), default=Value(1), output_field=IntegerField()
    )
    return qs.annotate(open_rank=rank).order_by("open_rank", "-created_at", "-id")


@login_required
def request_index(request):
    tab = "sent" if request.GET.get("tab") == "sent" else "received"
    if tab == "sent":
        qs = wr.visible_requests(request.user).filter(requested_by=request.user)
    else:
        qs = wr.received(request.user)
    return render(request, "requests/index.html", {"tab": tab, "rows": _pending_first(qs)})


@login_required
def request_new(request):
    my_orgs = list(orgs_of(request.user).order_by("name"))
    if not my_orgs:
        raise Http404
    org_id = request.POST.get("org") or request.GET.get("org")
    org = org_or_404(request.user, org_id) if org_id else current_org(request, my_orgs)
    # GET 값은 미리 채우기용이다(팀 화면의 [이 팀에 요청 보내기] → ?team=).
    values = request.POST if request.method == "POST" else request.GET
    errors = {}
    if request.method == "POST":
        team = None
        to_user = None
        if values.get("target") == "team":
            team = org.teams.filter(pk=values.get("team") or 0).first()
        elif values.get("target") == "user":
            to_user = org.members.filter(pk=values.get("user") or 0).first()
        try:
            try:
                due = date.fromisoformat(values["due_date"]) if values.get("due_date") else None
            except ValueError:
                raise ServiceError({"due_date": "기한 형식이 올바르지 않습니다."}) from None
            req = wr.create_request(
                org=org,
                kind=values.get("kind", ""),
                title=values.get("title", ""),
                body=values.get("body", ""),
                actor=request.user,
                source="web",
                team=team,
                to_user=to_user,
                due_date=due,
            )
        except ServiceError as e:
            errors = e.errors
        else:
            messages.success(request, f"{req.number} 요청을 보냈습니다.")
            return redirect(req.path)
    return render(
        request,
        "requests/new.html",
        {
            "org": org,
            "my_orgs": my_orgs,
            "kinds": KINDS,
            "teams": Team.objects.filter(org=org).order_by("name"),
            "people": org.members.filter(is_active=True)
            .exclude(pk=request.user.pk)
            .order_by("display_name"),
            "values": values,
            "errors": errors,
        },
    )


def _req_or_404(request, req_id):
    req = wr.get_visible_request(request.user, req_id)
    if req is None:
        raise Http404
    return req


@login_required
def request_detail(request, req_id):
    req = _req_or_404(request, req_id)
    can_answer = req.is_open and wr.can_respond(request.user, req)
    ctx = {
        "req": req,
        "can_answer": can_answer,
        "can_cancel": req.is_open and req.requested_by_id == request.user.pk,
        "can_complete": req.kind == "general"
        and req.status == "accepted"
        and wr.can_respond(request.user, req),
    }
    if can_answer and req.kind == "work":
        ctx["projects"] = wr.projects_for(req, request.user)
        ctx["assignees"] = (
            req.team.members.filter(is_active=True).order_by("display_name") if req.team_id else []
        )
    return render(request, "requests/detail.html", ctx)


@login_required
@require_POST
def request_act(request, req_id, action):
    if action not in ("accept", "decline", "cancel", "complete"):
        raise Http404
    req = _req_or_404(request, req_id)
    post = request.POST
    note = post.get("note", "")
    try:
        if action == "accept":
            project = (
                visible_projects(request.user, req.org).filter(pk=post.get("project") or 0).first()
            )
            assignee = req.org.members.filter(pk=post.get("assignee") or 0).first()
            try:
                due = date.fromisoformat(post["due_date"]) if post.get("due_date") else None
            except ValueError:
                raise ServiceError({"due_date": "기한 형식이 올바르지 않습니다."}) from None
            wr.accept(
                req,
                request.user,
                source="web",
                project=project,
                assignee=assignee,
                due_date=due,
                note=note,
            )
            messages.success(request, "요청을 수락했습니다.")
        elif action == "decline":
            wr.decline(req, request.user, note)
            messages.success(request, "요청을 거절했습니다.")
        elif action == "cancel":
            wr.cancel(req, request.user)
            messages.success(request, "요청을 취소했습니다.")
        else:
            wr.complete(req, request.user, note)
            messages.success(request, "요청을 완료했습니다.")
    except ServiceError as e:
        messages.error(request, " ".join(e.errors.values()))
    return redirect(req.path)
