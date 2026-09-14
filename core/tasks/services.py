from datetime import date, timedelta

from django.db import transaction
from django.db.models import Max, Q
from django.utils import timezone

from accounts.models import IdempotencyKey, User
from common.dates import kst_day_range, today_kst, week_bounds
from common.errors import ConflictError, ServiceError
from orgs import settings as S
from orgs.services import ai_check, is_admin, is_member, orgs_of
from projects.services import is_owner, project_stats

from .models import ChangeLog, ChecklistItem, Link, Task, TodayItem

# 자동 저장되는 부속 텍스트. version·ChangeLog 없음.
TEXT_FIELDS = ("title", "description", "done_when", "next_action", "notes")
TEXT_MAX = {"title": 200, "done_when": 300, "next_action": 200}
# 낙관적 잠금이 걸리는 팀 데이터
LOCKED_FIELDS = {"assignee", "priority", "due_date", "no_due_reason", "project", "stop_reason"}
EDITABLE = LOCKED_FIELDS | set(TEXT_FIELDS)
TRACKED = ("assignee", "due_date", "project", "priority", "stop_reason")

NO_DUE_FOR_DOING = "목표 기한이 없어서 진행 중으로 바꾸지 못했어요. 기한을 먼저 정해 주세요."

# 내 태스크 화면 필터 값. (코드, 화면 표기)
DUE_FILTERS = [
    ("", "모든 기한"),
    ("overdue", "기한 초과"),
    ("today", "오늘 마감"),
    ("week", "이번 주 남은 마감"),
    ("this_week", "이번 주 전체 마감"),
    ("later", "그 이후"),
    ("none", "기한 미정"),
]
STATUS_FILTERS = (
    [("", "모든 상태")]
    + [(c, label) for c, label in Task.STATUSES if c in Task.OPEN]
    + [("done_today", "오늘 완료"), ("done_7d", "지난 7일 완료")]
)
PRIORITY_FILTERS = [("", "모든 중요도")] + Task.TIER_LABELS
GROUP_OPTIONS = [("due", "기한별"), ("project", "프로젝트별"), ("status", "상태별")]
SORT_OPTIONS = [("due", "기한"), ("priority", "중요도"), ("updated", "최근 수정")]


# ---------- 공통 ----------


def _s(v) -> str:
    if v is None:
        return ""
    if hasattr(v, "pk"):
        return str(v.pk)
    if hasattr(v, "isoformat"):
        return v.isoformat()
    return str(v)


def _log(task, field, old, new, actor, source, token=None, note="", external_actor=""):
    """actor가 None이면 external_actor(GitHub 로그인)가 행위자를 대신한다.

    그 사람이 나중에 GitHub를 연결하면 github.services.backfill_actor()가 소급해 채운다.
    """
    ChangeLog.objects.create(
        target_type="task",
        target_id=task.pk,
        field=field,
        old_value=_s(old),
        new_value=_s(new),
        note=note[:200],
        actor=actor,
        external_actor=(external_actor or "")[:100],
        source=source,
        token=token,
    )


def _require_member(actor, project):
    """actor가 None이면 GitHub 웹훅이다. 연결된 저장소가 곧 권한의 근거다.

    None을 넘기는 호출은 github/services.py 안에만 있어야 한다
    (test_actor_none_only_from_github_services가 grep으로 고정한다).
    """
    if actor is None:
        return
    if not is_member(actor, project.org):
        raise ServiceError({"project": "이 조직의 멤버가 아닙니다."})


def _validate(
    *,
    project,
    assignee,
    status,
    priority,
    due_date,
    no_due_reason,
    stop_reason,
    title,
    actor,
    check_assignee=True,
):
    """check_assignee=False면 담당자가 조직의 활성 멤버인지 보지 않는다.

    담당자를 바꾸지 않는 수정에는 이 검사를 걸지 않는다. 담당자가 조직에서 빠지거나
    비활성이 되면(멤버 관리 화면의 [제거]) 그 태스크의 중요도·기한조차 못 고치게 되고,
    화면에는 이미 나간 사람 이름이 담긴 오류만 나온다.

    actor가 None이면 GitHub 웹훅이다. task.* 설정은 사람의 입력을 막는 것이라 적용하지 않는다.
    """
    errors = {}
    if not title or not title.strip():
        errors["title"] = "제목을 입력하세요."
    if project.is_archived:
        errors["project"] = "보관된 프로젝트에는 태스크를 둘 수 없습니다."
    if assignee is None:
        errors["assignee"] = "담당자를 지정하세요."
    elif check_assignee and (not assignee.is_active or not is_member(assignee, project.org)):
        errors["assignee"] = "담당자는 이 조직의 활성 멤버여야 합니다."
    if not isinstance(priority, int) or isinstance(priority, bool) or not 1 <= priority <= 10:
        errors["priority"] = "중요도는 1~10 사이의 정수여야 합니다."
    if status == "doing" and due_date is None:
        errors["due_date"] = NO_DUE_FOR_DOING
    elif (
        actor is not None
        and status in Task.OPEN
        and due_date is None
        and S.effective("task.due_required", project=project)
    ):
        errors["due_date"] = "이 프로젝트는 기한이 필수예요."
    elif status in Task.OPEN and due_date is None and not (no_due_reason or "").strip():
        errors["no_due_reason"] = "기한이 없으면 사유를 입력하세요."
    reason = (stop_reason or "").strip()
    if status == "blocked" and not reason:
        errors["stop_reason"] = "막힘 사유를 입력하세요."
    if status not in Task.STOPPED and reason:
        errors["stop_reason"] = "일시정지·막힘 상태에서만 사유를 둘 수 있습니다."
    if errors:
        raise ServiceError(errors)


