from django.conf import settings
from django.db.models import Count, Q

from orgs.services import orgs_of
from tasks.models import Task

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
    "org_settings": "org",
    "org_discord": "org",
    "org_issues": "org",
    "org_github": "org",
    "search": "search",
}


def shell(request):
    """base.html 셸: 현재 조직, 프로젝트 레일, nav 강조, 닫기 후 돌아갈 주소."""
    if not request.user.is_authenticated:
        return {}
    if settings.GITHUB_ENABLED:
        from github.services import refresh_github_access

        refresh_github_access(request)
    # 셸이 조직 전환 패널을 그리므로 목록을 여기서 한 번 읽고 current_org에 넘긴다.
    my_orgs = list(orgs_of(request.user).order_by("name"))
    org = current_org(request, my_orgs)
    match = request.resolver_match
    url_name = match.url_name if match else ""
    nav = NAV_BY_URL.get(url_name, "")
    projects = []
    if nav == "project" and org is not None:
        projects = (
            org.projects.filter(is_archived=False)
            .annotate(open_count=Count("tasks", filter=Q(tasks__status__in=Task.OPEN)))
            .order_by("name")
        )
    return {
        "current_org": org,
        "my_orgs": my_orgs,
        "nav_projects": projects,  # 프로젝트 영역이 아니면 빈 목록이라 레일이 렌더되지 않는다
        "nav": nav,
        "current_project_id": match.kwargs.get("project_id") if match else None,
        "page_url": request.get_full_path(),
        "github_enabled": settings.GITHUB_ENABLED,
        "discord_enabled": bool(settings.DISCORD_CLIENT_ID),
        "webmcp_origin_trial": settings.WEBMCP_ORIGIN_TRIAL,
    }
