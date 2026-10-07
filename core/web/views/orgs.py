from django.conf import settings
from django.contrib import messages
from django.contrib.auth.decorators import login_required
from django.db.models import Count, Prefetch
from django.shortcuts import get_object_or_404, redirect, render
from django.urls import reverse
from django.utils import timezone
from django.views.decorators.http import require_POST

from common.errors import ServiceError
from github import services as gh_services
from github import writes as gh_writes
from orgs import requests as creq
from orgs import services as osv
from orgs.governance import governance_text
from orgs.models import ChangeRequest, Invite, OrgMembership, TeamMembership
from orgs.settings import GROUPS, SPECS, display, effective, enforced, locked_keys, specs_for
from projects.services import project_stats_bulk, visible_projects
from reports.services import org_status
from tasks.models import TaskProject

from ..forms import InviteForm, OrgForm
from .common import apply_service_error, can_admin, current_org, not_admin, org_or_404
from .github_retries import attempt


@login_required
def org_current(request):
    org = current_org(request)
    if org is None:
        return redirect("org_list")
    return redirect("org_detail", org_id=org.pk)


@login_required
def org_list(request):
    orgs = list(
        osv.orgs_of(request.user)
        .annotate(project_count=Count("projects", distinct=True))
        .annotate(member_count=Count("memberships", distinct=True))
        .order_by("name")
    )
    if len(orgs) == 1:
        return redirect("org_detail", org_id=orgs[0].pk)
    admin_org_ids = set(
        OrgMembership.objects.filter(user=request.user, role="admin").values_list(
            "org_id", flat=True
        )
    )
    return render(request, "orgs/list.html", {"orgs": orgs, "admin_org_ids": admin_org_ids})


@login_required
def org_new(request):
    form = OrgForm(request.POST or None)
    if request.method == "POST" and form.is_valid():
        d = form.cleaned_data
        try:
            org = osv.create_org(d["name"], d["purpose"], request.user)
            request.session["org_id"] = org.pk
            return redirect("org_detail", org_id=org.pk)
        except ServiceError as e:
            apply_service_error(form, e)
    return render(request, "orgs/new.html", {"form": form})


@login_required
def org_detail(request, org_id):
    """조직 현황. README §3."""
    org = org_or_404(request.user, org_id)
    request.session["org_id"] = org.pk
    include_archived = request.GET.get("include_archived") == "1"
    st = org_status(org, viewer=request.user)
    c = st["counts"]
    me_url = reverse("me")
    tiles = [
        ("미완료", c["open"], f"{me_url}?member=0", False),
        ("진행 중", c["doing"], f"{me_url}?member=0&status=doing", False),
        ("검토 대기", c["review"], f"{me_url}?member=0&status=review", False),
        ("기한 초과", c["overdue"], f"{me_url}?member=0&due=overdue", True),
        ("막힘", c["blocked"], f"{me_url}?member=0&status=blocked", True),
        ("완료", c["done"], f"{me_url}?member=0&status=done_7d", False),
    ]
    projects = (
        visible_projects(request.user, org)
        .select_related("org")
        .prefetch_related("owners", "teams")
        .order_by("name")
    )
    if not include_archived:
        projects = projects.filter(is_archived=False)
    projects = list(projects)
    stats = project_stats_bulk(projects)
    return render(
        request,
        "orgs/detail.html",
        {
            "org": org,
            "tiles": tiles,
            "project_rows": [(p, stats[p.pk]) for p in projects],
            "has_linked": TaskProject.objects.filter(status="active", project__org=org).exists(),
            "by_assignee": st["by_assignee"],
            "me_url": me_url,
            "include_archived": include_archived,
            "is_admin": can_admin(request.user, org),
            "tab": "overview",
        },
    )


