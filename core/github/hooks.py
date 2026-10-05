"""GitHub 저장소 웹훅 → Discord 프로젝트 채널 자동 설정(IMPL-PLAN-8 §10-2, G5′).

사람이 Discord 채널 웹훅을 만들고 그 URL에 `/github`를 붙여 GitHub 저장소 Settings → Webhooks에
넣던 일을 버튼 하나로 대신한다. core는 봇 토큰이 없어 Discord를 부르지 않으므로(GUIDE-00 §3) 세 걸음이다.

1. 웹에서 누르면 `request_setup`이 대기 상태(`pending`)를 남긴다.
2. 봇이 틱마다 `pending_jobs`를 가져가 그 채널에 웹훅을 만들고 `on_created`로 id·토큰을 보고한다.
3. `on_created`가 `<웹훅 URL>/github`를 GitHub 저장소 웹훅으로 등록한다 — **누른 사람의 사용자 토큰**.

해제는 반대 순서다. GitHub 훅을 먼저 지우고(누른 사람 토큰) `removing`으로 두면 봇이 Discord 웹훅을 지운다.
Discord 웹훅 URL은 토큰을 품는다. DB·로그·화면·API 응답 어디에도 원문을 남기지 않는다.

상태(`RepoConnection.discord_hook`): {} 없음 | pending | active | error | removing.
"""

import re

from django.core.cache import cache
from django.utils import timezone

from common.errors import ServiceError
from orgs.channels import ADMINISTRATOR, MANAGE_WEBHOOKS, require_discord
from orgs.settings import effective
from projects.services import _log, require_level

from . import client
from .client import GitHubError
from .models import GitHubInstallation, RepoConnection

# Discord의 GitHub 호환 엔드포인트가 받는 이벤트 중 고를 수 있게 둔 것. 순서 = 화면 순서.
EVENTS = {
    "push": "푸시",
    "pull_request": "PR",
    "pull_request_review": "PR 리뷰",
    "issues": "이슈",
    "issue_comment": "이슈·PR 댓글",
    "release": "릴리스",
    "create": "브랜치·태그 생성",
    "delete": "브랜치·태그 삭제",
}
DEFAULT_EVENTS = ["push", "pull_request", "issues", "release"]
WEBHOOK_BASE = "https://discord.com/api/webhooks"
CAPS_TTL = 3600
_TOKEN_RE = re.compile(r"^[A-Za-z0-9_\-]{20,200}$")
_URL_RE = re.compile(r"(/api/webhooks/\d+/)[A-Za-z0-9_\-]+")

APP_FIX = (
    "GitHub 앱 설정 → Permissions → Repository permissions → Webhooks를 Read and write로 바꾸고, "
    "설치 계정(조직 또는 개인)에서 새 권한을 승인해 주세요."
)


def mask(text: str) -> str:
    """Discord 웹훅 URL의 토큰 부분을 가린다."""
    return _URL_RE.sub(r"\1****", str(text or ""))


def _conn(project) -> RepoConnection:
    # project.repo는 캐시된 인스턴스라 봇 보고로 바뀐 상태를 못 본다. 늘 다시 읽는다.
    conn = RepoConnection.objects.filter(project=project).select_related("project").first()
    if conn is None:
        raise ServiceError({"hook": "저장소가 연결된 프로젝트만 설정할 수 있습니다."})
    return conn


def _actor_token(actor) -> str:
    from .writes import _actor_token as token

    return token(actor)


def _reason(e: Exception) -> str:
    if isinstance(e, ServiceError):
        return " ".join(str(v) for v in e.errors.values())
    if isinstance(e, GitHubError):
        if e.status == 0:
            return "GitHub에 연결하지 못했습니다. 잠시 뒤 다시 시도해 주세요."
        if e.status == 404:
            return "GitHub가 저장소 웹훅을 거부했습니다(HTTP 404). " + APP_FIX
        if e.status == 403:
            return "GitHub가 거부했습니다(HTTP 403). 저장소 admin 권한과 앱의 Webhooks 쓰기 권한을 확인해 주세요."
        return mask(f"GitHub가 거부했습니다(HTTP {e.status}: {e.message}).")
    return "알 수 없는 오류입니다."


def app_can_write_hooks(org) -> bool | None:
    """앱 설치에 Repository "Webhooks" 쓰기 권한이 있는가. 설치가 없거나 GitHub 오류면 None(모름). 1시간 캐시."""
    inst = GitHubInstallation.objects.filter(org=org).first()
    if inst is None:
        return None
    key = f"gh-app-hooks:{inst.installation_id}"
    hit = cache.get(key)
    if hit is not None:
        return hit
    try:
        data = client.request("GET", f"/app/installations/{inst.installation_id}", client.app_jwt())
    except (GitHubError, ValueError):  # ValueError: 앱 개인키가 없거나 깨졌다
        return None
    ok = ((data or {}).get("permissions") or {}).get("repository_hooks") in ("write", "admin")
    cache.set(key, ok, CAPS_TTL)
    return ok


