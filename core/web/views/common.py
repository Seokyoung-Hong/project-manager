import json
import uuid
from datetime import date, timedelta
from urllib.parse import urlencode

from django.contrib import messages
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
from tasks.services import get_visible_task, today_flag, today_membership

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
    """유예를 적용한 초과 여부. `Task.is_overdue`는 사실이고, 화면은 조직 설정을 본다."""
    return bool(task.due_date) and task.due_date < overdue_before(task.project.org)


def due_label(task) -> str:
    """행 우측 기한 라벨: '오늘 마감' / '9월 12일' / '기한 미정', 초과면 ' 초과'."""
    if not task.due_date:
        return "기한 미정"
    label = "오늘 마감" if task.due_date == today_kst() else fmt_md(task.due_date)
    return label + " 초과" if _overdue(task) else label


def due_class(task) -> str:
    """기한 배지의 변형. 색과 테두리는 이 한 곳에서만 정한다."""
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
}


def _display(field, raw: str) -> str:
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
    if field == "owners":
        names = [u.display_name for u in User.objects.filter(pk__in=raw.split(","))]
        return ", ".join(names) or raw
    return raw


def history_rows(logs) -> list[dict]:
    """ChangeLog → 패널 표시용. 최신이 먼저."""
    rows = []
    for log in logs:
        to = _display(log.field, log.new_value)
        if log.note:
            to += f" ({log.note})"
        at = timezone.localtime(log.created_at)
        rows.append(
            {
                "field": FIELD_LABELS.get(log.field, log.field),
                "from": _display(log.field, log.old_value),
                "to": to,
                "time": f"{at.month}월 {at.day}일 {at:%H:%M}",
                # actor가 비면 GitHub 로그인(external_actor)이 대신 남아 있다 — 모델 주석 참고.
                "actor": log.actor.display_name if log.actor else (log.external_actor or "GitHub"),
                "source": log.get_source_display(),
            }
        )
    return rows


# ---------- 태스크 행 ----------

ROW_OPTS = ("next", "move", "noassignee", "notoday", "ro", "today", "board")


def row_ctx(user, task, opts: str = "", membership: dict | None = None, selected_id=None) -> dict:
    """tasks/_row.html 렌더링 context.
    opts: 쉼표 구분. next(다음 행동 표시) move(↑↓) noassignee(담당자 숨김) notoday(오늘 버튼 숨김)
          ro(상태 select 비활성) today(오늘 화면 안: 목록 전체를 갱신, 자기 갱신 없음)
          board(칸반 드래그, 자기 갱신 없음)."""
    o = {x for x in opts.split(",") if x in ROW_OPTS}
    m = membership or today_membership(user)
    flag = today_flag(task, m)
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
    }


def rows_for(user, tasks, opts: str = "", selected_id=None) -> list[dict]:
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
