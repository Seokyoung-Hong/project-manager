"""Private portfolio draft services.

Drafts retain gist-only snapshots of their selected decision records. Access to
the snapshots is conditional on the owner still being an organization member
and every referenced decision record still being eligible for that owner.
"""

import json

from django.core.exceptions import ValidationError
from django.db import transaction
from django.utils import timezone

from common.errors import ConflictError, ServiceError
from orgs.models import Organization
from orgs.services import is_member
from tasks.models import TaskDecisionRecord

from .models import PortfolioDraft, PortfolioSource
from .sources import get_allowed_records

MAX_BODY_BYTES = 256 * 1024


def _member_org(user, org_id):
    org = Organization.objects.filter(pk=org_id).first()
    if (
        org is None
        or not getattr(user, "is_authenticated", False)
        or not getattr(user, "is_active", False)
        or not is_member(user, org)
    ):
        raise ServiceError({"org": "이 조직의 멤버가 아닙니다."})
    return org


def _owned_draft(user, draft_id):
    draft = (
        PortfolioDraft.objects.filter(pk=draft_id, owner=user)
        .select_related("org", "owner")
        .first()
    )
    if draft is None:
        # Do not disclose whether another user's private draft exists.
        raise ServiceError({"draft": "포트폴리오 초안을 찾을 수 없습니다."})
    if not getattr(user, "is_active", False) or not is_member(user, draft.org):
        raise ServiceError({"org": "이 조직의 멤버가 아닙니다."})
    return draft


def _normalize_source_ids(source_ids):
    if source_ids is None or isinstance(source_ids, (str, bytes)):
        raise ServiceError({"source_ids": "출처 기록 ID 목록을 입력해 주세요."})
    try:
        ids = list(dict.fromkeys(int(item) for item in source_ids))
    except (TypeError, ValueError):
        raise ServiceError({"source_ids": "출처 기록 ID는 정수 목록이어야 합니다."}) from None
    if not ids:
        raise ServiceError({"source_ids": "최소 한 개의 출처 기록을 선택해 주세요."})
    if len(ids) > 500:
        raise ServiceError({"source_ids": "출처 기록은 한 초안에 500개까지 선택할 수 있습니다."})
    if any(item < 1 for item in ids):
        raise ServiceError({"source_ids": "출처 기록 ID가 올바르지 않습니다."})
    return ids


def _selected_records(user, org_id, source_ids):
    ids = _normalize_source_ids(source_ids)
    try:
        records = get_allowed_records(user, ids)
    except ValidationError:
        raise ServiceError({"source_ids": "선택한 출처 중 더 이상 사용할 수 없는 기록이 있습니다."}) from None
    if any(record.task.project.org_id != org_id for record in records):
        raise ServiceError({"source_ids": "같은 조직에서 사용할 수 있는 기록만 선택해 주세요."})
    return records


def _snapshot(draft, records):
    PortfolioSource.objects.bulk_create(
        [
            PortfolioSource(
                draft=draft,
                decision_record=record,
                record_kind=record.kind,
                record_summary=record.summary,
                record_status=record.status,
                record_created_at=record.created_at,
                task_number=record.task.number,
                project_name=record.task.project.name,
            )
            for record in records
        ]
    )


def _check_sources(user, draft):
    """Revalidate all sources and flag still-visible snapshots that have changed."""
    sources = list(
        draft.sources.select_related(
            "decision_record",
            "decision_record__task",
            "decision_record__task__project",
        ).order_by("record_created_at", "id")
    )
    if not sources:
        raise ServiceError({"source_ids": "출처가 없는 초안은 열 수 없습니다."})
    ids = [source.decision_record_id for source in sources]
    # A superseded source remains visible to its original subject and should be
    # flagged stale. A rejected/withdrawn source revokes access. Recheck owner,
    # org and project visibility every time; never trust only the saved FK.
    current = {
        record.pk: record
        for record in TaskDecisionRecord.objects.filter(
            pk__in=ids,
            task__project__org_id=draft.org_id,
        ).select_related("task", "task__project")
    }

    stale_ids = []
    for source in sources:
        record = current.get(source.decision_record_id)
        if record is None or record.task.project.org_id != draft.org_id:
            raise ServiceError({"source_ids": "초안의 출처 기록 중 더 이상 접근할 수 없는 기록이 있습니다."})
        if record.kind == "user_input":
            visible = (
                record.status in {"captured", "confirmed", "superseded"}
                and (record.subject_user_id == user.pk or record.confirmed_by_id == user.pk)
            )
        else:
            visible = record.status in {"recorded", "superseded"}
        if not visible:
            raise ServiceError({"source_ids": "초안의 출처 기록 중 더 이상 접근할 수 없는 기록이 있습니다."})
        stale = (
            record.kind != source.record_kind
            or record.summary != source.record_summary
            or record.status != source.record_status
            or record.task.number != source.task_number
            or record.task.project.name != source.project_name
        )
        source.is_stale = stale
        if stale:
            stale_ids.append(record.pk)
    # Consumers can display a warning; snapshots remain unchanged until the
    # user explicitly replaces the source selection through update_draft.
    draft.stale_source_ids = stale_ids
    draft.portfolio_sources = sources
    return sources


def _validate_title(title):
    if not isinstance(title, str):
        raise ServiceError({"title": "제목을 입력해 주세요."})
    title = title.strip()
    if not title:
        raise ServiceError({"title": "제목을 입력해 주세요."})
    if len(title) > 200:
        raise ServiceError({"title": "제목은 200자 이내로 입력해 주세요."})
    return title


