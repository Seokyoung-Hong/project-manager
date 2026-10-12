"""조직 설정 [연결 시험] — 로컬 전사 서버 GET /v1/models."""

import io
import urllib.error

import pytest
from cryptography.fernet import Fernet

from orgs.services import set_org_settings

pytestmark = pytest.mark.django_db
URL = "/orgs/{}/settings/stt-test"


class _Resp(io.BytesIO):
    def __enter__(self):
        return self

    def __exit__(self, *a):
        return False


def _fake(monkeypatch, result):
    seen = {}

    def open_(self, req, timeout=None):
        seen["req"], seen["timeout"] = req, timeout
        if isinstance(result, Exception):
            raise result
        return _Resp(result)

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
    assert "large-v3" in body and "small" in body
    assert "sk-local-secret" not in body
    assert seen["req"].full_url == "http://172.30.1.50:8000/v1/models"
    assert seen["req"].get_header("Authorization") == "Bearer sk-local-secret"
    assert seen["timeout"] == 5


def test_401_is_auth_failure(client, org, admin, monkeypatch):
    _fake(monkeypatch, urllib.error.HTTPError("u", 401, "no", {}, None))
    client.force_login(admin)
    r = client.post(URL.format(org.pk), {"meeting.stt_url": "http://172.30.1.50:8000"})
    assert "인증에 실패" in r.content.decode()


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
