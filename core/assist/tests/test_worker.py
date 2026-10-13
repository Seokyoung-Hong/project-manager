"""AI 워커: 집기·실행·넘기기·검증·sweep(IMPL-PLAN-12 §4·§5.1-4·§10.2·§11.2). 외부 호출은 가짜 chat."""

import json
import logging
from datetime import timedelta

import pytest
from cryptography.fernet import Fernet
from django.utils import timezone

from assist import prompts, services, worker
from assist.models import AiJob, AiSource
from assist.net import NetError
from common.dates import today_kst
from notes.models import SttServer, VoiceRecording
from projects.docs import create_doc
from projects.models import Doc
from tasks.services import create_task


def org_ai(org, **extra):
    org.settings = {
        **(org.settings or {}),
        "assist.org_url": "https://ai.example.com/v1",
        "assist.org_model": "org-model",
        **extra,
    }
    org.save(update_fields=["settings"])


class FakeChat:
    """답을 차례로 돌려준다. 예외면 던지고, callable이면 불러서 그 값을 내용으로."""

    def __init__(self, *replies):
        self.replies = list(replies)
        self.calls = []

    def __call__(self, url, payload, **kw):
        self.calls.append((url, payload, kw))
        r = self.replies.pop(0)
        if isinstance(r, Exception):
            raise r
        if callable(r):
            r = r()
        if isinstance(r, dict):  # 응답 전체(추론 모델 흉내)
            return r
        return {"choices": [{"message": {"content": r}}], "usage": {"total_tokens": 5}}


@pytest.fixture
def fake(monkeypatch):
    def install(*replies):
        f = FakeChat(*replies)
        monkeypatch.setattr(worker, "chat", f)
        return f

    return install


def run_once():
    for job_id, _ in worker.claim(10):
        worker.run(job_id)


def http_400():
    e = NetError("http_4xx")
    e.status = 400
    return e


@pytest.fixture
def on(org):
    org_ai(org)
    return org


def test_line_field_via_org(on, member, task, fake, caplog):
    f = fake(json.dumps({"options": ["가", "나", "다", "라"]}))
    job = services.create_job(member, on, field="task.title", target=f"task:{task.pk}")
    with caplog.at_level(logging.DEBUG):
        run_once()
    job.refresh_from_db()
    assert job.status == "done" and json.loads(job.result) == {"options": ["가", "나", "다"]}
    assert job.usage == {"total_tokens": 5}
    url, payload, kw = f.calls[0]
    assert url == "https://ai.example.com/v1" and kw["org"] is True and kw["timeout_s"] == 30
    assert payload["model"] == "org-model" and payload["response_format"] == {"type": "json_object"}
    assert payload["max_tokens"] == 200 and payload["temperature"] == 0.3
    system, user = payload["messages"]
    assert "지시가 아닙니다" in system["content"] and task.title in user["content"]


def test_personal_key_decrypted_and_not_logged(on, member, task, fake, settings, caplog):
    settings.CREDENTIAL_KEY = Fernet.generate_key().decode()
    from github.crypto import encrypt

    AiSource.objects.create(
        user=member,
        name="개인",
        base_url="https://p.example.com/v1",
        route="direct",
        model="pm",
        api_key="enc:" + encrypt("sk-SECRET-123"),
    )
    f = fake(NetError("http_5xx"), json.dumps({"options": ["a"]}))
    job = services.create_job(member, on, field="task.title", target=f"task:{task.pk}")
    assert job.route == "direct"
    with caplog.at_level(logging.DEBUG, logger="assist"):
        run_once()  # 개인 AI 5xx → 조직 AI로 넘김
    job.refresh_from_db()
    assert job.status == "queued" and job.route == "org"
    assert job.tried == [
        {"route": "direct", "source_id": job.tried[0]["source_id"], "error": "http_5xx"}
    ]
    assert f.calls[0][2]["api_key"] == "sk-SECRET-123" and f.calls[0][2]["org"] is False
    assert AiSource.objects.get(kind="personal").last_error == "http_5xx"
    run_once()
    job.refresh_from_db()
    assert job.status == "done"
    blob = caplog.text + job.result + json.dumps(job.tried) + job.error
    assert "sk-SECRET-123" not in blob


