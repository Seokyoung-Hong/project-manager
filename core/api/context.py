from ninja.errors import HttpError

from orgs.models import Organization
from orgs.services import is_member
from tasks.services import get_visible_task


def ctx(request) -> dict:
    """services 함수에 넘길 actor/source/token."""
    token = getattr(request, "api_token", None)
    header_ai = request.headers.get("X-Source", "").lower() in ("mcp", "ai")
    if token is None:
        # 세션 요청도 WebMCP(브라우저 안 AI)가 보낼 수 있다. webmcp.js가 X-Source: ai를 붙인다.
        # 헤더로는 AI로 올릴 수만 있으므로 사람의 요청이 AI로 내려갈 일은 없다.
        source = "mcp" if header_ai else "web"
    elif token.for_ai or header_ai:
        # AI 여부는 발급 때 정한 토큰 표시로 판단한다. 헤더는 호출자가 붙이므로 사람용 토큰을
        # AI로 올릴 수만 있고, AI용 토큰을 사람으로 내릴 수는 없다.
        # 내부 코드는 "mcp" 하나로 둔다(화면 표시는 "AI"). 스킬은 "ai"를 보낸다.
        source = "mcp"
    else:
        source = "api"
    return {"actor": request.auth, "source": source, "token": token}


def idem_key(request) -> str | None:
    key = request.headers.get("Idempotency-Key")
    return key[:100] if key else None


def task_or_404(request, task_id: int):
    task = get_visible_task(request.auth, task_id)
    if task is None:
        raise HttpError(404, "태스크를 찾을 수 없습니다.")
    return task


def org_or_404(request, org_id: int):
    org = Organization.objects.filter(pk=org_id).first()
    if org is None or not is_member(request.auth, org):
        raise HttpError(404, "조직을 찾을 수 없습니다.")
    return org


def clamp_page(limit: int, offset: int) -> tuple[int, int]:
    return max(1, min(limit, 200)), max(0, offset)
