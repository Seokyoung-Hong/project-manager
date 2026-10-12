"""조직 전사 메뉴(IMPL-PLAN-10-transcribe-menu, 시안 B): 전사 작업 목록 + 패널, 전사 서버 보기.

전사문(녹음을 글로 옮긴 원문)만 다룬다. 회의록 본문은 바꾸지 않는다.
"""

from datetime import timedelta

from django.contrib import messages
from django.contrib.auth.decorators import login_required
from django.db.models import Q
from django.http import Http404
from django.shortcuts import get_object_or_404, redirect, render
from django.urls import reverse
from django.utils import timezone
from django.views.decorators.http import require_POST

from common.errors import ServiceError
from notes import transcription as tx
from notes.models import TranscriptionJob, VoiceRecording
from orgs import services as osv
from orgs.settings import SPECS, STT_KEYS, display, effective, secret_value

from .common import not_admin, org_or_404
from .orgs import _settings_from_post, stt_models

RECENT = timedelta(days=7)


def _admin_org(request, org_id):
    org = org_or_404(request.user, org_id)
    return org, not_admin(request, org, "전사")


def _job_row(job, eta):
    left, wait = eta.get(job.pk, (None, 0.0))
    pct = round(100 * min(job.done_ms, job.audio_ms) / job.audio_ms) if job.audio_ms else 0
    return {
        "job": job,
        "label": job.stats.get("label") or tx.model_label(job.engine, job.model),
        "eta": tx.eta_text(left),
        "wait": tx.eta_text(wait) if job.status == "queued" and wait else "",
        "pct": pct,
        "done_min": round(min(job.done_ms, job.audio_ms) / 60000),
        "audio_min": round(job.audio_ms / 60000),
        "stale": tx.is_stale(job),
    }


def _jobs_ctx(org):
    since = timezone.now() - RECENT
    jobs = list(
        TranscriptionJob.objects.filter(recording__note__org=org)
        .filter(Q(status__in=TranscriptionJob.ACTIVE) | Q(created_at__gte=since))
        .select_related("recording__note")
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


def _server_rows(org):
    return [
        {
            "spec": SPECS[k],
            "value": effective(k, org=org),
            "display": display(k, effective(k, org=org)),
            "can_edit": True,
            "show_override": False,
        }
        for k in STT_KEYS
    ]


@login_required
def org_transcribe(request, org_id):
    org, deny = _admin_org(request, org_id)
    if deny:
        return deny
    view = "server" if request.GET.get("view") == "server" else "jobs"
    ctx = {"org": org, "tab": "transcribe", "is_admin": True, "view": view, **_jobs_ctx(org)}
    if view == "server":
        ctx["rows"] = _server_rows(org)
    return render(request, "orgs/transcribe.html", ctx)


@require_POST
@login_required
def org_transcribe_server(request, org_id):
    """전사 서버 저장. 다른 조직 설정 값은 그대로 둔다."""
    org, deny = _admin_org(request, org_id)
    if deny:
        return deny
    keep = {k: v for k, v in (org.settings or {}).items() if k not in STT_KEYS}
    try:
        osv.set_org_settings(
            org,
            {**keep, **_settings_from_post(request.POST, [SPECS[k] for k in STT_KEYS])},
            request.user,
        )
        messages.success(request, "전사 서버 설정을 저장했습니다.")
    except ServiceError as e:
        messages.error(request, " ".join(e.errors.values()))
    return redirect(reverse("org_transcribe", args=[org.pk]) + "?view=server")


@login_required
def org_transcribe_jobs(request, org_id):
    org, deny = _admin_org(request, org_id)
    if deny:
        return deny
    return render(request, "orgs/_transcribe_jobs.html", _jobs_ctx(org))


def _recording(org, rec_id):
    return get_object_or_404(
        VoiceRecording.objects.select_related("note"), pk=rec_id, note__org=org
    )


def _options(org, rec):
    """다시 전사 선택지: 로컬 서버의 준비된 모델(맞지 않는 모델 제외) + 조직 OpenAI 키."""
    a, n = tx.speech_ms(rec.segments)
    out, error = [], ""
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
                }
            )
    if secret_value("meeting.openai_api_key", org):
        rtf = tx.prior_rtf(org, "openai", tx.OPENAI_MODEL)
        out.append(
            {
                "value": f"openai|{tx.OPENAI_MODEL}",
                "label": tx.model_label("openai", tx.OPENAI_MODEL),
                "eta": tx.eta_text(tx.estimate_s(a, n, rtf, tx.parallel("openai"))),
            }
        )
    if error:
        error = f"로컬 전사 서버 모델 목록을 불러오지 못했습니다. {error}"
    return out, error


