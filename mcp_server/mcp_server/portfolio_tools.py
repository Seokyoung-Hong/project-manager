"""MCP helpers for private, source-grounded portfolio drafts.

Portfolio inputs are decision-record IDs and server-produced gist summaries.
These tools intentionally have no transcript or verbatim-message parameter.
"""

from datetime import date
from typing import Literal

from .core_client import Core

PortfolioInputType = Literal[
    "major_choice",
    "requirement",
    "answer",
    "steer",
    "implementation_instruction",
    "ai_workflow_instruction",
]


def list_portfolio_sources(
    core: Core,
    org_id: int | None = None,
    project_id: int | None = None,
    from_date: str | None = None,
    to_date: str | None = None,
    input_type: PortfolioInputType | None = None,
    limit: int = 50,
    offset: int = 0,
) -> dict:
    """List eligible portfolio source gists for the authenticated user.

    The core API enforces membership and record ownership and returns concise
    decision summaries, never conversation messages. Dates are inclusive
    ``YYYY-MM-DD`` record-creation dates. Use the returned source IDs when
    saving a draft, and build claims only from the returned evidence. Keep AI
    judgments clearly labeled as AI context; do not present them as user
    decisions or invent outcomes, responsibilities, dates, or reasons.
    """
    for field, value in (("from_date", from_date), ("to_date", to_date)):
        if value is not None:
            try:
                date.fromisoformat(value)
            except (TypeError, ValueError) as exc:
                raise ValueError(f"{field} must use YYYY-MM-DD format") from exc
    if limit < 1 or offset < 0:
        raise ValueError("limit must be positive and offset must be non-negative")
    if org_id is not None and org_id < 1:
        raise ValueError("org_id must be positive")
    if project_id is not None and project_id < 1:
        raise ValueError("project_id must be positive")

    return core.get(
        "/api/me/portfolio-sources",
        org_id=org_id,
        project_id=project_id,
        from_date=from_date,
        to_date=to_date,
        input_type=input_type,
        limit=limit,
        offset=offset,
    )


def create_portfolio_draft(
    core: Core,
    org_id: int,
    title: str,
    body_md: str,
    source_ids: list[int],
    scope_json: dict | None = None,
) -> dict:
    """Save an AI-written, private Markdown portfolio draft for the user.

    ``source_ids`` must be IDs returned by ``list_portfolio_sources``. The
    core API rechecks that every source is eligible, belongs to this
    organization, and is accessible to the authenticated user. Include only
    information supported by those source summaries. Never paste or submit
    raw chat/session messages, private phrasing, credentials, or transcript
    excerpts; this tool accepts only a concise Markdown draft and source IDs.
    Distinguish the user's decisions from AI judgments, label AI judgments as
    context, and omit unsupported claims instead of filling gaps by inference.
    Saving creates a private editable draft; it does not publish it.
    """
    if not isinstance(title, str) or not title.strip():
        raise ValueError("title must not be empty")
    if len(title.strip()) > 200:
        raise ValueError("title must be at most 200 characters")
    if not isinstance(body_md, str):
        raise ValueError("body_md must be a Markdown string")
    if len(body_md.encode("utf-8")) > 256 * 1024:
        raise ValueError("body_md must be at most 256 KB")
    if not isinstance(source_ids, list) or not source_ids:
        raise ValueError("source_ids must contain at least one source ID")
    if len(source_ids) > 500 or any(not isinstance(item, int) or item < 1 for item in source_ids):
        raise ValueError("source_ids must contain at most 500 positive integer IDs")
    if scope_json is not None and not isinstance(scope_json, dict):
        raise ValueError("scope_json must be a JSON object")

    return core.post(
        "/api/me/portfolio-drafts",
        {
            "org_id": org_id,
            "title": title.strip(),
            "body_md": body_md,
            "source_ids": source_ids,
            "scope_json": scope_json or {},
        },
    )


def get_portfolio_draft(core: Core, draft_id: int) -> dict:
    """Read the authenticated user's private draft and its source references.

    Access and current source eligibility are rechecked by the core API. The
    draft is not public; do not copy its contents to an external publisher
    unless the user separately asks for that action.
    """
    if draft_id < 1:
        raise ValueError("draft_id must be positive")
    return core.get(f"/api/me/portfolio-drafts/{draft_id}")


def update_portfolio_draft(
    core: Core,
    draft_id: int,
    version: int,
    title: str | None = None,
    body_md: str | None = None,
    source_ids: list[int] | None = None,
) -> dict:
    """Edit a private draft with optimistic version checking.

    Preserve source-grounded claims and the user-decision/AI-context
    distinction. Do not add transcript text. A version conflict requires
    fetching the latest draft before retrying.
    """
    if draft_id < 1 or version < 1:
        raise ValueError("draft_id and version must be positive")
    body = {"version": version}
    if title is not None:
        body["title"] = title
    if body_md is not None:
        if len(body_md.encode("utf-8")) > 256 * 1024:
            raise ValueError("body_md must be at most 256 KB")
        body["body_md"] = body_md
    if source_ids is not None:
        if not source_ids or len(source_ids) > 500:
            raise ValueError("source_ids must contain between 1 and 500 IDs")
        if any(not isinstance(item, int) or item < 1 for item in source_ids):
            raise ValueError("source_ids must contain positive integer IDs")
        body["source_ids"] = source_ids
    return core.patch(f"/api/me/portfolio-drafts/{draft_id}", body)


def export_portfolio_markdown(core: Core, draft_id: int) -> dict:
    """Fetch Markdown for a private draft after the core rechecks its sources.

    This returns content for user review/export; it does not publish or send
    the portfolio to a third party.
    """
    if draft_id < 1:
        raise ValueError("draft_id must be positive")
    return core.get(f"/api/me/portfolio-drafts/{draft_id}/markdown")
