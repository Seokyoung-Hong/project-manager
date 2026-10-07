"""회의록 → 문서 1/3(스키마): VoiceRecording.doc(빈 값 허용) 추가. 0005 데이터 이전, 0006 정리."""

import django.db.models.deletion
from django.db import migrations, models

# Postgres: 같은 트랜잭션에서 DML(RunPython) 뒤에 DDL을 하면 지연 FK 트리거가 남아
# "pending trigger events"로 실패한다(Fable S §3.1). 그래서 데이터 이전은 스키마 변경과 다른 마이그레이션에 둔다.


class Migration(migrations.Migration):
    dependencies = [
        ("notes", "0003_voice_recording"),
        ("projects", "0016_doc_scope_restrict"),
        ("tasks", "0010_taskproject_git_project"),
    ]

    operations = [
        migrations.AddField(
            model_name="voicerecording",
            name="doc",
            field=models.OneToOneField(
                null=True,
                on_delete=django.db.models.deletion.CASCADE,
                related_name="+",
                to="projects.doc",
            ),
        ),
    ]
