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
        "guild_id": "9001",
        "kind": "team",
        "target_id": team.pk,
        "channel_id": "555",
        "viewers": viewers,
        **kw,
    }
    return bot("/channel-check", body).json()


CHANNELS, ROLES, GUILD, ADMINISTRATOR = 1 << 4, 1 << 28, 1 << 5, 1 << 3


def perm(did, bits):
    return {"discord_user_id": did, "permissions": bits}


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
    body = {
        "discord_user_id": "111",
        "guild_id": "9001",
        "kind": "team",
        "target_id": team.pk,
        "channel_id": "555",
    }
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
def granted(bot, linked_org, admin):
    """봇이 admin(Discord 100)의 서버 권한을 보고했다: 채널 관리 + 역할 관리."""
    bot("/member-permissions", {"guild_id": "9001", "members": [perm("100", CHANNELS | ROLES)]})
    admin.refresh_from_db()


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


def test_allowed_stays_and_revoke_warns_again(linked_team, bot, admin, linked_org, granted):
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
    type(linked_team).objects.filter(pk=linked_team.pk).update(discord_channel_managed=True)
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


def test_web_status_allow_revoke_and_toggle(linked_team, bot, client, admin, linked_org, granted):
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
    client.post(f"{url}/managed", {"kind": "team", "id": linked_team.pk, "managed": "0"})
    linked_team.refresh_from_db()
    assert linked_team.discord_channel_managed is False


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


# ---------- 결함 수정: 한 채널은 한 대상에만, 깜빡임, 길드 검증, 자동 관리 확인 ----------


def test_one_channel_links_to_one_target_only(linked_org, team, project, bot, admin):
    check(bot, team, [v(111)])
    body = {
        "discord_user_id": "100",
        "guild_id": "9001",
        "kind": "project",
        "target_id": project.pk,
        "channel_id": "555",
        "created": True,
    }
    r = bot("/channel-check", body)
    assert r.status_code == 400 and "팀 백엔드" in str(r.json())
    project.refresh_from_db()
    assert project.discord_channel_id == ""


def test_clearing_one_of_legacy_duplicates_keeps_the_others_allowed_list(
    linked_team, project, linked_org, bot
):
    type(project).objects.filter(pk=project.pk).update(discord_channel_id="555")  # 옛 중복 데이터
    alerts(bot, [v(777)])
    ch.clear_alerts("555", "project", project.pk)  # 팀이 아직 쓰고 있다
    assert DiscordChannelAlert.objects.filter(channel_id="555").count() == 1
    type(project).objects.filter(pk=project.pk).update(discord_channel_id="")
    ch.clear_alerts("555", "team", linked_team.pk)
    assert DiscordChannelAlert.objects.count() == 0


def test_missing_rows_do_not_flicker(linked_team, bot):
    alerts(bot, [], missing=[v(111, "팀원")])
    first = DiscordChannelAlert.objects.get(discord_user_id="111")
    alerts(bot, [], missing=[v(111, "팀원")])
    assert DiscordChannelAlert.objects.get(discord_user_id="111").pk == first.pk
    alerts(bot, [], missing=[])  # 접근을 얻으면 사라진다
    assert DiscordChannelAlert.objects.count() == 0


def test_channel_check_rejects_a_channel_from_another_guild(linked_org, team, bot):
    r = check(bot, team, [v(111)], guild_id="777")
    assert r.get("linked") is None  # 400 본문
    team.refresh_from_db()
    assert team.discord_channel_id == ""


