from django.contrib import admin
from django.contrib.auth.views import redirect_to_login
from django.urls import include, path, reverse

from api.api import api
from web.views.auth import logout_view

_admin_login = admin.site.login


def admin_login(request, extra_context=None):
    """admin 로그인 폼은 쓰지 않는다 — 그 폼은 시도 제한(accounts.auth)을 거치지 않는다.

    로그인 안 한 사람은 /login?next=로 보낸다. 로그인한 사람의 GET만 원래 화면(staff면 이동,
    아니면 '권한 없음')에 맡긴다. POST는 다른 계정 비밀번호를 맞혀 보는 길이므로 받지 않는다.
    """
    if request.user.is_authenticated and request.method == "GET":
        return _admin_login(request, extra_context)
    return redirect_to_login(request.GET.get("next") or reverse("admin:index"))


admin.site.login = admin_login
admin.site.logout = lambda request, extra_context=None: logout_view(request)  # logout_user를 지난다

urlpatterns = [
    path("admin/", admin.site.urls),
    path("api/", api.urls),
    path("", include("web.urls")),
]
