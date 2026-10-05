from django.conf import settings
from django.db import models


class MeetingNote(models.Model):
    org = models.ForeignKey("orgs.Organization", on_delete=models.CASCADE, related_name="notes")
    # 프로젝트가 없으면 "팀 공통" 회의록이다.
    project = models.ForeignKey(
        "projects.Project", on_delete=models.SET_NULL, null=True, blank=True, related_name="notes"
    )
    # 팀 회의록. 확정 뒤에도 그 팀을 볼 수 있는 사람(visible_teams)에게만 보인다.
    team = models.ForeignKey(
        "orgs.Team", on_delete=models.SET_NULL, null=True, blank=True, related_name="notes"
    )
    # 음성 회의 초안(draft)은 시작자·조직 관리자만 본다. 웹에서 만든 회의록은 처음부터 final이다.
    status = models.CharField(
        max_length=10, choices=[("draft", "초안"), ("final", "확정")], default="final"
    )
    source = models.CharField(
        max_length=10, choices=[("web", "웹"), ("voice", "음성 회의")], default="web"
    )
    title = models.CharField("제목", max_length=200, default="제목 없는 회의록")
    body_md = models.TextField("본문", blank=True)
    # 회의 날짜+시각. 사용자가 고치고 비워 둘 수도 있다. created_at(기록 시각)과 다르다.
    created_on = models.DateTimeField("회의 일시", null=True, blank=True)
    # 자유 태그. OrgMembership.tags(스킬 태그)와 같은 방식 — 새 표 없이 문자열 목록 하나.
    tags = models.JSONField(default=list, blank=True)
    version = models.PositiveIntegerField(default=1)
    # related_name="notes"는 Task.notes(진행 메모 텍스트 필드)와 이름이 부딪힌다.
    tasks = models.ManyToManyField("tasks.Task", blank=True, related_name="meeting_notes")
    created_by = models.ForeignKey(
        settings.AUTH_USER_MODEL, on_delete=models.PROTECT, related_name="+"
    )
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        ordering = ["-created_on", "-id"]

    def __str__(self):
        return self.title


class VoiceRecording(models.Model):
    """Discord 음성 회의 녹음 한 번(IMPL-PLAN-9 v1 §3.1, v2 §5). 오디오 파일은 core에 두지 않는다."""

    STATUSES = [
        ("recording", "녹음 중"),
        ("transcribing", "전사 중"),
        ("draft", "초안"),
        ("done", "확정"),
        ("failed", "실패"),
    ]
    END_REASONS = [
        ("command", "종료 명령"),
        ("starter_left", "시작자 퇴장"),
        ("max_length", "최대 길이"),
        ("empty", "모두 퇴장"),
        ("restart", "봇 재시작"),
        ("failed", "실패"),
    ]

    note = models.OneToOneField(MeetingNote, on_delete=models.CASCADE, related_name="recording")
    guild_id = models.CharField(max_length=32)
    voice_channel_id = models.CharField(max_length=32)
    started_by = models.ForeignKey(
        settings.AUTH_USER_MODEL, on_delete=models.PROTECT, related_name="+"
    )
    # /회의_이어가기로 바뀐다. 초안 열람·편집·종료 권한은 시작자와 이 사람이 같이 갖는다.
    current_owner = models.ForeignKey(
        settings.AUTH_USER_MODEL, on_delete=models.PROTECT, related_name="+"
    )
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
