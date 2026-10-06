# 구현 지시서 01-1: core — 환경, 골격, 데이터 모델


> **이 문서는 2026-09-10에 끝난 최초 구축의 기록이다.** 지금 할 일은 [GUIDE-V2-00-overview.md](GUIDE-V2-00-overview.md)부터 시작하는 묶음이다. 이 문서에 나오는 `Team`·`teams`·"팀"은 2026-09-11 개명 전 용어로 **조직**을 뜻한다. 대조표는 [GUIDE-V2-01](GUIDE-V2-01-org-teams.md) §1에 있다.

GUIDE-00을 먼저 읽는다. 이 문서는 Step 0 ~ Step 2를 다룬다.
이어지는 문서: 01-2(서비스 계층), 01-3(API), 01-4(웹 화면), 01-5(테스트·완료 체크).

개정 2026-09-10: 목업 정합([IMPL-PLAN.md](IMPL-PLAN.md) §3). 태스크 상태 7개, 중요도 1~10, 프로젝트 상태 8개·관리자 여러 명, 댓글 삭제 → 진행 메모, 오늘 목록 자동 담기.

개정 2026-09-10 (Discord 봇): `User`에 연결 필드 3개, `ApiToken.SCOPES`에 `bot`, `ChangeLog.SOURCES`에 `dc`, `DiscordWebhook` 모델 삭제, `SecretFilter` 패턴 교체, accounts admin readonly.

---

## Step 0. 저장소와 환경

1. 저장소 루트 `project-manager/`에서:

```bash
git init
```

2. GUIDE-00 6절의 `.gitignore`를 루트에 만든다.

3. `core/` 디렉터리를 만들고 그 안에서:

```bash
uv init --no-workspace --name udally-core --python 3.12
uv add "django>=5.2,<6" "django-ninja>=1.3" "psycopg[binary]>=3.2" "dj-database-url>=2.3" "gunicorn>=23" "whitenoise>=6.7"
uv add --dev "pytest>=8" "pytest-django>=4.9" "ruff>=0.6"
```

`uv init`이 만든 `main.py` 또는 `hello.py`가 있으면 지운다.

4. `core/pyproject.toml`에 다음 블록을 추가한다 (기존 `[project]`는 유지):

```toml
[tool.pytest.ini_options]
DJANGO_SETTINGS_MODULE = "config.settings"
python_files = ["tests.py", "test_*.py"]

[tool.ruff]
line-length = 100
target-version = "py312"

[tool.ruff.lint]
select = ["E", "F", "I", "UP", "B"]
ignore = ["E501"]
```

5. Django 프로젝트 골격 생성 (`core/` 안에서):

```bash
uv run django-admin startproject config .
uv run python manage.py startapp accounts
uv run python manage.py startapp teams
uv run python manage.py startapp projects
uv run python manage.py startapp tasks
uv run python manage.py startapp reports
uv run python manage.py startapp api
uv run python manage.py startapp web
mkdir common
```

`common/`은 Django 앱이 아니다. `common/__init__.py`(빈 파일)만 만든다.

각 앱의 자동 생성 파일 중 `views.py`, `tests.py`는 지시서에서 쓰라고 할 때까지 비워 둔다(파일은 남겨도 됨). `models.py`가 없는 앱(`reports`, `web`)은 그대로 둔다.

**검증:** `uv run python -c "import django; print(django.get_version())"` → `5.2.x`.

---

## Step 1. 설정과 URL 골격

### 1.1 `core/config/settings.py` 전체를 다음으로 교체

