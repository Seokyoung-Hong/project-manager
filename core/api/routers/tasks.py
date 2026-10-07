from datetime import date

from django.conf import settings
from django.db.models import Exists, F, OuterRef, Q
from django.utils.dateparse import parse_datetime
from ninja import Query, Router
from ninja.errors import HttpError

from accounts.models import User
from common.errors import ConflictError, ServiceError
from github import client as github_client
from github import writes as gh_writes
from github.client import GitHubError
from github.models import RepoIssue, TaskGitLink
from github.services import can_view_repo, continuation, task_repo, task_repo_state, user_token
from orgs.services import ai_denied
from orgs.settings import effective
from projects.services import can_view_project, visible_projects
from tasks.brief import task_brief
from tasks.models import ChangeLog, Task, TaskProject
from tasks.services import (
    WideningRequired,
    approve_link,
    create_task,
    delete_task,
    duplicate_task,
    extend_due,
    leaf_only,
    link_project,
    reject_link,
    replace_checklist,
    set_group,
    set_template,
    transition,
    unlink_project,
    update_task,
    visible_tasks,
)
from tasks.split import ONE_ASSIGNEE, split_by_assignees

from ..context import clamp_page, ctx, idem_key, task_or_404
from ..schemas import (
    ChangeLogOut,
    ConflictOut,
    ErrorOut,
    ExtendIn,
    LinkedProjectOut,
    LinkRejectIn,
    TaskCreateIn,
    TaskDuplicateIn,
    TaskListOut,
    TaskOut,
    TaskPatchIn,
    TaskProjectIn,
    TaskSplitIn,
    TransitionIn,
)
from ..serialize import changelog_out, task_out

router = Router(tags=["tasks"])


@router.get("", response=TaskListOut)
def list_tasks(
    request,
    org: int | None = None,
    project: int | None = None,
    assignee: int | None = None,
    status: str | None = None,
    due_from: date | None = None,
    due_to: date | None = None,
    q: str | None = None,
    updated_since: str | None = None,
    include_archived: bool = False,
    include_templates: bool = False,
    parent: int | None = None,
    group: int | None = None,
    leaf_only_: bool = Query(False, alias="leaf_only"),
    primary_only: bool = False,
    limit: int = 50,
    offset: int = 0,
):
    """project는 그 프로젝트에 연결된 태스크도 포함한다(primary_only=true면 주 프로젝트만).
    group=상위 id면 그 상위의 하위만, leaf_only=true면 하위가 있는 상위를 뺀다."""
    qs = visible_tasks(request.auth)
    if not include_templates:
        qs = qs.filter(is_template=False)
    if parent is not None:
        qs = qs.filter(parent_id=parent)
    if group is not None:
        qs = qs.filter(group_id=group)
    if leaf_only_:  # 집계용: 하위가 있는 상위는 뺀다(하위가 대표한다)
        qs = leaf_only(qs)
    if org is not None:
        qs = qs.filter(project__org_id=org)
    if project is not None:
        if primary_only:
            qs = qs.filter(project_id=project)
        else:
            linked = TaskProject.objects.filter(
                task_id=OuterRef("pk"), project_id=project, status="active"
            )
            qs = qs.filter(Q(project_id=project) | Exists(linked))
    if assignee is not None:
        qs = qs.filter(assignee_id=assignee)
    if status:
        values = [s.strip() for s in status.split(",") if s.strip()]
        bad = [s for s in values if s not in dict(Task.STATUSES)]
        if bad:
            raise HttpError(
                400,
                f"알 수 없는 상태: {', '.join(bad)}. 가능한 값: {', '.join(dict(Task.STATUSES))}",
            )
        qs = qs.filter(status__in=values)
    if due_from:
        qs = qs.filter(due_date__gte=due_from)
    if due_to:
        qs = qs.filter(due_date__lte=due_to)
    if q:
        qs = qs.filter(title__icontains=q)
    if updated_since:
        # 채널 게시가 이전 틱 이후 바뀐 것만 받아 상태를 비교한다. 상태를 가리지 않는다 —
        # 방금 done으로 넘어간 것도 봐야 '완료' 사건을 만들 수 있다.
        moment = parse_datetime(updated_since)
        if moment is None:
            raise HttpError(400, "updated_since는 ISO 8601 시각이어야 합니다.")
        qs = qs.filter(updated_at__gt=moment)
    if not include_archived:
        qs = qs.filter(project__is_archived=False)
    limit, offset = clamp_page(limit, offset)
    # nulls_last를 명시해야 SQLite(기한 미정이 앞)와 Postgres(뒤)가 같아지고, by_due()와도 맞는다.
    # 검토 독촉이 PR 리뷰 요청 시각을 쓴다. LEFT JOIN 한 번이라 N+1이 없다.
    qs = qs.annotate(review_requested_at=F("git__review_requested_at"))
    qs = qs.order_by(F("due_date").asc(nulls_last=True), "id")
    total = qs.count()
    return {
        "items": [task_brief(t) for t in qs[offset : offset + limit]],
        "total": total,
        "limit": limit,
        "offset": offset,
    }


