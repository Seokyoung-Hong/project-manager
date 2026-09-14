from django.contrib import messages
from django.contrib.auth.decorators import login_required
from django.shortcuts import get_object_or_404, redirect, render
from django.views.decorators.http import require_POST

from accounts.models import ApiToken
from accounts.services import issue_link_code, set_user_settings, unlink_discord
from common.errors import ServiceError
from orgs import settings as S
from orgs.services import orgs_of

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
            "tokens": request.user.tokens.all(),
            "new_token": request.session.pop("new_token", None),
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
    """개인 설정(알림·표시). 본인만. 이력 없음."""
    from .orgs import _settings_form

    u = request.user
    errors = {}
    if request.method == "POST":
        try:
            set_user_settings(u, _settings_form(request.POST, "user"))
            messages.success(request, "설정을 저장했습니다.")
            return redirect("preferences")
        except ServiceError as e:
            errors = e.errors
    # 조직이 끈 마감 알림 종류는 고를 수 없다(교집합). 조직이 여럿이면 합집합을 보여 준다.
    org_kinds = set()
    for org in orgs_of(u):
        org_kinds |= set(S.effective("notify.deadline_kinds", org=org))
    items = [
        {
            "spec": spec,
            "value": u.settings.get(spec.key, spec.default),
            "is_default": spec.key not in u.settings,
        }
        for spec in S.specs("user")
    ]
    return render(
        request,
        "settings/preferences.html",
        {
            "items": items,
            "org_kinds": org_kinds,
            "errors": errors,
            "auto_pull_days": u.auto_pull_days,
        },
    )
