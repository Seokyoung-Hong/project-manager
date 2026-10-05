"""GitHub 연동의 업무 규칙. 뷰·라우터에는 규칙을 두지 않는다.

권한의 경계가 둘이다.
- **태스크**는 조직 규칙으로 본다(`orgs.services.is_member`).
- **GitHub에서 온 것**은 GitHub 권한으로 본다(`can_view_repo`). 조직 멤버라도 그 저장소를
  볼 수 없으면 브랜치·PR·이슈가 보이지 않는다.

`actor=None`은 웹훅 경로에서만 쓴다. 이 파일 밖에서 `tasks.services`에 None을 넘기지 않는다.
"""

import logging
import re
from datetime import datetime, timedelta
from urllib.parse import quote, urlencode

from django.conf import settings
from django.core.cache import cache
from django.db import transaction
from django.db.models import Q
from django.utils import timezone

from common.errors import ConflictError, ServiceError
from orgs.models import TeamMembership
from orgs.services import ai_denied, is_member, orgs_of
from orgs.settings import effective
from projects.services import _log, require_level
from tasks import work_requests as wr
from tasks.models import ChangeLog, Task
from tasks.services import _log as _task_log
from tasks.services import create_task, duplicate_task, transition, update_task

from . import client
from . import notify as gh_notify
from .client import GitHubError
from .crypto import decrypt, encrypt
from .models import (
    GitEvent,
    GitHubIdentity,
    GitHubInstallation,
    GitHubTeamLink,
    RepoConnection,
    RepoIssue,
    TaskGitLink,
)

log = logging.getLogger(__name__)

REPO_TTL = timedelta(hours=6)
REPO_RETRY_SECONDS = 300
ISSUE_TTL = timedelta(minutes=10)
EVENT_KEEP = 50


# ---------- 권한 ----------


def can_view_repo(user, full_name: str) -> bool:
    """이 사람이 GitHub에서 그 저장소를 볼 수 있는가. 화면 전부가 여기를 지난다."""
    if not full_name:
        return False
    identity = getattr(user, "github", None)
    return bool(identity and full_name in (identity.repos or []))


def repo_state(user, project) -> dict:
    """패널·탭이 함께 쓰는 상태. 넷 중 하나다."""
    conn = getattr(project, "repo", None)
    if conn is None:
        return {"conn": None, "state": "none"}  # 저장소 미연결
    if getattr(user, "github", None) is None:
        return {"conn": conn, "state": "unlinked"}  # GitHub 미연결
    if not can_view_repo(user, conn.full_name):
        return {"conn": conn, "state": "denied"}  # 접근 권한 없음
    return {"conn": conn, "state": "ok"}


# ---------- 조직 설치 ----------


def is_user_install(org) -> bool:
    """개인 계정(User)에 설치됐는가. 그러면 조직 전용 기능을 끈다.

    개인 계정에는 `/orgs/*`(멤버·팀)가 없고, 저장소 하나가 곧 조직인 작은 프로젝트라
    이슈 자동 가져오기도 쓰지 않는다. account_type이 빈 옛 행은 조직으로 본다.
    """
    inst = getattr(org, "github", None)
    return inst is not None and inst.account_type == "User"


def save_installation(org, installation_id: int, *, actor) -> GitHubInstallation:
    """GET /app/installations/{id}(앱 JWT)로 계정 정보를 읽어 저장한다.

    설치 id는 Setup URL의 GET 값이라 누구나 바꿔 넣을 수 있다(순차 정수라 추측도 된다).
    "볼 수 있는 설치"(`/user/installations`)로는 부족하다 — 읽기 전용 협력자에게도 보인다.
    그러면 남의 설치를 먼저 연결해 설치 토큰으로 비공개 저장소 목록을 볼 수 있다.
    그래서 **설치 계정의 주인**만 받는다: 개인 계정이면 그 본인, 조직이면 그 조직의 활성 admin.
    다른 조직이 이미 그 설치를 쓰고 있어도 거부한다.
    """
    identity = getattr(actor, "github", None)
    if identity is None:
        raise ServiceError({"installation": "먼저 GitHub 계정을 연결하세요."})
    other = (
        GitHubInstallation.objects.filter(installation_id=installation_id).exclude(org=org).exists()
    )
    if other:
        raise ServiceError({"installation": "이 설치는 이미 다른 조직이 사용하고 있습니다."})
    data = client.request("GET", f"/app/installations/{installation_id}", client.app_jwt())
    account = data.get("account") or {}
    if not _owns_account(identity, account):
        raise ServiceError(
            {
                "installation": "설치한 GitHub 계정의 본인이나 그 GitHub 조직의 관리자(admin)만 "
                "연결할 수 있습니다."
            }
        )
    GitHubInstallation.objects.update_or_create(
        org=org,
        defaults={
            "installation_id": installation_id,
            "account_login": (account.get("login") or "")[:100],
            "account_type": (account.get("type") or "")[:20],
            "repo_selection": (data.get("repository_selection") or "")[:10],
            "installed_by": actor,
        },
    )
    return org.github


def _owns_account(identity, account: dict) -> bool:
    """이 사람이 설치 계정의 주인인가. 개인 계정은 같은 GitHub id, 조직은 활성 admin."""
    if account.get("type") == "User":
        return bool(account.get("id")) and account.get("id") == identity.github_id
    login = account.get("login") or ""
    if account.get("type") != "Organization" or not login:
        return False
    try:
        m = client.request("GET", f"/user/memberships/orgs/{quote(login)}", user_token(identity))
    except GitHubError as e:
        if e.status in (403, 404):  # 그 조직의 멤버가 아니다
            return False
        raise
    return (m or {}).get("role") == "admin" and (m or {}).get("state") == "active"


# 기능 → (권한 키, 최소 수준, 이벤트들). 권한·구독이 없으면 그 기능은 조용히 꺼진다(IMPL-PLAN-8 §0.1).
REQUIRED_CAPS = {
    "ci": ("checks", "read", ("check_suite",)),
    "ci_status": ("statuses", "read", ("status",)),
    "review": ("pull_requests", "read", ("pull_request_review",)),
    "milestone": ("issues", "read", ("milestone",)),
    "release": ("contents", "read", ("release",)),
}
PERM_LABELS = {
    "checks": "Checks",
    "statuses": "Commit statuses",
    "pull_requests": "Pull requests",
    "issues": "Issues",
    "contents": "Contents",
}
LEVELS = ("read", "write", "admin")
CAPS_TTL = 3600


def app_capabilities(org) -> dict | None:
    """GET /app/installations/{id}(앱 JWT)의 permissions·events로 기능별 사용 가능 여부. 1시간 캐시.
    설치가 없거나 GitHub 오류면 None(화면은 '확인 불가'로 그린다). 쓰는 곳: 조직 GitHub 탭(관리자).

    반환 예: {"ci": {"ok": False, "missing": ["Checks 읽기 권한", "check_suite 구독"]}, ...}
    """
    inst = GitHubInstallation.objects.filter(org=org).first()
    if inst is None:
        return None
    key = f"gh-app-caps:{inst.installation_id}"
    caps = cache.get(key)
    if caps is not None:
        return caps
    try:
        data = client.request("GET", f"/app/installations/{inst.installation_id}", client.app_jwt())
    except (GitHubError, ValueError):  # ValueError: 앱 개인키가 없거나 깨졌다
        return None
    perms = (data or {}).get("permissions") or {}
    events = set((data or {}).get("events") or [])
    caps = {}
    for feature, (perm, level, needed) in REQUIRED_CAPS.items():
        missing = []
        if perms.get(perm) not in LEVELS[LEVELS.index(level) :]:
            missing.append(f"{PERM_LABELS[perm]} 읽기 권한")
        missing += [f"{e} 구독" for e in needed if e not in events]
        caps[feature] = {"ok": not missing, "missing": missing}
    cache.set(key, caps, CAPS_TTL)
    return caps


# ---------- 사용자 토큰 ----------


