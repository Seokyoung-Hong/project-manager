"""개인 AI를 PC 없이 OAuth 로그인만으로 연결한다: OpenRouter(PKCE로 사용자 키 발급)·Hugging Face(inference-api).

- state는 세션 1회용(꺼내면 지운다), PKCE는 S256. 세션에 시작한 사람의 id도 적어 콜백을 그 사람만 끝낸다.
- 공급자 주소는 고정 상수지만 호출은 net 관문(_request)을 지난다.
- 키·토큰은 AiSource.api_key에 "enc:"+Fernet로만 둔다. HF는 갱신용 토큰·만료 시각까지 JSON 한 덩어리로
  암호화한다(마이그레이션 없이). 실행 쪽은 source_key()로만 꺼낸다 — 만료가 가까우면 여기서 갱신한다.
"""

import json
import secrets
import time
from urllib.parse import urlencode

from django.conf import settings
from django.db import transaction

from accounts.models import pkce_challenge
from github.crypto import decrypt, encrypt

from . import net

ENC = "enc:"
OPENROUTER_URL = "https://openrouter.ai/api/v1"
HF_URL = "https://router.huggingface.co/v1"
HF_HUB = "https://huggingface.co/oauth"
_HF_MARK = '{"hf":'  # api_key 평문이 이걸로 시작하면 HF OAuth 덩어리
_SKEW = 120  # 만료 2분 전이면 미리 갱신

# 이름·기본 모델은 사용자가 행 [수정]에서 바꿀 수 있다.
PROVIDERS = {
    "openrouter": {"name": "OpenRouter", "base_url": OPENROUTER_URL, "model": "openrouter/auto"},
    "hf": {"name": "Hugging Face", "base_url": HF_URL, "model": "openai/gpt-oss-20b"},
}

# 행을 지워도 공급자 쪽 키·권한은 남는다. OpenRouter는 사용자 키로 자기 키를 지우는 API가 없고(관리 키 필요),
# HF 권한 회수 API도 문서에 없어 사용자가 직접 지우게 안내한다.
REVOKE_NOTE = {
    OPENROUTER_URL: "OpenRouter에서 발급된 키는 유달리에서 삭제되지 않습니다. 더 이상 사용하지 않으면 OpenRouter 설정 > API Keys(openrouter.ai/settings/keys)에서 키를 삭제해 주세요.",  # COPY:assist_oauth_revoke_openrouter
    HF_URL: "Hugging Face에서 유달리에 준 권한은 유달리에서 회수되지 않습니다. 더 이상 사용하지 않으면 Hugging Face 설정 > Connected Apps(huggingface.co/settings/connected-applications)에서 권한을 회수해 주세요.",  # COPY:assist_oauth_revoke_hf
}


class OAuthError(Exception):
    """콜백 실패. code: state | denied | exchange | limit | crypto."""

    def __init__(self, code: str):
        self.code = code
        super().__init__(code)


def available() -> list[str]:
    """버튼을 그릴 공급자. OpenRouter PKCE는 앱 등록이 없어 늘 켜고, HF는 client id가 있어야 한다."""
    out = ["openrouter"]
    if settings.HF_OAUTH_CLIENT_ID:
        out.append("hf")
    return out


def callback_url(provider: str) -> str:
    return f"{settings.SITE_URL}/settings/ai/oauth/{provider}/callback"


def _skey(provider: str) -> str:
    return f"ai_oauth_{provider}"


def start(request, provider: str) -> str:
    """세션에 state·verifier를 새로 적고 공급자 인가 주소를 돌려준다."""
    state, verifier = secrets.token_urlsafe(24), secrets.token_urlsafe(48)
    request.session[_skey(provider)] = {
        "state": state,
        "verifier": verifier,
        "uid": request.user.pk,
    }
    pkce = {"code_challenge": pkce_challenge(verifier), "code_challenge_method": "S256"}
    if provider == "openrouter":
        q = {"callback_url": callback_url(provider), "state": state, **pkce}
        return "https://openrouter.ai/auth?" + urlencode(q)
    q = {
        "client_id": settings.HF_OAUTH_CLIENT_ID,
        "redirect_uri": callback_url(provider),
        "scope": "openid inference-api",
        "response_type": "code",
        "state": state,
        **pkce,
    }
    return f"{HF_HUB}/authorize?" + urlencode(q)


def _hf_basic():
    sec = settings.HF_OAUTH_CLIENT_SECRET
    return (settings.HF_OAUTH_CLIENT_ID, sec) if sec else None  # 비밀 없는 공개 앱이면 PKCE만


