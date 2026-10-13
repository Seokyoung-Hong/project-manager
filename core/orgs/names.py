"""사람 이름을 조직 맥락에 맞게 보여 주는 유일한 자리(IMPL-PLAN-13 §3).

display_for(user, org):
  user 없음                         → ""
  org 없음(조직을 정할 수 없는 자리)   → 계정 표시 이름
  조직이 "실명으로 표시"이고 실명 있음  → 계정 실명
  그 조직의 조직 표시 이름 있음        → 조직 표시 이름
  그 밖(구성원 아님·탈퇴자 포함)       → 계정 표시 이름

저장된 사본이 없고 읽을 때 계산한다 — 실명·옵션·조직 표시 이름을 바꾸면 곧바로 반영된다.
캐시는 요청 하나 동안의 조직별 이름표뿐이다(common.middleware.names_scope가 요청마다 비운다).
요청 밖(워커·관리 명령)에서는 캐시 없이 매번 읽는다.
"""

from contextvars import ContextVar

from .member_info import definition
from .models import OrgMembership

# ponytail: 요청 단위 캐시. 조직이 수천 명이면 org_names를 필요한 user_id만 읽게 바꾼다.
_cache: ContextVar[dict | None] = ContextVar("org_names", default=None)


def _org_id(org):
    return getattr(org, "pk", org)


def org_names(org_id) -> dict[int, str]:
    """{user_id: 그 조직 표시 이름} — 구성원만. 쿼리 1회(구성원 행 + 계정 이름 + 조직 옵션)."""
    org_id = _org_id(org_id)
    cache = _cache.get()
    if cache is not None and org_id in cache:
        return cache[org_id]
    rows = OrgMembership.objects.filter(org_id=org_id).values_list(
        "user_id", "nickname", "user__real_name", "user__display_name", "org__member_fields"
    )
    out = {}
    for uid, nickname, real_name, display_name, fields in rows:
        if definition(fields)["show_real_name"] and real_name:
            out[uid] = real_name
        else:
            out[uid] = nickname or display_name
    if cache is not None:
        cache[org_id] = out
    return out


def display_for(user, org=None) -> str:
    """org는 조직 객체·id·None."""
    if user is None:
        return ""
    if org is None:
        return user.display_name
    return org_names(org).get(user.pk, user.display_name)


def sort_by_name(users, org) -> list:
    """이름순 목록. order_by("display_name")은 조직 표시 이름과 순서가 어긋나서 대신 쓴다."""
    shown = org_names(org)  # 한 번만 — 요청 밖(캐시 없음)에서 사람마다 다시 읽지 않게
    return sorted(users, key=lambda u: shown.get(u.pk, u.display_name))


def forget(org_id):
    """표시 이름·실명·옵션을 바꾼 서비스가 부른다(이 요청 안에서 다시 읽게)."""
    cache = _cache.get()
    if cache is not None:
        cache.pop(_org_id(org_id), None)


def forget_all():
    """계정 실명·표시 이름처럼 여러 조직에 걸친 값을 바꾼 뒤 부른다."""
    cache = _cache.get()
    if cache is not None:
        cache.clear()