def _store_tokens(identity, data: dict):
    """OAuth 응답을 암호화해 저장한다. 평문은 어디에도 남기지 않는다."""
    now = timezone.now()
    fields = []
    if data.get("access_token"):
        identity.token_enc = encrypt(data["access_token"])
        fields.append("token_enc")
        if data.get("expires_in"):
            identity.token_expires_at = now + timedelta(seconds=int(data["expires_in"]))
            fields.append("token_expires_at")
    if data.get("refresh_token"):
        identity.refresh_enc = encrypt(data["refresh_token"])
        fields.append("refresh_enc")
        if data.get("refresh_token_expires_in"):
            identity.refresh_expires_at = now + timedelta(
                seconds=int(data["refresh_token_expires_in"])
            )
            fields.append("refresh_expires_at")
    if fields:
        identity.save(update_fields=fields)


def user_token(identity) -> str:
    """살아 있는 사용자 토큰. 만료됐으면 refresh 토큰으로 갱신한다."""
    now = timezone.now()
    if identity.token_expires_at and identity.token_expires_at > now + timedelta(minutes=2):
        return decrypt(identity.token_enc)
    refresh = decrypt(identity.refresh_enc)
    if not refresh or (identity.refresh_expires_at and identity.refresh_expires_at <= now):
        raise ServiceError({"github": "GitHub 연결이 만료됐습니다. 프로필에서 다시 연결하세요."})
    data = client.refresh_user_token(refresh)
    _store_tokens(identity, data)
    return decrypt(identity.token_enc)


def sync_repos(identity) -> list[str]:
    """앱이 설치된 저장소 중 이 사람이 볼 수 있는 것. 설치마다 물어 합친다."""
    token = user_token(identity)
    names = []
    # 이 사람이 속한 조직의 설치만 묻는다. 남의 조직 설치는 어차피 403이다.
    installs = GitHubInstallation.objects.filter(
        suspended_at__isnull=True, org__in=orgs_of(identity.user)
    )
    for inst in installs:
        try:
            names += [
                r["full_name"]
                for r in client.paginate(
                    f"/user/installations/{inst.installation_id}/repositories",
                    token,
                    key="repositories",
                )
            ]
        except GitHubError as e:
            # 403·404는 그 설치에 접근 권한이 없다는 뜻이다 — 건너뛴다. 그 밖의 오류(5xx·429·
            # 네트워크)는 "볼 수 있는 저장소가 없다"가 아니다. 캐시를 빈 목록으로 덮으면
            # repo_state가 denied가 되어 GitHub 화면이 통째로 사라지므로 그대로 올린다.
            if e.status not in (403, 404):
                raise
    identity.repos = sorted(set(names))
    identity.repos_checked_at = timezone.now()
    identity.save(update_fields=["repos", "repos_checked_at"])
    return identity.repos


def refresh_github_access(request):
    """마지막 확인이 오래됐으면 다시 물어본다. 실패는 조용히 넘긴다.

    # ponytail: 요청 경로에서 GitHub를 한 번 부른다(6시간에 한 번). 느껴지면
    # GitHub 화면 첫 진입으로 미룬다.
    """
    if not settings.GITHUB_ENABLED or not request.user.is_authenticated:
        return
    identity = getattr(request.user, "github", None)
    if identity is None:
        return
    last = identity.repos_checked_at
    if last and timezone.now() - last < REPO_TTL:
        return
    # 실패해도 매 요청 다시 묻지 않는다. GitHub 장애가 모든 화면을 시간 초과만큼 붙잡기 때문이다.
    # ponytail: 프로세스별 캐시라 워커마다 한 번씩은 다시 묻는다. 거슬리면 DB에 시각을 둔다.
    retry_key = f"gh-repos-retry:{identity.pk}"
    if cache.get(retry_key):
        return
    try:
        sync_repos(identity)
    except (GitHubError, ServiceError):
        cache.set(retry_key, 1, REPO_RETRY_SECONDS)


def _free_username(login: str) -> str:
    """GitHub 로그인을 PM 아이디로 쓴다. 이미 있으면 -gh, -gh2 …를 붙인다.

    GitHub 로그인은 영문·숫자·하이픈뿐이라 Django 아이디 규칙을 그대로 통과한다.
    """
    from accounts.models import User

    base = login[:140]
    name, n = base, 1
    while User.objects.filter(username__iexact=name).exists():
        name = f"{base}-gh" if n == 1 else f"{base}-gh{n}"
        n += 1
    return name


def github_email(info: dict, token: str) -> str:
    """GitHub 주 이메일. 공개 이메일이 없으면 /user/emails를 묻는다. 권한이 없으면 빈 값."""
    if info.get("email"):
        return info["email"][:254]
    try:
        emails = client.request("GET", "/user/emails", token)
    except GitHubError:
        return ""
    primary = [e["email"] for e in emails if e.get("primary") and e.get("verified")]
    return primary[0][:254] if primary else ""


def lookalike_exists(login: str, email: str) -> bool:
    """같은 아이디나 이메일로 가입했지만 GitHub를 연결하지 않은 계정이 있는가."""
    from accounts.models import User

    q = Q(username__iexact=login)
    if email:
        q |= Q(email__iexact=email)
    return User.objects.filter(q, github__isnull=True).exists()


@transaction.atomic
def login_with_github(info: dict, token_data: dict) -> tuple:
    """GitHub 사용자 정보로 PM 사용자를 찾고, 없으면 만든다. (identity, 새로 만들었나)를 돌려준다.

    이미 연결된 GitHub 계정이면 그 사람이다. 처음 보는 계정이면 GitHub만으로 가입시킨다.
    같은 이메일·아이디의 기존 PM 계정에 자동으로 붙이지 않는다 — 남의 계정을 가로챌 수 있다.
    기존 계정을 쓰던 사람은 로그인한 뒤 프로필에서 GitHub를 연결하면 된다.
    """
    from accounts.identity import resolve
    from accounts.models import User

    github_id, login = info["id"], (info.get("login") or "")[:100]
    user = resolve("github", str(github_id))  # 비활성 사용자는 None
    if user is None and GitHubIdentity.objects.filter(github_id=github_id).exists():
        raise ServiceError({"github": "비활성화된 계정입니다. 조직 관리자에게 문의해 주세요."})
    identity = user.github if user else None
    created = identity is None
    if not created:
        if identity.login != login:
            identity.login = login
            identity.save(update_fields=["login"])
    else:
        user = User(
            username=_free_username(login or f"github-{github_id}"),
            display_name=(info.get("name") or login)[:50],
            email=info.get("email") or "",
        )
        user.set_unusable_password()  # 비밀번호 로그인은 없다. GitHub로만 들어온다.
        user.save()
        identity = GitHubIdentity.objects.create(user=user, github_id=github_id, login=login)
        backfill_actor(identity)
    _store_tokens(identity, token_data)
    return identity, created


def backfill_actor(identity):
    """이 로그인으로 남아 있던 GitHub 이력을 이 사람의 것으로 바꾼다."""
    ChangeLog.objects.filter(
        source="gh", actor__isnull=True, external_actor__iexact=identity.login
    ).update(actor_id=identity.user_id, external_actor="")
    GitEvent.objects.filter(actor_user__isnull=True, actor_login__iexact=identity.login).update(
        actor_user_id=identity.user_id
    )


# ---------- 저장소 주소 ----------


