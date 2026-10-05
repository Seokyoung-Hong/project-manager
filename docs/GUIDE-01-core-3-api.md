# 구현 지시서 01-3: core — HTTP API (Step 5)


> **이 문서는 2026-09-10에 끝난 최초 구축의 기록이다.** 지금 할 일은 [GUIDE-V2-00-overview.md](GUIDE-V2-00-overview.md)부터 시작하는 묶음이다. 이 문서에 나오는 `Team`·`teams`·"팀"은 2026-09-11 개명 전 용어로 **조직**을 뜻한다. 대조표는 [GUIDE-V2-01](GUIDE-V2-01-org-teams.md) §1에 있다.

이전: [01-2](GUIDE-01-core-2-services.md). Django Ninja로 만든다. 이 API는 MCP 서버·Discord 서비스와의 **유일한 계약**이다. 경로, 필드 이름, 응답 모양을 바꾸지 않는다.

개정 2026-09-10: 상태 7개, 중요도 정수, 프로젝트 `owners`, `stop_reason`·`notes`, `/block`·`/comments` 삭제, `/extend` 추가, 오늘 목록 제외·복원·설정.

개정 2026-09-10 (Discord 봇): 쓰기 게이트 `scope != "write"`, `BotTokenAuth`, 신규 라우터 `routers/discord.py`(봇 명령 5개), `/discord/webhooks` 삭제.

파일 구성:

```
core/api/
  api.py          NinjaAPI 인스턴스, 예외 처리, 라우터 등록
  auth.py         Bearer 토큰 인증
  context.py      요청에서 actor/source/token 꺼내기, 공통 헬퍼
  schemas.py      입력·출력 스키마
  serialize.py    모델 → dict
  routers/
    __init__.py
    me.py teams.py projects.py tasks.py today.py reports.py integrations.py
    discord.py    봇 명령 5개 (BotTokenAuth)
```

---

## 5.1 `core/api/auth.py`

```python
from ninja.errors import HttpError
from ninja.security import HttpBearer, SessionAuth

from accounts.models import ApiToken

WRITE_EXEMPT_PREFIX = "/api/integrations/"


class BrowserSessionAuth(SessionAuth):
    """세션 쿠키가 실제로 있을 때만 동작한다.

    django-ninja의 SessionAuth는 쿠키를 읽기 전에 CSRF를 검사하고 실패하면 403을 던진다.
    인증 목록의 첫 번째라서, 쿠키가 없는 Bearer 요청(MCP·Discord)까지 403이 되어 버린다.
    쿠키가 없으면 곧바로 넘겨 TokenAuth가 처리하게 한다. 쿠키가 있으면 CSRF 검사는 그대로다.
    """

    def __call__(self, request):
        if self.param_name not in request.COOKIES:
            return None
        return super().__call__(request)


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
        request.api_token = t
        return t.user


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
```

쓰기 게이트가 `t.scope == "read"`에서 **`t.scope != "write"`**로 바뀐 것에 주의한다. 범위가 셋(`read`·`write`·`bot`)이 되었으므로 화이트리스트로 물어야 한다 — 그러지 않으면 `bot` 토큰이 `POST /api/tasks` 같은 곳까지 통한다.

`/{name}/status`(틱의 상태 보고)는 계속 API 기본 인증을 쓴다. `bot` 범위 토큰도 `WRITE_EXEMPT_PREFIX` 덕에 그 POST는 통한다.

## 5.2 `core/api/context.py`

```python
from ninja.errors import HttpError

from tasks.services import get_visible_task
from teams.models import Team
from teams.services import is_member


def ctx(request) -> dict:
    """services 함수에 넘길 actor/source/token."""
    token = getattr(request, "api_token", None)
    if token is None:
        source = "web"
    elif token.for_ai or request.headers.get("X-Source", "").lower() in ("mcp", "ai"):
        # 2026-09-28: AI 여부는 발급 때 정한 토큰 표시(ApiToken.for_ai)로 본다. 헤더는 올리기만 한다.
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


def team_or_404(request, team_id: int):
    team = Team.objects.filter(pk=team_id).first()
    if team is None or not is_member(request.auth, team):
        raise HttpError(404, "팀을 찾을 수 없습니다.")
    return team


def clamp_page(limit: int, offset: int) -> tuple[int, int]:
    return max(1, min(limit, 200)), max(0, offset)
```

`ctx()`는 **바뀌지 않는다.** `source="dc"`(Discord)는 여기서 나오지 않는다 — Discord 라우터가 자기 `_ctx()`에서 `"dc"`를 직접 박는다(§5.6). `X-Source` 헤더는 클라이언트가 고르는 값이라 경로의 증거가 못 되고, 그 라우터에 들어왔다는 사실 자체가 증거다(`BotTokenAuth`를 통과해야 들어온다). 그래서 `mcp`처럼 헤더로 판정하는 분기를 추가하지 않는다.

## 5.3 `core/api/schemas.py`