def _member_teams(request, org):
    """팀원이 보는 팀 목록. 관리 기능 없이 누가 어느 팀이고 누가 팀장인지만 보여 준다."""
    mine = set(request.user.team_memberships.values_list("team_id", flat=True))
    # 비공개 팀은 이름만 보인다 — 인원·팀장은 볼 수 있는 팀에서만 센다.
    visible = set(osv.visible_teams(request.user, org).values_list("pk", flat=True))
    leads = Prefetch(
        "memberships",
        queryset=TeamMembership.objects.filter(is_lead=True).select_related("user"),
        to_attr="leads",
    )
    rows = [
        {
            "team": t,
            "mine": t.pk in mine,
            "visible": t.pk in visible,
            "member_count": t.member_count if t.pk in visible else None,
            "leads": [m.user for m in t.leads] if t.pk in visible else [],
        }
        for t in org.teams.annotate(member_count=Count("members")).prefetch_related(leads)
    ]
    rows.sort(key=lambda r: (not r["mine"], r["team"].name))
    return render(
        request, "orgs/teams_member.html", {"org": org, "team_rows": rows, "tab": "teams"}
    )


@login_required
def org_teams(request, org_id):
    """조직 → 팀. 멤버·태그·초대·팀을 한 화면에서 관리한다."""
    org = org_or_404(request.user, org_id)
    if not can_admin(request.user, org):
        return _member_teams(request, org)
    load = {r["assignee_id"]: r for r in org_status(org, viewer=request.user)["by_assignee"]}
    memberships = list(
        org.memberships.select_related("user")
        .prefetch_related("user__teams")  # 표의 소속 팀 배지
        .order_by("user__display_name")
    )
    # 마지막 관리자는 services.remove_member가 거부한다 — 버튼도 그 규칙을 그대로 보여 준다
    last_admin = sum(1 for m in memberships if m.role == "admin") <= 1
    rows = [
        {
            "m": m,
            "load": load.get(m.user_id),
            "can_remove": not (m.role == "admin" and last_admin),
        }
        for m in memberships
    ]
    teams = [
        {
            "team": t,
            "member_count": t.member_count,
            "project_count": t.project_count,
            "github": getattr(t, "github", None),
        }
        for t in org.teams.select_related("github").annotate(
            member_count=Count("members", distinct=True),
            project_count=Count("projects", distinct=True),
        )
    ]
    return render(
        request,
        "orgs/teams.html",
        {
            "org": org,
            "rows": rows,
            "admin_count": sum(1 for r in rows if r["m"].role == "admin"),
            "invites": org.invites.filter(revoked_at__isnull=True),
            "form": InviteForm(),
            "site_url": settings.SITE_URL,
            "team_rows": teams,
            "is_admin": True,
            "tab": "teams",
        },
    )


@login_required
@require_POST
def member_tags(request, membership_id):
    membership = get_object_or_404(OrgMembership.objects.select_related("org"), pk=membership_id)
    org_or_404(request.user, membership.org_id)
    tags = (request.POST.get("tags") or "").split(",")
    try:
        osv.set_tags(membership, tags, request.user)
    except ServiceError as e:
        messages.error(request, " ".join(e.errors.values()))
    return _member_redirect(request, membership.org_id)


def _member_redirect(request, org_id):
    # 팀 화면은 관리자 전용이다. 권한 없이 POST한 사람을 여기로 보내면 "관리자만 할 수
    # 있습니다" 메시지가 404 페이지에 묻힌다. 그 사람은 조직 현황으로 보낸다.
    is_admin = OrgMembership.objects.filter(org_id=org_id, user=request.user, role="admin").exists()
    return redirect("org_teams" if is_admin else "org_detail", org_id=org_id)


@login_required
@require_POST
def invite_create(request, org_id):
    org = org_or_404(request.user, org_id)
    form = InviteForm(request.POST)
    if not form.is_valid():
        messages.error(request, "만료 기간은 1~90일로 입력하세요. 초대 링크는 만들지 않았습니다.")
        return _member_redirect(request, org.pk)
    days = form.cleaned_data["days"]
    try:
        invite = osv.create_invite(org, request.user, days=days)
        messages.success(request, f"초대 링크: {settings.SITE_URL}{invite.path}")
    except ServiceError as e:
        messages.error(request, " ".join(e.errors.values()))
        return _member_redirect(request, org.pk)
    # 개인 계정 설치에는 GitHub 조직이 없다. 부르면 404와 쓸모없는 재시도 항목만 남는다.
    if (
        settings.GITHUB_ENABLED
        and form.cleaned_data["gh_invite"]
        and not gh_services.is_user_install(org)
    ):
        login = form.cleaned_data["gh_login"].strip()
        if login:
            warn = attempt(
                request,
                gh_writes.invite_to_org,
                org,
                login,
                actor=request.user,
                retry={
                    "kind": "invite",
                    "org_id": org.pk,
                    "invite_id": invite.pk,
                    "login": login,
                    "target": f"{org.name} · @{login}",
                },
            )
            if warn:
                messages.warning(request, warn, extra_tags="integration-help")
            else:
                messages.success(request, f"GitHub 조직에도 @{login}님을 초대했습니다.")
    return _member_redirect(request, org.pk)


