"""태스크 후보(IMPL-PLAN-12 §7.4·§11.2).

job.result(검증된 JSON) = {"tasks": [{"title", "description", "assignee", "due", "project", "evidence",
사후 처리가 붙이는 "assignee_id", "project_id", "similar": [task_id, ...]}]}, 최대 20개.
담당자·프로젝트는 AI가 쓴 이름을 허용 목록과 완전 일치로만 맞춘다(§11.3). 링크·URL은 만들지 않는다.
"""

import difflib
import json
from datetime import date, timedelta

from django.db import transaction
from django.http import Http404

from common.errors import ServiceError

MAX_CANDIDATES = 20
NAME_CHECK = "담당자 확인 필요"  # COPY:extract_assignee_check
NO_DUE_MEETING = (
    "회의록의 태스크 후보에서 생성되어 기한이 정해지지 않았습니다."  # COPY:extract_no_due_meeting
)
NO_DUE_ISSUE = "GitHub 이슈의 태스크 후보에서 생성되어 기한이 정해지지 않았습니다."  # COPY:extract_no_due_issue


def _s(v, limit):
    from .prompts import clean_text

    return clean_text(v, limit, one_line=limit <= 300) if isinstance(v, str) else ""


def _due(v, earliest):
    if not isinstance(v, str):
        return None
    try:
        d = date.fromisoformat(v.strip())
    except ValueError:
        return None
    if earliest is not None and d < earliest:
        return None  # 회의 일시 1년 전보다 이르면 버린다
    return d.isoformat()


def validate(data: dict, *, earliest=None) -> list[dict]:
    """후보 스키마 검사(§11.2). 제목 없는 행은 버리고 20개까지. 하나도 없으면 ValueError."""
    raw = data.get("tasks")
    if not isinstance(raw, list):
        raise ValueError('"tasks" 목록이 없습니다')
    out = []
    for row in raw:
        if not isinstance(row, dict):
            continue
        title = _s(row.get("title"), 200)
        if not title:
            continue
        out.append(
            {
                "title": title,
                "description": _s(row.get("description"), 2000),
                "assignee": _s(row.get("assignee"), 100) or None,
                "due": _due(row.get("due"), earliest),
                "project": _s(row.get("project"), 100) or None,
                "evidence": _s(row.get("evidence"), 300),
            }
        )
        if len(out) == MAX_CANDIDATES:
            break
    if not out and raw:
        raise ValueError("제목이 있는 후보가 없습니다")
    return out


def earliest_due(job, user):
    """기한 하한: 회의 일시(없으면 작성 시각)·이슈는 오늘 기준 1년 전."""
    from common.dates import today_kst

    from .context import resolve_target

    kind, obj = resolve_target(user, f"{job.target_type}:{job.target_id}")
    base = today_kst()
    if kind == "doc":
        when = obj.created_on or obj.created_at
        base = when.date()
    return base - timedelta(days=365)


def base_of(job, user):
    """(출처 객체, 기본 프로젝트, 조직). 볼 수 없으면 Http404."""
    from .context import resolve_target

    kind, obj = resolve_target(user, f"{job.target_type}:{job.target_id}")
    if kind == "issue":
        return obj, obj.connection.project, obj.connection.project.org
    return obj, obj.project, obj.org


def postprocess(job, user, tasks: list[dict]) -> list[dict]:
    """서버가 다시 맞춘다: 담당자(구성원 이름 완전 일치·유일), 프로젝트(볼 수 있는 이름 완전 일치),
    비슷한 태스크(같은 프로젝트의 볼 수 있는 열린 태스크, SequenceMatcher ≥ 0.6 상위 2개)."""
    from orgs.models import OrgMembership
    from projects.services import visible_projects
    from tasks.models import Task
    from tasks.services import visible_tasks

    _, base, org = base_of(job, user)
    projects = {p.name.casefold(): p for p in visible_projects(user, org)}
    names: dict[str, list[int]] = {}
    for m in OrgMembership.objects.filter(org=org).select_related("user"):
        for n in {m.user.display_name, m.user.username}:
            if n:
                names.setdefault(n.casefold(), []).append(m.user_id)
    open_cache: dict[int, list] = {}
    for row in tasks:
        p = projects.get((row.get("project") or "").casefold()) or base
        row["project_id"] = p.pk if p else None
        ids = set(names.get((row.get("assignee") or "").casefold(), []))
        row["assignee_id"] = ids.pop() if len(ids) == 1 else None
        row["assignee_note"] = "" if row["assignee_id"] or not row.get("assignee") else NAME_CHECK
        if p is None:
            row["similar"] = []
            continue
        if p.pk not in open_cache:
            open_cache[p.pk] = list(
                visible_tasks(user)
                .filter(project=p, status__in=Task.OPEN)
                .values_list("pk", "title")[:500]
            )
        scored = [
            (difflib.SequenceMatcher(None, row["title"], t).ratio(), pk)
            for pk, t in open_cache[p.pk]
        ]
        row["similar"] = [pk for r, pk in sorted(scored, reverse=True)[:2] if r >= 0.6]
    return tasks


