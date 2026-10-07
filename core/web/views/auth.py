from django.contrib import messages
from django.contrib.auth.forms import SetPasswordForm
from django.contrib.auth.tokens import default_token_generator
from django.shortcuts import redirect, render
from django.utils.http import url_has_allowed_host_and_scheme, urlsafe_base64_decode
from django.views.decorators.http import require_POST

from accounts.auth import (
    LockedOut,
    authenticate_password,
    check_lock,
    client_ip,
    login_user,
    logout_user,
    record_failure,
    record_success,
)
from accounts.models import User
from common.errors import ServiceError
from orgs.services import invite_org, join_by_token

from ..forms import LoginForm, SignupForm


def _too_many(e: LockedOut) -> str:
    return f"로그인 시도가 너무 많습니다. {e.retry_after_minutes}분 뒤 다시 시도해 주세요."


def _safe_next(request, nxt: str) -> str:
    # 외부 주소로 보내는 피싱 링크(/login?next=https://...)를 막는다
    ok = url_has_allowed_host_and_scheme(nxt, allowed_hosts={request.get_host()})
    return nxt if ok else ""


def root(request):
    return redirect("today" if request.user.is_authenticated else "login")


def login_view(request):
    if request.user.is_authenticated:
        return redirect(_safe_next(request, request.GET.get("next", "")) or "today")
    form = LoginForm(request.POST or None)
    if request.method == "POST" and form.is_valid():
        try:
            user = authenticate_password(
                request, form.cleaned_data["username"], form.cleaned_data["password"]
            )
        except LockedOut as e:
            form.add_error(None, _too_many(e))
        else:
            if user is None:
                form.add_error(None, "아이디 또는 비밀번호가 맞지 않습니다.")
            else:
                login_user(request, user, "password")
                start = "me" if user.settings.get("user.start_page") == "me" else "today"
                return redirect(_safe_next(request, request.POST.get("next", "")) or start)
    return render(request, "auth/login.html", {"form": form})


@require_POST
def logout_view(request):
    logout_user(request)
    return redirect("login")


def signup(request):
    if request.user.is_authenticated:
        return redirect("today")
    form = SignupForm(request.POST or None)
    if request.method == "POST" and form.is_valid():
        ip = client_ip(request)
        try:
            check_lock("signup_ip", ip)
        except LockedOut as e:
            form.add_error(None, _too_many(e))
            return render(request, "auth/signup.html", {"form": form})
        user = form.save()
        record_failure("signup_ip", ip)  # 실패가 아니라 생성 횟수를 센다
        login_user(request, user, "password")
        messages.info(request, "가입되었습니다. 조직을 만들거나 초대 링크로 참여하세요.")
        # 갓 가입한 사람은 조직이 없다. 오늘 화면은 빈 목록뿐이라 다음에 뭘 해야 하는지 안 보인다.
        # 조직 목록은 [조직 만들기]가 있는 화면이다(초대로 온 사람은 next를 타고 그대로 간다).
        return redirect(_safe_next(request, request.GET.get("next", "")) or "org_list")
    return render(request, "auth/signup.html", {"form": form})


def join(request, token):
    if not request.user.is_authenticated:
        # 초대받은 사람은 대개 계정이 없다. 맨몸 로그인 화면으로 보내면 무슨 링크였는지 잃는다.
        return render(request, "auth/join.html", {"token": token, "org": invite_org(token)})
    if request.method == "POST":
        try:
            org = join_by_token(request.user, token)
        except ServiceError as e:
            return render(request, "auth/join.html", {"error": e.errors["token"]})
        request.session["org_id"] = org.pk
        messages.success(request, f"{org.name} 조직에 참여했습니다.")
        return redirect("today")
    return render(request, "auth/join.html", {"token": token})


RESET_TOKEN_SESSION_KEY = "_password_reset_token"
RESET_INTERNAL_TOKEN = "set-password"


def password_reset_confirm(request, uidb64, token):
    """운영자가 발급한 비밀번호 재설정 링크(24시간·1회용). 성공해도 자동 로그인하지 않는다.

    Django 기본 뷰처럼 링크의 토큰을 세션으로 옮기고 토큰 없는 주소로 다시 보낸다 — 폼 화면의
    주소·Referer·이후 요청 로그에 토큰이 남지 않게 한다.
    """
    if request.user.is_authenticated:
        return render(request, "auth/reset.html", {"logged_in": True})
    if token != RESET_INTERNAL_TOKEN:
        request.session[RESET_TOKEN_SESSION_KEY] = token
        return redirect("password_reset_confirm", uidb64, RESET_INTERNAL_TOKEN)
    try:
        user = User.objects.get(pk=urlsafe_base64_decode(uidb64).decode(), is_active=True)
    except (ValueError, TypeError, OverflowError, User.DoesNotExist):
        user = None
    token = request.session.get(RESET_TOKEN_SESSION_KEY, "")
    if user is None or not default_token_generator.check_token(user, token):
        return render(request, "auth/reset.html", {"invalid": True})
    form = SetPasswordForm(user, request.POST or None)
    if request.method == "POST" and form.is_valid():
        form.save()  # 비밀번호 해시가 바뀌므로 같은 링크는 다시 쓸 수 없다
        request.session.pop(RESET_TOKEN_SESSION_KEY, None)
        record_success("user", user.username.lower())  # 로그인 잠금도 푼다
        messages.success(request, "비밀번호를 바꿨습니다. 새 비밀번호로 로그인해 주세요.")
        return redirect("login")
    return render(request, "auth/reset.html", {"form": form})