def installation_repos(org, user, *, strict=False) -> list[dict]:
    """조직의 GitHub 앱 설치가 접근할 수 있는 저장소 중 **이 사람도 볼 수 있는 것**.
    저장소 연결 화면의 자동완성이 쓴다.

    설치 토큰은 설치 범위 전부를 본다. 그대로 돌려주면 GitHub 권한이 없는 PM 멤버에게 비공개
    저장소 이름이 새므로 `can_view_repo`(그 사람의 GitHub 접근 목록)와 교집합만 낸다.

    이미 다른 프로젝트에 연결됐는지는 여기서 보지 않는다 — 호출부가 판단한다.
    설치가 없거나 GitHub가 오류를 내면 빈 목록을 돌려준다. 화면은 입력창만으로도 그대로
    동작해야 하기 때문이다.
    # ponytail: 캐시 없음. 매번 GitHub를 부르는 게 느껴지면 sync_repos처럼 checked_at을 둔다.
    """
    inst = getattr(org, "github", None)
    if inst is None:
        return []
    try:
        token = client.installation_token(inst.installation_id)
        repos = list(client.paginate("/installation/repositories", token, key="repositories"))
    except GitHubError:
        if strict:
            raise
        return []
    return [
        {
            "full_name": r["full_name"],
            "clone_url": r.get("clone_url", ""),
            "private": bool(r.get("private")),
        }
        for r in repos
        if can_view_repo(user, r["full_name"])
    ]


REPO_RE = re.compile(r"(?:github\.com[:/])([\w.-]+)/([\w.-]+?)(?:\.git)?/?$", re.I)


def parse_repo_url(url: str) -> str:
    m = REPO_RE.search((url or "").strip())
    if not m:
        raise ServiceError(
            {"url": "GitHub 저장소 주소를 넣으세요. 예: https://github.com/owner/repo.git"}
        )
    return f"{m.group(1)}/{m.group(2)}"


def _check_ai_manage_repo(org, source: str):
    """source가 mcp인데 AI 정책이 저장소 연결·해제를 막아 뒀으면 거부한다."""
    if source != "mcp":
        return
    if not effective("ai.enabled", org=org) or effective("ai.manage_repo", org=org) == "deny":
        raise ServiceError({"url": ai_denied("저장소 연결")})


def shared_repo_warning(project, full_name: str) -> str:
    """같은 조직의 다른 프로젝트가 이미 이 저장소에 이어져 있으면 경고 문구. 막지는 않는다.

    개인 계정 설치는 자동 가져오기를 끄므로 이슈가 겹쳐 생기지 않는다 — 경고하지 않는다.
    """
    if is_user_install(project.org):
        return ""
    names = list(
        RepoConnection.objects.filter(project__org=project.org, full_name__iexact=full_name)
        .exclude(project=project)
        .values_list("project__name", flat=True)
    )
    if not names:
        return ""
    return (
        f"이 저장소는 이미 {', '.join(names)} 프로젝트에 연결돼 있습니다. 두 프로젝트 모두 "
        "새 이슈 자동 가져오기를 켜면 이슈 하나가 프로젝트마다 태스크로 생깁니다."
    )


def connect_repo(
    *, project, url, actor, source: str = "web", confirm_shared: bool = True
) -> RepoConnection:
    """저장소를 프로젝트에 잇는다. 그 사람이 볼 수 있는 저장소여야 한다.

    등급·AI 정책 검사가 맨 앞이다 — MCP로도 이 함수를 부르게 될 것이므로 강제는 여기
    있어야 한다(IMPL-PLAN-4 원칙 3).
    confirm_shared=False면 다른 프로젝트와 겹치는 저장소에서 멈추고 경고를
    ServiceError({"confirm_shared": …})로 올린다 — 화면이 한 번 더 묻는 데 쓴다.
    """
    require_level(actor, project, effective("project.settings_by", org=project.org), "url")
    _check_ai_manage_repo(project.org, source)
    if not is_member(actor, project.org):
        raise ServiceError({"org": "이 조직의 멤버가 아닙니다."})
    full_name = parse_repo_url(url)
    if not can_view_repo(actor, full_name):
        raise ServiceError(
            {"url": "그 저장소에 접근할 수 없습니다. GitHub 연결과 권한을 확인하세요."}
        )
    if not confirm_shared and (warning := shared_repo_warning(project, full_name)):
        raise ServiceError({"confirm_shared": warning})
    conn, _ = RepoConnection.objects.update_or_create(
        project=project,
        defaults={"url": url.strip()[:300], "full_name": full_name, "created_by": actor},
    )
    # 저장소를 이으면 개발 도구가 기본이다(사용자 결정). 연결을 끊어도 켜진 채로 남도록 설정에 적는다.
    if (project.settings or {}).get("project.dev_tools") is not True:
        project.settings = {**(project.settings or {}), "project.dev_tools": True}
        project.save(update_fields=["settings"])
    try:
        sync_issues_if_stale(conn)
    except Exception:
        # 연결은 이미 저장됐다. 이슈는 다음 동기화에 맞춰지므로 화면을 500으로 깨지 않는다.
        log.exception("저장소 연결 직후 이슈 동기화에 실패했습니다: %s", full_name)
    return conn


REPO_SETTING_FIELDS = (
    "import_label",
    "auto_import",
    "rule_issue",
    "rule_branch",
    "rule_commit",
    "rule_pr",
    "rule_merge",
    # 라운드 8(G9): 화면 체크박스와 같은 커밋에서 넣는다. rule_sync는 §10-1로 쓰지 않는다.
    "rule_review",
    "rule_milestone",
)


def update_repo_settings(conn, changes: dict, *, actor, source: str = "web", token=None):
    """저장소 규칙·가져오기 설정을 바꾼다. connect_repo와 같은 등급·AI 검사를 받는다."""
    project = conn.project
    require_level(actor, project, effective("project.settings_by", org=project.org), "repo")
    _check_ai_manage_repo(project.org, source)
    if is_user_install(project.org):
        changes = {**changes, "auto_import": False}  # 개인 계정 설치는 자동 가져오기를 강제로 끈다
    changed = []
    for field, new in changes.items():
        if field not in REPO_SETTING_FIELDS or getattr(conn, field) == new:
            continue
        _log(project, f"repo.{field}", getattr(conn, field), new, actor, source, token)
        setattr(conn, field, new)
        changed.append(field)
    if changed:
        conn.save(update_fields=changed)
    return conn


def link_event(event, task, *, actor, source: str = "web") -> None:
    """미매칭 이벤트(예: 번호 없는 커밋)를 손으로 태스크에 잇는다. 저장소 설정과 같은 등급이다."""
    project = event.connection.project
    require_level(actor, project, effective("project.settings_by", org=project.org), "task_id")
    if task.project_id != project.pk:
        raise ServiceError({"task_id": "이 프로젝트의 태스크만 연결할 수 있습니다."})
    event.task = task
    event.save(update_fields=["task"])


def disconnect_repo(*, project, actor, source: str = "web") -> bool:
    """저장소 연결을 끊는다. connect_repo와 같은 등급·AI 검사를 받는다.

    연결이 없어도 조용히 끝낸다 — 화면의 [연결 해제] 버튼은 연결이 있을 때만 보이지만,
    두 탭이 열려 있으면 먼저 끊은 쪽이 이긴다.
    """
    require_level(actor, project, effective("project.settings_by", org=project.org), "url")
    _check_ai_manage_repo(project.org, source)
    conn = getattr(project, "repo", None)
    if conn is None:
        return False
    if (conn.discord_hook or {}).get("state") == "active":
        from . import hooks

        # GitHub 저장소의 Discord 알림 훅을 먼저 지운다(누른 사람 토큰). 실패하면 해제도 멈춘다 —
        # 연결을 지우고 나면 그 훅을 찾아 지울 길이 없다. pending·registering·error는 GitHub 훅이 없거나
        # 등록 중이라 행만 지운다: 봇의 늦은 보고는 hooks.on_created가 행 없음을 보고 보상 삭제한다.
        # ponytail: 봇이 지울 Discord 쪽 웹훅은 연결 행과 함께 사라져 채널에 남는다(GitHub 훅이 없어 조용하다).
        # 남는 게 문제가 되면 정리 작업을 연결 밖(프로젝트)에 두는 표를 만든다.
        hooks.remove(project, actor=actor, source=source)
    conn.delete()
    return True


