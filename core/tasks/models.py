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
        "todo": "아직 손대지 않았어요.",
        "doing": "지금 하고 있어요.",
        "paused": "개인 사유나 다른 작업 때문에 잠시 멈췄어요. 다시 시작하면 진행 중으로 바꿔 주세요.",
        "blocked": "운영상 문제 등 외부 요인으로 멈췄어요. 팀이 함께 풀어야 하는 상태예요.",
        "review": "다 했고, 다른 사람의 확인을 기다려요.",
        "done": "끝났어요.",
        "cancelled": "하지 않기로 했어요.",
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
