import secrets
from datetime import timedelta

from django.conf import settings as conf  # 모델의 settings 필드와 이름이 겹친다
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
    # 조직 설정. 키·형·기본값은 orgs/settings.py 레지스트리가 정한다. 키가 없으면 기본값이다.
    settings = models.JSONField("설정", default=dict, blank=True)
    created_by = models.ForeignKey(conf.AUTH_USER_MODEL, on_delete=models.PROTECT, related_name="+")
    created_at = models.DateTimeField(auto_now_add=True)
    members = models.ManyToManyField(
        conf.AUTH_USER_MODEL, through="OrgMembership", related_name="orgs"
    )

    class Meta:
        ordering = ["name"]

    def __str__(self):
        return self.name


class OrgMembership(models.Model):
    ROLES = [("admin", "관리자"), ("member", "멤버")]

    org = models.ForeignKey(Organization, on_delete=models.CASCADE, related_name="memberships")
    user = models.ForeignKey(
        conf.AUTH_USER_MODEL, on_delete=models.CASCADE, related_name="org_memberships"
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
    created_by = models.ForeignKey(conf.AUTH_USER_MODEL, on_delete=models.PROTECT, related_name="+")
    created_at = models.DateTimeField(auto_now_add=True)
    members = models.ManyToManyField(
        conf.AUTH_USER_MODEL, through="TeamMembership", related_name="teams"
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
        conf.AUTH_USER_MODEL, on_delete=models.CASCADE, related_name="team_memberships"
    )
    joined_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        constraints = [
            models.UniqueConstraint(fields=["team", "user"], name="teammembership_team_user"),
        ]


class Invite(models.Model):
    """조직 초대 링크. 팀 배정은 하지 않는다(가입 후 팀 화면에서 넣는다)."""

    org = models.ForeignKey(Organization, on_delete=models.CASCADE, related_name="invites")
    token = models.CharField(max_length=64, unique=True, default=_token)
    created_by = models.ForeignKey(conf.AUTH_USER_MODEL, on_delete=models.PROTECT, related_name="+")
    created_at = models.DateTimeField(auto_now_add=True)
    expires_at = models.DateTimeField(default=_default_expiry)
    revoked_at = models.DateTimeField(null=True, blank=True)
    use_count = models.PositiveIntegerField(default=0)
    max_uses = models.PositiveIntegerField("최대 사용 횟수", default=0)  # 0=무제한

    class Meta:
        ordering = ["-created_at"]

    @property
    def is_usable(self) -> bool:
        if self.max_uses and self.use_count >= self.max_uses:
            return False
        return self.revoked_at is None and self.expires_at > timezone.now()

    @property
    def path(self) -> str:
        return f"/join/{self.token}"
