"""AI 자동완성 설정·운영 화면(IMPL-PLAN-12 §7.5): 설정 AI 탭, 조직 AI 시험, 운영 콘솔 허용 호스트.

서버에서 AI 주소로 나가는 호출은 모두 assist.net 관문을 지난다(§11.1) — _stt_call·validate_stt_url은 쓰지 않는다.
화면 문구는 임시다(COPY:키, 최종 문구는 Sol).
"""

import ipaddress
import re

from django.conf import settings
from django.contrib import messages
from django.contrib.auth.decorators import login_required
from django.db import IntegrityError
from django.db.models import Max
from django.http import HttpResponse, HttpResponseForbidden
from django.shortcuts import get_object_or_404, redirect, render
from django.urls import reverse
from django.utils import timezone
from django.views.decorators.http import require_POST

from assist import codex_login, net, oauth
from assist.models import CODEX_URL, AiSource, AllowedHost
from common.errors import ServiceError
from github.crypto import encrypt
from notes import transcription as tx
from notes.models import SttServer
from ops import services as ops_services
from ops.access import ops_required
from orgs.settings import effective, secret_value

from .common import can_admin, dialog, org_or_404

_ENC = "enc:"

# 오류 코드(assist.models.ERROR_CODES) → 화면 문구. 응답 본문 일부는 내지 않는다(§11.4).
ERROR_TEXT = {
    "connect_failed": "AI 서버에 연결하지 못했습니다. 서버 주소와 연결 상태를 확인해 주세요.",  # COPY:assist_err_connect_failed
    "timeout": "AI 서버가 제한 시간 안에 응답하지 않았습니다. 잠시 후 다시 시도해 주세요.",  # COPY:assist_err_timeout
    "http_4xx": "AI 서버가 요청을 거부했습니다. 서버 주소·모델·키와 서버의 이용 조건을 확인해 주세요.",  # COPY:assist_err_http_4xx
    "http_5xx": "AI 서버에 오류가 발생했습니다. 잠시 후 다시 시도해 주세요.",  # COPY:assist_err_http_5xx
    "auth_failed": "AI 서버에서 키를 인증하지 못했습니다. 키의 유효 기간과 사용 권한을 확인해 주세요.",  # COPY:assist_err_auth_failed
    "model_not_found": "AI 서버에서 지정한 모델을 찾지 못했습니다. 모델 이름을 확인해 주세요.",  # COPY:assist_err_model_not_found
    "bad_output": "AI 응답이 필요한 형식과 맞지 않습니다. 다시 시도하고, 계속되면 서버와 모델의 OpenAI 호환 여부를 확인해 주세요.",  # COPY:assist_err_bad_output
    "too_large": "AI 응답이 허용 크기를 넘었습니다. 요청 범위를 줄이거나 다른 모델로 다시 시도해 주세요.",  # COPY:assist_err_too_large
    "blocked_address": "보안 제한으로 AI 서버에 연결하지 못했습니다. 개인 AI는 주소와 내 PC 연결을 확인하고, 조직 AI는 관리자에게 공개 HTTPS 주소 또는 허용 호스트 설정 확인을 요청해 주세요.",  # COPY:assist_err_blocked_address
    "pc_offline": "요청을 보낼 내 PC에 연결할 수 없습니다. PC에서 내 PC 연결을 실행한 뒤 다시 시도해 주세요.",  # COPY:assist_err_pc_offline
    "pc_unlinked": "개인 AI에 연결된 내 PC가 없습니다. 설정 > AI에서 [PC 다시 고르기]를 눌러 연결할 PC를 선택해 주세요.",  # COPY:assist_err_pc_unlinked
    "pc_error": "내 PC에서 AI 서버에 요청하지 못했습니다. PC의 연결 상태와 AI 서버 주소·모델·키를 확인해 주세요.",  # COPY:assist_err_pc_error
    "codex_missing": "선택한 내 PC에 Codex가 설치되어 있지 않습니다. 해당 PC에 Codex를 설치하고 로그인한 뒤 다시 시도해 주세요.",  # COPY:assist_err_codex_missing
    "codex_link_update": "선택한 내 PC의 udally-link가 Codex를 지원하지 않는 버전입니다. 해당 PC의 udally-link를 최신 버전으로 업데이트한 뒤 다시 시도해 주세요.",  # COPY:assist_err_codex_link_update
    "codex_auth": "선택한 내 PC의 Codex에 로그인되어 있지 않습니다. 해당 PC에서 `codex login`으로 로그인한 뒤 다시 시도해 주세요.",  # COPY:assist_err_codex_auth
    "payment_required": "해당 AI 서비스의 크레딧 충전이나 결제가 필요합니다. AI 서비스의 결제 설정을 확인하거나 다른 AI를 사용해 주세요.",  # COPY:assist_err_payment_required (임시)
    "reasoning_budget": "추론 모델이 답을 끝내지 못했습니다. 다시 시도하거나, 개인 AI 설정에서 추론이 짧은 다른 모델을 골라 주세요.",  # COPY:assist_err_reasoning_budget (임시)
    "rate": "오늘의 조직 AI 사용 한도에 도달했습니다. 내일 다시 시도하거나 설정 > AI에서 개인 AI를 등록해 주세요.",  # COPY:assist_err_rate
    # 작업(자동완성) 쪽 코드. no_source는 "쓸 AI가 없음"과 "대상을 더 볼 수 없음" 둘 다다(assist.worker).
    "no_source": "사용 가능한 AI가 없거나 대상에 접근할 수 없습니다. 대상 접근 권한과 설정 > AI의 사용 여부·사용 순서를 확인하고, 조직 AI는 관리자에게 등록·권한·하루 한도 확인을 요청해 주세요.",  # COPY:assist_err_no_source
    "no_worker": "AI 작업을 처리할 수 없어 요청이 중단되었습니다. 잠시 후 다시 요청하고, 계속되면 서비스 운영자에게 문의해 주세요.",  # COPY:assist_err_no_worker
    "org_disabled": "이 조직의 AI 자동완성이 꺼져 있습니다. 사용이 필요하면 조직 관리자에게 문의해 주세요.",  # COPY:assist_err_org_disabled
    "cancelled": "AI 작업을 취소했습니다.",  # COPY:assist_cancelled
}
ERROR_FALLBACK = "AI 서버에 요청하지 못했습니다. 연결 상태와 AI 설정을 확인한 뒤 다시 시도해 주세요."  # COPY:assist_err_unknown