```python
import os
from pathlib import Path

import dj_database_url

BASE_DIR = Path(__file__).resolve().parent.parent

SECRET_KEY = os.environ.get("SECRET_KEY", "dev-only-insecure-key")
DEBUG = os.environ.get("DEBUG", "1") == "1"
ALLOWED_HOSTS = [h for h in os.environ.get("ALLOWED_HOSTS", "localhost,127.0.0.1").split(",") if h]
CSRF_TRUSTED_ORIGINS = [o for o in os.environ.get("CSRF_TRUSTED_ORIGINS", "").split(",") if o]
SITE_URL = os.environ.get("SITE_URL", "http://localhost:8000").rstrip("/")

INSTALLED_APPS = [
    "django.contrib.admin",
    "django.contrib.auth",
    "django.contrib.contenttypes",
    "django.contrib.sessions",
    "django.contrib.messages",
    "django.contrib.staticfiles",
    "accounts",
    "teams",
    "projects",
    "tasks",
    "reports",
    "api",
    "web",
]

MIDDLEWARE = [
    "django.middleware.security.SecurityMiddleware",
    "whitenoise.middleware.WhiteNoiseMiddleware",
    "django.contrib.sessions.middleware.SessionMiddleware",
    "django.middleware.common.CommonMiddleware",
    "django.middleware.csrf.CsrfViewMiddleware",
    "django.contrib.auth.middleware.AuthenticationMiddleware",
    "django.contrib.messages.middleware.MessageMiddleware",
    "django.middleware.clickjacking.XFrameOptionsMiddleware",
]

ROOT_URLCONF = "config.urls"

TEMPLATES = [
    {
        "BACKEND": "django.template.backends.django.DjangoTemplates",
        "DIRS": [BASE_DIR / "web" / "templates"],
        "APP_DIRS": True,
        "OPTIONS": {
            "context_processors": [
                "django.template.context_processors.request",
                "django.contrib.auth.context_processors.auth",
                "django.contrib.messages.context_processors.messages",
            ],
        },
    },
]

WSGI_APPLICATION = "config.wsgi.application"

DATABASES = {
    "default": dj_database_url.config(
        default=f"sqlite:///{BASE_DIR / 'db.sqlite3'}",
        conn_max_age=60,
    )
}

AUTH_USER_MODEL = "accounts.User"

AUTH_PASSWORD_VALIDATORS = [
    {
        "NAME": "django.contrib.auth.password_validation.MinimumLengthValidator",
        "OPTIONS": {"min_length": 8},
    },
]

LANGUAGE_CODE = "ko"
TIME_ZONE = "Asia/Seoul"
USE_I18N = True
USE_TZ = True

STATIC_URL = "/static/"
STATIC_ROOT = BASE_DIR / "staticfiles"
STATICFILES_DIRS = [BASE_DIR / "web" / "static"]
STORAGES = {
    "default": {"BACKEND": "django.core.files.storage.FileSystemStorage"},
    "staticfiles": {"BACKEND": "whitenoise.storage.CompressedStaticFilesStorage"},
}

DEFAULT_AUTO_FIELD = "django.db.models.BigAutoField"

LOGIN_URL = "/login"
LOGIN_REDIRECT_URL = "/today"
LOGOUT_REDIRECT_URL = "/login"

SECURE_PROXY_SSL_HEADER = ("HTTP_X_FORWARDED_PROTO", "https")
if not DEBUG:
    SESSION_COOKIE_SECURE = True
    CSRF_COOKIE_SECURE = True

LOGGING = {
    "version": 1,
    "disable_existing_loggers": False,
    "filters": {"secrets": {"()": "common.logging.SecretFilter"}},
    "handlers": {
        "console": {
            "class": "logging.StreamHandler",
            "filters": ["secrets"],
        }
    },
    "root": {"handlers": ["console"], "level": "INFO"},
}
```

(Step 6에서 `context_processors`에 `"web.context.shell"` 한 줄을 추가한다. 지금은 넣지 않는다.)

### 1.2 `core/common/logging.py`

```python
import logging
import re

_PATTERNS = [
    re.compile(r"pm_[A-Za-z0-9_\-]{20,}"),
    re.compile(r"(?i)bearer\s+\S+"),
    # Discord 봇 토큰은 `Authorization: Bot <token>`으로 실린다. bearer 패턴이 못 잡는다.
    re.compile(r"(?i)\bbot\s+[A-Za-z0-9_\-.]{20,}"),
    re.compile(r"[A-Za-z0-9_\-]{24,}\.[A-Za-z0-9_\-]{6,}\.[A-Za-z0-9_\-]{27,}"),
    re.compile(r"(?i)DISCORD_BOT_TOKEN=\S+"),
    re.compile(r"/u/[A-Za-z0-9_\-]{20,}/"),
]


class SecretFilter(logging.Filter):
    """로그 메시지에서 API 토큰과 Discord 봇 토큰을 가린다."""

    def filter(self, record: logging.LogRecord) -> bool:
        msg = record.getMessage()
        for p in _PATTERNS:
            msg = p.sub("[redacted]", msg)
        record.msg = msg
        record.args = ()
        return True
```

### 1.3 `core/common/errors.py`

