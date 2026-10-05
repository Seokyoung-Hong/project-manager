import re
from pathlib import Path

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
from orgs.settings import SPECS, display
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


def _orgs_json() -> str:
    """조직 설정의 비밀값(kind=secret)은 암호문 대신 '설정됨/미설정'만 내보낸다."""
    orgs = list(Organization.objects.all())
    for o in orgs:
        o.settings = {
            k: display(k, v) if k in SPECS and SPECS[k].kind == "secret" else v
            for k, v in (o.settings or {}).items()
        }
    return serializers.serialize("json", orgs)


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
        _orgs_json(),
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


CSS = Path(__file__).resolve().parent.parent / "static" / "app.css"
TOKEN = re.compile(r"(--[a-z0-9-]+):\s*([^;]+);")
DARK = "@media (prefers-color-scheme: dark)"


def css_tokens() -> tuple[dict, dict]:
    """app.css의 라이트(첫 :root)·다크(prefers-color-scheme 안 :root) 토큰. 견본이 코드와 늘 같다."""
    css = CSS.read_text(encoding="utf-8")
    light = dict(TOKEN.findall(css.split(DARK)[0]))
    dark = dict(TOKEN.findall(css.split(DARK, 1)[1].split("\n}\n", 1)[0]))
    return light, dark


@staff_member_required
def design(request):
    """살아 있는 스타일 가이드: 토큰 견본과 실제 클래스로 그린 컴포넌트(DESIGN.md의 화면판)."""
    light, dark = css_tokens()

    def group(*prefixes):
        return [
            (k, v.strip(), dark.get(k, "").strip())
            for k, v in light.items()
            if k.startswith(prefixes)
        ]

    return render(
        request,
        "ops_design.html",
        {
            "settings_tab": "design",
            "colors": group("--c-", "--plant-"),
            "font_sizes": group("--fs-"),
            "spaces": group("--sp-"),
            "radii": group("--r-"),
            "shadows": group("--sh-", "--scrim"),
            "layers": group("--z-"),
            "motions": group("--dur-", "--ease"),
            "statuses": Task.STATUSES,
        },
    )