```python
from datetime import date, datetime
from typing import Annotated, Literal

from ninja import Schema
from pydantic import Field

Status = Literal["todo", "doing", "paused", "blocked", "review", "done", "cancelled"]
Priority = Annotated[int, Field(ge=1, le=10)]
ProjectStatus = Literal["preparing", "on_hold", "waiting", "active", "paused", "done", "stopped", "eol"]


class UserBrief(Schema):
    id: int
    display_name: str
    discord_user_id: str | None = None


class ProjectBrief(Schema):
    id: int
    name: str
    team_id: int


class TaskBriefOut(Schema):
    id: int
    number: str
    title: str
    project: ProjectBrief
    assignee: UserBrief
    status: Status
    priority: int
    due_date: date | None
    stop_reason: str
    next_action: str
    url: str


class ChecklistItemOut(Schema):
    id: int
    text: str
    is_done: bool
    position: int


class ChecklistItemIn(Schema):
    text: str
    is_done: bool = False


class LinkOut(Schema):
    id: int
    title: str
    url: str
    kind: str


class TaskOut(TaskBriefOut):
    description: str
    done_when: str
    notes: str
    no_due_reason: str
    stopped_at: datetime | None
    completed_at: datetime | None
    version: int
    created_by: UserBrief
    created_at: datetime
    updated_at: datetime
    checklist: list[ChecklistItemOut]
    checklist_done: int
    checklist_total: int
    links: list[LinkOut]


class TaskCreateIn(Schema):
    project_id: int
    title: str
    assignee_id: int | None = None
    description: str = ""
    done_when: str = ""
    next_action: str = ""
    priority: Priority = 5
    due_date: date | None = None
    no_due_reason: str = ""
    checklist: list[ChecklistItemIn] | None = None


class TaskPatchIn(Schema):
    version: int
    title: str | None = None
    description: str | None = None
    done_when: str | None = None
    next_action: str | None = None
    notes: str | None = None
    assignee_id: int | None = None
    project_id: int | None = None
    priority: Priority | None = None
    due_date: date | None = None
    no_due_reason: str | None = None
    stop_reason: str | None = None
    checklist: list[ChecklistItemIn] | None = None


class TransitionIn(Schema):
    status: Status
    reason: str = ""
    version: int


class ExtendIn(Schema):
    due_date: date
    reason: str
    version: int


class ChangeLogOut(Schema):
    id: int
    field: str
    old_value: str
    new_value: str
    note: str
    actor: UserBrief
    source: str
    created_at: datetime


class TaskListOut(Schema):
    items: list[TaskBriefOut]
    total: int
    limit: int
    offset: int


class ProjectStats(Schema):
    total: int
    open: int
    overdue: int
    review: int
    blocked: int
    done: int


class ProjectOut(Schema):
    id: int
    team_id: int
    name: str
    purpose: str
    owners: list[UserBrief]
    status: ProjectStatus
    status_label: str
    is_archived: bool
    version: int
    stats: ProjectStats
    links: list[LinkOut]
    url: str


class ProjectCreateIn(Schema):
    team_id: int
    name: str
    purpose: str = ""
    owner_ids: list[int] = []
    status: ProjectStatus = "preparing"


class ProjectPatchIn(Schema):
    version: int
    name: str | None = None
    purpose: str | None = None
    owner_ids: list[int] | None = None
    status: ProjectStatus | None = None


class TeamBrief(Schema):
    id: int
    name: str
    purpose: str
    role: str


class MeOut(Schema):
    id: int
    username: str
    display_name: str
    discord_user_id: str | None
    auto_pull_days: int
    teams: list[TeamBrief]


class TeamOut(Schema):
    id: int
    name: str
    purpose: str
    role: str
    projects: list[ProjectOut]


class InviteIn(Schema):
    days: int = 7


class InviteOut(Schema):
    id: int
    url: str
    expires_at: datetime
    use_count: int
    revoked_at: datetime | None


class TodayItemOut(TaskBriefOut):
    auto_pulled: bool


class TodayOut(Schema):
    date: date
    items: list[TodayItemOut]
    focus: TaskBriefOut | None
    done_today: list[TaskBriefOut]
    auto_pull_days: int
    counts: dict


class TodayAddIn(Schema):
    task_id: int


class TodayOrderIn(Schema):
    task_ids: list[int]


class TodaySettingsIn(Schema):
    auto_pull_days: int


class StatusIn(Schema):
    ok: bool
    detail: dict = {}


# ---------- Discord 봇 ----------
# discord_user_id는 게이트웨이가 채운 author.id다. 클라이언트가 고르는 값이 아니다.


class DiscordLinkIn(Schema):
    code: str
    discord_user_id: str


class DiscordActorIn(Schema):
    discord_user_id: str


class DiscordExtendIn(Schema):
    discord_user_id: str
    due_date: date
    reason: str = ""


class ErrorOut(Schema):
    detail: dict | str


class ConflictOut(Schema):
    detail: str
    latest: dict
```

## 5.4 `core/api/serialize.py`

