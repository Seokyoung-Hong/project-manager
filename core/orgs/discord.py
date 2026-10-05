"""조직 ↔ Discord 서버 바인딩. IMPL-PLAN-4 §8.4.

전에는 `.env.discord`의 `ORG_ID`·`DISCORD_GUILD_ID`·`DISCORD_CHANNEL_ID` 한 벌이 전부라
**조직 하나 = 컨테이너 한 벌**이었다. 조직마다 Discord 서버가 다른 것이 정상이므로 그 관계를
DB로 올린다. 봇은 하나이고 여러 길드에 설치된다.

길드 하나는 조직 하나에만 붙는다(`discord_guild_id`가 unique) — 한 채널에 두 조직의 알림이
섞이면 아무도 안 본다. 알림 채널은 **길드 안에서** `/알림채널`로 정한다. core는 봇 토큰이 없어
채널 목록을 뽑을 수 없고, 그 토큰을 받아 오면 비밀 반경이 깨진다(GUIDE-00 §3).
"""

import http.client
import json
import urllib.error
import urllib.parse
import urllib.request
from datetime import date, timedelta

from django.conf import settings
from django.db import transaction
from django.utils import timezone

from common.errors import ServiceError

from .models import Organization
from .services import is_admin, require_admin


def _log(org, field, old, new, actor, source="web"):
    from tasks.models import ChangeLog

    ChangeLog.objects.create(
        target_type="org",
        target_id=org.pk,
        field=field,
        old_value=str(old or ""),
        new_value=str(new or ""),
        actor=actor,
        source=source,
    )


TOKEN_URL = "https://discord.com/api/v10/oauth2/token"


def guild_from_code(code: str, redirect_uri: str) -> str:
    """설치 콜백의 `code`를 Discord에서 토큰으로 바꾸고 응답의 `guild.id`를 돌려준다.

    콜백 쿼리의 `guild_id`는 누구나 고쳐 쓸 수 있다. 봇 설치(`bot` scope) 교환 응답에는 실제로
    설치된 서버가 실려 오므로 그 값만 믿는다(C-improvements S2).
    """
    if not settings.DISCORD_CLIENT_SECRET:
        raise ServiceError(
            {"guild_id": "서버에 DISCORD_CLIENT_SECRET이 없어 연결을 확인할 수 없습니다."}
        )
    if not code:
        raise ServiceError({"guild_id": "Discord 설치 응답에 code가 없습니다."})
    body = urllib.parse.urlencode(
        {
            "grant_type": "authorization_code",
            "code": code,
            "redirect_uri": redirect_uri,
            "client_id": settings.DISCORD_CLIENT_ID,
            "client_secret": settings.DISCORD_CLIENT_SECRET,
        }
    ).encode()
    req = urllib.request.Request(TOKEN_URL, data=body, method="POST")
    req.add_header("Content-Type", "application/x-www-form-urlencoded")
    req.add_header("User-Agent", "udally")
    try:
        with urllib.request.urlopen(req, timeout=15) as r:  # noqa: S310 — 고정 호스트
            data = json.loads(r.read())
    except (OSError, ValueError, http.client.HTTPException):
        # URLError·TimeoutError·연결 끊김은 모두 OSError다. 500이 아니라 안내로 끝낸다.
        raise ServiceError({"guild_id": "Discord에서 설치를 확인하지 못했습니다."}) from None
    guild = data.get("guild") if isinstance(data, dict) else None
    guild_id = str((guild or {}).get("id") or "") if isinstance(guild, dict) else ""
    if not guild_id:
        raise ServiceError({"guild_id": "Discord에서 설치를 확인하지 못했습니다."})
    return guild_id


# ---------- 마감 DM 대상 ----------

DUE_KINDS = {3: "d3", 1: "d1", 0: "d0"}


def _overdue_due_today(n: int, repeat: str, today: date) -> bool:
    """유예를 지나 n일째(1부터) 초과인 태스크에 오늘 초과 알림을 보내는가(`notify.overdue_repeat`).

    # ponytail: '한 번만'·'주 1회'는 초과 1일째(그 뒤 7일마다)에 보낸다. 그날 봇이 꺼져 있으면
    # 그 회차는 건너뛴다 — 보낸 기록을 core에 두면 정확해지지만 지금은 날짜 계산으로 충분하다.
    """
    if repeat == "never":
        return n == 1
    if repeat == "weekly":
        return (n - 1) % 7 == 0
    if repeat == "weekdays":
        return today.weekday() < 5
    return True


