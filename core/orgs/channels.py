"""팀·프로젝트 Discord 채널의 권한 밖 인원 비교와 경고 상태. IMPL-PLAN-5 B.

core는 Discord로 나가지 않는다(GUIDE-00 §3). 채널을 누가 보는지는 봇이 계산해 올리고, 여기서는
PM 데이터로 만든 "허용 집합"과 비교해 상태만 남긴다. 권한 밖 인원을 쫓아내지는 않는다.
"""

from datetime import timedelta

from django.conf import settings
from django.db import transaction
from django.utils import timezone

from common.errors import ServiceError

from .models import DiscordChannelAlert, DiscordMemberPermission, OrgMembership, Team

# VIEW_CHANNEL | SEND_MESSAGES | READ_MESSAGE_HISTORY | MANAGE_CHANNELS | MANAGE_ROLES. 봇은 가진 권한만
# 덮어쓰기로 줄 수 있어 기록 읽기도 둔다. 자동 관리가 멤버 덮어쓰기를 넣으려면 Manage Roles가 필요하다.
REQUIRED_PERMISSIONS = 268504080
WATCH_STALE = timedelta(minutes=15)  # 봇 감시 주기는 5분. 세 번 놓치면 "감시 꺼짐"
CHECK_REQUIRED = "채널 연결은 권한 밖 인원 확인을 거쳐야 합니다. Discord의 /팀채널·/프로젝트채널로 연결해 주세요."


def _linked(users) -> set[str]:
    return {
        u.discord_user_id
        for u in users
        if u.is_active and u.discord_user_id and u.discord_linked_at
    }


def targets(org) -> list[tuple[str, object]]:
    """채널을 가질 수 있는 팀·프로젝트. 보관한 프로젝트는 뺀다."""
    from projects.models import Project

    out: list[tuple[str, object]] = [("team", t) for t in Team.objects.filter(org=org)]
    out += [("project", p) for p in Project.objects.filter(org=org, is_archived=False)]
    return out


def base_allowed(kind: str, obj) -> set[str]:
    """B1: 팀 채널 = 팀원, 프로젝트 채널 = 프로젝트 관리자 ∪ 담당 팀의 팀원. PM에 연결한 Discord 계정만."""
    if kind == "team":
        return _linked(obj.members.all())
    users = list(obj.owners.all())
    for team in obj.teams.all():
        users += list(team.members.all())
    return _linked(users)


def explicit_allowed(channel_id: str) -> set[str]:
    return set(
        DiscordChannelAlert.objects.filter(channel_id=channel_id, status="allowed").values_list(
            "discord_user_id", flat=True
        )
    )


def outsiders(viewers: list[dict], allowed: set[str]) -> list[dict]:
    """채널을 보는 사람 중 허용 집합 밖. 순수 함수. 봇 계정은 봇이 이미 뺐다."""
    seen: set[str] = set()
    out = []
    for v in viewers:
        uid = str(v["id"])
        if uid in allowed or uid in seen:
            continue
        seen.add(uid)
        out.append({"id": uid, "name": v.get("name") or ""})
    return out


def label(kind: str, obj) -> str:
    return f"{'팀' if kind == 'team' else '프로젝트'} {obj.name}"


def target_by_channel(org, channel_id: str):
    """이 조직에서 그 채널을 연결한 (kind, obj). 없으면 None."""
    for kind, obj in targets(org):
        if obj.discord_channel_id and obj.discord_channel_id == channel_id:
            return kind, obj
    return None


def linked_elsewhere(channel_id: str, kind: str, pk: int):
    """그 채널을 이미 연결한 다른 팀·프로젝트(kind, obj). 없으면 None. 한 채널은 한 대상에만 연결한다."""
    from projects.models import Project

    other = (
        Team.objects.filter(discord_channel_id=channel_id)
        .exclude(pk=pk if kind == "team" else None)
        .first()
    )
    if other:
        return "team", other
    other = (
        Project.objects.filter(discord_channel_id=channel_id)
        .exclude(pk=pk if kind == "project" else None)
        .first()
    )
    return ("project", other) if other else None


