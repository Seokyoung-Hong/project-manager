"""조직 전사 메뉴(IMPL-PLAN-10-transcribe-menu, 시안 B): 전사 작업 목록 + 패널, 전사 서버 보기.

전사문(녹음을 글로 옮긴 원문)만 다룬다. 회의록 본문은 바꾸지 않는다.
구성원 누구나 연다(IMPL-PLAN-11-local-stt-link §6.2) — 작업은 그 사람이 볼 수 있는 회의록의 녹음만,
"전사 서버" 보기(조직 서버 주소·키·정책)는 관리자만. 지시·취소 권한은 notes.transcription(§8).
"""

from datetime import timedelta

from django.contrib import messages
from django.contrib.auth.decorators import login_required
from django.db.models import Q
from django.http import Http404
from django.shortcuts import get_object_or_404, redirect, render
from django.utils import timezone
from django.views.decorators.http import require_POST

from common.errors import ServiceError
from notes import transcription as tx
from notes.models import SttServer, TranscriptionJob, VoiceRecording
from notes.services import GLOSSARY_MAX, glossary_terms, visible_notes
from orgs import services as osv
from orgs.names import display_for
from orgs.settings import SPECS, STT_KEYS, display, effective, secret_value

from .common import not_admin, org_or_404, settings_tab_url
from .notes import audio_ctx
from .orgs import _settings_from_post, stt_models

RECENT = timedelta(days=7)
POLICY_KEYS = ("meeting.member_pc", "meeting.transcribe_level")


def _admin_org(request, org_id):
    org = org_or_404(request.user, org_id)
    return org, not_admin(request, org, "전사 서버")


def _job_row(job, eta, user=None):
    left, wait = eta.get(job.pk, (None, 0.0))
    pct = round(100 * min(job.done_ms, job.audio_ms) / job.audio_ms) if job.audio_ms else 0
    runner = ""
    if job.engine == "pc":
        server = job.server
        runner = (
            f"{display_for(server.owner, job.recording.note.org_id)}님의 PC({server.name})"  # COPY:job_runner_pc
            if server
            else "연결이 끊긴 PC"  # COPY:job_runner_pc_gone
        )
    return {
        "job": job,
        "label": job.stats.get("label") or tx.model_label(job.engine, job.model),
        "runner": runner,
        "error_label": tx.ERROR_LABELS.get(job.error, ""),
        "waiting_pc": job.engine == "pc" and job.status == "queued" and not tx.online(job.server),
        "eta": tx.eta_text(left),
        "wait": tx.eta_text(wait) if job.status == "queued" and wait else "",
        "pct": pct,
        "done_min": round(min(job.done_ms, job.audio_ms) / 60000),
        "audio_min": round(job.audio_ms / 60000),
        "stale": tx.is_stale(job),
        "can_cancel": bool(user) and tx.can_cancel(job, user),
    }


def _jobs_ctx(org, user):
    since = timezone.now() - RECENT
    jobs = list(
        TranscriptionJob.objects.filter(recording__note__org=org)
        .filter(recording__note__in=visible_notes(user).filter(org=org).values("pk"))
        .filter(Q(status__in=TranscriptionJob.ACTIVE) | Q(created_at__gte=since))
        .select_related("recording__note", "server__owner")
        .order_by("-created_at")[:50]
    )
    eta = tx.queue_eta([j for j in jobs if j.status in TranscriptionJob.ACTIVE])
    rows = [_job_row(j, eta) for j in jobs]
    groups = [
        ("진행 중", [r for r in rows if r["job"].status in TranscriptionJob.RUNNING]),
        ("대기", [r for r in rows if r["job"].status == "queued"]),
        ("끝남 · 최근 7일", [r for r in rows if r["job"].status not in TranscriptionJob.ACTIVE]),
    ]
    return {
        "org": org,
        "groups": [(label, rs) for label, rs in groups if rs],
        "has_jobs": bool(rows),
        "polling": any(j.status in TranscriptionJob.ACTIVE for j in jobs),
    }


def _server_rows(org, keys):
    return [
        {
            "spec": SPECS[k],
            "value": effective(k, org=org),
            "display": display(k, effective(k, org=org)),
            "can_edit": True,
            "show_override": False,
        }
        for k in keys
    ]


@login_required
def org_transcribe(request, org_id):
    org = org_or_404(request.user, org_id)
    admin = osv.is_admin(request.user, org)
    if admin and request.GET.get("view") == "server":  # 옛 주소 -> 설정 / 회의·전사
        return redirect(settings_tab_url(org, "meeting", "stt"))
    ctx = {"org": org, "tab": "transcribe", "is_admin": admin, **_jobs_ctx(org, request.user)}
    return render(request, "orgs/transcribe.html", ctx)


def stt_ctx(request, org) -> dict:
    """설정 → 회의·전사 탭 전사 섹션의 맥락(IMPL-PLAN-14 §10.1). 호출자가 관리자를 이미 확인했다."""
    return {
        "org": org,
        "policy_rows": _server_rows(org, POLICY_KEYS),
        "rows": _server_rows(org, [k for k in STT_KEYS if k not in POLICY_KEYS]),
        "pc_online": SttServer.objects.filter(
            owner__org_memberships__org=org, last_seen_at__gt=timezone.now() - tx.ONLINE_FOR
        )
        .distinct()
        .count(),
    }


