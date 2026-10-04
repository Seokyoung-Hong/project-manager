from django.conf import settings
from django.db import models


class Project(models.Model):
    STATUSES = [
        ("preparing", "🧪 준비 중"),
        ("on_hold", "🕓 보류 중"),
        ("waiting", "🗂️ 대기 중"),
        ("active", "🚧 진행 중"),
        ("paused", "⏸️ 일시 중단"),
        ("done", "✅ 완료"),
        ("stopped", "🛑 정지"),
        ("eol", "⚰️ 지원 종료"),
    ]
    STATUS_DESC = {
        "preparing": "기획/기초 구상 중",
        "on_hold": "기능 추가 예정이나 우선순위 낮아 대기 중",
        "waiting": "착수 예정이지만 아직 명확하지 않음",
        "active": "작업 진행 중",
        "paused": "외부 사유나 리소스 부족으로 잠시 멈춤",
        "done": "계획한 작업을 모두 마침(유지 작업만 남음)",
        "stopped": "모든 작업이 완료되어 현재 상태로 종료 가능하지만, 다른 프로젝트와의 연계 가능성이 높아 추후 재개될 여지가 많은 상태",
        "eol": "프로젝트가 더 이상 필요하지 않거나 대체되어, 유지보수·재개 가능성 모두 없는 상태",
    }

    VISIBILITIES = [("org", "조직 전체"), ("teams", "담당 팀만")]

    org = models.ForeignKey("orgs.Organization", on_delete=models.CASCADE, related_name="projects")
    teams = models.ManyToManyField(
        "orgs.Team", blank=True, related_name="projects", verbose_name="담당 팀"
    )
    name = models.CharField("이름", max_length=100)
    purpose = models.CharField("목적", max_length=200, blank=True)
    owners = models.ManyToManyField(
        settings.AUTH_USER_MODEL, blank=True, related_name="owned_projects", verbose_name="관리자"
    )
    status = models.CharField("상태", max_length=10, choices=STATUSES, default="preparing")
    discord_channel_id = models.CharField("Discord 채널", max_length=32, blank=True)
    discord_channel_managed = models.BooleanField("채널 자동 관리", default=False)
    visibility = models.CharField("공개 범위", max_length=5, choices=VISIBILITIES, default="org")
    is_archived = models.BooleanField(default=False)
    archived_at = models.DateTimeField(null=True, blank=True)
    version = models.PositiveIntegerField(default=1)
    created_by = models.ForeignKey(
        settings.AUTH_USER_MODEL, on_delete=models.PROTECT, related_name="+"
    )
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)
    governance_extra = models.TextField("프로젝트 거버넌스", blank=True)
    # settings.AUTH_USER_MODEL을 쓰는 필드들 뒤에 온다(orgs.Organization.settings와 같은 이유).
    settings = models.JSONField("설정", default=dict, blank=True)

    class Meta:
        ordering = ["name"]
        constraints = [
            models.UniqueConstraint(fields=["org", "name"], name="project_org_name"),
        ]

    def __str__(self):
        return self.name

    @property
    def status_label(self) -> str:
        return dict(self.STATUSES)[self.status]

    @property
    def status_desc(self) -> str:
        return self.STATUS_DESC[self.status]

    @property
    def dev_tools(self) -> bool:
        """개발 화면을 보일지. 저장소가 연결돼 있으면 설정과 무관하게 켬(데이터 숨김 방지)."""
        from orgs.settings import effective

        if getattr(self, "repo", None) is not None:
            return True
        return effective("project.dev_tools", org=self.org, project=self)


class Milestone(models.Model):
    STATUSES = [("planned", "준비 중"), ("active", "진행 중"), ("done", "완료")]

    project = models.ForeignKey(Project, on_delete=models.CASCADE, related_name="milestones")
    name = models.CharField("이름", max_length=100)
    start_date = models.DateField("시작일", null=True, blank=True)
    target_date = models.DateField("목표일")
    status = models.CharField("상태", max_length=7, choices=STATUSES, default="planned")
    created_by = models.ForeignKey(
        settings.AUTH_USER_MODEL, on_delete=models.PROTECT, related_name="+"
    )
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ["target_date", "id"]

    def __str__(self):
        return self.name

    @property
    def status_label(self) -> str:
        return dict(self.STATUSES)[self.status]


class ApiSpec(models.Model):
    project = models.OneToOneField(Project, on_delete=models.CASCADE, related_name="api_spec")
    source_url = models.CharField("출처", max_length=500, blank=True)
    spec = models.JSONField()
    fetched_at = models.DateTimeField(auto_now=True)
    uploaded_by = models.ForeignKey(
        settings.AUTH_USER_MODEL, on_delete=models.PROTECT, related_name="+"
    )

    def __str__(self):
        return f"{self.project.name} API"


class ProjectDoc(models.Model):
    """프로젝트 전용 문서. GitHub의 README·Wiki 자리를 앱 안에서 대신한다.

    회의록(notes.MeetingNote)과 나란한 구조지만 조직이 아니라 프로젝트에 매인다.
    같은 블록 편집기(web/static/notes.js)를 쓰므로 저장 규약(X-Note-Version)도 같다.
    """

    # tasks.ChangeLog.SOURCES와 같은 코드를 쓴다. "discord"는 4자를 넘으므로 "dc"다.
    SOURCES = [("web", "웹"), ("api", "API"), ("mcp", "AI"), ("dc", "Discord")]

    project = models.ForeignKey(Project, on_delete=models.CASCADE, related_name="docs")
    title = models.CharField("제목", max_length=200, default="제목 없는 문서")
    body_md = models.TextField("본문", blank=True)
    version = models.PositiveIntegerField(default=1)
    # 이 문서가 다루는 태스크. 같은 프로젝트의 태스크만 건다(docs.link_task가 검사한다).
    tasks = models.ManyToManyField("tasks.Task", blank=True, related_name="docs")
    created_by = models.ForeignKey(
        settings.AUTH_USER_MODEL, on_delete=models.PROTECT, related_name="+"
    )
    # 마지막으로 고친 사람과 경로. AI도 문서를 고치므로, 누가 언제 손댔는지 화면에서 보여야 한다.
    updated_by = models.ForeignKey(
        settings.AUTH_USER_MODEL, on_delete=models.PROTECT, related_name="+", null=True, blank=True
    )
    updated_source = models.CharField(max_length=4, choices=SOURCES, default="web")
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        # 만든 순서로 고정한다. 수정할 때마다 목록이 뒤집히면 문서를 다시 찾기 어렵다.
        ordering = ["created_at", "id"]

    def __str__(self):
        return self.title


class ProjectDependency(models.Model):
    from_project = models.ForeignKey(Project, on_delete=models.CASCADE, related_name="dependencies")
    to_project = models.ForeignKey(Project, on_delete=models.CASCADE, related_name="dependents")
    note = models.CharField("메모", max_length=200, blank=True)
    is_blocking = models.BooleanField("차단", default=False)
    created_by = models.ForeignKey(
        settings.AUTH_USER_MODEL, on_delete=models.PROTECT, related_name="+"
    )
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ["-is_blocking", "id"]
        constraints = [
            models.UniqueConstraint(
                fields=["from_project", "to_project"], name="dependency_from_to"
            ),
            models.CheckConstraint(
                condition=~models.Q(from_project=models.F("to_project")),
                name="dependency_not_self",
            ),
        ]
