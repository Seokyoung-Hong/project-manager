"""조직 삭제(delete_org). Postgres 트리거까지 보려면 DATABASE_URL=postgres… 로 돌린다."""

import datetime
import decimal
import itertools

import pytest
from django.apps import apps
from django.db import IntegrityError, models, transaction
from django.urls import reverse
from django.utils import timezone

from accounts.models import User
from common.dates import today_kst
from orgs.models import Organization, OrgMembership
from orgs.services import create_org, delete_org
from projects.models import Project
from projects.services import create_project
from tasks.models import ChangeLog, Task, TaskDecisionRecord
from tasks.services import create_task

pytestmark = pytest.mark.django_db

_n = itertools.count(1)


def _value(field):
    """필수 필드에 넣을 값. 고유 제약에 걸리지 않게 번호를 붙인다."""
    if field.choices:
        return field.choices[0][0]
    n = next(_n)
    if isinstance(field, models.EmailField):
        return f"a{n}@example.com"
    if isinstance(field, models.URLField):
        return f"https://example.com/{n}"
    if isinstance(field, models.GenericIPAddressField):
        return "127.0.0.1"
    if isinstance(field, models.FileField):
        return f"test/{n}.txt"
    if isinstance(field, models.DateTimeField):
        return timezone.now()
    if isinstance(field, models.DateField):
        return datetime.date(2026, 1, 1)
    if isinstance(field, models.DurationField):
        return datetime.timedelta(seconds=1)
    if isinstance(field, models.DecimalField):
        return decimal.Decimal(1)
    if isinstance(field, models.BooleanField):
        return False
    if isinstance(field, (models.IntegerField, models.FloatField)):
        return n
    if isinstance(field, models.JSONField):
        return {}
    if isinstance(field, models.BinaryField):
        return b""
    if isinstance(field, models.UUIDField):
        import uuid

        return uuid.uuid4()
    if isinstance(field, (models.CharField, models.TextField)):
        return f"x{n}"[: field.max_length or 50]
    raise AssertionError(f"픽스처가 모르는 필드 형식: {field!r}")


def _org_models():
    """Organization에 (FK 사슬로) 매달린 모든 구체 모델. 새 모델이 생기면 자동으로 들어온다."""
    found = {Organization}
    grew = True
    while grew:
        grew = False
        for m in apps.get_models():
            if m in found or m._meta.proxy:
                continue
            if any(
                f.many_to_one or f.one_to_one
                for f in m._meta.concrete_fields
                if f.is_relation and f.related_model in found and not f.null
            ):
                found.add(m)
                grew = True
    return found


# CHECK 제약 때문에 첫 선택지로는 만들 수 없는 모델만 값을 정해 준다.
OVERRIDES = {
    "tasks.TaskDecisionRecord": {"kind": "ai_judgment", "status": "recorded", "confirmed_by": None},
    "tasks.WorkRequest": {"to_user": None},
    "tasks.Link": {"task": None},
    "tasks.Attachment": {"task": None, "doc": None},
    "projects.Doc": {"team": None},
}


def _row(m, i, made, user, rows):
    """m의 i번째 행. 같은 모델을 가리키는 FK가 여럿이면 서로 다른 행을 고른다(자기 의존 금지 제약)."""
    kw, seen = {}, {}
    for f in m._meta.concrete_fields:
        if f.primary_key or f.auto_created:
            continue
        if f.is_relation:
            target = f.related_model
            j = seen[target] = seen.get(target, -1) + 1
            if target is User:
                kw[f.name] = user
            elif target is m:
                kw[f.name] = rows[0] if rows else None
            elif target in made:
                kw[f.name] = made[target][(i + j) % len(made[target])]
            elif not f.null:
                raise AssertionError(f"{m._meta.label}.{f.name}을 채울 수 없습니다.")
        elif not (f.has_default() or f.null or getattr(f, "auto_now", False)):
            if not getattr(f, "auto_now_add", False):
                kw[f.name] = _value(f)
    kw.update(OVERRIDES.get(m._meta.label, {}))
    return m.objects.create(**kw)


