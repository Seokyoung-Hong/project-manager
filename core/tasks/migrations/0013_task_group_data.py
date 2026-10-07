"""Task.group 2/2(데이터): S1 '사람별로 나누기' 결과를 하위 태스크로 바꾼다.

Postgres: 같은 트랜잭션에서 DML(RunPython) 뒤에 DDL(0012의 FK·인덱스 지연 생성)을 하면
"pending trigger events"로 실패할 수 있다(Fable S §3.1). 그래서 0012(스키마)와 나눈다.
"""

from django.db import migrations


def split_to_subtasks(apps, schema_editor):
    """안전망(IMPL-PLAN-12 §2.2, 멱등): S1 '사람별로 나누기'가 계열(parent)로 묶은 태스크를 하위(group)로
    바꾸고, 원본 체크리스트가 전부 'TASK-n …' 꼴이면(S1이 바꿔 놓은 것) 지운다. 운영은 S1 이전이라 보통 0건."""
    Task = apps.get_model("tasks", "Task")
    ChangeLog = apps.get_model("tasks", "ChangeLog")
    ChecklistItem = apps.get_model("tasks", "ChecklistItem")
    for log in ChangeLog.objects.filter(target_type="task", field="split"):
        top = Task.objects.filter(
            pk=log.target_id,
            group__isnull=True,
            is_template=False,
            status__in=("todo", "doing", "paused", "blocked", "review"),  # 닫힌 원본은 건너뛴다(I2)
        ).first()
        if top is None:
            continue
        ids = [
            int(n[5:])
            for n in log.new_value.split(",")
            if n.startswith("TASK-") and n[5:].isdigit()
        ]
        Task.objects.filter(pk__in=ids, project_id=top.project_id, is_template=False).exclude(
            pk=top.pk
        ).update(group=top, parent=None)
        items = ChecklistItem.objects.filter(task=top)
        if items.exists() and not items.exclude(text__startswith="TASK-").exists():
            items.delete()


class Migration(migrations.Migration):
    dependencies = [
        ("tasks", "0012_task_group"),
    ]

    operations = [
        migrations.RunPython(split_to_subtasks, migrations.RunPython.noop),
    ]
