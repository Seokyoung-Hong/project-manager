import json
import time
import urllib.error
import urllib.parse
import urllib.request

from django.conf import settings
from django.contrib import messages
from django.contrib.auth.decorators import login_required
from django.core.exceptions import PermissionDenied
from django.db.models import Count, Prefetch
from django.http import Http404, HttpResponseBadRequest, HttpResponseForbidden
from django.shortcuts import get_object_or_404, redirect, render
from django.urls import reverse
from django.utils import timezone
from django.views.decorators.http import require_POST

from common.errors import ServiceError
from github import services as gh_services
from github import writes as gh_writes
from notes.transcription import parse_models
from orgs import member_info
from orgs import requests as creq
from orgs import services as osv
from orgs.governance import governance_text
from orgs.models import ChangeRequest, Invite, OrgMembership, TeamMembership
from orgs.names import display_for
from orgs.settings import (
    ADMIN_TABS,
    COPY_DRAFT,
    ORG_TABS,
    SPECS,
    STT_KEYS,
    display,
    effective,
    enforced,
    locked_keys,
    secret_value,
    tab_keys,
    validate_stt_url,
)
from projects.services import project_stats_bulk, visible_projects
from reports.services import org_status
from tasks.models import Task, TaskProject

from ..forms import InviteForm, OrgForm
from .auth import _safe_next
from .common import apply_service_error, can_admin, current_org, not_admin, org_or_404
from .github_retries import attempt


@login_required
def org_current(request):
    org = current_org(request)
    if org is None:
        return redirect("org_list")
    return redirect("org_detail", org_id=org.pk)


@login_required
def org_list(request):
    orgs = list(
        osv.orgs_of(request.user)
        .annotate(project_count=Count("projects", distinct=True))
        .annotate(member_count=Count("memberships", distinct=True))
        .order_by("name")
    )
    if len(orgs) == 1:
        return redirect("org_detail", org_id=orgs[0].pk)
    admin_org_ids = set(
        OrgMembership.objects.filter(user=request.user, role="admin").values_list(
            "org_id", flat=True
        )
    )
    return render(request, "orgs/list.html", {"orgs": orgs, "admin_org_ids": admin_org_ids})


@login_required
def org_new(request):
    form = OrgForm(request.POST or None)
    if request.method == "POST" and form.is_valid():
        d = form.cleaned_data
        try:
            org = osv.create_org(d["name"], d["purpose"], request.user)
            request.session["org_id"] = org.pk
            return redirect("org_detail", org_id=org.pk)
        except ServiceError as e:
            apply_service_error(form, e)
    return render(request, "orgs/new.html", {"form": form})


def _getting_started(org) -> list[dict] | None:
    """갓 만든 조직(태스크 0개)의 "시작하기" 단계. 다 끝냈거나 태스크가 생기면 None(카드를 숨긴다)."""
    if Task.objects.filter(project__org=org).exists():
        return None
    steps = [
        {
            "label": "첫 프로젝트 만들기",
            "value": "프로젝트를 만들면 관련 태스크와 진행 상황을 함께 볼 수 있습니다.",
            "done": org.projects.exists(),
            "url": None,  # 템플릿에서 [새 프로젝트] 대화상자를 연다
        },
        {
            "label": "팀원 초대",
            "value": "초대 링크로 가입한 팀원은 이 조직에 바로 참여할 수 있습니다.",
            "done": org.memberships.count() > 1 or org.invites.exists(),
            "url": _settings_url(org.pk, "members", anchor="settings-members-invites"),
        },
    ]
    if settings.GITHUB_ENABLED:
        steps.append(
            {
                "label": "저장소 연결",
                "value": "저장소를 연결하면 연결된 PR의 생성·병합에 따라 태스크 상태가 바뀝니다.",
                "done": hasattr(org, "github"),
                "url": _settings_url(org.pk, "integrations", anchor="github"),
            }
        )
    if settings.DISCORD_CLIENT_ID:
        steps.append(
            {
                "label": "Discord 알림",
                "value": "Discord 서버를 연결하면 팀 채널에서 조직 알림과 주간 보고를 받을 수 있습니다.",
                "done": bool(org.discord_guild_id),
                "url": _settings_url(org.pk, "integrations", anchor="discord"),
            }
        )
    return None if all(s["done"] for s in steps) else steps


