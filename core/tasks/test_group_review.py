"""Sol 검토(R-sol-review-r11-12) R4·R5·R8 재현 — 상위·하위 경쟁, 숨긴 상위 번호, 프로젝트별 집계."""

import threading
from datetime import timedelta

import pytest
from django.db import close_old_connections, connection

from accounts.models import ApiToken, User
from common.dates import today_kst
from common.errors import ConflictError, ServiceError
from orgs.models import OrgMembership
from orgs.services import add_team_member, create_team
from projects.services import create_project
from reports.services import org_status, weekly
from tasks import services as ts
from tasks.brief import task_brief
from tasks.models import Task

pytestmark = pytest.mark.django_db


def _t(project, actor, title="일", **kw):
    kw.setdefault("due_date", today_kst() + timedelta(days=5))
    return ts.create_task(project=project, title=title, actor=actor, source="web", **kw)


def _go(task, status, actor):
    fresh = Task.objects.get(pk=task.pk)
    return ts.transition(fresh, status, actor=actor, source="web", expected_version=fresh.version)


# ---------- R4: 오래된 상위 캐시로 불변식 깨기(순차 재현) ----------


def test_r4_stale_group_cache_cannot_reopen_sub(project, admin, member):
    top = _t(project, member, "상위")
    sub = _t(project, member, group=top)
    _go(sub, "done", member)
    stale = Task.objects.select_related("group").get(pk=sub.pk)
    assert stale.group.status == "todo"  # 열린 상위를 캐시
    _go(top, "done", member)
    with pytest.raises(ServiceError) as e:
        ts.transition(stale, "todo", actor=admin, source="web", expected_version=stale.version)
    assert "완료·취소 상태" in e.value.errors["status"]
    assert Task.objects.get(pk=sub.pk).status == "done"


def test_r4_stale_group_object_cannot_take_new_sub(project, member):
    top = _t(project, member, "상위")
    stale = Task.objects.get(pk=top.pk)
    _go(top, "cancelled", member)
    with pytest.raises(ServiceError):
        _t(project, member, group=stale)
    other = _t(project, member, "넣을 것")
    with pytest.raises(ServiceError):
        ts.set_group(other, stale, actor=member, expected_version=other.version)
    assert not Task.objects.filter(group=top).exists()


def test_r4_stale_closing_sees_new_sub(project, member):
    top = _t(project, member, "상위")
    stale = Task.objects.get(pk=top.pk)
    _t(project, member, group=top)
    with pytest.raises(ServiceError):
        ts.transition(stale, "done", actor=member, source="web", expected_version=stale.version)


def test_r4_regroup_while_reopening_conflicts(project, member):
    """재개하려는 하위가 그사이 다른 상위로 옮겨졌으면 오래된 관계로 검사하지 않는다."""
    a, b = _t(project, member, "가"), _t(project, member, "나")
    sub = _t(project, member, group=a)
    _go(sub, "done", member)
    stale = Task.objects.get(pk=sub.pk)
    fresh = Task.objects.get(pk=sub.pk)
    ts.set_group(fresh, b, actor=member, expected_version=fresh.version)
    _go(b, "done", member)
    with pytest.raises((ServiceError, ConflictError)):
        ts.transition(stale, "todo", actor=member, source="web", expected_version=stale.version)
    assert Task.objects.get(pk=sub.pk).status == "done"


# ---------- R4: Postgres 두 연결 경쟁 ----------

PG = connection.vendor == "postgresql"


def _race(fn_a, fn_b):
    barrier = threading.Barrier(2)
    errors = []

    def run(fn):
        try:
            barrier.wait(5)
            fn()
        except (ServiceError, ConflictError):
            pass
        except Exception as e:  # noqa: BLE001 — 테스트가 그대로 보여 준다
            errors.append(e)
        finally:
            close_old_connections()
            connection.close()

    ts_ = [threading.Thread(target=run, args=(f,)) for f in (fn_a, fn_b)]
    for t in ts_:
        t.start()
    for t in ts_:
        t.join(20)
    assert not errors, errors


@pytest.fixture
def pg_flushable():
    """transaction=True 테스트는 끝에 표를 TRUNCATE한다. 감사 로그의 append-only 트리거(ops 0001)가 이를
    막으므로 **테스트 DB에서만** 정리 직전에 끈다(이 fixture가 DB 정리보다 먼저 내려간다)."""
    yield
    with connection.cursor() as c:
        c.execute("ALTER TABLE ops_opsauditlog DISABLE TRIGGER ops_audit_no_truncate")


