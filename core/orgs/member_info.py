"""조직별 구성원 정보. 조직 관리자가 항목을 정하고, 구성원이 조직마다 따로 입력한다.

정의(Organization.member_fields): {"show_real_name": bool,
  "fields": [{"id", "label", "kind": "text|long|choice", "required", "help", "choices"}]} — 목록 순서가 화면 순서.
show_real_name은 "실명으로 표시"(조직 표시 이름 = 계정 실명, orgs/names.py). 실명 자체는 계정에 있다(User.real_name).
값(OrgMembership): info = {항목 id: 값}. id 기준이라 라벨을 바꿔도 값이 남고, 지운 항목의 값은
화면에 나오지 않는다(다음 저장 때 지워진다).

필수 항목이 빈 구성원은 그 조직을 못 쓴다. 웹은 common.middleware.MemberInfoGate, API는 api.auth가
request_org_id로 요청의 조직을 정하고 blocked_org로 확인한다.
"""

import json
import re
import secrets

from django.conf import settings
from django.db import transaction
from django.urls import reverse

from common.errors import ServiceError

from .models import OrgMembership

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
    """{"show_real_name": bool, "fields": [...]}. org는 조직 또는 member_fields dict.

    키 호환은 여기 한 곳: orgs 0014 이전 모양(real_name: off|optional|required)이면 required를 켬으로 읽는다.
    그래서 마이그레이션 전후·되돌리기 중에도 화면과 names.org_names가 깨지지 않는다.
    """
    d = (org if isinstance(org, dict) else org.member_fields) or {}
    show = d["show_real_name"] if "show_real_name" in d else d.get("real_name") == "required"
    return {"show_real_name": bool(show), "fields": d.get("fields", [])}


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


@transaction.atomic
def set_definition(org, actor, *, show_real_name=None, fields=None):
    """ "실명으로 표시"와 항목 정의를 바꾼다. 둘 중 None인 쪽은 그대로 둔다(IMPL-PLAN-14 §8.4).

    부르는 법: set_definition(org, actor, show_real_name=…, fields=…).
    바뀌면 조직 이력(ChangeLog)에 전후 요약을 남긴다. 행을 잠그고 다시 읽어 합친다.
    """
    from tasks.models import ChangeLog

    from . import names
    from .models import Organization
    from .services import require_admin

    require_admin(actor, org)
    if fields is not None:
        if len(fields) > MAX_FIELDS:
            raise ServiceError({"member_fields": f"항목은 {MAX_FIELDS}개까지 만들 수 있습니다."})
        fields = [_clean_field(f) for f in fields]
        ids = [f["id"] for f in fields]
        if len(set(ids)) != len(ids):
            raise ServiceError(
                {
                    "member_fields": "같은 항목이 두 번 들어왔습니다. 화면을 새로 고쳐 다시 저장해 주세요."
                }
            )
    org.member_fields = (
        Organization.objects.select_for_update()
        .values_list("member_fields", flat=True)
        .get(pk=org.pk)
    )
    old = definition(org)
    new = {
        "show_real_name": old["show_real_name"] if show_real_name is None else bool(show_real_name),
        "fields": old["fields"] if fields is None else fields,
    }
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
    if "_legacy_real_name" in (org.member_fields or {}):  # orgs 0014 되돌리기가 옛 모드를 복원한다
        new["_legacy_real_name"] = org.member_fields["_legacy_real_name"]
    org.member_fields = new
    org.save(update_fields=["member_fields"])
    names.forget(org.pk)
    return org


def lock_definition(org):
    """조직 행을 잠그고 member_fields를 다시 읽어 org에 넣는다(같은 트랜잭션 안에서).

    실명으로 표시·필수 항목 검사가 요청 전에 읽은 낡은 정의를 믿지 않게 한다 — set_definition과 같은 행 잠금이라
    정의 변경과 표시 이름·구성원 정보 저장이 차례로 지나간다.
    """
    from .models import Organization

    org.member_fields = (
        Organization.objects.select_for_update()
        .values_list("member_fields", flat=True)
        .get(pk=org.pk)
    )
    return org


def summary(d: dict) -> str:
    # COPY:member_fields.summary_show_real_name
    parts = ["실명 표시: " + ("켜짐" if d["show_real_name"] else "꺼짐")]
    parts += [f["label"] + (" (필수)" if f["required"] else "") for f in d["fields"]]
    return ", ".join(parts)[:500]


def missing(membership) -> bool:
    """필수 항목이 하나라도 비었는가."""
    info = membership.info or {}
    return any(
        f["required"] and not str(info.get(f["id"], "")).strip()
        for f in definition(membership.org)["fields"]
    )


def rows(membership) -> list[dict]:
    """입력 화면·구성원 표가 쓰는 현재 항목과 값. 지운 항목의 값은 나오지 않는다."""
    info = membership.info or {}
    return [{**f, "value": info.get(f["id"], "")} for f in definition(membership.org)["fields"]]


