from datetime import date, timedelta

from django.db import IntegrityError, transaction
from django.db.models import Exists, F, Max, OuterRef, Q
from django.db.models.functions import Coalesce
from django.utils import timezone

from accounts.models import IdempotencyKey, User
from common.dates import kst_day_range, overdue_before, today_kst, week_bounds
from common.errors import ConflictError, Forbidden, ServiceError
from orgs.models import OrgMembership
from orgs.services import ai_denied, is_admin, is_member, require_admin
from orgs.settings import effective
from projects.models import Project
from projects.services import can_view_project, is_owner, project_stats_bulk, visible_projects

from . import work_requests as wr
from .models import ChangeLog, ChecklistItem, Link, Task, TaskProject, TodayItem

# 자동 저장되는 부속 텍스트. version·ChangeLog 없음.
TEXT_FIELDS = ("title", "description", "done_when", "next_action", "notes")
TEXT_MAX = {"title": 200, "done_when": 300, "next_action": 200}
# 낙관적 잠금이 걸리는 팀 데이터
LOCKED_FIELDS = {
    "assignee",
    "priority",
    "due_date",
    "no_due_reason",
    "project",
    "stop_reason",
    "reviewer",
}
EDITABLE = LOCKED_FIELDS | set(TEXT_FIELDS)
TRACKED = ("assignee", "due_date", "project", "priority", "stop_reason", "reviewer")

NO_DUE_FOR_DOING = "목표 기한이 없어 진행 중으로 바꿀 수 없습니다. 기한을 먼저 정해 주세요."

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
# "없음"을 명시적으로 둔다 — 눌린 버튼이 하나도 없는 상태를 "분류 안 함"으로 읽어내게 하지 않는다.
GROUP_OPTIONS = [
    ("due", "기한별"),
    ("project", "프로젝트별"),
    ("status", "상태별"),
    ("none", "없음"),
]
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
    if not can_view_project(actor, project):
        raise ServiceError({"project": "볼 수 없는 프로젝트입니다."})


ASSIGNEE_CANT_SEE = "담당자가 볼 수 없는 프로젝트입니다. 담당 팀에 넣거나 공개 범위를 바꾸세요."


REVIEWER_CANT_SEE = "검토자가 볼 수 없는 프로젝트입니다. 담당 팀에 넣거나 공개 범위를 바꾸세요."


def can_see(user, project) -> bool:
    """공개 프로젝트는 조직 멤버 검사로 충분하다 — 비공개일 때만 가시성 질의를 한다."""
    return project.visibility == "org" or can_view_project(user, project)


def _require_viewer(assignee, project):
    """비공개 프로젝트(IMPL-PLAN-7 F)의 담당자는 그 프로젝트를 볼 수 있어야 한다."""
    if not can_see(assignee, project):
        raise ServiceError({"assignee": ASSIGNEE_CANT_SEE})


