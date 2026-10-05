from django.db.models import Avg, Count, DurationField, ExpressionWrapper, F, Q

from .models import RepoConnection, TaskGitLink


def weekly_metrics(projects, start, end) -> dict | None:
    """주간 GitHub 지표. 저장소가 연결된 프로젝트가 없으면 None.

    TaskGitLink에서만 센다(GitEvent는 50건에 잘린다). 쿼리 두 번(연결 유무, 집계).
    """
    if not RepoConnection.objects.filter(project__in=projects).exists():
        return None
    links = TaskGitLink.objects.filter(connection__project__in=projects)
    wait = ExpressionWrapper(
        F("reviewed_at") - F("review_requested_at"), output_field=DurationField()
    )
    in_week = Q(reviewed_at__gte=start, reviewed_at__lt=end, review_requested_at__isnull=False)
    r = links.aggregate(
        merged=Count("id", filter=Q(merged_at__gte=start, merged_at__lt=end)),
        opened=Count("id", filter=Q(pr_opened_at__gte=start, pr_opened_at__lt=end)),
        open=Count("id", filter=Q(pr_state="open")),
        wait=Avg(wait, filter=in_week),
        ci_failing=Count("id", filter=Q(pr_state="open", ci_state="failure")),
    )
    wait = r.pop("wait")
    r["avg_review_hours"] = round(wait.total_seconds() / 3600, 1) if wait is not None else None
    return r
