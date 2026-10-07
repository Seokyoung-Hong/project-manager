from django import template

from tasks.split import task_split_candidates

register = template.Library()


@register.inclusion_tag("tasks/_split_hint.html")
def split_hint(task):
    """{% split_hint task %} — 제목·설명에 멤버 이름이 둘 이상 보이면 막지 않는 안내(.notice)."""
    return {"task": task, "people": task_split_candidates(task) if task.is_open else []}
