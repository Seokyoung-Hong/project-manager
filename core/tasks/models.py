import uuid
from pathlib import PurePath

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
    # 계열(회차·변형). 평평하다 — parent는 항상 계열의 뿌리이고 뿌리의 parent는 None이다.
    parent = models.ForeignKey(
        "self",
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name="children",
        verbose_name="원본",
    )
    # 템플릿은 진행하지 않는다. 회차는 duplicate_task로 만든다(자동 생성 없음).
    is_template = models.BooleanField("템플릿", default=False)
    reviewer = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name="reviewing_tasks",
        verbose_name="검토자",
    )

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
            models.CheckConstraint(
                condition=~Q(is_template=True) | Q(status="todo"),
                name="task_template_is_todo",
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

    task = models.ForeignKey(Task, on_delete=models.PROTECT, related_name="decision_records")
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
    evidence_basis = models.CharField(max_length=20, choices=EVIDENCE_BASES, null=True, blank=True)
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
            models.CheckConstraint(condition=~Q(summary=""), name="decision_summary_nonempty"),
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
                        evidence_basis__in=["explicit_reply", "explicit_instruction", "inferred"],
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
        ("out", "산출물"),
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


class WorkRequest(models.Model):
    """팀이나 사람에게 보내는 요청. GitHub 이슈와 달리 조직 밖에는 보이지 않는다.

    - work: 일을 맡아 달라는 요청. 받는 쪽이 프로젝트를 골라 수락하면 태스크가 생긴다.
    - assign: 이미 있는 태스크의 담당을 넘겨받아 달라는 요청. 수락해야 담당자가 바뀐다.
    - general: 태스크로 만들 일은 아닌 부탁(검토·확인 등). 수락한 뒤 완료로 닫는다.
    """

    KINDS = [("work", "작업 요청"), ("assign", "담당 요청"), ("general", "일반 요청")]
    STATUSES = [
        ("pending", "대기"),
        ("accepted", "수락"),
        ("declined", "거절"),
        ("cancelled", "취소"),
        ("done", "완료"),
    ]

    org = models.ForeignKey("orgs.Organization", on_delete=models.CASCADE, related_name="+")
    kind = models.CharField(max_length=7, choices=KINDS)
    title = models.CharField("제목", max_length=200)
    body = models.TextField("내용", blank=True)
    requested_by = models.ForeignKey(
        settings.AUTH_USER_MODEL, on_delete=models.PROTECT, related_name="+"
    )
    # 받는 쪽은 팀 하나 또는 사람 한 명이다.
    team = models.ForeignKey(
        "orgs.Team", on_delete=models.CASCADE, null=True, blank=True, related_name="requests"
    )
    to_user = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.CASCADE,
        null=True,
        blank=True,
        related_name="received_requests",
    )
    # assign은 넘길 태스크, work는 수락해서 생긴 태스크
    due_date = models.DateField("희망 기한", null=True, blank=True)
    task = models.ForeignKey(
        Task, on_delete=models.SET_NULL, null=True, blank=True, related_name="requests"
    )
    status = models.CharField(max_length=9, choices=STATUSES, default="pending")
    responded_by = models.ForeignKey(
        settings.AUTH_USER_MODEL, on_delete=models.SET_NULL, null=True, blank=True, related_name="+"
    )
    responded_at = models.DateTimeField(null=True, blank=True)
    response_note = models.CharField("답변", max_length=300, blank=True)
    source = models.CharField(max_length=4, choices=ChangeLog.SOURCES, default="web")
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ["-created_at", "-id"]
        constraints = [
            models.CheckConstraint(
                condition=Q(team__isnull=True) ^ Q(to_user__isnull=True),
                name="workrequest_one_target",
            ),
        ]
        indexes = [models.Index(fields=["status", "to_user"])]

    def __str__(self):
        return f"{self.number} {self.title}"

    @property
    def number(self) -> str:
        return f"REQ-{self.pk}"

    @property
    def is_open(self) -> bool:
        return self.status == "pending"

    @property
    def path(self) -> str:
        return f"/requests/{self.pk}"


class Notice(models.Model):
    """Discord로 보낼 알림. core는 Discord에 직접 보내지 않으므로(GUIDE-00) 여기 쌓고 봇이 가져간다.

    받는 곳은 사람(DM) 또는 채널 하나다. 보낼 수 없는 알림(Discord 미연결)은 애초에 만들지 않는다.
    """

    org = models.ForeignKey("orgs.Organization", on_delete=models.CASCADE, related_name="+")
    user = models.ForeignKey(
        settings.AUTH_USER_MODEL, on_delete=models.CASCADE, null=True, blank=True, related_name="+"
    )
    channel_id = models.CharField(max_length=32, blank=True)
    text = models.TextField()
    created_at = models.DateTimeField(auto_now_add=True)
    sent_at = models.DateTimeField(null=True, blank=True)

    class Meta:
        ordering = ["id"]
        indexes = [models.Index(fields=["sent_at"])]


def attachment_path(instance, filename):
    """att/<org_id>/<uuid4 hex><ext>. 원래 이름은 Attachment.name에만 둔다(경로 조작·충돌 차단)."""
    project = instance.project or instance.task.project
    return f"att/{project.org_id}/{uuid.uuid4().hex}{PurePath(filename).suffix.lower()}"


class Attachment(models.Model):
    """태스크·프로젝트에 붙는 파일. 산출물(시안·게시 증빙)이면 kind로 구분하고 버전은 replaces로 잇는다."""

    KINDS = [("file", "파일"), ("out", "산출물"), ("proof", "증빙")]

    project = models.ForeignKey(
        "projects.Project",
        on_delete=models.CASCADE,
        null=True,
        blank=True,
        related_name="attachments",
    )
    task = models.ForeignKey(
        Task, on_delete=models.CASCADE, null=True, blank=True, related_name="attachments"
    )
    file = models.FileField(upload_to=attachment_path, max_length=200)
    name = models.CharField("파일 이름", max_length=200)  # 원래 이름(표시·다운로드용)
    size = models.PositiveBigIntegerField()
    # 확장자 표(tasks.attachments.ALLOWED)에서 정한 값. 업로드 헤더를 믿지 않는다.
    content_type = models.CharField(max_length=100)
    sha256 = models.CharField(max_length=64)
    kind = models.CharField(max_length=5, choices=KINDS, default="file")
    note = models.CharField("메모", max_length=200, blank=True)  # "v2 — 색 수정"
    version = models.PositiveSmallIntegerField(default=1)
    replaces = models.ForeignKey(
        "self", on_delete=models.SET_NULL, null=True, blank=True, related_name="replaced_by"
    )
    created_by = models.ForeignKey(
        settings.AUTH_USER_MODEL, on_delete=models.PROTECT, related_name="+"
    )
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ["-id"]
        constraints = [
            models.CheckConstraint(
                condition=(Q(project__isnull=False) & Q(task__isnull=True))
                | (Q(project__isnull=True) & Q(task__isnull=False)),
                name="attachment_exactly_one_target",
            ),
            # 버전 체인은 갈라지지 않는다 — 한 파일을 대체하는 새 버전은 하나뿐이다.
            models.UniqueConstraint(
                fields=["replaces"],
                condition=Q(replaces__isnull=False),
                name="attachment_single_successor",
            ),
        ]

    def __str__(self):
        return self.name

    @property
    def target_project(self):
        return self.project or self.task.project
