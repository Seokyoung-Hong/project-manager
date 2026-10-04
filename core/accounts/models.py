import base64
import hashlib
import secrets
from datetime import timedelta

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
    # AI가 쓰는 토큰인가. 조직의 AI 정책(ai.*)은 이 표시로 걸린다 — 호출자가 붙이는 X-Source 헤더는
    # 더 엄격하게만 만들 수 있다. 발급 뒤에는 바꾸지 않는다(바꾸려면 새로 발급).
    for_ai = models.BooleanField("AI용", default=True)
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
    def issue(cls, user, name: str, scope: str = "read", expires_at=None, for_ai: bool = True):
        """토큰을 만들고 (객체, 원문)을 돌려준다. 원문은 이때 한 번만 볼 수 있다.

        기본은 AI용이다. 사람용은 웹 발급 화면에서 사람이 고를 때만 만든다. 봇 토큰은 사람 명령을 옮기므로 AI가 아니다.
        """
        raw = "pm_" + secrets.token_urlsafe(32)
        token = cls.objects.create(
            user=user,
            name=name[:50],
            prefix=raw[:12],
            key_hash=cls._hash(raw),
            scope=scope,
            expires_at=expires_at,
            for_ai=for_ai and scope != "bot",
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


class OAuthClient(models.Model):
    """MCP 커넥터가 RFC 7591로 스스로 등록한 클라이언트.

    사전 등록이 불가능한 것이 MCP의 전제다 — 사람이 Claude 앱에 주소만 넣으면 앱이 알아서
    등록하고 인가를 시작한다. 그래서 비밀이 없는 공개 클라이언트만 받고, 코드는 PKCE(S256)가
    지킨다.
    """

    client_id = models.CharField(max_length=64, unique=True)
    name = models.CharField(max_length=100, blank=True)
    redirect_uris = models.JSONField(default=list)
    created_at = models.DateTimeField(auto_now_add=True)

    def __str__(self):
        return self.name or self.client_id

    @classmethod
    def register(cls, name: str, redirect_uris: list[str]):
        return cls.objects.create(
            client_id=secrets.token_urlsafe(32),
            name=(name or "")[:100],
            redirect_uris=redirect_uris,
        )


class OAuthCode(models.Model):
    """인가 코드. 1회용, 10분.

    교환하면 나오는 것은 평범한 ApiToken이다 — 새 토큰 종류를 만들지 않는다. 그래야 발급된
    커넥터가 /settings/tokens 목록에 그대로 보이고, 폐기도 늘 쓰던 그 버튼으로 끝난다.
    """

    TTL = timedelta(minutes=10)

    code_hash = models.CharField(max_length=64, unique=True)
    client = models.ForeignKey(OAuthClient, on_delete=models.CASCADE, related_name="codes")
    user = models.ForeignKey(User, on_delete=models.CASCADE, related_name="oauth_codes")
    redirect_uri = models.CharField(max_length=500)
    code_challenge = models.CharField(max_length=128)
    scope = models.CharField(max_length=5, choices=ApiToken.SCOPES, default="read")
    created_at = models.DateTimeField(auto_now_add=True)
    used_at = models.DateTimeField(null=True, blank=True)

    @classmethod
    def issue(cls, **fields):
        """코드를 만들고 (객체, 원문)을 돌려준다. 원문은 리다이렉트로만 나간다."""
        raw = secrets.token_urlsafe(32)
        return cls.objects.create(code_hash=ApiToken._hash(raw), **fields), raw

    @classmethod
    def claim(cls, raw: str, client_id: str, redirect_uri: str, verifier: str):
        """전부 맞으면 코드를 소진하고 돌려준다. 하나라도 어긋나면 None."""
        if not raw:
            return None
        code = (
            cls.objects.select_related("client", "user")
            .filter(code_hash=ApiToken._hash(raw))
            .first()
        )
        if code is None or code.created_at + cls.TTL <= timezone.now():
            return None
        if code.client.client_id != client_id or code.redirect_uri != redirect_uri:
            return None
        if not secrets.compare_digest(pkce_challenge(verifier), code.code_challenge):
            return None
        # 소진은 DB에서 한 번에 한다. 읽고 나서 저장하면 동시에 두 번 온 교환이 둘 다 통과한다.
        if cls.objects.filter(pk=code.pk, used_at__isnull=True).update(used_at=timezone.now()) != 1:
            return None
        return code


def pkce_challenge(verifier: str) -> str:
    """RFC 7636 S256. verifier가 비어 있어도 절대 맞지 않는 값을 돌려준다."""
    digest = hashlib.sha256((verifier or "").encode()).digest()
    return base64.urlsafe_b64encode(digest).rstrip(b"=").decode()


class LoginLock(models.Model):
    """로그인·가입 시도 카운터와 잠금. 규칙은 accounts/auth.py(LOCK_POLICY).

    캐시가 아니라 표인 이유: 캐시 백엔드가 LocMem이라 gunicorn 워커마다 따로 센다.
    표는 워커 공통이고 재시작에 살아남으며 /ops에서 보고 풀 수 있다.
    """

    kind = models.CharField(max_length=10)
    key = models.CharField(max_length=150)
    failures = models.PositiveSmallIntegerField(default=0)
    window_started_at = models.DateTimeField()
    locked_until = models.DateTimeField(null=True, blank=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        constraints = [models.UniqueConstraint(fields=["kind", "key"], name="loginlock_kind_key")]

    def __str__(self):
        return f"{self.kind}:{self.key}"
