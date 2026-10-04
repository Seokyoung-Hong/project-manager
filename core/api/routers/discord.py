"""Discord 봇 명령이 들어오는 곳.

봇은 자기 이름으로 일하지 않는다. 연결된 Discord 사용자를 **사람**으로 바꿔 그 사람의 팀
범위 안에서만 움직인다(`get_visible_task(actor, …)`). 변경 이력에는 행위자=그 사람,
경로=Discord(`dc`), 토큰=봇 토큰이 남는다.

라우터 인증이 `BotTokenAuth` 하나라서 세션 쿠키·읽기·쓰기 토큰은 이 경로에 들어오지 못한다.
"""

from ninja import Router
from ninja.errors import HttpError

from accounts.models import User
from accounts.services import link_discord, unlink_discord_by_id, user_by_discord_id
from orgs import channels as org_channels
from orgs import discord as org_discord
from orgs import settings as org_settings
from orgs.models import OrgMembership, Team
from orgs.services import orgs_of, set_team_channel
from projects.models import Project
from projects.services import set_project_channel
from tasks import work_requests as wr
from tasks.brief import task_brief
from tasks.models import Task
from tasks.services import (
    by_due,
    create_task,
    extend_due,
    get_visible_task,
    today_view,
    transition,
    update_task,
    update_text,
    visible_tasks,
)

from ..auth import BotTokenAuth
from ..schemas import (
    DiscordActorIn,
    DiscordAlertsIn,
    DiscordChannelCheckIn,
    DiscordChannelIn,
    DiscordExtendIn,
    DiscordGuildReportIn,
    DiscordLinkIn,
    DiscordNoteIn,
    DiscordNoticeAckIn,
    DiscordOrgChannelIn,
    DiscordRequestAnswerIn,
    DiscordRequestIn,
    DiscordStatusIn,
    DiscordTaskCreateIn,
    DiscordTaskUpdateIn,
)
from ..serialize import request_out, task_out

router = Router(tags=["discord"], auth=BotTokenAuth())

UNLINKED = "연결되지 않은 Discord 계정입니다. 웹 설정 → 프로필에서 연결 코드를 받으세요."


def _actor(discord_user_id: str):
    user = user_by_discord_id(discord_user_id)
    if user is None:
        raise HttpError(404, UNLINKED)
    return user


def _ctx(request, actor) -> dict:
    """X-Source 헤더를 믿지 않는다. 이 라우터에 들어온 것 자체가 경로의 증거다."""
    return {"actor": actor, "source": "dc", "token": getattr(request, "api_token", None)}


def _task(actor, task_id: int):
    task = get_visible_task(actor, task_id)
    if task is None:
        raise HttpError(404, "태스크를 찾을 수 없습니다.")
    return task


@router.post("/link", response=dict)
def link(request, payload: DiscordLinkIn):
    user = link_discord(payload.code, payload.discord_user_id)
    return {"display_name": user.display_name}


@router.post("/unlink", response=dict)
def unlink(request, payload: DiscordActorIn):
    return {"unlinked": unlink_discord_by_id(payload.discord_user_id)}


@router.post("/today", response=dict)
def today(request, payload: DiscordActorIn):
    """식별자를 쿼리 문자열에 싣지 않으려고 GET이 아니라 POST다."""
    actor = _actor(payload.discord_user_id)
    view = today_view(actor)
    return {
        "display_name": actor.display_name,
        "date": view["date"].isoformat(),
        "items": [task_brief(t) for t in view["items"]],
        "counts": view["counts"],
    }


@router.post("/tasks/{task_id}/done", response=dict)
def done(request, task_id: int, payload: DiscordActorIn):
    actor = _actor(payload.discord_user_id)
    task = _task(actor, task_id)
    was = task.get_status_display()
    # 사용자는 버전을 본 적이 없다. 의도는 "지금 완료로 바꿔라"다. 한 요청 안에서 읽고
    # 그 값으로 CAS를 건다 — 그 사이(수 ms)에 끼면 409로 알린다(조용히 덮어쓰지 않는다).
    task = transition(
        task, "done", expected_version=task.version, reason="", **_ctx(request, actor)
    )
    return {"was": was, "task": task_out(task)}