def deadline_alerts(org, today: date) -> list[tuple]:
    """오늘 보낼 마감 알림 `[(태스크, 종류)]`. 종류는 d3·d1·d0·overdue.

    알림 설정은 **여기 한 곳**에서 거른다 — 봇은 이 목록을 사람별·시각별로 나눠 보내기만 한다.
    조직 `notify.deadline_kinds` ∩ 담당자 `user.notify_kinds`, `notify.quiet_weekend`(토·일 없음),
    `notify.overdue_repeat`, 초과 유예 `task.overdue_grace_days`(화면 배지와 같은 기준).
    DM 수신 여부(`user.notify_dm`)와 시각은 봇이 멤버 설정으로 가른다.
    """
    from tasks.models import Task

    from .settings import effective

    if effective("notify.quiet_weekend", org=org) and today.weekday() >= 5:
        return []
    org_kinds = set(effective("notify.deadline_kinds", org=org))
    if not org_kinds:
        return []
    repeat = effective("notify.overdue_repeat", org=org)
    # 유예일은 프로젝트가 덮어쓸 수 있다(overridable). 프로젝트마다 한 번만 계산한다.
    grace_by_project: dict[int, date] = {}

    def overdue_before(project) -> date:
        if project.pk not in grace_by_project:
            days = effective("task.overdue_grace_days", org=org, project=project)
            grace_by_project[project.pk] = today - timedelta(days=days)
        return grace_by_project[project.pk]

    qs = (
        Task.objects.filter(
            project__org=org,
            project__is_archived=False,
            status__in=Task.OPEN,
            assignee__isnull=False,
            due_date__lte=today + timedelta(days=3),
        )
        .select_related("project", "assignee", "reviewer")
        .order_by("due_date", "id")
    )
    from projects.services import can_view_project

    out = []
    for t in qs:
        # 공개 범위가 바뀌어 담당자가 더는 못 보는 비공개 프로젝트면 제목을 DM으로 흘리지 않는다.
        if t.project.visibility != "org" and not can_view_project(t.assignee, t.project):
            continue
        delta = (t.due_date - today).days
        if delta < 0:
            before = overdue_before(t.project)
            if t.due_date >= before:
                continue  # 유예 안이다
            n = (before - t.due_date).days
            kind = "overdue" if _overdue_due_today(n, repeat, today) else None
        else:
            kind = DUE_KINDS.get(delta)
        if kind and kind in org_kinds and kind in effective("user.notify_kinds", user=t.assignee):
            out.append((t, kind))
    return out


def org_by_guild(guild_id: str):
    """그 길드에 붙은 조직. 없으면 None — 길드 명령이 이 값으로 범위를 정한다."""
    if not guild_id:
        return None
    return Organization.objects.filter(discord_guild_id=str(guild_id)).first()


def bound_orgs():
    """Discord 서버가 붙은 조직 전부. 틱이 이 목록을 돈다."""
    return Organization.objects.exclude(discord_guild_id=None).order_by("pk")


@transaction.atomic
def link_guild(org, guild_id: str, actor, source: str = "web") -> Organization:
    require_admin(actor, org)
    guild_id = str(guild_id or "").strip()
    if not guild_id.isdecimal():
        raise ServiceError({"guild_id": "Discord 서버를 확인하지 못했습니다."})
    taken = Organization.objects.filter(discord_guild_id=guild_id).exclude(pk=org.pk).first()
    if taken is not None:
        raise ServiceError(
            {"guild_id": f"이 Discord 서버는 이미 {taken.name} 조직에 연결되어 있습니다."}
        )
    old = org.discord_guild_id
    org.discord_guild_id = guild_id
    org.discord_linked_at = timezone.now()
    org.discord_linked_by = actor
    # 서버가 바뀌면 옛 채널 id는 그 서버의 것이라 쓸 수 없다.
    if old and old != guild_id:
        org.discord_channel_id = ""
    org.save(
        update_fields=[
            "discord_guild_id",
            "discord_channel_id",
            "discord_linked_at",
            "discord_linked_by",
        ]
    )
    _log(org, "discord_guild", old, guild_id, actor, source)
    return org


@transaction.atomic
def unlink_guild(org, actor, source: str = "web") -> Organization:
    require_admin(actor, org)
    if source == "web":  # core는 Discord를 부르지 않는다. 봇이 보고한 서버 권한으로 판정한다
        from .channels import require_discord

        require_discord(actor, org, "unlink_guild")
    old = org.discord_guild_id
    org.discord_guild_id = None
    org.discord_channel_id = ""
    org.discord_linked_at = None
    org.discord_linked_by = None
    org.save(
        update_fields=[
            "discord_guild_id",
            "discord_channel_id",
            "discord_linked_at",
            "discord_linked_by",
        ]
    )
    _log(org, "discord_guild", old, "", actor, source)
    return org


@transaction.atomic
def set_channel_by_guild(guild_id: str, actor, channel_id: str) -> Organization:
    """`/알림채널`이 부른다. 길드에 붙은 조직의 관리자만 바꿀 수 있다."""
    org = org_by_guild(guild_id)
    if org is None:
        raise ServiceError({"guild_id": "이 서버는 아직 조직에 연결되지 않았습니다."})
    if not is_admin(actor, org):
        raise ServiceError({"org": "조직 관리자만 할 수 있습니다."})
    channel_id = str(channel_id or "").strip()
    if not channel_id.isdecimal():
        raise ServiceError({"channel_id": "채널을 확인하지 못했습니다."})
    old = org.discord_channel_id
    org.discord_channel_id = channel_id
    org.save(update_fields=["discord_channel_id"])
    _log(org, "discord_channel", old, channel_id, actor, "dc")
    return org
