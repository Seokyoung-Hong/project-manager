from django.conf import settings
from django.db import models
from django.db.models import Q

from common.dates import today_kst


class Task(models.Model):
    STATUSES = [
        ("todo", "시작 전"),
        ("doing", "진행 중"),
        ("paused", "일시정지"),
        ("blocked", "막힘"),
        ("review", "검토 대기"),
        ("done", "완료"),
        ("cancelled", "취소"),
    ]
    STATUS_HINT = {
        "todo": "아직 시작하지 않은 상태입니다.",
        "doing": "현재 진행 중입니다.",
        "paused": "개인 사유나 다른 작업으로 잠시 멈춘 상태입니다. 재개하면 진행 중으로 바꿔 주세요.",
        "blocked": "외부 요인으로 진행이 막힌 상태입니다. 팀이 함께 해결해야 합니다.",
        "review": "작업을 마치고 확인을 기다리는 상태입니다.",
        "done": "완료된 상태입니다.",
        "cancelled": "진행하지 않기로 한 상태입니다.",
    }
    OPEN = ("todo", "doing", "paused", "blocked", "review")
    STOPPED = ("paused", "blocked")
    CLOSED = ("done", "cancelled")
    TIERS = {"high": (8, 10), "mid": (4, 7), "low": (1, 3)}
    TIER_LABELS = [("high", "높음 8~10"), ("mid", "중간 4~7"), ("low", "낮음 1~3")]

    project = models.ForeignKey("projects.Project", on_delete=models.PROTECT, related_name="tasks")
    title = models.CharField("제목", max_length=200)
    description = models.TextField("설명", blank=True)
    done_when = models.CharField("완료 조건", max_length=300, blank=True)
    next_action = models.CharField("다음 행동", max_length=200, blank=True)
    notes = models.TextField("진행 메모", blank=True)
    assignee = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.PROTECT,
        related_name="tasks",
        verbose_name="담당자",
    )
    priority = models.PositiveSmallIntegerField("중요도", default=5)
    status = models.CharField("상태", max_length=9, choices=STATUSES, default="todo")
    due_date = models.DateField("목표 기한", null=True, blank=True)
    no_due_reason = models.CharField("기한 미정 사유", max_length=200, blank=True)
    stop_reason = models.CharField("멈춘 사유", max_length=300, blank=True)
    stopped_at = models.DateTimeField(null=True, blank=True)
    completed_at = models.DateTimeField(null=True, blank=True)
    version = models.PositiveIntegerField(default=1)
    created_by = models.ForeignKey(
        settings.AUTH_USER_MODEL, on_delete=models.PROTECT, related_name="+"
    )
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        ordering = ["-id"]
        constraints = [
            models.CheckConstraint(
                condition=Q(priority__gte=1) & Q(priority__lte=10),
                name="task_priority_range",
            ),
            models.CheckConstraint(
                condition=~Q(status="doing") | Q(due_date__isnull=False),
                name="task_doing_requires_due",
            ),
            models.CheckConstraint(
                condition=~Q(status="blocked") | ~Q(stop_reason=""),
                name="task_blocked_requires_reason",
            ),
            models.CheckConstraint(
                condition=~Q(status="done") | Q(completed_at__isnull=False),
                name="task_done_requires_completed_at",
            ),
        ]
        indexes = [
            models.Index(fields=["assignee", "status"]),
            models.Index(fields=["project", "status"]),
            models.Index(fields=["due_date"]),
        ]

    def __str__(self):
        return f"{self.number} {self.title}"

    @property
    def number(self) -> str:
        return f"TASK-{self.pk}"

    @property
    def is_open(self) -> bool:
        return self.status in self.OPEN

    @property
    def is_closed(self) -> bool:
        return self.status in self.CLOSED

    @property
    def is_stopped(self) -> bool:
        return self.status in self.STOPPED

    @property
    def is_blocked(self) -> bool:
        return self.status == "blocked"

    @property
    def is_overdue(self) -> bool:
        return self.is_open and self.due_date is not None and self.due_date < today_kst()

    @property
    def priority_tier(self) -> str:
        return "high" if self.priority >= 8 else "mid" if self.priority >= 4 else "low"

    @property
    def status_label(self) -> str:
        return dict(self.STATUSES)[self.status]

    @property
    def status_hint(self) -> str:
        return self.STATUS_HINT[self.status]


