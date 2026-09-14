from django.conf import settings

from projects.services import project_stats
from tasks.brief import task_brief, user_brief


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


def task_out(t) -> dict:
    items = list(t.checklist.all())
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
        }
    )
    return d


def project_out(p) -> dict:
    return {
        "id": p.pk,
        "org_id": p.org_id,
        "name": p.name,
        "purpose": p.purpose,
        "owners": [user_brief(u) for u in p.owners.all()],
        "teams": [
            {"id": t.pk, "name": t.name, "purpose": t.purpose, "member_count": t.members.count()}
            for t in p.teams.all()
        ],
        "status": p.status,
        "status_label": p.status_label,
        "discord_channel_id": p.discord_channel_id,
        "is_archived": p.is_archived,
        "version": p.version,
        "stats": project_stats(p),
        "links": [link_out(link) for link in p.links.all()],
        "url": f"{settings.SITE_URL}/projects/{p.pk}",
    }


def invite_out(inv) -> dict:
    return {
        "id": inv.pk,
        "url": f"{settings.SITE_URL}{inv.path}",
        "expires_at": inv.expires_at,
        "use_count": inv.use_count,
        "revoked_at": inv.revoked_at,
    }
