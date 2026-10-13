"""AI 자동완성 작업 화면(IMPL-PLAN-12 §7.1·§7.3·§7.4).

뷰는 assist.services·assist.extract만 부른다. 조각은 base.html의 <dialog id="ai-dlg"> 안에 그려진다(ai-fill.js).
사용자 문구는 임시 격식체다 — 최종 문구는 Sol(주석의 COPY:키).
"""

import json

from django.contrib.auth.decorators import login_required
from django.http import Http404, HttpResponse
from django.shortcuts import render
from django.views.decorators.http import require_GET, require_POST

from assist import extract, fields, services
from assist.models import AiJob
from common.errors import ConflictError, ServiceError
from orgs.names import sort_by_name
from orgs.services import is_admin
from orgs.settings import effective
from projects.services import visible_projects
from tasks.services import visible_tasks

from .assist_settings import ERROR_TEXT
from .common import current_org

GENERIC = "AI 요청을 완료하지 못했습니다(오류 코드 {code}). 잠시 후 다시 요청해 주세요."  # COPY:ai_err_generic
BAD_FIELD = "이 칸은 AI 자동완성을 지원하지 않습니다. AI로 쓰기 버튼이 있는 칸에서 요청해 주세요."  # COPY:ai_err_field
BAD_TARGET = "요청할 대상이 선택되지 않았습니다. 대상 태스크·문서·프로젝트를 선택해 주세요."  # COPY:ai_err_target
RATE = "동시에 처리할 수 있는 AI 요청 수를 넘었습니다. 진행 중인 작업이 끝난 뒤 다시 요청해 주세요."  # COPY:ai_err_rate
CONFLICT = "요청 후 본문이 변경되어 적용하지 못했습니다. 새로고침하여 본문을 확인한 뒤 다시 요청해 주세요."  # COPY:ai_err_conflict


def _message(code: str) -> str:
    if code in ERROR_TEXT:
        return ERROR_TEXT[code]
    if code and not code.isascii():  # 서비스가 코드 대신 문구를 준 경우
        return code
    return GENERIC.format(code=code or "unknown")


# 설정에서 풀 수 있는 오류 — 오류 조각에 [AI 설정 열기]를 둔다
SETUP_ERRORS = {
    "no_source",
    "rate",
    "codex_missing",
    "codex_auth",
    "codex_link_update",
    "auth_failed",
    "model_not_found",
    "blocked_address",
    "pc_offline",
    "pc_unlinked",
    "payment_required",
    "reasoning_budget",
}


def _error(request, text: str, status: int, code: str = ""):
    ctx = {"text": text, "setup": code in SETUP_ERRORS}
    return render(request, "assist/_error.html", ctx, status=status)


def _service_error(request, e: ServiceError, status=400):
    code = e.errors.get("assist") or " ".join(e.errors.values())
    return _error(request, RATE if status == 429 else _message(code), status, code)


def _own_job(request, job_id: int) -> AiJob:
    """요청자 본인 작업만. get_job이 이미 보지만 뷰에서 한 번 더 막는다(§10.2)."""
    job = services.get_job(request.user, job_id)
    if job is None or job.user_id != request.user.pk:
        raise Http404
    return job


def _org_line(user, org) -> str:
    """대화상자의 "오늘 조직 AI n/30" — 조직 AI를 쓸 수 있는 멤버에게만(§5.2). 관리자·무제한·조직 AI 미등록이면 빈 값.

    ponytail: 순서에 조직 AI가 있는지(sources.plan)는 보지 않고 조직 AI 주소가 있는지만 본다.
    """
    if is_admin(user, org) or not effective("assist.org_url", org=org):
        return ""
    if effective("assist.org_level", org=org) == "admin":
        return ""
    limit = effective("assist.org_daily_limit", org=org)
    if not limit:
        return ""
    return f"오늘 조직 AI {services.today_org_count(user, org)}/{limit}"  # COPY:ai_org_count


def _source_line(job) -> str:
    name = job.source.name if job.source_id and job.source else ""
    if job.route == "org":
        return "조직 AI"  # COPY:ai_by_org
    if job.route == "pc":
        return f"개인 AI · {name} · 내 PC 거쳐 보내기"  # COPY:ai_by_pc
    if job.route == "direct":
        return f"개인 AI · {name}"  # COPY:ai_by_personal
    return ""


def _parse(job) -> dict:
    try:
        data = json.loads(job.result or "{}")
    except ValueError:
        return {}
    return data if isinstance(data, dict) else {}


def _candidates(request, job, results=None):
    """후보 표(§7.4). results = create_from_candidates의 [(index, Task|None, 오류)] — 만든 행·실패 행 표시."""
    data = _parse(job)
    done = {i: (t, err) for i, t, err in results or []}
    rows = []
    similar_ids = set()
    for i, c in enumerate((data.get("tasks") or [])[:20]):
        if not isinstance(c, dict):
            continue
        task, err = done.get(i, (None, ""))
        similar_ids.update(x for x in c.get("similar") or [] if isinstance(x, int))
        rows.append({"index": i, "c": c, "created": task, "error": err})
    similar = {t.pk: t for t in visible_tasks(request.user).filter(pk__in=similar_ids)}
    for r in rows:
        r["similar"] = [similar[x] for x in r["c"].get("similar") or [] if x in similar]
    ctx = {
        "job": job,
        "rows": rows,
        "members": sort_by_name(job.org.members.filter(is_active=True), job.org),
        "projects": visible_projects(request.user, job.org)
        .filter(is_archived=False)
        .order_by("name"),
    }
    return render(request, "assist/_candidates.html", ctx)


