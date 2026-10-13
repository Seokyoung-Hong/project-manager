"""사람별 초대(가입 전 구성원 인계)."""

import pytest
from django.utils import timezone

from accounts.models import User
from common.errors import ServiceError
from github.models import GitHubIdentity
from github.services import login_with_github
from tasks.models import ChangeLog
from tasks.services import create_task

from .models import Invite, OrgMembership
from .services import (
    add_pending_member,
    create_invite,
    create_personal_invite,
    is_member,
    is_pending,
    join_by_token,
)

pytestmark = pytest.mark.django_db

PW = "Udally-pass-2026!"


@pytest.fixture
def pending(org, admin):
    return add_pending_member(org, admin, " 김신입 ")


def _signup(client, token, username="kim.new"):
    return client.post(
        f"/join/{token}",
        {
            "username": username,
            "real_name": "김신입",
            "display_name": "김신입(본인)",
            "password1": PW,
            "password2": PW,
            "age_ok": "on",
        },
    )


def test_add_pending_member_and_judgement(org, admin, member, pending):
    user = pending.user
    assert user.display_name == "김신입" and is_member(user, org) and pending.role == "member"
    assert is_pending(user) and not is_pending(member)
    # 셸로 만든 계정(비밀번호 없음·GitHub 없음·로그인 기록 없음)도 가입 전이다
    shell = User(username="shell1")
    shell.set_unusable_password()
    shell.save()
    assert is_pending(shell)
    assert ChangeLog.objects.filter(
        target_type="org", target_id=org.pk, field="member_add_pending"
    ).exists()
    with pytest.raises(ServiceError):
        add_pending_member(org, admin, "  ")


def test_non_admin_rejected(org, member, pending):
    with pytest.raises(ServiceError):
        add_pending_member(org, member, "누구")
    with pytest.raises(ServiceError):
        create_personal_invite(pending, member)


def test_teams_screen_shows_pending_and_creates_link(client, org, admin, pending):
    client.force_login(admin)
    page = client.get(f"/orgs/{org.pk}/teams").content.decode()
    assert "가입 전" in page and "초대 링크 만들기" in page
    client.post(f"/orgs/{org.pk}/members/pending", {"display_name": "박예비"})
    assert OrgMembership.objects.filter(org=org, user__display_name="박예비").exists()
    client.post(f"/orgs/memberships/{pending.pk}/invite")
    invite = Invite.objects.get(for_user=pending.user)
    page = client.get(f"/orgs/{org.pk}/teams").content.decode()
    assert invite.path in page
    # 사람별 링크는 조직 초대 링크 표에 섞이지 않는다
    assert "초대 링크가 없습니다." in page


def test_reissue_revokes_previous(org, admin, pending):
    first = create_personal_invite(pending, admin)
    second = create_personal_invite(pending, admin)
    first.refresh_from_db()
    assert first.revoked_at is not None and second.revoked_at is None
    assert second.max_uses == 1
    assert ChangeLog.objects.filter(target_id=org.pk, field="invite_personal").count() == 2


def test_claim_keeps_account_and_logs_in(client, org, admin, project, pending):
    task = create_task(
        project=project,
        title="인계 대상",
        actor=admin,
        source="web",
        assignee=pending.user,
        no_due_reason="테스트",
    )
    invite = create_personal_invite(pending, admin)
    page = client.get(f"/join/{invite.token}").content.decode()
    assert "김신입" in page and "초대 링크로 가입" in page
    res = _signup(client, invite.token)
    assert res.status_code == 302
    user = User.objects.get(pk=pending.user_id)
    assert user.username == "kim.new" and user.display_name == "김신입(본인)"
    assert user.check_password(PW) and not is_pending(user)
    task.refresh_from_db()
    assert task.assignee_id == user.pk
    assert int(client.session["_auth_user_id"]) == user.pk
    # 세션이 살아 있고, 인계 때 받은 실명으로 관문 없이 조직 화면이 열린다
    assert user.real_name == "김신입"
    assert client.get(f"/orgs/{org.pk}").status_code == 200
    invite.refresh_from_db()
    assert invite.use_count == 1
    assert ChangeLog.objects.filter(target_id=org.pk, field="invite_claimed").exists()
    assert User.objects.count() == 3  # 새 계정이 생기지 않았다(관리자·팀원·가입 전)


def test_claim_rejected_when_used_expired_revoked(client, org, admin, pending):
    invite = create_personal_invite(pending, admin)
    _signup(client, invite.token)
    client.logout()
    res = _signup(client, invite.token, username="again")
    assert res.status_code == 200 and not User.objects.filter(username="again").exists()

    other = add_pending_member(org, admin, "이예비")
    expired = create_personal_invite(other, admin)
    expired.expires_at = timezone.now() - timezone.timedelta(days=1)
    expired.save(update_fields=["expires_at"])
    _signup(client, expired.token, username="exp")
    old = Invite.objects.get(pk=expired.pk)
    create_personal_invite(other, admin)  # 다시 만들면 이전 링크는 취소
    _signup(client, old.token, username="rev")
    assert not User.objects.filter(username__in=["exp", "rev"]).exists()
    assert is_pending(other.user)


def test_already_joined_user_rejected(client, org, admin, pending):
    invite = create_personal_invite(pending, admin)
    user = pending.user
    user.set_password(PW)
    user.save()  # 운영자 재설정 링크 등으로 이미 계정을 쓰기 시작했다
    with pytest.raises(ServiceError):
        create_personal_invite(pending, admin)
    _signup(client, invite.token, username="hijack")
    assert not User.objects.filter(username="hijack").exists()


def test_logged_in_other_account_rejected(client, org, admin, outsider, pending):
    invite = create_personal_invite(pending, admin)
    client.force_login(outsider)
    page = client.get(f"/join/{invite.token}").content.decode()
    assert "새 계정용" in page
    _signup(client, invite.token, username="merge")
    with pytest.raises(ServiceError):
        join_by_token(outsider, invite.token)
    assert not is_member(outsider, org) and is_pending(pending.user)


def test_github_claim_attaches_identity(org, admin, pending):
    invite = create_personal_invite(pending, admin)
    identity, created = login_with_github({"id": 777, "login": "kimgh"}, {}, claim=invite.token)
    assert identity.user_id == pending.user_id and created
    assert User.objects.count() == 3 and not is_pending(identity.user)
    # 같은 링크로 다른 GitHub 계정은 넘겨받지 못한다
    with pytest.raises(ServiceError):
        login_with_github({"id": 778, "login": "other"}, {}, claim=invite.token)
    assert not GitHubIdentity.objects.filter(github_id=778).exists()


def test_general_invite_unchanged(org, admin, outsider):
    invite = create_invite(org, admin)
    join_by_token(outsider, invite.token)
    invite.refresh_from_db()
    assert is_member(outsider, org) and invite.use_count == 1
