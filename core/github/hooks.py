"""GitHub 저장소 웹훅 → Discord 프로젝트 채널 자동 설정(IMPL-PLAN-8 §10-2, G5′).

사람이 Discord 채널 웹훅을 만들고 그 URL에 `/github`를 붙여 GitHub 저장소 Settings → Webhooks에
넣던 일을 버튼 하나로 대신한다. core는 봇 토큰이 없어 Discord를 부르지 않으므로(GUIDE-00 §3) 세 걸음이다.

1. 웹에서 누르면 `request_setup`이 대기 상태(`pending`)를 남긴다.
2. 봇이 틱마다 `pending_jobs`를 가져가 그 채널에 웹훅을 만들고 `on_created`로 id·토큰을 보고한다.
3. `on_created`가 `<웹훅 URL>/github`를 GitHub 저장소 웹훅으로 등록한다 — **누른 사람의 사용자 토큰**.

해제는 반대 순서다. GitHub 훅을 먼저 지우고(누른 사람 토큰) `removing`으로 두면 봇이 Discord 웹훅을 지운다.
Discord 웹훅 URL은 토큰을 품는다. DB·로그·화면·API 응답 어디에도 원문을 남기지 않는다.

상태(`RepoConnection.discord_hook`): {} 없음 | pending | registering(core가 GitHub 등록 중) | active | error | removing.
요청마다 세대 `job`을 두고 봇 보고는 세대·상태가 맞을 때만 반영한다. 지울 웹훅은 `cleanup` 목록에 남겨
봇 틱마다 다시 시도한다(취소된 생성의 보상 삭제도 여기로 간다).
"""

import re
import secrets

from django.core.cache import cache
from django.db import transaction
from django.db.models import Q
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
BUSY = ("pending", "registering", "active", "removing")
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


def _locked(project_id):
    return (
        RepoConnection.objects.select_for_update()
        .filter(project_id=project_id)
        .select_related("project")
        .first()
    )


def _write(conn, hook: dict):
    """잠근 행에 쓴다. 빈 정리 목록은 남기지 않는다."""
    hook = dict(hook)
    if not hook.get("cleanup"):
        hook.pop("cleanup", None)
    conn.discord_hook = hook
    conn.save(update_fields=["discord_hook"])


def _add_cleanup(hook: dict, webhook_id: str, hook_id=None, by=None):
    """지울 웹훅을 정리 목록에 올린다. 봇 틱마다 다시 시도하므로 한 번 실패해도 사라지지 않는다."""
    if not webhook_id:
        return
    items = [dict(c) for c in hook.get("cleanup") or []]
    for c in items:
        if c["webhook_id"] == webhook_id:
            if hook_id:
                c.update(hook_id=hook_id, by=by)
            break
    else:
        items.append({"webhook_id": webhook_id, "hook_id": hook_id, "by": by})
    hook["cleanup"] = items


