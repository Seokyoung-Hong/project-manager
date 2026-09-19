import json
import re
from datetime import timedelta
from pathlib import Path

import pytest
from django.conf import settings

from accounts.models import User
from common.dates import fmt_md, today_kst
from tasks.models import Task, TodayItem

pytestmark = pytest.mark.django_db
HX = {"HX-Request": "true"}


@pytest.fixture
def logged(client, member):
    client.login(username="member1", password="pw12345678")
    return client


def test_root_redirects(client, member):
    assert client.get("/").headers["Location"] == "/login"
    client.login(username="member1", password="pw12345678")
    assert client.get("/").headers["Location"] == "/today"


def test_today_page_renders(logged, org, project, task):
    body = logged.get("/today").content.decode()
    assert "오늘 목록" in body
    assert "전체 조직 · 내 담당 태스크" in body
    assert "빠른 추가" in body


def test_quick_add_creates_task_in_today(logged, project, member):
    r = logged.post(
        "/today/quick",
        {
            "title": "빠른 일",
            "project": project.pk,
            "priority": 5,
            "due_date": (today_kst() + timedelta(days=1)).isoformat(),
            "idem": "q1",
        },
        headers=HX,
    )
    assert r.status_code == 204
    assert r.headers["HX-Redirect"] == "/today"
    item = TodayItem.objects.get(user=member)
    assert item.excluded is False


def test_status_change_returns_row(logged, task):
    r = logged.post(f"/tasks/{task.pk}/status", {"status": "doing", "version": 1}, headers=HX)
    assert r.status_code == 200
    assert f'id="task-{task.pk}"' in r.content.decode()
    assert "task-updated" in r.headers["HX-Trigger"]
    task.refresh_from_db()
    assert task.status == "doing"


def test_status_blocked_without_reason_shows_error(logged, task):
    r = logged.post(f"/tasks/{task.pk}/status", {"status": "blocked", "version": 1}, headers=HX)
    assert r.status_code == 200
    assert "막힘 사유" in r.content.decode()
    task.refresh_from_db()
    assert task.status == "todo"


def test_status_change_conflict_shows_message(logged, task):
    logged.post(f"/tasks/{task.pk}/status", {"status": "doing", "version": 1}, headers=HX)
    r = logged.post(f"/tasks/{task.pk}/status", {"status": "review", "version": 1}, headers=HX)
    assert "먼저 수정했습니다" in r.content.decode()


def test_panel_contains_sections(logged, task):
    body = logged.get(f"/tasks/{task.pk}/panel").content.decode()
    for needle in (
        "변경 이력",
        'id="checklist"',
        "진행 메모",
        "목표일",
        'class="panel-mobile-context"',
        'aria-label="태스크 상세 닫기"',
    ):
        assert needle in body


def test_text_autosave(logged, task):
    r = logged.post(f"/tasks/{task.pk}/text/notes", {"value": "메모"}, headers=HX)
    assert r.status_code == 204
    assert r.headers["HX-Trigger"] == "saved"
    task.refresh_from_db()
    assert task.notes == "메모"
    assert task.version == 1
    assert logged.post(f"/tasks/{task.pk}/text/title", {"value": ""}, headers=HX).status_code == 400


def test_stop_reason_confirm_block(logged, task):
    r = logged.post(
        f"/tasks/{task.pk}/stop-reason",
        {"reason": "서류", "version": 1, "confirm_block": "1"},
        headers=HX,
    )
    assert r.status_code == 200
    task.refresh_from_db()
    assert task.status == "blocked"
    assert "서류" in r.content.decode()
    assert "task-changed" in r.headers["HX-Trigger"]


def test_extend_from_panel(logged, task):
    new = today_kst() + timedelta(days=5)
    r = logged.post(
        f"/tasks/{task.pk}/extend",
        {"due_date": new.isoformat(), "reason": "회의", "version": 1},
        headers=HX,
    )
    assert r.status_code == 200
    assert fmt_md(new) in r.content.decode()
    task.refresh_from_db()
    assert task.due_date == new


def test_project_dialog_and_create(client, org, admin):
    client.login(username="admin1", password="pw12345678")
    body = client.get(f"/projects/new?org={org.pk}", headers=HX).content.decode()
    assert "<form" in body
    assert "프로젝트 만들기" in body
    r = client.post(
        "/projects/new",
        {"org": org.pk, "name": "챗봇", "status": "active", "owners": [admin.pk]},
        headers=HX,
    )
    assert r.status_code == 204
    assert "/projects/" in r.headers["HX-Redirect"]
    r = client.post("/projects/new", {"org": org.pk, "status": "active"}, headers=HX)
    assert r.status_code == 200
    assert "이름을 입력하세요" in r.content.decode()


def test_project_inline_task_create(logged, project, member):
    r = logged.post(
        f"/projects/{project.pk}/tasks",
        {
            "title": "인라인",
            "assignee": member.pk,
            "priority": 5,
            "due_date": (today_kst() + timedelta(days=2)).isoformat(),
            "idem": "i1",
        },
        headers=HX,
    )
    assert r.status_code == 204
    assert "#task-" in r.headers["HX-Redirect"]
    t = Task.objects.get(title="인라인")
    assert t.assignee == member
    assert t.project == project  # A02: 그 화면의 프로젝트에 자동 연결
    assert t.status == "todo"


def test_me_team_view_read_only(logged, task):
    """보기 전용이면 상태는 고를 수 없는 정적 배지로 그린다(비활성 셀렉트가 아니다)."""
    body = logged.get("/me?member=0").content.decode()
    assert "보기 전용" in body
    assert 'class="pill todo static"' in body
    assert 'class="pill todo"' not in body  # 셀렉트 모양의 상태는 없다


def test_panel_edits_project_and_assignee_inline(logged, task, admin, org):
    """표면마다 고칠 수 있는 필드가 다르면 안 된다 — 패널이 프로젝트·담당자까지 맡는다."""
    from projects.services import create_project

    other = create_project(org=org, name="다른 프로젝트", actor=admin, owners=[admin])
    r = logged.post(
        f"/tasks/{task.pk}/meta",
        {"version": task.version, "project": other.pk},
        headers=HX,
    )
    assert r.status_code == 200
    task.refresh_from_db()
    assert task.project == other

    r = logged.post(
        f"/tasks/{task.pk}/meta",
        {"version": task.version, "assignee": admin.pk},
        headers=HX,
    )
    assert r.status_code == 200
    task.refresh_from_db()
    assert task.assignee == admin


def test_panel_meta_rejects_outside_org(logged, task, outsider):
    r = logged.post(
        f"/tasks/{task.pk}/meta",
        {"version": task.version, "assignee": outsider.pk},
        headers=HX,
    )
    assert r.status_code == 200
    assert "맡길 수 없습니다" in r.content.decode()
    task.refresh_from_db()
    assert task.assignee != outsider


def test_task_edit_page_is_gone(logged, task):
    """편집 화면은 패널에 흡수됐다. 남아 있으면 같은 필드를 두 곳에서 고치게 된다."""
    assert logged.get(f"/tasks/{task.pk}/edit").status_code == 404


def test_events_stream_reports_changes(logged, task, member):
    """/events는 방금 바뀐 태스크 id를 흘려보낸다 — 실시간 반영의 유일한 출처."""
    from tasks.services import update_text
    from web.views import events as ev

    update_text(task, "title", "다른 사람이 고친 제목", actor=member)
    r = logged.get("/events")
    assert r.status_code == 200
    assert r["Content-Type"] == "text/event-stream"
    assert r["X-Accel-Buffering"] == "no"
    # 스트림을 통째로 돌리면 STREAM_SECONDS만큼 걸린다. 피드 함수만 직접 확인한다.
    since = task.updated_at - timedelta(seconds=1)
    assert task.pk in [pk for pk, _ in ev._changed_since(task.project.org, since)]
    r.close()


def test_events_needs_login(client):
    assert client.get("/events").status_code == 302


def test_me_group_buttons_mark_one(logged, task):
    """묶음은 '없음'까지 포함해 항상 하나만 눌려 있다(눌림 없음 = 분류 없음이 아니다)."""
    pressed = 'aria-pressed="true"'

    def group_row(body):
        return body.split('aria-label="묶음"')[1].split('aria-label="정렬"')[0]

    # 기본·오타는 기한별
    for url in ("/me?member=0", "/me?member=0&group=nonsense"):
        body = logged.get(url).content.decode()
        assert group_row(body).count(pressed) == 1
        assert 'value="due" aria-pressed="true">기한별' in body
        assert "<h2>미완료 <" not in body
    body = logged.get("/me?member=0&group=none").content.decode()
    assert group_row(body).count(pressed) == 1
    assert 'value="none" aria-pressed="true">없음' in body
    assert "<h2>미완료 <" in body and "<h2>기한 초과 <" not in body


