"""문서 화면(IMPL-PLAN-11 §4.6). 조직 탭 "문서"와 프로젝트 탭 "문서"가 같은 화면을 쓴다.

편집기(doc-tiptap.js)·저장 규약(X-Note-Version)은 회의록과 같다. 이전 버전·연결·파일 묶음(`docs/_extras.html`)은
회의록 화면도 그대로 쓴다. 규칙은 전부 projects.docs에 있고 여기는 부르기만 한다.
"""

from urllib.parse import quote

from django.contrib import messages
from django.contrib.auth.decorators import login_required
from django.http import Http404, HttpResponse, JsonResponse
from django.shortcuts import redirect, render
from django.urls import reverse
from django.utils.http import url_has_allowed_host_and_scheme
from django.views.decorators.http import require_POST

from common.errors import ConflictError, ServiceError
from orgs.services import is_admin, visible_teams
from projects import docs as ts_docs
from projects.services import visible_projects
from tasks.attachments import attachments_of
from tasks.services import visible_tasks

from .common import CONFLICT_MSG, org_or_404, project_or_404, task_or_404, trigger, version_of


def _doc_or_404(user, doc_id):
    try:
        doc = ts_docs.get_visible_doc(user, int(doc_id))
    except (TypeError, ValueError):
        doc = None
    if doc is None:
        raise Http404
    return doc


def page_url(doc) -> str:
    """문서의 정식 화면. 회의록은 회의록 화면, 프로젝트 문서는 프로젝트 탭, 나머지는 조직 탭."""
    if doc.kind == "meeting":
        return f"{reverse('org_notes', args=[doc.org_id])}?note={doc.pk}"
    if doc.project_id:
        return f"{reverse('project_docs', args=[doc.project_id])}?doc={doc.pk}"
    return f"{reverse('org_docs', args=[doc.org_id])}?doc={doc.pk}"


def _back(request, doc=None, fallback=""):
    """폼이 보낸 next(같은 사이트 경로)로, 없으면 문서의 정식 화면으로."""
    nxt = request.POST.get("next", "")
    if nxt and url_has_allowed_host_and_scheme(nxt, allowed_hosts={request.get_host()}):
        if doc is not None and "doc=" not in nxt and "note=" not in nxt:
            nxt += (
                ("&" if "?" in nxt else "?")
                + ("note=" if doc.kind == "meeting" else "doc=")
                + str(doc.pk)
            )
        return redirect(nxt)
    return redirect(page_url(doc) if doc is not None else fallback)


def _err(request, what, e):
    messages.error(request, f"{what} " + " ".join(str(v) for v in e.errors.values()))


# ---------- 목록·트리 ----------


def _tree(docs):
    """[{doc, children}]. 부모를 못 보는 문서는 맨 위로 올라온다(안 보이는 부모를 드러내지 않는다)."""
    ids = {d.pk for d in docs}
    by_parent = {}
    for d in docs:
        by_parent.setdefault(d.parent_id if d.parent_id in ids else None, []).append(d)

    def build(pid):
        return [{"doc": d, "children": build(d.pk)} for d in by_parent.get(pid, [])]

    return build(None)


def _ancestors(user, doc):
    out, pid = [], doc.parent_id
    while pid is not None:
        p = ts_docs.get_visible_doc(user, pid)
        if p is None:
            break
        out.insert(0, p)
        pid = p.parent_id
    return out


def extras_ctx(user, doc) -> dict:
    """편집기 아래 묶음(이전 버전·연결·파일). 문서·회의록 화면이 같이 쓴다."""
    org = doc.org
    links = ts_docs.backlinks(doc, user)
    return {
        "revisions": list(doc.revisions.select_related("saved_by")),
        "backlinks": links,
        "backlink_count": len(links["docs"]) + len(links["tasks"]),
        "linked_tasks": list(visible_tasks(user).filter(docs=doc)),
        "attachments": attachments_of(doc),
        "can_delete": doc.created_by_id == user.pk or is_admin(user, org),
    }