def _ai_check(org, key: str, action: str, source: str, field: str):
    """source가 mcp일 때만 본다. ai.enabled가 꺼졌거나 그 키가 deny면 ServiceError."""
    if source != "mcp":
        return
    if not effective("ai.enabled", org=org) or effective(key, org=org) == "deny":
        raise ServiceError({field: ai_denied(action)})


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
    source,
    check_assignee=True,
    check_priority=True,
    reviewer=None,
    check_reviewer=False,
    is_template=False,
    task=None,
):
    """check_assignee=False면 담당자가 조직의 활성 멤버인지 보지 않는다.

    담당자를 바꾸지 않는 수정에는 이 검사를 걸지 않는다. 담당자가 조직에서 빠지거나
    비활성이 되면(멤버 관리 화면의 [제거]) 그 태스크의 중요도·기한조차 못 고치게 되고,
    화면에는 이미 나간 사람 이름이 담긴 오류만 나온다.

    actor·source는 `task.priority_cap`(등급 판정)과 `ai.priority_cap`(source=="mcp")에 쓴다.
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
    elif check_priority:
        # 바꾸지 않은 중요도에는 상한을 다시 묻지 않는다. 관리자가 9로 둔 태스크의 기한을
        # 일반 멤버가 고치는 것까지 막히기 때문이다(담당자의 check_assignee와 같은 이유).
        cap = effective("task.priority_cap", org=project.org, project=project)
        if (
            cap
            and priority > cap
            and not (is_owner(actor, project) or is_admin(actor, project.org))
        ):
            errors["priority"] = f"중요도 {cap} 초과는 프로젝트 관리자만 정할 수 있습니다."
        ai_cap = effective("ai.priority_cap", org=project.org)
        if source == "mcp" and ai_cap and priority > ai_cap:
            errors["priority"] = f"AI는 중요도 {ai_cap}을(를) 넘겨 지정할 수 없습니다."
    if status == "doing" and due_date is None:
        errors["due_date"] = NO_DUE_FOR_DOING
    elif status in Task.OPEN and due_date is None:
        if not is_template and effective("task.due_required", org=project.org, project=project):
            errors["due_date"] = "기한을 반드시 정해야 합니다. 기한 미정 사유로 대신할 수 없습니다."
        elif not (no_due_reason or "").strip():
            errors["no_due_reason"] = "기한이 없으면 사유를 입력하세요."
    reason = (stop_reason or "").strip()
    if status == "blocked" and not reason:
        errors["stop_reason"] = "막힘 사유를 입력하세요."
    if status not in Task.STOPPED and reason:
        errors["stop_reason"] = "일시정지·막힘 상태에서만 사유를 둘 수 있습니다."
    if reviewer is not None:
        if check_reviewer and (not reviewer.is_active or not is_member(reviewer, project.org)):
            errors["reviewer"] = "검토자는 이 조직의 활성 멤버여야 합니다."
        elif check_reviewer and not (
            can_see(reviewer, project) if task is None else _sees_task(reviewer, task, project)
        ):
            errors["reviewer"] = REVIEWER_CANT_SEE
        elif reviewer == assignee and not effective(
            "task.self_review", org=project.org, project=project
        ):
            errors["reviewer"] = "본인 검토가 꺼져 있어 담당자를 검토자로 지정할 수 없습니다."
    if errors:
        raise ServiceError(errors)


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
    """user가 볼 수 있는 태스크 queryset. 열람 범위 = 주 프로젝트 ∪ 확정(active) 연결 프로젝트.

    distinct가 아니라 Exists라 count()·annotate가 그대로 맞는다(visible_projects와 같은 선택).
    # ponytail: visible_projects 서브쿼리를 두 번 품는다. 느려지면 요청당 id 목록으로 물질화한다.
    """
    vp = visible_projects(user)
    linked = TaskProject.objects.filter(task_id=OuterRef("pk"), status="active", project__in=vp)
    return Task.objects.filter(Q(project__in=vp) | Exists(linked)).select_related(
        "project", "project__org", "assignee", "reviewer"
    )


def get_visible_task(user, task_id: int) -> Task | None:
    return visible_tasks(user).filter(pk=task_id).first()


def can_view_task(user, task) -> bool:
    """태스크 단위 접근 검사는 이 한 곳이다(주 ∪ 확정 연결)."""
    return visible_tasks(user).filter(pk=task.pk).exists()


def tasks_of(project):
    """프로젝트 기준 목록: 주 프로젝트가 이것이거나 이것에 확정 연결된 태스크.
    project를 볼 수 있는 사람은 정의상 이 태스크들을 모두 볼 수 있다."""
    linked = TaskProject.objects.filter(task_id=OuterRef("pk"), project=project, status="active")
    return Task.objects.filter(Q(project=project) | Exists(linked))


def tasks_visible_in(org, viewer=None):
    """조직 집계용 태스크(태스크당 한 행). viewer가 None(봇·조직 채널 게시)이면 공개 프로젝트에
    주로 있거나 확정 연결된 것만."""
    if viewer is not None:
        return visible_tasks(viewer).filter(project__org=org)
    public = TaskProject.objects.filter(
        task_id=OuterRef("pk"), status="active", project__visibility="org"
    )
    return Task.objects.filter(project__org=org).filter(
        Q(project__visibility="org") | Exists(public)
    )


def _require_task(actor, task):
    """태스크에 쓰는 함수의 입구. _require_member의 태스크판 — 연결 프로젝트로 보는 사람도 통과한다."""
    if actor is None:
        return
    if not is_member(actor, task.project.org):
        raise ServiceError({"project": "이 조직의 멤버가 아닙니다."})
    if task.project.visibility != "org" and not can_view_task(actor, task):
        raise ServiceError({"project": "볼 수 없는 프로젝트입니다."})


def _sees_task(user, task, project) -> bool:
    """project가 주 프로젝트 그대로면 태스크 열람(주 ∪ 연결)으로, 옮기는 중이면 새 프로젝트로 본다."""
    if project.pk != task.project_id:
        return can_see(user, project)
    return project.visibility == "org" or can_view_task(user, task)


def by_due(t):
    """기한 오름차순, 기한 없음은 뒤로, 같으면 id."""
    return (t.due_date or date.max, t.pk)


# ---------- 생성·수정 ----------


IDEM_REUSED = "이미 다른 작업에 쓴 키입니다."


def _idem_replay(actor, existing, project):
    """같은 Idempotency-Key 재요청이면 처음 만든 태스크를 돌려준다.

    대상 프로젝트가 다르거나 지금은 볼 수 없는 태스크면(공개 범위가 바뀌어 권한을 잃은 경우)
    내용을 돌려주지 않고 거절한다 — 키로 비공개 태스크를 꺼내 볼 수 없어야 한다.
    """
    if existing.project_id != project.pk or not can_view_project(actor, existing.project):
        raise ServiceError({"idempotency_key": IDEM_REUSED})
    return existing


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
    notify_assignee=True,
    linked_project_ids=(),
    confirm_widening=False,
) -> Task:
    """notify_assignee=False: 호출부가 담당자에게 따로 알린다(GitHub 재개는 담당 요청 한 통).

    linked_project_ids: 만들자마자 연결할 프로젝트. 열람 확대가 있으면 confirm_widening 없이는
    WideningRequired로 생성 전체가 롤백되고, 있으면 그 연결은 승인 대기로 남는다(link_project)."""
    _require_member(actor, project)
    _ai_check(project.org, "ai.create_task", "태스크 만들기", source, "title")
    if idempotency_key:
        idempotency_key = idempotency_key[:100]
        hit = IdempotencyKey.objects.filter(
            user=actor, key=idempotency_key, target_type="task"
        ).first()
        if hit:
            existing = Task.objects.filter(pk=hit.target_id).select_related("project").first()
            if existing is not None:
                return _idem_replay(actor, existing, project)
            hit.delete()  # 대상이 지워진 키는 새로 만든다
    assignee = assignee or actor
    _require_viewer(assignee, project)
    # 남에게 맡길 권한이 없으면 일단 만든 사람이 맡고, 받을 사람에게 담당 요청을 보낸다.
    ask = None
    if not wr.can_assign_directly(actor, assignee, project.org, source):
        ask, assignee = assignee, actor
    if priority is None:
        priority = effective("task.default_priority", org=project.org, project=project)
    if (
        effective("task.require_done_when", org=project.org, project=project)
        and not (done_when or "").strip()
    ):
        raise ServiceError({"done_when": "완료 조건을 입력해야 합니다."})
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
        source=source,
    )
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
    if ask is not None:
        wr.request_assign(task, ask, actor, source)
    elif assignee != actor and notify_assignee:
        wr.notify_assigned(task, actor)
    if idempotency_key:
        # 같은 키로 동시에 두 번 오면 둘 다 위의 조회를 비켜 간다. 유니크 충돌이 난 쪽은
        # 자기 태스크를 롤백하고 먼저 만들어진 것을 돌려준다.
        try:
            with transaction.atomic():
                IdempotencyKey.objects.create(
                    user=actor, key=idempotency_key, target_type="task", target_id=task.pk
                )
        except IntegrityError:
            hit = IdempotencyKey.objects.get(user=actor, key=idempotency_key, target_type="task")
            transaction.set_rollback(True)
            return _idem_replay(actor, Task.objects.get(pk=hit.target_id), project)
    for pid in dict.fromkeys(linked_project_ids or ()):
        target = Project.objects.filter(pk=pid, org_id=project.org_id).first()
        if target is None:
            raise ServiceError({"linked_project_ids": f"프로젝트 {pid}을(를) 찾을 수 없습니다."})
        link_project(
            task, target, actor=actor, source=source, token=token, confirm_widening=confirm_widening
        )
    return task


def update_text(task, field: str, value: str, *, actor, source: str = "web") -> Task:
    """제목·설명·완료 조건·다음 행동·진행 메모 자동 저장. version·ChangeLog를 건드리지 않는다.
    # ponytail: 부속 텍스트는 last-write-wins. 동시 편집 보호가 필요해지면 필드별 갱신 시각 비교로.
    """
    _require_task(actor, task)
    if field not in TEXT_FIELDS:
        raise ServiceError({field: "수정할 수 없는 항목입니다."})
    _ai_check(task.project.org, "ai.edit_text", "본문 고치기", source, field)
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
    reason: str = "",
) -> Task:
    """팀 데이터 필드는 version 검사 후 갱신·이력 기록. TEXT_FIELDS는 update_text로 보낸다.

    reason: 담당자·기한 변경 사유. 조직 설정이 요구할 때만 필수이고, 있으면 이력 note에 남는다.
    """
    _require_task(actor, task)
    unknown = set(changes) - EDITABLE
    if unknown:
        raise ServiceError({k: "수정할 수 없는 항목입니다." for k in sorted(unknown)})
    for f in TEXT_FIELDS:
        if f in changes:
            update_text(task, f, changes[f], actor=actor, source=source)
    changes = {f: v for f, v in changes.items() if f in LOCKED_FIELDS}
    if not changes:
        return task
    reason = (reason or "").strip()[:300]
    if "assignee" in changes:
        _ai_check(task.project.org, "ai.change_assignee", "담당자 바꾸기", source, "assignee")
        needs = effective("task.assignee_change_reason", org=task.project.org, project=task.project)
        if needs and not reason:
            raise ServiceError({"reason": "담당자 변경 사유를 입력하세요."})
    if "due_date" in changes:
        _ai_check(task.project.org, "ai.change_due", "기한 바꾸기", source, "due_date")
        needs = effective("task.due_change_reason", org=task.project.org, project=task.project)
        if needs and not reason:
            raise ServiceError({"reason": "기한 변경 사유를 입력하세요."})
    if "priority" in changes:
        _ai_check(task.project.org, "ai.change_priority", "중요도 바꾸기", source, "priority")
    ask = None
    if changes.get("assignee") is not None and changes["assignee"] != task.assignee:
        # 담당 요청으로 돌기 전에 막는다 — 못 보는 사람에게 요청 알림이 가면 안 된다.
        # 주 프로젝트를 그대로 두면 연결 프로젝트로 보는 사람도 담당할 수 있다(can_view_task).
        if not _sees_task(changes["assignee"], task, changes.get("project", task.project)):
            raise ServiceError({"assignee": ASSIGNEE_CANT_SEE})
    if (
        "assignee" in changes
        and changes["assignee"] != task.assignee
        and not wr.can_assign_directly(actor, changes["assignee"], task.project.org, source)
    ):
        ask = changes.pop("assignee")
        wr.request_assign(task, ask, actor, source, note=reason)
    new = {f: changes.get(f, getattr(task, f)) for f in LOCKED_FIELDS}
    if "project" in changes:
        _require_member(actor, new["project"])
        if new["project"].org_id != task.project.org_id:
            raise ServiceError({"project": "다른 조직의 프로젝트로 옮길 수 없습니다."})
        if new["assignee"] is not None:
            _require_viewer(new["assignee"], new["project"])
        # 검토자도 담당자와 같은 규칙: 옮길 프로젝트를 못 보면 이동을 거부한다.
        if new["reviewer"] is not None and not can_see(new["reviewer"], new["project"]):
            raise ServiceError({"reviewer": REVIEWER_CANT_SEE})
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
        actor=actor,
        source=source,
        check_assignee="assignee" in changes,
        check_priority="priority" in changes,
        reviewer=new["reviewer"],
        check_reviewer="reviewer" in changes,
        is_template=task.is_template,
        task=task,
    )
    old = {f: getattr(task, f) for f in LOCKED_FIELDS}
    fields = {f: v for f, v in new.items() if v != old[f]}
    if not fields:
        return task
    _apply(task, expected_version, fields)
    if "project" in fields:
        # 문서는 같은 프로젝트의 태스크에만 걸린다(projects.docs.link_task). 옮기면 옛 프로젝트 문서
        # 연결을 끊는다 — 남겨 두면 공개 프로젝트에서 비공개 문서 제목이 보인다.
        task.docs.remove(
            *task.docs.filter(kind="doc", project__isnull=False).exclude(project_id=task.project_id)
        )
        # 새 주 프로젝트가 연결에 있었으면 그 연결은 지운다(주 ≠ 연결). 옛 주는 연결로 남기지 않는다.
        TaskProject.objects.filter(task=task, project=task.project).delete()
        _drop_stale_git_project(task)
    if "assignee" in fields:
        wr.drop_assign_requests(task, keep_user=ask)
        if task.assignee != actor:
            wr.notify_assigned(task, actor)
    for f in TRACKED:
        if f in fields:
            _log(
                task,
                f,
                old[f],
                fields[f],
                actor,
                source,
                token,
                note=reason,
                external_actor=external_actor,
            )
    return task


def can_reject(actor, task) -> bool:
    """검토 대기를 시작 전·진행 중으로 되돌릴(반려) 수 있는가.

    지정 검토자가 있으면 그 사람·조직 관리자·프로젝트 관리자, 그리고 담당자(검토 요청 철회)만.
    검토자가 없으면 예전처럼 프로젝트를 볼 수 있는 멤버 누구나. 볼 수 있는지는 transition 입구
    (_require_member → can_view_project)가 먼저 본다 — 비공개 프로젝트를 못 보는 검토자는 거기서 막힌다.
    """
    if task.status != "review":
        return False
    if not task.reviewer_id:
        return True
    return (
        actor.pk in (task.reviewer_id, task.assignee_id)
        or is_admin(actor, task.project.org)
        or is_owner(actor, task.project)
    )


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
    - 재개·취소 사유 필수, 동시 진행 한도, 검토 대기 필수는 조직 설정이 켜야 걸린다(§4.1).
    """
    _require_task(actor, task)
    if task.is_template:
        raise ServiceError({"status": "템플릿은 상태를 바꾸지 않습니다. 회차를 만들어 진행하세요."})
    labels = dict(Task.STATUSES)
    if new_status not in labels:
        raise ServiceError({"status": "알 수 없는 상태입니다."})
    if new_status == task.status:
        return task
    if task.is_closed and new_status not in ("todo", "doing"):
        raise ServiceError(
            {
                "status": f"{labels[task.status]}에서 {labels[new_status]}(으)로 바꿀 수 없습니다. "
                "먼저 시작 전이나 진행 중으로 다시 여세요."
            }
        )
    org = task.project.org
    reopening = task.is_closed and new_status in ("todo", "doing")
    closing = new_status in ("done", "cancelled")
    if reopening and task.project.is_archived:
        raise ServiceError({"status": "보관된 프로젝트의 태스크는 다시 열 수 없습니다."})
    if reopening:
        _ai_check(org, "ai.reopen_task", "완료·취소 되돌리기", source, "status")
    elif closing:
        _ai_check(org, "ai.close_task", "완료·취소 처리", source, "status")
    else:
        _ai_check(org, "ai.transition_open", "미완료 상태 바꾸기", source, "status")
    reason = (reason or "").strip()[:300]
    if reopening and effective("task.reopen_reason_required", org=org, project=task.project):
        if not reason:
            raise ServiceError({"reason": "재개 사유를 입력하세요."})
    rejecting = task.status == "review" and new_status in ("todo", "doing")
    if rejecting and actor is not None and not can_reject(actor, task):
        raise ServiceError(
            {
                "status": f"검토자 {task.reviewer.display_name}님 또는 프로젝트 관리자만 "
                "반려할 수 있습니다."
            }
        )
    if (
        rejecting
        and effective("task.reject_reason_required", org=org, project=task.project)
        and not reason
    ):
        raise ServiceError({"reason": "반려 사유를 입력하세요."})
    if new_status == "doing" and task.due_date is None:
        raise ServiceError({"due_date": NO_DUE_FOR_DOING})
    if new_status == "doing":
        limit = effective("task.doing_limit", org=org)
        if limit and effective("task.doing_limit_mode", org=org) == "block":
            doing = (
                Task.objects.filter(assignee=task.assignee, project__org=org, status="doing")
                .exclude(pk=task.pk)
                .count()
            )
            if doing >= limit:
                raise ServiceError(
                    {
                        "status": f"동시 진행 한도 {limit}건을 넘었습니다. 다른 태스크를 먼저 정리해 주세요."
                    }
                )
    if new_status == "blocked" and not reason:
        raise ServiceError({"stop_reason": "막힘 사유를 입력하세요."})
    if new_status == "cancelled":
        if effective("task.cancel_reason_required", org=org, project=task.project) and not reason:
            raise ServiceError({"reason": "취소 사유를 입력하세요."})
    if new_status == "done":
        if (
            effective("task.review_required", org=org, project=task.project)
            and task.status != "review"
        ):
            raise ServiceError({"status": "검토 대기를 거쳐야 완료할 수 있습니다."})
        if (
            task.status == "review"
            and actor is not None
            and actor == task.assignee
            and not effective("task.self_review", org=org, project=task.project)
        ):
            raise ServiceError(
                {"status": "본인이 담당한 태스크는 본인이 검토를 완료 처리할 수 없습니다."}
            )
        # 지정 검토자가 있으면 그 사람이나 관리자만 완료한다. actor가 None(GitHub 머지)이면
        # 검토는 PR에서 끝난 것이므로 막지 않는다.
        if (
            task.status == "review"
            and task.reviewer_id
            and actor is not None
            and actor.pk != task.reviewer_id
            and not is_admin(actor, org)
            and not is_owner(actor, task.project)
        ):
            raise ServiceError(
                {
                    "status": f"검토자 {task.reviewer.display_name}님 또는 프로젝트 관리자만 "
                    "완료 처리할 수 있습니다."
                }
            )
    # 같은 상태 재요청은 위에서 돌아갔다. 검토 대기 경과일은 이 시각부터 잰다.
    fields = {"status": new_status, "status_since": timezone.now()}
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
    if closing:
        wr.drop_assign_requests(task)
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
def duplicate_task(
    task,
    *,
    actor,
    source,
    token=None,
    title=None,
    due_date=None,
    no_due_reason="",
    assignee=None,
    idempotency_key=None,
    notify_assignee=True,
) -> Task:
    """복제·회차·변형 공통. 설명·완료 조건·다음 행동·중요도·체크리스트(전부 미완료)·링크·문서 연결을
    복사한다. 첨부 파일은 복사하지 않는다(회차는 새 파일을 만든다). 상태는 todo, 템플릿 아님.
    parent = task.parent or task (계열은 평평하다). create_task를 부르므로 ai.create_task·담당 규칙이 그대로 걸린다."""
    new = create_task(
        project=task.project,
        title=title or task.title,
        actor=actor,
        source=source,
        token=token,
        assignee=assignee or task.assignee,
        description=task.description,
        done_when=task.done_when,
        next_action=task.next_action,
        priority=task.priority,
        due_date=due_date,
        no_due_reason=no_due_reason,
        idempotency_key=idempotency_key,
        notify_assignee=notify_assignee,
    )
    if new.parent_id is not None:
        return new  # 같은 Idempotency-Key 재요청 — 이미 복사까지 끝난 회차다
    root = task.parent or task
    reviewer = task.reviewer if task.reviewer_id and task.reviewer != new.assignee else None
    Task.objects.filter(pk=new.pk).update(parent=root, reviewer=reviewer)
    ChecklistItem.objects.bulk_create(
        ChecklistItem(task=new, text=i.text, position=i.position) for i in task.checklist.all()
    )
    Link.objects.bulk_create(
        Link(task=new, title=lk.title, url=lk.url, kind=lk.kind, created_by=actor)
        for lk in task.links.all()
    )
    new.docs.set(task.docs.all())
    # 확정 연결만 복사한다 — 같은 열람자 집합이라 확대 재검사가 필요 없다. 승인 대기는 복사하지 않는다.
    TaskProject.objects.bulk_create(
        TaskProject(task=new, project_id=lk.project_id, created_by=actor)
        for lk in task.project_links.filter(status="active")
    )
    new.refresh_from_db()
    _log(new, "parent", "", root.number, actor, source, token, note=f"{task.number}에서 복제")
    return new


