from ninja import Router
from ninja.errors import HttpError

from accounts.models import User
from orgs.governance import governance_text
from orgs.models import Invite, OrgMembership, Team
from orgs.services import (
    add_team_member,
    create_invite,
    create_team,
    delete_team,
    remove_team_member,
    revoke_invite,
    set_governance,
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
    TeamCreateIn,
    TeamMemberIn,
    TeamOut,
    UserBrief,
)
from ..serialize import invite_out, project_out

router = Router(tags=["orgs"])


@router.get("/{org_id}", response=OrgOut)
def get_org(request, org_id: int):
    org = org_or_404(request, org_id)
    role = OrgMembership.objects.get(org=org, user=request.auth).role
    projects = org.projects.filter(is_archived=False).prefetch_related("owners", "teams")
    teams = org.teams.all()
    return {
        "id": org.pk,
        "name": org.name,
        "purpose": org.purpose,
        "role": role,
        "discord_guild_id": org.discord_guild_id,
        "projects": [project_out(p) for p in projects],
        "teams": [
            {
                "id": t.pk,
                "name": t.name,
                "purpose": t.purpose,
                "member_count": t.members.count(),
            }
            for t in teams
        ],
    }


@router.get("/{org_id}/members", response=list[UserBrief])
def members(request, org_id: int):
    org = org_or_404(request, org_id)
    return [user_brief(u) for u in org.members.filter(is_active=True).order_by("display_name")]


@router.get("/{org_id}/teams", response=list[TeamOut])
def teams(request, org_id: int):
    org = org_or_404(request, org_id)
    return [
        {
            "id": t.pk,
            "name": t.name,
            "purpose": t.purpose,
            "member_count": t.members.count(),
        }
        for t in org.teams.all()
    ]


@router.get("/{org_id}/status", response=dict)
def status(request, org_id: int):
    return org_status(org_or_404(request, org_id))


@router.post("/{org_id}/invites", response={201: InviteOut, 400: ErrorOut})
def create_invite_ep(request, org_id: int, payload: InviteIn):
    org = org_or_404(request, org_id)
    inv = create_invite(org, ctx(request)["actor"], days=payload.days)
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


@router.put("/{org_id}/governance", response={200: GovernanceOut, 400: ErrorOut})
def put_governance(request, org_id: int, payload: GovernanceIn):
    org = set_governance(org_or_404(request, org_id), payload.text, request.auth)
    return {"text": governance_text(org), "is_default": not org.governance.strip()}


# ---- 팀 쓰기 ----


def _team_out(t: Team) -> dict:
    return {"id": t.pk, "name": t.name, "purpose": t.purpose, "member_count": t.members.count()}


def _team_or_404(request, team_id: int) -> Team:
    team = Team.objects.filter(pk=team_id).select_related("org").first()
    if team is None:
        raise HttpError(404, "팀을 찾을 수 없습니다.")
    org_or_404(request, team.org_id)
    return team


@router.post("/{org_id}/teams", response={201: TeamOut, 400: ErrorOut})
def create_team_ep(request, org_id: int, payload: TeamCreateIn):
    org = org_or_404(request, org_id)
    team = create_team(org=org, name=payload.name, purpose=payload.purpose, actor=request.auth)
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
    add_team_member(team, user, request.auth)
    return _team_out(team)


@router.delete("/teams/{team_id}/members/{user_id}", response={200: TeamOut, 400: ErrorOut})
def remove_team_member_ep(request, team_id: int, user_id: int):
    team = _team_or_404(request, team_id)
    user = User.objects.filter(pk=user_id).first()
    if user is None:
        raise HttpError(404, "사용자를 찾을 수 없습니다.")
    remove_team_member(team, user, request.auth)
    return _team_out(team)


@router.get("/{org_id}/repos", response=list[dict])
def org_repos(request, org_id: int):
    """조직의 GitHub 설치가 접근할 수 있는 저장소. 프로젝트에 무엇을 이을지 고르는 목록이다.

    설치가 없거나 GitHub이 답하지 않으면 빈 목록이다 — 화면도 AI도 그대로 동작해야 한다.
    """
    from github import services as gh_services

    org = org_or_404(request, org_id)
    return gh_services.installation_repos(org)
