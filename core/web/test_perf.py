"""성능·안정성 회귀 테스트(IMPL-PLAN-7 H).

- N+1: 규모 2와 10에서 같은 주소를 불러 쿼리 수가 같아야 한다. 늘면 어딘가 루프 안에서 조회한다.
- SSE(/events): 사용자당·전체 동시 연결 상한, 비공개 프로젝트 태스크를 못 보는 멤버에게 안 흘림.
- 초과 판정: 화면·집계가 프로젝트별 유예(`task.overdue_grace_days`)를 Discord 알림과 같이 본다.
"""

from datetime import timedelta
from itertools import count

import pytest
from django.db import connection
from django.test.utils import CaptureQueriesContext

from accounts.models import User
from common.dates import today_kst
from orgs.models import OrgMembership
from orgs.services import add_team_member, create_team
from projects.services import create_milestone, create_project
from tasks.services import add_link, checklist_add, create_task, today_add

_seq = count()


def _seed(org, admin, member, k):
    """k묶음을 더한다: 팀·팀원·프로젝트(공개/팀 한정)·링크·마일스톤·태스크(체크리스트 포함)."""
    today = today_kst()
    for _ in range(k):
        i = next(_seq)
        u = User.objects.create_user(f"perf{i}", password="pw12345678", display_name=f"사람{i}")
        OrgMembership.objects.create(org=org, user=u, role="member")
        team = create_team(org=org, name=f"팀{i}", actor=admin)
        add_team_member(team, member, admin)
        add_team_member(team, u, admin)
        p = create_project(
            org=org,
            name=f"프로젝트{i}",
            actor=admin,
            owners=[admin],
            status="active",
            teams=[team],
            visibility="teams" if i % 2 else "org",
        )
        add_link(actor=admin, title="문서", url="https://example.com", project=p)
        create_milestone(
            project=p, name=f"M{i}", target_date=today + timedelta(days=5), actor=admin
        )
        for due in (today - timedelta(days=3), today, today + timedelta(days=2), None):
            t = create_task(
                project=p,
                title=f"할 일 {i}",
                actor=admin,
                source="web",
                assignee=member,
                due_date=due,
                no_due_reason="" if due else "미정",
            )
            checklist_add(t, "확인", actor=admin)
            if due == today + timedelta(days=2):
                today_add(member, t)


def _queries(client, url, headers=None) -> int:
    with CaptureQueriesContext(connection) as ctx:
        r = client.get(url, headers=headers or {})
    assert r.status_code == 200, (url, r.status_code)
    import os

    if os.environ.get("DUMP"):
        from collections import Counter

        c = Counter(q["sql"][:150] for q in ctx.captured_queries)
        print("\n".join(f"{n} {s}" for s, n in c.most_common(4)))
    return len(ctx.captured_queries)


WEB = [
    "/me",
    "/me?member=0",
    "/me?group=status",
    "/today",
    "/orgs/{org}",
    "/orgs/{org}/teams",
    "/orgs/{org}/roadmap",
    "/orgs/{org}/capacity",
    "/search?q=할",
]
API = [
    "/api/projects",
    "/api/orgs/{org}",
    "/api/orgs/{org}/teams",
    "/api/today",
    "/api/reports/weekly?org={org}&week_start={monday}",  # 주간 보고 by_project
]


@pytest.mark.parametrize("who", ["member", "admin"])
@pytest.mark.parametrize("url", WEB + API)
def test_query_count_flat(client, org, admin, member, who, url):
    """규모 2 → 10에서 쿼리 수가 같다."""
    from accounts.models import ApiToken

    user = member if who == "member" else admin
    today = today_kst()
    url = url.format(org=org.pk, monday=today - timedelta(days=today.weekday()))
    headers = None
    if url.startswith("/api/"):
        _, raw = ApiToken.issue(user, "t", "read", for_ai=False)
        headers = {"Authorization": f"Bearer {raw}"}
    else:
        client.force_login(user)
    _seed(org, admin, member, 2)
    small = _queries(client, url, headers)
    _seed(org, admin, member, 8)
    big = _queries(client, url, headers)
    assert big == small, f"{url} ({who}): 규모 2 → {small}회, 10 → {big}회"


# ---------- SSE ----------


@pytest.fixture
def ev(monkeypatch):
    from web.views import events

    # 테스트 DB 연결을 닫지 않게 한다.
    monkeypatch.setattr(events, "connection", type("C", (), {"close": staticmethod(lambda: None)}))
    yield events
    left = dict(events._active)
    events._active.clear()
    assert not left, "열린 스트림이 남았다 — 닫을 때 자리를 돌려주지 않는다"