def _check_priority_cap(project, priority: int, actor, source="web"):
    """task.priority_cap: 상한 초과는 프로젝트 관리자·조직 관리자만. actor 가 None(GitHub 웹훅)이면 면제.
    ai.priority_cap: AI 경로는 사람의 등급과 무관하게 이 상한을 넘지 못한다."""
    if source == "mcp":
        ai_cap = S.effective("ai.priority_cap", org=project.org)
        if ai_cap and priority > ai_cap:
            raise ServiceError(
                {
                    "priority": f"AI는 중요도 {ai_cap}까지만 정할 수 있어요. 더 높이려면 사람에게 요청하세요."
                }
            )
    cap = S.effective("task.priority_cap", project=project)
    if actor is None or not cap or priority <= cap:
        return
    if is_owner(actor, project) or is_admin(actor, project.org):
        return
    raise ServiceError({"priority": f"중요도 {cap + 1} 이상은 프로젝트 관리자만 정할 수 있어요."})


def doing_over_limit(user, org) -> tuple[int, int] | None:
    """task.doing_limit_mode=warn 용. 한도를 넘겼으면 (현재 수, 한도), 아니면 None."""
    limit = S.effective("task.doing_limit", org=org)
    if not limit:
        return None
    count = Task.objects.filter(assignee=user, project__org=org, status="doing").count()
    return (count, limit) if count >= limit else None


def overdue_cutoff(project) -> date:
    """초과 유예(task.overdue_grace_days)를 적용한 기준일. Task.is_overdue 자체는 그대로 사실만 본다."""
    grace = S.effective("task.overdue_grace_days", project=project)
    return today_kst() - timedelta(days=grace)


def _apply(task, expected_version: int, fields: dict):
    """낙관적 잠금 갱신. 버전이 다르면 ConflictError(최신 객체)."""
    updated = Task.objects.filter(pk=task.pk, version=expected_version).update(
        version=expected_version + 1, updated_at=timezone.now(), **fields
    )
    if updated != 1:
        task.refresh_from_db()
        raise ConflictError(task)
    task.refresh_from_db()


def visible_tasks(user):
    """user가 볼 수 있는 태스크 queryset (내 조직 범위)."""
    return Task.objects.filter(project__org__in=orgs_of(user)).select_related(
        "project", "project__org", "assignee"
    )


def get_visible_task(user, task_id: int) -> Task | None:
    return visible_tasks(user).filter(pk=task_id).first()


def by_due(t):
    """기한 오름차순, 기한 없음은 뒤로, 같으면 id."""
    return (t.due_date or date.max, t.pk)


# ---------- 생성·수정 ----------


