"""첨부 파일 올리기·지우기·내려받기. 규칙은 tasks/attachments.py에 있다."""

from django.contrib import messages
from django.contrib.auth.decorators import login_required
from django.http import FileResponse, Http404
from django.shortcuts import redirect
from django.views.decorators.http import require_POST

from common.errors import ServiceError
from tasks import attachments as at
from tasks.models import Attachment

from .common import _pk_or_404, project_or_404, task_or_404


def attachment_or_404(user, att_id) -> Attachment:
    """볼 수 없는 첨부는 있는지도 알리지 않는다(404)."""
    att = (
        Attachment.objects.select_related("task__project__org", "project__org")
        .filter(pk=_pk_or_404(att_id))
        .first()
    )
    if att is None or not at.can_download(user, att):
        raise Http404
    return att


def download_response(att) -> FileResponse:
    """웹·API 공통. 이미지·PDF만 인라인이고 나머지는 내려받기를 강제한다."""
    try:
        fh = att.file.open("rb")
    except FileNotFoundError:
        raise Http404 from None
    inline = att.content_type in at.INLINE
    r = FileResponse(fh, as_attachment=not inline, filename=att.name, content_type=att.content_type)
    r["X-Content-Type-Options"] = "nosniff"
    if inline:
        r["Content-Security-Policy"] = "sandbox"
    return r


def _upload(request, **target):
    p = request.POST
    replaces = None
    if p.get("replaces"):
        replaces = attachment_or_404(request.user, p["replaces"])
    upload = request.FILES.get("file")
    if upload is None:
        raise ServiceError({"file": "파일을 고르세요."})
    return at.add_attachment(
        actor=request.user,
        upload=upload,
        kind=p.get("kind", "file"),
        note=p.get("note", ""),
        replaces=replaces,
        **target,
    )


@login_required
@require_POST
def task_attachment_add(request, task_id):
    from .tasks import _refs

    task = task_or_404(request.user, task_id)
    try:
        _upload(request, task=task)
    except ServiceError as e:
        return _refs(request, task, error=" ".join(e.errors.values()))
    return _refs(request, task)


@login_required
@require_POST
def project_attachment_add(request, project_id):
    project = project_or_404(request.user, project_id)
    try:
        _upload(request, project=project)
        messages.success(request, "파일을 올렸습니다.")
    except ServiceError as e:
        messages.error(request, " ".join(e.errors.values()))
    return redirect("project_docs", project_id=project.pk)


@login_required
@require_POST
def attachment_delete(request, att_id):
    att = attachment_or_404(request.user, att_id)
    task = att.task
    try:
        at.delete_attachment(att, actor=request.user)
        error = None
    except ServiceError as e:
        error = " ".join(e.errors.values())
    if task is not None:
        from .tasks import _refs

        return _refs(request, task, error=error)
    if error:
        messages.error(request, error)
    return redirect("project_docs", project_id=att.project_id)


@login_required
def attachment_download(request, att_id, name=""):
    """URL의 이름은 보기 좋게만 둔다 — 내려줄 파일은 id로만 고른다."""
    return download_response(attachment_or_404(request.user, att_id))
