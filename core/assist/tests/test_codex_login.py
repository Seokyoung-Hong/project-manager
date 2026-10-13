"""웹에서 시작하는 Codex 로그인(기기 코드): PC 주인만·도메인 검사·만료·코드가 새지 않음."""

import logging
from datetime import timedelta

import pytest
from django.utils import timezone

from assist import codex_login
from assist.models import CODEX_URL, AiSource, CodexLogin
from notes.test_stt_link import _api, _beat, _link

pytestmark = pytest.mark.django_db
CODE = "ABCD-EFGH1"
URL = "https://auth.openai.com/codex/device"


def _src(user, server):
    return AiSource.objects.create(
        user=user, name="Codex", base_url=CODEX_URL, route="pc", server=server
    )


def _report(client, tok, login_id, **data):
    return _api(client, "post", f"/api/integrations/stt/codex-login/{login_id}", data, tok)


def _page(client, src, **post):
    url = f"/settings/ai/{src.pk}/codex"
    return (client.post(url, post) if post else client.get(url)).content.decode()


def test_login_flow_owner_only(client, member, admin, caplog):
    caplog.set_level(logging.DEBUG)
    server, tok = _link(client, member)
    other, other_tok = _link(client, admin)
    src = _src(member, server)
    client.force_login(admin)
    assert (
        client.post(f"/settings/ai/{src.pk}/codex", {"action": "login"}).status_code == 404
    )  # 남의 AI
    theirs = _src(admin, server)  # 남의 PC를 고른 행(불변식 위반 데이터)도 명령을 걸지 못한다
    assert client.post(f"/settings/ai/{theirs.pk}/codex", {"action": "login"}).status_code == 403
    assert "codex_login" not in _beat(client, tok, ai=1).json()

    client.force_login(member)
    assert "Codex 로그인" in _page(client, src)
    html = _page(client, src, action="login")
    assert "요청 중" in html and 'hx-trigger="every 3s"' in html
    row = CodexLogin.objects.get(server=server)
    assert "codex_login" not in _beat(client, other_tok, ai=1).json()  # 다른 PC로는 가지 않는다
    assert _beat(client, tok, ai=1).json()["codex_login"] == {"id": row.pk}
    _page(client, src, action="login")  # 진행 중이면 새로 만들지 않는다
    assert CodexLogin.objects.get(server=server).pk == row.pk
    assert _report(client, other_tok, row.pk, url=URL, code=CODE).status_code == 404  # 남의 요청

    assert _report(client, tok, row.pk, url=URL, code=CODE, expires_in=900).json() == {
        "state": "code"
    }
    assert "codex_login" not in _beat(client, tok, ai=1).json()
    html = _page(client, src)
    assert CODE in html and URL in html and "직접 [Codex 로그인]을 누른 경우에만" in html
    assert _report(client, tok, row.pk, done=True, logged_in=True).json() == {"state": "done"}
    server.refresh_from_db()
    assert server.device["codex"]["login"] is True
    html = _page(client, src)
    assert CODE not in html and "로그인됨" in html and "Codex 로그아웃" in html
    row.refresh_from_db()
    assert row.code == "" and row.url == ""
    assert _report(client, tok, row.pk, done=True).status_code == 409
    assert not any(CODE in r.getMessage() for r in caplog.records)  # 코드는 로그에 남지 않는다

    _page(client, src, action="logout")
    assert _beat(client, tok, ai=1).json()["codex_logout"] == {"id": row.pk}


@pytest.mark.parametrize(
    "url",
    [
        "https://evil.example/codex/device",
        "http://auth.openai.com/x",
        "https://auth.openai.com.evil.io/",
    ],
)
def test_unexpected_login_url_is_refused(client, member, url):
    server, tok = _link(client, member)
    row = codex_login.start(member, server, "login")
    assert _report(client, tok, row.pk, url=url, code=CODE).json() == {"state": "failed"}
    row.refresh_from_db()
    assert row.error == "bad_login_url" and row.url == "" and row.code == ""


def test_code_expires_and_is_wiped(client, member):
    server, tok = _link(client, member)
    row = codex_login.start(member, server, "login")
    _report(client, tok, row.pk, url=URL, code=CODE, expires_in=900)
    CodexLogin.objects.filter(pk=row.pk).update(expires_at=timezone.now() - timedelta(seconds=1))
    client.force_login(member)
    html = _page(client, _src(member, server))
    assert CODE not in html and "만료" in html
    row.refresh_from_db()
    assert row.state == "expired" and row.code == "" and row.url == ""
    assert _report(client, tok, row.pk, done=True, logged_in=True).status_code == 409


def test_docker_pc_shows_guidance_instead_of_button(client, member):
    server, tok = _link(client, member)
    _beat(client, tok, ai=1, device={"codex": {"docker": True}})
    src = _src(member, server)
    client.force_login(member)
    html = _page(client, src)
    assert "Docker로 설치" in html and "Codex 로그인</button>" not in html
    assert "Docker" in _page(client, src, action="login")
    assert not CodexLogin.objects.filter(server=server).exists()
