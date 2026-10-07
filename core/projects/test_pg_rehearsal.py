"""라운드 11·12 마이그레이션 리허설(Postgres 전용). 운영과 비슷한 "라운드 시작 상태"를 만들고 HEAD까지 migrate.

SQLite는 FK를 즉시 검사해서 "pending trigger events"(같은 트랜잭션의 DML 뒤 DDL)를 못 잡는다(Fable S §3.1).
그래서 이 테스트는 DATABASE_URL이 Postgres일 때만 돈다. 실행: scripts/pg-migrate-rehearsal.sh (Docker).
"""

import pytest
from django.db import connection
from django.db.migrations.executor import MigrationExecutor

from accounts.models import User
from orgs.models import Organization, OrgMembership, Team

PG = connection.vendor == "postgresql"
# 라운드 11 시작 직전(운영 ba4c3a1 이후) 상태.
BEFORE = [
    ("projects", "0011_milestone_gh_number"),
    ("tasks", "0009_task_status_since"),
    ("notes", "0003_voice_recording"),
]


@pytest.mark.skipif(
    not PG, reason="Postgres 전용 리허설(DATABASE_URL=postgres…, scripts/pg-migrate-rehearsal.sh)"
)
@pytest.mark.django_db(transaction=True)
def test_round11_migrations_on_postgres_with_data(pg_flushable):
    ex = MigrationExecutor(connection)
    ex.migrate(BEFORE)
    old = MigrationExecutor(connection).loader.project_state(BEFORE).apps
    P = old.get_model("projects", "Project")
    PD = old.get_model("projects", "ProjectDoc")
    T = old.get_model("tasks", "Task")
    CL = old.get_model("tasks", "ChangeLog")
    Att = old.get_model("tasks", "Attachment")
    N = old.get_model("notes", "MeetingNote")
    R = old.get_model("notes", "VoiceRecording")

    a = User.objects.create_user("pg-a", password="pw12345678", display_name="관리")
    b = User.objects.create_user("pg-b", password="pw12345678", display_name="멤버")
    orgs = [Organization.objects.create(name=f"조직{i}", created_by=a) for i in (1, 2)]
    org = orgs[0]
    OrgMembership.objects.create(org=org, user=a, role="admin")
    OrgMembership.objects.create(org=org, user=b, role="member")
    team = Team.objects.create(org=org, name="팀", created_by=a)
    p1 = P.objects.create(org_id=org.pk, name="P1", created_by_id=a.pk)
    p2 = P.objects.create(org_id=org.pk, name="P2", created_by_id=a.pk, visibility="teams")
    tasks = [
        T.objects.create(project_id=p1.pk, title=f"일{i}", created_by_id=a.pk, assignee_id=b.pk)
        for i in range(4)
    ]
    # S1 '사람별로 나누기' 이력(tasks 0012 데이터 이전 대상)
    for t in tasks[1:3]:
        T.objects.filter(pk=t.pk).update(parent_id=tasks[0].pk)
    CL.objects.create(
        target_type="task",
        target_id=tasks[0].pk,
        field="split",
        new_value=f"TASK-{tasks[1].pk},TASK-{tasks[2].pk}",
        source="web",
        actor_id=a.pk,
    )
    docs = [
        PD.objects.create(
            project_id=p.pk, title=f"문서{p.name}", body_md="본문", created_by_id=a.pk
        )
        for p in (p1, p2)
    ]
    docs[0].tasks.add(tasks[0].pk)
    notes = [
        N.objects.create(org_id=org.pk, title="확정", created_by_id=a.pk, project_id=p1.pk),
        N.objects.create(org_id=org.pk, title="팀", created_by_id=a.pk, team_id=team.pk),
        N.objects.create(org_id=org.pk, title="공통", created_by_id=b.pk, tags=["주간"]),
        N.objects.create(
            org_id=org.pk, title="음성", created_by_id=a.pk, status="draft", source="voice"
        ),
    ]
    notes[0].tasks.add(tasks[1].pk)
    notes[3].attendees.add(a.pk, b.pk)
    R.objects.create(
        note_id=notes[3].pk, guild_id="g", voice_channel_id="v", started_by_id=a.pk, host_id=b.pk
    )
    Att.objects.create(
        project_id=p1.pk,
        file="att/1/a.png",
        name="a.png",
        size=1,
        content_type="image/png",
        sha256="0" * 64,
        created_by_id=a.pk,
    )
    Att.objects.create(
        task_id=tasks[0].pk,
        file="att/1/b.pdf",
        name="b.pdf",
        size=1,
        content_type="application/pdf",
        sha256="0" * 64,
        created_by_id=a.pk,
    )

    try:
        ex = MigrationExecutor(connection)
        ex.migrate(ex.loader.graph.leaf_nodes())  # 운영의 entrypoint migrate와 같다

        from notes.models import VoiceRecording
        from projects.models import Doc, DocRevision
        from tasks.models import Attachment, Task

        meetings = Doc.objects.filter(kind="meeting", is_template=False)
        plain = Doc.objects.filter(kind="doc", is_template=False)
        assert meetings.count() == len(notes)
        assert sorted(plain.values_list("pk", "title", "org_id")) == sorted(
            (d.pk, d.title, org.pk) for d in docs
        )
        assert DocRevision.objects.count() == Doc.objects.filter(is_template=False).count()
        for o in orgs:
            assert Doc.objects.filter(org=o, is_template=True).count() == 2
        assert not Doc.objects.filter(org__isnull=True).exists()
        voice = meetings.get(title="음성")
        assert (voice.status, voice.origin, voice.attendees.count()) == ("draft", "voice", 2)
        rec = VoiceRecording.objects.get()
        assert rec.note_id == voice.pk and rec.host_id == b.pk
        assert list(meetings.get(title="확정").tasks.values_list("pk", flat=True)) == [tasks[1].pk]
        assert meetings.get(title="팀").team_id == team.pk
        assert list(Doc.objects.get(pk=docs[0].pk).tasks.values_list("pk", flat=True)) == [
            tasks[0].pk
        ]
        assert Attachment.objects.count() == 2
        assert set(Task.objects.filter(group_id=tasks[0].pk).values_list("pk", flat=True)) == {
            tasks[1].pk,
            tasks[2].pk,
        }
    finally:
        from projects.models import Doc

        # 다음 테스트를 위해 비운다(TransactionTestCase가 flush하지만 회의록 역이전 거부를 피한다).
        Doc.objects.all().delete()
