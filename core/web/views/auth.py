from django.contrib import messages
from django.contrib.auth import login
from django.shortcuts import redirect, render
from django.utils.http import url_has_allowed_host_and_scheme

from common.errors import ServiceError
from orgs.services import invite_org, join_by_token

from ..forms import SignupForm


def root(request):
    return redirect("today" if request.user.is_authenticated else "login")


def signup(request):
    if request.user.is_authenticated:
        return redirect("today")
    form = SignupForm(request.POST or None)
    if request.method == "POST" and form.is_valid():
        user = form.save()
        login(request, user)
        messages.info(request, "가입되었습니다. 조직을 만들거나 초대 링크로 참여하세요.")
        # 갓 가입한 사람은 조직이 없다. 오늘 화면은 빈 목록뿐이라 다음에 뭘 해야 하는지 안 보인다.
        # 조직 목록은 [조직 만들기]가 있는 화면이다(초대로 온 사람은 next를 타고 그대로 간다).
        nxt = request.GET.get("next", "")
        if not url_has_allowed_host_and_scheme(nxt, allowed_hosts={request.get_host()}):
            nxt = ""  # 외부 주소로 보내는 피싱 링크(/signup?next=https://...)를 막는다
        return redirect(nxt or "org_list")
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
