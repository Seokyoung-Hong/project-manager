"""ProjectDoc → Doc(IMPL-PLAN-11 §4.2). 기존 행은 그대로 남고 org는 project.org로 채운다.

related_name("docs")·M2M(Task.docs)은 이름이 같다. 기존 문서마다 이전 버전 1개를 남겨
첫 수정 뒤에도 원래 본문으로 되돌릴 수 있게 한다. 조직마다 템플릿 2개를 깐다.
"""

import django.db.models.deletion
from django.conf import settings
from django.db import migrations, models
from django.db.models import OuterRef, Subquery

from projects.doc_templates import seed


def fill_org(apps, schema_editor):
    Doc = apps.get_model("projects", "Doc")
    Project = apps.get_model("projects", "Project")
    Doc.objects.update(
        org_id=Subquery(Project.objects.filter(pk=OuterRef("project_id")).values("org_id"))
    )


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
        migrations.RunPython(fill_org, migrations.RunPython.noop),
        migrations.AlterField(
            model_name="doc",
            name="org",
            field=models.ForeignKey(
                on_delete=django.db.models.deletion.CASCADE,
                related_name="docs",
                to="orgs.organization",
            ),
        ),
        migrations.AlterField(
            model_name="doc",
            name="project",
            field=models.ForeignKey(
                blank=True,
                null=True,
                on_delete=django.db.models.deletion.SET_NULL,
                related_name="docs",
                to="projects.project",
            ),
        ),
        migrations.AddField(
            model_name="doc",
            name="kind",
            field=models.CharField(
                choices=[("doc", "문서"), ("meeting", "회의록")], default="doc", max_length=7
            ),
        ),
        migrations.AddField(
            model_name="doc",
            name="team",
            field=models.ForeignKey(
                blank=True,
                null=True,
                on_delete=django.db.models.deletion.SET_NULL,
                related_name="docs",
                to="orgs.team",
            ),
        ),
        migrations.AddField(
            model_name="doc",
            name="parent",
            field=models.ForeignKey(
                blank=True,
                null=True,
                on_delete=django.db.models.deletion.CASCADE,
                related_name="children",
                to="projects.doc",
            ),
        ),
        migrations.AddField(
            model_name="doc", name="position", field=models.PositiveIntegerField(default=0)
        ),
        migrations.AddField(
            model_name="doc", name="is_template", field=models.BooleanField(default=False)
        ),
        migrations.AddField(
            model_name="doc",
            name="status",
            field=models.CharField(
                choices=[("draft", "초안"), ("final", "확정")], default="final", max_length=5
            ),
        ),
        migrations.AddField(
            model_name="doc",
            name="origin",
            field=models.CharField(
                choices=[("web", "웹"), ("voice", "음성 회의"), ("import", "가져오기")],
                default="web",
                max_length=6,
            ),
        ),
        migrations.AddField(
            model_name="doc",
            name="created_on",
            field=models.DateTimeField(blank=True, null=True, verbose_name="회의 일시"),
        ),
        migrations.AddField(
            model_name="doc",
            name="tags",
            field=models.JSONField(blank=True, default=list),
        ),
        migrations.AddField(
            model_name="doc",
            name="import_key",
            field=models.CharField(blank=True, db_index=True, max_length=64),
        ),
        migrations.AddField(
            model_name="doc",
            name="attendees",
            field=models.ManyToManyField(blank=True, related_name="+", to=settings.AUTH_USER_MODEL),
        ),
        migrations.AlterModelOptions(
            name="doc", options={"ordering": ["position", "created_at", "id"]}
        ),
        migrations.AddConstraint(
            model_name="doc",
            constraint=models.CheckConstraint(
                condition=models.Q(
                    ("project__isnull", True), ("team__isnull", True), _connector="OR"
                ),
                name="doc_scope_one",
            ),
        ),
        migrations.AddConstraint(
            model_name="doc",
            constraint=models.CheckConstraint(
                condition=models.Q(
                    models.Q(("kind", "meeting"), _negated=True),
                    ("parent__isnull", True),
                    _connector="OR",
                ),
                name="doc_meeting_no_parent",
            ),
        ),
        migrations.AddIndex(
            model_name="doc",
            index=models.Index(
                fields=["org", "kind", "parent"], name="projects_do_org_id_1159c0_idx"
            ),
        ),
        migrations.AddIndex(
            model_name="doc",
            index=models.Index(
                fields=["org", "kind", "created_on"], name="projects_do_org_id_511cc1_idx"
            ),
        ),
        migrations.CreateModel(
            name="DocRevision",
            fields=[
                (
                    "id",
                    models.BigAutoField(
                        auto_created=True, primary_key=True, serialize=False, verbose_name="ID"
                    ),
                ),
                ("version", models.PositiveIntegerField()),
                ("title", models.CharField(max_length=200)),
                ("body_md", models.TextField(blank=True)),
                (
                    "source",
                    models.CharField(
                        choices=[("web", "웹"), ("api", "API"), ("mcp", "AI"), ("dc", "Discord")],
                        default="web",
                        max_length=4,
                    ),
                ),
                ("saved_at", models.DateTimeField()),
                (
                    "doc",
                    models.ForeignKey(
                        on_delete=django.db.models.deletion.CASCADE,
                        related_name="revisions",
                        to="projects.doc",
                    ),
                ),
                (
                    "saved_by",
                    models.ForeignKey(
                        null=True,
                        on_delete=django.db.models.deletion.SET_NULL,
                        related_name="+",
                        to=settings.AUTH_USER_MODEL,
                    ),
                ),
            ],
            options={
                "ordering": ["-version"],
                "constraints": [
                    models.UniqueConstraint(
                        fields=("doc", "version"), name="docrevision_doc_version"
                    )
                ],
            },
        ),
        migrations.RunPython(seed_rest, migrations.RunPython.noop),
    ]
