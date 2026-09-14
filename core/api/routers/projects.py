import json

from ninja import Router
from ninja.errors import HttpError

from accounts.models import User
from orgs import settings as S
from orgs.models import Team
from orgs.services import orgs_of
from projects.models import Project
from projects.services import (
    create_project,
    parse_spec,
    set_api_spec,
    set_governance_extra,
    set_project_settings,
    update_project,
)

from ..context import ctx, org_or_404
from ..schemas import (
    ApiSpecIn,
    ConflictOut,
    ErrorOut,
    GovernanceExtraIn,
    GovernanceExtraOut,
    ProjectCreateIn,
    ProjectOut,
    ProjectPatchIn,
    ProjectSettingsIn,
    ProjectSettingsOut,
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


# ---- 설정 ----


def _project_settings_out(project) -> dict:
    overridable = [s for s in S.specs("org") if s.overridable]
    return {
        "values": dict(project.settings),
        "effective": {s.key: S.effective(s.key, project=project) for s in overridable},
        "locked": S.locked_keys(project.org),
    }


@router.get("/{project_id}/settings", response=ProjectSettingsOut)
def get_project_settings(request, project_id: int):
    return _project_settings_out(_project_or_404(request, project_id))


@router.put("/{project_id}/settings", response={200: ProjectSettingsOut, 400: ErrorOut})
def put_project_settings(request, project_id: int, payload: ProjectSettingsIn):
    p = _project_or_404(request, project_id)
    c = ctx(request)
    p = set_project_settings(p, payload.values, actor=c["actor"], source=c["source"])
    return _project_settings_out(p)


@router.get("/{project_id}/governance-extra", response=GovernanceExtraOut)
def get_governance_extra(request, project_id: int):
    return {"text": _project_or_404(request, project_id).governance_extra}


@router.put("/{project_id}/governance-extra", response={200: GovernanceExtraOut, 400: ErrorOut})
def put_governance_extra(request, project_id: int, payload: GovernanceExtraIn):
    p = _project_or_404(request, project_id)
    p = set_governance_extra(p, payload.text, actor=request.auth)
    return {"text": p.governance_extra}
