"""회의록 사용자 API(IMPL-PLAN-9 v2 §4.1). 사용자의 AI(MCP·스킬)가 음성 회의 전사를 읽고 정리한다.

가시성은 `visible_notes` 하나(초안은 시작자·조직 관리자만). AI 편집은 `ai.edit_text` 정책을 타고,
확정은 AI가 할 수 없다(사람이 웹에서).
"""

from ninja import Router, Schema
from ninja.errors import HttpError

from notes import services as ns
from orgs.models import Team
from projects.services import visible_projects
from tasks.services import get_visible_task

from ..context import ctx, org_or_404
from ..schemas import ErrorOut

router = Router(tags=["notes"])


def note_out(n, *, body: bool = True, transcript: bool = False) -> dict:
    rec = getattr(n, "recording", None)
    out = {
        "id": n.pk,
        "org_id": n.org_id,
        "title": n.title,
        "status": n.status,
        "source": n.source,
        "project_id": n.project_id,
        "project_name": n.project.name if n.project_id else "",
        "team_id": n.team_id,
        "created_on": n.created_on,
        "created_by": n.created_by.display_name,
        "tags": n.tags,
        "version": n.version,
        "updated_at": n.updated_at,
        "task_ids": [t.pk for t in n.tasks.all()],
        "recording": None
        if rec is None
        else {
            "status": rec.status,
            "started_at": rec.started_at,
            "ended_at": rec.ended_at,
            "end_reason": rec.end_reason,
            "participant_count": len(rec.participants or []),
            "engines": (rec.stats or {}).get("engines", []),
        },
    }
    if body:
        out["body_md"] = n.body_md
    if transcript and rec is not None:
        out["recording"].update(
            transcript_md=rec.transcript_md, stats=rec.stats, participants=rec.participants
        )
    return out


def _qs(request):
    return (
        ns.visible_notes(request.auth)
        .select_related("project", "created_by", "org", "recording")
        .prefetch_related("tasks")
    )


def _note_or_404(request, note_id: int):
    n = _qs(request).filter(pk=note_id).first()
    if n is None:
        raise HttpError(404, "회의록을 찾을 수 없습니다.")
    return n


@router.get("/orgs/{org_id}/notes", response=dict)
def list_notes(request, org_id: int, status: str | None = None, project: int | None = None):
    """회의록 목록(본문 제외). status=draft|final, project로 좁힌다. 초안은 내가 볼 수 있는 것만."""
    org = org_or_404(request, org_id)
    qs = _qs(request).filter(org=org)
    if status:
        qs = qs.filter(status=status)
    if project is not None:
        qs = qs.filter(project_id=project)
    return {"items": [note_out(n, body=False) for n in qs[:200]]}


@router.get("/notes/{note_id}", response=dict)
def get_note(request, note_id: int, transcript: bool = False):
    """본문까지. transcript=1이면 녹음의 전사 원문·통계·참여자를 함께 준다."""
    return note_out(_note_or_404(request, note_id), transcript=transcript)


class NotePatchIn(Schema):
    version: int
    title: str | None = None
    body_md: str | None = None
    tags: list[str] | None = None
    task_ids: list[int] | None = None  # 이 회의록에 태스크를 더 연결한다(빼지는 않는다)


@router.patch("/notes/{note_id}", response={200: dict, 400: ErrorOut, 403: ErrorOut, 409: dict})
def patch_note(request, note_id: int, payload: NotePatchIn):
    """제목·본문·태그 고치기. version이 다르면 409와 최신 회의록. 한 항목마다 version이 1 오른다."""
    n = _note_or_404(request, note_id)
    c = ctx(request)
    version = payload.version
    for field in ("title", "body_md", "tags"):
        value = getattr(payload, field)
        if value is None:
            continue
        n = ns.update_note(
            n, field, value, actor=c["actor"], expected_version=version, source=c["source"]
        )
        version = n.version
    for task_id in payload.task_ids or []:
        task = get_visible_task(c["actor"], task_id)
        if task is None:
            raise HttpError(404, "태스크를 찾을 수 없습니다.")
        ns.link_task(n, task, c["actor"], source=c["source"])
    return note_out(_note_or_404(request, note_id))


class FinalizeIn(Schema):
    project_id: int | None = None
    team_id: int | None = None


@router.post("/notes/{note_id}/finalize", response={200: dict, 400: ErrorOut, 403: ErrorOut})
def finalize_note(request, note_id: int, payload: FinalizeIn):
    """초안 확정과 공개 범위(프로젝트·팀·둘 다 없으면 조직 공통). AI(source=mcp)는 403."""
    n = _note_or_404(request, note_id)
    c = ctx(request)
    project = team = None
    if payload.project_id is not None:
        project = visible_projects(c["actor"]).filter(pk=payload.project_id).first()
        if project is None:
            raise HttpError(404, "프로젝트를 찾을 수 없습니다.")
    if payload.team_id is not None:
        team = Team.objects.filter(pk=payload.team_id).first()
        if team is None:
            raise HttpError(404, "팀을 찾을 수 없습니다.")
    ns.finalize_note(n, actor=c["actor"], source=c["source"], project=project, team=team)
    return note_out(_note_or_404(request, note_id))