@router.post("/tasks/{task_id}/extend", response=dict)
def extend(request, task_id: int, payload: DiscordExtendIn):
    actor = _actor(payload.discord_user_id)
    task = _task(actor, task_id)
    task = extend_due(
        task,
        payload.due_date,
        payload.reason,
        expected_version=task.version,
        **_ctx(request, actor),
    )
    return {"task": task_out(task)}


# ---------- 슬래시 명령 (IMPL-PLAN-3). 자동완성 목록도 행위자 범위로만 준다 ----------


def _project(actor, project_id: int):
    project = Project.objects.filter(pk=project_id, org__in=orgs_of(actor)).first()
    if project is None:
        raise HttpError(404, "프로젝트를 찾을 수 없습니다.")
    return project


def _assignee(assignee_id: int | None):
    if assignee_id is None:
        return None
    user = User.objects.filter(pk=assignee_id).first()
    if user is None:
        raise HttpError(400, "담당자를 찾을 수 없습니다.")
    return user


@router.get("/orgs", response=list[dict])
def orgs(request):
    """Discord 서버가 붙은 조직 전부. 틱이 이 목록을 돌며 조직마다 알림을 보낸다.

    `settings`는 **실효 설정**이다 — 봇이 기본값을 따로 알 필요가 없게 여기서 다 채워 보낸다.
    """
    out = []
    for org in org_discord.bound_orgs():
        values = {
            spec.key: org_settings.effective(spec.key, org=org)
            for spec in org_settings.SPECS.values()
            if spec.scope == "org"
        }
        out.append(
            {
                "org_id": org.pk,
                "name": org.name,
                "guild_id": org.discord_guild_id,
                "channel_id": org.discord_channel_id,
                "settings": values,
            }
        )
    return out


@router.get("/orgs/{int:org_id}/members", response=list[dict])
def org_members(request, org_id: int):
    """그 조직의 멤버와 개인 알림 설정. 봇이 누구에게 무엇을 보낼지 여기서 정한다."""
    rows = (
        OrgMembership.objects.filter(org_id=org_id, user__is_active=True)
        .select_related("user")
        .order_by("user__display_name")
    )
    out = []
    for m in rows:
        u = m.user
        out.append(
            {
                "id": u.pk,
                "display_name": u.display_name,
                "discord_user_id": u.discord_user_id,
                "role": m.role,
                "notify_dm": org_settings.effective("user.notify_dm", user=u),
                "notify_kinds": list(org_settings.effective("user.notify_kinds", user=u)),
                "notify_hour": org_settings.effective("user.notify_hour", user=u),
            }
        )
    return out


def _people(users) -> list[dict]:
    return [
        {"id": u.pk, "display_name": u.display_name, "discord_user_id": u.discord_user_id}
        for u in users
    ]


@router.get("/projects/{int:project_id}/owners", response=list[dict])
def project_owners(request, project_id: int):
    """프로젝트 관리자. 막힘·검토 에스컬레이션 DM의 1차 수신자다."""
    project = Project.objects.filter(pk=project_id).first()
    if project is None:
        raise HttpError(404, "프로젝트를 찾을 수 없습니다.")
    return _people(project.owners.filter(is_active=True).order_by("display_name"))


@router.get("/orgs/{int:org_id}/admins", response=list[dict])
def org_admins(request, org_id: int):
    """조직 관리자. 프로젝트 관리자가 0명일 때의 대체 수신자다."""
    rows = (
        OrgMembership.objects.filter(org_id=org_id, role="admin", user__is_active=True)
        .select_related("user")
        .order_by("user__display_name")
    )
    return _people([m.user for m in rows])


@router.post("/orgs/channel", response=dict)
def org_channel(request, payload: DiscordOrgChannelIn):
    """`/알림채널`. 길드에 붙은 조직의 관리자만 바꿀 수 있다(서비스가 검사한다)."""
    actor = _actor(payload.discord_user_id)
    org = org_discord.set_channel_by_guild(payload.guild_id, actor, payload.channel_id)
    return {"org_id": org.pk, "name": org.name, "channel_id": org.discord_channel_id}


