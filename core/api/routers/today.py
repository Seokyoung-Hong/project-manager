from ninja import Router

from tasks.brief import task_brief
from tasks.services import (
    attach_group_visible,
    today_add,
    today_exclude,
    today_reorder,
    today_restore_excluded,
    today_set_auto_pull,
    today_view,
)

from ..context import task_or_404
from ..schemas import ErrorOut, TodayAddIn, TodayOrderIn, TodayOut, TodaySettingsIn

router = Router(tags=["today"])


def _out(user) -> dict:
    v = today_view(user)
    attach_group_visible([*v["items"], v["focus"], *v["done_today"]], user)
    return {
        "date": v["date"],
        "items": [{**task_brief(t), "auto_pulled": t.auto_pulled} for t in v["items"]],
        "focus": task_brief(v["focus"]) if v["focus"] else None,
        "done_today": [task_brief(t) for t in v["done_today"]],
        "auto_pull_days": v["auto_pull_days"],
        "counts": v["counts"],
    }


@router.get("", response=TodayOut)
def get_today(request):
    return _out(request.auth)


@router.post("", response=TodayOut)
def add(request, payload: TodayAddIn):
    today_add(request.auth, task_or_404(request, payload.task_id))
    return _out(request.auth)


@router.delete("/excluded", response=TodayOut)
def restore(request):
    today_restore_excluded(request.auth)
    return _out(request.auth)


@router.patch("/order", response=TodayOut)
def order(request, payload: TodayOrderIn):
    today_reorder(request.auth, payload.task_ids)
    return _out(request.auth)


@router.patch("/settings", response={200: TodayOut, 400: ErrorOut})
def settings_ep(request, payload: TodaySettingsIn):
    today_set_auto_pull(request.auth, payload.auto_pull_days)
    return _out(request.auth)


# 고정 경로(/excluded, /order, /settings)를 /{task_id}보다 먼저 등록한다.
# django-ninja는 int 변환기를 붙이지 않으므로 순서가 곧 우선순위다.
@router.delete("/{task_id}", response=TodayOut)
def exclude(request, task_id: int):
    today_exclude(request.auth, task_or_404(request, task_id))
    return _out(request.auth)
