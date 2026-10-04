"""팀·사람에게 보내는 요청과 Discord 알림 발송함.

남에게 태스크를 맡기려면 받는 사람이 수락해야 한다. 본인·조직 관리자·받는 사람이 속한 팀의
팀장은 승인 없이 바로 맡긴다(`can_assign_directly`). 태스크 생성·담당자 변경의 그 갈림길은
tasks/services.py가 이 모듈을 불러 처리한다.
"""

from django.conf import settings
from django.db import transaction
from django.db.models import Q
from django.utils import timezone

from common.errors import ServiceError
from orgs.models import Team, TeamMembership
from orgs.services import is_admin, is_member, orgs_of
from projects.models import Project

from . import services as ts
from .models import Notice, WorkRequest

RESPONSE_MAX = 300


def can_assign_directly(actor, assignee, org, source: str = "") -> bool:
    """GitHub 경로(source="gh", actor None)는 이슈 담당자를 그대로 따른다 — 거기서 이미 정해진 배정이다."""
    if (
        source == "gh"
        or actor is None
        or assignee is None
        or actor == assignee
        or is_admin(actor, org)
    ):
        return True
    return TeamMembership.objects.filter(
        user=actor, is_lead=True, team__org=org, team__memberships__user=assignee
    ).exists()


# ---------- 알림 ----------


def notify(org, text: str, *, user=None, channel_id: str = ""):
    """보낼 수 없는 알림(Discord 미연결, 채널 없음)은 만들지 않는다."""
    if user is not None and not (user.discord_user_id and user.discord_linked_at):
        return
    if user is None and not channel_id:
        return
    Notice.objects.create(org=org, user=user, channel_id=channel_id, text=text[:1900])


def _link(path: str) -> str:
    return settings.SITE_URL + path


def notify_assigned(task, actor):
    """승인 없이 남에게 맡겼을 때 받은 사람에게 알린다."""
    who = actor.display_name if actor else "GitHub"
    notify(
        task.project.org,
        f"📌 {who}님이 **{task.number}** {task.title} 담당자로 지정했습니다.\n"
        + _link(f"/tasks/{task.pk}"),
        user=task.assignee,
    )


def _notify_new(req, posted_in: str = ""):
    head = f"📨 {req.requested_by.display_name}님의 {req.get_kind_display()} **{req.number}** {req.title}"
    link = _link(req.path)
    if req.to_user_id:
        notify(req.org, f"{head}\n수락·거절: {link}", user=req.to_user)
        return
    if posted_in and posted_in == req.team.discord_channel_id:
        return  # /요청을 친 그 팀 채널에 봇이 이미 공개로 알렸다
    if req.team.discord_channel_id:
        notify(req.org, f"{head}\n수락·거절: {link}", channel_id=req.team.discord_channel_id)
        return
    # ponytail: 팀 채널이 없으면 팀원 모두에게 DM한다. 팀이 커지면 팀장에게만 보내도록 좁힌다.
    for user in req.team.members.filter(is_active=True):
        notify(req.org, f"{head}\n수락·거절: {link}", user=user)


def _notify_requester(req, actor, verb: str):
    note = f"\n> {req.response_note}" if req.response_note else ""
    notify(
        req.org,
        f"↩️ {actor.display_name}님이 **{req.number}** {req.title} 요청을 {verb}했습니다."
        f"{note}\n{_link(req.path)}",
        user=req.requested_by,
    )


def pending_notices(limit: int = 50):
    return list(Notice.objects.filter(sent_at__isnull=True).select_related("user")[:limit])


def mark_sent(ids: list[int]) -> int:
    return Notice.objects.filter(pk__in=ids, sent_at__isnull=True).update(sent_at=timezone.now())


# ---------- 조회 ----------


def visible_requests(user):
    """보낸 사람·받는 사람·받는 팀의 팀원·조직 관리자만 본다."""
    return (
        WorkRequest.objects.filter(
            Q(requested_by=user)
            | Q(to_user=user)
            | Q(team__memberships__user=user)
            | Q(org__memberships__user=user, org__memberships__role="admin")
        )
        .filter(org__in=orgs_of(user))
        .select_related("org", "team", "to_user", "requested_by", "responded_by", "task")
        .distinct()
    )