def test_me_omits_empty_due_groups_and_marks_advanced_filters(logged, task):
    body = logged.get("/me").content.decode()
    assert task.title in body
    assert "<h2>기한 초과 <" not in body
    assert "<h2>오늘 마감 <" not in body
    assert 'data-filter-active="0"' in body
    assert "기한 · 프로젝트 · 상태 · 중요도" in body

    filtered = logged.get("/me?priority=high").content.decode()
    assert 'data-filter-active="1"' in filtered
    assert "조건 적용됨" in filtered


def test_me_sort_survives_filters(logged, task):
    body = logged.get("/me?member=0&sort=priority&due=overdue").content.decode()
    assert 'value="priority" aria-pressed="true">중요도' in body
    assert '<input type="hidden" name="sort" value="priority">' in body
    assert "&group=due&sort=priority" in body  # 필터 지우기 링크
    body = logged.get("/me?member=0&sort=nonsense").content.decode()
    assert 'value="due" aria-pressed="true">기한' in body


def test_org_page_renders(logged, org, project):
    body = logged.get(f"/orgs/{org.pk}").content.decode()
    assert "미완료" in body
    assert project.name in body
    assert "새 프로젝트" in body


def test_signup_lands_on_org_list_with_create_button(client):
    """조직이 없는 채로 가입한 사람은 [조직 만들기]가 있는 화면에 내린다."""
    r = client.post(
        "/signup",
        {
            "username": "newbie",
            "display_name": "새사람",
            "password1": "verysecret123",
            "password2": "verysecret123",
        },
    )
    assert r.status_code == 302
    assert r.headers["Location"] == "/orgs"
    body = client.get("/orgs").content.decode()
    assert "조직 만들기" in body
    assert "초대 링크" in body


def test_ops_requires_staff(client, member):
    client.login(username="member1", password="pw12345678")
    assert client.get("/ops").status_code in (302, 403)
    User.objects.filter(pk=member.pk).update(is_staff=True, is_superuser=True)
    assert client.get("/ops").status_code == 200


def test_export_json_has_no_secrets(client, member, admin, org, task):
    """백업에 비밀번호·초대 token·Discord 연결 코드가 들어가지 않는다."""
    from accounts.services import issue_link_code
    from orgs.services import create_invite

    invite = create_invite(org, admin)
    code = issue_link_code(admin)
    User.objects.filter(pk=member.pk).update(is_staff=True, is_superuser=True)
    client.login(username="member1", password="pw12345678")
    r = client.get("/ops/export.json")
    assert r.status_code == 200
    body = r.content.decode()
    assert "password" not in body
    assert invite.token not in body
    # 연결 코드는 살아 있는 10분 동안 자격증명이다. 연결 시각은 기록이므로 남는다.
    assert code not in body
    assert "discord_link_code" not in body
    assert "discord_linked_at" in body


def test_healthz(client):
    r = client.get("/healthz")
    assert r.status_code == 200
    assert r.json() == {"ok": True}


def test_token_shown_once(logged):
    r = logged.post("/settings/tokens", {"name": "t", "scope": "read"})
    assert r.status_code == 302
    assert "pm_" in logged.get("/settings/tokens").content.decode()
    assert "pm_" not in logged.get("/settings/tokens").content.decode()


def test_token_page_shows_the_real_mcp_url(logged, settings):
    """연결 예시에 <MCP_URL> 자리표시자를 남기지 않는다 — 절반이 틀린 주소로 붙는다."""
    settings.MCP_URL = "https://mcp.example.test"
    body = logged.get("/settings/tokens").content.decode()
    assert "MCP_URL" not in body
    assert "https://mcp.example.test/mcp" in body
    assert "https://mcp.example.test/u/" in body


def test_schedule_card_is_scoped_to_org_membership(logged, task, project, member):
    """일정 카드도 조직 범위를 따른다. 조직에서 빠지면 마감이 달력에 남지 않는다."""
    from orgs.models import OrgMembership

    body = logged.get("/today?schedule=1&cal=month").content.decode()
    assert task.title in body

    OrgMembership.objects.filter(org=project.org, user=member).delete()
    body = logged.get("/today?schedule=1&cal=month").content.decode()
    assert task.title not in body


def test_non_numeric_ids_are_404_not_500(logged, project):
    """쿼리·경로의 id가 숫자가 아니면 404다. filter(pk="abc")는 ValueError -> 500이 된다."""
    assert logged.get("/projects/new?org=abc").status_code == 404
    assert logged.post("/projects/new", {"org": "abc", "name": "x"}, headers=HX).status_code == 404


def test_weird_digit_query_params_do_not_crash(logged, task):
    """isdigit()은 '²'에 True지만 int()는 실패한다. isdecimal()로 막아야 한다."""
    assert logged.get("/search?q=²").status_code == 200
    assert logged.get("/me?member=²").status_code == 200
    assert logged.get("/me?project=²").status_code == 200


def test_profile_has_no_discord_id_input(client, admin, member):
    """자유 입력칸을 남겨 두면 코드 교환 전체가 무의미해진다(위조 경로)."""
    client.login(username="admin1", password="pw12345678")
    assert 'name="discord_user_id"' not in client.get("/settings/profile").content.decode()

    r = client.post("/settings/profile", {"display_name": "관리자", "discord_user_id": "222"})
    assert r.status_code == 302
    admin.refresh_from_db()
    assert admin.display_name == "관리자"
    assert admin.discord_user_id is None


def test_discord_link_code_is_shown_once_then_unlink_clears(client, admin):
    """코드는 발급 직후 한 번만 보인다(토큰 화면의 new_token과 같은 방식)."""
    from accounts.services import link_discord

    client.login(username="admin1", password="pw12345678")
    assert client.post("/settings/profile/discord").status_code == 302
    admin.refresh_from_db()
    code = admin.discord_link_code
    assert code and len(code) == 8

    body = client.get("/settings/profile").content.decode()
    assert f"연결 {code}" in body
    assert code not in client.get("/settings/profile").content.decode()

    link_discord(code, "222")
    assert "연결됨" in client.get("/settings/profile").content.decode()

    assert client.post("/settings/profile/discord/unlink").status_code == 302
    admin.refresh_from_db()
    assert admin.discord_user_id is None
    assert admin.discord_linked_at is None


def test_long_idem_key_does_not_crash(logged, project):
    """IdempotencyKey.key는 varchar(100). 폼이 막지 않으면 Postgres에서 DataError -> 500."""
    r = logged.post(
        "/today/quick",
        {
            "title": "긴 idem",
            "project": project.pk,
            "priority": 5,
            "due_date": (today_kst() + timedelta(days=1)).isoformat(),
            "idem": "z" * 300,
        },
        headers=HX,
    )
    assert r.status_code in (200, 204)


def test_far_future_schedule_day_does_not_crash(logged, task):
    """week_days()가 date.max 근처에서 OverflowError를 내지 않아야 한다."""
    for day in ("9999-12-01", "9999-12-31", "0001-01-01"):
        assert logged.get(f"/today?schedule=1&cal=month&day={day}").status_code == 200


def test_admin_task_and_project_are_read_only(client, member, task, project):
    """GUIDE-00 §3: Task·Project는 services 밖에서 바꾸지 않는다. admin은 조회 전용이다.

    조회(목록·상세)는 200으로 남고, 추가·삭제는 403, 변경 POST는 403이며 값이 바뀌지 않는다.
    """
    User.objects.filter(pk=member.pk).update(is_staff=True, is_superuser=True)
    client.login(username="member1", password="pw12345678")

    assert client.get("/admin/tasks/task/").status_code == 200
    assert client.get(f"/admin/tasks/task/{task.pk}/change/").status_code == 200
    assert client.get(f"/admin/projects/project/{project.pk}/change/").status_code == 200

    assert client.get("/admin/tasks/task/add/").status_code == 403
    assert client.get(f"/admin/tasks/task/{task.pk}/delete/").status_code == 403

    r = client.post(f"/admin/tasks/task/{task.pk}/change/", {"status": "done", "title": "해킹"})
    assert r.status_code == 403
    task.refresh_from_db()
    assert task.status == "todo"
    assert task.title == "메뉴 누락 개선"


