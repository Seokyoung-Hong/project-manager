"""매일 쓰는 화면 검토(design-review/b-workspace.md) 수정의 회귀 검사. 바꾼 동작마다 하나씩."""

import json
import re
from datetime import timedelta
from pathlib import Path

import pytest

from accounts.models import User
from common.dates import today_kst
from orgs.models import OrgMembership
from orgs.services import create_org
from projects.services import create_project
from tasks.models import Task
from tasks.services import create_task

HX = {"HX-Request": "true"}
TEMPLATES = Path(__file__).parent / "templates"


@pytest.fixture
def logged(client, member):
    client.login(username="member1", password="pw12345678")
    return client


@pytest.fixture
def as_admin(client, org):
    client.login(username="admin1", password="pw12345678")
    return client


def _with_due_days(org, days=3):
    org.settings = {**(org.settings or {}), "task.default_due_days": days}
    org.save()


# ---------- 오늘 화면(중-4, 중-5, 상-2) ----------


def test_today_h1_is_the_screen_not_the_slogan(logged, task):
    body = logged.get("/today").content.decode()
    h1 = re.search(r"<h1[^>]*>(.*?)</h1>", body, re.S).group(1)
    assert h1.startswith("오늘 · ")
    assert '<p class="hero-title">일은 차근차근' in body
    assert "직접 추가한 순서" not in body  # 정렬 설명은 지웠다


def test_today_auto_pull_setting_is_folded_into_one_line(logged, task, member):
    member.auto_pull_days = 5
    member.save()
    body = logged.get("/today").content.decode()
    assert "기한이 5일 안인 태스크 1건을 자동으로 담았습니다." in body
    assert 'name="auto_pull_days"' not in body  # 설정은 환경설정 화면에 있다(중-5)
    assert "/settings/preferences#setting-auto_pull_days" in body


def test_auto_pull_setting_lives_in_preferences(logged, member):
    body = logged.get("/settings/preferences").content.decode()
    assert 'id="setting-auto_pull_days"' in body
    logged.post("/settings/preferences", {"auto_pull_days": "3"})
    member.refresh_from_db()
    assert member.auto_pull_days == 3
    logged.post("/settings/preferences", {"auto_pull_days": "4"})  # 고를 수 없는 값은 거절
    member.refresh_from_db()
    assert member.auto_pull_days == 3


def test_today_empty_without_org_points_to_org_creation(client, db):
    User.objects.create_user("lonely", password="pw12345678", display_name="혼자")
    client.login(username="lonely", password="pw12345678")
    body = client.get("/today").content.decode()
    assert "아직 속한 조직이 없습니다." in body and 'href="/orgs/new"' in body


def test_today_empty_without_project_admin_vs_member(client, admin, member):
    org = create_org("빈 조직", "", admin)
    OrgMembership.objects.create(org=org, user=member, role="member")
    client.login(username="admin1", password="pw12345678")
    body = client.get("/today").content.decode()
    assert "첫 프로젝트 만들기" in body
    client.login(username="member1", password="pw12345678")
    body = client.get("/today").content.decode()
    assert "관리자가 프로젝트를 만들면 여기에 표시됩니다." in body
    assert "첫 프로젝트 만들기" not in body


def test_today_empty_without_tasks_offers_task_creation(logged, project):
    body = logged.get("/today").content.decode()
    assert "맡은 태스크가 없습니다." in body and 'data-target="#quick"' in body


def test_head_done_offers_undo(logged, task):
    task.status = "doing"
    task.save()
    r = logged.post(
        f"/tasks/{task.pk}/status",
        {"status": "done", "version": task.version, "from": "head"},
        headers=HX,
    )
    info = json.loads(r.headers["HX-Trigger"])["task-updated"]
    assert info["undo_status"] == "doing" and info["version"] > task.version


# ---------- 빠른 추가·생성 폼 기본값(상-1, 중-6, 시스템화 D) ----------


