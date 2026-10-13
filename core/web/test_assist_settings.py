"""IMPL-PLAN-12 B 갈래: 설정 AI 탭·조직 AI 시험·운영 콘솔 허용 호스트. assist.net은 목으로 대체한다."""

import pytest
from cryptography.fernet import Fernet
from django.urls import reverse

from assist import net
from assist.models import AiSource, AllowedHost
from notes.models import SttServer
from ops.models import OpsAuditLog
from orgs.services import set_org_settings

KEY = "sk-very-secret-key-123"


@pytest.fixture(autouse=True)
def _crypto(settings):
    settings.CREDENTIAL_KEY = Fernet.generate_key().decode()


@pytest.fixture
def fake_net(monkeypatch):
    calls = []

    def classify(url):
        return "pc" if "localhost" in url or "192.168." in url else "direct"

    def list_models(base_url, *, api_key="", org=False, timeout_s=5):
        calls.append({"url": base_url, "key": api_key, "org": org, "timeout": timeout_s})
        if "down" in base_url:
            raise net.NetError("connect_failed")
        return ["model-a", "model-b"]

    monkeypatch.setattr(net, "classify", classify)
    monkeypatch.setattr(net, "list_models", list_models)
    return calls


def _add(client, **kw):
    data = {"name": "내 AI", "base_url": "https://api.example.com/v1", "model": "m", **kw}
    return client.post(reverse("settings_ai_add"), data)


def test_tab_lists_org_row_and_adds_direct_source_with_hidden_key(client, member, fake_net):
    client.force_login(member)
    r = client.get(reverse("settings_ai"))
    assert r.status_code == 200 and "조직 AI" in r.content.decode()
    assert AiSource.objects.filter(user=member, kind="org").count() == 1
    assert _add(client, api_key=KEY).status_code == 302
    src = AiSource.objects.get(user=member, kind="personal")
    assert src.route == "direct" and src.server is None and src.api_key.startswith("enc:")
    assert src.position > AiSource.objects.get(user=member, kind="org").position
    page = client.get(reverse("settings_ai")).content.decode()
    assert KEY not in page and src.api_key not in page and "설정됨" in page


def test_pc_route_requires_own_server(client, member, admin, fake_net):
    """불변식 1: route=pc면 server.owner == user. 남의 PC id를 위조해 넣어도 저장되지 않는다."""
    mine = SttServer.objects.create(owner=member, name="내 PC", machine_id="m1")
    other = SttServer.objects.create(owner=admin, name="남의 PC", machine_id="m2")
    client.force_login(member)
    url = "http://localhost:11434/v1"
    assert _add(client, base_url=url).status_code == 400  # PC 안 고름
    assert _add(client, base_url=url, server=other.pk).status_code == 400  # 남의 PC
    assert not AiSource.objects.filter(kind="personal").exists()
    assert _add(client, base_url=url, server=mine.pk).status_code == 302
    src = AiSource.objects.get(kind="personal")
    assert src.route == "pc" and src.server == mine
    # 공개 주소로 바꾸면 PC를 떼어 낸다
    client.post(
        reverse("settings_ai_row", args=[src.pk]),
        {"name": "x", "base_url": "https://api.example.com/v1", "server": mine.pk},
    )
    src.refresh_from_db()
    assert src.route == "direct" and src.server is None


def test_codex_source_needs_own_pc_and_takes_no_url_or_key(client, member, admin, fake_net):
    mine = SttServer.objects.create(owner=member, name="내 PC", machine_id="m1")
    other = SttServer.objects.create(owner=admin, name="남의 PC", machine_id="m2")
    client.force_login(member)
    assert _add(client, backend="codex", base_url="", model="").status_code == 400  # PC 안 고름
    assert _add(client, backend="codex", base_url="", server=other.pk).status_code == 400
    r = _add(
        client, name="Codex", backend="codex", base_url="", model="", api_key=KEY, server=mine.pk
    )
    assert r.status_code == 302
    src = AiSource.objects.get(kind="personal")
    assert src.is_codex and src.route == "pc" and src.server == mine and src.api_key == ""
    page = client.get(reverse("settings_ai")).content.decode()
    assert "Codex(내 구독)" in page and "Codex 기본 모델" in page


def test_unlinked_pc_row_shows_repick(client, member, fake_net):
    pc = SttServer.objects.create(owner=member, name="내 PC", machine_id="m1")
    client.force_login(member)
    _add(client, base_url="http://192.168.0.9:8000/v1", server=pc.pk)
    pc.delete()  # 연결 끊기 → SET_NULL
    page = client.get(reverse("settings_ai")).content.decode()
    assert "연결된 PC가 없습니다" in page and "PC 다시 고르기" in page


