"""프로젝트 문서 읽기. AI가 배경·결정·절차를 찾아 읽는 통로다.

한 번의 호출로 조직 전체의 문서를 훑을 수 있어야 한다 — 프로젝트마다 따로 물으면
프로젝트가 스무 개인 조직에서 스물한 번을 왕복하게 된다.
AI도 만들고 고칠 수 있다. 다만 지우는 일은 화면에서 사람이 한다.
"""

from ninja import Router, Schema
from ninja.errors import HttpError

from projects.docs import create_doc, update_doc
from projects.models import ProjectDoc
from projects.services import visible_projects

from ..context import clamp_page, ctx
from ..schemas import ErrorOut

router = Router(tags=["docs"])


def _visible(request):
    return ProjectDoc.objects.filter(project__in=visible_projects(request.auth))


def doc_out(d, *, body: bool) -> dict:
    out = {
        "id": d.pk,
        "project_id": d.project_id,
        "project_name": d.project.name,
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


@router.get("", response=dict)
def list_docs(
    request,
    project: int | None = None,
    org: int | None = None,
    q: str | None = None,
    limit: int = 50,
    offset: int = 0,
):
    """문서 목록. project·org로 좁히고 q로 제목을 거른다. 본문은 빼고 보낸다.

    목록에 본문을 실으면 문서 수십 개짜리 조직에서 응답이 감당이 안 된다.
    본문은 GET /api/docs/{id}로 하나씩 읽는다.
    """
    qs = _visible(request).select_related("project").prefetch_related("tasks")
    if project is not None:
        qs = qs.filter(project_id=project)
    if org is not None:
        qs = qs.filter(project__org_id=org)
    if q:
        qs = qs.filter(title__icontains=q)
    total = qs.count()
    limit, offset = clamp_page(limit, offset)
    return {
        "items": [doc_out(d, body=False) for d in qs[offset : offset + limit]],
        "total": total,
        "limit": limit,
        "offset": offset,
    }


@router.get("/{doc_id}", response=dict)
def get_doc(request, doc_id: int):
    """문서 하나의 본문(마크다운)까지."""
    d = (
        _visible(request)
        .select_related("project")
        .prefetch_related("tasks")
        .filter(pk=doc_id)
        .first()
    )
    if d is None:
        raise HttpError(404, "문서를 찾을 수 없습니다.")
    return doc_out(d, body=True)


# ---------- 쓰기 ----------
#
# AI도 문서를 고친다. 다만 지우지는 않는다 — 되돌릴 수 없는 일은 화면에서 사람이 한다.
# 쓰기 범위(scope="write") 토큰만 여기 닿는다(api/auth.py의 TokenAuth가 막는다).


class DocCreateIn(Schema):
    project_id: int
    title: str = "제목 없는 문서"
    body_md: str = ""


class DocPatchIn(Schema):
    version: int
    title: str | None = None
    body_md: str | None = None


@router.post("", response={201: dict, 400: ErrorOut})
def create_doc_ep(request, payload: DocCreateIn):
    """문서를 새로 만든다. 배경·결정·절차를 글로 남길 때 쓴다."""
    p = visible_projects(request.auth).filter(pk=payload.project_id).select_related("org").first()
    if p is None:
        raise HttpError(404, "프로젝트를 찾을 수 없습니다.")
    d = create_doc(
        project=p,
        actor=request.auth,
        title=payload.title,
        body_md=payload.body_md,
        source=ctx(request)["source"],
    )
    return 201, doc_out(d, body=True)


@router.patch("/{doc_id}", response={200: dict, 400: ErrorOut, 409: dict})
def patch_doc(request, doc_id: int, payload: DocPatchIn):
    """문서를 고친다. version을 함께 보낸다 — 다르면 409와 함께 최신 문서를 돌려준다.

    한 번에 한 항목씩 적용하므로 title과 body_md를 같이 보내면 version이 두 번 오른다.
    """
    d = _visible(request).select_related("project", "project__org").filter(pk=doc_id).first()
    if d is None:
        raise HttpError(404, "문서를 찾을 수 없습니다.")
    source = ctx(request)["source"]
    version = payload.version
    for field in ("title", "body_md"):
        value = getattr(payload, field)
        if value is None:
            continue
        d = update_doc(d, field, value, actor=request.auth, expected_version=version, source=source)
        version = d.version
    return doc_out(d, body=True)
