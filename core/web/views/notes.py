import re
from datetime import datetime

from django.contrib import messages
from django.contrib.auth.decorators import login_required
from django.http import FileResponse, Http404, HttpResponse, JsonResponse
from django.shortcuts import redirect, render
from django.urls import reverse
from django.views.decorators.http import require_POST

from common.dates import KST
from common.errors import ConflictError, Forbidden, ServiceError
from notes import services as ts_notes
from orgs.services import visible_teams
from projects.services import visible_projects

from .common import (
    CONFLICT_MSG,
    can_admin,
    org_or_404,
    project_or_404,
    task_or_404,
    trigger,
    version_of,
)
from .tasks import _refs


def _note_or_404(user, note_id):
    note = ts_notes.get_visible_note(user, note_id)
    if note is None:
        raise Http404
    return note


@login_required
def org_notes(request, org_id):
    org = org_or_404(request.user, org_id)
    scope = request.GET.get("scope", "all")
    qs = (
        ts_notes.visible_notes(request.user).filter(org=org).select_related("project", "created_by")
    )
    if scope == "team":
        qs = qs.filter(project__isnull=True)
    elif scope.isdecimal():
        qs = qs.filter(project_id=int(scope))
    notes = list(qs)

    # 태그 필터는 DB가 아니라 파이썬에서 거른다 — OrgMembership 스킬 태그 필터와 같은 방식.
    all_tags = sorted({t for n in notes for t in n.tags})
    tag = request.GET.get("tag", "")
    if tag:
        notes = [n for n in notes if tag in n.tags]

    raw = request.GET.get("note", "")
    note = next((n for n in notes if str(n.pk) == raw), None) or (notes[0] if notes else None)
    editor_open = bool(note and raw == str(note.pk))

    # 프로젝트별 묶음. 팀 공통이 맨 뒤.
    groups, seen = [], {}
    for n in notes:
        key = n.project_id or 0
        if key not in seen:
            seen[key] = {
                "title": n.project.name if n.project else "조직 공통(프로젝트 미지정)",
                "items": [],
            }
            groups.append(seen[key])
        seen[key]["items"].append(n)
    groups.sort(key=lambda g: g["title"] == "조직 공통(프로젝트 미지정)")
    for g in groups:
        g["hint"] = f"{len(g['items'])}건"

    extras = {}
    if note is not None:
        from .docs import extras_ctx

        extras = extras_ctx(request.user, note)
        extras["here"] = request.get_full_path()
        extras["recording"] = rec = getattr(note, "recording", None)
        # 녹음 내려받기: ready | expired | None(올린 파일 없음)
        extras["audio_state"] = (
            None
            if rec is None or not rec.audio_size
            else "expired"
            if not rec.audio or ts_notes.audio_expired(rec)
            else "ready"
        )
        extras["audio_expired_text"] = ts_notes.AUDIO_EXPIRED
        if extras["audio_state"] == "ready":
            extras["tracks"] = [
                {
                    "id": t.discord_user_id,
                    "name": _track_name(rec, t.discord_user_id),
                    "size": t.audio_size,
                }
                for t in rec.tracks.exclude(audio="").order_by("pk")
            ]
        if rec is not None:
            # 전사 진행(전사문 쪽 상태). 회의록 본문과 별개다.
            from notes import transcription as tx
            from notes.models import TranscriptionJob

            active = list(rec.jobs.filter(status__in=TranscriptionJob.ACTIVE))
            if active:
                left, _ = tx.queue_eta(active).get(active[0].pk, (None, 0))
                extras["transcribe_line"] = (
                    "전사 대기 중"
                    if active[0].status == "queued"
                    else f"전사 중 · {tx.eta_text(left)}"
                )
            extras["transcribe_admin"] = can_admin(request.user, org)
        extras["can_finalize"] = note.status == "draft" and ts_notes._is_owner(note, request.user)
        extras["teams"] = visible_teams(request.user, org).order_by("name")
    return render(
        request,
        "notes/list.html",
        {
            **extras,
            "org": org,
            "tab": "notes",
            "is_admin": can_admin(request.user, org),
            "groups": groups,
            "note": note,
            "editor_open": editor_open,
            "scope": scope,
            "tag": tag,
            "all_tags": all_tags,
            "projects": visible_projects(request.user, org)
            .filter(is_archived=False)
            .order_by("name"),
            "can_delete": bool(note)
            and (note.created_by_id == request.user.pk or can_admin(request.user, org)),
        },
    )


@login_required
@require_POST
def note_new(request, org_id):
    org = org_or_404(request.user, org_id)
    try:
        note = ts_notes.create_note(org=org, actor=request.user)
    except ServiceError as e:
        messages.error(request, "회의록을 만들지 못했습니다. " + " ".join(e.errors.values()))
        return redirect("org_notes", org_id=org.pk)
    return redirect(f"{reverse('org_notes', args=[org.pk])}?note={note.pk}")


@login_required
@require_POST
def note_upload(request, org_id):
    org = org_or_404(request.user, org_id)
    f = request.FILES.get("file")
    project = None
    raw_project = request.POST.get("project", "")
    if raw_project:
        project = project_or_404(request.user, raw_project)
    if f is None:
        messages.error(request, "올릴 Markdown 파일(.md 또는 .markdown)을 선택해 주세요.")
        return redirect("org_notes", org_id=org.pk)
    try:
        note = ts_notes.upload_note(
            org=org, actor=request.user, filename=f.name, raw=f.read(), project=project
        )
    except ServiceError as e:
        messages.error(request, "회의록을 올리지 못했습니다. " + " ".join(e.errors.values()))
        return redirect("org_notes", org_id=org.pk)
    return redirect(f"{reverse('org_notes', args=[org.pk])}?note={note.pk}")


