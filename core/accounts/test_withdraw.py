"""회원 탈퇴(개인정보 처리 결정 A): 지우는 것·익명화하는 것·남는 것."""

import re

import pytest
from django.contrib.sessions.models import Session
from django.test import Client
from django.utils import timezone

from accounts.models import ApiToken, IdempotencyKey, LoginLock, OAuthClient, OAuthCode, User
from accounts.services import DELETED_NAME, withdraw
from common.dates import today_kst
from common.errors import ServiceError
from github.models import GitHubIdentity
from orgs.models import DiscordMemberPermission, OrgMembership, TeamMembership
from orgs.services import change_role
from portfolio.models import PortfolioDraft
from tasks.models import ChangeLog, Notice, Task, TodayItem
from tasks.services import create_task


def _fill(user, org, task):
    """탈퇴로 지워져야 할 개인 데이터를 한 벌 만든다."""
    ApiToken.issue(user, "ai")
    ApiToken.issue(user, "human", "write", for_ai=False)
    client = OAuthClient.register("Claude", ["https://claude.ai/cb"])
    OAuthCode.issue(
        client=client, user=user, redirect_uri="https://claude.ai/cb", code_challenge="x"
    )
    IdempotencyKey.objects.create(user=user, key="k", target_type="task", target_id=task.pk)
    GitHubIdentity.objects.create(user=user, github_id=42, login="gh-member")
    TodayItem.objects.create(user=user, task=task, date=today_kst())
    PortfolioDraft.objects.create(owner=user, org=org, title="내 포트폴리오")
    Notice.objects.create(org=org, user=user, text="DM")
    DiscordMemberPermission.objects.create(
        org=org, user=user, permissions=8, reported_at=timezone.now()
    )
    LoginLock.objects.create(
        kind="user", key=user.username.lower(), window_started_at=timezone.now()
    )
    user.email = "m@example.com"
    user.settings = {"user.notify_dm": False}
    user.save()


def test_withdraw_deletes_personal_data_and_keeps_work_records(
    member, admin, org, team, project, task
):
    _fill(member, org, task)
    project.owners.add(member)
    assigned = create_task(
        project=project,
        title="남는 일",
        actor=admin,
        source="web",
        assignee=member,
        no_due_reason="테스트",
    )
    logs_before = ChangeLog.objects.filter(actor=member).count()
    assert logs_before > 0

    withdraw(member, "pw12345678")
    member.refresh_from_db()

    # 지운 것
    for qs in (
        ApiToken.objects.filter(user=member),
        OAuthCode.objects.filter(user=member),
        IdempotencyKey.objects.filter(user=member),
        GitHubIdentity.objects.filter(user=member),
        TodayItem.objects.filter(user=member),
        PortfolioDraft.objects.filter(owner=member),
        Notice.objects.filter(user=member),
        DiscordMemberPermission.objects.filter(user=member),
        OrgMembership.objects.filter(user=member),
        TeamMembership.objects.filter(user=member),
        member.owned_projects.all(),
        LoginLock.objects.filter(kind="user", key="member1"),
    ):
        assert not qs.exists(), qs.model.__name__
    # 익명화
    assert member.username == f"deleted-{member.pk}"
    assert member.display_name == DELETED_NAME == str(member)
    assert not member.has_usable_password()
    assert member.email == member.first_name == member.last_name == ""
    assert member.discord_user_id is None and member.discord_linked_at is None
    assert member.discord_link_code is None
    assert member.settings == {}
    assert not member.is_active and not member.is_staff and not member.is_superuser
    # 남는 것: 업무 기록과 작성자 연결
    assert Task.objects.get(pk=task.pk).created_by_id == member.pk
    assert Task.objects.get(pk=assigned.pk).assignee.display_name == DELETED_NAME
    assert ChangeLog.objects.filter(actor=member).count() == logs_before
    assert OAuthClient.objects.exists()  # 커넥터 등록 자체는 사용자 것이 아니다


def test_wrong_password_changes_nothing(member, org, task):
    _fill(member, org, task)
    with pytest.raises(ServiceError):
        withdraw(member, "틀린비밀번호")
    member.refresh_from_db()
    assert member.username == "member1" and member.is_active
    assert ApiToken.objects.filter(user=member).count() == 2
    assert OrgMembership.objects.filter(user=member).exists()


def test_github_only_user_confirms_with_username(db):
    user = User.objects.create_user("ghonly", display_name="깃허브")
    user.set_unusable_password()
    user.save()
    GitHubIdentity.objects.create(user=user, github_id=7, login="ghonly")
    with pytest.raises(ServiceError):
        withdraw(user, "")
    with pytest.raises(ServiceError):
        withdraw(user, "other")
    withdraw(user, "ghonly")
    user.refresh_from_db()
    assert user.username == f"deleted-{user.pk}"
    assert not GitHubIdentity.objects.exists()


def test_last_admin_cannot_withdraw(admin, member, org):
    with pytest.raises(ServiceError) as e:
        withdraw(admin, "pw12345678")
    assert "마지막 관리자" in e.value.errors["org"]
    admin.refresh_from_db()
    assert admin.is_active and admin.username == "admin1"

    change_role(OrgMembership.objects.get(org=org, user=member), "admin", admin)
    withdraw(admin, "pw12345678")
    assert list(OrgMembership.objects.filter(org=org).values_list("user", "role")) == [
        (member.pk, "admin")
    ]


def test_same_username_can_sign_up_again(member, org):
    withdraw(member, "pw12345678")
    again = User.objects.create_user("member1", password="pw12345678")
    assert again.pk != member.pk
    c = Client()
    assert c.login(username="member1", password="pw12345678")


def test_placeholder_username_taken_does_not_block(member, org):
    User.objects.create_user(f"deleted-{member.pk}", password="pw12345678")
    withdraw(member, "pw12345678")
    member.refresh_from_db()
    assert member.username.startswith(f"deleted-{member.pk}-")


def test_withdraw_screen_ends_every_session(client, member, org, task):
    other = Client()
    other.force_login(member)
    client.force_login(member)
    page = client.get("/settings/account")
    assert page.status_code == 200
    assert "되돌릴 수 없습니다" in page.content.decode()

    bad = client.post("/settings/account", {"confirm": "nope"})
    assert "비밀번호가 맞지 않습니다" in bad.content.decode()

    done = client.post("/settings/account", {"confirm": "pw12345678"})
    assert "탈퇴를 마쳤습니다" in done.content.decode()
    assert not Session.objects.exists()
    assert other.get("/settings/profile").status_code == 302
    assert not client.login(username="member1", password="pw12345678")


def test_withdrawn_assignee_shows_as_deleted_and_leaves_picker(client, admin, member, org, project):
    t = create_task(
        project=project,
        title="맡긴 일",
        actor=admin,
        source="web",
        assignee=member,
        no_due_reason="테스트",
    )
    withdraw(member, "pw12345678")
    client.force_login(admin)
    html = client.get(f"/tasks/{t.pk}/panel").content.decode()
    assert f"<option selected disabled>{DELETED_NAME}</option>" in html
    assert not re.search(rf'<option value="{member.pk}"[^>]*>(검토자 )?{DELETED_NAME}', html)
    # 담당자로 다시 고를 수 없다
    r = client.post(f"/tasks/{t.pk}/meta", {"assignee": member.pk, "version": t.version})
    assert "맡길 수 없습니다" in r.content.decode()
