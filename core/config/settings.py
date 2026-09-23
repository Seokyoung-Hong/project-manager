import os
import sys
from pathlib import Path

import dj_database_url

BASE_DIR = Path(__file__).resolve().parent.parent

SECRET_KEY = os.environ.get("SECRET_KEY", "dev-only-insecure-key")
DEBUG = os.environ.get("DEBUG", "1") == "1"
ALLOWED_HOSTS = [h for h in os.environ.get("ALLOWED_HOSTS", "localhost,127.0.0.1").split(",") if h]
CSRF_TRUSTED_ORIGINS = [o for o in os.environ.get("CSRF_TRUSTED_ORIGINS", "").split(",") if o]
SITE_URL = os.environ.get("SITE_URL", "http://localhost:8000").rstrip("/")
# MCP 서버의 공개 주소. /settings/tokens의 연결 예시가 이 값으로 그려진다 — 사람이
# <MCP_URL>을 손으로 바꿔 넣게 두면 절반이 틀린 주소로 붙는다.
# 운영은 core와 같은 도메인을 쓰고 앞단이 경로로 나눈다(mcp_server/README.md). 도메인을
# 따로 둔다면 그 주소를 넣는다.
MCP_URL = os.environ.get("MCP_URL", SITE_URL).rstrip("/")
# WebMCP는 크롬 149·엣지 150에서 아직 오리진 트라이얼이라 도메인마다 토큰을 받아야 켜진다.
# 토큰이 있으면 <meta http-equiv="origin-trial">로 실어 보낸다. 없으면 기능만 조용히 빠진다.
WEBMCP_ORIGIN_TRIAL = os.environ.get("WEBMCP_ORIGIN_TRIAL", "")

INSTALLED_APPS = [
    "django.contrib.admin",
    "django.contrib.auth",
    "django.contrib.contenttypes",
    "django.contrib.sessions",
    "django.contrib.messages",
    "django.contrib.staticfiles",
    "accounts",
    "orgs",
    "projects",
    "tasks",
    "portfolio",
    "notes",
    "github",
    "reports",
    "api",
    "web",
]

MIDDLEWARE = [
    "django.middleware.security.SecurityMiddleware",
    "common.middleware.origin_agent_cluster",
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
                "web.context.shell",
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

# ---- 리버스 프록시 뒤에서 ----
# 앞단(NginxProxyManager·Cloudflare Tunnel)이 TLS를 끝내고 평문 HTTP로 넘긴다. 이 헤더가
# 없으면 request.is_secure()가 False라서 https 링크가 http로 나가고 CSRF가 오리진 비교에서
# 막힌다. 프록시가 이 헤더를 **덮어써야** 한다(클라이언트가 보낸 값을 그대로 통과시키면 안 된다).
SECURE_PROXY_SSL_HEADER = ("HTTP_X_FORWARDED_PROTO", "https")

# USE_X_FORWARDED_HOST는 켜지 않는다. NginxProxyManager는 Host를 원래 도메인 그대로 넘기고
# X-Forwarded-Host를 세우지 않는다. 켜 두면 클라이언트가 그 헤더를 지어내 ALLOWED_HOSTS
# 검사를 우회할 수 있다.

# SECURE_SSL_REDIRECT도 켜지 않는다. mcp·discord 컨테이너가 http://web:8000 으로 직접
# 부르는데 그 요청까지 https로 돌려보내면 연동이 통째로 끊긴다. 평문 접속 차단은 앞단의
# Force SSL과 방화벽이 맡는다.

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

# ---- GitHub App ----
# 등록 절차는 docs/GITHUB-APP-SETUP.md. 여기 있는 값은 전부 비밀이라 로그에 찍지 않는다
# (common/logging.py의 SecretFilter가 키 이름과 토큰 접두어를 가린다).
GITHUB_APP_ID = os.environ.get("GITHUB_APP_ID", "")
GITHUB_APP_SLUG = os.environ.get("GITHUB_APP_SLUG", "")
GITHUB_CLIENT_ID = os.environ.get("GITHUB_CLIENT_ID", "")
GITHUB_CLIENT_SECRET = os.environ.get("GITHUB_CLIENT_SECRET", "")
GITHUB_WEBHOOK_SECRET = os.environ.get("GITHUB_WEBHOOK_SECRET", "")
# .env에는 한 줄로 들어 있다. 줄바꿈 자리의 \n 을 되돌린다.
GITHUB_APP_PRIVATE_KEY = os.environ.get("GITHUB_APP_PRIVATE_KEY", "").replace("\\n", "\n")
# Discord 앱의 Client ID(= Application ID). 비밀이 아니다 — 조직이 봇을 자기 서버에 설치하는
# 링크를 만들 때만 쓴다. 봇 토큰은 여기 없다(.env.discord에만 있다, GUIDE-00 §3).
DISCORD_CLIENT_ID = os.environ.get("DISCORD_CLIENT_ID", "")
# 사용자 GitHub 토큰을 Fernet으로 암호화하는 키. 갈면 저장된 토큰을 전부 못 읽는다.
CREDENTIAL_KEY = os.environ.get("CREDENTIAL_KEY", "")
# 설정이 없으면 GitHub 화면과 버튼을 아예 그리지 않는다(개발·테스트 환경).
GITHUB_ENABLED = bool(GITHUB_APP_ID and GITHUB_APP_PRIVATE_KEY and CREDENTIAL_KEY)

# 테스트에서만 해시를 약한 것으로 바꾼다. 픽스처가 테스트마다 계정을 만드는데 PBKDF2는
# 한 번에 수백 ms가 든다 — 스위트 시간의 대부분이 거기였다. 운영 경로는 그대로다.
if "pytest" in sys.modules:
    PASSWORD_HASHERS = ["django.contrib.auth.hashers.MD5PasswordHasher"]