def _make(job, i, row, actor, *, project, group, no_due):
    from accounts.models import User
    from tasks.services import create_task

    title = (row.get("title") or "").strip()
    if not title:
        raise ServiceError(
            {"title": "후보 제목이 없습니다. 태스크 제목을 입력해 주세요."}
        )  # COPY:extract_title_required
    assignee = None
    if row.get("assignee_id"):
        assignee = User.objects.filter(pk=row["assignee_id"], is_active=True).first()
    due = row.get("due") or None
    if isinstance(due, str):
        try:
            due = date.fromisoformat(due)
        except ValueError:
            raise ServiceError(
                {
                    "due": "기한 형식이 올바르지 않습니다. 날짜 입력 칸에서 유효한 날짜를 선택해 주세요."
                }
            ) from None  # COPY:extract_due_invalid
    return create_task(
        project=project,
        title=title[:200],
        actor=actor,
        source="web",
        assignee=assignee,
        description=(row.get("description") or "")[:2000],
        due_date=due,
        no_due_reason="" if due else no_due,
        idempotency_key=f"assist:{job.pk}:{i}",
        group=group,
    )


def _err(e) -> str:
    if isinstance(e, ServiceError):
        return " ".join(str(v) for v in e.errors.values())
    return "이 후보로 태스크를 만들지 못했습니다. 입력 내용과 프로젝트 권한을 확인한 뒤 다시 시도해 주세요."  # COPY:extract_row_failed


def create_from_candidates(job, rows: list[dict], actor) -> list:
    """고른 행으로 태스크를 만든다. rows = [{"index", "title", "description", "assignee_id", "due",
    "project_id"}]. 행마다 create_task(idempotency_key=f"assist:{job.pk}:{index}").

    돌려주는 값: 행마다 (index, Task | None, 오류 문구) — 실패한 행만 오류를 보인다.
    회의록: 각 태스크를 회의록에 연결(link_task). 이슈: 첫 후보 = 이슈 연결, 나머지 = 그 하위 태스크.
    이미 가져온 이슈면 모두 그 태스크의 하위로 만든다.
    """
    from projects.docs import link_task
    from projects.services import visible_projects

    if job.user_id != actor.pk:
        raise Http404
    if job.kind != "extract" or job.status != "done":
        raise ServiceError(
            {
                "assist": "태스크 후보가 아직 준비되지 않았습니다. 후보 뽑기가 끝난 뒤 다시 시도해 주세요."
            }
        )  # COPY:extract_not_ready
    try:
        count = len(json.loads(job.result or "{}").get("tasks") or [])
    except ValueError:
        count = 0
    src, base, org = base_of(job, actor)
    out = []
    if job.target_type == "issue":
        from github.models import RepoIssue
        from github.services import link_issue_task

        first = src.task
        for row in rows:
            i = row.get("index")
            if not isinstance(i, int) or not 0 <= i < count:
                out.append(
                    (
                        i,
                        None,
                        "해당 태스크 후보를 찾을 수 없습니다. 후보를 다시 뽑은 뒤 선택해 주세요.",
                    )
                )  # COPY:extract_row_missing
                continue
            try:
                with transaction.atomic():
                    if first is None:
                        issue = RepoIssue.objects.select_for_update().get(pk=src.pk)
                        if issue.task_id is not None:
                            first = issue.task
                    if first is None:
                        task = _make(
                            job, i, row, actor, project=base, group=None, no_due=NO_DUE_ISSUE
                        )
                        link_issue_task(issue, task)
                        first = task
                    else:
                        task = _make(
                            job,
                            i,
                            row,
                            actor,
                            project=first.project,
                            group=first,
                            no_due=NO_DUE_ISSUE,
                        )
                out.append((i, task, ""))
            except (ServiceError, ValueError) as e:
                out.append((i, None, _err(e)))
        return out
    allowed = {p.pk: p for p in visible_projects(actor, org)}
    for row in rows:
        i = row.get("index")
        if not isinstance(i, int) or not 0 <= i < count:
            out.append(
                (i, None, "해당 태스크 후보를 찾을 수 없습니다. 후보를 다시 뽑은 뒤 선택해 주세요.")
            )  # COPY:extract_row_missing
            continue
        project = allowed.get(row.get("project_id")) or base
        if project is None:
            out.append(
                (i, None, "프로젝트가 선택되지 않았습니다. 태스크를 만들 프로젝트를 선택해 주세요.")
            )  # COPY:extract_project_required
            continue
        try:
            task = _make(job, i, row, actor, project=project, group=None, no_due=NO_DUE_MEETING)
        except (ServiceError, ValueError) as e:
            out.append((i, None, _err(e)))
            continue
        try:
            link_task(src, task, actor)
        except ServiceError:
            pass  # 다른 프로젝트로 만든 태스크는 프로젝트 회의록에 걸 수 없다 — 태스크는 남긴다
        out.append((i, task, ""))
    return out