@login_required
def org_detail(request, org_id):
    """조직 현황. README §3."""
    org = org_or_404(request.user, org_id)
    request.session["org_id"] = org.pk
    include_archived = request.GET.get("include_archived") == "1"
    st = org_status(org, viewer=request.user)
    c = st["counts"]
    me_url = reverse("me")
    tiles = [
        ("미완료", c["open"], f"{me_url}?member=0", False),
        ("진행 중", c["doing"], f"{me_url}?member=0&status=doing", False),
        ("검토 대기", c["review"], f"{me_url}?member=0&status=review", False),
        ("기한 초과", c["overdue"], f"{me_url}?member=0&due=overdue", True),
        ("막힘", c["blocked"], f"{me_url}?member=0&status=blocked", True),
        ("완료", c["done"], f"{me_url}?member=0&status=done_7d", False),
    ]
    projects = (
        visible_projects(request.user, org)
        .select_related("org")
        .prefetch_related("owners", "teams")
        .order_by("name")
    )
    if not include_archived:
        projects = projects.filter(is_archived=False)
    projects = list(projects)
    stats = project_stats_bulk(projects)
    is_admin = can_admin(request.user, org)
    return render(
        request,
        "orgs/detail.html",
        {
            "org": org,
            "tiles": tiles,
            "project_rows": [(p, stats[p.pk]) for p in projects],
            "has_linked": TaskProject.objects.filter(status="active", project__org=org).exists(),
            "by_assignee": st["by_assignee"],
            "me_url": me_url,
            "include_archived": include_archived,
            "is_admin": is_admin,
            "getting_started": _getting_started(org) if is_admin else None,
            "tab": "overview",
        },
    )


def _member_teams(request, org):
    """팀원이 보는 팀 목록. 관리 기능 없이 누가 어느 팀이고 누가 팀장인지만 보여 준다."""
    mine = set(request.user.team_memberships.values_list("team_id", flat=True))
    # 비공개 팀은 이름만 보인다 — 인원·팀장은 볼 수 있는 팀에서만 센다.
    visible = set(osv.visible_teams(request.user, org).values_list("pk", flat=True))
    leads = Prefetch(
        "memberships",
        queryset=TeamMembership.objects.filter(is_lead=True).select_related("user"),
        to_attr="leads",
    )
    rows = [
        {
            "team": t,
            "mine": t.pk in mine,
            "visible": t.pk in visible,
            "member_count": t.member_count if t.pk in visible else None,
            "leads": [m.user for m in t.leads] if t.pk in visible else [],
        }
        for t in org.teams.annotate(member_count=Count("members")).prefetch_related(leads)
    ]
    rows.sort(key=lambda r: (not r["mine"], r["team"].name))
    return render(
        request, "orgs/teams_member.html", {"org": org, "team_rows": rows, "tab": "teams"}
    )


@login_required
def org_teams(request, org_id):
    """조직 → 팀(관리자). 구성원·초대는 설정 → 구성원 관리(IMPL-PLAN-14 §4)."""
    org = org_or_404(request.user, org_id)
    if not can_admin(request.user, org):
        return _member_teams(request, org)
    teams = [
        {
            "team": t,
            "member_count": t.member_count,
            "project_count": t.project_count,
            "github": getattr(t, "github", None),
        }
        for t in org.teams.select_related("github").annotate(
            member_count=Count("members", distinct=True),
            project_count=Count("projects", distinct=True),
        )
    ]
    return render(
        request,
        "orgs/teams.html",
        {
            "org": org,
            "team_rows": teams,
            "is_admin": True,
            "tab": "teams",
        },
    )


@login_required
@require_POST
def member_tags(request, membership_id):
    membership = get_object_or_404(OrgMembership.objects.select_related("org"), pk=membership_id)
    org_or_404(request.user, membership.org_id)
    tags = (request.POST.get("tags") or "").split(",")
    try:
        osv.set_tags(membership, tags, request.user)
    except ServiceError as e:
        messages.error(request, " ".join(e.errors.values()))
    return _member_redirect(request, membership.org_id, membership.pk)


@login_required
@require_POST
def member_nickname(request, membership_id):
    """조직 표시 이름 바꾸기 — 본인(구성원 정보 화면) 또는 관리자(구성원 목록). 권한·실명 표시 조직은 서비스가 거른다."""
    membership = get_object_or_404(
        OrgMembership.objects.select_related("org", "user"), pk=membership_id
    )
    org_or_404(request.user, membership.org_id)
    try:
        osv.set_nickname(membership, request.POST.get("nickname", ""), request.user)
        messages.success(request, "조직 표시 이름을 저장했습니다.")  # COPY:nickname.saved
    except ServiceError as e:
        messages.error(request, " ".join(e.errors.values()))
    nxt = _safe_next(request, request.POST.get("next", ""))
    return redirect(nxt) if nxt else _member_redirect(request, membership.org_id, membership.pk)


