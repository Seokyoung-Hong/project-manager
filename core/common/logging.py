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
    # 운영자가 발급한 비밀번호 재설정 링크(/reset/<uid>/<token>). 토큰은 24시간 자격증명이다.
    re.compile(r"/reset/[A-Za-z0-9_\-]+/[0-9a-z]+-[0-9a-f]{20,}"),
    # Discord 웹훅 URL은 경로에 토큰을 품는다(GitHub 알림 웹훅, github/hooks.py).
    re.compile(r"/webhooks/\d+/[A-Za-z0-9_\-]{20,}"),
    # GitHub 토큰. 설치(ghs_)·사용자(ghu_)·refresh(ghr_)는 접두어로 구분된다.
    re.compile(r"gh[sur]_[A-Za-z0-9]{20,}"),
    re.compile(
        r"(?i)(GITHUB_APP_PRIVATE_KEY|GITHUB_CLIENT_SECRET|GITHUB_WEBHOOK_SECRET|CREDENTIAL_KEY)=\S+"
    ),
    re.compile(r"-----BEGIN [A-Z ]*PRIVATE KEY-----.*?-----END [A-Z ]*PRIVATE KEY-----", re.S),
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
