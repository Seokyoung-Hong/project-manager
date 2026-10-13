"""orgs 0014: 조직 실명 → 계정 실명 이전, 정의 변환, 되돌리기(IMPL-PLAN-13 §2.3)."""

import pytest
from django.db import connection
from django.db.migrations.executor import MigrationExecutor

BEFORE = [("accounts", "0009_termsagreement"), ("orgs", "0012_member_info")]
AFTER = [("orgs", "0014_real_name_to_account")]


def _apps(target):
    ex = MigrationExecutor(connection)
    ex.migrate(target)
    return MigrationExecutor(connection).loader.project_state(target).apps


@pytest.mark.django_db(transaction=True)
def test_real_name_moves_to_account_and_back(pg_flushable):
    try:
        old = _apps(BEFORE)
        User = old.get_model("accounts", "User")
        Org = old.get_model("orgs", "Organization")
        M = old.get_model("orgs", "OrgMembership")
        one, clash, none = (User.objects.create(username=n, display_name=n) for n in ("one", "clash", "none"))  # fmt: skip
        req = Org.objects.create(name="필수", created_by=one, member_fields={"real_name": "required", "fields": [{"id": "abcd1234"}]})  # fmt: skip
        opt = Org.objects.create(
            name="선택", created_by=one, member_fields={"real_name": "optional"}
        )
        bare = Org.objects.create(name="빈", created_by=one)
        M.objects.create(org=req, user=one, real_name=" 홍  길동 ")
        M.objects.create(org=opt, user=one, real_name="홍 길동")  # 공백 정리 후 같은 값
        M.objects.create(org=req, user=clash, real_name="김갑")
        M.objects.create(org=opt, user=clash, real_name="김을")
        M.objects.create(org=bare, user=none)

        new = _apps(AFTER)
        User = new.get_model("accounts", "User")
        Org = new.get_model("orgs", "Organization")
        M = new.get_model("orgs", "OrgMembership")
        assert User.objects.get(pk=one.pk).real_name == "홍 길동"
        c = User.objects.get(pk=clash.pk)
        assert c.real_name == "" and sorted(c.settings["real_name_candidates"]) == ["김갑", "김을"]
        assert User.objects.get(pk=none.pk).real_name == ""
        assert Org.objects.get(pk=req.pk).member_fields == {
            "show_real_name": True,
            "_legacy_real_name": "required",
            "fields": [{"id": "abcd1234"}],
        }
        assert Org.objects.get(pk=opt.pk).member_fields["show_real_name"] is False
        assert Org.objects.get(pk=bare.pk).member_fields["show_real_name"] is False
        assert M.objects.get(org_id=req.pk, user_id=clash.pk).real_name == "김갑"  # 옛 열은 그대로

        old = _apps(BEFORE)
        Org = old.get_model("orgs", "Organization")
        User = old.get_model("accounts", "User")
        assert Org.objects.get(pk=req.pk).member_fields == {
            "real_name": "required",
            "fields": [{"id": "abcd1234"}],
        }
        assert Org.objects.get(pk=opt.pk).member_fields["real_name"] == "optional"
        assert "real_name_candidates" not in User.objects.get(pk=clash.pk).settings

        new = _apps(AFTER)  # 다시 앞으로
        assert new.get_model("accounts", "User").objects.get(pk=one.pk).real_name == "홍 길동"
    finally:
        ex = MigrationExecutor(connection)
        ex.migrate(ex.loader.graph.leaf_nodes())


@pytest.mark.django_db(transaction=True)
def test_definition_save_keeps_legacy_for_rollback(pg_flushable):
    """앞으로 → 새 코드로 설정 저장 → 뒤로 → 앞으로: 옛 optional이 살아남는다(Sol 검토 P2)."""
    from accounts.models import User as LiveUser
    from orgs.member_info import set_definition
    from orgs.models import Organization as LiveOrg
    from orgs.models import OrgMembership as LiveM

    try:
        old = _apps(BEFORE)
        User = old.get_model("accounts", "User")
        Org = old.get_model("orgs", "Organization")
        boss = User.objects.create(username="boss", display_name="boss")
        opt = Org.objects.create(name="선택", created_by=boss, member_fields={"real_name": "optional"})  # fmt: skip
        old.get_model("orgs", "OrgMembership").objects.create(org=opt, user=boss, role="admin")

        _apps(AFTER)
        org = LiveOrg.objects.get(pk=opt.pk)
        assert LiveM.objects.filter(org=org, role="admin").exists()
        set_definition(org, True, [], LiveUser.objects.get(pk=boss.pk))
        assert org.member_fields["_legacy_real_name"] == "optional"

        old = _apps(BEFORE)
        assert old.get_model("orgs", "Organization").objects.get(pk=opt.pk).member_fields == {
            "real_name": "optional",
            "fields": [],
        }
        new = _apps(AFTER)
        assert new.get_model("orgs", "Organization").objects.get(pk=opt.pk).member_fields == {
            "show_real_name": False,
            "_legacy_real_name": "optional",
            "fields": [],
        }
    finally:
        MigrationExecutor(connection).migrate(
            MigrationExecutor(connection).loader.graph.leaf_nodes()
        )
