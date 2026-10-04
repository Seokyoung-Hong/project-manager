"""요청 명령·알림 발송함. core는 가짜 transport, Discord는 FakeBot."""

import json
import re
from datetime import datetime, timedelta, timezone
from types import SimpleNamespace

import discord
import httpx
from conftest import BOT_PREFIX, FakeBot, FakeCore, make_bot, make_core, task
from discord import app_commands
from test_slash import DID, GUILD, FakeInteraction, _cmd, run

from discord_service import slash
from discord_service.scheduler import tick

KST = timezone(timedelta(hours=9))


def req(i=3, status="pending", team=True, to_user=False, kind="work", here=False):
    return {
        "announce_here": here,
        "id": i,
        "number": f"REQ-{i}",
        "kind": kind,
        "kind_label": "작업" if kind == "work" else "일반",
        "title": f"요청 {i}",
        "status": status,
        "status_label": "대기" if status == "pending" else "수락",
        "requested_by": {"id": 1, "display_name": "관리자", "discord_user_id": "9"},
        "team": {"id": 1, "name": "백엔드"} if team else None,
        "to_user": {"id": 2, "display_name": "팀원", "discord_user_id": "111"} if to_user else None,
        "url": f"http://pm/requests/{i}",
    }


class ReqCore(FakeCore):
    def __init__(self):
        super().__init__([task(1, "2026-09-12")])
        self.received, self.sent = [req(3), req(4, "accepted", kind="general")], [req(5)]
        self.notices = [
            {"id": 1, "discord_user_id": "111", "channel_id": "", "text": "DM 알림"},
            {"id": 2, "discord_user_id": None, "channel_id": "777", "text": "채널 알림"},
        ]
        self.acked: list[int] = []
        self.created = None

    def handler(self, request: httpx.Request) -> httpx.Response:
        path = request.url.path.removeprefix(BOT_PREFIX)
        body = json.loads(request.content) if request.content else {}
        if request.method == "GET" and path == "notices":
            return httpx.Response(200, json=self.notices)
        if path == "notices/ack":
            self.acked += body["ids"]
            return httpx.Response(200, json={"acked": len(body["ids"])})
        if path == "requests":
            self.created = body
            return httpx.Response(
                200,
                json={
                    "request": req(
                        7,
                        to_user="to_user_id" in body,
                        team="to_user_id" not in body,
                        here=getattr(self, "here", "to_user_id" not in body),
                    )
                },
            )
        if path == "requests/mine":
            return httpx.Response(200, json={"received": self.received, "sent": self.sent})
        m = re.fullmatch(r"requests/(\d+)/(\w+)", path)
        if m:
            self.calls.append((path, body))
            if m.group(2) == "projects":
                return httpx.Response(200, json=[{"id": 1, "name": "학식 API"}])
            if m.group(2) == "accept":
                t = task(50, body.get("due_date"))
                t["pending_assignee"] = {"id": 2, "display_name": "팀원"}
                return httpx.Response(200, json={"request": req(3, "accepted"), "task": t})
            return httpx.Response(200, json={"request": req(int(m.group(1)), "declined")})
        return super().handler(request)


def _tree(core):
    tree = app_commands.CommandTree(discord.Client(intents=discord.Intents.none()))
    cfg = SimpleNamespace(site_name="x", guild_id="1")
    slash.register(tree, GUILD, cfg, make_core(core), {})
    return tree


def test_core_client_request_methods_hit_the_right_paths():
    core = ReqCore()
    c = make_core(core)
    assert c.create_request(DID, {"title": "t"})["number"] == "REQ-7"
    assert len(c.received_requests(DID)) == 2
    assert c.request_projects(DID, 3) == [{"id": 1, "name": "학식 API"}]
    c.accept_request(DID, 3, {"project_id": 1})
    c.decline_request(DID, 3, "바쁨")
    c.done_request(DID, 4, "끝")
    assert core.paths() == [
        "requests/3/projects",
        "requests/3/accept",
        "requests/3/decline",
        "requests/4/done",
    ]
    assert core.calls[2][1] == {"discord_user_id": DID, "note": "바쁨"}
    assert c.notices()[0]["id"] == 1
    assert c.ack_notices([1, 2]) == {"acked": 2}


