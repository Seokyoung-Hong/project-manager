import time

from django.core.management import call_command
from django.core.management.base import BaseCommand
from django.db import close_old_connections

from assist import worker as assist_worker

# (명령, 주기 초). 기동하자마자 한 번씩 돌고, 그 뒤 주기마다 돈다.
# ponytail: sleep 루프라 정시가 아니고 실패 알림이 없다(로그만). 필요하면 cron이나 전용 스케줄러로.
JOBS = [("github_reconcile", 300), ("purge_expired", 86400)]
TICK = 30


def run_due(last: dict, now: float, stderr) -> None:
    """주기가 된 작업을 돌린다. 한 작업이 실패해도 다음 작업과 루프는 계속한다."""
    for name, every in JOBS:
        if name in last and now - last[name] < every:
            continue
        last[name] = now  # 실패해도 다음 주기에 다시(매 틱 재시도로 몰아치지 않는다)
        try:
            call_command(name)
        except Exception as e:  # noqa: BLE001 — 루프를 살리는 게 목적이다
            stderr.write(f"{name} 실패: {e!r}")
        finally:
            close_old_connections()  # 끊긴 DB 연결을 들고 다음 회차로 가지 않는다


class Command(BaseCommand):
    help = "주기 작업 실행기: github_reconcile 5분, purge_expired 하루."

    def handle(self, *args, **options):
        assist_worker.start()  # AI 워커 스레드(IMPL-PLAN-12 §4.1)
        last = {}
        while True:
            run_due(last, time.monotonic(), self.stderr)
            time.sleep(TICK)
