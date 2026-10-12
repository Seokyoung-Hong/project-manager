"""SSE·폴링 전송(설계 DESIGN-v2 3절 프로토콜). realtime 프로세스(config.rt_asgi)에서만 동작한다.

web(gunicorn)에서는 허브가 없어 503이다. 앞단(NPM)은 /rt/를 realtime으로 보낸다.
- stream id는 첫 요청 때 발급해 첫 메시지 `{"op":"stream","stream":id}`(SSE) 또는 응답의 `stream`(폴링)으로 준다.
  stream은 발급받은 사용자만 쓸 수 있다(다른 사용자가 주면 새 stream을 발급한다).
- 첫 연결의 since는 첫 구독을 받은 뒤 그 구독으로 걸러 재생한다(SSE는 구독 때 밀어 넣고, 폴링은 구독 전까지
  응답 seq를 since 그대로 돌려준다). seq는 정수이고 클라이언트는 그대로 since로 돌려보낸다.
- SSE는 15초마다 `data: {"op":"ping"}`(EventSource는 주석 하트비트를 받지 못한다).
- 세션이 끝났으면 401 `{"op":"logout"}`.
"""

import asyncio
import json
import time

from django.http import HttpResponse, JsonResponse, StreamingHttpResponse
from django.views.decorators.http import require_GET, require_POST

from .hub import Conn, hub

HEARTBEAT = 15


async def _user(request):
    user = await request.auser()
    return user if user.is_authenticated else None


def _stream(request, user, kind: str) -> Conn | None:
    c = hub.conns.get(request.GET.get("stream", ""))
    if c is not None and c.user_id == user.pk and c.kind == kind:
        c.seen = time.monotonic()
        return c
    c = Conn(user.pk, request.session.session_key, kind)
    return c if hub.add(c) else None


def _gate(request):
    if not hub.running:
        return HttpResponse(status=503)
    return None


def _since(raw: str | None) -> int | None:
    return int(raw) if raw and raw.isdecimal() else None


def _sse(msg: dict) -> str:
    head = f"id: {msg['seq']}\n" if "seq" in msg else ""
    return f"{head}data: {json.dumps(msg)}\n\n"


@require_GET
async def sse(request):
    if (r := _gate(request)) is not None:
        return r
    if (user := await _user(request)) is None:
        return JsonResponse({"op": "logout"}, status=401)
    if (c := _stream(request, user, "sse")) is None:
        return HttpResponse(status=429)
    since = _since(request.headers.get("Last-Event-ID") or request.GET.get("since"))

    async def gen():
        c.live = True
        deferred = since is not None and not c.keys
        if deferred:  # 새 stream: 첫 구독(POST /rt/subscribe)을 받은 뒤 그 구독으로 걸러 재생
            c.since = since
        try:
            yield _sse({"op": "stream", "stream": c.id})
            if since is not None and not deferred:
                events = hub.replay(since, c.keys)
                for e in events if events is not None else [{"op": "resync"}]:
                    yield _sse(e)
            while True:
                try:
                    msg = await asyncio.wait_for(c.queue.get(), HEARTBEAT)
                except TimeoutError:  # EventSource는 주석을 못 받으므로 data로 보낸다
                    msg = {"op": "ping"}
                yield _sse(msg)
                if msg.get("op") == "logout":
                    return
        finally:
            c.live = False
            c.seen = time.monotonic()

    resp = StreamingHttpResponse(gen(), content_type="text/event-stream")
    resp["Cache-Control"] = "no-cache"
    resp["X-Accel-Buffering"] = "no"
    return resp


@require_GET
async def poll(request):
    if (r := _gate(request)) is not None:
        return r
    if (user := await _user(request)) is None:
        return JsonResponse({"op": "logout"}, status=401)
    if (c := _stream(request, user, "poll")) is None:
        return HttpResponse(status=429)
    ops = []  # 폴링 stream의 큐에는 제어 메시지(denied·resync)만 쌓인다
    while not c.queue.empty():
        ops.append(c.queue.get_nowait())
    since = _since(request.GET.get("since"))
    body = {"stream": c.id, "seq": hub.seq, "events": ops}
    if since is not None:
        events = hub.replay(since, c.keys)
        if events is None:
            body["op"] = "resync"
        elif not c.keys:
            body["seq"] = (
                since  # 아직 구독 전: since를 그대로 돌려줘 구독 뒤 다음 폴링이 재생하게 한다
            )
        else:
            body["events"] += events
    return JsonResponse(body)


@require_POST
async def subscribe(request):
    """SSE·폴링 stream의 구독 변경. CSRF는 미들웨어가 본다. 본문 {stream, keys, unsub}."""
    if (r := _gate(request)) is not None:
        return r
    if (user := await _user(request)) is None:
        return JsonResponse({"op": "logout"}, status=401)
    try:
        data = json.loads(request.body or b"{}")
        c = hub.conns.get(str(data.get("stream", "")))
        keys, unsub = data.get("keys") or [], data.get("unsub") or []
    except (ValueError, AttributeError):
        return HttpResponse(status=400)
    if c is None or c.user_id != user.pk or c.kind == "ws" or not isinstance(keys, list):
        return JsonResponse({"op": "resync"}, status=404)  # stream이 없어졌다 → 새로 열고 다시 구독
    if isinstance(unsub, list):
        c.keys -= {k for k in unsub if isinstance(k, str)}
    c.seen = time.monotonic()
    denied = await hub.subscribe(c, keys)
    if (
        c.since is not None and c.live
    ):  # 새 SSE stream의 since: 지금 구독으로 걸러 재생(WS 첫 sub와 같다)
        events = hub.replay(c.since, c.keys)
        c.since = None
        for e in events if events is not None else [{"op": "resync"}]:
            c.push(e)
    return JsonResponse({"denied": denied})
