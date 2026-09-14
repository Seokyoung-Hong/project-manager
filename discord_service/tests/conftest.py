import json

import httpx
import pytest

from discord_service.core_client import CoreClient
from discord_service.discord import Bot
from discord_service.messages import STATUS
from discord_service.store import Store

OPEN = ("todo", "doing", "paused", "blocked", "review")
BOT_PREFIX = "/api/integrations/discord/"
CHANNEL = "999"  # 조직 채널 id (DISCORD_CHANNEL_ID)

DEFAULT_SETTINGS = {
    "notify.deadline_kinds": ["d3", "d1", "d0", "overdue"],
    "notify.send_hour": None,
    "notify.overdue_repeat": "daily",
    "notify.quiet_weekend": False,
    "notify.weekly_enabled": True,
    "notify.weekly_weekday": None,
    "notify.weekly_hour": None,
    "notify.blocked_escalate_days": 0,
    "notify.review_nudge_days": 0,
    "notify.project_channel_events": [],
    "notify.team_channel_weekly": False,
}


def member(i=2, did="111", name="팀원"):
    return {"id": i, "display_name": name, "discord_user_id": did}


def task(i, due, status="todo", stop_reason="", assignee=None):
    return {
        "id": i,
        "number": f"TASK-{i}",
        "title": f"할 일 {i}",
        "project": {"id": 1, "name": "학식 API", "org_id": 1},
        "assignee": member() if assignee is None else assignee,
        "status": status,
        "priority": 5,
        "due_date": due,
        "stop_reason": stop_reason,
        "next_action": "",
        "url": f"http://pm/tasks/{i}",
    }


def weekly_data(
    completed=(),
    reopened=(),
    due_this_week=(),
    overdue=(),
    blocked=(),
    by_project=None,
    members=None,
):
    completed, reopened = list(completed), list(reopened)
    due_this_week, overdue, blocked = list(due_this_week), list(overdue), list(blocked)
    return {
        "org": {"id": 1, "name": "산돌이"},
        "period_start": "2026-08-31",
        "period_end": "2026-09-07",
        "completed": completed,
        "reopened": reopened,
        "due_this_week": due_this_week,
        "overdue": overdue,
        "blocked": blocked,
        "by_project": by_project
        if by_project is not None
        else [
            {
                "project": {"id": 1, "name": "학식 API", "status": "active"},
                "completed": len(completed),
                "reopened": len(reopened),
                "open": 2,
                "overdue": len(overdue),
                "blocked": len(blocked),
            }
        ],
        "counts": {
            "completed": len(completed),
            "reopened": len(reopened),
            "due_this_week": len(due_this_week),
            "overdue": len(overdue),
            "blocked": len(blocked),
            "open": 2,
            "review": 0,
            "no_due": 0,
        },
        "members": [member()] if members is None else list(members),
    }