@transaction.atomic
def create_task(
    *,
    project,
    title,
    actor,
    source,
    token=None,
    assignee=None,
    description="",
    done_when="",
    next_action="",
    priority=None,
    due_date=None,
    no_due_reason="",
    idempotency_key=None,
) -> Task:
    _require_member(actor, project)
    ai_check(project.org, "create_task", source, "태스크 생성", "title")
    if idempotency_key:
        idempotency_key = idempotency_key[:100]
        hit = IdempotencyKey.objects.filter(
            user=actor, key=idempotency_key, target_type="task"
        ).first()
        if hit:
            return Task.objects.get(pk=hit.target_id)
    assignee = assignee or actor
    if priority is None:
        priority = S.effective("task.default_priority", project=project)
    if (
        actor is not None
        and S.effective("task.require_done_when", project=project)
        and not (done_when or "").strip()
    ):
        raise ServiceError({"done_when": "완료 조건을 입력하세요."})
    _validate(
        project=project,
        assignee=assignee,
        status="todo",
        priority=priority,
        due_date=due_date,
        no_due_reason=no_due_reason,
        stop_reason="",
        title=title,
        actor=actor,
    )
    _check_priority_cap(project, priority, actor, source)
    task = Task.objects.create(
        project=project,
        title=title.strip()[:200],
        description=description or "",
        done_when=(done_when or "")[:300],
        next_action=(next_action or "")[:200],
        assignee=assignee,
        priority=priority,
        due_date=due_date,
        no_due_reason=(no_due_reason or "").strip()[:200],
        created_by=actor,
    )
    _log(task, "created", "", task.number, actor, source, token)
    if idempotency_key:
        IdempotencyKey.objects.create(
            user=actor, key=idempotency_key[:100], target_type="task", target_id=task.pk
        )
    return task


def update_text(task, field: str, value: str, *, actor) -> Task:
    """제목·설명·완료 조건·다음 행동·진행 메모 자동 저장. version·ChangeLog를 건드리지 않는다.
    # ponytail: 부속 텍스트는 last-write-wins. 동시 편집 보호가 필요해지면 필드별 갱신 시각 비교로.
    """
    _require_member(actor, task.project)
    if field not in TEXT_FIELDS:
        raise ServiceError({field: "수정할 수 없는 항목입니다."})
    value = value or ""
    if field == "title":
        value = value.strip()
        if not value:
            raise ServiceError({"title": "제목을 입력하세요."})
    if field in TEXT_MAX:
        value = value[: TEXT_MAX[field]]
    Task.objects.filter(pk=task.pk).update(**{field: value}, updated_at=timezone.now())
    task.refresh_from_db()
    return task


@transaction.atomic
def update_task(
    task,
    changes: dict,
    *,
    actor,
    source,
    token=None,
    expected_version: int,
    external_actor="",
    reason="",
) -> Task:
    """팀 데이터 필드는 version 검사 후 갱신·이력 기록. TEXT_FIELDS는 update_text로 보낸다.

    reason: 담당자·기한 변경 사유. task.assignee_change_reason·task.due_change_reason이 켜져
    있으면 필수다. 있으면 그 필드의 이력 note에 남는다.
    """
    _require_member(actor, task.project)
    unknown = set(changes) - EDITABLE
    if unknown:
        raise ServiceError({k: "수정할 수 없는 항목입니다." for k in sorted(unknown)})
    org = task.project.org
    if any(f in changes for f in TEXT_FIELDS):
        ai_check(org, "edit_text", source, "본문 수정", "title")
    if "assignee" in changes:
        ai_check(org, "change_assignee", source, "담당자 변경", "assignee")
    if "due_date" in changes or "no_due_reason" in changes:
        ai_check(org, "change_due", source, "기한 변경", "due_date")
    if "priority" in changes:
        ai_check(org, "change_priority", source, "중요도 변경", "priority")
    for f in TEXT_FIELDS:
        if f in changes:
            update_text(task, f, changes[f], actor=actor)
    changes = {f: v for f, v in changes.items() if f in LOCKED_FIELDS}
    if not changes:
        return task
    new = {f: changes.get(f, getattr(task, f)) for f in LOCKED_FIELDS}
    if "project" in changes:
        _require_member(actor, new["project"])
        if new["project"].org_id != task.project.org_id:
            raise ServiceError({"project": "다른 조직의 프로젝트로 옮길 수 없습니다."})
    new["no_due_reason"] = (new["no_due_reason"] or "").strip()[:200]
    new["stop_reason"] = (new["stop_reason"] or "").strip()[:300]
    _validate(
        project=new["project"],
        assignee=new["assignee"],
        status=task.status,
        priority=new["priority"],
        due_date=new["due_date"],
        no_due_reason=new["no_due_reason"],
        stop_reason=new["stop_reason"],
        title=task.title,
        check_assignee="assignee" in changes,
        actor=actor,
    )
    old = {f: getattr(task, f) for f in LOCKED_FIELDS}
    fields = {f: v for f, v in new.items() if v != old[f]}
    if not fields:
        return task
    if "priority" in fields:
        _check_priority_cap(new["project"], fields["priority"], actor, source)
    reason = (reason or "").strip()[:300]
    if actor is not None:
        if (
            "assignee" in fields
            and S.effective("task.assignee_change_reason", project=new["project"])
            and not reason
        ):
            raise ServiceError({"reason": "담당자 변경 사유를 입력하세요."})
        if (
            "due_date" in fields
            and S.effective("task.due_change_reason", project=new["project"])
            and not reason
        ):
            raise ServiceError({"reason": "기한 변경 사유를 입력하세요."})
    _apply(task, expected_version, fields)
    for f in TRACKED:
        if f in fields:
            note = reason if f in ("assignee", "due_date") else ""
            _log(
                task,
                f,
                old[f],
                fields[f],
                actor,
                source,
                token,
                note=note,
                external_actor=external_actor,
            )
    return task


