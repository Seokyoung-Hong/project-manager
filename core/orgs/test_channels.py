"""팀·프로젝트 채널의 권한 밖 인원 확인·경고·허용(IMPL-PLAN-5 B)."""

import pytest
from django.core.cache import cache
from django.utils import timezone

from accounts.models import ApiToken, User
from common.errors import ServiceError
from orgs import channels as ch
from orgs.models import DiscordChannelAlert
from tasks.models import Notice

from . import discord as dc

DC = "/api/integrations/discord"
pytestmark = pytest.mark.django_db


@pytest.fixture(autouse=True)
def _fresh(settings):
    settings.DISCORD_CLIENT_ID = "123456789"
    cache.clear()
    yield
    cache.clear()


@pytest.fixture
def linked_org(org, admin):
    dc.link_guild(org, "9001", actor=admin)
    User.objects.filter(pk=admin.pk).update(discord_user_id="100", discord_linked_at=timezone.now())
    return org


@pytest.fixture
def bot_token(db):
    bot = User.objects.create_user("discord-bot", password="pw12345678", display_name="봇")
    _, raw = ApiToken.issue(bot, "봇", "bot")
    return raw


@pytest.fixture
def bot(client, bot_token):
    def call(path, body=None, method="post"):
        kw = {"headers": {"Authorization": f"Bearer {bot_token}"}}
        if method == "get":
            return client.get(f"{DC}{path}", **kw)
        return client.post(f"{DC}{path}", data=body or {}, content_type="application/json", **kw)

    return call


def check(bot, team, viewers, **kw):
    body = {
        "discord_user_id": "100",
        "kind": "team",
        "target_id": team.pk,
        "channel_id": "555",
        "viewers": viewers,
        **kw,
    }
    return bot("/channel-check", body).json()


def v(i, name="x"):
    return {"id": str(i), "name": name}


# ---------- 순수 비교 ----------


def test_outsiders_is_pure_and_dedupes():
    assert ch.outsiders([v(1), v(2), v(2), v(3)], {"1"}) == [
        {"id": "2", "name": "x"},
        {"id": "3", "name": "x"},
    ]


def test_allowed_set_team_and_project(linked_org, team, project, admin, member):
    assert ch.base_allowed("team", team) == {"111"}  # 연결 안 한 사람은 권한 밖이다
    project.teams.add(team)
    assert ch.base_allowed("project", project) == {"100", "111"}  # 관리자(owners) + 담당 팀원


# ---------- 연결 전 확인 ----------


def test_connect_without_outsiders_links_unmanaged(linked_org, team, bot):
    r = check(bot, team, [v(111)])
    assert r == {"linked": True, "unknown": False, "outsiders": []}
    team.refresh_from_db()
    assert (team.discord_channel_id, team.discord_channel_managed) == ("555", False)


def test_outsiders_refuse_then_allow_records_allowed(linked_org, team, bot):
    r = check(bot, team, [v(111), v(777, "외부인")])
    assert r["linked"] is False and r["outsiders"] == [{"id": "777", "name": "외부인"}]
    team.refresh_from_db()
    assert team.discord_channel_id == ""
    # 명단은 다시 계산하므로 그사이 늘어난 사람도 함께 기록된다
    r = check(
        bot, team, [v(111), v(777, "외부인"), v(888, "또")], allow_outsiders=True, managed=True
    )
    assert r["linked"] is True
    team.refresh_from_db()
    assert (team.discord_channel_id, team.discord_channel_managed) == ("555", True)
    rows = DiscordChannelAlert.objects.filter(channel_id="555", status="allowed")
    assert {x.discord_user_id for x in rows} == {"777", "888"}


def test_unknown_viewers_fail_closed(linked_org, team, bot):
    r = check(bot, team, None)
    assert r["linked"] is False and r["unknown"] is True
    assert check(bot, team, None, allow_outsiders=True)["linked"] is True


def test_created_channel_links_managed(linked_org, team, bot):
    assert check(bot, team, None, created=True)["linked"] is True
    team.refresh_from_db()
    assert team.discord_channel_managed is True


def test_check_requires_org_admin(linked_org, team, bot):
    body = {"discord_user_id": "111", "kind": "team", "target_id": team.pk, "channel_id": "555"}
    r = bot("/channel-check", {**body, "viewers": []})
    assert r.status_code == 400
    team.refresh_from_db()
    assert team.discord_channel_id == ""


def test_changing_or_clearing_channel_deletes_alerts(linked_org, team, bot):
    check(bot, team, [v(777)], allow_outsiders=True)
    assert DiscordChannelAlert.objects.count() == 1
    check(bot, team, [], channel_id="556")
    assert DiscordChannelAlert.objects.count() == 0
    check(bot, team, [v(5)], channel_id="556", allow_outsiders=True)
    bot(f"/teams/{team.pk}/channel", {"discord_user_id": "100", "channel_id": ""})
    assert DiscordChannelAlert.objects.count() == 0


# ---------- 감시 상태 전이 ----------


def alerts(bot, outsiders, channel="555", missing=None):
    body = {"channel_id": channel, "outsiders": outsiders}
    if missing is not None:
        body["missing"] = missing
    return bot("/channel-alerts", {"guild_id": "9001", "channels": [body]})


def status_of(uid):
    return DiscordChannelAlert.objects.get(channel_id="555", discord_user_id=uid).status


@pytest.fixture
def linked_team(linked_org, team, bot):
    check(bot, team, [v(111)])
    return team


