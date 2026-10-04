"""조직 ↔ Discord 서버 바인딩(IMPL-PLAN-4 §8.4). 서비스·웹 흐름·봇 엔드포인트."""

import pytest
from django.core.cache import cache
from django.utils import timezone

from accounts.models import ApiToken, User
from common.errors import ServiceError

from . import discord as dc
from .models import Organization
from .services import create_org

DC = "/api/integrations/discord"

pytestmark = pytest.mark.django_db


@pytest.fixture(autouse=True)
def _client_id(settings):
    settings.DISCORD_CLIENT_ID = "123456789"
    cache.clear()
    yield
    cache.clear()


@pytest.fixture
def bot_token(db):
    bot = User.objects.create_user("discord-bot", password="pw12345678", display_name="산돌이 봇")
    _, raw = ApiToken.issue(bot, "봇", "bot")
    return raw


# ---------- 서비스 ----------


def test_link_guild_requires_admin(org, member):
    with pytest.raises(ServiceError):
        dc.link_guild(org, "9001", actor=member)


def test_link_guild_records_who_and_when(org, admin):
    dc.link_guild(org, "9001", actor=admin)
    org.refresh_from_db()
    assert org.discord_guild_id == "9001"
    assert org.discord_linked_by == admin
    assert org.discord_linked_at is not None


def test_guild_belongs_to_one_org(org, admin):
    other = create_org("다른 조직", "", admin)
    dc.link_guild(org, "9001", actor=admin)
    with pytest.raises(ServiceError) as e:
        dc.link_guild(other, "9001", actor=admin)
    assert "이미" in " ".join(e.value.errors.values())


def test_changing_guild_drops_the_old_channel(org, admin):
    dc.link_guild(org, "9001", actor=admin)
    dc.set_channel_by_guild("9001", admin, "555")
    dc.link_guild(org, "9002", actor=admin)
    org.refresh_from_db()
    assert org.discord_channel_id == ""  # 옛 채널은 옛 서버의 것이다


def test_unlink_clears_everything(org, admin):
    from datetime import timedelta  # noqa: F401

    from orgs.models import DiscordMemberPermission

    dc.link_guild(org, "9001", actor=admin)
    User.objects.filter(pk=admin.pk).update(discord_user_id="100", discord_linked_at=timezone.now())
    admin.refresh_from_db()
    # 웹의 서버 연결 해제는 사용자의 Discord 서버 권한(서버 관리)을 봇 보고값으로 확인한다
    DiscordMemberPermission.objects.create(
        org=org, user=admin, permissions=1 << 5, reported_at=timezone.now()
    )
    dc.unlink_guild(org, actor=admin)
    org.refresh_from_db()
    assert org.discord_guild_id is None
    assert org.discord_channel_id == ""
    assert not dc.bound_orgs().exists()


def test_set_channel_needs_binding_and_admin(org, admin, member):
    with pytest.raises(ServiceError):
        dc.set_channel_by_guild("9001", admin, "555")  # 아직 안 붙었다
    dc.link_guild(org, "9001", actor=admin)
    with pytest.raises(ServiceError):
        dc.set_channel_by_guild("9001", member, "555")
    assert dc.set_channel_by_guild("9001", admin, "555").discord_channel_id == "555"


def test_org_by_guild(org, admin):
    assert dc.org_by_guild("9001") is None
    dc.link_guild(org, "9001", actor=admin)
    assert dc.org_by_guild("9001") == org


# ---------- 웹 흐름 ----------


def test_connect_sends_to_discord_with_state(client, org, admin):
    client.force_login(admin)
    r = client.get(f"/orgs/{org.pk}/discord/connect")
    assert r.status_code == 302
    assert r.headers["Location"].startswith("https://discord.com/oauth2/authorize?")
    assert client.session["dc_state"] in r.headers["Location"]
    assert client.session["dc_org"] == org.pk


def test_installed_without_state_is_404(client, org, admin):
    """Discord 쪽에서 곧바로 설치하면 state가 없다. GitHub 설치와 같은 방어다."""
    client.force_login(admin)
    r = client.get("/orgs/discord/installed?guild_id=9001&state=엉뚱한값")
    assert r.status_code == 404
    org.refresh_from_db()
    assert org.discord_guild_id is None


def test_installed_binds_the_guild(client, org, admin):
    client.force_login(admin)
    client.get(f"/orgs/{org.pk}/discord/connect")
    state = client.session["dc_state"]
    r = client.get(f"/orgs/discord/installed?guild_id=9001&state={state}")
    assert r.status_code == 302
    org.refresh_from_db()
    assert org.discord_guild_id == "9001"


def test_discord_tab_hidden_without_client_id(client, org, admin, settings):
    settings.DISCORD_CLIENT_ID = ""
    client.force_login(admin)
    assert client.get(f"/orgs/{org.pk}/discord").status_code == 404


