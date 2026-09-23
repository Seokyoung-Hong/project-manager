"""Personal portfolio source and private draft API."""

from datetime import date

from django.core.exceptions import ValidationError
from ninja import Router
from ninja.errors import HttpError

from common.errors import ConflictError

from . import drafts, sources
from .schemas import (
    PortfolioDraftConflictOut,
    PortfolioDraftCreateIn,
    PortfolioDraftOut,
    PortfolioDraftPatchIn,
    PortfolioMarkdownOut,
    PortfolioSourcesOut,
)

router = Router(tags=["portfolio"])


def _source_out(record):
    # Use the exact safe projection from sources.py. It never selects or
    # returns the web-only verbatim_text field.
    return sources._serialize_source(record)


def _draft_out(draft):
    stale_ids = set(getattr(draft, "stale_source_ids", ()))
    selected = draft.portfolio_sources
    return {
        "id": draft.pk,
        "org_id": draft.org_id,
        "title": draft.title,
        "scope_json": draft.scope_json,
        "body_md": draft.body_md,
        "status": draft.status,
        "prompt_version": draft.prompt_version,
        "version": draft.version,
        "created_at": draft.created_at,
        "updated_at": draft.updated_at,
        "sources": [
            {
                "decision_record_id": row.decision_record_id,
                "record_kind": row.record_kind,
                "record_summary": row.record_summary,
                "record_status": row.record_status,
                "record_created_at": row.record_created_at,
                "task_number": row.task_number,
                "project_name": row.project_name,
                "stale": getattr(row, "is_stale", row.decision_record_id in stale_ids),
            }
            for row in selected
        ],
        "stale_source_ids": sorted(stale_ids),
    }


@router.get("/portfolio-sources", response=PortfolioSourcesOut)
def list_sources(
    request,
    org_id: int | None = None,
    project_id: int | None = None,
    from_date: date | None = None,
    to_date: date | None = None,
    input_type: str | None = None,
    limit: int = 50,
    offset: int = 0,
):
    """Return only this user's eligible decision gists and AI context."""
    try:
        result = sources.list_portfolio_sources(
            request.auth,
            org_id=org_id,
            project_id=project_id,
            from_date=from_date,
            to_date=to_date,
            input_type=input_type,
            limit=limit,
            offset=offset,
        )
    except ValidationError as exc:
        raise HttpError(400, str(exc)) from exc
    return {
        **result,
        "items": [_source_out(item) if not isinstance(item, dict) else item for item in result["items"]],
    }


@router.post("/portfolio-drafts", response={201: PortfolioDraftOut})
def create_portfolio_draft(request, payload: PortfolioDraftCreateIn):
    """Create a private draft from explicitly selected source record IDs."""
    try:
        draft = drafts.create_draft(
            request.auth,
            org_id=payload.org_id,
            title=payload.title,
            body_md=payload.body_md,
            source_ids=payload.source_ids,
            scope_json=payload.scope_json,
            prompt_version=payload.prompt_version,
        )
    except ValidationError as exc:
        raise HttpError(400, str(exc)) from exc
    return 201, _draft_out(draft)


@router.get("/portfolio-drafts/{draft_id}", response=PortfolioDraftOut)
def get_portfolio_draft(request, draft_id: int):
    """Fetch a draft only for its owner; ownership is checked in the service."""
    try:
        draft = drafts.get_draft(request.auth, draft_id)
    except ValidationError as exc:
        raise HttpError(404, "포트폴리오 초안을 찾을 수 없습니다.") from exc
    return _draft_out(draft)


@router.patch(
    "/portfolio-drafts/{draft_id}",
    response={200: PortfolioDraftOut, 409: PortfolioDraftConflictOut},
)
def patch_portfolio_draft(request, draft_id: int, payload: PortfolioDraftPatchIn):
    """Edit Markdown/title/source selection with optimistic version checking."""
    try:
        draft = drafts.update_draft(
            request.auth,
            draft_id,
            version=payload.version,
            title=payload.title,
            body_md=payload.body_md,
            source_ids=payload.source_ids,
        )
    except ConflictError as exc:
        latest = drafts.get_draft(request.auth, exc.latest.pk)
        return 409, {"detail": "초안이 다른 곳에서 변경되었습니다.", "latest": _draft_out(latest)}
    except ValidationError as exc:
        raise HttpError(400, str(exc)) from exc
    return _draft_out(draft)


@router.get("/portfolio-drafts/{draft_id}/markdown", response=PortfolioMarkdownOut)
def export_portfolio_markdown(request, draft_id: int):
    """Export the owner's current Markdown and report stale selected sources."""
    try:
        draft = drafts.get_draft(request.auth, draft_id)
        markdown = drafts.export_markdown(request.auth, draft_id)
    except ValidationError as exc:
        raise HttpError(404, "포트폴리오 초안을 찾을 수 없습니다.") from exc
    return {
        "draft_id": draft.pk,
        "title": draft.title,
        "markdown": markdown,
        "version": draft.version,
        "stale_source_ids": sorted(set(getattr(draft, "stale_source_ids", ()))),
    }
