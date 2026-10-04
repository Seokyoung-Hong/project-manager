from django.contrib import messages
from django.contrib.admin.views.decorators import staff_member_required
from django.core import serializers
from django.db import connection
from django.http import HttpResponse, JsonResponse
from django.shortcuts import redirect, render
from django.views.decorators.http import require_POST

from accounts.auth import active_locks, unlock
from accounts.models import User
from api.models import IntegrationStatus
from orgs.models import Invite, Organization, OrgMembership, Team, TeamMembership
from projects.models import Project
from tasks.models import ChangeLog, ChecklistItem, Link, Task, TodayItem


def healthz(request):
    with connection.cursor() as c:
        c.execute("SELECT 1")
    return JsonResponse({"ok": True})


@staff_member_required
def ops(request):
    return render(
        request,
        "ops.html",
        {"statuses": IntegrationStatus.objects.order_by("name"), "locks": active_locks()},
    )


@staff_member_required
@require_POST
def unlock_login(request):
    n = unlock(request.POST.get("key", ""))
    messages.success(request, f"잠금을 풀었습니다({n}건).")
    return redirect("ops")


@staff_member_required
def export_json(request):
    parts = [
        serializers.serialize(
            "json",
            User.objects.all(),
            # discord_link_code는 살아 있는 동안 자격증명이므로 넣지 않는다.
            fields=(
                "username",
                "display_name",
                "discord_user_id",
                "discord_linked_at",
                "is_active",
                "auto_pull_days",
            ),
        ),
        serializers.serialize("json", Organization.objects.all()),
        serializers.serialize("json", OrgMembership.objects.all()),
        serializers.serialize(
            "json",
            Invite.objects.all(),
            fields=("org", "expires_at", "revoked_at", "use_count"),
        ),
        serializers.serialize("json", Team.objects.all()),
        serializers.serialize("json", TeamMembership.objects.all()),
        serializers.serialize("json", Project.objects.all()),
        serializers.serialize("json", Task.objects.all()),
        serializers.serialize("json", ChecklistItem.objects.all()),
        serializers.serialize("json", TodayItem.objects.all()),
        serializers.serialize("json", Link.objects.all()),
        serializers.serialize("json", ChangeLog.objects.all()),
    ]
    body = "[" + ",".join(p[1:-1] for p in parts if len(p) > 2) + "]"
    resp = HttpResponse(body, content_type="application/json")
    resp["Content-Disposition"] = 'attachment; filename="export.json"'
    return resp