@transaction.atomic
def transition(
    task,
    new_status: str,
    *,
    actor,
    source,
    token=None,
    reason="",
    expected_version: int,
    external_actor="",
) -> Task:
    """상태 변경. 규칙:
    - 미완료 5개 사이는 자유. 미완료 → 완료·취소 가능. 완료·취소 → 시작 전·진행 중으로만 재개.
    - 같은 상태 재요청은 아무것도 바꾸지 않는다 (A06).
    - doing 진입 시 기한 필수. blocked 진입 시 reason 필수. paused는 reason 선택.
    - paused·blocked 밖으로 나가면 stop_reason·stopped_at 초기화.
    - done 진입 시 completed_at=now. 재개·취소 시 completed_at=None.
    - 재개 사유(reason)는 선택. 있으면 이력 note에 남는다.
    """
    _require_member(actor, task.project)
    labels = dict(Task.STATUSES)
    if new_status not in labels:
        raise ServiceError({"status": "알 수 없는 상태입니다."})
    if new_status == task.status:
        return task
    if task.is_closed:
        ai_check(task.project.org, "reopen_task", source, "재개", "status")
    elif new_status in Task.CLOSED:
        ai_check(task.project.org, "close_task", source, "완료·취소 처리", "status")
    else:
        ai_check(task.project.org, "transition_open", source, "상태 변경", "status")
    if task.is_closed and new_status not in ("todo", "doing"):
        raise ServiceError(
            {
                "status": f"{labels[task.status]}에서 {labels[new_status]}(으)로 바꿀 수 없습니다. "
                "먼저 시작 전이나 진행 중으로 다시 여세요."
            }
        )
    reason = (reason or "").strip()[:300]
    if new_status == "doing" and task.due_date is None:
        raise ServiceError({"due_date": NO_DUE_FOR_DOING})
    if new_status == "blocked" and not reason:
        raise ServiceError({"stop_reason": "막힘 사유를 입력하세요."})
    if actor is not None and new_status == "doing":
        limit = S.effective("task.doing_limit", project=task.project)
        if limit:
            mode = S.effective("task.doing_limit_mode", project=task.project)
            count = (
                Task.objects.filter(
                    assignee=task.assignee, project__org=task.project.org, status="doing"
                )
                .exclude(pk=task.pk)
                .count()
            )
            if count >= limit and mode == "block":
                raise ServiceError(
                    {
                        "status": f"동시에 진행할 수 있는 태스크는 {limit}개예요. "
                        "하나를 끝내거나 멈춘 뒤 시작하세요."
                    }
                )
    if (
        new_status == "done"
        and task.status != "review"
        and actor is not None
        and S.effective("task.review_required", project=task.project)
    ):
        raise ServiceError({"status": "검토 대기를 거쳐야 완료할 수 있어요."})
    if (
        new_status == "done"
        and task.status == "review"
        and actor is not None
        and S.effective("task.review_required", project=task.project)
        and not S.effective("task.self_review", project=task.project)
        and actor == task.assignee
    ):
        raise ServiceError({"status": "본인이 담당한 태스크는 다른 사람이 완료 확인을 해야 해요."})
    if (
        actor is not None
        and task.status in Task.CLOSED
        and new_status in ("todo", "doing")
        and S.effective("task.reopen_reason_required", project=task.project)
        and not reason
    ):
        raise ServiceError({"reason": "재개 사유를 입력하세요."})
    if (
        actor is not None
        and new_status == "cancelled"
        and S.effective("task.cancel_reason_required", project=task.project)
        and not reason
    ):
        raise ServiceError({"reason": "취소 사유를 입력하세요."})
    fields = {"status": new_status}
    if new_status in Task.STOPPED:
        fields["stop_reason"] = reason or (task.stop_reason if task.is_stopped else "")
        if not task.is_stopped:
            fields["stopped_at"] = timezone.now()
    else:
        fields["stop_reason"] = ""
        fields["stopped_at"] = None
    if new_status == "done":
        fields["completed_at"] = timezone.now()
    elif task.is_closed or new_status == "cancelled":
        fields["completed_at"] = None
    old_status, old_completed, old_reason = task.status, task.completed_at, task.stop_reason
    _apply(task, expected_version, fields)
    _log(
        task,
        "status",
        old_status,
        new_status,
        actor,
        source,
        token,
        note=reason,
        external_actor=external_actor,
    )
    if old_status == "done" and old_completed is not None:
        _log(
            task,
            "completed_at",
            old_completed,
            None,
            actor,
            source,
            token,
            note="재개",
            external_actor=external_actor,
        )
    if old_reason and not task.stop_reason:
        _log(
            task,
            "stop_reason",
            old_reason,
            "",
            actor,
            source,
            token,
            note="상태 변경으로 해제",
            external_actor=external_actor,
        )
    return task


