from django.conf import settings
from django.db import models

from projects.models import Doc


class MeetingNoteManager(models.Manager):
    def get_queryset(self):
        return super().get_queryset().filter(kind="meeting", is_template=False)


class MeetingNote(Doc):
    """회의록 = kind="meeting"인 문서(IMPL-PLAN-11 §4.3). 표는 projects.Doc 하나다.

    옛 이름과 정렬(회의 일시 역순)을 유지하는 프록시. 편집·이전 버전·백링크는 projects.docs가 맡고
    회의 고유 규칙(음성 회의·진행자·초안/확정·참여자)은 notes.services에 남는다.
    """

    objects = MeetingNoteManager()

    class Meta:
        proxy = True
        ordering = ["-created_on", "-id"]

    def save(self, *args, **kwargs):
        self.kind = "meeting"
        if self._state.adding and self.title == "제목 없는 문서":
            self.title = "제목 없는 회의록"
        super().save(*args, **kwargs)


class VoiceRecording(models.Model):
    """회의 한 번의 녹음(IMPL-PLAN-9 v1 §3.1, v2 §5). 오디오 파일은 core에 두지 않는다."""

    STATUSES = [
        ("recording", "녹음 중"),
        ("transcribing", "전사 중"),
        ("draft", "초안"),
        ("done", "확정"),
        ("failed", "실패"),
    ]
    END_REASONS = [
        ("command", "/회의종료"),
        ("host_left", "진행자 퇴장"),
        ("max_length", "최대 길이"),
        ("empty", "모두 퇴장"),
        ("restart", "봇 재시작"),
        ("failed", "실패"),
    ]

    # 회의록 문서(kind="meeting"). 문서 쪽에서는 doc.recording.
    note = models.OneToOneField("projects.Doc", on_delete=models.CASCADE, related_name="recording")
    guild_id = models.CharField(max_length=32)
    voice_channel_id = models.CharField(max_length=32)
    started_by = models.ForeignKey(
        settings.AUTH_USER_MODEL, on_delete=models.PROTECT, related_name="+"
    )
    # 진행자. /회의진행자로 넘어간다. 초안 열람·편집·종료·확정은 지금 진행자와 조직 관리자만 한다.
    host = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.PROTECT, related_name="+")
    # 진행자 넘김 이력 [{from_user_id, to_user_id, by_user_id, at}]
    host_changes = models.JSONField(default=list, blank=True)
    # /회의받기 넘겨받기 요청. 대기(pending)는 회의당 하나.
    # [{id, requester_user_id, requester_discord_user_id, at, expires_at, status, responded_by_user_id, responded_at}]
    # status: pending | approved | rejected | expired | cancelled
    host_requests = models.JSONField(default=list, blank=True)
    started_at = models.DateTimeField(auto_now_add=True)
    ended_at = models.DateTimeField(null=True, blank=True)
    end_reason = models.CharField(max_length=20, choices=END_REASONS, blank=True)
    status = models.CharField(max_length=20, choices=STATUSES, default="recording")
    # [{discord_user_id, display_name, user_id|null, joined_at, left_at}]
    participants = models.JSONField(default=list, blank=True)
    transcript_md = models.TextField(blank=True)
    # {segments, skipped, decrypt_failures, transcribe_failed, engines: [{engine, host, model, segments, failed}]}
    stats = models.JSONField(default=dict, blank=True)
    audio_expires_at = models.DateTimeField(null=True, blank=True)

    def __str__(self):
        return f"녹음 #{self.pk}"
