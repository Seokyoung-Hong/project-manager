import hashlib
import secrets

from django.contrib.auth.models import AbstractUser
from django.db import models
from django.utils import timezone


class User(AbstractUser):
    AUTO_PULL_CHOICES = [(0, "끄기"), (1, "1일"), (3, "3일"), (5, "5일"), (7, "7일"), (14, "14일")]

    display_name = models.CharField("표시 이름", max_length=50, blank=True)
    # Discord snowflake. 사용자가 직접 입력하지 않는다 — 봇이 게이트웨이에서 읽은 author.id와
    # 웹에서 발급한 1회용 코드를 맞바꿔야 채워진다(GUIDE-00 §3). 봇이 이 값으로 사람을
    # 찾으므로 검증 없이 채워지면 곧 로그인 자격증명이 된다.
    discord_user_id = models.CharField(
        "Discord 사용자 ID", max_length=32, null=True, blank=True, unique=True
    )
    discord_link_code = models.CharField(
        "Discord 연결 코드", max_length=8, null=True, blank=True, unique=True
    )
    discord_link_expires_at = models.DateTimeField(null=True, blank=True)
    discord_linked_at = models.DateTimeField("Discord 연결 시각", null=True, blank=True)
    auto_pull_days = models.PositiveSmallIntegerField(
        "마감 기준 자동 담기(일)", choices=AUTO_PULL_CHOICES, default=5
    )
    # 개인 설정(알림·표시 취향). 규칙은 없다 — orgs/settings.py 의 user.* 키만.
    settings = models.JSONField("설정", default=dict, blank=True)

    def save(self, *args, **kwargs):
        if not self.discord_user_id:
            self.discord_user_id = None
        if not self.display_name:
            # username은 150자까지, display_name은 50자다. 자르지 않으면 Postgres에서 DataError.
            self.display_name = self.username[:50]
        super().save(*args, **kwargs)

    def __str__(self):
        return self.display_name or self.username


class ApiToken(models.Model):
    SCOPES = [("read", "읽기"), ("write", "읽기·쓰기"), ("bot", "Discord 봇")]

    user = models.ForeignKey(User, on_delete=models.CASCADE, related_name="tokens")
    name = models.CharField(max_length=50)
    prefix = models.CharField(max_length=12)
    key_hash = models.CharField(max_length=64, unique=True)
    scope = models.CharField(max_length=5, choices=SCOPES, default="read")
    created_at = models.DateTimeField(auto_now_add=True)
    expires_at = models.DateTimeField(null=True, blank=True)
    revoked_at = models.DateTimeField(null=True, blank=True)
    last_used_at = models.DateTimeField(null=True, blank=True)

    class Meta:
        ordering = ["-created_at"]

    def __str__(self):
        return f"{self.prefix}… ({self.user})"

    @staticmethod
    def _hash(raw: str) -> str:
        return hashlib.sha256(raw.encode()).hexdigest()

    @classmethod
    def issue(cls, user, name: str, scope: str = "read", expires_at=None):
        """토큰을 만들고 (객체, 원문)을 돌려준다. 원문은 이때 한 번만 볼 수 있다."""
        raw = "pm_" + secrets.token_urlsafe(32)
        token = cls.objects.create(
            user=user,
            name=name[:50],
            prefix=raw[:12],
            key_hash=cls._hash(raw),
            scope=scope,
            expires_at=expires_at,
        )
        return token, raw

    @classmethod
    def authenticate(cls, raw: str | None):
        if not raw:
            return None
        token = cls.objects.select_related("user").filter(key_hash=cls._hash(raw)).first()
        if token is None or not token.is_valid:
            return None
        cls.objects.filter(pk=token.pk).update(last_used_at=timezone.now())
        return token

    @property
    def is_valid(self) -> bool:
        if self.revoked_at or not self.user.is_active:
            return False
        if self.expires_at and self.expires_at <= timezone.now():
            return False
        return True

    def revoke(self):
        if not self.revoked_at:
            self.revoked_at = timezone.now()
            self.save(update_fields=["revoked_at"])


class IdempotencyKey(models.Model):
    user = models.ForeignKey(User, on_delete=models.CASCADE)
    key = models.CharField(max_length=100)
    target_type = models.CharField(max_length=20)
    target_id = models.PositiveBigIntegerField()
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        constraints = [
            models.UniqueConstraint(fields=["user", "key"], name="idem_user_key"),
        ]
