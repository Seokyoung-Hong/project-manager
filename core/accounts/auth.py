"""인증 — 누구인가를 확인하고 로그인을 끝낸다. 시도 제한도 여기 있다.

모든 사람 로그인 경로(비밀번호·가입·GitHub, 나중에 OIDC)는 `login_user()` 하나를 지난다.
외부 계정(subject) → User 찾기는 `accounts/identity.py`가 맡는다.

인가 지도(코드는 각 자리에 그대로 있다). Keycloak이 와도 이 표는 PM에 남는다. IdP는 1행만 맡는다.
| 층 | 위치 |
|---|---|
| 1. 인증(누구인가) | 이 모듈, accounts/identity.py, github/services.login_with_github |
| 2. 조직 역할 | orgs/services(is_member·is_admin·require_admin) |
| 3. 프로젝트 등급 | projects/services.require_level |
| 4. 가시성 | projects/services.visible_projects |
| 5. 토큰 범위 | api/auth(TokenAuth) |
| 6. AI 정책 | 각 services의 _ai_check |

서비스 자격(ApiToken 사람용·AI용, OAuth로 발급한 MCP Bearer, Discord 봇 토큰)은 32바이트
난수라 맞혀 볼 수 없다. 그래서 시도 제한 대상이 아니다. 세션은 Django DB 세션이다.
"""

import math
from datetime import timedelta

from django.contrib.auth import authenticate, login, logout
from django.db import transaction
from django.utils import timezone

from .models import LoginLock

LOCK_POLICY = {  # kind: (실패 횟수, 창(분), 잠금(분))
    "user": (
        5,
        15,
        15,
    ),  # 같은 아이디(소문자) 기준. 존재하지 않는 아이디도 센다(존재 여부를 숨긴다)
    "ip": (30, 15, 60),  # 같은 IP 기준
    "signup_ip": (10, 60, 60),  # 가입 생성 수
}


class LockedOut(Exception):
    def __init__(self, retry_after_minutes: int):
        super().__init__(retry_after_minutes)
        self.retry_after_minutes = retry_after_minutes


def client_ip(request) -> str:
    """X-Forwarded-For의 **맨 오른쪽** 값(앞단 프록시 하나가 덧붙인 값), 없으면 REMOTE_ADDR.
    왼쪽 값은 클라이언트가 지어낼 수 있다. compose는 web 포트를 프록시 IP에만 연다."""
    xff = request.META.get("HTTP_X_FORWARDED_FOR", "")
    return xff.rsplit(",", 1)[-1].strip() or request.META.get("REMOTE_ADDR", "")


def check_lock(kind: str, key: str) -> None:
    lock = LoginLock.objects.filter(
        kind=kind, key=key[:150], locked_until__gt=timezone.now()
    ).first()
    if lock:
        left = (lock.locked_until - timezone.now()).total_seconds()
        raise LockedOut(max(1, math.ceil(left / 60)))


@transaction.atomic
def record_failure(kind: str, key: str) -> None:
    limit, window, lock_minutes = LOCK_POLICY[kind]
    now = timezone.now()
    LoginLock.objects.filter(updated_at__lt=now - timedelta(days=1)).delete()
    # select_for_update: 워커 둘이 동시에 세면 하나를 잃는다(SQLite는 무시하지만 운영은 Postgres).
    lock, _ = LoginLock.objects.select_for_update().get_or_create(
        kind=kind, key=key[:150], defaults={"window_started_at": now}
    )
    if lock.window_started_at <= now - timedelta(minutes=window):
        lock.failures, lock.window_started_at, lock.locked_until = 0, now, None
    lock.failures += 1
    if lock.failures >= limit:
        lock.locked_until = now + timedelta(minutes=lock_minutes)
    lock.save()


def record_success(kind: str, key: str) -> None:
    LoginLock.objects.filter(kind=kind, key=key[:150]).delete()


def authenticate_password(request, username: str, password: str):
    """잠금 확인 → 인증 → 실패면 아이디·IP 둘 다 세고, 성공이면 아이디 카운터를 지운다.

    잠겨 있으면 비밀번호가 맞아도 LockedOut이다. User 또는 None.
    """
    user_key, ip = (username or "").lower(), client_ip(request)
    check_lock("user", user_key)
    check_lock("ip", ip)
    user = authenticate(request, username=username, password=password)
    if user is None:
        record_failure("user", user_key)
        record_failure("ip", ip)
    else:
        record_success("user", user_key)
    return user


def login_user(request, user, method: str) -> None:
    """로그인 완료. method = "password" | "github" | 나중에 "oidc".

    모든 로그인 경로가 이 함수를 지난다 — OIDC 로그아웃(RP-initiated)이 method를 봐야 한다.
    """
    login(request, user, backend="django.contrib.auth.backends.ModelBackend")
    request.session["auth_method"] = method


def logout_user(request) -> None:
    # ponytail: auth_method == "oidc"면 여기서 IdP end_session_endpoint로 보낸다(IMPL-PLAN-7 §4.4).
    logout(request)


def active_locks() -> list[LoginLock]:
    return list(LoginLock.objects.filter(locked_until__gt=timezone.now()).order_by("-locked_until"))


def unlock(key: str) -> int:
    """아이디(대소문자 무관) 또는 IP의 잠금·카운터를 모두 지운다. 지운 행 수."""
    return LoginLock.objects.filter(key__in={key, key.lower()}).delete()[0]