class TaskDecisionRecord(models.Model):
    """Structured, source-aware record of a user input or an AI judgment."""

    KINDS = [
        ("user_input", "사용자 입력"),
        ("ai_judgment", "AI 작업 판단"),
    ]
    INPUT_TYPES = [
        ("major_choice", "주요 선택"),
        ("requirement", "요구·제약"),
        ("answer", "명시적 답변"),
        ("steer", "방향 수정"),
        ("implementation_instruction", "구현 방식 지시"),
        ("ai_workflow_instruction", "AI 협업 방식 지시"),
    ]
    STATUSES = [
        ("captured", "세션에서 수집"),
        ("proposed", "확인 대기"),
        ("confirmed", "사용자 확인"),
        ("rejected", "제외"),
        ("recorded", "기록됨"),
        ("superseded", "대체됨"),
    ]
    EVIDENCE_BASES = [
        ("explicit_reply", "명시적 답변"),
        ("explicit_instruction", "명시적 지시"),
        ("inferred", "AI 추론"),
    ]
    SOURCES = [("web", "웹"), ("api", "API"), ("mcp", "MCP")]

    task = models.ForeignKey(
        Task, on_delete=models.PROTECT, related_name="decision_records"
    )
    kind = models.CharField(max_length=11, choices=KINDS)
    input_type = models.CharField(max_length=26, choices=INPUT_TYPES, null=True, blank=True)
    status = models.CharField(max_length=10, choices=STATUSES)
    question_summary = models.CharField(max_length=300, blank=True)
    summary = models.CharField(max_length=800)
    reason_summary = models.CharField(max_length=500, blank=True)
    rejection_reason = models.CharField(max_length=300, blank=True)
    alternatives = models.JSONField(default=list, blank=True)
    impact_summary = models.CharField(max_length=500, blank=True)
    recorded_by = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.SET_NULL,
        related_name="recorded_task_decisions",
        null=True,
        blank=True,
    )
    subject_user = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.SET_NULL,
        related_name="subject_task_decisions",
        null=True,
        blank=True,
    )
    confirmed_by = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.SET_NULL,
        related_name="confirmed_task_decisions",
        null=True,
        blank=True,
    )
    evidence_basis = models.CharField(
        max_length=20, choices=EVIDENCE_BASES, null=True, blank=True
    )
    source = models.CharField(max_length=3, choices=SOURCES)
    client_name = models.CharField(max_length=80, blank=True)
    session_ref = models.CharField(max_length=200, blank=True)
    # Verbatim content is an explicit web-only exception; MCP schemas must omit it.
    verbatim_text = models.CharField(max_length=4000, blank=True)
    supersedes = models.ForeignKey(
        "self",
        on_delete=models.PROTECT,
        related_name="superseding_records",
        null=True,
        blank=True,
    )
    created_at = models.DateTimeField(auto_now_add=True)
    confirmed_at = models.DateTimeField(null=True, blank=True)
    source_time = models.DateTimeField(null=True, blank=True)
    client_request_id = models.UUIDField(null=True, blank=True)

    class Meta:
        ordering = ["created_at", "id"]
        constraints = [
            models.CheckConstraint(
                condition=~Q(summary=""), name="decision_summary_nonempty"
            ),
            models.CheckConstraint(
                condition=(
                    Q(
                        kind="user_input",
                        input_type__in=[
                            "major_choice",
                            "requirement",
                            "answer",
                            "steer",
                            "implementation_instruction",
                            "ai_workflow_instruction",
                        ],
                    )
                    | Q(kind="ai_judgment", input_type__isnull=True)
                ),
                name="decision_kind_input_type",
            ),
            models.CheckConstraint(
                condition=(
                    Q(
                        kind="user_input",
                        status__in=["captured", "proposed", "confirmed", "rejected", "superseded"],
                        evidence_basis__in=[
                            "explicit_reply", "explicit_instruction", "inferred"
                        ],
                    )
                    | Q(
                        kind="ai_judgment",
                        status__in=["recorded", "superseded"],
                        evidence_basis__isnull=True,
                    )
                ),
                name="decision_kind_status_basis",
            ),
            models.CheckConstraint(
                condition=(
                    Q(
                        kind="user_input",
                        status="confirmed",
                        confirmed_by__isnull=False,
                        confirmed_at__isnull=False,
                    )
                    | Q(
                        kind="user_input",
                        status__in=["captured", "proposed", "rejected"],
                        confirmed_by__isnull=True,
                        confirmed_at__isnull=True,
                    )
                    | Q(
                        kind="user_input",
                        status="superseded",
                        confirmed_by__isnull=True,
                        confirmed_at__isnull=True,
                    )
                    | Q(
                        kind="user_input",
                        status="superseded",
                        confirmed_by__isnull=False,
                        confirmed_at__isnull=False,
                    )
                    | Q(
                        kind="ai_judgment",
                        confirmed_by__isnull=True,
                        confirmed_at__isnull=True,
                    )
                ),
                name="decision_confirmation_fields",
            ),
            models.UniqueConstraint(
                fields=["task", "subject_user", "client_request_id"],
                condition=Q(subject_user__isnull=False, client_request_id__isnull=False),
                name="decision_req_user_uniq",
            ),
            models.UniqueConstraint(
                fields=["task", "client_request_id"],
                condition=Q(subject_user__isnull=True, client_request_id__isnull=False),
                name="decision_req_task_uniq",
            ),
        ]
        indexes = [
            models.Index(fields=["task", "created_at", "id"]),
            models.Index(fields=["task", "status", "created_at"]),
            models.Index(fields=["confirmed_by", "confirmed_at"]),
        ]

    def __str__(self):
        return f"{self.task.number} decision {self.pk}: {self.summary[:60]}"