@login_required
@require_POST
def invite_revoke(request, invite_id):
    invite = get_object_or_404(Invite.objects.select_related("org"), pk=invite_id)
    org_or_404(request.user, invite.org_id)
    try:
        osv.revoke_invite(invite, request.user)
    except ServiceError as e:
        messages.error(request, " ".join(e.errors.values()))
    return _member_redirect(request, invite.org_id)


@login_required
@require_POST
def member_role(request, membership_id):
    membership = get_object_or_404(OrgMembership.objects.select_related("org"), pk=membership_id)
    org_or_404(request.user, membership.org_id)
    try:
        osv.change_role(membership, request.POST.get("role", ""), request.user)
    except ServiceError as e:
        messages.error(request, " ".join(e.errors.values()))
    return _member_redirect(request, membership.org_id)


@login_required
@require_POST
def member_remove(request, membership_id):
    membership = get_object_or_404(
        OrgMembership.objects.select_related("org", "user"), pk=membership_id
    )
    org_or_404(request.user, membership.org_id)
    org_id = membership.org_id
    org, user = membership.org, membership.user
    try:
        osv.remove_member(membership, request.user)
    except ServiceError as e:
        messages.error(request, " ".join(e.errors.values()))
        return _member_redirect(request, org_id)
    if (
        settings.GITHUB_ENABLED
        and getattr(org, "github", None) is not None
        and not gh_services.is_user_install(org)
    ):
        login = gh_writes._login_of(user)
        if login:
            warn = attempt(
                request,
                gh_writes.remove_from_org,
                org,
                login,
                actor=request.user,
                retry={
                    "kind": "remove",
                    "org_id": org.pk,
                    "user_id": user.pk,
                    "login": login,
                    "target": f"{org.name} · @{login}",
                },
            )
            if warn:
                messages.warning(request, warn, extra_tags="integration-help")
    return _member_redirect(request, org_id)


@login_required
def org_governance(request, org_id):
    """개발 거버넌스. 멤버는 읽고 관리자는 고친다."""
    org = org_or_404(request.user, org_id)
    is_admin = can_admin(request.user, org)
    error = ""
    if request.method == "POST" and is_admin:
        try:
            osv.set_governance(
                org, "" if request.POST.get("reset") else request.POST["text"], request.user
            )
            messages.success(request, "거버넌스를 저장했습니다.")
            return redirect("org_governance", org_id=org.pk)
        except ServiceError as e:
            error = "; ".join(e.errors.values())
    return render(
        request,
        "orgs/governance.html",
        {
            "org": org,
            "text": governance_text(org),
            "is_default": not org.governance.strip(),
            "is_admin": is_admin,
            "error": error,
            "tab": "governance",
            "enforced_rows": enforced(org),
            "pending_requests": _pending(org, "governance") if is_admin else [],
        },
    )


def _pending(org, kind):
    return list(
        org.change_requests.filter(
            kind=kind, status="pending", expires_at__gt=timezone.now()
        ).select_related("requested_by")
    )


