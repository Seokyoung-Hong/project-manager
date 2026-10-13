"""대상 풀기·볼 수 있는 범위(IMPL-PLAN-12 §10.1).

대상과 맥락은 모두 요청자 가시성 관문 함수로만 꺼낸다: tasks.services.visible_tasks,
projects.docs.get_visible_doc/visible_docs, projects.services.visible_projects, visible_issue,
tasks.work_requests.get_visible_request, 조직 구성원 판정. 결정 기록 원문·실명·구성원 정보는 넣지 않는다.
"""

from django.http import Http404

TARGET_TYPES = ("task", "project", "doc", "request", "issue", "org", "user")


def visible_issue(user, issue_id: int):
    """RepoIssue: connection.project가 visible_projects(user)에 있고 can_view_repo(user, full_name)일 때만. 아니면 Http404."""
    from github.models import RepoIssue
    from github.services import can_view_repo
    from projects.services import visible_projects

    issue = (
        RepoIssue.objects.select_related("connection", "connection__project", "task")
        .filter(pk=issue_id, connection__project__in=visible_projects(user))
        .first()
    )
    if issue is None or not can_view_repo(user, issue.connection.full_name):
        raise Http404
    return issue


def _find(user, kind: str, pk: int):
    from orgs.models import Organization
    from orgs.services import is_member
    from projects.docs import get_visible_doc
    from projects.services import visible_projects
    from tasks.services import get_visible_task
    from tasks.work_requests import get_visible_request

    if kind == "task":
        return get_visible_task(user, pk)
    if kind == "project":
        return visible_projects(user).select_related("org").filter(pk=pk).first()
    if kind == "doc":
        return get_visible_doc(user, pk)
    if kind == "request":
        return get_visible_request(user, pk)
    if kind == "issue":
        try:
            return visible_issue(user, pk)
        except Http404:
            return None
    if kind == "org":
        org = Organization.objects.filter(pk=pk).first()
        return org if org is not None and is_member(user, org) else None
    if kind == "user":
        return user if user.pk == pk else None  # 내 것만(포트폴리오)
    return None


def resolve_target(user, target: str):
    """ "task:12" 같은 문자열 → (종류, 객체). 요청자가 볼 수 없거나 모르는 종류면 Http404."""
    kind, _, raw = (target or "").partition(":")
    if kind not in TARGET_TYPES or not raw.isdigit():
        raise Http404
    obj = _find(user, kind, int(raw))
    if obj is None:
        raise Http404
    return kind, obj


def org_id_of(kind: str, obj):
    """대상이 속한 조직 id. user는 조직이 없다(None)."""
    if kind == "task":
        return obj.project.org_id
    if kind == "issue":
        return obj.connection.project.org_id
    if kind == "org":
        return obj.pk
    if kind == "user":
        return None
    return obj.org_id


# ---------- 맥락 조립: ctx(user, obj) -> [(label, text)] ----------


def _project_lines(user, project):
    """프로젝트 이름·목적. 요청자가 그 프로젝트를 볼 수 없으면 빈 목록(초안·연결 태스크로 숨긴 프로젝트가 새지 않게)."""
    from projects.services import visible_projects

    if project is None or not visible_projects(user).filter(pk=project.pk).exists():
        return []
    out = [("프로젝트", project.name)]
    if project.purpose:
        out.append(("프로젝트 목적", project.purpose))
    return out


def task_ctx(user, task):
    from github.models import RepoIssue
    from projects.docs import visible_docs
    from tasks.services import visible_tasks

    out = _project_lines(user, task.project)
    out.append(("태스크 제목", task.title))
    for label, value in (
        ("설명", task.description),
        ("완료 조건", task.done_when),
        ("다음 행동", task.next_action),
        ("진행 메모(끝부분)", (task.notes or "")[-2000:]),
        ("기한 미정 사유", task.no_due_reason),
        ("멈춘 사유", task.stop_reason),
    ):
        if value:
            out.append((label, value))
    out.append(("상태", task.get_status_display()))
    if task.due_date:
        out.append(("기한", task.due_date.isoformat()))
    checks = [c.text for c in task.checklist.all()[:30]]
    if checks:
        out.append(("체크 항목", "\n".join(f"- {c}" for c in checks)))
    if task.group_id:
        parent = visible_tasks(user).filter(pk=task.group_id).first()
        if parent:
            out.append(("상위 태스크", parent.title))
    subs = visible_tasks(user).filter(group_id=task.pk).values_list("title", flat=True)[:30]
    if subs:
        out.append(("하위 태스크", "\n".join(f"- {t}" for t in subs)))
    docs = visible_docs(user, task.project.org).filter(tasks=task).values_list("title", flat=True)
    if docs:
        out.append(("연결 문서", "\n".join(f"- {t}" for t in docs[:20])))
    issue = RepoIssue.objects.filter(task=task).first()
    if issue is not None:
        try:
            issue = visible_issue(user, issue.pk)
            out.append((f"연결 이슈 #{issue.number}", f"{issue.title}\n{issue.body}"))
        except Http404:
            pass
    return out


def project_ctx(user, project):
    from tasks.models import Task
    from tasks.services import visible_tasks

    out = _project_lines(user, project)
    titles = (
        visible_tasks(user)
        .filter(project=project, status__in=Task.OPEN)
        .order_by("-created_at")
        .values_list("title", flat=True)[:30]
    )
    if titles:
        out.append(("열린 태스크", "\n".join(f"- {t}" for t in titles)))
    ms = list(project.milestones.values_list("name", flat=True)[:20])
    if ms:
        out.append(("마일스톤", "\n".join(f"- {m}" for m in ms)))
    return out


def org_ctx(user, org):
    from projects.services import visible_projects

    out = [("조직", org.name)]
    names = visible_projects(user, org).values_list("name", flat=True)[:50]
    if names:
        out.append(("프로젝트 목록", "\n".join(f"- {n}" for n in names)))
    return out


def doc_ctx(user, doc):
    out = [("문서 제목", doc.title)]
    if doc.project_id:
        out[:0] = _project_lines(user, doc.project)
    if doc.body_md:
        out.append(("본문", doc.body_md[:4000]))
    return out


def request_ctx(user, req):
    from tasks.services import get_visible_task

    out = [("요청 제목", req.title)]
    if req.body:
        out.append(("요청 내용", req.body))
    if req.task_id and get_visible_task(user, req.task_id):
        out.append(("대상 태스크", req.task.title))
    return out


def issue_ctx(user, issue):
    return _project_lines(user, issue.connection.project) + [
        (f"GitHub 이슈 #{issue.number}", issue.title),
        ("이슈 본문", issue.body or ""),  # 사본 5000자(github/services.py가 자른다)
    ]


def user_ctx(user, obj):
    return [("작성자", obj.display_name or obj.username)]


CONTEXT = {
    "task": task_ctx,
    "project": project_ctx,
    "org": org_ctx,
    "doc": doc_ctx,
    "request": request_ctx,
    "issue": issue_ctx,
    "user": user_ctx,
}


def transcript_of(doc) -> str:
    """회의록의 전사문(없으면 ""). 문서를 볼 수 있는지는 호출자가 이미 확인했다."""
    rec = getattr(doc, "recording", None) if doc.kind == "meeting" else None
    return (rec.transcript_md or "") if rec is not None else ""