def test_quick_add_dialog_defaults_to_viewed_project_and_suggested_due(logged, org, project, admin):
    _with_due_days(org)
    other = create_project(org=org, name="가나다 첫 프로젝트", actor=admin, owners=[admin])
    r = logged.get(f"/today/quick?project={project.pk}", headers=HX)
    body = r.content.decode()
    assert f'<option value="{project.pk}" data-due-suggestion="' in body
    assert re.search(rf'<option value="{project.pk}"[^>]*selected', body)
    assert not re.search(rf'<option value="{other.pk}"[^>]*selected', body)
    assert re.search(r'name="due_date" value="\d{4}-\d{2}-\d{2}"', body)
    assert 'id="quick-nodue" data-nodue hidden' in body
    assert 'name="in_dialog" value="1"' in body


def test_quick_add_in_dialog_returns_to_current_page_and_remembers_project(logged, project):
    data = {
        "title": "대화상자에서 만든 일",
        "project": project.pk,
        "priority": 5,
        "due_date": (today_kst() + timedelta(days=1)).isoformat(),
        "in_dialog": "1",
    }
    headers = {**HX, "HX-Current-URL": f"http://testserver/projects/{project.pk}?view=board"}
    r = logged.post("/today/quick", data, headers=headers)
    assert r.headers["HX-Redirect"] == f"/projects/{project.pk}?view=board"
    assert logged.session["quick_project"] == project.pk
    body = logged.get("/today/quick", headers=HX).content.decode()
    assert re.search(rf'<option value="{project.pk}"[^>]*selected', body)


def test_project_task_form_prefills_suggested_due(logged, org, project):
    _with_due_days(org)
    body = logged.get(f"/projects/{project.pk}?view=list").content.decode()
    form = body[body.index('id="task-form"') :]
    assert re.search(r'name="due_date" value="\d{4}-\d{2}-\d{2}"', form)
    assert "기한 없이 만들기" in form and 'id="task-nodue" data-nodue hidden' in form


def test_subtask_form_defaults_to_me(logged, task, member, admin):
    task.assignee = admin
    task.save()
    body = logged.get(f"/tasks/{task.pk}/panel", headers=HX).content.decode()
    sub = body[body.index('id="sub-add-') :]
    assert f'<option value="{member.pk}" selected>나 (' in sub


# ---------- 태스크 행 맥락(중-3, 시스템화 A) ----------


def test_project_rows_hide_project_name_and_board_has_no_status_select(logged, project, task):
    body = logged.get(f"/projects/{project.pk}?view=list").content.decode()
    row = body[body.index(f'id="task-{task.pk}"') :]
    assert f'<div class="proj">{project.name}' not in row.split("</li>")[0]
    board = logged.get(f"/projects/{project.pk}?view=board").content.decode()
    card = board[board.index(f'id="task-{task.pk}"') :].split("</li>")[0]
    assert 'name="status"' not in card


def test_auto_mark_only_on_today(logged, task, member):
    member.auto_pull_days = 5
    member.save()
    assert "자동 추가</span>" in logged.get("/today").content.decode()
    assert "자동 추가</span>" not in logged.get("/me").content.decode()


# ---------- 태스크 패널(상-3, 중-1, 중-10, 중-12, A2) ----------


def test_panel_daily_fields_first_and_rare_ones_folded(logged, task):
    body = logged.get(f"/tasks/{task.pk}/panel", headers=HX).content.decode()
    # 매일 쓰는 칸이 접힌 묶음보다 먼저 나온다
    assert body.index("다음 행동") < body.index('class="stack panel-folds"')
    assert body.index("진행 메모") < body.index('id="task-projects"')
    # 기한은 한 곳에만, 보이는 라벨과 함께
    assert body.count("기한 연장하기") == 1 and ">기한</span>" in body
    # 저장 안내 문단은 없고 막대의 표시만 남는다
    assert "저장 완료 표시를 확인해 주세요" not in body
    # 하위 만들기 폼은 [하위 태스크 추가]를 눌러야 펼친다
    assert re.search(r'id="sub-add-\d+" class="stack" hidden', body)