def continuation(task) -> dict:
    """재개(PR·이슈 reopened, §4)로 이어진 계열. 원 태스크의 `reopened_as` 이력이 근거다.

    {"by": 이 태스크를 이어받은 가장 최근 새 태스크 | None, "from": 이 태스크가 이어받은 원 태스크 | None}.
    둘 다 같은 프로젝트 안이라 가시성은 태스크와 같다.
    """
    by = from_ = None
    log = (
        ChangeLog.objects.filter(target_type="task", target_id=task.pk, field="reopened_as")
        .order_by("-id")
        .first()
    )
    if log:
        num = log.new_value.removeprefix("TASK-")
        by = Task.objects.filter(project=task.project, pk=num).first() if num.isdecimal() else None
    src = (
        ChangeLog.objects.filter(field="reopened_as", new_value=task.number, target_type="task")
        .order_by("-id")
        .first()
    )
    if src:
        from_ = Task.objects.filter(project=task.project, pk=src.target_id).first()
    return {"by": by, "from": from_}


# ---------- 이벤트 공통 ----------


def parse_ts(value) -> datetime:
    """GitHub의 ISO 8601을 읽는다. Z는 fromisoformat이 못 읽으므로 바꾼다."""
    if not value:
        return timezone.now()
    try:
        return datetime.fromisoformat(str(value).replace("Z", "+00:00"))
    except ValueError:
        return timezone.now()


def user_for_sender(payload: dict):
    """payload.sender가 PM 사용자면 그 사람. 아니면 None."""
    sender = payload.get("sender") or {}
    gid = sender.get("id")
    if not gid:
        return None
    identity = GitHubIdentity.objects.filter(github_id=gid).select_related("user").first()
    return identity.user if identity and identity.user.is_active else None


def record_event(conn, delivery, *, kind, payload, summary, task=None, result=""):
    """이벤트 한 줄을 남기고 연결당 최근 EVENT_KEEP건만 유지한다.

    delivery_id는 f"{delivery}:{conn.pk}"다. 한 저장소를 두 프로젝트가 가리킬 수 있어
    delivery 하나에 행이 여럿 생기기 때문이다.
    # ponytail: 표 하나에 잘라 둔다. 감사 로그가 필요해지면 보관 정책으로 바꾼다.
    """
    sender = payload.get("sender") or {}
    event = GitEvent.objects.create(
        connection=conn,
        delivery_id=f"{delivery}:{conn.pk}"[:64],
        occurred_at=_occurred_at(kind, payload),
        kind=kind,
        actor_login=(sender.get("login") or "")[:100],
        actor_user=user_for_sender(payload),
        summary=summary[:200],
        task=task,
        result=result[:100],
    )
    conn.last_event_at = event.occurred_at
    conn.save(update_fields=["last_event_at"])
    keep = conn.events.order_by("-occurred_at", "-id").values_list("pk", flat=True)[:EVENT_KEEP]
    conn.events.exclude(pk__in=list(keep)).delete()
    return event


def _occurred_at(kind: str, payload: dict) -> datetime:
    if kind == "push":
        return parse_ts((payload.get("head_commit") or {}).get("timestamp"))
    if kind == "pull_request":
        return parse_ts((payload.get("pull_request") or {}).get("updated_at"))
    if kind == "issues":
        return parse_ts((payload.get("issue") or {}).get("updated_at"))
    if kind == "pull_request_review":
        return parse_ts((payload.get("review") or {}).get("submitted_at"))
    if kind == "check_suite":
        return parse_ts((payload.get("check_suite") or {}).get("updated_at"))
    if kind == "status":
        return parse_ts(payload.get("updated_at"))
    if kind == "release":
        return parse_ts((payload.get("release") or {}).get("published_at"))
    if kind == "milestone":
        return parse_ts((payload.get("milestone") or {}).get("updated_at"))
    return timezone.now()


# ---------- 웹훅 진입점 ----------


def handle_event(event: str, delivery: str, payload: dict) -> tuple[int, dict]:
    if event in ("installation", "installation_repositories"):
        _installation_event(event, payload)
        return 200, {"ok": True}
    if event == "membership":
        _on_membership(payload)
    elif event == "team":
        _on_team(payload)
    full_name = ((payload.get("repository") or {}).get("full_name")) or ""
    conns = list(
        RepoConnection.objects.filter(full_name__iexact=full_name).select_related(
            "project", "project__org"
        )
    )
    if not conns:
        return 202, {"ignored": "연결되지 않은 저장소"}
    # delivery_id는 연결마다 f"{delivery}:{conn.pk}"로 저장되므로 접두어로 찾는다.
    if delivery and GitEvent.objects.filter(delivery_id__startswith=f"{delivery}:").exists():
        return 200, {"ok": True, "duplicate": True}
    handler = _handlers().get(event)
    if handler is None:
        for conn in conns:
            if event in ("membership", "team"):
                record_event(
                    conn, delivery, kind=event, payload=payload, summary=_short(event, payload)
                )
        return 202, {"ignored": event}
    for conn in conns:  # 한 저장소를 두 프로젝트가 가리킬 수 있다
        # 연결마다 따로 묶는다. 한 연결의 실패(보관 프로젝트, 비활성 담당자 …)가 웹훅 전체를
        # 400으로 만들면 앞 연결만 반영되고, 재전송은 중복으로 버려져 뒤 연결은 영영 빠진다.
        try:
            with transaction.atomic():
                handler(conn, delivery, payload)
        except ServiceError as e:
            _record_failure(conn, delivery, event, payload, " ".join(map(str, e.errors.values())))
        except ConflictError:
            _record_failure(conn, delivery, event, payload, "다른 변경과 충돌")
    return 200, {"ok": True}


def _handlers() -> dict:
    """이벤트 → 처리기. 새 처리기 파일이 services를 import하므로 늦게 묶는다(순환 import 회피)."""
    from . import ci, sync

    return {
        "create": _on_create,
        "push": _on_push,
        "pull_request": _on_pr,
        "issues": _on_issues,
        "pull_request_review": _on_pr_review,
        "check_suite": ci.on_check_suite,
        "status": ci.on_status,
        "milestone": sync.on_milestone,
        "release": sync.on_release,
    }


def record_ignored(conn, delivery, event, payload):
    """받았지만 아직 처리하지 않는 이벤트. 들어왔다는 사실만 남긴다(G0 골격)."""
    record_event(
        conn, delivery, kind=event, payload=payload, summary=_short(event, payload), result="무시"
    )


def _record_failure(conn, delivery, event, payload, reason):
    record_event(
        conn,
        delivery,
        kind=event,
        payload=payload,
        summary=_short(event, payload),
        result=f"실패: {reason}",
    )


def _on_membership(payload: dict):
    """GitHub 팀 멤버 추가·제거 → PM TeamMembership. 저장소가 없는 조직 수준 이벤트라
    RepoConnection과 무관하게 처리한다.
    """
    action = payload.get("action")
    gh_team_id = (payload.get("team") or {}).get("id")
    gh_member_id = (payload.get("member") or {}).get("id")
    if action not in ("added", "removed") or not gh_team_id or not gh_member_id:
        return
    link = GitHubTeamLink.objects.filter(github_team_id=gh_team_id).select_related("team").first()
    if link is None:
        return
    identity = GitHubIdentity.objects.filter(github_id=gh_member_id).select_related("user").first()
    if identity is None or not is_member(identity.user, link.team.org):
        return  # 조직 멤버가 아니면 아무것도 하지 않는다(이벤트에만 남는다)
    if action == "added":
        TeamMembership.objects.get_or_create(team=link.team, user=identity.user)
    else:
        TeamMembership.objects.filter(team=link.team, user=identity.user).delete()


def _on_team(payload: dict):
    """GitHub 팀 수정·삭제 → GitHubTeamLink. 삭제해도 PM 팀은 남긴다."""
    action = payload.get("action")
    team_data = payload.get("team") or {}
    gh_team_id = team_data.get("id")
    if not gh_team_id:
        return
    link = GitHubTeamLink.objects.filter(github_team_id=gh_team_id).first()
    if link is None:
        return
    if action == "edited":
        link.slug = (team_data.get("slug") or link.slug)[:100]
        link.name = (team_data.get("name") or link.name)[:100]
        link.save(update_fields=["slug", "name"])
    elif action == "deleted":
        link.delete()


