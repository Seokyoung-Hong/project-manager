from datetime import date

from ninja import Router
from ninja.errors import HttpError

from accounts.models import User
from orgs.governance import governance_text
from orgs.models import Invite, OrgMembership, Team
from orgs.requests import pending_out, request_change
from orgs.services import (
    add_team_member,
    can_view_team,
    create_invite,
    create_team,
    delete_team,
    remove_team_member,
    require_admin,
    require_ai_enabled,
    revoke_invite,
    set_governance,
    visible_teams,
)
from reports.services import org_status
from tasks.brief import user_brief

from ..context import ctx, org_or_404
from ..schemas import (
    ErrorOut,
    GovernanceIn,
    GovernanceOut,
    InviteIn,
    InviteOut,
    OrgOut,
    TaskListOut,
    TeamCreateIn,
    TeamMemberIn,
    TeamOut,
    UserBrief,
)
from ..serialize import invite_out, project_out
from .tasks import list_tasks

router = Router(tags=["orgs"])


@router.post("/{org_id}/discord-control-check", response=dict)
def discord_control_check(request, org_id: int):
    """사용자 토큰으로 Discord 변경 전 AI 정책을 확인한다. 읽기는 차단하지 않는다."""
    org = org_or_404(request, org_id)
    context = ctx(request)
    require_admin(context["actor"], org)
    require_ai_enabled(org, context["source"], "Discord 채널 관리")
    return {"ok": True}


@router.get("/{org_id}", response=OrgOut)
def get_org(request, org_id: int):
    org = org_or_404(request, org_id)
    role = OrgMembership.objects.get(org=org, user=request.auth).role
    projects = org.projects.filter(is_archived=False).prefetch_related("owners", "teams")
    return {
        "id": org.pk,
        "name": org.name,
        "purpose": org.purpose,
        "role": role,
        "discord_guild_id": org.discord_guild_id,
        "projects": [project_out(p) for p in projects],
        "teams": _teams_out(org, request.auth),
    }


@router.get("/{org_id}/members", response=list[UserBrief])
def members(request, org_id: int):
    org = org_or_404(request, org_id)
    return [user_brief(u) for u in org.members.filter(is_active=True).order_by("display_name")]


@router.get("/{org_id}/teams", response=list[TeamOut])
def teams(request, org_id: int):
    return _teams_out(org_or_404(request, org_id), request.auth)


@router.get("/{org_id}/status", response=dict)
def status(request, org_id: int):
    return org_status(org_or_404(request, org_id), viewer=request.auth)


@router.post("/{org_id}/invites", response={201: InviteOut, 400: ErrorOut})
def create_invite_ep(request, org_id: int, payload: InviteIn):
    org = org_or_404(request, org_id)
    c = ctx(request)
    inv = create_invite(org, c["actor"], days=payload.days, source=c["source"])
    return 201, invite_out(inv)


@router.delete("/invites/{invite_id}", response={204: None})
def delete_invite(request, invite_id: int):
    inv = Invite.objects.filter(pk=invite_id).select_related("org").first()
    if inv is None:
        raise HttpError(404, "초대를 찾을 수 없습니다.")
    org_or_404(request, inv.org_id)
    revoke_invite(inv, ctx(request)["actor"])
    return 204, None


# ---- 거버넌스 ----


@router.get("/{org_id}/governance", response=GovernanceOut)
def get_governance(request, org_id: int):
    org = org_or_404(request, org_id)
    return {"text": governance_text(org), "is_default": not org.governance.strip()}


@router.put(
    "/{org_id}/governance", response={200: GovernanceOut, 202: dict, 400: ErrorOut, 403: ErrorOut}
)
def put_governance(request, org_id: int, payload: GovernanceIn, reason: str = ""):
    org = org_or_404(request, org_id)
    # 거버넌스는 AI가 따르는 규칙이라 AI가 직접 고치지 않는다. 요청으로 남기고 사람이 허용한다.
    c = ctx(request)
    if c["source"] == "mcp":
        return 202, pending_out(
            request_change(
                org, "governance", payload.text, actor=c["actor"], reason=reason, token=c["token"]
            )
        )
    org = set_governance(org, payload.text, request.auth)
    return {"text": governance_text(org), "is_default": not org.governance.strip()}


# ---- 팀 쓰기 ----


