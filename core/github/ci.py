"""CI 상태(check_suite·status) → TaskGitLink 배지·실패 알림(IMPL-PLAN-8 §3.6·§3.7).

services가 이 파일을 늦게 import한다(`services._handlers`). 여기서 services를 import해도 순환이 없다.
권한(Checks·Commit statuses Read)이 없으면 이벤트가 오지 않을 뿐이라 기능이 조용히 꺼진다.
"""

from django.utils import timezone

from . import notify
from .models import TaskGitLink
from .services import record_event, record_ignored

FAIL = {"failure", "timed_out", "cancelled", "action_required", "error", "startup_failure", "stale"}
_OPEN = ("todo", "doing", "paused", "blocked", "review")


def _links_for(conn, sha: str, branches: list[str]) -> list[TaskGitLink]:
    """head_sha가 같은 링크 → 없으면 branch가 같은 링크. 열린 태스크 우선."""
    qs = TaskGitLink.objects.filter(connection=conn).select_related("task", "task__project")
    found = list(qs.filter(head_sha=sha)) if sha else []
    if not found and branches:
        found = list(qs.filter(branch__in=branches))
    return sorted(found, key=lambda link: link.task.status not in _OPEN)


def recompute(link) -> None:
    """ci_checks → ci_state(failure > pending > success). 저장한다."""
    values = set(link.ci_checks.values())
    if "failure" in values:
        link.ci_state = "failure"
    elif "pending" in values:
        link.ci_state = "pending"
    else:
        link.ci_state = "success" if values else ""
    link.ci_at = timezone.now()
    link.save(update_fields=["ci_checks", "ci_state", "ci_url", "ci_at", "head_sha"])


def _apply(conn, delivery, event, payload, sha, branches, key, state, url) -> None:
    first = None
    for link in _links_for(conn, sha, branches):
        if link.head_sha != sha:
            # 브랜치로만 맞았다. PR이 있으면 head_sha는 synchronize가 관리하므로 옛 커밋 CI는 버린다.
            if link.pr_number:
                continue
            link.head_sha, link.ci_checks = sha, {}
        before = link.ci_state
        link.ci_checks = {**link.ci_checks, key: state}
        link.ci_url = url[:300]
        recompute(link)
        first = first or link
        if link.ci_state == "failure" and before != "failure" and link.task.is_open:
            _alert(conn, link)
    if first is None:
        return record_ignored(conn, delivery, event, payload)
    record_event(
        conn,
        delivery,
        kind="check",
        payload=payload,
        task=first.task,
        summary=f"CI {first.ci_state} {sha[:7]}",
        result=first.ci_state,
    )


def _alert(conn, link) -> None:
    task = link.task
    head = f"❌ CI 실패 · PR #{link.pr_number}" if link.pr_number else "❌ CI 실패"
    notify.dm(task, task.assignee, "❌ CI 실패", extra=link.ci_url)
    notify.channel(conn, "ci_failed", head, task, extra=link.ci_url)


def on_check_suite(conn, delivery, payload):
    s = payload.get("check_suite") or {}
    sha = s.get("head_sha") or ""
    if payload.get("action") == "completed" and s.get("conclusion"):
        state = "failure" if s["conclusion"] in FAIL else "success"
    else:  # requested·rerequested, 결론 없는 completed
        state = "pending"
    url = f"https://github.com/{conn.full_name}/commit/{sha}/checks"
    branch = [s["head_branch"]] if s.get("head_branch") else []
    key = f"suite:{s.get('id')}"
    _apply(conn, delivery, "check_suite", payload, sha, branch, key, state, url)


def on_status(conn, delivery, payload):
    sha = payload.get("sha") or ""
    state = {"success": "success", "pending": "pending"}.get(payload.get("state"), "failure")
    branches = [b["name"] for b in payload.get("branches") or [] if b.get("name")]
    url = payload.get("target_url") or f"https://github.com/{conn.full_name}/commit/{sha}"
    key = f"status:{payload.get('context')}"
    _apply(conn, delivery, "status", payload, sha, branches, key, state, url)
