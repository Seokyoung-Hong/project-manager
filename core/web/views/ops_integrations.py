"""운영 콘솔 연동 화면(IMPL-PLAN-10 §6.5). GitHub 설치·Discord 서버·알림 대기열은 집계만 보인다."""

from datetime import timedelta

from django.conf import settings
from django.db.models import Count, Max, Min, Q
from django.shortcuts import render
from django.utils import timezone

from api.models import IntegrationStatus
from github.models import GitEvent, GitHubInstallation
from github.services import app_capabilities
from ops.access import ops_required
from orgs.models import Organization
from tasks.models import Notice

WATCH_STALE = timedelta(minutes=10)


def _caps(org) -> tuple[str, str]:
    """(conn-state 클래스, 문구). 캐시 1시간이라 첫 로드만 GitHub를 부른다."""
    caps = app_capabilities(org)
    if caps is None:
        return "warn", "확인 불가"
    off = sum(1 for c in caps.values() if not c["ok"])
    return ("warn", f"{off}개 기능 꺼짐") if off else ("on", "정상")


@ops_required
def integrations(request):
    now = timezone.now()
    installs = []
    if settings.GITHUB_ENABLED:
        for i in GitHubInstallation.objects.select_related("org").order_by("org__name"):
            state, label = _caps(i.org)
            installs.append({"i": i, "org_name": i.org.name, "state": state, "label": label})
    beat = IntegrationStatus.objects.filter(name="discord").first()
    guilds = list(
        Organization.objects.exclude(discord_guild_id=None).values(
            "name",
            "discord_guild_id",
            "discord_channel_id",
            "discord_watch_at",
            "discord_intent_denied",
            "discord_bot_permissions",
        )
    )
    for g in guilds:
        w = g["discord_watch_at"]
        g["watching"] = bool(w and now - w <= WATCH_STALE)
    notices = Notice.objects.aggregate(
        waiting=Count("id", filter=Q(sent_at__isnull=True)),
        oldest=Min("created_at", filter=Q(sent_at__isnull=True)),
        sent_24h=Count("id", filter=Q(sent_at__gte=now - timedelta(hours=24))),
        sent_7d=Count("id", filter=Q(sent_at__gte=now - timedelta(days=7))),
    )
    events = GitEvent.objects.aggregate(
        n24=Count("id", filter=Q(occurred_at__gte=now - timedelta(hours=24))),
        last=Max("occurred_at"),
    )
    return render(
        request,
        "ops/integrations.html",
        {
            "ops_nav": "integrations",
            "github_enabled": settings.GITHUB_ENABLED,
            "installs": installs,
            "beat": beat,
            "beat_stale": bool(beat is None or now - beat.last_run_at > WATCH_STALE),
            "guilds": guilds,
            "notices": notices,
            "events": events,
        },
    )