def _member_redirect(request, org_id, member=None):
    """구성원 액션 뒤 설정 → 구성원 관리(구성원 단위면 그 패널)로. 관리자가 아니면 조직 현황으로 —
    관리자 탭은 비관리자를 내 정보로 돌리므로 "관리자만 할 수 있습니다" 메시지가 엉뚱한 곳에 묻힌다."""
    is_admin = OrgMembership.objects.filter(org_id=org_id, user=request.user, role="admin").exists()
    if not is_admin:
        return redirect("org_detail", org_id=org_id)
    return redirect(_settings_url(org_id, "members", member=member))


@login_required
@require_POST
def invite_create(request, org_id):
    org = org_or_404(request.user, org_id)
    form = InviteForm(request.POST)
    if not form.is_valid():
        messages.error(
            request, "만료 기간은 1~90일로 입력해 주세요. 초대 링크는 만들지 않았습니다."
        )
        return _member_redirect(request, org.pk)
    days = form.cleaned_data["days"]
    try:
        invite = osv.create_invite(org, request.user, days=days)
        messages.success(request, f"초대 링크: {settings.SITE_URL}{invite.path}")
    except ServiceError as e:
        messages.error(request, " ".join(e.errors.values()))
        return _member_redirect(request, org.pk)
    # 개인 계정 설치에는 GitHub 조직이 없다. 부르면 404와 쓸모없는 재시도 항목만 남는다.
    if (
        settings.GITHUB_ENABLED
        and form.cleaned_data["gh_invite"]
        and not gh_services.is_user_install(org)
    ):
        login = form.cleaned_data["gh_login"].strip()
        if login:
            warn = attempt(
                request,
                gh_writes.invite_to_org,
                org,
                login,
                actor=request.user,
                retry={
                    "kind": "invite",
                    "org_id": org.pk,
                    "invite_id": invite.pk,
                    "login": login,
                    "target": f"{org.name} · @{login}",
                },
            )
            if warn:
                messages.warning(request, warn, extra_tags="integration-help")
            else:
                messages.success(request, f"GitHub 조직에도 @{login}님을 초대했습니다.")
    return _member_redirect(request, org.pk)


@login_required
@require_POST
def member_add_pending(request, org_id):
    org = org_or_404(request.user, org_id)
    try:
        m = osv.add_pending_member(org, request.user, request.POST.get("display_name", ""))
        messages.success(
            request,
            f"가입 전 구성원 {display_for(m.user, org)}님을 추가했습니다. [초대 링크 만들기]로 본인에게 넘겨 주세요.",
        )
    except ServiceError as e:
        messages.error(request, " ".join(e.errors.values()))
        return _member_redirect(request, org.pk)
    return _member_redirect(request, org.pk, m.pk)


@login_required
@require_POST
def member_invite(request, membership_id):
    membership = get_object_or_404(
        OrgMembership.objects.select_related("org", "user"), pk=membership_id
    )
    org_or_404(request.user, membership.org_id)
    try:
        invite = osv.create_personal_invite(membership, request.user)
        messages.success(
            request,
            f"{display_for(membership.user, membership.org_id)}님의 초대 링크: {settings.SITE_URL}{invite.path}",
        )
    except ServiceError as e:
        messages.error(request, " ".join(e.errors.values()))
    return _member_redirect(request, membership.org_id, membership.pk)


@login_required
@require_POST
def invite_revoke(request, invite_id):
    invite = get_object_or_404(Invite.objects.select_related("org"), pk=invite_id)
    org_or_404(request.user, invite.org_id)
    try:
        osv.revoke_invite(invite, request.user)
    except ServiceError as e:
        messages.error(request, " ".join(e.errors.values()))
    return _member_redirect(request, invite.org_id)


@login_required
@require_POST
def member_role(request, membership_id):
    membership = get_object_or_404(OrgMembership.objects.select_related("org"), pk=membership_id)
    org_or_404(request.user, membership.org_id)
    try:
        osv.change_role(membership, request.POST.get("role", ""), request.user)
    except ServiceError as e:
        messages.error(request, " ".join(e.errors.values()))
    return _member_redirect(request, membership.org_id, membership.pk)


