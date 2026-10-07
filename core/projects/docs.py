"""문서 — 조직·프로젝트·팀 범위의 마크다운 글과 그 트리(IMPL-PLAN-11 §4.4).

회의록도 문서의 한 종류(kind="meeting")라 편집·이전 버전·백링크·올리기·내보내기를 여기서 같이 쓴다.
회의 고유 규칙(음성 회의·진행자·확정)은 notes.services에 남는다.

규칙
- 한 번에 한 항목, 버전이 다르면 ConflictError, 본문 상한 256KB.
- 읽기·쓰기: 그 문서를 볼 수 있는 조직 멤버(visible_docs). 삭제: 작성자나 조직 관리자.
- 공개 범위(project·team)는 뿌리 문서에만 뜻이 있고 하위 문서는 뿌리 값을 복사해 둔다.
- ChangeLog는 쓰지 않는다(이전 버전이 이력). 삭제만 org 이력에 남긴다.
"""

import io
import re
import zipfile
from datetime import timedelta

from django.conf import settings
from django.db import transaction
from django.db.models import Exists, OuterRef, Q
from django.utils import timezone

from common.dates import now_kst
from common.errors import ConflictError, Forbidden, ServiceError
from orgs import settings as org_settings
from orgs.models import OrgMembership
from orgs.services import (
    ai_denied,
    can_view_team,
    is_admin,
    is_member,
    orgs_of,
    require_ai_enabled,
    visible_teams,
)

from .models import Doc, DocRevision
from .services import can_view_project, visible_projects

MAX_BODY = 256 * 1024  # 회의록과 같은 상한
MAX_DEPTH = 6
MAX_REVISIONS = 50
REVISION_WINDOW = timedelta(minutes=10)
EDITABLE = {"title", "body_md"}
MEETING_EDITABLE = EDITABLE | {"created_on", "tags", "project"}
# ZIP 가져오기 상한. 압축 폭탄을 막으려고 풀린 크기로 센다.
ZIP_MAX_FILES = 500
ZIP_MAX_TOTAL = 20 * 1024 * 1024

_KEEP = object()  # move_doc에서 "주지 않음"과 None(뿌리로)을 가른다


def _default_title(kind: str) -> str:
    return "제목 없는 회의록" if kind == "meeting" else "제목 없는 문서"


def _clean_body(value) -> str:
    value = (value or "").replace("\r\n", "\n")
    if len(value.encode()) > MAX_BODY:
        raise ServiceError({"body_md": "본문이 너무 깁니다 (256KB 상한)."})
    return value


def _clean_tags(tags) -> list[str]:
    """공백 제거·중복 제거·20자·최대 10개(회의록 태그와 같은 규칙)."""
    cleaned, seen = [], set()
    for t in tags or []:
        t = (t or "").strip()[:20]
        if t and t not in seen:
            seen.add(t)
            cleaned.append(t)
    return cleaned[:10]


# ---------- 가시성 ----------


def visible_docs(user, org=None):
    """문서 가시성 관문. 문서를 내보내는 모든 경로(웹·API·MCP·백링크·검색)가 이것을 지난다.

    확정(final): 프로젝트 문서는 그 프로젝트를, 팀 문서는 그 팀을 볼 수 있을 때만.
    초안(draft, 음성 회의 회의록): 작성자와 조직 관리자만. D3에서 녹음 진행자로 바뀐다.
    """
    if not getattr(user, "is_authenticated", False):
        return Doc.objects.none()
    qs = Doc.objects.filter(org__in=orgs_of(user))
    if org is not None:
        qs = qs.filter(org=org)
    admin = OrgMembership.objects.filter(user=user, role="admin", org_id=OuterRef("org_id"))
    final = (
        Q(status="final")
        & (Q(project__isnull=True) | Q(project__in=visible_projects(user)))
        & (Q(team__isnull=True) | Q(team__in=visible_teams(user)))
    )
    draft = Q(status="draft") & (Q(created_by=user) | Exists(admin))
    return qs.filter(final | draft)


def project_docs(project):
    """프로젝트 문서 탭의 목록. 프로젝트를 볼 수 있는지는 호출자가 이미 확인했다."""
    return project.docs.filter(kind="doc", is_template=False).select_related(
        "created_by", "updated_by"
    )


