"""개인 AI "GitHub Copilot(내 구독)": 플래그로 숨김·연결·모델·실행·토큰 비노출·만료 갱신. Copilot 런타임·GitHub는 목."""

import json
import logging
from datetime import timedelta

import pytest
from cryptography.fernet import Fernet
from django.urls import reverse
from django.utils import timezone

from assist import copilot, services, worker
from assist.models import AiJob, AiSource
from assist.net import NetError
from assist.sources import plan
from github.crypto import encrypt
from github.models import GitHubIdentity

TOKEN = "ghu_" + "A" * 36
NEW_TOKEN = "ghu_" + "B" * 36


@pytest.fixture(autouse=True)
def _crypto(settings):
    settings.CREDENTIAL_KEY = Fernet.generate_key().decode()


@pytest.fixture
def cp_on(settings):
    settings.ASSIST_COPILOT_ENABLED = True
    settings.COPILOT_RUNTIME_URL = "copilot:4321"
    settings.COPILOT_CONNECTION_TOKEN = "test-runtime-secret"
    settings.COPILOT_MODELS = ["gpt-5-mini", "claude-sonnet-4.5"]
    return settings


def identity(user, token=TOKEN, expires_in=timedelta(hours=8), refresh="ghr_" + "R" * 36):
    return GitHubIdentity.objects.create(
        user=user,
        github_id=1000 + user.pk,
        login=user.username,
        token_enc=encrypt(token),
        token_expires_at=timezone.now() + expires_in,
        refresh_enc=encrypt(refresh) if refresh else "",
    )


def cp_source(user, **kw):
    return AiSource.objects.create(
        user=user,
        name="GitHub Copilot",
        base_url=copilot.URL,
        route="direct",
        model="gpt-5-mini",
        **kw,
    )


@pytest.fixture
def on(org):
    org.settings = {**(org.settings or {}), "assist.enabled": True}
    org.save(update_fields=["settings"])
    return org


# ---------- 화면 ----------


def test_off_by_default_hides_button_and_rejects(client, member):
    client.force_login(member)
    identity(member)
    page = client.get(reverse("settings_ai")).content.decode()
    assert "GitHub Copilot으로 연결" not in page
    assert client.post(reverse("settings_ai_copilot")).status_code == 404
    assert not AiSource.objects.filter(base_url=copilot.URL).exists()


def test_off_skips_existing_row_in_plan(member, on, settings):
    src = cp_source(member)
    settings.ASSIST_COPILOT_ENABLED = False
    assert all(a.source != src for a in plan(member, on))
    settings.ASSIST_COPILOT_ENABLED = True
    settings.COPILOT_RUNTIME_URL = ""  # 런타임 주소가 없어도 끈 것과 같다
    assert all(a.source != src for a in plan(member, on))
    settings.COPILOT_RUNTIME_URL = "copilot:4321"
    settings.COPILOT_CONNECTION_TOKEN = ""  # 런타임과 나누는 비밀이 없어도 끈 것과 같다
    assert all(a.source != src for a in plan(member, on))


def test_connect_creates_keyless_row(client, member, on, cp_on):
    client.force_login(member)
    identity(member)
    page = client.get(reverse("settings_ai")).content.decode()
    assert "GitHub Copilot으로 연결" in page
    r = client.post(reverse("settings_ai_copilot"))
    assert r.status_code == 302
    src = AiSource.objects.get(user=member, base_url=copilot.URL)
    assert (src.route, src.api_key, src.model) == ("direct", "", "gpt-5-mini")
    assert any(a.source == src for a in plan(member, on))
    client.post(reverse("settings_ai_copilot"))  # 두 번째는 만들지 않는다
    assert AiSource.objects.filter(user=member, base_url=copilot.URL).count() == 1
    page = client.get(reverse("settings_ai")).content.decode()
    assert TOKEN not in page and "GitHub Copilot(내 구독)" in page
    assert reverse("settings_ai_test", args=[src.pk]) not in page  # OpenAI 호환 시험 버튼 없음


def test_connect_requires_github_identity(client, member, cp_on):
    client.force_login(member)
    client.post(reverse("settings_ai_copilot"))
    assert not AiSource.objects.filter(user=member).exclude(kind="org").exists()