def blockers(actor, project) -> list[dict]:
    """버튼 대신 보여 줄 이유와 해결 방법. 비어 있으면 설정할 수 있다. 저장소 admin 여부는 누를 때 GitHub에 묻는다."""
    org = project.org
    out = []
    if not (org.discord_guild_id and project.discord_channel_id):
        out.append(
            {
                "reason": "이 프로젝트에 Discord 프로젝트 채널이 없습니다.",
                "fix": "Discord에서 /프로젝트채널로 채널을 먼저 연결해 주세요.",
            }
        )
    perms = org.discord_bot_permissions
    if perms is None:
        out.append(
            {
                "reason": "봇의 Discord 서버 권한을 아직 확인하지 못했습니다.",
                "fix": "봇이 실행 중인지 확인하고 몇 분 뒤 다시 열어 주세요.",
            }
        )
    elif not (perms & ADMINISTRATOR) and not (perms & MANAGE_WEBHOOKS):
        out.append(
            {
                "reason": "봇에 Discord 웹후크 관리(Manage Webhooks) 권한이 없습니다.",
                "fix": "Discord 서버 설정 → 역할에서 봇 역할에 웹후크 관리 권한을 주거나, 조직 Discord 탭에서 봇을 다시 초대해 주세요.",
            }
        )
    if getattr(actor, "github", None) is None:
        out.append(
            {
                "reason": "GitHub 계정이 연결되어 있지 않습니다.",
                "fix": "설정 → 프로필에서 GitHub를 연결해 주세요(웹훅은 누른 사람 이름으로 등록됩니다).",
            }
        )
    if app_can_write_hooks(org) is False:
        out.append({"reason": "GitHub 앱에 Webhooks 쓰기 권한이 없습니다.", "fix": APP_FIX})
    try:
        require_discord(actor, org, "webhooks")
    except ServiceError as e:
        out.append({"reason": _reason(e), "fix": ""})
    return out


def _require(actor, project):
    require_level(actor, project, effective("project.settings_by", org=project.org), "hook")
    require_discord(actor, project.org, "webhooks")


def _require_repo_admin(conn, token: str):
    try:
        data = client.request("GET", f"/repos/{conn.full_name}", token)
    except GitHubError as e:
        raise ServiceError({"hook": "저장소 권한을 확인하지 못했습니다. " + _reason(e)}) from None
    if not ((data or {}).get("permissions") or {}).get("admin"):
        raise ServiceError(
            {
                "hook": "GitHub 저장소 관리자(admin)만 웹훅을 설정할 수 있습니다. 저장소 Settings → "
                "Collaborators and teams에서 Admin 역할을 받거나 저장소 관리자에게 요청해 주세요."
            }
        )


def _save(conn, new: dict, actor=None, source="web"):
    old = conn.discord_hook or {}
    conn.discord_hook = new
    conn.save(update_fields=["discord_hook"])
    if actor is not None and old.get("state") != new.get("state"):
        _log(
            conn.project,
            "repo.discord_hook",
            old.get("state", ""),
            new.get("state", ""),
            actor,
            source,
        )


def _events(events) -> list[str]:
    picked = set(events or [])
    out = [e for e in EVENTS if e in picked]
    if not out:
        raise ServiceError({"hook": "이벤트를 하나 이상 골라 주세요."})
    return out


# ---------- 웹(누른 사람) ----------


def request_setup(project, events, *, actor, source="web") -> dict:
    conn = _conn(project)
    require_level(actor, project, effective("project.settings_by", org=project.org), "hook")
    if found := blockers(actor, project):
        raise ServiceError({"hook": f"{found[0]['reason']} {found[0]['fix']}".strip()})
    if (conn.discord_hook or {}).get("state") in ("pending", "active", "removing"):
        raise ServiceError({"hook": "이미 설정되어 있거나 처리 중입니다."})
    events = _events(events)
    _require_repo_admin(conn, _actor_token(actor))
    hook = {
        "state": "pending",
        "events": events,
        "by": actor.pk,
        "channel_id": project.discord_channel_id,
        "at": timezone.now().isoformat(),
    }
    _save(conn, hook, actor, source)
    return hook


def update_events(project, events, *, actor, source="web") -> dict:
    conn = _conn(project)
    _require(actor, project)
    hook = dict(conn.discord_hook or {})
    if hook.get("state") not in ("pending", "active"):
        raise ServiceError({"hook": "설정된 웹훅이 없습니다."})
    events = _events(events)
    if hook["state"] == "active":
        try:
            client.request(
                "PATCH",
                f"/repos/{conn.full_name}/hooks/{hook['hook_id']}",
                _actor_token(actor),
                body={"events": events, "active": True},
            )
        except GitHubError as e:
            raise ServiceError({"hook": _reason(e)}) from None
    hook["events"] = events
    _save(conn, hook, actor, source)
    return hook


