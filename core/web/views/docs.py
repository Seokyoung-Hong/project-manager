"""프로젝트 문서 탭. 회의록 화면과 같은 편집기를 쓰고 저장 규약도 같다."""

from django.contrib import messages
from django.contrib.auth.decorators import login_required
from django.http import Http404, HttpResponse, JsonResponse
from django.shortcuts import redirect, render
from django.urls import reverse
from django.views.decorators.http import require_POST

from common.errors import ConflictError, ServiceError
from orgs.services import is_admin
from projects import docs as ts_docs
from tasks.attachments import attachments_of

from .common import CONFLICT_MSG, project_or_404, task_or_404, trigger, version_of


def _doc_or_404(user, doc_id):
    doc = ts_docs.get_visible_doc(user, doc_id)
    if doc is None:
        raise Http404
    return doc


@login_required
def project_docs(request, project_id):
    project = project_or_404(request.user, project_id)
    items = list(ts_docs.visible_docs(project).select_related("updated_by"))
    picked = request.GET.get("doc")
    doc = next((d for d in items if str(d.pk) == picked), None)
    # 고른 것이 없으면 첫 문서를 편다 — 빈 편집기를 먼저 보여 줄 이유가 없다.
    if doc is None and items:
        doc = items[0]
    return render(
        request,
        "projects/docs.html",
        {
            "project": project,
            "tab": "docs",
            "docs": items,
            "doc": doc,
            # 서비스 규칙(작성자 또는 조직 관리자)과 같은 조건이어야 버튼과 결과가 어긋나지 않는다
            "can_delete": doc is not None
            and (doc.created_by_id == request.user.pk or is_admin(request.user, project.org)),
            "attachments": attachments_of(project),
            "is_admin": is_admin(request.user, project.org),
        },
    )


def _back(project_id, doc=None):
    url = reverse("project_docs", args=[project_id])
    return redirect(f"{url}?doc={doc.pk}" if doc else url)


@login_required
@require_POST
def doc_new(request, project_id):
    project = project_or_404(request.user, project_id)
    try:
        doc = ts_docs.create_doc(project=project, actor=request.user)
    except ServiceError as e:
        messages.error(request, "문서를 만들지 못했습니다. " + " ".join(e.errors.values()))
        return _back(project_id)
    return _back(project_id, doc)


@login_required
@require_POST
def doc_upload(request, project_id):
    project = project_or_404(request.user, project_id)
    f = request.FILES.get("file")
    if f is None:
        messages.error(request, "업로드할 Markdown 파일(.md 또는 .markdown)을 선택하세요.")
        return _back(project_id)
    try:
        doc = ts_docs.upload_doc(project=project, actor=request.user, filename=f.name, raw=f.read())
    except ServiceError as e:
        messages.error(request, "문서를 업로드하지 못했습니다. " + " ".join(e.errors.values()))
        return _back(project_id)
    return _back(project_id, doc)


@login_required
@require_POST
def doc_save(request, doc_id):
    """편집기(notes.js)가 부르는 자동 저장. 204 + X-Note-Version."""
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
def doc_delete(request, doc_id):
    doc = _doc_or_404(request.user, doc_id)
    project_id = doc.project_id
    try:
        ts_docs.delete_doc(doc, request.user)
    except ServiceError as e:
        messages.error(request, "문서를 삭제하지 못했습니다. " + " ".join(e.errors.values()))
        return _back(project_id, doc)
    return _back(project_id)


# ---------- 태스크 참고 자료로 걸기 ----------


@login_required
@require_POST
def task_doc_link(request, task_id):
    from .tasks import _refs

    task = task_or_404(request.user, task_id)
    try:
        doc = _doc_or_404(request.user, int(request.POST.get("doc", "")))
    except (TypeError, ValueError):
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