def error_text(code: str) -> str:
    return ERROR_TEXT.get(code, ERROR_FALLBACK)


# ---------------------------------------------------------------- 설정 AI 탭(사용자)


def _sources(user):
    """내 AI 목록. 조직 AI 자리 행이 없으면 맨 뒤에 만든다 — 순서 바꾸기·끄기의 대상이 되게(§3.1)."""
    if not AiSource.objects.filter(user=user, kind="org").exists():
        last = AiSource.objects.filter(user=user).aggregate(m=Max("position"))["m"]
        try:
            AiSource.objects.create(user=user, kind="org", position=0 if last is None else last + 1)
        except IntegrityError:  # 동시 요청이 먼저 만들었다
            pass
    rows = list(AiSource.objects.filter(user=user).select_related("server"))
    for r in rows:
        r.error_label = error_text(r.last_error)
        r.unusable = _unusable(r)
    return rows


def _unusable(r) -> bool:
    """켜 두었지만 지금 실제로 쓸 수 없는 개인 AI(행 상태를 "사용 불가"로). 이유 문구는 행 아래에 따로 보인다."""
    from assist import copilot

    if r.kind != "personal":
        return False
    if r.is_copilot:
        return not copilot.enabled()
    if r.route == "pc" and (r.server is None or not tx.online(r.server)):
        return True
    if r.is_codex:
        dev = codex_login.device(r.server)
        return (
            not settings.ASSIST_CODEX_ENABLED
            or bool(dev.get("docker"))
            or dev.get("login") is False
        )
    return False


