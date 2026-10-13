"""작업 만들기·조회·취소·적용(IMPL-PLAN-12 §4·§5.2·§7.3·§10)."""

from datetime import timedelta

import pytest
from django.http import Http404
from django.utils import timezone

from assist import services as svc
from assist.models import AiJob
from common.errors import ConflictError, ServiceError
from notes.models import VoiceRecording
from orgs.services import create_org
from projects.docs import create_doc
from projects.models import Doc
from projects.services import create_project
from tasks.services import create_task


def org_ai(org, **extra):
    org.settings = {
        **(org.settings or {}),
        "assist.org_url": "https://ai.example.com/v1",
        "assist.org_model": "m",
        **extra,
    }
    org.save(update_fields=["settings"])


def make(user, org, field="task.title", target=None, **kw):
    return svc.create_job(user, org, field=field, target=target, **kw)


@pytest.fixture
def on(org):
    org_ai(org)
    return org


def test_create_ok(on, member, task):
    job = make(member, on, target=f"task:{task.pk}", user_input="x" * 9000)
    assert (job.kind, job.status, job.route, job.target_type) == ("field", "queued", "org", "task")
    assert len(job.user_input) == AiJob.MAX_INPUT


def test_create_refusals(on, member, outsider, task):
    t = f"task:{task.pk}"
    with pytest.raises(Http404):
        make(outsider, on, target=t)  # 구성원 아님
    with pytest.raises(ServiceError):
        make(member, on, field="secret.token", target=t)  # 등록표 밖
    with pytest.raises(ServiceError):
        make(member, on, field="doc.title", target=t)  # 칸이 받지 않는 대상 종류
    with pytest.raises(Http404):
        make(member, on, target="task:999999")
    with pytest.raises(Http404):
        make(member, on, target="secret:1")
    org_ai(on, **{"assist.enabled": False})
    with pytest.raises(ServiceError) as e:
        make(member, on, target=t)
    assert e.value.errors == {"assist": "org_disabled"}


def test_no_source(org, member, task):
    with pytest.raises(ServiceError) as e:
        make(member, org, target=f"task:{task.pk}")  # 조직 AI 미설정·개인 없음
    assert e.value.errors == {"assist": "no_source"}


def test_other_org_target_is_404(on, member, outsider):
    o2 = create_org("남의 조직", "", outsider)
    p2 = create_project(org=o2, name="비밀", actor=outsider, owners=[outsider], status="active")
    t2 = create_task(
        project=p2, title="비밀 태스크", actor=outsider, source="web", no_due_reason="x"
    )
    with pytest.raises(Http404):
        make(member, on, target=f"task:{t2.pk}")
    with pytest.raises(Http404):
        make(member, on, field="project.name", target=f"project:{p2.pk}")
    with pytest.raises(Http404):
        make(member, on, field="project.name", target=f"org:{o2.pk}")


def test_draft_meeting_not_host_is_404(on, member, admin):
    d = create_doc(org=on, actor=member, kind="meeting")
    Doc.objects.filter(pk=d.pk).update(status="draft")
    VoiceRecording.objects.create(
        note=d,
        guild_id="g",
        voice_channel_id="v",
        started_by=admin,
        host=admin,
        transcript_md="회의 내용",
    )
    with pytest.raises(Http404):
        make(member, on, field="meeting.minutes", target=f"doc:{d.pk}")
    assert make(admin, on, field="meeting.minutes", target=f"doc:{d.pk}").kind == "meeting"


def test_meeting_needs_transcript(on, member):
    d = create_doc(org=on, actor=member, kind="meeting")
    with pytest.raises(ServiceError):
        make(member, on, field="meeting.minutes", target=f"doc:{d.pk}")


def test_template_option(on, member):
    d = create_doc(org=on, actor=member, title="문서")
    with pytest.raises(ServiceError):
        make(member, on, field="doc.template", target=f"doc:{d.pk}", options={"template_id": d.pk})
    tpl = create_doc(org=on, actor=member, title="틀")
    Doc.objects.filter(pk=tpl.pk).update(is_template=True)
    job = make(
        member,
        on,
        field="doc.template",
        target=f"doc:{d.pk}",
        options={"template_id": tpl.pk, "junk": 1},
    )
    assert job.options == {"template_id": tpl.pk}