@login_required
@require_POST
def note_save(request, note_id):
    note = _note_or_404(request.user, note_id)
    field = request.POST.get("field", "")
    raw = request.POST.get("value", "")
    value = raw
    if field == "project":
        value = project_or_404(request.user, raw) if raw else None
    elif field == "created_on":
        # <input type="datetime-local">는 "YYYY-MM-DDTHH:MM"(초·시간대 없음)을 준다.
        # 빈 값은 "회의 일시 없음" — 작성 시각(created_at)과 별개로 비워 둘 수 있다.
        try:
            value = datetime.fromisoformat(raw).replace(tzinfo=KST) if raw else None
        except ValueError:
            value = None
    elif field == "tags":
        value = raw.split(",")
    try:
        note = ts_notes.update_note(
            note, field, value, actor=request.user, expected_version=version_of(request)
        )
    except ServiceError as e:
        return JsonResponse(
            {"error": " ".join(e.errors.values())},
            status=400,
            json_dumps_params={"ensure_ascii": False},
        )
    except ConflictError:
        return JsonResponse(
            {"error": CONFLICT_MSG}, status=409, json_dumps_params={"ensure_ascii": False}
        )
    resp = HttpResponse(status=204)
    resp["X-Note-Version"] = str(note.version)
    return trigger(resp, "saved")


@login_required
@require_POST
def note_delete(request, note_id):
    note = _note_or_404(request.user, note_id)
    org_id = note.org_id
    try:
        ts_notes.delete_note(note, request.user)
    except ServiceError as e:
        messages.error(request, "회의록을 삭제하지 못했습니다. " + " ".join(e.errors.values()))
        return redirect(f"{reverse('org_notes', args=[org_id])}?note={note.pk}")
    return redirect("org_notes", org_id=org_id)


@login_required
@require_POST
def task_note_link(request, task_id):
    task = task_or_404(request.user, task_id)
    try:
        note = _note_or_404(request.user, int(request.POST.get("note", "")))
    except (TypeError, ValueError):
        return _refs(request, task, error="회의록을 선택해 주세요.")
    try:
        ts_notes.link_task(note, task, request.user)
    except ServiceError as e:
        return _refs(request, task, error=" ".join(e.errors.values()))
    return _refs(request, task)


@login_required
@require_POST
def task_note_unlink(request, task_id, note_id):
    task = task_or_404(request.user, task_id)
    note = _note_or_404(request.user, note_id)
    ts_notes.unlink_task(note, task, request.user)
    return _refs(request, task)


@login_required
@require_POST
def note_finalize(request, note_id):
    """초안 확정(IMPL-PLAN-9 M4의 확정 화면). 공개 범위: 조직 공통 | p<id> | t<id>."""
    note = _note_or_404(request.user, note_id)
    raw = request.POST.get("scope", "")
    project = team = None
    if raw[:1] == "p" and raw[1:].isdecimal():
        project = project_or_404(request.user, raw[1:])
    elif raw[:1] == "t" and raw[1:].isdecimal():
        team = visible_teams(request.user, note.org).filter(pk=int(raw[1:])).first()
        if team is None:
            raise Http404
    try:
        ts_notes.finalize_note(note, actor=request.user, source="web", project=project, team=team)
        messages.success(request, "회의록을 확정했습니다. 고른 공개 범위의 사람이 볼 수 있습니다.")
    except (ServiceError, Forbidden) as e:
        messages.error(request, "확정하지 못했습니다. " + " ".join(e.errors.values()))
    return redirect(f"{reverse('org_notes', args=[note.org_id])}?note={note.pk}")


@login_required
def note_audio(request, note_id):
    """회의 녹음 내려받기. 회의록을 볼 수 있는 사람만(초안이면 진행자·조직 관리자 — visible_notes)."""
    note = _note_or_404(request.user, note_id)
    rec = getattr(note, "recording", None)
    if rec is None or not rec.audio or ts_notes.audio_expired(rec):
        raise Http404
    try:
        fh = rec.audio.open("rb")
    except FileNotFoundError:
        raise Http404 from None
    r = FileResponse(
        fh, as_attachment=True, filename=f"회의록-{note.pk}.ogg", content_type="audio/ogg"
    )
    r["X-Content-Type-Options"] = "nosniff"
    return r


def _track_name(rec, discord_user_id):
    p = next((p for p in rec.participants or [] if p.get("discord_user_id") == discord_user_id), {})
    return (p.get("display_name") or discord_user_id).removesuffix(ts_notes.UNLINKED_MARK)


@login_required
def note_track(request, note_id, discord_user_id):
    """참여자별 녹음 내려받기. 권한은 note_audio와 같다."""
    note = _note_or_404(request.user, note_id)
    rec = getattr(note, "recording", None)
    if rec is None or ts_notes.audio_expired(rec):
        raise Http404
    track = rec.tracks.filter(discord_user_id=discord_user_id).exclude(audio="").first()
    if track is None:
        raise Http404
    try:
        fh = track.audio.open("rb")
    except FileNotFoundError:
        raise Http404 from None
    name = re.sub(r"[^\w-]+", "_", _track_name(rec, discord_user_id)).strip("_") or "참여자"
    r = FileResponse(
        fh, as_attachment=True, filename=f"회의록-{note.pk}-{name}.ogg", content_type="audio/ogg"
    )
    r["X-Content-Type-Options"] = "nosniff"
    return r
