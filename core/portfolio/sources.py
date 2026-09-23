"""Privacy-safe decision record queries for portfolio drafts.

Only structured summaries are returned. The web-only ``verbatim_text`` field is
intentionally never selected or serialized here.
"""

from django.core.exceptions import ValidationError
from django.db.models import Q

from orgs.models import OrgMembership
from tasks.models import TaskDecisionRecord

MAX_PAGE_SIZE = 100
DEFAULT_PAGE_SIZE = 50


def _member_org_ids(user):
    """Return organizations the active user can see, without trusting a caller scope."""
    if not getattr(user, "is_authenticated", False) or not getattr(user, "is_active", False):
        return OrgMembership.objects.none().values_list("org_id", flat=True)
    return OrgMembership.objects.filter(user_id=user.pk).values_list("org_id", flat=True)


def _allowed_source_records(user):
    """Base queryset for this user's own decisions plus accessible AI judgments."""
    member_org_ids = _member_org_ids(user)
    own_user_inputs = Q(
        kind="user_input",
        status__in=("captured", "confirmed"),
    ) & (Q(subject_user_id=user.pk) | Q(confirmed_by_id=user.pk))
    ai_context = Q(kind="ai_judgment", status="recorded")
    return (
        TaskDecisionRecord.objects.filter(
            task__project__org_id__in=member_org_ids,
        )
        .filter(own_user_inputs | ai_context)
        .select_related("task", "task__project")
        .order_by("created_at", "id")
    )


def _serialize_source(record):
    """Serialize only the decision gist and safe project/task context."""
    result = {
        "id": record.pk,
        "kind": record.kind,
        # Keep AI judgments explicitly contextual; never imply they are the user's choice.
        "portfolio_role": "context" if record.kind == "ai_judgment" else "user_decision",
        "input_type": record.input_type,
        "status": record.status,
        "summary": record.summary,
        "reason_summary": record.reason_summary,
        "impact_summary": record.impact_summary,
        "evidence_basis": record.evidence_basis,
        "created_at": record.created_at.isoformat(),
        "task_id": record.task_id,
        "task_number": record.task.number,
        "project_id": record.task.project_id,
        "project_name": record.task.project.name,
        "org_id": record.task.project.org_id,
    }
    if record.confirmed_at:
        result["confirmed_at"] = record.confirmed_at.isoformat()
    return result


def list_portfolio_sources(
    user,
    *,
    org_id=None,
    project_id=None,
    from_date=None,
    to_date=None,
    input_type=None,
    limit=DEFAULT_PAGE_SIZE,
    offset=0,
):
    """List a page of portfolio-eligible records as gist-only dictionaries.

    ``from_date`` and ``to_date`` are inclusive record creation dates. An
    inaccessible organization yields an empty page rather than revealing
    whether records or projects exist there.
    """
    try:
        limit = int(limit)
        offset = int(offset)
    except (TypeError, ValueError) as exc:
        raise ValidationError("limit and offset must be integers") from exc
    if limit < 1 or offset < 0:
        raise ValidationError("limit must be positive and offset must be non-negative")
    limit = min(limit, MAX_PAGE_SIZE)

    records = _allowed_source_records(user)
    if org_id is not None:
        records = records.filter(task__project__org_id=org_id)
    if project_id is not None:
        records = records.filter(task__project_id=project_id)
    if from_date is not None:
        records = records.filter(created_at__date__gte=from_date)
    if to_date is not None:
        records = records.filter(created_at__date__lte=to_date)
    if input_type is not None:
        records = records.filter(kind="user_input", input_type=input_type)

    total = records.count()
    page = records[offset : offset + limit]
    return {
        "items": [_serialize_source(record) for record in page],
        "total": total,
        "limit": limit,
        "offset": offset,
    }


def get_allowed_records(user, record_ids):
    """Validate and return all selected eligible records in caller-supplied order.

    Raises ``ValidationError`` if any id is malformed, inaccessible, superseded,
    or otherwise not eligible. No partial result is returned.
    """
    try:
        ids = list(dict.fromkeys(int(record_id) for record_id in record_ids))
    except (TypeError, ValueError) as exc:
        raise ValidationError("record_ids must contain integer ids") from exc
    if not ids:
        return []

    allowed = {record.pk: record for record in _allowed_source_records(user).filter(pk__in=ids)}
    if len(allowed) != len(ids):
        raise ValidationError("One or more decision records are unavailable for this portfolio")
    return [allowed[record_id] for record_id in ids]
