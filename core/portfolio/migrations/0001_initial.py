# Generated for the private portfolio draft and source snapshot models.

import django.db.models.deletion
from django.conf import settings
from django.db import migrations, models


class Migration(migrations.Migration):
    initial = True

    dependencies = [
        migrations.swappable_dependency(settings.AUTH_USER_MODEL),
        ("orgs", "0004_settings_and_discord_binding"),
        ("tasks", "0003_taskdecisionrecord"),
    ]

    operations = [
        migrations.CreateModel(
            name="PortfolioDraft",
            fields=[
                (
                    "id",
                    models.BigAutoField(
                        auto_created=True,
                        primary_key=True,
                        serialize=False,
                        verbose_name="ID",
                    ),
                ),
                ("title", models.CharField(max_length=200, verbose_name="제목")),
                (
                    "scope_json",
                    models.JSONField(blank=True, default=dict, verbose_name="출처 선택 범위"),
                ),
                ("body_md", models.TextField(blank=True, verbose_name="Markdown 본문")),
                (
                    "status",
                    models.CharField(
                        choices=[("draft", "초안")],
                        default="draft",
                        max_length=12,
                        verbose_name="상태",
                    ),
                ),
                (
                    "prompt_version",
                    models.CharField(blank=True, max_length=40, verbose_name="프롬프트 버전"),
                ),
                ("version", models.PositiveIntegerField(default=1, verbose_name="버전")),
                ("created_at", models.DateTimeField(auto_now_add=True, verbose_name="생성 시각")),
                ("updated_at", models.DateTimeField(auto_now=True, verbose_name="수정 시각")),
                (
                    "org",
                    models.ForeignKey(
                        on_delete=django.db.models.deletion.PROTECT,
                        related_name="portfolio_drafts",
                        to="orgs.organization",
                        verbose_name="조직",
                    ),
                ),
                (
                    "owner",
                    models.ForeignKey(
                        on_delete=django.db.models.deletion.CASCADE,
                        related_name="portfolio_drafts",
                        to=settings.AUTH_USER_MODEL,
                        verbose_name="소유자",
                    ),
                ),
            ],
            options={"ordering": ["-updated_at", "-id"]},
        ),
        migrations.CreateModel(
            name="PortfolioSource",
            fields=[
                (
                    "id",
                    models.BigAutoField(
                        auto_created=True,
                        primary_key=True,
                        serialize=False,
                        verbose_name="ID",
                    ),
                ),
                ("record_kind", models.CharField(max_length=20, verbose_name="기록 종류 스냅샷")),
                ("record_summary", models.TextField(verbose_name="의사 요지 스냅샷")),
                (
                    "record_status",
                    models.CharField(max_length=12, verbose_name="확인 상태 스냅샷"),
                ),
                (
                    "record_created_at",
                    models.DateTimeField(verbose_name="기록 시각 스냅샷"),
                ),
                ("task_number", models.CharField(max_length=32, verbose_name="태스크 번호 스냅샷")),
                ("project_name", models.CharField(max_length=100, verbose_name="프로젝트명 스냅샷")),
                ("created_at", models.DateTimeField(auto_now_add=True, verbose_name="출처 추가 시각")),
                (
                    "decision_record",
                    models.ForeignKey(
                        on_delete=django.db.models.deletion.PROTECT,
                        related_name="portfolio_sources",
                        to="tasks.taskdecisionrecord",
                    ),
                ),
                (
                    "draft",
                    models.ForeignKey(
                        on_delete=django.db.models.deletion.CASCADE,
                        related_name="sources",
                        to="portfolio.portfoliodraft",
                    ),
                ),
            ],
            options={"ordering": ["record_created_at", "id"]},
        ),
        migrations.AddConstraint(
            model_name="portfoliosource",
            constraint=models.UniqueConstraint(
                fields=("draft", "decision_record"),
                name="portfolio_source_once_per_draft",
            ),
        ),
        migrations.AddIndex(
            model_name="portfoliodraft",
            index=models.Index(fields=["owner", "updated_at"], name="portdraft_owner_updated_idx"),
        ),
        migrations.AddIndex(
            model_name="portfoliosource",
            index=models.Index(
                fields=["draft", "record_created_at"], name="portsrc_draft_created_idx"
            ),
        ),
    ]