def test_web_discord_actions_check_the_users_server_permissions(
    linked_team, bot, client, admin, linked_org, member
):
    """자동 관리 켜기·끄기, 허용·철회, 서버 연결 해제: PM 관리자 + Discord 서버 권한(fail closed)."""
    from datetime import timedelta

    from orgs.models import DiscordMemberPermission

    admin.refresh_from_db()
    alerts(bot, [v(777)])
    row = DiscordChannelAlert.objects.get(discord_user_id="777")

    def attempts():
        def toggle():
            ch.set_managed(linked_org, "team", linked_team.pk, True, admin)

        def allow():
            ch.resolve(linked_org, row.pk, "allow", admin)

        def unlink():
            dc.unlink_guild(linked_org, actor=admin)

        return {"managed": toggle, "managed ": allow, "unlink_guild": unlink}

    def refused(fn, text):
        with pytest.raises(ServiceError) as e:
            fn()
        assert text in " ".join(e.value.errors.values())

    # 확인 불가: 보고 없음(멤버 인텐트 꺼짐) → 거절하고 Discord 명령 안내
    for fn in attempts().values():
        refused(fn, "명령으로 해 주세요")
    # Discord 미연결
    User.objects.filter(pk=admin.pk).update(discord_user_id=None)
    admin.refresh_from_db()
    refused(attempts()["managed"], "Discord 계정 연결이 필요")
    User.objects.filter(pk=admin.pk).update(discord_user_id="100")
    admin.refresh_from_db()
    # 권한 부족: 채널 관리만 있으면 자동 관리·허용은 거절(역할 관리도 필요), 서버 관리 없으면 연결 해제 거절
    bot("/member-permissions", {"guild_id": "9001", "members": [perm("100", CHANNELS)]})
    refused(attempts()["managed"], "채널 관리, 역할 관리 권한이 필요")
    refused(attempts()["managed "], "역할 관리")
    refused(attempts()["unlink_guild"], "서버 관리 권한이 필요")
    # 오래된 보고
    DiscordMemberPermission.objects.update(reported_at=timezone.now() - timedelta(minutes=16))
    refused(attempts()["managed"], "오래됐습니다")
    # 정상: 채널 관리 + 역할 관리 / 관리자 비트는 전부 통과
    bot("/member-permissions", {"guild_id": "9001", "members": [perm("100", CHANNELS | ROLES)]})
    attempts()["managed"]()
    attempts()["managed "]()
    assert status_of("777") == "allowed"
    refused(attempts()["unlink_guild"], "서버 관리 권한이 필요")
    bot("/member-permissions", {"guild_id": "9001", "members": [perm("100", ADMINISTRATOR)]})
    attempts()["unlink_guild"]()
    linked_org.refresh_from_db()
    assert linked_org.discord_guild_id is None


def test_member_permissions_only_for_linked_org_members(linked_org, bot, outsider):
    User.objects.filter(pk=outsider.pk).update(
        discord_user_id="999", discord_linked_at=timezone.now()
    )
    r = bot(
        "/member-permissions",
        {"guild_id": "9001", "members": [perm("999", ADMINISTRATOR), perm("100", ROLES)]},
    )
    assert r.status_code == 200
    from orgs.models import DiscordMemberPermission

    assert [p.permissions for p in DiscordMemberPermission.objects.all()] == [ROLES]
    assert bot("/member-permissions", {"guild_id": "1", "members": []}).status_code == 404


def test_rest_unlink_needs_the_users_discord_permission(
    linked_team, client, admin, linked_org, project, bot
):
    _, raw = ApiToken.issue(admin, "w2", "write")
    type(project).objects.filter(pk=project.pk).update(discord_channel_id="777")

    def put():
        return client.put(
            f"/api/projects/{project.pk}/discord-channel",
            data={"channel_id": ""},
            content_type="application/json",
            headers={"Authorization": f"Bearer {raw}"},
        )

    r = put()
    assert r.status_code == 400 and "명령으로" in str(r.json())
    bot("/member-permissions", {"guild_id": "9001", "members": [perm("100", CHANNELS)]})
    assert put().status_code == 200


def test_guild_report_shows_denied_intent(linked_org, bot, client, admin):
    bot("/guild-report", {"guild_id": "9001", "permissions": 268504080, "intent_denied": True})
    client.force_login(admin)
    assert "서버 멤버 인텐트 꺼짐" in client.get(f"/orgs/{linked_org.pk}/discord").content.decode()
