"""실시간 허브(설계 DESIGN-v2 1·2·3절). realtime 프로세스(uvicorn 1개) 안에서만 돈다.

- Postgres `LISTEN udally_rt` 연결 하나로 알림을 받는다. 끊기면 다시 붙고, 붙은 직후 모든 연결에 resync.
- 이벤트 `{seq, key, section}`을 최근 BUFFER개 고리 버퍼에 둔다. seq는 부팅 시각(ms)에서 시작해
  프로세스가 바뀌면 옛 seq가 버퍼 밖이 되어 resync로 처리된다(부팅 id를 따로 두지 않는다).
- 같은 (키, 섹션)은 1초에 한 번만 보낸다(첫 번째는 바로, 나머지는 1초 끝에 하나로).
- 구독 검사: T=visible_tasks, P=visible_projects, U=본인, O=조직 멤버. `A`가 오면 1초 묶어 전체 재검사.
- `S:<해시>` = 그 세션의 연결을 logout 후 끊음. `X:U:<id>` = 그 사람 연결의 세션을 재인증해 무효면 끊음.
"""

import asyncio
import hashlib
import json
import logging
import os
import re
import secrets
import time
from collections import deque
from http.cookies import SimpleCookie
from importlib import import_module
from urllib.parse import parse_qs, urlsplit

import psycopg
from asgiref.sync import sync_to_async
from django.conf import settings
from django.db import close_old_connections, connections
from django.http.request import split_domain_port, validate_host

from .keys import CHANNEL

log = logging.getLogger("udally.rt")

KEY_RE = re.compile(r"^[TPUO]:[1-9]\d{0,17}$")
BUFFER = 2000
DEBOUNCE = 1.0
TICK = 0.25
MAX_PER_USER = 6
MAX_TOTAL = int(os.environ.get("RT_MAX_CONNECTIONS", "2000"))
MAX_KEYS = 500
QUEUE = 1000
IDLE_STREAM = 120  # 소비자가 붙어 있지 않은 SSE·폴링 stream을 남겨 두는 시간(초)
REAUTH = 60  # 모든 연결의 세션을 다시 확인하는 주기(초). 만료 세션은 늦어도 이만큼 뒤에 끊긴다.


def skey_hash(session_key: str) -> str:
    return hashlib.sha256(session_key.encode()).hexdigest()[:16]


# ---------- 동기(DB) 도우미: sync_to_async로 부른다 ----------


def session_user_id(session_key: str | None) -> int | None:
    """세션 키로 로그인 사용자 id. 세션 행·인증 해시(비밀번호)·is_active까지 Django가 확인한다."""
    if not session_key:
        return None
    close_old_connections()
    from django.contrib.auth import get_user
    from django.http import HttpRequest

    req = HttpRequest()
    req.session = import_module(settings.SESSION_ENGINE).SessionStore(session_key)
    user = get_user(req)
    return user.pk if user.is_authenticated else None


def allowed(user_id: int, keys) -> set[str]:
    """keys 중 user가 볼 수 있는 것."""
    close_old_connections()
    from accounts.models import User
    from orgs.models import OrgMembership
    from projects.services import visible_projects
    from tasks.services import visible_tasks

    user = User.objects.filter(pk=user_id, is_active=True).first()
    if user is None:
        return set()
    ids: dict[str, set[int]] = {"T": set(), "P": set(), "U": set(), "O": set()}
    for k in keys:
        kind, _, n = k.partition(":")
        ids[kind].add(int(n))
    ok = {f"U:{user_id}"} if user_id in ids["U"] else set()
    if ids["T"]:
        qs = visible_tasks(user).filter(pk__in=ids["T"]).values_list("pk", flat=True)
        ok |= {f"T:{i}" for i in qs}
    if ids["P"]:
        qs = visible_projects(user).filter(pk__in=ids["P"]).values_list("pk", flat=True)
        ok |= {f"P:{i}" for i in qs}
    if ids["O"]:
        qs = OrgMembership.objects.filter(user=user, org_id__in=ids["O"]).values_list(
            "org_id", flat=True
        )
        ok |= {f"O:{i}" for i in qs}
    return ok


