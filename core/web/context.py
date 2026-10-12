from django.conf import settings
from django.db.models import Count, Q

from orgs.member_info import blocked_orgs
from orgs.services import orgs_of
from projects.services import visible_projects
from tasks.models import Task
from tasks.work_requests import received

from .views.common import current_org

NAV_BY_URL = {
    "today": "today",
    "today_quick": "today",
    "me": "me",
    "project_index": "project",
    "project_detail": "project",
    "project_docs": "project",
    "project_settings": "project",
    "project_repo": "project",
    "project_issues": "project",
    "project_api": "project",
    "org": "org",
    "org_list": "org",
    "org_detail": "org",
    "org_new": "org",
    "org_members": "org",
    "org_teams": "org",
    "team_detail": "org",
    "org_capacity": "org",
    "org_roadmap": "org",
    "org_governance": "org",
    "org_notes": "org",
    "org_docs": "org",
    "org_settings": "org",
    "org_member_info": "org",
    "org_discord": "org",
    "org_issues": "org",
    "org_github": "org",
    "search": "search",
    "request_index": "request",
    "request_new": "request",
    "request_detail": "request",
}


def rt_keys(request, url_name, match):
    """실시간 구독 키(realtime.js): 오늘은 내 할 일(U), 프로젝트 화면은 그 프로젝트(P). 권한은 /rt/ 서버가 다시 본다."""
    if url_name == "today":
        return f"U:{request.user.pk}"
    if url_name == "project_detail":
        return f"P:{match.kwargs['project_id']}"
    return ""


def shell(request):
    """base.html 셸: 현재 조직, 프로젝트 레일, nav 강조, 닫기 후 돌아갈 주소."""
    if not request.user.is_authenticated:
        return {"github_enabled": settings.GITHUB_ENABLED}  # 로그인·가입 화면의 GitHub 버튼
    # 셸이 조직 전환 패널을 그리므로 목록을 여기서 한 번 읽고 current_org에 넘긴다.
    my_orgs = list(orgs_of(request.user).order_by("name"))
    org = current_org(request, my_orgs)
    match = request.resolver_match
    url_name = match.url_name if match else ""
    nav = NAV_BY_URL.get(url_name, "")
    projects = []
    if nav == "project" and org is not None:
        projects = (
            visible_projects(request.user, org)
            .filter(is_archived=False)
            # 연결 태스크도 센다(프로젝트별 수치는 연결 포함, IMPL-PLAN-11 §3.4). 두 조인을 distinct로
            # 세어 곱이 생기지 않게 한다.
            .annotate(
                open_count=Count("tasks", filter=Q(tasks__status__in=Task.OPEN), distinct=True)
                + Count(
                    "task_links",
                    filter=Q(task_links__status="active", task_links__task__status__in=Task.OPEN),
                    distinct=True,
                )
            )
            .order_by("name")
        )
    return {
        "current_org": org,
        # 막힌 조직은 열람 관문이 빼므로 화면마다 안내를 한 줄 붙인다(입력 화면 자체는 빼고)
        "blocked_orgs": [] if url_name == "org_member_info" else blocked_orgs(request.user),
        "my_orgs": my_orgs,
        "nav_projects": projects,  # 프로젝트 영역이 아니면 빈 목록이라 레일이 렌더되지 않는다
        "nav": nav,
        "request_badge": received(request.user).filter(status="pending").count(),
        "current_project_id": match.kwargs.get("project_id") if match else None,
        "rt_keys": rt_keys(request, url_name, match),
        "page_url": request.get_full_path(),
        "github_enabled": settings.GITHUB_ENABLED,
        "discord_enabled": bool(settings.DISCORD_CLIENT_ID),
        "webmcp_origin_trial": settings.WEBMCP_ORIGIN_TRIAL,
    }