def test_model_only_from_list_and_only_mine(client, member, outsider, cp_on):
    src = cp_source(member)
    client.force_login(member)
    url = reverse("settings_ai_copilot_model", args=[src.pk])
    assert client.post(url, {"model": "claude-sonnet-4.5"}).status_code == 302
    assert client.post(url, {"model": "evil"}).status_code == 400
    src.refresh_from_db()
    assert src.model == "claude-sonnet-4.5"
    client.force_login(outsider)
    assert client.post(url, {"model": "gpt-5-mini"}).status_code == 404


# ---------- 실행 ----------


@pytest.fixture
def fake_cp(monkeypatch):
    calls = []

    def chat(messages, *, token, model, timeout_s):
        calls.append({"token": token, "model": model, "messages": messages})
        r = calls_replies.pop(0)
        if isinstance(r, Exception):
            raise r
        return r

    calls_replies = []
    monkeypatch.setattr(copilot, "chat", chat)

    def install(*replies):
        calls_replies.extend(replies)
        return calls

    return install


def run_once():
    for job_id, _ in worker.claim(10):
        worker.run(job_id)


def test_job_runs_with_requesters_own_token(member, admin, on, task, cp_on, fake_cp, caplog):
    identity(member)
    identity(admin, token="ghu_" + "C" * 36)  # 남의 토큰은 쓰이지 않는다
    cp_source(member)
    calls = fake_cp(json.dumps({"options": ["가", "나", "다", "라"]}))
    job = services.create_job(member, on, field="task.title", target=f"task:{task.pk}")
    with caplog.at_level(logging.DEBUG):
        run_once()
    job.refresh_from_db()
    assert job.status == "done", (job.error, job.tried)
    assert calls[0]["token"] == TOKEN and calls[0]["model"] == "gpt-5-mini"
    assert TOKEN not in caplog.text and TOKEN not in job.result


def test_expired_token_is_refreshed(member, on, task, cp_on, fake_cp, monkeypatch):
    from github import client as gh_client

    identity(member, expires_in=timedelta(minutes=-1))
    monkeypatch.setattr(
        gh_client,
        "refresh_user_token",
        lambda r: {
            "access_token": NEW_TOKEN,
            "expires_in": 28800,
            "refresh_token": "ghr_" + "N" * 36,
        },
    )
    cp_source(member)
    calls = fake_cp(json.dumps({"options": ["가"]}))
    job = services.create_job(member, on, field="task.title", target=f"task:{task.pk}")
    run_once()
    job.refresh_from_db()
    assert job.status == "done" and calls[0]["token"] == NEW_TOKEN
    assert NEW_TOKEN not in GitHubIdentity.objects.get(user=member).token_enc  # 암호화 저장


def test_expired_without_refresh_moves_on_with_auth_failed(member, on, task, cp_on, fake_cp):
    identity(member, expires_in=timedelta(minutes=-1), refresh="")
    src = cp_source(member)
    calls = fake_cp()
    job = services.create_job(member, on, field="task.title", target=f"task:{task.pk}")
    run_once()
    job.refresh_from_db()
    assert calls == []
    assert job.tried[0] == {"route": "direct", "source_id": src.pk, "error": "auth_failed"}
    assert AiJob.objects.get(pk=job.pk).status in ("queued", "failed")


# ---------- 어댑터 ----------


def test_prompt_and_error_codes(cp_on):
    system, prompt = copilot._prompt(
        [
            {"role": "system", "content": "S"},
            {"role": "user", "content": "Q"},
            {"role": "assistant", "content": "A"},
            {"role": "user", "content": "다시"},
        ]
    )
    assert system == "S" and "[AI]\nA" in prompt and prompt.endswith("다시")
    assert copilot._prompt([{"role": "user", "content": "Q"}]) == ("", "Q")
    assert copilot._code(TimeoutError()) == "timeout"
    assert copilot._code(ConnectionRefusedError()) == "connect_failed"
    assert (
        copilot._code(Exception("JSON-RPC Error -32002: AUTHENTICATION_FAILED")) == "connect_failed"
    )
    assert copilot._code(Exception("GitHub token validation failed: 401")) == "auth_failed"
    assert copilot._code(Exception("weird")) == "http_5xx"


def test_chat_off_is_no_source(settings):
    settings.ASSIST_COPILOT_ENABLED = False
    with pytest.raises(NetError) as e:
        copilot.chat([{"role": "user", "content": "Q"}], token=TOKEN, model="", timeout_s=5)
    assert e.value.code == "no_source"