@transaction.atomic
def extend_due(
    task,
    new_date: date | None,
    reason: str,
    *,
    actor,
    source,
    token=None,
    expected_version: int,
    external_actor="",
) -> Task:
    """목표일 연장. 기한이 없던 태스크는 목표일 정하기. 새 날짜는 현 기한보다 뒤, 사유 필수.
    이력에 'due_date' 행 하나, note='연장: 사유'. 진행 메모는 건드리지 않는다."""
    _require_member(actor, task.project)
    ai_check(task.project.org, "change_due", source, "기한 변경", "due_date")
    if not task.is_open:
        raise ServiceError({"due_date": "완료·취소된 태스크의 기한은 바꿀 수 없습니다."})
    if new_date is None:
        raise ServiceError({"due_date": "새 목표일을 선택하세요."})
    if task.due_date is not None and new_date <= task.due_date:
        raise ServiceError({"due_date": "현재 목표일보다 뒤의 날짜를 선택하세요."})
    reason = (reason or "").strip()
    if not reason:
        raise ServiceError({"reason": "연장 사유를 입력하세요."})
    old = task.due_date
    _apply(task, expected_version, {"due_date": new_date, "no_due_reason": ""})
    note = f"연장: {reason}" if old else f"목표일 지정: {reason}"
    _log(
        task,
        "due_date",
        old,
        new_date,
        actor,
        source,
        token,
        note=note,
        external_actor=external_actor,
    )
    return task


# ---------- 링크 ----------


def add_link(*, actor, title, url, kind="doc", task=None, project=None) -> Link:
    if (task is None) == (project is None):
        raise ServiceError({"target": "태스크 또는 프로젝트 중 하나에만 연결합니다."})
    target_project = project if project is not None else task.project
    _require_member(actor, target_project)
    title, url = (title or "").strip(), (url or "").strip()
    if not title or not url:
        raise ServiceError({"url": "제목과 URL을 입력하세요."})
    if not url.startswith(("http://", "https://")):
        raise ServiceError({"url": "http:// 또는 https:// 로 시작해야 합니다."})
    if kind not in dict(Link.KINDS):
        raise ServiceError({"kind": "알 수 없는 종류입니다."})
    return Link.objects.create(
        task=task, project=project, title=title[:100], url=url[:500], kind=kind, created_by=actor
    )


def delete_link(link, *, actor):
    target_project = link.project or link.task.project
    _require_member(actor, target_project)
    link.delete()


# ---------- 체크리스트 ----------


@transaction.atomic
def replace_checklist(task, items: list[dict], *, actor, source="web") -> list[ChecklistItem]:
    """items: [{'text': str, 'is_done': bool}, ...]. 전체 교체."""
    _require_member(actor, task.project)
    ai_check(task.project.org, "edit_text", source, "체크리스트 수정", "checklist")
    cleaned = []
    for i, item in enumerate(items):
        text = (item.get("text") or "").strip()
        if not text:
            raise ServiceError({"checklist": f"{i + 1}번째 항목의 내용이 비어 있습니다."})
        cleaned.append(
            ChecklistItem(task=task, text=text[:200], is_done=bool(item.get("is_done")), position=i)
        )
    task.checklist.all().delete()
    ChecklistItem.objects.bulk_create(cleaned)
    return list(task.checklist.all())


def checklist_add(task, text: str, *, actor) -> ChecklistItem:
    _require_member(actor, task.project)
    text = (text or "").strip()
    if not text:
        raise ServiceError({"text": "내용을 입력하세요."})
    pos = (task.checklist.aggregate(m=Max("position"))["m"] or 0) + 1
    return ChecklistItem.objects.create(task=task, text=text[:200], position=pos)


def checklist_toggle(item, *, actor) -> ChecklistItem:
    _require_member(actor, item.task.project)
    item.is_done = not item.is_done
    item.save(update_fields=["is_done"])
    return item


def checklist_delete(item, *, actor):
    _require_member(actor, item.task.project)
    item.delete()