class FakeCore:
    """core API 흉내. tasks dict를 바꾸면 응답이 바뀐다.

    봇 명령 5개(`/api/integrations/discord/…`)를 함께 흉내 낸다. `bot_status`를
    404·403·409·429·400 중 하나로 바꾸면 그 상태와 `bot_detail`(한국어 문구)로 답한다.
    """

    def __init__(self, tasks: list[dict], weekly: dict | None = None):
        self.tasks = {t["id"]: t for t in tasks}
        self.weekly_data = weekly
        self.status_reports = []
        self.calls: list[tuple[str, dict]] = []  # 봇 명령 호출 (경로, 본문)
        self.writes: list[tuple[str, dict]] = []  # 실제로 태스크를 바꾼 호출만
        self.bot_status = 200
        self.bot_detail = "x"
        # 슬래시 명령용. admin=False면 채널 저장이 400, channel_save_fail이면 새 id 저장만 500.
        self.admin = True
        self.channel_save_fail = False
        self.channels = {"team": "", "project": ""}
        self.next_id = 100
        # --- 설정 시스템 (IMPL-PLAN-4 §4.5) ---
        self.org_settings_values: dict = {}
        self.org_members_data: list[
            dict
        ] = []  # [{id, display_name, discord_user_id, notify:{dm,kinds,hour}}]
        self.org_teams_data: list[dict] = []  # [{id, name, discord_channel_id}]
        self.org_projects_data: list[dict] = []  # [{id, name, discord_channel_id, teams:[...]}]
        self.projects_by_id: dict[int, dict] = {}  # id -> project_out 흉내 (owners 포함)

    # --- 조회 도움말 ---
    def paths(self) -> list[str]:
        return [p for p, _ in self.calls]

    def handler(self, request: httpx.Request) -> httpx.Response:
        path = request.url.path
        if path == "/api/tasks":
            status_param = request.url.params.get("status")
            statuses = set(status_param.split(",")) if status_param else set(OPEN)
            items = [t for t in self.tasks.values() if t["status"] in statuses]
            project_param = request.url.params.get("project")
            if project_param:
                items = [t for t in items if str(t["project"]["id"]) == project_param]
            due_to = request.url.params.get("due_to")
            if due_to:
                items = [t for t in items if t["due_date"] and t["due_date"] <= due_to]
            return httpx.Response(
                200, json={"items": items, "total": len(items), "limit": 200, "offset": 0}
            )
        if path.startswith("/api/tasks/"):
            t = self.tasks.get(int(path.rsplit("/", 1)[1]))
            return httpx.Response(200, json=t) if t else httpx.Response(404, json={"detail": "x"})
        if path == "/api/reports/weekly":
            return httpx.Response(200, json=self.weekly_data)
        if path == "/api/projects":
            return httpx.Response(200, json=self.org_projects_data)
        if path.startswith("/api/projects/"):
            p = self.projects_by_id.get(int(path.rsplit("/", 1)[1]))
            return httpx.Response(200, json=p) if p else httpx.Response(404, json={"detail": "x"})
        if path.endswith("/settings") and path.startswith("/api/orgs/"):
            return httpx.Response(
                200,
                json={
                    "values": self.org_settings_values,
                    "defaults": DEFAULT_SETTINGS,
                    "locked": [],
                },
            )
        if path.endswith("/members") and path.startswith("/api/orgs/"):
            return httpx.Response(200, json=self.org_members_data)
        if path.endswith("/teams") and path.startswith("/api/orgs/"):
            return httpx.Response(200, json=self.org_teams_data)
        if path == BOT_PREFIX + "status":
            self.status_reports.append(json.loads(request.content))
            return httpx.Response(204)
        if path.startswith(BOT_PREFIX):
            return self._bot(path.removeprefix(BOT_PREFIX), json.loads(request.content))
        return httpx.Response(404)

    def _bot(self, cmd: str, body: dict) -> httpx.Response:
        self.calls.append((cmd, body))
        if self.bot_status != 200:
            return httpx.Response(self.bot_status, json={"detail": self.bot_detail})
        if cmd == "link":
            return httpx.Response(200, json={"display_name": "홍길동"})
        if cmd == "unlink":
            return httpx.Response(200, json={"unlinked": True})
        if cmd == "today":
            items = [t for t in self.tasks.values() if t["status"] in OPEN]
            return httpx.Response(
                200,
                json={
                    "display_name": "홍길동",
                    "date": "2026-09-09",
                    "items": items,
                    "counts": {"my_open": len(items), "done_today": 1},
                },
            )
        if cmd == "projects":
            return httpx.Response(
                200,
                json=[
                    {
                        "id": 1,
                        "name": "학식 API",
                        "org_id": 1,
                        "discord_channel_id": self.channels["project"],
                    },
                    {"id": 2, "name": "산돌이 봇", "org_id": 1, "discord_channel_id": ""},
                ],
            )
        if cmd == "teams":
            return httpx.Response(
                200,
                json=[
                    {
                        "id": 1,
                        "name": "백엔드",
                        "org_id": 1,
                        "discord_channel_id": self.channels["team"],
                    }
                ],
            )
        if cmd == "members":
            return httpx.Response(
                200, json=[{"id": 1, "display_name": "관리자"}, {"id": 2, "display_name": "팀원"}]
            )
        if cmd == "mytasks":
            return httpx.Response(200, json=[t for t in self.tasks.values() if t["status"] in OPEN])
        if cmd == "tasks":
            if not body.get("due_date") and not body.get("no_due_reason"):
                return httpx.Response(
                    400, json={"detail": {"no_due_reason": "기한이 없으면 사유를 입력하세요."}}
                )
            self.writes.append((cmd, body))
            t = task(self.next_id, body.get("due_date"))
            t["title"] = body["title"]
            self.tasks[t["id"]] = t
            self.next_id += 1
            return httpx.Response(200, json={"task": t})
        parts = cmd.split("/")  # tasks/<id>/<action> · teams/<id>/channel · projects/<id>/channel
        if len(parts) == 3 and parts[2] == "channel":
            kind = parts[0].removesuffix("s")
            if int(parts[1]) != 1:
                return httpx.Response(404, json={"detail": "찾을 수 없습니다."})
            if not self.admin:
                return httpx.Response(
                    400, json={"detail": {"org": "조직 관리자만 할 수 있습니다."}}
                )
            if body["channel_id"] and self.channel_save_fail:
                return httpx.Response(500, json={"detail": "boom"})
            self.channels[kind] = body["channel_id"]
            return httpx.Response(200, json={"id": 1, "discord_channel_id": body["channel_id"]})
        if len(parts) == 3 and parts[0] == "tasks":
            t = self.tasks.get(int(parts[1]))
            if t is None:
                return httpx.Response(404, json={"detail": "태스크를 찾을 수 없습니다."})
            self.writes.append((cmd, body))
            if parts[2] == "done":
                was = STATUS[t["status"]]
                t["status"] = "done"
                return httpx.Response(200, json={"was": was, "task": t})
            if parts[2] == "extend":
                t["due_date"] = body["due_date"]
                return httpx.Response(200, json={"task": t})
            if parts[2] == "update":
                t.update({k: v for k, v in body.items() if k in t})
                return httpx.Response(200, json={"task": t})
            if parts[2] == "note":
                return httpx.Response(200, json={"task": t})
            if parts[2] == "status":
                was = STATUS[t["status"]]
                t["status"] = body["status"]
                t["stop_reason"] = body["reason"]
                return httpx.Response(200, json={"was": was, "task": t})
        return httpx.Response(404, json={"detail": "x"})