def _save(conn, new: dict, actor=None, source="web", cleanup: tuple = ()):
    """웹 쪽 상태 변경. 정리 목록은 봇 보고가 동시에 늘릴 수 있어 잠근 최신 행의 것을 잇는다."""
    with transaction.atomic():
        row = _locked(conn.project_id)
        if row is None:
            return
        old = dict(row.discord_hook or {})
        new = {k: v for k, v in new.items() if k != "cleanup"}
        new["cleanup"] = old.get("cleanup") or []
        for webhook_id in cleanup:
            _add_cleanup(new, webhook_id)
        _write(row, new)
    conn.discord_hook = row.discord_hook
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
    if (conn.discord_hook or {}).get("state") in BUSY:
        raise ServiceError({"hook": "이미 설정되어 있거나 처리 중입니다."})
    events = _events(events)
    _require_repo_admin(conn, _actor_token(actor))
    hook = {
        "state": "pending",
        "job": secrets.token_hex(8),  # 요청 세대. 봇 보고는 이 값이 맞을 때만 반영한다
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
        raise ServiceError({"hook": "설정된 웹훅이 없거나 처리 중입니다."})
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
    """active면 GitHub 훅을 지우고 봇에 Discord 웹훅 삭제를 맡긴다. 그 밖에는 기록만 지운다.

    등록 중(registering)에 취소하면 `on_created`가 끝난 뒤 세대가 바뀐 것을 보고 양쪽 훅을 정리한다.
    """
    conn = _conn(project)
    require_level(actor, project, effective("project.settings_by", org=project.org), "hook")
    hook = conn.discord_hook or {}
    state = hook.get("state")
    cleanup: tuple = ()
    if state == "active":
        # Discord 서버 권한은 실제 훅이 있을 때만 본다. pending·error는 기록만 지우므로 묻지 않는다 —
        # 봇 권한 부족으로 생긴 오류를 같은 권한 없는 사람이 못 지우는 잠김을 막는다.
        require_discord(actor, project.org, "webhooks")
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
    elif state in ("pending", "registering", "error"):
        new = {}
        if state == "registering":  # core가 등록 도중 멈췄어도 Discord 웹훅은 남지 않게 한다
            cleanup = (hook.get("webhook_id", ""),)
    else:
        return hook
    _save(conn, new, actor, source, cleanup=cleanup)
    return new


def status(project) -> dict:
    """화면용. 비밀은 담지 않는다. 등록 중(registering)은 화면에서 대기(pending)로 보인다."""
    conn = getattr(project, "repo", None)
    hook = {
        k: v for k, v in ((conn.discord_hook if conn else None) or {}).items() if k != "cleanup"
    }
    if hook.get("state") == "registering":
        hook["state"] = "pending"
    picked = hook.get("events") or DEFAULT_EVENTS
    hook["choices"] = [(k, label, k in picked) for k, label in EVENTS.items()]
    hook["labels"] = [EVENTS[e] for e in picked if e in EVENTS]
    if hook.get("webhook_id"):
        hook["masked_url"] = f"{WEBHOOK_BASE}/{hook['webhook_id']}/****/github"
    return hook


# ---------- 봇 ----------


def _delete_github(full_name: str, hook_id, by) -> bool:
    """정리용 GitHub 훅 삭제. 지웠거나 이미 없으면 True."""
    from accounts.models import User

    try:
        client.request(
            "DELETE",
            f"/repos/{full_name}/hooks/{hook_id}",
            _actor_token(User.objects.filter(pk=by).first()),
        )
    except GitHubError as e:
        return e.status == 404
    except ServiceError:
        return False
    return True


def _sweep(conn) -> list[dict]:
    """정리 목록의 GitHub 훅을 먼저 지운다. GitHub 쪽이 끝난 항목만 Discord 삭제 작업으로 돌려준다.

    # ponytail: GitHub 삭제가 계속 거부되면(토큰 만료 등) 틱마다 다시 시도한다. 횟수 제한은 두지 않았다.
    """
    done = {
        c["webhook_id"]
        for c in conn.discord_hook.get("cleanup") or []
        if c.get("hook_id") and _delete_github(conn.full_name, c["hook_id"], c.get("by"))
    }
    if done:
        with transaction.atomic():
            row = _locked(conn.project_id)
            hook = dict(row.discord_hook or {})
            hook["cleanup"] = [
                {**c, "hook_id": None} if c["webhook_id"] in done else c
                for c in hook.get("cleanup") or []
            ]
            _write(row, hook)
            conn = row
    return [c for c in conn.discord_hook.get("cleanup") or [] if not c.get("hook_id")]


def pending_jobs() -> list[dict]:
    """봇이 틱마다 가져가는 일. create = 그 채널에 웹훅 만들기, delete = 그 웹훅 지우기.

    delete는 해제(removing)와 정리 목록(취소된 생성의 보상) 둘에서 나온다. 봇이 지우고 보고할 때까지 남는다.
    """
    out = []
    for conn in RepoConnection.objects.filter(
        Q(discord_hook__state__in=["pending", "removing"]) | Q(discord_hook__has_key="cleanup")
    ).order_by("pk"):
        hook = conn.discord_hook
        if hook.get("state") == "pending":
            out.append(
                {
                    "project_id": conn.project_id,
                    "action": "create",
                    "job": hook.get("job", ""),
                    "channel_id": hook.get("channel_id", ""),
                    "webhook_id": "",
                }
            )
        elif hook.get("state") == "removing":
            out.append(
                {
                    "project_id": conn.project_id,
                    "action": "delete",
                    "job": "",
                    "channel_id": hook.get("channel_id", ""),
                    "webhook_id": hook.get("webhook_id", ""),
                }
            )
        out += [
            {
                "project_id": conn.project_id,
                "action": "delete",
                "job": "",
                "channel_id": "",
                "webhook_id": c["webhook_id"],
            }
            for c in _sweep(conn)
        ]
    return out


def on_created(project_id: int, job: str, webhook_id: str, webhook_token: str) -> dict:
    """봇이 만든 Discord 웹훅을 GitHub에 등록한다. **같은 보고가 여러 번 와도 결과가 같다**(응답 유실 재보고).

    세대(`job`)가 다르거나 그새 취소됐으면 그 웹훅을 정리 목록에 올린다. GitHub 등록 중에 취소되면
    등록이 끝난 뒤 세대를 다시 확인해 양쪽 훅을 정리 목록으로 보낸다(보상). `delete_webhook`은
    정리 목록을 둘 연결 행이 사라졌을 때만 True다 — 그때만 봇이 직접 지운다.
    """
    from accounts.models import User

    job, webhook_id, webhook_token = str(job), str(webhook_id), str(webhook_token)
    if not webhook_id.isdecimal():
        return {"ok": False, "delete_webhook": False}  # 지울 수도 없는 값이다
    with transaction.atomic():
        conn = _locked(project_id)
        if conn is None:
            return {"ok": False, "delete_webhook": True}
        hook = dict(conn.discord_hook or {})
        state = hook.get("state")
        if hook.get("job", "") == job and hook.get("webhook_id") == webhook_id:
            if state in ("registering", "active"):
                return {"ok": state == "active", "delete_webhook": False}  # 다시 온 같은 보고
        if any(c["webhook_id"] == webhook_id for c in hook.get("cleanup") or []):
            return {"ok": False, "delete_webhook": False}  # 이미 정리 대상이다
        if hook.get("job", "") != job or state != "pending":
            _add_cleanup(hook, webhook_id)  # 취소됐거나 다른 세대의 보고다
            _write(conn, hook)
            return {"ok": False, "delete_webhook": False}
        if not _TOKEN_RE.match(webhook_token):
            hook.update(state="error", error="봇이 보낸 웹훅 정보가 올바르지 않습니다.")
            _add_cleanup(hook, webhook_id)
            _write(conn, hook)
            return {"ok": False, "delete_webhook": False}
        hook.update(state="registering", webhook_id=webhook_id)
        _write(conn, hook)
        full_name, by, events = conn.full_name, hook.get("by"), hook["events"]

    # GitHub 호출은 잠금 밖에서 한다. 그동안 웹에서 취소·재설정할 수 있다.
    hook_id, error = None, ""
    try:
        data = client.request(
            "POST",
            f"/repos/{full_name}/hooks",
            _actor_token(User.objects.filter(pk=by).first()),
            body={
                "name": "web",
                "active": True,
                "events": events,
                "config": {
                    "url": f"{WEBHOOK_BASE}/{webhook_id}/{webhook_token}/github",
                    "content_type": "json",
                },
            },
        )
        hook_id = (data or {})["id"]
    except (GitHubError, ServiceError) as e:
        error = _reason(e)

    with transaction.atomic():
        conn = _locked(project_id)
        if conn is None:  # 그새 저장소 연결이 지워졌다. 정리 목록을 둘 곳이 없어 여기서 지운다
            if hook_id:
                _delete_github(full_name, hook_id, by)
            return {"ok": False, "delete_webhook": True}
        cur = dict(conn.discord_hook or {})
        if cur.get("job", "") == job and cur.get("state") == "registering":
            if hook_id:
                cur.update(state="active", hook_id=hook_id)
            else:
                cur.update(state="error", error=error)
                _add_cleanup(cur, webhook_id)
        else:
            _add_cleanup(cur, webhook_id, hook_id, by)  # 등록하는 사이 취소됐다: 보상 삭제
        _write(conn, cur)
        return {
            "ok": cur.get("state") == "active" and cur.get("job") == job,
            "delete_webhook": False,
        }


def on_failed(project_id: int, job: str, reason: str) -> dict:
    with transaction.atomic():
        conn = _locked(project_id)
        hook = dict((conn.discord_hook if conn else None) or {})
        if hook.get("state") != "pending" or hook.get("job", "") != str(job):
            return {"ok": False}
        hook.update(
            state="error",
            error=f"봇이 Discord 웹훅을 만들지 못했습니다({mask(reason)[:200]}). 봇 역할과 그 채널의 "
            "권한 덮어쓰기에 웹후크 관리 권한이 있는지 확인해 주세요.",
        )
        _write(conn, hook)
    return {"ok": True}


def on_removed(project_id: int, webhook_id: str) -> dict:
    """봇이 그 Discord 웹훅을 지웠다. 해제 중이면 끝내고, 정리 목록에서도 뺀다."""
    webhook_id = str(webhook_id or "")
    with transaction.atomic():
        conn = _locked(project_id)
        if conn is None:
            return {"ok": False}
        hook = dict(conn.discord_hook or {})
        cleanup = [c for c in hook.get("cleanup") or [] if c["webhook_id"] != webhook_id]
        if hook.get("state") == "removing" and hook.get("webhook_id", "") == webhook_id:
            hook = {}
        hook["cleanup"] = cleanup
        _write(conn, hook)
    return {"ok": True}