def checklist_move(item, direction: str, *, actor):
    """direction: 'up' | 'down'. 이웃과 position을 맞바꾼다."""
    _require_member(actor, item.task.project)
    siblings = list(item.task.checklist.all())
    idx = siblings.index(item)
    j = idx - 1 if direction == "up" else idx + 1
    if 0 <= j < len(siblings):
        siblings[idx], siblings[j] = siblings[j], siblings[idx]
        for pos, s in enumerate(siblings):
            ChecklistItem.objects.filter(pk=s.pk).update(position=pos)


# ---------- 오늘 목록 (개인 계획) ----------
# 오늘 목록 = 직접 담은 것 ∪ (내 미완료 태스크 중 기한 ≤ 오늘+auto_pull_days, '오늘 제외' 아님).
# 어느 조작도 Task의 상태·기한·중요도·version·ChangeLog를 건드리지 않는다.


def _pull_end(user, day: date) -> date | None:
    n = user.auto_pull_days
    return day + timedelta(days=n) if n > 0 else None


def today_items(user, day: date):
    """그 날짜의 오늘 목록 행. 조직 범위를 벗어난 태스크는 제외한다.

    TodayItem은 태스크를 담은 시점의 기록이라, 그 뒤 조직에서 빠지면 남아 있을 수 있다.
    담기·읽기 두 경로가 같은 범위를 쓰도록 여기 한 곳에서 거른다.
    """
    return TodayItem.objects.filter(user=user, date=day, task__project__org__in=orgs_of(user))


def today_membership(user, day: date | None = None) -> dict:
    """행 렌더링용. 키: user_id, manual(set), excluded(set), pull_end."""
    day = day or today_kst()
    rows = today_items(user, day).values_list("task_id", "excluded")
    return {
        "user_id": user.pk,
        "manual": {tid for tid, ex in rows if not ex},
        "excluded": {tid for tid, ex in rows if ex},
        "pull_end": _pull_end(user, day),
    }


def today_flag(task, m: dict) -> str:
    """'manual' | 'auto' | ''. 자동 담기는 내가 담당한 미완료 태스크에만 적용된다."""
    if task.pk in m["manual"]:
        return "manual"
    if (
        m["pull_end"] is not None
        and task.assignee_id == m["user_id"]
        and task.is_open
        and task.due_date is not None
        and task.due_date <= m["pull_end"]
        and task.pk not in m["excluded"]
    ):
        return "auto"
    return ""


def today_add(user, task, day: date | None = None) -> TodayItem:
    _require_member(user, task.project)
    day = day or today_kst()
    pos = (TodayItem.objects.filter(user=user, date=day).aggregate(m=Max("position"))["m"] or 0) + 1
    item, created = TodayItem.objects.get_or_create(
        user=user, task=task, date=day, defaults={"position": pos, "excluded": False}
    )
    if not created and item.excluded:
        item.excluded, item.position = False, pos
        item.save(update_fields=["excluded", "position"])
    return item


def today_exclude(user, task, day: date | None = None):
    """직접 담은 항목이면 빼고, 자동 담기 대상이면 오늘 하루 제외한다. 둘 다 같은 행 하나로 표현."""
    day = day or today_kst()
    TodayItem.objects.update_or_create(
        user=user, task=task, date=day, defaults={"excluded": True, "position": 0}
    )


def today_restore_excluded(user, day: date | None = None):
    day = day or today_kst()
    TodayItem.objects.filter(user=user, date=day, excluded=True).delete()


def today_set_auto_pull(user, days: int):
    if days not in dict(User.AUTO_PULL_CHOICES):
        raise ServiceError({"auto_pull_days": "0, 1, 3, 5, 7, 14 중 하나여야 합니다."})
    user.auto_pull_days = days
    user.save(update_fields=["auto_pull_days"])


def today_reorder(user, task_ids: list[int], day: date | None = None):
    day = day or today_kst()
    items = {i.task_id: i for i in TodayItem.objects.filter(user=user, date=day, excluded=False)}
    for pos, tid in enumerate(task_ids):
        if tid in items:
            TodayItem.objects.filter(pk=items[tid].pk).update(position=pos)


def today_move(user, task, direction: str, day: date | None = None):
    """직접 담은 항목끼리만 순서를 바꾼다. 자동 담긴 항목은 정렬 규칙을 따른다."""
    day = day or today_kst()
    ids = [i.task_id for i in TodayItem.objects.filter(user=user, date=day, excluded=False)]
    if task.pk not in ids:
        return
    idx = ids.index(task.pk)
    j = idx - 1 if direction == "up" else idx + 1
    if 0 <= j < len(ids):
        ids[idx], ids[j] = ids[j], ids[idx]
        today_reorder(user, ids, day)


