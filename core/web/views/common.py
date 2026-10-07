import json
import uuid
from datetime import date, timedelta
from urllib.parse import urlencode

from django.contrib import messages
from django.db.models import Count, Q, prefetch_related_objects
from django.http import Http404, HttpResponse
from django.shortcuts import redirect, render
from django.urls import reverse
from django.utils import timezone

from accounts.models import User
from common.dates import fmt_md, overdue_before, today_kst
from common.errors import ServiceError
from orgs.models import Organization
from orgs.services import is_admin, is_member, orgs_of
from projects.models import Project
from projects.services import can_view_project
from tasks.models import Task
from tasks.services import (
    attach_linked,
    get_visible_task,
    hidden_task_refs,
    mask_task_refs,
    today_flag,
    today_membership,
    visible_tasks,
)

CONFLICT_MSG = "다른 사람이 먼저 수정했습니다. 최신 내용을 다시 확인하세요."


def task_or_404(user, task_id):
    task = get_visible_task(user, task_id)
    if task is None:
        raise Http404
    return task


def _pk_or_404(value) -> int:
    """URL·쿼리에서 온 id를 정수로. 숫자가 아니면 404.

    filter(pk="abc")는 Django가 ValueError를 던져 500이 된다. 여기서 한 번 막으면
    이 헬퍼를 쓰는 모든 뷰가 함께 보호된다.
    """
    try:
        return int(value)
    except (TypeError, ValueError):
        raise Http404 from None


def org_or_404(user, org_id):
    org = Organization.objects.filter(pk=_pk_or_404(org_id)).first()
    if org is None or not is_member(user, org):
        raise Http404
    return org


def project_or_404(user, project_id):
    p = (
        Project.objects.filter(pk=_pk_or_404(project_id))
        .select_related("org")
        .prefetch_related("owners")
        .first()
    )
    if p is None or not can_view_project(user, p):
        raise Http404
    return p


def current_org(request, orgs=None):
    """세션의 org_id가 내 조직이면 그 조직, 아니면 이름순 첫 조직. 조직이 없으면 None.

    orgs를 주면 그것을 쓴다 — 셸이 조직 목록(전환 패널)을 이미 읽었을 때 같은 질의를 두 번 하지 않는다.
    """
    if orgs is None:
        orgs = list(orgs_of(request.user).order_by("name"))
    if not orgs:
        return None
    oid = request.session.get("org_id")
    for o in orgs:
        if o.pk == oid:
            return o
    return orgs[0]


def apply_service_error(form, exc: ServiceError):
    """ServiceError의 {필드: 메시지}를 폼 오류로 옮긴다. 폼에 없는 필드는 non_field로."""
    for field, msg in exc.errors.items():
        form.add_error(field if field in form.fields else None, msg)


def new_idem() -> str:
    return uuid.uuid4().hex


def can_admin(user, org) -> bool:
    return is_admin(user, org)


def hx_redirect(request, url: str):
    """HTMX 요청이면 204 + HX-Redirect, 아니면 일반 302."""
    if request.headers.get("HX-Request"):
        return HttpResponse(status=204, headers={"HX-Redirect": url})
    return redirect(url)


def not_admin(request, org, what=""):
    """관리자 전용 화면의 관문. 멤버지만 관리자가 아니면 이유를 말하고 조직 현황으로 보낸다.

    조직 밖 사람은 그 전에 org_or_404가 404를 낸다 — 존재를 숨기는 일은 그쪽 몫이다.
    멤버에게까지 404를 주면 "없는 페이지"로 읽혀 권한 문제인지 알 수 없다.
    what: 시도한 화면 이름. 문구에 넣어 "왜 여기로 왔는지"를 알린다.
    """
    if is_admin(request.user, org):
        return None
    messages.warning(
        request,
        f"{what} 화면은 조직 관리자만 접근할 수 있습니다. 조직 현황으로 이동했습니다. 권한이 필요하면 조직 관리자에게 요청해 주세요."
        if what
        else "이 화면은 조직 관리자만 접근할 수 있습니다. 조직 현황으로 이동했습니다. 권한이 필요하면 조직 관리자에게 요청해 주세요.",
    )
    return hx_redirect(request, reverse("org_detail", args=[org.pk]))


