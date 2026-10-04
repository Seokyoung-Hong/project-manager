from datetime import date

from django.db import transaction
from ninja import Router, Schema
from ninja.errors import HttpError

from accounts.models import IdempotencyKey, User
from orgs.models import Organization, Team
from orgs.services import is_member, orgs_of
from projects.models import Project
from tasks import work_requests as wr
from tasks.models import WorkRequest

from ..context import clamp_page, ctx, idem_key
from ..schemas import ErrorOut
from ..serialize import request_out, task_out

router = Router(tags=["requests"])

BOXES = ("received", "sent", "all")


class RequestCreateIn(Schema):
    org_id: int
    kind: str = "work"  # work | general
    title: str
    body: str = ""
    team_id: int | None = None
    to_user_id: int | None = None
    due_date: date | None = None


class RequestAcceptIn(Schema):
    project_id: int | None = None
    assignee_id: int | None = None
    due_date: date | None = None
    note: str = ""


class RequestNoteIn(Schema):
    note: str = ""


def _not_found(what: str):
    return HttpError(400, f"{what}을(를) 찾을 수 없습니다.")


def _request_or_404(request, request_id: int) -> WorkRequest:
    req = wr.get_visible_request(request.auth, request_id)
    if req is None:
        raise HttpError(404, "요청을 찾을 수 없습니다.")
    return req


def _detail(user, req) -> dict:
    return {
        **request_out(req),
        "can_answer": req.is_open and wr.can_respond(user, req),
        "can_cancel": req.is_open and req.requested_by_id == user.pk,
        "can_complete": req.kind == "general"
        and req.status == "accepted"
        and wr.can_respond(user, req),
    }


@router.get("", response={200: dict, 400: ErrorOut})
def list_requests(
    request,
    box: str = "received",
    status: str | None = None,
    org: int | None = None,
    limit: int = 50,
    offset: int = 0,
):
    if box not in BOXES:
        raise HttpError(400, f"box는 {', '.join(BOXES)} 중 하나여야 합니다.")
    user = request.auth
    qs = wr.received(user) if box == "received" else wr.visible_requests(user)
    if box == "sent":
        qs = qs.filter(requested_by=user)
    if org is not None:
        qs = qs.filter(org_id=org)
    if status:
        values = [s.strip() for s in status.split(",") if s.strip()]
        bad = [s for s in values if s not in dict(WorkRequest.STATUSES)]
        if bad:
            raise HttpError(
                400,
                f"알 수 없는 상태: {', '.join(bad)}. 가능한 값: {', '.join(dict(WorkRequest.STATUSES))}",
            )
        qs = qs.filter(status__in=values)
    qs = qs.order_by("-id")
    limit, offset = clamp_page(limit, offset)
    return {
        "items": [request_out(r) for r in qs[offset : offset + limit]],
        "total": qs.count(),
        "limit": limit,
        "offset": offset,
    }


@router.get("/{request_id}", response=dict)
def get_request(request, request_id: int):
    return _detail(request.auth, _request_or_404(request, request_id))


@router.post("", response={201: dict, 400: ErrorOut})
def create_request_ep(request, payload: RequestCreateIn):
    c = ctx(request)
    org = Organization.objects.filter(pk=payload.org_id, pk__in=orgs_of(c["actor"])).first()
    if org is None:
        raise _not_found("조직")
    key = idem_key(request)
    if key:
        # 키는 사람마다 하나의 대상에만 쓴다(idem_user_key). 다른 종류에 쓴 키면 만들기 전에 거절한다.
        hit = IdempotencyKey.objects.filter(user=c["actor"], key=key).first()
        if hit and hit.target_type != "request":
            return 400, {"detail": {"idempotency_key": "이미 다른 작업에 쓴 키입니다."}}
        if hit:
            return 201, request_out(WorkRequest.objects.get(pk=hit.target_id))
    team = to_user = None
    if payload.team_id is not None:
        team = Team.objects.filter(pk=payload.team_id, org=org).first()
        if team is None:
            raise _not_found("팀")
    if payload.to_user_id is not None:
        to_user = User.objects.filter(pk=payload.to_user_id).first()
        if to_user is None or not is_member(to_user, org):
            raise _not_found("받는 사람")
    with transaction.atomic():  # 키 기록이 실패하면 요청·알림도 남기지 않는다
        req = wr.create_request(
            org=org,
            kind=payload.kind,
            title=payload.title,
            body=payload.body,
            team=team,
            to_user=to_user,
            due_date=payload.due_date,
            actor=c["actor"],
            source=c["source"],
        )
        if key:
            IdempotencyKey.objects.create(
                user=c["actor"], key=key, target_type="request", target_id=req.pk
            )
    return 201, request_out(req)


@router.post("/{request_id}/accept", response={200: dict, 400: ErrorOut})
def accept_request(request, request_id: int, payload: RequestAcceptIn):
    req = _request_or_404(request, request_id)
    project = assignee = None
    if payload.project_id is not None:
        project = Project.objects.filter(pk=payload.project_id, org=req.org).first()
        if project is None:
            raise _not_found("프로젝트")
    if payload.assignee_id is not None:
        assignee = User.objects.filter(pk=payload.assignee_id).first()
        if assignee is None or not is_member(assignee, req.org):
            raise _not_found("담당자")
    req = wr.accept(
        req,
        request.auth,
        source=ctx(request)["source"],
        project=project,
        assignee=assignee,
        due_date=payload.due_date,
        note=payload.note,
    )
    out = request_out(req)
    if req.task_id:
        out["task"] = task_out(req.task)
    return out


@router.post("/{request_id}/decline", response={200: dict, 400: ErrorOut})
def decline_request(request, request_id: int, payload: RequestNoteIn):
    req = _request_or_404(request, request_id)
    note, source = payload.note, ctx(request)["source"]
    return request_out(wr.decline(req, request.auth, note, source=source))


@router.post("/{request_id}/cancel", response={200: dict, 400: ErrorOut})
def cancel_request(request, request_id: int):
    req = _request_or_404(request, request_id)
    return request_out(wr.cancel(req, request.auth, source=ctx(request)["source"]))


@router.post("/{request_id}/done", response={200: dict, 400: ErrorOut})
def complete_request(request, request_id: int, payload: RequestNoteIn):
    req = _request_or_404(request, request_id)
    note, source = payload.note, ctx(request)["source"]
    return request_out(wr.complete(req, request.auth, note, source=source))