def test_rate_limits(on, member, task):
    t = f"task:{task.pk}"
    make(member, on, target=t)
    make(member, on, target=t)
    with pytest.raises(svc.RateLimited):
        make(member, on, target=t)  # 동시 2
    AiJob.objects.filter(user=member).update(status="done")
    AiJob.objects.bulk_create(
        [AiJob(user=member, org=on, kind="field", field="task.title", status="done")] * 118
    )
    with pytest.raises(svc.RateLimited):
        make(member, on, target=t)  # 시간당 120


def test_get_and_cancel(on, member, admin, task):
    job = make(member, on, target=f"task:{task.pk}")
    with pytest.raises(Http404):
        svc.get_job(admin, job.pk)  # 남의 작업
    assert svc.cancel_job(member, job.pk).status == "cancelled"
    job2 = make(member, on, target=f"task:{task.pk}")
    AiJob.objects.filter(pk=job2.pk).update(status="running", claimed_at=timezone.now())
    assert svc.cancel_job(member, job2.pk).status == "cancelling"


def test_stale_queued_no_worker_on_read(on, member, task):
    job = make(member, on, target=f"task:{task.pk}")
    AiJob.objects.filter(pk=job.pk).update(created_at=timezone.now() - timedelta(minutes=6))
    got = svc.get_job(member, job.pk)
    assert (got.status, got.error) == ("failed", "no_worker")


def _done_doc_job(user, org, doc, field, result):
    return AiJob.objects.create(
        user=user,
        org=org,
        kind="doc",
        field=field,
        target_type="doc",
        target_id=doc.pk,
        status="done",
        result=result,
    )


def test_apply_doc(on, member):
    d = create_doc(org=on, actor=member, title="문서", body_md="처음")
    n = d.revisions.count()
    job = _done_doc_job(member, on, d, "doc.fill", "AI 본문")
    d = svc.apply_job(member, job.pk, version=d.version)
    assert d.body_md == "AI 본문" and d.revisions.count() == n + 1
    assert AiJob.objects.get(pk=job.pk).applied_at is not None
    with pytest.raises(ConflictError):
        svc.apply_job(member, job.pk, version=d.version - 1)
    job2 = _done_doc_job(member, on, d, "doc.continue", "이어서")
    assert svc.apply_job(member, job2.pk).body_md == "AI 본문\n\n이어서"


def test_apply_refusals(on, member, admin, task):
    d = create_doc(org=on, actor=member, title="문서")
    job = _done_doc_job(member, on, d, "doc.fill", "x")
    with pytest.raises(Http404):
        svc.apply_job(admin, job.pk)
    field_job = make(member, on, target=f"task:{task.pk}")
    with pytest.raises(ServiceError):
        svc.apply_job(member, field_job.pk)


def test_purge_old_jobs(on, member):
    """처리방침대로 만든 날 기준 7일(끝난 날이 최근이어도 지운다)."""
    old = AiJob.objects.create(user=member, org=on, kind="field", field="task.title", status="done")
    AiJob.objects.filter(pk=old.pk).update(
        created_at=timezone.now() - timedelta(days=8),
        finished_at=timezone.now() - timedelta(days=6),
    )
    AiJob.objects.create(user=member, org=on, kind="field", field="task.title", status="queued")
    assert svc.purge_old_jobs() == 1 and not AiJob.objects.filter(pk=old.pk).exists()


def test_apply_mode_append(on, member):
    d = create_doc(org=on, actor=member, title="회의", body_md="기존")
    job = _done_doc_job(member, on, d, "doc.fill", "새 글")
    with pytest.raises(ServiceError):
        svc.apply_job(member, job.pk, mode="merge")
    assert svc.apply_job(member, job.pk, mode="append").body_md == "기존\n\n새 글"


def test_request_fields_take_org_target(on, member):
    job = make(member, on, field="request.body", target=f"org:{on.pk}")
    assert (job.target_type, job.target_id) == ("org", on.pk)