def dialog(request, template: str, ctx: dict):
    """모달 조각. HTMX면 조각만, 아니면 셸에 담아 준다.

    주소를 직접 열거나 뒤로 가기로 돌아오면 HX-Request가 없어 조각이 맨몸(CSS 없는 폼)으로 보였다.
    """
    if request.headers.get("HX-Request"):
        return render(request, template, ctx)
    return render(request, "dialog_page.html", {**ctx, "dialog_template": template})


def trigger(response, event: str, task=None):
    """응답에 HX-Trigger 헤더를 붙인다. task를 주면 {"event": {"id": n}} 형식."""
    response["HX-Trigger"] = json.dumps({event: {"id": task.pk}}) if task else event
    return response


def version_of(request) -> int:
    try:
        return int(request.POST.get("version", 0))
    except ValueError:
        return 0


# ---------- 표시 문자열 ----------


def _overdue(task) -> bool:
    """유예를 적용한 초과 여부. `Task.is_overdue`는 사실이고, 화면은 프로젝트(없으면 조직) 설정을 본다."""
    # 닫힌 태스크는 초과가 아니다(`Task.is_overdue`와 같은 규칙) — 결과 기록이 연체 목록처럼 보이면 안 된다.
    return (
        task.is_open
        and bool(task.due_date)
        and task.due_date < overdue_before(task.project.org, task.project)
    )


def due_label(task) -> str:
    """행 우측 기한 라벨: '오늘 마감' / '9월 12일' / '기한 미정', 초과면 ' 초과'.
    닫힌 태스크는 중립 날짜 '목표일 9월 12일'."""
    if not task.due_date:
        return "기한 미정"
    if task.is_closed:
        return f"목표일 {fmt_md(task.due_date)}"
    label = "오늘 마감" if task.due_date == today_kst() else fmt_md(task.due_date)
    return label + " 초과" if _overdue(task) else label


def due_class(task) -> str:
    """기한 배지의 변형. 색과 테두리는 이 한 곳에서만 정한다."""
    if task.is_closed:
        return "closed"
    if _overdue(task):
        return "overdue"
    if not task.due_date:
        return "none"
    return "today" if task.due_date == today_kst() else ""


def due_full(task) -> str:
    """패널 목표일 블록: '2026년 9월 12일 (초과)' / '기한 미정 · 사유'."""
    if task.due_date:
        return f"{task.due_date.year}년 {fmt_md(task.due_date)}" + (
            " (초과)" if _overdue(task) else ""
        )
    return "기한 미정" + (f" · {task.no_due_reason}" if task.no_due_reason else "")


FIELD_LABELS = {
    "created": "생성",
    "status": "상태",
    "assignee": "담당자",
    "due_date": "기한",
    "project": "프로젝트",
    "priority": "중요도",
    "stop_reason": "사유",
    "completed_at": "완료 시각",
    "owners": "관리자",
    "is_archived": "보관",
    "reviewer": "검토자",
    "is_template": "템플릿",
    "parent": "계열",
    "projects": "연결 프로젝트",
    "git_project": "연동 프로젝트",
    "group": "상위 태스크",
    "split": "사람별로 나누기",
}


def _display(field, raw: str, viewer=None) -> str:
    if raw == "":
        return "없음"
    if field == "status":
        return dict(Task.STATUSES).get(raw, raw)
    if field == "priority":
        return f"{raw}/10"
    if field == "visibility":
        return dict(Project.VISIBILITIES).get(raw, raw)
    if field == "due_date":
        return fmt_md(date.fromisoformat(raw))
    if field == "completed_at":
        return raw[:10]
    if field == "is_template":
        return "예" if raw == "True" else "아니오"
    if field in ("assignee", "reviewer"):
        u = User.objects.filter(pk=raw).first()
        return u.display_name if u else raw
    if field == "project":
        p = Project.objects.filter(pk=raw).first()
        return p.name if p else raw
    if field in ("projects", "git_project"):
        # 연결은 비공개 프로젝트일 수 있다 — 보는 사람이 못 보는 프로젝트는 이름을 숨긴다(§3.4).
        p = Project.objects.filter(pk=raw).first()
        if p is None:
            return raw
        return p.name if viewer is None or can_view_project(viewer, p) else "볼 수 없는 프로젝트"
    if field in ("group", "split"):  # 못 보는 번호는 history_rows가 이미 가렸다(R5)
        return raw.replace(",", ", ")
    if field == "owners":
        names = [u.display_name for u in User.objects.filter(pk__in=raw.split(","))]
        return ", ".join(names) or raw
    return raw


