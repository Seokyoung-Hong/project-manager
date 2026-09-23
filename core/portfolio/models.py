from django.conf import settings
from django.db import models


class PortfolioDraft(models.Model):
    """Private, editable Markdown draft owned by one organization member."""

    STATUSES = [("draft", "초안")]

    owner = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.CASCADE,
        related_name="portfolio_drafts",
        verbose_name="소유자",
    )
    org = models.ForeignKey(
        "orgs.Organization",
        on_delete=models.PROTECT,
        related_name="portfolio_drafts",
        verbose_name="조직",
    )
    title = models.CharField("제목", max_length=200)
    scope_json = models.JSONField("출처 선택 범위", default=dict, blank=True)
    body_md = models.TextField("Markdown 본문", blank=True)
    status = models.CharField("상태", max_length=12, choices=STATUSES, default="draft")
    prompt_version = models.CharField("프롬프트 버전", max_length=40, blank=True)
    version = models.PositiveIntegerField("버전", default=1)
    created_at = models.DateTimeField("생성 시각", auto_now_add=True)
    updated_at = models.DateTimeField("수정 시각", auto_now=True)

    class Meta:
        ordering = ["-updated_at", "-id"]
        indexes = [
            models.Index(fields=["owner", "updated_at"], name="portdraft_owner_updated_idx")
        ]

    def __str__(self):
        return self.title


class PortfolioSource(models.Model):
    """A selected decision record plus a safe, immutable-at-selection snapshot."""

    draft = models.ForeignKey(
        PortfolioDraft,
        on_delete=models.CASCADE,
        related_name="sources",
    )
    decision_record = models.ForeignKey(
        "tasks.TaskDecisionRecord",
        on_delete=models.PROTECT,
        related_name="portfolio_sources",
    )
    record_kind = models.CharField("기록 종류 스냅샷", max_length=20)
    record_summary = models.TextField("의사 요지 스냅샷")
    record_status = models.CharField("확인 상태 스냅샷", max_length=12)
    record_created_at = models.DateTimeField("기록 시각 스냅샷")
    task_number = models.CharField("태스크 번호 스냅샷", max_length=32)
    project_name = models.CharField("프로젝트명 스냅샷", max_length=100)
    created_at = models.DateTimeField("출처 추가 시각", auto_now_add=True)

    class Meta:
        ordering = ["record_created_at", "id"]
        constraints = [
            models.UniqueConstraint(
                fields=["draft", "decision_record"],
                name="portfolio_source_once_per_draft",
            ),
        ]
        indexes = [
            models.Index(
                fields=["draft", "record_created_at"], name="portsrc_draft_created_idx"
            )
        ]

    def __str__(self):
        return f"{self.task_number} · 기록 #{self.decision_record_id}"
