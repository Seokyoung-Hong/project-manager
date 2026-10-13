"""IMPL-PLAN-12 D: 내 PC 거쳐 보내기 — heartbeat 배정·취소·보고·소유자 불변식·PC 끊김."""

import pytest
from cryptography.fernet import Fernet

from assist.models import CODEX_URL, AiJob, AiSource
from github.crypto import encrypt
from notes import stt_link
from notes.test_stt_link import _api, _beat, _link

pytestmark = pytest.mark.django_db
MSGS = [{"role": "user", "content": "자료"}]


@pytest.fixture(autouse=True)
def _env(settings, tmp_path, monkeypatch):
    settings.CREDENTIAL_KEY = Fernet.generate_key().decode()
    settings.MEDIA_ROOT = tmp_path
    monkeypatch.setattr("assist.prompts.build_messages", lambda job, user: MSGS)


def _job(user, org, server, **kw):
    src = AiSource.objects.create(
        user=user,
        name="Ollama",
        base_url="http://localhost:11434/v1",
        route="pc",
        server=server,
        model="qwen3",
        api_key="enc:" + encrypt("sk-local"),
    )
    kw.setdefault("route", "pc")
    return AiJob.objects.create(
        user=user, org=org, kind="field", field="task.title", source=src, server=server, **kw
    )


def _ai(client, token, **extra):
    r = _beat(client, token, ai=1, **extra)
    assert r.status_code == 200, r.content
    return r.json()


def _report(client, token, job_id, **data):
    return _api(client, "patch", f"/api/integrations/stt/ai-jobs/{job_id}", data, token)


def test_job_goes_only_to_owners_pc_with_ai_capability(client, org, member, admin):
    mine, tok = _link(client, member)
    _, admin_tok = _link(client, admin)
    forged = _job(admin, org, mine)  # server는 내 PC지만 요청자가 남 → 배정 안 됨(불변식 2)
    assert "ai_job" not in _ai(client, tok)
    assert "ai_job" not in _beat(client, tok).json()  # ai 능력 표시 없는 옛 PC
    job = _job(member, org, mine)
    assert "ai_job" not in _ai(client, admin_tok)  # 남의 PC
    got = _ai(client, tok, job_id=999)["ai_job"]  # 전사 중이어도 AI는 따로 받는다
    assert got["id"] == job.pk and got["api_key"] == "sk-local" and got["messages"] == MSGS
    assert got["url"] == "http://localhost:11434/v1" and got["model"] == "qwen3"
    assert got["response_format"] == {"type": "json_object"} and got["timeout_s"] == 30
    job.refresh_from_db()
    forged.refresh_from_db()
    assert job.status == "running" and forged.status == "queued"


def test_codex_source_sends_backend_without_url_or_key(client, org, member):
    server, tok = _link(client, member)
    job = _job(member, org, server)
    AiSource.objects.filter(pk=job.source_id).update(base_url=CODEX_URL, model="")
    got = _ai(client, tok, codex=1)["ai_job"]
    assert got["backend"] == "codex" and got["url"] == "" and got["api_key"] == ""
    assert got["model"] == "" and got["timeout_s"] >= 180 and got["messages"] == MSGS
    r = _report(client, tok, job.pk, status="failed", error="codex_auth")
    job.refresh_from_db()
    assert r.json()["status"] == "queued" and job.tried[0]["error"] == "codex_auth"
    assert "ai_job" not in _ai(client, tok, ai_job_id=job.pk)  # 하는 중이면 새로 안 준다


def test_codex_job_skips_pc_without_codex_capability(client, org, member):
    """옛 link(codex 표시 없음)·Codex 없는 PC에는 Codex 작업을 주지 않고 다음 AI로 넘긴다."""
    server, tok = _link(client, member)
    job = _job(member, org, server)
    AiSource.objects.filter(pk=job.source_id).update(base_url=CODEX_URL, model="")
    plain = _job(member, org, server)  # 같은 PC의 OpenAI 호환 작업은 그대로 받는다
    got = _ai(client, tok)
    assert got["ai_job"]["id"] == plain.pk
    job.refresh_from_db()
    assert job.status == "queued" and job.route == "" and job.server is None
    # codex 칸 없음 = Codex를 모르는 옛 udally-link
    assert job.tried == [{"route": "pc", "source_id": job.source_id, "error": "codex_link_update"}]
    assert AiSource.objects.get(pk=job.source_id).last_error == "codex_link_update"
    _report(client, tok, plain.pk, status="done", content='{"options":["가"]}')
    again = _job(member, org, server)
    AiSource.objects.filter(pk=again.source_id).update(base_url=CODEX_URL)
    assert "ai_job" not in _ai(client, tok, codex=0)  # 새 link인데 Codex CLI가 없음
    again.refresh_from_db()
    assert again.tried[0]["error"] == "codex_missing"