def clear_alerts(channel_id: str, kind: str = "", pk: int | None = None):
    """채널 연결을 끊거나 바꾸면 그 채널의 경고·허용 기록을 지운다.

    옛 데이터에 같은 채널을 쓰는 다른 대상이 남아 있으면 그쪽의 허용 목록이므로 지우지 않는다.
    """
    if channel_id and not (kind and linked_elsewhere(channel_id, kind, pk)):
        DiscordChannelAlert.objects.filter(channel_id=channel_id).delete()


@transaction.atomic
def connect(
    kind, obj, channel_id, actor, *, viewers, allow_outsiders, managed, created, guild_id
) -> dict:
    """봇이 채널 연결 전에 부른다. 권한 밖 인원이 있거나 확인할 수 없으면(viewers=None) 허용 옵션 없이는 연결하지 않는다."""
    from projects.services import set_project_channel

    from .services import require_admin, set_team_channel

    require_admin(actor, obj.org)
    channel_id = str(channel_id or "").strip()
    if not channel_id.isdecimal():
        raise ServiceError({"channel_id": "채널을 확인하지 못했습니다."})
    # 채널이 이 조직의 연결 길드 것이어야 한다(다른 서버의 채널 id로 연결하는 것을 막는다)
    if not obj.org.discord_guild_id or str(guild_id) != obj.org.discord_guild_id:
        raise ServiceError({"guild_id": "이 조직에 연결된 Discord 서버의 채널이 아닙니다."})
    # 한 채널은 한 대상에만 연결한다 — 두 대상이 허용 집합을 다르게 보면 경고·조정이 서로 엇갈린다
    if (other := linked_elsewhere(channel_id, kind, obj.pk)) is not None:
        raise ServiceError({"channel_id": f"이미 {label(*other)}에 연결된 채널입니다."})
    unknown = viewers is None and not created
    found = []
    if viewers is not None and not created:
        found = outsiders(viewers, base_allowed(kind, obj) | explicit_allowed(channel_id))
    if (found or unknown) and not allow_outsiders:
        return {"linked": False, "unknown": unknown, "outsiders": found}
    if managed is None and created:
        managed = True
    setter = set_team_channel if kind == "team" else set_project_channel
    setter(obj, channel_id, actor, checked=True, managed=managed)
    for o in found:
        DiscordChannelAlert.objects.update_or_create(
            channel_id=channel_id,
            discord_user_id=o["id"],
            defaults={
                "org": obj.org,
                "display_name": o["name"][:100],
                "status": "allowed",
                "resolved_by": actor,
                "resolved_at": timezone.now(),
            },
        )
    return {"linked": True, "unknown": unknown, "outsiders": found}


def _warn_admins(org, kind, obj, new: list[dict]):
    from tasks.work_requests import notify

    names = ", ".join(n["name"] or n["id"] for n in new)
    text = (
        f"⚠️ {label(kind, obj)}의 Discord 채널 <#{obj.discord_channel_id}>을 권한 밖 {len(new)}명이 "
        f"볼 수 있습니다: {names}\n허용하거나 Discord에서 정리해 주세요: "
        f"{settings.SITE_URL}/orgs/{org.pk}/discord"
    )
    for m in OrgMembership.objects.filter(org=org, role="admin").select_related("user"):
        notify(org, text, user=m.user)  # notify가 1900자로 자르고, 채널에는 올리지 않는다


