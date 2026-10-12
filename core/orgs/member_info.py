"""조직별 구성원 정보. 조직 관리자가 항목을 정하고, 구성원이 조직마다 따로 입력한다.

정의(Organization.member_fields): {"real_name": "off|optional|required",
  "fields": [{"id", "label", "kind": "text|long|choice", "required", "help", "choices"}]} — 목록 순서가 화면 순서.
값(OrgMembership): real_name, info = {항목 id: 값}. id 기준이라 라벨을 바꿔도 값이 남고, 지운 항목의 값은
화면에 나오지 않는다(다음 저장 때 지워진다).

필수 항목이 빈 구성원은 그 조직을 못 쓴다. 웹은 common.middleware.MemberInfoGate, API는 api.auth가
request_org_id로 요청의 조직을 정하고 blocked_org로 확인한다.
"""

import json
import re
import secrets

from django.conf import settings
from django.urls import reverse

from common.errors import ServiceError

from .models import OrgMembership

REAL_NAME = (("off", "받지 않음"), ("optional", "선택"), ("required", "필수"))
KINDS = (("text", "짧은 글"), ("long", "긴 글"), ("choice", "선택지"))
MAX_LEN = {"text": 200, "long": 2000, "choice": 50}
MAX_FIELDS = 30
_ID = re.compile(r"^[0-9a-f]{8}$")


class MemberInfoRequired(Exception):
    """API가 403 profile_required로 돌려준다(api/api.py)."""

    def __init__(self, org):
        self.org = org
        self.url = settings.SITE_URL + url(org.pk)
        super().__init__(message(org))


def definition(org) -> dict:
    d = org.member_fields or {}
    return {"real_name": d.get("real_name", "off"), "fields": d.get("fields", [])}


def _clean_field(f: dict) -> dict:
    label = (f.get("label") or "").strip()[:50]
    if not label:
        raise ServiceError({"member_fields": "항목 이름을 입력해 주세요."})
    kind = f.get("kind")
    if kind not in MAX_LEN:
        raise ServiceError({"member_fields": f"‘{label}’ 항목의 형식을 다시 골라 주세요."})
    choices = []
    if kind == "choice":
        for c in f.get("choices") or []:
            c = str(c).strip()[:50]
            if c and c not in choices:
                choices.append(c)
        if not choices:
            raise ServiceError(
                {"member_fields": f"‘{label}’ 항목의 선택지를 한 줄에 하나씩 입력해 주세요."}
            )
    fid = f.get("id") or ""
    return {
        "id": fid if _ID.match(fid) else secrets.token_hex(4),
        "label": label,
        "kind": kind,
        "required": bool(f.get("required")),
        "help": (f.get("help") or "").strip()[:200],
        "choices": choices[:30],
    }


def set_definition(org, real_name: str, fields: list[dict], actor):
    """항목 정의를 통째로 바꾼다. 바뀌면 조직 이력(ChangeLog)에 전후 요약을 남긴다."""
    from tasks.models import ChangeLog

    from .services import require_admin

    require_admin(actor, org)
    if real_name not in dict(REAL_NAME):
        raise ServiceError({"member_fields": "실명 입력 방식을 다시 골라 주세요."})
    if len(fields) > MAX_FIELDS:
        raise ServiceError({"member_fields": f"항목은 {MAX_FIELDS}개까지 만들 수 있습니다."})
    cleaned = [_clean_field(f) for f in fields]
    ids = [f["id"] for f in cleaned]
    if len(set(ids)) != len(ids):
        raise ServiceError(
            {
                "member_fields": "같은 항목이 두 번 들어왔습니다. 화면을 새로 고쳐 다시 저장해 주세요."
            }
        )
    old = definition(org)
    new = {"real_name": real_name, "fields": cleaned}
    if old == new:
        return org
    ChangeLog.objects.create(
        target_type="org",
        target_id=org.pk,
        field="member_fields",
        old_value=summary(old),
        new_value=summary(new),
        actor=actor,
        source="web",
    )
    org.member_fields = new
    org.save(update_fields=["member_fields"])
    return org


def summary(d: dict) -> str:
    parts = [f"실명 {dict(REAL_NAME)[d['real_name']]}"]
    parts += [f["label"] + (" (필수)" if f["required"] else "") for f in d["fields"]]
    return ", ".join(parts)[:500]