def _check(org, values: dict, errors: dict, *, required: bool = True) -> dict:
    """values({항목 id: 값})를 검사해 저장할 info를 돌려준다. 오류는 errors에 모은다.
    required=False(관리자 대리 수정)는 필수 비움을 허용한다."""
    info = {}
    for f in definition(org)["fields"]:
        v = str(values.get(f["id"]) or "").strip()
        if required and f["required"] and not v:
            errors[f["id"]] = f"{f['label']}을(를) 입력해 주세요."
        elif v and f["kind"] == "choice" and v not in f["choices"]:
            errors[f["id"]] = f"{f['label']}은(는) 목록에서 골라 주세요."
        elif len(v) > MAX_LEN[f["kind"]]:
            errors[f["id"]] = f"{f['label']}은(는) {MAX_LEN[f['kind']]}자까지 입력할 수 있습니다."
        elif v:
            info[f["id"]] = v
    return info


def save(membership, values: dict):
    """구성원이 자기 정보를 저장한다. values는 {항목 id: 값}. 실명은 계정에 있다(설정 → 프로필)."""
    errors = {}
    info = _check(membership.org, values, errors)
    if errors:
        raise ServiceError(errors)
    membership.info = info
    membership.save(update_fields=["info"])
    return membership


def _check_nickname(membership, value, errors: dict):
    """조직 표시 이름 검사. 바꿀 필요가 없으면 None, 바꿀 값이면 정리한 문자열."""
    from accounts.services import clean_real_name

    try:
        new = clean_real_name(value, field="nickname", required=False)
    except ServiceError as e:
        errors.update(e.errors)
        return None
    if new == membership.nickname:
        return None
    if definition(membership.org)["show_real_name"]:
        # COPY:nickname.real_name_org (services.set_nickname과 같은 문구)
        errors["nickname"] = (
            "이 조직은 구성원 이름을 실명으로 표시합니다. 본인과 관리자 모두 조직 표시 이름을 변경할 수 없습니다."
        )
        return None
    return new


@transaction.atomic
def save_me(membership, *, real_name=None, nickname=None, values=None):
    """내 정보 한 폼 원자 저장(IMPL-PLAN-14 §7): 계정 실명·조직 표시 이름·구성원 정보.

    셋을 모두 먼저 검사해 오류를 한꺼번에 ServiceError({필드: 문구})로 낸다(필드 = real_name·nickname·항목 id).
    오류가 하나라도 있으면 아무것도 쓰지 않는다. None = 안 보냄 = 그대로(옛 폼 호환).
    대상은 항상 membership.user 본인이다 — 호출자는 request.user의 멤버십만 넘긴다.
    """
    from accounts.services import clean_real_name, set_real_name

    from .services import set_nickname

    lock_definition(membership.org)
    errors, info, nick = {}, None, None
    if real_name is not None:
        try:
            clean_real_name(real_name)
        except ServiceError as e:
            errors.update(e.errors)
    if nickname is not None:
        nick = _check_nickname(membership, nickname, errors)
    if values is not None:
        info = _check(membership.org, values, errors)
    if errors:
        raise ServiceError(errors)
    user = membership.user
    if real_name is not None:
        set_real_name(user, real_name)
    if nick is not None:
        set_nickname(membership, nick, user)
    if info is not None:
        membership.info = info
        membership.save(update_fields=["info"])
    return membership


@transaction.atomic
def admin_save(membership, actor, *, nickname=None, values=None):
    """조직 관리자가 구성원이 이 조직에 낸 정보(조직 표시 이름·구성원 정보)를 고친다(IMPL-PLAN-14 §8.2).

    실명·계정 표시 이름·아이디는 받지 않는다. 형식·길이·선택지만 검사하고 필수 비움은 허용한다.
    조직 표시 이름은 set_nickname이 이력을 남기고, 구성원 정보가 바뀌면 조직 이력에
    field="member_info", new_value="이름(user pk): 바뀐 항목 이름들" 1건 — 값은 남기지 않는다.
    """
    from tasks.models import ChangeLog

    from .services import require_admin, set_nickname

    org, user = membership.org, membership.user
    require_admin(actor, org)
    lock_definition(org)
    errors, info, nick = {}, None, None
    if nickname is not None:
        nick = _check_nickname(membership, nickname, errors)
    if values is not None:
        info = _check(org, values, errors, required=False)
    if errors:
        raise ServiceError(errors)
    if nick is not None:
        set_nickname(membership, nick, actor)
    if info is not None:
        old = membership.info or {}
        changed = [
            f["label"]
            for f in definition(org)["fields"]
            if str(old.get(f["id"], "")) != info.get(f["id"], "")
        ]
        if changed:
            ChangeLog.objects.create(
                target_type="org",
                target_id=org.pk,
                field="member_info",
                old_value="",
                new_value=f"{membership.nickname or user.display_name}({user.pk}): "
                + ", ".join(changed),
                actor=actor,
                source="web",
            )
            membership.info = info
            membership.save(update_fields=["info"])
    return membership


