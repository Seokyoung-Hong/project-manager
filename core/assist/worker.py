"""AI 워커(IMPL-PLAN-12 §4.1·§4.3). purge 컨테이너의 run_periodic이 start()를 한 번 부른다. 몸체는 A 갈래.

PC 작업(route="pc")은 집지 않는다 — heartbeat 경로(assist.pc)가 맡는다.
"""


def start() -> None:
    """데몬 스레드 1개(배정 루프 1초 틱, 10초마다 sweep) + ThreadPoolExecutor(settings.ASSIST_WORKERS).

    ASSIST_WORKERS=0이면 아무것도 띄우지 않는다(되돌리기, §4.5).
    """
    raise NotImplementedError


def sweep() -> None:
    """정체 정리(§4.3): running 시간 초과·PC 15초 무응답 → 다음 항목, queued 5분 → failed(no_worker)."""
    raise NotImplementedError