def test_secret_filter_redacts_tokens(caplog):
    """GUIDE-00: 로그에 API 토큰·Discord 봇 토큰 원문이 남지 않는다 (common.logging)."""
    import logging

    from common.logging import SecretFilter

    bot = "MTk4NjIyNDgzNDcxOTI1MjQ4.Cl2FMQ.ZnCjm1XVW7vRze4b7Cq4se7kKWs"
    f = SecretFilter()
    cases = [
        ("token=pm_abcdefghijklmnopqrstuvwxyz012345", "pm_"),
        ("Authorization: Bearer pm_abcdefghijklmnopqrstuvwxyz012345", "Bearer"),
        ("GET /u/pm_abcdefghijklmnopqrstuvwxyz012345/mcp", "/u/pm_"),
        # 봇 REST 호출은 `Bot <token>`으로 실린다. bearer 패턴이 못 잡는 형식이다.
        (f"POST /channels/1/messages Authorization: Bot {bot}", bot),
        (f"env DISCORD_BOT_TOKEN={bot}", bot),
    ]
    for msg, secret in cases:
        rec = logging.LogRecord("t", logging.INFO, "p", 1, msg, None, None)
        f.filter(rec)
        assert "[redacted]" in rec.getMessage()
        assert secret not in rec.getMessage(), rec.getMessage()

    # args를 쓰는 형식도 가려진다
    rec = logging.LogRecord(
        "t", logging.INFO, "p", 1, "token %s", ("pm_abcdefghijklmnopqrstuvwxyz012345",), None
    )
    f.filter(rec)
    assert "pm_" not in rec.getMessage()


# ---------- 멤버 관리 (조직 관리자 전용) ----------


@pytest.fixture
def as_admin(client, org):
    client.login(username="admin1", password="pw12345678")
    return client


def test_admin_pages_explain_to_members(logged, org):
    """멤버가 관리 화면을 열면 404가 아니라 이유를 말하고 조직 현황으로 보낸다.

    예전에는 404였다. 멤버는 팀이 있다는 걸 이미 아는 사람이라 숨길 것이 없고,
    "없는 페이지"로 읽히면 권한 문제인지 알 수 없었다. 존재를 숨기는 404는 조직 밖 사람 몫이다.
    """
    r = logged.get(f"/orgs/{org.pk}/teams")
    assert r.status_code == 302 and r.url == f"/orgs/{org.pk}"
    page = logged.get(r.url)
    assert page.status_code == 200 and "조직 관리자만 접근할 수 있습니다" in page.content.decode()


def test_webhook_routes_are_gone(as_admin, org):
    """알림 채널 화면은 대체가 아니라 삭제다. 관리자에게도 경로가 없다."""
    for path in (f"/orgs/{org.pk}/webhooks", f"/orgs/{org.pk}/webhooks/new"):
        assert as_admin.get(path).status_code == 404
        assert as_admin.post(path, {"name": "x", "url": "https://x"}).status_code == 404


def test_members_page_shows_workload_and_discord_link(as_admin, org, task, member):
    body = as_admin.get(f"/orgs/{org.pk}/teams").content.decode()
    assert "멤버" in body
    assert member.display_name in body
    assert "연결" in body  # member 픽스처는 연결이 끝난 상태다
    assert "관리자 1명" in body


def test_token_form_cannot_mint_a_bot_scope_token(logged, member):
    """bot 범위 자기 발급은 권한 상승이다. 발급은 서버 셸로만 한다."""
    from accounts.models import ApiToken

    body = logged.get("/settings/tokens").content.decode()
    assert '<option value="bot"' not in body

    r = logged.post("/settings/tokens", {"name": "봇", "scope": "bot"})
    assert r.status_code == 200  # 폼이 무효라 발급 없이 화면만 다시 그린다
    assert not ApiToken.objects.exists()


# ---------- V2-02: 셸과 내비게이션 ----------


def test_project_index_uses_session_then_first(logged, org, project, member):
    """세션 프로젝트 → 조직 첫 프로젝트 순서."""
    from projects.services import create_project

    r = logged.get("/projects")
    assert r.status_code == 302
    assert r.headers["Location"] == f"/projects/{project.pk}"

    p2 = create_project(org=org, name="다른 프로젝트", actor=member, owners=[member])
    session = logged.session
    session["project_id"] = p2.pk
    session.save()
    r = logged.get("/projects")
    assert r.headers["Location"] == f"/projects/{p2.pk}"


def test_project_index_empty_screen(logged, org):
    r = logged.get("/projects")
    assert r.status_code == 200
    assert "아직 프로젝트가 없습니다" in r.content.decode()


def test_rail_only_in_project_area(logged, org, project):
    assert 'class="rail"' not in logged.get("/today").content.decode()
    assert 'class="project-picker"' not in logged.get("/today").content.decode()
    assert 'class="rail"' not in logged.get(f"/orgs/{org.pk}").content.decode()
    body = logged.get(f"/projects/{project.pk}").content.decode()
    assert 'class="rail"' in body
    assert 'class="project-picker"' in body


def test_project_and_org_sibling_tabs_keep_shell_context(logged, org, project):
    for url in (f"/projects/{project.pk}/docs", f"/projects/{project.pk}/settings"):
        body = logged.get(url).content.decode()
        assert 'href="/projects" aria-current="page"' in body
        assert 'class="rail"' in body
        assert f"프로젝트 전환, 현재 {project.name}" in body

    for url in (f"/orgs/{org.pk}/governance", f"/orgs/{org.pk}/settings"):
        body = logged.get(url).content.decode()
        assert 'href="/org" aria-current="page"' in body


def test_mobile_project_picker_names_current_project(logged, project, task):
    body = logged.get(f"/projects/{project.pk}").content.decode()
    assert f"프로젝트 전환, 현재 {project.name}" in body
    assert f"<strong>{project.name}</strong>" in body
    assert f'href="/projects/{project.pk}" aria-current="page"' in body
    assert 'class="tiles five project-kpis" tabindex="0" role="region"' in body
    assert "프로젝트 태스크 요약, 좌우로 스크롤 가능" in body


def test_rail_shows_open_counts(logged, project, task):
    body = logged.get(f"/projects/{project.pk}").content.decode()
    assert '<span class="count t12 muted">1</span>' in body


def test_rail_close_handle_hides_list_completely(logged, project):
    """레일에는 다시 여는 손잡이(data-action="toggle-rail")가 있고, 닫힘 클래스가 붙으면
    목록이 아이콘만 남는 게 아니라 완전히 숨겨져야 한다(display:none). JS 토글 자체는 다루지 않는다."""
    body = logged.get(f"/projects/{project.pk}").content.decode()
    assert 'data-action="toggle-rail"' in body

    css = (Path(__file__).resolve().parent / "static" / "app.css").read_text(encoding="utf-8")
    assert (
        ".rail.collapsed .rail-list" in css
        and "display: none" in css.split(".rail.collapsed .rail-list")[1].split("}")[0]
    )


def test_org_tabs_hidden_for_member(logged, org):
    body = logged.get(f"/orgs/{org.pk}").content.decode()
    assert f"/orgs/{org.pk}/teams" not in body


def test_org_teams_denial_is_htmx_aware(logged, org):
    """탭을 HTMX로 열다 거절되면 조각 대신 HX-Redirect로 조직 현황에 착지한다."""
    r = logged.get(f"/orgs/{org.pk}/teams", headers={"HX-Request": "true"})
    assert r.status_code == 204 and r.headers["HX-Redirect"] == f"/orgs/{org.pk}"


def test_team_crud_via_web(as_admin, org):
    from orgs.models import Team

    r = as_admin.post(f"/orgs/{org.pk}/teams/new", {"name": "디자인", "purpose": "UI"}, headers=HX)
    assert r.status_code == 204
    team = Team.objects.get(org=org, name="디자인")

    r = as_admin.post(f"/teams/{team.pk}/edit", {"name": "디자인팀", "purpose": ""}, headers=HX)
    assert r.status_code == 204
    team.refresh_from_db()
    assert team.name == "디자인팀"

    r = as_admin.post(f"/teams/{team.pk}/delete")
    assert r.status_code == 302
    assert not Team.objects.filter(pk=team.pk).exists()