def _short(event: str, payload: dict) -> str:
    action = payload.get("action") or ""
    return f"{event} {action}".strip()


def _installation_event(event: str, payload: dict):
    inst_id = ((payload.get("installation") or {}).get("id")) or 0
    if not inst_id:
        return
    inst = GitHubInstallation.objects.filter(installation_id=inst_id).first()
    if event == "installation_repositories":
        # 저장소 범위가 바뀌었다. 모두의 캐시를 비워 다음 접속에 다시 묻게 한다.
        GitHubIdentity.objects.update(repos_checked_at=None)
        return
    action = payload.get("action") or ""
    if action == "new_permissions_accepted":
        cache.delete_many(
            [f"gh-app-caps:{inst_id}", f"gh-app-hooks:{inst_id}"]
        )  # 재승인 → 다시 묻는다
        return
    if inst is None:
        return
    if action == "deleted":
        inst.delete()
    elif action == "suspend":
        inst.suspended_at = timezone.now()
        inst.save(update_fields=["suspended_at"])
    elif action == "unsuspend":
        inst.suspended_at = None
        inst.save(update_fields=["suspended_at"])


# ---------- 자동 전환 규칙 ----------

TASK_RE = re.compile(r"TASK-(\d+)(?::(\d+))?", re.I)
COMMIT_KEEP = 100


def _find_task(conn, *texts):
    """연결된 프로젝트 안에서만 찾는다. 다른 프로젝트 번호를 적어도 움직이지 않는다."""
    for text in texts:
        for m in TASK_RE.finditer(text or ""):
            task = Task.objects.filter(pk=int(m.group(1)), project=conn.project).first()
            if task:
                return task, (int(m.group(2)) if m.group(2) else None)
    return None, None


def _reason(e) -> str:
    errors = getattr(e, "errors", None)
    if isinstance(errors, dict) and errors:
        first = next(iter(errors.values()))
        return str(first)[:100]
    return type(e).__name__


def _apply(task, status, *, actor, actor_login, note=""):
    """규칙이 상태를 바꾸는 유일한 통로. 실패해도 연결은 남기고 사유만 기록한다."""
    if task.status == status:
        return "변경 없음"
    if not task.is_open:
        # 완료·취소한 태스크를 GitHub 이벤트가 다시 열지 않는다.
        return "닫힌 태스크"
    try:
        transition(
            task,
            status,
            actor=actor,
            source="gh",
            reason=note,
            expected_version=task.version,
            external_actor=actor_login,
        )
        return dict(Task.STATUSES)[status]
    except (ServiceError, ConflictError) as e:
        return _reason(e)


def _link_for(conn, task) -> TaskGitLink:
    link, _ = TaskGitLink.objects.get_or_create(task=task, defaults={"connection": conn})
    if link.connection_id != conn.pk:
        link.connection = conn
        link.save(update_fields=["connection"])
    return link


def _sender_login(payload) -> str:
    return ((payload.get("sender") or {}).get("login")) or ""


# ---- create (브랜치) ----


def _on_create(conn, delivery, payload):
    if payload.get("ref_type") != "branch":
        return
    branch = payload.get("ref") or ""
    task, _ = _find_task(conn, branch)
    if not conn.rule_branch or task is None:
        record_event(
            conn,
            delivery,
            kind="create",
            payload=payload,
            summary=f"브랜치 {branch}",
            task=task,
            result="규칙 꺼짐" if task is not None else "연결 안 됨",
        )
        return
    link = _link_for(conn, task)
    link.branch = branch[:200]
    link.save(update_fields=["branch"])
    result = _apply(
        task, "doing", actor=user_for_sender(payload), actor_login=_sender_login(payload)
    )
    record_event(
        conn,
        delivery,
        kind="create",
        payload=payload,
        summary=f"브랜치 {branch}",
        task=task,
        result=result,
    )


# ---- push (커밋) ----


def _on_push(conn, delivery, payload):
    branch = (payload.get("ref") or "").removeprefix("refs/heads/")
    commits = payload.get("commits") or []
    matched = 0
    last_task = None
    for c in commits:
        message = c.get("message") or ""
        task, item = _find_task(conn, message, branch)
        if task is None:
            continue
        last_task = task
        matched += 1
        if not conn.rule_commit:
            continue
        link = _link_for(conn, task)
        entry = {
            "sha": (c.get("id") or "")[:40],
            "message": message.splitlines()[0][:200] if message else "",
            "item": item,
            "at": (c.get("timestamp") or ""),
        }
        # ponytail: JSON 목록 100건. 커밋 전체 이력이 필요해지면 별도 표로.
        # 같은 커밋이 여러 브랜치로 다시 push되면 sha가 같다. 한 번만 쌓는다.
        if not any(entry["sha"] and x.get("sha") == entry["sha"] for x in link.commits or []):
            link.commits = ([*(link.commits or []), entry])[-COMMIT_KEEP:]
            link.save(update_fields=["commits"])
        if item:
            _check_item(task, item)
    record_event(
        conn,
        delivery,
        kind="push",
        payload=payload,
        summary=f"{branch} 커밋 {len(commits)}건",
        task=last_task,
        result=(f"{matched}건 연결" if matched else "연결 안 됨"),
    )


def _check_item(task, position: int):
    """TASK-147:2 → 체크리스트 2번째(1부터 센다)를 체크한다."""
    item = task.checklist.all()[position - 1 : position].first()
    if item and not item.is_done:
        item.is_done = True
        item.save(update_fields=["is_done"])


# ---- pull_request ----


PR_ACTIONS = (
    "opened",
    "closed",
    "reopened",
    "ready_for_review",
    "converted_to_draft",
    "synchronize",
    "edited",
    "review_requested",
    "review_request_removed",
)


def _pr_link(conn, number):
    """같은 PR에 링크가 여럿(재개로 생긴 새 태스크)이면 열린 태스크 우선, 없으면 최신."""
    links = list(
        TaskGitLink.objects.filter(connection=conn, pr_number=number)
        .select_related("task", "task__project", "task__assignee")
        .order_by("-task_id")
    )
    return next((lk for lk in links if lk.task.is_open), links[0] if links else None)


def _pr_rule(conn, action, merged):
    if action == "closed":
        return conn.rule_merge if merged else conn.rule_pr
    if action in ("review_requested", "review_request_removed"):
        return conn.rule_review
    if action in ("synchronize", "edited"):
        return True  # 상태를 바꾸지 않는다 — 링크 정보만 갱신
    return conn.rule_pr


