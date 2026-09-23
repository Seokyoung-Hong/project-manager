"""Services for task decision records.

Decision text is deliberately a short gist. This module has no transcript or
message-array input, and rejects common credential-shaped strings before they
can be persisted.
"""

import re
import uuid

from django.db import IntegrityError, transaction
from django.db.models import Q
from django.utils import timezone

from common.errors import ConflictError, ServiceError
from orgs.services import is_member
from orgs.settings import effective

from .models import TaskDecisionRecord

_SECRET_PATTERNS = (
    re.compile(r"-----BEGIN (?:RSA |EC |OPENSSH )?PRIVATE KEY-----", re.I),
    re.compile(r"\bBearer\s+[A-Za-z0-9._~+/=-]{16,}", re.I),
    re.compile(r"\bpm_[A-Za-z0-9_-]{24,}\b"),
    re.compile(r"\bAKIA[0-9A-Z]{16}\b"),
    re.compile(r"\beyJ[A-Za-z0-9_-]{8,}\.[A-Za-z0-9_-]{8,}\.[A-Za-z0-9_-]{8,}\b"),
    re.compile(
        r"\b(?:api[_-]?key|access[_-]?token|refresh[_-]?token|client[_-]?secret|"
        r"password|passwd|authorization)\b\s*[:=]\s*['\"]?[^\s'\"]{8,}",
        re.I,
    ),
    re.compile(r"https?://[^\s/@:]+:[^\s/@]+@", re.I),
)

_USER_INPUT_TYPES = {value for value, _label in TaskDecisionRecord.INPUT_TYPES}
_KINDS = {value for value, _label in TaskDecisionRecord.KINDS}
_USER_STATUSES = {"captured", "proposed"}
_EVIDENCE = {value for value, _label in TaskDecisionRecord.EVIDENCE_BASES}
_SOURCES = {value for value, _label in TaskDecisionRecord.SOURCES}


def _require_member(task, actor):
    if actor is None or not is_member(actor, task.project.org):
        raise ServiceError({"org": "이 조직의 멤버가 아닙니다."})


def _require_mcp_write(task, actor, token):
    if token is None or token.user_id != getattr(actor, "pk", None) or token.scope != "write":
        raise ServiceError({"token": "쓰기 권한이 있는 본인 토큰이 필요합니다."})
    org = task.project.org
    if not effective("ai.enabled", org=org) or effective("ai.record_work", org=org) != "allow":
        raise ServiceError({"ai": "조직 정책에서 AI 작업 기록을 허용하지 않습니다."})


def _authorize(task, actor, source, token=None, *, writing=False):
    _require_member(task, actor)
    if source not in _SOURCES:
        raise ServiceError({"source": "기록 출처가 올바르지 않습니다."})
    # X-Source is supplied by the caller and cannot identify a browser session.
    # Every bearer-token write therefore obeys the same AI write policy, even
    # when the caller labels the request "api" or "web".
    if writing and (source == "mcp" or token is not None):
        _require_mcp_write(task, actor, token)


def _clean_summary(field, value, max_length, *, required=False):
    if not isinstance(value, str):
        raise ServiceError({field: "의사 요약은 문자열이어야 합니다."})
    cleaned = " ".join(value.replace("\x00", "").split())
    if required and not cleaned:
        raise ServiceError({field: "의사 요약을 입력해 주세요."})
    if len(cleaned) > max_length:
        raise ServiceError({field: f"{max_length}자 이내로 요지를 입력해 주세요."})
    if any(pattern.search(cleaned) for pattern in _SECRET_PATTERNS):
        raise ServiceError({field: "비밀값으로 보이는 내용은 기록할 수 없습니다. 의사 요지만 입력해 주세요."})
    return cleaned


def _clean_alternatives(value):
    if value in (None, ""):
        return []
    if not isinstance(value, (list, tuple)):
        raise ServiceError({"alternatives": "대안은 문자열 목록으로 입력해 주세요."})
    if len(value) > 10:
        raise ServiceError({"alternatives": "대안은 최대 10개까지 입력할 수 있습니다."})
    return [_clean_summary("alternatives", item, 300, required=True) for item in value]


def _find_record(task, record_id, actor):
    record = (
        TaskDecisionRecord.objects.select_for_update()
        .filter(pk=record_id, task=task)
        .first()
    )
    if record is None:
        raise ServiceError({"record": "이 태스크의 기록을 찾을 수 없습니다."})
    _require_member(task, actor)
    return record