def _job(request, job, status=200):
    if job.status == "done" and job.kind == "extract":
        return _candidates(request, job)
    field = fields.FIELDS.get(job.field)
    data = _parse(job) if field and field.shape in ("line", "list") else {}
    ctx = {
        "job": job,
        "shape": field.shape if field else job.kind,  # line|text|list|doc|meeting
        "options": [o for o in data.get("options") or [] if isinstance(o, str)][:3],
        "items": [o for o in data.get("items") or [] if isinstance(o, str)][:20],
        "active": job.status in AiJob.ACTIVE,
        "error_text": _message(job.error) if job.status in ("failed", "cancelled") else "",
        "setup_errors": SETUP_ERRORS,
        "org_line": _org_line(request.user, job.org),
        "source_line": _source_line(job),
    }
    return render(request, "assist/_job.html", ctx, status=status)


@login_required
@require_POST
def job_create(request):
    """POST {field, target, input, options(JSON)} → 작업 조각(폴링 시작)."""
    field = request.POST.get("field", "")
    target = request.POST.get("target", "")
    kind = fields.kind_of(field)
    if kind is None:
        return _error(request, BAD_FIELD, 400)
    allowed = fields.FIELDS[field].targets if kind == "field" else (fields.MODES[field][1],)
    tkind, _, tid = target.partition(":")
    if tkind not in allowed or not tid.isdigit():
        return _error(request, BAD_TARGET, 400)
    org = current_org(request)
    if org is None:
        raise Http404
    if not services.ai_on(request.user, org):
        return _error(request, ERROR_TEXT["org_disabled"], 403)
    try:
        options = json.loads(request.POST.get("options") or "{}")
    except ValueError:
        options = {}
    try:
        job = services.create_job(
            request.user,
            org,
            field=field,
            target=target,
            user_input=request.POST.get("input", "")[: AiJob.MAX_INPUT],
            options=options if isinstance(options, dict) else {},
        )
    except services.RateLimited as e:
        return _service_error(request, e, 429)
    except ServiceError as e:
        return _service_error(request, e)
    return _job(request, job)


@login_required
@require_GET
def job_detail(request, job_id: int):
    """1초 폴링. ?s=<지난 상태>와 같고 아직 진행 중이면 204(화면을 다시 그리지 않아 읽기 프로그램이 조용하다)."""
    job = _own_job(request, job_id)
    if job.status in AiJob.ACTIVE and request.GET.get("s") == job.status:
        return HttpResponse(status=204)
    return _job(request, job)


@login_required
@require_POST
def job_cancel(request, job_id: int):
    job = _own_job(request, job_id)
    return _job(request, services.cancel_job(request.user, job.pk) or job)


@login_required
@require_POST
def job_apply(request, job_id: int):
    """문서·회의록 [적용](§7.3). 성공하면 화면을 새로 불러 이전 버전·본문을 다시 그린다."""
    job = _own_job(request, job_id)
    try:
        version = int(request.POST.get("version") or 0) or None
    except ValueError:
        version = None
    try:
        services.apply_job(
            request.user, job.pk, version=version, mode=request.POST.get("mode") or "replace"
        )
    except ConflictError:
        return _error(request, CONFLICT, 409)
    except ServiceError as e:
        return _service_error(request, e)
    return HttpResponse(status=204, headers={"HX-Refresh": "true"})


def _int(v):
    try:
        return int(v) if v else None
    except ValueError:
        return None


@login_required
@require_POST
def job_create_tasks(request, job_id: int):
    """[고른 후보로 태스크 만들기](§7.4). 행마다 결과를 표에 다시 그린다(실패 행만 오류)."""
    job = _own_job(request, job_id)
    if job.kind != "extract" or job.status != "done":
        raise Http404
    p = request.POST
    rows = []
    for raw in p.getlist("pick"):
        i = _int(raw)
        if i is None:
            continue
        rows.append(
            {
                "index": i,
                "title": p.get(f"title_{i}", "").strip(),
                "description": p.get(f"description_{i}", ""),
                "assignee_id": _int(p.get(f"assignee_{i}")),
                "due": p.get(f"due_{i}") or None,
                "project_id": _int(p.get(f"project_{i}")),
            }
        )
    if not rows:
        return _error(
            request, "선택한 태스크 후보가 없습니다. 만들 후보를 하나 이상 선택해 주세요.", 400
        )  # COPY:ai_pick_none
    try:
        results = extract.create_from_candidates(job, rows, request.user)
    except ServiceError as e:
        return _service_error(request, e)
    return _candidates(request, job, results)
