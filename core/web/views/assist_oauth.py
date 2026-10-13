"""개인 AI [OpenRouter로 연결]·[Hugging Face로 연결](assist/oauth.py). 문구는 임시(COPY:키, 최종 문구는 Sol)."""

from django.contrib import messages
from django.contrib.auth.decorators import login_required
from django.http import Http404
from django.shortcuts import redirect
from django.views.decorators.http import require_POST

from assist import oauth
from assist.models import AiSource

ERRORS = {
    "state": "연결 확인 정보가 만료되었거나 일치하지 않습니다. 설정 > AI에서 연결을 다시 시작해 주세요.",  # COPY:assist_oauth_err_state
    "denied": "연결이 취소되었거나 승인되지 않았습니다. 연결하려면 다시 시작해 승인해 주세요.",  # COPY:assist_oauth_err_denied
    "exchange": "AI 서비스에서 연결 정보를 받지 못했습니다. 잠시 후 연결을 다시 시작해 주세요.",  # COPY:assist_oauth_err_exchange
    "limit": f"개인 AI 등록 한도인 {AiSource.MAX_PERSONAL}개에 도달했습니다. 사용하지 않는 개인 AI를 삭제한 뒤 다시 연결해 주세요.",  # COPY:assist_oauth_err_limit
    "crypto": "서버의 암호화 설정이 없어 키를 저장할 수 없습니다. 서비스 운영자에게 문의해 주세요.",  # COPY:assist_src_key_no_crypto
}


def _provider_or_404(provider: str) -> str:
    if provider not in oauth.available():
        raise Http404
    return provider


@require_POST
@login_required
def ai_oauth_start(request, provider: str):
    return redirect(oauth.start(request, _provider_or_404(provider)))


@login_required
def ai_oauth_callback(request, provider: str):
    try:
        src = oauth.finish(request, _provider_or_404(provider))
    except oauth.OAuthError as e:
        messages.error(request, ERRORS[e.code])
    else:
        messages.success(
            request,
            f"개인 AI ‘{src.name}’을 연결했습니다. 모델은 {src.model}이며 [{src.name} 수정]에서 바꿀 수 있습니다.",  # COPY:assist_oauth_connected
        )
    return redirect("settings_ai")
