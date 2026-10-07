"""IMPL-PLAN-12 G2: 상위·하위 태스크 웹 화면 — 패널 칸·행 표시·목록 묶음·보드 막대·나누기 문구."""

import re
from datetime import timedelta

import pytest
from django.db import connection
from django.test.utils import CaptureQueriesContext

from accounts.models import User
from common.dates import today_kst
from orgs.models import OrgMembership
from orgs.services import add_team_member, create_team
from projects.services import create_project
from tasks import services as ts
from tasks.models import Task

pytestmark = pytest.mark.django_db
HX = {"HX-Request": "true"}


def _t(project, actor, title="일", **kw):
    kw.setdefault("due_date", today_kst() + timedelta(days=5))
    return ts.create_task(project=project, title=title, actor=actor, source="web", **kw)


def _panel(client, task) -> str:
    return client.get(f"/tasks/{task.pk}/panel").content.decode()


def _close(task, actor, status="done"):
    task.refresh_from_db()
    ts.transition(task, status, actor=actor, source="web", expected_version=task.version)


@pytest.fixture
def logged(client, member):
    client.force_login(member)
    return client


def test_panel_create_put_ungroup(logged, project, member):
    top = _t(project, member, "행사 준비")
    html = _panel(logged, top)
    assert 'id="task-subtasks"' in html and "하위 태스크 0/0" in html and "하위 만들기" in html
    r = logged.post(
        f"/tasks/{top.pk}/subtasks",
        {"title": "장소 섭외", "assignee": member.pk, "due_date": top.due_date.isoformat()},
        headers=HX,
    )
    body = r.content.decode()
    assert r.status_code == 200 and "하위 태스크를 만들었습니다." in body and "장소 섭외" in body
    assert "task-changed" in r["HX-Trigger"]
    sub = Task.objects.get(group=top)
    other = _t(project, member, "포스터")
    assert f'<option value="{other.pk}">' in _panel(logged, top)  # 넣기 후보
    body = logged.post(f"/tasks/{top.pk}/group", {"task": other.pk}, headers=HX).content.decode()
    assert f"{other.number}을 하위로 넣었습니다." in body and "하위 태스크 0/2" in body
    # 하위 패널: 상위 줄 + 떼어내기, 나누기 버튼 없음(한 겹)
    html = _panel(logged, sub)
    assert f"{top.number} 행사 준비" in html and "사람별로 나누기" not in html
    assert 'id="task-subtasks"' not in html
    sub.refresh_from_db()
    body = logged.post(
        f"/tasks/{sub.pk}/ungroup", {"version": sub.version}, headers=HX
    ).content.decode()
    assert "떼어냈습니다." in body
    sub.refresh_from_db()
    assert sub.group_id is None
    # 상위 패널의 하위 행에서 떼어내기(back=상위)
    other.refresh_from_db()
    body = logged.post(
        f"/tasks/{other.pk}/ungroup", {"version": other.version, "back": top.pk}, headers=HX
    ).content.decode()
    assert "하위 태스크 0/0" in body and not Task.objects.filter(group=top).exists()


def test_panel_one_level_error_shown(logged, project, member):
    top = _t(project, member, "상위")
    sub = _t(project, member, group=top)
    child = _t(project, member, "또")
    body = logged.post(f"/tasks/{sub.pk}/group", {"task": child.pk}, headers=HX).content.decode()
    assert ts.ONE_LEVEL in body


def test_panel_suggest_done_and_refusal(logged, project, member):
    top = _t(project, member, "상위")
    a = _t(project, member, "가", group=top)
    # 열린 하위가 있으면 상위 완료가 거절되고 문구가 패널에 보인다.
    body = logged.post(
        f"/tasks/{top.pk}/status",
        {"status": "done", "version": top.version, "from": "panel"},
        headers=HX,
    ).content.decode()
    assert "하위 태스크 1건이 아직 열려 있습니다" in body
    _close(a, member)
    html = _panel(logged, top)
    assert "하위 태스크가 모두 끝났습니다. 상위를 완료로 표시해 주세요." in html
    assert "완료로 표시" in html and "하위 태스크 1/1" in html