def empty_counts(org) -> dict[str, int]:
    """항목 id → 그 항목이 빈 구성원 수(가입 전 구성원 제외). 필수로 바꿀 때 영향 인원 안내용.

    # ponytail: 구성원마다 is_pending이 GitHub 연결을 한 번 읽는다(조직당 수십 명). 커지면 한 쿼리로 모은다.
    """
    from .services import is_pending

    fields = definition(org)["fields"]
    counts = {f["id"]: 0 for f in fields}
    for m in OrgMembership.objects.filter(org=org).select_related("user"):
        if is_pending(m.user):
            continue
        info = m.info or {}
        for f in fields:
            if not str(info.get(f["id"], "")).strip():
                counts[f["id"]] += 1
    return counts


def blocked_org(user, org_id):
    """user가 org_id 조직의 구성원인데 필수 항목이 비었으면 그 조직. 아니면 None."""
    if not org_id or not getattr(user, "is_authenticated", False):
        return None
    m = OrgMembership.objects.select_related("org").filter(org_id=org_id, user=user).first()
    return m.org if m is not None and missing(m) else None


def blocked_orgs(user) -> list:
    """user가 필수 항목을 비워 쓸 수 없는 조직들. 열람 관문(visible_projects·visible_docs)이 이 조직을 뺀다.

    # ponytail: 부를 때마다 내 구성원 행을 한 번 읽는다(사람당 조직 몇 개). 느려지면 요청 단위로 캐시한다.
    """
    if not getattr(user, "is_authenticated", False):
        return []
    ms = OrgMembership.objects.select_related("org").filter(user=user)
    return [m.org for m in ms if missing(m)]


def blocked_user_ids(org_id) -> set[int]:
    """이 조직에서 필수 항목이 빈 구성원. 열람 함수를 거치지 않는 알림(DM·기한 알림)이 수신자에서 뺀다."""
    ms = OrgMembership.objects.select_related("org").filter(org_id=org_id)
    return {m.user_id for m in ms if missing(m)}


def blocked_out(user) -> list[dict]:
    """여러 조직에 걸친 응답에 붙이는 안내: 빠진 조직과 입력 화면 주소."""
    return [
        {
            "org_id": o.pk,
            "org_name": o.name,
            "message": notice(o),
            "url": settings.SITE_URL + url(o.pk),
        }
        for o in blocked_orgs(user)
    ]


def notice(org) -> str:
    return f"{org.name} 조직은 구성원 정보를 입력해야 볼 수 있습니다."


def url(org_id) -> str:
    return reverse("org_settings", args=[org_id]) + "?tab=me"


def message(org) -> str:
    return f"{org.name} 조직의 구성원 정보를 먼저 입력해 주세요: {settings.SITE_URL}{url(org.pk)}"


def _int(v):
    try:
        return int(v)
    except (TypeError, ValueError):
        return None


def _org_of(kind: str, pk: int):
    from projects.models import Doc, Milestone, Project
    from tasks.models import Task, WorkRequest

    from .models import Invite, Team

    if kind == "org":
        return pk
    model, path = {
        "project": (Project, "org_id"),
        "task": (Task, "project__org_id"),
        "team": (Team, "org_id"),
        "doc": (Doc, "org_id"),
        "note": (Doc, "org_id"),
        "milestone": (Milestone, "project__org_id"),
        "invite": (Invite, "org_id"),
        "membership": (OrgMembership, "org_id"),
        "req": (WorkRequest, "org_id"),  # 웹 /requests/<req_id>
        "request": (WorkRequest, "org_id"),  # API /api/requests/{request_id}
    }[kind]
    return model.objects.filter(pk=pk).values_list(path, flat=True).first()


# URL 인자는 대상 객체의 조직으로, 쿼리·본문은 조직을 고르는 값(org·project·task·team)만 본다.
_URL_KINDS = ("org", "project", "task", "team", "doc", "note", "milestone", "invite", "membership", "req", "request")  # fmt: skip
_PARAM_KINDS = ("org", "project", "task", "team")


def request_org_id(kwargs: dict, params: dict | None = None):
    """요청이 가리키는 조직 id. URL 인자(org_id·project_id·…)가 먼저, 없으면 쿼리·본문의
    org·project·task·team(…_id 포함). 못 정하면 None."""
    for kind in _URL_KINDS:
        pk = _int(kwargs.get(kind + "_id"))
        if pk is not None:
            return _org_of(kind, pk)
    params = params or {}
    for kind in _PARAM_KINDS:
        for name in (kind + "_id", kind):
            pk = _int(params.get(name))
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
