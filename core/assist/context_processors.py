from django.utils.functional import SimpleLazyObject

from .services import ai_on as _ai_on


def ai_on(request):
    """`{% if ai_on %}` — 현재 조직의 AI 자동완성 스위치(IMPL-PLAN-12 §7.1).

    쓰는 템플릿에서만 판정하도록 늦게 계산한다(쓰지 않는 화면은 질의가 늘지 않는다).
    """
    from web.views.common import current_org

    def get():
        user = request.user
        if not user.is_authenticated:
            return False
        return _ai_on(user, current_org(request))

    from . import copilot

    on = copilot.enabled()  # 설정값만 본다(질의 없음)
    return {
        "ai_on": SimpleLazyObject(get),
        "copilot_on": on,
        "copilot_models": copilot.models() if on else [],
    }