def test_panel_pickers_start_empty(logged, task, org, admin):
    create_project(org=org, name="다른 프로젝트", actor=admin, owners=[admin])
    create_task(
        project=task.project, title="넣을 후보", actor=admin, source="web", no_due_reason="미정"
    )
    body = logged.get(f"/tasks/{task.pk}/panel", headers=HX).content.decode()
    assert '<option value="">프로젝트 고르기…</option>' in body
    assert '<option value="">태스크 고르기…</option>' in body
    r = logged.post(f"/tasks/{task.pk}/projects", {"project": ""}, headers=HX)
    assert "연결할 프로젝트를 선택해 주세요." in r.content.decode()


def test_stop_box_buttons_do_not_say_cancel(logged, task):
    body = logged.get(f"/tasks/{task.pk}/panel?block=1", headers=HX).content.decode()
    box = body[body.index('for="stop-reason-') :].split("</form>")[0]
    assert "막힘 사유" in box and "막힘으로 바꾸지 않기" in box
    assert ">취소</button>" not in box


# ---------- 빈 상태 부품(시스템화 C) ----------


def test_me_with_no_tasks_hides_filters_and_shows_one_action(logged, project):
    body = logged.get("/me").content.decode()
    assert "담당 중인 미완료 태스크가 없습니다." in body
    assert re.search(r'<form id="me-filter"[^>]*hidden', body)
    assert "결과 없음" not in body


def test_requests_empty_explains_what_requests_are(logged, org):
    body = logged.get("/requests").content.decode()
    assert "다른 사람이 보낸 작업·검토 요청을 여기서 확인할 수 있습니다." in body
    assert "<th>요청</th>" not in body


def test_projects_empty_for_member_is_not_a_dead_end(client, admin, member):
    org = create_org("빈 조직", "", admin)
    OrgMembership.objects.create(org=org, user=member, role="member")
    client.login(username="member1", password="pw12345678")
    session = client.session
    session["org_id"] = org.pk
    session.save()
    body = client.get("/projects", follow=True).content.decode()
    assert "관리자가 프로젝트를 만들면 여기에 표시됩니다." in body
    assert "＋ 새 프로젝트" not in body  # 레일의 같은 버튼도 숨긴다


def test_portfolio_hides_org_picker_and_prompt_button_when_nothing_to_pick(logged, org):
    body = logged.get("/portfolio").content.decode()
    assert 'name="org" onchange' not in body
    assert "아직 결정 기록이 없습니다." in body
    assert "AI 요청문 만들기" not in body


# ---------- 보드·주소 직접 열기·주 버튼(중-9, 하-6, 중-2, 시스템화 E) ----------


def test_board_warns_about_blocked_tasks(logged, project, task):
    Task.objects.filter(pk=task.pk).update(status="blocked", stop_reason="외부 승인")
    body = logged.get(f"/projects/{project.pk}?view=board").content.decode()
    assert "막힌 태스크가 1건 있습니다." in body and 'href="#board-col-blocked"' in body


def test_direct_task_url_draws_project_board_behind(logged, task):
    body = logged.get(f"/tasks/{task.pk}").content.decode()
    assert 'id="board"' in body and 'data-status="todo"' in body


def test_no_toggle_primary_buttons_in_templates():
    """여는 버튼이 주 버튼이면서 [닫기]로 바뀌는 패턴(주 버튼 둘)을 막는다. 주 버튼 규칙(DESIGN.md 3장)."""
    bad = []
    for path in TEMPLATES.rglob("*.html"):
        for line in path.read_text(encoding="utf-8").splitlines():
            if "btn primary" in line and 'data-action="toggle"' in line and "data-alt" in line:
                bad.append(f"{path.name}: {line.strip()[:80]}")
    assert not bad, bad