# ---------- 봇 엔드포인트 ----------


def test_bot_lists_bound_orgs_with_effective_settings(client, org, admin, bot_token):
    dc.link_guild(org, "9001", actor=admin)
    dc.set_channel_by_guild("9001", admin, "555")
    r = client.get(f"{DC}/orgs", headers={"Authorization": f"Bearer {bot_token}"})
    assert r.status_code == 200
    (row,) = r.json()
    assert row["org_id"] == org.pk
    assert row["guild_id"] == "9001"
    assert row["channel_id"] == "555"
    # 실효 설정이 기본값까지 채워져 온다 — 봇이 기본값을 알 필요가 없다.
    assert row["settings"]["notify.send_hour"] == -1
    assert row["settings"]["notify.weekly_enabled"] is True


def test_unbound_org_is_not_listed(client, org, bot_token):
    r = client.get(f"{DC}/orgs", headers={"Authorization": f"Bearer {bot_token}"})
    assert r.json() == []


def test_bot_reads_member_notify_settings(client, org, admin, member, bot_token):
    member.settings = {"user.notify_dm": False}
    member.save(update_fields=["settings"])
    r = client.get(f"{DC}/orgs/{org.pk}/members", headers={"Authorization": f"Bearer {bot_token}"})
    assert r.status_code == 200
    rows = {m["display_name"]: m for m in r.json()}
    assert rows[member.display_name]["notify_dm"] is False
    assert rows[admin.display_name]["notify_dm"] is True
    assert rows[admin.display_name]["notify_kinds"] == ["d3", "d1", "d0", "overdue"]


def test_slash_channel_command_sets_the_org_channel(client, org, admin, member, bot_token):
    dc.link_guild(org, "9001", actor=admin)
    admin.discord_user_id = "222"
    admin.discord_linked_at = timezone.now()
    admin.save(update_fields=["discord_user_id", "discord_linked_at"])
    r = client.post(
        f"{DC}/orgs/channel",
        data={"discord_user_id": "222", "guild_id": "9001", "channel_id": "777"},
        content_type="application/json",
        headers={"Authorization": f"Bearer {bot_token}"},
    )
    assert r.status_code == 200
    org.refresh_from_db()
    assert org.discord_channel_id == "777"


def test_slash_channel_command_rejects_non_admin(client, org, admin, member, bot_token):
    dc.link_guild(org, "9001", actor=admin)
    member.discord_user_id = "333"
    member.discord_linked_at = timezone.now()
    member.save(update_fields=["discord_user_id", "discord_linked_at"])
    r = client.post(
        f"{DC}/orgs/channel",
        data={"discord_user_id": "333", "guild_id": "9001", "channel_id": "777"},
        content_type="application/json",
        headers={"Authorization": f"Bearer {bot_token}"},
    )
    assert r.status_code == 400
    org.refresh_from_db()
    assert org.discord_channel_id == ""


def test_bound_orgs_is_ordered_and_excludes_unbound(admin):
    a = create_org("가", "", admin)
    b = create_org("나", "", admin)
    dc.link_guild(b, "9002", actor=admin)
    assert list(dc.bound_orgs()) == [b]
    dc.link_guild(a, "9001", actor=admin)
    assert list(dc.bound_orgs()) == [a, b]
    assert Organization.objects.count() == 2


def test_bot_reads_escalation_recipients(client, org, admin, member, project, bot_token):
    project.owners.add(member)
    r = client.get(
        f"{DC}/projects/{project.pk}/owners", headers={"Authorization": f"Bearer {bot_token}"}
    )
    assert member.display_name in [p["display_name"] for p in r.json()]
    r = client.get(f"{DC}/orgs/{org.pk}/admins", headers={"Authorization": f"Bearer {bot_token}"})
    assert [p["display_name"] for p in r.json()] == [admin.display_name]


def test_tasks_updated_since_ignores_status(client, org, admin, task, write_token):
    """채널 게시는 방금 done으로 넘어간 것도 봐야 '완료' 사건을 만든다."""
    from tasks.services import transition

    transition(task, "doing", actor=admin, source="web", expected_version=task.version)
    r = client.get(
        f"/api/tasks?org={org.pk}&updated_since=2000-01-01T00:00:00Z",
        headers={"Authorization": f"Bearer {write_token}"},
    )
    (item,) = [i for i in r.json()["items"] if i["id"] == task.pk]
    assert item["status"] == "doing"
    assert "discord_channel_id" in item["project"]
    assert "stopped_at" in item and "updated_at" in item
    later = client.get(
        f"/api/tasks?org={org.pk}&updated_since=2999-01-01T00:00:00Z",
        headers={"Authorization": f"Bearer {write_token}"},
    )
    assert later.json()["total"] == 0