def history_rows(logs, viewer=None) -> list[dict]:
    """ChangeLog → 패널 표시용. 최신이 먼저. viewer가 있으면 못 보는 연결 프로젝트 이름을 숨긴다."""
    logs = list(logs)
    hidden = hidden_task_refs(logs, viewer) if viewer is not None else set()
    rows = []
    for log in logs:
        to = _display(log.field, mask_task_refs(log.field, log.new_value, hidden), viewer)
        if log.note:
            to += f" ({log.note})"
        at = timezone.localtime(log.created_at)
        rows.append(
            {
                "field": FIELD_LABELS.get(log.field, log.field),
                "from": _display(
                    log.field, mask_task_refs(log.field, log.old_value, hidden), viewer
                ),
                "to": to,
                "time": f"{at.month}월 {at.day}일 {at:%H:%M}",
                # actor가 비면 GitHub 로그인(external_actor)이 대신 남아 있다 — 모델 주석 참고.
                "actor": log.actor.display_name if log.actor else (log.external_actor or "GitHub"),
                "source": log.get_source_display(),
            }
        )
    return rows


# ---------- 태스크 행 ----------

ROW_OPTS = ("next", "move", "noassignee", "notoday", "ro", "today", "board", "sub", "fold")


def attach_subtasks(tasks, viewer) -> None:
    """행·카드 표시용(IMPL-PLAN-12 §5.1): `sub_done`·`sub_total`(취소를 뺀 하위), `group_shown`(viewer가
    상위를 볼 수 있는가 — 못 보면 '↳ TASK-N'을 그리지 않는다). 태스크 수와 무관하게 쿼리 한두 번."""
    tasks = [t for t in tasks if not hasattr(t, "sub_total")]
    if not tasks:
        return
    counts = {
        r["group_id"]: r
        for r in Task.objects.filter(group_id__in=[t.pk for t in tasks])
        .exclude(status="cancelled")
        .values("group_id")
        .order_by()
        .annotate(total=Count("id"), done=Count("id", filter=Q(status="done")))
    }
    gids = {t.group_id for t in tasks if t.group_id}
    shown = (
        set(visible_tasks(viewer).filter(pk__in=gids).values_list("pk", flat=True))
        if gids
        else set()
    )
    for t in tasks:
        c = counts.get(t.pk, {})
        t.sub_total, t.sub_done = c.get("total", 0), c.get("done", 0)
        t.group_shown = t.group_id in shown


def nest_rows(rows) -> list[dict]:
    """프로젝트 목록 보기만(§5.3): 기한순 목록에서 상위 바로 뒤에 그 하위를 붙인다(하위끼리는 기한순 그대로).
    상위가 목록에 없으면 하위는 제자리에 평면 행으로 남는다('↳ TASK-N'이 길을 알려 준다)."""
    present = {r["task"].pk for r in rows}
    kids = {}
    for r in rows:
        if r["task"].group_id in present:
            kids.setdefault(r["task"].group_id, []).append(r)
    out = []
    for r in rows:
        if r["task"].group_id in present:
            continue
        out.append(r)
        for k in kids.get(r["task"].pk, ()):
            _add_opt(k, "sub")
            out.append(k)
        if r["task"].pk in kids:
            _add_opt(r, "fold")
    return out


