import json

import httpx
import pytest

import mcp_server.core_client as cc
from mcp_server.auth import current_token


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
            (request.method, request.url.path, dict(request.headers), request.content)
        )
        auth = request.headers.get("authorization", "")
        if auth != "Bearer pm_good":
            return httpx.Response(401, json={"detail": "Unauthorized"})
        p = request.url.path
        if p == "/api/me":
            return httpx.Response(
                200,
                json={"id": 2, "orgs": [{"id": 1, "name": "산돌이", "role": "member"}]},
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
        if p == "/api/orgs/1/governance" and request.method == "GET":
            return httpx.Response(
                200, json={"text": "# 기본안", "is_default": True, "enforced": []}
            )
        if p == "/api/orgs/1/settings" and request.method == "GET":
            return httpx.Response(
                200, json={"values": {"ai.close_task": "deny"}, "defaults": {}, "locked": []}
            )
        if p == "/api/projects/1/settings" and request.method == "GET":
            return httpx.Response(
                200, json={"values": {}, "effective": {"task.priority_cap": 7}, "locked": []}
            )
        if p == "/api/tasks" and request.method == "POST":
            if json.loads(request.content).get("project_id") == 999:
                return httpx.Response(404, json={"detail": "프로젝트를 찾을 수 없습니다."})
            return httpx.Response(201, json={**self.tasks[1], "id": 9, "number": "TASK-9"})
        if p == "/api/orgs/teams/1/members" and request.method == "POST":
            return httpx.Response(404, json={"detail": "사용자를 찾을 수 없습니다."})
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