def missing(membership) -> bool:
    """필수 항목이 하나라도 비었는가."""
    d = definition(membership.org)
    if d["real_name"] == "required" and not membership.real_name.strip():
        return True
    info = membership.info or {}
    return any(f["required"] and not str(info.get(f["id"], "")).strip() for f in d["fields"])


def rows(membership) -> list[dict]:
    """입력 화면·구성원 표가 쓰는 현재 항목과 값. 지운 항목의 값은 나오지 않는다."""
    info = membership.info or {}
    return [{**f, "value": info.get(f["id"], "")} for f in definition(membership.org)["fields"]]


def save(membership, real_name: str, values: dict):
    """구성원이 자기 정보를 저장한다. values는 {항목 id: 값}."""
    d = definition(membership.org)
    errors = {}
    real_name = (real_name or "").strip()
    if d["real_name"] == "off":
        real_name = membership.real_name  # 받지 않는 동안 예전 값은 건드리지 않는다
    elif len(real_name) > 50:
        errors["real_name"] = "실명은 50자까지 입력할 수 있습니다."
    elif d["real_name"] == "required" and not real_name:
        errors["real_name"] = "실명을 입력해 주세요."
    info = {}
    for f in d["fields"]:
        v = str(values.get(f["id"]) or "").strip()
        if f["required"] and not v:
            errors[f["id"]] = f"{f['label']}을(를) 입력해 주세요."
        elif v and f["kind"] == "choice" and v not in f["choices"]:
            errors[f["id"]] = f"{f['label']}은(는) 목록에서 골라 주세요."
        elif len(v) > MAX_LEN[f["kind"]]:
            errors[f["id"]] = f"{f['label']}은(는) {MAX_LEN[f['kind']]}자까지 입력할 수 있습니다."
        elif v:
            info[f["id"]] = v
    if errors:
        raise ServiceError(errors)
    membership.real_name = real_name
    membership.info = info
    membership.save(update_fields=["real_name", "info"])
    return membership


def blocked_org(user, org_id):
    """user가 org_id 조직의 구성원인데 필수 항목이 비었으면 그 조직. 아니면 None."""
    if not org_id or not getattr(user, "is_authenticated", False):
        return None
    m = OrgMembership.objects.select_related("org").filter(org_id=org_id, user=user).first()
    return m.org if m is not None and missing(m) else None


def url(org_id) -> str:
    return reverse("org_member_info", args=[org_id])


def message(org) -> str:
    return f"{org.name} 조직의 구성원 정보를 먼저 입력해 주세요: {settings.SITE_URL}{url(org.pk)}"


def _int(v):
    try:
        return int(v)
    except (TypeError, ValueError):
        return None


def _org_of(kind: str, pk: int):
    from projects.models import Doc, Project
    from tasks.models import Task

    from .models import Team

    if kind == "org":
        return pk
    model, path = {
        "project": (Project, "org_id"),
        "task": (Task, "project__org_id"),
        "team": (Team, "org_id"),
        "doc": (Doc, "org_id"),
        "note": (Doc, "org_id"),
    }[kind]
    return model.objects.filter(pk=pk).values_list(path, flat=True).first()


_KINDS = ("org", "project", "task", "team", "doc", "note")


def request_org_id(kwargs: dict, params: dict | None = None):
    """요청이 가리키는 조직 id. URL 인자(org_id·project_id·task_id·team_id·doc_id·note_id)가 먼저,
    없으면 쿼리·JSON 본문의 org·project·task·team(…_id 포함). 못 정하면 None."""
    for source, suffixes in ((kwargs, ("_id",)), (params or {}, ("_id", ""))):
        for kind in _KINDS:
            for suffix in suffixes:
                pk = _int(source.get(kind + suffix))
                if pk is not None:
                    return _org_of(kind, pk)
    return None


def api_params(request) -> dict:
    """API 요청의 쿼리 + JSON 본문(객체일 때만). 파일 올리기 같은 다른 본문은 읽지 않는다."""
    params = request.GET.dict()
    if request.content_type == "application/json" and request.method in ("POST", "PUT", "PATCH"):
        try:
            body = json.loads(request.body or b"{}")
        except ValueError:
            body = None
        if isinstance(body, dict):
            params = {**params, **body}
    return params