def test_team_member_add_remove_via_web(as_admin, org, team, member, admin, outsider):
    r = as_admin.post(f"/teams/{team.pk}/members", {"user": outsider.pk})
    assert r.status_code == 302
    assert not team.members.filter(pk=outsider.pk).exists()  # 조직 멤버만 추가된다

    r = as_admin.post(f"/teams/{team.pk}/members", {"user": admin.pk})
    assert r.status_code == 302
    assert team.members.filter(pk=admin.pk).exists()

    assert team.members.filter(pk=member.pk).exists()
    r = as_admin.post(f"/teams/{team.pk}/members/{member.pk}/remove")
    assert r.status_code == 302
    assert not team.members.filter(pk=member.pk).exists()


def test_member_tags_saved_and_normalized(as_admin, org, member):
    from orgs.models import OrgMembership

    membership = OrgMembership.objects.get(org=org, user=member)
    r = as_admin.post(
        f"/orgs/memberships/{membership.pk}/tags", {"tags": " 파이썬 , 파이썬, ,장고"}
    )
    assert r.status_code == 302
    membership.refresh_from_db()
    assert membership.tags == ["파이썬", "장고"]


def test_project_dialog_sets_teams(as_admin, org, project, team, admin):
    from tasks.models import ChangeLog

    r = as_admin.post(
        f"/projects/{project.pk}/edit",
        {
            "name": project.name,
            "purpose": project.purpose,
            "status": project.status,
            "owners": [admin.pk],
            "teams": [team.pk],
            "version": project.version,
        },
        headers=HX,
    )
    assert r.status_code == 204
    project.refresh_from_db()
    assert team in project.teams.all()
    assert ChangeLog.objects.filter(
        target_type="project", target_id=project.pk, field="teams"
    ).exists()


def test_org_overview_tiles(logged, org, project, task):
    from reports.services import org_status

    st = org_status(org)
    body = logged.get(f"/orgs/{org.pk}").content.decode()
    for label in ("미완료", "진행 중", "검토 대기", "기한 초과", "막힘", "완료"):
        assert label in body
    assert f"<b>{st['counts']['open']}</b>" in body


def test_org_overview_marks_mobile_scroll_regions(as_admin, org, project, task):
    body = as_admin.get(f"/orgs/{org.pk}").content.decode()
    assert 'class="tabs org-tabs"' in body
    assert 'class="tiles org-kpis" tabindex="0" role="region"' in body
    assert 'aria-label="조직 태스크 요약, 좌우로 스크롤 가능"' in body
    assert 'class="table-scroll" tabindex="0" role="region"' in body
    assert 'class="grid project-table"' in body
    assert 'class="grid assignee-table"' in body


def test_capacity_uses_aligned_load_grid_and_focusable_summary(as_admin, org, project, task):
    body = as_admin.get(f"/orgs/{org.pk}/capacity").content.decode()
    assert 'class="tiles five org-kpis" tabindex="0" role="region"' in body
    assert 'class="grow stack load-meter"' in body
    assert 'class="chips load-tags"' in body
    assert 'class="badge load-verdict' in body


def test_roadmap_marks_responsive_timeline_regions(as_admin, org, project, admin):
    from projects.services import create_milestone

    create_milestone(
        project=project,
        name="모바일 마일스톤",
        target_date=today_kst() + timedelta(days=7),
        actor=admin,
    )
    body = as_admin.get(f"/orgs/{org.pk}/roadmap").content.decode()
    assert 'class="card org-roadmap-card"' in body
    assert 'class="row tl-actions"' in body


# ---------- V2-03: 칸반 드래그 ----------


def test_board_always_has_done_column(logged, project, task):
    body = logged.get(f"/projects/{project.pk}?view=board").content.decode()
    assert 'class="col" data-status="done"' in body
    assert 'class="col" data-status="cancelled"' not in body


def test_board_columns_cover_all_statuses(logged, project, task):
    body = logged.get(f"/projects/{project.pk}?view=board&include_closed=1").content.decode()
    assert body.count('class="col" data-status="') == len(Task.STATUSES)


def test_board_part_renders_only_board(logged, project, task):
    r = logged.get(f"/projects/{project.pk}?view=board&part=board")
    body = r.content.decode().strip()
    assert body.startswith('<div id="board"')


def test_board_has_explicit_scroll_navigation(logged, project, task):
    body = logged.get(f"/projects/{project.pk}?view=board").content.decode()
    assert 'class="board-track" tabindex="0" role="region"' in body
    assert body.count('data-action="scroll-board"') == 2
    assert 'aria-label="이전 상태 열"' in body
    assert 'aria-label="다음 상태 열"' in body


def test_drop_changes_status_and_returns_board(logged, task):
    r = logged.post(
        f"/tasks/{task.pk}/status",
        {"status": "doing", "version": task.version, "from": "board"},
        headers=HX,
    )
    assert r.status_code == 200
    assert 'id="board"' in r.content.decode()
    assert "task-updated" in r.headers["HX-Trigger"]
    task.refresh_from_db()
    assert task.status == "doing"


def test_drop_to_doing_without_due_shows_error_in_board(logged, project, member):
    from tasks.services import create_task

    t = create_task(
        project=project, title="기한 없음", actor=member, source="web", no_due_reason="사유"
    )
    r = logged.post(
        f"/tasks/{t.pk}/status",
        {"status": "doing", "version": t.version, "from": "board"},
        headers=HX,
    )
    assert r.status_code == 200
    body = r.content.decode()
    assert 'id="board"' in body
    assert "error" in body
    t.refresh_from_db()
    assert t.status == "todo"


def test_drop_blocked_without_reason_shows_error_in_board(logged, task):
    r = logged.post(
        f"/tasks/{task.pk}/status",
        {"status": "blocked", "version": task.version, "from": "board"},
        headers=HX,
    )
    assert r.status_code == 200
    assert 'id="board"' in r.content.decode()
    task.refresh_from_db()
    assert task.status != "blocked"


def test_drop_conflict_shows_message_in_board(logged, task):
    r = logged.post(
        f"/tasks/{task.pk}/status",
        {"status": "doing", "version": task.version + 1, "from": "board"},
        headers=HX,
    )
    assert r.status_code == 200
    assert 'id="board"' in r.content.decode()


def test_row_draggable_only_in_board(logged, project, task):
    body = logged.get(f"/projects/{project.pk}?view=board").content.decode()
    assert 'draggable="true"' in body
    body = logged.get(f"/projects/{project.pk}?view=list").content.decode()
    assert 'draggable="true"' not in body


def test_schedule_has_no_time_view(logged, task):
    """?cal=time을 줘도 시간표는 없고 월 캘린더만 나온다."""
    body = logged.get("/today?schedule=1&cal=time").content.decode()
    assert 'class="hours"' not in body
    assert '<div class="cal">' in body


def test_schedule_disclosure_and_date_state_are_accessible(logged, task):
    body = logged.get("/today?schedule=1").content.decode()
    assert 'href="/today?schedule=0#today-list"' in body
    assert 'aria-expanded="true"' in body
    assert 'aria-controls="today-schedule"' in body
    assert 'class="card today-list-card" tabindex="-1"' in body
    assert 'id="today-schedule"' in body
    assert 'aria-current="date"' in body
    assert "선택됨" in body
    assert "일정 닫기" in body


def test_schedule_state_survives_htmx_partial_refreshes(logged, task):
    current = "http://testserver/today?schedule=1&month=2026-08&day=2026-08-12"
    headers = {**HX, "HX-Current-URL": current}

    body = logged.get("/today?part=list", headers=headers).content.decode()
    assert 'href="/today?schedule=0#today-list"' in body
    assert 'aria-expanded="true"' in body

    body = logged.get("/today?part=schedule", headers=headers).content.decode()
    assert "2026년 8월" in body
    assert "8월 12일" in body
    assert (
        'hx-trigger="task-changed from:body, task-updated from:body, today-changed from:body"'
        in body
    )

    body = logged.post(
        "/today/settings",
        {"auto_pull_days": 3},
        headers=headers,
    ).content.decode()
    assert 'aria-expanded="true"' in body
    assert "일정 닫기" in body


def test_schedule_state_is_explicit_when_task_panel_owns_current_url(logged, task):
    state = "schedule=1&month=2026-08&day=2026-08-12"
    escaped_state = state.replace("&", "&amp;")
    headers = {**HX, "HX-Current-URL": f"http://testserver/tasks/{task.pk}"}

    body = logged.get(f"/today?part=list&{state}", headers=headers).content.decode()
    assert f"/today?part=list&amp;{escaped_state}" in body
    assert f"/tasks/{task.pk}/status?{escaped_state}" in body
    assert 'aria-expanded="true"' in body
    assert "일정 닫기" in body

    body = logged.get(f"/today?part=schedule&{state}", headers=headers).content.decode()
    assert f"/today?part=schedule&amp;{escaped_state}" in body
    assert "2026년 8월" in body


