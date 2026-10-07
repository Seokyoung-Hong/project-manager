"""운영 콘솔 · 사용자 `/ops/users` (IMPL-PLAN-10 §6.2).

보이는 것은 집계와 식별자뿐이다(§5.3). 변경은 ops.services를 거쳐 사유와 함께 감사 기록에 남는다.
"""

from django.contrib import messages
from django.core.paginator import Paginator
from django.db.models import Count, Q
from django.http import Http404
from django.shortcuts import get_object_or_404, redirect, render
from django.urls import reverse

from accounts.models import ApiToken, LoginLock, User
from common.errors import ServiceError
from github.models import GitHubIdentity
from ops import services as ops_services
from ops.access import ops_required
from ops.models import OpsAuditLog
from orgs.models import OrgMembership

from .common import dialog

RESET_SESSION_KEY = "ops_reset_link"


def _unlock(request, user, reason, confirm):
    ops_services.unlock_login(request, user.username.lower(), reason)


# 동작 → (제목, 설명, 대상 재입력, 위험, 버튼, 최고 운영자 전용, 실행, 완료 문구)
ACTIONS = {
    "suspend": (
        "사용자 정지",
        "로그인·API·MCP가 다음 요청부터 막힙니다.",
        True,
        True,
        "정지",
        False,
        ops_services.suspend_user,
        "사용자를 정지했습니다.",
    ),
    "reactivate": (
        "사용자 재활성",
        "다시 로그인하고 토큰을 쓸 수 있게 됩니다.",
        False,
        False,
        "재활성",
        False,
        lambda request, user, reason, confirm: ops_services.reactivate_user(request, user, reason),
        "사용자를 재활성했습니다.",
    ),
    "reset-link": (
        "비밀번호 재설정 링크 발급",
        "24시간 동안 한 번 쓸 수 있는 링크를 만듭니다. 링크를 받는 사람이 계정을 갖게 되므로 본인 확인된 경로로만 전달해 주세요.",
        True,
        True,
        "링크 발급",
        False,
        ops_services.issue_reset_link,
        "비밀번호 재설정 링크를 발급했습니다.",
    ),
    "unlock": (
        "로그인 잠금 해제",
        "이 아이디의 잠금과 실패 기록을 지웁니다.",
        False,
        False,
        "잠금 해제",
        False,
        _unlock,
        "로그인 잠금을 풀었습니다.",
    ),
    "grant-staff": (
        "운영자 권한 부여",
        "운영 콘솔 전체를 보고 사용자 정지·토큰 폐기를 할 수 있게 됩니다.",
        True,
        True,
        "권한 부여",
        True,
        ops_services.grant_staff,
        "운영자 권한을 부여했습니다.",
    ),
    "revoke-staff": (
        "운영자 권한 회수",
        "운영 콘솔에 더 들어갈 수 없게 됩니다.",
        True,
        True,
        "권한 회수",
        True,
        ops_services.revoke_staff,
        "운영자 권한을 회수했습니다.",
    ),
}


def _annotated():
    return User.objects.annotate(
        org_count=Count("org_memberships", distinct=True),
        token_count=Count("tokens", filter=Q(tokens__revoked_at__isnull=True), distinct=True),
    )


@ops_required
def users(request):
    q = request.GET.get("q", "").strip()
    state = request.GET.get("state", "active")
    qs = _annotated().order_by("username")
    if q:
        qs = qs.filter(Q(username__icontains=q) | Q(display_name__icontains=q))
    if state == "suspended":
        qs = qs.filter(is_active=False)
    elif state == "staff":
        qs = qs.filter(Q(is_staff=True) | Q(is_superuser=True))
    else:
        state = "active"
        qs = qs.filter(is_active=True)
    page = Paginator(qs, 50).get_page(request.GET.get("page"))
    return render(
        request,
        "ops/users.html",
        {"ops_nav": "users", "page": page, "q": q, "state": state},
    )


@ops_required
def user_detail(request, user_id):
    user = get_object_or_404(_annotated(), pk=user_id)
    reset = request.session.get(RESET_SESSION_KEY)
    reset_link = ""
    if reset and reset.get("user") == user.pk:  # 한 번 보여 주고 지운다
        reset_link = request.session.pop(RESET_SESSION_KEY)["url"]
    key = user.username.lower()
    return render(
        request,
        "ops/user.html",
        {
            "ops_nav": "users",
            "target": user,
            "reset_link": reset_link,
            "github_login": GitHubIdentity.objects.filter(user=user)
            .values_list("login", flat=True)
            .first(),
            "orgs": OrgMembership.objects.filter(user=user)
            .order_by("org__name")
            .values("org__name", "role"),
            "tokens": ApiToken.objects.filter(user=user),
            "lock": LoginLock.objects.filter(kind="user", key=key).first(),
            "audits": OpsAuditLog.objects.filter(
                Q(target_type="user", target_id=user.pk) | Q(target_type="login", target_label=key)
            )[:20],
        },
    )


@ops_required
def user_action(request, user_id, action):
    """GET은 확인 대화상자, POST는 실행(같은 URL)."""
    if action not in ACTIONS:
        raise Http404
    title, summary, needs_confirm, danger, button, root_only, run, done = ACTIONS[action]
    if root_only and not request.user.is_superuser:
        raise Http404
    user = get_object_or_404(User, pk=user_id)
    if request.method != "POST":
        return dialog(
            request,
            "ops/_confirm.html",
            {
                "action_url": reverse("ops_user_action", args=[user.pk, action]),
                "title": f"{title} — {user.username}",
                "summary": summary,
                "confirm_value": user.username if needs_confirm else "",
                "danger": danger,
                "button": button,
            },
        )
    try:
        result = run(request, user, request.POST.get("reason"), request.POST.get("confirm"))
    except ServiceError as e:
        for msg in e.errors.values():
            messages.error(request, msg)
    else:
        if action == "reset-link":
            request.session[RESET_SESSION_KEY] = {"user": user.pk, "url": result}
        messages.success(request, done)
    return redirect("ops_user", user.pk)
