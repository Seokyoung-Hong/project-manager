"""AI의 조직 설정·거버넌스 변경 요청. 올리는 건 API(AI 토큰), 허용·거절은 웹(로그인 세션)만 한다."""

import difflib
import unicodedata

from django.conf import settings
from django.db import transaction
from django.utils import timezone

from common.errors import ServiceError

from .governance import DEFAULT_GOVERNANCE
from .models import ChangeRequest, Organization
from .services import _display_setting, ai_denied, require_admin, set_governance, set_org_settings
from .settings import LOCKED, SPECS, clean, effective

GOVERNANCE_MAX = 20000


def _current(org, kind: str):
    return (org.settings or {}) if kind == "settings" else org.governance


def request_change(org, kind: str, data, *, actor, reason: str = "", token=None) -> ChangeRequest:
    """바꿀 내용을 검증해 요청으로 남긴다. 바로 바꿀 권한이 있는 사람(조직 관리자)의 AI만 올릴 수 있다.

    잘못된 값은 여기서 바로 400으로 돌려보낸다 — 허용 화면에서야 틀린 걸 알면 사람이 헛걸음한다.
    """
    require_admin(actor, org)
    if not effective("ai.enabled", org=org):
        # AI를 끈 조직에서 "다시 켜 달라"는 요청이 쌓이지 않게 한다.
        raise ServiceError({"ai": ai_denied("설정·거버넌스 변경 요청")})
    base = _current(org, kind)
    if kind == "settings":
        proposed = clean("org", data, allow_locked=True)
        same = proposed == base
    else:
        proposed = (data or "").strip()
        if len(proposed) > GOVERNANCE_MAX:
            raise ServiceError({"governance": "2만 자를 넘을 수 없습니다."})
        # 비어 있으면 기본안이 쓰인다. 실제로 적용되는 글이 같으면 비교 화면이 비어 보이므로 받지 않는다.
        same = (proposed or DEFAULT_GOVERNANCE).strip() == (base or DEFAULT_GOVERNANCE).strip()
    if same:
        raise ServiceError({kind: "바뀌는 내용이 없습니다."})
    reason = (reason or "").strip()
    if not reason:
        raise ServiceError(
            {"reason": "왜 바꾸려는지 reason에 적어 주세요. 사람이 허용할지 판단하는 근거입니다."}
        )
    if len(reason) > 500:
        raise ServiceError({"reason": "변경 이유는 500자까지입니다."})
    return ChangeRequest.objects.create(
        org=org,
        kind=kind,
        base=base,
        proposed=proposed,
        reason=reason,
        requested_by=actor,
        token=token,
    )


def pending_out(req: ChangeRequest) -> dict:
    """API 응답. AI는 approve_url을 사용자에게 그대로 보여 주고, 허용될 때까지 다시 시도하지 않는다."""
    return {
        "status": "pending",
        "request_id": req.pk,
        "approve_url": settings.SITE_URL + req.path,
        "expires_at": req.expires_at,
        "detail": "바로 바꾸지 않고 승인 요청을 올렸습니다. 조직 관리자가 이 링크를 열어 허용하면 반영됩니다.",
    }


def approve(req: ChangeRequest, actor) -> ChangeRequest:
    req = _approve(req, actor)
    if req.status == "stale":
        # 무효 표시는 저장한 뒤에 알린다. 트랜잭션 안에서 던지면 그 표시까지 되돌아간다.
        raise ServiceError(
            {
                "request": "요청을 올린 뒤에 내용이 바뀌어 무효가 됐습니다. AI에게 다시 요청해 달라고 해 주세요."
            }
        )
    return req


@transaction.atomic
def _approve(req, actor):
    req = ChangeRequest.objects.select_for_update().get(pk=req.pk)
    # 조직 행도 잠근다. 비교와 저장 사이에 사람이 웹에서 저장한 값을 덮지 않게.
    org = Organization.objects.select_for_update().get(pk=req.org_id)
    require_admin(actor, org)
    if not req.is_open:
        raise ServiceError({"request": "이미 처리했거나 만료된 요청입니다."})
    if _current(org, req.kind) != req.base:
        # 요청 뒤에 사람이 먼저 바꿨다. 옛 값을 기준으로 만든 변경안이 그 수정을 덮으면 안 된다.
        req.status = "stale"
        req.save(update_fields=["status"])
        return req
    if req.kind == "settings":
        # 이력은 허용한 사람 이름으로 남되, 어느 AI의 요청이었는지 이어 둔다.
        set_org_settings(org, req.proposed, actor, note=f"AI 요청 #{req.pk} 허용", token=req.token)
    else:
        set_governance(org, req.proposed, actor)
    return _close(req, actor, "approved")


@transaction.atomic
def reject(req: ChangeRequest, actor, reason: str = "") -> ChangeRequest:
    req = ChangeRequest.objects.select_for_update().select_related("org").get(pk=req.pk)
    require_admin(actor, req.org)
    if not req.is_open:
        raise ServiceError({"request": "이미 처리했거나 만료된 요청입니다."})
    req.reject_reason = (reason or "").strip()[:300]
    return _close(req, actor, "rejected")


def _close(req, actor, status):
    req.status = status
    req.reviewed_by = actor
    req.reviewed_at = timezone.now()
    req.save(update_fields=["status", "reviewed_by", "reviewed_at", "reject_reason"])
    return req


def settings_diff(req: ChangeRequest) -> list[dict]:
    """바뀌는 설정만. 사람이 읽는 이름과 값으로."""
    rows = []
    for key in sorted(set(req.base) | set(req.proposed)):
        old, new = req.base.get(key), req.proposed.get(key)
        if old == new:
            continue
        label = (
            "프로젝트가 덮어쓸 수 없는 항목"
            if key == LOCKED
            else SPECS[key].label
            if key in SPECS
            else key
        )
        rows.append(
            {
                "key": key,
                "label": label,
                "old": _visible(
                    _display_setting(key, old) if key == LOCKED or key in SPECS else str(old)
                ),
                "new": _visible(_display_setting(key, new)),
                "ai": key in SPECS and SPECS[key].ai_only,
            }
        )
    return rows


def governance_diff(req: ChangeRequest) -> list[str]:
    # 비어 있으면 기본안이 쓰인다. 사람이 보는 것도 실제로 적용되는 글끼리의 차이여야 한다.
    old, new = req.base or DEFAULT_GOVERNANCE, req.proposed or DEFAULT_GOVERNANCE
    lines = difflib.unified_diff(old.splitlines(), new.splitlines(), lineterm="", n=2)
    return [_visible(line) for line in list(lines)[2:]]  # ---/+++ 머리줄은 빼고 색으로만 구분한다


def governance_after(req: ChangeRequest) -> str:
    """허용하면 적용될 글 전체. 비교만으로는 크게 고친 글의 맥락을 알기 어렵다."""
    return _visible(req.proposed or DEFAULT_GOVERNANCE)


def _visible(text: str) -> str:
    """보이지 않는 서식 문자(폭 없는 공백·방향 제어 등)를 드러낸다. 같아 보이는 두 줄로 사람을 속이지 못하게."""
    return "".join(f"⟨U+{ord(c):04X}⟩" if unicodedata.category(c) == "Cf" else c for c in text)