@router.get("/{task_id}", response=TaskOut)
def get_task(request, task_id: int):
    return task_out(task_or_404(request, task_id), request.auth)


@router.get("/{task_id}/github", response=dict)
def get_task_github(request, task_id: int):
    """GitHub 작업 연결과 동기화된 이슈 본문. GitHub 저장소 권한도 확인한다."""
    task = task_or_404(request, task_id)
    link = TaskGitLink.objects.filter(task=task).select_related("connection").first()
    if link is None:
        return {"linked": False}
    conn = link.connection
    if not can_view_repo(request.auth, conn.full_name):
        raise HttpError(403, "이 GitHub 저장소를 볼 권한이 없습니다.")
    if conn.project_id != task.project_id and not can_view_project(request.auth, conn.project):
        raise HttpError(403, "이 태스크의 연동 프로젝트를 볼 수 없습니다.")  # Sol 검토 R7
    issue = None
    if link.issue_number:
        issue = RepoIssue.objects.filter(connection=conn, number=link.issue_number).first()
    issue_data = None
    if link.issue_number:
        # 캐시 갱신 웹훅이 늦었거나 이슈가 PM에서 막 만들어진 경우도 즉시 읽을 수 있게
        # 연결한 사용자의 GitHub 권한으로 최신 본문을 요청한다. 실패하면 저장된 스냅샷을 쓴다.
        live_issue = None
        try:
            token = user_token(request.auth.github)
            live_issue = github_client.request(
                "GET", f"/repos/{conn.full_name}/issues/{link.issue_number}", token
            )
        except (GitHubError, ServiceError):
            pass
        issue_data = {
            "number": link.issue_number,
            "title": (live_issue or {}).get("title", link.issue_title),
            "state": (live_issue or {}).get("state", link.issue_state),
            "url": f"https://github.com/{conn.full_name}/issues/{link.issue_number}",
            "body": (live_issue or {}).get("body", issue.body if issue else ""),
            "labels": (
                [label["name"] for label in live_issue.get("labels", [])]
                if live_issue
                else (issue.labels if issue else [])
            ),
            "author_login": ((live_issue or {}).get("user") or {}).get(
                "login", issue.author_login if issue else ""
            ),
            "assignee_login": ((live_issue or {}).get("assignee") or {}).get(
                "login", issue.assignee_login if issue else ""
            ),
            "updated_at": (live_issue or {}).get("updated_at")
            or (issue.updated_at if issue else None),
            "source": "github" if live_issue else "cache",
        }
    return {
        "linked": True,
        "repository": conn.full_name,
        "repository_url": conn.url,
        "issue": issue_data,
        "branch": link.branch,
        "pull_request": {
            "number": link.pr_number,
            "title": link.pr_title,
            "state": link.pr_state,
            "url": (
                f"https://github.com/{conn.full_name}/pull/{link.pr_number}"
                if link.pr_number
                else ""
            ),
            "merged_at": link.merged_at,
            "draft": link.pr_draft,
            "head_sha": link.head_sha,
            "review_state": link.review_state,
            "reviews": link.review_states,
            "ci_state": link.ci_state,
            "ci_url": link.ci_url,
        }
        if link.pr_number
        else None,
        "commits": link.commits,
        "continued_by": _continued_by(task),
    }


def _continued_by(task):
    """재개(PR·이슈 reopened)로 이 태스크를 이어받은 가장 최근 새 태스크. 없으면 None."""
    new = continuation(task)["by"]
    return {"id": new.pk, "number": new.number, "status": new.status} if new else None


