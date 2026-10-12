import logging
import re
from collections import Counter
from datetime import timedelta

from django.db import transaction
from django.utils import timezone

from accounts.identity import resolve
from common.dates import now_kst
from common.errors import Forbidden, ServiceError
from orgs import settings as org_settings
from orgs.models import Organization, OrgMembership
from orgs.services import ai_denied, is_admin, is_member, visible_teams
from projects import docs
from projects.services import can_view_project, visible_projects

from .models import MeetingNote, VoiceRecording, VoiceTrack

log = logging.getLogger(__name__)

MAX_BODY = 256 * 1024  # 256KB. 회의록 한 편이 이보다 클 이유가 없다.


def visible_notes(user):
    """회의록 가시성 관문 = 문서 관문(projects.docs.visible_docs)을 회의록만으로 거른 것.

    확정(final): 프로젝트 회의록은 그 프로젝트를, 팀 회의록은 그 팀을 볼 수 있을 때만(IMPL-PLAN-7 F).
    초안(draft, 음성 회의): 지금 진행자(recording.host)와 조직 관리자만(IMPL-PLAN-9 결정 2-5).
    """
    return docs.visible_docs(user, model=MeetingNote)


def get_visible_note(user, note_id: int):
    return (
        visible_notes(user)
        .select_related("project", "created_by", "org")
        .filter(pk=note_id)
        .first()
    )


def _check_project(org, project, actor):
    if project is not None and project.org_id != org.pk:
        raise ServiceError(
            {
                "project": "다른 조직의 프로젝트는 선택할 수 없습니다. 같은 조직의 프로젝트를 선택해 주세요."
            }
        )
    if project is not None and not can_view_project(actor, project):
        raise ServiceError(
            {
                "project": "프로젝트를 볼 권한이 없습니다. 프로젝트 관리자에게 접근 권한을 요청해 주세요."
            }
        )


def create_note(
    *, org, actor, title="제목 없는 회의록", project=None, body_md="", created_on=None, tags=None
):
    """웹·API에서 만든 회의록은 처음부터 확정(final)이다. 만들기는 문서 서비스가 한다."""
    if not is_member(actor, org):
        raise ServiceError({"org": "이 조직에 속해 있지 않아 작업할 수 없습니다."})
    return docs.create_doc(
        org=org,
        actor=actor,
        kind="meeting",
        title=title,
        project=project,
        body_md=body_md,
        created_on=created_on,
        tags=tags,
    )


def _is_owner(note, user) -> bool:
    """초안을 다룰 수 있는 사람: 지금 진행자·조직 관리자. 녹음 없는 회의록은 작성자."""
    rec = getattr(note, "recording", None)
    who = rec.host_id if rec is not None else note.created_by_id
    return who == user.pk or is_admin(user, note.org)


def _check_edit(note, actor, source: str):
    if not is_member(actor, note.org):
        raise ServiceError({"org": "이 조직에 속해 있지 않아 작업할 수 없습니다."})
    if note.status == "draft" and not _is_owner(note, actor):
        raise Forbidden({"note": "초안은 진행자나 조직 관리자만 고칠 수 있습니다."})
    # AI 편집은 태스크 본문과 같은 정책(ai.edit_text)을 탄다. 새 키를 만들지 않는다.
    if source == "mcp" and (
        not org_settings.effective("ai.enabled", org=note.org)
        or org_settings.effective("ai.edit_text", org=note.org) == "deny"
    ):
        raise Forbidden({"ai": ai_denied("회의록 고치기")})


def update_note(note, field: str, value, *, actor, expected_version: int, source: str = "web"):
    """한 번에 한 항목. 버전이 다르면 ConflictError(최신 객체). 초안 규칙을 먼저 보고 문서 서비스로 넘긴다."""
    _check_edit(note, actor, source)
    return docs.update_doc(
        note, field, value, actor=actor, expected_version=expected_version, source=source
    )


def upload_note(*, org, actor, filename: str, raw: bytes, project=None):
    """.md 본문 텍스트만 읽어 새 회의록을 만든다. 파일은 저장하지 않는다."""
    if not is_member(actor, org):
        raise ServiceError({"org": "이 조직에 속해 있지 않아 작업할 수 없습니다."})
    return docs.upload_doc(
        org=org, actor=actor, filename=filename, raw=raw, kind="meeting", project=project
    )


