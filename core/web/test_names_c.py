"""IMPL-PLAN-13 갈래 C: 웹 화면의 사람 이름은 그 화면(행)의 조직 표시 이름이다(§4.1·§4.2·§4.6)."""

import re
from datetime import timedelta
from pathlib import Path

import pytest
from django.db import connection
from django.test.utils import CaptureQueriesContext
from django.urls import reverse

from accounts.models import User
from common.dates import today_kst
from orgs.models import OrgMembership
from orgs.services import create_org
from projects.services import create_project
from tasks.services import create_task

pytestmark = pytest.mark.django_db

WEB = Path(__file__).resolve().parent
# 계정 표시 이름을 그대로 쓰는 자리(§4.2). 그 밖의 `.display_name` 출력은 조직 이름을 건너뛴 것이다.
ALLOWED = {
    "base.html": None,  # 내 메뉴 = 계정 이름
    "today/_head.html": None,  # 머리말 인사 = 계정 이름
    # 관리자 구성원 목록: 조직 이름 아래 계정 이름·아이디, 표시 이름 칸 자리표시 = 계정 이름
    "orgs/teams.html": r"\br\.m\.user\.display_name\b",
    # 본인 조직 표시 이름 칸의 자리표시 = 계정 이름(비우면 이 이름이 보인다)
    "orgs/member_info.html": r"\{\{ user\.display_name \}\}",
    # user_brief dict 키 — B 갈래가 조직 이름으로 채운다(reports/services.py)
    "orgs/capacity.html": r"\b[rc]\.user\.display_name\b",
    # DiscordChannelAlert.display_name = Discord 닉네임(사람 계정과 무관)
    "orgs/discord.html": r"\b[am]\.display_name\|default:[am]\.discord_user_id",
}
# C 갈래 뷰: DB 이름순은 조직 표시 이름과 어긋난다 → sort_by_name
VIEWS = (
    "common me projects tasks split teams work_requests assist transcribe ops_orgs ops_users"
).split()


def test_no_raw_display_name_in_templates():
    bad = []
    for path in (WEB / "templates").rglob("*.html"):
        rel = path.relative_to(WEB / "templates").as_posix()
        if rel.startswith("ops/") or (rel in ALLOWED and ALLOWED[rel] is None):
            continue  # 운영 콘솔 = 계정 이름 + 실명
        for no, line in enumerate(path.read_text(encoding="utf-8").splitlines(), 1):
            if rel in ALLOWED:
                line = re.sub(ALLOWED[rel], "", line)
            if re.search(r"\.display_name\b", line):
                bad.append(f"{rel}:{no}")
    assert bad == []


def test_views_do_not_sort_by_account_name():
    for name in VIEWS:
        src = (WEB / "views" / f"{name}.py").read_text(encoding="utf-8")
        assert 'order_by("display_name")' not in src, name
        assert 'order_by("user__display_name")' not in src, name


def _nick(org, user, nickname):
    OrgMembership.objects.filter(org=org, user=user).update(nickname=nickname)


def _task(project, actor, assignee, title):
    return create_task(
        project=project,
        title=title,
        actor=actor,
        source="web",
        assignee=assignee,
        due_date=today_kst() + timedelta(days=3),
    )


def test_task_panel_uses_org_name(client, org, project, admin, member):
    _nick(org, member, "산돌팀원")
    t = _task(project, admin, member, "패널 이름")
    client.force_login(admin)
    html = client.get(reverse("task_detail", args=[t.pk])).content.decode()
    assert "산돌팀원" in html  # 담당자 고르기·이력
    assert ">팀원<" not in html


def test_rows_use_each_rows_org(client, org, project, admin, member):
    other = create_org("다른조직", "", admin)
    OrgMembership.objects.create(org=other, user=member, role="member", nickname="다른별명")
    _nick(org, member, "산돌별명")
    p2 = create_project(org=other, name="다른 프로젝트", actor=admin, owners=[admin])
    _task(project, admin, member, "첫째 일")
    _task(p2, admin, member, "둘째 일")
    client.force_login(admin)
    html = client.get(f"/me?member={member.pk}").content.decode()
    assert "산돌별명" in html and "다른별명" in html


def test_real_name_org_and_ops(client, org, project, admin, member):
    org.member_fields = {"show_real_name": True, "fields": []}
    org.save(update_fields=["member_fields"])
    t = _task(project, admin, member, "실명 표시")
    client.force_login(admin)
    assert "김팀원" in client.get(reverse("task_detail", args=[t.pk])).content.decode()
    User.objects.filter(pk=admin.pk).update(is_staff=True)
    html = client.get("/ops/users?q=김팀").content.decode()  # 운영 검색은 실명도 찾는다
    assert "member1" in html and "김팀원" in html


def test_panel_queries_flat_in_member_count(
    client, org, project, admin, member, django_assert_num_queries
):
    """구성원 이름표는 조직당 쿼리 1개 — 사람 수가 늘어도 패널 쿼리 수는 같다."""
    t = _task(project, admin, member, "쿼리 수")
    client.force_login(admin)
    url = reverse("task_detail", args=[t.pk])
    client.get(url)

    with CaptureQueriesContext(connection) as q:
        client.get(url)
    for i in range(10):
        u = User.objects.create_user(f"x{i}", display_name=f"사람{i}", real_name="실명")
        OrgMembership.objects.create(org=org, user=u, nickname=f"별명{i}")
    with django_assert_num_queries(len(q)):
        assert client.get(url).status_code == 200