def remove(project, *, actor, source="web") -> dict:
    """active면 GitHub 훅을 지우고 봇에 Discord 웹훅 삭제를 맡긴다. pending·error는 기록만 지운다."""
    conn = _conn(project)
    _require(actor, project)
    hook = conn.discord_hook or {}
    state = hook.get("state")
    if state == "active":
        try:
            client.request(
                "DELETE", f"/repos/{conn.full_name}/hooks/{hook['hook_id']}", _actor_token(actor)
            )
        except GitHubError as e:
            if e.status != 404:  # 이미 GitHub에서 지웠다면 그대로 진행한다
                raise ServiceError({"hook": _reason(e)}) from None
        new = {
            "state": "removing",
            "webhook_id": hook.get("webhook_id", ""),
            "channel_id": hook.get("channel_id", ""),
        }
    elif state in ("pending", "error"):
        new = {}  # pending 중 봇이 뒤늦게 보고하면 on_created가 Discord 웹훅을 지우게 한다
    else:
        return hook
    _save(conn, new, actor, source)
    return new


def status(project) -> dict:
    """화면용. 비밀은 담지 않는다."""
    conn = getattr(project, "repo", None)
    hook = dict((conn.discord_hook if conn else None) or {})
    picked = hook.get("events") or DEFAULT_EVENTS
    hook["choices"] = [(k, label, k in picked) for k, label in EVENTS.items()]
    hook["labels"] = [EVENTS[e] for e in picked if e in EVENTS]
    if hook.get("webhook_id"):
        hook["masked_url"] = f"{WEBHOOK_BASE}/{hook['webhook_id']}/****/github"
    return hook


# ---------- 봇 ----------


def pending_jobs() -> list[dict]:
    """봇이 틱마다 가져가는 일. create = 그 채널에 웹훅 만들기, delete = 그 웹훅 지우기."""
    out = []
    for conn in RepoConnection.objects.filter(
        discord_hook__state__in=["pending", "removing"]
    ).order_by("pk"):
        hook = conn.discord_hook
        out.append(
            {
                "project_id": conn.project_id,
                "action": "create" if hook["state"] == "pending" else "delete",
                "channel_id": hook.get("channel_id", ""),
                "webhook_id": hook.get("webhook_id", ""),
            }
        )
    return out


def on_created(project_id: int, webhook_id: str, webhook_token: str) -> dict:
    """봇이 만든 Discord 웹훅을 GitHub에 등록한다. 실패하면 봇이 그 웹훅을 지우도록 delete_webhook을 돌려준다.

    # ponytail: 이 응답이 봇에 닿지 못하면 봇은 웹훅을 지우고 다음 틱에 다시 만들지만, 여기는 이미 active라
    # GitHub 훅이 지워진 URL을 가리킨다. 드물다 — 화면에서 해제 후 다시 설정하면 된다.
    """
    from accounts.models import User

    conn = RepoConnection.objects.filter(project_id=project_id).select_related("project").first()
    hook = dict((conn.discord_hook if conn else None) or {})
    if hook.get("state") != "pending":
        return {"ok": False, "delete_webhook": True}  # 그새 취소됐다
    webhook_id, webhook_token = str(webhook_id), str(webhook_token)
    if not (webhook_id.isdecimal() and _TOKEN_RE.match(webhook_token)):
        _save(conn, {**hook, "state": "error", "error": "봇이 보낸 웹훅 정보가 올바르지 않습니다."})
        return {"ok": False, "delete_webhook": True}
    url = f"{WEBHOOK_BASE}/{webhook_id}/{webhook_token}/github"
    try:
        data = client.request(
            "POST",
            f"/repos/{conn.full_name}/hooks",
            _actor_token(User.objects.filter(pk=hook.get("by")).first()),
            body={
                "name": "web",
                "active": True,
                "events": hook["events"],
                "config": {"url": url, "content_type": "json"},
            },
        )
    except (GitHubError, ServiceError) as e:
        _save(conn, {**hook, "state": "error", "error": _reason(e)})
        return {"ok": False, "delete_webhook": True}
    _save(
        conn, {**hook, "state": "active", "webhook_id": webhook_id, "hook_id": (data or {})["id"]}
    )
    return {"ok": True, "delete_webhook": False}


def on_failed(project_id: int, reason: str) -> dict:
    conn = RepoConnection.objects.filter(project_id=project_id).first()
    hook = dict((conn.discord_hook if conn else None) or {})
    if hook.get("state") != "pending":
        return {"ok": False}
    text = mask(reason)[:200]
    hook.update(
        state="error",
        error=f"봇이 Discord 웹훅을 만들지 못했습니다({text}). 봇 역할과 그 채널의 권한 덮어쓰기에 "
        "웹후크 관리 권한이 있는지 확인해 주세요.",
    )
    _save(conn, hook)
    return {"ok": True}


def on_removed(project_id: int) -> dict:
    conn = RepoConnection.objects.filter(project_id=project_id).first()
    if conn is None or (conn.discord_hook or {}).get("state") != "removing":
        return {"ok": False}
    _save(conn, {})
    return {"ok": True}
