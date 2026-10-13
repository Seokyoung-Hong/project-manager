"""AI 자동완성(IMPL-PLAN-12 §3). 이 앱의 모델·마이그레이션은 A0 갈래만 바꾼다."""

from django.conf import settings
from django.db import models

# 작업·설정 행에 남는 오류 코드(§11.4). 로그·화면에는 이 코드만 나간다 — 키·본문·응답 일부는 금지.
ERROR_CODES = (
    "connect_failed",
    "timeout",
    "http_4xx",
    "http_5xx",
    "auth_failed",
    "model_not_found",
    "bad_output",
    "too_large",
    "blocked_address",
    "pc_offline",
    "pc_unlinked",
    "pc_error",
    "no_source",
    "no_worker",
    "org_disabled",
    "cancelled",
    "codex_missing",
    "codex_auth",
    "codex_link_update",  # PC의 udally-link가 Codex를 모르는 옛 버전(heartbeat에 codex 칸 없음)
    "rate",
)
CODEX_URL = (
    "codex:"  # 개인 AI "Codex(내 구독, 내 PC)" — 주소 대신 이 값, route=pc(마이그레이션 없이 표현)
)

ROUTES = [
    ("direct", "유달리 서버에서 요청"),  # COPY:assist_route_direct
    ("pc", "내 PC 거쳐 보내기"),  # COPY:assist_route_pc
    ("org", "조직 AI"),
]


class AiSource(models.Model):
    """사용자 AI 목록 한 행(§3.1). 개인 AI 여러 개 + "조직 AI" 자리 한 행을 position 순으로 시도한다.

    kind=org 행은 "작업 대상 조직의 조직 AI" 자리라 조직 FK·주소가 없다. 사람당 하나.
    """

    KINDS = [("personal", "개인 AI"), ("org", "조직 AI")]
    MAX_PERSONAL = 5  # 사람당 개인 AI 상한(서비스가 센다)

    user = models.ForeignKey(
        settings.AUTH_USER_MODEL, on_delete=models.CASCADE, related_name="ai_sources"
    )
    kind = models.CharField(max_length=10, choices=KINDS, default="personal")
    name = models.CharField(max_length=50, blank=True)
    base_url = models.CharField(max_length=300, blank=True)  # .../v1까지. org 행은 빈 값
    route = models.CharField(max_length=10, choices=ROUTES[:2], blank=True)  # 저장 때 net.classify
    # 거쳐 갈 내 PC. 저장 때 server.owner_id == user_id(불변식 1, §5.3). PC를 끊으면 NULL → plan()에서 빠진다.
    server = models.ForeignKey(
        "notes.SttServer",
        null=True,
        blank=True,
        on_delete=models.SET_NULL,
        related_name="ai_sources",
    )
    api_key = models.TextField(blank=True)  # "enc:"+Fernet. 화면엔 설정됨/미설정만
    model = models.CharField(max_length=200, blank=True)
    position = models.PositiveIntegerField(default=0)
    enabled = models.BooleanField(default=True)
    last_ok_at = models.DateTimeField(null=True, blank=True)
    last_error = models.CharField(max_length=40, blank=True)  # ERROR_CODES

    class Meta:
        ordering = ["position", "id"]
        constraints = [
            models.UniqueConstraint(
                fields=["user"], condition=models.Q(kind="org"), name="uniq_ai_source_org"
            )
        ]

    def __str__(self):
        return self.name or self.get_kind_display()

    @property
    def is_codex(self) -> bool:
        return self.base_url == CODEX_URL