def conninfo() -> dict:
    s = connections["default"].settings_dict
    kw = {"dbname": s["NAME"], "user": s["USER"], "password": s["PASSWORD"], "host": s["HOST"]}
    kw = {k: v for k, v in kw.items() if v}
    if s.get("PORT"):
        kw["port"] = s["PORT"]
    # 반쯤 끊긴 TCP에서 notifies()가, 응답 없는 DB에서 connect()가 영영 기다리지 않게 한다.
    return kw | {
        "connect_timeout": 10,
        "keepalives": 1,
        "keepalives_idle": 30,
        "keepalives_interval": 10,
        "keepalives_count": 3,
    }


# ---------- 연결 ----------


class Conn:
    """WebSocket 연결 하나, 또는 SSE·폴링 stream 하나."""

    def __init__(self, user_id: int, session_key: str, kind: str):
        self.id = secrets.token_urlsafe(16)
        self.user_id = user_id
        self.session_key = session_key
        self.shash = skey_hash(session_key)
        self.kind = kind  # ws | sse | poll
        self.keys: set[str] = set()
        self.queue: asyncio.Queue = asyncio.Queue(QUEUE)
        # 이벤트를 큐로 받는 소비자가 붙어 있나(폴링·끊긴 SSE는 버퍼에서 재생)
        self.live = kind == "ws"
        self.seen = time.monotonic()
        self.closed = False
        self.since: int | None = None  # SSE 새 stream: 첫 구독 뒤 재생할 seq

    def push(self, msg: dict) -> None:
        try:
            self.queue.put_nowait(msg)
        except asyncio.QueueFull:  # 못 따라오면 비우고 resync 하나로 대신한다
            while not self.queue.empty():
                self.queue.get_nowait()
            self.queue.put_nowait({"op": "resync"})


