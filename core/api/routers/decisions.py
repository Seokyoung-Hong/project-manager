"""Task decision record API.

All decision text is a gist. This API intentionally exposes no transcript/raw
message input and never treats an X-Source header as proof of a browser user.
"""

from ninja import Router
from ninja.errors import HttpError

from common.errors import ConflictError
from tasks.decision_services import (
    confirm_record,
    create_record,
    effective_records,
    list_records,
    reject_record,
)

from ..context import clamp_page, ctx, task_or_404
from ..decision_schemas import (
    DecisionConflictOut,
    DecisionCreateIn,
    DecisionListOut,
    DecisionRecordOut,
    DecisionRejectIn,
)

router = Router(tags=["task decisions"])


def _has_browser_session(request) -> bool:
    user = getattr(request, "user", None)
    auth = getattr(request, "auth", None)
    return (
        getattr(request, "api_token", None) is None
        and bool(request.COOKIES.get("sessionid"))
        and bool(getattr(user, "is_authenticated", False))
        and getattr(auth, "pk", None) == getattr(user, "pk", None)
    )


def _record_out(record):
    subject = getattr(record, "subject_user", None)
    return {
        "id": record.pk,
        "task_id": record.task_id,
        "kind": record.kind,
        "input_type": record.input_type,
        "status": record.status,
        "question_summary": record.question_summary,
        "summary": record.summary,
        "reason_summary": record.reason_summary,
        "rejection_reason": record.rejection_reason,
        "alternatives": record.alternatives or [],
        "impact_summary": record.impact_summary,
        "evidence_basis": record.evidence_basis or "",
        "source": record.source,
        "client_name": record.client_name,
        "session_ref": record.session_ref,
        "subject_user_id": record.subject_user_id,
        "subject_user_name": getattr(subject, "display_name", "") if subject else "",
        "recorded_by_id": record.recorded_by_id,
        "confirmed_by_id": record.confirmed_by_id,
        "supersedes_id": record.supersedes_id,
        "created_at": record.created_at,
        "confirmed_at": record.confirmed_at,
    }


@router.get("/{task_id}/decisions", response=DecisionListOut)
def get_task_decisions(
    request,
    task_id: int,
    limit: int = 50,
    offset: int = 0,
    effective_only: bool = False,
):
    task = task_or_404(request, task_id)
    page_limit, page_offset = clamp_page(limit, offset)
    # The service caps a decision page at 100 records.
    page_limit = min(page_limit, 100)
    c = ctx(request)
    if effective_only:
        records = effective_records(task, actor=c["actor"])
        total = records.count()
        page = records.order_by("created_at", "id")[page_offset : page_offset + page_limit]
    else:
        page, total = list_records(
            task, actor=c["actor"], limit=page_limit, offset=page_offset
        )
    return {
        "items": [_record_out(record) for record in page],
        "total": total,
        "limit": page_limit,
        "offset": page_offset,
    }


@router.post(
    "/{task_id}/decisions",
    response={201: DecisionRecordOut, 409: DecisionConflictOut},
)
def create_task_decision(request, task_id: int, payload: DecisionCreateIn):
    task = task_or_404(request, task_id)
    c = ctx(request)
    values = payload.dict()
    try:
        record = create_record(
            task,
            actor=c["actor"],
            source=c["source"],
            token=c["token"],
            **values,
        )
    except ConflictError as exc:
        return 409, {"detail": "conflict", "latest": _record_out(exc.latest)}
    return 201, _record_out(record)


@router.post(
    "/{task_id}/decisions/{record_id}/confirm", response=DecisionRecordOut
)
def confirm_task_decision(request, task_id: int, record_id: int):
    task = task_or_404(request, task_id)
    c = ctx(request)
    # X-Source is untrusted. Only the actual session-auth path, with no API token,
    # can turn an AI-proposed record into a user confirmation.
    if not _has_browser_session(request):
        raise HttpError(403, "의사결정 기록 확인은 로그인한 웹 세션에서만 가능합니다.")
    record = confirm_record(
        task,
        record_id,
        actor=c["actor"],
        source="web",
        token=None,
    )
    return _record_out(record)


@router.post(
    "/{task_id}/decisions/{record_id}/reject", response=DecisionRecordOut
)
def reject_task_decision(
    request, task_id: int, record_id: int, payload: DecisionRejectIn
):
    task = task_or_404(request, task_id)
    c = ctx(request)
    if not _has_browser_session(request):
        raise HttpError(403, "의사결정 기록 제외는 로그인한 웹 세션에서만 가능합니다.")
    record = reject_record(
        task,
        record_id,
        actor=c["actor"],
        source="web",
        token=None,
        reason=payload.reason_summary,
    )
    return _record_out(record)


@router.post(
    "/{task_id}/decisions/{record_id}/supersede",
    response={201: DecisionRecordOut, 409: DecisionConflictOut},
)
def supersede_task_decision(request, task_id: int, record_id: int, payload: DecisionCreateIn):
    task = task_or_404(request, task_id)
    c = ctx(request)
    values = payload.dict()
    if values.get("supersedes_id") not in (None, record_id):
        raise HttpError(400, "supersedes_id는 경로의 기록 id와 같아야 합니다.")
    values["supersedes_id"] = record_id
    try:
        record = create_record(
            task,
            actor=c["actor"],
            source=c["source"],
            token=c["token"],
            **values,
        )
    except ConflictError as exc:
        return 409, {"detail": "conflict", "latest": _record_out(exc.latest)}
    return 201, _record_out(record)
