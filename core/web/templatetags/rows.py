from django import template

register = template.Library()


@register.inclusion_tag("tasks/_row.html")
def task_row(ctx: dict):
    """{% task_row r %} — r은 views.common.row_ctx()가 만든 dict."""
    return ctx


@register.filter
def get_item(d, key):
    """{{ dict|get_item:key }} — 설정 화면처럼 키가 변수일 때."""
    return (d or {}).get(key)
