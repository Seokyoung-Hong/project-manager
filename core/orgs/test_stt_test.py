"""조직 설정 [연결 시험]·[적용] — 로컬 전사 서버 GET /v1/models, POST /v1/models/{id}."""

import io
import urllib.error

import pytest
from cryptography.fernet import Fernet

from orgs.services import set_org_settings

pytestmark = pytest.mark.django_db
URL = "/orgs/{}/settings/stt-test"


class _Resp(io.BytesIO):
    status = 200

    def __enter__(self):
        return self

    def __exit__(self, *a):
        return False


def _fake(monkeypatch, result):
    seen = {}

    def open_(self, req, timeout=None):
        seen["req"], seen["timeout"] = req, timeout
        seen.setdefault("calls", []).append((req.get_method(), req.full_url))
        out = result(req) if callable(result) else result
        if isinstance(out, Exception):
            raise out
        return _Resp(out)

    monkeypatch.setattr("urllib.request.OpenerDirector.open", open_)
    return seen


def test_success_lists_models_and_sends_key(client, org, admin, monkeypatch, settings):
    settings.CREDENTIAL_KEY = Fernet.generate_key().decode()
    set_org_settings(org, {"meeting.stt_api_key": "sk-local-secret"}, admin)
    seen = _fake(monkeypatch, b'{"data":[{"id":"large-v3"},{"id":"small"}]}')
    client.force_login(admin)
    r = client.post(URL.format(org.pk), {"meeting.stt_url": "http://172.30.1.50:8000/"})
    body = r.content.decode()
    assert r.status_code == 200
    assert '<option value="large-v3">' in body and '<option value="small">' in body
    assert 'hx-swap-oob="true"' in body
    assert "sk-local-secret" not in body
    assert seen["req"].full_url == "http://172.30.1.50:8000/v1/models"
    assert seen["req"].get_header("Authorization") == "Bearer sk-local-secret"
    assert seen["timeout"] == 5


def test_401_is_auth_failure(client, org, admin, monkeypatch):
    _fake(monkeypatch, urllib.error.HTTPError("u", 401, "no", {}, None))
    client.force_login(admin)
    r = client.post(URL.format(org.pk), {"meeting.stt_url": "http://172.30.1.50:8000"})
    body = r.content.decode()
    assert "인증에 실패" in body
    assert '<option value="" selected>' in body  # 서버가 안 되면 현재 값(기본값)만 남는다


def test_timeout(client, org, admin, monkeypatch):
    _fake(monkeypatch, urllib.error.URLError(TimeoutError("timed out")))
    client.force_login(admin)
    r = client.post(URL.format(org.pk), {"meeting.stt_url": "http://172.30.1.50:8000"})
    assert "5초" in r.content.decode()


def test_member_forbidden(client, org, member, monkeypatch):
    seen = _fake(monkeypatch, b"{}")
    client.force_login(member)
    r = client.post(URL.format(org.pk), {"meeting.stt_url": "http://172.30.1.50:8000"})
    assert r.status_code == 403
    assert "req" not in seen


def test_rejects_loopback_without_request(client, org, admin, monkeypatch):
    seen = _fake(monkeypatch, b"{}")
    client.force_login(admin)
    r = client.post(URL.format(org.pk), {"meeting.stt_url": "http://127.0.0.1:8000"})
    assert "루프백" in r.content.decode()
    assert "req" not in seen


def test_current_model_kept_when_missing_from_list(client, org, admin, monkeypatch):
    _fake(monkeypatch, b'{"data":[{"id":"small"}]}')
    client.force_login(admin)
    r = client.post(
        URL.format(org.pk),
        {"meeting.stt_url": "http://172.30.1.50:8000", "meeting.stt_model": "old-model"},
    )
    body = r.content.decode()
    assert '<option value="old-model" selected>' in body
    assert '<option value="small">' in body


def test_settings_page_autoloads_and_saves_select_value(client, org, admin):
    set_org_settings(org, {"meeting.stt_url": "http://172.30.1.50:8000"}, admin)
    client.force_login(admin)
    page = client.get(f"/orgs/{org.pk}/settings").content.decode()
    assert 'hx-trigger="load"' in page
    assert '<select id="setting-meeting.stt_model"' in page
    client.post(
        f"/orgs/{org.pk}/settings",
        {"meeting.stt_url": "http://172.30.1.50:8000", "meeting.stt_model": "large-v3"},
    )
    org.refresh_from_db()
    assert org.settings["meeting.stt_model"] == "large-v3"


BASE = "http://172.30.1.50:8000"
APPLY = "/orgs/{}/settings/stt-apply"


def test_apply_starts_download_saves_and_polls(client, org, admin, monkeypatch):
    def server(req):
        if req.get_method() == "POST":
            return b"{}"
        return b'{"data":[{"id":"large-v3","status":"downloading","progress":0.4}]}'

    seen = _fake(monkeypatch, server)
    client.force_login(admin)
    r = client.post(
        APPLY.format(org.pk), {"meeting.stt_url": BASE, "meeting.stt_model": "large-v3"}
    )
    body = r.content.decode()
    assert seen["calls"][0] == ("POST", BASE + "/v1/models/large-v3")
    org.refresh_from_db()
    assert org.settings["meeting.stt_model"] == "large-v3"
    assert "받는 중 40%" in body
    assert 'hx-trigger="load delay:3s"' in body  # 폴링 시작


def test_poll_stops_when_ready(client, org, admin, monkeypatch):
    _fake(monkeypatch, b'{"data":[{"id":"large-v3","status":"ready"}]}')
    client.force_login(admin)
    r = client.post(URL.format(org.pk), {"meeting.stt_url": BASE, "meeting.stt_model": "large-v3"})
    body = r.content.decode()
    assert "delay:3s" not in body
    assert '<option value="large-v3" selected>large-v3</option>' in body


def test_apply_on_server_without_status_only_saves(client, org, admin, monkeypatch):
    def server(req):
        if req.get_method() == "POST":
            return urllib.error.HTTPError(req.full_url, 405, "no", {}, None)
        return b'{"data":[{"id":"whisper-1"}]}'

    _fake(monkeypatch, server)
    client.force_login(admin)
    r = client.post(
        APPLY.format(org.pk), {"meeting.stt_url": BASE, "meeting.stt_model": "whisper-1"}
    )
    body = r.content.decode()
    org.refresh_from_db()
    assert org.settings["meeting.stt_model"] == "whisper-1"
    assert "적용해 저장" in body and "delay:3s" not in body


def test_apply_member_forbidden(client, org, member, monkeypatch):
    seen = _fake(monkeypatch, b"{}")
    client.force_login(member)
    r = client.post(APPLY.format(org.pk), {"meeting.stt_url": BASE, "meeting.stt_model": "x"})
    assert r.status_code == 403 and "req" not in seen