def _page(request, status=200, **extra):
    ctx = {
        "settings_tab": "ai",
        "sources": _sources(request.user),
        "servers": _servers(request),
        "personal_max": AiSource.MAX_PERSONAL,
        "codex_on": settings.ASSIST_CODEX_ENABLED,
        "oauth_providers": oauth.available(),
        **extra,
    }
    ctx["personal_count"] = sum(s.kind == "personal" for s in ctx["sources"])
    ctx["has_copilot"] = any(s.is_copilot for s in ctx["sources"])  # 이미 연결했으면 [연결] 숨김
    return render(request, "settings/ai.html", ctx, status=status)


def _mine(request, source_id) -> AiSource:
    return get_object_or_404(
        AiSource.objects.select_related("server"), pk=source_id, user=request.user
    )


def _save_personal(user, src: AiSource, post) -> None:
    """개인 AI 저장. 주소 판정(net.classify)과 PC 소유자 불변식 1(§5.3)을 여기 한 곳에서 지킨다."""
    errors = {}
    name = post.get("name", "").strip()
    codex = post.get("backend") == "codex" and settings.ASSIST_CODEX_ENABLED
    url = CODEX_URL if codex else post.get("base_url", "").strip().rstrip("/")
    model = post.get("model", "").strip()
    if not name or len(name) > 50:
        errors["name"] = (
            "이름이 없거나 50자를 넘었습니다. 이름을 50자 이내로 입력해 주세요."  # COPY:assist_src_name_invalid
        )
    if not url or len(url) > 300:
        errors["base_url"] = (
            "AI 서버 주소가 없거나 300자를 넘었습니다. 주소를 300자 이내로 입력해 주세요."  # COPY:assist_src_url_required
        )
    if len(model) > 200:
        errors["model"] = (
            "모델 이름이 200자를 넘었습니다. 모델 이름을 200자 이내로 입력해 주세요."  # COPY:assist_src_model_long
        )
    if errors:
        raise ServiceError(errors)
    try:
        route = "pc" if codex else net.classify(url)
    except net.NetError as e:
        raise ServiceError({"base_url": error_text(e.code)}) from None
    server = None
    if codex:
        server = SttServer.objects.filter(pk=_int(post.get("server")), owner=user).first()
        if server is None:
            raise ServiceError(
                {
                    "server": "Codex를 사용할 내 PC를 선택해 주세요. 해당 PC에 Codex가 설치되어 있고 로그인되어 있어야 합니다."  # COPY:assist_src_codex_pc_required
                }
            )
        src.api_key = ""  # 구독 토큰은 PC 밖으로 나오지 않는다 — 키를 받지 않는다
    elif route == "pc":
        # 폼에는 내 PC만 나오지만 POST 위조 대비로 주인을 다시 본다(불변식 1).
        server = SttServer.objects.filter(pk=_int(post.get("server")), owner=user).first()
        if server is None:
            raise ServiceError(
                {
                    "server": "PC 내부 또는 사설망 주소는 내 PC를 거쳐 요청해야 합니다. 연결할 내 PC를 선택해 주세요."  # COPY:assist_src_pc_required
                }
            )
    key = "" if codex else post.get("api_key", "").strip()
    if key:
        try:
            src.api_key = _ENC + encrypt(key)
        except ValueError:
            raise ServiceError(
                {
                    "api_key": "서버의 암호화 설정이 없어 키를 저장할 수 없습니다. 서비스 운영자에게 문의해 주세요."  # COPY:assist_src_key_no_crypto
                }
            ) from None
    elif post.get("clear_key") == "on" or (url != src.base_url and oauth.is_hf_blob(src.api_key)):
        src.api_key = ""  # HF 토큰(갱신 토큰 포함)을 다른 주소로 보내지 않는다
    if url != src.base_url or route != src.route:
        src.last_error, src.last_ok_at = "", None
    src.name, src.base_url, src.model, src.route, src.server = name, url, model, route, server
    src.save()


def _int(v):
    try:
        return int(v)
    except (TypeError, ValueError):
        return None