@transaction.atomic
def sync_alerts(org, channel_id: str, current: list[dict], missing: list[dict] | None = None):
    """봇이 올린 "지금 권한 밖 전체"를 기존 행과 맞춘다. 새로 보이거나 gone에서 돌아온 사람만 DM으로 알린다."""
    hit = target_by_channel(org, channel_id)
    if hit is None:
        return
    rows = {r.discord_user_id: r for r in DiscordChannelAlert.objects.filter(channel_id=channel_id)}
    now_ids, new = set(), []
    for o in current:
        uid = o["id"]
        now_ids.add(uid)
        row = rows.get(uid)
        if row is None:
            DiscordChannelAlert.objects.create(
                org=org, channel_id=channel_id, discord_user_id=uid, display_name=o["name"][:100]
            )
            new.append(o)
        elif row.status in ("gone", "missing"):
            row.status, row.display_name = "open", o["name"][:100]
            row.save(update_fields=["status", "display_name"])
            new.append(o)
    for uid, row in rows.items():
        if uid not in now_ids and row.status == "open":
            row.status = "gone"
            row.save(update_fields=["status"])
    if missing is not None:  # 자동 관리가 꺼진 채널의 "Discord 미접근 팀원" 안내. 알림은 없다
        want = {
            m["id"]: m
            for m in missing
            if m["id"] not in now_ids and (m["id"] not in rows or rows[m["id"]].status == "missing")
        }
        DiscordChannelAlert.objects.filter(channel_id=channel_id, status="missing").exclude(
            discord_user_id__in=want
        ).delete()
        for uid, m in want.items():
            DiscordChannelAlert.objects.get_or_create(
                channel_id=channel_id,
                discord_user_id=uid,
                defaults={"org": org, "display_name": m["name"][:100], "status": "missing"},
            )
    if new:
        _warn_admins(org, *hit, new)


def resolve(org, alert_id: int, action: str, actor):
    """웹의 [허용]·[철회]. 철회는 행을 지운다 — 다음 감시에서 아직 보이면 다시 경고가 된다."""
    from .services import require_admin

    require_admin(actor, org)
    require_discord(actor, org, "managed")
    row = DiscordChannelAlert.objects.filter(pk=alert_id, org=org).first()
    if row is None:
        raise ServiceError({"alert": "경고를 찾을 수 없습니다."})
    if action == "allow" and row.status in ("open", "gone"):
        row.status, row.resolved_by, row.resolved_at = "allowed", actor, timezone.now()
        row.save(update_fields=["status", "resolved_by", "resolved_at"])
    elif action == "revoke" and row.status == "allowed":
        row.delete()


# 기능별 필요 Discord 서버 권한(비트). 웹·REST 동작은 봇이 보고한 값으로, 슬래시·MCP는 봇이 직접 확인한다.
MANAGE_CHANNELS, MANAGE_ROLES, MANAGE_GUILD, ADMINISTRATOR = 1 << 4, 1 << 28, 1 << 5, 1 << 3
NEEDS = {
    "channel": MANAGE_CHANNELS,  # 채널 연결 해제(REST)
    "managed": MANAGE_CHANNELS | MANAGE_ROLES,  # 자동 관리 켜기·끄기, 권한 밖 인원 허용·철회
    "unlink_guild": MANAGE_GUILD,  # 웹의 Discord 서버 연결 해제
}
NEED_NAMES = {MANAGE_CHANNELS: "채널 관리", MANAGE_ROLES: "역할 관리", MANAGE_GUILD: "서버 관리"}
PERMISSION_STALE = timedelta(minutes=15)