def can_view_doc(user, doc) -> bool:
    return visible_docs(user, doc.org).filter(pk=doc.pk).exists()


def get_visible_doc(user, doc_id: int):
    """내가 볼 수 있는 문서만. 아니면 None."""
    return (
        visible_docs(user)
        .select_related("org", "project", "project__org", "team", "created_by")
        .filter(pk=doc_id)
        .first()
    )


def _require_view(user, doc):
    if not can_view_doc(user, doc):
        raise ServiceError({"doc": "볼 수 없는 문서입니다."})


def _check_ai_edit(org, source: str, action: str):
    """AI 편집은 태스크 본문과 같은 정책(ai.edit_text)을 탄다."""
    require_ai_enabled(org, source, action)
    if source == "mcp" and org_settings.effective("ai.edit_text", org=org) == "deny":
        raise Forbidden({"ai": ai_denied(action)})


def _check_scope(org, actor, project, team):
    if project is not None and team is not None:
        raise ServiceError({"scope": "공개 범위는 프로젝트나 팀 중 하나만 고릅니다."})
    if project is not None:
        if project.org_id != org.pk:
            raise ServiceError({"project": "같은 조직의 프로젝트여야 합니다."})
        if not can_view_project(actor, project):
            raise ServiceError({"project": "볼 수 없는 프로젝트입니다."})
    if team is not None:
        if team.org_id != org.pk:
            raise ServiceError({"team": "같은 조직의 팀이어야 합니다."})
        if not can_view_team(actor, team):
            raise ServiceError({"team": "볼 수 없는 팀입니다."})


# ---------- 트리 ----------


def _depth(doc) -> int:
    """뿌리가 1. 부모를 따라 올라간다(깊이 ≤ 6이라 쿼리도 6번 이하)."""
    n, pid = 1, doc.parent_id
    while pid is not None:
        n += 1
        pid = Doc.objects.filter(pk=pid).values_list("parent_id", flat=True).first()
    return n


def _descendant_levels(doc) -> list[list[int]]:
    """하위 문서 id를 층별로. 첫 층이 자식이다."""
    levels, frontier = [], [doc.pk]
    while frontier:
        frontier = list(Doc.objects.filter(parent_id__in=frontier).values_list("pk", flat=True))
        if frontier:
            levels.append(frontier)
    return levels


def _check_parent(org, actor, parent, kind):
    if parent is None:
        return
    if kind == "meeting":
        raise ServiceError({"parent": "회의록에는 상위 문서를 둘 수 없습니다."})
    if parent.org_id != org.pk or parent.kind != "doc" or parent.is_template:
        raise ServiceError({"parent": "같은 조직의 일반 문서만 상위 문서가 될 수 있습니다."})
    _require_view(actor, parent)


# ---------- 이전 버전 ----------


def _record_revision(doc, actor, source, *, force_new=False):
    """같은 사람·10분 안이면 마지막 행을 덮어쓴다. 문서마다 50개까지."""
    now = timezone.now()
    last = doc.revisions.first()
    fields = dict(version=doc.version, title=doc.title, body_md=doc.body_md, saved_at=now)
    if (
        not force_new
        and last is not None
        and last.saved_by_id == actor.pk
        and now - last.saved_at < REVISION_WINDOW
    ):
        DocRevision.objects.filter(pk=last.pk).update(source=source, **fields)
    else:
        DocRevision.objects.create(doc=doc, saved_by=actor, source=source, **fields)
    old = doc.revisions.values_list("pk", flat=True)[MAX_REVISIONS:]
    DocRevision.objects.filter(pk__in=list(old)).delete()


# ---------- 만들기·고치기 ----------


