from datetime import datetime

from django.contrib.auth.decorators import login_required
from django.http import Http404, HttpResponse
from django.shortcuts import redirect, render
from django.urls import reverse
from django.views.decorators.http import require_POST

from common.dates import KST
from common.errors import ConflictError, ServiceError
from notes import services as ts_notes

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
    qs = org.notes.select_related("project", "created_by")
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
            seen[key] = {"title": n.project.name if n.project else "팀 공통", "items": []}
            groups.append(seen[key])
        seen[key]["items"].append(n)
    groups.sort(key=lambda g: g["title"] == "팀 공통")
    for g in groups:
        g["hint"] = f"{len(g['items'])}건"

    return render(
        request,
        "notes/list.html",
        {
            "org": org,
            "tab": "notes",
            "is_admin": can_admin(request.user, org),
            "groups": groups,
            "note": note,
            "editor_open": editor_open,
            "scope": scope,
            "tag": tag,
            "all_tags": all_tags,
            "projects": org.projects.filter(is_archived=False).order_by("name"),
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
    except ServiceError:
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
        return redirect("org_notes", org_id=org.pk)
    try:
        note = ts_notes.upload_note(
            org=org, actor=request.user, filename=f.name, raw=f.read(), project=project
        )
    except ServiceError:
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
        return HttpResponse(" ".join(e.errors.values()), status=400)
    except ConflictError:
        return HttpResponse(CONFLICT_MSG, status=409)
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
    except ServiceError:
        return redirect(f"{reverse('org_notes', args=[org_id])}?note={note.pk}")
    return redirect("org_notes", org_id=org_id)


@login_required
@require_POST
def task_note_link(request, task_id):
    task = task_or_404(request.user, task_id)
    try:
        note = _note_or_404(request.user, int(request.POST.get("note", "")))
    except (TypeError, ValueError):
        return _refs(request, task, error="회의록을 선택하세요.")
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
