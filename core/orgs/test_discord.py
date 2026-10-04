"""조직 ↔ Discord 서버 바인딩(IMPL-PLAN-4 §8.4). 서비스·웹 흐름·봇 엔드포인트."""

import json
import urllib.error
import urllib.parse
from datetime import date, timedelta

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


class _Resp:
    def __init__(self, body: bytes):
        self.body = body

    def read(self):
        return self.body

    def __enter__(self):
        return self

    def __exit__(self, *a):
        return False


@pytest.fixture
def discord_token(monkeypatch, settings):
    """Discord 토큰 엔드포인트 흉내. `calls`에 보낸 본문이 쌓이고 `guild`가 응답의 서버다."""
    settings.DISCORD_CLIENT_SECRET = "s3cret"
    state = {"guild": "9001", "calls": [], "fail": False}

    def fake_urlopen(req, timeout=None):
        state["calls"].append((req.full_url, dict(urllib.parse.parse_qsl(req.data.decode()))))
        if state["fail"]:
            raise urllib.error.HTTPError(req.full_url, 400, "bad", {}, None)
        return _Resp(json.dumps({"access_token": "x", "guild": {"id": state["guild"]}}).encode())

    monkeypatch.setattr("orgs.discord.urllib.request.urlopen", fake_urlopen)
    return state


def _install(client, org, query):
    client.get(f"/orgs/{org.pk}/discord/connect")
    state = client.session["dc_state"]
    return client.get(f"/orgs/discord/installed?{query}&state={state}")


def test_installed_binds_the_guild_from_code_exchange(client, org, admin, discord_token):
    client.force_login(admin)
    r = _install(client, org, "code=abc&guild_id=9001")
    assert r.status_code == 302
    org.refresh_from_db()
    assert org.discord_guild_id == "9001"
    ((url, body),) = discord_token["calls"]
    assert url == "https://discord.com/api/v10/oauth2/token"
    assert body["code"] == "abc"
    assert body["client_secret"] == "s3cret"
    assert body["grant_type"] == "authorization_code"


def test_installed_rejects_a_forged_guild_id(client, org, admin, discord_token):
    """쿼리의 guild_id를 남의 서버로 고쳐도 code 교환 결과와 다르면 붙이지 않는다(S2)."""
    discord_token["guild"] = "9001"
    client.force_login(admin)
    _install(client, org, "code=abc&guild_id=7777")
    org.refresh_from_db()
    assert org.discord_guild_id is None


def test_installed_rejects_when_exchange_fails(client, org, admin, discord_token):
    discord_token["fail"] = True
    client.force_login(admin)
    _install(client, org, "code=abc&guild_id=9001")
    org.refresh_from_db()
    assert org.discord_guild_id is None


def test_installed_without_code_or_secret_does_not_bind(
    client, org, admin, discord_token, settings
):
    client.force_login(admin)
    _install(client, org, "guild_id=9001")
    settings.DISCORD_CLIENT_SECRET = ""
    _install(client, org, "code=abc&guild_id=9001")
    org.refresh_from_db()
    assert org.discord_guild_id is None
    assert discord_token["calls"] == []


def test_installed_without_session_state_is_404(client, org, admin, discord_token):
    """세션에 state가 없으면(None) 빈 state로도 통과하지 못한다."""
    client.force_login(admin)
    r = client.get("/orgs/discord/installed?code=abc&guild_id=9001&state=")
    assert r.status_code == 404


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


# ---------- 마감 DM 대상(F1): 알림 설정을 core 한 곳에서 적용 ----------

MON = date(2026, 9, 7)  # 월요일


def _due(project, member, title, due):
    from tasks.models import Task
    from tasks.services import create_task

    t = create_task(project=project, title=title, actor=member, source="web", due_date=due)
    Task.objects.filter(pk=t.pk).update(due_date=due, assignee=member)
    return t


def _kinds(org, today):
    return {t.title: kind for t, kind in dc.deadline_alerts(org, today)}


def _org_set(org, **values):
    org.settings = {**(org.settings or {}), **values}
    org.save(update_fields=["settings"])


@pytest.fixture
def dues(project, member):
    for title, days in (("d3", 3), ("d2", 2), ("d1", 1), ("d0", 0), ("over1", -1), ("over8", -8)):
        _due(project, member, title, MON + timedelta(days=days))


def test_deadline_alerts_default_kinds(org, dues):
    assert _kinds(org, MON) == {
        "d3": "d3",
        "d1": "d1",
        "d0": "d0",
        "over1": "overdue",
        "over8": "overdue",
    }


def test_deadline_alerts_org_and_user_kinds_intersect(org, dues, member):
    _org_set(org, **{"notify.deadline_kinds": ["d3", "d1", "overdue"]})
    member.settings = {"user.notify_kinds": ["d1", "d0", "overdue"]}
    member.save(update_fields=["settings"])
    assert _kinds(org, MON) == {"d1": "d1", "over1": "overdue", "over8": "overdue"}


def test_deadline_alerts_grace_days_match_the_web(org, dues):
    """유예 3일: 1일 지난 것은 웹에서도 초과가 아니라 DM도 없다. 8일 지난 것만 초과다."""
    _org_set(org, **{"task.overdue_grace_days": 3})
    got = _kinds(org, MON)
    assert "over1" not in got
    assert got["over8"] == "overdue"


def test_deadline_alerts_quiet_weekend(org, dues):
    _org_set(org, **{"notify.quiet_weekend": True})
    assert _kinds(org, MON - timedelta(days=1)) == {}  # 일요일
    assert _kinds(org, MON) != {}


def test_deadline_alerts_overdue_repeat(org, project, member):
    _due(project, member, "late", MON - timedelta(days=1))  # 월요일에 초과 1일째
    _org_set(org, **{"notify.overdue_repeat": "never"})
    assert _kinds(org, MON) == {"late": "overdue"}
    assert _kinds(org, MON + timedelta(days=1)) == {}
    _org_set(org, **{"notify.overdue_repeat": "weekly"})
    assert _kinds(org, MON + timedelta(days=1)) == {}
    assert _kinds(org, MON + timedelta(days=7)) == {"late": "overdue"}
    _org_set(org, **{"notify.overdue_repeat": "weekdays"})
    assert _kinds(org, MON + timedelta(days=4)) == {"late": "overdue"}  # 금요일
    assert _kinds(org, MON + timedelta(days=5)) == {}  # 토요일


def test_bot_deadlines_endpoint(client, org, dues, bot_token):
    r = client.get(
        f"{DC}/orgs/{org.pk}/deadlines?date={MON.isoformat()}",
        headers={"Authorization": f"Bearer {bot_token}"},
    )
    assert r.status_code == 200
    rows = {row["title"]: row for row in r.json()}
    assert rows["d1"]["alert_kind"] == "d1"
    assert rows["d1"]["project"]["name"] == "학식 API"
    assert rows["d1"]["url"].endswith(f"/tasks/{rows['d1']['id']}")
    assert "d2" not in rows


def test_unbuilt_notify_settings_are_hidden():
    from .settings import SPECS, specs_for

    keys = {s.key for s in specs_for("org")}
    assert "notify.team_channel_weekly" not in keys
    assert "milestone_due" not in dict(SPECS["notify.project_channel_events"].choices)