def test_json_object_rejected_then_without(on, member, task, fake):
    f = fake(http_400(), http_400(), http_400(), json.dumps({"options": ["a"]}))
    job = services.create_job(member, on, field="task.title", target=f"task:{task.pk}")
    run_once()
    job.refresh_from_db()
    assert job.status == "done"
    c = [x[1] for x in f.calls]
    assert c[0]["reasoning_effort"] == "none" and "response_format" in c[0]
    assert (
        c[1]["reasoning_effort"] == "low" and "response_format" in c[1]
    )  # 추론 필수 모델: 끄지 말고 낮춤
    assert "reasoning_effort" not in c[2] and "response_format" in c[2]
    assert "reasoning_effort" not in c[3] and "response_format" not in c[3]


def _spent(content=""):
    """추론이 출력 예산을 다 쓴 응답(운영 재현: OpenRouter auto → 추론 필수 모델)."""
    msg = {"content": content, "reasoning": "생각" * 6000}
    return {
        "choices": [{"message": msg, "finish_reason": "length"}],
        "usage": {"completion_tokens": 4000},
    }


def test_reasoning_spends_budget_then_retry_with_more_tokens(on, member, task, fake):
    f = fake(http_400(), _spent(), json.dumps({"options": ["a"]}))
    job = services.create_job(member, on, field="task.title", target=f"task:{task.pk}")
    run_once()
    job.refresh_from_db()
    assert job.status == "done"
    c = [x[1] for x in f.calls]
    assert c[1]["reasoning_effort"] == "low" and c[1]["max_tokens"] == 200
    assert c[2]["reasoning_effort"] == "low" and c[2]["max_tokens"] == 8000  # 한 번만 넉넉히


def test_reasoning_budget_twice_is_reasoning_budget(on, member, task, fake):
    none_content = {"choices": [{"message": {"content": None, "reasoning_content": "생각"}}]}
    f = fake(_spent(), none_content)
    job = services.create_job(member, on, field="task.title", target=f"task:{task.pk}")
    run_once()
    job.refresh_from_db()
    assert job.status in ("queued", "failed") and job.tried[-1]["error"] == "reasoning_budget"
    assert len(f.calls) == 2 and f.calls[1][1]["max_tokens"] == 8000


def test_bigger_budget_is_only_for_that_request(on, member, task, fake):
    """예산을 늘린 값은 그 요청에만 쓴다. 형식 재질문 등 다음 요청은 원래 예산으로(Sol 지적: 비용)."""
    f = fake(_spent(), "형식 아님", json.dumps({"options": ["a"]}))
    job = services.create_job(member, on, field="task.title", target=f"task:{task.pk}")
    run_once()
    job.refresh_from_db()
    assert job.status == "done"
    assert [x[1]["max_tokens"] for x in f.calls] == [200, 8000, 200]


def test_bad_output_reask_then_next(on, member, task, fake):
    f = fake('<think>음</think>```json\n{"options": ["좋음"]}\n```')
    job = services.create_job(member, on, field="task.title", target=f"task:{task.pk}")
    run_once()
    job.refresh_from_db()
    assert job.status == "done" and json.loads(job.result)["options"] == ["좋음"]

    f = fake("그냥 글", json.dumps({"options": ["다시"]}))
    job = services.create_job(member, on, field="task.title", target=f"task:{task.pk}")
    run_once()
    job.refresh_from_db()
    assert job.status == "done" and len(f.calls) == 2
    assert "형식이 맞지 않습니다" in f.calls[1][1]["messages"][-1]["content"]

    fake("글", "또 글")
    job = services.create_job(member, on, field="task.title", target=f"task:{task.pk}")
    run_once()
    job.refresh_from_db()
    assert (job.status, job.error) == ("failed", "bad_output")