@router.post("/{task_id}/github/issue", response={201: dict, 400: ErrorOut})
def create_task_issue(request, task_id: int):
    """태스크로 GitHub 이슈를 만들고 잇는다. 웹 패널의 '이슈 만들기'와 같은 함수, 같은 조건이다.

    이슈는 호출한 사람의 GitHub 권한으로 만든다. AI는 `ai.create_task`가 막혀 있으면 못 만든다.
    """
    if not settings.GITHUB_ENABLED:
        raise HttpError(404, "GitHub 연동이 꺼져 있습니다.")
    task = task_or_404(request, task_id)
    org = task.project.org
    if ctx(request)["source"] == "mcp" and (
        not effective("ai.enabled", org=org) or effective("ai.create_task", org=org) == "deny"
    ):
        raise ServiceError({"github": ai_denied("GitHub 이슈 생성")})
    state = task_repo_state(request.auth, task)["state"]
    if state != "ok":
        raise ServiceError(
            {
                "github": {
                    "none": "프로젝트에 연결된 저장소가 없습니다.",
                    "unselected": "연동 프로젝트를 먼저 선택하세요.",
                    "hidden": "이 태스크의 연동 프로젝트를 볼 수 없습니다.",
                    "unlinked": "GitHub 계정을 먼저 연결해야 합니다.",
                    "denied": "이 저장소에 접근할 권한이 없습니다.",
                }[state]
            }
        )
    if TaskGitLink.objects.filter(task=task).exclude(issue_number=None).exists():
        raise ServiceError({"github": "이미 이슈가 연결된 태스크입니다."})
    try:
        data = gh_writes.create_issue(task, actor=request.auth)
    except GitHubError as e:
        raise HttpError(502, e.message) from e
    full_name = task_repo(task).full_name
    return 201, {
        "number": data["number"],
        "title": data["title"],
        "url": f"https://github.com/{full_name}/issues/{data['number']}",
    }


@router.get("/{task_id}/history", response=list[ChangeLogOut])
def history(request, task_id: int):
    task = task_or_404(request, task_id)
    logs = ChangeLog.objects.filter(target_type="task", target_id=task.pk).select_related("actor")
    out = [changelog_out(log) for log in logs]
    # 연결·연동 프로젝트 이력의 값은 프로젝트 id다. 못 보는 프로젝트 id는 지운다(Sol 검토 R7).
    pfields = ("projects", "git_project")
    ids = {
        int(v)
        for r in out
        if r["field"] in pfields
        for v in (r["old_value"], r["new_value"])
        if v.isdecimal()
    }
    if ids:
        seen = {
            str(pk)
            for pk in visible_projects(request.auth).filter(pk__in=ids).values_list("pk", flat=True)
        }
        for r in out:
            if r["field"] in pfields:
                for k in ("old_value", "new_value"):
                    if r[k].isdecimal() and r[k] not in seen:
                        r[k] = ""
    return out


def _widening_400(e: WideningRequired):
    """열람 확대 확인이 필요하다. MCP는 이 모양(error=visibility_widening)을 보고 거부·안내한다."""
    return 400, {
        "detail": e.errors["confirm"],
        "error": "visibility_widening",
        "message": e.errors["confirm"],
        "widening_count": len(e.users),
        "widening": [{"id": u.pk, "display_name": u.display_name} for u in e.users[:5]],
    }


@router.post("", response={201: TaskOut, 400: dict})
def create_task_ep(request, payload: TaskCreateIn):
    if payload.assignee_ids is not None:
        raise ServiceError({"assignee_ids": ONE_ASSIGNEE})
    project = visible_projects(request.auth).filter(pk=payload.project_id).first()
    if project is None:
        raise HttpError(404, "프로젝트를 찾을 수 없습니다.")
    assignee = None
    if payload.assignee_id:
        assignee = User.objects.filter(pk=payload.assignee_id).first()
        if assignee is None:
            raise HttpError(400, "담당자를 찾을 수 없습니다.")
    group = None
    if payload.group_id is not None:
        group = visible_tasks(request.auth).filter(pk=payload.group_id).first()
        if group is None:
            raise HttpError(404, "상위 태스크를 찾을 수 없습니다.")
    c = ctx(request)
    try:
        task = create_task(
            project=project,
            group=group,
            title=payload.title,
            assignee=assignee,
            description=payload.description,
            done_when=payload.done_when,
            next_action=payload.next_action,
            priority=payload.priority,
            due_date=payload.due_date,
            no_due_reason=payload.no_due_reason,
            idempotency_key=idem_key(request),
            linked_project_ids=payload.linked_project_ids,
            confirm_widening=payload.confirm_visibility_widening,
            **c,
        )
    except WideningRequired as e:
        return _widening_400(e)
    if payload.checklist is not None and not task.checklist.exists():
        replace_checklist(
            task, [i.dict() for i in payload.checklist], actor=c["actor"], source=c["source"]
        )
    return 201, task_out(task, request.auth)