def delete_note(note, actor):
    """작성자 본인이거나 조직 관리자만."""
    if note.status == "draft":
        if not _is_owner(note, actor):
            raise ServiceError(
                {
                    "note": "회의록 초안은 진행자나 조직 관리자만 삭제할 수 있습니다. 해당 담당자에게 삭제를 요청해 주세요."
                }
            )
    elif note.created_by_id != actor.pk and not is_admin(actor, note.org):
        raise ServiceError(
            {
                "note": "작성자나 조직 관리자만 삭제할 수 있습니다. 해당 담당자에게 삭제를 요청해 주세요."
            }
        )
    note.delete()


def link_task(note, task, actor, source: str = "web"):
    _check_edit(note, actor, source)
    if task.project.org_id != note.org_id:
        raise ServiceError(
            {"task": "다른 조직의 태스크는 연결할 수 없습니다. 같은 조직의 태스크를 선택해 주세요."}
        )
    note.tasks.add(task)


def unlink_task(note, task, actor):
    if not is_member(actor, note.org):
        raise ServiceError({"org": "이 조직에 속해 있지 않아 작업할 수 없습니다."})
    note.tasks.remove(task)


@transaction.atomic
def finalize_note(note, *, actor, source: str, project=None, team=None) -> MeetingNote:
    """초안 확정. 공개 범위는 프로젝트·팀·조직 공통(둘 다 None) 중 하나. 확정은 사람이 웹에서 한다."""
    if source == "mcp":
        raise Forbidden({"ai": "회의록 확정은 웹 회의록 화면에서 사람이 합니다."})
    if note.status != "draft":
        raise ServiceError(
            {"note": "이미 확정된 회의록입니다. 내용을 바꾸려면 회의록을 수정해 주세요."}
        )
    if not _is_owner(note, actor):
        raise Forbidden({"note": "진행자나 조직 관리자만 확정할 수 있습니다."})
    rec = getattr(note, "recording", None)
    if rec is not None and rec.status in ("recording", "transcribing"):
        raise ServiceError(
            {
                "note": "녹음·전사가 진행 중이라 확정할 수 없습니다. 작업이 끝난 뒤 회의록을 확정해 주세요."
            }
        )
    if project is not None and team is not None:
        raise ServiceError(
            {"scope": "프로젝트와 팀을 함께 선택할 수 없습니다. 공개 범위를 하나만 선택해 주세요."}
        )
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
        raise ServiceError(
            {"team": "팀을 볼 권한이 없습니다. 조직 관리자에게 팀 참여를 요청해 주세요."}
        )


