"""AI 자동완성 화면(IMPL-PLAN-12 C 갈래). 서비스 몸체는 A 갈래라 여기서는 목으로 바꾼다."""

import json

import pytest
from django.urls import reverse

from assist import extract, services
from assist.models import AiJob
from common.errors import ConflictError
from notes.services import create_note

HX = {"HX-Request": "true"}


@pytest.fixture
def logged(client, member):
    client.force_login(member)
    return client


@pytest.fixture
def stub_get(monkeypatch):
    """주인 검사를 하지 않는 get_job — 뷰가 스스로 남의 작업을 막는지 본다."""
    monkeypatch.setattr(services, "get_job", lambda user, job_id: AiJob.objects.get(pk=job_id))


def _job(user, org, **kw):
    kw.setdefault("kind", "field")
    kw.setdefault("field", "task.title")
    return AiJob.objects.create(user=user, org=org, **kw)


def _switch(org, on):
    org.settings = {**(org.settings or {}), "assist.enabled": on}
    org.save()


def test_switch_controls_attributes(logged, org, task):
    url = f"/tasks/{task.pk}/panel"
    body = logged.get(url, headers=HX).content.decode()
    for key in (
        "task.title",
        "task.next_action",
        "task.notes",
        "task.done_when",
        "task.description",
    ):
        assert f'data-ai="{key}" data-ai-target="task:{task.pk}"' in body
    assert 'data-ai="task.checklist"' in body
    _switch(org, False)
    assert "data-ai=" not in logged.get(url, headers=HX).content.decode()
    page = logged.get("/today").content.decode()
    assert 'id="ai-dlg"' in page and "ai-fill.js" in page


def test_meeting_buttons_and_transcript(logged, org, member):
    note = create_note(org=org, actor=member, title="주간 회의")
    body = logged.get(f"/orgs/{org.pk}/notes?note={note.pk}").content.decode()
    assert 'data-ai-mode="meeting.minutes"' in body and 'aria-describedby="ai-minutes-why"' in body
    assert (
        'data-ai-mode="extract.meeting"' in body
        and f'data-ai="doc.title" data-ai-target="doc:{note.pk}"' in body
    )
    _switch(org, False)
    assert "data-ai-mode" not in logged.get(f"/orgs/{org.pk}/notes?note={note.pk}").content.decode()


def test_create_rejects_bad_key_target_and_switch(logged, org, task, monkeypatch):
    called = []
    monkeypatch.setattr(services, "create_job", lambda *a, **k: called.append(1))
    url = reverse("assist_job_create")
    assert (
        logged.post(url, {"field": "secret.token", "target": f"task:{task.pk}"}).status_code == 400
    )
    assert logged.post(url, {"field": "task.title", "target": "project:1"}).status_code == 400
    assert logged.post(url, {"field": "task.title", "target": "task:"}).status_code == 400
    _switch(org, False)
    assert logged.post(url, {"field": "task.title", "target": f"task:{task.pk}"}).status_code == 403
    assert called == []


def test_create_renders_job_and_polls(logged, org, member, task, monkeypatch, stub_get):
    seen = {}

    def fake(user, o, **kw):
        seen.update(kw, org=o)
        return _job(user, o)

    monkeypatch.setattr(services, "create_job", fake)
    r = logged.post(
        reverse("assist_job_create"),
        {"field": "task.title", "target": f"task:{task.pk}", "input": "초안", "options": "{}"},
    )
    assert r.status_code == 200
    body = r.content.decode()
    job = AiJob.objects.get()
    assert f'hx-get="/assist/jobs/{job.pk}?s=queued"' in body and "AI 작업 취소" in body
    assert seen["field"] == "task.title" and seen["user_input"] == "초안" and seen["org"] == org
    assert (
        logged.get(f"/assist/jobs/{job.pk}?s=queued").status_code == 204
    )  # 상태 그대로면 다시 그리지 않음
    job.status = "done"
    job.result = json.dumps({"options": ["가", "나", "다"]})
    job.save()
    done = logged.get(f"/assist/jobs/{job.pk}?s=queued").content.decode()
    assert 'data-ai-value="나"' in done and "hx-trigger" not in done


def test_rate_limited_is_429(logged, task, monkeypatch):
    def fake(*a, **k):
        raise services.RateLimited({"assist": "rate_limited"})

    monkeypatch.setattr(services, "create_job", fake)
    r = logged.post(
        reverse("assist_job_create"), {"field": "task.title", "target": f"task:{task.pk}"}
    )
    assert r.status_code == 429 and "AI 요청이 너무 많습니다" in r.content.decode()


