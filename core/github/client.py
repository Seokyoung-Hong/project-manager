"""GitHub HTTP 호출. stdlib urllib만 쓴다(httpx·requests를 넣지 않는다).

토큰은 두 가지이고 쓰임이 갈린다.
- **설치 토큰**: 서버가 앱 개인키로 받아 오는 1시간짜리. **읽기에만** 쓴다.
- **사용자 토큰**: 그 사람의 권한 확인과 모든 쓰기에 쓴다(쓰기는 V2-08).
"""

import base64
import json
import time
import urllib.error
import urllib.parse
import urllib.request

from cryptography.hazmat.primitives import hashes, serialization
from cryptography.hazmat.primitives.asymmetric import padding
from django.conf import settings

API = "https://api.github.com"
TIMEOUT = 15


class GitHubError(Exception):
    """GitHub가 거부했다. status와 사람이 읽을 메시지를 들고 있다."""

    def __init__(self, status: int, message: str):
        self.status, self.message = status, message
        super().__init__(f"GitHub {status}: {message}")


def request(method: str, path: str, token: str, *, body=None, accept="application/vnd.github+json"):
    url = path if path.startswith("http") else API + path
    data = json.dumps(body).encode() if body is not None else None
    req = urllib.request.Request(url, data=data, method=method)
    req.add_header("Authorization", f"Bearer {token}")
    req.add_header("Accept", accept)
    req.add_header("X-GitHub-Api-Version", "2022-11-28")
    req.add_header("User-Agent", "udally")
    if data is not None:
        req.add_header("Content-Type", "application/json")
    try:
        with urllib.request.urlopen(req, timeout=TIMEOUT) as r:  # noqa: S310 — 고정 호스트
            raw = r.read()
            return json.loads(raw) if raw else None
    except urllib.error.HTTPError as e:
        try:
            msg = json.loads(e.read()).get("message", "")
        except Exception:  # noqa: BLE001 — 본문이 JSON이 아닐 수 있다
            msg = ""
        raise GitHubError(e.code, msg or e.reason) from None
    except urllib.error.URLError as e:
        raise GitHubError(0, str(e.reason)) from None


PER_PAGE = 100


def paginate(path: str, token: str, *, key=None, per_page: int = PER_PAGE):
    """목록 API를 끝까지 읽는다. `?`가 이미 있으면 뒤에 붙인다.

    key를 주면 {"repositories": [...]} 같은 감싼 응답에서 그 키를 꺼낸다.
    """
    sep = "&" if "?" in path else "?"
    page = 1
    while True:
        data = request("GET", f"{path}{sep}per_page={per_page}&page={page}", token)
        items = (data or {}).get(key, []) if key else (data or [])
        yield from items
        if len(items) < per_page:
            return
        page += 1


def _b64(raw: bytes) -> bytes:
    return base64.urlsafe_b64encode(raw).rstrip(b"=")


def app_jwt() -> str:
    """앱 개인키로 서명한 10분짜리 JWT. PyJWT 없이 직접 만든다."""
    key = serialization.load_pem_private_key(
        settings.GITHUB_APP_PRIVATE_KEY.encode(), password=None
    )
    now = int(time.time())
    header = _b64(json.dumps({"alg": "RS256", "typ": "JWT"}).encode())
    payload = _b64(
        json.dumps({"iat": now - 60, "exp": now + 540, "iss": settings.GITHUB_APP_ID}).encode()
    )
    signing_input = header + b"." + payload
    sig = key.sign(signing_input, padding.PKCS1v15(), hashes.SHA256())
    return (signing_input + b"." + _b64(sig)).decode()


# ponytail: 프로세스별 캐시. 워커가 많아지면 DB나 캐시 백엔드로 옮긴다.
_install_cache: dict[int, tuple[str, float]] = {}


def installation_token(installation_id: int) -> str:
    """1시간짜리 설치 토큰. 5분 여유를 두고 캐시한다. 읽기에만 쓴다."""
    hit = _install_cache.get(installation_id)
    if hit and hit[1] > time.time():
        return hit[0]
    data = request("POST", f"/app/installations/{installation_id}/access_tokens", app_jwt())
    token = data["token"]
    _install_cache[installation_id] = (token, time.time() + 3300)
    return token


def exchange_code(code: str) -> dict:
    """OAuth 코드를 사용자 토큰으로 바꾼다."""
    body = urllib.parse.urlencode(
        {
            "client_id": settings.GITHUB_CLIENT_ID,
            "client_secret": settings.GITHUB_CLIENT_SECRET,
            "code": code,
        }
    ).encode()
    return _oauth_post(body)


def refresh_user_token(refresh_token: str) -> dict:
    body = urllib.parse.urlencode(
        {
            "client_id": settings.GITHUB_CLIENT_ID,
            "client_secret": settings.GITHUB_CLIENT_SECRET,
            "grant_type": "refresh_token",
            "refresh_token": refresh_token,
        }
    ).encode()
    return _oauth_post(body)


def _oauth_post(body: bytes) -> dict:
    req = urllib.request.Request(
        "https://github.com/login/oauth/access_token", data=body, method="POST"
    )
    req.add_header("Accept", "application/json")
    req.add_header("User-Agent", "udally")
    try:
        with urllib.request.urlopen(req, timeout=TIMEOUT) as r:  # noqa: S310 — 고정 호스트
            data = json.loads(r.read())
    except urllib.error.URLError as e:
        raise GitHubError(0, str(e)) from None
    if "error" in data:
        raise GitHubError(400, data.get("error_description") or data["error"])
    return data