def _panel(request, org, rec, *, error=""):
    jobs = list(rec.jobs.all())
    active = [j for j in jobs if j.status in TranscriptionJob.ACTIVE]
    eta = tx.queue_eta(active)
    latest = active[0] if active else (jobs[0] if jobs else None)
    block = tx.retry_block(rec)
    opts, opts_error = _options(org, rec) if not block else ([], "")
    a, _ = tx.speech_ms(rec.segments)
    return render(
        request,
        "orgs/_transcribe_panel.html",
        {
            "org": org,
            "rec": rec,
            "note": rec.note,
            "row": _job_row(latest, eta) if latest else None,
            "active_row": _job_row(active[0], eta) if active else None,
            "history": [
                {**_job_row(j, eta), "current": j.pk == rec.transcript_job_id} for j in jobs
            ],
            "speech_min": round(a / 60000),
            "block": block,
            "options": opts,
            "options_error": opts_error,
            "running": any(j.status in TranscriptionJob.RUNNING for j in active),
            "error": error,
        },
    )


@login_required
def transcribe_panel(request, org_id, rec_id):
    org, deny = _admin_org(request, org_id)
    if deny:
        return deny
    return _panel(request, org, _recording(org, rec_id))


@login_required
def transcribe_progress(request, org_id, rec_id):
    """패널의 진행 칸만(5초 폴링). 고른 선택지를 잃지 않게 패널 전체를 다시 그리지 않는다."""
    org, deny = _admin_org(request, org_id)
    if deny:
        return deny
    rec = _recording(org, rec_id)
    active = list(rec.jobs.filter(status__in=TranscriptionJob.ACTIVE))
    row = _job_row(active[0], tx.queue_eta(active)) if active else None
    r = render(request, "orgs/_transcribe_progress.html", {"org": org, "rec": rec, "row": row})
    if row is None:
        r["HX-Trigger"] = "transcribe-changed"  # 끝났으면 목록·패널을 새로 그린다
    return r


def _after(request, org, rec, error=""):
    r = _panel(request, org, rec, error=error)
    r["HX-Trigger"] = "transcribe-list"  # 패널은 이 응답으로 이미 새로 그렸다. 목록만 갱신
    return r


@require_POST
@login_required
def transcribe_retry(request, org_id, rec_id):
    org, deny = _admin_org(request, org_id)
    if deny:
        return deny
    rec = _recording(org, rec_id)
    engine, _, model = request.POST.get("choice", "").partition("|")
    info = None
    if engine == "local":
        models, _, _ = stt_models(org, effective("meeting.stt_url", org=org))
        info = next((m["info"] for m in models if m["id"] == model), None)
    try:
        tx.request_retry(rec, engine=engine, model=model, actor=request.user, info=info)
    except ServiceError as e:
        return _after(request, org, rec, " ".join(e.errors.values()))
    return _after(request, org, rec)


def _job(org, job_id):
    job = TranscriptionJob.objects.select_related("recording__note").filter(pk=job_id).first()
    if job is None or job.recording.note.org_id != org.pk:
        raise Http404
    return job


@require_POST
@login_required
def transcribe_cancel(request, org_id, job_id):
    org, deny = _admin_org(request, org_id)
    if deny:
        return deny
    job = tx.cancel(_job(org, job_id), request.user)
    return _after(request, org, job.recording)


@require_POST
@login_required
def transcribe_use(request, org_id, job_id):
    org, deny = _admin_org(request, org_id)
    if deny:
        return deny
    job = _job(org, job_id)
    try:
        tx.use(job, request.user)
    except ServiceError as e:
        return _after(request, org, job.recording, " ".join(e.errors.values()))
    return _after(request, org, job.recording)
