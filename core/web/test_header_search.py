"""헤더 통합 검색: 펼침 패널 조각·권한·화면/설정 색인, 색인 메뉴 표와 템플릿 메뉴의 대조."""

import re
from pathlib import Path

import pytest

from common.dates import today_kst
from orgs.services import create_org
from projects.services import create_project
from tasks.services import create_task
from web import search_index

pytestmark = pytest.mark.django_db
TPL = Path(__file__).parent / "templates"


def _panel(client, q):
    return client.get("/search", {"panel": "1", "q": q}).content.decode()


def test_header_has_search_box_not_search_tab(client, org, member):
    client.force_login(member)
    body = client.get("/today").content.decode()
    nav = re.search(r'<nav class="nav".*?</nav>', body, re.S).group(0)
    assert "/search" not in nav
    assert 'id="hsearch-q"' in body and 'role="combobox"' in body and 'role="search"' in body


def test_panel_tasks_only_visible_ones(client, org, member, task, outsider):
    other = create_org("다른 조직", "", outsider)
    p = create_project(
        org=other, name="비밀 프로젝트", actor=outsider, owners=[outsider], status="active"
    )
    create_task(
        project=p, title="메뉴 비밀 작업", actor=outsider, source="web", due_date=today_kst()
    )
    client.force_login(member)
    body = _panel(client, "메뉴")
    assert f"TASK-{task.pk} 메뉴 누락 개선" in body and f'href="/tasks/{task.pk}"' in body
    assert "메뉴 비밀 작업" not in body
    assert 'role="listbox"' in body and 'data-summary="검색 결과' in body


def test_panel_admin_settings_only_for_admin(client, org, admin, member):
    client.force_login(member)
    body = _panel(client, "기본 중요도")
    assert "setting-task.default_priority" not in body and "결과가 없습니다" in body
    assert "구성원 관리" not in _panel(client, "구성원")  # 관리자 탭
    client.force_login(admin)
    body = _panel(client, "기본 중요도")
    assert f"/orgs/{org.pk}/settings?tab=work#setting-task.default_priority" in body
    assert "조직 설정 · 태스크·프로젝트" in body


def test_panel_tabs_and_personal_settings(client, org, member):
    client.force_login(member)
    body = _panel(client, "로드맵")
    assert f'href="/orgs/{org.pk}/roadmap"' in body and "조직 · 산돌이" in body
    body = _panel(client, "DM")  # 개인 설정 항목(이름)
    assert 'href="/settings/preferences#setting-user.notify_dm"' in body
    assert 'href="/settings/preferences"' in _panel(client, "환경설정")
    assert "/ops" not in _panel(client, "운영")  # 운영 콘솔은 staff만
    assert _panel(client, " ").strip() == ""


def test_full_search_page_lists_screens_and_settings(client, org, member):
    client.force_login(member)
    body = client.get("/search", {"q": "프로필"}).content.decode()
    assert "화면·탭" in body and 'href="/settings/profile"' in body


def test_index_menus_match_templates():
    """색인의 손 메뉴 표는 템플릿 메뉴를 옮긴 것이다. 메뉴를 바꾸면 search_index.py도 같이 바꾼다."""
    cases = [
        ("base.html", r'<nav class="nav".*?</nav>', search_index.HEADER_NAV),
        ("orgs/_tabs.html", r"<nav.*?</nav>", search_index.ORG_MENU),
        ("settings/_tabs.html", r"<nav.*?</nav>", search_index.SETTINGS_TABS),
    ]
    for name, block, menu in cases:
        nav = re.search(block, (TPL / name).read_text(encoding="utf-8"), re.S).group(0)
        nav = re.sub(r"\{% url '(\w+)'.*?%\}", r"URL:\1", re.sub(r"\{%(?! url).*?%\}", "", nav))
        pairs = re.findall(r"URL:(\w+)[^>]*>([^<]+)", nav)
        assert [(label.strip(), n) for n, label in pairs] == menu, name