def _on_pr(conn, delivery, payload):
    action = payload.get("action") or ""
    pr = payload.get("pull_request") or {}
    branch = ((pr.get("head") or {}).get("ref")) or ""
    number = pr.get("number")
    summary = f"PR #{number} {action}"
    # 이미 이어진 PR은 그 링크가 기준이다(재개로 이어진 열린 태스크 우선). 제목에서 TASK 번호를
    # 지워도 연결이 끊기지 않는다. 번호 탐색은 처음 연결할 때만 한다.
    linked = _pr_link(conn, number) if number else None
    if linked is not None:
        task = linked.task
    else:
        task, _ = _find_task(conn, pr.get("title") or "", pr.get("body") or "", branch)
    if task is None or action not in PR_ACTIONS:
        record_event(
            conn,
            delivery,
            kind="pull_request",
            payload=payload,
            summary=summary,
            task=task,
            result="연결 안 됨" if task is None else "무시",
        )
        return
    merged = bool(pr.get("merged"))
    draft = bool(pr.get("draft"))
    rule_on = _pr_rule(conn, action, merged)
    if action == "reopened" and not task.is_open:
        if rule_on:
            reopen_as_new(conn, delivery, payload, old=task, kind="pr")
        else:
            record_event(
                conn,
                delivery,
                kind="pull_request",
                payload=payload,
                summary=summary,
                task=task,
                result="규칙 꺼짐",
            )
        return
    now = timezone.now()
    link = _link_for(conn, task)
    link.pr_number = number
    link.pr_title = (pr.get("title") or "")[:300]
    link.pr_state = "merged" if merged else ("closed" if action == "closed" else "open")
    link.pr_draft = draft
    head_sha = ((pr.get("head") or {}).get("sha")) or ""
    if head_sha:
        link.head_sha = head_sha[:40]
    if merged:
        link.merged_at = parse_ts(pr.get("merged_at"))
    if branch and not link.branch:
        link.branch = branch[:200]
    if action == "opened":
        link.pr_opened_at = parse_ts(pr.get("created_at"))
        if not draft:
            link.review_requested_at = now
    elif action == "ready_for_review" and link.review_requested_at is None:
        link.review_requested_at = now
    elif action == "review_requested":
        link.review_requested_at = now
    elif action == "synchronize":
        # 새 커밋: CI는 새 sha 기준으로 다시 모은다. 변경 요청 뒤의 푸시는 새 검토 라운드다.
        link.ci_checks, link.ci_state = {}, ""
        if link.review_state == "changes_requested":
            link.review_requested_at, link.reviewed_at = now, None
    link.save()
    url = pr.get("html_url") or ""
    if action == "opened":
        gh_notify.channel(conn, "pr_opened", f"🔀 PR #{number} 열림", task, url)
    elif merged:
        gh_notify.channel(conn, "pr_merged", f"🔀 PR #{number} 병합", task, url)
    if not rule_on:
        record_event(
            conn,
            delivery,
            kind="pull_request",
            payload=payload,
            summary=summary,
            task=task,
            result="규칙 꺼짐",
        )
        return
    result = "기록만"
    actor = user_for_sender(payload)
    login = _sender_login(payload)
    if action in ("opened", "reopened"):
        result = _apply(task, "doing" if draft else "review", actor=actor, actor_login=login)
    elif action == "ready_for_review":
        result = _apply(task, "review", actor=actor, actor_login=login)
    elif action == "converted_to_draft" and task.status == "review":
        result = _apply(task, "doing", actor=actor, actor_login=login)
    elif merged:
        result = _apply(task, "done", actor=actor, actor_login=login)
    elif action in ("review_requested", "review_request_removed"):
        result = _pr_reviewer(task, payload, number, adding=action == "review_requested")
    record_event(
        conn,
        delivery,
        kind="pull_request",
        payload=payload,
        summary=summary,
        task=task,
        result=result,
    )


def _pr_reviewer(task, payload, number, *, adding: bool) -> str:
    """GitHub 리뷰 요청 ↔ 태스크 검토자. 팀 리뷰어는 무시한다. 조직 멤버·가시성·본인 검토 검사는
    update_task가 한다 — 비공개 프로젝트를 못 보는 사람은 거기서 거부되고 사유가 남는다."""
    gid = (payload.get("requested_reviewer") or {}).get("id")
    if not gid:
        return "팀 리뷰어 무시"
    identity = GitHubIdentity.objects.filter(github_id=gid).select_related("user").first()
    user = identity.user if identity and identity.user.is_active else None
    if user is None:
        return "PM 사용자 아님"
    if (task.reviewer_id == user.pk) == adding:
        return "변경 없음"
    try:
        update_task(
            task,
            {"reviewer": user if adding else None},
            actor=user_for_sender(payload),
            source="gh",
            expected_version=task.version,
            external_actor=_sender_login(payload),
        )
    except (ServiceError, ConflictError) as e:
        return _reason(e)
    if not adding:
        return "검토자 해제"
    gh_notify.dm(task, user, f"👀 PR #{number} 리뷰 요청")
    return f"검토자 {user.display_name}"


# ---- pull_request_review ----

REVIEW_STATES = ("approved", "changes_requested", "commented")


def _review_state(reviews: dict) -> str:
    values = {v.get("state") if isinstance(v, dict) else v for v in reviews.values()}
    if "changes_requested" in values:
        return "changes_requested"
    return "approved" if "approved" in values else ""


def _on_pr_review(conn, delivery, payload):
    """pull_request_review submitted|dismissed|edited. 태스크는 pr_number로 찾는다(제목 재탐색 안 함)."""
    action = payload.get("action") or ""
    review = payload.get("review") or {}
    number = (payload.get("pull_request") or {}).get("number")
    state = (review.get("state") or "").lower()
    summary = f"PR #{number} 리뷰 {state or action}"
    link = _pr_link(conn, number)
    if link is None:
        record_event(
            conn,
            delivery,
            kind="pull_request_review",
            payload=payload,
            summary=summary,
            result="연결 안 됨",
        )
        return
    # 같은 PR의 리뷰가 동시에 와도 JSON 갱신을 잃지 않게 링크 행을 잠근다.
    link = TaskGitLink.objects.select_for_update().select_related("task").get(pk=link.pk)
    task = link.task
    login = ((review.get("user") or {}).get("login")) or ""
    reviews = dict(link.reviews or {})
    prev = reviews.get(login)
    prev = prev if isinstance(prev, dict) else {"state": prev}  # 옛 행: 순서 정보 없음
    rid, at = review.get("id"), parse_ts(review.get("submitted_at")).isoformat()
    if action == "dismissed":
        # 철회는 그 리뷰에만 걸린다. 뒤늦게 온 옛 리뷰의 철회가 새 리뷰를 지우면 안 된다.
        if prev.get("id") in (None, rid):
            reviews.pop(login, None)
    elif action == "submitted" and state in REVIEW_STATES and login:
        if prev.get("at") and (at, rid or 0) <= (prev["at"], prev.get("id") or 0):
            # 늦게 도착한 옛 리뷰. 최신 리뷰를 덮지도, 상태를 바꾸지도 않는다.
            record_event(
                conn,
                delivery,
                kind="pull_request_review",
                payload=payload,
                summary=summary,
                task=task,
                result="오래된 리뷰 무시",
            )
            return
        # 코멘트 리뷰는 GitHub에서도 앞선 승인·변경 요청을 지우지 않는다(시각만 앞으로 민다).
        kept = prev.get("state") if state == "commented" and prev.get("state") else state
        reviews[login] = {"state": kept, "id": rid, "at": at}
        if state != "commented":
            link.reviewed_at = parse_ts(review.get("submitted_at"))
    link.reviews = reviews
    link.review_state = _review_state(reviews)
    link.save(update_fields=["reviews", "review_state", "reviewed_at"])
    result = "기록만"
    if action == "submitted" and state == "changes_requested":
        if not conn.rule_review:
            result = "규칙 꺼짐"
        elif task.status == "review":
            # 반려 권한(지정 검토자·관리자)은 PM 규칙이다. GitHub에서 변경을 요청할 수 있었다면
            # 그걸로 충분하다 — 머지처럼 웹훅 경로(actor=None)로 돌린다.
            result = _apply(
                task, "doing", actor=None, actor_login=login, note=f"PR #{number} 변경 요청"
            )
        gh_notify.dm(task, task.assignee, f"✏️ PR #{number} 변경 요청")
        gh_notify.channel(conn, "pr_changes", f"✏️ PR #{number} 변경 요청", task)
    elif action == "submitted" and state == "approved":
        gh_notify.dm(task, task.assignee, f"✅ PR #{number} 승인")
    record_event(
        conn,
        delivery,
        kind="pull_request_review",
        payload=payload,
        summary=summary,
        task=task,
        result=result,
    )


# ---- 재개 = 신규 태스크(IMPL-PLAN-8 §4) ----


