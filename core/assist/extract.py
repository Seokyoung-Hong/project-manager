"""태스크 후보(IMPL-PLAN-12 §7.4·§11.2). 몸체는 A 갈래.

job.result(검증된 JSON) = {"tasks": [{"title", "description", "assignee", "due", "project", "evidence",
사후 처리가 붙이는 "assignee_id", "project_id", "similar": [task_id, ...]}]}, 최대 20개.
"""


def create_from_candidates(job, rows: list[dict], actor) -> list:
    """고른 행으로 태스크를 만든다. rows = [{"index", "title", "description", "assignee_id", "due",
    "project_id"}]. 행마다 create_task(idempotency_key=f"assist:{job.pk}:{index}").

    돌려주는 값: 행마다 (index, Task | None, 오류 문구) — 실패한 행만 오류를 보인다.
    """
    raise NotImplementedError