def set_template(task, on: bool, *, actor, source="web", token=None) -> Task:
    """템플릿으로 두거나 해제한다. 템플릿은 상태를 바꾸지 않고 기한이 없으며 집계에서 빠진다."""
    _require_task(actor, task)
    _ai_check(task.project.org, "ai.create_task", "템플릿 바꾸기", source, "is_template")
    on = bool(on)
    if on == task.is_template:
        return task
    if on and task.status != "todo":
        raise ServiceError({"is_template": "시작 전 상태에서만 템플릿으로 바꿀 수 있습니다."})
    fields = {"is_template": on}
    if on:
        fields.update(due_date=None, no_due_reason="템플릿")
    _apply(task, task.version, fields)
    _log(task, "is_template", not on, on, actor, source, token)
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
    _require_task(actor, task)
    _ai_check(task.project.org, "ai.change_due", "기한 바꾸기", source, "due_date")
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


@transaction.atomic
def delete_task(task, *, actor, source: str = "web") -> None:
    """조직 관리자만. 의사결정 기록이 있는 태스크는 보존한다."""
    require_admin(actor, task.project.org)
    _ai_check(task.project.org, "ai.delete", "삭제", source, "task")
    if task.decision_records.exists():
        raise ServiceError(
            {
                "task": "의사결정 기록이 있는 태스크는 삭제할 수 없습니다. 취소하거나 프로젝트를 보관해 주세요."
            }
        )
    ChangeLog.objects.create(
        target_type="org",
        target_id=task.project.org_id,
        field="delete",
        old_value="",
        new_value=f"{task.number} {task.title}",
        actor=actor,
        source=source,
    )
    wr.drop_assign_requests(task)
    from .attachments import purge_files

    purge_files(task.attachments.all())  # 첨부 행은 CASCADE, 파일은 커밋 뒤에 지운다
    task.delete()


