"""개인 AI OAuth 연결(assist/oauth.py). 공급자 호출은 net._request 목으로 대체한다(실제 외부 호출 없음)."""

import json
import time
from urllib.parse import parse_qs, urlsplit

import pytest
from cryptography.fernet import Fernet
from django.urls import reverse

from accounts.models import pkce_challenge
from assist import net, oauth
from assist.models import AiSource
from github.crypto import decrypt, encrypt

OR_KEY = "sk-or-v1-" + "a" * 40
HF_TOKEN = "hf_oauth_" + "b" * 30


@pytest.fixture(autouse=True)
def _crypto(settings):
    settings.CREDENTIAL_KEY = Fernet.generate_key().decode()
    settings.SITE_URL = "https://udally.example"
    settings.HF_OAUTH_CLIENT_ID = "hf-client"
    settings.HF_OAUTH_CLIENT_SECRET = "hf-secret"


@pytest.fixture
def fake(monkeypatch):
    calls = []

    def _request(method, base_url, path, **kw):
        calls.append({"url": base_url + path, **kw})
        if path == "/auth/keys":
            return {"key": OR_KEY}
        if kw["form"]["grant_type"] == "refresh_token":
            return {"access_token": "hf_new_" + "c" * 30, "expires_in": 3600}
        return {"access_token": HF_TOKEN, "refresh_token": "hf_refresh", "expires_in": 28800}

    monkeypatch.setattr(net, "_request", _request)
    return calls


def _start(client, provider):
    r = client.post(reverse("settings_ai_oauth", args=[provider]))
    assert r.status_code == 302
    return parse_qs(urlsplit(r["Location"]).query)


def _callback(client, provider, state, code="c0de"):
    return client.get(
        reverse("settings_ai_oauth_callback", args=[provider]), {"state": state, "code": code}
    )


def test_buttons_hidden_without_hf_client_id(client, member, settings):
    client.force_login(member)
    page = client.get(reverse("settings_ai")).content.decode()
    assert "OpenRouter 계정으로 연결" in page and "Hugging Face 계정으로 연결" in page
    settings.HF_OAUTH_CLIENT_ID = ""
    page = client.get(reverse("settings_ai")).content.decode()
    assert "Hugging Face 계정으로 연결" not in page
    assert client.post(reverse("settings_ai_oauth", args=["hf"])).status_code == 404
    assert client.post(reverse("settings_ai_oauth", args=["nope"])).status_code == 404


def test_openrouter_pkce_creates_direct_source_and_hides_key(client, member, fake):
    client.force_login(member)
    q = _start(client, "openrouter")
    assert q["code_challenge_method"] == ["S256"]
    assert q["callback_url"] == ["https://udally.example/settings/ai/oauth/openrouter/callback"]
    assert _callback(client, "openrouter", q["state"][0]).status_code == 302
    body = fake[0]["body"]
    assert fake[0]["url"] == "https://openrouter.ai/api/v1/auth/keys"
    assert pkce_challenge(body["code_verifier"]) == q["code_challenge"][0]
    src = AiSource.objects.get(user=member, kind="personal")
    assert (src.base_url, src.route, src.model) == (
        oauth.OPENROUTER_URL,
        "direct",
        "openrouter/auto",
    )
    assert src.api_key.startswith("enc:") and decrypt(src.api_key[4:]) == OR_KEY
    page = client.get(reverse("settings_ai")).content.decode()
    assert OR_KEY not in page and src.api_key not in page
    # 다시 연결하면 같은 행의 키만 바뀐다
    _callback(client, "openrouter", _start(client, "openrouter")["state"][0])
    assert AiSource.objects.filter(user=member, kind="personal").count() == 1
    # 삭제하면 OpenRouter에서 키를 지우라는 안내
    r = client.post(reverse("settings_ai_delete", args=[src.pk]), follow=True)
    assert "openrouter.ai/settings/keys" in r.content.decode()


def test_forged_and_replayed_state_rejected(client, member, fake):
    client.force_login(member)
    q = _start(client, "openrouter")
    r = _callback(client, "openrouter", "forged", code="x")
    assert r.status_code == 302 and not fake
    # 위조로 시도가 소진됐으니 진짜 state도 이제 안 된다(1회용)
    _callback(client, "openrouter", q["state"][0])
    q = _start(client, "openrouter")
    _callback(client, "openrouter", q["state"][0])
    assert len(fake) == 1
    _callback(client, "openrouter", q["state"][0])  # 재사용
    assert len(fake) == 1
    assert AiSource.objects.filter(user=member, kind="personal").count() == 1


