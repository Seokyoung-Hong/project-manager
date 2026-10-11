from urllib.parse import urlencode

from django.conf import settings
from django.contrib import messages
from django.contrib.auth import logout
from django.contrib.auth.decorators import login_required
from django.http import Http404
from django.shortcuts import get_object_or_404, redirect, render
from django.urls import reverse
from django.utils.http import url_has_allowed_host_and_scheme
from django.views.decorators.http import require_POST

from accounts.consents import NOTICES, TARGETS
from accounts.models import ApiToken
from accounts.services import (
    give_consent,
    has_consent,
    issue_link_code,
    missing_consents,
    set_user_settings,
    unlink_discord,
    withdraw,
    withdraw_consent,
)
from common.errors import ServiceError
from orgs.settings import effective, specs_for

from ..forms import ProfileForm, TokenForm


@login_required
def profile(request):
    u = request.user
    form = ProfileForm(request.POST or None, initial={"display_name": u.display_name})
    if request.method == "POST" and form.is_valid():
        u.display_name = form.cleaned_data["display_name"]
        u.save(update_fields=["display_name"])
        messages.success(request, "프로필을 저장했습니다.")
        return redirect("profile")
    return render(
        request,
        "settings/profile.html",
        # 연결 코드는 발급 직후 한 번만 보여준다(토큰 화면의 new_token과 같은 방식).
        {"form": form, "link_code": request.session.pop("discord_link_code", None)},
    )


@login_required
@require_POST
def discord_link(request):
    """연결 코드 발급. 실제 연결은 Discord에서 봇에게 DM으로 코드를 보낼 때 이뤄진다."""
    try:
        request.session["discord_link_code"] = issue_link_code(request.user)
    except ServiceError:
        return consent_redirect("discord", reverse("profile"))
    return redirect("profile")


@login_required
@require_POST
def discord_unlink(request):
    unlink_discord(request.user)
    messages.success(request, "Discord 연결을 끊었습니다. 마감 알림 DM도 멈춥니다.")
    return redirect("profile")


@login_required
def tokens(request):
    if request.method == "POST":
        form = TokenForm(request.POST)
        if form.is_valid():
            d = form.cleaned_data
            if d["purpose"] == "ai" and not has_consent(request.user, "ai"):
                return consent_redirect("ai", reverse("tokens"))
            _, raw = ApiToken.issue(
                request.user, d["name"], d["scope"], for_ai=d["purpose"] == "ai"
            )
            request.session["new_token"] = raw
            return redirect("tokens")
    else:
        form = TokenForm()
    return render(
        request,
        "settings/tokens.html",
        {
            "form": form,
            # 폐기된 토큰이 활성 토큰과 섞이면 살아 있는 것을 세기 어렵다
            "tokens": request.user.tokens.filter(revoked_at__isnull=True),
            "revoked_tokens": request.user.tokens.filter(revoked_at__isnull=False),
            "new_token": request.session.pop("new_token", None),
            "mcp_url": settings.MCP_URL,
        },
    )


@login_required
@require_POST
def token_revoke(request, token_id):
    token = get_object_or_404(ApiToken, pk=token_id, user=request.user)
    token.revoke()
    return redirect("tokens")


@login_required
def preferences(request):
    """개인 설정. IMPL-PLAN-4 §7."""
    user = request.user
    specs = specs_for("user")
    if request.method == "POST":
        data = {}
        for spec in specs:
            if spec.kind == "bool":
                data[spec.key] = spec.key in request.POST
            elif spec.kind == "set":
                data[spec.key] = request.POST.getlist(spec.key)
            elif spec.key in request.POST:
                data[spec.key] = request.POST[spec.key]
        try:
            set_user_settings(user, data)
            messages.success(request, "환경설정을 저장했습니다.")
        except ServiceError as e:
            messages.error(request, " ".join(e.errors.values()))
        return redirect("preferences")
    rows = [
        {
            "spec": s,
            "value": effective(s.key, user=user),
            "can_edit": True,
            "show_override": False,
        }
        for s in specs
    ]
    groups = [
        ("알림", [row for row in rows if row["spec"].key.startswith("user.notify_")]),
        ("화면 기본값", [row for row in rows if not row["spec"].key.startswith("user.notify_")]),
    ]
    return render(request, "settings/preferences.html", {"rows": rows, "groups": groups})


@login_required
def account(request):
    """개인 설정 > 계정 > 회원 탈퇴(개인정보 처리 결정 A)."""
    error = None
    if request.method == "POST":
        try:
            withdraw(request.user, request.POST.get("confirm", ""))
        except ServiceError as e:
            error = " ".join(e.errors.values())
        else:
            logout(request)
            return render(request, "settings/withdrawn.html")
    return render(request, "settings/account.html", {"error": error})


# ---------- 국외 이전 동의 ----------


def consent_redirect(target: str, nxt: str):
    """동의가 없으면 동의 화면으로 보낸다. 동의하면 nxt로 돌아온다."""
    return redirect(f"{reverse('consent', args=[target])}?{urlencode({'next': nxt})}")


@login_required
def consent(request, target):
    if target not in NOTICES:
        raise Http404
    nxt = request.POST.get("next") or request.GET.get("next", "")
    if not url_has_allowed_host_and_scheme(nxt, allowed_hosts={request.get_host()}):
        nxt = ""
    if request.method == "POST":
        give_consent(request.user, target)
        return redirect(nxt or "consents")
    return render(
        request,
        "settings/consent.html",
        {"target": target, "label": dict(TARGETS)[target], "notice": NOTICES[target], "next": nxt},
    )


@login_required
def consents(request):
    active = {c.target: c for c in request.user.consents.filter(withdrawn_at__isnull=True)}
    missing = missing_consents(request.user)
    rows = [
        {"target": t, "label": label, "consent": active.get(t), "missing": t in missing}
        for t, label in TARGETS
    ]
    return render(request, "settings/consents.html", {"rows": rows})


@login_required
@require_POST
def consent_withdraw(request, target):
    try:
        if withdraw_consent(request.user, target):
            messages.success(request, "동의를 철회하고 연결을 끊었습니다.")
    except ServiceError as e:
        messages.error(request, " ".join(e.errors.values()))
    return redirect("consents")
