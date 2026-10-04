import secrets
from datetime import timedelta

from django.conf import settings
from django.db import models
from django.utils import timezone


def _token():
    return secrets.token_urlsafe(32)


def _default_expiry():
    return timezone.now() + timedelta(days=7)


class Organization(models.Model):
    """가시성의 경계. 조직 멤버는 조직의 프로젝트·태스크를 전부 본다."""

    name = models.CharField("이름", max_length=100)
    purpose = models.CharField("목적", max_length=200, blank=True)
    # 개발 거버넌스(마크다운). 비어 있으면 governance.DEFAULT_GOVERNANCE를 쓴다.
    governance = models.TextField("개발 거버넌스", blank=True)
    created_by = models.ForeignKey(
        settings.AUTH_USER_MODEL, on_delete=models.PROTECT, related_name="+"
    )
    created_at = models.DateTimeField(auto_now_add=True)
    members = models.ManyToManyField(
        settings.AUTH_USER_MODEL, through="OrgMembership", related_name="orgs"
    )
    # Discord 바인딩(IMPL-PLAN-4 §8.4). 길드 하나는 조직 하나에만 붙는다 — 한 채널에 두 조직의
    # 알림이 섞이면 아무도 안 본다. 채널은 길드 안에서 `/알림채널`로 정한다(core는 봇 토큰이 없다).
    discord_guild_id = models.CharField(
        "Discord 서버", max_length=32, null=True, blank=True, unique=True
    )
    discord_channel_id = models.CharField("알림 채널", max_length=32, blank=True)
    discord_linked_at = models.DateTimeField(null=True, blank=True)
    # 봇이 길드 권한과 감시 시각을 보고한다(IMPL-PLAN-5 B). 권한이 모자라면 웹이 재설치를 안내하고,
    # 감시 시각이 오래되면 "감시 꺼짐"으로 보인다.
    discord_bot_permissions = models.BigIntegerField(null=True, blank=True)
    discord_watch_at = models.DateTimeField(null=True, blank=True)
    # 포털에서 Server Members 인텐트가 꺼져 봇이 인텐트 없이 다시 접속했다(감시 꺼짐의 원인).
    discord_intent_denied = models.BooleanField(default=False)
    discord_linked_by = models.ForeignKey(
        settings.AUTH_USER_MODEL, null=True, blank=True, on_delete=models.SET_NULL, related_name="+"
    )
    # 이 줄은 반드시 settings.AUTH_USER_MODEL을 쓰는 필드들 뒤에 온다 —
    # 클래스 본문에서 이름이 가려져 django.conf.settings를 더 못 읽기 때문이다.
    settings = models.JSONField("설정", default=dict, blank=True)

    class Meta:
        ordering = ["name"]

    def __str__(self):
        return self.name


class OrgMembership(models.Model):
    ROLES = [("admin", "관리자"), ("member", "멤버")]

    org = models.ForeignKey(Organization, on_delete=models.CASCADE, related_name="memberships")
    user = models.ForeignKey(
        settings.AUTH_USER_MODEL, on_delete=models.CASCADE, related_name="org_memberships"
    )
    role = models.CharField(max_length=6, choices=ROLES, default="member")
    # 스킬 태그(부하 현황에서 담당자 찾기에 쓴다). ArrayField는 Postgres 전용이라
    # SQLite 테스트가 깨진다.
    tags = models.JSONField(default=list, blank=True)
    joined_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        constraints = [
            models.UniqueConstraint(fields=["org", "user"], name="orgmembership_org_user"),
        ]

    def __str__(self):
        return f"{self.user} @ {self.org} ({self.role})"


class Team(models.Model):
    """조직 안의 사람 묶음(백엔드·프론트엔드 등).

    가시성을 제한하지 않는다. 부하 현황 필터, 프로젝트 담당 표시, GitHub 팀 연결에 쓴다.
    한 사람이 여러 팀에 속할 수 있다.
    """

    org = models.ForeignKey(Organization, on_delete=models.CASCADE, related_name="teams")
    name = models.CharField("이름", max_length=100)
    purpose = models.CharField("목적", max_length=200, blank=True)
    # 봇이 만든 팀 채널의 snowflake. 비밀이 아니고 core는 저장·표시만 한다(발송은 봇 전담).
    discord_channel_id = models.CharField("Discord 채널", max_length=32, blank=True)
    # 봇이 허용 집합의 멤버 덮어쓰기를 맞춰 주는 채널인가(IMPL-PLAN-5 B, 사용자 결정 3).
    discord_channel_managed = models.BooleanField("채널 자동 관리", default=False)
    created_by = models.ForeignKey(
        settings.AUTH_USER_MODEL, on_delete=models.PROTECT, related_name="+"
    )
    created_at = models.DateTimeField(auto_now_add=True)
    members = models.ManyToManyField(
        settings.AUTH_USER_MODEL, through="TeamMembership", related_name="teams"
    )

    class Meta:
        ordering = ["name"]
        constraints = [
            models.UniqueConstraint(fields=["org", "name"], name="team_org_name"),
        ]

    def __str__(self):
        return f"{self.name} ({self.org.name})"


class TeamMembership(models.Model):
    team = models.ForeignKey(Team, on_delete=models.CASCADE, related_name="memberships")
    user = models.ForeignKey(
        settings.AUTH_USER_MODEL, on_delete=models.CASCADE, related_name="team_memberships"
    )
    joined_at = models.DateTimeField(auto_now_add=True)
    # 팀장은 승인 없이 팀원에게 태스크를 맡길 수 있다. 팀장이 없는 팀도 있다.
    is_lead = models.BooleanField("팀장", default=False)

    class Meta:
        constraints = [
            models.UniqueConstraint(fields=["team", "user"], name="teammembership_team_user"),
        ]