def test_schedule_cells_multiple_of_seven(member, task):
    from datetime import date

    from django.test import RequestFactory

    from web.views.today import _schedule

    req = RequestFactory().get("/today", {"month": "2026-09"})
    req.user = member
    ctx = _schedule(req, date(2026, 9, 12))
    assert len(ctx["cal_cells"]) in (28, 35, 42)
    assert ctx["cal_prev"].endswith("#today-schedule")


def test_schedule_month_nav(logged, task):
    from common.dates import today_kst

    body = logged.get("/today?schedule=1").content.decode()
    assert "이전 달" in body
    assert "다음 달" in body
    assert "이번 달" not in body

    this_month = today_kst().replace(day=1)
    prev_month = (this_month - timedelta(days=1)).replace(day=1)
    body = logged.get(f"/today?schedule=1&month={prev_month:%Y-%m}").content.decode()
    assert "이번 달" in body


def test_schedule_labels(logged, project, member):
    from common.dates import today_kst
    from tasks.services import create_task

    due = today_kst() + timedelta(days=2)
    create_task(project=project, title="라벨용", actor=member, source="web", due_date=due)

    body = logged.get(f"/today?schedule=1&month={due:%Y-%m}&day={due.isoformat()}").content.decode()
    assert "마감 1건" in body

    empty_day = due + timedelta(days=1)
    body = logged.get(
        f"/today?schedule=1&month={empty_day:%Y-%m}&day={empty_day.isoformat()}"
    ).content.decode()
    assert "마감 없음" in body

    other_month_day = (today_kst().replace(day=1) - timedelta(days=40)).isoformat()
    body = logged.get(f"/today?schedule=1&day={other_month_day}").content.decode()
    assert "날짜를 누르면 그날 마감이 보입니다" in body


def test_schedule_counts_exclude_closed(logged, project, member):
    from common.dates import today_kst
    from tasks import services as ts
    from tasks.services import create_task

    due = today_kst() + timedelta(days=2)
    t = create_task(project=project, title="완료됨", actor=member, source="web", due_date=due)
    ts.transition(t, "doing", actor=member, source="web", expected_version=t.version)
    t.refresh_from_db()
    ts.transition(t, "review", actor=member, source="web", expected_version=t.version)
    t.refresh_from_db()
    ts.transition(t, "done", actor=member, source="web", expected_version=t.version)

    body = logged.get(f"/today?schedule=1&month={due:%Y-%m}").content.decode()
    assert "●" not in body


# ---------- 회의록 (V2-05) ----------


def test_note_create_and_list_scopes(logged, org, project, member):
    from notes.services import create_note

    team_note = create_note(org=org, actor=member, title="팀 공통 회의록")
    project_note = create_note(org=org, actor=member, title="프로젝트 회의록", project=project)

    body = logged.get(f"/orgs/{org.pk}/notes?scope=all").content.decode()
    assert "팀 공통 회의록" in body and "프로젝트 회의록" in body

    body = logged.get(f"/orgs/{org.pk}/notes?scope=team").content.decode()
    assert "팀 공통 회의록" in body and "프로젝트 회의록" not in body

    body = logged.get(f"/orgs/{org.pk}/notes?scope={project.pk}").content.decode()
    assert "프로젝트 회의록" in body and "팀 공통 회의록" not in body

    assert team_note.pk and project_note.pk


def test_note_click_shows_selected_body(logged, org, member):
    """목록에서 회의록을 고르면(=note 쿼리) 그 회의록의 본문이 뜬다.

    /orgs/<id>/notes는 note-item을 누르면 HTMX 부분 렌더가 아니라 전체 페이지를
    다시 그린다(hx-get·hx-target이 없다) — 그래서 편집기(.doc)도 매 요청마다
    새로 만들어진다. 여기서는 그 전체 렌더 결과에 고른 회의록의 본문이 실제로
    담기는지, 목록의 다른 회의록 본문과 섞이지 않는지를 확인한다."""
    from notes.services import create_note

    n1 = create_note(org=org, actor=member, title="첫 회의록", body_md="첫 회의 본문")
    n2 = create_note(org=org, actor=member, title="둘째 회의록", body_md="둘째 회의 본문")

    body = logged.get(f"/orgs/{org.pk}/notes?scope=all&note={n2.pk}").content.decode()
    assert 'class="notes-columns note-editor-open"' in body
    assert 'class="doc"' in body
    assert 'id="doc-src"' in body
    assert 'class="card note-editor-card" id="note-editor"' in body
    assert 'class="btn sm note-back"' in body
    assert 'class="note-save-status" data-state="saved"' in body
    assert "저장됨 · v1" in body
    assert 'aria-current="page"' in body
    assert "둘째 회의 본문" in body
    assert "첫 회의 본문" not in body

    body = logged.get(f"/orgs/{org.pk}/notes?scope=all&note={n1.pk}").content.decode()
    assert "첫 회의 본문" in body
    assert "둘째 회의 본문" not in body


def test_note_list_mode_is_distinct_from_requested_editor(logged, org, member):
    from notes.services import create_note

    note = create_note(org=org, actor=member, title="목록과 편집기")
    body = logged.get(f"/orgs/{org.pk}/notes?scope=all").content.decode()
    assert 'class="notes-columns">' in body
    assert 'class="notes-columns note-editor-open"' not in body
    assert 'class="card list note-list" id="note-list"' in body
    assert f"note={note.pk}" in body

    selected = logged.get(f"/orgs/{org.pk}/notes?scope=all&note={note.pk}").content.decode()
    assert 'class="notes-columns note-editor-open"' in selected
    assert "← 회의록 목록" in selected


def test_note_save_bumps_version(logged, org, member):
    from notes.services import create_note

    note = create_note(org=org, actor=member)
    r = logged.post(
        f"/notes/{note.pk}/save", {"field": "title", "value": "새 제목", "version": note.version}
    )
    assert r.status_code == 204
    assert r.headers["X-Note-Version"] == "2"
    note.refresh_from_db()
    assert note.title == "새 제목"
    assert note.version == 2


def test_note_save_conflict_returns_409(logged, org, member):
    from notes.services import create_note

    note = create_note(org=org, actor=member)
    logged.post(
        f"/notes/{note.pk}/save", {"field": "title", "value": "1차 수정", "version": note.version}
    )
    r = logged.post(
        f"/notes/{note.pk}/save", {"field": "title", "value": "낡은 수정", "version": note.version}
    )
    assert r.status_code == 409


def test_note_save_tags_and_meeting_datetime(logged, org, member):
    """태그는 쉼표로 구분한 문자열 하나로 저장(공백 제거·중복 제거), 회의 일시는
    datetime-local 문자열을 받아 저장하고 빈 값이면 비워 둘 수 있다(작성 시각과 별개)."""
    from datetime import datetime

    from common.dates import KST
    from notes.services import create_note

    note = create_note(org=org, actor=member)
    r = logged.post(
        f"/notes/{note.pk}/save",
        {"field": "tags", "value": " 스프린트 , 결정사항 ,스프린트", "version": note.version},
    )
    assert r.status_code == 204
    note.refresh_from_db()
    assert note.tags == ["스프린트", "결정사항"]

    r = logged.post(
        f"/notes/{note.pk}/save",
        {"field": "created_on", "value": "2026-09-20T14:30", "version": note.version},
    )
    assert r.status_code == 204
    note.refresh_from_db()
    assert note.created_on == datetime(2026, 9, 20, 14, 30, tzinfo=KST)

    r = logged.post(
        f"/notes/{note.pk}/save", {"field": "created_on", "value": "", "version": note.version}
    )
    assert r.status_code == 204
    note.refresh_from_db()
    assert note.created_on is None


def test_note_tag_filter(logged, org, member):
    from notes.services import create_note

    a = create_note(org=org, actor=member, title="스프린트 회고", tags=["스프린트", "회고"])
    b = create_note(org=org, actor=member, title="결정 사항 정리", tags=["결정사항"])

    body = logged.get(f"/orgs/{org.pk}/notes?scope=all&tag=스프린트").content.decode()
    assert "스프린트 회고" in body and "결정 사항 정리" not in body

    body = logged.get(f"/orgs/{org.pk}/notes?scope=all").content.decode()
    assert "스프린트 회고" in body and "결정 사항 정리" in body

    assert a.pk and b.pk


