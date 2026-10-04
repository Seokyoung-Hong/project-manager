from collections import defaultdict
from datetime import date, timedelta

from django.db.models import Count, Q

from common.dates import kst_week_range, overdue_before, today_kst, week_bounds
from orgs.models import Team, TeamMembership
from orgs.services import visible_teams
from tasks.brief import task_brief, user_brief
from tasks.models import ChangeLog, Task


def _open_qs(org):
    return Task.objects.filter(project__org=org, project__is_archived=False, status__in=Task.OPEN)


def org_status(org, *, viewer=None) -> dict:
    """조직 지표. 키: counts, by_project, by_assignee, capacity, projects_without_owner

    capacity의 팀 소속은 viewer가 볼 수 있는 팀만 담는다(`visible_teams`). viewer가 None(봇·
    조직 채널 게시 등)이면 비공개 팀을 뺀다.
    """
    today = today_kst()
    # 초과 판정만 유예(task.overdue_grace_days)를 본다. 화면 배지·알림과 같은 기준이다.
    overdue_day = overdue_before(org)
    monday, sunday = week_bounds(today)
    open_qs = _open_qs(org)
    counts = {
        "open": open_qs.count(),
        "doing": open_qs.filter(status="doing").count(),
        "review": open_qs.filter(status="review").count(),
        "blocked": open_qs.filter(status="blocked").count(),
        "overdue": open_qs.filter(due_date__lt=overdue_day).count(),
        "due_this_week": open_qs.filter(due_date__gte=monday, due_date__lte=sunday).count(),
        "no_due": open_qs.filter(due_date__isnull=True).count(),
        "done": Task.objects.filter(
            project__org=org, project__is_archived=False, status="done"
        ).count(),
    }

    projects = (
        org.projects.filter(is_archived=False)
        .prefetch_related("owners", "teams")
        .annotate(
            open_count=Count("tasks", filter=Q(tasks__status__in=Task.OPEN)),
            overdue_count=Count(
                "tasks", filter=Q(tasks__status__in=Task.OPEN, tasks__due_date__lt=overdue_day)
            ),
            review_count=Count("tasks", filter=Q(tasks__status="review")),
            blocked_count=Count("tasks", filter=Q(tasks__status="blocked")),
            done_count=Count("tasks", filter=Q(tasks__status="done")),
            total_count=Count("tasks", filter=~Q(tasks__status="cancelled")),
        )
    )
    by_project = [
        {
            "id": p.pk,
            "name": p.name,
            "status": p.status,
            "owners": [user_brief(u) for u in p.owners.all()],
            "teams": [{"id": t.pk, "name": t.name} for t in p.teams.all()],
            "open": p.open_count,
            "overdue": p.overdue_count,
            "review": p.review_count,
            "blocked": p.blocked_count,
            "done": p.done_count,
            "total": p.total_count,
        }
        for p in projects
    ]

    by_assignee = list(
        open_qs.values("assignee_id", "assignee__display_name")
        .annotate(
            open=Count("id"),
            doing=Count("id", filter=Q(status="doing")),
            overdue=Count("id", filter=Q(due_date__lt=overdue_day)),
            review=Count("id", filter=Q(status="review")),
            blocked=Count("id", filter=Q(status="blocked")),
        )
        .order_by("-open")
    )

    # 부하 현황은 미완료가 하나도 없는 사람도 보여야 한다. by_assignee는 집계라
    # 태스크가 있는 사람만 나오므로 활성 멤버 전원을 기준으로 다시 만든다.
    rows = {r["assignee_id"]: r for r in by_assignee}
    tags_by_user = {m.user_id: m.tags for m in org.memberships.all()}
    teams_by_user = defaultdict(list)
    if viewer is None:
        shown = Team.objects.filter(org=org, is_private=False)
    else:
        shown = visible_teams(viewer, org)
    for tm in TeamMembership.objects.filter(team__in=shown).select_related("team"):
        teams_by_user[tm.user_id].append({"id": tm.team_id, "name": tm.team.name})

    members = list(org.members.filter(is_active=True).order_by("display_name"))
    capacity = []
    for u in members:
        r = rows.get(u.pk, {})
        doing, review = r.get("doing", 0), r.get("review", 0)
        overdue = r.get("overdue", 0)
        capacity.append(
            {
                "user": user_brief(u),
                "open": r.get("open", 0),
                "doing": doing,
                "review": review,
                "blocked": r.get("blocked", 0),
                "overdue": overdue,
                "load": doing + review,
                "tags": tags_by_user.get(u.pk, []),
                "teams": teams_by_user.get(u.pk, []),
            }
        )
    # 상대 막대만 두면 "조직에서 가장 바쁜 사람"이 항상 꽉 찬다. 기준 수치를 함께 준다.
    max_load = max([c["load"] for c in capacity], default=0) or 1
    for c in capacity:
        c["bar"] = round(c["load"] / max_load * 100)
        c["over"] = c["load"] >= 4 or c["overdue"] >= 2
        c["verdict"] = "과부하" if c["over"] else "여유" if c["load"] <= 1 else "적정"
        c["scale"] = max_load
    counts["avg_doing"] = (
        round(sum(c["doing"] for c in capacity) / len(members), 1) if members else 0.0
    )

    projects_without_owner = list(
        org.projects.filter(is_archived=False, owners__isnull=True).values("id", "name")
    )
    return {
        "counts": counts,
        "by_project": by_project,
        "by_assignee": by_assignee,
        "capacity": capacity,
        "projects_without_owner": projects_without_owner,
    }


