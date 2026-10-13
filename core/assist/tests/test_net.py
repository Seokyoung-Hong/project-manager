"""관문 assist.net(IMPL-PLAN-12 §11.1·§6.1). DNS는 가짜 getaddrinfo, 연결은 로컬 가짜 서버로만 — 외부 호출 없음."""

import json
import socket
import threading
import time
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

import pytest

from assist import net
from assist.models import AllowedHost
from assist.net import NetError
from common.errors import ServiceError


def _fake_dns(monkeypatch, table):
    """table: 호스트 → IP 목록(호출마다 다른 값을 주려면 리스트의 리스트). 호출 기록을 돌려준다."""
    calls = []
    real = socket.getaddrinfo

    def fake(host, port, *a, **kw):
        if host == "127.0.0.1":  # 가짜 서버로 돌려 보내는 진짜 연결
            return real(host, port, *a, **kw)
        calls.append(host)
        got = table.get(host)
        if got is None:
            raise socket.gaierror("no such host")
        if got and isinstance(got[0], list):
            got = got[min(len(calls), len(got)) - 1]
        return [(socket.AF_INET, socket.SOCK_STREAM, 6, "", (ip, port)) for ip in got]

    monkeypatch.setattr(net.socket, "getaddrinfo", fake)
    return calls


@pytest.mark.parametrize(
    "url",
    [
        "https://127.0.0.1/v1",
        "https://localhost/v1",
        "https://2130706433/v1",
        "https://0x7f.1/v1",
        "https://127.1/v1",
        "https://[::1]/v1",
        "https://[::ffff:127.0.0.1]/v1",
        "https://[64:ff9b::a9fe:a9fe]/v1",  # NAT64 안의 169.254.169.254
        "https://169.254.169.254/latest",
        "https://0.0.0.0/v1",
        "https://100.64.0.1/v1",
        "https://10.0.0.5/v1",
        "https://[fd00::1]/v1",
        "https://[fe80::1]/v1",
        "https://user@ai.example.com/v1",
        "https://ai.example.com/v1?x=1",
        "https://db/v1",
        "ftp://ai.example.com/v1",
    ],
)
@pytest.mark.django_db
def test_gate_blocks(url, monkeypatch):
    _fake_dns(monkeypatch, {"ai.example.com": ["93.184.216.34"]})
    for org in (False, True):
        with pytest.raises(NetError) as e:
            net.check(url, org=org)
        assert e.value.code == "blocked_address"


@pytest.mark.django_db
def test_gate_all_ips_and_https(monkeypatch):
    _fake_dns(
        monkeypatch,
        {
            "ai.example.com": ["93.184.216.34"],
            "mixed.example.com": ["93.184.216.34", "10.1.2.3"],
            "meta.example.com": ["169.254.169.254"],
        },
    )
    assert net.check("https://ai.example.com/v1")[1] == "93.184.216.34"
    with pytest.raises(NetError):
        net.check("http://ai.example.com/v1")  # 공개 주소는 https만
    with pytest.raises(NetError):
        net.check("https://mixed.example.com/v1")  # 하나라도 사설이면 거부
    with pytest.raises(NetError):
        net.check("https://meta.example.com/v1", org=True)
    with pytest.raises(NetError) as e:
        net.check("https://nowhere.example.com/v1")
    assert e.value.code == "connect_failed"


@pytest.mark.django_db
def test_allowed_host_exact_and_org_only(monkeypatch):
    _fake_dns(
        monkeypatch,
        {
            "llm.corp.example": ["10.0.0.5"],
            "x.llm.corp.example": ["10.0.0.6"],
            "loop.corp.example": ["127.0.0.1"],
            "meta.corp.example": ["169.254.169.254"],
        },
    )
    for h in ("llm.corp.example", "loop.corp.example", "meta.corp.example", "10.0.0.7"):
        AllowedHost.objects.create(host=h)
    assert net.check("http://llm.corp.example:8080/v1", org=True)[1] == "10.0.0.5"
    assert net.check("http://10.0.0.7/v1", org=True)[1] == "10.0.0.7"
    for url in ("http://x.llm.corp.example/v1", "https://corp.example.llm/v1"):
        with pytest.raises(NetError):
            net.check(url, org=True)  # 부분 일치는 안 된다
    for url in ("http://loop.corp.example/v1", "http://meta.corp.example/v1"):
        with pytest.raises(NetError):
            net.check(url, org=True)  # 허용돼도 루프백·메타데이터는 거부
    with pytest.raises(NetError):
        net.check("http://llm.corp.example/v1", org=False)  # 개인 AI는 허용 목록을 보지 않는다


@pytest.mark.django_db
def test_classify(monkeypatch):
    _fake_dns(
        monkeypatch,
        {"ai.example.com": ["93.184.216.34"], "nas.example.com": ["192.168.0.10"]},
    )
    AllowedHost.objects.create(host="nas.example.com")  # 개인 AI 판정과 무관
    assert net.classify("http://localhost:11434/v1") == "pc"
    assert net.classify("http://host.docker.internal:1234/v1") == "pc"
    assert net.classify("http://gpu-box:8000/v1") == "pc"
    assert net.classify("http://ollama.lan/v1") == "pc"
    assert net.classify("http://127.0.0.1:11434/v1") == "pc"
    assert net.classify("https://nas.example.com/v1") == "pc"
    assert net.classify("https://ai.example.com/v1") == "direct"
    assert net.classify("https://[2001:4860:4860::8888]/v1") == "direct"
    for bad in (
        "http://ai.example.com/v1",
        "https://nowhere.example.com/v1",
        "https://u@x.example/v1",
    ):
        with pytest.raises(ServiceError):
            net.classify(bad)