@router.delete("/{task_id}", response={204: None, 400: ErrorOut})
def delete_task_ep(request, task_id: int):
    """조직 관리자만. 체크리스트·링크가 함께 사라진다."""
    task = task_or_404(request, task_id)
    c = ctx(request)
    delete_task(task, actor=c["actor"], source=c["source"])
    return 204, None


@router.patch("/{task_id}", response={200: TaskOut, 400: ErrorOut, 409: ConflictOut})
def patch_task(request, task_id: int, payload: TaskPatchIn):
    task = task_or_404(request, task_id)
    if payload.assignee_ids is not None:
        raise ServiceError({"assignee_ids": ONE_ASSIGNEE})
    c = ctx(request)
    data = payload.dict(exclude_unset=True)
    version = data.pop("version")
    checklist = data.pop("checklist", None)
    template = data.pop("is_template", None)
    group_given = "group_id" in data
    gid = data.pop("group_id", None)
    group = None
    if gid is not None:
        group = visible_tasks(request.auth).filter(pk=gid).first()
        if group is None:
            raise HttpError(404, "상위 태스크를 찾을 수 없습니다.")
    if "assignee_id" in data:
        aid = data.pop("assignee_id")
        data["assignee"] = User.objects.filter(pk=aid).first() if aid else None
    if "reviewer_id" in data:
        rid = data.pop("reviewer_id")
        data["reviewer"] = User.objects.filter(pk=rid).first() if rid else None
        if rid and data["reviewer"] is None:
            raise HttpError(400, "검토자를 찾을 수 없습니다.")
    if "git_project_id" in data:
        gid = data.pop("git_project_id")
        data["git_project"] = visible_projects(request.auth).filter(pk=gid).first() if gid else None
        if gid and data["git_project"] is None:
            raise HttpError(404, "프로젝트를 찾을 수 없습니다.")
    if "project_id" in data:
        pid = data.pop("project_id")
        data["project"] = visible_projects(request.auth).filter(pk=pid).first()
        if data["project"] is None:
            raise HttpError(404, "프로젝트를 찾을 수 없습니다.")
    if data:
        task = update_task(task, data, expected_version=version, **c)
    if group_given:
        # 상위·하위는 한 겹·같은 프로젝트 검사가 set_group에 있다 — update_task로 우회하지 않는다.
        task = set_group(task, group, expected_version=task.version if data else version, **c)
    changed = bool(data) or group_given
    if checklist is not None:
        # 체크리스트만 바꿀 때도 version은 본다. 안 그러면 오래된 화면이 남의 수정을 통째로 덮는다.
        if not changed and task.version != version:
            raise ConflictError(task)
        replace_checklist(task, checklist, actor=c["actor"], source=c["source"])
    if template is not None:
        if not changed and checklist is None and task.version != version:
            raise ConflictError(task)
        task = set_template(task, template, **c)
    return task_out(task, request.auth)


@router.post("/{task_id}/duplicate", response={201: TaskOut, 400: ErrorOut})
def duplicate_ep(request, task_id: int, payload: TaskDuplicateIn):
    """복제·회차 만들기. 체크리스트(미완료)·링크·문서 연결을 복사하고 계열(parent_id)로 묶는다. 하위 태스크는 복사하지 않는다."""
    task = task_or_404(request, task_id)
    assignee = None
    if payload.assignee_id:
        assignee = User.objects.filter(pk=payload.assignee_id).first()
        if assignee is None:
            raise HttpError(400, "담당자를 찾을 수 없습니다.")
    new = duplicate_task(
        task,
        title=payload.title,
        due_date=payload.due_date,
        no_due_reason=payload.no_due_reason,
        assignee=assignee,
        idempotency_key=idem_key(request),
        **ctx(request),
    )
    return 201, task_out(new, request.auth)


@router.post("/{task_id}/transition", response={200: TaskOut, 400: ErrorOut, 409: ConflictOut})
def transition_ep(request, task_id: int, payload: TransitionIn):
    task = task_or_404(request, task_id)
    task = transition(
        task,
        payload.status,
        reason=payload.reason,
        expected_version=payload.version,
        **ctx(request),
    )
    return task_out(task, request.auth)


