"""AI 자동완성 작업 경로(IMPL-PLAN-12 §7). 이름은 A0가 고정했다 — 뷰는 C 갈래."""

from django.urls import path

from .views import assist

urlpatterns = [
    path("assist/jobs", assist.job_create, name="assist_job_create"),  # POST {field, target, input}
    path("assist/jobs/<int:job_id>", assist.job_detail, name="assist_job"),  # 폴링 조각
    path("assist/jobs/<int:job_id>/cancel", assist.job_cancel, name="assist_job_cancel"),
    path("assist/jobs/<int:job_id>/apply", assist.job_apply, name="assist_job_apply"),  # {version}
    path(
        "assist/jobs/<int:job_id>/create-tasks",
        assist.job_create_tasks,
        name="assist_job_create_tasks",
    ),
]