@login_required
@require_POST
def member_remove(request, membership_id):
    membership = get_object_or_404(
        OrgMembership.objects.select_related("org", "user"), pk=membership_id
    )
    org_or_404(request.user, membership.org_id)
    org_id = membership.org_id
    org, user = membership.org, membership.user
    try:
        osv.remove_member(membership, request.user)
    except ServiceError as e:
        messages.error(request, " ".join(e.errors.values()))
        return _member_redirect(request, org_id, membership.pk)
    if (
        settings.GITHUB_ENABLED
        and getattr(org, "github", None) is not None
        and not gh_services.is_user_install(org)
    ):
        login = gh_writes._login_of(user)
        if login:
            warn = attempt(
                request,
                gh_writes.remove_from_org,
                org,
                login,
                actor=request.user,
                retry={
                    "kind": "remove",
                    "org_id": org.pk,
                    "user_id": user.pk,
                    "login": login,
                    "target": f"{org.name} · @{login}",
                },
            )
            if warn:
                messages.warning(request, warn, extra_tags="integration-help")
    return _member_redirect(request, org_id)


@login_required
def org_governance(request, org_id):
    """개발 거버넌스. 멤버는 읽고 관리자는 고친다."""
    org = org_or_404(request.user, org_id)
    is_admin = can_admin(request.user, org)
    error = ""
    if request.method == "POST" and is_admin:
        try:
            osv.set_governance(
                org, "" if request.POST.get("reset") else request.POST["text"], request.user
            )
            messages.success(request, "업무 규칙을 저장했습니다.")
            return redirect("org_governance", org_id=org.pk)
        except ServiceError as e:
            error = "; ".join(e.errors.values())
    return render(
        request,
        "orgs/governance.html",
        {
            "org": org,
            "text": governance_text(org),
            "is_default": not org.governance.strip(),
            "is_admin": is_admin,
            "error": error,
            "tab": "governance",
            "enforced_rows": enforced(org),
            "pending_requests": _pending(org, "governance") if is_admin else [],
        },
    )


def _pending(org, kind):
    return list(
        org.change_requests.filter(
            kind=kind, status="pending", expires_at__gt=timezone.now()
        ).select_related("requested_by")
    )


@login_required
def change_request(request, org_id, req_id):
    """AI가 올린 설정·거버넌스 변경 요청을 보고 허용·거절한다. 로그인 세션 전용 — API 토큰으로는 못 온다."""
    org = org_or_404(request.user, org_id)
    if resp := not_admin(request, org, "AI 변경 요청"):
        return resp
    req = get_object_or_404(
        ChangeRequest.objects.select_related("requested_by", "token", "reviewed_by"),
        pk=req_id,
        org=org,
    )
    if request.method == "POST":
        try:
            if request.POST.get("action") == "approve":
                creq.approve(req, request.user)
                messages.success(request, f"{req.get_kind_display()} 변경을 허용해 반영했습니다.")
            elif request.POST.get("action") == "reject":
                creq.reject(req, request.user, request.POST.get("reason", ""))
                messages.success(request, "요청을 거절했습니다.")
        except ServiceError as e:
            messages.error(request, " ".join(e.errors.values()))
        return redirect("change_request", org_id=org.pk, req_id=req.pk)
    return render(
        request,
        "orgs/change_request.html",
        {
            "org": org,
            "is_admin": True,
            "tab": req.kind,
            "req": req,
            "rows": creq.settings_diff(req) if req.kind == "settings" else [],
            "diff": creq.governance_diff(req) if req.kind == "governance" else [],
            "after": creq.governance_after(req) if req.kind == "governance" else "",
        },
    )


# ---------- 설정 (IMPL-PLAN-4 §7) ----------


def _settings_from_post(post, specs):
    """체크박스가 꺼진 bool은 폼에 안 실려 오므로 레지스트리를 돌며 False로 채운다."""
    data = {}
    for spec in specs:
        if spec.kind == "bool":
            data[spec.key] = spec.key in post
        elif spec.kind == "secret":
            # 빈 칸 = 그대로 둔다(merge_secrets). '지우기'를 고르면 False.
            data[spec.key] = (
                False if post.get(f"clear__{spec.key}") == "on" else post.get(spec.key, "")
            )
        elif spec.kind == "set":
            data[spec.key] = post.getlist(spec.key)
        elif spec.key in post:
            data[spec.key] = post[spec.key]
    return data