@login_required
def ai_index(request):
    return _page(request)


@require_POST
@login_required
def ai_add(request):
    user = request.user
    if AiSource.objects.filter(user=user, kind="personal").count() >= AiSource.MAX_PERSONAL:
        messages.error(
            request,
            f"개인 AI 등록 한도인 {AiSource.MAX_PERSONAL}개에 도달했습니다. 새로 등록하려면 사용하지 않는 개인 AI를 삭제해 주세요.",  # COPY:assist_src_limit
        )
        return redirect("settings_ai")
    last = AiSource.objects.filter(user=user).aggregate(m=Max("position"))["m"]
    src = AiSource(user=user, kind="personal", position=0 if last is None else last + 1)
    try:
        _save_personal(user, src, request.POST)
    except ServiceError as e:
        return _page(request, status=400, add_errors=e.errors, add_values=request.POST)
    messages.success(request, f"개인 AI ‘{src.name}’을 등록했습니다.")  # COPY:assist_src_added
    return redirect("settings_ai")


@login_required
def ai_row(request, source_id: int):
    """GET 행 조각. POST action=toggle 이면 켜기·끄기, 그 밖은 개인 AI 고치기."""
    src = _mine(request, source_id)
    if request.method != "POST":
        src.error_label = error_text(src.last_error)
        src.unusable = _unusable(src)
        return render(
            request,
            "settings/_ai_source.html",
            {"s": src, "servers": _servers(request), "codex_on": settings.ASSIST_CODEX_ENABLED},
        )
    if request.POST.get("action") == "toggle":
        src.enabled = not src.enabled
        src.save(update_fields=["enabled"])
        return redirect("settings_ai")
    if src.kind != "personal":
        return HttpResponseForbidden()
    try:
        _save_personal(request.user, src, request.POST)
    except ServiceError as e:
        return _page(request, status=400, edit_id=src.pk, edit_errors=e.errors)
    messages.success(request, f"개인 AI ‘{src.name}’ 설정을 저장했습니다.")  # COPY:assist_src_saved
    return redirect("settings_ai")


CODEX_LOGIN_ERRORS = {
    "codex_missing": "선택한 내 PC에서 Codex를 찾지 못했습니다. 해당 PC에 Codex를 설치한 뒤 다시 시도해 주세요.",  # COPY:codex_login_err_missing
    "codex_docker": "Docker로 설치한 udally-link에서는 Codex를 사용할 수 없습니다. 해당 PC에 udally-link를 uv로 설치해 주세요.",  # COPY:codex_login_err_docker
    "login_failed": "Codex 로그인 또는 로그아웃을 완료하지 못했습니다. 다시 시도해 주세요.",  # COPY:codex_login_err_failed
    "bad_login_url": "내 PC가 허용되지 않은 인증 주소를 보내 로그인을 중단했습니다. 해당 PC의 udally-link와 Codex를 업데이트한 뒤 다시 시도해 주세요.",  # COPY:codex_login_err_url
    "pc_error": "내 PC에서 Codex 로그인 또는 로그아웃을 처리하지 못했습니다. 해당 PC의 연결 상태를 확인한 뒤 다시 시도해 주세요.",  # COPY:codex_login_err_pc
}


def _codex_ctx(src, error=""):
    server = src.server
    row = codex_login.current(server)
    ctx = {
        "s": src,
        "server": server,
        "row": row,
        "dev": codex_login.device(server),
        "online": tx.online(server),
        "error": error,
    }
    if row and row.state in codex_login.OPEN:
        ctx["polling"] = True
        ctx["minutes"] = max(1, round((row.expires_at - timezone.now()).total_seconds() / 60))
    if row and row.state == "failed":
        ctx["error"] = ctx["error"] or CODEX_LOGIN_ERRORS.get(
            row.error, CODEX_LOGIN_ERRORS["pc_error"]
        )
    return ctx


