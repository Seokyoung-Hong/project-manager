from django.conf import settings
from django.contrib import messages
from django.contrib.auth.decorators import login_required
from django.shortcuts import get_object_or_404, redirect, render
from django.views.decorators.http import require_POST

from accounts.models import ApiToken
from accounts.services import issue_link_code, set_user_settings, unlink_discord
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
    request.session["discord_link_code"] = issue_link_code(request.user)
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
            _, raw = ApiToken.issue(request.user, d["name"], d["scope"])
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
