"""IMPL-PLAN-11 §2(S1): 담당자 1명 고정 · 감지 · 사람별로 나누기."""

from datetime import timedelta

import pytest

from accounts.models import User
from common.dates import today_kst
from common.errors import ServiceError
from github.models import RepoConnection, TaskGitLink
from orgs.models import OrgMembership
from orgs.services import add_team_member, create_team
from projects.services import create_project
from tasks import services as ts
from tasks.models import ChangeLog, Task, TaskProject
from tasks.split import looks_multi_assignee, split_by_assignees

pytestmark = pytest.mark.django_db


def _user(org, name, active=True):
    u = User.objects.create_user(
        f"u{User.objects.count()}", password="pw12345678", display_name=name
    )
    OrgMembership.objects.create(org=org, user=u, role="member")
    if not active:
        User.objects.filter(pk=u.pk).update(is_active=False)
        u.refresh_from_db()
    return u


@pytest.fixture
def people(org):
    return [_user(org, "김철수"), _user(org, "이영희"), _user(org, "박민수")]


# ---------- 감지 ----------


def test_detect_two_names(org, people):
    got = looks_multi_assignee("이영희와 김철수 로그인 개선", "", org)
    assert [u.display_name for u in got] == ["이영희", "김철수"]  # 등장 순서
    assert [u.display_name for u in looks_multi_assignee("로그인", "박민수, 김철수 담당", org)] == [
        "박민수",
        "김철수",
    ]


def test_detect_one_name_or_keyword_only(org, people):
    assert looks_multi_assignee("김철수 로그인 개선", "", org) == []
    assert looks_multi_assignee("같이 함께 공동으로 전원 참여", "", org) == []


def test_detect_ignores_inactive_member(org, people):
    _user(org, "최비활", active=False)
    assert looks_multi_assignee("김철수와 최비활", "", org) == []


# ---------- 나누기 ----------


def _task(project, member, **kw):
    kw.setdefault("due_date", today_kst() + timedelta(days=5))
    return ts.create_task(project=project, title="로그인 개선", actor=member, source="web", **kw)


def test_split_three(project, member, people, admin):
    t = _task(project, member, description="본문", done_when="끝")
    ts.checklist_add(t, "스펙 확인", actor=member)
    t.refresh_from_db()
    out = split_by_assignees(t, people, actor=member, source="web", roles={people[0].pk: "백엔드"})
    assert len(out) == 3
    assert [n.assignee_id for n in out] == [u.pk for u in people] or any(
        n.assignee_id == member.pk
        for n in out  # 담당 요청 규칙(받을 사람이 수락 전이면 만든 사람)
    )
    assert [n.title for n in out][0] == "로그인 개선 — 김철수 (백엔드)"
    assert [n.title for n in out][1] == "로그인 개선 — 이영희"
    for n in out:
        assert n.parent_id == t.pk
        assert n.due_date == t.due_date
        assert n.description == "본문" and n.done_when == "끝"
        assert [c.text for c in n.checklist.all()] == ["스펙 확인"]
        assert not n.checklist.filter(is_done=True).exists()
    t.refresh_from_db()
    # 원본은 지우거나 취소하지 않고, 체크리스트가 만든 태스크 목록으로 바뀐다.
    assert t.status == "todo" and t.parent_id is None
    assert [c.text for c in t.checklist.all()] == [f"{n.number} {n.title}" for n in out]
    assert "사람별로 나눴습니다" in t.notes and out[0].number in t.notes
    log = ChangeLog.objects.get(target_id=t.pk, field="split")
    assert log.new_value == ",".join(n.number for n in out)


def test_split_counts(project, member, people):
    t = _task(project, member)
    with pytest.raises(ServiceError):
        split_by_assignees(t, people[:1], actor=member, source="web")
    with pytest.raises(ServiceError):
        split_by_assignees(t, [people[0], people[0]], actor=member, source="web")  # 중복 = 1명
    org = project.org
    many = people + [_user(org, f"사람{i}") for i in range(8)]  # 11명
    with pytest.raises(ServiceError):
        split_by_assignees(t, many, actor=member, source="web")
    assert Task.objects.filter(parent=t).count() == 0


def test_split_rejects_bad_pattern_and_outsider(project, member, people, outsider):
    t = _task(project, member)
    with pytest.raises(ServiceError):
        split_by_assignees(t, people, actor=member, source="web", title_pattern="{title}")
    with pytest.raises(ServiceError):
        split_by_assignees(t, people, actor=member, source="web", title_pattern="{x} {name}")
    with pytest.raises(ServiceError):
        split_by_assignees(t, [people[0], outsider], actor=member, source="web")
    assert Task.objects.filter(parent=t).count() == 0


def test_split_without_due_date_follows_reason(project, member, people):
    t = _task(project, member, due_date=None, no_due_reason="미정")
    out = split_by_assignees(t, people[:2], actor=member, source="web")
    assert all(n.due_date is None and n.no_due_reason == "미정" for n in out)


def test_split_does_not_copy_git_link(project, member, people):
    t = _task(project, member)
    conn = RepoConnection.objects.create(
        project=project, url="https://github.com/o/r.git", full_name="o/r", created_by=member
    )
    TaskGitLink.objects.create(task=t, connection=conn, branch="feat/x")
    out = split_by_assignees(t, people[:2], actor=member, source="web")
    assert not TaskGitLink.objects.filter(task__in=out).exists()