# ---------- 링크 ----------


def add_link(*, actor, title, url, kind="doc", task=None, project=None) -> Link:
    if (task is None) == (project is None):
        raise ServiceError({"target": "태스크 또는 프로젝트 중 하나에만 연결합니다."})
    if task is not None:
        _require_task(actor, task)
    else:
        _require_member(actor, project)
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
    if link.task_id:
        _require_task(actor, link.task)
    else:
        _require_member(actor, link.project)
    link.delete()


# ---------- 체크리스트 ----------


@transaction.atomic
def replace_checklist(
    task, items: list[dict], *, actor, source: str = "web"
) -> list[ChecklistItem]:
    """items: [{'text': str, 'is_done': bool}, ...]. 전체 교체."""
    _require_task(actor, task)
    _ai_check(task.project.org, "ai.edit_text", "본문 고치기", source, "checklist")
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
    _require_task(actor, task)
    text = (text or "").strip()
    if not text:
        raise ServiceError({"text": "내용을 입력하세요."})
    pos = (task.checklist.aggregate(m=Max("position"))["m"] or 0) + 1
    return ChecklistItem.objects.create(task=task, text=text[:200], position=pos)


def checklist_toggle(item, *, actor) -> ChecklistItem:
    _require_task(actor, item.task)
    item.is_done = not item.is_done
    item.save(update_fields=["is_done"])
    return item


