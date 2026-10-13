"""IMPL-PLAN-13 §4.1: GitHub로 나가는 글에는 실명·조직 표시 이름이 실리지 않는다. 웹 경고만 조직 이름."""

import json

import pytest

from github import writes
from github.models import GitHubTeamLink, RepoConnection
from github.test_writes import _identity, calls, installed  # noqa: F401
from orgs.models import OrgMembership
from orgs.services import add_team_member

pytestmark = pytest.mark.django_db


def test_no_real_name_or_nickname_goes_to_github(installed, admin, member, team, task, calls):  # noqa: F811
    installed.member_fields = {"show_real_name": False, "fields": []}
    installed.save()
    OrgMembership.objects.filter(org=installed, user=member).update(nickname="별명팀원")
    add_team_member(team, admin, admin)
    add_team_member(team, member, admin)  # GitHub 미연결 → 경고
    GitHubTeamLink.objects.create(team=team, github_team_id=2, slug="backend")
    team.refresh_from_db()

    _, warns = writes.reconcile_team(team, actor=admin)
    assert any(w.startswith("별명팀원:") for w in warns)  # 웹 경고는 조직 이름

    # 실명으로 표시 조직에서도 GitHub 요청에는 이름이 없다
    installed.member_fields = {"show_real_name": True, "fields": []}
    installed.save()
    _identity(member, "member-gh")
    team.refresh_from_db()
    writes.reconcile_team(team, actor=admin)
    RepoConnection.objects.create(project=task.project, url="u", full_name="o/r", created_by=admin)
    task.project.refresh_from_db()
    writes.create_issue(task, actor=admin)
    sent = json.dumps(calls, ensure_ascii=False)
    for secret in ("김팀원", "김관리", "별명팀원"):
        assert secret not in sent
