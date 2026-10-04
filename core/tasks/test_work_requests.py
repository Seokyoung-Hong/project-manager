import pytest
from django.utils import timezone

from accounts.models import User
from common.errors import ServiceError
from orgs.models import OrgMembership
from orgs.services import add_team_member, create_team, set_team_lead
from tasks import work_requests as wr
from tasks.models import Notice, WorkRequest
from tasks.services import create_task, update_task


@pytest.fixture
def mate(org):
    """디스코드를 연결한 두 번째 팀원."""
    u = User.objects.create_user(
        "mate",
        password="pw12345678",
        display_name="동료",
        discord_user_id="222",
        discord_linked_at=timezone.now(),
    )
    OrgMembership.objects.create(org=org, user=u, role="member")
    return u


@pytest.fixture
def squad(org, admin, member, mate):
    t = create_team(org=org, name="프론트", actor=admin)
    add_team_member(t, member, admin)
    add_team_member(t, mate, admin)
    return t


def _task(project, actor, assignee=None):
    return create_task(
        project=project,
        title="화면 고치기",
        actor=actor,
        assignee=assignee,
        source="web",
        no_due_reason="미정",
    )


def test_member_assigning_someone_else_becomes_request(project, member, mate):
    t = _task(project, member, assignee=mate)
    assert t.assignee == member  # 수락 전까지는 만든 사람이 맡는다
    req = WorkRequest.objects.get(kind="assign", task=t)
    assert (req.to_user, req.status) == (mate, "pending")
    assert Notice.objects.filter(user=mate).count() == 1

    wr.accept(req, mate, source="web")
    t.refresh_from_db()
    assert t.assignee == mate
    assert Notice.objects.filter(user=member).exists()  # 요청자에게 결과 알림


def test_decline_keeps_assignee(project, member, mate):
    t = _task(project, member)
    update_task(t, {"assignee": mate}, actor=member, source="web", expected_version=t.version)
    req = WorkRequest.objects.get(kind="assign", task=t)
    with pytest.raises(ServiceError):
        wr.accept(req, member, source="web")  # 받는 사람만 답한다
    wr.decline(req, mate, "이번 주는 어렵습니다")
    t.refresh_from_db()
    assert t.assignee == member
    assert WorkRequest.objects.get(pk=req.pk).status == "declined"


def test_team_lead_and_admin_assign_directly(project, admin, member, mate, squad):
    set_team_lead(squad, member, True, admin)
    t = _task(project, member, assignee=mate)
    assert t.assignee == mate
    assert not WorkRequest.objects.exists()
    note = Notice.objects.get(user=mate, text__contains="담당자로 지정")
    # 번호만이 아니라 프로젝트·제목·기한·상태·웹 링크가 다 있다.
    assert project.name in note.text and t.title in note.text
    assert f"/tasks/{t.pk}>)" in note.text
    assert note.text.endswith(" · 기한 없음 · 시작 전")

    t2 = _task(project, admin, assignee=member)
    assert t2.assignee == member


def test_lead_bypass_only_for_own_team(project, org, admin, member, mate, squad):
    other = User.objects.create_user("x", password="pw12345678", display_name="다른팀")
    OrgMembership.objects.create(org=org, user=other, role="member")
    set_team_lead(squad, member, True, admin)
    t = _task(project, member, assignee=other)
    assert t.assignee == member
    assert WorkRequest.objects.filter(to_user=other, kind="assign").exists()


def test_team_work_request_accept_creates_task(org, project, admin, member, mate, squad):
    req = wr.create_request(
        org=org,
        kind="work",
        title="로그인 화면 다크모드",
        body="디자인 링크 참고",
        actor=admin,
        source="web",
        team=squad,
    )
    # 팀 채널이 없으면 팀원에게 DM. member·mate 둘 다 연결돼 있다.
    assert Notice.objects.filter(user__in=[member, mate]).count() == 2
    with pytest.raises(ServiceError):
        wr.accept(req, mate, source="web")  # 프로젝트 필수
    req = wr.accept(req, mate, source="web", project=project)
    assert req.task.assignee == mate
    assert "REQ-" in req.task.description
    assert req.status == "accepted"