def _page(request, *, org, project=None):
    user = request.user
    qs = ts_docs.visible_docs(user, org).filter(kind="doc", is_template=False)
    scope = request.GET.get("scope", "")
    if project is not None:
        qs = qs.filter(project=project)
    elif scope == "org":
        qs = qs.filter(project__isnull=True, team__isnull=True)
    elif scope[:1] in ("p", "t") and scope[1:].isdecimal():
        qs = qs.filter(**{"project_id" if scope[0] == "p" else "team_id": int(scope[1:])})
    q = request.GET.get("q", "").strip()
    docs = list(qs.select_related("created_by", "updated_by", "project", "team"))
    hits = (
        list(ts_docs.search_docs(user, q, org, kind="doc").filter(pk__in=[d.pk for d in docs]))
        if q
        else None
    )

    picked = request.GET.get("doc", "")
    doc = next((d for d in docs if str(d.pk) == picked), None)
    if doc is None and picked.isdecimal():
        doc = ts_docs.get_visible_doc(user, int(picked))  # 범위 밖이어도 볼 수 있으면 연다
        if doc is not None and doc.kind != "doc":
            doc = None
    if doc is None and not picked and docs and not q:
        doc = docs[0]  # 빈 편집기보다 첫 문서를 먼저 보인다

    projects = visible_projects(user, org).filter(is_archived=False).order_by("name")
    teams = visible_teams(user, org).order_by("name")
    ctx = {
        "org": org,
        "project": project,
        "tab": "docs",
        "is_admin": is_admin(user, org),
        "docs": docs,
        "tree": _tree(docs),
        "hits": hits,
        "q": q,
        "scope": scope,
        "doc": doc,
        "scope_choices": [(f"p{p.pk}", f"프로젝트 · {p.name}") for p in projects]
        + [(f"t{t.pk}", f"팀 · {t.name}") for t in teams],
        "templates": ts_docs.visible_docs(user, org).filter(is_template=True, kind="doc"),
        "here": request.get_full_path(),
        # 모바일은 문서를 고른 경우에만 본문을 연다. 첫 문서 자동 선택은 데스크톱 오른쪽 칸을 채우는 용도라
        # 이것까지 열면 ‘목록으로’를 눌러도 목록이 다시 숨는다.
        "editor_open": doc is not None and bool(picked),
        "open_ids": set(),
    }
    if project is not None:
        ctx["project_files"] = attachments_of(project)
    if doc is not None:
        ctx.update(extras_ctx(user, doc))
        ctx["path"] = _ancestors(user, doc)
        # 트리는 접어 두고 현재 문서까지 가는 가지만 편다(나머지 펼침은 브라우저가 기억한다).
        ctx["open_ids"] = {p.pk for p in ctx["path"]} | {doc.pk}
        ctx["doc_scope"] = (
            f"p{doc.project_id}" if doc.project_id else f"t{doc.team_id}" if doc.team_id else ""
        )
        # 옮길 수 있는 상위 문서: 자기와 하위 문서는 뺀다.
        below = {doc.pk} | {pk for lv in ts_docs._descendant_levels(doc) for pk in lv}
        ctx["parents"] = [d for d in docs if d.pk not in below and d.org_id == doc.org_id]
    return render(request, "docs/index.html", ctx)


@login_required
def org_docs(request, org_id):
    return _page(request, org=org_or_404(request.user, org_id))


@login_required
def project_docs(request, project_id):
    project = project_or_404(request.user, project_id)
    return _page(request, org=project.org, project=project)


@login_required
def doc_home(request, doc_id):
    """정식 주소 /docs/<id>. 문서 본문 링크와 백링크가 여기를 가리킨다."""
    return redirect(page_url(_doc_or_404(request.user, doc_id)))


# ---------- 만들기·올리기 ----------


def _scope_from_post(request, org):
    """scope 값: ""(조직 전체) | p<id> | t<id>."""
    raw = request.POST.get("scope", "")
    if raw[:1] == "p" and raw[1:].isdecimal():
        p = project_or_404(request.user, raw[1:])
        if p.org_id != org.pk:
            raise Http404
        return p, None
    if raw[:1] == "t" and raw[1:].isdecimal():
        t = visible_teams(request.user, org).filter(pk=int(raw[1:])).first()
        if t is None:
            raise Http404
        return None, t
    return None, None


def _parent_from_post(request):
    raw = request.POST.get("parent", "")
    return _doc_or_404(request.user, raw) if raw else None


@login_required
@require_POST
def org_doc_new(request, org_id):
    org = org_or_404(request.user, org_id)
    return _new(request, org)


@login_required
@require_POST
def doc_new(request, project_id):
    project = project_or_404(request.user, project_id)
    return _new(request, project.org, default_project=project)


