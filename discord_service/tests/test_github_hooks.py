"""GitHub 알림 웹훅의 Discord 쪽(IMPL-PLAN-8 §10-2): 만들기·보고·실패 시 정리·삭제."""

import json

import httpx

from discord_service.core_client import CoreClient
from discord_service.discord import Bot
from discord_service.github_hooks import run_github_hooks

TOKEN = "webhook-token-abcdefghijklmnopqrstuvwxyz"


def _pair(jobs, created_reply=None, discord_status=200):
    calls = []

    def core(req: httpx.Request):
        calls.append(("core", req.method, req.url.path, req.content.decode()))
        if req.url.path.endswith("/github-hooks"):
            return httpx.Response(200, json=jobs)
        if req.url.path.endswith("/created"):
            return httpx.Response(200, json=created_reply or {"ok": True, "delete_webhook": False})
        return httpx.Response(200, json={"ok": True})

    def discord(req: httpx.Request):
        calls.append(("discord", req.method, req.url.path, req.content.decode()))
        if req.method == "POST" and discord_status != 200:
            return httpx.Response(
                discord_status, json={"message": "Missing Permissions", "code": 50013}
            )
        if req.method == "POST":
            return httpx.Response(200, json={"id": "777", "token": TOKEN})
        return httpx.Response(204)

    c = CoreClient("http://core", "t", transport=httpx.MockTransport(core))
    b = Bot("bot", transport=httpx.MockTransport(discord), sleep=lambda s: None)
    return c, b, calls


def test_create_reports_id_and_token_to_core_only():
    c, b, calls = _pair(
        [{"project_id": 5, "action": "create", "channel_id": "555", "webhook_id": ""}]
    )
    assert run_github_hooks(c, b) == 1
    assert ("discord", "POST", "/api/v10/channels/555/webhooks", '{"name":"GitHub"}') in calls
    created = [x for x in calls if x[2].endswith("/github-hooks/5/created")]
    assert json.loads(created[0][3]) == {"webhook_id": "777", "webhook_token": TOKEN}
    assert not any(x[0] == "discord" and x[1] == "DELETE" for x in calls)


def test_core_refusal_deletes_the_new_webhook():
    c, b, calls = _pair(
        [{"project_id": 5, "action": "create", "channel_id": "555", "webhook_id": ""}],
        created_reply={"ok": False, "delete_webhook": True},
    )
    run_github_hooks(c, b)
    assert ("discord", "DELETE", "/api/v10/webhooks/777", "") in calls


def test_missing_permission_is_reported_as_failed():
    c, b, calls = _pair(
        [{"project_id": 5, "action": "create", "channel_id": "555", "webhook_id": ""}],
        discord_status=403,
    )
    run_github_hooks(c, b)
    failed = [x for x in calls if x[2].endswith("/github-hooks/5/failed")]
    assert "50013" in json.loads(failed[0][3])["reason"]


def test_delete_removes_webhook_then_reports():
    c, b, calls = _pair(
        [{"project_id": 5, "action": "delete", "channel_id": "555", "webhook_id": "777"}]
    )
    run_github_hooks(c, b)
    paths = [x[2] for x in calls]
    assert paths.index("/api/v10/webhooks/777") < paths.index(
        "/api/integrations/discord/github-hooks/5/removed"
    )
