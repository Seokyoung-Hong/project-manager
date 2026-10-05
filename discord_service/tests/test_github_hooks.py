"""GitHub 알림 웹훅의 Discord 쪽(IMPL-PLAN-8 §10-2): 만들기·보고·재보고·삭제."""

import json

import httpx

from discord_service.core_client import CoreClient
from discord_service.discord import Bot
from discord_service.github_hooks import run_github_hooks

TOKEN = "webhook-token-abcdefghijklmnopqrstuvwxyz"
CREATE = {"project_id": 5, "action": "create", "job": "j1", "channel_id": "555", "webhook_id": ""}


def _pair(jobs, created=None, discord_status=200):
    """created: /created 응답들의 목록. 예외 객체면 그 요청을 실패시킨다(응답 유실)."""
    calls = []
    replies = list(created or [{"ok": True, "delete_webhook": False}])

    def core(req: httpx.Request):
        calls.append(("core", req.method, req.url.path, req.content.decode()))
        if req.url.path.endswith("/github-hooks"):
            return httpx.Response(200, json=jobs)
        if req.url.path.endswith("/created"):
            reply = replies.pop(0) if len(replies) > 1 else replies[0]
            if isinstance(reply, Exception):
                raise httpx.ReadTimeout("lost", request=req)
            return httpx.Response(200, json=reply)
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


def _created(calls):
    return [json.loads(x[3]) for x in calls if x[2].endswith("/github-hooks/5/created")]


def test_create_reports_job_id_and_token_to_core_only():
    c, b, calls = _pair([CREATE])
    assert run_github_hooks(c, b, {}) == 1
    assert ("discord", "POST", "/api/v10/channels/555/webhooks", '{"name":"GitHub"}') in calls
    assert _created(calls) == [{"job": "j1", "webhook_id": "777", "webhook_token": TOKEN}]
    assert not any(x[0] == "discord" and x[1] == "DELETE" for x in calls)


def test_lost_response_keeps_webhook_and_rereports_same_job_next_tick():
    pending: dict = {}
    c, b, calls = _pair([CREATE], created=[RuntimeError(), {"ok": True, "delete_webhook": False}])
    run_github_hooks(c, b, pending)
    assert not any(x[1] == "DELETE" for x in calls)  # 실패로 보여도 지우지 않는다
    assert "j1" in pending
    run_github_hooks(c, b, pending)  # 다음 틱: 새로 만들지 않고 같은 job으로 다시 보고
    assert sum(x[0] == "discord" and x[1] == "POST" for x in calls) == 1
    assert len(_created(calls)) == 2 and _created(calls)[0] == _created(calls)[1]
    assert pending == {}


def test_unreported_webhook_of_cancelled_job_is_still_reported():
    """취소돼 작업 목록에서 빠져도 보고해야 core가 정리 목록에 올린다."""
    pending = {"j0": {"project_id": 5, "id": "777", "token": TOKEN}}
    c, b, calls = _pair([], created=[{"ok": False, "delete_webhook": False}])
    run_github_hooks(c, b, pending)
    assert _created(calls)[0]["job"] == "j0" and pending == {}
    assert not any(x[1] == "DELETE" for x in calls)


def test_bot_deletes_only_when_core_has_nowhere_to_keep_cleanup():
    c, b, calls = _pair([CREATE], created=[{"ok": False, "delete_webhook": True}])
    run_github_hooks(c, b, {})
    assert ("discord", "DELETE", "/api/v10/webhooks/777", "") in calls


def test_missing_permission_is_reported_as_failed_with_job():
    c, b, calls = _pair([CREATE], discord_status=403)
    run_github_hooks(c, b, {})
    failed = [json.loads(x[3]) for x in calls if x[2].endswith("/github-hooks/5/failed")]
    assert failed[0]["job"] == "j1" and "50013" in failed[0]["reason"]


def test_delete_removes_webhook_then_reports_its_id():
    c, b, calls = _pair(
        [{"project_id": 5, "action": "delete", "job": "", "channel_id": "", "webhook_id": "777"}]
    )
    run_github_hooks(c, b, {})
    paths = [x[2] for x in calls]
    removed = "/api/integrations/discord/github-hooks/5/removed"
    assert paths.index("/api/v10/webhooks/777") < paths.index(removed)
    assert json.loads(next(x[3] for x in calls if x[2] == removed)) == {"webhook_id": "777"}
