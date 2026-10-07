from django.conf import settings
from django.db.models import Count, Prefetch

from orgs.models import Team
from orgs.services import visible_teams
from projects.docs import task_docs
from projects.services import project_stats, project_stats_bulk
from tasks.attachments import attachments_of
from tasks.brief import task_brief, user_brief
from tasks.services import linked_projects, subtask_progress, subtask_view, visible_tasks
from tasks.work_requests import pending_assignee


def link_out(link) -> dict:
    return {"id": link.pk, "title": link.title, "url": link.url, "kind": link.kind}


def changelog_out(log) -> dict:
    return {
        "id": log.pk,
        "field": log.field,
        "old_value": log.old_value,
        "new_value": log.new_value,
        "note": log.note,
        "actor": user_brief(log.actor),
        "source": log.source,
        "created_at": log.created_at,
    }


def task_out(t, viewer=None) -> dict:
    """viewer: 응답을 받는 사람. 다른 프로젝트로 간 회차는 viewer가 볼 수 있을 때만 센다.
    없으면 같은 프로젝트의 회차만 센다(태스크를 보는 사람은 그 프로젝트를 볼 수 있다)."""
    children = (
        visible_tasks(viewer).filter(parent=t)
        if viewer is not None
        else t.children.filter(project_id=t.project_id)
    )
    items = list(t.checklist.all())
    if viewer is not None:
        sv = subtask_view(viewer, t)
    else:
        done, total = subtask_progress(t)
        sv = {"group": None, "subtasks": [], "done": done, "total": total, "hidden": total}
    d = task_brief(t)
    d.update(
        {
            "description": t.description,
            "done_when": t.done_when,
            "notes": t.notes,
            "no_due_reason": t.no_due_reason,
            "stopped_at": t.stopped_at,
            "completed_at": t.completed_at,
            "version": t.version,
            "created_by": user_brief(t.created_by),
            "created_at": t.created_at,
            "updated_at": t.updated_at,
            "checklist": [
                {"id": i.pk, "text": i.text, "is_done": i.is_done, "position": i.position}
                for i in items
            ],
            "checklist_done": sum(1 for i in items if i.is_done),
            "checklist_total": len(items),
            "links": [link_out(link) for link in t.links.all()],
            # 참고 문서는 제목과 id만, 그리고 viewer가 볼 수 있는 것만(문서 가시성 관문 하나).
            # 태스크를 연결 프로젝트로 볼 수 있어도 주 프로젝트 문서까지 보게 되지는 않는다.
            "docs": [{"id": d.pk, "title": d.title} for d in task_docs(t, viewer)],
            # 담당 요청을 받은 사람이 아직 수락하지 않았다. 수락 전까지 assignee는 그대로다.
            "pending_assignee": user_brief(pending) if (pending := pending_assignee(t)) else None,
            "children_count": children.count(),
            "group": (
                {"id": sv["group"].pk, "number": sv["group"].number, "title": sv["group"].title}
                if sv["group"]
                else None
            ),
            "subtasks": [
                {
                    "id": s.pk,
                    "number": s.number,
                    "title": s.title,
                    "status": s.status,
                    "assignee": user_brief(s.assignee),
                    "due_date": s.due_date,
                    "due_after_group": s.due_after_group,
                }
                for s in sv["subtasks"]
            ],
            "subtask_done": sv["done"],
            "subtask_total": sv["total"],
            "subtask_hidden": sv["hidden"],
            "linked_projects": linked_projects(t, viewer) if viewer is not None else [],
            "git_project_id": t.git_project_id,
            "attachments": [attachment_out(a) for a in attachments_of(t)],  # 최신 버전만
        }
    )
    return d


def _shown_team_ids(viewer, org=None) -> set[int]:
    """viewer가 세부(목적·인원)를 볼 수 있는 팀. viewer가 없으면 공개 팀만."""
    if viewer is None:
        qs = Team.objects.filter(is_private=False)
        return set((qs.filter(org=org) if org is not None else qs).values_list("pk", flat=True))
    return set(visible_teams(viewer, org).values_list("pk", flat=True))