@router.post("/projects", response=list[dict])
def projects(request, payload: DiscordActorIn):
    """자동완성과 채널 생성용. 채널 id를 같이 주어 봇이 중복 생성 전에 확인한다."""
    actor = _actor(payload.discord_user_id)
    qs = Project.objects.filter(org__in=orgs_of(actor), is_archived=False)
    return [
        {"id": p.pk, "name": p.name, "org_id": p.org_id, "discord_channel_id": p.discord_channel_id}
        for p in qs
    ]


@router.post("/teams", response=list[dict])
def teams(request, payload: DiscordActorIn):
    actor = _actor(payload.discord_user_id)
    qs = Team.objects.filter(org__in=orgs_of(actor))
    return [
        {"id": t.pk, "name": t.name, "org_id": t.org_id, "discord_channel_id": t.discord_channel_id}
        for t in qs
    ]


@router.post("/members", response=list[dict])
def members(request, payload: DiscordActorIn):
    actor = _actor(payload.discord_user_id)
    qs = (
        User.objects.filter(org_memberships__org__in=orgs_of(actor), is_active=True)
        .distinct()
        .order_by("display_name")
    )
    return [{"id": u.pk, "display_name": u.display_name} for u in qs]


@router.post("/mytasks", response=list[dict])
def mytasks(request, payload: DiscordActorIn):
    """`번호` 자동완성용. 그 사람의 미완료만 — 조직 전체는 25개 상한에 걸리고 캐시도 못 한다."""
    actor = _actor(payload.discord_user_id)
    qs = visible_tasks(actor).filter(
        assignee=actor, status__in=Task.OPEN, project__is_archived=False
    )
    return [task_brief(t) for t in sorted(qs, key=by_due)]


@router.post("/tasks", response=dict)
def create(request, payload: DiscordTaskCreateIn):
    actor = _actor(payload.discord_user_id)
    task = create_task(
        project=_project(actor, payload.project_id),
        title=payload.title,
        assignee=_assignee(payload.assignee_id),
        priority=payload.priority,
        due_date=payload.due_date,
        no_due_reason=payload.no_due_reason,
        **_ctx(request, actor),
    )
    return {"task": task_out(task)}


@router.post("/tasks/{task_id}/update", response=dict)
def update(request, task_id: int, payload: DiscordTaskUpdateIn):
    actor = _actor(payload.discord_user_id)
    task = _task(actor, task_id)
    changes = payload.dict(exclude_unset=True, exclude={"discord_user_id"})
    if "assignee_id" in changes:
        changes["assignee"] = _assignee(changes.pop("assignee_id"))
    if changes:
        task = update_task(task, changes, expected_version=task.version, **_ctx(request, actor))
    return {"task": task_out(task)}


@router.post("/tasks/{task_id}/note", response=dict)
def note(request, task_id: int, payload: DiscordNoteIn):
    """MCP의 append_note와 같은 의미: 기존 메모 뒤에 줄을 덧붙인다."""
    actor = _actor(payload.discord_user_id)
    task = _task(actor, task_id)
    text = payload.text.strip()
    if not text:
        raise HttpError(400, "메모 내용을 입력하세요.")
    notes = f"{task.notes}\n{text}" if task.notes else text
    task = update_text(task, "notes", notes, actor=actor)
    return {"task": task_out(task)}


@router.post("/tasks/{task_id}/status", response=dict)
def status(request, task_id: int, payload: DiscordStatusIn):
    actor = _actor(payload.discord_user_id)
    task = _task(actor, task_id)
    was = task.get_status_display()
    task = transition(
        task,
        payload.status,
        expected_version=task.version,
        reason=payload.reason,
        **_ctx(request, actor),
    )
    return {"was": was, "task": task_out(task)}


@router.post("/teams/{team_id}/channel", response=dict)
def team_channel(request, team_id: int, payload: DiscordChannelIn):
    """채널을 만들지 않는다. 봇이 만든 결과 id를 적을 뿐이다(core는 Discord로 나가지 않는다)."""
    actor = _actor(payload.discord_user_id)
    team = Team.objects.filter(pk=team_id, org__in=orgs_of(actor)).first()
    if team is None:
        raise HttpError(404, "팀을 찾을 수 없습니다.")
    team = set_team_channel(team, payload.channel_id, actor)
    return {"id": team.pk, "name": team.name, "discord_channel_id": team.discord_channel_id}


