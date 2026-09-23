import json

import httpx
import pytest

import mcp_server.core_client as cc
from mcp_server.auth import current_token

# 토큰 -> (조직 역할 목록, 쓰기 가능 여부). permissions._probe가 /api/me의
# PATCH /api/tasks/0(있지도 않은 id) 응답으로 이 둘을 읽어 낸다.
TOKENS = {
    "pm_good": {"orgs": [{"id": 1, "name": "산돌이", "role": "member"}], "write": True},
    "pm_read": {"orgs": [{"id": 1, "name": "산돌이", "role": "member"}], "write": False},
    "pm_admin": {"orgs": [{"id": 1, "name": "산돌이", "role": "admin"}], "write": True},
}


class FakeCore:
    def __init__(self):
        self.calls = []
        self.tasks = {
            1: {
                "id": 1,
                "number": "TASK-1",
                "title": "메뉴 누락 개선",
                "version": 1,
                "status": "todo",
                "priority": 5,
                "due_date": "2026-09-12",
                "next_action": "",
                "done_when": "",
                "description": "",
                "notes": "",
                "stop_reason": "",
                "url": "http://pm/tasks/1",
                "project": {"id": 1, "name": "학식 API", "org_id": 1},
                "assignee": {"id": 2, "display_name": "팀원", "discord_user_id": None},
            },
        }

    def handler(self, request: httpx.Request) -> httpx.Response:
        self.calls.append(
            (
                request.method,
                request.url.path + (f"?{request.url.query.decode()}" if request.url.query else ""),
                dict(request.headers),
                request.content,
            )
        )
        auth = request.headers.get("authorization", "")
        token = auth.removeprefix("Bearer ")
        profile = TOKENS.get(token)
        if profile is None:
            return httpx.Response(401, json={"detail": "Unauthorized"})
        p = request.url.path
        if p == "/api/me":
            return httpx.Response(
                200,
                json={
                    "id": 2,
                    "orgs": profile["orgs"],
                    "token_scope": "write" if profile["write"] else "read",
                },
            )
        if p == "/api/tasks" and request.method == "GET":
            return httpx.Response(
                200,
                json={
                    "items": list(self.tasks.values()),
                    "total": 1,
                    "limit": 50,
                    "offset": 0,
                },
            )
        if p == "/api/tasks/1" and request.method == "GET":
            return httpx.Response(200, json=self.tasks[1])
        if p == "/api/tasks/1" and request.method == "PATCH":
            body = json.loads(request.content)
            if body["version"] != self.tasks[1]["version"]:
                return httpx.Response(409, json={"detail": "conflict", "latest": self.tasks[1]})
            self.tasks[1].update({k: v for k, v in body.items() if k != "version"})
            self.tasks[1]["version"] += 1
            return httpx.Response(200, json=self.tasks[1])
        if p == "/api/tasks/1/transition":
            body = json.loads(request.content)
            if body["status"] == "blocked" and not body.get("reason"):
                return httpx.Response(
                    400, json={"detail": {"stop_reason": "막힘 사유를 입력하세요."}}
                )
            self.tasks[1]["status"] = body["status"]
            self.tasks[1]["stop_reason"] = (
                body.get("reason", "") if body["status"] in ("paused", "blocked") else ""
            )
            self.tasks[1]["version"] += 1
            return httpx.Response(200, json=self.tasks[1])
        if p == "/api/orgs/1/repos" and request.method == "GET":
            return httpx.Response(
                200,
                json=[
                    {
                        "full_name": "teamSANDOL/sandol-api",
                        "clone_url": "https://github.com/teamSANDOL/sandol-api.git",
                        "private": False,
                    }
                ],
            )
        if p == "/api/projects/1/repo" and request.method == "POST":
            return httpx.Response(
                200, json={"connected": True, "full_name": "teamSANDOL/sandol-api"}
            )
        if p == "/api/projects/2/repo" and request.method == "POST":
            # 조직이 ai.manage_repo를 막아 둔 경우. 도구는 그 문구를 그대로 사람에게 전한다.
            return httpx.Response(
                400,
                json={"detail": {"url": "이 조직 설정에서 AI의 저장소 연결이 꺼져 있어요."}},
            )
        if p == "/api/orgs/1/governance" and request.method == "GET":
            return httpx.Response(200, json={"text": "# 기본안", "is_default": True})
        if p == "/api/orgs/1/settings" and request.method == "GET":
            return httpx.Response(
                200,
                json={
                    "values": {"task.default_priority": 5},
                    "specs": [
                        {
                            "key": "task.default_priority",
                            "label": "기본 중요도",
                            "help": "",
                            "kind": "int",
                            "default": 5,
                            "choices": [],
                            "lo": 1,
                            "hi": 10,
                            "group": "task",
                            "overridable": True,
                            "scope": "org",
                        }
                    ],
                    "locked": [],
                },
            )
        if p == "/api/tasks" and request.method == "POST":
            if json.loads(request.content).get("project_id") == 999:
                return httpx.Response(404, json={"detail": "프로젝트를 찾을 수 없습니다."})
            return httpx.Response(201, json={**self.tasks[1], "id": 9, "number": "TASK-9"})
        if p == "/api/orgs/teams/1/members" and request.method == "POST":
            return httpx.Response(404, json={"detail": "사용자를 찾을 수 없습니다."})
        if p == "/api/project-docs" and request.method == "GET":
            return httpx.Response(
                200,
                json={
                    "items": [
                        {
                            "id": 7,
                            "project_id": 1,
                            "project_name": "학식 API",
                            "title": "설계 결정",
                            "version": 2,
                            "updated_at": "2026-09-16T00:00:00Z",
                            "task_ids": [1],
                        }
                    ],
                    "total": 1,
                    "limit": 50,
                    "offset": 0,
                },
            )
        if p == "/api/project-docs/7" and request.method == "GET":
            return httpx.Response(
                200,
                json={
                    "id": 7,
                    "project_id": 1,
                    "project_name": "학식 API",
                    "title": "설계 결정",
                    "body_md": "# 배경\n메뉴 누락을 줄인다",
                    "version": 2,
                    "updated_at": "2026-09-16T00:00:00Z",
                    "task_ids": [1],
                },
            )
        if p == "/api/project-docs" and request.method == "POST":
            body = json.loads(request.content)
            return httpx.Response(
                201,
                json={
                    "id": 8,
                    "project_id": body["project_id"],
                    "project_name": "학식 API",
                    "title": body["title"],
                    "body_md": body.get("body_md", ""),
                    "version": 1,
                    "updated_by": "AI",
                    "updated_source": "mcp",
                    "task_ids": [],
                },
            )
        if p == "/api/project-docs/7" and request.method == "PATCH":
            body = json.loads(request.content)
            if body["version"] != 2:
                return httpx.Response(409, json={"detail": "conflict"})
            return httpx.Response(
                200,
                json={
                    "id": 7,
                    "project_id": 1,
                    "project_name": "학식 API",
                    "title": body.get("title", "설계 결정"),
                    "body_md": body.get("body_md", ""),
                    "version": 3,
                    "updated_by": "AI",
                    "updated_source": "mcp",
                    "task_ids": [1],
                },
            )
        if p == "/api/projects/404":
            return httpx.Response(404, text="<h1>Not Found</h1>")
        return httpx.Response(404, json={"detail": "x"})


@pytest.fixture
def fake_core(monkeypatch):
    fake = FakeCore()
    real_init = cc.Core.__init__

    def patched(self, token, transport=None):
        real_init(self, token, transport=httpx.MockTransport(fake.handler))

    monkeypatch.setattr(cc.Core, "__init__", patched)
    return fake


@pytest.fixture
def with_token():
    tok = current_token.set("pm_good")
    yield
    current_token.reset(tok)
