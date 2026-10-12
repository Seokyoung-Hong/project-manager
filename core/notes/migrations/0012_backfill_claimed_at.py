"""처음 가져간 시각(first_claimed_at)을 더하고, 배포 전 작업의 가져간 시각을 채운다(IMPL-PLAN-11-local-stt-link).

- 0011 전에는 claimed_at이 없었다. Node가 claim으로 가져가 돌던 다시 전사·올린 녹음 작업(running·cancelling)은
  started_at을 claimed_at으로 채워 Node 재시작 복구(transcription.requeue)에 걸리게 한다.
  자동 작업은 Node가 claim 없이 바로 전사하므로 채우지 않는다(복구 대상이 아니다).
- 자동이 아닌 작업 중 시작한 적이 있는 것은 first_claimed_at = started_at — 조직 수단 한도에서 실행한 시도로 센다.
"""

from django.db import migrations, models
from django.db.models import F


def backfill(apps, schema_editor):
    Job = apps.get_model("notes", "TranscriptionJob")
    manual = Job.objects.exclude(kind="auto").filter(started_at__isnull=False)
    manual.filter(first_claimed_at__isnull=True).update(first_claimed_at=F("started_at"))
    manual.filter(
        status__in=("running", "cancelling"), claimed_at__isnull=True, server__isnull=True
    ).update(claimed_at=F("started_at"))


class Migration(migrations.Migration):
    dependencies = [
        ("notes", "0011_stt_server"),
    ]

    operations = [
        migrations.AddField(
            model_name="transcriptionjob",
            name="first_claimed_at",
            field=models.DateTimeField(blank=True, null=True),
        ),
        migrations.RunPython(backfill, migrations.RunPython.noop),
    ]
