import re
from datetime import timedelta

from django.db import transaction
from django.db.models import Exists, OuterRef, Q
from django.utils import timezone

from common.dates import now_kst
from common.errors import ConflictError, Forbidden, ServiceError
from orgs import settings as org_settings
from orgs.models import OrgMembership
from orgs.services import ai_denied, is_admin, is_member, orgs_of, visible_teams
from projects.services import can_view_project, visible_projects

from .models import MeetingNote, VoiceRecording

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
    """회의록 가시성 관문. 회의록을 내보내는 모든 경로(웹·API·태스크 연결)가 이것을 지난다.

    확정(final): 프로젝트 회의록은 그 프로젝트를, 팀 회의록은 그 팀을 볼 수 있을 때만(IMPL-PLAN-7 F).
    초안(draft, 음성 회의): 시작자(이어가기로 넘겨받은 사람 포함)와 조직 관리자만(IMPL-PLAN-9 결정 2).
    """
    admin = OrgMembership.objects.filter(user=user, role="admin", org_id=OuterRef("org_id"))
    final = (
        Q(status="final")
        & (Q(project__isnull=True) | Q(project__in=visible_projects(user)))
        & (Q(team__isnull=True) | Q(team__in=visible_teams(user)))
    )
    draft = Q(status="draft") & (
        Q(created_by=user) | Q(recording__current_owner=user) | Exists(admin)
    )
    return MeetingNote.objects.filter(org__in=orgs_of(user)).filter(final | draft)


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


def _is_owner(note, user) -> bool:
    """초안을 다룰 수 있는 사람: 시작자·이어받은 사람·조직 관리자."""
    rec = getattr(note, "recording", None) if note.source == "voice" else None
    return (
        note.created_by_id == user.pk
        or (rec is not None and rec.current_owner_id == user.pk)
        or is_admin(user, note.org)
    )


def _check_edit(note, actor, source: str):
    if not is_member(actor, note.org):
        raise ServiceError({"org": "이 조직의 멤버가 아닙니다."})
    if note.status == "draft" and not _is_owner(note, actor):
        raise Forbidden({"note": "초안은 시작자나 조직 관리자만 고칠 수 있습니다."})
    # AI 편집은 태스크 본문과 같은 정책(ai.edit_text)을 탄다. 새 키를 만들지 않는다.
    if source == "mcp" and (
        not org_settings.effective("ai.enabled", org=note.org)
        or org_settings.effective("ai.edit_text", org=note.org) == "deny"
    ):
        raise Forbidden({"ai": ai_denied("회의록 고치기")})


@transaction.atomic
def update_note(
    note, field: str, value, *, actor, expected_version: int, source: str = "web"
) -> MeetingNote:
    """한 번에 한 항목. 버전이 다르면 ConflictError(최신 객체)."""
    _check_edit(note, actor, source)
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


def link_task(note, task, actor, source: str = "web"):
    _check_edit(note, actor, source)
    if task.project.org_id != note.org_id:
        raise ServiceError({"task": "같은 조직의 태스크여야 합니다."})
    note.tasks.add(task)


def unlink_task(note, task, actor):
    if not is_member(actor, note.org):
        raise ServiceError({"org": "이 조직의 멤버가 아닙니다."})
    note.tasks.remove(task)


@transaction.atomic
def finalize_note(note, *, actor, source: str, project=None, team=None) -> MeetingNote:
    """초안 확정. 공개 범위는 프로젝트·팀·조직 공통(둘 다 None) 중 하나. 확정은 사람이 웹에서 한다."""
    if source == "mcp":
        raise Forbidden({"ai": "회의록 확정은 웹 회의록 화면에서 사람이 합니다."})
    if note.status != "draft":
        raise ServiceError({"note": "이미 확정된 회의록입니다."})
    if not _is_owner(note, actor):
        raise Forbidden({"note": "시작자나 조직 관리자만 확정할 수 있습니다."})
    rec = getattr(note, "recording", None)
    if rec is not None and rec.status in ("recording", "transcribing"):
        raise ServiceError({"note": "녹음·전사가 끝난 뒤에 확정할 수 있습니다."})
    if project is not None and team is not None:
        raise ServiceError({"scope": "프로젝트와 팀 중 하나만 고를 수 있습니다."})
    _check_project(note.org, project, actor)
    _check_team(note.org, team, actor)
    note.project, note.team, note.status = project, team, "final"
    note.version += 1
    note.save(update_fields=["project", "team", "status", "version", "updated_at"])
    if rec is not None:
        rec.status = "done"
        rec.save(update_fields=["status"])
    return note


# ---------- 음성 회의 녹음 (IMPL-PLAN-9 M2). Discord 봇 API만 부른다 ----------

DRAFT_BODY = (
    "## 요약\n(아직 없음 — `/pm-meeting {id}` 또는 웹에서 작성해 주세요.)\n\n"
    "## 결정 사항\n\n## 할 일\n\n## 미결\n"
)
# 상태는 앞으로만 간다. 같은 상태 재전송(봇 재시도)은 받는다. draft 뒤의 done은 finalize_note만.
_NEXT = {
    "recording": {"transcribing", "failed"},
    "transcribing": {"draft", "failed"},
    "draft": set(),
}


def _check_team(org, team, actor):
    if team is None:
        return
    if team.org_id != org.pk or not visible_teams(actor, org).filter(pk=team.pk).exists():
        raise ServiceError({"team": "볼 수 없는 팀입니다."})


