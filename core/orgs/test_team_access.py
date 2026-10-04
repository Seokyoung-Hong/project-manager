"""IMPL-PLAN-7 A2: 비개발 팀(`Team.dev_tools`)과 팀 화면 비공개(`Team.is_private`)."""

import pytest
from django.core.cache import cache
from django.utils import timezone

from accounts.models import ApiToken, User
from common.errors import ServiceError
from github import writes as gh_writes
from github.models import GitHubInstallation, GitHubTeamLink
from orgs.models import OrgMembership
from orgs.services import (
    add_team_member,
    can_view_team,
    create_team,
    set_org_settings,
    update_team,
    visible_teams,
)
from reports.services import org_status

pytestmark = pytest.mark.django_db

HX = {"HX-Request": "true"}


@pytest.fixture
def other(org):
    """팀에 속하지 않은 일반 멤버."""
    u = User.objects.create_user("other1", password="pw12345678", display_name="다른멤버")
    OrgMembership.objects.create(org=org, user=u, role="member")
    return u


@pytest.fixture
def secret(org, admin, member):
    t = create_team(org=org, name="인사", actor=admin, is_private=True)
    add_team_member(t, member, admin)
    return t


def _login(client, username):
    client.login(username=username, password="pw12345678")
    return client


# ---------- 비개발 팀 ----------


def test_non_dev_team_hides_github_and_404s_endpoints(settings, client, org, admin, team):
    settings.GITHUB_ENABLED = True
    GitHubInstallation.objects.create(
        org=org, installation_id=99, account_login="acme", installed_by=admin
    )
    update_team(team, name=team.name, dev_tools=False, actor=admin)
    c = _login(client, "admin1")
    body = c.get(f"/teams/{team.pk}").content.decode()
    assert "GitHub 팀 연결" not in body and "<th>GitHub</th>" not in body
    for path in ("link", "create", "unlink", "reconcile"):
        assert c.post(f"/teams/{team.pk}/github/{path}").status_code == 404
    assert "—" in c.get(f"/orgs/{org.pk}/teams").content.decode()


def test_reconcile_refuses_non_dev_team(team, admin):
    GitHubTeamLink.objects.create(team=team, github_team_id=1, slug="backend")
    team.dev_tools = False
    with pytest.raises(ServiceError) as e:
        gh_writes.reconcile_team(team, actor=admin)
    assert "개발 도구" in e.value.errors["team"]


def test_team_dialog_saves_flags(client, org, admin):
    c = _login(client, "admin1")
    r = c.post(f"/orgs/{org.pk}/teams/new", {"name": "마케팅", "is_private": "1"}, headers=HX)
    assert r.status_code == 204
    t = org.teams.get(name="마케팅")
    assert t.dev_tools is False and t.is_private is True


# ---------- 팀 화면 비공개 ----------


def test_visible_teams_rule(org, admin, member, other, team, secret):
    assert set(visible_teams(other, org)) == {team}
    assert set(visible_teams(member, org)) == {team, secret}
    assert set(visible_teams(admin, org)) == {team, secret}
    assert not can_view_team(other, secret)


def test_private_team_detail_404_for_outsider(client, member, other, secret):
    assert _login(client, "other1").get(f"/teams/{secret.pk}").status_code == 404
    client.logout()
    assert _login(client, "member1").get(f"/teams/{secret.pk}").status_code == 200
    client.logout()
    assert _login(client, "admin1").get(f"/teams/{secret.pk}").status_code == 200


def test_private_team_list_shows_name_only(client, org, other, secret):
    body = _login(client, "other1").get(f"/orgs/{org.pk}/teams").content.decode()
    assert "인사" in body
    assert f'/teams/{secret.pk}"' not in body  # 상세 링크 없음


def test_only_admin_changes_private_flag(member, secret):
    with pytest.raises(ServiceError):
        update_team(secret, name=secret.name, is_private=False, actor=member)


def test_private_team_blocks_self_join(org, admin, other, secret):
    set_org_settings(org, {"org.team_join_self": True}, admin)
    with pytest.raises(ServiceError):
        add_team_member(secret, other, other)


def test_capacity_hides_private_membership(org, member, other, secret):
    def teams_of(viewer):
        rows = org_status(org, viewer=viewer)["capacity"]
        return [t["name"] for r in rows if r["user"]["id"] == member.pk for t in r["teams"]]

    assert "인사" not in teams_of(other)
    assert "인사" in teams_of(member)
    assert "인사" not in teams_of(None)


# ---------- API·Discord ----------


def _bearer(user):
    _, raw = ApiToken.issue(user, "t", "write", for_ai=False)
    return {"Authorization": f"Bearer {raw}"}


def test_api_team_list_hides_count(client, org, other, member, secret):
    cache.clear()
    rows = client.get(f"/api/orgs/{org.pk}/teams", headers=_bearer(other)).json()
    row = next(r for r in rows if r["id"] == secret.pk)
    assert row["member_count"] is None and row["is_private"] and row["dev_tools"]
    rows = client.get(f"/api/orgs/{org.pk}", headers=_bearer(member)).json()["teams"]
    assert next(r for r in rows if r["id"] == secret.pk)["member_count"] == 1


def test_discord_team_list_hides_channel(client, org, admin, other, secret):
    cache.clear()
    secret.discord_channel_id = "999"
    secret.save()
    other.discord_user_id = "222"
    other.save()
    User.objects.filter(pk=other.pk).update(discord_linked_at=timezone.now())
    bot = User.objects.create_user("bot", password="pw12345678", display_name="봇")
    _, raw = ApiToken.issue(bot, "봇", "bot")
    rows = client.post(
        "/api/integrations/discord/teams",
        data={"discord_user_id": "222"},
        content_type="application/json",
        headers={"Authorization": f"Bearer {raw}"},
    ).json()
    assert next(r for r in rows if r["id"] == secret.pk)["discord_channel_id"] == ""
