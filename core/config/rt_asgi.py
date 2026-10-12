"""realtime 컨테이너의 진입점: `uvicorn config.rt_asgi:app --workers 1`.

WebSocket(/rt/ws)은 허브가 직접 받고, http(/rt/sse·/rt/poll·/rt/subscribe 등)는 Django ASGI로 넘긴다.
허브(LISTEN·tick)는 lifespan에서 켜고 끈다. Channels·Redis는 쓰지 않는다(프로세스 하나가 직접 LISTEN).
"""

import os

os.environ.setdefault("DJANGO_SETTINGS_MODULE", "config.settings")

from django.core.asgi import get_asgi_application  # noqa: E402

django_app = get_asgi_application()

from web.realtime.hub import hub, ws_endpoint  # noqa: E402


async def app(scope, receive, send):
    if scope["type"] == "lifespan":
        while True:
            msg = await receive()
            if msg["type"] == "lifespan.startup":
                hub.start()
                await send({"type": "lifespan.startup.complete"})
            elif msg["type"] == "lifespan.shutdown":
                await hub.stop()
                await send({"type": "lifespan.shutdown.complete"})
                return
    elif scope["type"] == "websocket":
        if scope["path"] == "/rt/ws":
            await ws_endpoint(scope, receive, send)
        else:
            await receive()
            await send({"type": "websocket.close", "code": 4404})
    else:
        await django_app(scope, receive, send)
