from datetime import date, timedelta
from urllib.parse import parse_qs, urlencode, urlparse

from django.contrib.auth.decorators import login_required
from django.db.models import Count
from django.shortcuts import render
from django.urls import reverse
from django.views.decorators.http import require_POST

from accounts.models import User
from common.dates import fmt_md
from common.errors import ServiceError
from tasks import services as ts
from tasks.models import Task

from ..forms import QuickTaskForm
from .common import (
    apply_service_error,
    dialog,
    due_class,
    due_label,
    hx_redirect,
    new_idem,
    render_row,
    rows_for,
    task_or_404,
    trigger,
    week_days,
)

ROW_OPTS = "next,move,noassignee,today"
WEEKDAYS = "월화수목금토일"


def _request_param(request, name: str) -> str:
    """HTMX 조각 요청에서도 현재 Today 화면의 일정 상태를 이어 간다."""
    if name in request.GET:
        return request.GET.get(name, "")
    current_url = request.headers.get("HX-Current-URL", "")
    if not current_url:
        return ""
    return parse_qs(urlparse(current_url).query).get(name, [""])[-1]


def _ctx(request):
    v = ts.today_view(request.user)
    day = v["date"]
    v["date_label"] = f"{day.year}년 {day.month}월 {day.day}일 ({WEEKDAYS[day.weekday()]})"
    v["today_hint"] = f"오늘 목록 {v['counts']['today']}건" if v["focus"] else "오늘 목록 비어 있음"
    v["schedule_open"] = _request_param(request, "schedule") == "1"
    state = {"schedule": "1"} if v["schedule_open"] else {}
    if v["schedule_open"]:
        for name in ("month", "day"):
            if value := _request_param(request, name):
                state[name] = value
    v["today_state_query"] = urlencode(state)
    v["rows"] = rows_for(request.user, v["items"], ROW_OPTS)
    v["done_rows"] = rows_for(request.user, v["done_today"], "noassignee,notoday,today")
    for row in v["rows"] + v["done_rows"]:
        row["today_state_query"] = v["today_state_query"]
        if v["today_state_query"]:
            row["row_query"] = f"{row['row_query']}&{v['today_state_query']}"
    v["auto_pull_choices"] = User.AUTO_PULL_CHOICES
    v["focus_due"] = due_label(v["focus"]) if v["focus"] else ""
    v["focus_due_class"] = due_class(v["focus"]) if v["focus"] else ""
    return v


def _schedule(request, day: date) -> dict:
    """일정 카드. 월 캘린더만 있다. ?month=YYYY-MM&day=YYYY-MM-DD"""
    raw = _request_param(request, "month")
    try:
        month = date.fromisoformat(f"{raw}-01") if raw else day.replace(day=1)
    except ValueError:
        month = day.replace(day=1)
    try:
        selected = _request_param(request, "day")
        sel = date.fromisoformat(selected) if selected else day
    except ValueError:
        sel = day

    my_open = ts.visible_tasks(request.user).filter(assignee=request.user, status__in=Task.OPEN)
    counts = dict(
        my_open.filter(due_date__year=month.year, due_date__month=month.month)
        .values_list("due_date")
        .annotate(n=Count("id"))
    )
    cells_src = week_days(month)
    while len(cells_src) % 7:  # 28·35·42 중 하나가 되도록 뒤를 채운다
        cells_src.append(None)

    def url(d: date, m: date | None = None) -> str:
        m = m or month
        return f"{reverse('today')}?schedule=1&month={m:%Y-%m}&day={d.isoformat()}#today-schedule"

    sel_in_month = (sel.year, sel.month) == (month.year, month.month)
    sel_tasks = sorted(my_open.filter(due_date=sel), key=ts.by_due) if sel_in_month else []
    prev_m = (month.replace(day=1) - timedelta(days=1)).replace(day=1)
    next_m = (
        date(month.year + 1, 1, 1) if month.month == 12 else date(month.year, month.month + 1, 1)
    )
    this_m = day.replace(day=1)

    if not sel_in_month:
        sel_label = "날짜를 누르면 그날 마감이 보입니다"
    elif sel_tasks:
        sel_label = f"{fmt_md(sel)} 마감 {len(sel_tasks)}건"
    else:
        sel_label = f"{fmt_md(sel)} 마감 없음"

    return {
        "cal_title": f"{month.year}년 {month.month}월",
        "cal_prev": url(prev_m, prev_m),
        "cal_next": url(next_m, next_m),
        "cal_this": url(this_m, this_m) if month != this_m else "",
        "cal_cells": [
            None
            if d is None
            else {
                "day": d.day,
                "n": counts.get(d, 0),
                "today": d == day,
                "sel": sel_in_month and d == sel,
                "url": url(d),
                "aria": (
                    f"{d.month}월 {d.day}일 마감 {counts.get(d, 0)}건"
                    f"{' · 오늘' if d == day else ''}"
                    f"{' · 선택됨' if sel_in_month and d == sel else ''}"
                ),
            }
            for d in cells_src
        ],
        "cal_sel_label": sel_label,
        "cal_sel_tasks": sel_tasks,
    }


