"""Discord 계정 연결.

두 신원을 맞바꿔야 연결된다: **코드**는 로그인한 웹 세션에서만 나오고(= PM 쪽 신원),
**snowflake**는 게이트웨이가 채운 `author.id`에서만 나온다(= Discord 쪽 신원).
어느 한쪽만으로는 소유가 증명되지 않는다. 사용자가 직접 입력하는 경로는 두지 않는다.
"""

import secrets
from datetime import timedelta

from django.db import transaction
from django.utils import timezone

from common.errors import ServiceError

from .models import User

CODE_TTL = timedelta(minutes=10)


def issue_link_code(user) -> str:
    """1회용 연결 코드. 다시 발급하면 이전 코드는 그 순간 무효다."""
    code = secrets.token_hex(4).upper()
    User.objects.filter(pk=user.pk).update(
        discord_link_code=code, discord_link_expires_at=timezone.now() + CODE_TTL
    )
    return code


@transaction.atomic
def link_discord(code: str, discord_user_id: str) -> User:
    code = (code or "").strip().upper()
    did = (discord_user_id or "").strip()
    if not did.isdecimal():
        raise ServiceError({"discord_user_id": "Discord 사용자 ID 형식이 아닙니다."})
    now = timezone.now()
    user = User.objects.filter(
        discord_link_code=code, discord_link_expires_at__gt=now, is_active=True
    ).first()
    if user is None:
        raise ServiceError({"code": "코드가 틀렸거나 만료됐습니다. 웹에서 다시 발급하세요."})

    # 이 snowflake를 들고 있던 옛 행에서 가져온다. 코드와 snowflake가 둘 다 증명된 이 순간,
    # 남의 행에 남아 있는 값이 틀린 것이다. 선점당해 영구히 잠기는 경로를 없앤다.
    User.objects.filter(discord_user_id=did).exclude(pk=user.pk).update(
        discord_user_id=None, discord_linked_at=None
    )
    # 코드 1회용: 조건부 UPDATE의 rowcount로 보장한다. 비울 때는 반드시 None
    # (""로 비우면 두 번째 사용자가 unique 제약에 걸린다).
    updated = User.objects.filter(pk=user.pk, discord_link_code=code).update(
        discord_user_id=did,
        discord_linked_at=now,
        discord_link_code=None,
        discord_link_expires_at=None,
    )
    if updated != 1:
        raise ServiceError({"code": "이미 사용된 코드입니다."})
    user.refresh_from_db()
    return user


def unlink_discord(user) -> None:
    User.objects.filter(pk=user.pk).update(
        discord_user_id=None,
        discord_linked_at=None,
        discord_link_code=None,
        discord_link_expires_at=None,
    )


def unlink_discord_by_id(discord_user_id: str) -> bool:
    """봇의 `연결해제`. 알림 수신 거부 수단을 겸한다."""
    n = User.objects.filter(discord_user_id=(discord_user_id or "").strip()).update(
        discord_user_id=None, discord_linked_at=None
    )
    return n == 1


def user_by_discord_id(discord_user_id: str):
    """봇 명령의 행위자. 연결이 증명된 활성 사용자만 돌려준다."""
    did = (discord_user_id or "").strip()
    if not did:
        return None
    return User.objects.filter(
        discord_user_id=did, discord_linked_at__isnull=False, is_active=True
    ).first()


def set_user_settings(user, data: dict):
    """개인 설정 전체 교체. 이력 없음(개인 계획과 같은 원칙)."""
    from orgs import settings as S

    user.settings = S.clean("user", data)
    user.save(update_fields=["settings"])
    return user