```python
class ServiceError(Exception):
    """검증 실패. errors는 {필드명: 메시지}."""

    def __init__(self, errors: dict[str, str]):
        self.errors = errors
        super().__init__(str(errors))


class ConflictError(Exception):
    """낙관적 잠금 충돌. latest는 DB의 최신 객체."""

    def __init__(self, latest):
        self.latest = latest
        super().__init__("conflict")
```

### 1.4 `core/common/dates.py`

```python
from datetime import date, datetime, timedelta
from zoneinfo import ZoneInfo

from django.utils import timezone

KST = ZoneInfo("Asia/Seoul")


def now_kst():
    return timezone.now().astimezone(KST)


def today_kst() -> date:
    return now_kst().date()


def week_bounds(d: date | None = None) -> tuple[date, date]:
    """(이번 주 월요일, 이번 주 일요일)"""
    d = d or today_kst()
    monday = d - timedelta(days=d.weekday())
    return monday, monday + timedelta(days=6)


def last_week_start(d: date | None = None) -> date:
    """직전 주 월요일"""
    monday, _ = week_bounds(d)
    return monday - timedelta(days=7)


def kst_day_range(day: date):
    """day 00:00 KST 부터 다음날 00:00 KST 까지의 aware datetime 쌍"""
    start = datetime.combine(day, datetime.min.time(), tzinfo=KST)
    return start, start + timedelta(days=1)


def kst_week_range(week_start: date):
    """week_start 00:00 KST 부터 7일 뒤 00:00 KST 까지"""
    start = datetime.combine(week_start, datetime.min.time(), tzinfo=KST)
    return start, start + timedelta(days=7)


def fmt_md(d: date | None) -> str:
    """'9월 9일'. None이면 빈 문자열."""
    return f"{d.month}월 {d.day}일" if d else ""
```

### 1.5 `core/config/urls.py`

```python
from django.contrib import admin
from django.urls import include, path

from api.api import api

urlpatterns = [
    path("admin/", admin.site.urls),
    path("api/", api.urls),
    path("", include("web.urls")),
]
```

`api/api.py`와 `web/urls.py`는 뒤 Step에서 만든다. Step 1 검증 전까지는 임시로 다음 두 파일을 만든다.

`core/api/api.py` (임시):

```python
from ninja import NinjaAPI

api = NinjaAPI(title="Udally API", version="1")
```

`core/web/urls.py` (임시):

```python
urlpatterns = []
```

### 1.6 `core/accounts/models.py` (Step 2보다 먼저 필요: AUTH_USER_MODEL)

```python
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

    def save(self, *args, **kwargs):
        if not self.discord_user_id:
            self.discord_user_id = None
        if not self.display_name:
            # username은 150자, display_name은 50자다. 자르지 않으면 Postgres에서 DataError.
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
```

Discord 연결 필드 3개는 새 모델 없이 연결을 증명하기 위한 최소 구성이다.

| 필드 | 채우는 곳 | 비우는 곳 |
|---|---|---|
| `discord_link_code` | 웹 `[Discord 연결]` (`issue_link_code`) | 연결 성공 시 **`None`**으로. `""`로 비우면 두 번째 사용자가 `unique` 제약에 걸린다 |
| `discord_link_expires_at` | 같은 곳. `now + 10분` | 같은 곳 |
| `discord_user_id` | `link_discord`가 게이트웨이의 `author.id`로만 | `unlink_discord` / 다른 사람이 그 snowflake를 증명하면 회수된다 |
| `discord_linked_at` | `link_discord` | 해제 시 `None`. **이 값이 없는 행은 봇 명령의 행위자가 될 수 없다** |

`ApiToken.SCOPES`의 `bot`은 Discord 봇 계정 하나만 쓴다. `scope`는 `max_length=5`라 `"bot"`(3자)이 그대로 들어가므로 컬럼 변경은 없다. 이 범위는 `/api/integrations/discord/` 안에서만 쓸 수 있고(§5의 `BotTokenAuth`), 웹 화면에서는 발급할 수 없다(GUIDE-00 §3).

### 1.7 검증

```bash
uv run python manage.py makemigrations accounts
uv run python manage.py migrate
uv run python manage.py check
```

세 명령 모두 오류 없이 끝난다. `uv run python manage.py runserver`를 띄우고 `http://127.0.0.1:8000/admin/`이 로그인 화면을 보여 주면 통과. (`/`는 아직 404여도 된다.)

커밋: `step 1: django skeleton, settings, accounts.User`

---

## Step 2. 데이터 모델과 admin

