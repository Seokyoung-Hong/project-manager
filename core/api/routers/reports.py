from datetime import date

from ninja import Router
from ninja.errors import HttpError

from common.dates import last_week_start
from reports.services import weekly

from ..context import org_or_404

router = Router(tags=["reports"])


@router.get("/weekly", response=dict)
def weekly_ep(request, org: int, week_start: date | None = None):
    o = org_or_404(request, org)
    ws = week_start or last_week_start()
    if ws.weekday() != 0:
        raise HttpError(400, "week_start는 월요일이어야 합니다.")
    # 봇 토큰은 조직 채널에 게시하므로 비공개 프로젝트를 뺀다. 사람(스킬·API)은 자기가 볼 수 있는 만큼.
    token = getattr(request, "api_token", None)
    viewer = None if token is not None and token.scope == "bot" else request.auth
    return weekly(o, ws, viewer=viewer)