@transaction.atomic
def create_doc(
    *,
    actor,
    org=None,
    kind="doc",
    title=None,
    body_md="",
    project=None,
    team=None,
    parent=None,
    template=None,
    created_on=None,
    tags=None,
    origin="web",
    source="web",
) -> Doc:
    """org를 안 주면 project(또는 parent)의 조직. 하위 문서는 부모의 공개 범위를 따른다."""
    if kind not in dict(Doc.KINDS):
        raise ServiceError({"kind": "알 수 없는 종류입니다."})
    org = org or (project.org if project else parent.org if parent else None)
    if org is None:
        raise ServiceError({"org": "조직을 고르세요."})
    if not is_member(actor, org):
        # 옛 프로젝트 문서 호출부는 "볼 수 없는 프로젝트"를 기대한다.
        raise ServiceError({"project": "볼 수 없는 프로젝트입니다."})
    require_ai_enabled(org, source, "문서 만들기")
    _check_parent(org, actor, parent, kind)
    if parent is not None:
        if _depth(parent) >= MAX_DEPTH:
            raise ServiceError({"parent": f"하위 문서는 {MAX_DEPTH}단계까지입니다."})
        project, team = parent.project, parent.team
    else:
        _check_scope(org, actor, project, team)
    if template is not None:
        if not (template.is_template and template.org_id == org.pk):
            raise ServiceError({"template": "이 조직의 템플릿이 아닙니다."})
        body_md = body_md or template.body_md
    meeting = kind == "meeting"
    doc = Doc.objects.create(
        org=org,
        kind=kind,
        project=project,
        team=team,
        parent=parent,
        title=(title or "").strip()[:200] or _default_title(kind),
        body_md=_clean_body(body_md),
        created_on=(created_on or now_kst()) if meeting else created_on,
        tags=_clean_tags(tags),
        origin=origin,
        created_by=actor,
        updated_by=actor,
        updated_source=source,
    )
    _record_revision(doc, actor, source, force_new=True)
    return doc


@transaction.atomic
def update_doc(doc, field: str, value, *, actor, expected_version: int, source="web") -> Doc:
    """한 번에 한 항목. 버전이 다르면 ConflictError(최신 객체).

    source는 누가 고쳤는지 남기려는 것이다 — AI(mcp)도 문서를 고치므로 사람이 구별할 수 있어야 한다.
    """
    if not can_view_doc(actor, doc):
        raise ServiceError({"project": "볼 수 없는 문서입니다."})
    _check_ai_edit(doc.org, source, "문서 고치기")
    if field not in (MEETING_EDITABLE if doc.kind == "meeting" else EDITABLE):
        raise ServiceError({field: "수정할 수 없는 항목입니다."})
    if field == "title":
        value = (value or "").strip()[:200] or _default_title(doc.kind)
    elif field == "body_md":
        value = _clean_body(value)
    elif field == "tags":
        value = _clean_tags(value)
    elif field == "project":
        _check_scope(doc.org, actor, value, None)
    # created_on(회의 일시)은 비워 둘 수 있다 — 작성 시각(created_at)과 별개다.

    # auto_now는 update()를 타지 않으므로 직접 넣는다.
    updated = Doc.objects.filter(pk=doc.pk, version=expected_version).update(
        version=expected_version + 1,
        updated_at=timezone.now(),
        updated_by=actor,
        updated_source=source,
        **{field: value},
    )
    if updated != 1:
        doc.refresh_from_db()
        raise ConflictError(doc)
    doc.refresh_from_db()
    if field in EDITABLE:
        _record_revision(doc, actor, source)
    return doc


@transaction.atomic
def revert_doc(doc, revision, *, actor, expected_version: int, source="web") -> Doc:
    """이전 버전의 제목·본문으로 되돌린다. version은 1만 오르고 이전 버전도 1개 생긴다."""
    if revision.doc_id != doc.pk:
        raise ServiceError({"revision": "이 문서의 이전 버전이 아닙니다."})
    if not can_view_doc(actor, doc):
        raise ServiceError({"doc": "볼 수 없는 문서입니다."})
    _check_ai_edit(doc.org, source, "문서 되돌리기")
    updated = Doc.objects.filter(pk=doc.pk, version=expected_version).update(
        version=expected_version + 1,
        updated_at=timezone.now(),
        updated_by=actor,
        updated_source=source,
        title=revision.title,
        body_md=revision.body_md,
    )
    if updated != 1:
        doc.refresh_from_db()
        raise ConflictError(doc)
    doc.refresh_from_db()
    # 되돌리기 직전 상태가 덮어써지지 않게 새 행으로 남긴다.
    _record_revision(doc, actor, source, force_new=True)
    return doc