### 2.1 `core/teams/models.py`

```python
import secrets
from datetime import timedelta

from django.conf import settings
from django.db import models
from django.utils import timezone


def _token():
    return secrets.token_urlsafe(32)


def _default_expiry():
    return timezone.now() + timedelta(days=7)


class Team(models.Model):
    name = models.CharField("이름", max_length=100)
    purpose = models.CharField("목적", max_length=200, blank=True)
    created_by = models.ForeignKey(
        settings.AUTH_USER_MODEL, on_delete=models.PROTECT, related_name="+"
    )
    created_at = models.DateTimeField(auto_now_add=True)
    members = models.ManyToManyField(
        settings.AUTH_USER_MODEL, through="Membership", related_name="teams"
    )

    class Meta:
        ordering = ["name"]

    def __str__(self):
        return self.name


class Membership(models.Model):
    ROLES = [("admin", "관리자"), ("member", "팀원")]

    team = models.ForeignKey(Team, on_delete=models.CASCADE, related_name="memberships")
    user = models.ForeignKey(
        settings.AUTH_USER_MODEL, on_delete=models.CASCADE, related_name="memberships"
    )
    role = models.CharField(max_length=6, choices=ROLES, default="member")
    joined_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        constraints = [
            models.UniqueConstraint(fields=["team", "user"], name="membership_team_user"),
        ]

    def __str__(self):
        return f"{self.user} @ {self.team} ({self.role})"


class Invite(models.Model):
    team = models.ForeignKey(Team, on_delete=models.CASCADE, related_name="invites")
    token = models.CharField(max_length=64, unique=True, default=_token)
    created_by = models.ForeignKey(
        settings.AUTH_USER_MODEL, on_delete=models.PROTECT, related_name="+"
    )
    created_at = models.DateTimeField(auto_now_add=True)
    expires_at = models.DateTimeField(default=_default_expiry)
    revoked_at = models.DateTimeField(null=True, blank=True)
    use_count = models.PositiveIntegerField(default=0)

    class Meta:
        ordering = ["-created_at"]

    @property
    def is_usable(self) -> bool:
        return self.revoked_at is None and self.expires_at > timezone.now()

    @property
    def path(self) -> str:
        return f"/join/{self.token}"
```

`teams`에는 Discord 관련 모델이 없다. 팀의 알림 채널은 `DISCORD_CHANNEL_ID` 환경 변수 하나이고(배포당 값 하나, 비밀도 아니다), 개인 알림 대상은 `User.discord_user_id`다. 발송은 `discord_service`가 봇 토큰으로 하므로 core는 Discord로 나가는 요청을 하지 않는다 — 그래서 URL 검증(SSRF 방지)·마스킹·전용 조회 API가 전부 필요 없다. 팀이 둘 이상이 되면 모델이 아니라 `Team.discord_channel_id` 컬럼 하나를 붙인다.

`import re`는 이 파일에서 쓰지 않는다(웹훅 형식 검사와 함께 사라졌다).

### 2.2 `core/projects/models.py`

```python
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
        "active": "개발 또는 구현 진행 중",
        "paused": "외부 사유나 리소스 부족으로 잠시 멈춤",
        "done": "유지보수 외 별도 작업 없음",
        "stopped": "모든 작업이 완료되어 현재 상태로 종료 가능하지만, 다른 프로젝트와의 연계 가능성이 높아 추후 재개될 여지가 많은 상태",
        "eol": "프로젝트가 더 이상 필요하지 않거나 대체되어, 유지보수·재개 가능성 모두 없는 상태",
    }

    team = models.ForeignKey("teams.Team", on_delete=models.CASCADE, related_name="projects")
    name = models.CharField("이름", max_length=100)
    purpose = models.CharField("목적", max_length=200, blank=True)
    owners = models.ManyToManyField(
        settings.AUTH_USER_MODEL, blank=True, related_name="owned_projects", verbose_name="관리자"
    )
    status = models.CharField("상태", max_length=10, choices=STATUSES, default="preparing")
    is_archived = models.BooleanField(default=False)
    archived_at = models.DateTimeField(null=True, blank=True)
    version = models.PositiveIntegerField(default=1)
    created_by = models.ForeignKey(
        settings.AUTH_USER_MODEL, on_delete=models.PROTECT, related_name="+"
    )
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        ordering = ["name"]
        constraints = [
            models.UniqueConstraint(fields=["team", "name"], name="project_team_name"),
        ]

    def __str__(self):
        return self.name

    @property
    def status_label(self) -> str:
        return dict(self.STATUSES)[self.status]

    @property
    def status_desc(self) -> str:
        return self.STATUS_DESC[self.status]
```

