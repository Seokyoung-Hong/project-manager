from django import template

from orgs.names import display_for

register = template.Library()


@register.filter
def name_in(user, org):
    """{{ u|name_in:org }} — 그 조직에서 보이는 이름(orgs/names.py). org는 객체·id. 없으면 계정 표시 이름."""
    return display_for(user, org or None)