@transaction.atomic
def move_doc(doc, *, actor, parent=_KEEP, position=None, project=_KEEP, team=_KEEP) -> Doc:
    """상위 문서·순서·공개 범위를 바꾼다. 하위 문서의 공개 범위도 함께 다시 쓴다.

    parent=None은 뿌리로, 주지 않으면 그대로. 공개 범위는 뿌리 문서에서만 바꾼다.
    """
    _require_view(actor, doc)
    if parent is not _KEEP and (parent.pk if parent else None) != doc.parent_id:
        _check_parent(doc.org, actor, parent, doc.kind)
        levels = _descendant_levels(doc)
        if parent is not None:
            if parent.pk == doc.pk or any(parent.pk in lv for lv in levels):
                raise ServiceError({"parent": "자기 하위 문서 아래로는 옮길 수 없습니다."})
            if _depth(parent) + 1 + len(levels) > MAX_DEPTH:
                raise ServiceError({"parent": f"하위 문서는 {MAX_DEPTH}단계까지입니다."})
        doc.parent = parent
    if doc.parent is not None:
        if project is not _KEEP or team is not _KEEP:
            raise ServiceError({"scope": "공개 범위는 맨 위 문서에서만 바꿉니다."})
        doc.project, doc.team = doc.parent.project, doc.parent.team
    else:
        new_project = doc.project if project is _KEEP else project
        new_team = doc.team if team is _KEEP else team
        # 하나만 바꿔 주면 다른 쪽은 비운다(둘 중 하나만 둘 수 있다).
        if project is not _KEEP and project is not None and team is _KEEP:
            new_team = None
        if team is not _KEEP and team is not None and project is _KEEP:
            new_project = None
        _check_scope(doc.org, actor, new_project, new_team)
        doc.project, doc.team = new_project, new_team
    if position is not None:
        doc.position = max(0, int(position))
    doc.save(update_fields=["parent", "project", "team", "position", "updated_at"])
    ids = [pk for lv in _descendant_levels(doc) for pk in lv]
    Doc.objects.filter(pk__in=ids).update(project=doc.project, team=doc.team)
    return doc


def delete_doc(doc, actor) -> int:
    """작성자 본인이거나 조직 관리자만. 하위 문서도 함께 지워진다. 함께 지운 하위 문서 수를 돌려준다."""
    if not can_view_doc(actor, doc) or (
        doc.created_by_id != actor.pk and not is_admin(actor, doc.org)
    ):
        raise ServiceError({"doc": "작성자나 조직 관리자만 지울 수 있습니다."})
    from tasks.models import ChangeLog

    children = sum(len(lv) for lv in _descendant_levels(doc))
    ChangeLog.objects.create(
        target_type="org",
        target_id=doc.org_id,
        field="doc_deleted",
        note=doc.title[:200],
        actor=actor,
        source="web",
    )
    doc.delete()
    return children


# ---------- 연결·백링크·검색 ----------


def link_task(doc, task, actor, *, as_output=False):
    """문서를 태스크의 참고 자료로 건다. 같은 조직이면 되고, 프로젝트 문서는 그 프로젝트의 태스크만."""
    if not can_view_doc(actor, doc):
        raise ServiceError({"project": "볼 수 없는 문서입니다."})
    if task.project.org_id != doc.org_id:
        raise ServiceError({"task": "같은 조직의 태스크여야 합니다."})
    if doc.project_id is not None and task.project_id != doc.project_id:
        raise ServiceError({"task": "같은 프로젝트의 태스크여야 합니다."})
    doc.tasks.add(task)
    if as_output:
        # 내부 문서를 산출물로: "산출물" 링크 하나로 남겨 파일·외부 링크와 같은 목록에 보인다.
        from tasks.services import add_link

        add_link(actor=actor, task=task, title=doc.title, url=doc_url(doc), kind="out")


def unlink_task(doc, task, actor):
    if not can_view_doc(actor, doc):
        raise ServiceError({"project": "볼 수 없는 문서입니다."})
    doc.tasks.remove(task)


