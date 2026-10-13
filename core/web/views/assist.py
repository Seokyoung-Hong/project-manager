"""AI 자동완성 작업 화면(IMPL-PLAN-12 §7.1·§7.3·§7.4). A0는 자리만 — C 갈래가 채운다."""

from django.contrib.auth.decorators import login_required
from django.http import HttpResponse


@login_required
def job_create(request):
    return HttpResponse(status=501)


@login_required
def job_detail(request, job_id: int):
    return HttpResponse(status=501)


@login_required
def job_cancel(request, job_id: int):
    return HttpResponse(status=501)


@login_required
def job_apply(request, job_id: int):
    return HttpResponse(status=501)


@login_required
def job_create_tasks(request, job_id: int):
    return HttpResponse(status=501)