def _org_settings_history(org):
    from tasks.models import ChangeLog

    extra_labels = {
        "_locked": "프로젝트가 바꿀 수 있는 항목",
        "member_fields": "구성원 정보",
        "nickname": "조직 표시 이름",  # COPY:org_history.nickname
        "member_info": "구성원 정보 수정",  # COPY:org_history.member_info (관리자 대리 수정)
    }
    logs = (
        ChangeLog.objects.filter(target_type="org", target_id=org.pk)
        .select_related("actor")
        .order_by("-created_at")[:20]
    )
    rows = []
    for log in logs:
        spec = SPECS.get(log.field)
        at = timezone.localtime(log.created_at)
        rows.append(
            {
                "field": spec.label if spec else extra_labels.get(log.field, log.field),
                "from": log.old_value,
                "to": log.new_value,
                "time": f"{at.month}월 {at.day}일 {at:%H:%M}",
                "actor": display_for(log.actor, org)
                if log.actor
                else (log.external_actor or "GitHub"),
                "source": log.get_source_display(),
            }
        )
    return rows


@login_required
@require_POST
def org_delete(request, org_id):
    """조직 삭제. 관리자가 조직 이름을 정확히 입력해야 진행한다(JS 확인 창이 없어도 서버가 막는다)."""
    org = org_or_404(request.user, org_id)
    if not can_admin(request.user, org):
        raise PermissionDenied
    if request.POST.get("confirm_name", "").strip() != org.name:
        messages.error(
            request, "조직 이름이 일치하지 않아 삭제하지 않았습니다. 이름을 정확히 입력해 주세요."
        )
        return redirect(_settings_url(org.pk, "org", anchor="settings-org-danger"))
    name = org.name
    osv.delete_org(org, request.user)
    if request.session.get("org_id") == org_id:
        request.session.pop("org_id")
    messages.success(request, f"조직 '{name}'을(를) 삭제했습니다.")
    return redirect("org")


def _settings_url(org_id, tab="me", *, member=None, anchor="") -> str:
    """설정 셸 주소(IMPL-PLAN-14 §5). orgs/<id>/settings?tab=<코드>[&member=<m>][#앵커]."""
    url = reverse("org_settings", args=[org_id]) + "?tab=" + tab
    if member:
        url += f"&member={member}"
    return url + (f"#{anchor}" if anchor else "")


def _integrations_on() -> bool:
    return settings.GITHUB_ENABLED or bool(settings.DISCORD_CLIENT_ID)


def _settings_nav(org, tab, is_admin):
    """셸 왼쪽 탭(≤700px는 설정 목록 화면). [(묶음 라벨, [(코드, 라벨, 주소, 현재)])]."""
    shown = []
    for code, label_key, _ in ORG_TABS:
        if code in ADMIN_TABS and not is_admin:
            continue
        if code == "integrations" and not _integrations_on():
            continue
        shown.append(
            (code, COPY_DRAFT.get(label_key, label_key), _settings_url(org.pk, code), code == tab)
        )
    return [
        ("나", [t for t in shown if t[0] not in ADMIN_TABS]),  # COPY:org_settings.group.me
        ("조직 관리", [t for t in shown if t[0] in ADMIN_TABS]),  # COPY:org_settings.group.admin
    ]


def _tab_sections(tab):
    return next(sections for code, _, sections in ORG_TABS if code == tab)


def _save_keys(tab, section=None) -> tuple[str, ...]:
    """이 탭(섹션) 폼이 저장하는 키. 전사(stt) 섹션은 자기 폼·엔드포인트가 있어 뺀다(§9.2)."""
    return tuple(k for k in tab_keys(tab, section) if k not in STT_KEYS)


def _key_sections(org, tab):
    """설정 키 탭의 섹션별 행. 키 없는 섹션·전사 섹션은 템플릿이 따로 그린다."""
    locked = locked_keys(org)
    out = []
    for sec, label_key, _ in _tab_sections(tab):
        keys = _save_keys(tab, sec)
        if not keys:
            continue
        rows = []
        for key in keys:
            value = effective(key, org=org)
            rows.append(
                {
                    "spec": SPECS[key],
                    "value": value,
                    "display": display(key, value),
                    "unlocked": key not in locked,
                    "can_edit": True,
                    "show_override": True,
                }
            )
        out.append({"code": sec, "label": COPY_DRAFT.get(label_key, label_key), "rows": rows})
    return out


def _me_ctx(request, org, membership, errors=None, posted=None):
    """내 정보 탭(§7). posted = 오류로 다시 그릴 때 입력값 보존."""
    errors = errors or {}
    posted = posted or {}
    values = posted.get("values")
    rows = [
        {
            **r,
            "value": values.get(r["id"], "") if values is not None else r["value"],
            "error": errors.get(r["id"], ""),
        }
        for r in member_info.rows(membership)
    ]
    return {
        "me": membership,
        "me_rows": rows,
        "me_errors": errors,
        "me_real_name": posted.get("real_name", request.user.real_name),
        "me_nickname": posted.get("nickname", membership.nickname),
        "me_shown": display_for(request.user, org),
        "show_real_name": member_info.definition(org)["show_real_name"],
    }


