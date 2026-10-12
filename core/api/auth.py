from ninja.errors import HttpError
from ninja.security import HttpBearer, SessionAuth

from accounts.models import ApiToken
from accounts.services import consent_active, paused_message
from orgs.member_info import MemberInfoRequired, api_params, blocked_org, request_org_id

WRITE_EXEMPT_PREFIX = "/api/integrations/"


def member_info_gate(request, user):
    """요청이 가리키는 조직의 필수 구성원 정보가 비었으면 403 profile_required(api/api.py).

    모든 API 인증이 지나는 자리라 엔드포인트마다 붙이지 않는다. 봇·웹훅 경로(/api/integrations/)는
    사람의 조직 사용이 아니라 빼고, 조직을 정할 수 없는 요청(/api/me 등)은 막지 않는다.
    """
    if user is None or request.path.startswith(WRITE_EXEMPT_PREFIX):
        return user
    match = request.resolver_match
    org = blocked_org(user, request_org_id(match.kwargs if match else {}, api_params(request)))
    if org is not None:
        raise MemberInfoRequired(org)
    return user


class BrowserSessionAuth(SessionAuth):
    """세션 쿠키가 실제로 있을 때만 동작한다.

    django-ninja의 SessionAuth는 쿠키를 읽기 전에 CSRF를 검사하고 실패하면 403을 던진다.
    인증 목록의 첫 번째라서, 쿠키가 없는 Bearer 요청(MCP·Discord)까지 403이 되어 버린다.
    쿠키가 없으면 곧바로 넘겨 TokenAuth가 처리하게 한다. 쿠키가 있으면 CSRF 검사는 그대로다.
    """

    def __call__(self, request):
        if self.param_name not in request.COOKIES:
            return None
        return member_info_gate(request, super().__call__(request))


class TokenAuth(HttpBearer):
    def authenticate(self, request, token):
        t = ApiToken.authenticate(token)
        if t is None:
            return None
        if (
            # write가 아닌 모든 범위(read·bot)를 막는다. bot 범위는 아래 BotTokenAuth가
            # 지키는 /api/integrations/discord/ 안에서만 쓴다.
            t.scope != "write"
            and request.method not in ("GET", "HEAD", "OPTIONS")
            and not request.path.startswith(WRITE_EXEMPT_PREFIX)
        ):
            raise HttpError(403, "읽기 전용 토큰입니다.")
        # AI용 토큰(MCP OAuth로 받은 것 포함)은 국외 이전 동의가 있어야 쓴다. 유예 뒤에만 걸린다.
        if t.for_ai and not consent_active(t.user, "ai"):
            raise HttpError(403, paused_message("ai"))
        request.api_token = t
        return member_info_gate(request, t.user)


class BotTokenAuth(TokenAuth):
    """Discord 봇 명령 경로 전용 인증.

    `/api/integrations/`는 WRITE_EXEMPT_PREFIX라서 읽기 토큰으로도 POST가 통하고,
    API 기본 인증에는 세션 쿠키(BrowserSessionAuth)가 들어 있다. 라우터의 auth를
    이것 하나로 바꿔 두면 세션·읽기·쓰기 토큰이 이 경로에 아예 들어오지 못한다.
    엔드포인트마다 가드를 손으로 붙이지 않아도 되게 구조로 막는다.
    """

    def authenticate(self, request, token):
        user = super().authenticate(request, token)
        if user is None:
            return None
        if request.api_token.scope != "bot":
            raise HttpError(403, "Discord 봇 토큰이 필요합니다.")
        return user
