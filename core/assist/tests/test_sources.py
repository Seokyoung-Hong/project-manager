"""사용 순서·권한·한도(IMPL-PLAN-12 §5.1·§5.2)."""

from datetime import timedelta

from django.utils import timezone

from assist.models import AiJob, AiSource
from assist.services import today_org_count
from assist.sources import org_capped, plan
from notes.models import SttServer


def org_ai(org, **extra):
    org.settings = {
        **(org.settings or {}),
        "assist.org_url": "https://ai.example.com/v1",
        "assist.org_model": "m",
        **extra,
    }
    org.save(update_fields=["settings"])


def routes(user, org):
    return [a.route for a in plan(user, org)]


def personal(user, **kw):
    kw.setdefault("name", "개인")
    kw.setdefault("base_url", "https://p.example.com/v1")
    kw.setdefault("route", "direct")
    return AiSource.objects.create(user=user, **kw)


def test_switch_off_empty(org, member):
    org_ai(org)
    personal(member)
    org_ai(org, **{"assist.enabled": False})
    assert plan(member, org) == []


def test_order(org, member):
    assert routes(member, org) == []  # 조직 AI 미설정, 개인 없음
    org_ai(org)
    assert routes(member, org) == ["org"]  # 행 없음 = 조직만
    p = personal(member, position=1)
    assert routes(member, org) == ["direct", "org"]  # 기본 개인 우선
    row = AiSource.objects.create(user=member, kind="org", position=0)
    assert routes(member, org) == ["org", "direct"]  # 조직 AI 행을 위로
    row.enabled = False
    row.save()
    assert routes(member, org) == ["direct"]  # 조직 AI 행을 끄면 빠진다
    p.enabled = False
    p.save()
    assert routes(member, org) == []


def test_pc_rows(org, member, admin):
    now = timezone.now()
    mine = SttServer.objects.create(owner=member, name="내 PC", machine_id="a", last_seen_at=now)
    other = SttServer.objects.create(owner=admin, name="남 PC", machine_id="b", last_seen_at=now)
    base = {"route": "pc", "base_url": "http://localhost:11434/v1"}
    personal(member, server=None, **base)  # PC 끊김(SET_NULL)
    personal(member, server=other, **base)  # 불변식 1 위반
    p = personal(member, server=mine, **base)
    assert [(a.route, a.source) for a in plan(member, org)] == [("pc", p)]
    SttServer.objects.filter(pk=mine.pk).update(last_seen_at=now - timedelta(seconds=30))
    assert plan(member, org) == []  # 꺼진 PC


def test_org_level_and_daily_limit(org, member, admin):
    org_ai(org, **{"assist.org_level": "admin"})
    assert routes(member, org) == [] and routes(admin, org) == ["org"]
    org_ai(org, **{"assist.org_level": "member", "assist.org_daily_limit": 2})
    for who in (member, admin):
        for _ in range(2):
            AiJob.objects.create(
                user=who,
                org=org,
                kind="field",
                field="task.title",
                route="org",
                status="done",
                claimed_at=timezone.now(),
            )
    # 집히지 않고 끝난 작업·보내기 전에 넘긴 시도는 세지 않고, 조직 AI로 보냈다가 넘어간 시도는 센다
    AiJob.objects.create(
        user=member,
        org=org,
        kind="field",
        field="x",
        route="direct",
        status="done",
        tried=[{"route": "org", "source_id": None, "error": "no_source"}],
        claimed_at=timezone.now(),
    )
    AiJob.objects.create(
        user=member, org=org, kind="field", field="x", route="org", status="failed"
    )
    AiJob.objects.create(
        user=member,
        org=org,
        kind="field",
        field="x",
        route="direct",
        status="done",
        tried=[{"route": "org", "source_id": None, "error": "timeout"}],
        claimed_at=timezone.now(),
    )
    assert today_org_count(member, org) == 3
    assert routes(member, org) == []  # 멤버 한도 도달
    assert org_capped(member, org) and not org_capped(admin, org)  # 작업 만들기 오류 코드 rate
    assert routes(admin, org) == ["org"]  # 관리자 예외
    org_ai(org, **{"assist.org_daily_limit": 0})
    assert routes(member, org) == ["org"]  # 0 = 무제한


def test_yesterday_not_counted(org, member):
    org_ai(org, **{"assist.org_daily_limit": 1})
    j = AiJob.objects.create(
        user=member,
        org=org,
        kind="field",
        field="task.title",
        route="org",
        status="done",
        claimed_at=timezone.now(),
    )
    AiJob.objects.filter(pk=j.pk).update(created_at=timezone.now() - timedelta(days=2))
    assert today_org_count(member, org) == 0 and routes(member, org) == ["org"]


def test_outsider_gets_no_org_ai(org, outsider):
    org_ai(org)
    assert plan(outsider, org) == []
