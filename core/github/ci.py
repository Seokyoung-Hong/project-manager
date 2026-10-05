"""CI 상태(check_suite·status) → TaskGitLink 배지. 본문은 G2(IMPL-PLAN-8 §3.6·§3.7).

services가 이 파일을 늦게 import한다(`services._handlers`). 여기서 services를 import해도 순환이 없다.
"""

from .services import record_ignored


def on_check_suite(conn, delivery, payload):
    record_ignored(conn, delivery, "check_suite", payload)


def on_status(conn, delivery, payload):
    record_ignored(conn, delivery, "status", payload)
