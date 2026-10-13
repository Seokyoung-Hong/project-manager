"""웹에서 시작하는 Codex 로그인(기기 코드)·로그아웃. 토큰·auth.json은 PC 밖으로 나오지 않는다.

흐름: [Codex 로그인] → start() → 그 PC의 다음 heartbeat 응답에 codex_login {id} → udally-link가
`codex login --device-auth`를 돌려 인증 주소·사용자 코드만 report() → 화면이 폴링으로 보여 줌 →
사용자가 자기 브라우저에서 입력 → PC가 `codex login status` 결과(로그인 여부)를 report(done).
주소는 OpenAI 인증 도메인일 때만 받는다. 코드는 만료(Codex가 준 시간, 없으면 15분)되면 tidy()가 지운다.
코드는 로그에 남기지 않는다.
"""

import re
from datetime import timedelta
from urllib.parse import urlsplit

from django.db import transaction
from django.http import Http404
from django.utils import timezone

from common.errors import ServiceError

from .models import CodexLogin

LOGIN_HOSTS = {"auth.openai.com"}  # 기기 코드 입력 주소로 받아 주는 곳
CODE = re.compile(r"[A-Z0-9]{4,8}-[A-Z0-9]{4,8}")
PICKUP = timedelta(minutes=2)  # PC가 이 안에 명령을 받아 코드를 보고하지 않으면 만료
DEFAULT_TTL, MAX_TTL = 15 * 60, 30 * 60
ERRORS = {"codex_missing", "codex_docker", "login_failed", "bad_login_url", "pc_error"}
OPEN = ("requested", "code")


def device(server) -> dict:
    """PC가 heartbeat device에 실어 보낸 Codex 상태({docker, installed, version, login})."""
    d = (server.device or {}).get("codex")
    return d if isinstance(d, dict) else {}


def tidy(row: CodexLogin) -> CodexLogin:
    if row.state in OPEN and row.expires_at and row.expires_at <= timezone.now():
        row.state, row.url, row.code = "expired", "", ""
        row.save(update_fields=["state", "url", "code", "updated_at"])
    return row


def current(server) -> CodexLogin | None:
    row = CodexLogin.objects.filter(server=server).first()
    return tidy(row) if row else None


@transaction.atomic
def start(user, server, action: str) -> CodexLogin:
    """PC 주인만. PC당 진행 중 하나 — 같은 동작이 진행 중이면 그대로 돌려준다."""
    if server is None or server.owner_id != user.pk:
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
    row.expires_at = timezone.now() + PICKUP
    row.save()
    return row


def on_heartbeat(server) -> dict:
    row = current(server)
    if row is None or row.state != "requested":
        return {}
    return {f"codex_{row.action}": {"id": row.pk}}


class Finished(Exception):
    """이미 끝났거나 만료된 요청에 온 보고(409)."""


def _ok_url(url: str) -> bool:
    try:
        u = urlsplit(url)
    except ValueError:
        return False
    return u.scheme == "https" and u.hostname in LOGIN_HOSTS and not u.username and not u.port


@transaction.atomic
def report(server, login_id: int, data: dict) -> CodexLogin:
    row = CodexLogin.objects.select_for_update().filter(pk=login_id, server=server).first()
    if row is None:
        raise Http404
    tidy(row)
    if row.state not in OPEN:
        raise Finished
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
