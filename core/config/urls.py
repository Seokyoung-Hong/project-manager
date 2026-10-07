from functools import wraps

from django.conf import settings
from django.contrib import admin
from django.contrib.admin import AdminSite
from django.contrib.auth.views import redirect_to_login
from django.urls import include, path, reverse

from api.api import api
from ops.services import audit
from web.views.auth import logout_view

# 덮어쓰기는 클래스의 원래 메서드를 부른다 — 테스트가 이 모듈을 다시 읽어도(reload) 겹겹이 감싸지 않는다.


def admin_login(request, extra_context=None):
    """admin 로그인 폼은 쓰지 않는다 — 그 폼은 시도 제한(accounts.auth)을 거치지 않는다.

    로그인 안 한 사람은 /login?next=로 보낸다. 로그인한 사람의 GET만 원래 화면(최고 운영자면 이동,
    아니면 '권한 없음')에 맡긴다. POST는 다른 계정 비밀번호를 맞혀 보는 길이므로 받지 않는다.
    """
    if request.user.is_authenticated and request.method == "GET":
        return AdminSite.login(admin.site, request, extra_context)
    return redirect_to_login(request.GET.get("next") or reverse("admin:index"))


def admin_view(view, cacheable=False):
    """모든 admin 뷰(AdminSite·ModelAdmin.get_urls)가 지나는 자리에서 접근을 감사 기록에 남긴다.

    권한이 없으면 Django가 로그인 화면으로 보낸다 — 거부된 시도도 allowed=False로 남는다.
    세부 변경(add/change/delete)은 Django가 django_admin_log에 따로 남긴다.
    """
    inner = AdminSite.admin_view(admin.site, view, cacheable)

    @wraps(inner)
    def logged(request, *a, **kw):
        if request.user.is_authenticated and not request.path.endswith("/jsi18n/"):
            audit(
                request,
                "admin.access",
                target_type="admin",
                target_label=request.path[:200],
                detail={"method": request.method, "allowed": admin.site.has_permission(request)},
            )
        return inner(request, *a, **kw)

    return logged


admin.site.login = admin_login
admin.site.logout = lambda request, extra_context=None: logout_view(request)  # logout_user를 지난다
# 최고 운영자만. is_staff만 있는 서비스 운영자는 운영 콘솔(/ops)을 쓴다.
admin.site.has_permission = lambda request: request.user.is_active and request.user.is_superuser
# admin.site.urls가 import 시점에 admin_view를 부르므로 urlpatterns보다 먼저 바꾼다.
admin.site.admin_view = admin_view

urlpatterns = [
    path("api/", api.urls),
    path("", include("web.urls")),
]
if settings.DJANGO_ADMIN_ENABLED:  # 끄면 /admin 경로 자체가 없다(404)
    urlpatterns.insert(0, path("admin/", admin.site.urls))
