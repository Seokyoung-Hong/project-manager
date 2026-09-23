"""MCP client helpers for task decision records.

These helpers deliberately expose only concise, structured summaries. They do
not accept a transcript, message body, quotation, or verbatim-text field.
"""

from typing import Literal

from .core_client import Core

DecisionKind = Literal["user_input", "ai_judgment"]
InputType = Literal[
    "major_choice",
    "requirement",
    "answer",
    "steer",
    "implementation_instruction",
    "ai_workflow_instruction",
]
EvidenceBasis = Literal["explicit_reply", "explicit_instruction", "inferred"]


def list_task_decisions(
    core: Core,
    task_id: int,
    effective_only: bool = False,
    limit: int = 50,
    offset: int = 0,
) -> dict:
    """List concise decision summaries for a task, in server-defined time order.

    Set ``effective_only`` to exclude rejected and superseded records. Results
    are access-controlled by the ProjectManager API.
    """
    return core.get(
        f"/api/tasks/{task_id}/decisions",
        effective_only=effective_only,
        limit=limit,
        offset=offset,
    )


def record_task_decision(
    core: Core,
    task_id: int,
    kind: DecisionKind,
    summary: str,
    input_type: InputType | None = None,
    question_summary: str = "",
    reason_summary: str = "",
    alternatives: list[str] | None = None,
    impact_summary: str = "",
    evidence_basis: EvidenceBasis | None = None,
    client_name: str = "",
    session_ref: str = "",
    supersedes_id: int | None = None,
    client_request_id: str | None = None,
) -> dict:
    """Record a short gist of a user input or an important AI judgment.

    For ``user_input``, explicit replies/instructions use ``explicit_reply`` or
    ``explicit_instruction`` and are captured by the API. AI-inferred user
    choices use ``inferred`` and remain proposed for confirmation. For
    ``ai_judgment``, omit ``input_type`` and ``evidence_basis``; it is recorded
    as an AI judgment, never as a user decision.

    Send only neutral, concise summaries in the summary fields. Do not send
    conversation messages, transcripts, long quotations, private phrasing, or
    secrets. Verbatim storage is currently unsupported, even when requested;
    never bypass this tool's gist-only contract. ``client_request_id`` makes retries idempotent.
    """
    summary = (summary or "").strip()
    if not summary:
        raise ValueError("summary must contain a concise decision gist")
    limits = {
        "question_summary": (question_summary, 300),
        "summary": (summary, 800),
        "reason_summary": (reason_summary, 500),
        "impact_summary": (impact_summary, 500),
        "client_name": (client_name, 80),
        "session_ref": (session_ref, 160),
    }
    for field, (value, maximum) in limits.items():
        if len(value.strip()) > maximum:
            raise ValueError(f"{field} must be at most {maximum} characters; submit a shorter gist")
    if len(alternatives or []) > 10 or any(len(item.strip()) > 300 for item in alternatives or []):
        raise ValueError("alternatives must contain at most 10 short summaries (300 characters each)")

    if kind == "user_input":
        if input_type is None:
            raise ValueError("user_input requires input_type")
        if evidence_basis not in ("explicit_reply", "explicit_instruction", "inferred"):
            raise ValueError("user_input requires a valid evidence_basis")
    elif kind == "ai_judgment":
        if input_type is not None or evidence_basis is not None:
            raise ValueError("ai_judgment cannot be attributed to a user input")
    else:  # Runtime callers may bypass the MCP Literal schema.
        raise ValueError("kind must be user_input or ai_judgment")

    body = {
        "kind": kind,
        "input_type": input_type,
        "question_summary": question_summary.strip(),
        "summary": summary,
        "reason_summary": reason_summary.strip(),
        "alternatives": [item.strip() for item in (alternatives or []) if item.strip()],
        "impact_summary": impact_summary.strip(),
        "evidence_basis": evidence_basis,
        "client_name": client_name.strip(),
        "session_ref": session_ref.strip(),
        "supersedes_id": supersedes_id,
        "client_request_id": client_request_id,
    }
    headers = {"Idempotency-Key": client_request_id} if client_request_id else None
    return core.post(f"/api/tasks/{task_id}/decisions", body, headers=headers)
