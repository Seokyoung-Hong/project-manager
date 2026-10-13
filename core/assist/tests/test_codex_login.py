"""웹에서 시작하는 Codex 로그인(기기 코드): PC 주인만·도메인 검사·만료·코드가 새지 않음."""

import logging
from datetime import timedelta

import pytest
from django.http import Http404
from django.utils import timezone

from assist import codex_login
from assist.models import CODEX_URL, AiSource, CodexLogin
from notes.test_stt_link import _api, _beat, _link

pytestmark = pytest.mark.django_db


@pytest.fixture(autouse=True)
def _codex_on(settings):
    settings.ASSIST_CODEX_ENABLED = True


def _pc(client, tok, **extra):
    """정책을 아는 새 link의 heartbeat."""
    return _beat(client, tok, ai=1, codex_policy=2, **extra).json()


def _cmd(client, tok, action="login"):
    return _pc(client, tok).get(f"codex_{action}")


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
    assert "codex_login" not in _pc(client, tok)

    client.force_login(member)
    assert "Codex 로그인" in _page(client, src)
    html = _page(client, src, action="login")
    assert "요청 중" in html and 'hx-trigger="every 3s"' in html
    row = CodexLogin.objects.get(server=server)
    assert "codex_login" not in _pc(client, other_tok)  # 다른 PC로는 가지 않는다
    assert "codex_login" not in _beat(client, tok, ai=1).json()  # 정책을 모르는 옛 link엔 안 보냄
    cmd = _cmd(client, tok)
    assert cmd == {"id": row.pk, "attempt": row.attempt} and len(row.attempt) == 16
    att = row.attempt
    _page(client, src, action="login")  # 진행 중이면 새로 만들지 않는다
    assert CodexLogin.objects.get(server=server).pk == row.pk
    assert _report(client, other_tok, row.pk, attempt=att, url=URL, code=CODE).status_code == 404
    assert _report(client, tok, row.pk, url=URL, code=CODE).status_code == 409  # 시도 값 없음

    assert _report(
        client, tok, row.pk, attempt=att, url=URL, code=CODE, expires_in=7200
    ).json() == {"state": "code"}
    row.refresh_from_db()  # PC가 길게 보내도 처리방침대로 최대 15분
    assert row.expires_at <= timezone.now() + timedelta(minutes=15, seconds=5)
    assert "codex_login" not in _pc(client, tok)
    html = _page(client, src)
    assert CODE in html and URL in html and "직접 [Codex 로그인]을 눌러 시작한 경우에만" in html
    assert f'data-copy-text="{CODE}"' in html and "코드 복사" in html
    assert _report(client, tok, row.pk, attempt=att, done=True, logged_in=True).json() == {
        "state": "done"
    }
    server.refresh_from_db()
    assert server.device["codex"]["login"] is True
    html = _page(client, src)
    assert CODE not in html and "로그인됨" in html and "Codex 로그아웃" in html
    row.refresh_from_db()
    assert row.code == "" and row.url == ""
    assert _report(client, tok, row.pk, attempt=att, done=True).status_code == 409
    assert not any(CODE in r.getMessage() for r in caplog.records)  # 코드는 로그에 남지 않는다

    _page(client, src, action="logout")
    row.refresh_from_db()
    assert _cmd(client, tok, "logout") == {"id": row.pk, "attempt": row.attempt} != cmd


def test_late_report_of_old_attempt_does_not_finish_new_one(client, member):
    """로그인 A 완료 보고가 늦게 오는 사이 로그아웃 B를 시작하면(같은 행), A의 보고는 B를 끝내지 못한다."""
    server, tok = _link(client, member)
    a = codex_login.start(member, server, "login")
    att_a = a.attempt
    _report(client, tok, a.pk, attempt=att_a, url=URL, code=CODE)
    b = codex_login.start(member, server, "logout")
    assert b.pk == a.pk and b.attempt != att_a
    assert _report(client, tok, a.pk, attempt=att_a, done=True, logged_in=True).status_code == 409
    b.refresh_from_db()
    server.refresh_from_db()
    assert b.state == "requested" and b.action == "logout"
    assert "login" not in server.device.get("codex", {})
    assert (
        _report(client, tok, b.pk, attempt=b.attempt, done=True, logged_in=False).status_code == 200
    )
    server.refresh_from_db()
    assert server.device["codex"]["login"] is False


def test_switch_off_blocks_start_relay_and_reports(client, member, settings):
    """ASSIST_CODEX_ENABLED를 끄면 화면·시작·heartbeat 전달·보고가 모두 멈춘다(끄기 전에 접수한 명령 포함)."""
    server, tok = _link(client, member)
    src = _src(member, server)
    row = codex_login.start(member, server, "login")  # 켜져 있을 때 접수
    settings.ASSIST_CODEX_ENABLED = False
    assert "codex_login" not in _pc(client, tok)
    assert _report(client, tok, row.pk, attempt=row.attempt, url=URL, code=CODE).status_code == 409
    row.refresh_from_db()
    assert row.state == "expired" and row.code == ""
    client.force_login(member)
    r = client.post(f"/settings/ai/{src.pk}/codex", {"action": "logout"})
    assert r.status_code == 200 and r.content == b""
    assert client.get(f"/settings/ai/{src.pk}/codex").content == b""
    row.refresh_from_db()
    assert row.action == "login"  # 로그아웃은 접수되지 않았다
    with pytest.raises(Http404):
        codex_login.start(member, server, "login")


def test_sweep_wipes_expired_code_without_page_visit(client, member):
    from assist import worker

    server, tok = _link(client, member)
    row = codex_login.start(member, server, "login")
    _report(client, tok, row.pk, attempt=row.attempt, url=URL, code=CODE)
    CodexLogin.objects.filter(pk=row.pk).update(expires_at=timezone.now() - timedelta(seconds=1))
    worker.sweep()
    row.refresh_from_db()
    assert row.state == "expired" and row.code == "" and row.url == ""


def test_bad_port_is_refused_not_500():
    assert codex_login._ok_url("https://auth.openai.com:bad/x") is False


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
    assert _report(client, tok, row.pk, attempt=row.attempt, url=url, code=CODE).json() == {
        "state": "failed"
    }
    row.refresh_from_db()
    assert row.error == "bad_login_url" and row.url == "" and row.code == ""


def test_code_expires_and_is_wiped(client, member):
    server, tok = _link(client, member)
    row = codex_login.start(member, server, "login")
    _report(client, tok, row.pk, attempt=row.attempt, url=URL, code=CODE, expires_in=900)
    CodexLogin.objects.filter(pk=row.pk).update(expires_at=timezone.now() - timedelta(seconds=1))
    client.force_login(member)
    html = _page(client, _src(member, server))
    assert CODE not in html and "만료" in html
    row.refresh_from_db()
    assert row.state == "expired" and row.code == "" and row.url == ""
    assert (
        _report(client, tok, row.pk, attempt=row.attempt, done=True, logged_in=True).status_code
        == 409
    )


def test_docker_pc_shows_guidance_instead_of_button(client, member):
    server, tok = _link(client, member)
    _beat(client, tok, ai=1, device={"codex": {"docker": True}})
    src = _src(member, server)
    client.force_login(member)
    html = _page(client, src)
    assert "Docker로 설치" in html and "Codex 로그인</button>" not in html
    assert "Docker" in _page(client, src, action="login")
    assert not CodexLogin.objects.filter(server=server).exists()
