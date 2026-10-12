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


class MemberInfoGate:
    """현재 조직의 필수 구성원 정보가 비었으면 그 조직 화면 대신 입력 화면으로 보낸다(orgs/member_info.py).

    URL이 조직·프로젝트·태스크·팀·문서를 가리키면 그 조직을, 아니면 세션의 현재 조직을 본다.
    다른 조직 화면은 그 조직 기준이라 막히지 않는다. API(/api/)는 api.auth가 따로 막는다.
    """

    def __init__(self, get_response):
        self.get_response = get_response

    def __call__(self, request):
        return self.get_response(request)

    def process_view(self, request, view_func, view_args, view_kwargs):
        match = request.resolver_match
        if (
            not request.user.is_authenticated
            or match is None
            or match.url_name in _OPEN_VIEWS
            or request.path.strip("/").split("/")[0] not in _ORG_PREFIXES
        ):
            return None
        from orgs.member_info import blocked_org, request_org_id, url
        from web.views.common import current_org, hx_redirect

        # ponytail: 세션 조직이 이미 나간 조직이면 current_org의 대체 조직을 못 본다(다음 조직 화면 진입에서 막힌다)
        org_id = (
            request_org_id(view_kwargs)
            or request.session.get("org_id")
            or getattr(current_org(request), "pk", None)
        )
        org = blocked_org(request.user, org_id)
        return hx_redirect(request, url(org.pk)) if org else None