def _rank(t):
    """자동 담긴 항목 정렬: 중요도 desc → 기한 asc → id."""
    return (-t.priority, t.due_date or date.max, t.pk)


def today_view(user, day: date | None = None) -> dict:
    """오늘 화면 데이터. 키: date, items, focus, done_today, auto_pull_days, counts.
    items 순서: 직접 담은 것(위치 순) → 자동 담긴 것(_rank) → 닫힌 것은 맨 뒤.
    각 Task에 auto_pulled(bool) 속성을 붙여 돌려준다."""
    day = day or today_kst()
    m = today_membership(user, day)
    manual = [
        i.task
        for i in today_items(user, day)
        .filter(excluded=False)
        .select_related("task__project", "task__assignee")
        .order_by("position", "id")
    ]
    # 조직에서 빠진 뒤에도 담당으로 남은 태스크가 새는 것을 막는다(다른 읽기 경로와 같은 범위).
    mine = visible_tasks(user).filter(assignee=user)
    my_open = mine.filter(status__in=Task.OPEN)
    auto = []
    if m["pull_end"] is not None:
        auto = sorted(
            my_open.filter(due_date__lte=m["pull_end"]).exclude(pk__in=m["manual"] | m["excluded"]),
            key=_rank,
        )
    for t in manual:
        t.auto_pulled = False
    for t in auto:
        t.auto_pulled = True
    both = manual + auto
    items = [t for t in both if t.is_open] + [t for t in both if t.is_closed]
    start, end = kst_day_range(day)
    done_today = list(
        mine.filter(status="done", completed_at__gte=start, completed_at__lt=end).order_by(
            "-completed_at"
        )
    )
    week_start, _ = kst_day_range(day - timedelta(days=6))
    counts = {
        "today": len(items),
        "auto_pulled": len(auto),
        "excluded": len(m["excluded"]),
        "done_today": len(done_today),
        "done_7d": mine.filter(
            status="done", completed_at__gte=week_start, completed_at__lt=end
        ).count(),
        "my_open": my_open.count(),
        "due_today": my_open.filter(due_date=day).count(),
        "overdue": my_open.filter(due_date__lt=day).count(),
        "review": my_open.filter(status="review").count(),
        "blocked": my_open.filter(status="blocked").count(),
    }
    # ponytail: 다중 조직이면 첫 조직만 본다. 지금은 조직이 하나라 항상 맞다.
    org = orgs_of(user).first()
    doing_warn = None
    if org is not None and S.effective("task.doing_limit_mode", org=org) == "warn":
        doing_warn = doing_over_limit(user, org)
    return {
        "date": day,
        "items": items,
        "focus": next((t for t in items if t.is_open), None),
        "done_today": done_today,
        "auto_pull_days": user.auto_pull_days,
        "counts": counts,
        "doing_warn": doing_warn,
    }


# ---------- 내 태스크 · 검색 ----------


def _due_preds(today: date) -> dict:
    monday, sunday = week_bounds(today)
    return {
        "overdue": lambda t: t.due_date is not None and t.due_date < today,
        "today": lambda t: t.due_date == today,
        "week": lambda t: t.due_date is not None and today < t.due_date <= sunday,
        "this_week": lambda t: t.due_date is not None and monday <= t.due_date <= sunday,
        "later": lambda t: t.due_date is not None and t.due_date > sunday,
        "none": lambda t: t.due_date is None,
    }