def _add_opt(r, opt):
    """행 자기 갱신(task_row)이 같은 모양으로 다시 그리도록 opts에 남긴다."""
    opts = ",".join(sorted({*filter(None, r["row_opts"].split(",")), opt}))
    r.update(
        row_opts=opts, row_query=urlencode({"opts": opts}), nested=r.get("nested") or opt == "sub"
    )
    r["foldable"] = r.get("foldable") or opt == "fold"


def row_ctx(user, task, opts: str = "", membership: dict | None = None, selected_id=None) -> dict:
    """tasks/_row.html 렌더링 context.
    opts: 쉼표 구분. next(다음 행동 표시) move(↑↓) noassignee(담당자 숨김) notoday(오늘 버튼 숨김)
          ro(상태 select 비활성) today(오늘 화면 안: 목록 전체를 갱신, 자기 갱신 없음)
          board(칸반 드래그, 자기 갱신 없음)."""
    o = {x for x in opts.split(",") if x in ROW_OPTS}
    m = membership or today_membership(user)
    flag = today_flag(task, m)
    attach_linked([task], user)  # rows_for가 이미 붙였으면 쿼리 없음
    attach_subtasks([task], user)
    items = list(task.checklist.all())
    opts = ",".join(sorted(o))
    return {
        "task": task,
        "row_opts": opts,
        "row_query": urlencode({"opts": opts}),
        "show_next": "next" in o and bool(task.next_action),
        "show_move": "move" in o and flag == "manual",
        "hide_assignee": "noassignee" in o,
        "hide_today": "notoday" in o,
        "read_only": "ro" in o,
        "in_today_page": "today" in o,
        "in_board": "board" in o,
        "row_target": "#today-list" if "today" in o else f"#task-{task.pk}",
        "in_today": flag != "",
        "auto_pulled": flag == "auto",
        "selected": task.pk == selected_id,
        "checklist_done": sum(1 for i in items if i.is_done),
        "checklist_total": len(items),
        "due_label": due_label(task),
        "due_class": due_class(task),
        # 연결 프로젝트(보는 사람이 볼 수 있는 것만). 행에 "↔ n"으로, 이름은 툴팁에.
        "linked": task.linked_shown,
        "linked_names": ", ".join(name for _, name in task.linked_shown),
        # 상위·하위(§5.1). 하위 행은 '↳ TASK-N'(상위를 볼 수 있을 때만), 상위 행은 '하위 n/m'.
        "sub_done": task.sub_done,
        "sub_total": task.sub_total,
        "sub_pct": task.sub_done * 100 // task.sub_total if task.sub_total else 0,
        "group_shown": task.group_shown,
        "nested": "sub" in o,
        "foldable": "fold" in o,
    }


def rows_for(user, tasks, opts: str = "", selected_id=None) -> list[dict]:
    tasks = list(tasks)
    # 행마다 체크리스트를 따로 읽지 않게 한 번에 붙인다(이미 붙어 있으면 건너뛴다).
    prefetch_related_objects(tasks, "checklist")
    attach_linked(tasks, user)
    attach_subtasks(tasks, user)
    m = today_membership(user)
    return [row_ctx(user, t, opts, m, selected_id) for t in tasks]


def render_row(request, task, error=None):
    """행 하나를 다시 그린다. opts는 요청의 POST 또는 GET `opts`에서 읽는다."""
    from django.shortcuts import render

    opts = request.POST.get("opts") or request.GET.get("opts", "")
    ctx = row_ctx(request.user, task, opts)
    ctx["error"] = error
    return render(request, "tasks/_row.html", ctx)


def week_days(day: date) -> list[date | None]:
    """월간 달력 셀. 그 달 1일 앞의 빈칸(None) + 날짜. 월요일 시작."""
    first = day.replace(day=1)
    if first.month == 12:
        # date.max(9999-12-31)에서 다음 달을 계산하면 OverflowError가 난다.
        nxt = (
            date(first.year, 12, 31) if first.year == date.max.year else date(first.year + 1, 1, 1)
        )
    else:
        nxt = date(first.year, first.month + 1, 1)
    cells: list[date | None] = [None] * first.weekday()
    d = first
    while d < nxt:
        cells.append(d)
        d += timedelta(days=1)
    return cells
