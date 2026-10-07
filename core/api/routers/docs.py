"""문서 API(IMPL-PLAN-11 §4.7). AI가 배경·결정·절차를 찾아 읽고 고치는 통로이기도 하다.

/api/docs는 Ninja의 Swagger UI가 쓰므로 문서 하나는 옛 경로 /api/project-docs/{id}를 그대로 쓰고,
조직 단위(목록·내보내기·가져오기)는 /api/orgs/{id}/docs 아래에 둔다.
가시성은 전부 projects.docs.visible_docs를 지난다. 지우기는 API 토큰(사람)만, MCP 도구는 없다.
"""

import json

from django.http import HttpResponse
from ninja import Router, Schema
from ninja.errors import HttpError

from common.errors import ServiceError
from orgs.models import Team
from orgs.services import orgs_of
from projects import docs as svc
from projects.models import Doc
from projects.services import visible_projects

from ..context import clamp_page, ctx
from ..schemas import ErrorOut

router = Router(tags=["docs"])


def doc_out(d, *, body: bool) -> dict:
    out = {
        "id": d.pk,
        "org_id": d.org_id,
        "kind": d.kind,
        "project_id": d.project_id,
        "project_name": d.project.name if d.project_id else "",
        "team_id": d.team_id,
        "parent_id": d.parent_id,
        "position": d.position,
        "is_template": d.is_template,
        "status": d.status,
        "title": d.title,
        "version": d.version,
        "updated_at": d.updated_at,
        "task_ids": [t.pk for t in d.tasks.all()],
        # 누가 마지막으로 고쳤는지. source가 "mcp"면 AI가 고친 것이다.
        "updated_by": d.updated_by.display_name if d.updated_by_id else "",
        "updated_source": d.updated_source,
    }
    if body:
        out["body_md"] = d.body_md
    return out


def _doc_or_404(request, doc_id: int) -> Doc:
    d = svc.get_visible_doc(request.auth, doc_id)
    if d is None:
        raise HttpError(404, "문서를 찾을 수 없습니다.")
    return d


def _org_or_404(request, org_id: int):
    org = orgs_of(request.auth).filter(pk=org_id).first()
    if org is None:
        raise HttpError(404, "조직을 찾을 수 없습니다.")
    return org


def _scope(request, project_id, team_id, parent_id):
    """id → 객체. 못 보는 것은 404(있는지도 알리지 않는다)."""
    project = team = parent = None
    if project_id is not None:
        project = visible_projects(request.auth).filter(pk=project_id).select_related("org").first()
        if project is None:
            raise HttpError(404, "프로젝트를 찾을 수 없습니다.")
    if team_id is not None:
        team = Team.objects.filter(pk=team_id, org__in=orgs_of(request.auth)).first()
        if team is None:
            raise HttpError(404, "팀을 찾을 수 없습니다.")
    if parent_id is not None:
        parent = _doc_or_404(request, parent_id)
    return project, team, parent


def _page(qs, limit, offset):
    total = qs.count()
    limit, offset = clamp_page(limit, offset)
    return {
        "items": [doc_out(d, body=False) for d in qs[offset : offset + limit]],
        "total": total,
        "limit": limit,
        "offset": offset,
    }


# ---------- 읽기 ----------


@router.get("/project-docs", response=dict)
def list_docs(
    request,
    project: int | None = None,
    org: int | None = None,
    team: int | None = None,
    parent: int | None = None,
    kind: str = "doc",
    template: bool = False,
    q: str | None = None,
    limit: int = 50,
    offset: int = 0,
):
    """문서 목록. 본문은 빼고 보낸다(GET /api/project-docs/{id}로 하나씩 읽는다).

    kind=doc|meeting|all, template=true면 템플릿만. q는 제목·본문 검색. parent=0이면 맨 위 문서만.
    """
    qs = svc.search_docs(request.auth, q, kind=None if kind == "all" else kind, template=template)
    if project is not None:
        qs = qs.filter(project_id=project)
    if org is not None:
        qs = qs.filter(org_id=org)
    if team is not None:
        qs = qs.filter(team_id=team)
    if parent is not None:
        qs = qs.filter(parent_id=parent or None)
    return _page(
        qs.select_related("project", "updated_by").prefetch_related("tasks"), limit, offset
    )


