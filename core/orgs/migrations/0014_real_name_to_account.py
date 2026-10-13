"""조직별 실명을 계정 실명으로 옮긴다(IMPL-PLAN-13 §2.3). 데이터만 — 스키마는 0013·accounts 0010.

Postgres는 DML 뒤 같은 트랜잭션의 DDL에서 지연 트리거 오류가 난다(notes 0004·0005 전례). 그래서 파일을 나눴다.

- 조직 정의: real_name "required" → show_real_name True, 그 밖 → False. 옛 값은 _legacy_real_name에 둔다.
- 계정 실명이 빈 사람만: 조직 실명(공백 정리·중복 제거)이 한 가지면 그 값, 여러 가지면 비우고
  settings["real_name_candidates"]에 가입 최신순으로 둔다(본인이 고른다).
- backward: 정의를 되돌리고 후보 키를 지운다. 옮긴 계정 실명은 accounts 0010 되돌리기가 열과 함께 지운다.
  OrgMembership.real_name은 건드리지 않으므로 잃는 값이 없다.
"""

from django.db import migrations


def _clean(v):
    return " ".join((v or "").split())[:50]


def forward(apps, schema_editor):
    Organization = apps.get_model("orgs", "Organization")
    OrgMembership = apps.get_model("orgs", "OrgMembership")
    User = apps.get_model("accounts", "User")

    orgs = []
    for o in Organization.objects.iterator():
        d = dict(o.member_fields or {})
        if "show_real_name" in d:
            continue
        legacy = d.pop("real_name", "off")
        d["show_real_name"] = legacy == "required"
        d["_legacy_real_name"] = legacy
        d.setdefault("fields", [])
        o.member_fields = d
        orgs.append(o)
    Organization.objects.bulk_update(orgs, ["member_fields"], batch_size=500)

    names = {}  # user_id → [이름, …] 가입 최신순
    rows = (
        OrgMembership.objects.exclude(real_name="")
        .filter(user__real_name="")
        .order_by("user_id", "-joined_at", "-pk")
        .values_list("user_id", "real_name")
    )
    for uid, raw in rows.iterator():
        v = _clean(raw)
        if v and v not in names.setdefault(uid, []):
            names[uid].append(v)
    users, moved, conflicts = [], 0, 0
    for u in User.objects.filter(pk__in=[k for k, v in names.items() if v]).iterator():
        found = names[u.pk]
        if len(found) == 1:
            u.real_name = found[0]
            moved += 1
        else:
            u.settings = {**(u.settings or {}), "real_name_candidates": found}
            conflicts += 1
        users.append(u)
    User.objects.bulk_update(users, ["real_name", "settings"], batch_size=500)
    print(
        f"\n  real_name: 조직 {len(orgs)}곳 정의 변환, 계정 실명 이전 {moved}명, 충돌 {conflicts}명"
    )


def backward(apps, schema_editor):
    Organization = apps.get_model("orgs", "Organization")
    User = apps.get_model("accounts", "User")

    orgs = []
    for o in Organization.objects.iterator():
        d = dict(o.member_fields or {})
        if "show_real_name" not in d and "_legacy_real_name" not in d:
            continue
        show = d.pop("show_real_name", False)
        d["real_name"] = d.pop("_legacy_real_name", "required" if show else "off")
        o.member_fields = d
        orgs.append(o)
    Organization.objects.bulk_update(orgs, ["member_fields"], batch_size=500)

    users = []
    for u in User.objects.iterator():
        if "real_name_candidates" in (u.settings or {}):
            u.settings = {k: v for k, v in u.settings.items() if k != "real_name_candidates"}
            users.append(u)
    User.objects.bulk_update(users, ["settings"], batch_size=500)


class Migration(migrations.Migration):
    dependencies = [
        ("orgs", "0013_orgmembership_nickname"),
    ]

    operations = [migrations.RunPython(forward, backward)]