def _validate_body(body_md):
    if not isinstance(body_md, str):
        raise ServiceError({"body_md": "Markdown 본문은 문자열이어야 합니다."})
    body_md = body_md.replace("\r\n", "\n").replace("\r", "\n")
    if len(body_md.encode("utf-8")) > MAX_BODY_BYTES:
        raise ServiceError({"body_md": "본문이 너무 깁니다 (256KB 상한)."})
    return body_md


def _validate_scope(scope_json):
    if scope_json is None:
        return {}
    if not isinstance(scope_json, dict):
        raise ServiceError({"scope_json": "출처 선택 범위는 JSON 객체여야 합니다."})
    try:
        encoded = json.dumps(scope_json, ensure_ascii=False, allow_nan=False)
    except (TypeError, ValueError):
        raise ServiceError({"scope_json": "출처 선택 범위는 JSON으로 표현할 수 있어야 합니다."}) from None
    if len(encoded.encode("utf-8")) > 16 * 1024:
        raise ServiceError({"scope_json": "출처 선택 범위는 16KB 이내여야 합니다."})
    return scope_json


@transaction.atomic
def create_draft(
    user,
    *,
    org_id,
    title,
    body_md,
    source_ids,
    scope_json=None,
    prompt_version="v1",
):
    """Create an owner-only draft with immutable, gist-only source snapshots."""
    org = _member_org(user, org_id)
    records = _selected_records(user, org.pk, source_ids)
    title = _validate_title(title)
    body_md = _validate_body(body_md)
    scope_json = _validate_scope(scope_json)
    if not isinstance(prompt_version, str) or len(prompt_version) > 40:
        raise ServiceError({"prompt_version": "프롬프트 버전은 40자 이내 문자열이어야 합니다."})
    draft = PortfolioDraft.objects.create(
        owner=user,
        org=org,
        title=title,
        body_md=body_md,
        scope_json=scope_json,
        prompt_version=prompt_version,
    )
    _snapshot(draft, records)
    draft.stale_source_ids = []
    draft.portfolio_sources = list(draft.sources.all())
    return draft


def get_draft(user, draft_id):
    """Fetch a private draft after rechecking owner membership and all sources."""
    draft = _owned_draft(user, draft_id)
    _check_sources(user, draft)
    return draft


def list_drafts(user, *, org_id=None, limit=50):
    """List lightweight metadata for the caller's accessible drafts only.

    Body text is deliberately omitted from the list contract. Drafts with a
    withdrawn or otherwise inaccessible source are omitted as inaccessible.
    """
    if not getattr(user, "is_authenticated", False) or not getattr(user, "is_active", False):
        return []
    try:
        limit = int(limit)
    except (TypeError, ValueError):
        raise ServiceError({"limit": "목록 개수는 정수여야 합니다."}) from None
    if limit < 1 or limit > 100:
        raise ServiceError({"limit": "목록 개수는 1~100 사이여야 합니다."})

    from orgs.models import OrgMembership

    memberships = OrgMembership.objects.filter(user=user)
    if org_id is not None:
        if not memberships.filter(org_id=org_id).exists():
            return []
        memberships = memberships.filter(org_id=org_id)
    drafts = list(
        PortfolioDraft.objects.filter(owner=user, org_id__in=memberships.values("org_id"))
        .select_related("org")
        .order_by("-updated_at", "-id")[:limit]
    )
    result = []
    for draft in drafts:
        try:
            _check_sources(user, draft)
        except ServiceError:
            continue
        result.append(
            {
                "id": draft.pk,
                "org_id": draft.org_id,
                "title": draft.title,
                "status": draft.status,
                "version": draft.version,
                "source_count": len(draft.portfolio_sources),
                "stale_source_ids": draft.stale_source_ids,
                "created_at": draft.created_at,
                "updated_at": draft.updated_at,
            }
        )
    return result


@transaction.atomic
def update_draft(
    user,
    draft_id,
    *,
    version,
    title=None,
    body_md=None,
    source_ids=None,
):
    """Edit an owned draft with optimistic locking; never rewrites markdown on refresh."""
    draft = PortfolioDraft.objects.select_for_update().filter(pk=draft_id, owner=user).select_related("org").first()
    if draft is None:
        raise ServiceError({"draft": "포트폴리오 초안을 찾을 수 없습니다."})
    if not getattr(user, "is_active", False) or not is_member(user, draft.org):
        raise ServiceError({"org": "이 조직의 멤버가 아닙니다."})
    # Even edits must fail closed if an existing source was withdrawn.
    _check_sources(user, draft)
    try:
        expected_version = int(version)
    except (TypeError, ValueError):
        raise ServiceError({"version": "초안 버전이 올바르지 않습니다."}) from None
    if expected_version != draft.version:
        raise ConflictError(draft)

    fields = {}
    if title is not None:
        fields["title"] = _validate_title(title)
    if body_md is not None:
        fields["body_md"] = _validate_body(body_md)
    records = None
    if source_ids is not None:
        records = _selected_records(user, draft.org_id, source_ids)

    for field, value in fields.items():
        setattr(draft, field, value)
    draft.version += 1
    draft.updated_at = timezone.now()
    draft.save(update_fields=[*fields.keys(), "version", "updated_at"])

    if records is not None:
        draft.sources.all().delete()
        _snapshot(draft, records)
        draft.stale_source_ids = []
        draft.portfolio_sources = list(draft.sources.all())
    else:
        _check_sources(user, draft)
    return draft


def export_markdown(user, draft_id):
    """Return Markdown only after rechecking that every selected source is eligible."""
    draft = get_draft(user, draft_id)
    body = draft.body_md.strip()
    if body.splitlines()[:1] == [f"# {draft.title}"]:
        return draft.body_md
    return f"# {draft.title}\n\n{draft.body_md}" if body else f"# {draft.title}\n"
