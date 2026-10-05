"""마일스톤·릴리스 동기화(IMPL-PLAN-8 §3.9·§3.10).

services가 이 파일을 늦게 import한다(`services._handlers`). 여기서 services를 import해도 순환이 없다.
이슈 필드 양방향 동기화(§3.8)는 사용자 결정(§10-1)으로 하지 않는다.
"""

from datetime import date

from django.db.models import Q

from projects.models import Milestone
from projects.services import can_view_project, sync_milestone, visible_projects

from . import notify
from .models import GitRelease, RepoConnection
from .services import (
    _import_actor,
    can_view_repo,
    parse_ts,
    record_event,
    record_ignored,
    repo_state,
)

# ---------- 마일스톤 ----------


def _due(milestone: dict) -> date | None:
    # GitHub due_on은 날짜를 시각으로 담는다. 앞 10자만 읽는다(PM→GH는 정오 UTC로 보낸다).
    raw = milestone.get("due_on") or ""
    try:
        return date.fromisoformat(raw[:10]) if raw else None
    except ValueError:
        return None


def on_milestone(conn, delivery, payload):
    """created|edited|opened|closed → sync_milestone, deleted → gh_number만 비운다(PM 행은 남긴다)."""
    action = payload.get("action") or ""
    milestone = payload.get("milestone") or {}
    number = milestone.get("number")
    title = milestone.get("title") or ""
    summary = f"마일스톤 '{title}' {action}"
    if not number or action not in ("created", "edited", "opened", "closed", "deleted"):
        result = "무시"
    elif not conn.rule_milestone:
        result = "기록만"
    elif action == "deleted":
        n = Milestone.objects.filter(project=conn.project, gh_number=number).update(gh_number=None)
        result = "연결 해제" if n else "변경 없음"
    else:
        ms = sync_milestone(
            conn.project,
            gh_number=number,
            name=title,
            target_date=_due(milestone),
            status=milestone.get("state") or "open",
            created_by=_import_actor(conn, payload) or conn.created_by,
        )
        result = ms.sync_result
    record_event(conn, delivery, kind="milestone", payload=payload, summary=summary, result=result)


# ---------- 릴리스 ----------


def on_release(conn, delivery, payload):
    """published|edited → GitRelease upsert(태그 기준). deleted|unpublished → 삭제. draft는 무시."""
    action = payload.get("action") or ""
    rel = payload.get("release") or {}
    tag = (rel.get("tag_name") or "")[:100]
    name = (rel.get("name") or "")[:200]
    summary = f"릴리스 {tag} {action}"
    if not tag:
        return record_ignored(conn, delivery, "release", payload)
    if action in ("deleted", "unpublished"):
        n, _ = GitRelease.objects.filter(connection=conn, tag=tag).delete()
        result = "삭제" if n else "변경 없음"
    elif action in ("published", "edited") and not rel.get("draft"):
        q = Q(name__iexact=tag) | (Q(name__iexact=name) if name else Q(pk__in=[]))
        ms = Milestone.objects.filter(project=conn.project).filter(q).first()
        GitRelease.objects.update_or_create(
            connection=conn,
            tag=tag,
            defaults={
                "name": name,
                "url": (rel.get("html_url") or "")[:300],
                "prerelease": bool(rel.get("prerelease")),
                "published_at": parse_ts(rel.get("published_at")),
                "milestone": ms,
            },
        )
        result = f"저장 · 마일스톤 '{ms.name}'" if ms else "저장"
        if action == "published":
            extra = rel.get("html_url") or ""
            if ms and ms.status != "done":
                extra += f"\n마일스톤 '{ms.name}'를 완료로 표시할 수 있습니다."
            notify.channel(conn, "release", f"🔖 릴리스 {tag} 발행", extra=extra.strip())
    else:
        result = "무시"
    record_event(conn, delivery, kind="release", payload=payload, summary=summary, result=result)


def can_see_releases(user, project) -> bool:
    """릴리스(태그·이름·URL)를 보여 줘도 되는가. 화면·API의 릴리스 경로는 전부 여기를 지난다.
    프로젝트를 볼 수 있고 GitHub에서 그 저장소를 볼 수 있는 사람만(비공개 저장소 보호)."""
    return can_view_project(user, project) and repo_state(user, project)["state"] == "ok"


def releases_for(project, user, limit: int = 5) -> list[GitRelease]:
    """선반·API용 최근 릴리스."""
    if not can_see_releases(user, project):
        return []
    return list(
        GitRelease.objects.filter(connection=project.repo).select_related("milestone")[:limit]
    )


def releases_by_milestone(user, milestones) -> dict[int, list[GitRelease]]:
    """로드맵 칩용 {마일스톤 id: 릴리스}. 릴리스를 볼 수 없는 프로젝트의 마일스톤은 뺀다."""
    # can_see_releases와 같은 규칙을 묶음으로(프로젝트 수만큼 쿼리가 늘지 않게).
    pids = {ms.project_id for ms in milestones}
    visible = set(visible_projects(user).filter(pk__in=pids).values_list("pk", flat=True))
    allowed = {
        c.project_id
        for c in RepoConnection.objects.filter(project_id__in=visible)
        if can_view_repo(user, c.full_name)
    }
    shown = [ms for ms in milestones if ms.project_id in allowed]
    out = {}
    for rel in GitRelease.objects.filter(milestone__in=shown):
        out.setdefault(rel.milestone_id, []).append(rel)
    return out