def checklist_delete(item, *, actor):
    _require_task(actor, item.task)
    item.delete()


def checklist_move(item, direction: str, *, actor):
    """direction: 'up' | 'down'. 이웃과 position을 맞바꾼다."""
    _require_task(actor, item.task)
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
    return TodayItem.objects.filter(user=user, date=day, task__project__in=visible_projects(user))


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
    _require_task(user, task)
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
        .select_related("task__project__org", "task__assignee", "task__reviewer")
        .order_by("position", "id")
    ]
    # 조직에서 빠진 뒤에도 담당으로 남은 태스크가 새는 것을 막는다(다른 읽기 경로와 같은 범위).
    mine = visible_tasks(user).filter(assignee=user, is_template=False)
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
        # 프로젝트별 유예를 보므로 쿼리셋 필터가 아니라 파이썬에서 태스크마다 판정한다.
        "overdue": sum(
            1
            for t in my_open
            if t.due_date is not None and t.due_date < overdue_before(t.project.org, t.project)
        ),
        "review": my_open.filter(status="review").count(),
        "blocked": my_open.filter(status="blocked").count(),
    }
    return {
        "date": day,
        "items": items,
        "focus": next((t for t in items if t.is_open), None),
        "done_today": done_today,
        "auto_pull_days": user.auto_pull_days,
        "counts": counts,
    }


