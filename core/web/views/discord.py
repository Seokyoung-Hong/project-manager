"""조직의 Discord 서버 연결 화면. IMPL-PLAN-4 §8.4.

GitHub 앱 설치와 같은 모양이다. 세션에 `state`를 두고 Discord로 보냈다가, 돌아온 `code`를
Discord에서 교환해 실제로 설치된 서버를 그 조직에 붙인다(쿼리의 `guild_id`는 믿지 않는다 —
고쳐 쓰면 남의 서버를 선점할 수 있다). `state` 대조가 CSRF 방어다 — Discord 쪽에서 곧바로 설치하면 이 값이 없어
연결이 기록되지 않는다(GitHub 설치와 같은 규칙이다).

채널은 여기서 고르지 않는다. 목록을 뽑으려면 봇 토큰이 필요한데 core는 그 토큰을 갖지 않는다.
길드 안에서 `/알림채널`을 실행하면 그 채널이 저장된다.
"""

import secrets
from urllib.parse import urlencode

from django.conf import settings
from django.contrib import messages
from django.contrib.auth.decorators import login_required
from django.http import Http404
from django.shortcuts import redirect, render
from django.views.decorators.http import require_POST

from common.errors import ServiceError
from orgs import channels
from orgs import discord as dc

from .common import not_admin, org_or_404

# VIEW_CHANNEL | SEND_MESSAGES | MANAGE_CHANNELS | MANAGE_ROLES. 봇이 사람의 권한을 넘겨받는 통로가 되면
# 안 되므로 이 넷만 받는다(IMPL-PLAN-3 §채널 명령). Manage Roles는 자동 관리(IMPL-PLAN-5 사용자 결정 3)용이다.
BOT_PERMISSIONS = str(channels.REQUIRED_PERMISSIONS)
AUTHORIZE = "https://discord.com/oauth2/authorize"


def _redirect_uri() -> str:
    return f"{settings.SITE_URL}/orgs/discord/installed"


def _enabled_or_404():
    if not settings.DISCORD_CLIENT_ID:
        raise Http404


@login_required
def org_discord(request, org_id):
    _enabled_or_404()
    org = org_or_404(request.user, org_id)
    if denied := not_admin(request, org, "Discord 연동"):
        return denied
    return render(
        request,
        "orgs/discord.html",
        {
            "org": org,
            "is_admin": True,
            "tab": "discord",
            "rows": channels.overview(org),
            "watching": channels.watching(org),
            "intent_denied": org.discord_intent_denied,
            "reauthorize": channels.needs_reauthorization(org),
        },
    )


@login_required
@require_POST
def discord_alert(request, org_id, alert_id, action):
    """경고 [허용]·허용 [철회]. 철회하면 행이 지워지고 다음 감시에서 아직 보이면 다시 경고가 된다."""
    _enabled_or_404()
    org = org_or_404(request.user, org_id)
    if denied := not_admin(request, org, "Discord 연동"):
        return denied
    if action not in ("allow", "revoke"):
        raise Http404
    try:
        channels.resolve(org, alert_id, action, request.user)
    except ServiceError as e:
        messages.error(request, " ".join(e.errors.values()))
    return redirect("org_discord", org_id=org.pk)


@login_required
@require_POST
def discord_managed(request, org_id):
    """채널 자동 관리 토글. 켜면 봇이 허용 집합 멤버에게 채널 보기·쓰기 권한을 맞춘다."""
    _enabled_or_404()
    org = org_or_404(request.user, org_id)
    if denied := not_admin(request, org, "Discord 연동"):
        return denied
    kind = request.POST.get("kind")
    if kind not in ("team", "project") or not request.POST.get("id", "").isdecimal():
        raise Http404
    try:
        channels.set_managed(
            org, kind, int(request.POST["id"]), request.POST.get("managed") == "1", request.user
        )
    except ServiceError as e:
        messages.error(request, " ".join(e.errors.values()))
    return redirect("org_discord", org_id=org.pk)


@login_required
def discord_connect(request, org_id):
    _enabled_or_404()
    org = org_or_404(request.user, org_id)
    if denied := not_admin(request, org, "Discord 연동"):
        return denied
    state = secrets.token_urlsafe(16)
    request.session["dc_state"] = state
    request.session["dc_org"] = org.pk
    query = urlencode(
        {
            "client_id": settings.DISCORD_CLIENT_ID,
            "scope": "bot applications.commands",
            "permissions": BOT_PERMISSIONS,
            "response_type": "code",
            "redirect_uri": _redirect_uri(),
            "state": state,
        }
    )
    return redirect(f"{AUTHORIZE}?{query}")


@login_required
def discord_installed(request):
    """Discord가 되돌려 주는 곳. ?code=&guild_id=&permissions=&state= — 서버는 code 교환 결과로 정한다."""
    _enabled_or_404()
    expected = request.session.pop("dc_state", None)
    got = request.GET.get("state") or ""
    # 바이트로 비교한다. str끼리는 비ASCII가 섞이면 compare_digest가 TypeError(500)를 낸다.
    if not expected or not secrets.compare_digest(got.encode(), expected.encode()):
        raise Http404
    org_id = request.session.pop("dc_org", None)
    org = org_or_404(request.user, org_id)
    if denied := not_admin(request, org, "Discord 연동"):
        return denied
    try:
        guild_id = dc.guild_from_code(request.GET.get("code", ""), _redirect_uri())
        if request.GET.get("guild_id") and request.GET["guild_id"] != guild_id:
            raise ServiceError({"guild_id": "Discord가 알려 준 서버와 요청의 서버가 다릅니다."})
        dc.link_guild(org, guild_id, actor=request.user)
        messages.success(
            request, "Discord 서버를 연결했습니다. 알림 채널은 그 서버에서 /알림채널로 정해 주세요."
        )
    except ServiceError as e:
        messages.error(request, " ".join(e.errors.values()))
    return redirect("org_discord", org_id=org.pk)


@login_required
@require_POST
def discord_unlink(request, org_id):
    _enabled_or_404()
    org = org_or_404(request.user, org_id)
    if denied := not_admin(request, org, "Discord 연동"):
        return denied
    try:
        dc.unlink_guild(org, actor=request.user)
        messages.success(request, "Discord 서버 연결을 해제했습니다.")
    except ServiceError as e:
        messages.error(request, " ".join(e.errors.values()))
    return redirect("org_discord", org_id=org.pk)
