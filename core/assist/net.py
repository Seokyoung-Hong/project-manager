"""모든 서버발 AI 호출의 관문(IMPL-PLAN-12 §11.1·§6.1).

IP 고정·리다이렉트 거부·1MB 상한. 기존 _stt_call·validate_stt_url은 쓰지 않는다.
실패는 NetError(code), code는 assist.models.ERROR_CODES 중 하나.

- 주소를 해석한 **모든** IP를 판정하고, 통과한 첫 IP로 직접 연결한다(DNS 재바인딩 차단).
  TLS는 원래 호스트 이름으로 검증한다(인증서 검증 유지).
- http.client를 직접 쓰므로 리다이렉트를 따라가지 않고 프록시 환경 변수도 보지 않는다.
"""

import http.client
import ipaddress
import json
import socket
import ssl
import time
from urllib.parse import urlsplit

from common.errors import ServiceError

MAX_BODY = 1024 * 1024  # 응답 상한(읽으며 센다)
CONNECT_S = 5
MAX_URL = 300

# 사설(허용 호스트면 조직 AI만 연다). 그 밖의 비공개 대역은 항상 거부한다.
_PRIVATE = [
    ipaddress.ip_network(n)
    for n in ("10.0.0.0/8", "172.16.0.0/12", "192.168.0.0/16", "100.64.0.0/10", "fc00::/7")
]
_NAT64 = ipaddress.ip_network("64:ff9b::/96")
# PC 안 주소로 보는 이름(개인 AI 판정, §6.1). 관문에서는 사설과 같게 다룬다(해석 결과로 다시 판정).
_LOCAL_NAMES = ("localhost", "host.docker.internal")
_LOCAL_SUFFIXES = (".localhost", ".local", ".lan", ".home.arpa")


class NetError(Exception):
    def __init__(self, code: str):
        self.code = code
        super().__init__(code)


def _ip_kind(ip) -> str:
    """public | private | blocked. IPv4 매핑·NAT64·6to4·Teredo는 안쪽 IPv4로 다시 판정한다."""
    if ip.version == 6:
        inner = []
        if ip.ipv4_mapped:
            inner.append(ip.ipv4_mapped)
        if ip in _NAT64:
            inner.append(ipaddress.IPv4Address(int(ip) & 0xFFFFFFFF))
        if ip.sixtofour:
            inner.append(ip.sixtofour)
        if ip.teredo:
            inner.extend(ip.teredo)
        if inner:
            kinds = {_ip_kind(i) for i in inner}
            return (
                "blocked" if "blocked" in kinds else ("private" if "private" in kinds else "public")
            )
    if any(ip in n for n in _PRIVATE):
        return "private"
    if ip.is_global and not ip.is_multicast:
        return "public"
    return "blocked"  # 루프백·링크로컬(메타데이터)·0/8·멀티캐스트·예약·문서용 등


def _parse(url: str):
    """형식만 본다. 틀리면 None."""
    if not url or len(url) > MAX_URL:
        return None
    try:
        parts = urlsplit(url)
        _ = parts.port
    except ValueError:
        return None
    if parts.scheme not in ("http", "https") or not parts.hostname:
        return None
    if parts.username or parts.password or parts.query or parts.fragment or "@" in parts.netloc:
        return None
    return parts


def _literal(host: str):
    try:
        return ipaddress.ip_address(host)
    except ValueError:
        return None


def _numeric_like(host: str) -> bool:
    """`2130706433`·`0x7f.1`·`127.1`처럼 inet_aton이 IP로 읽는 꼴. 정식 IP가 아니면 거부한다."""
    last = host.rsplit(".", 1)[-1]
    return last.isdigit() or last.startswith("0x")


def _resolve(host: str, port: int) -> list:
    try:
        infos = socket.getaddrinfo(host, port, type=socket.SOCK_STREAM)
    except (OSError, UnicodeError):
        raise NetError("connect_failed") from None
    ips = []
    for info in infos:
        ip = ipaddress.ip_address(info[4][0].split("%")[0])
        if ip not in ips:
            ips.append(ip)
    if not ips:
        raise NetError("connect_failed")
    return ips


def _host_allowed(host: str) -> bool:
    from .models import AllowedHost

    return AllowedHost.objects.filter(host=host).exists()


