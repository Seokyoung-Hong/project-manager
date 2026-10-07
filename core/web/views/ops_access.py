"""운영 콘솔 · 접근 `/ops/access` (IMPL-PLAN-10 §6.3): API 토큰 현황, AI 사용, 로그인 잠금·실패.

토큰은 앞자리·범위·용도·시각만 보인다(사용자가 적은 이름·해시는 보이지 않는다, §5.3).
"""

from collections import Counter
from datetime import timedelta

from django.contrib import messages
from django.db.models import Count
from django.shortcuts import get_object_or_404, redirect, render
from django.urls import reverse
from django.utils import timezone

from accounts.models import ApiToken, LoginLock
from common.errors import ServiceError
from ops import services as ops_services
from ops.access import ops_required
from orgs.models import Organization
from projects.models import Project
from tasks.models import ChangeLog, Task

from .common import dialog


def _ai_by_org(since) -> list[tuple[str, int]]:
    """AI(MCP) 변경 건수를 조직별로 센다. ChangeLog에는 조직이 없어 대상에서 거꾸로 찾는다."""
    rows = list(
        ChangeLog.objects.filter(source="mcp", created_at__gte=since)
        .values("target_type", "target_id")
        .annotate(n=Count("id"))
    )
    ids = {"task": set(), "project": set(), "org": set()}
    for r in rows:
        ids[r["target_type"]].add(r["target_id"])
    org_of = {
        "task": dict(
            Task.objects.filter(pk__in=ids["task"]).values_list("pk", "project__org__name")
        ),
        "project": dict(
            Project.objects.filter(pk__in=ids["project"]).values_list("pk", "org__name")
        ),
        "org": dict(Organization.objects.filter(pk__in=ids["org"]).values_list("pk", "name")),
    }
    count = Counter()
    for r in rows:
        name = org_of[r["target_type"]].get(r["target_id"])
        if name:
            count[name] += r["n"]
    return count.most_common(5)


@ops_required
def access(request):
    now = timezone.now()
    # ponytail: 활성 토큰을 한 번에 읽어 파이썬에서 묶는다. 토큰이 수천 개가 되면 annotate로.
    tokens = list(
        ApiToken.objects.filter(revoked_at__isnull=True)
        .select_related("user")
        .order_by("user__username", "-created_at")
    )
    live = [t for t in tokens if not t.expires_at or t.expires_at > now]
    by_user: dict[str, list] = {}
    for t in live:
        by_user.setdefault(t.user.username, []).append(t)
    people = [
        {
            "username": name,
            "tokens": ts,
            "active": len(ts),
            "ai": sum(t.for_ai for t in ts),
            "bot": sum(t.scope == "bot" for t in ts),
            "last_used": max((t.last_used_at for t in ts if t.last_used_at), default=None),
        }
        for name, ts in by_user.items()
    ]
    mcp = ChangeLog.objects.filter(source="mcp")
    locks = list(LoginLock.objects.order_by("-updated_at"))
    for lock in locks:
        lock.locked = bool(lock.locked_until and lock.locked_until > now)
    return render(
        request,
        "ops/access.html",
        {
            "ops_nav": "access",
            "tiles": [
                ("활성", len(live)),
                ("AI용", sum(t.for_ai for t in live)),
                ("사람용", sum(not t.for_ai and t.scope != "bot" for t in live)),
                ("봇", sum(t.scope == "bot" for t in live)),
                (
                    "7일 내 사용",
                    sum(
                        bool(t.last_used_at and t.last_used_at >= now - timedelta(7)) for t in live
                    ),
                ),
                (
                    "만료 예정(7일)",
                    sum(bool(t.expires_at and t.expires_at <= now + timedelta(7)) for t in live),
                ),
            ],
            "people": people,
            "ai_7d": mcp.filter(created_at__gte=now - timedelta(7)).count(),
            "ai_30d": mcp.filter(created_at__gte=now - timedelta(30)).count(),
            "ai_orgs": _ai_by_org(now - timedelta(30)),
            "locks": [x for x in locks if x.locked or x.failures >= 3],
        },
    )


@ops_required
def token_revoke(request, token_id):
    """다른 사람의 토큰 폐기. GET은 확인 대화상자(앞자리 재입력), POST는 실행."""
    token = get_object_or_404(ApiToken.objects.select_related("user"), pk=token_id)
    label = ops_services.token_label(token)
    if request.method != "POST":
        return dialog(
            request,
            "ops/_confirm.html",
            {
                "action_url": reverse("ops_token_revoke", args=[token.pk]),
                "title": f"토큰 폐기 — {token.user.username}",
                "summary": "이 토큰으로 돌던 자동화가 곧바로 멈춥니다. 되돌릴 수 없습니다.",
                "confirm_value": label,
                "danger": True,
                "button": "폐기",
            },
        )
    try:
        ops_services.revoke_token(
            request, token, request.POST.get("reason"), request.POST.get("confirm")
        )
    except ServiceError as e:
        for msg in e.errors.values():
            messages.error(request, msg)
    else:
        messages.success(request, "토큰을 폐기했습니다.")
    return redirect("ops_access")
