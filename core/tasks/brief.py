from django.conf import settings


def user_brief(u) -> dict | None:
    if u is None:
        return None
    return {"id": u.pk, "display_name": u.display_name, "discord_user_id": u.discord_user_id}


def _iso(value):
    return value.isoformat() if value else None


def _reviewer_sees(t) -> bool:
    if t.reviewer_id is None:
        return False
    from tasks.services import _sees_task

    return _sees_task(t.reviewer, t, t.project)


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
        # 공개 범위·담당 팀이 바뀌어 검토자가 더는 못 보면 내보내지 않는다 → 독촉은 관리자에게 간다.
        "reviewer": user_brief(t.reviewer) if _reviewer_sees(t) else None,
        "status": t.status,
        "priority": t.priority,
        "due_date": t.due_date.isoformat() if t.due_date else None,
        "stop_reason": t.stop_reason,
        # 막힘·검토 에스컬레이션이 경과일을 재는 기준.
        "stopped_at": t.stopped_at.isoformat() if t.stopped_at else None,
        "status_since": t.status_since.isoformat() if t.status_since else None,
        # PR 리뷰 요청 시각. 목록 API가 annotate한 경우에만 있다(그 밖은 None).
        "review_requested_at": _iso(getattr(t, "review_requested_at", None)),
        "updated_at": t.updated_at.isoformat() if t.updated_at else None,
        "next_action": t.next_action,
        # 템플릿은 진행하지 않는다. 회차·변형은 parent_id(계열의 뿌리)로 묶인다.
        "is_template": t.is_template,
        "parent_id": t.parent_id,
        # 상위 태스크(한 겹). 번호는 비밀이 아니라 id만 낸다 — 제목은 볼 수 있는 사람에게만(task_out).
        "group_id": t.group_id,
        "url": f"{settings.SITE_URL}/tasks/{t.pk}",
    }
