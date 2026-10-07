"""GitHub 사건 알림(IMPL-PLAN-8 §2.3). Notice 발송함으로만 만든다 — core는 Discord로 직접
나가지 않고 `discord_service`의 `deliver_notices`가 보낸다. Discord 미연결이면 `notify`가 만들지 않는다.
"""

from orgs.services import is_member
from orgs.settings import effective
from tasks.work_requests import _due_text, _link, notify


def _line(task) -> str:
    """알림 메시지 형식(라운드 7): 제목·프로젝트·D-n·상태·링크. 격식체."""
    title = task.title.replace("[", "\\[").replace("]", "\\]")
    return (
        f"**{task.project.name}**\n• [{task.number} {title}](<{_link(f'/tasks/{task.pk}')}>)"
        f" · {_due_text(task.due_date)} · {task.get_status_display()}"
    )


def channel(conn, kind: str, head: str, task=None, extra: str = "") -> None:
    """`notify.github_channel_events`에 kind가 있고 프로젝트 채널이 있을 때만.
    비공개 프로젝트도 자기 채널이면 올린다. 태스크가 있으면 그 **주 프로젝트** 채널이다 — 연결 태스크가
    연동 프로젝트(다른 저장소)를 따르더라도 알림은 번호·알림의 소유자인 주 프로젝트로 간다(IMPL-PLAN-11 §3.4)."""
    project = task.project if task is not None else conn.project
    if kind not in effective("notify.github_channel_events", org=project.org, project=project):
        return
    if not project.discord_channel_id:
        return
    text = head + ("\n" + _line(task) if task else "") + (f"\n{extra}" if extra else "")
    notify(project.org, text, channel_id=project.discord_channel_id)


def dm(task, user, head: str, extra: str = "") -> None:
    """`notify.github_dm`(조직·프로젝트)과 `user.notify_dm`(개인)이 둘 다 켜져 있고,
    그 사람이 아직 조직 멤버이며 프로젝트를 볼 수 있을 때만."""
    from tasks.services import _sees_task

    project = task.project
    if user is None or not is_member(user, project.org) or not _sees_task(user, task, project):
        return
    if not effective("notify.github_dm", org=project.org, project=project):
        return
    if not effective("user.notify_dm", user=user):
        return
    notify(project.org, head + "\n" + _line(task) + (f"\n{extra}" if extra else ""), user=user)
