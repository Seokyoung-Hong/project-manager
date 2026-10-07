"""실시간 푸시(SSE). 남이 고친 태스크가 내 화면에도 곧바로 반영되게 한다.

브라우저는 `EventSource`로 이 주소를 열어 두고, 서버는 내 조직에서 방금 바뀐 태스크의
id를 흘려보낸다. 클라이언트(app.js)가 그것을 기존 HTMX 이벤트(task-changed·task-updated)로
바꿔 쏘면, 이미 그 이벤트를 듣고 있는 행·패널·오늘 목록이 스스로 새로고침한다.
즉 템플릿은 하나도 바뀌지 않는다 — 이 파일과 app.js 몇 줄이 실시간의 전부다.

한 연결은 STREAM_SECONDS 뒤 스스로 닫는다. EventSource가 알아서 다시 붙으므로 끊김은
사용자에게 보이지 않고, 대신 죽은 스레드·프록시 유휴 종료·배포 후 낡은 연결이 쌓이지 않는다.

연결 하나가 gthread 스레드 하나를 붙잡으므로 상한을 둔다(IMPL-PLAN-7 H). 사용자당
MAX_STREAMS_PER_USER개, 워커 전체 MAX_STREAMS개를 넘으면 `retry: 30000`만 보내고 바로 닫는다 —
브라우저는 30초 뒤에 다시 붙고, 그동안 그 탭은 새로고침해야 남의 변경을 본다. 스레드가 남아야
페이지 요청이 멈추지 않는다.
"""

import json
import threading
import time
from collections import Counter

from django.contrib.auth.decorators import login_required
from django.db import connection
from django.http import StreamingHttpResponse
from django.utils import timezone

from tasks.models import Task
from tasks.services import visible_tasks

from .common import current_org

POLL_SECONDS = 2  # 변경을 확인하는 주기
STREAM_SECONDS = 50  # gunicorn --timeout(60)보다 짧게 잡아 연결을 먼저 닫는다
HEARTBEAT_SECONDS = 15  # 프록시가 유휴로 보고 끊지 않게 주석 한 줄을 보낸다
# ponytail: 상한은 워커(프로세스)마다 센다. 워커가 2개면 한 사람이 최대 2×3개를 연다.
# 정확히 세야 하면 캐시(Redis)로 옮기거나 SSE를 비동기 워커로 분리한다.
MAX_STREAMS_PER_USER = 3
MAX_STREAMS = 24  # entrypoint.sh --threads 32 중 페이지 요청 몫 8개를 남긴다
BUSY_RETRY_MS = 30000

_active: Counter = Counter()  # user_id → 열린 스트림 수
_lock = threading.Lock()


def _acquire(user_id) -> bool:
    with _lock:
        if _active[user_id] >= MAX_STREAMS_PER_USER or sum(_active.values()) >= MAX_STREAMS:
            return False
        _active[user_id] += 1
        return True


def _release(user_id):
    with _lock:
        _active[user_id] -= 1
        if _active[user_id] <= 0:
            del _active[user_id]


def _changed_since(org, since, user=None):
    """org의 태스크 중 since 이후에 바뀐 것. user를 주면 그 사람이 볼 수 있는 프로젝트만 —
    비공개 프로젝트 태스크의 번호·수정 시각을 못 보는 멤버에게 흘리지 않는다.

    # ponytail: updated_at 순차 조회. ChangeLog는 본문 텍스트 자동 저장을 기록하지 않으므로
    # 그쪽을 피드로 쓰면 메모 편집이 상대 화면에 안 보인다. 팀 규모가 커져 이 질의가 무거워지면
    # updated_at에 인덱스를 두거나 Postgres LISTEN/NOTIFY로 바꾼다.
    """
    qs = Task.objects.filter(project__org=org, updated_at__gt=since)
    if user is not None:
        # 열람 = 주 ∪ 확정 연결(visible_tasks). 연결·승인이 updated_at을 올려 새 열람자에게도 바로 간다.
        qs = visible_tasks(user).filter(project__org=org, updated_at__gt=since)
    return list(qs.order_by("updated_at").values_list("pk", "updated_at")[:50])


def _stream(user, org, since):
    # 생성기 안에서 자리를 잡아야 닫힐 때(finally) 반드시 돌려준다.
    # 시작도 안 된 생성기는 close()해도 finally가 돌지 않는다.
    if not _acquire(user.pk):
        yield f"retry: {BUSY_RETRY_MS}\n\n"
        return
    try:
        yield from _feed(user, org, since)
    finally:
        _release(user.pk)


def _feed(user, org, since):
    started = time.monotonic()
    last_beat = started
    # 재연결 간격을 브라우저에 알려 둔다(기본값은 3초로 제각각이다).
    yield f"retry: {POLL_SECONDS * 1000}\n\n"
    while time.monotonic() - started < STREAM_SECONDS:
        rows = _changed_since(org, since, user)
        # 스트림이 사는 동안 DB 연결을 붙잡고 있지 않는다 — 보는 사람 수만큼 연결이 늘어난다.
        connection.close()
        if rows:
            since = rows[-1][1]
            for pk, _ in rows:
                yield f"data: {json.dumps({'id': pk})}\n\n"
            last_beat = time.monotonic()
        elif time.monotonic() - last_beat > HEARTBEAT_SECONDS:
            yield ": keepalive\n\n"
            last_beat = time.monotonic()
        time.sleep(POLL_SECONDS)


@login_required
def events(request):
    org = current_org(request)
    if org is None:
        # 조직이 없으면 보낼 것도 없다. 빈 스트림을 바로 닫는다.
        return StreamingHttpResponse(iter([": no org\n\n"]), content_type="text/event-stream")
    response = StreamingHttpResponse(
        _stream(request.user, org, timezone.now()), content_type="text/event-stream"
    )
    response["Cache-Control"] = "no-cache"
    response["X-Accel-Buffering"] = "no"  # nginx/NPM이 스트림을 버퍼링하지 않게
    return response
