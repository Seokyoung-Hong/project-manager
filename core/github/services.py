"""GitHub 연동의 업무 규칙. 뷰·라우터에는 규칙을 두지 않는다.

권한의 경계가 둘이다.
- **태스크**는 조직 규칙으로 본다(`orgs.services.is_member`).
- **GitHub에서 온 것**은 GitHub 권한으로 본다(`can_view_repo`). 조직 멤버라도 그 저장소를
  볼 수 없으면 브랜치·PR·이슈가 보이지 않는다.

`actor=None`은 웹훅 경로에서만 쓴다. 이 파일 밖에서 `tasks.services`에 None을 넘기지 않는다.
"""

import re
from datetime import datetime, timedelta
from urllib.parse import urlencode

from django.conf import settings
from django.utils import timezone

from common.errors import ConflictError, ServiceError
from orgs.models import TeamMembership
from orgs.services import is_member, orgs_of
from tasks.models import ChangeLog, Task
from tasks.services import create_task, transition

from . import client
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

REPO_TTL = timedelta(hours=6)
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


def save_installation(org, installation_id: int, *, actor) -> GitHubInstallation:
    """GET /app/installations/{id}(앱 JWT)로 계정 정보를 읽어 저장한다.

    다른 조직이 이미 그 설치를 쓰고 있으면 거부한다.
    """
    other = (
        GitHubInstallation.objects.filter(installation_id=installation_id).exclude(org=org).exists()
    )
    if other:
        raise ServiceError({"installation": "이 설치는 이미 다른 조직이 사용하고 있습니다."})
    data = client.request("GET", f"/app/installations/{installation_id}", client.app_jwt())
    account = data.get("account") or {}
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
        page = 1
        while True:
            try:
                data = client.request(
                    "GET",
                    f"/user/installations/{inst.installation_id}/repositories"
                    f"?per_page=100&page={page}",
                    token,
                )
            except GitHubError:
                break  # 그 설치에 접근 권한이 없다(403·404). 건너뛴다.
            repos = (data or {}).get("repositories", [])
            names += [r["full_name"] for r in repos]
            if len(repos) < 100:
                break
            page += 1
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
    try:
        sync_repos(identity)
    except (GitHubError, ServiceError):
        pass


def backfill_actor(identity):
    """이 로그인으로 남아 있던 GitHub 이력을 이 사람의 것으로 바꾼다."""
    ChangeLog.objects.filter(
        source="gh", actor__isnull=True, external_actor__iexact=identity.login
    ).update(actor_id=identity.user_id, external_actor="")
    GitEvent.objects.filter(actor_user__isnull=True, actor_login__iexact=identity.login).update(
        actor_user_id=identity.user_id
    )


# ---------- 저장소 주소 ----------

REPO_RE = re.compile(r"(?:github\.com[:/])([\w.-]+)/([\w.-]+?)(?:\.git)?/?$", re.I)


def parse_repo_url(url: str) -> str:
    m = REPO_RE.search((url or "").strip())
    if not m:
        raise ServiceError(
            {"url": "GitHub 저장소 주소를 넣으세요. 예: https://github.com/owner/repo.git"}
        )
    return f"{m.group(1)}/{m.group(2)}"


def connect_repo(*, project, url, actor) -> RepoConnection:
    """저장소를 프로젝트에 잇는다. 그 사람이 볼 수 있는 저장소여야 한다."""
    if not is_member(actor, project.org):
        raise ServiceError({"org": "이 조직의 멤버가 아닙니다."})
    full_name = parse_repo_url(url)
    if not can_view_repo(actor, full_name):
        raise ServiceError(
            {"url": "그 저장소에 접근할 수 없습니다. GitHub 연결과 권한을 확인하세요."}
        )
    conn, _ = RepoConnection.objects.update_or_create(
        project=project,
        defaults={"url": url.strip()[:300], "full_name": full_name, "created_by": actor},
    )
    sync_issues_if_stale(conn)  # 붙이자마자 목록이 비어 보이지 않게
    return conn


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
    handler = {
        "create": _on_create,
        "push": _on_push,
        "pull_request": _on_pr,
        "issues": _on_issues,
    }.get(event)
    if handler is None:
        for conn in conns:
            if event in ("membership", "team"):
                record_event(
                    conn, delivery, kind=event, payload=payload, summary=_short(event, payload)
                )
        return 202, {"ignored": event}
    for conn in conns:  # 한 저장소를 두 프로젝트가 가리킬 수 있다
        handler(conn, delivery, payload)
    return 200, {"ok": True}


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
    branch = (payload.get("ref") or "").rsplit("/", 1)[-1]
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


