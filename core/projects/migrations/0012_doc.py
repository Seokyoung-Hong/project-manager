"""ProjectDoc → Doc(IMPL-PLAN-11 §4.2) 1/4(스키마): 이름 바꾸기 + org(빈 값 허용).

related_name("docs")·M2M(Task.docs)은 이름이 같다. 이어서 0013 org 채우기 → 0014 나머지 열·제약·
DocRevision → 0015 이전 버전·템플릿 시드.
"""

import django.db.models.deletion
from django.conf import settings
from django.db import migrations, models

# Postgres: 같은 트랜잭션에서 DML(RunPython) 뒤에 DDL을 하면 지연 FK 트리거가 남아
# "pending trigger events"로 실패한다(Fable S §3.1). 그래서 데이터 이전은 스키마 변경과 다른 마이그레이션에 둔다.


class Migration(migrations.Migration):
    dependencies = [
        ("orgs", "0009_team_dev_tools_is_private"),
        ("projects", "0011_milestone_gh_number"),
        ("tasks", "0009_task_status_since"),
        migrations.swappable_dependency(settings.AUTH_USER_MODEL),
    ]

    operations = [
        migrations.RenameModel("ProjectDoc", "Doc"),
        migrations.AddField(
            model_name="doc",
            name="org",
            field=models.ForeignKey(
                null=True,
                on_delete=django.db.models.deletion.CASCADE,
                related_name="docs",
                to="orgs.organization",
            ),
        ),
    ]
