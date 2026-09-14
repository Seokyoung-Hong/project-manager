from django.conf import settings as conf  # 모델의 settings 필드와 이름이 겹친다
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
        "active": "개발 또는 구현 진행 중",
        "paused": "외부 사유나 리소스 부족으로 잠시 멈춤",
        "done": "유지보수 외 별도 작업 없음",
        "stopped": "모든 작업이 완료되어 현재 상태로 종료 가능하지만, 다른 프로젝트와의 연계 가능성이 높아 추후 재개될 여지가 많은 상태",
        "eol": "프로젝트가 더 이상 필요하지 않거나 대체되어, 유지보수·재개 가능성 모두 없는 상태",
    }

    org = models.ForeignKey("orgs.Organization", on_delete=models.CASCADE, related_name="projects")
    teams = models.ManyToManyField(
        "orgs.Team", blank=True, related_name="projects", verbose_name="담당 팀"
    )
    name = models.CharField("이름", max_length=100)
    purpose = models.CharField("목적", max_length=200, blank=True)
    owners = models.ManyToManyField(
        conf.AUTH_USER_MODEL, blank=True, related_name="owned_projects", verbose_name="관리자"
    )
    status = models.CharField("상태", max_length=10, choices=STATUSES, default="preparing")
    discord_channel_id = models.CharField("Discord 채널", max_length=32, blank=True)
    # 프로젝트 설정(조직 설정 덮어쓰기). 조직이 잠근 키는 무시된다.
    settings = models.JSONField("설정", default=dict, blank=True)
    # 조직 거버넌스 뒤에 덧붙는 프로젝트 문단.
    governance_extra = models.TextField("프로젝트 거버넌스", blank=True)
    is_archived = models.BooleanField(default=False)
    archived_at = models.DateTimeField(null=True, blank=True)
    version = models.PositiveIntegerField(default=1)
    created_by = models.ForeignKey(conf.AUTH_USER_MODEL, on_delete=models.PROTECT, related_name="+")
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

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


class Milestone(models.Model):
    STATUSES = [("planned", "준비 중"), ("active", "진행 중"), ("done", "완료")]

    project = models.ForeignKey(Project, on_delete=models.CASCADE, related_name="milestones")
    name = models.CharField("이름", max_length=100)
    start_date = models.DateField("시작일", null=True, blank=True)
    target_date = models.DateField("목표일")
    status = models.CharField("상태", max_length=7, choices=STATUSES, default="planned")
    created_by = models.ForeignKey(conf.AUTH_USER_MODEL, on_delete=models.PROTECT, related_name="+")
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
        conf.AUTH_USER_MODEL, on_delete=models.PROTECT, related_name="+"
    )

    def __str__(self):
        return f"{self.project.name} API"


class ProjectDependency(models.Model):
    from_project = models.ForeignKey(Project, on_delete=models.CASCADE, related_name="dependencies")
    to_project = models.ForeignKey(Project, on_delete=models.CASCADE, related_name="dependents")
    note = models.CharField("메모", max_length=200, blank=True)
    is_blocking = models.BooleanField("차단", default=False)
    created_by = models.ForeignKey(conf.AUTH_USER_MODEL, on_delete=models.PROTECT, related_name="+")
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