def test_new_outsider_dms_admin_not_channel(linked_team, bot):
    assert alerts(bot, [v(777, "외부인")]).status_code == 200
    assert status_of("777") == "open"
    [n] = Notice.objects.all()
    assert n.user.discord_user_id == "100" and n.channel_id == ""  # 채널에는 올리지 않는다
    assert "외부인" in n.text and "1명" in n.text
    alerts(bot, [v(777, "외부인")])  # 같은 사람은 다시 알리지 않는다
    assert Notice.objects.count() == 1


def test_open_gone_then_reappear_warns_again(linked_team, bot):
    alerts(bot, [v(777)])
    alerts(bot, [])
    assert status_of("777") == "gone"
    alerts(bot, [v(777)])
    assert status_of("777") == "open"
    assert Notice.objects.count() == 2


def test_allowed_stays_and_revoke_warns_again(linked_team, bot, admin, linked_org):
    alerts(bot, [v(777)])
    row = DiscordChannelAlert.objects.get(discord_user_id="777")
    ch.resolve(linked_org, row.pk, "allow", admin)
    assert status_of("777") == "allowed"
    alerts(bot, [])
    assert status_of("777") == "allowed"  # 사라져도 허용은 그대로
    assert "777" in bot("/channels", method="get").json()[0]["allowed_ids"]
    ch.resolve(linked_org, row.pk, "revoke", admin)
    assert not DiscordChannelAlert.objects.filter(discord_user_id="777").exists()
    alerts(bot, [v(777)])
    assert status_of("777") == "open"
    assert Notice.objects.count() == 2


def test_resolve_is_admin_only(linked_team, bot, linked_org, member):
    alerts(bot, [v(777)])
    row = DiscordChannelAlert.objects.get(discord_user_id="777")
    with pytest.raises(ServiceError):
        ch.resolve(linked_org, row.pk, "allow", member)


def test_unlinked_channel_ignored_and_dm_is_cut(linked_team, bot):
    alerts(bot, [v(1)], channel="999")
    assert DiscordChannelAlert.objects.count() == 0
    alerts(bot, [v(i, "가" * 90) for i in range(30)])
    assert len(Notice.objects.get().text) <= 1900


def test_missing_members_shown_only_when_unmanaged(linked_org, linked_team, bot, admin):
    alerts(bot, [], missing=[v(111, "팀원")])
    row = next(r for r in ch.overview(linked_org) if r["kind"] == "team")
    assert [m.display_name for m in row["missing"]] == ["팀원"]
    assert Notice.objects.count() == 0  # 알림은 없다
    ch.set_managed(linked_org, "team", linked_team.pk, True, admin)
    row = next(r for r in ch.overview(linked_org) if r["kind"] == "team")
    assert row["missing"] == []


# ---------- 봇 API ----------


def test_channels_listing(linked_org, team, project, bot):
    rows = bot("/channels", method="get").json()
    by = {(r["kind"], r["name"]): r for r in rows}
    assert by[("team", "백엔드")]["grant_ids"] == ["111"]
    assert by[("project", "학식 API")]["grant_ids"] == ["100"]
    assert (
        by[("team", "백엔드")]["guild_id"] == "9001" and by[("team", "백엔드")]["channel_id"] == ""
    )


def test_guild_report_marks_reauthorization_and_watching(linked_org, bot):
    assert bot("/guild-report", {"guild_id": "9001", "permissions": 3088}).status_code == 200
    linked_org.refresh_from_db()
    assert ch.needs_reauthorization(linked_org) and not ch.watching(linked_org)
    bot("/guild-report", {"guild_id": "9001", "permissions": 268504080, "watching": True})
    linked_org.refresh_from_db()
    assert not ch.needs_reauthorization(linked_org) and ch.watching(linked_org)
    assert bot("/guild-report", {"guild_id": "1", "permissions": 1}).status_code == 404


# ---------- 웹 ----------


def test_web_status_allow_revoke_and_toggle(linked_team, bot, client, admin, linked_org):
    alerts(bot, [v(777, "외부인")])
    client.force_login(admin)
    url = f"/orgs/{linked_org.pk}/discord"
    page = client.get(url).content.decode()
    assert "권한 밖 1명" in page and "외부인" in page
    row = DiscordChannelAlert.objects.get(discord_user_id="777")
    client.post(f"{url}/alerts/{row.pk}/allow")
    assert "허용 · 외부인" in client.get(url).content.decode()
    client.post(f"{url}/alerts/{row.pk}/revoke")
    assert DiscordChannelAlert.objects.count() == 0
    client.post(f"{url}/managed", {"kind": "team", "id": linked_team.pk, "managed": "1"})
    linked_team.refresh_from_db()
    assert linked_team.discord_channel_managed is True


def test_web_is_admin_only_and_install_link_has_new_permissions(
    linked_team, client, member, admin, linked_org
):
    client.force_login(member)
    row = DiscordChannelAlert.objects.create(org=linked_org, channel_id="555", discord_user_id="7")
    client.post(f"/orgs/{linked_org.pk}/discord/alerts/{row.pk}/allow")
    row.refresh_from_db()
    assert row.status == "open"
    client.force_login(admin)
    assert (
        "permissions=268504080" in client.get(f"/orgs/{linked_org.pk}/discord/connect")["Location"]
    )
    ch.record_guild_report(linked_org, 3088, True)
    assert "권한 갱신 필요" in client.get(f"/orgs/{linked_org.pk}/discord").content.decode()