def _matches_idempotent_retry(
    existing,
    *,
    kind,
    input_type,
    summary,
    question_summary,
    reason_summary,
    alternatives,
    impact_summary,
    status,
    evidence_basis,
    source,
    client_name,
    session_ref,
    source_time,
    supersedes_id,
):
    # Confirmation/exclusion/supersession changes workflow status after the
    # original capture. For user input the original status is deterministic:
    # inferred evidence is proposed, explicit evidence is captured.
    initial_status = (
        "proposed" if evidence_basis == "inferred" else "captured"
    ) if kind == "user_input" else "recorded"
    reason_matches = existing.reason_summary == reason_summary
    stable_fields_match = (
        existing.kind == kind
        and existing.input_type == input_type
        and existing.summary == summary
        and existing.question_summary == question_summary
        and reason_matches
        and existing.alternatives == alternatives
        and existing.impact_summary == impact_summary
        and existing.evidence_basis == evidence_basis
        and existing.source == source
        and existing.client_name == client_name
        and existing.session_ref == session_ref
        and existing.source_time == source_time
        and existing.supersedes_id == supersedes_id
    )
    if not stable_fields_match:
        return False
    if existing.status == status:
        return True
    # The request's status must match the deterministic creation status, while
    # the stored row may now have a legitimate workflow transition.
    return (
        status == initial_status
        and existing.status in {"confirmed", "rejected", "superseded"}
        and (existing.status != "superseded" or existing.superseding_records.exists())
    )


def create_record(
    task,
    *,
    actor,
    source,
    token=None,
    kind,
    input_type="",
    status=None,
    evidence_basis="",
    summary,
    question_summary="",
    reason_summary="",
    alternatives="",
    impact_summary="",
    client_name="",
    session_ref="",
    source_time=None,
    client_request_id="",
    supersedes_id=None,
):
    """Create a gist record; returns an existing record for a matching idempotency key."""
    _authorize(task, actor, source, token, writing=True)
    if kind not in _KINDS:
        raise ServiceError({"kind": "기록 종류가 올바르지 않습니다."})

    if kind == "user_input":
        if input_type not in _USER_INPUT_TYPES:
            raise ServiceError({"input_type": "사용자 입력 유형이 올바르지 않습니다."})
        if evidence_basis not in _EVIDENCE:
            raise ServiceError({"evidence_basis": "입력 근거 유형이 올바르지 않습니다."})
        status = status or ("proposed" if evidence_basis == "inferred" else "captured")
        if status not in _USER_STATUSES:
            raise ServiceError({"status": "새 사용자 입력은 captured 또는 proposed로 기록해야 합니다."})
        if evidence_basis == "inferred" and status != "proposed":
            raise ServiceError({"status": "AI가 추론한 입력은 사용자가 확인하기 전까지 proposed 상태여야 합니다."})
        if evidence_basis != "inferred" and status != "captured":
            raise ServiceError({"status": "명시적 사용자 입력은 captured 상태로 기록해야 합니다."})
        stored_input_type = input_type
        stored_evidence = evidence_basis
        subject_user = actor
    else:
        # AI judgment is an independent record type and can never be promoted
        # to user input by an MCP-supplied input_type/status.
        if input_type not in (None, "") or evidence_basis not in (None, ""):
            raise ServiceError({"kind": "AI 판단에는 사용자 입력 유형이나 답변 근거를 지정할 수 없습니다."})
        status = status or "recorded"
        if status != "recorded":
            raise ServiceError({"status": "새 AI 판단은 recorded 상태로만 기록할 수 있습니다."})
        stored_input_type = None
        stored_evidence = None
        subject_user = None

    summary = _clean_summary("summary", summary, 800, required=True)
    question_summary = _clean_summary("question_summary", question_summary, 300)
    reason_summary = _clean_summary("reason_summary", reason_summary, 500)
    impact_summary = _clean_summary("impact_summary", impact_summary, 500)
    alternatives = _clean_alternatives(alternatives)
    client_name = _clean_summary("client_name", client_name, 80)
    session_ref = _clean_summary("session_ref", session_ref, 200)

    request_uuid = None
    if client_request_id not in (None, ""):
        try:
            request_uuid = uuid.UUID(str(client_request_id))
        except (ValueError, TypeError, AttributeError):
            raise ServiceError({"client_request_id": "요청 중복 방지 ID가 UUID 형식이 아닙니다."}) from None

    with transaction.atomic():
        # Resolve retries before checking the target's current status: a prior
        # successful retry may itself have been superseded by a later request.
        if request_uuid is not None:
            existing = TaskDecisionRecord.objects.filter(
                task=task, subject_user=subject_user, client_request_id=request_uuid
            ).first()
            if existing is not None:
                if _matches_idempotent_retry(
                    existing,
                    kind=kind,
                    input_type=stored_input_type,
                    summary=summary,
                    question_summary=question_summary,
                    reason_summary=reason_summary,
                    alternatives=alternatives,
                    impact_summary=impact_summary,
                    status=status,
                    evidence_basis=stored_evidence,
                    source=source,
                    client_name=client_name,
                    session_ref=session_ref,
                    source_time=source_time,
                    supersedes_id=supersedes_id,
                ):
                    return existing
                raise ConflictError(existing)

        prior = None
        if supersedes_id is not None:
            prior = TaskDecisionRecord.objects.select_for_update().filter(
                pk=supersedes_id, task=task
            ).first()
            if prior is None:
                raise ServiceError({"supersedes_id": "같은 태스크의 대체 대상 기록이 필요합니다."})
            if prior.kind != kind or prior.status in {"rejected", "superseded"}:
                raise ServiceError({"supersedes_id": "같은 종류의 유효한 기록만 대체할 수 있습니다."})
            if prior.subject_user_id != getattr(subject_user, "pk", None):
                raise ServiceError({"supersedes_id": "본인에게 귀속된 기록만 대체할 수 있습니다."})

        try:
            with transaction.atomic():
                record = TaskDecisionRecord.objects.create(
                    task=task,
                    kind=kind,
                    input_type=stored_input_type,
                    status=status,
                    evidence_basis=stored_evidence,
                    summary=summary,
                    question_summary=question_summary,
                    reason_summary=reason_summary,
                    alternatives=alternatives,
                    impact_summary=impact_summary,
                    recorded_by=actor,
                    subject_user=subject_user,
                    source=source,
                    client_name=client_name,
                    session_ref=session_ref,
                    source_time=source_time,
                    client_request_id=request_uuid,
                    supersedes=prior,
                )
        except IntegrityError:
            if request_uuid is None:
                raise
            existing = TaskDecisionRecord.objects.filter(
                task=task, subject_user=subject_user, client_request_id=request_uuid
            ).first()
            if existing is None:
                raise
            if _matches_idempotent_retry(
                existing,
                kind=kind,
                input_type=stored_input_type,
                summary=summary,
                question_summary=question_summary,
                reason_summary=reason_summary,
                alternatives=alternatives,
                impact_summary=impact_summary,
                status=status,
                evidence_basis=stored_evidence,
                source=source,
                client_name=client_name,
                session_ref=session_ref,
                source_time=source_time,
                supersedes_id=supersedes_id,
            ):
                return existing
            raise ConflictError(existing) from None

        if prior is not None:
            prior.status = "superseded"
            # Confirmation is an immutable audit fact. A later record may make
            # the decision obsolete, but must not erase who confirmed it.
            prior.save(update_fields=["status"])
        return record