def test_sse_per_user_limit(ev, org, member):
    from django.utils import timezone

    now = timezone.now()
    open_ = [ev._stream(member, org, now) for _ in range(ev.MAX_STREAMS_PER_USER)]
    for g in open_:
        assert next(g).startswith("retry: 2000")
    extra = ev._stream(member, org, now)
    assert list(extra) == [f"retry: {ev.BUSY_RETRY_MS}\n\n"]  # 즉시 닫힌다
    open_[0].close()  # 탭 하나를 닫으면 자리가 난다
    again = ev._stream(member, org, now)
    assert next(again).startswith("retry: 2000")
    for g in [*open_, again]:
        g.close()


def test_sse_total_limit(ev, monkeypatch, org, admin, member):
    from django.utils import timezone

    monkeypatch.setattr(ev, "MAX_STREAMS", 1)
    first = ev._stream(admin, org, timezone.now())
    next(first)
    busy = list(ev._stream(member, org, timezone.now()))
    assert busy == [f"retry: {ev.BUSY_RETRY_MS}\n\n"]
    first.close()


def test_sse_hides_private_project_tasks(ev, monkeypatch, org, admin, member):
    """담당 팀이 아닌 멤버에게 비공개 프로젝트 태스크의 번호를 보내지 않는다."""
    from django.utils import timezone

    secret = create_project(org=org, name="비공개", actor=admin, visibility="teams")
    open_ = create_project(org=org, name="공개", actor=admin)
    since = timezone.now() - timedelta(seconds=1)
    hidden = create_task(project=secret, title="숨김", actor=admin, source="web", no_due_reason="-")
    shown = create_task(project=open_, title="보임", actor=admin, source="web", no_due_reason="-")

    assert [pk for pk, _ in ev._changed_since(org, since, member)] == [shown.pk]
    assert {pk for pk, _ in ev._changed_since(org, since, admin)} == {hidden.pk, shown.pk}
    # 스트림도 같은 거름을 쓴다.
    monkeypatch.setattr(ev, "POLL_SECONDS", 0)
    monkeypatch.setattr(ev, "STREAM_SECONDS", 0.01)
    body = "".join(ev._stream(member, org, since))
    assert f'"id": {shown.pk}' in body and f'"id": {hidden.pk}' not in body


# ---------- 초과 판정: 프로젝트별 유예 ----------


def test_overdue_uses_project_grace(org, admin, member):
    """조직 유예 0, 프로젝트 A만 유예 3일. 이틀 지난 태스크는 A에선 초과가 아니다 —
    Discord 마감 알림(`deadline_alerts`)과 화면·집계가 같은 판정을 내린다."""
    from orgs.discord import deadline_alerts
    from projects.models import Project
    from projects.services import project_stats
    from reports.services import org_status
    from tasks.services import me_view
    from web.views.common import due_class

    today = today_kst()
    lenient = create_project(org=org, name="유예", actor=admin, status="active")
    strict = create_project(org=org, name="엄격", actor=admin, status="active")
    Project.objects.filter(pk=lenient.pk).update(settings={"task.overdue_grace_days": 3})
    late = today - timedelta(days=2)
    a = create_task(
        project=lenient, title="유예 안", actor=admin, source="web", assignee=member, due_date=late
    )
    b = create_task(
        project=strict, title="초과", actor=admin, source="web", assignee=member, due_date=late
    )
    a.project.refresh_from_db()

    assert due_class(a) == "" and due_class(b) == "overdue"
    assert {t.pk for t, kind in deadline_alerts(org, today) if kind == "overdue"} <= {b.pk}
    assert all(t.pk != a.pk for t, _ in deadline_alerts(org, today))
    assert project_stats(a.project)["overdue"] == 0
    assert project_stats(b.project)["overdue"] == 1
    st = org_status(org, viewer=admin)
    assert st["counts"]["overdue"] == 1
    assert {r["name"]: r["overdue"] for r in st["by_project"]} == {"유예": 0, "엄격": 1}
    view = me_view(member, due="overdue")
    assert [t.pk for g in view["groups"] for t in g["tasks"]] == [b.pk]


def test_overdue_locked_grace_ignores_project(org, admin, member):
    """조직이 잠근 항목은 프로젝트 값이 무시된다(effective 규칙 그대로)."""
    from projects.models import Project
    from projects.services import project_stats

    org.settings = {"task.overdue_grace_days": 0, "_locked": ["task.overdue_grace_days"]}
    org.save()
    p = create_project(org=org, name="잠김", actor=admin, status="active")
    Project.objects.filter(pk=p.pk).update(settings={"task.overdue_grace_days": 5})
    create_task(
        project=p, title="초과", actor=admin, source="web", due_date=today_kst() - timedelta(days=1)
    )
    p.refresh_from_db()
    assert project_stats(p)["overdue"] == 1
