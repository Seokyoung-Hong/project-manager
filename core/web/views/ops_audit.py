"""운영 콘솔 감사 기록 `/ops/audit` 조회와 CSV 내보내기. 읽기 전용(수정·삭제 화면 없음)."""

import csv
from datetime import date

from django.core.paginator import Paginator
from django.db.models import Q
from django.http import StreamingHttpResponse
from django.shortcuts import render
from django.utils import timezone

from ops import services as ops_services
from ops.access import ops_required
from ops.models import OpsAuditLog

PER_PAGE = 100
COLUMNS = [
    "id", "created_at", "actor_username", "action", "target_type", "target_id",
    "target_label", "reason", "detail", "ip",
]  # fmt: skip


def _day(value):
    try:
        return date.fromisoformat((value or "").strip())
    except ValueError:
        return None


def _filters(request) -> dict:
    """GET 필터. 값이 비었거나 잘못되면 그 필터는 건다고 치지 않는다."""
    g = request.GET
    action = g.get("action", "")
    return {
        "from": _day(g.get("from")),
        "to": _day(g.get("to")),
        "actor": g.get("actor", "").strip(),
        "action": action if action in dict(OpsAuditLog.ACTIONS) else "",
        "target": g.get("target", "").strip(),
    }


def _queryset(f: dict):
    qs = OpsAuditLog.objects.all()
    if f["from"]:
        qs = qs.filter(created_at__date__gte=f["from"])
    if f["to"]:
        qs = qs.filter(created_at__date__lte=f["to"])
    if f["actor"]:
        qs = qs.filter(actor_username__icontains=f["actor"])
    if f["action"]:
        qs = qs.filter(action=f["action"])
    if f["target"]:
        qs = qs.filter(
            Q(target_label__icontains=f["target"]) | Q(target_type__icontains=f["target"])
        )
    return qs


@ops_required
def audit_list(request):
    f = _filters(request)
    page = Paginator(_queryset(f), PER_PAGE).get_page(request.GET.get("page"))
    q = request.GET.copy()
    q.pop("page", None)
    return render(
        request,
        "ops/audit.html",
        {
            "ops_nav": "audit",
            "page": page,
            "f": f,
            "actions": OpsAuditLog.ACTIONS,
            "query": q.urlencode(),
        },
    )


class _Echo:
    def write(self, value):
        return value


def _cell(value) -> str:
    """스프레드시트가 수식으로 읽지 않게 작은따옴표를 붙인다.

    =+-@로 시작하거나, 선행 공백·TAB·CR·LF 뒤에 그 글자가 오거나, TAB·CR로 시작하면 텍스트로 만든다.
    """
    s = "" if value is None else str(value)
    risky = s[:1] in ("\t", "\r") or s.lstrip(" \t\r\n")[:1] in ("=", "+", "-", "@")
    return "'" + s if risky else s


@ops_required
def audit_csv(request):
    f = _filters(request)
    last = OpsAuditLog.objects.order_by("-id").values_list("id", flat=True).first() or 0
    qs = (
        _queryset(f).filter(id__lte=last).order_by("id")
    )  # 아래 기록(자기 자신)은 파일에 넣지 않는다
    ops_services.audit(
        request,
        "audit.export",
        target_type="audit",
        detail={"rows": qs.count(), "filter": {k: str(v) for k, v in f.items() if v}},
    )
    w = csv.writer(_Echo())

    def stream():
        yield "﻿" + w.writerow(COLUMNS)  # BOM: 엑셀에서 한글이 깨지지 않게
        for a in qs.iterator(chunk_size=500):
            yield w.writerow(
                _cell(v)
                for v in (
                    a.id,
                    timezone.localtime(a.created_at).isoformat(timespec="seconds"),
                    a.actor_username,
                    a.action,
                    a.target_type,
                    a.target_id,
                    a.target_label,
                    a.reason,
                    a.detail,
                    a.ip,
                )
            )

    resp = StreamingHttpResponse(stream(), content_type="text/csv; charset=utf-8")
    resp["Content-Disposition"] = 'attachment; filename="audit.csv"'
    return resp