def check(url: str, *, org: bool = False):
    """관문 판정 → (parts, 연결할 IP 문자열). 실패는 NetError.

    사설은 조직 AI이고 호스트 문자열이 AllowedHost와 정확히 일치할 때만. http도 그때만.
    """
    parts = _parse(url)
    if parts is None:
        raise NetError("blocked_address")
    host = parts.hostname.lower()
    port = parts.port or (443 if parts.scheme == "https" else 80)
    lit = _literal(host)
    if lit is not None:
        ips = [lit]
    elif "." not in host or _numeric_like(host):
        raise NetError("blocked_address")  # compose 서비스 이름(db·web)·숫자 꼴 우회
    else:
        ips = _resolve(host, port)
    kinds = {_ip_kind(ip) for ip in ips}
    if "blocked" in kinds:
        raise NetError("blocked_address")
    allowed = org and _host_allowed(host)
    if "private" in kinds and not allowed:
        raise NetError("blocked_address")
    if parts.scheme == "http" and not allowed:
        raise NetError("blocked_address")
    return parts, str(ips[0])


def classify(url: str) -> str:
    """개인 AI 주소 판정: "direct"(모두 공개 IP, https만) | "pc"(PC 안·사설). 쓸 수 없으면 ServiceError."""
    parts = _parse(url)
    if parts is None:
        raise ServiceError(
            {
                "base_url": "AI 서버 주소 형식이 올바르지 않습니다. http:// 또는 https://로 시작하고 사용자 정보·쿼리를 포함하지 않는 주소를 입력해 주세요."
            }
        )  # COPY:assist_url_invalid
    host = parts.hostname.lower()
    lit = _literal(host)
    if lit is None and (
        host in _LOCAL_NAMES
        or host.endswith(_LOCAL_SUFFIXES)
        or "." not in host
        or _numeric_like(host)
    ):
        return "pc"
    try:
        ips = [lit] if lit is not None else _resolve(host, parts.port or 443)
    except NetError:
        raise ServiceError(
            {
                "base_url": "AI 서버 주소를 찾을 수 없습니다. 호스트 이름과 네트워크 연결을 확인해 주세요."
            }
        ) from None  # COPY:assist_url_unresolved
    if any(_ip_kind(ip) != "public" for ip in ips):
        return "pc"
    if parts.scheme != "https":
        raise ServiceError(
            {
                "base_url": "공개 AI 서버 주소에는 HTTPS가 필요합니다. https://로 시작하는 주소를 입력해 주세요."
            }
        )  # COPY:assist_url_https
    return "direct"


def check_org_url(url: str) -> str:
    """조직 AI 주소 검사(조직 설정 validate). 오류 문구, ""면 통과.

    저장 때는 DNS를 묻지 않는다(설정 저장이 외부 조회에 기대지 않게). IP 리터럴·이름 꼴·http 여부만 보고,
    해석한 IP 판정은 실행할 때마다 check()가 다시 한다.
    """
    if not url:
        return ""
    parts = _parse(url)
    if parts is None:
        try:
            p = urlsplit(url)
            _ = p.port
        except ValueError:
            return "AI 서버 주소 형식이 올바르지 않습니다. http:// 또는 https://로 시작하고 사용자 정보·쿼리를 포함하지 않는 주소를 입력해 주세요."  # COPY:assist_url_invalid
        if p.scheme not in ("http", "https") or not p.hostname:
            return "AI 서버 주소에 통신 방식 또는 호스트가 없습니다. http:// 또는 https://로 시작하는 전체 주소를 입력해 주세요."  # COPY:assist_url_scheme
        return "AI 서버 주소에 사용자 정보 또는 쿼리가 포함되어 있습니다. 해당 정보를 제외한 주소를 입력해 주세요."  # COPY:assist_url_extra
    blocked = "보안 제한으로 사용할 수 없는 주소입니다. 공개 HTTPS 주소를 사용하거나, 사설망 주소이면 서비스 운영자에게 허용 호스트 등록 가능 여부를 문의해 주세요."  # COPY:assist_url_blocked
    host = parts.hostname.lower()
    lit = _literal(host)
    kind = _ip_kind(lit) if lit is not None else "public"
    if kind == "blocked" or (lit is None and ("." not in host or _numeric_like(host))):
        return blocked
    local = kind == "private" or host in _LOCAL_NAMES or host.endswith(_LOCAL_SUFFIXES)
    if (local or parts.scheme == "http") and not _host_allowed(host):  # 공개 https는 DB도 안 본다
        return (
            blocked
            if local
            else "공개 AI 서버 주소에는 HTTPS가 필요합니다. https://로 시작하는 주소를 입력해 주세요."
        )  # COPY:assist_url_https
    return ""


