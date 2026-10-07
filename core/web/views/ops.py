"""운영 콘솔 `/ops`: 개요·시스템·디자인 시스템·운영 데이터 내보내기·잠금 해제, 그리고 healthz.

서비스 운영자 전용(아니면 404). 변경은 ops.services를 거쳐 사유와 함께 감사 기록에 남는다.
"""

import re
from pathlib import Path

from django.contrib import messages
from django.core import serializers
from django.db import connection
from django.http import HttpResponse, JsonResponse
from django.shortcuts import redirect, render
from django.urls import reverse

from accounts.auth import active_locks
from accounts.models import User
from api.models import IntegrationStatus
from common.errors import ServiceError
from ops import services as ops_services
from ops.access import ops_required, superuser_required
from ops.models import OpsAuditLog
from orgs.models import Invite, Organization, OrgMembership, Team, TeamMembership
from orgs.settings import SPECS, display
from projects.models import Project
from tasks.models import ChangeLog, ChecklistItem, Link, Task, TodayItem

from .common import dialog


def healthz(request):
    with connection.cursor() as c:
        c.execute("SELECT 1")
    return JsonResponse({"ok": True})


def _fail(request, exc: ServiceError, to: str):
    for msg in exc.errors.values():
        messages.error(request, msg)
    return redirect(to)


@ops_required
def ops(request):
    """개요. 주의 타일은 O2에서 더한다."""
    return render(
        request,
        "ops/home.html",
        {
            "ops_nav": "home",
            "audits": OpsAuditLog.objects.all()[:10],
            "superusers_without_staff": User.objects.filter(
                is_superuser=True, is_staff=False, is_active=True
            ).count(),
        },
    )


@ops_required
def system(request):
    return render(
        request,
        "ops/system.html",
        {
            "ops_nav": "system",
            "statuses": IntegrationStatus.objects.order_by("name"),
            "locks": active_locks(),
        },
    )


@ops_required
def unlock_login(request):
    """GET은 확인 대화상자, POST는 사유와 함께 잠금 해제."""
    key = request.POST.get("key") if request.method == "POST" else request.GET.get("key")
    key = (key or "").strip()
    if request.method != "POST":
        return dialog(
            request,
            "ops/_confirm.html",
            {
                "action_url": reverse("ops_unlock"),
                "hidden": {"key": key},
                "title": "로그인 잠금 해제",
                "summary": f"{key}의 잠금과 실패 기록을 지웁니다.",
                "button": "잠금 해제",
            },
        )
    try:
        n = ops_services.unlock_login(request, key, request.POST.get("reason"))
    except ServiceError as e:
        return _fail(request, e, "ops_system")
    messages.success(request, f"잠금을 풀었습니다({n}건).")
    return redirect("ops_system")


def _orgs_json() -> str:
    """조직 설정의 비밀값(kind=secret)은 암호문 대신 '설정됨/미설정'만 내보낸다."""
    orgs = list(Organization.objects.all())
    for o in orgs:
        o.settings = {
            k: display(k, v) if k in SPECS and SPECS[k].kind == "secret" else v
            for k, v in (o.settings or {}).items()
        }
    return serializers.serialize("json", orgs)


@superuser_required
def export_json(request):
    """운영 데이터 JSON 내보내기. 최고 운영자 + 사유 + "export" 재입력, 감사 기록(§11 Q2 추천안)."""
    if request.method != "POST":
        return dialog(
            request,
            "ops/_confirm.html",
            {
                "action_url": reverse("export_json"),
                "title": "운영 데이터 JSON 내보내기",
                "summary": "태스크·변경 이력의 내용까지 담긴 파일을 내려받습니다. 실행은 감사 기록에 남습니다.",
                "confirm_value": ops_services.EXPORT_CONFIRM,
                "button": "내보내기",
                "danger": True,
            },
        )
    try:
        ops_services.record_export(request, request.POST.get("reason"), request.POST.get("confirm"))
    except ServiceError as e:
        return _fail(request, e, "ops_system")
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


@ops_required
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
        "ops/design.html",
        {
            "ops_nav": "design",
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
