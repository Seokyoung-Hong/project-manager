"""운영 콘솔 `/ops`: 개요·시스템·디자인 시스템·운영 데이터 내보내기·잠금 해제, 그리고 healthz.

서비스 운영자 전용(아니면 404). 변경은 ops.services를 거쳐 사유와 함께 감사 기록에 남는다.
"""

import re
import shutil
from datetime import timedelta
from pathlib import Path

from django.conf import settings
from django.contrib import messages
from django.core import serializers
from django.db import connection
from django.db.migrations.executor import MigrationExecutor
from django.db.migrations.recorder import MigrationRecorder
from django.db.models import Count, Min, Sum
from django.http import HttpResponse, JsonResponse
from django.shortcuts import redirect, render
from django.urls import reverse
from django.utils import timezone
from django.utils.dateparse import parse_datetime

from accounts.auth import active_locks
from accounts.models import User
from api.models import IntegrationStatus
from common.errors import ServiceError
from notes.models import VoiceRecording
from ops import services as ops_services
from ops.access import ops_required, superuser_required
from ops.models import OpsAuditLog
from orgs.models import Invite, Organization, OrgMembership, Team, TeamMembership
from orgs.settings import SPECS, display
from projects.models import Project
from tasks.models import Attachment, ChangeLog, ChecklistItem, Link, Notice, Task, TodayItem

from .common import dialog


def healthz(request):
    with connection.cursor() as c:
        c.execute("SELECT 1")
    return JsonResponse({"ok": True})


def _fail(request, exc: ServiceError, to: str):
    for msg in exc.errors.values():
        messages.error(request, msg)
    return redirect(to)


BACKUP_STALE = timedelta(hours=26)
STUCK_REC = timedelta(hours=6)
HEARTBEAT_STALE = timedelta(minutes=10)


def _backup() -> dict:
    """백업·복구 시험 상태. `backup` 행은 O4의 record_backup이 쓰고, 여기서는 읽기만 한다."""
    row = IntegrationStatus.objects.filter(name="backup").first()
    restore = IntegrationStatus.objects.filter(name="restore-test").first()
    last_ok = parse_datetime(((row and row.detail) or {}).get("last_ok_at") or "")
    age = timezone.now() - last_ok if last_ok else None
    return {
        "row": row,
        "restore": restore,
        "last_ok": last_ok,
        "age_hours": int(age.total_seconds() // 3600) if age else None,
        "stale": age is None or age > BACKUP_STALE,
        "failed": bool(row and not row.ok),
    }


def _pending_migrations() -> int:
    ex = MigrationExecutor(connection)
    return len(ex.migration_plan(ex.loader.graph.leaf_nodes()))


def _stuck_recordings() -> int:
    return VoiceRecording.objects.filter(
        status__in=("recording", "transcribing"), started_at__lt=timezone.now() - STUCK_REC
    ).count()


@ops_required
def ops(request):
    """개요: 주의 타일 6개 + 최근 감사 기록."""
    now = timezone.now()
    backup = _backup()
    waiting = Notice.objects.filter(sent_at__isnull=True)
    oldest = waiting.aggregate(m=Min("created_at"))["m"]
    pending = _pending_migrations()
    failed = IntegrationStatus.objects.filter(ok=False).count()
    stuck = _stuck_recordings()
    tiles = [
        ("실패한 통합", failed, failed > 0),
        (
            "마지막 백업 성공 후 경과",
            "기록 없음" if backup["age_hours"] is None else f"{backup['age_hours']}시간",
            backup["stale"],
        ),
        ("잠긴 아이디·IP", len(active_locks()), False),
        (
            "대기 알림",
            waiting.count(),
            bool(oldest and now - oldest > timedelta(hours=1)),
        ),
        ("멈춘 녹음", stuck, stuck > 0),
        ("미적용 마이그레이션", pending, pending > 0),
    ]
    return render(
        request,
        "ops/home.html",
        {
            "ops_nav": "home",
            "tiles": [{"label": a, "value": b, "danger": c} for a, b, c in tiles],
            "audits": OpsAuditLog.objects.all()[:10],
            "superusers_without_staff": User.objects.filter(
                is_superuser=True, is_staff=False, is_active=True
            ).count(),
        },
    )


@ops_required
def system(request):
    """시스템 카드: 서비스 상태·백업·저장소·DB·녹음·Django 관리 화면. 모두 집계."""
    now = timezone.now()
    att = Attachment.objects.all()
    disk = None
    try:
        du = shutil.disk_usage(settings.MEDIA_ROOT)
        disk = {"total": du.total, "used": du.used, "free": du.free}
    except OSError:
        pass
    by_org: dict[int, int] = {}
    for pk, tk, size in att.values_list("project__org_id", "task__project__org_id", "size"):
        by_org[pk or tk] = by_org.get(pk or tk, 0) + size
    names = dict(Organization.objects.filter(pk__in=by_org).values_list("pk", "name"))
    top_orgs = [(names.get(k, "?"), v) for k, v in sorted(by_org.items(), key=lambda x: -x[1])[:5]]
    rec_counts = dict(
        VoiceRecording.objects.values_list("status").annotate(n=Count("id")).order_by()
    )
    applied: dict[str, str] = {}
    for app, name in sorted(MigrationRecorder(connection).applied_migrations()):
        applied[app] = name
    statuses = list(IntegrationStatus.objects.order_by("name"))
    return render(
        request,
        "ops/system.html",
        {
            "ops_nav": "system",
            "statuses": statuses,
            "mcp_missing": not any(s.name == "mcp" for s in statuses),
            "locks": active_locks(),
            "backup": _backup(),
            "disk": disk,
            "att_count": att.count(),
            "att_size": att.aggregate(s=Sum("size"))["s"] or 0,
            "top_orgs": top_orgs,
            "db_vendor": connection.vendor,
            "pending_migrations": _pending_migrations(),
            "applied": sorted(applied.items()),
            "rec_statuses": [(label, rec_counts.get(k, 0)) for k, label in VoiceRecording.STATUSES],
            "rec_stuck": _stuck_recordings(),
            "rec_failed_7d": VoiceRecording.objects.filter(
                status="failed", started_at__gte=now - timedelta(days=7)
            ).count(),
            "admin_enabled": settings.DJANGO_ADMIN_ENABLED,
            "admin_access": OpsAuditLog.objects.filter(action="admin.access")[:5],
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