@login_required
def ai_codex(request, source_id: int):
    """Codex 행의 로그인 상태 조각. POST action=login|logout은 그 PC에 명령을 건다(PC 주인만)."""
    src = _mine(request, source_id)
    if not codex_login.enabled():
        return HttpResponse("")  # 스위치가 꺼지면 상태·버튼을 그리지 않고 명령도 받지 않는다
    if not src.is_codex or src.server is None or src.server.owner_id != request.user.pk:
        return HttpResponseForbidden()
    error = ""
    if request.method == "POST":
        try:
            codex_login.start(request.user, src.server, request.POST.get("action", ""))
        except ServiceError as e:
            error = next(iter(e.errors.values()))
    return render(request, "settings/_codex_login.html", _codex_ctx(src, error))


def _servers(request):
    return list(SttServer.objects.filter(owner=request.user))


@require_POST
@login_required
def ai_move(request, source_id: int, direction: str):
    """사용 순서 한 칸 위·아래. 순서를 0부터 다시 매긴다."""
    src = _mine(request, source_id)
    rows = _sources(request.user)
    i = next(n for n, r in enumerate(rows) if r.pk == src.pk)
    j = i - 1 if direction == "up" else i + 1 if direction == "down" else i
    if 0 <= j < len(rows):
        rows[i], rows[j] = rows[j], rows[i]
    for n, r in enumerate(rows):
        r.position = n
    AiSource.objects.bulk_update(rows, ["position"])
    return redirect("settings_ai")


@require_POST
@login_required
def ai_delete(request, source_id: int):
    src = _mine(request, source_id)
    if src.kind != "personal":  # 조직 AI 자리는 지우지 않고 끈다
        return HttpResponseForbidden()
    src.delete()
    messages.success(request, f"개인 AI ‘{src.name}’을 삭제했습니다.")  # COPY:assist_src_deleted
    if note := oauth.REVOKE_NOTE.get(src.base_url):
        messages.info(request, note)
    return redirect("settings_ai")


def _source_result(request, source_id: int, *, fill: bool):
    """[연결 시험]·[모델 불러오기] 공용. direct 개인 AI만, 관문 5초. 결과(코드)를 행에 남긴다."""
    src = _mine(request, source_id)
    # 화면이 버튼을 그리지 않는다(PC 경로는 v1에서 시험 없음, §6.2)
    if src.kind != "personal" or src.route != "direct":
        return HttpResponseForbidden()
    try:
        key = oauth.source_key(src)  # HF OAuth면 만료 전에 갱신
        models = net.list_models(src.base_url, api_key=key, org=False, timeout_s=5)
    except net.NetError as e:
        src.last_error = e.code
        src.save(update_fields=["last_error"])
        return render(request, "settings/_ai_result.html", {"error": error_text(e.code)})
    src.last_error, src.last_ok_at = "", timezone.now()
    src.save(update_fields=["last_error", "last_ok_at"])
    ctx = {"count": len(models)}
    if fill:
        ctx.update(models=models[:200], list_id=f"ai-models-{src.pk}")
    return render(request, "settings/_ai_result.html", ctx)


@require_POST
@login_required
def ai_test(request, source_id: int):
    return _source_result(request, source_id, fill=False)


@require_POST
@login_required
def ai_models(request, source_id: int):
    return _source_result(request, source_id, fill=True)


# ---------------------------------------------------------------- 조직 AI 시험(조직 관리자)


def _org_models(request, org_id: int, *, fill: bool):
    org = org_or_404(request.user, org_id)
    if not can_admin(request.user, org):
        return HttpResponseForbidden()
    # 저장 전 폼 값(hx-include)으로 시험한다. 키는 새로 입력했으면 그것, 아니면 저장된 키.
    url = (request.POST.get("assist.org_url") or effective("assist.org_url", org=org) or "").strip()
    key = request.POST.get("assist.org_api_key", "").strip() or secret_value(
        "assist.org_api_key", org
    )
    model = request.POST.get("assist.org_model", effective("assist.org_model", org=org) or "")
    ctx = {"org": org, "fill": fill, "model": model}
    if not url:
        ctx["error"] = (
            "조직 AI 주소가 없습니다. 조직 AI 서버 주소를 입력해 주세요."  # COPY:assist_org_url_required
        )
    elif problem := net.check_org_url(url):
        ctx["error"] = problem
    else:
        try:
            models = net.list_models(url.rstrip("/"), api_key=key, org=True, timeout_s=5)
            ctx.update(count=len(models), models=models[:200])
        except net.NetError as e:
            ctx["error"] = error_text(e.code)
    return render(request, "orgs/_assist_result.html", ctx)


