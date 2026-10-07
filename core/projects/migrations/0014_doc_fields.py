"""Doc 3/4(스키마): org NOT NULL, 범위·트리·kind·템플릿·회의록 열, 제약·인덱스, DocRevision."""

import django.db.models.deletion
from django.conf import settings
from django.db import migrations, models

# Postgres: 같은 트랜잭션에서 DML(RunPython) 뒤에 DDL을 하면 지연 FK 트리거가 남아
# "pending trigger events"로 실패한다(Fable S §3.1). 그래서 데이터 이전은 스키마 변경과 다른 마이그레이션에 둔다.


class Migration(migrations.Migration):
    dependencies = [
        ("orgs", "0009_team_dev_tools_is_private"),
        ("projects", "0013_doc_fill_org"),
        migrations.swappable_dependency(settings.AUTH_USER_MODEL),
    ]

    operations = [
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
    ]