def _fill(org) -> dict:
    """org 아래 모든 모델에 행을 두 개씩 만든다. 자기 참조가 있으면 둘째 행이 첫 행을 가리킨다.

    고유 제약(조직당 하나 같은 것) 때문에 둘째 행을 못 만들면 하나만 둔다.
    """
    user = User.objects.create_user(f"fill{next(_n)}", password="pw12345678")
    made = {Organization: [org]}
    todo = _org_models() - {Organization}
    while todo:
        progressed = False
        for m in sorted(todo, key=lambda m: m._meta.label):
            deps = {
                f.related_model for f in m._meta.concrete_fields if f.is_relation and not f.null
            }
            if not deps - {m, User} <= set(made):
                continue
            rows = [_row(m, 0, made, user, [])]
            try:
                with transaction.atomic():
                    rows.append(_row(m, 1, made, user, rows))
            except IntegrityError:
                pass
            for f in m._meta.many_to_many:
                target = made.get(f.related_model, [user] if f.related_model is User else [])
                if target and f.remote_field.through._meta.auto_created:
                    getattr(rows[0], f.name).set(target[:1])
            made[m] = rows
            todo.discard(m)
            progressed = True
        assert progressed, f"채울 순서를 정할 수 없는 모델: {sorted(x._meta.label for x in todo)}"
    return made


def _alive(made) -> dict:
    return {
        m._meta.label: m._base_manager.filter(pk__in=[r.pk for r in rows]).count()
        for m, rows in made.items()
    }


def test_delete_org_removes_every_model_and_keeps_other_org(org, admin, outsider):
    """(4) 모든 모델을 채운 뒤 지운다. 새 PROTECT FK가 생기면 여기서 ProtectedError로 실패한다."""
    other = create_org("다른 조직", "", outsider)
    mine, theirs = _fill(org), _fill(other)
    assert {"tasks.TaskDecisionRecord", "portfolio.PortfolioDraft", "projects.Doc"} <= set(
        _alive(mine)
    )
    before, org_pk = _alive(theirs), org.pk
    delete_org(org, admin)
    assert all(v == 0 for v in _alive(mine).values()), _alive(mine)
    assert _alive(theirs) == before
    assert ChangeLog.objects.filter(target_type="org", target_id=org_pk, field="delete").exists()


def _post_delete(client, user, org, name):
    client.force_login(user)
    return client.post(reverse("org_delete", args=[org.pk]), {"confirm_name": name})


def _project_task_record(org, admin):
    p = create_project(org=org, name="학식 API", actor=admin, owners=[admin], status="active")
    t = create_task(
        project=p, title="메뉴 누락 개선", actor=admin, source="web", due_date=today_kst()
    )
    TaskDecisionRecord.objects.create(
        task=t, kind="ai_judgment", status="recorded", summary="결정", source="web"
    )


def test_admin_deletes_org_by_typing_name(client, org, admin, outsider):
    """(1) 이름을 입력한 관리자 → 조직·프로젝트·태스크·결정 기록이 사라지고 다른 조직은 남는다."""
    other = create_org("다른 조직", "", outsider)
    _project_task_record(org, admin)
    _project_task_record(other, outsider)
    client.force_login(admin)
    s = client.session
    s["org_id"] = org.pk
    s.save()
    r = client.post(reverse("org_delete", args=[org.pk]), {"confirm_name": org.name})
    assert r.status_code == 302 and r.url == reverse("org")
    assert "org_id" not in client.session
    assert not Organization.objects.filter(name="산돌이").exists()
    assert Task.objects.count() == 1 and TaskDecisionRecord.objects.count() == 1
    assert Project.objects.filter(org=other).count() == 1
    assert User.objects.filter(pk=admin.pk).exists()  # 계정은 남는다


def test_member_cannot_delete_org(client, org, admin, member):
    """(2) 관리자가 아니면 403."""
    _project_task_record(org, admin)
    r = _post_delete(client, member, org, org.name)
    assert r.status_code == 403
    assert Organization.objects.filter(pk=org.pk).exists()
    assert TaskDecisionRecord.objects.count() == 1


def test_wrong_name_deletes_nothing(client, org, admin):
    """(3) 이름이 다르면 아무것도 지우지 않는다."""
    _project_task_record(org, admin)
    r = _post_delete(client, admin, org, "산돌")
    assert r.status_code == 302
    assert r.url == reverse("org_settings", args=[org.pk]) + "?tab=org#settings-org-danger"
    assert Organization.objects.filter(pk=org.pk).exists()
    assert Task.objects.count() == 1 and TaskDecisionRecord.objects.count() == 1
    assert OrgMembership.objects.filter(org=org).count() == 2


def test_settings_shows_danger_zone_only_to_admin(client, org, admin, member):
    client.force_login(admin)
    body = client.get(reverse("org_settings", args=[org.pk]) + "?tab=org").content.decode()
    assert "조직 삭제" in body and "GitHub에서 앱 설치는 따로 해제해야 합니다" in body
    client.force_login(member)
    r = client.get(reverse("org_settings", args=[org.pk]) + "?tab=org", follow=True)
    assert "confirm_name" not in r.content.decode()