def doc_url(doc) -> str:
    # 프로젝트 문서는 지금 화면 주소. 그 밖의 문서는 D2의 정식 주소(/docs/<id>).
    if doc.project_id is not None:
        return f"{settings.SITE_URL}/projects/{doc.project_id}/docs?doc={doc.pk}"
    return f"{settings.SITE_URL}/docs/{doc.pk}"


def backlinks(doc, viewer) -> dict:
    """이 문서를 가리키는 문서·태스크(본문 검색). viewer가 볼 수 있는 것만."""
    # ponytail: 본문 icontains 스캔. 문서 1,000건을 넘으면 DocRef 색인 표로 바꾼다.
    from tasks.services import visible_tasks

    pat = re.compile(rf"(/docs/|[?&]doc=){doc.pk}(?!\d)")
    hit = Q(body_md__contains=f"/docs/{doc.pk}") | Q(body_md__contains=f"doc={doc.pk}")
    docs = [
        d
        for d in visible_docs(viewer, doc.org)
        .filter(hit)
        .exclude(pk=doc.pk)
        .only("pk", "title", "body_md", "kind")
        if pat.search(d.body_md)
    ]
    thit = Q()
    for f in ("description", "notes"):
        thit |= Q(**{f"{f}__contains": f"/docs/{doc.pk}"}) | Q(
            **{f"{f}__contains": f"doc={doc.pk}"}
        )
    tasks = [
        t
        for t in visible_tasks(viewer).filter(project__org_id=doc.org_id).filter(thit)
        if pat.search(t.description) or pat.search(t.notes)
    ]
    return {"docs": docs, "tasks": tasks}


def search_docs(user, q: str, org=None, kind=None):
    qs = visible_docs(user, org).filter(is_template=False)
    if kind:
        qs = qs.filter(kind=kind)
    q = (q or "").strip()
    if q:
        qs = qs.filter(Q(title__icontains=q) | Q(body_md__icontains=q))
    return qs


# ---------- 올리기·내보내기·가져오기 ----------


def _decode_md(filename: str, raw: bytes) -> tuple[str, str]:
    if not filename.lower().endswith((".md", ".markdown")):
        raise ServiceError({"file": ".md 또는 .markdown 파일만 올릴 수 있습니다."})
    if len(raw) > MAX_BODY:
        raise ServiceError({"file": "파일이 너무 큽니다 (256KB 상한)."})
    try:
        body = raw.decode("utf-8-sig")
    except UnicodeDecodeError:
        raise ServiceError({"file": "UTF-8로 저장된 파일만 읽을 수 있습니다."}) from None
    name = filename.replace("\\", "/").rsplit("/", 1)[-1]
    return re.sub(r"\.(md|markdown)$", "", name, flags=re.I), body


def upload_doc(
    *, actor, filename: str, raw: bytes, org=None, kind="doc", project=None, team=None, parent=None
) -> Doc:
    """.md 본문 텍스트만 읽어 새 문서를 만든다. 파일 자체는 저장하지 않는다."""
    title, body = _decode_md(filename, raw)
    return create_doc(
        actor=actor,
        org=org,
        kind=kind,
        title=title,
        body_md=body,
        project=project,
        team=team,
        parent=parent,
    )


def _safe_name(title: str) -> str:
    return re.sub(r'[\\/:*?"<>|\x00-\x1f]', "_", title).strip(" .") or "문서"


def export_md(doc) -> tuple[str, bytes]:
    """(파일 이름, 본문). 다시 올리면 같은 제목·본문의 문서가 된다."""
    return f"{_safe_name(doc.title)}.md", doc.body_md.encode()