def _new(request, org, default_project=None):
    parent = _parent_from_post(request)
    if "scope" in request.POST:
        project, team = _scope_from_post(request, org)
    else:
        project, team = default_project, None
    tpl = request.POST.get("template", "")
    template = _doc_or_404(request.user, tpl) if tpl else None
    try:
        doc = ts_docs.create_doc(
            org=org,
            actor=request.user,
            title=request.POST.get("title", ""),
            project=project,
            team=team,
            parent=parent,
            template=template,
        )
    except ServiceError as e:
        _err(request, "문서를 만들지 못했습니다.", e)
        return _back(request, fallback=reverse("org_docs", args=[org.pk]))
    return _back(request, doc)


@login_required
@require_POST
def org_doc_import(request, org_id):
    org = org_or_404(request.user, org_id)
    return _import(request, org)


@login_required
@require_POST
def doc_upload(request, project_id):
    project = project_or_404(request.user, project_id)
    return _import(request, project.org, default_project=project)


def _import(request, org, default_project=None):
    """md 여러 개(또는 ZIP)를 한 번에. Notion 내보내기는 이름의 id·속성 줄·링크를 정리한다."""
    files = request.FILES.getlist("file")
    fallback = (
        reverse("project_docs", args=[default_project.pk])
        if default_project
        else reverse("org_docs", args=[org.pk])
    )
    if not files:
        messages.error(request, "가져올 Markdown 파일(.md) 또는 ZIP을 선택하세요.")
        return _back(request, fallback=fallback)
    parent = _parent_from_post(request)
    if "scope" in request.POST:
        project, team = _scope_from_post(request, org)
    else:
        project, team = default_project, None
    try:
        out = ts_docs.import_md(
            org=org,
            actor=request.user,
            files=[(f.name, f) for f in files],  # 읽기는 서비스가 상한을 본 뒤에 한다
            project=project,
            team=team,
            parent=parent,
        )
    except ServiceError as e:
        _err(request, "문서를 가져오지 못했습니다.", e)
        return _back(request, fallback=fallback)
    made, skipped = out["created"], out["skipped"]
    text = f"문서 {len(made)}개를 가져왔습니다."
    if skipped:
        text += f" 이미 가져온 {len(skipped)}개는 건너뛰었습니다."
    if out["images"]:
        text += f" 이미지 {out['images']}개는 경로만 남겼습니다. 파일에서 다시 올려 주세요."
    messages.success(request, text)
    return _back(request, made[0] if made else None, fallback=fallback)


# ---------- 저장·되돌리기·옮기기·지우기 ----------


@login_required
@require_POST
def doc_save(request, doc_id):
    """편집기(doc-tiptap.js)가 부르는 자동 저장. 204 + X-Note-Version."""
    doc = _doc_or_404(request.user, doc_id)
    try:
        doc = ts_docs.update_doc(
            doc,
            request.POST.get("field", ""),
            request.POST.get("value", ""),
            actor=request.user,
            expected_version=version_of(request),
            source="web",
        )
    except ServiceError as e:
        return JsonResponse(
            {"error": " ".join(e.errors.values())},
            status=400,
            json_dumps_params={"ensure_ascii": False},
        )
    except ConflictError:
        return JsonResponse(
            {"error": CONFLICT_MSG}, status=409, json_dumps_params={"ensure_ascii": False}
        )
    resp = HttpResponse(status=204)
    resp["X-Note-Version"] = str(doc.version)
    return trigger(resp, "saved")


@login_required
@require_POST
def doc_revert(request, doc_id):
    doc = _doc_or_404(request.user, doc_id)
    rev = doc.revisions.filter(pk=request.POST.get("revision") or 0).first()
    if rev is None:
        raise Http404
    try:
        ts_docs.revert_doc(doc, rev, actor=request.user, expected_version=version_of(request))
        messages.success(request, f"v{rev.version}으로 되돌렸습니다.")
    except ConflictError:
        messages.error(request, CONFLICT_MSG)
    except ServiceError as e:
        _err(request, "되돌리지 못했습니다.", e)
    return _back(request, doc)


@login_required
@require_POST
def doc_move(request, doc_id):
    doc = _doc_or_404(request.user, doc_id)
    kw = {"parent": _parent_from_post(request)}
    if kw["parent"] is None and "scope" in request.POST:
        kw["project"], kw["team"] = _scope_from_post(request, doc.org)
    try:
        ts_docs.move_doc(doc, actor=request.user, **kw)
        messages.success(request, "문서를 옮겼습니다.")
    except ServiceError as e:
        _err(request, "옮기지 못했습니다.", e)
    return _back(request, doc)


