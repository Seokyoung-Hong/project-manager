import json


def origin_agent_cluster(get_response):
    """WebMCP는 오리진 키 에이전트 클러스터에서만 동작한다.

    스펙상 `document.modelContext`의 registerTool·getTools·executeTool은 문서가 오리진 키가
    아니면 SecurityError로 거절한다. 브라우저가 기본으로 오리진 키를 주는지는 보장이 없으므로
    헤더로 못 박는다. 이 사이트는 document.domain을 쓰지 않아 잃는 것이 없다.
    """

    def middleware(request):
        response = get_response(request)
        response.headers.setdefault("Origin-Agent-Cluster", "?1")
        return response

    return middleware


# 조직 화면으로 보는 첫 경로 조각. 계정 설정·운영 콘솔·로그인·도움말 등은 조직과 상관없어 막지 않는다.
_ORG_PREFIXES = {"today", "me", "requests", "org", "orgs", "projects", "tasks", "teams", "docs", "notes", "milestones", "search"}  # fmt: skip
# 막혀도 열 수 있는 화면: 입력 화면, 조직 목록·만들기(전환), 항목 정의를 고치는 조직 설정.
_OPEN_VIEWS = {"org_member_info", "org_list", "org_new", "org_settings", "org_member_fields"}
# 여러 조직에 걸친 화면. 막힌 조직의 데이터는 열람 관문(usable_orgs)이 빼고 셸이 안내를 붙이므로
# 세션의 현재 조직으로 막지 않는다.
_CROSS_ORG_VIEWS = {"today", "today_quick", "me", "search", "request_index"}


class MemberInfoGate:
    """현재 조직의 필수 구성원 정보가 비었으면 그 조직 화면 대신 입력 화면으로 보낸다(orgs/member_info.py).

    URL이 조직·프로젝트·태스크·팀·문서·초대·구성원·마일스톤·요청을 가리키면 그 객체의 조직을, 폼·쿼리에
    org·project가 있으면 그 조직을, 아니면(여러 조직 화면 제외) 세션의 현재 조직을 본다.
    다른 조직 화면은 그 조직 기준이라 막히지 않는다. API(/api/)는 api.auth가 따로 막는다.
    """

    def __init__(self, get_response):
        self.get_response = get_response

    def __call__(self, request):
        response = self.get_response(request)
        # API 성공 응답에 막힌 조직 안내를 헤더로 붙인다. 목록 응답(/api/projects 등)의 형식을 깨지 않는
        # 공통 자리다. JSON(ASCII 이스케이프)이라 헤더에 한글이 그대로 실리지 않는다. pm.py·MCP가 읽어 보여 준다.
        user = getattr(request, "auth", None)
        if (
            request.path.startswith("/api/")
            and not request.path.startswith("/api/integrations/")
            and response.status_code < 300
            and getattr(user, "is_authenticated", False)
        ):
            from orgs.member_info import blocked_out

            if blocked := blocked_out(user):
                response.headers["X-Blocked-Orgs"] = json.dumps(blocked)
        return response

    def process_view(self, request, view_func, view_args, view_kwargs):
        match = request.resolver_match
        # 경로부터 본다: request.user는 DB를 읽는다. /rt/(SSE)에서 읽으면 스트림 내내 연결 하나를 붙잡는다.
        if (
            match is None
            or match.url_name in _OPEN_VIEWS
            or request.path.strip("/").split("/")[0] not in _ORG_PREFIXES
            or not request.user.is_authenticated
        ):
            return None
        from orgs.member_info import blocked_org, request_org_id, url
        from web.views.common import current_org, hx_redirect

        org_id = request_org_id(view_kwargs, {**request.GET.dict(), **request.POST.dict()})
        if org_id is None and match.url_name not in _CROSS_ORG_VIEWS:
            org_id = getattr(current_org(request), "pk", None)
        org = blocked_org(request.user, org_id)
        return hx_redirect(request, url(org.pk)) if org else None