def _on_pr(conn, delivery, payload):
    action = payload.get("action") or ""
    pr = payload.get("pull_request") or {}
    branch = ((pr.get("head") or {}).get("ref")) or ""
    task, _ = _find_task(conn, pr.get("title") or "", pr.get("body") or "", branch)
    number = pr.get("number")
    summary = f"PR #{number} {action}"
    if task is None or action not in ("opened", "closed"):
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
    rule_on = conn.rule_merge if (action == "closed" and merged) else conn.rule_pr
    link = _link_for(conn, task)
    link.pr_number = number
    link.pr_title = (pr.get("title") or "")[:300]
    link.pr_state = "merged" if merged else ("closed" if action == "closed" else "open")
    if merged:
        link.merged_at = parse_ts(pr.get("merged_at"))
    if branch and not link.branch:
        link.branch = branch[:200]
    link.save()
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
    if action == "opened":
        result = _apply(task, "review", actor=actor, actor_login=login)
    elif merged:
        result = _apply(task, "done", actor=actor, actor_login=login)
    record_event(
        conn,
        delivery,
        kind="pull_request",
        payload=payload,
        summary=summary,
        task=task,
        result=result,
    )


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
            "state": issue.get("state") or ("closed" if action == "closed" else "open"),
            "assignee_login": ((issue.get("assignee") or {}).get("login")) or "",
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
    elif action == "opened" and conn.rule_issue and conn.auto_import:
        if conn.import_label and conn.import_label not in labels:
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
    if row.task:
        link = TaskGitLink.objects.filter(task=row.task).first()
        if link:
            link.issue_state = row.state
            link.save(update_fields=["issue_state"])
    _mark_issues_synced(conn)  # 웹훅이 살아 있다 — 폴링으로 또 물어보지 않는다
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

    설치 토큰으로 읽는다 — 이 토큰은 읽기에만 쓴다.
    # ponytail: 첫 100건. 이슈가 그보다 많은 저장소가 생기면 페이지를 돈다.
    """
    inst = getattr(conn.project.org, "github", None)
    if inst is None:
        raise ServiceError({"github": "조직에 GitHub 앱이 설치되지 않았습니다."})
    token = client.installation_token(inst.installation_id)
    # 빈 labels를 보내면 GitHub가 "라벨 없는 이슈"로 읽는다. 값이 있을 때만 넣는다.
    params = {"state": "open", "per_page": 100}
    if conn.import_label:
        params["labels"] = conn.import_label
    q = urlencode(params)
    seen = set()
    for item in client.request("GET", f"/repos/{conn.full_name}/issues?{q}", token) or []:
        if "pull_request" in item:
            continue
        seen.add(item["number"])
        RepoIssue.objects.update_or_create(
            connection=conn,
            number=item["number"],
            defaults={
                "title": item["title"][:300],
                "state": item.get("state") or "open",
                "assignee_login": ((item.get("assignee") or {}).get("login")) or "",
                "labels": [lb["name"] for lb in item.get("labels", []) if isinstance(lb, dict)],
            },
        )
    if not conn.import_label:
        # 라벨로 걸렀다면 목록에 없는 = 라벨이 없는 이슈다. 닫혔다고 단정할 수 없다.
        conn.issues.filter(state="open").exclude(number__in=seen).update(state="closed")
    _mark_issues_synced(conn)
    return len(seen)


def _mark_issues_synced(conn):
    conn.issues_synced_at = timezone.now()
    conn.save(update_fields=["issues_synced_at"])


def sync_issues_if_stale(conn):
    """이슈 목록은 서버가 알아서 맞춘다 — 사람이 [새로고침]을 누를 일이 없어야 한다.

    웹훅(`issues`)이 들어오면 시각을 갱신하므로, 웹훅이 살아 있는 저장소는 여기서 GitHub를
    부르지 않는다. 웹훅이 끊겼거나 처음 연결한 저장소만 TTL마다 한 번 물어본다.
    실패는 조용히 넘긴다 — 화면이 GitHub 때문에 깨지면 안 된다.
    """
    if conn.issues_synced_at and timezone.now() - conn.issues_synced_at < ISSUE_TTL:
        return
    try:
        sync_issues(conn)
    except (ServiceError, GitHubError):
        pass


# ---------- 연결 해제 ----------

# 단계 이름 → 비울 열. "all"은 링크 행 자체를 지운다.
UNLINK_FIELDS = {
    "issue": {"issue_number": None, "issue_title": "", "issue_state": ""},
    "branch": {"branch": ""},
    "pr": {"pr_number": None, "pr_title": "", "pr_state": "", "merged_at": None},
}


def unlink(task, what: str = "all"):
    """태스크와 GitHub 사이를 끊는다. 단계 하나만 끊을 수도, 전부 끊을 수도 있다.

    이슈를 끊을 때는 RepoIssue.task도 함께 비운다. 그러지 않으면 저장소 탭에서 그 이슈가
    영영 "가져옴"으로 남아 다시 가져올 수 없다.
    """
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
    # 역참조 캐시에 지워진 행이 남으면 화면이 방금 끊은 것을 그대로 다시 그린다.
    task._state.fields_cache.pop("git", None)


def pr_compare_url(link) -> str:
    """GitHub의 PR 작성 화면. 본문의 Closes #N 때문에 머지하면 이슈도 함께 닫힌다."""
    q = urlencode(
        {
            "quick_pull": "1",
            "title": f"{link.task.number} {link.task.title}",
            "body": f"Closes #{link.issue_number}" if link.issue_number else "",
        }
    )
    return f"https://github.com/{link.connection.full_name}/compare/{link.branch}?{q}"
