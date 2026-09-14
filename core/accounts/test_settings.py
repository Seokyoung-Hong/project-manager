"""개인 설정 user.* (IMPL-PLAN-4 3단계, core 쪽)."""

import pytest

from accounts.models import ApiToken
from accounts.services import set_user_settings
from common.errors import ServiceError
from orgs.services import set_org_settings

pytestmark = pytest.mark.django_db


def test_set_user_settings_only_user_scope(member):
    set_user_settings(member, {"user.start_page": "me", "user.notify_dm": "0"})
    member.refresh_from_db()
    assert member.settings == {"user.start_page": "me", "user.notify_dm": False}
    with pytest.raises(ServiceError):
        set_user_settings(member, {"task.priority_cap": 7})


def test_start_page_and_me_defaults(client, member, org):
    client.force_login(member)
    assert client.get("/").url.endswith("/today")
    set_user_settings(member, {"user.start_page": "me", "user.me_group": "none"})
    assert client.get("/").url.endswith("/me")
    r = client.get("/me")
    assert r.status_code == 200


def test_preferences_page_saves(client, member, org):
    client.force_login(member)
    r = client.get("/settings/preferences")
    assert r.status_code == 200
    r = client.post(
        "/settings/preferences",
        {"user.notify_dm": "0", "user.notify_kinds": ["", "d1"], "user.start_page": "today"},
    )
    assert r.status_code == 302
    member.refresh_from_db()
    assert member.settings == {"user.notify_dm": False, "user.notify_kinds": ["d1"]}


def test_me_settings_api(api, member):
    r = api.put("/api/me/settings", {"values": {"user.board_default": True}})
    assert r.status_code == 200 and r.json()["values"] == {"user.board_default": True}
    assert api.get("/api/me/settings").json()["defaults"]["user.start_page"] == "today"


def test_members_notify_only_for_bot_token(client, api, org, admin, member):
    set_org_settings(org, {"notify.deadline_kinds": ["d1", "d0"]}, admin)
    set_user_settings(member, {"user.notify_kinds": ["d3", "d0"], "user.notify_hour": 11})
    r = api.get(f"/api/orgs/{org.pk}/members")
    assert all("notify" not in u or u["notify"] is None for u in r.json())
    _, raw = ApiToken.issue(admin, "bot", "bot")
    r = client.get(f"/api/orgs/{org.pk}/members", headers={"Authorization": f"Bearer {raw}"})
    row = next(u for u in r.json() if u["id"] == member.pk)
    assert row["notify"] == {"dm": True, "kinds": ["d0"], "hour": 11}