def test_cannot_touch_others_source(client, member, admin, fake_net):
    client.force_login(admin)
    _add(client)
    src = AiSource.objects.get(user=admin, kind="personal")
    client.force_login(member)
    for name, args in [
        ("settings_ai_row", [src.pk]),
        ("settings_ai_delete", [src.pk]),
        ("settings_ai_move", [src.pk, "up"]),
        ("settings_ai_test", [src.pk]),
        ("settings_ai_models", [src.pk]),
    ]:
        assert client.post(reverse(name, args=args), {"name": "탈취"}).status_code == 404, name
    assert client.get(reverse("settings_ai_row", args=[src.pk])).status_code == 404
    src.refresh_from_db()
    assert src.name == "내 AI"


def test_move_toggle_delete_and_org_row_not_deletable(client, member, fake_net):
    client.force_login(member)
    client.get(reverse("settings_ai"))
    _add(client)
    org_row = AiSource.objects.get(user=member, kind="org")
    personal = AiSource.objects.get(user=member, kind="personal")
    client.post(reverse("settings_ai_move", args=[personal.pk, "up"]))
    assert [s.kind for s in AiSource.objects.filter(user=member)] == ["personal", "org"]
    client.post(reverse("settings_ai_row", args=[org_row.pk]), {"action": "toggle"})
    org_row.refresh_from_db()
    assert org_row.enabled is False
    assert client.post(reverse("settings_ai_delete", args=[org_row.pk])).status_code == 403
    client.post(reverse("settings_ai_delete", args=[personal.pk]))
    assert not AiSource.objects.filter(pk=personal.pk).exists()


def test_test_and_models_use_gate_and_record_error(client, member, fake_net):
    client.force_login(member)
    _add(client, api_key=KEY)
    src = AiSource.objects.get(kind="personal")
    r = client.post(reverse("settings_ai_models", args=[src.pk]))
    assert r.status_code == 200 and "model-b" in r.content.decode()
    assert fake_net[-1] == {
        "url": "https://api.example.com/v1",
        "key": KEY,
        "org": False,
        "timeout": 5,
    }
    src.base_url = "https://down.example.com/v1"
    src.save()
    r = client.post(reverse("settings_ai_test", args=[src.pk]))
    assert "접속할 수 없습니다" in r.content.decode()
    src.refresh_from_db()
    assert src.last_error == "connect_failed"


def test_org_assist_test_admin_only_and_uses_gate(client, org, admin, member, fake_net):
    set_org_settings(
        org,
        {**org.settings, "assist.org_url": "https://llm.example.com/v1", "assist.org_api_key": KEY},
        admin,
    )
    org.refresh_from_db()
    client.force_login(member)
    assert client.post(reverse("org_assist_test", args=[org.pk])).status_code == 403
    assert client.post(reverse("org_assist_models", args=[org.pk])).status_code == 403
    assert fake_net == []
    client.force_login(admin)
    page = client.get(reverse("org_settings", args=[org.pk])).content.decode()
    assert "조직 AI 연결 시험" in page and KEY not in page
    r = client.post(reverse("org_assist_models", args=[org.pk]))
    body = r.content.decode()
    assert "model-a" in body and 'list="assist-org-models"' in body and KEY not in body
    assert fake_net[-1]["org"] is True and fake_net[-1]["key"] == KEY


def test_ops_assist_staff_only_and_audited(client, admin, member):
    client.force_login(member)
    assert client.get(reverse("ops_assist")).status_code == 404
    assert client.post(reverse("ops_assist"), {"host": "10.0.0.5"}).status_code == 404
    admin.is_staff = True
    admin.save()
    client.force_login(admin)
    assert client.get(reverse("ops_assist")).status_code == 200
    client.post(reverse("ops_assist"), {"host": "http://x/", "reason": "실험실 서버"})
    client.post(reverse("ops_assist"), {"host": "LLM.Lab.Internal", "reason": "짧"})
    assert not AllowedHost.objects.exists()
    client.post(reverse("ops_assist"), {"host": "LLM.Lab.Internal", "reason": "실험실 서버 허용"})
    row = AllowedHost.objects.get()
    assert row.host == "llm.lab.internal" and row.added_by == admin
    assert OpsAuditLog.objects.filter(action="assist.host_add", target_id=row.pk).exists()
    assert client.get(reverse("ops_assist_delete", args=[row.pk])).status_code == 200
    client.post(reverse("ops_assist_delete", args=[row.pk]), {"reason": "더 이상 쓰지 않음"})
    assert not AllowedHost.objects.exists()
    assert OpsAuditLog.objects.filter(action="assist.host_remove").exists()
