from django.contrib.auth.decorators import login_required
from django.shortcuts import render

from projects.docs import search_docs
from tasks import services as ts

from .common import rows_for


@login_required
def search(request):
    q = request.GET.get("q", "")
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
        },
    )
