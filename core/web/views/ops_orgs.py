"""운영 콘솔 조직 목록(IMPL-PLAN-10 §6.4). 집계만 — 업무 내용은 꺼내지 않는다."""

from datetime import timedelta

from django.db.models import Count, Max, Q
from django.shortcuts import render
from django.utils import timezone

from ops.access import ops_required
from orgs.models import Organization, OrgMembership
from tasks.models import Attachment, Task

INACTIVE = timedelta(days=90)
WATCH_STALE = timedelta(minutes=10)


@ops_required
def orgs(request):
    now = timezone.now()
    rows = Organization.objects.annotate(
        member_n=Count("memberships", distinct=True),
        projects_n=Count("projects", distinct=True),
        open_n=Count(
            "projects__tasks", filter=Q(projects__tasks__status__in=Task.OPEN), distinct=True
        ),
        done_n=Count("projects__tasks", filter=Q(projects__tasks__status="done"), distinct=True),
        active_at=Max("projects__tasks__updated_at"),
    ).values(
        "id",
        "name",
        "created_at",
        "member_n",
        "projects_n",
        "open_n",
        "done_n",
        "active_at",
        "discord_guild_id",
        "discord_watch_at",
        "discord_intent_denied",
        "github__id",
    )
    size: dict[int, int] = {}
    for pk, tk, n in Attachment.objects.values_list(
        "project__org_id", "task__project__org_id", "size"
    ):
        size[pk or tk] = size.get(pk or tk, 0) + n
    admins: dict[int, list[str]] = {}
    for oid, name in OrgMembership.objects.filter(role="admin").values_list(
        "org_id", "user__display_name"
    ):
        admins.setdefault(oid, []).append(name)
    out = []
    for o in rows:
        watch = o["discord_watch_at"]
        if not o["discord_guild_id"]:
            discord = "off"
        elif o["discord_intent_denied"]:
            discord = "bad"
        else:
            discord = "on" if watch and now - watch <= WATCH_STALE else "warn"
        out.append(
            {
                **o,
                "admins": ", ".join(admins.get(o["id"], [])),
                "bytes": size.get(o["id"], 0),
                "inactive": not o["active_at"] or now - o["active_at"] > INACTIVE,
                "discord": discord,
                "github": o["github__id"] is not None,
            }
        )
    return render(request, "ops/orgs.html", {"ops_nav": "orgs", "orgs": out})