@router.get("/orgs/{org_id}/docs", response=dict)
def org_docs(
    request,
    org_id: int,
    kind: str = "doc",
    project: int | None = None,
    team: int | None = None,
    q: str | None = None,
    limit: int = 50,
    offset: int = 0,
):
    """조직의 문서(트리는 parent_id로 그린다)."""
    return list_docs(
        request,
        project=project,
        org=_org_or_404(request, org_id).pk,
        team=team,
        kind=kind,
        q=q,
        limit=limit,
        offset=offset,
    )


@router.get("/project-docs/{doc_id}", response=dict)
def get_doc(request, doc_id: int):
    """문서 하나의 본문(마크다운)까지."""
    return doc_out(_doc_or_404(request, doc_id), body=True)


@router.get("/project-docs/{doc_id}/revisions", response=list[dict])
def list_revisions(request, doc_id: int, body: bool = False):
    """이전 버전(최근 것부터, 최대 50개). body=true면 본문까지."""
    d = _doc_or_404(request, doc_id)
    out = []
    for r in d.revisions.select_related("saved_by"):
        row = {
            "id": r.pk,
            "version": r.version,
            "title": r.title,
            "saved_by": r.saved_by.display_name if r.saved_by_id else "",
            "source": r.source,
            "saved_at": r.saved_at,
        }
        if body:
            row["body_md"] = r.body_md
        out.append(row)
    return out


@router.get("/project-docs/{doc_id}/backlinks", response=dict)
def get_backlinks(request, doc_id: int):
    """이 문서를 가리키는 문서·태스크(볼 수 있는 것만)."""
    links = svc.backlinks(_doc_or_404(request, doc_id), request.auth)
    return {
        "docs": [{"id": d.pk, "title": d.title, "kind": d.kind} for d in links["docs"]],
        "tasks": [{"id": t.pk, "title": t.title} for t in links["tasks"]],
    }


def _file(name: str, data: bytes, content_type: str) -> HttpResponse:
    from urllib.parse import quote

    resp = HttpResponse(data, content_type=content_type)
    resp["Content-Disposition"] = f"attachment; filename*=UTF-8''{quote(name)}"
    return resp


@router.get("/project-docs/{doc_id}/export.md")
def export_md(request, doc_id: int):
    name, data = svc.export_md(_doc_or_404(request, doc_id))
    return _file(name, data, "text/markdown; charset=utf-8")


@router.get("/orgs/{org_id}/docs/export.zip")
def export_zip(request, org_id: int, kind: str = "doc", root: int | None = None):
    """볼 수 있는 문서를 트리 모양 그대로 ZIP으로. root를 주면 그 문서와 하위만."""
    org = _org_or_404(request, org_id)
    root_doc = _doc_or_404(request, root) if root is not None else None
    data = svc.export_zip(org, request.auth, root=root_doc, kind=kind)
    return _file(f"{org.name}-문서.zip", data, "application/zip")


# ---------- 쓰기 ----------
#
# AI도 문서를 만들고 고친다. 다만 지우지는 않는다 — 되돌릴 수 없는 일은 사람이 한다.
# 쓰기 범위(scope="write") 토큰만 여기 닿는다(api/auth.py의 TokenAuth가 막는다).


class DocCreateIn(Schema):
    project_id: int | None = None
    org_id: int | None = None
    team_id: int | None = None
    parent_id: int | None = None
    template_id: int | None = None
    kind: str = "doc"
    title: str = ""
    body_md: str = ""


class DocPatchIn(Schema):
    version: int
    title: str | None = None
    body_md: str | None = None


class DocRevertIn(Schema):
    version: int
    revision_id: int


class DocMoveIn(Schema):
    # 보낸 키만 바꾼다. parent_id=null이면 맨 위로.
    parent_id: int | None = None
    position: int | None = None
    project_id: int | None = None
    team_id: int | None = None


@router.post("/project-docs", response={201: dict, 400: ErrorOut, 403: ErrorOut})
def create_doc_ep(request, payload: DocCreateIn):
    """문서를 새로 만든다. org_id·project_id·team_id 중 범위를, parent_id로 상위 문서를 고른다."""
    project, team, parent = _scope(request, payload.project_id, payload.team_id, payload.parent_id)
    org = _org_or_404(request, payload.org_id) if payload.org_id is not None else None
    template = None
    if payload.template_id is not None:
        template = _doc_or_404(request, payload.template_id)
    d = svc.create_doc(
        actor=request.auth,
        org=org,
        kind=payload.kind,
        title=payload.title,
        body_md=payload.body_md,
        project=project,
        team=team,
        parent=parent,
        template=template,
        source=ctx(request)["source"],
    )
    return 201, doc_out(d, body=True)


