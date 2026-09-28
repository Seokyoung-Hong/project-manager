"""AI의 조직 설정·거버넌스 변경 요청. 올리는 건 API(AI 토큰), 허용·거절은 웹(로그인 세션)만 한다."""

import difflib

from django.conf import settings
from django.db import transaction
from django.utils import timezone

from common.errors import ServiceError

from .governance import DEFAULT_GOVERNANCE
from .models import ChangeRequest
from .services import _display_setting, require_admin, set_governance, set_org_settings
from .settings import LOCKED, SPECS, clean

GOVERNANCE_MAX = 20000


def _current(org, kind: str):
    return (org.settings or {}) if kind == "settings" else org.governance


def request_change(org, kind: str, data, *, actor, token=None) -> ChangeRequest:
    """바꿀 내용을 검증해 요청으로 남긴다. 바로 바꿀 권한이 있는 사람(조직 관리자)의 AI만 올릴 수 있다.

    잘못된 값은 여기서 바로 400으로 돌려보낸다 — 허용 화면에서야 틀린 걸 알면 사람이 헛걸음한다.
    """
    require_admin(actor, org)
    if kind == "settings":
        proposed = clean("org", data, allow_locked=True)
    else:
        proposed = (data or "").strip()
        if len(proposed) > GOVERNANCE_MAX:
            raise ServiceError({"governance": "2만 자를 넘을 수 없습니다."})
    base = _current(org, kind)
    if proposed == base:
        raise ServiceError({kind: "바뀌는 내용이 없습니다."})
    return ChangeRequest.objects.create(
        org=org, kind=kind, base=base, proposed=proposed, requested_by=actor, token=token
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
    req = ChangeRequest.objects.select_for_update().select_related("org").get(pk=req.pk)
    require_admin(actor, req.org)
    if not req.is_open:
        raise ServiceError({"request": "이미 처리했거나 만료된 요청입니다."})
    if _current(req.org, req.kind) != req.base:
        # 요청 뒤에 사람이 먼저 바꿨다. 옛 값을 기준으로 만든 변경안이 그 수정을 덮으면 안 된다.
        req.status = "stale"
        req.save(update_fields=["status"])
        return req
    if req.kind == "settings":
        set_org_settings(req.org, req.proposed, actor)
    else:
        set_governance(req.org, req.proposed, actor)
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
                "old": _display_setting(key, old) if key == LOCKED or key in SPECS else str(old),
                "new": _display_setting(key, new),
                "ai": key in SPECS and SPECS[key].ai_only,
            }
        )
    return rows


def governance_diff(req: ChangeRequest) -> list[str]:
    # 비어 있으면 기본안이 쓰인다. 사람이 보는 것도 실제로 적용되는 글끼리의 차이여야 한다.
    old, new = req.base or DEFAULT_GOVERNANCE, req.proposed or DEFAULT_GOVERNANCE
    lines = difflib.unified_diff(old.splitlines(), new.splitlines(), lineterm="", n=2)
    return list(lines)[2:]  # ---/+++ 머리줄은 빼고 색으로만 구분한다