def reopen_as_new(conn, delivery, payload, *, old, kind: str) -> Task | None:
    """닫힌 태스크에 연결된 PR·이슈가 다시 열렸다. 원 태스크는 두고 계열(parent)로 이어지는 새 태스크를
    만들어 그 PR·이슈에 잇는다. 담당자는 원 담당자이고, 그 사람에게 담당 요청을 보내 수락·거절하게
    한다(§10-3). 같은 번호에 열린 태스크가 이미 있으면 그것을 돌려주고 만들지 않는다.
    """
    is_pr = kind == "pr"
    event = "pull_request" if is_pr else "issues"
    item = (payload.get("pull_request") if is_pr else payload.get("issue")) or {}
    number = item.get("number")
    label = "PR" if is_pr else "이슈"
    summary = f"{label} #{number} reopened"
    field = "pr_number" if is_pr else "issue_number"
    # 같은 PR·이슈의 reopen이 동시에 와도 새 태스크는 하나만. 원 태스크 행을 잠그면 뒤에 온 쪽은
    # 앞쪽이 커밋할 때까지 기다렸다가 아래 조회에서 그 태스크를 본다.
    Task.objects.select_for_update().filter(pk=old.pk).first()
    existing = (
        TaskGitLink.objects.filter(connection=conn, **{field: number}, task__status__in=Task.OPEN)
        .select_related("task")
        .first()
    )
    if existing:
        record_event(
            conn,
            delivery,
            kind=event,
            payload=payload,
            summary=summary,
            task=existing.task,
            result="이미 재개됨",
        )
        return existing.task
    login = _sender_login(payload)
    # created_by가 NOT NULL이라 None일 수 없다. source="gh"라 담당자는 그대로 정해진다.
    actor = _import_actor(conn, payload) or old.assignee
    note = f"{label} #{number} 재개"
    new = duplicate_task(
        old,
        actor=actor,
        source="gh",
        title=old.title,
        due_date=None,
        no_due_reason=f"{note}로 생성",
        assignee=old.assignee,
        notify_assignee=False,  # 담당 요청(또는 재개 DM) 한 통으로 알린다
    )
    src = TaskGitLink.objects.filter(task=old).first()
    link = _link_for(conn, new)
    if src is not None:
        link.issue_number = src.issue_number
        link.issue_title = src.issue_title
        link.issue_state = src.issue_state
        link.branch = src.branch
    if is_pr:
        link.pr_number = number
        link.pr_title = (item.get("title") or "")[:300]
        link.pr_state = "open"
        link.pr_draft = bool(item.get("draft"))
        link.head_sha = (((item.get("head") or {}).get("sha")) or "")[:40]
        link.pr_opened_at = src.pr_opened_at if src else None
        link.review_requested_at = None if link.pr_draft else timezone.now()
    else:
        link.issue_number = number
        link.issue_title = (item.get("title") or link.issue_title)[:300]
        link.issue_state = "open"
        # 이슈 하나는 열린 태스크 하나만 가리킨다.
        RepoIssue.objects.filter(connection=conn, number=number).update(task=new)
    link.save()
    if is_pr:
        # draft면 기한이 없어 "기한…" 사유로 todo에 남는다. 사람이 기한을 넣고 시작한다.
        _apply(
            new,
            "doing" if link.pr_draft else "review",
            actor=user_for_sender(payload),
            actor_login=login,
        )
    _task_log(old, "reopened_as", "", new.number, actor, "gh", note=note, external_actor=login)
    head = f"🔁 {label} #{number} 재개 → {new.number} 생성"
    if actor != new.assignee:
        # 원 담당자가 다시 맡을지 정한다. 담당 요청 알림 하나에 재개 안내를 담으므로 재개 DM은 따로 없다.
        wr.request_assign(new, new.assignee, actor, "gh", note=f"{note} — {old.number}에서 이어짐")
    else:
        gh_notify.dm(new, new.assignee, head)  # 본인이 다시 열었으면 담당 요청 없이 DM만
    gh_notify.channel(conn, "reopened", head, new)
    record_event(
        conn,
        delivery,
        kind=event,
        payload=payload,
        summary=summary,
        task=new,
        result=f"{new.number} 생성",
    )
    return new


# ---- issues ----


def _import_actor(conn, payload):
    """행위자: sender가 PM 사용자면 그 사람 → 프로젝트 첫 관리자 → 없으면 None(가져오지 않는다)."""
    sender = user_for_sender(payload)
    if sender is not None:
        return sender
    return conn.project.owners.filter(is_active=True).order_by("id").first()


def _assigned_member(conn, issue):
    """이슈에 배정된 사람이 GitHub를 연결한 조직 멤버면 그 사용자, 아니면 None.

    자동 가져오기의 문턱이다. 이슈는 저장소를 볼 수 있는 누구나 열 수 있지만 배정은 협업자만
    할 수 있다. 배정을 요구하지 않으면 공개 저장소에서 이슈만 열어도 PM에 태스크가 쌓인다.
    """
    login = ((issue.get("assignee") or {}).get("login")) or ""
    if not login:
        return None
    identity = GitHubIdentity.objects.filter(login__iexact=login).select_related("user").first()
    if identity and identity.user.is_active and is_member(identity.user, conn.project.org):
        return identity.user
    return None


def _on_issues(conn, delivery, payload):
    action = payload.get("action") or ""
    issue = payload.get("issue") or {}
    number = issue.get("number")
    labels = [lb["name"] for lb in (issue.get("labels") or []) if isinstance(lb, dict)]
    row, _ = RepoIssue.objects.update_or_create(
        connection=conn,
        number=number,
        defaults={
            "title": (issue.get("title") or "")[:300],
            # action이 아니라 payload의 상태를 따른다. 닫힌 이슈에 온 labeled·edited가 다시 열면 안 된다.
            "state": issue.get("state")
            if issue.get("state") in ("open", "closed")
            else ("closed" if action == "closed" else "open"),
            "assignee_login": ((issue.get("assignee") or {}).get("login")) or "",
            "author_login": ((issue.get("user") or {}).get("login")) or "",
            "body": (issue.get("body") or "")[:5000],
            "labels": labels,
        },
    )
    summary = f"이슈 #{number} {action}"
    result = "기록만"
    task = row.task
    if action == "closed" and row.task and row.task.is_open and conn.rule_issue:
        result = _apply(
            row.task, "done", actor=user_for_sender(payload), actor_login=_sender_login(payload)
        )
        task = row.task
    elif action == "reopened" and row.task and not row.task.is_open:
        if conn.rule_issue:
            # 닫힌 태스크는 되살리지 않고 계열로 이어지는 새 태스크를 만든다(§4).
            reopen_as_new(conn, delivery, payload, old=row.task, kind="issue")
            _mark_issues_synced(conn)
            return
        result = "규칙 꺼짐"
    elif (
        action == "opened"
        and conn.rule_issue
        and conn.auto_import
        and not is_user_install(conn.project.org)
    ):
        if row.task_id is not None:
            result = "이미 가져옴"
        elif conn.import_label and conn.import_label not in labels:
            result = "라벨 불일치"
        else:
            member = _assigned_member(conn, issue)
            if member is None:
                # 배정되지 않은 이슈는 자동으로 가져오지 않는다. 기록만 남기고, 필요하면
                # 저장소 탭에서 사람이 [태스크로 가져오기]를 누른다.
                result = "담당자 미배정 · 가져오지 않음"
            else:
                # 행위자: sender가 PM 사용자면 그 사람 → 프로젝트 첫 관리자 → 배정된 멤버.
                # 배정된 멤버가 있는 한 행위자가 비어 막히는 일은 없다.
                actor = _import_actor(conn, payload) or member
                task = create_task(
                    project=conn.project,
                    title=(issue.get("title") or "")[:200],
                    actor=actor,
                    source="gh",
                    assignee=member,
                    description=(issue.get("body") or "")[:2000],
                    # GitHub 이슈에는 기한이 없다. create_task는 열린 태스크에 기한이나
                    # 사유 중 하나를 요구하므로 고정 사유를 채운다.
                    no_due_reason="GitHub 이슈로 가져옴",
                )
                row.task = task
                row.save(update_fields=["task"])
                link = _link_for(conn, task)
                link.issue_number = number
                link.issue_title = (issue.get("title") or "")[:300]
                link.issue_state = "open"
                link.save(update_fields=["issue_number", "issue_title", "issue_state"])
                result = f"태스크 {task.number} 생성"
                gh_notify.channel(
                    conn, "issue_imported", f"📥 이슈 #{number} → {task.number} 가져옴", task
                )
    if row.task:
        link = TaskGitLink.objects.filter(task=row.task).first()
        if link:
            link.issue_state = row.state
            link.save(update_fields=["issue_state"])
    _mark_issues_synced(conn)
    record_event(
        conn,
        delivery,
        kind="issues",
        payload=payload,
        summary=summary,
        task=task,
        result=result,
    )