def weekly(org, week_start: date) -> dict:
    """주간 집계. week_start는 월요일이어야 한다."""
    if week_start.weekday() != 0:
        raise ValueError("week_start must be a Monday")
    start, end = kst_week_range(week_start)
    period_end = week_start + timedelta(days=7)
    this_monday, this_sunday = week_bounds(period_end)

    org_task_ids = Task.objects.filter(project__org=org).values("id")
    logs = ChangeLog.objects.filter(
        target_type="task",
        field="status",
        target_id__in=org_task_ids,
        created_at__gte=start,
        created_at__lt=end,
    )
    completed_ids = set(logs.filter(new_value="done").values_list("target_id", flat=True))
    reopened_ids = set(
        logs.filter(
            old_value__in=["done", "cancelled"], new_value__in=["todo", "doing"]
        ).values_list("target_id", flat=True)
    )

    def briefs(ids):
        qs = (
            Task.objects.filter(pk__in=ids)
            .select_related("project", "assignee")
            .order_by("project__name", "id")
        )
        return [task_brief(t) for t in qs]

    open_qs = _open_qs(org).select_related("project", "assignee")
    due_this_week = [
        task_brief(t)
        for t in open_qs.filter(due_date__gte=this_monday, due_date__lte=this_sunday).order_by(
            "due_date", "id"
        )
    ]
    overdue_day = overdue_before(org)  # 화면 배지와 같은 유예 기준
    overdue = [
        task_brief(t) for t in open_qs.filter(due_date__lt=overdue_day).order_by("due_date", "id")
    ]
    blocked = [task_brief(t) for t in open_qs.filter(status="blocked").order_by("id")]

    by_project = []
    for p in org.projects.filter(is_archived=False).order_by("name"):
        p_ids = set(Task.objects.filter(project=p).values_list("id", flat=True))
        by_project.append(
            {
                "project": {"id": p.pk, "name": p.name, "status": p.status},
                "completed": len(completed_ids & p_ids),
                "reopened": len(reopened_ids & p_ids),
                "open": open_qs.filter(project=p).count(),
                "overdue": open_qs.filter(project=p, due_date__lt=overdue_day).count(),
                "blocked": open_qs.filter(project=p, status="blocked").count(),
            }
        )

    return {
        "org": {"id": org.pk, "name": org.name},
        "period_start": week_start.isoformat(),
        "period_end": period_end.isoformat(),
        # 보고를 만든 날. 봇이 항목마다 D-n·초과 n일을 이 날 기준으로 적는다.
        "today": today_kst().isoformat(),
        "completed": briefs(completed_ids),
        "reopened": briefs(reopened_ids),
        "due_this_week": due_this_week,
        "overdue": overdue,
        "blocked": blocked,
        "by_project": by_project,
        "counts": {
            "completed": len(completed_ids),
            "reopened": len(reopened_ids),
            "due_this_week": len(due_this_week),
            "overdue": len(overdue),
            "blocked": len(blocked),
            "open": open_qs.count(),
            "review": open_qs.filter(status="review").count(),
            "no_due": open_qs.filter(due_date__isnull=True).count(),
        },
        "members": [
            user_brief(u) for u in org.members.filter(is_active=True).order_by("display_name")
        ],
    }