@login_required
def today(request):
    v = _ctx(request)
    part = request.GET.get("part")
    if part == "head":
        return render(request, "today/_head.html", v)
    if part == "list":
        return render(request, "today/_list.html", v)
    if part == "schedule":
        v.update(_schedule(request, v["date"]))
        return render(request, "today/_schedule.html", v)
    v["quick_open"] = request.GET.get("quick") == "1"
    v["form"] = QuickTaskForm(user=request.user, initial={"idem": new_idem(), "priority": 5})
    if v["schedule_open"]:
        v.update(_schedule(request, v["date"]))
    return render(request, "today.html", v)


def head(request, error=None):
    """오늘 화면 머리(날짜·지표·지금 할 일 카드). tasks.task_status가 from=head일 때도 부른다."""
    v = _ctx(request)
    v["error"] = error
    return render(request, "today/_head.html", v)


def _list(request):
    return render(request, "today/_list.html", _ctx(request))


def _after_change(request, task):
    """오늘 화면 안이면 목록 전체, 다른 화면이면 그 행만 돌려준다. 머리는 today-changed로 갱신된다."""
    if "today" in request.GET.get("opts", ""):
        return trigger(_list(request), "today-changed")
    return trigger(render_row(request, task), "today-changed")


@login_required
@require_POST
def quick_add(request):
    form = QuickTaskForm(request.POST, user=request.user)
    if form.is_valid():
        d = form.cleaned_data
        try:
            task = ts.create_task(
                project=d["project"],
                title=d["title"],
                actor=request.user,
                source="web",
                priority=d["priority"],
                due_date=d["due_date"],
                no_due_reason=d["no_due_reason"],
                idempotency_key=d["idem"] or None,
            )
            ts.today_add(request.user, task)
            return hx_redirect(request, reverse("today"))
        except ServiceError as e:
            apply_service_error(form, e)
    return dialog(request, "today/_quick.html", {"form": form, "quick_open": True})


@login_required
@require_POST
def add(request, task_id):
    task = task_or_404(request.user, task_id)
    ts.today_add(request.user, task)
    return _after_change(request, task)


@login_required
@require_POST
def exclude(request, task_id):
    task = task_or_404(request.user, task_id)
    ts.today_exclude(request.user, task)
    return _after_change(request, task)


@login_required
@require_POST
def restore(request):
    ts.today_restore_excluded(request.user)
    return trigger(_list(request), "today-changed")


@login_required
@require_POST
def move(request, task_id, direction):
    ts.today_move(request.user, task_or_404(request.user, task_id), direction)
    return _list(request)


@login_required
@require_POST
def auto_pull(request):
    try:
        ts.today_set_auto_pull(request.user, int(request.POST.get("auto_pull_days", "5")))
    except (ValueError, ServiceError):
        pass
    return trigger(_list(request), "today-changed")
