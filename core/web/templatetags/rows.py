from django import template

from tasks.work_requests import _due_text

register = template.Library()


@register.inclusion_tag("tasks/_row.html")
def task_row(ctx: dict):
    """{% task_row r %} — r은 views.common.row_ctx()가 만든 dict."""
    return ctx


# 상태를 색으로만 알리지 않기 위한 기호. 색약 사용자와 흑백 인쇄에서도 구분된다.
STATUS_MARKS = {
    "todo": "○",
    "doing": "▶",
    "paused": "⏸",
    "blocked": "■",
    "review": "◆",
    "done": "✓",
    "cancelled": "✕",
}


@register.filter
def due_text(due) -> str:
    return _due_text(due)


@register.filter
def status_mark(code: str) -> str:
    return STATUS_MARKS.get(code, "")


@register.filter
def initial(name: str) -> str:
    """이름 아바타 글자. "[데모] 산돌이"의 "["처럼 기호로 시작하는 이름을 건너뛴다."""
    for ch in name or "":
        if ch.isalnum():
            return ch.upper()
    return "?"
