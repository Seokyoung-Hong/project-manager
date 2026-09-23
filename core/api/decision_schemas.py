"""HTTP schemas for gist-only task decision records.

The write schema deliberately has no transcript, message, raw_text, or verbatim
field. MCP clients must submit a concise, neutral account of the user's intent.
"""

from datetime import datetime
from typing import Literal
from uuid import UUID

from ninja import Schema
from pydantic import Field

DecisionKind = Literal["user_input", "ai_judgment"]
DecisionInputType = Literal[
    "major_choice",
    "requirement",
    "answer",
    "steer",
    "implementation_instruction",
    "ai_workflow_instruction",
]
EvidenceBasis = Literal["explicit_reply", "explicit_instruction", "inferred"]
DecisionStatus = Literal[
    "captured", "proposed", "confirmed", "rejected", "recorded", "superseded"
]


class DecisionCreateIn(Schema):
    """A structured summary, never the conversation that produced it."""

    kind: DecisionKind
    input_type: DecisionInputType | None = None
    question_summary: str = Field(default="", max_length=300)
    summary: str = Field(min_length=1, max_length=800)
    reason_summary: str = Field(default="", max_length=500)
    alternatives: list[str] = Field(default_factory=list, max_length=10)
    impact_summary: str = Field(default="", max_length=500)
    evidence_basis: EvidenceBasis | None = None
    client_name: str = Field(default="", max_length=80)
    session_ref: str = Field(default="", max_length=160)
    source_time: datetime | None = None
    client_request_id: UUID | None = None
    supersedes_id: int | None = Field(default=None, gt=0)

    class Config:
        extra = "forbid"


class DecisionRejectIn(Schema):
    reason_summary: str = Field(default="", max_length=500)

    class Config:
        extra = "forbid"


class DecisionRecordOut(Schema):
    id: int
    task_id: int
    kind: DecisionKind
    input_type: str | None = None
    status: DecisionStatus
    question_summary: str
    summary: str
    reason_summary: str
    rejection_reason: str
    alternatives: list[str]
    impact_summary: str
    evidence_basis: str
    source: str
    client_name: str
    session_ref: str
    subject_user_id: int | None = None
    subject_user_name: str = ""
    recorded_by_id: int | None = None
    confirmed_by_id: int | None = None
    supersedes_id: int | None = None
    created_at: datetime
    confirmed_at: datetime | None = None


class DecisionListOut(Schema):
    items: list[DecisionRecordOut]
    total: int
    limit: int
    offset: int


class DecisionConflictOut(Schema):
    detail: str
    latest: DecisionRecordOut
