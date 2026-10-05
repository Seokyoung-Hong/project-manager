"""마일스톤·릴리스 동기화. 본문은 G4(IMPL-PLAN-8 §3.9·§3.10).

services가 이 파일을 늦게 import한다(`services._handlers`). 여기서 services를 import해도 순환이 없다.
"""

from .services import record_ignored


def on_milestone(conn, delivery, payload):
    record_ignored(conn, delivery, "milestone", payload)


def on_release(conn, delivery, payload):
    record_ignored(conn, delivery, "release", payload)
