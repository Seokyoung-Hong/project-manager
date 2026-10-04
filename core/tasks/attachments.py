"""첨부 파일·산출물. IMPL-PLAN-7 §3.

파일은 MEDIA_ROOT 아래 uuid 이름으로 저장하고, 내려줄 때는 web/views/attachments.py·API가
`can_download`를 거친다(정적 서빙 없음). content_type은 업로드 헤더가 아니라 아래 확장자 표에서 정한다.
"""

import hashlib
import logging
from pathlib import PurePath

from django.db import transaction
from django.db.models import Q, Sum

from common.errors import ServiceError
from orgs.services import is_admin, is_member
from orgs.settings import effective
from projects.services import can_view_project

from .models import Attachment

log = logging.getLogger(__name__)

MAX_BYTES = 25 * 1024 * 1024  # 사용자 결정(질문 3). 조직 합계는 org.attachment_quota_mb
MAX_PER_TARGET = 50
ALLOWED = {  # 확장자 → 저장 content_type. 여기 없는 확장자는 거부한다
    ".png": "image/png",
    ".jpg": "image/jpeg",
    ".jpeg": "image/jpeg",
    ".gif": "image/gif",
    ".webp": "image/webp",
    ".pdf": "application/pdf",
    ".txt": "text/plain",
    ".md": "text/markdown",
    ".csv": "text/csv",
    ".docx": "application/vnd.openxmlformats-officedocument.wordprocessingml.document",
    ".xlsx": "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
    ".pptx": "application/vnd.openxmlformats-officedocument.presentationml.presentation",
    ".hwp": "application/x-hwp",
    ".hwpx": "application/hwp+zip",
    ".zip": "application/zip",
    ".ai": "application/postscript",
    ".psd": "image/vnd.adobe.photoshop",
    ".mp4": "video/mp4",
}
# 브라우저에서 바로 보여도 되는 것. svg·html은 표에 없다(스크립트 실행).
INLINE = {"image/png", "image/jpeg", "image/gif", "image/webp", "application/pdf"}


def _project_of(task, project):
    if (task is None) == (project is None):
        raise ServiceError({"target": "태스크나 프로젝트 중 하나에만 붙일 수 있습니다."})
    return project if project is not None else task.project


def org_usage_bytes(org) -> int:
    return (
        Attachment.objects.filter(Q(task__project__org=org) | Q(project__org=org)).aggregate(
            s=Sum("size")
        )["s"]
        or 0
    )


def can_download(user, att) -> bool:
    """접근 검사는 projects.services.can_view_project 한 곳에 둔다(공개 범위가 생기면 거기서 좁힌다)."""
    return can_view_project(user, att.target_project)


@transaction.atomic
def add_attachment(
    *, actor, upload, kind="file", note="", task=None, project=None, replaces=None, source="web"
) -> Attachment:
    target_project = _project_of(task, project)
    if not is_member(actor, target_project.org) or not can_view_project(actor, target_project):
        raise ServiceError({"project": "이 프로젝트에 파일을 올릴 수 없습니다."})
    if target_project.is_archived:
        raise ServiceError({"project": "보관된 프로젝트에는 파일을 올릴 수 없습니다."})
    # 크기는 읽기 전에 본다. 업로드 핸들러가 이미 임시 파일로 받았더라도 해시·저장은 하지 않는다.
    if upload.size > MAX_BYTES:
        raise ServiceError({"file": f"파일은 {MAX_BYTES // (1024 * 1024)}MB까지 올릴 수 있습니다."})
    name = PurePath(upload.name or "").name.strip()[:200]
    ext = PurePath(name).suffix.lower()
    if ext not in ALLOWED:
        raise ServiceError({"file": f"올릴 수 없는 형식입니다({ext or '확장자 없음'})."})
    if kind not in dict(Attachment.KINDS):
        raise ServiceError({"kind": "알 수 없는 종류입니다."})
    target = {"task": task} if task is not None else {"project": project}
    if Attachment.objects.filter(**target).count() >= MAX_PER_TARGET:
        raise ServiceError({"file": f"한 곳에 {MAX_PER_TARGET}개까지 붙일 수 있습니다."})
    quota = effective("org.attachment_quota_mb", org=target_project.org) * 1024 * 1024
    if org_usage_bytes(target_project.org) + upload.size > quota:
        raise ServiceError(
            {"file": "조직의 첨부 파일 용량을 넘습니다. 조직 관리자에게 문의하세요."}
        )
    version = 1
    if replaces is not None:
        if (replaces.task_id, replaces.project_id) != (
            getattr(task, "pk", None),
            getattr(project, "pk", None),
        ):
            raise ServiceError({"replaces": "같은 곳에 붙은 파일의 새 버전만 올릴 수 있습니다."})
        if replaces.replaced_by.exists():
            raise ServiceError({"replaces": "이미 새 버전이 있습니다. 최신 버전에서 올리세요."})
        version = replaces.version + 1
    digest = hashlib.sha256()
    for chunk in upload.chunks():
        digest.update(chunk)
    upload.seek(0)
    att = Attachment(
        **target,
        name=name,
        size=upload.size,
        content_type=ALLOWED[ext],
        sha256=digest.hexdigest(),
        kind=kind,
        note=(note or "").strip()[:200],
        version=version,
        replaces=replaces,
        created_by=actor,
    )
    att.file.save(name, upload, save=False)
    try:
        att.save()
    except Exception:
        att.file.delete(save=False)
        raise
    # ponytail: 바깥 트랜잭션이 나중에 롤백되면 파일만 남는다. 쌓이면 DB에 없는 파일을 지우는 명령을 둔다.
    log.info("첨부 업로드: %s (%d bytes, %s)", name, upload.size, source)
    return att


def delete_attachment(att, *, actor) -> None:
    """올린 사람 또는 조직 관리자(문서와 같은 규칙). 파일도 지운다."""
    org = att.target_project.org
    if att.created_by_id != actor.pk and not is_admin(actor, org):
        raise ServiceError({"attachment": "올린 사람이나 조직 관리자만 지울 수 있습니다."})
    purge_files([att])
    att.delete()
    log.info("첨부 삭제: %s", att.name)


def purge_files(atts) -> None:
    """행을 지우는 트랜잭션이 커밋된 뒤에 파일을 지운다. 롤백되면 파일은 남는다."""
    names = [a.file.name for a in atts if a.file]
    if not names:
        return
    storage = Attachment._meta.get_field("file").storage

    def _rm():
        for n in names:
            storage.delete(n)

    transaction.on_commit(_rm)


def attachments_of(target) -> list[Attachment]:
    """최신 버전만. 각 항목의 `.history`에 이전 버전을(최신→과거) 붙여 준다."""
    rows = list(target.attachments.select_related("created_by").order_by("-id"))
    by_id = {a.pk: a for a in rows}
    newer = {a.replaces_id for a in rows if a.replaces_id}
    latest = [a for a in rows if a.pk not in newer]
    for a in latest:
        a.history = []
        prev = by_id.get(a.replaces_id)
        while prev is not None:
            a.history.append(prev)
            prev = by_id.get(prev.replaces_id)
    return latest