def test_due_warning(logged, project, member):
    top = _t(project, member, "상위", due_date=today_kst() + timedelta(days=2))
    sub = _t(project, member, group=top, due_date=today_kst() + timedelta(days=9))
    assert f"⚠ 목표일이 상위 {top.number}(" in _panel(logged, sub)
    assert "상위 기한 초과" in _panel(logged, top)


def test_hidden_group_and_subtasks(client, org, admin, member):
    team = create_team(org=org, name="비밀", actor=admin)
    add_team_member(team, member, admin)
    secret = create_project(
        org=org, name="비공개", actor=admin, owners=[admin], teams=[team], visibility="teams"
    )
    public = create_project(org=org, name="공개", actor=admin)
    viewer = User.objects.create_user("vw", password="pw12345678", display_name="바깥")
    OrgMembership.objects.create(org=org, user=viewer, role="member")
    top = _t(secret, member, "비밀 상위")
    sub = _t(secret, member, "하위 일", group=top)
    ts.approve_link(ts.link_project(sub, public, actor=member, confirm_widening=True), actor=admin)
    client.force_login(viewer)
    html = _panel(client, sub)
    assert "비밀 상위" not in html and top.number not in html
    row = client.get(f"/projects/{public.pk}?view=list").content.decode()
    assert "↳" not in row and "하위 일" in row
    # 상위만 보이는 경우: 못 보는 하위 수
    sub2 = _t(secret, member, "둘", group=top)
    assert sub2.pk
    ts.unlink_project(sub, public, actor=member)
    ts.approve_link(ts.link_project(top, public, actor=member, confirm_widening=True), actor=admin)
    html = _panel(client, top)
    assert "볼 수 없는 하위 2건" in html and "하위 일" not in html


def test_project_list_nests_and_board_bar(logged, project, member):
    late = _t(project, member, "늦은 상위", due_date=today_kst() + timedelta(days=9))
    early = _t(project, member, "이른 일", due_date=today_kst() + timedelta(days=1))
    sub = _t(project, member, "하위 일", group=late, due_date=today_kst() + timedelta(days=3))
    html = logged.get(f"/projects/{project.pk}?view=list").content.decode()
    order = [m for m in re.findall(r'id="task-(\d+)"', html)]
    assert order == [str(early.pk), str(late.pk), str(sub.pk)]  # 하위는 상위 바로 뒤
    assert f'data-group="{late.pk}"' in html and "task-row" in html and ' sub"' in html
    assert 'data-action="toggle-subtasks"' in html and "하위 0/1" in html
    assert f"↳ {late.number}" in html
    # 행 자기 갱신도 같은 모양(opts=sub)
    row = logged.get(f"/tasks/{sub.pk}/row?opts=sub").content.decode()
    assert f'data-group="{late.pk}"' in row
    board = logged.get(f"/projects/{project.pk}?view=board").content.decode()
    assert 'aria-label="하위 0% 완료"' in board and "toggle-subtasks" not in board


def test_project_list_query_count_flat(logged, project, member):
    def count():
        with CaptureQueriesContext(connection) as q:
            assert logged.get(f"/projects/{project.pk}?view=list").status_code == 200
        return len(q)

    top = _t(project, member, "상위0")
    _t(project, member, group=top)
    small = count()
    for i in range(4):
        _t(project, member, group=_t(project, member, f"상위{i + 1}"))
    assert count() == small


def test_split_dialog_and_toast(logged, project, member, org):
    a = User.objects.create_user("p1", password="pw12345678", display_name="김철수")
    b = User.objects.create_user("p2", password="pw12345678", display_name="이영희")
    for u in (a, b):
        OrgMembership.objects.create(org=org, user=u, role="member")
    t = _t(project, member, "로그인 개선")
    html = logged.get(f"/tasks/{t.pk}/split", headers=HX).content.decode()
    assert "하위 태스크를 만듭니다" in html and "계열" not in html
    logged.post(f"/tasks/{t.pk}/split", {"assignee": [a.pk, b.pk]}, headers=HX)
    page = logged.get(f"/tasks/{t.pk}").content.decode()
    assert "하위 태스크 2건을 만들었습니다." in page and "하위 태스크 0/2" in page