class FakeBot:
    """Discord 봇 REST 흉내. 실제 `Bot`을 MockTransport로 감싼다.

    `errors[채널id]`(또는 모든 채널을 뜻하는 `"*"`)에 `(상태, 본문)`을 넣으면 그 순서로
    답한다. 예: `{"dm-111": [(403, {"code": 50007})]}`, `{"*": [429]}`.
    """

    def __init__(self, errors: dict | None = None):
        self.calls: list[dict] = []  # 모든 요청 (경로·본문·헤더)
        self.opened: list[str] = []  # /users/@me/channels 를 부른 recipient_id
        self.messages: list[dict] = []  # 성공한 발송 (채널·본문·allowed_mentions)
        self.errors = {k: list(v) for k, v in (errors or {}).items()}

    # --- 조회 도움말 ---
    @property
    def sent(self) -> list[str]:
        return [m["content"] for m in self.messages]

    def to(self, channel: str) -> list[str]:
        return [m["content"] for m in self.messages if m["channel"] == channel]

    def dm(self, discord_user_id: str) -> list[str]:
        return self.to(f"dm-{discord_user_id}")

    def attempts(self, channel: str) -> int:
        return sum(1 for c in self.calls if c["path"] == f"/channels/{channel}/messages")

    def handler(self, request: httpx.Request) -> httpx.Response:
        path = request.url.path.removeprefix("/api/v10")
        body = json.loads(request.content)
        self.calls.append(
            {
                "path": path,
                "body": body,
                "auth": request.headers.get("Authorization"),
                "ua": request.headers.get("User-Agent"),
            }
        )
        if path == "/users/@me/channels":
            recipient = str(body["recipient_id"])
            self.opened.append(recipient)
            return httpx.Response(200, json={"id": f"dm-{recipient}"})
        channel = path.split("/")[2]
        status, payload = self._next(channel)
        if status != 200:
            headers = {"Retry-After": "0"} if status == 429 else {}
            return httpx.Response(status, json=payload, headers=headers)
        self.messages.append(
            {
                "channel": channel,
                "content": body["content"],
                "allowed_mentions": body["allowed_mentions"],
            }
        )
        return httpx.Response(200, json={"id": "m1"})

    def _next(self, channel: str) -> tuple[int, dict]:
        for key in (channel, "*"):
            queue = self.errors.get(key)
            if queue:
                e = queue.pop(0)
                return (e, {}) if isinstance(e, int) else e
        return 200, {}


def make_bot(fake: FakeBot, store=None, channel_id: str = CHANNEL) -> Bot:
    return Bot(
        "botsecret",
        channel_id,
        store,
        transport=httpx.MockTransport(fake.handler),
        sleep=lambda s: None,
    )


def make_core(fake: FakeCore) -> CoreClient:
    return CoreClient("http://core", "pm_test", transport=httpx.MockTransport(fake.handler))


@pytest.fixture
def store(tmp_path):
    return Store(str(tmp_path / "t.sqlite"))


@pytest.fixture
def fake_bot():
    return FakeBot()


@pytest.fixture
def bot(fake_bot, store):
    return make_bot(fake_bot, store)
