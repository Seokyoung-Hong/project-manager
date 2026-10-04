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
        "project": {
            "id": t.project_id,
            "name": t.project.name,
            "org_id": t.project.org_id,
            # 프로젝트 채널 게시(IMPL-PLAN-4 §4.5)가 목적지를 여기서 읽는다.
            "discord_channel_id": t.project.discord_channel_id,
        },
        "assignee": user_brief(t.assignee),
        # 지정 검토자. 검토 독촉(escalate)이 관리자보다 먼저 이 사람에게 보낸다.
        "reviewer": user_brief(t.reviewer),
        "status": t.status,
        "priority": t.priority,
        "due_date": t.due_date.isoformat() if t.due_date else None,
        "stop_reason": t.stop_reason,
        # 막힘·검토 에스컬레이션이 경과일을 재는 기준.
        "stopped_at": t.stopped_at.isoformat() if t.stopped_at else None,
        "updated_at": t.updated_at.isoformat() if t.updated_at else None,
        "next_action": t.next_action,
        # 템플릿은 진행하지 않는다. 회차·변형은 parent_id(계열의 뿌리)로 묶인다.
        "is_template": t.is_template,
        "parent_id": t.parent_id,
        "url": f"{settings.SITE_URL}/tasks/{t.pk}",
    }