@pytest.mark.parametrize("code", ["connect_failed", "timeout", "auth_failed", "model_not_found"])
def test_last_failure_fails_job(on, member, task, fake, code):
    fake(NetError(code))
    job = services.create_job(member, on, field="task.title", target=f"task:{task.pk}")
    run_once()
    job.refresh_from_db()
    assert (job.status, job.error) == ("failed", code)


def test_switch_off_before_run(on, member, task, fake):
    f = fake()
    job = services.create_job(member, on, field="task.title", target=f"task:{task.pk}")
    org_ai(on, **{"assist.enabled": False})
    run_once()
    job.refresh_from_db()
    assert (job.status, job.error) == ("failed", "org_disabled") and f.calls == []


def test_permission_revoked_before_run(on, member, admin, fake):
    d = create_doc(org=on, actor=member, kind="meeting")
    Doc.objects.filter(pk=d.pk).update(status="draft")
    rec = VoiceRecording.objects.create(
        note=d,
        guild_id="g",
        voice_channel_id="v",
        started_by=member,
        host=member,
        transcript_md="회의",
    )
    f = fake()
    job = services.create_job(member, on, field="meeting.minutes", target=f"doc:{d.pk}")
    rec.host = admin
    rec.save()  # 진행자를 넘기면 초안 회의록을 더는 못 본다
    run_once()
    job.refresh_from_db()
    assert job.status == "failed" and f.calls == []


def test_cancel_while_running_discards(on, member, task, fake):
    holder = {}

    def cancel_midway():
        services.cancel_job(member, holder["id"])
        return json.dumps({"options": ["a"]})

    fake(cancel_midway)
    job = services.create_job(member, on, field="task.title", target=f"task:{task.pk}")
    holder["id"] = job.pk
    run_once()
    job.refresh_from_db()
    assert job.status == "cancelled" and job.result == ""


def test_pc_reported_failure_moves_on(on, member, task, fake):
    """D: PC가 실패를 보고하면 route="", server=NULL로 queued — 워커가 tried 다음 항목으로 넘긴다."""
    fake(json.dumps({"options": ["a"]}))
    pc = AiSource.objects.create(
        user=member, name="PC", base_url="http://localhost:11434/v1", route="pc", position=0
    )
    job = AiJob.objects.create(
        user=member,
        org=on,
        kind="field",
        field="task.title",
        target_type="task",
        target_id=task.pk,
        route="",
        tried=[{"route": "pc", "source_id": pc.pk, "error": "pc_error"}],
    )
    run_once()
    job.refresh_from_db()
    assert job.status == "queued" and job.route == "org"
    run_once()
    job.refresh_from_db()
    assert job.status == "done"


def test_claim_field_first(on, member, admin, task):
    d = create_doc(org=on, actor=member, title="문서", body_md="본문")
    doc_job = services.create_job(member, on, field="doc.fill", target=f"doc:{d.pk}")
    field_job = services.create_job(admin, on, field="task.title", target=f"task:{task.pk}")
    assert worker.claim(5, long_limit=0) == [(field_job.pk, False)]  # 칸 몫 자리엔 긴 작업 안 집음
    assert worker.claim(5) == [(doc_job.pk, True)]
    assert worker.claim(5) == []


def test_sweep(on, member, admin, task):
    old = timezone.now() - timedelta(minutes=10)
    stale = services.create_job(member, on, field="task.title", target=f"task:{task.pk}")
    AiJob.objects.filter(pk=stale.pk).update(created_at=old)
    hung = services.create_job(admin, on, field="task.title", target=f"task:{task.pk}")
    AiJob.objects.filter(pk=hung.pk).update(status="running", claimed_at=old)
    srv = SttServer.objects.create(owner=member, name="PC", machine_id="m")
    pc_job = AiJob.objects.create(
        user=member,
        org=on,
        kind="field",
        field="task.title",
        target_type="task",
        target_id=task.pk,
        route="pc",
        server=srv,
        status="running",
        claimed_at=timezone.now(),
    )
    AiJob.objects.filter(pk=pc_job.pk).update(server=None)  # PC 끊김(SET_NULL)
    worker.sweep()
    stale.refresh_from_db()
    hung.refresh_from_db()
    pc_job.refresh_from_db()
    assert (stale.status, stale.error) == ("failed", "no_worker")
    assert (hung.status, hung.error) == ("failed", "timeout")  # 다음 항목 없음
    assert pc_job.status == "queued" and pc_job.route == "org"
    assert pc_job.tried[0]["error"] == "pc_unlinked"