class AiJob(models.Model):
    """AI 작업 한 번(§3.2). 메시지 본문은 저장하지 않는다 — 실행 직전에 요청자 권한으로 다시 조립한다(§10.2)."""

    KINDS = [("field", "칸"), ("doc", "문서"), ("meeting", "회의록"), ("extract", "태스크 후보")]
    STATUSES = [
        ("queued", "대기"),
        ("running", "쓰는 중"),
        ("cancelling", "취소 중"),
        ("done", "끝남"),
        ("failed", "실패"),
        ("cancelled", "취소됨"),
    ]
    ACTIVE = ("queued", "running", "cancelling")
    MAX_INPUT = 8000  # user_input 상한(서비스가 자른다)
    MAX_RESULT = 256 * 1024  # result 상한(바이트, PC 보고는 넘으면 413)

    user = models.ForeignKey(
        settings.AUTH_USER_MODEL, on_delete=models.CASCADE, related_name="ai_jobs"
    )
    org = models.ForeignKey("orgs.Organization", on_delete=models.CASCADE, related_name="+")
    kind = models.CharField(max_length=10, choices=KINDS)
    field = models.CharField(max_length=60)  # 칸 키 또는 모드(assist.fields)
    target_type = models.CharField(
        max_length=20, blank=True
    )  # task|project|doc|request|issue|org|user
    target_id = models.PositiveBigIntegerField(null=True, blank=True)
    user_input = models.TextField(blank=True)
    options = models.JSONField(default=dict, blank=True)  # 템플릿 id 등
    status = models.CharField(max_length=12, choices=STATUSES, default="queued")
    route = models.CharField(max_length=10, choices=ROUTES, blank=True)  # 지금 시도 경로
    source = models.ForeignKey(
        AiSource, null=True, blank=True, on_delete=models.SET_NULL, related_name="jobs"
    )
    server = models.ForeignKey(
        "notes.SttServer",
        null=True,
        blank=True,
        on_delete=models.SET_NULL,
        related_name="ai_jobs",
    )
    tried = models.JSONField(default=list, blank=True)  # [{route, source_id, error}]
    result = models.TextField(blank=True)  # 미리보기 글 또는 검증된 JSON
    usage = models.JSONField(default=dict, blank=True)
    error = models.CharField(max_length=40, blank=True)  # ERROR_CODES
    claimed_at = models.DateTimeField(null=True, blank=True)
    created_at = models.DateTimeField(auto_now_add=True)
    finished_at = models.DateTimeField(null=True, blank=True)
    applied_at = models.DateTimeField(null=True, blank=True)

    class Meta:
        ordering = ["-created_at", "-id"]
        indexes = [
            models.Index(fields=["status", "created_at"], name="assist_job_status"),
            models.Index(fields=["user", "created_at"], name="assist_job_user"),
            # 조직 AI 하루 한도(요청자·조직·오늘). 조직 AI 행 없이 맨 뒤에 붙는 시도는 source가 NULL이라
            # 계획서의 (org, source, created_at) 대신 요청자 기준으로 둔다.
            models.Index(fields=["org", "user", "created_at"], name="assist_job_org_user"),
        ]

    def __str__(self):
        return f"AI 작업 #{self.pk}"


class AllowedHost(models.Model):
    """운영자가 허용한 사설 호스트(§3.3). 조직 AI에만, 호스트 문자열 정확 일치만(와일드카드 없음)."""

    host = models.CharField(max_length=253, unique=True)  # 소문자 호스트 이름 또는 IP 리터럴
    added_by = models.ForeignKey(
        settings.AUTH_USER_MODEL, null=True, blank=True, on_delete=models.SET_NULL, related_name="+"
    )
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ["host"]

    def __str__(self):
        return self.host


class CodexLogin(models.Model):
    """웹에서 시작한 Codex 로그인·로그아웃 한 건(PC당 하나, 진행 중 1개).

    토큰·auth.json은 PC 밖으로 나오지 않는다. 여기엔 기기 코드 화면에 필요한 인증 주소·사용자 코드·만료만
    잠깐 두고, 끝나거나 만료되면 지운다(assist.codex_login.tidy). 로그인 여부는 SttServer.device["codex"].
    """

    STATES = [
        ("requested", "PC에 요청함"),
        ("code", "코드 표시 중"),
        ("done", "끝남"),
        ("failed", "실패"),
        ("expired", "만료"),
    ]
    server = models.OneToOneField(
        "notes.SttServer", on_delete=models.CASCADE, related_name="codex_login"
    )
    action = models.CharField(max_length=10, default="login")  # login | logout
    state = models.CharField(max_length=10, choices=STATES, default="requested")
    url = models.CharField(max_length=200, blank=True)
    code = models.CharField(max_length=20, blank=True)
    expires_at = models.DateTimeField(null=True, blank=True)
    error = models.CharField(max_length=40, blank=True)
    updated_at = models.DateTimeField(auto_now=True)

    def __str__(self):
        return f"Codex {self.action} #{self.pk}"
