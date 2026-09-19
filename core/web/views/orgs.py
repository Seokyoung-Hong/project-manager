from django.conf import settings
from django.contrib import messages
from django.contrib.auth.decorators import login_required
from django.db.models import Count
from django.shortcuts import get_object_or_404, redirect, render
from django.urls import reverse
from django.utils import timezone
from django.views.decorators.http import require_POST

from common.errors import ServiceError
from github import writes as gh_writes
from orgs import services as osv
from orgs.governance import governance_text
from orgs.models import Invite, OrgMembership
from orgs.settings import GROUPS, SPECS, display, effective, enforced, locked_keys, specs_for
from projects.services import project_stats
from reports.services import org_status

from ..forms import InviteForm, OrgForm
from .common import apply_service_error, can_admin, current_org, not_admin, org_or_404


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
    st = org_status(org)
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
    projects = org.projects.prefetch_related("owners", "teams").order_by("name")
    if not include_archived:
        projects = projects.filter(is_archived=False)
    return render(
        request,
        "orgs/detail.html",
        {
            "org": org,
            "tiles": tiles,
            "project_rows": [(p, project_stats(p)) for p in projects],
            "by_assignee": st["by_assignee"],
            "me_url": me_url,
            "include_archived": include_archived,
            "is_admin": can_admin(request.user, org),
            "tab": "overview",
        },
    )


@login_required
def org_teams(request, org_id):
    """조직 → 팀. 멤버·태그·초대·팀을 한 화면에서 관리한다."""
    org = org_or_404(request.user, org_id)
    if denied := not_admin(request, org, "팀·멤버 관리"):
        return denied
    load = {r["assignee_id"]: r for r in org_status(org)["by_assignee"]}
    memberships = list(org.memberships.select_related("user").order_by("user__display_name"))
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
            "member_count": t.members.count(),
            "project_count": t.projects.count(),
            "github": getattr(t, "github", None),
        }
        for t in org.teams.all()
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
    days = form.cleaned_data["days"] if form.is_valid() else 7
    try:
        invite = osv.create_invite(org, request.user, days=days)
        messages.success(request, f"초대 링크: {settings.SITE_URL}{invite.path}")
    except ServiceError as e:
        messages.error(request, " ".join(e.errors.values()))
        return _member_redirect(request, org.pk)
    if settings.GITHUB_ENABLED and form.is_valid() and form.cleaned_data["gh_invite"]:
        login = form.cleaned_data["gh_login"].strip()
        if login:
            warn = gh_writes.try_write(gh_writes.invite_to_org, org, login, actor=request.user)
            if warn:
                messages.warning(request, warn)
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
    if settings.GITHUB_ENABLED and getattr(org, "github", None) is not None:
        login = gh_writes._login_of(user)
        if login:
            warn = gh_writes.try_write(gh_writes.remove_from_org, org, login, actor=request.user)
            if warn:
                messages.warning(request, warn)
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
        },
    )


# ---------- 설정 (IMPL-PLAN-4 §7) ----------


def _settings_from_post(post, specs):
    """체크박스가 꺼진 bool은 폼에 안 실려 오므로 레지스트리를 돌며 False로 채운다."""
    data = {}
    for spec in specs:
        if spec.kind == "bool":
            data[spec.key] = spec.key in post
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
        },
    )