def get_visible_request(user, pk: int) -> WorkRequest | None:
    return visible_requests(user).filter(pk=pk).first()


def received(user):
    return visible_requests(user).filter(Q(to_user=user) | Q(team__memberships__user=user))


def can_respond(user, req) -> bool:
    if req.to_user_id:
        return req.to_user_id == user.pk
    return req.team.memberships.filter(user=user).exists()


# ---------- 만들기 ----------


@transaction.atomic
def create_request(
    *,
    org,
    kind: str,
    title: str,
    actor,
    source: str,
    body: str = "",
    team=None,
    to_user=None,
    posted_in: str = "",
) -> WorkRequest:
    """posted_in: Discord에서 명령을 친 채널. 받는 팀의 채널이면 봇이 거기 이미 알렸다."""
    ts._ai_check(org, "ai.create_request", "요청 보내기", source, "request")
    if kind not in ("work", "general"):
        raise ServiceError({"kind": "작업 요청이나 일반 요청만 직접 만들 수 있습니다."})
    if not is_member(actor, org):
        raise ServiceError({"org": "이 조직의 멤버가 아닙니다."})
    title = (title or "").strip()[:200]
    if not title:
        raise ServiceError({"title": "제목을 입력하세요."})
    if (team is None) == (to_user is None):
        raise ServiceError({"target": "받을 팀이나 사람 중 하나를 고르세요."})
    if team is not None and team.org_id != org.pk:
        raise ServiceError({"team": "이 조직의 팀이 아닙니다."})
    if to_user is not None:
        if not to_user.is_active or not is_member(to_user, org):
            raise ServiceError({"to_user": "받는 사람은 이 조직의 활성 멤버여야 합니다."})
        if to_user == actor:
            raise ServiceError({"to_user": "자기 자신에게는 요청할 수 없습니다."})
    req = WorkRequest.objects.create(
        org=org,
        kind=kind,
        title=title,
        body=(body or "").strip(),
        requested_by=actor,
        team=team,
        to_user=to_user,
        source=source,
    )
    _notify_new(req, posted_in)
    return req


def request_assign(task, to_user, actor, source: str, note: str = "") -> WorkRequest:
    """tasks/services.py가 부른다. 같은 사람에게 이미 대기 중인 요청이 있으면 그걸 돌려준다."""
    org = task.project.org
    if not to_user.is_active or not is_member(to_user, org):
        raise ServiceError({"assignee": "담당자는 이 조직의 활성 멤버여야 합니다."})
    existing = WorkRequest.objects.filter(
        task=task, kind="assign", to_user=to_user, status="pending"
    ).first()
    if existing:
        return existing
    req = WorkRequest.objects.create(
        org=org,
        kind="assign",
        title=task.title[:200],
        body=note,
        requested_by=actor,
        to_user=to_user,
        task=task,
        source=source,
    )
    _notify_new(req)
    return req


def drop_assign_requests(task, keep_user=None):
    """담당자가 이미 정해졌거나(바로 할당·다른 요청 수락) 태스크가 닫혔다. 남은 담당 요청을
    나중에 수락하면 그 결정을 덮어쓰므로 취소한다."""
    WorkRequest.objects.filter(task=task, kind="assign", status="pending").exclude(
        to_user=keep_user
    ).update(status="cancelled", responded_at=timezone.now())


def pending_assignee(task):
    req = (
        WorkRequest.objects.filter(task=task, kind="assign", status="pending")
        .select_related("to_user")
        .first()
    )
    return req.to_user if req else None


# ---------- 답하기 ----------


def _lock_open(req, actor) -> WorkRequest:
    req = (
        WorkRequest.objects.select_for_update()
        .select_related("org", "team", "to_user", "requested_by", "task")
        .get(pk=req.pk)
    )
    if not req.is_open:
        raise ServiceError({"request": "이미 처리된 요청입니다."})
    if not can_respond(actor, req):
        raise ServiceError({"request": "받는 사람(팀원)만 답할 수 있습니다."})
    return req


def _close(req, actor, status: str, note: str = ""):
    req.status = status
    req.responded_by = actor
    req.responded_at = timezone.now()
    req.response_note = (note or "").strip()[:RESPONSE_MAX]
    req.save(update_fields=["status", "responded_by", "responded_at", "response_note", "task"])


