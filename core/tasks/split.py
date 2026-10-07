"""IMPL-PLAN-11 §2: 담당자는 한 명. 여러 사람이 맡는 일은 사람별 태스크로 나눠 계열로 묶는다."""

from django.db import transaction

from common.dates import today_kst
from common.errors import ServiceError

from .services import _log, _require_task, duplicate_task, replace_checklist, update_text

MIN_PEOPLE, MAX_PEOPLE = 2, 10
ONE_ASSIGNEE = (
    "담당자는 한 명입니다. 사람별로 나누려면 만든 뒤 POST /api/tasks/{id}/split 을 쓰세요."
)
SPLIT_NOTE = "담당자는 한 명입니다. 사람별로 나누려면 웹에서 [사람별로 나누기]를 누르세요."


def looks_multi_assignee(title, description, org) -> list:
    """제목·설명에 조직 활성 멤버의 표시 이름이 2명 이상 보이면 그 사람들(등장 순서). 아니면 [].

    # ponytail: 이름 부분 문자열 일치 — 두 글자 미만 이름은 오탐이 많아 건너뛴다.
    # '같이·함께·공동' 키워드는 쓰지 않는다(이름 없이는 근거가 없다). 필요하면 이름 1명 + 키워드로.
    """
    text = f"{title or ''}\n{description or ''}"
    hits = sorted(
        (text.find(u.display_name), u.pk, u)
        for u in org.members.filter(is_active=True)
        if len(u.display_name) >= 2 and u.display_name in text
    )
    users = [u for _, _, u in hits]
    return users if len(users) >= MIN_PEOPLE else []


def task_split_candidates(task) -> list:
    return looks_multi_assignee(task.title, task.description, task.project.org)


@transaction.atomic
def split_by_assignees(
    task,
    users,
    *,
    actor,
    source,
    token=None,
    roles=None,
    title_pattern="{title} — {name}",
    idempotency_key=None,
) -> list:
    """사람마다 태스크 하나(2~10명). duplicate_task로 설명·체크리스트·링크·문서·연결 프로젝트를 복사하고
    원본의 계열(parent)로 묶는다. 기한은 원본을 따른다. 원본은 지우거나 취소하지 않는다 —
    원본 체크리스트를 'TASK-n 이름' 목록으로 바꾸고 진행 메모에 한 줄 남긴다.
    roles: {user_id: 역할 이름} — 제목에 '이름 (역할)'로 붙는다. 연동 프로젝트(GitHub)는 복사하지 않는다."""
    _require_task(actor, task)
    users = list(dict.fromkeys(users))
    if task.is_template:
        raise ServiceError({"task": "템플릿은 나눌 수 없습니다. 회차를 만든 뒤 나누세요."})
    if not MIN_PEOPLE <= len(users) <= MAX_PEOPLE:
        raise ServiceError({"assignee_ids": f"{MIN_PEOPLE}명 이상 {MAX_PEOPLE}명 이하로 고르세요."})
    members = set(task.project.org.members.filter(is_active=True).values_list("pk", flat=True))
    if any(u.pk not in members for u in users):
        raise ServiceError({"assignee_ids": "조직 멤버가 아닌 사람이 있습니다."})
    if "{name}" not in title_pattern:
        raise ServiceError({"title_pattern": "제목 규칙에 {name}이 있어야 합니다."})
    roles = roles or {}
    out = []
    for u in users:
        role = (roles.get(u.pk) or "").strip()
        label = f"{u.display_name} ({role})" if role else u.display_name
        try:
            title = title_pattern.format(title=task.title, name=label)
        except (KeyError, IndexError, ValueError) as e:
            raise ServiceError(
                {"title_pattern": "제목 규칙은 {title}과 {name}만 쓸 수 있습니다."}
            ) from e
        out.append(
            duplicate_task(
                task,
                actor=actor,
                source=source,
                token=token,
                title=title,
                due_date=task.due_date,
                no_due_reason=task.no_due_reason or ("" if task.due_date else "원본을 따름"),
                assignee=u,
                idempotency_key=f"{idempotency_key}:{u.pk}" if idempotency_key else None,
            )
        )
    replace_checklist(
        task, [{"text": f"{n.number} {n.title}"} for n in out], actor=actor, source=source
    )
    numbers = ",".join(n.number for n in out)
    note = f"{today_kst():%Y-%m-%d} 사람별로 나눴습니다: {numbers}"
    update_text(
        task, "notes", f"{task.notes}\n{note}" if task.notes else note, actor=actor, source=source
    )
    _log(task, "split", "", numbers, actor, source, token)
    return out