def export_zip(org, viewer, *, root=None, kind="doc") -> bytes:
    """볼 수 있는 문서를 트리 모양 그대로: 문서는 `<제목>.md`, 하위 문서는 `<제목>/` 폴더 안."""
    docs = list(
        visible_docs(viewer, org)
        .filter(is_template=False, kind=kind)
        .only("pk", "parent_id", "title", "body_md")
    )
    by_parent: dict = {}
    for d in docs:
        by_parent.setdefault(d.parent_id, []).append(d)
    ids = {d.pk for d in docs}
    if root is not None:
        tops = [d for d in docs if d.pk == root.pk]
    else:
        # 부모를 못 보면 그 문서가 맨 위로 올라온다(안 보이는 부모 제목을 새지 않는다).
        tops = [d for d in docs if d.parent_id is None or d.parent_id not in ids]

    buf = io.BytesIO()
    with zipfile.ZipFile(buf, "w", zipfile.ZIP_DEFLATED) as zf:

        def put(siblings, prefix):
            used = set()
            for d in siblings:
                name = _safe_name(d.title)
                if name.lower() in used:
                    name = f"{name} ({d.pk})"
                used.add(name.lower())
                zf.writestr(f"{prefix}{name}.md", d.body_md)
                put(by_parent.get(d.pk, []), f"{prefix}{name}/")

        put(tops, "")
    return buf.getvalue()


# Notion이 내보낸 md: 파일·폴더 이름 끝에 " <32자리 hex>"가 붙고, 링크는 URL 인코딩 상대 경로다.
_NOTION_ID = re.compile(r"\s+([0-9a-f]{32})$")
_MD_LINK = re.compile(r"(!?)\[([^\]]*)\]\(([^)\s]+)\)")
_PROP = re.compile(r"^([^:\n#>|*\-][^:\n]{0,39}):\s+(\S.*)$")


def _strip_id(segment: str) -> tuple[str, str]:
    m = _NOTION_ID.search(segment)
    return (segment[: m.start()], m.group(1)) if m else (segment, "")


def _clean_path(path: str) -> tuple[str, str]:
    """`a 1f..e/b 2c..d.md` → (`a/b`, 마지막 id). 확장자·id를 뗀다."""
    from urllib.parse import unquote

    path = re.sub(r"\.(md|markdown)$", "", unquote(path).replace("\\", "/"), flags=re.I)
    parts, nid = [], ""
    for seg in path.strip("/").split("/"):
        if seg in ("", "."):
            continue
        name, nid = _strip_id(seg)
        parts.append(name.strip() or "문서")
    return "/".join(parts), nid


def _split_notion_body(name: str, body: str) -> tuple[str, str]:
    """(제목, 본문). 첫 줄 `# 제목`이 있으면 그것이 제목이다(파일 이름보다 정확하다).

    제목 바로 뒤 `속성: 값` 줄 묶음(Notion DB 행)은 한 줄씩 붙어 한 문단으로 뭉개지므로 목록으로 바꾼다.
    """
    lines = body.split("\n")
    title = name
    if lines and lines[0].startswith("# "):
        title = _strip_id(lines[0][2:].strip())[0] or name
        lines = lines[1:]
    start = 0
    while start < len(lines) and not lines[start].strip():
        start += 1
    end = start
    while end < len(lines) and _PROP.match(lines[end]):
        end += 1
    if end > start and (end == len(lines) or not lines[end].strip()):
        props = [_PROP.match(ln) for ln in lines[start:end]]
        lines = [f"- **{m.group(1)}**: {m.group(2)}" for m in props] + lines[end:]
    else:
        lines = lines[start:]
    return title, "\n".join(lines).strip("\n") + "\n" if any(lines) else ""


def _rewrite_links(body: str, here: str, ids: dict[str, int]) -> tuple[str, int]:
    """상대 링크를 고친다. 같은 묶음의 .md → `/docs/<id>`, 아니면 텍스트만. 상대 이미지 → 안내 문구.

    돌려주는 수는 경로만 남긴 이미지 개수다(첨부로 다시 올려야 한다).
    """
    import posixpath

    images = 0

    def sub(m):
        nonlocal images
        bang, text, href = m.groups()
        if re.match(r"^[a-z][a-z0-9+.-]*:|^/|^#", href, flags=re.I):
            return m.group(0)  # 바깥 주소·절대 경로·앵커는 그대로
        if bang:
            images += 1
            return f"`{_clean_path(href)[0] or href}` (이미지 — 첨부로 다시 올려 주세요)"
        if re.search(r"\.(md|markdown)$", href.split("#")[0], flags=re.I):
            target = posixpath.normpath(posixpath.join(posixpath.dirname(here), href.split("#")[0]))
            key = _clean_path(target)[0]
            return f"[{text}](/docs/{ids[key]})" if key in ids else text
        return m.group(0)

    return _MD_LINK.sub(sub, body), images