def test_team_request_is_confirmed_privately_then_announced_publicly():
    core = ReqCore()
    i = FakeInteraction()
    run(_cmd(_tree(core), "요청").callback(i, title="API 부탁"))
    assert core.created["channel_id"] == "555" and core.created["kind"] == "work"
    assert "team_id" not in core.created
    assert [e for _, e in i.sent] == [True, False]
    assert "/요청수락" in i.sent[1][0] and "REQ-7" in i.sent[1][0]


def test_team_request_from_another_channel_is_not_announced_there():
    core = ReqCore()
    core.here = False  # core가 '이 채널은 받는 팀의 채널이 아니다'라고 답했다
    i = FakeInteraction()
    run(_cmd(_tree(core), "요청").callback(i, title="API 부탁", team=1))
    assert [e for _, e in i.sent] == [True]


def test_request_to_a_person_stays_private():
    core = ReqCore()
    i = FakeInteraction()
    run(_cmd(_tree(core), "요청").callback(i, title="부탁", to_user=2))
    assert core.created["to_user_id"] == 2
    assert [e for _, e in i.sent] == [True]


def test_accept_autocompletes_only_pending_and_projects_by_typed_number():
    core = ReqCore()
    tree = _tree(core)
    i = FakeInteraction()
    names = [c.name for c in run(slash_ac(tree, "요청수락", "번호")(i, ""))]
    assert names == ["REQ-3 요청 3"]
    i.namespace = SimpleNamespace(number=3)
    assert [c.name for c in run(slash_ac(tree, "요청수락", "프로젝트")(i, ""))] == ["학식 API"]
    i.namespace = SimpleNamespace()
    assert run(slash_ac(tree, "요청수락", "프로젝트")(i, "")) == []


def slash_ac(tree, name, param):
    p = next(p for p in _cmd(tree, name)._params.values() if p.display_name == param)
    return p.autocomplete


def test_accept_reply_mentions_pending_assignee_and_bad_date_is_refused():
    core = ReqCore()
    tree = _tree(core)
    i = FakeInteraction()
    run(_cmd(tree, "요청수락").callback(i, number=3, project=1, due="2026-10-01"))
    assert "수락했습니다" in i.reply and "팀원님 수락 대기" in i.reply
    assert core.calls[-1][1]["project_id"] == 1
    j = FakeInteraction()
    run(_cmd(tree, "요청수락").callback(j, number=3, due="내일"))
    assert "날짜" in j.reply


def test_list_decline_done_replies():
    core = ReqCore()
    tree = _tree(core)
    i = FakeInteraction()
    run(_cmd(tree, "요청목록").callback(i))
    assert "받은 요청 2건" in i.reply and "보낸 요청 1건" in i.reply
    i = FakeInteraction()
    run(_cmd(tree, "요청거절").callback(i, number=3, note="바쁨"))
    assert "거절했습니다" in i.reply
    i = FakeInteraction()
    run(_cmd(tree, "요청완료").callback(i, number=4))
    assert "완료로 처리" in i.reply


def _tick(core, bot, store):
    cfg = SimpleNamespace(send_hour=9, weekly_weekday=0, weekly_hour=9, llm_provider="none")
    tick(cfg, make_core(core), bot, store, datetime(2026, 9, 9, 8, tzinfo=KST))


def test_notices_are_delivered_then_acked(store):
    core, fb = ReqCore(), FakeBot()
    _tick(core, make_bot(fb, store), store)
    assert fb.dm("111") == ["DM 알림"] and fb.to("777") == ["채널 알림"]
    assert core.acked == [1, 2]


def test_failed_notice_is_still_acked_and_does_not_block_the_rest(store):
    core, fb = ReqCore(), FakeBot(errors={"dm-111": [(403, {"code": 50007})]})
    _tick(core, make_bot(fb, store), store)
    assert fb.to("777") == ["채널 알림"]
    assert core.acked == [1, 2]


def test_core_down_skips_notices_quietly(store):
    class Down(ReqCore):
        def handler(self, request):
            return httpx.Response(500)

    fb = FakeBot()
    _tick(Down(), make_bot(fb, store), store)
    assert fb.messages == []