def _hf_token(form: dict) -> str:
    """HF 토큰 엔드포인트 → 저장할 JSON 덩어리. 실패는 net.NetError(auth_failed 등)."""
    try:
        out = net._request(
            "POST",
            HF_HUB,
            "/token",
            form={**form, "client_id": settings.HF_OAUTH_CLIENT_ID},
            basic=_hf_basic(),
            timeout_s=10,
        )
    except net.NetError as e:
        raise net.NetError("auth_failed" if e.code == "http_4xx" else e.code) from None
    access = out.get("access_token")
    if not isinstance(access, str) or not access:
        raise net.NetError("bad_output")
    exp = int(time.time()) + int(out.get("expires_in") or 28800)
    return json.dumps({"hf": 1, "a": access, "r": out.get("refresh_token") or "", "exp": exp})


def _exchange(provider: str, code: str, verifier: str) -> str:
    """인가 코드 → api_key에 넣을 평문(OpenRouter 키, HF 덩어리)."""
    if provider == "openrouter":
        out = net._request(
            "POST",
            OPENROUTER_URL,
            "/auth/keys",
            body={"code": code, "code_verifier": verifier, "code_challenge_method": "S256"},
            timeout_s=10,
        )
        key = out.get("key")
        if not isinstance(key, str) or not key:
            raise net.NetError("bad_output")
        return key
    return _hf_token(
        {
            "grant_type": "authorization_code",
            "code": code,
            "redirect_uri": callback_url(provider),
            "code_verifier": verifier,
        }
    )


def finish(request, provider: str):
    """콜백: state·사람 확인 → 코드 교환 → 개인 AI 행 만들기(같은 주소 행이 있으면 그 행의 키를 바꾼다)."""
    from django.db.models import Max

    from .models import AiSource

    saved = request.session.pop(_skey(provider), None)  # 맞든 틀리든 이 시도는 여기서 끝난다
    got = request.GET.get("state", "")
    if (
        not isinstance(saved, dict)
        or saved.get("uid") != request.user.pk
        or not secrets.compare_digest(got.encode(), str(saved.get("state", "")).encode())
    ):
        raise OAuthError("state")
    code = request.GET.get("code", "")
    if request.GET.get("error") or not code:
        raise OAuthError("denied")
    user, p = request.user, PROVIDERS[provider]
    src = AiSource.objects.filter(user=user, kind="personal", base_url=p["base_url"]).first()
    if src is None and (
        AiSource.objects.filter(user=user, kind="personal").count() >= AiSource.MAX_PERSONAL
    ):
        raise OAuthError("limit")  # 교환 전에 막아 쓰지 않을 키를 만들지 않는다
    try:
        secret = _exchange(provider, code, saved["verifier"])
    except net.NetError:
        raise OAuthError("exchange") from None
    try:
        enc = ENC + encrypt(secret)
    except ValueError:
        raise OAuthError("crypto") from None
    if src is None:
        last = AiSource.objects.filter(user=user).aggregate(m=Max("position"))["m"]
        src = AiSource(
            user=user,
            kind="personal",
            name=p["name"],
            base_url=p["base_url"],
            model=p["model"],
            position=0 if last is None else last + 1,
        )
    src.route, src.server, src.api_key, src.last_error = "direct", None, enc, ""
    src.save()
    return src


def is_hf_blob(api_key: str) -> bool:
    raw = decrypt(api_key[len(ENC) :]) if (api_key or "").startswith(ENC) else ""
    return raw.startswith(_HF_MARK)


def source_key(src) -> str:
    """개인 AI 키 평문. HF OAuth면 접근 토큰(만료가 가까우면 갱신해 저장). 갱신 실패는 NetError(auth_failed)."""
    raw = decrypt(src.api_key[len(ENC) :]) if (src.api_key or "").startswith(ENC) else ""
    if not raw.startswith(_HF_MARK):
        return raw
    d = json.loads(raw)
    if d["exp"] - _SKEW > time.time():
        return d["a"]
    return _refresh(src.pk)


def _refresh(source_id: int) -> str:
    """행을 잠그고 갱신한다 — 두 워커가 같은 갱신 토큰을 동시에 쓰지 않게(회전형이면 하나가 무효가 된다)."""
    from .models import AiSource

    with transaction.atomic():
        row = AiSource.objects.select_for_update().get(pk=source_id)
        raw = decrypt(row.api_key[len(ENC) :]) if row.api_key.startswith(ENC) else ""
        if not raw.startswith(_HF_MARK):
            raise net.NetError("auth_failed")
        d = json.loads(raw)
        if d["exp"] - _SKEW > time.time():
            return d["a"]  # 먼저 잠근 쪽이 이미 갱신했다
        if not d.get("r"):
            raise net.NetError("auth_failed")  # 갱신 토큰이 없으면 다시 연결해야 한다
        blob = _hf_token({"grant_type": "refresh_token", "refresh_token": d["r"]})
        nd = json.loads(blob)
        if not nd["r"]:
            nd["r"] = d["r"]  # 회전하지 않는 공급자면 옛 갱신 토큰을 계속 쓴다
        row.api_key = ENC + encrypt(json.dumps(nd))
        row.save(update_fields=["api_key"])
        return nd["a"]
