from ninja import Router

from orgs.member_info import blocked_out
from orgs.models import OrgMembership

from ..schemas import MeOut

router = Router(tags=["me"])


@router.get("/me", response=MeOut)
def me(request):
    u = request.auth
    memberships = OrgMembership.objects.filter(user=u).select_related("org").order_by("org__name")
    return {
        "id": u.pk,
        "username": u.username,
        "display_name": u.display_name,
        "discord_user_id": u.discord_user_id,
        "auto_pull_days": u.auto_pull_days,
        # 이 요청에 쓴 토큰의 범위. MCP가 "이 토큰으로 할 수 있는 도구"만 보여 줄 때 읽는다.
        # 세션 쿠키로 들어오면 토큰이 없으므로 write로 본다(웹은 그 사람 권한 그대로다).
        "token_scope": getattr(getattr(request, "api_token", None), "scope", "write"),
        "orgs": [
            {"id": m.org_id, "name": m.org.name, "purpose": m.org.purpose, "role": m.role}
            for m in memberships
        ],
        "blocked_orgs": blocked_out(u),
    }