@transaction.atomic
def accept(
    req, actor, *, source: str, project=None, assignee=None, due_date=None, note: str = ""
) -> WorkRequest:
    """work는 project가 필요하다. assignee가 수락한 사람이 아니면 태스크 생성 규칙대로
    (팀장이면 바로, 아니면 그 사람에게 다시 담당 요청이 간다) 처리된다."""
    ts._ai_check(req.org, "ai.answer_request", "요청 수락", source, "request")
    req = _lock_open(req, actor)
    if req.kind == "assign":
        _accept_assign(req, actor, source)
    elif req.kind == "work":
        req.task = _task_from_request(req, actor, source, project, assignee, due_date)
    _close(req, actor, "accepted", note)
    _notify_requester(req, actor, "수락")
    return req


def _accept_assign(req, actor, source):
    task = req.task
    if task is None:
        raise ServiceError({"request": "태스크가 지워져 넘겨받을 수 없습니다."})
    if task.assignee_id != actor.pk:
        ts.update_task(
            task,
            {"assignee": actor},
            actor=actor,
            source=source,
            expected_version=task.version,
            reason=f"{req.number} 수락 — {req.body}" if req.body else f"{req.number} 수락",
        )


def _task_from_request(req, actor, source, project, assignee, due_date):
    if project is None:
        raise ServiceError({"project": "태스크를 둘 프로젝트를 고르세요."})
    if project.org_id != req.org_id:
        raise ServiceError({"project": "이 조직의 프로젝트가 아닙니다."})
    footer = f"({req.number} · {req.requested_by.display_name}님의 요청)"
    return ts.create_task(
        project=project,
        title=req.title,
        description=f"{req.body}\n\n{footer}".strip(),
        assignee=assignee or actor,
        due_date=due_date,
        no_due_reason="" if due_date else "요청으로 생긴 태스크 — 기한 미정",
        actor=actor,
        source=source,
    )


@transaction.atomic
def decline(req, actor, note: str = "", *, source: str = "web") -> WorkRequest:
    ts._ai_check(req.org, "ai.answer_request", "요청 거절", source, "request")
    req = _lock_open(req, actor)
    _close(req, actor, "declined", note)
    _notify_requester(req, actor, "거절")
    return req


@transaction.atomic
def cancel(req, actor, *, source: str = "web") -> WorkRequest:
    ts._ai_check(req.org, "ai.create_request", "요청 취소", source, "request")
    req = WorkRequest.objects.select_for_update().get(pk=req.pk)
    if req.requested_by_id != actor.pk:
        raise ServiceError({"request": "요청한 사람만 취소할 수 있습니다."})
    if not req.is_open:
        raise ServiceError({"request": "이미 처리된 요청입니다."})
    _close(req, actor, "cancelled")
    return req


@transaction.atomic
def complete(req, actor, note: str = "", *, source: str = "web") -> WorkRequest:
    """수락한 일반 요청을 끝낸다. 답한 사람(또는 받는 쪽 팀원)이 닫는다."""
    ts._ai_check(req.org, "ai.answer_request", "요청 완료", source, "request")
    req = WorkRequest.objects.select_for_update().select_related("team").get(pk=req.pk)
    if req.kind != "general" or req.status != "accepted":
        raise ServiceError({"request": "수락한 일반 요청만 완료할 수 있습니다."})
    if not can_respond(actor, req):
        raise ServiceError({"request": "받는 사람(팀원)만 완료할 수 있습니다."})
    req.status = "done"
    if note:
        req.response_note = note.strip()[:RESPONSE_MAX]
    req.save(update_fields=["status", "response_note"])
    _notify_requester(req, actor, "완료")
    return req


# ---------- Discord ----------


def team_by_channel(channel_id: str):
    if not channel_id:
        return None
    return Team.objects.filter(discord_channel_id=channel_id).select_related("org").first()


def projects_for(req):
    """수락할 때 고를 프로젝트. 받는 팀이 맡은 프로젝트를 앞에 둔다."""
    qs = Project.objects.filter(org=req.org, is_archived=False)
    if req.team_id:
        mine = list(qs.filter(teams=req.team))
        return mine + [p for p in qs.exclude(teams=req.team)]
    return list(qs)