class ChecklistItem(models.Model):
    task = models.ForeignKey(Task, on_delete=models.CASCADE, related_name="checklist")
    text = models.CharField(max_length=200)
    is_done = models.BooleanField(default=False)
    position = models.PositiveIntegerField(default=0)

    class Meta:
        ordering = ["position", "id"]


class TodayItem(models.Model):
    """사용자별·날짜별 오늘 목록. excluded=False면 직접 담은 것, True면 '오늘 제외'한 것."""

    user = models.ForeignKey(
        settings.AUTH_USER_MODEL, on_delete=models.CASCADE, related_name="today_items"
    )
    task = models.ForeignKey(Task, on_delete=models.CASCADE, related_name="today_items")
    date = models.DateField()
    position = models.PositiveIntegerField(default=0)
    excluded = models.BooleanField(default=False)

    class Meta:
        ordering = ["position", "id"]
        constraints = [
            models.UniqueConstraint(fields=["user", "task", "date"], name="today_user_task_date"),
        ]


class Link(models.Model):
    KINDS = [
        ("doc", "문서"),
        ("issue", "이슈"),
        ("dash", "대시보드"),
        ("other", "기타"),
        # 아래 둘은 이제 폼에서 고를 수 없다. PR·저장소는 GitHub 연결이 자동으로 붙인다.
        ("pr", "PR"),
        ("repo", "저장소"),
    ]

    project = models.ForeignKey(
        "projects.Project", on_delete=models.CASCADE, null=True, blank=True, related_name="links"
    )
    task = models.ForeignKey(
        Task, on_delete=models.CASCADE, null=True, blank=True, related_name="links"
    )
    title = models.CharField(max_length=100)
    url = models.URLField(max_length=500)
    kind = models.CharField(max_length=5, choices=KINDS, default="doc")
    created_by = models.ForeignKey(
        settings.AUTH_USER_MODEL, on_delete=models.PROTECT, related_name="+"
    )
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ["id"]
        constraints = [
            models.CheckConstraint(
                condition=(Q(project__isnull=False) & Q(task__isnull=True))
                | (Q(project__isnull=True) & Q(task__isnull=False)),
                name="link_exactly_one_target",
            ),
        ]


class ChangeLog(models.Model):
    TARGETS = [("task", "task"), ("project", "project"), ("org", "org")]
    # source는 max_length=4다. "discord"는 안 들어가므로 코드는 "dc", 표시는 "Discord".
    SOURCES = [("web", "웹"), ("api", "API"), ("mcp", "AI"), ("dc", "Discord"), ("gh", "GitHub")]

    target_type = models.CharField(max_length=10, choices=TARGETS)
    target_id = models.PositiveBigIntegerField()
    field = models.CharField(max_length=40)
    old_value = models.TextField(blank=True)
    new_value = models.TextField(blank=True)
    note = models.CharField(max_length=200, blank=True)
    # GitHub 이벤트의 행위자가 아직 PM 계정과 이어지지 않았을 때 로그인을 남긴다(GUIDE-V2-07).
    # 그 사람이 GitHub를 연결하면 소급해서 actor를 채운다.
    actor = models.ForeignKey(
        settings.AUTH_USER_MODEL, on_delete=models.PROTECT, related_name="+", null=True, blank=True
    )
    external_actor = models.CharField(max_length=100, blank=True)
    source = models.CharField(max_length=4, choices=SOURCES)
    token = models.ForeignKey(
        "accounts.ApiToken", on_delete=models.SET_NULL, null=True, blank=True, related_name="+"
    )
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ["created_at", "id"]
        indexes = [
            models.Index(fields=["target_type", "target_id"]),
            models.Index(fields=["created_at"]),
        ]
