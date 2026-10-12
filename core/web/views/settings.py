import secrets
import time
from types import SimpleNamespace
from urllib.parse import urlencode

from django.conf import settings
from django.contrib import messages
from django.contrib.auth import logout
from django.contrib.auth.decorators import login_required
from django.db import IntegrityError, transaction
from django.http import Http404
from django.shortcuts import get_object_or_404, redirect, render
from django.urls import reverse
from django.utils.http import url_has_allowed_host_and_scheme
from django.views.decorators.http import require_POST

from accounts.consents import NOTICES, TARGETS
from accounts.models import ApiToken, IdempotencyKey, User
from accounts.services import (
    give_consent,
    has_consent,
    issue_link_code,
    last_admin_orgs,
    missing_consents,
    set_user_settings,
    unlink_discord,
    withdraw,
    withdraw_consent,
)
from common.errors import ServiceError
from orgs.settings import effective, specs_for
from tasks.services import today_set_auto_pull

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
        return _consent_then(request, "discord", reverse("profile"))
    return redirect("profile")


@login_required
@require_POST
def discord_unlink(request):
    unlink_discord(request.user)
    messages.success(request, "Discord 연결을 끊었습니다. 기한 알림 DM도 멈춥니다.")
    return redirect("profile")


@login_required
def tokens(request):
    if request.method == "POST":
        form = TokenForm(request.POST)
        if form.is_valid():
            d = form.cleaned_data
            if d["purpose"] == "ai" and not has_consent(request.user, "ai"):
                # 동의하고 돌아오면 이름·범위를 다시 입력하지 않게 맡겨 두었다가 곧바로 발급한다
                return _consent_then(
                    request, "ai", reverse("tokens"), name=d["name"], scope=d["scope"]
                )
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
            # 전사 서버 토큰은 내 PC 연결 화면에서 관리한다
            "tokens": request.user.tokens.filter(revoked_at__isnull=True).exclude(scope="stt"),
            "revoked_tokens": request.user.tokens.filter(revoked_at__isnull=False).exclude(
                scope="stt"
            ),
            "new_token": request.session.pop("new_token", None),
            "mcp_url": settings.MCP_URL,
            # 스킬 설치 명령. 설치 스크립트와 같은 정식 주소
            "site_url": settings.SITE_URL,
        },
    )


