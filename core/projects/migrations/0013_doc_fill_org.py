"""Doc 2/4(데이터): 기존 행의 org를 project.org로 채운다."""

from django.db import migrations
from django.db.models import OuterRef, Subquery

# Postgres: 같은 트랜잭션에서 DML(RunPython) 뒤에 DDL을 하면 지연 FK 트리거가 남아
# "pending trigger events"로 실패한다(Fable S §3.1). 그래서 데이터 이전은 스키마 변경과 다른 마이그레이션에 둔다.


def fill_org(apps, schema_editor):
    Doc = apps.get_model("projects", "Doc")
    Project = apps.get_model("projects", "Project")
    Doc.objects.update(
        org_id=Subquery(Project.objects.filter(pk=OuterRef("project_id")).values("org_id"))
    )


class Migration(migrations.Migration):
    dependencies = [
        ("projects", "0012_doc"),
    ]

    operations = [
        migrations.RunPython(fill_org, migrations.RunPython.noop),
    ]