@router.post("/projects/{project_id}/channel", response=dict)
def project_channel(request, project_id: int, payload: DiscordChannelIn):
    actor = _actor(payload.discord_user_id)
    project = set_project_channel(_project(actor, project_id), payload.channel_id, actor)
    return {
        "id": project.pk,
        "name": project.name,
        "discord_channel_id": project.discord_channel_id,
    }


# ---------- 채널 관리(IMPL-PLAN-5 B). core는 Discord로 나가지 않고 봇이 올린 값만 비교한다 ----------


@router.get("/channels", response=list[dict])
def channel_targets(request):
    """봇이 감시·조정할 대상 전부(연결 안 된 팀·프로젝트 포함 — 비공개 생성이 허용 집합을 여기서 읽는다).

    `allowed_ids` = 허용 집합 ∪ 명시적 허용(권한 밖 비교용). `grant_ids` = 허용 집합(자동 관리가 덮어쓰기를 넣을 계정).
    """
    out = []
    for org in org_discord.bound_orgs():
        for kind, obj in org_channels.targets(org):
            base = org_channels.base_allowed(kind, obj)
            cid = obj.discord_channel_id
            out.append(
                {
                    "org_id": org.pk,
                    "guild_id": org.discord_guild_id,
                    "kind": kind,
                    "id": obj.pk,
                    "name": obj.name,
                    "channel_id": cid,
                    "managed": obj.discord_channel_managed,
                    "allowed_ids": sorted(base | (org_channels.explicit_allowed(cid) if cid else set())),
                    "grant_ids": sorted(base),
                }
            )
    return out


@router.post("/channel-check", response=dict)
def channel_check(request, payload: DiscordChannelCheckIn):
    """채널 연결의 유일한 문. 권한 밖 인원이 있거나 확인 불가면 `allow_outsiders` 없이는 연결하지 않는다."""
    actor = _actor(payload.discord_user_id)
    if payload.kind == "team":
        obj = Team.objects.filter(pk=payload.target_id, org__in=orgs_of(actor)).first()
    elif payload.kind == "project":
        obj = Project.objects.filter(pk=payload.target_id, org__in=orgs_of(actor)).first()
    else:
        raise HttpError(400, "kind는 team 또는 project여야 합니다.")
    if obj is None:
        raise HttpError(404, "대상을 찾을 수 없습니다.")
    viewers = None if payload.viewers is None else [v.dict() for v in payload.viewers]
    return org_channels.connect(
        payload.kind,
        obj,
        payload.channel_id,
        actor,
        viewers=viewers,
        allow_outsiders=payload.allow_outsiders,
        managed=payload.managed,
        created=payload.created,
    )


@router.post("/channel-alerts", response=dict)
def channel_alerts(request, payload: DiscordAlertsIn):
    """채널별 **현재** 권한 밖 인원 전체. 새로 보인 사람만 조직 관리자에게 DM으로 알린다."""
    org = org_discord.org_by_guild(payload.guild_id)
    if org is None:
        raise HttpError(404, "이 서버는 조직에 연결되지 않았습니다.")
    for ch in payload.channels:
        org_channels.sync_alerts(
            org,
            ch.channel_id,
            [v.dict() for v in ch.outsiders],
            None if ch.missing is None else [v.dict() for v in ch.missing],
        )
    return {"ok": True}


@router.post("/guild-report", response=dict)
def guild_report(request, payload: DiscordGuildReportIn):
    """봇이 이 길드에서 가진 권한과 감시 여부. 권한이 모자라면 웹이 재승인을 안내한다."""
    org = org_discord.org_by_guild(payload.guild_id)
    if org is None:
        raise HttpError(404, "이 서버는 조직에 연결되지 않았습니다.")
    org_channels.record_guild_report(org, payload.permissions, payload.watching)
    return {"ok": True}


# ---------- 요청 (/요청). 팀 채널에서 치면 그 팀으로 간다 ----------


def _request(actor, request_id: int):
    req = wr.get_visible_request(actor, request_id)
    if req is None:
        raise HttpError(404, "요청을 찾을 수 없습니다.")
    return req


