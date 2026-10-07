"""notes 0004: 회의록 → Doc(kind="meeting") 이전 전후 데이터 보존."""

from datetime import UTC, datetime

import pytest
from django.db import connection
from django.db.migrations.executor import MigrationExecutor

from accounts.models import User
from orgs.models import Organization, Team
from projects.models import Project

BEFORE = [("notes", "0003_voice_recording")]
AFTER = [("notes", "0006_merge_into_doc_cleanup")]
T0 = datetime(2026, 9, 1, 3, 0, tzinfo=UTC)


@pytest.mark.django_db(transaction=True)
def test_meeting_notes_move_into_docs(pg_flushable):
    ex = MigrationExecutor(connection)
    ex.migrate(BEFORE)
    old = ex.loader.project_state(BEFORE).apps
    try:
        # 다른 앱 표는 최신 상태 그대로라 지금 모델로 만든다. 옛 모델은 notes만.
        host = User.objects.create_user("h0", password="pw12345678", display_name="진행자")
        guest = User.objects.create_user("g0", password="pw12345678", display_name="참여자")
        org = Organization.objects.create(name="조직", created_by=host)
        team = Team.objects.create(org=org, name="팀", created_by=host)
        open_p = Project.objects.create(org=org, name="공개", created_by=host)
        closed_p = Project.objects.create(
            org=org, name="비공개", created_by=host, visibility="teams"
        )
        from tasks.models import Task

        task = Task.objects.create(project=open_p, title="일", created_by=host, assignee=host)
        Note = old.get_model("notes", "MeetingNote")
        Rec = old.get_model("notes", "VoiceRecording")
        n1 = Note.objects.create(
            org_id=org.pk,
            project_id=open_p.pk,
            status="draft",
            source="voice",
            title="음성 회의",
            body_md="전사 초안",
            version=4,
            created_on=T0,
            tags=["주간"],
            created_by_id=host.pk,
        )
        Note.objects.filter(pk=n1.pk).update(created_at=T0, updated_at=T0)
        n1.tasks.add(task.pk)
        n1.attendees.add(host.pk, guest.pk)
        Rec.objects.create(
            note_id=n1.pk,
            guild_id="g",
            voice_channel_id="v",
            started_by_id=host.pk,
            host_id=guest.pk,
            transcript_md="안녕",
        )
        # 공개 범위가 둘 다인 옛 행(프로젝트 ∩ 팀). 이전은 이런 행이 있으면 아무것도 바꾸지 않고 멈춘다.
        n2 = Note.objects.create(
            org_id=org.pk,
            project_id=open_p.pk,
            team_id=team.pk,
            title="둘 다",
            created_by_id=host.pk,
        )
        n3 = Note.objects.create(
            org_id=org.pk,
            project_id=closed_p.pk,
            team_id=team.pk,
            title="비공개 둘 다",
            created_by_id=host.pk,
        )

        with pytest.raises(RuntimeError, match="둘 다 지정된 회의록이 2건"):
            MigrationExecutor(connection).migrate(AFTER)
        assert MigrationExecutor(connection).loader.applied_migrations.get(AFTER[0]) is None
        assert Note.objects.count() == 3  # 아무것도 바뀌지 않았다

        # 관리자 결정: n2는 팀만, n3는 프로젝트만 남긴다. 그 뒤에는 그대로 옮겨진다.
        Note.objects.filter(pk=n2.pk).update(project=None)
        Note.objects.filter(pk=n3.pk).update(team=None)
        ex = MigrationExecutor(connection)
        ex.migrate(AFTER)
        from notes.models import MeetingNote, VoiceRecording

        assert MeetingNote.objects.count() == 3
        d1 = MeetingNote.objects.get(title="음성 회의")
        assert (d1.kind, d1.status, d1.source, d1.version) == ("meeting", "draft", "voice", 4)
        assert (d1.project_id, d1.body_md, d1.tags) == (open_p.pk, "전사 초안", ["주간"])
        assert (d1.created_on, d1.created_at, d1.created_by_id) == (T0, T0, host.pk)
        assert list(d1.tasks.all()) == [task]
        assert set(d1.attendees.all()) == {host, guest}
        rec = VoiceRecording.objects.get()
        assert rec.note_id == d1.pk and rec.host == guest and rec.transcript_md == "안녕"
        assert d1.recording == rec and d1.revisions.get().version == 4
        assert [d.pk for d in task.docs.all()] == [d1.pk]
        d2 = MeetingNote.objects.get(title="둘 다")
        assert (d2.project_id, d2.team_id) == (None, team.pk)
        d3 = MeetingNote.objects.get(title="비공개 둘 다")
        assert (d3.project_id, d3.team_id) == (closed_p.pk, None)
    finally:
        from projects.models import Doc

        Doc.objects.filter(kind="meeting", is_template=False).delete()
        ex = MigrationExecutor(connection)
        ex.migrate(ex.loader.graph.leaf_nodes())
