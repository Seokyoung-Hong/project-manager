"""프로젝트 문서. GitHub를 붙이지 않아도 프로젝트를 굴릴 수 있게 하는 조각이다.

회의록(notes.services)과 규칙을 일부러 맞춰 두었다 — 한 번에 한 항목, 버전이 다르면
ConflictError, 본문 상한 256KB. 편집기가 같으므로 규칙까지 달라지면 사용자가 두 벌을 배운다.
읽기·쓰기는 조직 멤버, 삭제는 작성자나 조직 관리자다(회의록과 같다).
"""

import re

from django.db import transaction
from django.utils import timezone

from common.errors import ConflictError, ServiceError
from orgs.services import is_admin, is_member, require_ai_enabled

from .models import ProjectDoc

EDITABLE = {"title", "body_md"}
MAX_BODY = 256 * 1024  # 회의록과 같은 상한


def visible_docs(project):
    return project.docs.select_related("created_by", "updated_by")


def get_visible_doc(user, doc_id: int):
    """내가 속한 조직의 문서만. 아니면 None."""
    doc = (
        ProjectDoc.objects.select_related("project", "project__org", "created_by")
        .filter(pk=doc_id)
        .first()
    )
    if doc is None or not is_member(user, doc.project.org):
        return None
    return doc


def create_doc(*, project, actor, title="제목 없는 문서", body_md="", source="web"):
    if not is_member(actor, project.org):
        raise ServiceError({"project": "이 조직의 멤버가 아닙니다."})
    require_ai_enabled(project.org, source, "문서 만들기")
    if len((body_md or "").encode()) > MAX_BODY:
        raise ServiceError({"body_md": "본문이 너무 깁니다 (256KB 상한)."})
    return ProjectDoc.objects.create(
        project=project,
        title=(title or "").strip()[:200] or "제목 없는 문서",
        body_md=(body_md or "").replace("\r\n", "\n"),
        created_by=actor,
        updated_by=actor,
        updated_source=source,
    )


@transaction.atomic
def update_doc(doc, field: str, value, *, actor, expected_version: int, source="web") -> ProjectDoc:
    """한 번에 한 항목. 버전이 다르면 ConflictError(최신 객체).

    source는 누가 고쳤는지 남기려는 것이다 — AI(mcp)도 문서를 고치므로 사람이 구별할 수 있어야 한다.
    """
    if not is_member(actor, doc.project.org):
        raise ServiceError({"project": "이 조직의 멤버가 아닙니다."})
    require_ai_enabled(doc.project.org, source, "문서 고치기")
    if field not in EDITABLE:
        raise ServiceError({field: "수정할 수 없는 항목입니다."})
    if field == "title":
        value = (value or "").strip()[:200] or "제목 없는 문서"
    elif field == "body_md":
        value = (value or "").replace("\r\n", "\n")
        if len(value.encode()) > MAX_BODY:
            raise ServiceError({"body_md": "본문이 너무 깁니다 (256KB 상한)."})

    # auto_now는 update()를 타지 않으므로 직접 넣는다.
    updated = ProjectDoc.objects.filter(pk=doc.pk, version=expected_version).update(
        version=expected_version + 1,
        updated_at=timezone.now(),
        updated_by=actor,
        updated_source=source,
        **{field: value},
    )
    if updated != 1:
        doc.refresh_from_db()
        raise ConflictError(doc)
    doc.refresh_from_db()
    return doc


def upload_doc(*, project, actor, filename: str, raw: bytes) -> ProjectDoc:
    """.md 본문 텍스트만 읽어 새 문서를 만든다. 파일 자체는 저장하지 않는다.

    이미 README.md를 쓰던 팀이 그대로 옮겨 올 수 있어야 한다.
    """
    if not filename.lower().endswith((".md", ".markdown")):
        raise ServiceError({"file": ".md 또는 .markdown 파일만 올릴 수 있습니다."})
    if len(raw) > MAX_BODY:
        raise ServiceError({"file": "파일이 너무 큽니다 (256KB 상한)."})
    try:
        body = raw.decode("utf-8")
    except UnicodeDecodeError:
        raise ServiceError({"file": "UTF-8로 저장된 파일만 읽을 수 있습니다."}) from None
    title = re.sub(r"\.(md|markdown)$", "", filename, flags=re.I)
    return create_doc(project=project, actor=actor, title=title, body_md=body)


def delete_doc(doc, actor):
    """작성자 본인이거나 조직 관리자만."""
    if doc.created_by_id != actor.pk and not is_admin(actor, doc.project.org):
        raise ServiceError({"doc": "작성자나 조직 관리자만 지울 수 있습니다."})
    doc.delete()


def link_task(doc, task, actor, *, as_output=False):
    """문서를 태스크의 참고 자료로 건다.

    문서는 프로젝트에 매여 있으므로 같은 프로젝트의 태스크만 건다. 조직 전체를 도는 글은
    회의록(notes)의 몫이다 — 그쪽은 프로젝트 없이도 존재한다.
    """
    if not is_member(actor, doc.project.org):
        raise ServiceError({"project": "이 조직의 멤버가 아닙니다."})
    if task.project_id != doc.project_id:
        raise ServiceError({"task": "같은 프로젝트의 태스크여야 합니다."})
    doc.tasks.add(task)
    if as_output:
        # 내부 문서를 산출물로: "산출물" 링크 하나로 남겨 파일·외부 링크와 같은 목록에 보인다.
        from django.conf import settings

        from tasks.services import add_link

        add_link(
            actor=actor,
            task=task,
            title=doc.title,
            url=f"{settings.SITE_URL}/projects/{doc.project_id}/docs?doc={doc.pk}",
            kind="out",
        )


def unlink_task(doc, task, actor):
    if not is_member(actor, doc.project.org):
        raise ServiceError({"project": "이 조직의 멤버가 아닙니다."})
    doc.tasks.remove(task)