```python
from django.conf import settings

from projects.services import project_stats
from tasks.brief import task_brief, user_brief


def link_out(link) -> dict:
    return {"id": link.pk, "title": link.title, "url": link.url, "kind": link.kind}


def changelog_out(log) -> dict:
    return {
        "id": log.pk, "field": log.field, "old_value": log.old_value,
        "new_value": log.new_value, "note": log.note, "actor": user_brief(log.actor),
        "source": log.source, "created_at": log.created_at,
    }


def task_out(t) -> dict:
    items = list(t.checklist.all())
    d = task_brief(t)
    d.update({
        "description": t.description,
        "done_when": t.done_when,
        "notes": t.notes,
        "no_due_reason": t.no_due_reason,
        "stopped_at": t.stopped_at,
        "completed_at": t.completed_at,
        "version": t.version,
        "created_by": user_brief(t.created_by),
        "created_at": t.created_at,
        "updated_at": t.updated_at,
        "checklist": [
            {"id": i.pk, "text": i.text, "is_done": i.is_done, "position": i.position} for i in items
        ],
        "checklist_done": sum(1 for i in items if i.is_done),
        "checklist_total": len(items),
        "links": [link_out(link) for link in t.links.all()],
    })
    return d


def project_out(p) -> dict:
    return {
        "id": p.pk, "team_id": p.team_id, "name": p.name, "purpose": p.purpose,
        "owners": [user_brief(u) for u in p.owners.all()],
        "status": p.status, "status_label": p.status_label,
        "is_archived": p.is_archived, "version": p.version,
        "stats": project_stats(p),
        "links": [link_out(link) for link in p.links.all()],
        "url": f"{settings.SITE_URL}/projects/{p.pk}",
    }


def invite_out(inv) -> dict:
    return {
        "id": inv.pk, "url": f"{settings.SITE_URL}{inv.path}", "expires_at": inv.expires_at,
        "use_count": inv.use_count, "revoked_at": inv.revoked_at,
    }
```

## 5.5 `core/api/api.py` (임시 파일을 이걸로 교체)

```python
from django.contrib.auth.decorators import login_required
from ninja import NinjaAPI
from ninja.throttling import AuthRateThrottle

from common.errors import ConflictError, ServiceError

from .auth import BrowserSessionAuth, TokenAuth
from .routers import discord, integrations, me, projects, reports, tasks, teams, today
from .serialize import project_out, task_out

class UserRateThrottle(AuthRateThrottle):
    """사용자별 처리량 제한.

    기본 AuthRateThrottle은 `str(request.auth)`를 키로 쓴다. User.__str__은
    display_name이고 이건 본인이 바꿀 수 있으며 유일하지도 않다. 남과 같은 이름으로
    바꿔 두면 그 사람 몫까지 같이 갉아먹는다. 바뀌지 않는 사용자 id로 센다.
    """

    def get_cache_key(self, request) -> str:
        pk = getattr(getattr(request, "auth", None), "pk", None)
        if pk is None:
            return super().get_cache_key(request)
        return self.cache_format % {"scope": self.scope, "ident": f"user-{pk}"}


api = NinjaAPI(
    title="Udally API",
    version="1",
    auth=[BrowserSessionAuth(), TokenAuth()],
    throttle=[UserRateThrottle("60/m")],
    docs_decorator=login_required,
    urls_namespace="api",
)


@api.exception_handler(ServiceError)
def _service_error(request, exc):
    return api.create_response(request, {"detail": exc.errors}, status=400)


@api.exception_handler(ConflictError)
def _conflict(request, exc):
    latest = exc.latest
    data = task_out(latest) if hasattr(latest, "assignee") else project_out(latest)
    return api.create_response(request, {"detail": "conflict", "latest": data}, status=409)


api.add_router("/", me.router)
api.add_router("/teams", teams.router)
api.add_router("/projects", projects.router)
api.add_router("/tasks", tasks.router)
api.add_router("/today", today.router)
api.add_router("/reports", reports.router)
# 고정 경로를 먼저. /integrations/{name}/status가 /integrations/discord/...를 삼키지 않게 한다.
api.add_router("/integrations/discord", discord.router)
api.add_router("/integrations", integrations.router)
```

`core/api/routers/__init__.py`는 빈 파일.

**등록 순서가 규칙이다.** `/integrations/{name}/status`가 먼저 등록되면 `/integrations/discord/link`를 `name="discord"` + 남은 경로로 삼켜 404가 된다. 반대로 discord 라우터에는 `/status` 경로가 없으므로, 틱이 부르는 `POST /api/integrations/discord/status`는 discord 라우터를 지나쳐 뒤의 `report_status`로 정상 도달한다.

## 5.6 라우터

### `core/api/routers/me.py`

```python
from ninja import Router

from teams.models import Membership

from ..schemas import MeOut

router = Router(tags=["me"])


@router.get("/me", response=MeOut)
def me(request):
    u = request.auth
    memberships = Membership.objects.filter(user=u).select_related("team").order_by("team__name")
    return {
        "id": u.pk, "username": u.username, "display_name": u.display_name,
        "discord_user_id": u.discord_user_id, "auto_pull_days": u.auto_pull_days,
        "teams": [
            {"id": m.team_id, "name": m.team.name, "purpose": m.team.purpose, "role": m.role}
            for m in memberships
        ],
    }
```

### `core/api/routers/teams.py`