목표일(`target_date`)과 저장소(`repo_url`) 필드는 없다. 저장소·설계 문서는 `Link(project=...)`로 단다.

### 2.3 `core/tasks/models.py`

```python
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

    project = models.ForeignKey(
        "projects.Project", on_delete=models.PROTECT, related_name="tasks"
    )
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
    KINDS = [("doc", "문서"), ("pr", "PR"), ("repo", "저장소"), ("other", "기타")]

    project = models.ForeignKey(
        "projects.Project", on_delete=models.CASCADE, null=True, blank=True, related_name="links"
    )
    task = models.ForeignKey(Task, on_delete=models.CASCADE, null=True, blank=True, related_name="links")
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
    TARGETS = [("task", "task"), ("project", "project")]
    # source는 max_length=4다. "discord"는 안 들어가므로 코드는 "dc", 표시는 "Discord".
    SOURCES = [("web", "웹"), ("api", "API"), ("mcp", "AI"), ("dc", "Discord")]

    target_type = models.CharField(max_length=10, choices=TARGETS)
    target_id = models.PositiveBigIntegerField()
    field = models.CharField(max_length=40)
    old_value = models.TextField(blank=True)
    new_value = models.TextField(blank=True)
    note = models.CharField(max_length=200, blank=True)
    actor = models.ForeignKey(
        settings.AUTH_USER_MODEL, on_delete=models.PROTECT, related_name="+"
    )
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
```

`Comment` 모델은 없다. 진행 메모는 `Task.notes` 하나다.

### 2.4 `core/api/models.py`

```python
from django.db import models


class IntegrationStatus(models.Model):
    name = models.CharField(max_length=20, unique=True)
    last_run_at = models.DateTimeField()
    ok = models.BooleanField()
    detail = models.JSONField(default=dict, blank=True)
    updated_at = models.DateTimeField(auto_now=True)

    def __str__(self):
        return f"{self.name}: {'ok' if self.ok else 'fail'}"
```

### 2.5 admin 등록

`core/accounts/admin.py`:

```python
from django.contrib import admin
from django.contrib.auth.admin import UserAdmin

from .models import ApiToken, User


@admin.register(User)
class CustomUserAdmin(UserAdmin):
    """discord_user_id는 admin에서도 손으로 넣지 못한다.

    증명 없이 심을 수 있으면 코드 교환 연결이 무의미해진다. 연결은 웹의 [Discord 연결] →
    DM `연결 <코드>`로만, 해제는 웹의 [연결 해제]로.
    """

    list_display = ("username", "display_name", "discord_user_id", "is_active", "is_superuser")
    readonly_fields = ("discord_user_id", "discord_linked_at")
    fieldsets = UserAdmin.fieldsets + (
        (
            "프로필",
            {"fields": ("display_name", "auto_pull_days", "discord_user_id", "discord_linked_at")},
        ),
    )


@admin.register(ApiToken)
class ApiTokenAdmin(admin.ModelAdmin):
    list_display = ("prefix", "user", "name", "scope", "created_at", "expires_at", "revoked_at")
    readonly_fields = ("prefix", "key_hash", "created_at", "last_used_at")
```

`core/teams/admin.py`:

```python
from django.contrib import admin

from .models import Invite, Membership, Team


class MembershipInline(admin.TabularInline):
    model = Membership
    extra = 0


@admin.register(Team)
class TeamAdmin(admin.ModelAdmin):
    list_display = ("name", "created_by", "created_at")
    inlines = [MembershipInline]


@admin.register(Invite)
class InviteAdmin(admin.ModelAdmin):
    list_display = ("team", "created_by", "expires_at", "revoked_at", "use_count")
    readonly_fields = ("token",)
```

`core/projects/admin.py`:

```python
from django.contrib import admin

from .models import Project


from tasks.admin import ReadOnlyAdmin


@admin.register(Project)
class ProjectAdmin(ReadOnlyAdmin):
    """조회 전용. 이유는 tasks.admin.ReadOnlyAdmin 참고."""

    list_display = ("name", "team", "status", "is_archived")
    list_filter = ("team", "status", "is_archived")
    filter_horizontal = ("owners",)
```

