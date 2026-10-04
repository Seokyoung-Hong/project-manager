"""MCP 커넥터를 위한 OAuth 2.1 인가 서버.

왜 필요한가: 개인 비밀 URL(/u/<TOKEN>/mcp)은 사람이 토큰을 손으로 복사해 붙여야 하고,
그 주소가 곧 비밀번호라 브라우저 기록과 프록시 로그에 남는다. Claude 앱처럼 '연결' 한 번으로
끝나기를 기대하는 클라이언트에는 이쪽이 맞다.

MCP 클라이언트는 사전 등록이 불가능하므로 동적 등록(RFC 7591)을 열어 둔다. 등록된
클라이언트는 비밀이 없는 공개 클라이언트라 코드를 지키는 것은 PKCE(S256)뿐이다.
교환 결과는 평범한 ApiToken이다 — mcp_server는 지금과 똑같이 Bearer 토큰만 검사한다.
"""

import json
from urllib.parse import urlencode, urlparse

from django.conf import settings
from django.contrib.auth.decorators import login_required
from django.http import HttpResponse, JsonResponse
from django.shortcuts import render
from django.views.decorators.csrf import csrf_exempt
from django.views.decorators.http import require_POST

from accounts.models import ApiToken, OAuthClient, OAuthCode

SCOPES = ["read", "write"]


def metadata(request):
    """RFC 8414. 클라이언트는 이 문서만 보고 나머지 주소를 찾는다."""
    base = settings.SITE_URL
    return JsonResponse(
        {
            "issuer": base,
            "authorization_endpoint": f"{base}/oauth/authorize",
            "token_endpoint": f"{base}/oauth/token",
            "registration_endpoint": f"{base}/oauth/register",
            "response_types_supported": ["code"],
            "grant_types_supported": ["authorization_code"],
            "code_challenge_methods_supported": ["S256"],
            # 공개 클라이언트뿐이다. 비밀을 받지 않으니 인증 방식도 none 하나다.
            "token_endpoint_auth_methods_supported": ["none"],
            "scopes_supported": SCOPES,
        }
    )


def _error(code: str, desc: str, status: int = 400):
    r = JsonResponse({"error": code, "error_description": desc}, status=status)
    r["Cache-Control"] = "no-store"
    return r


def _redirect_ok(uri: str) -> bool:
    """평문 http로 코드를 돌려보내지 않는다(루프백은 네이티브 앱이라 예외).
    https와 앱 고유 스킴(vscode: 같은 것)은 받는다."""
    p = urlparse(uri)
    if not p.scheme or p.fragment:
        return False
    if p.scheme == "http":
        return p.hostname in ("localhost", "127.0.0.1", "::1")
    # 브라우저가 코드를 실행하거나 파일을 여는 스킴은 받지 않는다. 앱 고유 스킴만 남는다.
    return p.scheme not in ("javascript", "data", "vbscript", "file", "blob", "about")


@csrf_exempt
@require_POST
def register(request):
    """RFC 7591 동적 등록. 누구나 부를 수 있다 — 클라이언트는 아직 사람이 아니고,
    여기서 만들어지는 것은 권한이 없는 빈 껍데기다. 권한은 authorize에서 사람이 준다."""
    try:
        body = json.loads(request.body or b"{}")
    except ValueError:
        return _error("invalid_client_metadata", "JSON 본문이 필요합니다.")
    uris = body.get("redirect_uris")
    if not isinstance(uris, list) or not 1 <= len(uris) <= 5:
        return _error("invalid_redirect_uri", "redirect_uris를 1~5개 보내세요.")
    if not all(isinstance(u, str) and len(u) <= 500 and _redirect_ok(u) for u in uris):
        return _error("invalid_redirect_uri", "https 또는 루프백 주소만 받습니다.")
    client = OAuthClient.register(body.get("client_name", ""), uris)
    r = JsonResponse(
        {
            "client_id": client.client_id,
            "client_id_issued_at": int(client.created_at.timestamp()),
            "client_name": client.name,
            "redirect_uris": client.redirect_uris,
            "grant_types": ["authorization_code"],
            "response_types": ["code"],
            "token_endpoint_auth_method": "none",
        },
        status=201,
    )
    r["Cache-Control"] = "no-store"
    return r


