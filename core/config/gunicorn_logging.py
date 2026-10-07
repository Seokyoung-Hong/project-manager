"""Gunicorn 로거. 접속·오류 로그에도 SecretFilter를 건다(entrypoint.sh의 --logger-class).

Gunicorn의 gunicorn.access·gunicorn.error 로거는 propagate=False에 자기 핸들러를 따로 달아서
Django LOGGING(root 핸들러의 필터)을 거치지 않는다. 그래서 요청 줄·Referer에 실린
비밀번호 재설정 토큰(/reset/<uid>/<token>) 같은 자격증명이 그대로 찍혔다.
필터를 핸들러가 아니라 로거에 달아, 어떤 핸들러(stdout·파일·syslog·logconfig)로 나가든 먼저 가린다.
"""

from gunicorn.glogging import Logger

from common.logging import SecretFilter


class SecretLogger(Logger):
    def setup(self, cfg):
        super().setup(cfg)
        for log in (self.error_log, self.access_log):
            if not any(isinstance(f, SecretFilter) for f in log.filters):
                log.addFilter(SecretFilter())
