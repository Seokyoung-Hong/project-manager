"""내 PC를 전사 서버로 연결하기(IMPL-PLAN-11-local-stt-link §6.2·§9.2): /link · /settings/stt · /stt/*.

화면 문구는 임시다(docs/drafts/local-stt-link-copy.md, 최종 문구는 Sol).
"""

from django.conf import settings
from django.contrib import messages
from django.contrib.auth.decorators import login_required
from django.http import Http404, HttpResponseRedirect
from django.shortcuts import get_object_or_404, redirect, render
from django.utils import timezone
from django.views.decorators.http import require_POST

from accounts.auth import LockedOut, check_lock, record_failure
from common.errors import ServiceError
from notes import stt_link
from notes import transcription as tx
from notes.models import SttServer

SCRIPTS = {"install.ps1", "install.sh", "uninstall.ps1", "uninstall.sh"}

LINK_NOT_FOUND = (
    "코드를 찾을 수 없습니다. PC 화면에 보이는 코드를 다시 확인해 주세요."  # COPY:link_not_found
)
LINK_TOO_MANY = (
    "코드를 여러 번 잘못 입력했습니다. {minutes}분 뒤 다시 시도해 주세요."  # COPY:link_too_many
)
LINK_EXPIRED = "코드가 만료되었습니다. PC에서 연결 명령을 다시 실행해 주세요."  # COPY:link_expired


def _device_lines(device) -> list[tuple[str, str]]:
    """PC가 준 장치 정보(형식 자유)를 화면 줄로. 장치 종류를 특정 제조사로 해석하지 않는다."""
    out = []
    for k, v in (device or {}).items() if isinstance(device, dict) else []:
        if isinstance(v, list):
            v = ", ".join(
                " ".join(str(x) for x in i.values()) if isinstance(i, dict) else str(i) for i in v
            )
        elif isinstance(v, dict):
            v = ", ".join(f"{a} {b}" for a, b in v.items())
        out.append((str(k)[:40], str(v)[:200]))
    return out[:12]


@login_required
def link(request):
    """기기 인증 화면. 코드는 늘 빈 칸에서 시작한다 — `?code=`로 채우지 않는다(피싱 대비, §3)."""
    ctx = {"step": "enter"}
    if request.method != "POST":
        return render(request, "settings/stt_link.html", ctx)
    key = str(request.user.pk)
    try:
        check_lock("stt_link", key)
    except LockedOut as e:
        ctx["error"] = LINK_TOO_MANY.format(minutes=e.retry_after_minutes)
        return render(request, "settings/stt_link.html", ctx, status=429)
    step = request.POST.get("step", "lookup")
    code = stt_link.find_code(request.POST.get("code", ""))
    if code is None:
        record_failure("stt_link", key)
        if step == "lookup":
            ctx["error"] = LINK_NOT_FOUND
        else:
            ctx["step"], ctx["result"] = "result", "expired"
        return render(request, "settings/stt_link.html", ctx, status=400)
    # 맞힌 뒤에도 실패 횟수를 지우지 않는다 — 자기 코드로 횟수를 되돌리며 남의 코드를 맞혀 보지 못하게
    if step == "approve":
        try:
            stt_link.approve(code, request.user, request.POST.get("name", ""))
        except ServiceError as e:
            ctx.update(step="confirm", code=code, device=_device_lines(code.device))
            ctx["error"] = " ".join(e.errors.values())
            return render(request, "settings/stt_link.html", ctx, status=400)
        ctx.update(step="result", result="done", name=code.name)
    elif step == "deny":
        stt_link.deny(code)
        ctx.update(step="result", result="denied")
    else:
        ctx.update(step="confirm", code=code, device=_device_lines(code.device))
    return render(request, "settings/stt_link.html", ctx)


def _server_ctx(server) -> dict:
    models = tx.parse_models(server.models)
    downloading = any(m["status"] == "downloading" for m in models)
    pulling = server.pull_model and not tx.ready_model(server, server.pull_model)
    return {
        "server": server,
        "on": tx.online(server),
        "models": models,
        "ready_count": sum(1 for m in models if m["status"] == "ready" and m["fits"]),
        "default_name": next(
            (m["name"] for m in models if m["id"] == server.default_model), server.default_model
        ),
        "device": _device_lines(server.device),
        "polling": bool(pulling or downloading),
        "pull_error": next(
            (m["error"] for m in models if m["id"] == server.pull_model and m["error"]), ""
        ),
    }


@login_required
def settings_stt(request):
    servers = list(SttServer.objects.filter(owner=request.user))
    base = settings.SITE_URL
    return render(
        request,
        "settings/stt.html",
        {
            "settings_tab": "stt",
            "rows": [_server_ctx(s) for s in servers],
            "install_ps1": f"irm {base}/stt/install.ps1 | iex",
            "install_sh": f"curl -fsSL {base}/stt/install.sh | sh",
            "uninstall_ps1": f"irm {base}/stt/uninstall.ps1 | iex",
            "uninstall_sh": f"curl -fsSL {base}/stt/uninstall.sh | sh",
            "link_url": base + stt_link.LINK_PATH,
            "now": timezone.now(),
        },
    )


def _mine(request, server_id):
    return get_object_or_404(SttServer, pk=server_id, owner=request.user)


@login_required
def stt_server_row(request, server_id):
    """서버 행만(받는 중 3초 폴링)."""
    return render(request, "settings/_stt_server.html", _server_ctx(_mine(request, server_id)))


@require_POST
@login_required
def stt_pull(request, server_id):
    """[모델 적용] — 다음 heartbeat로 받기 명령을 보낸다. 다 받으면 자동 전사에 이 모델을 쓴다."""
    server = _mine(request, server_id)
    ctx = {}
    try:
        stt_link.set_pull(server, request.POST.get("model", "").strip())
        ctx["applied"] = True
    except ServiceError as e:
        ctx["error"] = " ".join(e.errors.values())
    return render(request, "settings/_stt_server.html", {**_server_ctx(server), **ctx})


@require_POST
@login_required
def stt_unlink(request, server_id):
    server = _mine(request, server_id)
    name = server.name
    stt_link.unlink(server)
    messages.success(request, f"'{name}' 연결을 끊었습니다.")  # COPY:unlink_done
    return redirect("settings_stt")


def stt_script(request, name):
    """한 줄 설치 스크립트 → udally-stt 저장소 원본으로 302(§10.1). 로그인 없이 연다."""
    if name not in SCRIPTS:
        raise Http404
    return HttpResponseRedirect(f"{settings.STT_SCRIPT_BASE}/scripts/{name}")
