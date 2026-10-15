from django.contrib.auth.decorators import login_required
from django.shortcuts import render
from django.urls import reverse

from projects.docs import search_docs
from tasks import services as ts

from .. import search_index
from .common import current_org, rows_for

PANEL_LIMIT = 5  # 헤더 펼침 패널의 묶음당 줄 수. 나머지는 [전체 결과 보기](/search)


@login_required
def search(request):
    q = request.GET.get("q", "")
    found_index = search_index.find(request.user, current_org(request), q)
    if request.GET.get("panel"):
        return _panel(request, q, found_index)
    include_closed = request.GET.get("include_closed") == "1"
    include_archived = request.GET.get("include_archived") == "1"
    results = list(
        ts.search(request.user, q, include_closed=include_closed, include_archived=include_archived)
    )
    # 문서·회의록은 제목·본문 검색(볼 수 있는 것만). 검색어가 없으면 내지 않는다.
    found = (
        list(search_docs(request.user, q).select_related("org", "project")[:60])
        if q.strip()
        else []
    )
    return render(
        request,
        "search.html",
        {
            "q": q,
            "count": len(results),
            "rows": rows_for(request.user, results),
            "include_closed": include_closed,
            "include_archived": include_archived,
            "docs": [d for d in found if d.kind == "doc"],
            "meetings": [d for d in found if d.kind == "meeting"],
            "screens": found_index["screen"],
            "settings_found": found_index["setting"],
        },
    )


def _panel(request, q, found_index):
    """헤더 검색 펼침 패널 조각. 태스크·문서 권한은 전체 검색과 같은 함수(visible_*)를 탄다."""
    groups = []
    if q.strip():
        tasks = [
            {
                "label": f"TASK-{t.pk} {t.title}",
                "hint": f"{t.project.name} · {t.get_status_display()}",
                "url": reverse("task_detail", args=[t.pk]),
            }
            for t in ts.search(request.user, q)[:PANEL_LIMIT]
        ]
        docs = [
            {
                "label": d.title,
                "hint": ("회의록" if d.kind == "meeting" else "문서")
                + f" · {d.project.name if d.project else d.org.name}",
                "url": reverse("doc_home", args=[d.pk]),
            }
            for d in search_docs(request.user, q).select_related("org", "project")[:PANEL_LIMIT]
        ]
        groups = [
            ("화면·탭", found_index["screen"][:PANEL_LIMIT]),
            ("설정", found_index["setting"][:PANEL_LIMIT]),
            ("태스크", tasks),
            ("문서·회의록", docs),
        ]
    total = sum(len(items) for _, items in groups)
    return render(request, "_search_panel.html", {"q": q, "groups": groups, "total": total})
