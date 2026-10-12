"""실시간: 키 사전 완결(SQLite) + 허브 버퍼·디바운스 + Postgres 트리거·WebSocket·폴링 종단 시험(pg 묶음).

pg 묶음 실행: Postgres를 띄우고 DATABASE_URL=postgres://… pytest -m pg web/realtime
"""

import asyncio
import json
import socket
import threading
import time
import urllib.request

import pytest
from django.apps import apps

from web.realtime import hub as hubmod
from web.realtime.keys import AUTH, KEYS, ignored


def test_dictionary_covers_every_table():
    """새 표가 생기면 사전(KEYS·AUTH)이나 무시 목록에 넣어야 한다."""
    tables = {m._meta.db_table for m in apps.get_models(include_auto_created=True)}
    covered = set(KEYS) | set(AUTH)
    assert tables - covered - {t for t in tables if ignored(t)} == set()
    assert covered - tables == set()  # 오타·지운 표
    assert {t for t in covered if ignored(t)} == set()


def test_hub_replay_and_debounce(monkeypatch):
    monkeypatch.setattr(hubmod, "BUFFER", 3)
    h = hubmod.Hub()
    start = h.seq
    h.on_notify("T:1|checklist")
    h.on_notify("T:1|checklist")  # 1초 안 같은 키 → 보류
    assert [e["key"] for e in h.buf] == ["T:1"] and ("T:1", "checklist") in h.pending
    for i in range(2, 6):
        h.on_notify(f"T:{i}|")
    assert h.replay(start, {"T:1"}) is None  # T:1이 밀려나 버퍼 밖
    assert [e["key"] for e in h.replay(h.seq - 2, {"T:4", "T:5", "T:9"})] == ["T:4", "T:5"]
    assert h.replay(h.seq + 5, set()) is None  # 다른(이후) 프로세스의 seq


# ---------------- Postgres ----------------


def _notifies(conn, seconds=1.0):
    return {n.payload for n in conn.notifies(timeout=seconds)}


@pytest.fixture
def listener(db):
    import psycopg

    with psycopg.connect(**hubmod.conninfo(), autocommit=True) as c:
        c.execute("LISTEN udally_rt")
        yield c


@pytest.mark.pg
@pytest.mark.django_db(transaction=True)
def test_triggers_emit_keys(pg_flushable, listener, client, task, member, admin, project):
    from django.contrib.auth.hashers import make_password

    from projects.services import create_project
    from tasks.models import ChecklistItem, Task

    _notifies(listener, 0.2)
    ChecklistItem.objects.create(task=task, text="a")
    other = create_project(org=project.org, name="다른", actor=admin, owners=[admin])
    _notifies(listener, 0.5)
    Task.objects.filter(pk=task.pk).update(project=other, assignee=admin)
    got = _notifies(listener)
    assert {
        f"T:{task.pk}|head",
        f"P:{project.pk}|",
        f"P:{other.pk}|",
        f"U:{admin.pk}|",
        "A|",
    } <= got

    client.force_login(member)
    import hashlib

    h = hashlib.sha256(client.cookies["sessionid"].value.encode()).hexdigest()[:16]
    _notifies(listener, 0.2)
    client.logout()
    assert f"S:{h}|" in _notifies(listener)
    type(member).objects.filter(pk=member.pk).update(password=make_password("새비밀번호123"))
    assert f"X:U:{member.pk}|" in _notifies(listener)


@pytest.fixture
def rt_server(db):
    """realtime 앱(config.rt_asgi)을 이 프로세스의 스레드에서 띄운다. psycopg 비동기는 Selector 루프가 필요하다."""
    import uvicorn

    from config.rt_asgi import app

    with socket.socket() as s:
        s.bind(("127.0.0.1", 0))
        port = s.getsockname()[1]
    server = uvicorn.Server(uvicorn.Config(app, host="127.0.0.1", port=port, log_level="warning"))
    t = threading.Thread(
        target=lambda: asyncio.run(server.serve(), loop_factory=asyncio.SelectorEventLoop),
        daemon=True,
    )
    t.start()
    for _ in range(100):
        if server.started and hubmod.hub.running:
            break
        time.sleep(0.05)
    time.sleep(0.5)  # LISTEN이 붙을 시간
    yield f"127.0.0.1:{port}"
    server.should_exit = True
    t.join(10)
    # 서버 스레드(sync_to_async 실행기)가 잡고 있던 DB 연결을 끊어야 테스트 DB를 지울 수 있다.
    from django.db import connection

    with connection.cursor() as c:
        c.execute(
            "SELECT pg_terminate_backend(pid) FROM pg_stat_activity "
            "WHERE datname = current_database() AND pid <> pg_backend_pid()"
        )


def _ws(addr, client, origin=None):
    from websockets.sync.client import connect

    return connect(
        f"ws://{addr}/rt/ws",
        additional_headers={
            "Cookie": f"sessionid={client.cookies['sessionid'].value}",
            "Origin": origin or f"http://{addr}",
        },
        open_timeout=5,
    )