def me_view(
    user,
    *,
    member=None,
    group="due",
    sort="due",
    due="",
    project=None,
    status="",
    priority="",
) -> dict:
    """내 태스크 화면 데이터. member: None=나, 0=조직 전체, User=다른 팀원.
    group: due/project/status, "none"이면 묶지 않고 한 목록. sort: SORT_OPTIONS 코드.
    반환: {title, hint, groups, read_only, completion}
    groups[i]: {title, count, empty_text, flat, tasks, projects:[{project, done, total, pct, tasks}]}
    flat이면 tasks를 그대로, 아니면 projects의 하위 묶음으로 그린다."""
    today = today_kst()
    preds = _due_preds(today)
    _grace_cache: dict[int, int] = {}

    def _overdue(t):
        if t.due_date is None:
            return False
        grace = _grace_cache.setdefault(
            t.project_id, S.effective("task.overdue_grace_days", project=t.project)
        )
        return t.due_date < today - timedelta(days=grace)

    preds["overdue"] = _overdue
    completion = status in ("done_today", "done_7d")
    base = visible_tasks(user).filter(project__is_archived=False)
    if member is None:
        base = base.filter(assignee=user)
    elif not isinstance(member, int):
        base = base.filter(assignee=member)
    if completion:
        first = today if status == "done_today" else today - timedelta(days=6)
        start, _ = kst_day_range(first)
        _, end = kst_day_range(today)
        base = base.filter(status="done", completed_at__gte=start, completed_at__lt=end)
    else:
        base = base.filter(status__in=Task.OPEN)
    qs = base
    if project is not None:
        qs = qs.filter(project=project)
    if status and not completion:
        qs = qs.filter(status=status)
    if priority in Task.TIERS:
        lo, hi = Task.TIERS[priority]
        qs = qs.filter(priority__gte=lo, priority__lte=hi)
    # 정렬은 묶기 전에 한 번. 하위 묶음은 이 순서를 걸러 쓰므로 그룹 안에서도 같은 순서다
    keys = {"priority": _rank, "updated": lambda t: (-t.updated_at.timestamp(), -t.pk)}
    tasks = sorted(qs, key=keys.get(sort, by_due))
    if due in preds:
        tasks = [t for t in tasks if preds[due](t)]

    def projects_of(ts):
        seen = {}
        for t in ts:
            seen.setdefault(t.project_id, t.project)
        return sorted(seen.values(), key=lambda p: p.name)

    def grp(title, pred, empty_text="", flat=False):
        ts = [t for t in tasks if pred(t)]
        g = {
            "title": title,
            "tasks": ts,
            "count": len(ts),
            "empty_text": empty_text,
            "flat": flat,
            "projects": [],
        }
        if not flat:
            for p in projects_of(ts):
                st = project_stats(p)
                pct = round(st["done"] / st["total"] * 100) if st["total"] else 0
                g["projects"].append(
                    {
                        "project": p,
                        "done": st["done"],
                        "total": st["total"],
                        "pct": pct,
                        "tasks": [t for t in ts if t.project_id == p.pk],
                    }
                )
        return g

    def eq(field, value):
        return lambda t: getattr(t, field) == value

    if completion:
        title = "오늘 완료" if status == "done_today" else "지난 7일 완료"
        groups = [grp(title, lambda t: True, "완료한 태스크가 없습니다.", flat=True)]
    elif group == "none":
        # 묶음 해제. 묶인 화면과 같은 정렬 순서라 토글해도 행이 섞이지 않는다
        groups = [grp("미완료", lambda t: True, flat=True)] if tasks else []
    elif group == "project":
        groups = [grp(p.name, eq("project_id", p.pk), flat=True) for p in projects_of(tasks)]
    elif group == "status":
        groups = [
            grp(label, eq("status", code)) for code, label in Task.STATUSES if code in Task.OPEN
        ]
        groups = [g for g in groups if g["count"]]
    else:
        groups = [
            grp("기한 초과", preds["overdue"], "기한 초과 태스크 없음"),
            grp("오늘 마감", preds["today"], "오늘 마감 태스크 없음"),
            grp("이번 주 마감", preds["week"], "이번 주 마감 태스크 없음"),
            grp("그 이후", preds["later"]),
            grp("기한 미정", preds["none"]),
        ]
        groups = [g for g in groups if g["count"] or (g["empty_text"] and not due)]
    if not groups:
        groups = [
            {
                "title": "결과 없음",
                "tasks": [],
                "count": 0,
                "empty_text": "조건에 맞는 태스크가 없습니다.",
                "flat": True,
                "projects": [],
            }
        ]

    if member is None:
        title = "내 태스크"
    elif isinstance(member, int):
        title = "조직 전체 태스크"
    else:
        title = f"{member.display_name}의 태스크"
    hint = f"{'완료' if completion else '미완료'} {base.count()}건 · 결과 {len(tasks)}건"
    if member is not None:
        hint += " · 보기 전용"
    return {
        "title": title,
        "hint": hint,
        "groups": groups,
        "read_only": member is not None,
        "completion": completion,
    }


def search(user, q: str, *, include_closed=False, include_archived=False):
    q = (q or "").strip()
    qs = visible_tasks(user)
    if not include_closed:
        qs = qs.filter(status__in=Task.OPEN)
    if not include_archived:
        qs = qs.filter(project__is_archived=False)
    if not q:
        return qs.none()
    cond = Q(title__icontains=q) | Q(project__name__icontains=q)
    num = q.upper().replace("TASK-", "")
    # isdigit()은 '²' 같은 문자에도 True다. int()가 받는 것은 isdecimal()뿐이다.
    if num.isdecimal():
        cond |= Q(pk=int(num))
    return qs.filter(cond).order_by("-id")[:100]
