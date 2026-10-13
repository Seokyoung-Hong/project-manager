"""웹에서 시작하는 Codex 로그인(기기 코드)·로그아웃. 토큰·auth.json은 PC 밖으로 나오지 않는다.

흐름: [Codex 로그인] → start() → 그 PC의 다음 heartbeat 응답에 codex_login {id} → udally-link가
`codex login --device-auth`를 돌려 인증 주소·사용자 코드만 report() → 화면이 폴링으로 보여 줌 →
사용자가 자기 브라우저에서 입력 → PC가 `codex login status` 결과(로그인 여부)를 report(done).
주소는 OpenAI 인증 도메인일 때만 받는다. 코드는 만료(Codex가 준 시간, 없으면 15분)되면 tidy()가 지운다.
코드는 로그에 남기지 않는다.
"""

import re
import secrets
from datetime import timedelta
from urllib.parse import urlsplit

from django.conf import settings
from django.db import transaction
from django.http import Http404
from django.utils import timezone

from common.errors import ServiceError

from .models import CodexLogin

LOGIN_HOSTS = {"auth.openai.com"}  # 기기 코드 입력 주소로 받아 주는 곳
CODE = re.compile(r"[A-Z0-9]{4,8}-[A-Z0-9]{4,8}")
PICKUP = timedelta(minutes=2)  # PC가 이 안에 명령을 받아 코드를 보고하지 않으면 만료
DEFAULT_TTL, MAX_TTL = 15 * 60, 15 * 60  # 처리방침: 기기 코드는 최대 15분
ERRORS = {"codex_missing", "codex_docker", "login_failed", "bad_login_url", "pc_error"}
OPEN = ("requested", "code")
POLICY = (
    2  # udally-link가 heartbeat codex_policy로 이 값 이상을 보내야 Codex 작업·로그인 명령을 준다
)
#             (2 = 기능 허용 목록·검증 버전 목록·로그인 시도 구분을 아는 link). 옛 link는 받지 않는다.


def enabled() -> bool:
    """Codex 경로 스위치(ASSIST_CODEX_ENABLED). 끄면 로그인·로그아웃 명령도 시작·전달하지 않는다."""
    return settings.ASSIST_CODEX_ENABLED


def policy_ok(data: dict) -> bool:
    try:
        return int(data.get("codex_policy") or 0) >= POLICY
    except (TypeError, ValueError):
        return False


def device(server) -> dict:
    """PC가 heartbeat device에 실어 보낸 Codex 상태({docker, installed, version, login})."""
    d = (server.device or {}).get("codex")
    return d if isinstance(d, dict) else {}


def tidy(row: CodexLogin) -> CodexLogin:
    if row.state in OPEN and row.expires_at and row.expires_at <= timezone.now():
        row.state, row.url, row.code = "expired", "", ""
        row.save(update_fields=["state", "url", "code", "updated_at"])
    return row


def sweep(now=None) -> int:
    """만료된 기기 코드를 DB에서 비운다(화면을 다시 열지 않아도). assist.worker.sweep이 주기로 부른다."""
    return CodexLogin.objects.filter(state__in=OPEN, expires_at__lte=now or timezone.now()).update(
        state="expired", url="", code="", updated_at=timezone.now()
    )


def current(server) -> CodexLogin | None:
    row = CodexLogin.objects.filter(server=server).first()
    return tidy(row) if row else None


@transaction.atomic
def start(user, server, action: str) -> CodexLogin:
    """PC 주인만. PC당 진행 중 하나 — 같은 동작이 진행 중이면 그대로 돌려준다."""
    if server is None or server.owner_id != user.pk or not enabled():
        raise Http404
    if action not in ("login", "logout"):
        raise ServiceError({"action": "알 수 없는 동작입니다."})
    if device(server).get("docker"):
        raise ServiceError(
            {"codex": "Docker로 설치한 udally-link에서는 Codex를 사용할 수 없습니다."}
        )  # COPY:codex_login_docker
    row, _ = CodexLogin.objects.select_for_update().get_or_create(
        server=server, defaults={"state": "done"}
    )
    tidy(row)
    if row.state in OPEN and row.action == action:
        return row
    row.action, row.state, row.url, row.code, row.error = action, "requested", "", "", ""
    row.attempt = secrets.token_hex(
        8
    )  # 행은 PC당 하나라 시도마다 새 값 — 옛 시도의 늦은 보고를 거른다
    row.expires_at = timezone.now() + PICKUP
    row.save()
    return row


def on_heartbeat(server, data: dict) -> dict:
    if not enabled() or not policy_ok(data):
        return {}  # 스위치를 끄면 끄기 전에 접수한 명령도 보내지 않는다
    row = current(server)
    if row is None or row.state != "requested":
        return {}
    return {f"codex_{row.action}": {"id": row.pk, "attempt": row.attempt}}


class Finished(Exception):
    """이미 끝났거나 만료된 요청에 온 보고(409)."""


def _ok_url(url: str) -> bool:
    try:
        u = urlsplit(url)
        return u.scheme == "https" and u.hostname in LOGIN_HOSTS and not u.username and not u.port
    except ValueError:  # 비정상 포트 등
        return False


def report(server, login_id: int, data: dict) -> CodexLogin:
    if (
        not enabled()
    ):  # 스위치를 끄면 진행 중 요청도 닫고 코드를 지운다(예외 전에 저장되게 트랜잭션 밖에서)
        CodexLogin.objects.filter(server=server, state__in=OPEN).update(
            state="expired", url="", code="", updated_at=timezone.now()
        )
        raise Finished
    return _report(server, login_id, data)


@transaction.atomic
def _report(server, login_id: int, data: dict) -> CodexLogin:
    row = CodexLogin.objects.select_for_update().filter(pk=login_id, server=server).first()
    if row is None:
        raise Http404
    tidy(row)
    attempt = str(data.get("attempt") or "")
    if row.state not in OPEN or not secrets.compare_digest(attempt.encode(), row.attempt.encode()):
        raise Finished  # 끝난 요청·다른 시도(같은 행을 다시 쓴 뒤 늦게 온 옛 보고)
    now = timezone.now()
    if data.get("error"):
        row.state, row.url, row.code = "failed", "", ""
        row.error = data["error"] if data["error"] in ERRORS else "pc_error"
    elif data.get("done"):
        row.state, row.url, row.code = "done", "", ""
        info = {**device(server), "login": bool(data.get("logged_in"))}
        server.device = {**(server.device or {}), "codex": info}
        server.save(update_fields=["device"])
    elif row.action == "login" and row.state == "requested":
        url, code = str(data.get("url") or ""), str(data.get("code") or "").upper()
        if not _ok_url(url) or not CODE.fullmatch(code):
            row.state, row.url, row.code, row.error = "failed", "", "", "bad_login_url"
        else:
            ttl = min(int(data.get("expires_in") or DEFAULT_TTL), MAX_TTL)
            row.state, row.url, row.code = "code", url, code
            row.expires_at = now + timedelta(seconds=max(ttl, 60))
    row.save()
    return row