@login_required
@require_POST
def token_revoke(request, token_id):
    token = get_object_or_404(ApiToken, pk=token_id, user=request.user)
    token.revoke()
    messages.success(request, f"'{token.name}' 토큰을 폐기했습니다.")
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
            if "auto_pull_days" in request.POST:
                days = request.POST["auto_pull_days"]
                today_set_auto_pull(user, int(days) if days.isdigit() else -1)
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
    # 오늘 목록 자동 담기는 User 필드라 설정 명세 밖에 있다. 같은 줄 모양으로 그린다(b-workspace 중-5).
    auto_pull = {
        "spec": SimpleNamespace(
            key="auto_pull_days",
            kind="int",
            label="오늘 목록 자동 담기",
            help="기한까지 남은 날이 이 기간 이내인 내 태스크를 오늘 목록에 자동으로 추가합니다.",
            input_choices=[
                (n, f"기한 {n}일 이내" if n else "쓰지 않음") for n, _ in User.AUTO_PULL_CHOICES
            ],
        ),
        "value": user.auto_pull_days,
        "can_edit": True,
        "show_override": False,
    }
    groups = [
        ("알림", [row for row in rows if row["spec"].key.startswith("user.notify_")]),
        (
            "화면 기본값",
            [auto_pull] + [row for row in rows if not row["spec"].key.startswith("user.notify_")],
        ),
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
    # 마지막 관리자인 조직이 있으면 입력받기 전에 알린다(탈퇴 시 서비스에서도 다시 막는다)
    blocked = last_admin_orgs(request.user)
    return render(request, "settings/account.html", {"error": error, "blocked": blocked})


# ---------- 국외 이전 동의 ----------


RESUME_KEY = "consent_resume"
RESUME_TTL = 30 * 60  # 동의 화면에서 이보다 오래 머물면 하던 일은 다시 시작한다


def consent_redirect(target: str, nxt: str):
    """동의가 없으면 동의 화면으로 보낸다. 동의하면 nxt로 돌아온다."""
    return redirect(f"{reverse('consent', args=[target])}?{urlencode({'next': nxt})}")


def _consent_then(request, target: str, nxt: str, **resume):
    """consent_redirect와 같되, 동의한 직후 하던 일(Discord 연결 코드, AI 토큰 발급)을 마저 한다 — _resume."""
    request.session[RESUME_KEY] = {
        "id": secrets.token_hex(16),
        "at": int(time.time()),
        "target": target,
        "next": nxt,
        **resume,
    }
    return consent_redirect(target, nxt)


def _resume(request, target: str, nxt: str) -> None:
    """동의 화면으로 오기 전 하던 일을 끝낸다. 같은 대상·같은 돌아갈 곳일 때만(다른 길로 온 동의는 그냥 동의만).

    같은 세션으로 POST가 동시에 두 번 와도 재개는 한 번만: 재개 id를 IdempotencyKey(user, key 유일)로
    DB에서 먼저 차지한 요청만 발급한다. 진 요청은 세션을 건드리지 않아 이긴 요청이 담은 토큰을 덮지 않는다.
    """
    pending = request.session.get(RESUME_KEY)
    if not pending:
        return
    if (
        pending.get("target") != target
        or pending.get("next") != nxt
        or "id" not in pending
        or time.time() - pending.get("at", 0) > RESUME_TTL
    ):
        request.session.pop(RESUME_KEY, None)
        return
    try:
        with transaction.atomic():
            mark = IdempotencyKey.objects.create(
                user=request.user,
                key=f"consent:{pending['id']}",
                target_type="consent",
                target_id=0,
            )
            if target == "discord":
                result = ("discord_link_code", issue_link_code(request.user))
            elif target == "ai":
                token, raw = ApiToken.issue(
                    request.user, pending["name"], pending["scope"], for_ai=True
                )
                IdempotencyKey.objects.filter(pk=mark.pk).update(target_id=token.pk)
                result = ("new_token", raw)
            else:
                result = None
    except IntegrityError:
        return
    request.session.pop(RESUME_KEY, None)
    if result:
        request.session[result[0]] = result[1]


@login_required
def consent(request, target):
    if target not in NOTICES:
        raise Http404
    nxt = request.POST.get("next") or request.GET.get("next", "")
    if not url_has_allowed_host_and_scheme(nxt, allowed_hosts={request.get_host()}):
        nxt = ""
    if request.method == "POST":
        give_consent(request.user, target)
        _resume(request, target, nxt)
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
    ai_tokens = request.user.tokens.filter(for_ai=True, revoked_at__isnull=True).count()
    # 철회하면 무엇이 끊기는지 확인 창에 구체적으로 적는다(A3)
    confirm = {
        "github": "GitHub 계정 연결이 끊기고 GitHub 로그인과 저장소 연동을 쓸 수 없게 됩니다.",
        "discord": "Discord 개인 연결이 끊기고 DM 알림과 봇 명령이 멈춥니다.",
        "ai": f"AI용 토큰(Claude 커넥터 포함) {ai_tokens}개가 폐기됩니다. "
        "폐기한 토큰은 되살릴 수 없어, 다시 쓰려면 새로 발급해야 합니다.",
    }
    connect = {"github": reverse("profile"), "discord": reverse("profile"), "ai": reverse("tokens")}
    rows = [
        {
            "target": t,
            "label": label,
            "consent": active.get(t),
            "missing": t in missing,
            "confirm": confirm[t],
            "connect": connect[t],
        }
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