`core/tasks/admin.py`:

```python
from django.contrib import admin

from .models import ChangeLog, Link, Task


class ReadOnlyAdmin(admin.ModelAdmin):
    """조회 전용 admin.

    GUIDE-00 §3: `Task`·`Project`는 `services.py` 밖에서 `save()`·`update()`로 바꾸지 않는다.
    admin 변경 폼은 그 규칙을 어긴다. 통과하는 수정은 ChangeLog도 version도 남기지 않아
    주간 보고(`reports.weekly`가 ChangeLog에서 완료 수를 센다)와 낙관적 잠금을 조용히 망가뜨리고,
    `status=done`처럼 DB 제약이 막는 조합은 500이 된다. 그래서 쓰기를 닫는다.
    """

    def has_add_permission(self, request):
        return False

    def has_change_permission(self, request, obj=None):
        return False

    def has_delete_permission(self, request, obj=None):
        return False


@admin.register(Task)
class TaskAdmin(ReadOnlyAdmin):
    list_display = ("id", "title", "project", "assignee", "status", "priority", "due_date")
    list_filter = ("status", "project__team")
    search_fields = ("title",)


@admin.register(ChangeLog)
class ChangeLogAdmin(admin.ModelAdmin):
    list_display = ("created_at", "target_type", "target_id", "field", "old_value", "new_value", "actor", "source")
    list_filter = ("target_type", "source")

    def has_add_permission(self, request):
        return False

    def has_change_permission(self, request, obj=None):
        return False

    def has_delete_permission(self, request, obj=None):
        return False


admin.site.register(Link)
```

`core/api/admin.py`:

```python
from django.contrib import admin

from .models import IntegrationStatus

admin.site.register(IntegrationStatus)
```

### 2.6 검증

```bash
uv run python manage.py makemigrations
uv run python manage.py migrate
uv run python manage.py check
uv run python manage.py createsuperuser --username admin --email admin@example.com
```

- 마이그레이션이 `accounts`, `teams`, `projects`, `tasks`, `api` 다섯 앱에 생기고 오류 없이 적용된다.
- admin은 `Task`·`Project`에 대해 **조회 전용**이다(GUIDE-00 §3). 제약 확인은 shell에서 한다:
  `Task.objects.create(...)`를 `status="doing"`+`due_date=None`, `status="blocked"`+`stop_reason=""`,
  `priority=11`, `status="done"`+`completed_at=None`으로 각각 시도하면 모두 `IntegrityError`가 나야 한다
  (`with transaction.atomic():` 안에서 감싼다).
- admin에 로그인해 팀 하나, 프로젝트 하나가 목록에 보이는지 확인한다(추가·변경 버튼은 없다).

**이미 배포된 DB에 이 개정(웹훅 → 봇)을 얹는 경우**에는 `0001`을 고치지 않고 마이그레이션 세 개를 새로 만든다. 이미 적용된 마이그레이션은 편집하지 않는다.

| 마이그레이션 | 내용 |
|---|---|
| `accounts/0002_discord_link.py` | 연결 필드 3개 `AddField` + `ApiToken.scope` `AlterField`(choices에 `bot`) + `RunPython(clear_unverified_links)` |
| `tasks/0002_alter_changelog_source.py` | `ChangeLog.source` `AlterField`. choices만 바뀌므로 Postgres에 DDL이 없다 |
| `teams/0003_delete_discordwebhook.py` | `DeleteModel("DiscordWebhook")`. **되돌릴 수 없다** — 등록해 둔 주소가 필요하면 먼저 `/ops` 내보내기로 백업한다 |

`clear_unverified_links`는 기존 `discord_user_id`를 **전부 `None`으로 비운다**:

```python
def clear_unverified_links(apps, schema_editor):
    apps.get_model("accounts", "User").objects.exclude(discord_user_id=None).update(
        discord_user_id=None, discord_linked_at=None
    )
```

예전 프로필 화면에서 손으로 입력한 값에는 소유 증명이 없다. 봇이 그 값으로 사람을 찾는 순간 자격증명이 되므로 승격시키지 않는다. `reverse_code`는 `migrations.RunPython.noop`이고, 배포 전에 팀에 공지한다 — **전원이 DM `연결`을 하기 전까지 개인 DM 알림은 0건이다.**

커밋: `step 2: models and admin`

다음: [GUIDE-01-core-2-services.md](GUIDE-01-core-2-services.md)