def test_task_note_link_unlink(logged, org, task, member, project, admin):
    from notes.services import create_note
    from orgs.models import OrgMembership
    from orgs.services import create_org

    note = create_note(org=org, actor=member)
    r = logged.post(f"/tasks/{task.pk}/notes", {"note": note.pk})
    assert r.status_code == 200
    assert note in task.meeting_notes.all()

    r = logged.post(f"/tasks/{task.pk}/notes/{note.pk}/unlink")
    assert r.status_code == 200
    assert note not in task.meeting_notes.all()

    other_org = create_org("다른 조직", "", admin)
    OrgMembership.objects.create(org=other_org, user=member, role="member")
    other_note = create_note(org=other_org, actor=member)
    r = logged.post(f"/tasks/{task.pk}/notes", {"note": other_note.pk})
    assert other_note not in task.meeting_notes.all()


def test_link_form_hides_pr_repo(logged, task):
    body = logged.get(f"/tasks/{task.pk}/panel").content.decode()
    assert "PR" not in body.split('name="kind"')[1].split("</select>")[0]
    assert "저장소" not in body.split('name="kind"')[1].split("</select>")[0]


def test_notes_hidden_from_other_org(client, org, outsider, member):
    from notes.services import create_note

    note = create_note(org=org, actor=member)
    client.login(username="outsider", password="pw12345678")
    assert client.get(f"/orgs/{org.pk}/notes").status_code == 404
    assert (
        client.post(f"/notes/{note.pk}/save", {"field": "title", "value": "x"}).status_code == 404
    )


# ---- V2-06: API 문서 ----


def test_spec_upload_json_only(logged, project):
    from django.core.files.uploadedfile import SimpleUploadedFile

    r = logged.post(
        f"/projects/{project.pk}/api",
        {"file": SimpleUploadedFile("spec.txt", b"not json", content_type="text/plain")},
    )
    assert "json 파일만" in r.content.decode()
    assert not hasattr(project, "api_spec") or project.api_spec is None


def test_spec_upload_saves_and_shows_endpoints(logged, project):
    from django.core.files.uploadedfile import SimpleUploadedFile

    from projects.tests import SAMPLE_SPEC

    body = json.dumps(SAMPLE_SPEC).encode()
    r = logged.post(
        f"/projects/{project.pk}/api",
        {"file": SimpleUploadedFile("openapi.json", body, content_type="application/json")},
    )
    assert r.status_code == 302
    body = logged.get(f"/projects/{project.pk}/api").content.decode()
    assert "/tasks" in body
    assert "tasks" in body


def test_api_tab_requires_membership(client, outsider, project):
    client.login(username="outsider", password="pw12345678")
    assert client.get(f"/projects/{project.pk}/api").status_code == 404


def test_git_panel_forms_are_htmx():
    """git 뷰는 전부 _panel 조각만 돌려준다 — 평범한 POST면 레이아웃 없는 조각 페이지로 튄다."""
    from pathlib import Path

    src = (Path(__file__).parent / "templates" / "tasks" / "_git.html").read_text(encoding="utf-8")
    assert 'method="post"' not in src
    assert src.count("<form") == src.count("hx-post")


def test_panel_survives_changelog_without_actor(logged, task):
    """GitHub 웹훅이 남긴 로그는 actor가 비고 external_actor만 있다."""
    from tasks.models import ChangeLog

    ChangeLog.objects.create(
        target_type="task",
        target_id=task.pk,
        field="status",
        old_value="todo",
        new_value="doing",
        actor=None,
        external_actor="ghost",
        source="gh",
    )
    body = logged.get(f"/tasks/{task.pk}/panel")
    assert body.status_code == 200
    assert "ghost" in body.content.decode()


def test_governance_page(client, org, admin, member):
    client.force_login(admin)
    r = client.get(f"/orgs/{org.pk}/governance")
    assert r.status_code == 200 and "개발 거버넌스" in r.content.decode()
    assert client.post(f"/orgs/{org.pk}/governance", {"text": "# 우리 규칙"}).status_code == 302
    org.refresh_from_db()
    assert org.governance == "# 우리 규칙"
    # 멤버는 보기만 한다. POST해도 안 바뀐다.
    client.force_login(member)
    assert client.get(f"/orgs/{org.pk}/governance").status_code == 200
    client.post(f"/orgs/{org.pk}/governance", {"text": "몰래"})
    org.refresh_from_db()
    assert org.governance == "# 우리 규칙"


def test_outsider_admin_page_still_404(client, outsider, org):
    """조직 밖 사람에게는 존재를 숨긴다 — 이쪽은 계속 404다."""
    client.force_login(outsider)
    assert client.get(f"/orgs/{org.pk}/teams").status_code == 404


def test_dialog_opened_directly_gets_the_shell(logged, project):
    """모달 조각을 주소로 직접 열면 조각이 맨몸으로 보이지 말고 셸 안에 담겨야 한다."""
    r = logged.get(f"/projects/{project.pk}/edit")
    assert r.status_code == 200
    body = r.content.decode()
    assert "app.css" in body and "프로젝트 수정" in body
    frag = logged.get(f"/projects/{project.pk}/edit", headers={"HX-Request": "true"})
    assert "app.css" not in frag.content.decode()


# ---------- 프로젝트 문서 화면 ----------


def test_docs_tab_is_always_there(logged, project, settings):
    """GitHub를 붙이지 않아도 문서 탭은 있어야 한다 — 기록할 곳이 사라지면 안 된다."""
    settings.GITHUB_ENABLED = False
    body = logged.get(f"/projects/{project.pk}").content.decode()
    assert f"/projects/{project.pk}/docs" in body
    assert f"/projects/{project.pk}/repo" not in body  # GitHub 탭만 사라진다


def test_file_upload_controls_are_keyboard_focusable(logged, org, project):
    pages = (
        (f"/projects/{project.pk}/docs", "doc-upload-file"),
        (f"/projects/{project.pk}/api", "api-upload-file"),
        (f"/orgs/{org.pk}/notes?scope=all", "note-upload-file"),
    )
    for url, control_id in pages:
        body = logged.get(url).content.decode()
        control = re.search(rf'<input[^>]*id="{re.escape(control_id)}"[^>]*>', body)
        assert control is not None
        assert 'class="file-upload-input"' in control.group()
        assert " hidden" not in control.group()
        assert f'for="{control_id}"' in body
    assert 'style="display:none"' not in logged.get(f"/projects/{project.pk}/docs").content.decode()


def test_doc_new_then_edit_through_the_screen(logged, project, member):
    r = logged.post(f"/projects/{project.pk}/docs/new")
    assert r.status_code == 302 and "?doc=" in r.headers["Location"]
    doc_id = r.headers["Location"].split("?doc=")[1]

    r = logged.post(f"/docs/{doc_id}/save", {"field": "title", "value": "운영 절차", "version": 1})
    assert r.status_code == 204 and r["X-Note-Version"] == "2"

    body = logged.get(f"/projects/{project.pk}/docs?doc={doc_id}").content.decode()
    assert "운영 절차" in body


def test_doc_save_reports_conflict(logged, project):
    doc_id = logged.post(f"/projects/{project.pk}/docs/new").headers["Location"].split("?doc=")[1]
    logged.post(f"/docs/{doc_id}/save", {"field": "body_md", "value": "먼저", "version": 1})
    r = logged.post(f"/docs/{doc_id}/save", {"field": "body_md", "value": "나중", "version": 1})
    assert r.status_code == 409


def test_doc_is_hidden_from_other_orgs(client, project, outsider):
    from projects.docs import create_doc

    doc = create_doc(project=project, actor=project.created_by)
    client.login(username="outsider", password="pw12345678")
    assert client.get(f"/projects/{project.pk}/docs").status_code == 404
    assert client.post(f"/docs/{doc.pk}/save", {"field": "title", "value": "x"}).status_code == 404


def test_docs_first_one_opens_by_default(logged, project):
    from projects.docs import create_doc

    create_doc(project=project, actor=project.created_by, title="개요", body_md="배경")
    body = logged.get(f"/projects/{project.pk}/docs").content.decode()
    assert 'id="doc-editor"' in body and "개요" in body