# ponytail: 등록은 인증 없이 열려 있다(MCP가 그걸 전제한다). 남용이 보이면 앞단 프록시에서
# /oauth/register에 속도 제한을 건다 — 앱 안에 카운터를 두는 것보다 그쪽이 싸다.


def _back(redirect_uri: str, state: str, **params):
    if state:
        params["state"] = state
    sep = "&" if urlparse(redirect_uri).query else "?"
    # HttpResponseRedirect는 http·https·ftp만 허용해 등록을 받아 준 앱 스킴(vscode: 등)에서
    # DisallowedRedirect를 낸다. 등록 단계(_redirect_ok)가 이미 걸렀으므로 그대로 보낸다.
    return HttpResponse(status=302, headers={"Location": f"{redirect_uri}{sep}{urlencode(params)}"})


@login_required
def authorize(request):
    p = request.POST if request.method == "POST" else request.GET
    client = OAuthClient.objects.filter(client_id=p.get("client_id", "")).first()
    redirect_uri = p.get("redirect_uri", "")
    # redirect_uri가 등록된 값과 같다고 확인하기 전에는 그리로 되돌려 보내지 않는다.
    # 확인 없이 되돌려 보내면 이 화면이 그대로 오픈 리다이렉터가 된다.
    if client is None or redirect_uri not in client.redirect_uris:
        return render(
            request,
            "oauth/error.html",
            {"message": "클라이언트 또는 redirect_uri가 등록된 값과 다릅니다."},
            status=400,
        )
    state = p.get("state", "")
    challenge = p.get("code_challenge", "")
    if p.get("response_type") != "code":
        return _back(redirect_uri, state, error="unsupported_response_type")
    if p.get("code_challenge_method") != "S256" or not challenge:
        return _back(
            redirect_uri,
            state,
            error="invalid_request",
            error_description="PKCE(S256) code_challenge가 필요합니다.",
        )

    if request.method == "POST":
        if request.POST.get("decision") != "allow":
            return _back(redirect_uri, state, error="access_denied")
        # 범위는 클라이언트가 요구하는 대로가 아니라 사람이 화면에서 고른 대로 준다.
        scope = "write" if request.POST.get("scope") == "write" else "read"
        _, raw = OAuthCode.issue(
            client=client,
            user=request.user,
            redirect_uri=redirect_uri,
            code_challenge=challenge[:128],
            scope=scope,
        )
        return _back(redirect_uri, state, code=raw)

    return render(
        request,
        "oauth/authorize.html",
        {
            "client": client,
            "redirect_host": urlparse(redirect_uri).netloc or redirect_uri,
            "params": {
                "client_id": client.client_id,
                "redirect_uri": redirect_uri,
                "state": state,
                "code_challenge": challenge,
                "code_challenge_method": "S256",
                "response_type": "code",
            },
        },
    )


@csrf_exempt
@require_POST
def token(request):
    """코드를 ApiToken으로 바꾼다. 비밀이 없으므로 신원 증명은 code_verifier뿐이다."""
    if request.POST.get("grant_type") != "authorization_code":
        return _error("unsupported_grant_type", "authorization_code만 지원합니다.")
    code = OAuthCode.claim(
        request.POST.get("code", ""),
        request.POST.get("client_id", ""),
        request.POST.get("redirect_uri", ""),
        request.POST.get("code_verifier", ""),
    )
    if code is None:
        return _error("invalid_grant", "코드가 만료됐거나 이미 쓰였거나 맞지 않습니다.")
    _, raw = ApiToken.issue(code.user, code.client.name or "MCP 커넥터", scope=code.scope)
    r = JsonResponse({"access_token": raw, "token_type": "Bearer", "scope": code.scope})
    r["Cache-Control"] = "no-store"
    return r
