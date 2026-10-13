"""설정 → 구성원 관리 탭(IMPL-PLAN-14 §8). A0 껍데기 — C 갈래가 채운다. URL 연결은 B 갈래(web/urls.py)."""

from django.contrib.auth.decorators import login_required
from django.http import Http404
from django.views.decorators.http import require_POST


def members_ctx(request, org, member_id) -> dict:
    """구성원 목록과 &member= 패널의 맥락. member_id는 쿼리 문자열 그대로(없으면 None)."""
    return {}


@login_required
@require_POST
def member_profile(request, membership_id):
    """관리자 패널 저장(nickname·v-*) → orgs.member_info.admin_save."""
    raise Http404