# ---------- GitHub를 끈 상태 ----------


def test_github_screens_404_when_disabled(logged, project, task, settings):
    """켜져 있지 않으면 404다. 예전에는 PEM을 읽으려다 500이 났다."""
    settings.GITHUB_ENABLED = False
    assert logged.get(f"/projects/{project.pk}/repo").status_code == 404
    assert logged.post(f"/projects/{project.pk}/repo/settings").status_code == 404
    assert logged.post(f"/tasks/{task.pk}/git/branch").status_code == 404
    assert logged.post(f"/tasks/{task.pk}/git/issue").status_code == 404


def test_task_panel_works_without_github(logged, task, settings):
    settings.GITHUB_ENABLED = False
    body = logged.get(f"/tasks/{task.pk}").content.decode()
    assert "GitHub" not in body
    for must_stay in ("진행 메모", "체크리스트", "참고 자료", "완료 조건"):
        assert must_stay in body


def test_task_refs_can_link_a_project_doc(logged, project, task):
    from projects.docs import create_doc

    doc = create_doc(project=project, actor=project.created_by, title="설계 결정")
    r = logged.post(f"/tasks/{task.pk}/docs/link", {"doc": doc.pk}, headers=HX)
    assert r.status_code == 200
    body = r.content.decode()
    assert "설계 결정" in body and "문서" in body
    assert list(task.docs.all()) == [doc]

    # 이미 걸린 문서는 후보 셀렉트에 다시 나오지 않는다
    assert "프로젝트 문서에서 고르기…" not in body

    r = logged.post(f"/tasks/{task.pk}/docs/{doc.pk}/unlink", headers=HX)
    assert r.status_code == 200
    assert not task.docs.exists()


def test_task_panel_shows_linked_docs_on_first_render(logged, project, task):
    """_refs.html은 패널 최초 렌더와 조각 갱신 양쪽에서 쓰인다 — 한쪽만 채우면 새로고침 전까지 안 보인다."""
    from projects.docs import create_doc, link_task

    doc = create_doc(project=project, actor=project.created_by, title="설계 결정")
    link_task(doc, task, project.created_by)
    body = logged.get(f"/tasks/{task.pk}").content.decode()
    assert "설계 결정" in body


def test_task_refs_rejects_doc_from_another_project(logged, project, org, admin, task):
    from projects.docs import create_doc
    from projects.services import create_project

    other = create_project(org=org, name="다른 프로젝트", actor=admin, owners=[admin])
    doc = create_doc(project=other, actor=admin, title="남의 문서")
    r = logged.post(f"/tasks/{task.pk}/docs/link", {"doc": doc.pk}, headers=HX)
    assert r.status_code == 200
    assert "같은 프로젝트의 태스크여야 합니다." in r.content.decode()
    assert not task.docs.exists()


# ---------- 설정 화면 (IMPL-PLAN-4 §7) ----------


def test_org_settings_admin_edits_member_reads_only(client, org, admin, member):
    # as_admin·logged는 둘 다 같은 client fixture를 로그인시키므로 한 테스트에서 같이
    # 쓰면 나중 로그인이 앞선 로그인을 덮어쓴다 — 여기서는 force_login으로 직접 오간다.
    client.force_login(admin)
    r = client.get(f"/orgs/{org.pk}/settings")
    assert r.status_code == 200 and "기본 중요도" in r.content.decode()

    r = client.post(
        f"/orgs/{org.pk}/settings",
        {"task.require_done_when": "on", "unlock__task.require_done_when": "on"},
    )
    assert r.status_code == 302
    org.refresh_from_db()
    assert org.settings.get("task.require_done_when") is True
    assert "task.require_done_when" not in (org.settings.get("_locked") or [])

    # 멤버는 링크도 못 보고, URL로 와도 읽기만 한다 — POST해도 안 바뀐다.
    client.force_login(member)
    assert f"/orgs/{org.pk}/settings" not in client.get(f"/orgs/{org.pk}").content.decode()
    r = client.get(f"/orgs/{org.pk}/settings")
    assert r.status_code == 200 and "조직 관리자만 고칠 수 있습니다" in r.content.decode()
    client.post(f"/orgs/{org.pk}/settings", {"task.require_done_when": "off"})
    org.refresh_from_db()
    assert org.settings.get("task.require_done_when") is True


def test_org_settings_outsider_404(client, outsider, org):
    client.force_login(outsider)
    assert client.get(f"/orgs/{org.pk}/settings").status_code == 404


def test_org_lock_blocks_project_override(as_admin, org, project):
    # unlock__를 보내지 않으면 그 회차의 모든 덮어쓸 수 있는 항목이 잠긴다.
    r = as_admin.post(f"/orgs/{org.pk}/settings", {"task.require_done_when": "on"})
    assert r.status_code == 302
    org.refresh_from_db()
    assert "task.require_done_when" in org.settings.get("_locked", [])

    body = as_admin.get(f"/projects/{project.pk}/settings").content.decode()
    assert "조직에서 잠금" in body
    assert 'id="setting-task.require_done_when"' not in body

    as_admin.post(f"/projects/{project.pk}/settings", {"task.require_done_when": "off"})
    project.refresh_from_db()
    assert "task.require_done_when" not in (project.settings or {})


def test_project_settings_roundtrip_and_governance_extra(as_admin, project):
    r = as_admin.post(f"/projects/{project.pk}/settings", {"task.require_done_when": "on"})
    assert r.status_code == 302
    project.refresh_from_db()
    assert project.settings.get("task.require_done_when") is True

    r = as_admin.post(
        f"/projects/{project.pk}/settings",
        {"action": "governance_extra", "governance_extra": "추가 규칙"},
    )
    assert r.status_code == 302
    project.refresh_from_db()
    assert project.governance_extra == "추가 규칙"


def test_project_settings_readonly_for_non_owner_member(logged, project):
    """project.settings_by 기본값은 '프로젝트 관리자'다 — 관리자가 아닌 멤버는 읽기만 한다."""
    r = logged.get(f"/projects/{project.pk}/settings")
    assert r.status_code == 200 and "프로젝트 관리자만 고칠 수 있습니다" in r.content.decode()
    logged.post(f"/projects/{project.pk}/settings", {"task.require_done_when": "on"})
    project.refresh_from_db()
    assert project.settings == {}


def test_project_settings_outsider_404(client, outsider, project):
    client.force_login(outsider)
    assert client.get(f"/projects/{project.pk}/settings").status_code == 404


def test_preferences_roundtrip(logged, member):
    r = logged.get("/settings/preferences")
    assert r.status_code == 200 and "환경설정" in r.content.decode()
    r = logged.post("/settings/preferences", {"user.start_page": "me"})
    assert r.status_code == 302
    member.refresh_from_db()
    assert member.settings.get("user.start_page") == "me"


def test_settings_controls_have_programmatic_labels(client, member, admin, org, project):
    client.force_login(member)
    personal = client.get("/settings/preferences").content.decode()
    assert 'for="setting-user.notify_dm"' in personal
    assert 'id="setting-user.notify_kinds-d3"' in personal
    assert 'aria-describedby="setting-help-user.notify_hour"' in personal

    client.force_login(admin)
    organization = client.get(f"/orgs/{org.pk}/settings").content.decode()
    assert 'aria-label="기본 중요도 · 프로젝트 변경 허용"' in organization
    assert 'class="settings-save-bar"' in organization
    assert organization.count('class="card settings-section"') == 5

    project_page = client.get(f"/projects/{project.pk}/settings").content.decode()
    assert "{# 태스크 규칙" not in project_page
    assert "프로젝트 설정 저장" in project_page
    assert "거버넌스 저장" in project_page


def test_governance_shows_enforced_settings(as_admin, org):
    body = as_admin.get(f"/orgs/{org.pk}/governance").content.decode()
    assert "설정에서 강제 중" not in body

    as_admin.post(f"/orgs/{org.pk}/settings", {"task.require_done_when": "on"})
    body = as_admin.get(f"/orgs/{org.pk}/governance").content.decode()
    assert "설정에서 강제 중" in body
    assert "완료 조건 필수" in body


def test_note_scope_filter_is_a_list_not_chips(logged, org, project, member):
    """범위는 프로젝트 수만큼 늘어난다 — 칩 줄이 아니라 고르는 목록이어야 한다."""
    body = logged.get(f"/orgs/{org.pk}/notes?scope=all").content.decode()
    assert '<select name="scope"' in body
    assert f'<option value="{project.pk}"' in body
    # 태그를 고른 상태로 범위를 바꿔도 태그가 유지된다.
    body = logged.get(f"/orgs/{org.pk}/notes?scope=all&tag=%EA%B8%B0%ED%9A%8D").content.decode()
    assert 'name="tag"' in body


