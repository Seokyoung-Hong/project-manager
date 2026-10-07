"""회의록(MeetingNote) → 문서(Doc, kind="meeting")(IMPL-PLAN-11 §4.3).

회의록마다 문서 하나를 만들고(id는 새로 받는다) 태스크 연결·참여자·작성자·시각·녹음을 옮긴다.
회의록이 있으면 되돌리지 않는다 — 되돌리려면 백업에서 복구한다.

공개 범위는 프로젝트나 팀 중 하나만 둘 수 있다(projects doc_scope_one). 옛 회의록은 둘 다 있으면
"프로젝트 ∩ 팀"으로 보였다. 하나를 임의로 떼면 열람자가 넓어지거나 연결이 사라지므로(Sol R3),
그런 행이 하나라도 있으면 아무것도 바꾸기 전에 중단하고 관리자가 회의록마다 범위를 정하게 한다.
"""

import django.db.models.deletion
from django.db import migrations, models


def forward(apps, schema_editor):
    Note = apps.get_model("notes", "MeetingNote")
    Rec = apps.get_model("notes", "VoiceRecording")
    Doc = apps.get_model("projects", "Doc")
    DocRevision = apps.get_model("projects", "DocRevision")

    both = list(
        Note.objects.filter(project__isnull=False, team__isnull=False)
        .order_by("pk")
        .values_list("pk", "org_id", "title")
    )
    if both:
        rows = ", ".join(f"#{pk}(조직 {org}) {title}" for pk, org, title in both[:20])
        raise RuntimeError(
            f"프로젝트와 팀이 둘 다 지정된 회의록이 {len(both)}건 있어 이전을 멈춥니다: {rows}. "
            "이전 전에 회의록마다 프로젝트나 팀 중 하나를 비우고(관리자 결정) 다시 migrate 하세요. "
            "둘 다 남기면 '프로젝트 ∩ 팀' 제한을 새 모델이 표현하지 못해 열람자가 바뀝니다."
        )

    for n in Note.objects.order_by("pk"):
        project_id, team_id = n.project_id, n.team_id
        d = Doc.objects.create(
            org_id=n.org_id,
            kind="meeting",
            project_id=project_id,
            team_id=team_id,
            status=n.status,
            origin=n.source,
            title=n.title,
            body_md=n.body_md,
            version=n.version,
            created_on=n.created_on,
            tags=n.tags,
            created_by_id=n.created_by_id,
            updated_by_id=None,
            updated_source="web",
        )
        # auto_now(_add)를 피해 원래 시각을 넣는다.
        Doc.objects.filter(pk=d.pk).update(created_at=n.created_at, updated_at=n.updated_at)
        d.tasks.set(n.tasks.all())
        d.attendees.set(n.attendees.all())
        DocRevision.objects.create(
            doc_id=d.pk,
            version=n.version,
            title=n.title,
            body_md=n.body_md,
            saved_by_id=n.created_by_id,
            source="web",
            saved_at=n.updated_at,
        )
        Rec.objects.filter(note_id=n.pk).update(doc_id=d.pk)


def backward(apps, schema_editor):
    """회의록이 하나라도 있으면 거부한다. 빈 DB(테스트·새 설치)만 되돌린다."""
    Doc = apps.get_model("projects", "Doc")
    if Doc.objects.filter(kind="meeting", is_template=False).exists():
        raise RuntimeError("회의록 이전은 되돌릴 수 없습니다. 백업에서 복구해 주세요.")


class Migration(migrations.Migration):
    dependencies = [
        ("notes", "0003_voice_recording"),
        ("projects", "0012_doc"),
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
        migrations.RunPython(forward, backward),
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
