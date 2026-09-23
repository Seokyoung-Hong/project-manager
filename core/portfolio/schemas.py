"""Request and response schemas for private portfolio drafts.

The request models deliberately reject unknown fields. In particular, MCP
clients cannot accidentally pass chat transcripts through an unrecognized
``messages`` or ``conversation`` property.
"""

from datetime import date, datetime
from typing import Annotated

from ninja import Schema
from pydantic import ConfigDict, Field


class StrictSchema(Schema):
    model_config = ConfigDict(extra="forbid")


PositiveId = Annotated[int, Field(gt=0)]
PageLimit = Annotated[int, Field(ge=1, le=100)]
PageOffset = Annotated[int, Field(ge=0)]
NonBlankTitle = Annotated[str, Field(min_length=1, max_length=200)]
Markdown = Annotated[str, Field(max_length=200_000)]


class PortfolioSourcesQuery(Schema):
    org_id: int | None = None
    project_id: int | None = None
    from_date: date | None = None
    to_date: date | None = None
    input_type: str | None = None
    limit: PageLimit = 50
    offset: PageOffset = 0


class PortfolioSourceOut(Schema):
    id: int
    kind: str
    portfolio_role: str
    input_type: str | None
    status: str
    summary: str
    reason_summary: str
    impact_summary: str
    evidence_basis: str | None
    created_at: datetime
    confirmed_at: datetime | None = None
    task_id: int
    task_number: str
    project_id: int
    project_name: str
    org_id: int


class PortfolioSourcesOut(Schema):
    items: list[PortfolioSourceOut]
    total: int
    limit: int
    offset: int


class PortfolioSourceSnapshotOut(Schema):
    decision_record_id: int
    record_kind: str
    record_summary: str
    record_status: str
    record_created_at: datetime
    task_number: str
    project_name: str
    stale: bool = False


class PortfolioDraftOut(Schema):
    id: int
    org_id: int
    title: str
    scope_json: dict
    body_md: str
    status: str
    prompt_version: str
    version: int
    created_at: datetime
    updated_at: datetime
    sources: list[PortfolioSourceSnapshotOut]
    stale_source_ids: list[int] = Field(default_factory=list)


class PortfolioDraftCreateIn(StrictSchema):
    org_id: PositiveId
    title: NonBlankTitle
    source_ids: list[PositiveId] = Field(min_length=1, max_length=500)
    scope_json: dict = Field(default_factory=dict)
    body_md: Markdown = ""
    prompt_version: Annotated[str, Field(max_length=40)] = "v1"


class PortfolioDraftPatchIn(StrictSchema):
    version: Annotated[int, Field(ge=1)]
    title: NonBlankTitle | None = None
    body_md: Markdown | None = None
    source_ids: list[PositiveId] | None = Field(default=None, max_length=500)


class PortfolioDraftConflictOut(Schema):
    detail: str
    latest: PortfolioDraftOut


class PortfolioMarkdownOut(Schema):
    draft_id: int
    title: str
    markdown: str
    version: int
    stale_source_ids: list[int] = Field(default_factory=list)