@require_POST
@login_required
def org_transcribe_server(request, org_id):
    """전사 서버 저장. 다른 조직 설정 값은 그대로 둔다."""
    org, deny = _admin_org(request, org_id)
    if deny:
        return deny
    try:
        # 전사 키만 부분 저장 — 그 사이 다른 탭이 저장한 값·숨김 키를 되돌리지 않는다(IMPL-PLAN-14 §9.1)
        org = osv.set_org_settings(
            org,
            _settings_from_post(request.POST, [SPECS[k] for k in STT_KEYS]),
            request.user,
            only=STT_KEYS,
        )
        messages.success(request, "전사 서버 설정을 저장했습니다.")
    except ServiceError as e:
        messages.error(request, " ".join(e.errors.values()))
    return redirect(settings_tab_url(org, "meeting", "stt"))


@login_required
def org_transcribe_jobs(request, org_id):
    org = org_or_404(request.user, org_id)
    return render(request, "orgs/_transcribe_jobs.html", _jobs_ctx(org, request.user))


def _recording(org, rec_id, user):
    """이 사람이 볼 수 있는 회의록의 녹음만. 아니면 404(존재를 숨긴다)."""
    return get_object_or_404(
        VoiceRecording.objects.select_related("note__org"),
        pk=rec_id,
        note__org=org,
        note__in=visible_notes(user).values("pk"),
    )


def options(org, rec, user):
    """전사 선택지(§9.1): 내 PC의 준비된 모델(꺼진 PC는 고를 수 없는 한 줄) + 조직 수단.

    → (선택지 [{value, label, eta, disabled}], 오류 문구, 조직 수단을 못 쓰는 이유).
    """
    a, n = tx.speech_ms(rec.segments)
    out, error = [], ""
    servers = list(SttServer.objects.filter(owner=user))
    if servers and not tx.member_pc(org):
        out.append({"value": "", "label": tx.PC_DISABLED_BY_ORG, "eta": "", "disabled": True})
    elif servers:
        many = len(servers) > 1
        for s in servers:
            if not tx.online(s):
                out.append(
                    {
                        "value": "",
                        "label": f"{'내 PC(' + s.name + ')' if many else '내 PC'} · 연결되지 않음",  # COPY:pc_offline_option
                        "eta": "",
                        "disabled": True,
                    }
                )
                continue
            for m in tx.parse_models(s.models):
                if m["status"] != "ready" or not m["fits"]:
                    continue
                info = {**m["info"], "concurrency": m["info"].get("concurrency", s.concurrency)}
                rtf = tx.prior_rtf(org, "pc", m["id"], info)
                out.append(
                    {
                        "value": f"pc|{s.pk}|{m['id']}",
                        "label": tx.pc_label(s, m["id"], m["info"], many=many),
                        "eta": tx.eta_text(tx.estimate_s(a, n, rtf, tx.parallel("pc", info))),
                        "disabled": False,
                    }
                )
    org_reason = tx.org_block(rec, user)
    if org_reason:
        return out, error, org_reason
    url = effective("meeting.stt_url", org=org)
    if url:
        models, error, _ = stt_models(org, url)
        for m in models:
            if m["status"] != "ready" or not m["fits"]:
                continue
            info = m["info"]
            rtf = tx.prior_rtf(org, "local", m["id"], info)
            out.append(
                {
                    "value": f"local|{m['id']}",
                    "label": tx.model_label("local", m["id"], info),
                    "eta": tx.eta_text(tx.estimate_s(a, n, rtf, tx.parallel("local", info))),
                    "disabled": False,
                }
            )
    if secret_value("meeting.openai_api_key", org):
        rtf = tx.prior_rtf(org, "openai", tx.OPENAI_MODEL)
        out.append(
            {
                "value": f"openai|{tx.OPENAI_MODEL}",
                "label": tx.model_label("openai", tx.OPENAI_MODEL),
                "eta": tx.eta_text(tx.estimate_s(a, n, rtf, tx.parallel("openai"))),
                "disabled": False,
            }
        )
    if error:
        error = f"로컬 전사 서버 모델 목록을 불러오지 못했습니다. {error}"
    return out, error, ""


def parse_choice(org, user, choice: str) -> dict:
    """선택지 값 → request_retry/request_upload 인자. `pc|<server_id>|<model>` · `local|<model>` · `openai|<model>`."""
    engine, _, rest = (choice or "").partition("|")
    if engine == "pc":
        sid, _, model = rest.partition("|")
        server = SttServer.objects.filter(pk=sid if sid.isdecimal() else 0, owner=user).first()
        info = (tx.ready_model(server, model) or {}).get("info") if server else None
        return {"engine": "pc", "model": model, "server": server, "info": info}
    info = None
    if engine == "local":
        models, _, _ = stt_models(org, effective("meeting.stt_url", org=org))
        info = next((m["info"] for m in models if m["id"] == rest), None)
    return {"engine": engine, "model": rest, "server": None, "info": info}