@require_POST
@login_required
def org_assist_test(request, org_id: int):
    return _org_models(request, org_id, fill=False)


@require_POST
@login_required
def org_assist_models(request, org_id: int):
    return _org_models(request, org_id, fill=True)


# ---------------------------------------------------------------- 운영 콘솔 허용 호스트(staff)

_HOSTNAME = re.compile(
    r"^(?=.{1,253}$)[a-z0-9]([a-z0-9-]{0,61}[a-z0-9])?(\.[a-z0-9]([a-z0-9-]{0,61}[a-z0-9])?)*$"
)


def normalize_host(raw: str) -> str:
    """호스트 이름 또는 IP 리터럴(소문자, 정확 일치용). 형식이 아니면 ServiceError. 와일드카드·포트·경로 없음."""
    host = (raw or "").strip().lower()
    if host.startswith("[") and host.endswith("]"):
        host = host[1:-1]
    try:
        return str(ipaddress.ip_address(host))
    except ValueError:
        pass
    if not _HOSTNAME.match(host):
        raise ServiceError(
            {
                "host": "허용 호스트 형식이 올바르지 않습니다. 호스트 이름 또는 IP 주소만 입력하고, http://·https://·포트·경로·*는 제외해 주세요."  # COPY:ops_assist_host_invalid
            }
        )
    return host


@ops_required
def ops_assist(request):
    """허용 호스트 목록·추가(§3.3). 조직 AI만 이 목록의 사설 주소를 쓸 수 있다."""
    if request.method == "POST":
        try:
            host = normalize_host(request.POST.get("host"))
            reason = ops_services._reason(request.POST.get("reason"))
            if AllowedHost.objects.filter(host=host).exists():
                raise ServiceError(
                    {"host": "이미 등록된 허용 호스트입니다. 목록에서 해당 호스트를 확인해 주세요."}
                )  # COPY:ops_assist_host_dup
            row = AllowedHost.objects.create(host=host, added_by=request.user)
            ops_services.audit(request, "assist.host_add", target=row, reason=reason)
        except ServiceError as e:
            for msg in e.errors.values():
                messages.error(request, msg)
        else:
            messages.success(
                request, f"허용 호스트 {host}를 추가했습니다."
            )  # COPY:ops_assist_host_added
        return redirect("ops_assist")
    return render(
        request,
        "ops/assist.html",
        {"ops_nav": "assist", "hosts": AllowedHost.objects.select_related("added_by")},
    )


@ops_required
def ops_assist_delete(request, host_id: int):
    """GET은 확인 대화상자(사유), POST는 삭제."""
    row = get_object_or_404(AllowedHost, pk=host_id)
    if request.method != "POST":
        return dialog(
            request,
            "ops/_confirm.html",
            {
                "action_url": reverse("ops_assist_delete", args=[row.pk]),
                "title": f"허용 호스트 삭제 · {row.host}",  # COPY:ops_assist_delete_title
                "summary": "이 호스트를 사용하는 조직 AI는 다음 요청부터 차단됩니다.",  # COPY:ops_assist_delete_summary
                "danger": True,
                "button": "허용 호스트 삭제",
            },
        )
    try:
        reason = ops_services._reason(request.POST.get("reason"))
    except ServiceError as e:
        for msg in e.errors.values():
            messages.error(request, msg)
        return redirect("ops_assist")
    ops_services.audit(request, "assist.host_remove", target=row, reason=reason)
    host = row.host
    row.delete()
    messages.success(request, f"허용 호스트 {host}를 삭제했습니다.")  # COPY:ops_assist_host_removed
    return redirect("ops_assist")
