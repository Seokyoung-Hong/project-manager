from django.contrib import messages
from django.contrib.auth import login
from django.contrib.auth.decorators import login_required
from django.shortcuts import redirect, render

from common.errors import ServiceError
from orgs.services import join_by_token

from ..forms import SignupForm


def root(request):
    if not request.user.is_authenticated:
        return redirect("login")
    from orgs import settings as S

    return redirect("me" if S.effective("user.start_page", user=request.user) == "me" else "today")


def signup(request):
    if request.user.is_authenticated:
        return redirect("today")
    form = SignupForm(request.POST or None)
    if request.method == "POST" and form.is_valid():
        user = form.save()
        login(request, user)
        messages.info(request, "가입되었습니다. 조직에 참여하려면 초대 링크가 필요합니다.")
        return redirect(request.GET.get("next") or "today")
    return render(request, "auth/signup.html", {"form": form})


@login_required
def join(request, token):
    if request.method == "POST":
        try:
            org = join_by_token(request.user, token)
        except ServiceError as e:
            return render(request, "auth/join.html", {"error": e.errors["token"]})
        request.session["org_id"] = org.pk
        messages.success(request, f"{org.name} 조직에 참여했습니다.")
        return redirect("today")
    return render(request, "auth/join.html", {"token": token})