class Hub:
    def __init__(self):
        self.seq = self.floor = int(time.time() * 1000)
        self.buf: deque = deque(maxlen=BUFFER)
        self.conns: dict[str, Conn] = {}
        self.last_sent: dict[tuple, float] = {}
        self.pending: dict[tuple, float] = {}
        self.auth_due: float | None = None
        self.running = False
        self._tasks: list[asyncio.Task] = []

    # --- 연결 관리 ---
    def add(self, conn: Conn) -> bool:
        mine = [c for c in self.conns.values() if c.user_id == conn.user_id]
        if len(mine) >= MAX_PER_USER:
            # 페이지 이동·새로고침마다 새 stream이 생기고 옛 것은 IDLE_STREAM 동안 남는다:
            # 소비자가 없는 가장 오래된 것을 비운다(아직 쓰는 폴링이면 다음 폴링이 새 stream을 받는다)
            idle = [c for c in mine if not c.live]
            if not idle:
                return False
            self.remove(min(idle, key=lambda c: c.seen))
        if len(self.conns) >= MAX_TOTAL:
            return False
        self.conns[conn.id] = conn
        return True

    def remove(self, conn: Conn) -> None:
        self.conns.pop(conn.id, None)

    def kick(self, conn: Conn) -> None:
        """세션이 끝났다: logout을 보내고 끊는다(소비자가 없으면 지우기만 — 다음 요청이 401 logout)."""
        conn.closed = True
        self.remove(conn)
        while not conn.queue.empty():
            conn.queue.get_nowait()
        conn.queue.put_nowait({"op": "logout"})

    async def subscribe(self, conn: Conn, keys) -> list[str]:
        """구독을 더하고 거절된 키를 돌려준다."""
        keys = [k for k in keys if isinstance(k, str)][:MAX_KEYS]
        want = {k for k in keys if KEY_RE.match(k)}
        room = MAX_KEYS - len(conn.keys - want)
        want = set(sorted(want)[: max(room, 0)])
        ok = await sync_to_async(allowed)(conn.user_id, want) if want else set()
        conn.keys |= ok
        return sorted(set(keys) - ok)

    # --- 이벤트 ---
    def replay(self, since: int, keys) -> list[dict] | None:
        """since 뒤 이벤트 중 keys 것. 버퍼 밖이면(또는 다른 프로세스의 seq면) None = resync."""
        if since < self.floor or since > self.seq:
            return None
        return [e for e in self.buf if e["seq"] > since and e["key"] in keys]

    def publish(self, ks: tuple) -> None:
        self.last_sent[ks] = time.monotonic()
        if len(self.buf) == BUFFER:
            self.floor = self.buf[0]["seq"]
        self.seq += 1
        ev = {"seq": self.seq, "key": ks[0], "section": ks[1]}
        self.buf.append(ev)
        # ponytail: 이벤트마다 연결 전체를 훑는다(상한 2000). 느려지면 키 → 연결 색인을 둔다.
        for c in self.conns.values():
            if c.live and ks[0] in c.keys:
                c.push(ev)

    def on_notify(self, payload: str) -> None:
        key, _, section = payload.partition("|")
        if key == "A":
            if self.auth_due is None:
                self.auth_due = time.monotonic() + DEBOUNCE
        elif key.startswith("S:"):
            for c in [c for c in self.conns.values() if c.shash == key[2:]]:
                self.kick(c)
        elif key.startswith("X:U:"):
            self._spawn(self.reauth(int(key[4:])))
        else:
            ks = (key, section or None)
            last = self.last_sent.get(ks)
            if last is None or time.monotonic() - last >= DEBOUNCE:
                self.publish(ks)
            else:
                self.pending.setdefault(ks, last + DEBOUNCE)

    def reset(self) -> None:
        """LISTEN이 끊겼다 붙었다: 그사이 놓친 게 있을 수 있으니 버퍼를 비우고 모두 resync.
        놓친 것에는 로그아웃(S)·권한 회수(A)도 있다 → 세션 재인증·권한 재검사를 먼저 돌린다."""
        self.buf.clear()
        self.seq += 1
        self.floor = self.seq
        self._spawn(self.reauth())
        self._spawn(self.recheck_all())
        for c in self.conns.values():
            if c.live:
                c.push({"op": "resync"})

    async def reauth(self, user_id: int | None = None) -> None:
        """세션이 무효(로그아웃·만료·비밀번호 변경)인 연결을 끊는다. user_id가 없으면 전부."""
        conns = [c for c in self.conns.values() if user_id is None or c.user_id == user_id]
        valid: dict[str, int | None] = {}  # 한 세션의 여러 연결(탭·stream)은 한 번만 조회
        for c in conns:
            if c.session_key not in valid:
                valid[c.session_key] = await sync_to_async(session_user_id)(c.session_key)
            if valid[c.session_key] != c.user_id:
                self.kick(c)

    async def recheck_all(self) -> None:
        for c in list(self.conns.values()):
            if not c.keys:
                continue
            ok = await sync_to_async(allowed)(c.user_id, set(c.keys))
            lost = c.keys - ok
            if lost:
                c.keys -= lost
                c.push({"op": "denied", "keys": sorted(lost)})

    # --- 백그라운드 ---
    def _spawn(self, coro) -> None:
        t = asyncio.get_running_loop().create_task(coro)
        self._tasks.append(t)
        t.add_done_callback(self._done)

    def _done(self, t: asyncio.Task) -> None:
        if t in self._tasks:
            self._tasks.remove(t)
        if not t.cancelled() and t.exception():
            log.error("realtime 작업 실패", exc_info=t.exception())

    async def tick(self) -> None:
        reauth_at = time.monotonic() + REAUTH
        while True:
            await asyncio.sleep(TICK)
            now = time.monotonic()
            if now >= reauth_at:  # 세션 자연 만료는 행이 남아 S 알림이 없다(정리 작업은 하루 한 번)
                reauth_at = now + REAUTH
                self._spawn(self.reauth())
            for ks in [ks for ks, due in self.pending.items() if due <= now]:
                del self.pending[ks]
                self.publish(ks)
            self.last_sent = {ks: t for ks, t in self.last_sent.items() if now - t < DEBOUNCE}
            if self.auth_due is not None and self.auth_due <= now:
                self.auth_due = None
                self._spawn(self.recheck_all())
            for c in [c for c in self.conns.values() if not c.live and now - c.seen > IDLE_STREAM]:
                self.remove(c)

    async def listen(self) -> None:
        first, delay = True, 1
        while True:
            try:
                db = await psycopg.AsyncConnection.connect(**conninfo(), autocommit=True)
                async with db:
                    await db.execute(f"LISTEN {CHANNEL}")
                    if not first:
                        self.reset()
                    first, delay = False, 1
                    log.info("realtime: LISTEN %s", CHANNEL)
                    async for n in db.notifies():
                        self.on_notify(n.payload)
            except asyncio.CancelledError:
                raise
            except Exception:
                log.exception("realtime: LISTEN 연결 끊김, %s초 뒤 다시", delay)
            await asyncio.sleep(delay)
            delay = min(delay * 2, 30)

    def start(self) -> None:
        self.running = True
        self._spawn(self.listen())
        self._spawn(self.tick())

    async def stop(self) -> None:
        self.running = False
        for t in list(self._tasks):
            t.cancel()
        await asyncio.gather(*self._tasks, return_exceptions=True)