@pytest.mark.django_db
def test_check_org_url_without_dns(monkeypatch):
    calls = _fake_dns(monkeypatch, {})
    assert net.check_org_url("https://api.example.com/v1") == ""
    assert net.check_org_url("http://api.example.com/v1")  # http는 허용 호스트만
    assert net.check_org_url("http://10.0.0.5/v1")
    assert net.check_org_url("https://db/v1")
    assert net.check_org_url("https://169.254.169.254/v1")
    AllowedHost.objects.create(host="10.0.0.5")
    AllowedHost.objects.create(host="169.254.169.254")
    assert net.check_org_url("http://10.0.0.5/v1") == ""
    assert net.check_org_url("https://169.254.169.254/v1")  # 허용 목록으로도 못 연다
    assert calls == []  # 저장 검사는 DNS를 묻지 않는다


@pytest.mark.django_db
def test_rebinding_connects_to_checked_ip(monkeypatch):
    """두 번째 해석이 루프백을 줘도 처음 판정한 IP로만 연결한다."""
    calls = _fake_dns(monkeypatch, {"ai.example.com": [["93.184.216.34"], ["127.0.0.1"]]})
    seen = []

    def fake_connect(addr, *a, **kw):
        seen.append(addr)
        raise OSError("refused")

    monkeypatch.setattr(net.socket, "create_connection", fake_connect)
    with pytest.raises(NetError) as e:
        net.chat("https://ai.example.com/v1", {"model": "m"}, api_key="sk-secret")
    assert e.value.code == "connect_failed"
    assert seen == [("93.184.216.34", 443)] and len(calls) == 1


# ---------- 로컬 가짜 서버(허용 호스트로 연결을 돌려 보낸다) ----------


class _H(BaseHTTPRequestHandler):
    seen = []

    def log_message(self, *a):
        pass

    def _send(self, status, body=b"", headers=None):
        self.send_response(status)
        for k, v in (headers or {}).items():
            self.send_header(k, v)
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    def do_GET(self):
        _H.seen.append((self.path, dict(self.headers)))
        if self.path == "/v1/models":
            self._send(200, json.dumps({"data": [{"id": "llama3"}, {"id": "qwen"}]}).encode())
        else:
            self._send(404)

    def do_POST(self):
        n = int(self.headers.get("Content-Length") or 0)
        body = json.loads(self.rfile.read(n) or b"{}")
        _H.seen.append((self.path, dict(self.headers), body))
        p = self.path
        if p.startswith("/redir"):
            self._send(302, headers={"Location": "http://169.254.169.254/"})
        elif p.startswith("/big"):
            self._send(200, b"{" + b" " * (net.MAX_BODY + 10) + b"}")
        elif p.startswith("/slow"):
            time.sleep(1.5)
            self._send(200, b"{}")
        elif p.startswith("/s401"):
            self._send(401)
        elif p.startswith("/s400"):
            self._send(400)
        elif p.startswith("/s500"):
            self._send(500)
        else:
            out = {"choices": [{"message": {"content": "안녕하세요"}}]}
            self._send(200, json.dumps(out).encode())


@pytest.fixture
def fake_llm(monkeypatch, db):
    srv = ThreadingHTTPServer(("127.0.0.1", 0), _H)
    threading.Thread(target=srv.serve_forever, daemon=True).start()
    _H.seen = []
    _fake_dns(monkeypatch, {"llm.corp.example": ["10.0.0.5"]})
    AllowedHost.objects.create(host="llm.corp.example")
    real = socket.create_connection
    pinned = []

    def to_local(addr, *a, **kw):
        pinned.append(addr)
        return real(("127.0.0.1", srv.server_address[1]), *a, **kw)

    monkeypatch.setattr(net.socket, "create_connection", to_local)
    yield pinned
    srv.shutdown()


def test_chat_and_models_through_gate(fake_llm):
    out = net.chat("http://llm.corp.example:8080/v1", {"model": "m"}, api_key="k", org=True)
    assert out["choices"][0]["message"]["content"] == "안녕하세요"
    path, headers, body = _H.seen[-1]
    assert path == "/v1/chat/completions" and body == {"model": "m"}
    assert headers["Host"] == "llm.corp.example:8080"
    assert headers["Authorization"] == "Bearer k"
    assert fake_llm == [("10.0.0.5", 8080)]
    assert net.list_models("http://llm.corp.example/v1", org=True) == ["llama3", "qwen"]


@pytest.mark.parametrize(
    "path,code",
    [
        ("/redir", "blocked_address"),
        ("/big", "too_large"),
        ("/s401", "auth_failed"),
        ("/s500", "http_5xx"),
        ("/nope", "model_not_found"),
    ],
)
def test_chat_failures(fake_llm, path, code):
    base = f"http://llm.corp.example{path}"
    if path == "/nope":
        with pytest.raises(NetError) as e:
            net.list_models(base, org=True)
    else:
        with pytest.raises(NetError) as e:
            net.chat(base, {}, org=True)
    assert e.value.code == code


def test_chat_timeout_and_400_status(fake_llm):
    with pytest.raises(NetError) as e:
        net.chat("http://llm.corp.example/slow", {}, org=True, timeout_s=1)
    assert e.value.code == "timeout"
    with pytest.raises(NetError) as e:
        net.chat("http://llm.corp.example/s400", {}, org=True)
    assert e.value.code == "http_4xx" and e.value.status == 400


def test_proxy_env_ignored(fake_llm, monkeypatch):
    monkeypatch.setenv("HTTPS_PROXY", "http://203.0.113.1:3128")
    monkeypatch.setenv("HTTP_PROXY", "http://203.0.113.1:3128")
    net.chat("http://llm.corp.example/v1", {}, org=True)
    assert fake_llm[-1] == ("10.0.0.5", 80)