# ---------- 연결 ----------


class _Conn(http.client.HTTPConnection):
    """관문이 고른 IP로만 소켓을 연다. Host 헤더는 원래 호스트(http.client가 self.host로 채운다)."""

    def __init__(self, host, port, ip, timeout):
        super().__init__(host, port, timeout=timeout)
        self._ip = ip

    def connect(self):
        self.sock = socket.create_connection((self._ip, self.port), CONNECT_S)
        self.sock.settimeout(self.timeout)


class _TLSConn(_Conn):
    def connect(self):
        super().connect()
        ctx = ssl.create_default_context()  # 인증서·호스트 이름 검증 유지
        self.sock = ctx.wrap_socket(self.sock, server_hostname=self.host)


def _status_error(status: int) -> NetError:
    if 300 <= status < 400:
        code = "blocked_address"  # 리다이렉트는 따라가지 않는다
    elif status in (401, 403):
        code = "auth_failed"
    elif status == 404:
        code = "model_not_found"
    elif status < 500:
        code = "http_4xx"
    else:
        code = "http_5xx"
    e = NetError(code)
    e.status = status  # 400이면 워커가 response_format 없이 다시 묻는다(§11.2)
    return e


def _request(
    method: str, base_url: str, path: str, *, body=None, api_key="", org=False, timeout_s=30
) -> dict:
    parts, ip = check(base_url, org=org)
    cls = _TLSConn if parts.scheme == "https" else _Conn
    port = parts.port or (443 if parts.scheme == "https" else 80)
    conn = cls(parts.hostname, port, ip, timeout_s)
    headers = {"Accept": "application/json"}
    if api_key:
        headers["Authorization"] = f"Bearer {api_key}"
    data = None
    if body is not None:
        data = json.dumps(body).encode()
        headers["Content-Type"] = "application/json"
    deadline = time.monotonic() + timeout_s
    try:
        conn.request(method, parts.path.rstrip("/") + path, body=data, headers=headers)
        resp = conn.getresponse()
        if resp.status != 200:
            raise _status_error(resp.status)
        buf = bytearray()
        while True:
            if time.monotonic() > deadline:
                raise NetError("timeout")
            chunk = resp.read(65536)
            if not chunk:
                break
            buf += chunk
            if len(buf) > MAX_BODY:
                raise NetError("too_large")
    except NetError:
        raise
    except TimeoutError:
        raise NetError("timeout") from None
    except (OSError, http.client.HTTPException):
        raise NetError("connect_failed") from None
    finally:
        conn.close()
    try:
        out = json.loads(buf)
    except ValueError:
        raise NetError("bad_output") from None
    if not isinstance(out, dict):
        raise NetError("bad_output")
    return out


def list_models(
    base_url: str, *, api_key: str = "", org: bool = False, timeout_s: int = 5
) -> list[str]:
    """GET {base_url}/models → 모델 id 목록. [연결 시험]·[모델 불러오기]가 쓴다. org=True면 허용 호스트를 본다."""
    out = _request("GET", base_url, "/models", api_key=api_key, org=org, timeout_s=timeout_s)
    data = out.get("data")
    if not isinstance(data, list):
        raise NetError("bad_output")
    return [str(m["id"])[:200] for m in data if isinstance(m, dict) and m.get("id")][:500]


def chat(
    base_url: str, payload: dict, *, api_key: str = "", org: bool = False, timeout_s: int = 30
) -> dict:
    """POST {base_url}/chat/completions → 응답 JSON. 워커가 쓴다."""
    return _request(
        "POST",
        base_url,
        "/chat/completions",
        body=payload,
        api_key=api_key,
        org=org,
        timeout_s=timeout_s,
    )