def _invariant_ok():
    return not Task.objects.filter(group__status__in=Task.CLOSED, status__in=Task.OPEN).exists()


@pytest.mark.skipif(not PG, reason="Postgres 두 연결이 필요하다(DATABASE_URL=postgres…)")
@pytest.mark.django_db(transaction=True)
def test_r4_pg_reopen_vs_close(pg_flushable, org, project, member):
    for _ in range(15):
        top = _t(project, member, "상위")
        sub = _t(project, member, group=top)
        _go(sub, "done", member)
        _race(lambda g=top: _go(g, "done", member), lambda s=sub: _go(s, "todo", member))
        assert _invariant_ok()


@pytest.mark.skipif(not PG, reason="Postgres 두 연결이 필요하다(DATABASE_URL=postgres…)")
@pytest.mark.django_db(transaction=True)
def test_r4_pg_create_vs_close(pg_flushable, org, project, member):
    for _ in range(15):
        top = _t(project, member, "상위")
        _race(lambda g=top: _go(g, "done", member), lambda g=top: _t(project, member, group=g))
        assert _invariant_ok()


# ---------- R5: 숨긴 상위 번호 ----------


@pytest.fixture
def hidden_group(org, admin, member):
    """비공개 프로젝트의 상위·하위. 하위만 공개 프로젝트에 연결 → 바깥 사람은 하위만 본다."""
    viewer = User.objects.create_user("vw", password="pw12345678", display_name="바깥")
    OrgMembership.objects.create(org=org, user=viewer, role="member")
    team = create_team(org=org, name="비밀", actor=admin)
    add_team_member(team, member, admin)
    secret = create_project(
        org=org, name="비공개", actor=admin, owners=[admin], teams=[team], visibility="teams"
    )
    public = create_project(org=org, name="공개", actor=admin)
    top = _t(secret, member, "비밀 상위")
    sub = _t(secret, member, "하위", group=top)
    ts.approve_link(ts.link_project(sub, public, actor=member, confirm_widening=True), actor=admin)
    assert not ts.can_view_task(viewer, top) and ts.can_view_task(viewer, sub)
    _, raw = ApiToken.issue(viewer, "t", "read", for_ai=False)
    return top, sub, viewer, {"Authorization": f"Bearer {raw}"}


def test_r5_api_hides_group_id_and_history(client, hidden_group, member):
    top, sub, viewer, h = hidden_group
    d = client.get(f"/api/tasks/{sub.pk}", headers=h).json()
    assert d["group"] is None and d["group_id"] is None
    items = client.get("/api/tasks", headers=h).json()["items"]
    assert [x["group_id"] for x in items if x["id"] == sub.pk] == [None]
    hist = client.get(f"/api/tasks/{sub.pk}/history", headers=h).json()
    assert top.number not in str(hist)
    assert any(x["field"] == "group" and x["new_value"] == ts.HIDDEN_TASK for x in hist)
    # 볼 수 있는 사람에게는 그대로
    _, raw = ApiToken.issue(member, "m", "read", for_ai=False)
    mine = client.get(f"/api/tasks/{sub.pk}", headers={"Authorization": f"Bearer {raw}"}).json()
    assert mine["group_id"] == top.pk


def test_r5_bot_brief_needs_public_group(hidden_group):
    top, sub, _, _ = hidden_group
    t = Task.objects.get(pk=sub.pk)
    ts.attach_group_visible([t])  # viewer None = 봇·채널
    assert task_brief(t)["group_id"] is None
    assert task_brief(Task.objects.get(pk=sub.pk))["group_id"] is None  # 표시 안 하면 닫힘


# ---------- R8: 프로젝트별 집계도 잎만 ----------


def test_r8_by_project_counts_leaves(org, project, member):
    top = _t(project, member, "상위")
    _t(project, member, "가", group=top)
    _t(project, member, "나", group=top)
    st = org_status(org, viewer=member)
    assert st["counts"]["open"] == 2
    assert [p["open"] for p in st["by_project"] if p["id"] == project.pk] == [2]
    monday = today_kst() - timedelta(days=today_kst().weekday())
    wk = weekly(org, monday, viewer=member)
    assert [p["open"] for p in wk["by_project"] if p["project"]["id"] == project.pk] == [2]