def test_service_error_code_message(logged, task, monkeypatch):
    def fake(*a, **k):
        raise services.ServiceError({"assist": "no_source"})

    monkeypatch.setattr(services, "create_job", fake)
    r = logged.post(
        reverse("assist_job_create"), {"field": "task.title", "target": f"task:{task.pk}"}
    )
    assert r.status_code == 400 and "쓸 수 있는 AI가 없습니다" in r.content.decode()


def test_other_users_job_is_404(logged, org, admin, monkeypatch, stub_get):
    job = _job(admin, org, kind="extract", field="extract.meeting", status="done", result="{}")
    for fn in ("cancel_job", "apply_job"):
        monkeypatch.setattr(services, fn, lambda *a, **k: pytest.fail("불리면 안 된다"))
    assert logged.get(f"/assist/jobs/{job.pk}").status_code == 404
    assert logged.post(f"/assist/jobs/{job.pk}/cancel").status_code == 404
    assert logged.post(f"/assist/jobs/{job.pk}/apply", {"version": 1}).status_code == 404
    assert logged.post(f"/assist/jobs/{job.pk}/create-tasks", {"pick": 0}).status_code == 404


def test_org_count_line_and_source(logged, org, member, monkeypatch, stub_get):
    org.settings = {"assist.org_url": "https://llm.example.com/v1"}
    org.save()
    monkeypatch.setattr(services, "today_org_count", lambda user, o: 3)
    job = _job(member, org, field="task.description", status="done", result="본문", route="org")
    body = logged.get(f"/assist/jobs/{job.pk}").content.decode()
    assert "오늘 조직 AI 3/30" in body and "쓴 AI: 조직 AI" in body
    assert 'data-ai-use="replace"' in body and 'data-ai-use="append"' in body


def test_apply_conflict_and_success(logged, org, member, monkeypatch, stub_get):
    job = _job(member, org, kind="doc", field="doc.fill", status="done", result="글")
    calls = []

    def conflict(user, job_id, *, version=None):
        calls.append(version)
        raise ConflictError(None)

    monkeypatch.setattr(services, "apply_job", conflict)
    r = logged.post(f"/assist/jobs/{job.pk}/apply", {"version": "7"})
    assert r.status_code == 409 and calls == [7]
    monkeypatch.setattr(services, "apply_job", lambda *a, **k: None)
    r = logged.post(f"/assist/jobs/{job.pk}/apply", {"version": "8"})
    assert r.status_code == 204 and r["HX-Refresh"] == "true"


def test_checklist_add_many_lines(logged, task):
    r = logged.post(reverse("checklist_add", args=[task.pk]), {"text": ["가\n나\n\n다", "라"]})
    assert r.status_code == 200
    assert list(task.checklist.values_list("text", flat=True)) == ["가", "나", "다", "라"]
    logged.post(
        reverse("checklist_add", args=[task.pk]), {"text": "\n".join(str(i) for i in range(30))}
    )
    assert task.checklist.count() == 4 + 20


def test_create_tasks_passes_rows(logged, org, member, project, task, monkeypatch, stub_get):
    result = {
        "tasks": [
            {
                "title": "후보 하나",
                "description": "설명",
                "assignee_id": member.pk,
                "project_id": project.pk,
                "similar": [task.pk],
            },
            {"title": "후보 둘", "assignee": "모르는 사람"},
        ]
    }
    job = _job(
        member,
        org,
        kind="extract",
        field="extract.meeting",
        status="done",
        result=json.dumps(result),
    )
    shown = logged.get(f"/assist/jobs/{job.pk}").content.decode()
    assert (
        "고른 후보로 태스크 만들기" in shown and task.number in shown and "이름 확인 필요" in shown
    )
    got = {}

    def fake(j, rows, actor):
        got["rows"] = rows
        return [(0, task, ""), (1, None, "프로젝트를 골라 주세요.")]

    monkeypatch.setattr(extract, "create_from_candidates", fake)
    r = logged.post(
        f"/assist/jobs/{job.pk}/create-tasks",
        {
            "pick": ["0", "1"],
            "title_0": "고친 제목",
            "assignee_0": str(member.pk),
            "due_0": "2026-11-01",
            "project_0": str(project.pk),
            "title_1": "둘",
        },
    )
    body = r.content.decode()
    assert got["rows"][0] == {
        "index": 0,
        "title": "고친 제목",
        "description": "",
        "assignee_id": member.pk,
        "due": "2026-11-01",
        "project_id": project.pk,
    }
    assert got["rows"][1]["assignee_id"] is None
    assert f'href="/tasks/{task.pk}"' in body and "프로젝트를 골라 주세요." in body
    assert logged.post(f"/assist/jobs/{job.pk}/create-tasks", {}).status_code == 400  # 고른 행 없음