def test_split_copies_active_links_only(org, admin, member):
    """다중 프로젝트 연결 태스크: 확정 연결은 복사(같은 열람자 집합), 승인 대기는 복사하지 않는다."""
    outside = _user(org, "바깥사람")  # 공개 프로젝트만 보는 사람 — 연결이 열람 확대가 된다
    team = create_team(org=org, name="비밀팀", actor=admin)
    add_team_member(team, member, admin)
    secret = create_project(
        org=org, name="비공개", actor=admin, owners=[admin], teams=[team], visibility="teams"
    )
    public = create_project(org=org, name="공개", actor=admin)
    team2 = create_team(org=org, name="다른팀", actor=admin)
    add_team_member(team2, _user(org, "둘째팀원"), admin)
    add_team_member(team2, member, admin)
    other_secret = create_project(
        org=org, name="비공개2", actor=admin, owners=[admin], teams=[team2], visibility="teams"
    )
    t = ts.create_task(project=secret, title="일", actor=member, source="web", no_due_reason="-")
    pending = ts.link_project(t, other_secret, actor=member, confirm_widening=True)
    assert pending.status == "pending"  # 승인 대기
    ts.approve_link(ts.link_project(t, public, actor=member, confirm_widening=True), actor=admin)
    out = split_by_assignees(t, [admin, member], actor=member, source="web")
    for n in out:
        assert n.project_id == secret.pk
        links = list(TaskProject.objects.filter(task=n).values_list("project_id", "status"))
        assert links == [(public.pk, "active")]
    # 비공개 프로젝트에서 못 보는 사람은 담당이 될 수 없다(거절, 아무것도 안 만든다).
    with pytest.raises(ServiceError):
        split_by_assignees(t, [admin, outside], actor=member, source="web")
    assert Task.objects.filter(parent=t).count() == 2


def test_split_template_refused(project, member, people):
    t = _task(project, member)
    ts.set_template(t, True, actor=member)
    t.refresh_from_db()
    with pytest.raises(ServiceError):
        split_by_assignees(t, people, actor=member, source="web")


# ---------- API ----------


def test_api_assignee_ids_400(api, project, member):
    r = api.post(
        "/api/tasks",
        {"project_id": project.pk, "title": "t", "no_due_reason": "-", "assignee_ids": [1, 2]},
    )
    assert r.status_code == 400 and "split" in r.json()["detail"]["assignee_ids"]
    assert "담당자는 한 명입니다" in r.json()["detail"]["assignee_ids"]
    t = _task(project, member)
    r = api.patch(f"/api/tasks/{t.pk}", {"version": t.version, "assignee_ids": [1, 2]})
    assert r.status_code == 400 and "담당자는 한 명입니다" in r.json()["detail"]["assignee_ids"]


def test_api_split(api, project, member, people):
    t = _task(project, member)
    body = {"assignee_ids": [u.pk for u in people], "roles": {str(people[0].pk): "디자인"}}
    h = {"Idempotency-Key": "sp-1"}
    r1 = api.post(f"/api/tasks/{t.pk}/split", body, headers=h)
    assert r1.status_code == 201
    got = r1.json()["tasks"]
    assert len(got) == 3 and all(x["parent_id"] == t.pk for x in got)
    assert got[0]["title"].endswith("김철수 (디자인)")
    r2 = api.post(f"/api/tasks/{t.pk}/split", body, headers=h)  # 재시도는 중복을 만들지 않는다
    assert r2.status_code == 201
    assert [x["id"] for x in r2.json()["tasks"]] == [x["id"] for x in got]
    assert Task.objects.filter(parent=t).count() == 3


def test_api_split_errors(api, project, member, people):
    t = _task(project, member)
    r = api.post(f"/api/tasks/{t.pk}/split", {"assignee_ids": [people[0].pk]})
    assert r.status_code == 400
    r = api.post(f"/api/tasks/{t.pk}/split", {"assignee_ids": [people[0].pk, 99999]})
    assert r.status_code == 400
    assert api.post("/api/tasks/99999/split", {"assignee_ids": [1, 2]}).status_code == 404


# ---------- 웹 ----------


def test_web_panel_hint_and_split_dialog(client, project, member, people, org):
    client.force_login(member)
    t = _task(project, member, description="김철수와 이영희가 함께 합니다")
    r = client.get(f"/tasks/{t.pk}/panel")
    html = r.content.decode()
    assert "여러 사람이 맡는 것처럼 보입니다" in html and "사람별로 나누기" in html
    plain = _task(project, member)
    assert "여러 사람이 맡는 것처럼" not in client.get(f"/tasks/{plain.pk}/panel").content.decode()
    r = client.get(f"/tasks/{t.pk}/split", headers={"HX-Request": "true"})
    html = r.content.decode()
    assert r.status_code == 200 and "맡을 사람" in html
    # 판정된 사람이 미리 체크된다.
    assert html.count(" checked") == 2
    r = client.post(
        f"/tasks/{t.pk}/split",
        {
            "assignee": [people[0].pk, people[1].pk],
            f"role_{people[0].pk}": "서버",
            "title_pattern": "{title}/{name}",
        },
        headers={"HX-Request": "true"},
    )
    assert r.status_code == 204 and r["HX-Redirect"] == f"/tasks/{t.pk}"
    assert sorted(Task.objects.filter(parent=t).values_list("title", flat=True)) == [
        "로그인 개선/김철수 (서버)",
        "로그인 개선/이영희",
    ]
    # 1명만 고르면 대화상자에 오류를 보인다.
    r = client.post(
        f"/tasks/{plain.pk}/split", {"assignee": [people[0].pk]}, headers={"HX-Request": "true"}
    )
    assert r.status_code == 200 and "2명 이상" in r.content.decode()