def glossary_ctx(rec, user, posted=None) -> dict:
    """[전사 시작] 전에 미리 채우는 용어집. 요청자가 볼 수 있는 자료로만 만든다(viewer=요청자).

    posted: 오류로 다시 그릴 때 사람이 고친 값을 잃지 않게.
    """
    terms, dropped = glossary_terms(rec, viewer=user)
    return {
        "glossary": ", ".join(terms) if posted is None else posted,
        "glossary_dropped": dropped,
        "glossary_max": GLOSSARY_MAX,
    }


def posted_glossary(request):
    """폼에 용어집 칸이 있었으면 그 값(빈 값 = 용어집 없이), 없었으면 None(보낼 때 자동)."""
    return request.POST.get("glossary") if "glossary" in request.POST else None


def _panel(request, org, rec, *, error="", glossary=None):
    jobs = list(rec.jobs.select_related("server__owner"))
    active = [j for j in jobs if j.status in TranscriptionJob.ACTIVE]
    eta = tx.queue_eta(active)
    latest = active[0] if active else (jobs[0] if jobs else None)
    block = tx.retry_block(rec)
    opts, opts_error, org_reason = options(org, rec, request.user) if not block else ([], "", "")
    a, _ = tx.speech_ms(rec.segments)
    can_use = bool(jobs) and tx.can_use(jobs[0], request.user)
    return render(
        request,
        "orgs/_transcribe_panel.html",
        {
            "org": org,
            "rec": rec,
            "note": rec.note,
            "row": _job_row(latest, eta, request.user) if latest else None,
            "active_row": _job_row(active[0], eta, request.user) if active else None,
            "history": [
                {**_job_row(j, eta), "current": j.pk == rec.transcript_job_id} for j in jobs
            ],
            "can_use": can_use,
            "speech_min": round(a / 60000),
            "block": block,
            "options": opts,
            "can_pick": any(not o["disabled"] for o in opts),
            "options_error": opts_error,
            "org_reason": org_reason,
            "running": any(j.status in TranscriptionJob.RUNNING for j in active),
            "error": error,
            "recording": rec,
            **audio_ctx(rec),
            **(glossary_ctx(rec, request.user, glossary) if opts else {}),
        },
    )


@login_required
def transcribe_panel(request, org_id, rec_id):
    org = org_or_404(request.user, org_id)
    return _panel(request, org, _recording(org, rec_id, request.user))


@login_required
def transcribe_progress(request, org_id, rec_id):
    """패널의 진행 칸만(5초 폴링). 고른 선택지를 잃지 않게 패널 전체를 다시 그리지 않는다."""
    org = org_or_404(request.user, org_id)
    rec = _recording(org, rec_id, request.user)
    active = list(rec.jobs.filter(status__in=TranscriptionJob.ACTIVE).select_related("server"))
    row = _job_row(active[0], tx.queue_eta(active), request.user) if active else None
    r = render(request, "orgs/_transcribe_progress.html", {"org": org, "rec": rec, "row": row})
    if row is None:
        r["HX-Trigger"] = "transcribe-changed"  # 끝났으면 목록·패널을 새로 그린다
    return r


def _after(request, org, rec, error="", glossary=None):
    r = _panel(request, org, rec, error=error, glossary=glossary)
    r["HX-Trigger"] = "transcribe-list"  # 패널은 이 응답으로 이미 새로 그렸다. 목록만 갱신
    return r


@require_POST
@login_required
def transcribe_retry(request, org_id, rec_id):
    org = org_or_404(request.user, org_id)
    rec = _recording(org, rec_id, request.user)
    glossary = posted_glossary(request)
    try:
        tx.request_retry(
            rec,
            actor=request.user,
            glossary=glossary,
            **parse_choice(org, request.user, request.POST.get("choice")),
        )
    except ServiceError as e:
        return _after(request, org, rec, " ".join(e.errors.values()), glossary)
    return _after(request, org, rec)


def _job(request, org, job_id):
    job = (
        TranscriptionJob.objects.select_related("recording__note", "server")
        .filter(pk=job_id, recording__note__in=visible_notes(request.user).values("pk"))
        .first()
    )
    if job is None or job.recording.note.org_id != org.pk:
        raise Http404
    return job


@require_POST
@login_required
def transcribe_cancel(request, org_id, job_id):
    org = org_or_404(request.user, org_id)
    job = _job(request, org, job_id)
    try:
        job = tx.cancel(job, request.user)
    except ServiceError as e:
        return _after(request, org, job.recording, " ".join(e.errors.values()))
    return _after(request, org, job.recording)


@require_POST
@login_required
def transcribe_use(request, org_id, job_id):
    org = org_or_404(request.user, org_id)
    job = _job(request, org, job_id)
    try:
        tx.use(job, request.user)
    except ServiceError as e:
        return _after(request, org, job.recording, " ".join(e.errors.values()))
    return _after(request, org, job.recording)
