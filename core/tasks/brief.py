from django.conf import settings


def user_brief(u) -> dict | None:
    if u is None:
        return None
    return {"id": u.pk, "display_name": u.display_name, "discord_user_id": u.discord_user_id}


def task_brief(t) -> dict:
    return {
        "id": t.pk,
        "number": t.number,
        "title": t.title,
        "project": {"id": t.project_id, "name": t.project.name, "org_id": t.project.org_id},
        "assignee": user_brief(t.assignee),
        "status": t.status,
        "priority": t.priority,
        "due_date": t.due_date.isoformat() if t.due_date else None,
        "stop_reason": t.stop_reason,
        "next_action": t.next_action,
        "stopped_at": t.stopped_at,
        "updated_at": t.updated_at,
        "url": f"{settings.SITE_URL}/tasks/{t.pk}",
    }
