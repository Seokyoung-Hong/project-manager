"""설정 화면 API. IMPL-PLAN-4 §8.1.

읽기·쓰기 모두 `orgs.settings`의 레지스트리 하나만 본다 — 형·범위 검증과 잠금 규칙은
거기 있는 `clean`·`effective`·`locked_keys`가 다 한다. 여기서는 권한(멤버·관리자)만 본다.
"""

from typing import Any

from ninja import Body, Router
from ninja.errors import HttpError

from accounts.services import set_user_settings
from common.errors import ServiceError
from orgs.requests import pending_out, request_change
from orgs.services import ai_denied, orgs_of, set_org_settings
from orgs.settings import SPECS, Spec, clean, effective, locked_keys, specs_for
from projects.models import Project
from projects.services import set_project_settings

from ..context import ctx, org_or_404
from ..schemas import ErrorOut

router = Router(tags=["settings"])
_BODY = Body(...)  # PUT 바디는 임의의 설정 키/값 dict다. 스키마가 아니라 레지스트리가 검증한다.


def _project_or_404(request, project_id: int) -> Project:
    p = (
        Project.objects.filter(pk=project_id, org__in=orgs_of(request.auth))
        .select_related("org")
        .first()
    )
    if p is None:
        raise HttpError(404, "프로젝트를 찾을 수 없습니다.")
    return p


def _spec_out(s: Spec) -> dict:
    return {
        "key": s.key,
        "label": s.label,
        "help": s.help,
        "kind": s.kind,
        "default": s.default,
        "choices": [list(c) for c in s.choices],
        "lo": s.lo,
        "hi": s.hi,
        "group": s.group,
        "overridable": s.overridable,
        "scope": s.scope,
    }


def _payload(scope: str, locked: list[str], **effective_kwargs) -> dict:
    specs = specs_for(scope)
    return {
        "values": {s.key: effective(s.key, **effective_kwargs) for s in specs},
        "specs": [_spec_out(s) for s in specs],
        "locked": locked,
    }


# ---- 조직 설정 ----


@router.get("/orgs/{org_id}/settings", response=dict)
def get_org_settings(request, org_id: int):
    org = org_or_404(request, org_id)
    return _payload("org", sorted(locked_keys(org)), org=org)


def _ai_policy(settings: dict) -> dict:
    return {k: settings.get(k) for k, s in SPECS.items() if s.ai_only}


@router.put("/orgs/{org_id}/settings", response={200: dict, 202: dict, 400: ErrorOut, 403: ErrorOut})
def put_org_settings(request, org_id: int, payload: dict[str, Any] = _BODY, reason: str = ""):
    org = org_or_404(request, org_id)
    # AI는 자기 정책(ai.*)을 직접 못 바꾼다. PUT은 통째 교체라 키를 빼기만 해도 기본값으로 풀리므로
    # 키 유무가 아니라 교체 전후의 ai.* 값을 비교한다. 바꾸려 하면 요청으로 남기고 허용 링크를 돌려준다.
    # 나머지 설정은 그대로 바꿀 수 있다.
    c = ctx(request)
    if c["source"] == "mcp" and not effective("ai.enabled", org=org):
        raise ServiceError({"ai": ai_denied("설정 변경")})  # AI를 끈 조직에서는 AI의 쓰기 전부를 막는다
    if c["source"] == "mcp" and _ai_policy(
        clean("org", payload, allow_locked=True)
    ) != _ai_policy(org.settings or {}):
        return 202, pending_out(request_change(org, "settings", payload, actor=c["actor"], reason=reason, token=c["token"]))
    org = set_org_settings(org, payload, request.auth)
    return _payload("org", sorted(locked_keys(org)), org=org)


# ---- 프로젝트 설정 ----


@router.get("/projects/{project_id}/settings", response=dict)
def get_project_settings(request, project_id: int):
    project = _project_or_404(request, project_id)
    project_keys = {s.key for s in specs_for("project")}
    locked = sorted(locked_keys(project.org) & project_keys)
    return _payload("project", locked, org=project.org, project=project)


@router.put("/projects/{project_id}/settings", response={200: dict, 400: ErrorOut})
def put_project_settings(request, project_id: int, payload: dict[str, Any] = _BODY):
    project = _project_or_404(request, project_id)
    project = set_project_settings(project, payload, **ctx(request))
    project_keys = {s.key for s in specs_for("project")}
    locked = sorted(locked_keys(project.org) & project_keys)
    return _payload("project", locked, org=project.org, project=project)


# ---- 개인 설정 ----


@router.get("/me/settings", response=dict)
def get_my_settings(request):
    return _payload("user", [], user=request.auth)


@router.put("/me/settings", response={200: dict, 400: ErrorOut})
def put_my_settings(request, payload: dict[str, Any] = _BODY):
    user = set_user_settings(request.auth, payload)
    return _payload("user", [], user=user)
