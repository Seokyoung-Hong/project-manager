from django.apps import AppConfig
from django.conf import settings
from django.core import checks


def privacy_placeholder_check(app_configs, **kwargs):
    """운영(DEBUG=False)에서 처리방침에 {{시행일}} 같은 자리표시가 남아 있으면 경고한다.

    서버 시작 때 migrate가 system check를 돌리므로 컨테이너 로그에 남는다. 막지는 않는다.
    """
    if settings.DEBUG:
        return []
    from .views.auth import PRIVACY_HTML

    if "{{" not in PRIVACY_HTML.read_text(encoding="utf-8"):
        return []
    return [
        checks.Warning(
            "개인정보 처리방침에 채우지 않은 자리표시({{…}})가 남아 있습니다.",
            hint="core/web/content/privacy.md의 {{시행일}}을 채우고 privacy.html을 다시 만들어 주세요.",
            id="web.W001",
        )
    ]


class WebConfig(AppConfig):
    default_auto_field = "django.db.models.BigAutoField"
    name = "web"

    def ready(self):
        checks.register(privacy_placeholder_check)
