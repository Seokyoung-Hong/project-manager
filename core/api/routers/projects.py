import json

from ninja import Router
from ninja.errors import HttpError

from accounts.models import User
from github import services as gh_services
from orgs.models import Team
from orgs.services import orgs_of
from projects.models import Project
from projects.services import (
    create_project,
    delete_project,
    parse_spec,
    set_api_spec,
    set_project_channel,
    update_project,
)

from ..context import ctx, org_or_404
from ..schemas import (
    ApiSpecIn,
    ConflictOut,
    ErrorOut,
    ProjectCreateIn,
    ProjectOut,
    ProjectPatchIn,
    ProjectDiscordChannelIn,
    RepoConnectIn,
)
from ..serialize import project_out

router = Router(tags=["projects"])


def _visible(request):
    return (
        Project.objects.filter(org__in=orgs_of(request.auth))
        .select_related("org")
        .prefetch_related("owners", "teams")
    )


def _project_or_404(request, project_id: int) -> Project:
    p = _visible(request).filter(pk=project_id).first()
    if p is None:
        raise HttpError(404, "프로젝트를 찾을 수 없습니다.")
    return p


def _owners(ids: list[int]) -> list[User]:
    users = list(User.objects.filter(pk__in=ids))
    if len(users) != len(set(ids)):
        raise HttpError(400, "관리자를 찾을 수 없습니다.")
    return users


def _teams(ids: list[int]) -> list[Team]:
    teams = list(Team.objects.filter(pk__in=ids))
    if len(teams) != len(set(ids)):
        raise HttpError(400, "팀을 찾을 수 없습니다.")
    return teams


@router.get("", response=list[ProjectOut])
def list_projects(request, org: int | None = None, include_archived: bool = False):
    qs = _visible(request)
    if org is not None:
        qs = qs.filter(org_id=org)
    if not include_archived:
        qs = qs.filter(is_archived=False)
    return [project_out(p) for p in qs.order_by("org__name", "name")]


@router.get("/{project_id}", response=ProjectOut)
def get_project(request, project_id: int):
    return project_out(_project_or_404(request, project_id))


@router.put("/{project_id}/discord-channel", response=dict)
def set_discord_channel(request, project_id: int, payload: ProjectDiscordChannelIn):
    """조직 관리자가 Discord 프로젝트 채널 ID를 연결하거나 해제한다."""
    project = set_project_channel(_project_or_404(request, project_id), payload.channel_id, request.auth)
    return {"id": project.pk, "name": project.name, "discord_channel_id": project.discord_channel_id}


@router.post("", response={201: ProjectOut, 400: ErrorOut})
def create_project_ep(request, payload: ProjectCreateIn):
    org = org_or_404(request, payload.org_id)
    p = create_project(
        org=org,
        name=payload.name,
        purpose=payload.purpose,
        owners=_owners(payload.owner_ids),
        teams=_teams(payload.team_ids),
        status=payload.status,
        **ctx(request),
    )
    return 201, project_out(p)


@router.patch("/{project_id}", response={200: ProjectOut, 400: ErrorOut, 409: ConflictOut})
def patch_project(request, project_id: int, payload: ProjectPatchIn):
    p = _project_or_404(request, project_id)
    data = payload.dict(exclude_unset=True)
    version = data.pop("version")
    if "owner_ids" in data:
        data["owners"] = _owners(data.pop("owner_ids") or [])
    if "team_ids" in data:
        data["teams"] = _teams(data.pop("team_ids") or [])
    p = update_project(p, data, expected_version=version, **ctx(request))
    return project_out(p)


@router.delete("/{project_id}", response={204: None, 400: ErrorOut})
def delete_project_ep(request, project_id: int):
    """조직 관리자만. 보관된 프로젝트만 지울 수 있다."""
    p = _project_or_404(request, project_id)
    c = ctx(request)
    delete_project(p, actor=c["actor"], source=c["source"])
    return 204, None


@router.get("/{project_id}/api-spec", response=dict)
def get_api_spec(request, project_id: int):
    p = _project_or_404(request, project_id)
    obj = getattr(p, "api_spec", None)
    if obj is None:
        raise HttpError(404, "등록된 API 문서가 없습니다.")
    return {"source_url": obj.source_url, "fetched_at": obj.fetched_at, "spec": obj.spec}


@router.put("/{project_id}/api-spec", response={200: dict, 400: ErrorOut})
def put_api_spec(request, project_id: int, payload: ApiSpecIn):
    p = _project_or_404(request, project_id)
    spec = parse_spec(json.dumps(payload.spec).encode(), source=payload.source_url or "요청 본문")
    obj = set_api_spec(p, spec, source_url=payload.source_url, actor=request.auth)
    return {"ok": True, "fetched_at": obj.fetched_at}


# ---------- 저장소 연결 (IMPL-PLAN-4 §4.4 `ai.manage_repo`) ----------


@router.get("/{project_id}/repo", response=dict)
def get_repo(request, project_id: int):
    """이 프로젝트에 연결된 저장소. 없으면 connected=false."""
    project = _project_or_404(request, project_id)
    conn = getattr(project, "repo", None)
    if conn is None:
        return {"connected": False}
    return {
        "connected": True,
        "full_name": conn.full_name,
        "url": conn.url,
        "auto_import": conn.auto_import,
        "import_label": conn.import_label,
    }


@router.post("/{project_id}/repo", response={200: dict, 400: ErrorOut})
def connect_repo(request, project_id: int, payload: RepoConnectIn):
    """저장소를 프로젝트에 잇는다.

    AI(MCP)도 여기까지 올 수 있다. 막는 규칙은 전부 `github.services.connect_repo` 안에 있다 —
    등급(`project.settings_by`)과 조직의 AI 정책(`ai.manage_repo`)이다. 끊는 일은 열지 않았다.
    """
    project = _project_or_404(request, project_id)
    c = ctx(request)
    conn = gh_services.connect_repo(
        project=project, url=payload.url, actor=c["actor"], source=c["source"]
    )
    return {"connected": True, "full_name": conn.full_name, "url": conn.url}