def _render_settings(request, org, tab, is_admin, membership, **me):
    ctx = {
        "org": org,
        "is_admin": is_admin,
        "tab": "settings",  # 조직 메뉴(_tabs.html) 강조
        "settings_tab": tab,
        "settings_tab_label": COPY_DRAFT.get(f"org_settings.tab.{tab}", tab),
        "settings_nav": _settings_nav(org, tab, is_admin),
        # 주소에 탭이 있으면 모바일은 탭 화면, 없으면 설정 목록 화면(시안 A)
        "in_tab": "tab" in request.GET or request.method == "POST",
        "me_blocked": member_info.missing(membership),
    }
    if tab == "me":
        ctx.update(_me_ctx(request, org, membership, **me))
    elif tab == "members":
        from .org_members import members_ctx

        ctx.update(members_ctx(request, org, request.GET.get("member")))
    elif tab == "integrations":
        from .discord import discord_ctx
        from .github import github_ctx

        if settings.GITHUB_ENABLED:
            ctx.update(github_ctx(request, org))
        if settings.DISCORD_CLIENT_ID:
            ctx.update(discord_ctx(request, org))
    else:
        ctx["key_sections"] = _key_sections(org, tab)
        ctx["pending_requests"] = _pending(org, "settings")
        if tab == "meeting":
            from .transcribe import stt_ctx

            ctx.update(stt_ctx(request, org))
        elif tab == "org":
            ctx["history"] = _org_settings_history(org)
    return render(request, "orgs/settings.html", ctx)


@login_required
def org_settings(request, org_id):
    """조직 설정 셸(IMPL-PLAN-14 §2·§5·§6). 모든 구성원이 들어오고, 관리자 탭은 매 요청 서버가 검사한다.

    GET ?tab=<코드>: 그 탭만 그린다. 모르는 탭 → 내 정보. 비관리자가 관리자 탭 → 내 정보로 돌린다.
    POST ?tab=<코드>[&section=<섹션>]: 그 탭(섹션) 키만 부분 저장. 비관리자 → 403.
    """
    org = org_or_404(request.user, org_id)
    is_admin = can_admin(request.user, org)
    membership = (
        OrgMembership.objects.select_related("org").filter(org=org, user=request.user).first()
    )
    tab = request.GET.get("tab") or "me"
    if tab not in {code for code, _, _ in ORG_TABS}:
        tab = "me"
    if tab in ADMIN_TABS and not is_admin:
        if request.method == "POST":
            raise PermissionDenied
        # COPY:org_settings.forbidden
        messages.info(request, "조직 관리자만 볼 수 있는 설정입니다. 내 정보로 이동했습니다.")
        return redirect(_settings_url(org.pk))
    if tab == "integrations" and not _integrations_on():
        return redirect(_settings_url(org.pk))
    # 연동 탭은 필수 구성원 정보 관문을 적용한다(§6). 다른 관리자 탭은 항목 정의를 고칠 수 있게 열어 둔다.
    if tab == "integrations" and membership is not None and member_info.missing(membership):
        # COPY:org_settings.integrations_blocked
        messages.error(
            request, "연동 설정을 사용하려면 내 정보의 필수 구성원 정보를 먼저 입력해 주세요."
        )
        return redirect(_settings_url(org.pk))
    if request.method == "POST":
        return _save_tab(request, org, tab)
    if membership is None:  # 구성원 아닌 운영자(org_or_404 통과) — 내 정보가 없다
        raise Http404
    return _render_settings(request, org, tab, is_admin, membership)


def _save_tab(request, org, tab):
    """설정 키 탭의 부분 저장(§9). 저장 키는 서버가 tab_keys로 정한다 — 폼이 보낸 키 목록은 믿지 않는다."""
    section = request.GET.get("section") or None
    keys = _save_keys(tab, section)
    if not keys:
        raise Http404
    specs = [SPECS[k] for k in keys]
    try:
        # 반환값(잠금 뒤 다시 읽은 새 객체)을 set_locks에 넘긴다 — 옛 org를 넘기면 방금 쓴 값을 덮는다(§9.1)
        org = osv.set_org_settings(
            org, _settings_from_post(request.POST, specs), request.user, only=keys
        )
        osv.set_locks(
            org,
            [
                s.key
                for s in specs
                if s.overridable and request.POST.get(f"unlock__{s.key}") != "on"
            ],
            request.user,
            only=keys,
        )
        label = COPY_DRAFT.get(f"org_settings.tab.{tab}", tab)
        messages.success(request, f"{label} 설정을 저장했습니다.")  # COPY:org_settings.saved_tab
    except ServiceError as e:
        messages.error(request, " ".join(e.errors.values()))
    return redirect(
        _settings_url(org.pk, tab, anchor=f"settings-{tab}-{section}" if section else "")
    )