def list_records(task, *, actor, limit=50, offset=0):
    """Return ``(page_queryset, total_count)`` for all records visible to a member."""
    _authorize(task, actor, "web")
    try:
        limit, offset = int(limit), int(offset)
    except (TypeError, ValueError):
        raise ServiceError({"pagination": "페이지 값이 올바르지 않습니다."}) from None
    if limit < 1 or limit > 100 or offset < 0:
        raise ServiceError({"pagination": "limit은 1~100, offset은 0 이상이어야 합니다."})
    base = TaskDecisionRecord.objects.filter(task=task).select_related(
        "recorded_by", "subject_user", "confirmed_by", "supersedes"
    )
    total = base.count()
    return base.order_by("created_at", "id")[offset : offset + limit], total


def effective_records(task, *, actor):
    """Return current decisions, confirmed/captured user inputs, and recorded AI judgments."""
    _authorize(task, actor, "web")
    return (
        TaskDecisionRecord.objects.filter(task=task)
        .filter(
            Q(kind="user_input", status__in=["captured", "confirmed"])
            | Q(kind="ai_judgment", status="recorded")
        )
        .select_related("recorded_by", "subject_user", "confirmed_by", "supersedes")
        .order_by("created_at", "id")
    )


@transaction.atomic
def confirm_record(task, record_id, *, actor, source, token=None):
    """Confirm a candidate from the actual subject user's browser session only."""
    if source != "web" or token is not None:
        raise ServiceError({"source": "사용자 확인은 로그인한 웹 세션에서만 할 수 있습니다."})
    record = _find_record(task, record_id, actor)
    if record.kind != "user_input" or record.subject_user_id != actor.pk:
        raise ServiceError({"record": "본인에게 귀속된 사용자 입력만 확인할 수 있습니다."})
    if record.status == "confirmed" and record.confirmed_by_id == actor.pk:
        return record
    if record.status not in _USER_STATUSES:
        raise ServiceError({"record": "확인 대기 또는 수집 상태의 기록만 확인할 수 있습니다."})
    record.status = "confirmed"
    record.confirmed_by = actor
    record.confirmed_at = timezone.now()
    record.save(update_fields=["status", "confirmed_by", "confirmed_at"])
    return record


@transaction.atomic
def reject_record(task, record_id, *, actor, source, token=None, reason=""):
    """Exclude a user's captured/proposed input while preserving its audit row."""
    if source != "web" or token is not None:
        raise ServiceError({"source": "기록 제외는 로그인한 웹 세션에서만 할 수 있습니다."})
    record = _find_record(task, record_id, actor)
    if record.kind != "user_input" or record.subject_user_id != actor.pk:
        raise ServiceError({"record": "본인에게 귀속된 사용자 입력만 제외할 수 있습니다."})
    if record.status not in _USER_STATUSES:
        raise ServiceError({"record": "확인 대기 또는 수집 상태의 기록만 제외할 수 있습니다."})
    cleaned_reason = _clean_summary("reason", reason, 300)
    record.status = "rejected"
    record.rejection_reason = cleaned_reason
    record.save(update_fields=["status", "rejection_reason"])
    return record
