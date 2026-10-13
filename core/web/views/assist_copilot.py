"""설정 AI 탭의 [GitHub Copilot으로 연결]·모델 고르기(assist/copilot.py). 문구는 임시(COPY:키, 최종 문구는 Sol).

새 OAuth는 없다 — 이미 연결된 GitHub 계정(GitHub App 사용자 토큰)을 그대로 쓴다. 행에는 키를 담지 않는다.
"""

from django.contrib import messages
from django.contrib.auth.decorators import login_required
from django.db.models import Max
from django.http import Http404, HttpResponseBadRequest
from django.shortcuts import get_object_or_404, redirect
from django.views.decorators.http import require_POST

from assist import copilot
from assist.models import AiSource
from github.models import GitHubIdentity


@require_POST
@login_required
def copilot_connect(request):
    """개인 AI(GitHub Copilot) 한 행을 만든다. 사람당 하나, 개인 AI 상한 안에서."""
    if not copilot.enabled():
        raise Http404
    user = request.user
    if not GitHubIdentity.objects.filter(user=user).exists():
        messages.error(
            request,
            "GitHub 계정이 연결되어 있지 않습니다. 프로필에서 GitHub 계정을 먼저 연결해 주세요.",  # COPY:assist_copilot_no_github
        )
        return redirect("settings_ai")
    if AiSource.objects.filter(user=user, base_url=copilot.URL).exists():
        messages.info(
            request, "GitHub Copilot이 이미 개인 AI로 등록되어 있습니다."
        )  # COPY:assist_copilot_exists
        return redirect("settings_ai")
    if AiSource.objects.filter(user=user, kind="personal").count() >= AiSource.MAX_PERSONAL:
        messages.error(
            request,
            f"개인 AI 등록 한도인 {AiSource.MAX_PERSONAL}개에 도달했습니다. 새로 등록하려면 사용하지 않는 개인 AI를 삭제해 주세요.",  # COPY:assist_src_limit
        )
        return redirect("settings_ai")
    last = AiSource.objects.filter(user=user).aggregate(m=Max("position"))["m"]
    AiSource.objects.create(
        user=user,
        kind="personal",
        name="GitHub Copilot",  # COPY:assist_copilot_name
        base_url=copilot.URL,
        route="direct",
        model=copilot.models()[0],
        position=0 if last is None else last + 1,
    )
    messages.success(
        request, "GitHub Copilot을 개인 AI로 등록했습니다."
    )  # COPY:assist_copilot_added
    return redirect("settings_ai")


@require_POST
@login_required
def copilot_model(request, source_id: int):
    """내 Copilot 행의 모델을 정해진 목록(COPILOT_MODELS) 안에서 바꾼다."""
    src = get_object_or_404(AiSource, pk=source_id, user=request.user, base_url=copilot.URL)
    model = request.POST.get("model", "")
    if model not in copilot.models():
        return HttpResponseBadRequest()
    src.model = model
    src.save(update_fields=["model"])
    messages.success(
        request, f"GitHub Copilot 모델을 {model}로 변경했습니다."
    )  # COPY:assist_copilot_model_saved
    return redirect("settings_ai")
