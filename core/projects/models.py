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
    # GitHub 마일스톤 번호. 저장소 하나가 프로젝트 둘에 이어지면 프로젝트마다 한 행씩 생긴다.
    gh_number = models.PositiveIntegerField(null=True, blank=True)

    class Meta:
        ordering = ["target_date", "id"]
        constraints = [
            models.UniqueConstraint(
                fields=["project", "gh_number"],
                condition=models.Q(gh_number__isnull=False),
                name="milestone_project_gh_number",
            )
        ]

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


class Doc(models.Model):
    """문서. 조직·프로젝트·팀 범위의 마크다운 글이고, 하위 문서로 트리를 이룬다(IMPL-PLAN-11 §4).

    회의록도 문서의 한 종류(kind="meeting")다 — 편집기·이전 버전·백링크·첨부를 한 벌로 쓴다.
    공개 범위(project·team)는 뿌리 문서에만 뜻이 있고, 하위 문서는 뿌리 값을 복사해 둔다
    (조회를 평평하게. docs.move_doc이 하위를 다시 쓴다).
    같은 블록 편집기(web/static/notes.js)를 쓰므로 저장 규약(X-Note-Version)도 같다.
    """

    KINDS = [("doc", "문서"), ("meeting", "회의록")]
    ORIGINS = [("web", "웹"), ("voice", "음성 회의"), ("import", "가져오기")]
    # tasks.ChangeLog.SOURCES와 같은 코드를 쓴다. "discord"는 4자를 넘으므로 "dc"다.
    SOURCES = [("web", "웹"), ("api", "API"), ("mcp", "AI"), ("dc", "Discord")]

    org = models.ForeignKey("orgs.Organization", on_delete=models.CASCADE, related_name="docs")
    kind = models.CharField(max_length=7, choices=KINDS, default="doc")
    # 범위가 비면 "조직 전체"로 읽힌다. 그래서 범위 삭제가 문서를 조용히 넓히지 않게 RESTRICT로 막고
    # 서비스가 명시적으로 처리한다(프로젝트 삭제는 문서도 지우고, 팀 삭제는 문서가 있으면 거절).
    # 조직 삭제는 org CASCADE로 문서도 함께 지워지므로 RESTRICT에 걸리지 않는다.
    project = models.ForeignKey(
        Project, on_delete=models.RESTRICT, null=True, blank=True, related_name="docs"
    )
    team = models.ForeignKey(
        "orgs.Team", on_delete=models.RESTRICT, null=True, blank=True, related_name="docs"
    )
    parent = models.ForeignKey(
        "self", on_delete=models.CASCADE, null=True, blank=True, related_name="children"
    )
    position = models.PositiveIntegerField(default=0)
    is_template = models.BooleanField(default=False)
    # 회의록 열(kind="meeting"에서만 뜻이 있다). 음성 회의 초안은 진행자·조직 관리자만 본다.
    status = models.CharField(
        max_length=5, choices=[("draft", "초안"), ("final", "확정")], default="final"
    )
    origin = models.CharField(max_length=6, choices=ORIGINS, default="web")
    created_on = models.DateTimeField("회의 일시", null=True, blank=True)
    tags = models.JSONField(default=list, blank=True)
    # md 가져오기의 중복 방지 키(Notion 페이지 id 또는 이름+본문 해시). 사람이 만든 문서는 빈 값.
    import_key = models.CharField(max_length=64, blank=True, db_index=True)
    attendees = models.ManyToManyField(settings.AUTH_USER_MODEL, blank=True, related_name="+")
    title = models.CharField("제목", max_length=200, default="제목 없는 문서")
    body_md = models.TextField("본문", blank=True)
    version = models.PositiveIntegerField(default=1)
    # 이 문서가 다루는 태스크(docs.link_task가 범위를 검사한다).
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
        ordering = ["position", "created_at", "id"]
        constraints = [
            models.CheckConstraint(
                condition=models.Q(project__isnull=True) | models.Q(team__isnull=True),
                name="doc_scope_one",
            ),
            models.CheckConstraint(
                condition=~models.Q(kind="meeting") | models.Q(parent__isnull=True),
                name="doc_meeting_no_parent",
            ),
        ]
        indexes = [
            models.Index(fields=["org", "kind", "parent"]),
            models.Index(fields=["org", "kind", "created_on"]),
        ]

    def __str__(self):
        return self.title

    # 옛 회의록(MeetingNote.source) 이름. 웹·API 응답이 그대로 쓴다.
    @property
    def source(self) -> str:
        return self.origin

    def save(self, *args, **kwargs):
        # 프로젝트 문서를 org 없이 만들던 호출(옛 ProjectDoc)이 그대로 돌게 한다.
        if self.org_id is None and self.project_id is not None:
            self.org_id = self.project.org_id
        super().save(*args, **kwargs)


# 옛 이름. 호출부·테스트가 그대로 쓴다.
ProjectDoc = Doc


class DocRevision(models.Model):
    """저장 이력. 자동 저장(0.8초)마다 쌓이지 않게 같은 사람·10분 안은 마지막 행을 덮어쓴다."""

    doc = models.ForeignKey(Doc, on_delete=models.CASCADE, related_name="revisions")
    version = models.PositiveIntegerField()
    title = models.CharField(max_length=200)
    body_md = models.TextField(blank=True)
    saved_by = models.ForeignKey(
        settings.AUTH_USER_MODEL, on_delete=models.SET_NULL, null=True, related_name="+"
    )
    source = models.CharField(max_length=4, choices=Doc.SOURCES, default="web")
    saved_at = models.DateTimeField()

    class Meta:
        ordering = ["-version"]
        constraints = [
            models.UniqueConstraint(fields=["doc", "version"], name="docrevision_doc_version")
        ]


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
