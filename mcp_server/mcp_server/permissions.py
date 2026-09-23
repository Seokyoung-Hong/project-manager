# 이 파일은 tools/list에 "보이는" 도구만 거른다 — 실제로 호출을 막는 곳은 core의 services다.
# 여기서 뺀 도구도 core는 여전히(권한 없으면) 거부한다. 목록에서 빼는 일과 호출을 막는 일은
# 서로 다른 문제이고, 규칙은 core 한 곳에만 있다 — 여기서 이중으로 판정하지 않는다.
import time

from .core_client import Core

# 도구 이름 -> 필요한 최소 단계. read(기본) < write < admin(조직 관리자).
NEEDS: dict[str, str] = {
    "get_guide": "read",
    "list_orgs": "read",
    "list_projects": "read",
    "get_project": "read",
    "get_org": "read",
    "list_discord_channels": "read",
    "plan_project_channel_assignments": "read",
    "assign_project_channel": "admin",
    "unlink_project_channel": "admin",
    "create_project_channel": "admin",
    "update_project": "write",
    "create_project": "write",
    "get_project_api_spec": "read",
    "set_project_api_spec": "write",
    "get_project_repo": "read",
    "list_tasks": "read",
    "get_task": "read",
    "get_task_github": "read",
    "get_task_history": "read",
    "create_task": "write",
    "update_task": "write",
    "transition_task": "write",
    "extend_task": "write",
    "append_note": "write",
    "get_governance": "read",
    "get_settings": "read",
    "update_org_settings": "admin",
    "get_project_settings": "read",
    "update_project_settings": "write",
    "get_my_settings": "read",
    "update_my_settings": "write",
    "create_invite": "admin",
    "revoke_invite": "admin",
    "update_governance": "admin",
    "get_today": "read",
    "add_today": "write",
    "exclude_today": "write",
    "restore_excluded_today": "write",
    "reorder_today": "write",
    "set_today_auto_pull": "write",
    "list_org_repos": "read",
    "connect_repo": "write",
    "list_docs": "read",
    "get_doc": "read",
    "create_doc": "write",
    "update_doc": "write",
    "list_teams": "read",
    "create_team": "admin",
    "add_team_member": "admin",
    "remove_team_member": "admin",
    "delete_team": "admin",
    "delete_project": "admin",
    "delete_task": "admin",
    "set_project_teams": "write",
    "get_org_status": "read",
    "get_weekly_report_data": "read",
    "list_members": "read",
    "search": "read",
    "fetch": "read",
}

_CACHE_TTL = 60
_cache: dict[str, tuple[float, frozenset[str]]] = {}


def _probe(token: str) -> frozenset[str]:
    """이 토큰이 볼 수 있는 최대 단계 집합. read는 늘 포함한다."""
    core = Core(token)
    try:
        me = core.get("/api/me")
    except Exception:
        # 토큰이 무효거나 core가 안 죽었어도 안 답하면, 안전한 쪽으로 닫는다(읽기만).
        return frozenset({"read"})
    levels = {"read"}
    if any(o.get("role") == "admin" for o in me.get("orgs", [])):
        levels.add("admin")
    # 토큰 범위는 core가 /api/me에서 그대로 알려 준다. 예전에는 없는 태스크에 PATCH를 보내
    # 403인지 보는 식으로 알아냈는데, 쓰기 요청으로 권한을 떠보는 것은 로그와 처리량 제한에
    # 흔적을 남긴다. 값이 없는 옛 core를 만나면 쓰기로 본다(차단은 어차피 core가 한다).
    if me.get("token_scope", "write") in ("write", "bot"):
        levels.add("write")
    return frozenset(levels)


def levels_for(token: str | None) -> frozenset[str]:
    """토큰의 단계 집합을 60초 캐시해서 돌려준다. 토큰이 없으면 읽기만."""
    if not token:
        return frozenset({"read"})
    now = time.monotonic()
    cached = _cache.get(token)
    if cached and now - cached[0] < _CACHE_TTL:
        return cached[1]
    levels = _probe(token)
    _cache[token] = (now, levels)
    return levels


def visible_names(token: str | None) -> frozenset[str]:
    """지금 이 토큰으로 목록에 보여도 되는 도구 이름."""
    levels = levels_for(token)
    return frozenset(name for name, need in NEEDS.items() if need in levels)
