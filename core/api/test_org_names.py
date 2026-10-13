"""IMPL-PLAN-13 갈래 B — API·Discord 응답의 display_name = 그 조직에서 보이는 이름, `/표시이름` 엔드포인트."""

import pytest
from django.core.cache import cache

from accounts.models import ApiToken, User
from api.schemas import DiscordNicknameIn
from orgs.models import OrgMembership
from tasks.brief import user_brief
from tasks.models import ChangeLog, Task

DC = "/api/integrations/discord"

pytestmark = pytest.mark.django_db


@pytest.fixture(autouse=True)
def _fresh_throttle():
    cache.clear()
    yield
    cache.clear()


@pytest.fixture
def nick(org, member):
    OrgMembership.objects.filter(org=org, user=member).update(nickname="새싹")
    return "새싹"


@pytest.fixture
def bot(client, db):
    bot = User.objects.create_user("discord-bot", password="pw12345678", display_name="봇")
    _, raw = ApiToken.issue(bot, "봇", "bot")

    def _call(method, path, body=None):
        return getattr(client, method)(
            f"{DC}{path}",
            data=body,
            content_type="application/json",
            headers={"Authorization": f"Bearer {raw}"},
        )

    return _call


def test_user_brief_uses_org_name(org, member, nick):
    assert user_brief(member)["display_name"] == "팀원"  # 조직 없음 = 계정 표시 이름
    assert user_brief(member, org)["display_name"] == "새싹"
    assert user_brief(member, org.pk)["display_name"] == "새싹"
    org.member_fields = {"show_real_name": True}
    org.save(update_fields=["member_fields"])
    assert user_brief(member, org)["display_name"] == "김팀원"


def test_task_and_members_api_show_org_name(api, org, task, member, admin, nick):
    Task.objects.filter(pk=task.pk).update(assignee=member)
    got = api.get(f"/api/tasks/{task.pk}").json()
    assert got["assignee"]["display_name"] == "새싹"
    assert got["created_by"]["display_name"] == "새싹"
    members = api.get(f"/api/orgs/{org.pk}/members").json()
    assert [m["display_name"] for m in members] == ["관리자", "새싹"]
    hist = api.get(f"/api/tasks/{task.pk}/history").json()
    assert {h["actor"]["display_name"] for h in hist} == {"새싹"}


def test_report_assignee_name(api, org, task, member, nick):
    Task.objects.filter(pk=task.pk).update(assignee=member)
    row = api.get(f"/api/orgs/{org.pk}/status").json()["by_assignee"][0]
    assert row["assignee_name"] == "새싹"
    assert row["assignee__display_name"] == "팀원"  # 호환 키는 그대로


def test_discord_lists(bot, org, project, member, admin, nick):
    people = bot("get", f"/orgs/{org.pk}/members").json()
    assert [p["display_name"] for p in people] == ["관리자", "새싹"]
    OrgMembership.objects.filter(org=org, user=admin).update(nickname="가람")
    assert [p["display_name"] for p in bot("get", f"/orgs/{org.pk}/admins").json()] == ["가람"]
    owners = bot("get", f"/projects/{project.pk}/owners").json()
    assert owners[0]["display_name"] == "가람"
    # /members(여러 조직 자동완성)는 계정 표시 이름 그대로(§4.4 v3)
    names = [m["display_name"] for m in bot("post", "/members", {"discord_user_id": "111"}).json()]
    assert names == ["관리자", "팀원"]


# ---------- /표시이름 ----------


@pytest.fixture
def guild(org):
    org.discord_guild_id = "999"
    org.save(update_fields=["discord_guild_id"])
    return "999"


def _nick(bot, name, guild="999", who="111"):
    return bot(
        "post", "/orgs/nickname", {"discord_user_id": who, "guild_id": guild, "nickname": name}
    )


def test_nickname_self_change_and_clear(bot, org, member, guild):
    r = _nick(bot, "  새싹 ")
    assert r.status_code == 200
    assert r.json() == {"org_id": org.pk, "org_name": org.name, "display_name": "새싹"}
    assert OrgMembership.objects.get(org=org, user=member).nickname == "새싹"
    log = ChangeLog.objects.get(target_type="org", target_id=org.pk, field="nickname")
    assert log.source == "dc" and log.actor == member
    assert _nick(bot, "").json()["display_name"] == "팀원"  # 비우면 계정 표시 이름
    assert OrgMembership.objects.get(org=org, user=member).nickname == ""


def test_nickname_refusals(bot, org, member, outsider, guild):
    org.member_fields = {"show_real_name": True}
    org.save(update_fields=["member_fields"])
    assert _nick(bot, "새싹").status_code == 400  # 실명으로 표시 조직
    assert _nick(bot, "새싹", guild="123").status_code == 400  # 길드 미연결
    assert _nick(bot, "새싹", who="404").status_code == 404  # Discord 미연결
    outsider.discord_user_id = "222"
    outsider.discord_linked_at = member.discord_linked_at
    outsider.save()
    assert _nick(bot, "새싹", who="222").status_code == 400  # 구성원 아님
    assert not ChangeLog.objects.filter(field="nickname").exists()


def test_nickname_body_has_no_target_user():
    assert set(DiscordNicknameIn.model_fields) == {"discord_user_id", "guild_id", "nickname"}