```python
from ninja import Router
from ninja.errors import HttpError

from reports.services import team_status
from tasks.brief import user_brief
from teams.models import Invite, Membership
from teams.services import create_invite, revoke_invite

from ..context import ctx, team_or_404
from ..schemas import ErrorOut, InviteIn, InviteOut, TeamOut, UserBrief
from ..serialize import invite_out, project_out

router = Router(tags=["teams"])


@router.get("/{team_id}", response=TeamOut)
def get_team(request, team_id: int):
    team = team_or_404(request, team_id)
    role = Membership.objects.get(team=team, user=request.auth).role
    projects = team.projects.filter(is_archived=False).prefetch_related("owners")
    return {
        "id": team.pk, "name": team.name, "purpose": team.purpose, "role": role,
        "projects": [project_out(p) for p in projects],
    }


@router.get("/{team_id}/members", response=list[UserBrief])
def members(request, team_id: int):
    team = team_or_404(request, team_id)
    return [user_brief(u) for u in team.members.filter(is_active=True).order_by("display_name")]


@router.get("/{team_id}/status", response=dict)
def status(request, team_id: int):
    return team_status(team_or_404(request, team_id))


@router.post("/{team_id}/invites", response={201: InviteOut, 400: ErrorOut})
def create_invite_ep(request, team_id: int, payload: InviteIn):
    team = team_or_404(request, team_id)
    inv = create_invite(team, ctx(request)["actor"], days=payload.days)
    return 201, invite_out(inv)


@router.delete("/invites/{invite_id}", response={204: None})
def delete_invite(request, invite_id: int):
    inv = Invite.objects.filter(pk=invite_id).select_related("team").first()
    if inv is None:
        raise HttpError(404, "초대를 찾을 수 없습니다.")
    team_or_404(request, inv.team_id)
    revoke_invite(inv, ctx(request)["actor"])
    return 204, None
```

`api.py`에서 `/teams` 라우터에 붙였으므로 실제 경로는 `DELETE /api/teams/invites/{id}`가 된다. 이것이 의도한 경로다.

### `core/api/routers/projects.py`

```python
from ninja import Router
from ninja.errors import HttpError

from accounts.models import User
from projects.models import Project
from projects.services import create_project, update_project
from teams.services import teams_of

from ..context import ctx, team_or_404
from ..schemas import ConflictOut, ErrorOut, ProjectCreateIn, ProjectOut, ProjectPatchIn
from ..serialize import project_out

router = Router(tags=["projects"])


def _visible(request):
    return Project.objects.filter(team__in=teams_of(request.auth)).select_related("team").prefetch_related("owners")


def _project_or_404(request, project_id: int) -> Project:
    p = _visible(request).filter(pk=project_id).first()
    if p is None:
        raise HttpError(404, "프로젝트를 찾을 수 없습니다.")
    return p


def _owners(ids: list[int]) -> list[User]:
    users = list(User.objects.filter(pk__in=ids))
    if len(users) != len(set(ids)):
        raise HttpError(400, "관리자를 찾을 수 없습니다.")
    return users


@router.get("", response=list[ProjectOut])
def list_projects(request, team: int | None = None, include_archived: bool = False):
    qs = _visible(request)
    if team is not None:
        qs = qs.filter(team_id=team)
    if not include_archived:
        qs = qs.filter(is_archived=False)
    return [project_out(p) for p in qs.order_by("team__name", "name")]


@router.get("/{project_id}", response=ProjectOut)
def get_project(request, project_id: int):
    return project_out(_project_or_404(request, project_id))


@router.post("", response={201: ProjectOut, 400: ErrorOut})
def create_project_ep(request, payload: ProjectCreateIn):
    team = team_or_404(request, payload.team_id)
    p = create_project(
        team=team, name=payload.name, purpose=payload.purpose,
        owners=_owners(payload.owner_ids), status=payload.status, **ctx(request),
    )
    return 201, project_out(p)


@router.patch("/{project_id}", response={200: ProjectOut, 400: ErrorOut, 409: ConflictOut})
def patch_project(request, project_id: int, payload: ProjectPatchIn):
    p = _project_or_404(request, project_id)
    data = payload.dict(exclude_unset=True)
    version = data.pop("version")
    if "owner_ids" in data:
        data["owners"] = _owners(data.pop("owner_ids") or [])
    p = update_project(p, data, expected_version=version, **ctx(request))
    return project_out(p)
```

### `core/api/routers/tasks.py`