@transaction.atomic
def import_md(*, org, actor, files, project=None, team=None, parent=None, source="web") -> dict:
    """여러 `.md`(또는 그것을 담은 ZIP)를 한 번에 문서로 만든다. Notion 내보내기도 이 길로 온다.

    - 폴더가 트리가 된다: `a.md`와 `a/` 폴더가 있으면 폴더 안이 a의 하위 문서. md 없는 폴더는 빈 문서.
    - 맨 위 문서는 주어진 범위(project·team) 또는 parent 아래. 하위는 부모를 따른다.
    - 같은 것을 다시 올리면 건너뛴다(Notion id, 없으면 경로+본문 해시). 건너뛴 문서 아래로는 이어 붙인다.
    files: [(파일 이름, bytes)]. 결과: {"created": [Doc], "skipped": [제목], "images": n}
    """
    import hashlib

    raw_entries: list[tuple[str, bytes]] = []
    for name, raw in files:
        if name.lower().endswith(".zip"):
            try:
                zf = zipfile.ZipFile(io.BytesIO(raw))
            except zipfile.BadZipFile:
                raise ServiceError({"file": f"{name}: ZIP 파일을 읽지 못했습니다."}) from None
            infos = [
                i
                for i in zf.infolist()
                if not i.is_dir()
                and i.filename.lower().endswith((".md", ".markdown"))
                and not i.filename.startswith("__MACOSX/")
            ]
            if sum(i.file_size for i in infos) > ZIP_MAX_TOTAL:
                raise ServiceError({"file": "ZIP이 너무 큽니다 (풀린 크기 20MB 상한)."})
            raw_entries += [(i.filename, zf.read(i)) for i in infos]
        else:
            raw_entries.append((name, raw))
    if not raw_entries:
        raise ServiceError({"file": ".md 파일이 없습니다."})
    if len(raw_entries) > ZIP_MAX_FILES:
        raise ServiceError({"file": f"한 번에 {ZIP_MAX_FILES}개까지 가져옵니다."})

    # 경로(id·확장자 뗀 것) → (원래 경로, 제목, 본문, 키)
    items: dict[str, tuple[str, str, str, str]] = {}
    for fname, raw in raw_entries:
        if ".." in fname.replace("\\", "/").split("/"):
            continue
        path, nid = _clean_path(fname)
        title, body = _split_notion_body(path.rsplit("/", 1)[-1], _decode_md(fname, raw)[1])
        key = nid or hashlib.sha256(f"{path}\n{body}".encode()).hexdigest()
        items[path] = (fname.replace("\\", "/"), title, body, key)
    for path in list(items):
        parts = path.split("/")
        for n in range(1, len(parts)):
            p = "/".join(parts[:n])
            if p not in items:
                items[p] = ("", parts[n - 1], "", hashlib.sha256(f"{p}\n".encode()).hexdigest())

    made: dict[str, Doc] = {}
    created, skipped = [], []
    for path in sorted(items, key=lambda p: (p.count("/"), p)):
        _, title, body, key = items[path]
        head = path.rpartition("/")[0]
        dup = visible_docs(actor, org).filter(import_key=key).first()
        if dup is not None:
            made[path] = dup
            skipped.append(title)
            continue
        d = create_doc(
            actor=actor,
            org=org,
            title=title,
            body_md=body,
            project=None if head else project,
            team=None if head else team,
            parent=made[head] if head else parent,
            origin="import",
            source=source,
        )
        Doc.objects.filter(pk=d.pk).update(import_key=key)
        made[path] = d
        created.append(d)

    # 링크는 문서 id가 다 생긴 뒤에 고친다. 처음 이전 버전도 같은 본문으로 맞춘다.
    ids = {p: d.pk for p, d in made.items()}
    images = 0
    for d in created:
        path = next(p for p, x in made.items() if x is d)
        body, n = _rewrite_links(d.body_md, items[path][0] or path + ".md", ids)
        images += n
        if body != d.body_md:
            d.body_md = body
            Doc.objects.filter(pk=d.pk).update(body_md=body)
            d.revisions.update(body_md=body)
    return {"created": created, "skipped": skipped, "images": images}