def test_archive_lives_in_project_settings_not_the_header(client, org, project, admin):
    """보관·삭제는 설정 페이지에 둔다. 머리글의 ⋯ 메뉴는 목록/보드 토글 옆이라 잘못된 자리였다."""
    client.force_login(admin)
    head = client.get(f"/projects/{project.pk}").content.decode()
    assert "프로젝트 보관" not in head
    body = client.get(f"/projects/{project.pk}/settings").content.decode()
    assert "프로젝트 보관" in body
    assert "미완료까지 취소하고 보관" in body
    assert "프로젝트 삭제" not in body  # 보관 전에는 지울 수 없다


def test_settings_shows_restore_and_delete_once_archived(client, org, project, admin):
    from projects.services import archive_project

    client.force_login(admin)
    archive_project(project, actor=admin)
    body = client.get(f"/projects/{project.pk}/settings").content.decode()
    assert "보관 해제" in body
    assert "프로젝트 삭제" in body


def test_project_settings_groups_share_one_card_with_the_save_button(client, project, admin):
    """태스크 규칙·프로젝트 권한·알림은 한 번에 저장되는 한 벌이다 — 카드도 하나다."""
    client.force_login(admin)
    body = client.get(f"/projects/{project.pk}/settings").content.decode()
    rules = body[
        body.index('<form method="post" class="settings-form project-settings-form">') : body.index(
            "프로젝트 설정 저장"
        )
    ]
    assert rules.count('<section class="card') == 1


def test_webmcp_script_only_for_logged_in(logged, org, project):
    """WebMCP 도구는 로그인한 세션으로 API를 부른다. 로그인 전 화면에는 실리지 않는다."""
    assert "webmcp.js" in logged.get("/today").content.decode()
    logged.logout()
    assert "webmcp.js" not in logged.get("/login").content.decode()


def test_webmcp_browser_requirements(logged, org, project, settings):
    """스펙이 요구하는 두 가지. 오리진 키 클러스터가 아니면 registerTool이 SecurityError로 죽고,
    오리진 트라이얼 토큰이 없으면 크롬·엣지에서 document.modelContext 자체가 없다."""
    assert logged.get("/today").headers["Origin-Agent-Cluster"] == "?1"
    settings.WEBMCP_ORIGIN_TRIAL = "TOKEN123"
    assert 'http-equiv="origin-trial" content="TOKEN123"' in logged.get("/today").content.decode()


def test_webmcp_tool_paths_exist_in_api():
    """webmcp.js가 부르는 경로가 실제 API에 다 있는지. 엔드포인트가 바뀌면 여기서 깨진다."""
    from api.api import api as ninja_api

    js = (settings.BASE_DIR / "web" / "static" / "webmcp.js").read_text(encoding="utf-8")
    paths = set(re.findall(r'path:\s*"([^"]+)"', js))
    assert len(paths) >= 8
    assert paths <= set(ninja_api.get_openapi_schema()["paths"])


# ---------- MCP 커넥터 OAuth ----------


def _register(client, uris=("https://claude.ai/api/mcp/auth_callback",)):
    r = client.post(
        "/oauth/register",
        json.dumps({"client_name": "Claude", "redirect_uris": list(uris)}),
        content_type="application/json",
    )
    assert r.status_code == 201, r.content
    return r.json()["client_id"]


def _pkce(verifier="v" * 43):
    from accounts.models import pkce_challenge

    return verifier, pkce_challenge(verifier)


def test_oauth_metadata_advertises_pkce_and_registration(client, settings):
    settings.SITE_URL = "https://project.example.test"
    m = client.get("/.well-known/oauth-authorization-server").json()
    assert m["issuer"] == "https://project.example.test"
    assert m["registration_endpoint"] == "https://project.example.test/oauth/register"
    assert m["code_challenge_methods_supported"] == ["S256"]
    assert m["token_endpoint_auth_methods_supported"] == ["none"]


def test_register_refuses_plaintext_redirect(client):
    r = client.post(
        "/oauth/register",
        json.dumps({"redirect_uris": ["http://evil.example/cb"]}),
        content_type="application/json",
    )
    assert r.status_code == 400
    assert r.json()["error"] == "invalid_redirect_uri"


def test_oauth_full_flow_issues_a_working_token(client, logged, member):
    """등록 → 동의 → 코드 교환. 나오는 것은 평범한 ApiToken이라 /settings/tokens에 보인다."""
    from accounts.models import ApiToken

    client_id = _register(client)
    verifier, challenge = _pkce()
    params = {
        "response_type": "code",
        "client_id": client_id,
        "redirect_uri": "https://claude.ai/api/mcp/auth_callback",
        "code_challenge": challenge,
        "code_challenge_method": "S256",
        "state": "xyz",
    }
    assert "허용" in logged.get("/oauth/authorize", params).content.decode()

    r = logged.post("/oauth/authorize", {**params, "decision": "allow", "scope": "write"})
    assert r.status_code == 302
    location = r.headers["Location"]
    assert location.startswith("https://claude.ai/api/mcp/auth_callback?")
    assert "state=xyz" in location
    code = re.search(r"code=([^&]+)", location).group(1)

    r = client.post(
        "/oauth/token",
        {
            "grant_type": "authorization_code",
            "code": code,
            "client_id": client_id,
            "redirect_uri": params["redirect_uri"],
            "code_verifier": verifier,
        },
    )
    assert r.status_code == 200, r.content
    body = r.json()
    assert body["token_type"] == "Bearer" and body["scope"] == "write"
    token = ApiToken.authenticate(body["access_token"])
    assert token is not None and token.user == member and token.scope == "write"

    # 같은 코드를 두 번 쓰지 못한다.
    again = client.post(
        "/oauth/token",
        {
            "grant_type": "authorization_code",
            "code": code,
            "client_id": client_id,
            "redirect_uri": params["redirect_uri"],
            "code_verifier": verifier,
        },
    )
    assert again.status_code == 400 and again.json()["error"] == "invalid_grant"


def test_oauth_token_needs_the_matching_verifier(client, logged):
    """PKCE가 유일한 방어선이다 — 공개 클라이언트라 비밀이 없다."""
    client_id = _register(client)
    _, challenge = _pkce()
    r = logged.post(
        "/oauth/authorize",
        {
            "response_type": "code",
            "client_id": client_id,
            "redirect_uri": "https://claude.ai/api/mcp/auth_callback",
            "code_challenge": challenge,
            "code_challenge_method": "S256",
            "decision": "allow",
        },
    )
    code = re.search(r"code=([^&]+)", r.headers["Location"]).group(1)
    r = client.post(
        "/oauth/token",
        {
            "grant_type": "authorization_code",
            "code": code,
            "client_id": client_id,
            "redirect_uri": "https://claude.ai/api/mcp/auth_callback",
            "code_verifier": "틀린값" * 10,
        },
    )
    assert r.status_code == 400 and r.json()["error"] == "invalid_grant"


def test_oauth_never_redirects_to_an_unregistered_uri(logged, client):
    """등록되지 않은 redirect_uri로 되돌려 보내면 이 화면이 오픈 리다이렉터가 된다."""
    client_id = _register(client)
    _, challenge = _pkce()
    r = logged.get(
        "/oauth/authorize",
        {
            "response_type": "code",
            "client_id": client_id,
            "redirect_uri": "https://evil.example/steal",
            "code_challenge": challenge,
            "code_challenge_method": "S256",
        },
    )
    assert r.status_code == 400
    assert "Location" not in r.headers


def test_oauth_authorize_requires_login(client):
    client_id = _register(client)
    r = client.get("/oauth/authorize", {"client_id": client_id})
    assert r.status_code == 302 and r.headers["Location"].startswith("/login")


def test_oauth_deny_sends_access_denied(logged, client):
    client_id = _register(client)
    _, challenge = _pkce()
    r = logged.post(
        "/oauth/authorize",
        {
            "response_type": "code",
            "client_id": client_id,
            "redirect_uri": "https://claude.ai/api/mcp/auth_callback",
            "code_challenge": challenge,
            "code_challenge_method": "S256",
            "decision": "deny",
        },
    )
    assert "error=access_denied" in r.headers["Location"]