```python
from datetime import date

from django.db.models import F
from ninja import Router
from ninja.errors import HttpError

from accounts.models import User
from projects.models import Project
from tasks.brief import task_brief
from tasks.models import ChangeLog, Task
from tasks.services import (
    create_task, extend_due, replace_checklist, transition, update_task, visible_tasks,
)
from teams.services import teams_of

from ..context import clamp_page, ctx, idem_key, task_or_404
from ..schemas import (
    ChangeLogOut, ConflictOut, ErrorOut, ExtendIn, TaskCreateIn, TaskListOut, TaskOut,
    TaskPatchIn, TransitionIn,
)
from ..serialize import changelog_out, task_out

router = Router(tags=["tasks"])


@router.get("", response=TaskListOut)
def list_tasks(
    request,
    team: int | None = None,
    project: int | None = None,
    assignee: int | None = None,
    status: str | None = None,
    due_from: date | None = None,
    due_to: date | None = None,
    q: str | None = None,
    include_archived: bool = False,
    limit: int = 50,
    offset: int = 0,
):
    qs = visible_tasks(request.auth)
    if team is not None:
        qs = qs.filter(project__team_id=team)
    if project is not None:
        qs = qs.filter(project_id=project)
    if assignee is not None:
        qs = qs.filter(assignee_id=assignee)
    if status:
        values = [s.strip() for s in status.split(",") if s.strip()]
        bad = [s for s in values if s not in dict(Task.STATUSES)]
        if bad:
            raise HttpError(400, f"알 수 없는 상태: {', '.join(bad)}")
        qs = qs.filter(status__in=values)
    if due_from:
        qs = qs.filter(due_date__gte=due_from)
    if due_to:
        qs = qs.filter(due_date__lte=due_to)
    if q:
        qs = qs.filter(title__icontains=q)
    if not include_archived:
        qs = qs.filter(project__is_archived=False)
    limit, offset = clamp_page(limit, offset)
    # nulls_last를 명시해야 SQLite(기한 미정이 앞)와 Postgres(뒤)가 같아지고 by_due()와도 맞는다.
    qs = qs.order_by(F("due_date").asc(nulls_last=True), "id")
    total = qs.count()
    return {
        "items": [task_brief(t) for t in qs[offset : offset + limit]],
        "total": total, "limit": limit, "offset": offset,
    }


@router.get("/{task_id}", response=TaskOut)
def get_task(request, task_id: int):
    return task_out(task_or_404(request, task_id))


@router.get("/{task_id}/history", response=list[ChangeLogOut])
def history(request, task_id: int):
    task = task_or_404(request, task_id)
    logs = ChangeLog.objects.filter(target_type="task", target_id=task.pk).select_related("actor")
    return [changelog_out(log) for log in logs]


@router.post("", response={201: TaskOut, 400: ErrorOut})
def create_task_ep(request, payload: TaskCreateIn):
    project = Project.objects.filter(pk=payload.project_id, team__in=teams_of(request.auth)).first()
    if project is None:
        raise HttpError(404, "프로젝트를 찾을 수 없습니다.")
    assignee = None
    if payload.assignee_id:
        assignee = User.objects.filter(pk=payload.assignee_id).first()
        if assignee is None:
            raise HttpError(400, "담당자를 찾을 수 없습니다.")
    c = ctx(request)
    task = create_task(
        project=project, title=payload.title, assignee=assignee,
        description=payload.description, done_when=payload.done_when,
        next_action=payload.next_action, priority=payload.priority,
        due_date=payload.due_date, no_due_reason=payload.no_due_reason,
        idempotency_key=idem_key(request), **c,
    )
    if payload.checklist is not None and not task.checklist.exists():
        replace_checklist(task, [i.dict() for i in payload.checklist], actor=c["actor"])
    return 201, task_out(task)


@router.patch("/{task_id}", response={200: TaskOut, 400: ErrorOut, 409: ConflictOut})
def patch_task(request, task_id: int, payload: TaskPatchIn):
    task = task_or_404(request, task_id)
    c = ctx(request)
    data = payload.dict(exclude_unset=True)
    version = data.pop("version")
    checklist = data.pop("checklist", None)
    if "assignee_id" in data:
        aid = data.pop("assignee_id")
        data["assignee"] = User.objects.filter(pk=aid).first() if aid else None
    if "project_id" in data:
        pid = data.pop("project_id")
        data["project"] = Project.objects.filter(pk=pid, team__in=teams_of(request.auth)).first()
        if data["project"] is None:
            raise HttpError(404, "프로젝트를 찾을 수 없습니다.")
    if data:
        task = update_task(task, data, expected_version=version, **c)
    if checklist is not None:
        replace_checklist(task, checklist, actor=c["actor"])
    return task_out(task)


@router.post("/{task_id}/transition", response={200: TaskOut, 400: ErrorOut, 409: ConflictOut})
def transition_ep(request, task_id: int, payload: TransitionIn):
    task = task_or_404(request, task_id)
    task = transition(
        task, payload.status, reason=payload.reason, expected_version=payload.version, **ctx(request)
    )
    return task_out(task)


@router.post("/{task_id}/extend", response={200: TaskOut, 400: ErrorOut, 409: ConflictOut})
def extend_ep(request, task_id: int, payload: ExtendIn):
    task = task_or_404(request, task_id)
    task = extend_due(
        task, payload.due_date, payload.reason, expected_version=payload.version, **ctx(request)
    )
    return task_out(task)
```

`PATCH`로 `title/description/done_when/next_action/notes`만 바꾸면 `version` 검사 없이 저장되고 `version`이 오르지 않는다(자동 저장 필드). 팀 데이터 필드가 하나라도 있으면 `version`이 검사된다.

### `core/api/routers/today.py`

