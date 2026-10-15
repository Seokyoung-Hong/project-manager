from ninja.errors import HttpError
from ninja.security import HttpBearer, SessionAuth

from accounts.models import ApiToken
from accounts.services import RealNameRequired, consent_active, paused_message
from orgs.member_info import MemberInfoRequired, api_params, blocked_org, request_org_id

WRITE_EXEMPT_PREFIX = "/api/integrations/"
STT_PREFIX = "/api/integrations/stt/"
# 계정 실명이 비어도 부를 수 있는 경로. 스킬·MCP가 안내를 띄우려면 내 정보는 읽어야 한다.
REAL_NAME_OPEN = {"/api/me"}


def member_info_gate(request, user):
    """계정 실명이 비었으면 403 real_name_required, 요청이 가리키는 조직의 필수 구성원 정보가 비었으면
    403 profile_required(api/api.py).

    모든 API 인증이 지나는 자리라 엔드포인트마다 붙이지 않는다. 봇·웹훅 경로(/api/integrations/)는
    사람의 조직 사용이 아니라 빼고, 조직을 정할 수 없는 요청(/api/me 등)은 구성원 정보로 막지 않는다.
    """
    if user is None or request.path.startswith(WRITE_EXEMPT_PREFIX):
        return user
    if not user.real_name and request.path not in REAL_NAME_OPEN:
        raise RealNameRequired()
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
            raise HttpError(401, ApiToken.rejection(token))
        # 전사 서버(PC) 토큰은 자기 경로 밖에서 GET까지 막는다. 아래 쓰기 검사만으로는 읽기가 열린다.
        if t.scope == "stt" and not request.path.startswith(STT_PREFIX):
            raise HttpError(403, "전사 서버 토큰은 전사 서버 연결에만 쓸 수 있습니다.")
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
        _discord_actor_gate(request)
        return user


DISCORD_PREFIX = "/api/integrations/discord/"


def _discord_actor_gate(request):
    """봇이 사람(discord_user_id) 대신 일할 때도 그 사람이 막힌 조직이면 404 대신 입력 안내를 준다.

    대상 조직은 경로의 task·project·team·request id, 본문의 project·team 또는 guild_id(연결 서버)로 정한다.
    회의 진행 중 이벤트(/meetings/{id}/…)는 봇이 대신 보고하는 것이라 막지 않는다.
    """
    from accounts.services import user_by_discord_id
    from orgs.models import Organization

    path = request.path
    if not path.startswith(DISCORD_PREFIX) or path.startswith(DISCORD_PREFIX + "meetings/"):
        return
    params = api_params(request)
    did = params.get("discord_user_id")
    actor = user_by_discord_id(str(did)) if did else None
    if actor is None:
        return
    match = request.resolver_match
    org_id = request_org_id(match.kwargs if match else {}, params)
    if org_id is None and params.get("guild_id"):
        org_id = (
            Organization.objects.filter(discord_guild_id=str(params["guild_id"]))
            .values_list("pk", flat=True)
            .first()
        )
    org = blocked_org(actor, org_id)
    if org is not None:
        raise MemberInfoRequired(org)


class SttTokenAuth(TokenAuth):
    """내 PC 전사 서버 경로 전용(IMPL-PLAN-11-local-stt-link §6.1). scope stt만 통과한다.

    토큰의 서버를 `request.stt_server`에 둔다. 서버를 끊으면 토큰도 폐기되므로 서버가 없는 토큰은 없다.
    """

    def authenticate(self, request, token):
        from notes.models import SttServer

        user = super().authenticate(request, token)
        if user is None:
            return None
        if request.api_token.scope != "stt":
            raise HttpError(403, "전사 서버 토큰이 필요합니다.")
        request.stt_server = SttServer.objects.filter(token=request.api_token).first()
        if request.stt_server is None:
            return None
        return user