def _fields_from_post(post) -> list[dict]:
    """조직 설정의 구성원 정보 표. 행마다 f<n>-이름. 이름이 빈 새 행과 [삭제] 표시한 행은 뺀다."""
    rows = []
    i = 0
    while f"f{i}-label" in post:
        p = f"f{i}-"
        fid = post.get(p + "id", "")
        if post.get(p + "delete") != "on" and (fid or post.get(p + "label", "").strip()):
            try:
                order = int(post.get(p + "order") or 0)
            except ValueError:
                order = 0
            rows.append(
                (
                    order,
                    i,
                    {
                        "id": fid,
                        "label": post.get(p + "label", ""),
                        "kind": post.get(p + "kind", ""),
                        "required": post.get(p + "required") == "on",
                        "help": post.get(p + "help", ""),
                        "choices": post.get(p + "choices", "").splitlines(),
                    },
                )
            )
        i += 1
    return [f for _, _, f in sorted(rows, key=lambda r: r[:2])]


@login_required
@require_POST
def org_member_fields(request, org_id):
    """이름 표시 방식(part=names)·요청할 정보 항목(part=fields). part 없음 = 옛 한 폼(둘 다)."""
    org = org_or_404(request.user, org_id)
    if denied := not_admin(request, org, "조직 설정"):
        return denied
    part = request.POST.get("part", "")
    if part not in ("", "names", "fields"):
        return HttpResponseBadRequest()
    kwargs = {}
    if part in ("", "names"):
        kwargs["show_real_name"] = request.POST.get("show_real_name") == "on"
    if part in ("", "fields"):
        kwargs["fields"] = _fields_from_post(request.POST)
    try:
        member_info.set_definition(org, request.user, **kwargs)
        messages.success(request, "구성원 정보 항목을 저장했습니다.")
    except ServiceError as e:
        messages.error(request, " ".join(e.errors.values()))
    return redirect(_settings_url(org.pk, "members", anchor=f"settings-members-{part or 'names'}"))


@login_required
def org_member_info(request, org_id):
    """내 정보 저장 엔드포인트(§5·§7). GET은 설정 → 내 정보로 보낸다(옛 주소).

    실명·조직 표시 이름·구성원 정보를 한 번에 원자 저장한다. 안 보낸 칸은 그대로(옛 v-* 폼 호환).
    대상은 항상 request.user 본인의 멤버십이다 — 본문의 대상 식별자는 받지 않는다.
    """
    org = org_or_404(request.user, org_id)
    if request.method != "POST":
        return redirect(_settings_url(org.pk))
    m = get_object_or_404(
        OrgMembership.objects.select_related("org", "user"), org=org, user=request.user
    )
    was_blocked = member_info.missing(m)
    post = request.POST
    values = {k[2:]: v for k, v in post.items() if k.startswith("v-")}
    real_name = post.get("real_name") if "real_name" in post else None
    nickname = post.get("nickname") if "nickname" in post else None
    try:
        member_info.save_me(m, real_name=real_name, nickname=nickname, values=values or None)
    except ServiceError as e:
        posted = {"values": values}
        if real_name is not None:
            posted["real_name"] = real_name
        if nickname is not None:
            posted["nickname"] = nickname
        return _render_settings(
            request, org, "me", can_admin(request.user, org), m, errors=e.errors, posted=posted
        )
    if was_blocked and not member_info.missing(m):
        messages.success(
            request,
            f"필수 구성원 정보가 모두 입력되었습니다. 이제 {org.name} 조직을 사용할 수 있습니다.",
        )  # COPY:me.unblocked
        return redirect("org_detail", org_id=org.pk)
    messages.success(request, "내 정보를 저장했습니다.")  # COPY:me.saved
    return redirect(_settings_url(org.pk))


class _NoRedirect(urllib.request.HTTPRedirectHandler):
    def redirect_request(self, *args, **kwargs):
        return None  # 3xx는 HTTPError로 끝낸다 — 다른 호스트로 끌려가지 않는다.