@router.post("/requests", response=dict)
def create_request(request, payload: DiscordRequestIn):
    actor = _actor(payload.discord_user_id)
    team = to_user = None
    if payload.to_user_id is not None:
        to_user = _assignee(payload.to_user_id)
    elif payload.team_id is not None:
        team = Team.objects.filter(pk=payload.team_id, org__in=orgs_of(actor)).first()
    else:
        team = wr.team_by_channel(payload.channel_id)
    if team is None and to_user is None:
        raise HttpError(400, "팀 채널에서 쓰거나 받을 팀·사람을 골라 주세요.")
    org = team.org if team else None
    if org is None:
        # 사람에게 보낼 때는 두 사람이 함께 속한 조직. 여럿이면 가장 먼저 만든 조직이다.
        org = orgs_of(actor).filter(memberships__user=to_user).order_by("pk").first()
        if org is None:
            raise HttpError(400, "같은 조직의 멤버에게만 요청할 수 있습니다.")
    req = wr.create_request(
        org=org,
        kind=payload.kind,
        title=payload.title,
        body=payload.body,
        actor=actor,
        source="dc",
        team=team,
        to_user=to_user,
        posted_in=payload.channel_id,
    )
    out = request_out(req)
    # 명령을 친 채널이 받는 팀의 채널일 때만 봇이 거기 공개로 알린다(다른 채널에 새지 않게).
    out["announce_here"] = bool(team and payload.channel_id == team.discord_channel_id)
    return {"request": out}


@router.post("/requests/mine", response=dict)
def my_requests(request, payload: DiscordActorIn):
    """`번호` 자동완성과 `/요청목록`. 내가 답할 대기 요청과 내가 보낸 대기 요청."""
    actor = _actor(payload.discord_user_id)
    received = (
        wr.received(actor)
        .filter(status__in=("pending", "accepted"))
        .exclude(status="accepted", kind__in=("work", "assign"))
    )
    sent = wr.visible_requests(actor).filter(requested_by=actor, status="pending")
    return {
        "received": [request_out(r) for r in received[:25]],
        "sent": [request_out(r) for r in sent[:25]],
    }


@router.post("/requests/{int:request_id}/projects", response=list[dict])
def request_projects(request, request_id: int, payload: DiscordActorIn):
    """수락할 때 `프로젝트` 자동완성. 받는 팀이 맡은 프로젝트가 앞에 온다."""
    req = _request(_actor(payload.discord_user_id), request_id)
    return [{"id": p.pk, "name": p.name} for p in wr.projects_for(req)]


@router.post("/requests/{int:request_id}/accept", response=dict)
def accept_request(request, request_id: int, payload: DiscordRequestAnswerIn):
    actor = _actor(payload.discord_user_id)
    req = _request(actor, request_id)
    project = _project(actor, payload.project_id) if payload.project_id else None
    req = wr.accept(
        req,
        actor,
        source="dc",
        project=project,
        assignee=_assignee(payload.assignee_id),
        due_date=payload.due_date,
        note=payload.note,
    )
    out = {"request": request_out(req)}
    if req.task_id:
        out["task"] = task_out(req.task)
    return out


@router.post("/requests/{int:request_id}/decline", response=dict)
def decline_request(request, request_id: int, payload: DiscordRequestAnswerIn):
    actor = _actor(payload.discord_user_id)
    return {"request": request_out(wr.decline(_request(actor, request_id), actor, payload.note))}


@router.post("/requests/{int:request_id}/done", response=dict)
def complete_request(request, request_id: int, payload: DiscordRequestAnswerIn):
    actor = _actor(payload.discord_user_id)
    return {"request": request_out(wr.complete(_request(actor, request_id), actor, payload.note))}


# ---------- 알림 발송함. 봇이 틱마다 가져가 보내고 ack한다 ----------


@router.get("/notices", response=list[dict])
def notices(request):
    return [
        {
            "id": n.pk,
            "discord_user_id": n.user.discord_user_id if n.user_id else None,
            "channel_id": n.channel_id,
            "text": n.text,
        }
        for n in wr.pending_notices()
    ]


@router.post("/notices/ack", response=dict)
def ack_notices(request, payload: DiscordNoticeAckIn):
    return {"acked": wr.mark_sent(payload.ids)}