# ---------- 내 태스크 · 검색 ----------


def _due_preds(today: date) -> dict:
    monday, sunday = week_bounds(today)
    return {
        # 초과는 today가 아니라 프로젝트별 유예(task.overdue_grace_days)를 더한 기준일로 본다.
        "overdue": lambda t: (
            t.due_date is not None and t.due_date < overdue_before(t.project.org, t.project)
        ),
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
    completion = status in ("done_today", "done_7d")
    base = visible_tasks(user).filter(project__is_archived=False, is_template=False)
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

    stats = {}  # 프로젝트 묶음 진행률. 처음 필요할 때 한 번에 센다

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
                if not stats:
                    stats.update(project_stats_bulk(projects_of(tasks)))
                st = stats[p.pk]
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
        # 빈 기한 구간을 큰 카드로 먼저 나열하면 실제 태스크가 화면 아래로 밀린다.
        # 결과가 하나도 없을 때는 아래의 단일 '결과 없음' 상태가 같은 피드백을 맡는다.
        groups = [g for g in groups if g["count"]]
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
    qs = visible_tasks(user).filter(is_template=False)
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


# 결과 선반 기간 필터. (코드, 화면 표기, 일수 — None은 전체)
SHELF_PERIODS = [("7", "최근 7일", 7), ("30", "최근 30일", 30), ("all", "전체", None)]


def closed_tasks(user, project, status: str, *, period: str = "all", q: str = ""):
    """결과 선반: 프로젝트의 완료·취소 태스크를 닫힌 시각 최신순으로.

    닫힌 시각은 완료일, 취소는 completed_at이 비므로 마지막 변경 시각으로 본다.
    visible_tasks 범위를 그대로 따른다. status는 Task.CLOSED 중 하나여야 한다.
    """
    if status not in Task.CLOSED:
        raise ValueError(status)
    qs = (
        visible_tasks(user)
        .filter(project=project, is_template=False, status=status)
        .annotate(closed_at=Coalesce("completed_at", "updated_at"))
    )
    days = {c: d for c, _, d in SHELF_PERIODS}.get(period)
    if days:
        qs = qs.filter(closed_at__gte=timezone.now() - timedelta(days=days))
    q = (q or "").strip()
    if q:
        cond = Q(title__icontains=q)
        num = q.upper().replace("TASK-", "")
        if num.isdecimal():
            cond |= Q(pk=int(num))
        qs = qs.filter(cond)
    return qs.order_by("-closed_at", "-id")


# ---------- 연결 프로젝트(IMPL-PLAN-11 §3, 결정 2-1: 열람 확대 = 관리자 승인) ----------


class WideningRequired(ServiceError):
    """열람자가 늘어나는 연결인데 호출자가 그것을 알고 요청한다는 표시(confirm_widening)가 없다.
    API는 400 `visibility_widening`, MCP는 거부 + 사용자 허락 안내로 바꾼다."""

    def __init__(self, project, users):
        self.project, self.users = project, users
        super().__init__({"confirm": widening_message(project, users)})


def widening_message(project, users) -> str:
    names = ", ".join(u.display_name for u in users[:3])
    more = " 외" if len(users) > 3 else ""
    return (
        f"주의: '{project.name}' 프로젝트의 열람자 중 지금 이 태스크를 볼 수 없는 {len(users)}명"
        f"({names}{more})도 연결 뒤 이 태스크를 보게 됩니다. 이 연결은 관리자 승인 뒤에 확정됩니다."
    )


def viewer_ids(project) -> set[int]:
    """project를 볼 수 있는 활성 사용자 id. visible_projects의 조건을 사람 쪽에서 센 것."""
    ms = OrgMembership.objects.filter(org_id=project.org_id, user__is_active=True)
    if project.visibility != "org":
        ms = ms.filter(
            Q(role="admin")
            | Q(user__in=project.owners.all())
            | Q(user__team_memberships__team__projects=project)
        )
    return set(ms.values_list("user_id", flat=True))


def widening(task, project) -> list[User]:
    """project를 연결하면 새로 이 태스크를 보게 될 사람(주 ∪ 확정 연결의 열람자 밖).
    쿼리 몇 번, 연결할 때만 돈다."""
    current = [
        task.project,
        *Project.objects.filter(task_links__task=task, task_links__status="active"),
    ]
    if any(p.visibility == "org" for p in current):
        return []  # 이미 조직 전원이 본다
    seen = set().union(*(viewer_ids(p) for p in current))
    new = viewer_ids(project) - seen
    return list(User.objects.filter(pk__in=new).order_by("display_name", "pk"))


def can_approve_widening(user, task) -> bool:
    """열람 확대 승인자. 주 프로젝트가 비공개면 그 프로젝트 관리자·조직 관리자, 아니면 조직 관리자.
    판정은 이 함수 하나다(결정 2-1)."""
    if is_admin(user, task.project.org):
        return True
    return task.project.visibility != "org" and is_owner(user, task.project)


def _approvers(task):
    q = Q(org_memberships__org_id=task.project.org_id, org_memberships__role="admin")
    if task.project.visibility != "org":
        q |= Q(pk__in=task.project.owners.values("pk"))
    return User.objects.filter(q, is_active=True).distinct()


def _touch(task):
    """연결이 바뀌면 version·updated_at을 올린다 — SSE가 새 열람자 화면에 바로 알린다."""
    Task.objects.filter(pk=task.pk).update(version=F("version") + 1, updated_at=timezone.now())
    task.refresh_from_db()


def _drop_stale_git_project(task):
    """연동 프로젝트가 더는 {주} ∪ 연결에 없으면 끈다(§3.3)."""
    gp = task.git_project_id
    if gp and gp != task.project_id and not task.project_links.filter(project_id=gp).exists():
        Task.objects.filter(pk=task.pk).update(git_project=None)
        task.git_project_id = None


def _check_link_target(actor, task, project):
    _require_task(actor, task)
    if project.pk == task.project_id:
        raise ServiceError({"project": "주 프로젝트는 연결할 수 없습니다."})
    if project.org_id != task.project.org_id:
        raise ServiceError({"project": "다른 조직의 프로젝트는 연결할 수 없습니다."})
    if not can_view_project(actor, project):
        raise ServiceError({"project": "볼 수 없는 프로젝트입니다."})


@transaction.atomic
def link_project(task, project, *, actor, source="web", token=None, confirm_widening=False):
    """태스크를 project에 연결한다. 이미 있으면(승인 대기 포함) 그것을 돌려준다.

    열람자가 늘어나면: confirm_widening이 없으면 WideningRequired, 있으면 승인 대기(pending)로 남기고
    승인자에게 알린다. 승인 전에는 열람 범위에 들어가지 않는다. 요청자가 승인자여도 자동 승인하지
    않는다 — 승인은 approve_link 한 곳(사람만)이다.
    """
    _check_link_target(actor, task, project)
    if project.is_archived:
        raise ServiceError({"project": "보관된 프로젝트에는 연결할 수 없습니다."})
    existing = TaskProject.objects.filter(task=task, project=project).first()
    if existing is not None:
        return existing
    users = widening(task, project)
    if users and not confirm_widening:
        raise WideningRequired(project, users)
    link = TaskProject.objects.create(
        task=task,
        project=project,
        created_by=actor,
        widened=bool(users),
        status="pending" if users else "active",
    )
    if not users:
        _log(task, "projects", "", project.pk, actor, source, token, note="연결")
        _touch(task)
        return link
    _log(
        task,
        "projects",
        "",
        project.pk,
        actor,
        source,
        token,
        note=f"연결 승인 요청: 열람자 {len(users)}명 늘어남",
    )
    text = (
        f"🔐 {actor.display_name}님이 {task.number} {task.title}을(를) "
        f"'{project.name}' 프로젝트에 연결하려 합니다. 열람자 {len(users)}명이 늘어납니다.\n"
        f"승인·거절: {wr._link(f'/tasks/{task.pk}')}"
    )
    for u in _approvers(task):
        wr.notify(task.project.org, text, user=u)
    return link


@transaction.atomic
def unlink_project(task, project, *, actor, source="web", token=None) -> Task:
    """연결 해제(승인 대기 취소 포함). 연결할 수 있는 사람이 한다. 좁히는 것이라 확인 없음."""
    _check_link_target(actor, task, project)
    link = TaskProject.objects.filter(task=task, project=project).first()
    if link is None:
        raise ServiceError({"project": "연결된 프로젝트가 아닙니다."})
    link.delete()
    note = "승인 요청 취소" if link.status == "pending" else "연결 해제"
    _log(task, "projects", project.pk, "", actor, source, token, note=note)
    _drop_stale_git_project(task)
    _touch(task)
    return task


def _decide(link, actor, source):
    if source == "mcp":
        raise Forbidden({"approve": "열람 확대 승인·거절은 사람이 웹에서 합니다."})
    if not can_approve_widening(actor, link.task):
        msg = (
            "주 프로젝트가 비공개라 그 프로젝트 관리자나 조직 관리자만 승인할 수 있습니다."
            if link.task.project.visibility != "org"
            else "조직 관리자만 승인할 수 있습니다."
        )
        raise Forbidden({"approve": msg})
    if link.status != "pending":
        raise ServiceError({"approve": "승인 대기 중인 연결이 아닙니다."})


@transaction.atomic
def approve_link(link, *, actor, source="web", token=None) -> TaskProject:
    """승인 대기 연결을 확정한다. 이때부터 연결 프로젝트의 열람자가 태스크를 본다."""
    _decide(link, actor, source)
    task = link.task
    link.status, link.decided_by, link.decided_at = "active", actor, timezone.now()
    link.save(update_fields=["status", "decided_by", "decided_at"])
    _log(task, "projects", "", link.project_id, actor, source, token, note="열람 확대 승인")
    _touch(task)
    wr.notify(
        task.project.org,
        f"✅ {actor.display_name}님이 {task.number}의 '{link.project.name}' 연결을 승인했습니다.\n"
        f"{wr._link(f'/tasks/{task.pk}')}",
        user=link.created_by,
    )
    return link


@transaction.atomic
def reject_link(link, *, actor, source="web", token=None, reason="") -> None:
    """승인 대기 연결을 거절한다(행을 지우고 이력·알림을 남긴다)."""
    _decide(link, actor, source)
    task = link.task
    link.delete()
    reason = (reason or "").strip()[:150]
    note = f"열람 확대 거절: {reason}" if reason else "열람 확대 거절"
    _log(task, "projects", link.project_id, "", actor, source, token, note=note)
    why = f"\n> {reason}" if reason else ""
    wr.notify(
        task.project.org,
        f"↩️ {actor.display_name}님이 {task.number}의 '{link.project.name}' 연결 요청을 "
        f"거절했습니다.{why}\n{wr._link(f'/tasks/{task.pk}')}",
        user=link.created_by,
    )


def linked_projects(task, viewer) -> list[dict]:
    """viewer가 볼 수 있는 연결 프로젝트만(못 보는 연결은 개수도 숨긴다 — 비공개 이름 노출 방지)."""
    links = list(task.project_links.select_related("project").order_by("id"))
    if not links:
        return []
    ids = [lk.project_id for lk in links]
    shown = set(visible_projects(viewer).filter(pk__in=ids).values_list("pk", flat=True))
    return [
        {"id": lk.project_id, "name": lk.project.name, "status": lk.status}
        for lk in links
        if lk.project_id in shown
    ]