def _team_out(t, shown: set[int]) -> dict:
    """비공개 팀을 볼 수 없는 사람에게는 이름만 준다(팀 목록과 같은 규칙)."""
    if t.pk not in shown:
        return {"id": t.pk, "name": t.name, "purpose": None, "member_count": None}
    return {
        "id": t.pk,
        "name": t.name,
        "purpose": t.purpose,
        "member_count": t.member_count
        if hasattr(t, "member_count")  # projects_out이 미리 센 값
        else t.members.count(),
    }


def project_out(p, stats=None, viewer=None, shown_teams=None) -> dict:
    """stats를 넘기면(projects_out) 다시 세지 않는다. viewer 밖 비공개 팀은 이름만."""
    if shown_teams is None:
        shown_teams = _shown_team_ids(viewer, p.org_id)
    return {
        "id": p.pk,
        "org_id": p.org_id,
        "name": p.name,
        "purpose": p.purpose,
        "discord_channel_id": p.discord_channel_id,
        "owners": [user_brief(u) for u in p.owners.all()],
        "teams": [_team_out(t, shown_teams) for t in p.teams.all()],
        "status": p.status,
        "status_label": p.status_label,
        "is_archived": p.is_archived,
        "dev_tools": p.dev_tools,
        "visibility": p.visibility,
        "version": p.version,
        "stats": stats if stats is not None else project_stats(p),
        "links": [link_out(link) for link in p.links.all()],
        "url": f"{settings.SITE_URL}/projects/{p.pk}",
    }


def projects_out(qs, viewer=None) -> list[dict]:
    """프로젝트 목록. 관리자·팀(인원 수)·링크·통계를 프로젝트 수와 무관하게 몇 번의 쿼리로 읽는다."""
    teams = Team.objects.annotate(member_count=Count("members"))
    ps = list(
        qs.select_related("org", "repo")  # repo: dev_tools 속성이 읽는다
        .prefetch_related(None)  # 호출자가 붙인 "teams"와 겹치지 않게 비우고 다시 붙인다
        .prefetch_related("owners", "links", Prefetch("teams", queryset=teams))
    )
    stats = project_stats_bulk(ps)
    shown = _shown_team_ids(viewer)
    return [project_out(p, stats[p.pk], shown_teams=shown) for p in ps]


def invite_out(inv) -> dict:
    return {
        "id": inv.pk,
        "url": f"{settings.SITE_URL}{inv.path}",
        "expires_at": inv.expires_at,
        "use_count": inv.use_count,
        "revoked_at": inv.revoked_at,
    }


def request_out(r) -> dict:
    return {
        "id": r.pk,
        "number": r.number,
        "kind": r.kind,
        "kind_label": r.get_kind_display(),
        "title": r.title,
        "body": r.body,
        "status": r.status,
        "status_label": r.get_status_display(),
        "requested_by": user_brief(r.requested_by),
        "team": {"id": r.team.pk, "name": r.team.name} if r.team_id else None,
        "to_user": user_brief(r.to_user) if r.to_user_id else None,
        "task_id": r.task_id,
        "due_date": r.due_date,
        "response_note": r.response_note,
        "url": settings.SITE_URL + r.path,
        "created_at": r.created_at,
    }


def attachment_out(a) -> dict:
    """url은 토큰 인증 다운로드 끝점이다. 브라우저 링크는 /attachments/{id}/{name}."""
    return {
        "id": a.pk,
        "name": a.name,
        "size": a.size,
        "kind": a.kind,
        "content_type": a.content_type,
        "version": a.version,
        "replaces_id": a.replaces_id,
        "note": a.note,
        "url": f"{settings.SITE_URL}/api/attachments/{a.pk}/download",
        "created_by": user_brief(a.created_by),
        "created_at": a.created_at,
    }