def meeting_scope(*, org, actor, project=None, team=None) -> dict:
    """녹음을 시작해도 되는가. 되면 봇이 쓸 실효 설정을 돌려준다(아니면 ServiceError/Forbidden)."""
    if not is_member(actor, org):
        raise Forbidden({"org": "이 조직의 멤버가 아닙니다."})
    _check_project(org, project, actor)
    _check_team(org, team, actor)
    if not org_settings.effective("meeting.recording_enabled", org=org, project=project):
        raise Forbidden({"meeting": "이 조직(프로젝트)은 회의 녹음을 켜지 않았습니다."})
    return {
        "max_minutes": org_settings.effective("meeting.max_minutes", org=org, project=project),
        "keep_days": org_settings.effective("meeting.audio_keep_days", org=org),
    }


@transaction.atomic
def start_recording(
    *, org, actor, guild_id: str, voice_channel_id: str, project=None, team=None, title=""
) -> VoiceRecording:
    meeting_scope(org=org, actor=actor, project=project, team=team)
    # 봇은 길드당 음성 연결 하나다.
    if VoiceRecording.objects.filter(guild_id=guild_id, status="recording").exists():
        raise ServiceError({"meeting": "이 서버에서는 이미 녹음 중입니다."})
    now = now_kst()
    note = MeetingNote.objects.create(
        org=org,
        project=project,
        team=team,
        title=(title or "").strip()[:200] or f"{now:%m월 %d일} 음성 회의",
        created_on=now,
        created_by=actor,
        status="draft",
        source="voice",
    )
    return VoiceRecording.objects.create(
        note=note,
        guild_id=guild_id,
        voice_channel_id=voice_channel_id,
        started_by=actor,
        current_owner=actor,
    )


def _notify_owner(rec, text: str):
    from django.conf import settings
    from django.urls import reverse

    from tasks.work_requests import notify

    note = rec.note
    link = settings.SITE_URL + reverse("org_notes", args=[note.org_id]) + f"?note={note.pk}"
    notify(note.org, f"{text} <{link}>", user=rec.current_owner)


@transaction.atomic
def update_recording(
    rec,
    *,
    status: str | None = None,
    stopped_by=None,
    new_owner=None,
    ended_at=None,
    end_reason: str = "",
    participants: list | None = None,
    transcript_md: str | None = None,
    stats: dict | None = None,
) -> VoiceRecording:
    """봇이 올리는 상태 전이·결과. 이어가기(new_owner)·종료(transcribing)·전사 결과(draft)·실패."""
    rec = (
        VoiceRecording.objects.select_for_update()
        .select_related("note", "note__org")
        .get(pk=rec.pk)
    )
    note = rec.note
    if new_owner is not None:
        if rec.status != "recording":
            raise ServiceError({"meeting": "녹음 중일 때만 이어갈 수 있습니다."})
        # 이어받는 사람도 시작할 수 있는 사람이어야 한다(멤버·프로젝트·팀 가시성).
        if not is_member(new_owner, note.org):
            raise Forbidden({"org": "이 조직의 멤버가 아닙니다."})
        _check_project(note.org, note.project, new_owner)
        _check_team(note.org, note.team, new_owner)
        rec.current_owner = new_owner
    if status is not None and status != rec.status:
        if status not in _NEXT.get(rec.status, set()):
            raise ServiceError({"status": f"{rec.status}에서 {status}(으)로 바꿀 수 없습니다."})
        if status == "transcribing":
            if end_reason == "command" and not (
                stopped_by is not None
                and (stopped_by.pk == rec.current_owner_id or is_admin(stopped_by, note.org))
            ):
                raise Forbidden({"meeting": "시작자나 조직 관리자만 녹음을 마칠 수 있습니다."})
            rec.ended_at = ended_at or timezone.now()
            keep = org_settings.effective("meeting.audio_keep_days", org=note.org)
            rec.audio_expires_at = rec.ended_at + timedelta(days=keep)
        if status == "failed" and not rec.ended_at:
            rec.ended_at = ended_at or timezone.now()
        rec.status = status
        if status == "draft":
            if not note.body_md.strip():
                note.body_md = DRAFT_BODY.format(id=note.pk)
                note.version += 1
                note.save(update_fields=["body_md", "version", "updated_at"])
            _notify_owner(
                rec,
                f"회의록 초안(전사)이 준비되었습니다. `/pm-meeting {note.pk}`로 정리하거나 "
                "웹에서 작성해 주세요.",
            )
        elif status == "failed":
            _notify_owner(rec, "음성 회의록을 만들지 못했습니다. 녹음 상태를 확인해 주세요.")
    if end_reason:
        if end_reason not in dict(VoiceRecording.END_REASONS):
            raise ServiceError({"end_reason": "알 수 없는 종료 사유입니다."})
        rec.end_reason = end_reason
    if participants is not None:
        rec.participants = participants
    if stats is not None:
        rec.stats = stats
    if transcript_md is not None:
        transcript_md = transcript_md.replace("\r\n", "\n")
        if len(transcript_md.encode()) > MAX_BODY:
            raise ServiceError({"transcript_md": "전사 원문이 너무 깁니다 (256KB 상한)."})
        rec.transcript_md = transcript_md
    rec.save()
    return rec