def require_discord(user, org, feature: str):
    """PM 관리자 확인에 더해 그 사용자의 Discord 서버 권한을 확인한다. 확인할 수 없으면 거절한다(fail closed)."""
    if not (user.discord_user_id and user.discord_linked_at):
        raise ServiceError(
            {"discord": "Discord 계정 연결이 필요합니다. 설정 → 프로필에서 연결해 주세요."}
        )
    row = DiscordMemberPermission.objects.filter(org=org, user=user).first()
    if row is None:
        raise ServiceError(
            {
                "discord": "Discord 권한 확인 정보가 없습니다. 서버 멤버 인텐트가 꺼져 있으면 "
                "웹에서는 할 수 없으니 Discord에서 명령으로 해 주세요."
            }
        )
    if timezone.now() - row.reported_at > PERMISSION_STALE:
        raise ServiceError(
            {"discord": "권한 확인 정보가 오래됐습니다. 잠시 뒤 다시 시도해 주세요."}
        )
    need = NEEDS[feature]
    if not (row.permissions & ADMINISTRATOR) and (row.permissions & need) != need:
        names = ", ".join(n for bit, n in NEED_NAMES.items() if need & bit)
        raise ServiceError({"discord": f"Discord 서버에서 {names} 권한이 필요합니다."})


def record_member_permissions(org, members: list[dict]):
    """봇이 올린 (Discord id → 권한 비트). 이 조직의 멤버로 연결된 계정만 받는다."""
    from accounts.models import User

    by_did = {
        u.discord_user_id: u
        for u in User.objects.filter(org_memberships__org=org, discord_user_id__isnull=False)
        if u.discord_linked_at
    }
    now = timezone.now()
    for m in members:
        user = by_did.get(str(m["discord_user_id"]))
        if user is not None:
            DiscordMemberPermission.objects.update_or_create(
                org=org, user=user, defaults={"permissions": m["permissions"], "reported_at": now}
            )


def set_managed(org, kind: str, target_id: int, managed: bool, actor):
    from projects.models import Project

    from .services import require_admin

    require_admin(actor, org)
    require_discord(actor, org, "managed")
    model = Team if kind == "team" else Project
    obj = model.objects.filter(pk=target_id, org=org).first()
    if obj is None:
        raise ServiceError({"target": "대상을 찾을 수 없습니다."})
    if managed and not obj.discord_channel_id:
        raise ServiceError({"target": "채널이 연결된 대상만 자동 관리를 켤 수 있습니다."})
    model.objects.filter(pk=obj.pk).update(discord_channel_managed=managed)


def record_guild_report(org, permissions: int | None, watching: bool, intent_denied: bool = False):
    org.discord_bot_permissions = permissions
    org.discord_intent_denied = intent_denied
    fields = ["discord_bot_permissions", "discord_intent_denied"]
    if watching:
        org.discord_watch_at = timezone.now()
        fields.append("discord_watch_at")
    org.save(update_fields=fields)


def needs_reauthorization(org) -> bool:
    p = org.discord_bot_permissions
    return p is not None and (p & REQUIRED_PERMISSIONS) != REQUIRED_PERMISSIONS


def watching(org) -> bool:
    return bool(org.discord_watch_at and timezone.now() - org.discord_watch_at < WATCH_STALE)


def overview(org) -> list[dict]:
    """웹 표. 대상마다 연결 채널·상태(ok|alert|unlinked|unwatched)와 경고 행."""
    rows = list(DiscordChannelAlert.objects.filter(org=org).order_by("first_seen"))
    on = watching(org)
    out = []
    for kind, obj in targets(org):
        cid = obj.discord_channel_id
        mine = [r for r in rows if cid and r.channel_id == cid]
        opened = [r for r in mine if r.status == "open"]
        if not cid:
            state = "unlinked"
        elif opened:
            state = "alert"
        elif not on:
            state = "unwatched"
        else:
            state = "ok"
        out.append(
            {
                "kind": kind,
                "id": obj.pk,
                "name": obj.name,
                "label": label(kind, obj),
                "channel_id": cid,
                "managed": obj.discord_channel_managed,
                "state": state,
                "open": opened,
                "allowed": [r for r in mine if r.status == "allowed"],
                "gone": [r for r in mine if r.status == "gone"],
                # 자동 관리가 꺼진 채널에서만 "Discord 미접근 팀원"으로 안내한다
                "missing": [
                    r for r in mine if r.status == "missing" and not obj.discord_channel_managed
                ],
            }
        )
    return out
