"""설정 → 구성원 관리 탭(IMPL-PLAN-14 §8). URL 연결은 B 갈래(web/urls.py)."""

from django.conf import settings
from django.contrib import messages
from django.contrib.auth.decorators import login_required
from django.core.exceptions import PermissionDenied
from django.http import Http404
from django.shortcuts import get_object_or_404, redirect
from django.urls import reverse
from django.views.decorators.http import require_POST

from common.errors import ServiceError
from orgs import member_info
from orgs import services as osv
from orgs.models import OrgMembership
from orgs.names import display_for
from orgs.settings import SPECS, display, effective, tab_keys

from ..forms import InviteForm
from .common import can_admin, org_or_404

# COPY:members.fields.kind_help.text/long/choice — (형식, 이름, 설명, 예시)
KIND_HELP = (
    ("text", "짧은 글", "한 줄 입력, 200자", "예: 학번"),
    ("long", "긴 글", "여러 줄, 2000자", "예: 가능한 시간"),
    ("choice", "선택지", "목록에서 하나 고름", "예: 학년(1·2·3·4)"),
)


def _rows(org, section):
    """설정 키 행(settings/_setting_row.html). 저장은 B의 org_settings ?tab=members&section=."""
    return [
        {
            "spec": SPECS[k],
            "value": effective(k, org=org),
            "display": display(k, effective(k, org=org)),
            "can_edit": True,
            "show_override": False,
        }
        for k in tab_keys("members", section)
    ]


def _missing_count(m) -> int:
    info = m.info or {}
    return sum(
        1
        for f in member_info.definition(m.org)["fields"]
        if f["required"] and not str(info.get(f["id"], "")).strip()
    )


def _panel(org, m, memberships):
    last_admin = sum(1 for x in memberships if x.role == "admin") <= 1
    return {
        "m": m,
        "name": display_for(m.user, org),
        "pending": osv.is_pending(m.user),
        "missing": _missing_count(m),
        "info_rows": [{**r, "error": ""} for r in member_info.rows(m)],
        "teams": [t for t in m.user.teams.all() if t.org_id == org.pk],
        "invite": org.invites.filter(for_user=m.user, revoked_at__isnull=True, use_count=0).first(),
        "can_remove": not (m.role == "admin" and last_admin),
    }


def members_ctx(request, org, member_id) -> dict:
    """구성원 목록과 &member= 패널의 맥락. member_id는 쿼리 문자열 그대로(없으면 None).

    member_id가 이 조직 멤버십이 아니면 404(다른 조직 구성원을 들여다보지 못하게).
    """
    if not can_admin(request.user, org):
        raise PermissionDenied
    memberships = sorted(
        org.memberships.select_related("user", "org").prefetch_related("user__teams"),
        key=lambda m: display_for(m.user, org),
    )
    rows = []
    for m in memberships:
        pending = osv.is_pending(m.user)
        rows.append(
            {
                "m": m,
                "name": display_for(m.user, org),
                "pending": pending,
                "missing": not pending and member_info.missing(m),
                "teams": [t for t in m.user.teams.all() if t.org_id == org.pk],
            }
        )
    panel = None
    if member_id not in (None, ""):
        m = next((x for x in memberships if str(x.pk) == str(member_id)), None)
        if m is None:
            raise Http404
        panel = _panel(org, m, memberships)
    d = member_info.definition(org)
    try:
        counts = member_info.empty_counts(org)
    except Exception:  # noqa: BLE001 — 영향 인원 안내만 빼고 화면은 그린다(§8.4)
        counts = {}
    me = next((x for x in memberships if x.user_id == request.user.pk), None)
    nick = (me.nickname if me else "") or request.user.display_name
    return {
        "member_rows": rows,
        "panel": panel,
        "show_real_name": d["show_real_name"],
        "field_cards": [{**f, "empty": counts.get(f["id"])} for f in d["fields"]],
        "field_kinds": KIND_HELP,
        "new_field_index": len(d["fields"]),
        "preview_rows": [{**r, "error": ""} for r in member_info.rows(me)] if me else [],
        "names_preview": {"nickname": nick, "real": request.user.real_name or nick},
        "invites": org.invites.filter(revoked_at__isnull=True, for_user__isnull=True),
        "invite_form": InviteForm(),
        "invite_rows": _rows(org, "invites"),
        "teams_tags_rows": _rows(org, "teams_tags"),
        "site_url": settings.SITE_URL,
        "max_fields": member_info.MAX_FIELDS,
    }


def panel_url(m) -> str:
    return reverse("org_settings", args=[m.org_id]) + f"?tab=members&member={m.pk}"


@login_required
@require_POST
def member_profile(request, membership_id):
    """관리자 패널 저장(nickname·v-*) → orgs.member_info.admin_save.

    실명·계정 표시 이름·아이디는 계정 정보라 받지 않는다(폼에 와도 읽지 않음).
    """
    m = get_object_or_404(OrgMembership.objects.select_related("org", "user"), pk=membership_id)
    org_or_404(request.user, m.org_id)  # 다른 조직이면 404
    if not can_admin(request.user, m.org):
        raise PermissionDenied
    was_missing = member_info.missing(m)
    values = {k[2:]: v for k, v in request.POST.items() if k.startswith("v-")}
    try:
        member_info.admin_save(
            m, request.user, nickname=request.POST.get("nickname"), values=values or None
        )
    except ServiceError as e:
        messages.error(request, " ".join(e.errors.values()))
        return redirect(panel_url(m))
    n = _missing_count(m)
    if was_missing and not n:
        messages.success(
            request, "이제 이 구성원은 조직을 쓸 수 있습니다."
        )  # COPY:members.panel.unblocked
    elif n:
        messages.warning(
            request, f"필수 항목 {n}개가 아직 비었습니다."
        )  # COPY:members.panel.still_missing
    else:
        messages.success(request, "저장했습니다.")  # COPY:members.panel.saved
    return redirect(panel_url(m))
