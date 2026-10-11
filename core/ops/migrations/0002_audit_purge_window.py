from django.db import migrations

# 개인정보 보관 기간(1년) 정리용 최소 개방: Postgres에서 purge_audit_log가 트랜잭션 안에서
# `ops.purge=on`을 켠 DELETE만 통과시킨다. UPDATE·TRUNCATE는 계속 막는다.
# SQLite는 명령이 DELETE 트리거를 트랜잭션 안에서 잠시 내렸다 다시 만든다(변수가 없다).
FN = """CREATE OR REPLACE FUNCTION ops_audit_block() RETURNS trigger AS $$
BEGIN
  IF TG_OP = 'DELETE' AND current_setting('ops.purge', true) = 'on' THEN RETURN OLD; END IF;
  RAISE EXCEPTION 'ops_opsauditlog is append-only';
END $$ LANGUAGE plpgsql"""
FN_OLD = """CREATE OR REPLACE FUNCTION ops_audit_block() RETURNS trigger AS $$
BEGIN RAISE EXCEPTION 'ops_opsauditlog is append-only'; END $$ LANGUAGE plpgsql"""


def _swap(sql):
    def run(apps, schema_editor):
        if schema_editor.connection.vendor == "postgresql":
            schema_editor.execute(sql)

    return run


class Migration(migrations.Migration):
    dependencies = [("ops", "0001_initial")]
    operations = [migrations.RunPython(_swap(FN), _swap(FN_OLD))]