@router.post("/{task_id}/extend", response={200: TaskOut, 400: ErrorOut, 409: ConflictOut})
def extend_ep(request, task_id: int, payload: ExtendIn):
    task = task_or_404(request, task_id)
    task = extend_due(
        task, payload.due_date, payload.reason, expected_version=payload.version, **ctx(request)
    )
    return task_out(task, request.auth)


# ---------- 연결 프로젝트(IMPL-PLAN-11 §3.7, 결정 2-1) ----------


def _link_or_404(task, project_id):
    link = (
        TaskProject.objects.filter(task=task, project_id=project_id)
        .select_related("project", "created_by", "task__project__org")
        .first()
    )
    if link is None:
        raise HttpError(404, "연결된 프로젝트가 아닙니다.")
    return link


def _link_out(link) -> dict:
    return {"id": link.project_id, "name": link.project.name, "status": link.status}


@router.post("/{task_id}/projects", response={201: LinkedProjectOut, 400: dict})
def link_project_ep(request, task_id: int, payload: TaskProjectIn):
    """태스크를 프로젝트에 연결한다. 열람자가 늘어나면 confirm_visibility_widening 없이는
    400 visibility_widening, 있으면 status=pending(관리자 승인 대기)으로 만든다."""
    task = task_or_404(request, task_id)
    project = visible_projects(request.auth).filter(pk=payload.project_id).first()
    if project is None:
        raise HttpError(404, "프로젝트를 찾을 수 없습니다.")
    try:
        link = link_project(
            task, project, confirm_widening=payload.confirm_visibility_widening, **ctx(request)
        )
    except WideningRequired as e:
        return _widening_400(e)
    return 201, _link_out(link)


@router.delete("/{task_id}/projects/{project_id}", response={204: None, 400: ErrorOut})
def unlink_project_ep(request, task_id: int, project_id: int):
    """연결 해제·승인 요청 취소."""
    task = task_or_404(request, task_id)
    link = _link_or_404(task, project_id)
    unlink_project(task, link.project, **ctx(request))
    return 204, None


@router.post(
    "/{task_id}/projects/{project_id}/approve",
    response={200: LinkedProjectOut, 400: ErrorOut, 403: ErrorOut},
)
def approve_link_ep(request, task_id: int, project_id: int):
    """열람 확대 승인. 주 프로젝트가 비공개면 그 프로젝트 관리자·조직 관리자, 아니면 조직 관리자.
    AI(MCP) 요청은 거부한다."""
    link = _link_or_404(task_or_404(request, task_id), project_id)
    return _link_out(approve_link(link, **ctx(request)))


@router.post(
    "/{task_id}/projects/{project_id}/reject",
    response={204: None, 400: ErrorOut, 403: ErrorOut},
)
def reject_link_ep(request, task_id: int, project_id: int, payload: LinkRejectIn):
    """열람 확대 거절. 승인과 같은 사람만, AI(MCP)는 거부한다."""
    link = _link_or_404(task_or_404(request, task_id), project_id)
    reject_link(link, reason=payload.reason, **ctx(request))
    return 204, None


# ---------- 사람별로 나누기(IMPL-PLAN-11 §2) ----------


@router.post("/{task_id}/split", response={201: dict, 400: ErrorOut})
def split_ep(request, task_id: int, payload: TaskSplitIn):
    """담당자는 한 명이다. 여러 사람이 맡는 일은 사람마다 하위 태스크를 만든다(2~10명).
    원본은 상위 태스크가 되어(만든 태스크의 group_id = 원본 id) 진행률을 보여 준다.
    기한·설명·체크리스트·링크는 복사한다. 하위 태스크는 더 나눌 수 없다(한 겹)."""
    task = task_or_404(request, task_id)
    users = list(User.objects.filter(pk__in=payload.assignee_ids))
    if len(users) != len(set(payload.assignee_ids)):
        raise HttpError(400, "담당자를 찾을 수 없습니다.")
    by_id = {u.pk: u for u in users}
    made = split_by_assignees(
        task,
        [by_id[i] for i in dict.fromkeys(payload.assignee_ids)],
        roles=payload.roles,
        title_pattern=payload.title_pattern,
        idempotency_key=idem_key(request),
        **ctx(request),
    )
    return 201, {"tasks": [task_out(t, request.auth) for t in made]}
