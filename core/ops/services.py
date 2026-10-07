"""운영 콘솔의 변경 동작과 감사 기록. 뷰는 여기만 부른다(IMPL-PLAN-10 §4.3·§5).

모든 변경은 사유 5~300자, 위험 작업은 대상 재입력이 필요하고, 변경과 감사 기록은 한 트랜잭션이다.
"""

from django.contrib.auth.tokens import default_token_generator
from django.db import transaction
from django.urls import reverse
from django.utils.encoding import force_bytes
from django.utils.http import urlsafe_base64_encode

from accounts.auth import client_ip, unlock
from accounts.models import User
from common.errors import ServiceError

from .models import OpsAuditLog

# detail에 넣지 않는 키(대소문자 무관, 중첩 dict까지). 토큰 원문·해시, 재설정 링크, 비밀번호,
# 초대 token, Discord 연결 코드, 조직 설정 비밀값.
FORBIDDEN_DETAIL_KEYS = frozenset(
    {
        "token",
        "raw",
        "key_hash",
        "password",
        "secret",
        "link",
        "reset_link",
        "url",
        "invite_token",
        "link_code",
        "discord_link_code",
        "api_key",
    }
)
REASON_ERROR = "사유를 적어 주세요(5자 이상)."
CONFIRM_ERROR = "대상이 일치하지 않습니다."


def _check_detail(d) -> None:
    if isinstance(d, dict):
        for k, v in d.items():
            if str(k).lower() in FORBIDDEN_DETAIL_KEYS:
                raise ValueError(f"감사 기록 detail에 넣을 수 없는 키입니다: {k}")
            _check_detail(v)
    elif isinstance(d, list | tuple):
        for v in d:
            _check_detail(v)


def audit(request, action, *, target=None, target_type="", target_label="", reason="", detail=None):
    """한 줄로 남긴다. request가 없으면(관리 명령) actor 없음(None)·actor_username="system"."""
    detail = detail or {}
    _check_detail(detail)
    user = getattr(request, "user", None) if request else None
    authed = bool(user and user.is_authenticated)
    return OpsAuditLog.objects.create(
        actor=user if authed else None,
        actor_username=user.get_username() if authed else "system",
        action=action,
        target_type=target_type or (type(target).__name__.lower() if target else ""),
        target_id=getattr(target, "pk", None),
        target_label=(target_label or (str(target) if target else ""))[:200],
        reason=reason,
        detail=detail,
        ip=client_ip(request) if request else "",
    )


def _reason(reason) -> str:
    reason = (reason or "").strip()
    if not 5 <= len(reason) <= 300:
        raise ServiceError({"reason": REASON_ERROR})
    return reason


def _confirm(confirm, expected: str) -> None:
    if (confirm or "").strip() != expected:
        raise ServiceError({"confirm": CONFIRM_ERROR})


def _is_operator(user) -> bool:
    return user.is_staff or user.is_superuser


def _require_superuser(request) -> None:
    if not request.user.is_superuser:
        raise ServiceError({"permission": "최고 운영자만 할 수 있습니다."})


def _set_user(request, user, action, field, value, reason, before) -> None:
    with transaction.atomic():
        User.objects.filter(pk=user.pk).update(**{field: value})
        audit(
            request,
            action,
            target=user,
            target_label=user.username,
            reason=reason,
            detail={"before": {field: before}, "after": {field: value}},
        )
    setattr(user, field, value)


def suspend_user(request, user, reason, confirm) -> None:
    reason = _reason(reason)
    _confirm(confirm, user.username)
    if user.pk == request.user.pk:
        raise ServiceError({"permission": "자기 자신은 정지할 수 없습니다."})
    if _is_operator(user):
        _require_superuser(request)
    _set_user(request, user, "user.suspend", "is_active", False, reason, user.is_active)


def reactivate_user(request, user, reason) -> None:
    reason = _reason(reason)
    _set_user(request, user, "user.reactivate", "is_active", True, reason, user.is_active)


def grant_staff(request, user, reason, confirm) -> None:
    reason = _reason(reason)
    _confirm(confirm, user.username)
    _require_superuser(request)
    _set_user(request, user, "user.grant_staff", "is_staff", True, reason, user.is_staff)


def revoke_staff(request, user, reason, confirm) -> None:
    reason = _reason(reason)
    _confirm(confirm, user.username)
    _require_superuser(request)
    if user.pk == request.user.pk:
        raise ServiceError({"permission": "자기 자신의 운영자 권한은 회수할 수 없습니다."})
    if user.is_superuser:
        raise ServiceError(
            {"permission": "최고 운영자의 권한은 Django 관리 화면이나 셸에서만 바꿀 수 있습니다."}
        )
    _set_user(request, user, "user.revoke_staff", "is_staff", False, reason, user.is_staff)


def issue_reset_link(request, user, reason, confirm) -> str:
    """비밀번호 재설정 링크(24시간·1회용)를 만들어 돌려준다. 링크는 감사 기록에 넣지 않는다.

    이메일 발송 기능이 없으므로 운영자가 본인 확인된 경로로 직접 전달한다.
    """
    reason = _reason(reason)
    _confirm(confirm, user.username)
    if not user.is_active:
        raise ServiceError({"permission": "정지된 사용자에게는 재설정 링크를 발급할 수 없습니다."})
    if _is_operator(user):
        _require_superuser(request)
    path = reverse(
        "password_reset_confirm",
        args=[
            urlsafe_base64_encode(force_bytes(user.pk)),
            default_token_generator.make_token(user),
        ],
    )
    audit(request, "user.reset_link", target=user, target_label=user.username, reason=reason)
    return request.build_absolute_uri(path)


def unlock_login(request, key, reason) -> int:
    """로그인 잠금 해제(아이디 또는 IP). 지운 행 수."""
    reason = _reason(reason)
    key = (key or "").strip()
    if not key:
        raise ServiceError({"key": "해제할 아이디나 IP를 적어 주세요."})
    with transaction.atomic():
        n = unlock(key)
        audit(
            request,
            "user.unlock",
            target_type="login",
            target_label=key,
            reason=reason,
            detail={"rows": n},
        )
    return n


def token_label(token) -> str:
    """토큰 앞자리 표기(토큰 화면과 같다). 재입력 확인값이기도 하다."""
    return token.prefix[3:]


def revoke_token(request, token, reason, confirm) -> None:
    reason = _reason(reason)
    _confirm(confirm, token_label(token))
    if token.scope == "bot":
        raise ServiceError({"permission": "봇 토큰은 셸에서 폐기해 주세요."})
    with transaction.atomic():
        before = token.revoked_at
        token.revoke()
        audit(
            request,
            "token.revoke",
            target=token,
            target_type="token",
            target_label=token_label(token) + "…",
            reason=reason,
            detail={"owner": token.user.username, "already_revoked": before is not None},
        )


EXPORT_CONFIRM = "export"


def record_export(request, reason, confirm) -> None:
    """운영 데이터 JSON 내보내기 전 검사와 기록(최고 운영자·사유·"export" 재입력)."""
    reason = _reason(reason)
    _confirm(confirm, EXPORT_CONFIRM)
    _require_superuser(request)
    audit(request, "export.json", target_type="export", target_label="export.json", reason=reason)
