"""회의록 → 문서 3/3(스키마): 녹음을 문서에 잇고 MeetingNote 표를 지운 뒤 같은 이름의 프록시로 둔다."""

import django.db.models.deletion
from django.db import migrations, models

# Postgres: 같은 트랜잭션에서 DML(RunPython) 뒤에 DDL을 하면 지연 FK 트리거가 남아
# "pending trigger events"로 실패한다(Fable S §3.1). 그래서 데이터 이전은 스키마 변경과 다른 마이그레이션에 둔다.


class Migration(migrations.Migration):
    dependencies = [
        ("notes", "0005_merge_into_doc_data"),
    ]

    operations = [
        migrations.RemoveField(model_name="voicerecording", name="note"),
        migrations.RenameField(model_name="voicerecording", old_name="doc", new_name="note"),
        migrations.AlterField(
            model_name="voicerecording",
            name="note",
            field=models.OneToOneField(
                on_delete=django.db.models.deletion.CASCADE,
                related_name="recording",
                to="projects.doc",
            ),
        ),
        migrations.DeleteModel(name="MeetingNote"),
        migrations.CreateModel(
            name="MeetingNote",
            fields=[],
            options={
                "ordering": ["-created_on", "-id"],
                "proxy": True,
                "indexes": [],
                "constraints": [],
            },
            bases=("projects.doc",),
        ),
    ]