def test_claim_rechecks_switch_and_source_before_sending(client, org, member):
    """대기 중에 조직 스위치·개인 AI를 끄면 PC로 내용이 나가지 않는다(§10.2)."""
    server, tok = _link(client, member)
    off_src = _job(member, org, server)
    AiSource.objects.filter(pk=off_src.source_id).update(enabled=False)
    assert "ai_job" not in _ai(client, tok)
    off_src.refresh_from_db()
    assert off_src.status == "queued" and off_src.tried[0]["error"] == "no_source"
    job = _job(member, org, server)
    org.settings = {**(org.settings or {}), "assist.enabled": False}
    org.save(update_fields=["settings"])
    assert "ai_job" not in _ai(client, tok)
    job.refresh_from_db()
    assert job.status == "failed" and job.error == "org_disabled"


def test_cancel_is_delivered_and_finishes_once(client, org, member):
    server, tok = _link(client, member)
    job = _job(member, org, server)
    _ai(client, tok)
    assert "ai_cancel" not in _ai(client, tok, ai_job_id=job.pk)
    AiJob.objects.filter(pk=job.pk).update(status="cancelling")
    assert _ai(client, tok, ai_job_id=job.pk)["ai_cancel"] is True
    r = _report(client, tok, job.pk, status="done", content="늦은 결과")
    assert r.json()["status"] == "cancelled"  # 취소 요청 뒤 결과는 버린다
    job.refresh_from_db()
    assert job.result == "" and job.error == "cancelled"
    assert _report(client, tok, job.pk, status="cancelled").status_code == 409


def test_report_owner_check_size_codes_and_fallthrough(client, org, member, admin):
    server, tok = _link(client, member)
    _, admin_tok = _link(client, admin)
    done, failed = _job(member, org, server), _job(member, org, server)
    _ai(client, tok)
    AiJob.objects.filter(pk=failed.pk).update(status="running")
    assert _report(client, admin_tok, done.pk, status="done", content="x").status_code == 404
    big = "가" * (AiJob.MAX_RESULT // 3 + 1)
    assert _report(client, tok, done.pk, status="done", content=big).status_code == 413
    r = _report(client, tok, done.pk, status="done", content='{"options":["가"]}', usage={"t": 3})
    assert r.status_code == 200 and r.json()["status"] == "done"
    done.refresh_from_db()
    assert done.result == '{"options": ["가"]}' and done.usage == {"t": 3} and done.finished_at
    assert done.source.last_ok_at and not done.source.last_error
    assert _report(client, tok, done.pk, status="done", content="x").status_code == 409
    r = _report(client, tok, failed.pk, status="failed", error="rm -rf")
    failed.refresh_from_db()
    assert r.json()["status"] == "queued" and failed.route == "" and failed.server is None
    assert failed.tried == [{"route": "pc", "source_id": failed.source_id, "error": "pc_error"}]
    failed.source.refresh_from_db()
    assert failed.source.last_error == "pc_error"
    bad = _job(member, org, server, status="running")  # 워커와 같은 검증: 형식이 틀리면 다음 항목
    r = _report(client, tok, bad.pk, status="done", content="형식 없는 글")
    bad.refresh_from_db()
    assert r.json()["status"] == "queued" and bad.tried[0]["error"] == "bad_output"


def test_pc_restart_releases_forgotten_job(client, org, member):
    server, tok = _link(client, member)
    job = _job(member, org, server)
    _ai(client, tok)
    other = _job(member, org, server)
    got = _ai(client, tok)["ai_job"]  # PC가 재시작해 job을 잊고 새로 받는다
    assert got["id"] == other.pk
    job.refresh_from_db()
    assert job.status == "queued" and job.route == "" and job.tried[0]["error"] == "pc_error"


def test_unlinked_pc_rows_are_never_assigned(client, org, member):
    server, tok = _link(client, member)
    job = _job(member, org, server)
    stt_link.unlink(server)
    job.refresh_from_db()
    job.source.refresh_from_db()
    assert job.server is None and job.source.server is None
    _, tok2 = _link(client, member)
    assert "ai_job" not in _ai(client, tok2)
    assert _report(client, tok, job.pk, status="done").status_code == 401
