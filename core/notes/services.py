import re

from django.db import transaction
from django.db.models import Q
from django.utils import timezone

from common.dates import now_kst
from common.errors import ConflictError, ServiceError
from orgs.services import is_admin, is_member, orgs_of
from projects.services import can_view_project, visible_projects

from .models import MeetingNote

EDITABLE = {"title", "project", "created_on", "body_md", "tags"}
MAX_BODY = 256 * 1024  # 256KB. 회의록 한 편이 이보다 클 이유가 없다.


def _clean_tags(tags) -> list[str]:
    """공백 제거·중복 제거·20자·최대 10개. OrgMembership.set_tags와 같은 규칙."""
    cleaned, seen = [], set()
    for t in tags or []:
        t = (t or "").strip()[:20]
        if t and t not in seen:
            seen.add(t)
            cleaned.append(t)
    return cleaned[:10]


def visible_notes(user):
    """프로젝트 회의록은 그 프로젝트를 볼 수 있을 때만(IMPL-PLAN-7 F)."""
    return MeetingNote.objects.filter(org__in=orgs_of(user)).filter(
        Q(project__isnull=True) | Q(project__in=visible_projects(user))
    )


def get_visible_note(user, note_id: int):
    return (
        visible_notes(user)
        .select_related("project", "created_by", "org")
        .filter(pk=note_id)
        .first()
    )


def _check_project(org, project, actor):
    if project is not None and project.org_id != org.pk:
        raise ServiceError({"project": "같은 조직의 프로젝트여야 합니다."})
    if project is not None and not can_view_project(actor, project):
        raise ServiceError({"project": "볼 수 없는 프로젝트입니다."})


def create_note(
    *, org, actor, title="제목 없는 회의록", project=None, body_md="", created_on=None, tags=None
):
    if not is_member(actor, org):
        raise ServiceError({"org": "이 조직의 멤버가 아닙니다."})
    _check_project(org, project, actor)
    return MeetingNote.objects.create(
        org=org,
        project=project,
        title=(title or "").strip()[:200] or "제목 없는 회의록",
        body_md=(body_md or "").replace("\r\n", "\n"),
        # 안 주면 지금 시각. 회의 일시는 나중에 편집으로 비울 수 있다(작성 시각과 별개).
        created_on=created_on or now_kst(),
        tags=_clean_tags(tags),
        created_by=actor,
    )


@transaction.atomic
def update_note(note, field: str, value, *, actor, expected_version: int) -> MeetingNote:
    """한 번에 한 항목. 버전이 다르면 ConflictError(최신 객체)."""
    if not is_member(actor, note.org):
        raise ServiceError({"org": "이 조직의 멤버가 아닙니다."})
    if field not in EDITABLE:
        raise ServiceError({field: "수정할 수 없는 항목입니다."})
    if field == "title":
        value = (value or "").strip()[:200] or "제목 없는 회의록"
    elif field == "body_md":
        value = (value or "").replace("\r\n", "\n")
        if len(value.encode()) > MAX_BODY:
            raise ServiceError({"body_md": "본문이 너무 깁니다 (256KB 상한)."})
    elif field == "project":
        _check_project(note.org, value, actor)
    elif field == "tags":
        value = _clean_tags(value)
    # created_on(회의 일시)은 비워 둘 수 있다 — 작성 시각(created_at)과 별개다.

    # auto_now는 update()를 타지 않으므로 직접 넣는다.
    updated = MeetingNote.objects.filter(pk=note.pk, version=expected_version).update(
        version=expected_version + 1, updated_at=timezone.now(), **{field: value}
    )
    if updated != 1:
        note.refresh_from_db()
        raise ConflictError(note)
    note.refresh_from_db()
    return note


def upload_note(*, org, actor, filename: str, raw: bytes, project=None) -> MeetingNote:
    """.md 본문 텍스트만 읽어 새 회의록을 만든다. 파일은 저장하지 않는다."""
    if not filename.lower().endswith((".md", ".markdown")):
        raise ServiceError({"file": ".md 또는 .markdown 파일만 올릴 수 있습니다."})
    if len(raw) > MAX_BODY:
        raise ServiceError({"file": "파일이 너무 큽니다 (256KB 상한)."})
    try:
        body = raw.decode("utf-8")
    except UnicodeDecodeError:
        raise ServiceError({"file": "UTF-8로 저장된 파일만 읽을 수 있습니다."}) from None
    title = re.sub(r"\.(md|markdown)$", "", filename, flags=re.I)
    return create_note(org=org, actor=actor, title=title, project=project, body_md=body)


def delete_note(note, actor):
    """작성자 본인이거나 조직 관리자만."""
    if note.created_by_id != actor.pk and not is_admin(actor, note.org):
        raise ServiceError({"note": "작성자나 조직 관리자만 지울 수 있습니다."})
    note.delete()


def link_task(note, task, actor):
    if not is_member(actor, note.org):
        raise ServiceError({"org": "이 조직의 멤버가 아닙니다."})
    if task.project.org_id != note.org_id:
        raise ServiceError({"task": "같은 조직의 태스크여야 합니다."})
    note.tasks.add(task)


def unlink_task(note, task, actor):
    if not is_member(actor, note.org):
        raise ServiceError({"org": "이 조직의 멤버가 아닙니다."})
    note.tasks.remove(task)