def test_callback_of_other_user_rejected(client, member, admin, fake):
    client.force_login(member)
    q = _start(client, "openrouter")
    client.force_login(admin)  # 다른 사람으로 바뀐 브라우저(세션 비움)
    _callback(client, "openrouter", q["state"][0])
    s = client.session
    s["ai_oauth_openrouter"] = {"state": "s", "verifier": "v", "uid": member.pk}  # 남의 시도
    s.save()
    _callback(client, "openrouter", "s")
    assert not fake and not AiSource.objects.filter(kind="personal").exists()


def test_denied_does_not_exchange(client, member, fake):
    client.force_login(member)
    q = _start(client, "openrouter")
    r = client.get(
        reverse("settings_ai_oauth_callback", args=["openrouter"]),
        {"state": q["state"][0], "error": "access_denied"},
    )
    assert r.status_code == 302 and not fake


def test_hf_token_stored_refreshed_and_used(client, member, fake):
    client.force_login(member)
    q = _start(client, "hf")
    assert q["scope"] == ["openid inference-api"] and q["client_id"] == ["hf-client"]
    _callback(client, "hf", q["state"][0])
    assert fake[0]["basic"] == ("hf-client", "hf-secret")
    assert (
        fake[0]["form"]["code_verifier"] and fake[0]["form"]["grant_type"] == "authorization_code"
    )
    src = AiSource.objects.get(user=member, kind="personal")
    assert src.base_url == oauth.HF_URL and src.route == "direct"
    assert HF_TOKEN not in src.api_key and "hf_refresh" not in src.api_key
    assert HF_TOKEN not in client.get(reverse("settings_ai")).content.decode()
    assert oauth.source_key(src) == HF_TOKEN and len(fake) == 1  # 아직 유효: 갱신 없음
    # 만료 → 갱신 토큰으로 새 토큰, 새 갱신 토큰이 없으면 옛것 유지
    d = json.loads(decrypt(src.api_key[4:]))
    d["exp"] = int(time.time()) - 1
    src.api_key = "enc:" + encrypt(json.dumps(d))
    src.save()
    assert oauth.source_key(src).startswith("hf_new_")
    assert fake[-1]["form"] == {
        "grant_type": "refresh_token",
        "refresh_token": "hf_refresh",
        "client_id": "hf-client",
    }
    src.refresh_from_db()
    assert json.loads(decrypt(src.api_key[4:]))["r"] == "hf_refresh"
    # 갱신 토큰이 없고 만료됐으면 다시 연결해야 한다
    d = {"hf": 1, "a": "x", "r": "", "exp": 0}
    src.api_key = "enc:" + encrypt(json.dumps(d))
    src.save()
    with pytest.raises(net.NetError) as e:
        oauth.source_key(src)
    assert e.value.code == "auth_failed"


def test_hf_token_not_sent_to_changed_url(client, member, fake, monkeypatch):
    monkeypatch.setattr(net, "classify", lambda url: "direct")
    client.force_login(member)
    _callback(client, "hf", _start(client, "hf")["state"][0])
    src = AiSource.objects.get(user=member, kind="personal")
    client.post(
        reverse("settings_ai_row", args=[src.pk]),
        {"name": "x", "base_url": "https://evil.example/v1", "model": "m"},
    )
    src.refresh_from_db()
    assert src.base_url == "https://evil.example/v1" and src.api_key == ""


def test_hf_refresh_failure_is_auth_failed(member, monkeypatch, db):
    def boom(*a, **kw):
        raise net.NetError("http_4xx")

    monkeypatch.setattr(net, "_request", boom)
    blob = json.dumps({"hf": 1, "a": "x", "r": "r", "exp": 0})
    src = AiSource.objects.create(
        user=member, base_url=oauth.HF_URL, route="direct", api_key="enc:" + encrypt(blob)
    )
    with pytest.raises(net.NetError) as e:
        oauth.source_key(src)
    assert e.value.code == "auth_failed"