```python
from ninja import Router

from tasks.brief import task_brief
from tasks.services import (
    today_add, today_exclude, today_reorder, today_restore_excluded, today_set_auto_pull,
    today_view,
)

from ..context import task_or_404
from ..schemas import ErrorOut, TodayAddIn, TodayOrderIn, TodayOut, TodaySettingsIn

router = Router(tags=["today"])


def _out(user) -> dict:
    v = today_view(user)
    return {
        "date": v["date"],
        "items": [{**task_brief(t), "auto_pulled": t.auto_pulled} for t in v["items"]],
        "focus": task_brief(v["focus"]) if v["focus"] else None,
        "done_today": [task_brief(t) for t in v["done_today"]],
        "auto_pull_days": v["auto_pull_days"],
        "counts": v["counts"],
    }


@router.get("", response=TodayOut)
def get_today(request):
    return _out(request.auth)


@router.post("", response=TodayOut)
def add(request, payload: TodayAddIn):
    today_add(request.auth, task_or_404(request, payload.task_id))
    return _out(request.auth)


@router.delete("/excluded", response=TodayOut)
def restore(request):
    today_restore_excluded(request.auth)
    return _out(request.auth)


@router.delete("/{task_id}", response=TodayOut)
def exclude(request, task_id: int):
    today_exclude(request.auth, task_or_404(request, task_id))
    return _out(request.auth)


@router.patch("/order", response=TodayOut)
def order(request, payload: TodayOrderIn):
    today_reorder(request.auth, payload.task_ids)
    return _out(request.auth)


@router.patch("/settings", response={200: TodayOut, 400: ErrorOut})
def settings_ep(request, payload: TodaySettingsIn):
    today_set_auto_pull(request.auth, payload.auto_pull_days)
    return _out(request.auth)
```

고정 경로(`/excluded`, `/order`, `/settings`)를 `/{task_id}`보다 **먼저** 등록한다.
django-ninja는 `{task_id}`에 Django `int` 변환기를 붙이지 않으므로 `/api/today/order`가
`DELETE /{task_id}`에 먼저 잡혀 **405**가 난다. 순서가 곧 우선순위다.

### `core/api/routers/reports.py`

```python
from datetime import date

from ninja import Router
from ninja.errors import HttpError

from common.dates import last_week_start
from reports.services import weekly

from ..context import team_or_404

router = Router(tags=["reports"])


@router.get("/weekly", response=dict)
def weekly_ep(request, team: int, week_start: date | None = None):
    t = team_or_404(request, team)
    ws = week_start or last_week_start()
    if ws.weekday() != 0:
        raise HttpError(400, "week_start는 월요일이어야 합니다.")
    return weekly(t, ws)
```

### `core/api/routers/integrations.py`

```python
from django.utils import timezone
from ninja import Router
from ninja.errors import HttpError

from ..models import IntegrationStatus
from ..schemas import StatusIn

router = Router(tags=["integrations"])
ALLOWED = {"discord", "mcp"}


@router.post("/{name}/status", response={204: None})
def report_status(request, name: str, payload: StatusIn):
    if name not in ALLOWED:
        raise HttpError(404, "알 수 없는 통합 이름입니다.")
    IntegrationStatus.objects.update_or_create(
        name=name,
        defaults={"last_run_at": timezone.now(), "ok": payload.ok, "detail": payload.detail},
    )
    return 204, None
```

라우터에 상태 보고 하나만 남았다. 웹훅 주소를 읽어 가는 엔드포인트는 없다 — 발송 대상이 core DB에 없기 때문이다(팀 채널은 `DISCORD_CHANNEL_ID` 환경 변수, 개인은 `User.discord_user_id`). `ALLOWED`는 바꾸지 않는다.

리스너(`discord-bot` 컨테이너)는 `/ops`에 보고하지 않는다: `IntegrationStatus.name`이 단일 키라 리스너가 보고하면 틱의 `discord` 행을 덮어쓰고, 재접속은 discord.py가 맡으니 보고할 close code도 없다. 리스너 상태는 `docker compose logs discord-bot`으로 본다.

### `core/api/routers/discord.py` (신규)

봇 명령 5개가 들어오는 곳. 라우터 인증이 `BotTokenAuth` **하나**라서 API 기본 인증(`[BrowserSessionAuth(), TokenAuth()]`)을 대체한다 — 세션 쿠키·읽기·쓰기 토큰은 이 경로에 들어올 수 없다. 엔드포인트마다 `if token.scope != "bot"` 가드를 손으로 붙이지 않는다.