hub = Hub()


# ---------- WebSocket /rt/ws ----------


def origin_ok(origin: str | None, host: str | None) -> bool:
    """CSWSH 막기: Origin이 CSRF_TRUSTED_ORIGINS에 있거나 같은 호스트(장고 CSRF의 같은 출처 규칙)."""
    if not origin or not host:
        return False
    if not validate_host(split_domain_port(host)[0], settings.ALLOWED_HOSTS):
        return False
    return origin in settings.CSRF_TRUSTED_ORIGINS or urlsplit(origin).netloc == host


def _send_json(msg: dict) -> dict:
    return {"type": "websocket.send", "text": json.dumps(msg)}


async def _writer(conn: Conn, send) -> None:
    while True:
        msg = await conn.queue.get()
        await send(_send_json(msg))
        if msg.get("op") == "logout":
            await send({"type": "websocket.close", "code": 4401})
            return


async def ws_endpoint(scope, receive, send) -> None:
    if (await receive())["type"] != "websocket.connect":
        return
    headers = {k.decode("latin-1"): v.decode("latin-1") for k, v in scope["headers"]}
    if not origin_ok(headers.get("origin"), headers.get("host")):
        await send({"type": "websocket.close", "code": 4403})
        return
    cookie = SimpleCookie(headers.get("cookie", ""))
    morsel = cookie.get(settings.SESSION_COOKIE_NAME)
    skey = morsel.value if morsel else None
    uid = await sync_to_async(session_user_id)(skey)
    await send({"type": "websocket.accept"})
    if uid is None:
        await send(_send_json({"op": "logout"}))
        await send({"type": "websocket.close", "code": 4401})
        return
    conn = Conn(uid, skey, "ws")
    if not hub.running or not hub.add(conn):
        await send({"type": "websocket.close", "code": 4429})
        return
    since: int | None = None
    raw = parse_qs(scope.get("query_string", b"").decode()).get("since", [""])[0]
    if raw.isdecimal():
        since = int(raw)
        if hub.replay(since, ()) is None:
            conn.push({"op": "resync"})
            since = None
    writer = asyncio.create_task(_writer(conn, send))
    try:
        while True:
            msg = await receive()
            if msg["type"] == "websocket.disconnect":
                break
            try:
                data = json.loads(msg.get("text") or "")
                op, keys = data.get("op"), data.get("keys") or []
                keys = keys if isinstance(keys, list) else []
            except (ValueError, AttributeError):
                continue
            if op == "ping":
                conn.push({"op": "pong"})
            elif op == "unsub":
                conn.keys -= {k for k in keys if isinstance(k, str)}
            elif op == "sub" and not conn.closed:
                denied = await hub.subscribe(conn, keys)
                if denied:
                    conn.push({"op": "denied", "keys": denied})
                if since is not None:  # 재연결: 구독 검사를 마친 뒤 지금 구독으로 걸러 재생
                    events = hub.replay(since, conn.keys)
                    since = None
                    for e in events if events is not None else [{"op": "resync"}]:
                        conn.push(e)
    finally:
        writer.cancel()
        hub.remove(conn)