def _stt_call(org, url: str, path: str, method: str = "GET"):
    """로컬 전사 서버 호출(discord_gateway transcribe.mjs와 같은 규약). (본문, 오류 문구, 상태 코드)."""
    # SSRF: 조직 관리자만 부를 수 있고 로컬 서버가 목적이라 사설 IP는 허용한다(루프백·내부 이름은 validate_stt_url이 막는다).
    error = validate_stt_url(url) if url else "서버 주소를 입력해 주세요."
    if error:
        return b"", error, None
    req = urllib.request.Request(url.rstrip("/") + path, method=method)
    key = secret_value("meeting.stt_api_key", org)
    if key:
        req.add_header("Authorization", f"Bearer {key}")
    try:
        with urllib.request.build_opener(_NoRedirect).open(req, timeout=5) as r:  # noqa: S310 — http(s)만 검증함
            body = r.read(1_000_001)
        return (
            (b"", "응답이 1MB를 넘습니다.", None) if len(body) > 1_000_000 else (body, "", r.status)
        )
    except urllib.error.HTTPError as e:
        if e.code in (401, 403):
            return b"", f"인증에 실패했습니다(HTTP {e.code}). 서버 키를 확인해 주세요.", e.code
        return b"", f"서버가 HTTP {e.code}로 응답했습니다.", e.code
    except TimeoutError:
        return b"", "응답 시간(5초)을 넘겼습니다.", None
    except OSError as e:  # URLError·연결 끊김
        timed_out = isinstance(getattr(e, "reason", None), TimeoutError)
        return (
            b"",
            "응답 시간(5초)을 넘겼습니다." if timed_out else "서버에 접속할 수 없습니다.",
            None,
        )


def _stt_url(request, org) -> str:
    return (
        request.POST.get("meeting.stt_url") or effective("meeting.stt_url", org=org) or ""
    ).strip()


def stt_models(org, url: str):
    """GET /v1/models → ([{id, status, label, name, fits, info}], 오류, ms). 없는 필드는 없는 대로 둔다."""
    start = time.monotonic()
    body, error, _ = _stt_call(org, url, "/v1/models")
    if error:
        return [], error, None
    try:
        models = parse_models(json.loads(body)["data"])
    except (ValueError, KeyError, TypeError):
        return [], "응답 형식이 OpenAI 호환 모델 목록이 아닙니다.", None
    return models, "", round((time.monotonic() - start) * 1000)


def _stt_models(request, org, ctx=None):
    """모델 select 부분 템플릿. downloading이 있으면 3초 뒤 다시 부른다(폴링)."""
    ctx = ctx or {}
    models, error, ms = stt_models(org, _stt_url(request, org))
    ctx["ms"] = ms
    ctx["error"] = ctx.get("error") or error
    # 지금 고른 값(폼 → 저장값)은 목록에 없어도 남겨 선택을 잃지 않는다.
    current = request.POST.get("meeting.stt_model", effective("meeting.stt_model", org=org))
    if current and current not in {m["id"] for m in models}:
        models.insert(0, {"id": current, "status": "", "label": "", "name": current, "fits": True})
    ctx.update(
        org=org,
        current=current,
        options=models,
        models_count=sum(1 for m in models if m["status"]),
        polling=not error and any(m["status"] == "downloading" for m in models),
    )
    return render(request, "orgs/_stt_test.html", ctx)


@require_POST
@login_required
def org_stt_test(request, org_id):
    """[연결 시험]·화면 열 때 자동 조회·받는 중 폴링."""
    org = org_or_404(request.user, org_id)
    if not can_admin(request.user, org):
        return HttpResponseForbidden()
    return _stt_models(request, org)


@require_POST
@login_required
def org_stt_apply(request, org_id):
    """[적용] POST /v1/models/{id}로 모델 받기를 시작하고 stt_model을 그 값으로 저장한다."""
    org = org_or_404(request.user, org_id)
    if not can_admin(request.user, org):
        return HttpResponseForbidden()
    model = request.POST.get("meeting.stt_model", "").strip()
    error, code = "", None
    if model:
        path = "/v1/models/" + urllib.parse.quote(model, safe="")
        _, error, code = _stt_call(org, _stt_url(request, org), path, "POST")
        if code in (404, 405):  # 받기를 지원하지 않는 서버 — 저장만 한다.
            error = ""
    if not error:
        try:
            org = osv.set_org_settings(
                org, {"meeting.stt_model": model}, request.user, only=("meeting.stt_model",)
            )
        except ServiceError as e:
            error = " ".join(e.errors.values())
    return _stt_models(request, org, {"error": error, "applied": not error})