def meeting_scope(*, org, actor, project=None, team=None) -> dict:
    """녹음을 시작해도 되는가. 되면 봇이 쓸 실효 설정을 돌려준다(아니면 ServiceError/Forbidden)."""
    if not is_member(actor, org):
        raise Forbidden({"org": "이 조직에 속해 있지 않아 작업할 수 없습니다."})
    if project is not None and team is not None:
        raise ServiceError(
            {"scope": "프로젝트와 팀을 함께 선택할 수 없습니다. 공개 범위를 하나만 선택해 주세요."}
        )
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
    # 봇은 길드당 음성 연결 하나다. 동시에 온 시작 요청은 조직 행 잠금으로 줄 세운다(길드 ↔ 조직 1:1).
    Organization.objects.select_for_update().filter(pk=org.pk).first()
    if VoiceRecording.objects.filter(guild_id=guild_id, status="recording").exists():
        raise ServiceError(
            {
                "meeting": "이 Discord 서버에서는 이미 회의가 진행 중입니다. 현재 회의를 종료한 뒤 새 회의를 시작해 주세요."
            }
        )
    now = now_kst()
    note = MeetingNote.objects.create(
        org=org,
        project=project,
        team=team,
        title=(title or "").strip()[:200] or f"{now:%m월 %d일} 음성 회의",
        created_on=now,
        created_by=actor,
        updated_by=actor,
        status="draft",
        origin="voice",
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
    from projects.models import Doc, Milestone
    from tasks.models import Task

    starter, org = rec.started_by, rec.note.org
    projects = visible_projects(starter, org)
    counts = Counter()
    for weight, titles in (
        (2, projects.values_list("name", flat=True)),
        (2, Milestone.objects.filter(project__in=projects).values_list("name", flat=True)),
        (
            1,
            Doc.objects.filter(project__in=projects, kind="doc").values_list("title", flat=True),
        ),
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
    segments: list | None = None,
) -> VoiceRecording:
    """봇이 올리는 상태 전이·결과. 종료(transcribing)·전사문(draft)·실패. 참여자는 PM 계정으로 매핑한다.

    전사문은 `rec.transcript_md`(현재 전사문)와 전사 작업에만 둔다. 회의록 본문에는 정리용 틀만 넣는다.
    """
    from . import transcription

    started_job = False
    rec = (
        VoiceRecording.objects.select_for_update()
        .select_related("note", "note__org", "started_by", "host")
        .get(pk=rec.pk)
    )
    note = rec.note
    if status is not None and status != rec.status:
        _close_pending(rec, "cancelled")  # 회의가 끝나면 대기 중인 넘겨받기 요청은 취소
        if status not in _NEXT.get(rec.status, set()):
            log.warning("녹음 %s 상태 전이 거절: %s → %s", rec.pk, rec.status, status)
            raise ServiceError(
                {
                    "status": "현재 녹음 상태에서는 요청한 상태로 바꿀 수 없습니다. 녹음 상태를 다시 확인해 주세요."
                }
            )
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
            started_job = True
        if status == "failed" and not rec.ended_at:
            rec.ended_at = ended_at or timezone.now()
        rec.status = status
        if status == "draft":
            if not note.body_md.strip():
                note.body_md = DRAFT_BODY.format(id=note.pk)
                note.version += 1
                note.save(update_fields=["body_md", "version", "updated_at"])
            engine = (stats if stats is not None else rec.stats or {}).get("engine")
            _notify_owner(
                rec,
                # 녹음만(전사 수단 없음, IMPL-PLAN-9-parallel §7). 실패가 아니다.
                "회의록 초안이 준비된 상태입니다. 녹음 파일은 회의록 화면에서 내려받아 직접 전사해 주세요."
                if engine == "none"
                else f"회의록 초안과 전사문이 준비된 상태입니다. `/pm-meeting {note.pk}`로 정리하거나 "
                "웹에서 작성해 주세요.",
            )
        elif status == "failed":
            _notify_owner(rec, "회의록을 만들지 못했습니다. 녹음 상태를 확인해 주세요.")
    if end_reason:
        if end_reason not in dict(VoiceRecording.END_REASONS):
            raise ServiceError(
                {"end_reason": "종료 사유가 올바르지 않습니다. 지원하는 종료 사유를 선택해 주세요."}
            )
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
            raise ServiceError(
                {
                    "transcript_md": "전사문이 용량 한도 256KB를 넘었습니다. 전사문을 줄여 다시 보내 주세요."
                }
            )
        rec.transcript_md = transcript_md
    if segments is not None:
        rec.segments = transcription.clean_segments(segments)
    rec.save()
    if started_job:
        transcription.start_auto_job(rec)
    if status == "draft":
        transcription.finish_auto_job(rec, transcript_md=transcript_md, stats=stats)
    elif status == "failed":
        transcription.fail_active(rec)
    return rec


AUDIO_MAX_BYTES = 300 * 1024 * 1024  # IMPL-PLAN-9-parallel §7
AUDIO_EXPIRED = "보관 기간이 지나 녹음 파일이 삭제된 상태입니다."


def audio_expired(rec) -> bool:
    return rec.audio_expires_at is not None and rec.audio_expires_at <= timezone.now()


def _is_ogg_opus(upload) -> bool:
    """Ogg Opus인가(stdlib만, RFC 3533·7845). 페이지를 처음부터 끝까지 걸어가며 본다.

    모든 페이지: `OggS`·버전 0, 세그먼트 표로 잰 길이가 빈틈·쓰레기 없이 파일 끝에 정확히 닿는다.
    BOS는 첫 페이지에만, EOS는 마지막 페이지에. 첫 페이지 = OpusHead 패킷 하나(19바이트 이상·
    버전 1·채널 1 이상), 둘째 페이지는 OpusTags로 시작. 본문은 첫 두 페이지만 읽고 나머지는 건너뛴다.
    ponytail: CRC는 보지 않는다. 손상된 본문까지 잡아야 하면 페이지 CRC32를 더한다."""
    size, pos, page, flags = upload.size, 0, 0, 0
    upload.seek(0)
    try:
        while pos < size:
            head = upload.read(27)
            if len(head) < 27 or head[:4] != b"OggS" or head[4] != 0:
                return False
            flags = head[5]
            if bool(flags & 0x02) != (page == 0):  # BOS
                return False
            table = upload.read(head[26])
            if len(table) != head[26]:
                return False
            body_len = sum(table)
            pos += 27 + len(table) + body_len
            if pos > size:
                return False
            if page == 0:
                body = upload.read(body_len)
                # OpusHead는 첫 페이지에 혼자, 그 페이지에서 끝난다(마지막 세그먼트 < 255)
                if not (
                    table
                    and table[-1] < 255
                    and len(body) >= 19
                    and body[:8] == b"OpusHead"
                    and body[8] == 1
                    and body[9] >= 1
                ):
                    return False
            elif page == 1:
                if upload.read(8) != b"OpusTags":
                    return False
                upload.seek(pos)
            else:
                upload.seek(pos)
            page += 1
        return page >= 2 and bool(flags & 0x04)  # EOS
    finally:
        upload.seek(0)


@transaction.atomic
def save_audio(rec, upload, discord_user_id: str | None = None):
    """봇이 올린 혼합 녹음(Ogg), discord_user_id가 있으면 그 참여자의 트랙(VoiceTrack).
    같은 대상에 다시 올리면 바꾼다. 옛 파일은 커밋 뒤에 지운다."""
    if upload.size > AUDIO_MAX_BYTES:
        raise ServiceError({"file": "녹음 파일의 크기 제한은 300MB입니다."})
    if not _is_ogg_opus(upload):
        raise ServiceError({"file": "올릴 수 있는 녹음 파일 형식은 Ogg입니다."})
    if discord_user_id is None:
        rec = VoiceRecording.objects.select_for_update().select_related("note").get(pk=rec.pk)
    else:
        if not 0 < len(discord_user_id) <= 32:
            raise ServiceError({"discord_user_id": "Discord 사용자 ID가 올바르지 않습니다."})
        rec = VoiceTrack.objects.select_for_update().get_or_create(
            recording=rec, discord_user_id=discord_user_id
        )[0]
    old = rec.audio.name
    rec.audio.save("meeting.ogg", upload, save=False)
    rec.audio_size = upload.size
    rec.save(update_fields=["audio", "audio_size"])
    if old:
        storage = rec.audio.storage
        transaction.on_commit(lambda: storage.delete(old))
    return rec


def purge_expired_audio() -> int:
    """보관 기간(audio_expires_at)이 지난 녹음 파일을 지운다. audio_size는 남긴다(화면의 "삭제함" 표시)."""
    storage = VoiceRecording._meta.get_field("audio").storage
    n = 0
    for rec in VoiceRecording.objects.filter(audio_expires_at__lte=timezone.now()).exclude(
        audio=""
    ):
        storage.delete(rec.audio.name)
        VoiceRecording.objects.filter(pk=rec.pk).update(audio="")
        n += 1
    for t in VoiceTrack.objects.filter(recording__audio_expires_at__lte=timezone.now()).exclude(
        audio=""
    ):
        storage.delete(t.audio.name)
        VoiceTrack.objects.filter(pk=t.pk).update(audio="")
    return n


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
        raise ServiceError(
            {
                "meeting": "진행 중인 회의가 없어 진행자를 변경할 수 없습니다. 회의를 시작한 뒤 다시 요청해 주세요."
            }
        )
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
        raise ServiceError(
            {
                "meeting": f"음성 채널에 있는 {verb} 수 있습니다. 해당 음성 채널에 참여한 뒤 다시 요청해 주세요."
            }
        )
    if not row.get("user_id"):
        raise ServiceError(
            {"meeting": f"유달리 계정을 연결한 {verb} 수 있습니다. 웹 설정에서 연결해 주세요."}
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
        raise ServiceError(
            {
                "meeting": "진행 중인 회의가 없어 넘겨받기를 요청할 수 없습니다. 회의를 시작한 뒤 다시 요청해 주세요."
            }
        )
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
        raise ServiceError(
            {"meeting": "넘겨받기 요청을 찾지 못했습니다. 요청 목록을 새로 확인해 주세요."}
        )
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