```python
"""Discord 봇 명령이 들어오는 곳.

봇은 자기 이름으로 일하지 않는다. 연결된 Discord 사용자를 **사람**으로 바꿔 그 사람의 팀
범위 안에서만 움직인다(`get_visible_task(actor, …)`). 변경 이력에는 행위자=그 사람,
경로=Discord(`dc`), 토큰=봇 토큰이 남는다.

라우터 인증이 `BotTokenAuth` 하나라서 세션 쿠키·읽기·쓰기 토큰은 이 경로에 들어오지 못한다.
"""

from ninja import Router
from ninja.errors import HttpError

from accounts.services import link_discord, unlink_discord_by_id, user_by_discord_id
from tasks.brief import task_brief
from tasks.services import extend_due, get_visible_task, today_view, transition

from ..auth import BotTokenAuth
from ..schemas import DiscordActorIn, DiscordExtendIn, DiscordLinkIn
from ..serialize import task_out

router = Router(tags=["discord"], auth=BotTokenAuth())

UNLINKED = "연결되지 않은 Discord 계정입니다. 웹 설정 → 프로필에서 연결 코드를 받으세요."


def _actor(discord_user_id: str):
    user = user_by_discord_id(discord_user_id)
    if user is None:
        raise HttpError(404, UNLINKED)
    return user


def _ctx(request, actor) -> dict:
    """X-Source 헤더를 믿지 않는다. 이 라우터에 들어온 것 자체가 경로의 증거다."""
    return {"actor": actor, "source": "dc", "token": getattr(request, "api_token", None)}


def _task(actor, task_id: int):
    task = get_visible_task(actor, task_id)
    if task is None:
        raise HttpError(404, "태스크를 찾을 수 없습니다.")
    return task


@router.post("/link", response=dict)
def link(request, payload: DiscordLinkIn):
    user = link_discord(payload.code, payload.discord_user_id)
    return {"display_name": user.display_name}


@router.post("/unlink", response=dict)
def unlink(request, payload: DiscordActorIn):
    return {"unlinked": unlink_discord_by_id(payload.discord_user_id)}


@router.post("/today", response=dict)
def today(request, payload: DiscordActorIn):
    """식별자를 쿼리 문자열에 싣지 않으려고 GET이 아니라 POST다."""
    actor = _actor(payload.discord_user_id)
    view = today_view(actor)
    return {
        "display_name": actor.display_name,
        "date": view["date"].isoformat(),
        "items": [task_brief(t) for t in view["items"]],
        "counts": view["counts"],
    }


@router.post("/tasks/{task_id}/done", response=dict)
def done(request, task_id: int, payload: DiscordActorIn):
    actor = _actor(payload.discord_user_id)
    task = _task(actor, task_id)
    was = task.get_status_display()
    # 사용자는 버전을 본 적이 없다. 의도는 "지금 완료로 바꿔라"다. 한 요청 안에서 읽고
    # 그 값으로 CAS를 건다 — 그 사이(수 ms)에 끼면 409로 알린다(조용히 덮어쓰지 않는다).
    task = transition(
        task, "done", expected_version=task.version, reason="", **_ctx(request, actor)
    )
    return {"was": was, "task": task_out(task)}


@router.post("/tasks/{task_id}/extend", response=dict)
def extend(request, task_id: int, payload: DiscordExtendIn):
    actor = _actor(payload.discord_user_id)
    task = _task(actor, task_id)
    task = extend_due(
        task,
        payload.due_date,
        payload.reason,
        expected_version=task.version,
        **_ctx(request, actor),
    )
    return {"task": task_out(task)}
```

읽는 순서대로의 근거:

- **행위자는 봇이 아니라 사람이다.** `_actor`가 snowflake로 사람을 찾고(`user_by_discord_id` — 연결이 증명된 활성 사용자만), 범위는 `get_visible_task(actor, …)`가 그 사람의 팀으로 좁힌다. 봇 계정이 팀 A에 있어도 팀 B 사용자의 태스크를 그 사람으로서 바꿀 수 있고, 그 사람이 못 보는 태스크는 404다.
- 연결되지 않은 계정은 **404 + 한국어 안내**다. 봇은 그 문구를 그대로 DM으로 돌려준다(`commands.py`의 404 분기).
- `expected_version`은 **같은 요청 안에서** 방금 읽은 객체의 값이다. 사용자는 버전을 본 적이 없고 의도는 "지금 바꿔라"이므로 이것은 lost update가 아니다. 읽기와 쓰기 사이(수 ms)에 웹 편집이 끼면 `ConflictError` → 409 → 봇이 "방금 다른 곳에서 바뀌었어요"로 답한다. 재시도 루프는 만들지 않는다.
- `/today`가 GET이 아니라 POST인 이유: 식별자(snowflake)를 쿼리 문자열에 싣지 않는다.
- 이 라우터에는 업무 규칙이 없다. 상태 전이·기한 검사·이력은 전부 `tasks/services.py`가 한다(GUIDE-00 §3). `done`을 두 번 보내도 같은 상태 재요청은 서비스가 조기 반환하므로 이력이 한 줄이고, `extend`는 현재 기한보다 앞선 날짜를 서비스가 거부한다(400 + 그 문구가 그대로 DM으로 간다).

---

## 5.7 엔드포인트 요약과 예시

