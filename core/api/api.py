from django.contrib.auth.decorators import login_required
from ninja import NinjaAPI
from ninja.throttling import AuthRateThrottle

from common.errors import ConflictError, ServiceError
from portfolio.api import router as portfolio_router

from .auth import BrowserSessionAuth, TokenAuth
from .routers import (
    decisions,
    discord,
    docs,
    github,
    integrations,
    me,
    orgs,
    pr_context,
    projects,
    reports,
    settings,
    tasks,
    today,
)
from .routers.docs import doc_out
from .serialize import project_out, task_out


class UserRateThrottle(AuthRateThrottle):
    """사용자별 처리량 제한.

    기본 AuthRateThrottle은 `str(request.auth)`를 키로 쓴다. User.__str__은
    display_name이고 이건 본인이 바꿀 수 있으며 유일하지도 않다. 남과 같은 이름으로
    바꿔 두면 그 사람 몫까지 같이 갉아먹는다. 바뀌지 않는 사용자 id로 센다.
    """

    def get_cache_key(self, request) -> str:
        pk = getattr(getattr(request, "auth", None), "pk", None)
        if pk is None:
            return super().get_cache_key(request)
        return self.cache_format % {"scope": self.scope, "ident": f"user-{pk}"}


api = NinjaAPI(
    title="Sandol PM API",
    version="1",
    auth=[BrowserSessionAuth(), TokenAuth()],
    throttle=[UserRateThrottle("60/m")],
    docs_decorator=login_required,
    urls_namespace="api",
)


@api.exception_handler(ServiceError)
def _service_error(request, exc):
    return api.create_response(request, {"detail": exc.errors}, status=400)


@api.exception_handler(ConflictError)
def _conflict(request, exc):
    latest = exc.latest
    if hasattr(latest, "assignee"):
        data = task_out(latest)
    elif hasattr(latest, "body_md"):
        # 프로젝트 문서. project_out을 태우면 없는 필드를 찾다 500이 난다.
        data = doc_out(latest, body=False)
    else:
        data = project_out(latest)
    return api.create_response(request, {"detail": "conflict", "latest": data}, status=409)


api.add_router("/", me.router)
api.add_router("/", settings.router)
api.add_router("/orgs", orgs.router)
api.add_router("/projects", projects.router)
# /api/docs는 Ninja의 Swagger UI가 이미 쓴다. 겹치면 문서 목록이 로그인 화면으로 넘어간다.
api.add_router("/project-docs", docs.router)
api.add_router("/tasks", tasks.router)
api.add_router("/tasks", decisions.router)
api.add_router("/tasks", pr_context.router)
api.add_router("/me", portfolio_router)
api.add_router("/today", today.router)
api.add_router("/reports", reports.router)
# 고정 경로를 먼저. /integrations/{name}/status가 /integrations/discord/...를 삼키지 않게 한다.
api.add_router("/integrations/discord", discord.router)
api.add_router("/integrations/github", github.router)
api.add_router("/integrations", integrations.router)
