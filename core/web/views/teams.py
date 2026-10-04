from django.conf import settings
from django.contrib import messages
from django.contrib.auth.decorators import login_required
from django.http import Http404
from django.shortcuts import get_object_or_404, redirect, render
from django.urls import reverse
from django.views.decorators.http import require_POST

from common.errors import ServiceError
from github import writes as gh_writes
from github.client import GitHubError
from github.models import GitHubTeamLink
from orgs import services as osv
from orgs.models import Team

from ..forms import TeamForm
from .common import can_admin, dialog, hx_redirect, not_admin, org_or_404


def _team_or_404(request, team_id):
    team = get_object_or_404(Team.objects.select_related("org"), pk=team_id)
    org_or_404(request.user, team.org_id)
    return team


def _admin_team_or_404(request, team_id):
    team = _team_or_404(request, team_id)
    if not can_admin(request.user, team.org):
        raise Http404
    return team


def _apply_errors(form, exc: ServiceError):
    for field, msg in exc.errors.items():
        form.add_error(field if field in form.fields else None, msg)


def _dialog(request, form, org, team=None):
    return dialog(request, "orgs/_team_dialog.html", {"form": form, "org": org, "team": team})


@login_required
def team_new(request, org_id):
    org = org_or_404(request.user, org_id)
    if denied := not_admin(request, org, "팀 관리"):
        return denied
    form = TeamForm(request.POST or None)
    if request.method == "POST" and form.is_valid():
        d = form.cleaned_data
        try:
            osv.create_team(org=org, name=d["name"], purpose=d["purpose"], actor=request.user)
            return hx_redirect(request, reverse("org_teams", args=[org.pk]))
        except ServiceError as e:
            _apply_errors(form, e)
    return _dialog(request, form, org)


@login_required
def team_edit(request, team_id):
    team = _team_or_404(request, team_id)
    if denied := not_admin(request, team.org, "팀 관리"):
        return denied
    form = TeamForm(request.POST or None, initial={"name": team.name, "purpose": team.purpose})
    if request.method == "POST" and form.is_valid():
        d = form.cleaned_data
        try:
            osv.update_team(team, name=d["name"], purpose=d["purpose"], actor=request.user)
        except ServiceError as e:
            _apply_errors(form, e)
            return _dialog(request, form, team.org, team)
        link = getattr(team, "github", None)
        if settings.GITHUB_ENABLED and link is not None:
            warn = gh_writes.try_write(gh_writes.rename_gh_team, link, team, actor=request.user)
            if warn:
                messages.warning(request, warn)
        return hx_redirect(request, reverse("team_detail", args=[team.pk]))
    return _dialog(request, form, team.org, team)


@login_required
@require_POST
def team_delete(request, team_id):
    team = _admin_team_or_404(request, team_id)
    org_id = team.org_id
    try:
        osv.delete_team(team, actor=request.user, source="web")
    except ServiceError as e:
        messages.error(request, " ".join(e.errors.values()))
    return redirect("org_teams", org_id=org_id)


@login_required
def team_detail(request, team_id):
    team = _team_or_404(request, team_id)
    if denied := not_admin(request, team.org, "팀 관리"):
        return denied
    members = team.members.order_by("display_name")
    candidates = (
        team.org.members.filter(is_active=True)
        .exclude(pk__in=members.values("pk"))
        .order_by("display_name")
    )
    gh_link = getattr(team, "github", None)
    gh_install = getattr(team.org, "github", None)
    gh_teams = []
    if settings.GITHUB_ENABLED and gh_install is not None and gh_link is None:
        try:
            gh_teams = gh_writes.list_org_teams(team.org, actor=request.user)
        except (ServiceError, GitHubError):
            gh_teams = []
    return render(
        request,
        "orgs/team_detail.html",
        {
            "org": team.org,
            "team": team,
            "members": members,
            "candidates": candidates,
            "projects": team.projects.filter(is_archived=False).order_by("name"),
            "is_admin": can_admin(request.user, team.org),
            "gh_link": gh_link,
            "gh_install": gh_install is not None,
            "gh_teams": gh_teams,
            "tab": "teams",
        },
    )