def sync_issues(conn) -> int:
    """열린 이슈를 RepoIssue에 맞춘다. PR은 이슈 API에도 섞여 오므로 뺀다.

    설치 토큰으로 읽는다 — 이 토큰은 읽기에만 쓴다. 이슈가 100건을 넘어도 끝까지 읽는다:
    한 페이지만 읽으면 나머지가 화면에서 사라질 뿐 아니라 아래 쓸기에 닫힌 것으로 찍힌다.

    라벨 필터(import_label)는 걸지 않는다 — 그건 자동 가져오기 문턱이지 조회 범위가 아니다.
    여기서 걸면 라벨 없는 이슈가 쓸기에 닫힌 것으로 찍혀 다음 조회부터 사라진다.
    """
    inst = getattr(conn.project.org, "github", None)
    if inst is None:
        raise ServiceError({"github": "조직에 GitHub 앱이 설치되지 않았습니다."})
    token = client.installation_token(inst.installation_id)
    seen = set()
    for item in client.paginate(f"/repos/{conn.full_name}/issues?state=open", token):
        if "pull_request" in item:
            continue
        seen.add(item["number"])
        RepoIssue.objects.update_or_create(
            connection=conn,
            number=item["number"],
            defaults={
                "title": item["title"][:300],
                "state": "open",
                "assignee_login": ((item.get("assignee") or {}).get("login")) or "",
                "author_login": ((item.get("user") or {}).get("login")) or "",
                "body": (item.get("body") or "")[:5000],
                "labels": [lb["name"] for lb in item.get("labels", []) if isinstance(lb, dict)],
            },
        )
    conn.issues.filter(state="open").exclude(number__in=seen).update(state="closed")
    _mark_issues_synced(conn)
    return len(seen)


def import_issue(issue, actor, *, source="web"):
    """이슈를 내 태스크로. 이미 가져온 이슈면 그 태스크를 그대로 돌려준다.

    저장소 탭과 조직 이슈 뷰어가 같은 함수를 부른다 — 두 곳에서 각자 만들면 링크를 거는 방식이
    갈라진다. GitHub 이슈에는 기한이 없으므로 고정 사유를 채운다(`create_task`가 열린 태스크에
    기한이나 사유 중 하나를 요구한다).
    """
    with transaction.atomic():
        # 두 사람이 동시에 누르면 태스크가 둘 생긴다. 행을 잠근 뒤 다시 본다.
        issue = RepoIssue.objects.select_for_update().select_related("connection").get(pk=issue.pk)
        if issue.task_id is not None:
            return issue.task
        return _import_locked(issue, actor, source)


def _import_locked(issue, actor, source):
    conn = issue.connection
    task = create_task(
        project=conn.project,
        title=issue.title[:200],
        actor=actor,
        source=source,
        assignee=actor,
        description=(issue.body or "")[:2000],
        no_due_reason="GitHub 이슈로 가져옴",
    )
    issue.task = task
    issue.save(update_fields=["task"])
    link, _ = TaskGitLink.objects.get_or_create(task=task, defaults={"connection": conn})
    link.connection = conn
    link.issue_number = issue.number
    link.issue_title = issue.title
    link.issue_state = issue.state
    link.save(update_fields=["connection", "issue_number", "issue_title", "issue_state"])
    return task


def org_issues(org, *, repo_id=None, imported=None, query=""):
    """조직에 연결된 저장소 전부의 열린 이슈. 이슈 뷰어가 쓴다.

    프로젝트 저장소 탭은 저장소 하나만 보여 준다. 사람은 "내가 지금 무엇을 가져갈 수 있나"를
    조직 단위로 보고 싶어 하므로 한 화면에 모은다.
    """
    qs = (
        RepoIssue.objects.filter(connection__project__org=org, state="open")
        .select_related("connection", "connection__project", "task")
        .order_by("connection__full_name", "-number")
    )
    if repo_id:
        qs = qs.filter(connection_id=repo_id)
    if imported is True:
        qs = qs.exclude(task=None)
    elif imported is False:
        qs = qs.filter(task=None)
    if query:
        qs = qs.filter(Q(title__icontains=query) | Q(body__icontains=query))
    return qs


def sync_org_issues(org, *, failures=None) -> tuple[int, int]:
    """조직의 모든 연결 저장소를 한 번에 새로 고친다. 실패한 저장소는 건너뛴다.

    조회 화면이 "0건"과 "전부 실패"를 구분해서 말할 수 있도록 실패한 저장소 수도 함께 돌려준다.
    """
    total = failed = 0
    for conn in RepoConnection.objects.filter(project__org=org).select_related("project"):
        try:
            total += sync_issues(conn)
        except (ServiceError, GitHubError) as error:
            failed += 1
            if failures is not None:
                failures.append(
                    {
                        "repo": conn.full_name,
                        "status": error.status if isinstance(error, GitHubError) else None,
                    }
                )
    return total, failed


def _mark_issues_synced(conn):
    conn.issues_synced_at = timezone.now()
    conn.save(update_fields=["issues_synced_at"])


def sync_issues_if_stale(conn):
    """Refresh issue data at most every ten minutes; webhook deliveries reset the clock."""
    if conn.issues_synced_at and timezone.now() - conn.issues_synced_at < ISSUE_TTL:
        return
    try:
        sync_issues(conn)
    except (ServiceError, GitHubError):
        pass


def link_issue(task, issue):
    """이미 동기화된 이슈를 태스크에 손으로 잇는다. 다른 태스크의 이슈는 빼앗지 않는다."""
    if issue.task_id not in (None, task.pk):
        raise ServiceError({"issue": f"이미 {issue.task.number}에 연결된 이슈입니다."})
    link = getattr(task, "git", None)
    if link is not None and link.issue_number and link.issue_number != issue.number:
        unlink(task, "issue")  # 전에 잇던 이슈를 놓아 다른 태스크가 가져갈 수 있게 한다
    link = _link_for(issue.connection, task)
    link.issue_number = issue.number
    link.issue_title = issue.title
    link.issue_state = issue.state
    link.save(update_fields=["issue_number", "issue_title", "issue_state"])
    issue.task = task
    issue.save(update_fields=["task"])
    task._state.fields_cache.pop("git", None)
    return link


UNLINK_FIELDS = {
    "issue": {"issue_number": None, "issue_title": "", "issue_state": ""},
    "branch": {"branch": ""},
    "pr": {"pr_number": None, "pr_title": "", "pr_state": "", "merged_at": None},
}


def unlink(task, what: str = "all"):
    """Clear one GitHub link or the whole link, and release an imported issue for reuse."""
    link = getattr(task, "git", None)
    if link is None:
        return
    if what in ("all", "issue") and link.issue_number:
        RepoIssue.objects.filter(
            connection=link.connection, number=link.issue_number, task=task
        ).update(task=None)
    if what == "all":
        link.delete()
    elif fields := UNLINK_FIELDS.get(what):
        for name, value in fields.items():
            setattr(link, name, value)
        link.save(update_fields=list(fields))
    task._state.fields_cache.pop("git", None)


def pr_compare_url(link) -> str:
    """GitHub의 PR 작성 화면. 본문의 Closes #N 때문에 머지하면 이슈도 함께 닫힌다."""
    q = urlencode(
        {
            "quick_pull": "1",
            "title": f"{link.task.title} ({link.task.number})",
            "body": f"Closes #{link.issue_number}" if link.issue_number else "",
        }
    )
    # 브랜치 이름에는 괄호나 한글이 들어올 수 있다. 경로에 그대로 붙이지 않는다.
    branch = quote(link.branch, safe="/")
    return f"https://github.com/{link.connection.full_name}/compare/{branch}?{q}"