def _recv_until(ws, pred, timeout=5.0):
    end = time.monotonic() + timeout
    while True:
        msg = json.loads(ws.recv(timeout=max(end - time.monotonic(), 0.01)))
        if pred(msg):
            return msg


@pytest.mark.pg
@pytest.mark.django_db(transaction=True)
def test_ws_subscribe_event_denied_recheck_logout(
    pg_flushable, rt_server, client, member, admin, org, project, task
):
    from websockets.exceptions import ConnectionClosed, InvalidStatus

    from projects.models import Project
    from projects.services import create_project
    from tasks.models import ChecklistItem
    from tasks.services import create_task

    secret = create_project(org=org, name="비공개", actor=admin, owners=[admin], visibility="teams")
    hidden = create_task(
        project=secret, title="숨김", actor=admin, source="web", due_date=task.due_date
    )
    client.force_login(member)

    with pytest.raises(InvalidStatus):  # 다른 사이트에서 연 연결(CSWSH)
        _ws(rt_server, client, origin="https://evil.example").close()

    with _ws(rt_server, client) as ws:
        keys = [
            f"T:{task.pk}",
            f"U:{member.pk}",
            f"P:{project.pk}",
            f"T:{hidden.pk}",
            f"U:{admin.pk}",
        ]
        ws.send(json.dumps({"op": "sub", "keys": keys}))
        denied = _recv_until(ws, lambda m: m.get("op") == "denied")
        assert denied["keys"] == sorted([f"T:{hidden.pk}", f"U:{admin.pk}"])

        ChecklistItem.objects.create(task=task, text="다른 연결에서 쓰기")
        ev = _recv_until(ws, lambda m: m.get("key") == f"T:{task.pk}")
        assert ev["section"] == "checklist" and ev["seq"] > 0

        # 권한 바뀜(A) → 1초 뒤 전체 재검사 → 볼 수 없게 된 키는 denied
        Project.objects.filter(pk=project.pk).update(visibility="teams")
        lost = _recv_until(ws, lambda m: m.get("op") == "denied")
        assert lost["keys"] == sorted([f"P:{project.pk}", f"T:{task.pk}"])

        client.logout()
        assert _recv_until(ws, lambda m: "op" in m)["op"] == "logout"
        with pytest.raises(ConnectionClosed):
            ws.recv(timeout=5)
    assert not hubmod.hub.conns


@pytest.mark.pg
@pytest.mark.django_db(transaction=True)
def test_poll_and_subscribe(pg_flushable, rt_server, client, member, task):
    from tasks.models import ChecklistItem

    client.force_login(member)
    csrf = "a" * 32
    cookie = f"sessionid={client.cookies['sessionid'].value}; csrftoken={csrf}"

    def call(path, body=None):
        req = urllib.request.Request(
            f"http://{rt_server}{path}",
            data=json.dumps(body).encode() if body is not None else None,
            headers={"Cookie": cookie, "X-CSRFToken": csrf, "Content-Type": "application/json"},
        )
        with urllib.request.urlopen(req, timeout=5) as r:
            return json.loads(r.read())

    since = hubmod.hub.seq
    ChecklistItem.objects.create(task=task, text="구독 전 쓰기")
    time.sleep(0.5)
    # 첫 폴링(stream 없음): 구독 전이라 since를 그대로 돌려준다 → 구독 뒤 다음 폴링이 재생한다
    first = call(f"/rt/poll?since={since}")
    stream = first["stream"]
    assert first["seq"] == since and first["events"] == []
    assert call("/rt/subscribe", {"stream": stream, "keys": [f"T:{task.pk}", "T:999999"]}) == {
        "denied": ["T:999999"]
    }
    got = call(f"/rt/poll?stream={stream}&since={first['seq']}")
    assert [(e["key"], e["section"]) for e in got["events"]] == [(f"T:{task.pk}", "checklist")]
    assert call(f"/rt/poll?stream={stream}&since=1")["op"] == "resync"

    # SSE: 첫 이벤트로 stream id → 구독 → since 이후 이벤트를 그 구독으로 걸러 받는다
    req = urllib.request.Request(
        f"http://{rt_server}/rt/sse?since={since}", headers={"Cookie": cookie}
    )
    with urllib.request.urlopen(req, timeout=5) as r:
        assert r.headers["X-Accel-Buffering"] == "no"
        line = r.readline().decode()
        hello = json.loads(line.removeprefix("data: "))
        assert hello["op"] == "stream"
        call("/rt/subscribe", {"stream": hello["stream"], "keys": [f"T:{task.pk}"]})
        while not (line := r.readline().decode()).startswith("data:"):
            pass
        assert json.loads(line.removeprefix("data: "))["key"] == f"T:{task.pk}"