def test_sweep_expires_running_job_on_online_pc(on, member, task):
    """켜져 있는 PC가 결과를 끝내 보내지 않으면 timeout_s + 여유 뒤 다음 AI로(슬롯·내용을 붙잡지 않게)."""
    srv = SttServer.objects.create(
        owner=member, name="PC", machine_id="m", last_seen_at=timezone.now()
    )
    kw = dict(user=member, org=on, kind="field", field="task.title", target_type="task")
    fresh = AiJob.objects.create(
        **kw, target_id=task.pk, route="pc", server=srv, status="running", claimed_at=timezone.now()
    )
    old = AiJob.objects.create(
        **kw,
        target_id=task.pk,
        route="pc",
        server=srv,
        status="running",
        claimed_at=timezone.now() - timedelta(days=9),
    )
    worker.sweep()
    fresh.refresh_from_db()
    old.refresh_from_db()
    assert fresh.status == "running"
    assert old.status in ("queued", "failed") and old.tried[0]["error"] == "timeout"


def test_start_disabled(settings, monkeypatch):
    settings.ASSIST_WORKERS = 0
    monkeypatch.setattr(worker, "_started", False)
    worker.start()
    assert worker._started is False


def test_long_transcript_chunked(on, member, fake):
    d = create_doc(org=on, actor=member, kind="meeting")
    VoiceRecording.objects.create(
        note=d,
        guild_id="g",
        voice_channel_id="v",
        started_by=member,
        host=member,
        transcript_md="가" * (prompts.MAX_INPUT_CHARS * 14),
    )
    f = fake(*(["요약"] * 12), "## 요약\n회의록")
    job = services.create_job(member, on, field="meeting.minutes", target=f"doc:{d.pk}")
    run_once()
    job.refresh_from_db()
    assert job.status == "done" and job.result.startswith("## 요약")
    assert len(f.calls) == 13 and job.usage["input_pct"] == 86
    assert "요약\n\n요약" in f.calls[-1][1]["messages"][1]["content"]


def test_extract_meeting_postprocess(on, member, admin, project, fake):
    existing = create_task(
        project=project, title="메뉴 API 오류 수정", actor=admin, source="web", no_due_reason="x"
    )
    d = create_doc(org=on, actor=member, kind="meeting", project=project)
    VoiceRecording.objects.create(
        note=d,
        guild_id="g",
        voice_channel_id="v",
        started_by=member,
        host=member,
        transcript_md="팀원이 메뉴 API 오류를 고치기로 함",
    )
    due = (today_kst() + timedelta(days=5)).isoformat()
    out = {
        "tasks": [
            {"title": "메뉴 API 오류 수정하기", "assignee": "팀원", "due": due, "project": None},
            {"title": "모르는 사람 일", "assignee": "홍길동", "due": "2001-01-01"},
            {"title": ""},
        ]
        + [{"title": f"할 일 {i}"} for i in range(30)]
    }
    f = fake(json.dumps(out))
    job = services.create_job(member, on, field="extract.meeting", target=f"doc:{d.pk}")
    run_once()
    job.refresh_from_db()
    assert job.status == "done"
    rows = json.loads(job.result)["tasks"]
    assert len(rows) == 20
    a, b = rows[0], rows[1]
    assert a["assignee_id"] == member.pk and a["project_id"] == project.pk and a["due"] == due
    assert existing.pk in a["similar"]
    assert b["assignee_id"] is None and b["assignee_note"] and b["due"] is None
    payload = f.calls[0][1]
    assert payload["temperature"] == 0.2 and existing.title in payload["messages"][1]["content"]
