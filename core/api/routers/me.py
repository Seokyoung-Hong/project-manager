from ninja import Router

from accounts.services import set_user_settings
from orgs import settings as S
from orgs.models import OrgMembership

from ..schemas import ErrorOut, MeOut, UserSettingsIn, UserSettingsOut

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
        "orgs": [
            {"id": m.org_id, "name": m.org.name, "purpose": m.org.purpose, "role": m.role}
            for m in memberships
        ],
    }


def _user_settings_out(u) -> dict:
    return {"values": dict(u.settings), "defaults": {s.key: s.default for s in S.specs("user")}}


@router.get("/me/settings", response=UserSettingsOut)
def get_my_settings(request):
    return _user_settings_out(request.auth)


@router.put("/me/settings", response={200: UserSettingsOut, 400: ErrorOut})
def put_my_settings(request, payload: UserSettingsIn):
    return _user_settings_out(set_user_settings(request.auth, payload.values))