class Invite(models.Model):
    """조직 초대 링크. 팀 배정은 하지 않는다(가입 후 팀 화면에서 넣는다)."""

    org = models.ForeignKey(Organization, on_delete=models.CASCADE, related_name="invites")
    token = models.CharField(max_length=64, unique=True, default=_token)
    created_by = models.ForeignKey(
        settings.AUTH_USER_MODEL, on_delete=models.PROTECT, related_name="+"
    )
    created_at = models.DateTimeField(auto_now_add=True)
    expires_at = models.DateTimeField(default=_default_expiry)
    revoked_at = models.DateTimeField(null=True, blank=True)
    use_count = models.PositiveIntegerField(default=0)
    max_uses = models.PositiveIntegerField("최대 사용 횟수", default=0)  # 0=무제한

    class Meta:
        ordering = ["-created_at"]

    @property
    def is_usable(self) -> bool:
        return self.revoked_at is None and self.expires_at > timezone.now()

    @property
    def path(self) -> str:
        return f"/join/{self.token}"


class ChangeRequest(models.Model):
    """AI가 올린 조직 설정·거버넌스 변경 요청. 관리자가 웹에서 허용해야 반영된다.

    AI는 자기 정책(ai.*)과 자기가 따르는 규칙(거버넌스)을 직접 못 바꾼다. 대신 바꿀 내용을 올리고
    사람이 링크를 열어 전후를 보고 허용한다. 허용은 로그인 세션에서만 된다(토큰으로는 못 한다).
    """

    KINDS = [("settings", "조직 설정"), ("governance", "개발 거버넌스")]
    STATUSES = [("pending", "대기"), ("approved", "허용"), ("rejected", "거절"), ("stale", "무효")]

    org = models.ForeignKey(Organization, on_delete=models.CASCADE, related_name="change_requests")
    kind = models.CharField(max_length=10, choices=KINDS)
    # 요청 시점의 값. 허용할 때 지금 값과 다르면(그사이 누가 바꿨으면) 반영하지 않고 무효로 만든다.
    base = models.JSONField()
    proposed = models.JSONField()
    # AI가 왜 바꾸려는지. 사람이 허용할지 판단하는 근거라 요청에 반드시 받는다.
    reason = models.CharField("변경 이유", max_length=500)
    # 거버넌스 변경은 이력(ChangeLog)이 없어 이 행이 유일한 기록이다. 계정을 지워도 남긴다.
    requested_by = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.PROTECT, related_name="+")
    token = models.ForeignKey(
        "accounts.ApiToken", on_delete=models.SET_NULL, null=True, blank=True, related_name="+"
    )
    status = models.CharField(max_length=10, choices=STATUSES, default="pending")
    reviewed_by = models.ForeignKey(
        settings.AUTH_USER_MODEL, on_delete=models.SET_NULL, null=True, blank=True, related_name="+"
    )
    reviewed_at = models.DateTimeField(null=True, blank=True)
    reject_reason = models.CharField("거절 사유", max_length=300, blank=True)
    created_at = models.DateTimeField(auto_now_add=True)
    expires_at = models.DateTimeField(default=_default_expiry)

    class Meta:
        ordering = ["-created_at"]

    def __str__(self):
        return f"{self.org.name} {self.get_kind_display()} #{self.pk} ({self.status})"

    @property
    def is_open(self) -> bool:
        return self.status == "pending" and self.expires_at > timezone.now()

    @property
    def path(self) -> str:
        return f"/orgs/{self.org_id}/requests/{self.pk}"


class DiscordChannelAlert(models.Model):
    """채널을 볼 수 있는 권한 밖 인원. 허용하면 allowed로 남아 허용 목록 역할도 한다.

    status: open(경고 중) | allowed(명시적 허용) | gone(경고 중에 사라짐)
            | missing(허용 집합인데 채널을 못 보는 사람 — 자동 관리가 꺼진 채널의 안내용, 알림 없음)
    """

    STATUSES = [("open", "경고"), ("allowed", "허용"), ("gone", "사라짐"), ("missing", "접근 없음")]

    org = models.ForeignKey(Organization, on_delete=models.CASCADE, related_name="+")
    channel_id = models.CharField(max_length=32)
    discord_user_id = models.CharField(max_length=32)
    display_name = models.CharField(max_length=100, blank=True)
    status = models.CharField(max_length=7, choices=STATUSES, default="open")
    first_seen = models.DateTimeField(auto_now_add=True)
    resolved_by = models.ForeignKey(
        settings.AUTH_USER_MODEL, null=True, blank=True, on_delete=models.SET_NULL, related_name="+"
    )
    resolved_at = models.DateTimeField(null=True, blank=True)

    class Meta:
        constraints = [
            models.UniqueConstraint(
                fields=["channel_id", "discord_user_id"], name="dcalert_channel_user"
            ),
        ]


class DiscordMemberPermission(models.Model):
    """봇이 보고한 PM 사용자의 Discord 서버 권한 비트(`member.guild_permissions.value`).

    core는 Discord를 부르지 않으므로 웹의 Discord 관리 동작은 이 보고값으로 사용자의 서버 권한을 판정한다.
    보고가 15분보다 오래됐으면 쓰지 않는다.
    """

    org = models.ForeignKey(Organization, on_delete=models.CASCADE, related_name="+")
    user = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.CASCADE, related_name="+")
    permissions = models.BigIntegerField()
    reported_at = models.DateTimeField()

    class Meta:
        constraints = [
            models.UniqueConstraint(fields=["org", "user"], name="dcmemberperm_org_user"),
        ]