def _team_out(t: Team, visible: bool = True) -> dict:
    return {
        "id": t.pk,
        "name": t.name,
        "purpose": t.purpose,
        "member_count": t.members.count() if visible else None,
        "dev_tools": t.dev_tools,
        "is_private": t.is_private,
    }


def _teams_out(org, user) -> list[dict]:
    """팀 목록. 볼 수 없는 비공개 팀은 이름만 — 인원은 null(`visible_teams`)."""
    visible = set(visible_teams(user, org).values_list("pk", flat=True))
    return [_team_out(t, t.pk in visible) for t in org.teams.all()]


def _team_or_404(request, team_id: int) -> Team:
    team = Team.objects.filter(pk=team_id).select_related("org").first()
    if team is None:
        raise HttpError(404, "팀을 찾을 수 없습니다.")
    org_or_404(request, team.org_id)
    return team


@router.post("/{org_id}/teams", response={201: TeamOut, 400: ErrorOut})
def create_team_ep(request, org_id: int, payload: TeamCreateIn):
    org = org_or_404(request, org_id)
    c = ctx(request)
    team = create_team(
        org=org,
        name=payload.name,
        purpose=payload.purpose,
        dev_tools=payload.dev_tools,
        is_private=payload.is_private,
        actor=c["actor"],
        source=c["source"],
    )
    return 201, _team_out(team)


@router.delete("/teams/{team_id}", response={204: None, 400: ErrorOut})
def delete_team_ep(request, team_id: int):
    """조직 관리자만. 팀만 지운다 — 멤버·프로젝트는 그대로 남는다."""
    team = _team_or_404(request, team_id)
    c = ctx(request)
    delete_team(team, actor=c["actor"], source=c["source"])
    return 204, None


@router.post("/teams/{team_id}/members", response={200: TeamOut, 400: ErrorOut})
def add_team_member_ep(request, team_id: int, payload: TeamMemberIn):
    team = _team_or_404(request, team_id)
    user = User.objects.filter(pk=payload.user_id).first()
    if user is None:
        raise HttpError(404, "사용자를 찾을 수 없습니다.")
    c = ctx(request)
    add_team_member(team, user, c["actor"], source=c["source"])
    return _team_out(team, can_view_team(c["actor"], team))


@router.delete("/teams/{team_id}/members/{user_id}", response={200: TeamOut, 400: ErrorOut})
def remove_team_member_ep(request, team_id: int, user_id: int):
    team = _team_or_404(request, team_id)
    user = User.objects.filter(pk=user_id).first()
    if user is None:
        raise HttpError(404, "사용자를 찾을 수 없습니다.")
    c = ctx(request)
    remove_team_member(team, user, c["actor"], source=c["source"])
    return _team_out(team, can_view_team(c["actor"], team))


@router.get("/{org_id}/repos", response=list[dict])
def org_repos(request, org_id: int):
    """조직의 GitHub 설치가 접근할 수 있는 저장소. 프로젝트에 무엇을 이을지 고르는 목록이다.

    설치가 없거나 GitHub이 답하지 않으면 빈 목록이다 — 화면도 AI도 그대로 동작해야 한다.
    """
    from github import services as gh_services

    org = org_or_404(request, org_id)
    return gh_services.installation_repos(org, request.auth)


@router.get("/{org_id}/tasks", response=TaskListOut)
def org_tasks(
    request,
    org_id: int,
    project: int | None = None,
    assignee: int | None = None,
    status: str | None = None,
    due_from: date | None = None,
    due_to: date | None = None,
    q: str | None = None,
    updated_since: str | None = None,
    include_archived: bool = False,
    limit: int = 50,
    offset: int = 0,
):
    """그 조직 안의 태스크만. 조직 안에서 보는 화면·AI는 이 경로를 쓴다.

    `/api/tasks`는 여러 조직을 가로지르는 개인 전체 보기(DM 등)로 남긴다. 여기서는 조직이 경로라
    빠뜨릴 수 없고, 다른 조직의 프로젝트를 넘기면 빈 목록이 아니라 404로 알린다.
    """
    org = org_or_404(request, org_id)
    if project is not None and not org.projects.filter(pk=project).exists():
        raise HttpError(404, "이 조직의 프로젝트가 아닙니다.")
    return list_tasks(
        request,
        org=org.pk,
        project=project,
        assignee=assignee,
        status=status,
        due_from=due_from,
        due_to=due_to,
        q=q,
        updated_since=updated_since,
        include_archived=include_archived,
        limit=limit,
        offset=offset,
    )