@router.patch(
    "/project-docs/{doc_id}", response={200: dict, 400: ErrorOut, 403: ErrorOut, 409: dict}
)
def patch_doc(request, doc_id: int, payload: DocPatchIn):
    """문서를 고친다. version을 함께 보낸다 — 다르면 409와 함께 최신 문서를 돌려준다.

    한 번에 한 항목씩 적용하므로 title과 body_md를 같이 보내면 version이 두 번 오른다.
    """
    d = _doc_or_404(request, doc_id)
    source = ctx(request)["source"]
    version = payload.version
    for field in ("title", "body_md"):
        value = getattr(payload, field)
        if value is None:
            continue
        d = svc.update_doc(
            d, field, value, actor=request.auth, expected_version=version, source=source
        )
        version = d.version
    return doc_out(d, body=True)


@router.post(
    "/project-docs/{doc_id}/revert", response={200: dict, 400: ErrorOut, 403: ErrorOut, 409: dict}
)
def revert_doc(request, doc_id: int, payload: DocRevertIn):
    """이전 버전으로 되돌린다. version이 다르면 409."""
    d = _doc_or_404(request, doc_id)
    rev = d.revisions.filter(pk=payload.revision_id).first()
    if rev is None:
        raise HttpError(404, "이전 버전을 찾을 수 없습니다.")
    d = svc.revert_doc(
        d, rev, actor=request.auth, expected_version=payload.version, source=ctx(request)["source"]
    )
    return doc_out(d, body=True)


@router.post("/project-docs/{doc_id}/move", response={200: dict, 400: ErrorOut})
def move_doc(request, doc_id: int, payload: DocMoveIn):
    """상위 문서·순서·공개 범위를 바꾼다. 하위 문서의 공개 범위도 함께 바뀐다."""
    d = _doc_or_404(request, doc_id)
    sent = payload.model_fields_set
    project, team, parent = _scope(request, payload.project_id, payload.team_id, payload.parent_id)
    kw = {}
    if "parent_id" in sent:
        kw["parent"] = parent
    if "project_id" in sent:
        kw["project"] = project
    if "team_id" in sent:
        kw["team"] = team
    d = svc.move_doc(d, actor=request.auth, position=payload.position, **kw)
    return doc_out(d, body=False)


@router.delete("/project-docs/{doc_id}", response={200: dict, 400: ErrorOut, 403: ErrorOut})
def delete_doc(request, doc_id: int):
    """문서를 지운다(하위 문서도 함께). 작성자나 조직 관리자만. AI는 지우지 않는다."""
    if ctx(request)["source"] == "mcp":
        raise HttpError(403, "문서 삭제는 사람이 합니다.")
    return {"deleted_children": svc.delete_doc(_doc_or_404(request, doc_id), request.auth)}


@router.post("/orgs/{org_id}/docs/import", response={201: dict, 400: ErrorOut, 403: ErrorOut})
def import_docs(request, org_id: int):
    """.md 여러 개(또는 그것을 담은 ZIP)를 문서로 만든다. Notion 내보내기 정리·중복 방지 포함.

    multipart: `file` 여러 개 + project_id·team_id·parent_id(선택).
    JSON: {"files": [{"name": "a.md", "content": "..."}], "project_id"?, "team_id"?, "parent_id"?}
    """
    org = _org_or_404(request, org_id)
    if request.content_type.startswith("multipart/"):
        data = request.POST
        files = [(f.name, f.read()) for f in request.FILES.getlist("file")]
    else:
        try:
            data = json.loads(request.body or b"{}")
            files = [(f["name"], f["content"].encode()) for f in data.get("files", [])]
        except (ValueError, KeyError, TypeError, AttributeError):
            raise ServiceError({"files": "files는 [{name, content}] 목록이어야 합니다."}) from None

    def _id(key):
        v = data.get(key)
        try:
            return int(v) if v not in (None, "") else None
        except (TypeError, ValueError):
            raise ServiceError({key: "숫자 id여야 합니다."}) from None

    project, team, parent = _scope(request, _id("project_id"), _id("team_id"), _id("parent_id"))
    out = svc.import_md(
        org=org,
        actor=request.auth,
        files=files,
        project=project,
        team=team,
        parent=parent,
        source=ctx(request)["source"],
    )
    return 201, {
        "created": [doc_out(d, body=False) for d in out["created"]],
        "skipped": out["skipped"],
        "images": out["images"],
    }