| 메서드·경로 | 성공 | 실패 |
|---|---|---|
| `GET /api/me` | 200 `MeOut` | 401 |
| `GET /api/teams/{id}` | 200 `TeamOut` | 404 |
| `GET /api/teams/{id}/members` | 200 `[UserBrief]` | 404 |
| `GET /api/teams/{id}/status` | 200 dict (`team_status`) | 404 |
| `POST /api/teams/{id}/invites` `{days}` | 201 `InviteOut` | 400(관리자 아님) |
| `DELETE /api/teams/invites/{id}` | 204 | 404 |
| `GET /api/projects?team=&include_archived=` | 200 `[ProjectOut]` | |
| `GET /api/projects/{id}` | 200 `ProjectOut` | 404 |
| `POST /api/projects` `{team_id, name, purpose, owner_ids, status}` | 201 | 400 |
| `PATCH /api/projects/{id}` (version 필수) | 200 | 400, 409 |
| `GET /api/tasks?team=&project=&assignee=&status=&due_from=&due_to=&q=&include_archived=&limit=&offset=` | 200 `TaskListOut` | 400(상태값 오류) |
| `GET /api/tasks/{id}` | 200 `TaskOut` | 404 |
| `GET /api/tasks/{id}/history` | 200 `[ChangeLogOut]` | 404 |
| `POST /api/tasks` (헤더 `Idempotency-Key` 선택) | 201 `TaskOut` | 400, 404 |
| `PATCH /api/tasks/{id}` (version 필수) | 200 | 400, 404, 409 |
| `POST /api/tasks/{id}/transition` `{status, reason, version}` | 200 | 400, 409 |
| `POST /api/tasks/{id}/extend` `{due_date, reason, version}` | 200 | 400, 409 |
| `GET /api/today` · `POST /api/today` `{task_id}` · `DELETE /api/today/{task_id}`(오늘 제외) · `DELETE /api/today/excluded`(제외 복원) · `PATCH /api/today/order` `{task_ids}` · `PATCH /api/today/settings` `{auto_pull_days}` | 200 `TodayOut` | 400, 404 |
| `GET /api/reports/weekly?team=&week_start=` | 200 dict (`weekly`) | 400, 404 |
| `POST /api/integrations/{name}/status` `{ok, detail}` | 204 | 404 |
| `POST /api/integrations/discord/link` `{code, discord_user_id}` | 200 `{display_name}` | 400(코드 틀림·만료·사용됨), 403(bot 범위 아님) |
| `POST /api/integrations/discord/unlink` `{discord_user_id}` | 200 `{unlinked: bool}` | 403 |
| `POST /api/integrations/discord/today` `{discord_user_id}` | 200 `{display_name, date, items, counts}` | 403, 404(미연결) |
| `POST /api/integrations/discord/tasks/{id}/done` `{discord_user_id}` | 200 `{was, task}` | 400, 403, 404(미연결·안 보이는 태스크), 409 |
| `POST /api/integrations/discord/tasks/{id}/extend` `{discord_user_id, due_date, reason}` | 200 `{task}` | 400, 403, 404, 409 |

공통:

- 인증 실패 401. 읽기 토큰으로 쓰기 요청 403.
- 검증 실패 400 본문: `{"detail": {"필드": "메시지"}}`.
- 충돌 409 본문: `{"detail": "conflict", "latest": <TaskOut 또는 ProjectOut>}`.
- AI용 토큰(`for_ai`, 기본값·OAuth 발급분)이거나 헤더 `X-Source: mcp|ai`가 있으면 변경 이력 `source`가 `mcp`로 기록된다. `/api/integrations/discord/`의 5개 경로는 헤더와 무관하게 `source="dc"`다(라우터가 정한다).
- `/api/integrations/discord/`는 `bot` 범위 토큰만 통한다. 세션 쿠키·읽기·쓰기 토큰은 403이고, 반대로 `bot` 토큰은 `/api/integrations/` 밖의 쓰기(`POST /api/tasks` 등)에서 403이다.
- 막힘·일시정지는 `transition`으로 한다: `{"status":"blocked","reason":"서류 대기","version":3}`. 이미 멈춘 태스크의 사유만 고치려면 `PATCH {"stop_reason": "...", "version": n}`.
- 진행 메모는 `PATCH {"notes": "..."}`로 통째로 바꾼다(덧붙이기는 클라이언트가 읽어서 이어 붙인다).

예시 (curl):

```bash
curl -s -H "Authorization: Bearer pm_..." "http://localhost:8000/api/tasks?team=1&status=todo,doing,paused,blocked,review&limit=20"
curl -s -H "Authorization: Bearer pm_..." -H "Content-Type: application/json" \
  -X POST http://localhost:8000/api/tasks/12/transition -d '{"status":"done","version":3}'
```

---

## 5.8 검증

```bash
uv run python manage.py check
uv run ruff check .
uv run python manage.py runserver
```

브라우저에서 admin 로그인 후 `http://127.0.0.1:8000/api/docs`가 열리고 5.7 표의 엔드포인트가 전부 보이면 통과. shell에서 토큰을 만들어 curl로 `GET /api/me`가 200을 돌려주는지 확인한다.

```bash
uv run python manage.py shell -c "
from accounts.models import User, ApiToken
u = User.objects.get(username='u1')
t, raw = ApiToken.issue(u, 'test', 'write')
print(raw)
"
```

봇 경로는 범위 차단까지 확인한다. 위의 **쓰기** 토큰으로 `POST /api/integrations/discord/today`를 부르면 403(`Discord 봇 토큰이 필요합니다.`)이어야 하고, `bot` 범위 토큰으로 `POST /api/tasks`를 부르면 403(`읽기 전용 토큰입니다.`)이어야 한다.

```bash
uv run python manage.py shell -c "
from accounts.models import User, ApiToken
from accounts.services import issue_link_code
u = User.objects.get(username='u1')
print(ApiToken.issue(u, 'Discord 봇', 'bot')[1])
print(issue_link_code(u))
"
```

커밋: `step 5: http api`

다음: [GUIDE-01-core-4-web.md](GUIDE-01-core-4-web.md)