@login_required
@require_POST
def team_member_add(request, team_id):
    team = _admin_team_or_404(request, team_id)
    user_id = request.POST.get("user")
    user = team.org.members.filter(pk=user_id or 0).first()
    if user is None:
        messages.error(request, "조직 멤버를 선택하세요.")
        return redirect("team_detail", team_id=team.pk)
    try:
        osv.add_team_member(team, user, request.user)
    except ServiceError as e:
        messages.error(request, " ".join(e.errors.values()))
        return redirect("team_detail", team_id=team.pk)
    _sync_member(request, team, user, add=True)
    return redirect("team_detail", team_id=team.pk)


@login_required
@require_POST
def team_member_remove(request, team_id, user_id):
    team = _admin_team_or_404(request, team_id)
    user = get_object_or_404(team.org.members, pk=user_id)
    try:
        osv.remove_team_member(team, user, request.user)
    except ServiceError as e:
        messages.error(request, " ".join(e.errors.values()))
        return redirect("team_detail", team_id=team.pk)
    _sync_member(request, team, user, add=False)
    return redirect("team_detail", team_id=team.pk)


def _sync_member(request, team, user, *, add: bool):
    """연결된 GitHub 팀에 멤버 추가·제거를 반영한다. GitHub 미연결 사용자는 PM에만 넣는다."""
    link = getattr(team, "github", None)
    if not settings.GITHUB_ENABLED or link is None:
        return
    login = gh_writes._login_of(user)
    if not login:
        return
    warn = gh_writes.try_write(
        gh_writes.set_gh_team_member, link, team.org, login, actor=request.user, add=add
    )
    if warn:
        messages.warning(request, warn)


# ---------- GitHub 팀 연결 ----------


@login_required
@require_POST
def team_github_link(request, team_id):
    """이미 있는 GitHub 팀을 고른다. GitHub는 부르지 않고 PM 연결만 만든다."""
    team = _admin_team_or_404(request, team_id)
    raw = request.POST.get("gh_team", "")
    gid, _, rest = raw.partition(":")
    slug, _, name = rest.partition(":")
    if not gid.isdecimal() or not slug:
        messages.error(request, "GitHub 팀을 선택하세요.")
    elif GitHubTeamLink.objects.filter(github_team_id=int(gid)).exclude(team=team).exists():
        messages.error(request, "그 GitHub 팀은 이미 다른 팀에 연결되어 있습니다.")
    else:
        GitHubTeamLink.objects.get_or_create(
            team=team, defaults={"github_team_id": int(gid), "slug": slug, "name": name}
        )
    return redirect("team_detail", team_id=team.pk)


@login_required
@require_POST
def team_github_create(request, team_id):
    """GitHub에 같은 이름의 새 팀을 만들고 곧바로 연결한다."""
    team = _admin_team_or_404(request, team_id)
    try:
        data = gh_writes.create_gh_team(team, actor=request.user)
    except (ServiceError, GitHubError) as e:
        msg = " ".join(e.errors.values()) if isinstance(e, ServiceError) else e.message
        messages.error(request, msg)
        return redirect("team_detail", team_id=team.pk)
    GitHubTeamLink.objects.get_or_create(
        team=team,
        defaults={
            "github_team_id": data["id"],
            "slug": data["slug"],
            "name": data.get("name", ""),
        },
    )
    messages.success(request, "GitHub에 팀을 만들었습니다.")
    return redirect("team_detail", team_id=team.pk)


@login_required
@require_POST
def team_github_unlink(request, team_id):
    """PM 연결만 끊는다. GitHub 팀은 그대로 둔다."""
    team = _admin_team_or_404(request, team_id)
    GitHubTeamLink.objects.filter(team=team).delete()
    messages.success(request, "GitHub 연결을 해제했습니다.")
    return redirect("team_detail", team_id=team.pk)


@login_required
@require_POST
def team_github_reconcile(request, team_id):
    team = _admin_team_or_404(request, team_id)
    try:
        done, warns = gh_writes.reconcile_team(team, actor=request.user)
        messages.success(request, f"GitHub 팀에 {done}명을 반영했습니다.")
        for w in warns:
            messages.warning(request, w)
    except ServiceError as e:
        messages.error(request, " ".join(e.errors.values()))
    return redirect("team_detail", team_id=team.pk)