def test_team_request_goes_to_channel(org, admin, squad):
    squad.discord_channel_id = "999"
    squad.save()
    wr.create_request(org=org, kind="work", title="x", actor=admin, source="web", team=squad)
    assert Notice.objects.get().channel_id == "999"
    # 그 팀 채널에서 /요청을 쳤으면 봇이 이미 거기 답했다.
    wr.create_request(
        org=org, kind="work", title="y", actor=admin, source="dc", team=squad, posted_in="999"
    )
    assert Notice.objects.count() == 1
    # 다른 채널에서 팀을 골라 보냈으면 받는 팀 채널에 알린다.
    wr.create_request(
        org=org, kind="work", title="z", actor=admin, source="dc", team=squad, posted_in="123"
    )
    assert Notice.objects.filter(channel_id="999").count() == 2


def test_direct_assignment_cancels_stale_assign_request(project, admin, member, mate, squad):
    t = _task(project, member, assignee=mate)
    req = WorkRequest.objects.get(kind="assign")
    update_task(t, {"assignee": admin}, actor=admin, source="web", expected_version=t.version)
    req.refresh_from_db()
    assert req.status == "cancelled"
    with pytest.raises(ServiceError):
        wr.accept(req, mate, source="web")


def test_closing_task_cancels_assign_request(project, member, mate):
    from tasks.services import transition

    t = _task(project, member, assignee=mate)
    transition(t, "cancelled", actor=member, source="web", expected_version=t.version)
    assert WorkRequest.objects.get(kind="assign").status == "cancelled"


def test_github_import_follows_issue_assignee(project, member, mate):
    t = create_task(
        project=project,
        title="이슈",
        actor=member,
        assignee=mate,
        source="gh",
        no_due_reason="GitHub 이슈로 가져옴",
    )
    assert t.assignee == mate
    assert not WorkRequest.objects.exists()


def test_non_lead_accepting_for_teammate_sends_assign_request(
    org, project, admin, member, mate, squad
):
    req = wr.create_request(org=org, kind="work", title="x", actor=admin, source="web", team=squad)
    req = wr.accept(req, member, source="web", project=project, assignee=mate)
    assert req.task.assignee == member
    assert WorkRequest.objects.filter(kind="assign", to_user=mate, task=req.task).exists()


def test_general_request_lifecycle_and_visibility(org, admin, member, mate, outsider):
    req = wr.create_request(
        org=org, kind="general", title="PR 리뷰 부탁", actor=member, source="web", to_user=mate
    )
    assert wr.get_visible_request(mate, req.pk)
    assert wr.get_visible_request(admin, req.pk)  # 조직 관리자
    assert wr.get_visible_request(outsider, req.pk) is None
    with pytest.raises(ServiceError):
        wr.complete(req, mate)  # 수락 전
    wr.accept(req, mate, source="web")
    req = wr.complete(req, mate, "머지했습니다")
    assert req.status == "done"
    with pytest.raises(ServiceError):
        wr.cancel(req, member)


def test_create_request_validation(org, member, outsider, squad):
    with pytest.raises(ServiceError):
        wr.create_request(org=org, kind="work", title="x", actor=outsider, source="web", team=squad)
    with pytest.raises(ServiceError):
        wr.create_request(org=org, kind="work", title="x", actor=member, source="web")
    with pytest.raises(ServiceError):
        wr.create_request(
            org=org, kind="work", title="x", actor=member, source="web", to_user=member
        )
    with pytest.raises(ServiceError):
        wr.create_request(org=org, kind="assign", title="x", actor=member, source="web", team=squad)


def test_notice_skipped_without_discord(org, admin, member):
    wr.create_request(org=org, kind="general", title="x", actor=member, source="web", to_user=admin)
    assert not Notice.objects.exists()  # admin은 Discord 미연결


def test_pending_and_mark_sent(project, member, mate):
    _task(project, member, assignee=mate)
    ids = [n.pk for n in wr.pending_notices()]
    assert wr.mark_sent(ids) == 1
    assert wr.pending_notices() == []


def test_same_request_within_window_is_not_duplicated(org, member, mate):
    """AI가 키 없이 재시도해도 같은 요청이 두 번 가지 않는다(알림도 한 번)."""
    kw = dict(org=org, kind="general", title="리뷰", actor=member, source="mcp", to_user=mate)
    a = wr.create_request(**kw)
    b = wr.create_request(**kw)
    assert a.pk == b.pk
    assert Notice.objects.filter(user=mate).count() == 1
    wr.cancel(a, member)
    assert wr.create_request(**kw).pk != a.pk  # 처리된 뒤에는 다시 보낼 수 있다
