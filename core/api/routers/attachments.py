"""첨부 파일 API. 업로드는 multipart(file, kind, note, replaces). 규칙은 tasks/attachments.py."""

from ninja import Router
from ninja.errors import HttpError

from common.errors import ServiceError
from tasks import attachments as at
from tasks.models import Attachment

from ..context import ctx, task_or_404
from ..schemas import AttachmentOut, ErrorOut
from ..serialize import attachment_out
from .projects import _project_or_404

router = Router(tags=["attachments"])


def _att_or_404(request, att_id: int) -> Attachment:
    att = Attachment.objects.filter(pk=att_id).first()
    if att is None or not at.can_download(request.auth, att):
        raise HttpError(404, "첨부 파일을 찾을 수 없습니다.")
    return att


def _list(target, all_versions: bool):
    rows = list(target.attachments.all()) if all_versions else at.attachments_of(target)
    return [attachment_out(a) for a in rows]


def _add(request, **target):
    p = request.POST
    upload = request.FILES.get("file")
    if upload is None:
        raise ServiceError({"file": "multipart의 file 필드로 파일을 보내세요."})
    replaces = (
        _att_or_404(request, int(p["replaces"])) if p.get("replaces", "").isdecimal() else None
    )
    c = ctx(request)
    att = at.add_attachment(
        actor=c["actor"],
        upload=upload,
        kind=p.get("kind", "file"),
        note=p.get("note", ""),
        replaces=replaces,
        source=c["source"],
        **target,
    )
    return 201, attachment_out(att)


@router.get("/tasks/{task_id}/attachments", response=list[AttachmentOut])
def task_attachments(request, task_id: int, all: bool = False):
    """최신 버전만. all=true면 이전 버전까지(replaces_id로 잇는다)."""
    return _list(task_or_404(request, task_id), all)


@router.post("/tasks/{task_id}/attachments", response={201: AttachmentOut, 400: ErrorOut})
def add_task_attachment(request, task_id: int):
    return _add(request, task=task_or_404(request, task_id))


@router.get("/projects/{project_id}/attachments", response=list[AttachmentOut])
def project_attachments(request, project_id: int, all: bool = False):
    return _list(_project_or_404(request, project_id), all)


@router.post("/projects/{project_id}/attachments", response={201: AttachmentOut, 400: ErrorOut})
def add_project_attachment(request, project_id: int):
    return _add(request, project=_project_or_404(request, project_id))


@router.delete("/attachments/{att_id}", response={204: None, 400: ErrorOut})
def delete_attachment(request, att_id: int):
    """올린 사람 또는 조직 관리자."""
    at.delete_attachment(_att_or_404(request, att_id), actor=request.auth)
    return 204, None


@router.get("/attachments/{att_id}/download")
def download_attachment(request, att_id: int):
    from web.views.attachments import download_response

    return download_response(_att_or_404(request, att_id))