@login_required
@require_POST
def doc_delete(request, doc_id):
    doc = _doc_or_404(request.user, doc_id)
    fallback = (
        reverse("project_docs", args=[doc.project_id])
        if doc.project_id
        else reverse("org_docs", args=[doc.org_id])
    )
    try:
        n = ts_docs.delete_doc(doc, request.user)
    except ServiceError as e:
        _err(request, "문서를 삭제하지 못했습니다.", e)
        return _back(request, doc)
    messages.success(request, f"문서를 삭제했습니다{f' (하위 문서 {n}개 포함)' if n else ''}.")
    return redirect(fallback)


# ---------- 내보내기 ----------


def _download(name: str, data: bytes, content_type: str) -> HttpResponse:
    resp = HttpResponse(data, content_type=content_type)
    resp["Content-Disposition"] = f"attachment; filename*=UTF-8''{quote(name)}"
    return resp


@login_required
def doc_export_md(request, doc_id):
    name, data = ts_docs.export_md(_doc_or_404(request.user, doc_id))
    return _download(name, data, "text/markdown; charset=utf-8")


@login_required
def org_doc_export(request, org_id):
    org = org_or_404(request.user, org_id)
    root = request.GET.get("root", "")
    root_doc = _doc_or_404(request.user, root) if root else None
    data = ts_docs.export_zip(org, request.user, root=root_doc)
    return _download(f"{org.name}-문서.zip", data, "application/zip")


# ---------- 첨부 ----------


@login_required
@require_POST
def doc_attachment_add(request, doc_id):
    from tasks import attachments as at

    doc = _doc_or_404(request.user, doc_id)
    upload = request.FILES.get("file")
    try:
        if upload is None:
            raise ServiceError({"file": "파일을 고르세요."})
        at.add_attachment(
            actor=request.user, upload=upload, doc=doc, note=request.POST.get("note", "")
        )
        messages.success(request, "파일을 올렸습니다.")
    except ServiceError as e:
        _err(request, "파일을 올리지 못했습니다.", e)
    return _back(request, doc)


# ---------- 태스크 참고 자료로 걸기 ----------


@login_required
@require_POST
def task_doc_link(request, task_id):
    from .tasks import _refs

    task = task_or_404(request.user, task_id)
    try:
        doc = _doc_or_404(request.user, int(request.POST.get("doc", "")))
    except (TypeError, ValueError, Http404):
        return _refs(request, task, error="문서를 선택하세요.")
    try:
        ts_docs.link_task(doc, task, request.user, as_output=request.POST.get("as_output") == "1")
    except ServiceError as e:
        return _refs(request, task, error=" ".join(e.errors.values()))
    return _refs(request, task)


@login_required
@require_POST
def task_doc_unlink(request, task_id, doc_id):
    from .tasks import _refs

    task = task_or_404(request.user, task_id)
    doc = _doc_or_404(request.user, doc_id)
    try:
        ts_docs.unlink_task(doc, task, request.user)
    except ServiceError as e:
        return _refs(request, task, error=" ".join(e.errors.values()))
    return _refs(request, task)


@login_required
@require_POST
def doc_task_link(request, doc_id):
    """문서 화면에서 태스크 번호로 연결. 연결은 태스크 패널과 같은 서비스를 쓴다."""
    doc = _doc_or_404(request.user, doc_id)
    raw = request.POST.get("task", "").strip().upper().removeprefix("TASK-")
    task = (
        visible_tasks(request.user)
        .filter(project__org=doc.org)
        .filter(pk=int(raw) if raw.isdecimal() else 0)
        .first()
    )
    if task is None:
        messages.error(
            request, "연결할 태스크를 찾지 못했습니다. 태스크 번호(TASK-n)를 확인하세요."
        )
        return _back(request, doc)
    try:
        ts_docs.link_task(doc, task, request.user)
    except ServiceError as e:
        _err(request, "연결하지 못했습니다.", e)
    return _back(request, doc)


@login_required
@require_POST
def doc_task_unlink(request, doc_id, task_id):
    doc = _doc_or_404(request.user, doc_id)
    task = task_or_404(request.user, task_id)
    ts_docs.unlink_task(doc, task, request.user)
    return _back(request, doc)
