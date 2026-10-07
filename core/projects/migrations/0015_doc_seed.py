"""Doc 4/4(데이터): 기존 문서마다 이전 버전 1개, 조직마다 템플릿 2개(회의록·설계 문서)."""

from django.db import migrations

from projects.doc_templates import seed

# Postgres: 같은 트랜잭션에서 DML(RunPython) 뒤에 DDL을 하면 지연 FK 트리거가 남아
# "pending trigger events"로 실패한다(Fable S §3.1). 그래서 데이터 이전은 스키마 변경과 다른 마이그레이션에 둔다.


def seed_rest(apps, schema_editor):
    Doc = apps.get_model("projects", "Doc")
    DocRevision = apps.get_model("projects", "DocRevision")
    Organization = apps.get_model("orgs", "Organization")
    DocRevision.objects.bulk_create(
        [
            DocRevision(
                doc_id=d.pk,
                version=d.version,
                title=d.title,
                body_md=d.body_md,
                saved_by_id=d.updated_by_id or d.created_by_id,
                source=d.updated_source,
                saved_at=d.updated_at,
            )
            for d in Doc.objects.all()
        ]
    )
    for org_id, user_id in Organization.objects.values_list("pk", "created_by_id"):
        seed(Doc, org_id, user_id)


class Migration(migrations.Migration):
    dependencies = [
        ("projects", "0014_doc_fields"),
    ]

    operations = [
        migrations.RunPython(seed_rest, migrations.RunPython.noop),
    ]