@login_required
def change_request(request, org_id, req_id):
    """AI가 올린 설정·거버넌스 변경 요청을 보고 허용·거절한다. 로그인 세션 전용 — API 토큰으로는 못 온다."""
    org = org_or_404(request.user, org_id)
    if resp := not_admin(request, org, "AI 변경 요청"):
        return resp
    req = get_object_or_404(
        ChangeRequest.objects.select_related("requested_by", "token", "reviewed_by"),
        pk=req_id,
        org=org,
    )
    if request.method == "POST":
        try:
            if request.POST.get("action") == "approve":
                creq.approve(req, request.user)
                messages.success(request, f"{req.get_kind_display()} 변경을 허용해 반영했습니다.")
            elif request.POST.get("action") == "reject":
                creq.reject(req, request.user, request.POST.get("reason", ""))
                messages.success(request, "요청을 거절했습니다.")
        except ServiceError as e:
            messages.error(request, " ".join(e.errors.values()))
        return redirect("change_request", org_id=org.pk, req_id=req.pk)
    return render(
        request,
        "orgs/change_request.html",
        {
            "org": org,
            "is_admin": True,
            "tab": req.kind,
            "req": req,
            "rows": creq.settings_diff(req) if req.kind == "settings" else [],
            "diff": creq.governance_diff(req) if req.kind == "governance" else [],
            "after": creq.governance_after(req) if req.kind == "governance" else "",
        },
    )


# ---------- 설정 (IMPL-PLAN-4 §7) ----------


def _settings_from_post(post, specs):
    """체크박스가 꺼진 bool은 폼에 안 실려 오므로 레지스트리를 돌며 False로 채운다."""
    data = {}
    for spec in specs:
        if spec.kind == "bool":
            data[spec.key] = spec.key in post
        elif spec.kind == "secret":
            # 빈 칸 = 그대로 둔다(merge_secrets). '지우기'를 고르면 False.
            data[spec.key] = (
                False if post.get(f"clear__{spec.key}") == "on" else post.get(spec.key, "")
            )
        elif spec.kind == "set":
            data[spec.key] = post.getlist(spec.key)
        elif spec.key in post:
            data[spec.key] = post[spec.key]
    return data


def _org_settings_history(org):
    from tasks.models import ChangeLog

    extra_labels = {"_locked": "프로젝트가 바꿀 수 있는 항목"}
    logs = (
        ChangeLog.objects.filter(target_type="org", target_id=org.pk)
        .select_related("actor")
        .order_by("-created_at")[:20]
    )
    rows = []
    for log in logs:
        spec = SPECS.get(log.field)
        at = timezone.localtime(log.created_at)
        rows.append(
            {
                "field": spec.label if spec else extra_labels.get(log.field, log.field),
                "from": log.old_value,
                "to": log.new_value,
                "time": f"{at.month}월 {at.day}일 {at:%H:%M}",
                "actor": log.actor.display_name if log.actor else (log.external_actor or "GitHub"),
                "source": log.get_source_display(),
            }
        )
    return rows


@login_required
def org_settings(request, org_id):
    """조직 설정. 관리자가 고치고 멤버는 읽기만 한다 — "왜 진행 중으로 못 바꾸지"의 답이 여기 있다."""
    org = org_or_404(request.user, org_id)
    is_admin = can_admin(request.user, org)
    specs = specs_for("org")
    if request.method == "POST" and is_admin:
        try:
            osv.set_org_settings(org, _settings_from_post(request.POST, specs), request.user)
            unlocked = {
                spec.key
                for spec in specs
                if spec.overridable and request.POST.get(f"unlock__{spec.key}") == "on"
            }
            osv.set_locks(
                org,
                [spec.key for spec in specs if spec.overridable and spec.key not in unlocked],
                request.user,
            )
            messages.success(request, "조직 설정을 저장했습니다.")
        except ServiceError as e:
            messages.error(request, " ".join(e.errors.values()))
        return redirect("org_settings", org_id=org.pk)
    locked = locked_keys(org)
    groups = []
    for code, label in GROUPS:
        rows = [
            {
                "spec": s,
                "value": effective(s.key, org=org),
                "display": display(s.key, effective(s.key, org=org)),
                "unlocked": s.key not in locked,
                "can_edit": is_admin,
                "show_override": is_admin,
            }
            for s in specs
            if s.group == code
        ]
        if rows:
            groups.append((label, rows))
    return render(
        request,
        "orgs/settings.html",
        {
            "org": org,
            "is_admin": is_admin,
            "groups": groups,
            "history": _org_settings_history(org),
            "tab": "settings",
            "pending_requests": _pending(org, "settings") if is_admin else [],
        },
    )
