import re
from collections import Counter
from datetime import timedelta

from django.db import transaction
from django.db.models import Exists, OuterRef, Q
from django.utils import timezone

from accounts.identity import resolve
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
    초안(draft, 음성 회의): 지금 진행자(recording.host)와 조직 관리자만(IMPL-PLAN-9 결정 2-5).
    진행자를 넘기면 이전 진행자는 더 이상 보지 못한다.
    """
    admin = OrgMembership.objects.filter(user=user, role="admin", org_id=OuterRef("org_id"))
    final = (
        Q(status="final")
        & (Q(project__isnull=True) | Q(project__in=visible_projects(user)))
        & (Q(team__isnull=True) | Q(team__in=visible_teams(user)))
    )
    draft = Q(status="draft") & (Q(recording__host=user) | Exists(admin))
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
    """초안을 다룰 수 있는 사람: 지금 진행자·조직 관리자. 녹음 없는 회의록은 작성자."""
    rec = getattr(note, "recording", None)
    who = rec.host_id if rec is not None else note.created_by_id
    return who == user.pk or is_admin(user, note.org)


def _check_edit(note, actor, source: str):
    if not is_member(actor, note.org):
        raise ServiceError({"org": "이 조직의 멤버가 아닙니다."})
    if note.status == "draft" and not _is_owner(note, actor):
        raise Forbidden({"note": "초안은 진행자나 조직 관리자만 고칠 수 있습니다."})
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
    if note.status == "draft":
        if not _is_owner(note, actor):
            raise ServiceError({"note": "초안은 진행자나 조직 관리자만 지울 수 있습니다."})
    elif note.created_by_id != actor.pk and not is_admin(actor, note.org):
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
        raise Forbidden({"note": "진행자나 조직 관리자만 확정할 수 있습니다."})
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

# 진행자가 음성 채널을 떠나 유예(meeting.leave_grace_s)가 지나면 봇이 이 문구를 채널에 올린다.
HOST_LEFT_NOTICE = (
    "회의 진행자가 나가서 회의를 종료하였습니다. 새 회의를 시작하려면 /회의시작 을 눌러 주세요."
)
UNLINKED_MARK = " (계정 없음)"
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
        "leave_grace_s": org_settings.effective("meeting.leave_grace_s", org=org),
    }


@transaction.atomic
def start_recording(
    *, org, actor, guild_id: str, voice_channel_id: str, project=None, team=None, title=""
) -> VoiceRecording:
    meeting_scope(org=org, actor=actor, project=project, team=team)
    # 봇은 길드당 음성 연결 하나다.
    if VoiceRecording.objects.filter(guild_id=guild_id, status="recording").exists():
        raise ServiceError({"meeting": "이 Discord 서버에서는 이미 회의가 진행 중입니다."})
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
        host=actor,
    )


def _notify_owner(rec, text: str):
    from django.conf import settings
    from django.urls import reverse

    from tasks.work_requests import notify

    note = rec.note
    link = settings.SITE_URL + reverse("org_notes", args=[note.org_id]) + f"?note={note.pk}"
    notify(note.org, f"{text} <{link}>", user=rec.host)


def speaker(org, discord_user_id: str, nick: str = "") -> dict:
    """전사 화자 표기. 계정을 연결한 조직 구성원은 PM 이름, 아니면 Discord 닉네임 + '(계정 없음)'."""
    user = resolve("discord", discord_user_id)
    if user is not None and is_member(user, org):
        return {
            "discord_user_id": discord_user_id,
            "user_id": user.pk,
            "display_name": user.display_name,
        }
    return {
        "discord_user_id": discord_user_id,
        "user_id": None,
        "display_name": f"{nick or discord_user_id}{UNLINKED_MARK}",
    }


def speaker_names(rec) -> list[dict]:
    """`/meetings/{id}/names`. 참여자 + 계정을 연결한 조직 구성원(참여자 목록이 아직 안 올라왔을 때)."""
    org = rec.note.org
    out = {
        p["discord_user_id"]: speaker(org, p["discord_user_id"], p.get("discord_name", ""))
        for p in rec.participants or []
        if p.get("discord_user_id")
    }
    linked = (
        OrgMembership.objects.filter(
            org=org, user__is_active=True, user__discord_linked_at__isnull=False
        )
        .exclude(user__discord_user_id=None)
        .values_list("user__discord_user_id", flat=True)
    )
    for did in linked:
        out.setdefault(did, speaker(org, did))
    return list(out.values())


# 전사 prompt 한도: whisper 계열 224토큰(docs/review-2026-10-04/L-voice-research.md:82).
# 토큰을 정확히 세지 않고 한글 1자=2토큰, 그 밖 3자=1토큰으로 넉넉히 잡는다.
PROMPT_TOKENS = 224
_TERM = re.compile(r"[가-힣]{2,}|[A-Za-z][A-Za-z0-9_.\-]*[A-Za-z0-9]")
_JOSA = (
    "에서",
    "으로",
    "에게",
    "까지",
    "부터",
    "을",
    "를",
    "이",
    "가",
    "은",
    "는",
    "의",
    "에",
    "로",
    "와",
    "과",
    "도",
)
_STOP = {
    "개선", "추가", "수정", "작업", "회의", "회의록", "정리", "확인", "문서", "기능", "관련",
    "진행", "제목", "없는", "주간", "검토", "요청", "처리", "변경", "적용", "테스트", "구현",
    "오류", "버그", "신규", "기존", "내용", "사항", "준비", "완료", "대응", "설정", "화면",
    "음성", "the", "and", "for", "with", "fix", "add", "update", "of", "to", "in", "on",
}  # fmt: skip


def _cost(term: str) -> float:
    return sum(2 if "가" <= c <= "힣" else 1 / 3 for c in term)


def _terms(text: str):
    for t in _TERM.findall(text or ""):
        if "가" <= t[0] <= "힣" and len(t) >= 3:
            for j in _JOSA:
                if t.endswith(j) and len(t) - len(j) >= 2:
                    t = t[: -len(j)]
                    break
        if t.lower() not in _STOP and t not in _STOP:
            yield t


def meeting_glossary(rec) -> str:
    """전사 정확도용 용어집(전사 API의 prompt). 처음 진행자(started_by)가 볼 수 있는 자료에서만
    뽑는다(결정 2-3). 진행자를 넘겨도 바꾸지 않는다 — 녹음 중 용어집이 넓어지지 않게.

    참여자 이름이 먼저, 그다음 프로젝트·마일스톤 이름(가중 2)과 문서·회의록·태스크 제목에 자주 나오는
    용어 순. 한 번만 나온 일반 용어는 뺀다.
    """
    from projects.models import Milestone, ProjectDoc
    from tasks.models import Task

    starter, org = rec.started_by, rec.note.org
    projects = visible_projects(starter, org)
    counts = Counter()
    for weight, titles in (
        (2, projects.values_list("name", flat=True)),
        (2, Milestone.objects.filter(project__in=projects).values_list("name", flat=True)),
        (1, ProjectDoc.objects.filter(project__in=projects).values_list("title", flat=True)),
        (
            1,
            # ponytail: 최근 2천 건만. 태스크가 훨씬 많아지면 집계 표를 따로 둔다
            Task.objects.filter(project__in=projects)
            .order_by("-id")
            .values_list("title", flat=True)[:2000],
        ),
        (
            1,
            visible_notes(starter)
            .filter(org=org)
            .exclude(pk=rec.note_id)
            .values_list("title", flat=True),
        ),
    ):
        for title in titles:
            for t in set(_terms(title)):
                counts[t] += weight
    names = [starter.display_name] + [
        s["display_name"].removesuffix(UNLINKED_MARK) for s in speaker_names(rec)
    ]
    picked, budget = [], PROMPT_TOKENS
    for term in dict.fromkeys(
        names + [t for t, n in counts.most_common() if n >= 2]
    ):  # 순서 유지 중복 제거
        cost = _cost(term) + 1  # 구분자 ", "
        if cost > budget:
            continue
        picked.append(term)
        budget -= cost
    return ", ".join(picked)


@transaction.atomic
def update_recording(
    rec,
    *,
    status: str | None = None,
    stopped_by=None,
    ended_at=None,
    end_reason: str = "",
    participants: list | None = None,
    transcript_md: str | None = None,
    stats: dict | None = None,
) -> VoiceRecording:
    """봇이 올리는 상태 전이·결과. 종료(transcribing)·전사문(draft)·실패. 참여자는 PM 계정으로 매핑한다."""
    rec = (
        VoiceRecording.objects.select_for_update()
        .select_related("note", "note__org", "started_by", "host")
        .get(pk=rec.pk)
    )
    note = rec.note
    if status is not None and status != rec.status:
        _close_pending(rec, "cancelled")  # 회의가 끝나면 대기 중인 넘겨받기 요청은 취소
        if status not in _NEXT.get(rec.status, set()):
            raise ServiceError({"status": f"{rec.status}에서 {status}(으)로 바꿀 수 없습니다."})
        if status == "transcribing":
            if end_reason == "command" and not (
                stopped_by is not None
                and (stopped_by.pk == rec.host_id or is_admin(stopped_by, note.org))
            ):
                raise Forbidden({"meeting": "진행자나 조직 관리자만 회의를 종료할 수 있습니다."})
            # 진행자를 넘긴 이전 진행자가 나가도 회의는 계속된다. 봇은 나간 사람을 discord_user_id로 보낸다.
            if end_reason == "host_left" and (stopped_by is None or stopped_by.pk != rec.host_id):
                raise ServiceError(
                    {"meeting": "나간 사람이 지금 진행자가 아니므로 회의를 계속합니다."}
                )
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
                f"회의록 초안(전사문)이 준비되었습니다. `/pm-meeting {note.pk}`로 정리하거나 "
                "웹에서 작성해 주세요.",
            )
        elif status == "failed":
            _notify_owner(rec, "회의록을 만들지 못했습니다. 녹음 상태를 확인해 주세요.")
    if end_reason:
        if end_reason not in dict(VoiceRecording.END_REASONS):
            raise ServiceError({"end_reason": "알 수 없는 종료 사유입니다."})
        rec.end_reason = end_reason
    if participants is not None:
        # 봇이 준 Discord 닉네임은 discord_name으로 남기고, 표시 이름·user_id는 core가 정한다.
        rows = []
        for p in participants:
            did = str(p.get("discord_user_id") or "")
            if not did:
                continue
            nick = p.get("discord_name") or p.get("display_name") or ""
            rows.append({**p, "discord_name": nick, **speaker(note.org, did, nick)})
        rec.participants = rows
        note.attendees.set([r["user_id"] for r in rows if r["user_id"]])
    if stats is not None:
        rec.stats = stats
    if transcript_md is not None:
        transcript_md = transcript_md.replace("\r\n", "\n")
        if len(transcript_md.encode()) > MAX_BODY:
            raise ServiceError({"transcript_md": "전사문이 너무 깁니다 (256KB 상한)."})
        rec.transcript_md = transcript_md
    rec.save()
    return rec


@transaction.atomic
def transfer_host(rec, *, by, to_discord_user_id: str, participants: list | None = None):
    """`/회의진행자 @참여자`. 지금 진행자만, 대상은 음성 채널에 남아 있는 계정 연결 참여자만.

    재실·연결 여부는 봇이 보낸 참여자 목록(participants, 없으면 저장된 목록) 기준이다.
    돌려주는 값: (녹음, 채널 공지 문구).
    """
    if participants is not None:
        rec = update_recording(rec, participants=participants)
    rec = (
        VoiceRecording.objects.select_for_update()
        .select_related("note", "note__org", "host")
        .get(pk=rec.pk)
    )
    if rec.status != "recording":
        raise ServiceError({"meeting": "회의가 진행 중일 때만 진행자를 넘길 수 있습니다."})
    if by is None or by.pk != rec.host_id:
        raise Forbidden({"meeting": "지금 진행자만 진행자를 넘길 수 있습니다."})
    row = _present_linked(rec, to_discord_user_id, "참여자에게만 넘길")
    if row["user_id"] == rec.host_id:
        raise ServiceError({"meeting": "이미 진행자입니다."})
    old = rec.host
    rec.host_id = row["user_id"]
    rec.host_changes = [
        *(rec.host_changes or []),
        {
            "from_user_id": old.pk,
            "to_user_id": rec.host_id,
            "by_user_id": by.pk,
            "at": timezone.now().isoformat(),
        },
    ]
    _close_pending(rec, "cancelled")  # 진행자가 바뀌면 대기 중인 넘겨받기 요청은 취소
    rec.save(update_fields=["host", "host_changes", "host_requests"])
    notice = f"회의 진행자가 {old.display_name}님에서 {row['display_name']}님으로 바뀌었습니다."
    return rec, notice


def _present_linked(rec, discord_user_id: str, verb: str) -> dict:
    """음성 채널에 남아 있고 PM 계정을 연결한 참여자 행. 봇이 보낸 참여자 목록 기준."""
    row = next(
        (
            p
            for p in rec.participants or []
            if p.get("discord_user_id") == discord_user_id and not p.get("left_at")
        ),
        None,
    )
    if row is None:
        raise ServiceError({"meeting": f"음성 채널에 있는 {verb} 수 있습니다."})
    if not row.get("user_id"):
        raise ServiceError(
            {"meeting": f"PM 계정을 연결한 {verb} 수 있습니다. 웹 설정에서 연결해 주세요."}
        )
    return row


# ---------- /회의받기: 넘겨받기 요청 (IMPL-PLAN-9 사용자 결정 3) ----------

HOST_REQUEST_TTL = timedelta(minutes=2)
HOST_REQUEST_TEXT = {
    "approve_label": "승인",
    "reject_label": "거절",
    "not_host": "지금 회의 진행자만 넘겨받기 요청을 승인하거나 거절할 수 있습니다.",
    "expired": "넘겨받기 요청이 2분 안에 응답이 없어 취소되었습니다.",
    "cancelled": "회의 진행자가 바뀌었거나 회의가 끝나 넘겨받기 요청이 취소되었습니다.",
    "pending": "이미 대기 중인 넘겨받기 요청이 있습니다. 진행자의 응답을 기다려 주세요.",
}


def _close_pending(rec, status: str, now=None):
    """대기 중인 요청을 닫는다. 만료 시각이 지났으면 status 대신 expired."""
    now = now or timezone.now()
    for r in rec.host_requests or []:
        if r["status"] == "pending":
            expired = now.isoformat() >= r["expires_at"]
            r["status"] = "expired" if expired else status
            r["closed_at"] = now.isoformat()


def _expire(rec, now) -> bool:
    """만료 시각이 지난 대기 요청을 expired로. 바뀌었으면 True."""
    changed = False
    for r in rec.host_requests or []:
        if r["status"] == "pending" and now.isoformat() >= r["expires_at"]:
            r["status"], r["closed_at"] = "expired", now.isoformat()
            changed = True
    return changed


def _locked(rec):
    return (
        VoiceRecording.objects.select_for_update()
        .select_related("note", "note__org", "host")
        .get(pk=rec.pk)
    )


@transaction.atomic
def request_host(rec, *, requester_discord_user_id: str, participants: list | None = None):
    """`/회의받기`. 돌려주는 값: (녹음, 요청, 봇 문구). 봇은 mention 문구와 버튼을 채널에 올린다."""
    if participants is not None:
        rec = update_recording(rec, participants=participants)
    rec, now = _locked(rec), timezone.now()
    if rec.status != "recording":
        raise ServiceError({"meeting": "회의가 진행 중일 때만 넘겨받기 요청을 보낼 수 있습니다."})
    row = _present_linked(rec, requester_discord_user_id, "참여자만 넘겨받기 요청을 보낼")
    if row["user_id"] == rec.host_id:
        raise ServiceError({"meeting": "이미 회의 진행자입니다."})
    if _expire(rec, now):
        rec.save(update_fields=["host_requests"])
    if any(r["status"] == "pending" for r in rec.host_requests):
        raise ServiceError({"meeting": HOST_REQUEST_TEXT["pending"]})
    req = {
        "id": len(rec.host_requests) + 1,
        "requester_user_id": row["user_id"],
        "requester_discord_user_id": requester_discord_user_id,
        "at": now.isoformat(),
        "expires_at": (now + HOST_REQUEST_TTL).isoformat(),
        "status": "pending",
    }
    rec.host_requests = [*rec.host_requests, req]
    rec.save(update_fields=["host_requests"])
    texts = {
        **HOST_REQUEST_TEXT,
        "mention": (
            f"<@{rec.host.discord_user_id}> 님, {row['display_name']}님이 넘겨받기 요청을 "
            "보냈습니다. 승인하면 회의 진행자가 바뀝니다. 2분 안에 응답해 주세요."
        ),
    }
    return rec, req, texts


def answer_host_request(rec, *, request_id: int, by_discord_user_id: str, approve: bool):
    """[승인]/[거절]. 누른 사람이 지금 진행자일 때만. 돌려주는 값: (녹음, 요청, 봇 문구)."""
    # 만료 표시는 거절(예외)로 되돌려지지 않게 먼저 따로 저장한다.
    with transaction.atomic():
        locked = _locked(rec)
        if _expire(locked, timezone.now()):
            locked.save(update_fields=["host_requests"])
    return _answer_host_request(rec, request_id, by_discord_user_id, approve)


@transaction.atomic
def _answer_host_request(rec, request_id, by_discord_user_id, approve):
    rec, now = _locked(rec), timezone.now()
    req = next((r for r in rec.host_requests or [] if r["id"] == request_id), None)
    if req is None:
        raise ServiceError({"meeting": "넘겨받기 요청을 찾을 수 없습니다."})
    if req["status"] != "pending":
        key = req["status"] if req["status"] in ("expired", "cancelled") else None
        raise ServiceError(
            {"meeting": HOST_REQUEST_TEXT[key] if key else "이미 응답한 넘겨받기 요청입니다."}
        )
    by = resolve("discord", by_discord_user_id)
    if by is None or by.pk != rec.host_id:
        raise Forbidden({"meeting": HOST_REQUEST_TEXT["not_host"]})
    texts = {}
    if approve:
        # 넘김 규칙·이력·채널 공지는 /회의진행자와 같다. 넘기면서 대기 요청은 cancelled가 되므로 다시 쓴다.
        rec, texts["channel_notice"] = transfer_host(
            rec, by=by, to_discord_user_id=req["requester_discord_user_id"]
        )
    req = next(r for r in rec.host_requests if r["id"] == request_id)
    req.update(
        status="approved" if approve else "rejected",
        responded_by_user_id=by.pk,
        responded_at=now.isoformat(),
    )
    req.pop("closed_at", None)
    rec.save(update_fields=["host_requests"])
    if not approve:
        texts["requester_notice"] = f"{by.display_name}님이 넘겨받기 요청을 거절했습니다."
    return rec, req, texts
