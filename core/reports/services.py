from collections import defaultdict
from datetime import date, timedelta

from django.db.models import Count, Q

from common.dates import kst_week_range, overdue_q, today_kst, week_bounds
from github.metrics import weekly_metrics
from orgs.models import Team, TeamMembership
from orgs.services import visible_teams
from projects.services import visible_projects
from tasks.brief import task_brief, user_brief
from tasks.models import ChangeLog, Task, TaskProject
from tasks.services import attach_group_visible, leaf_only, tasks_visible_in


def _projects(org, viewer):
    """viewer가 None(봇·조직 채널 게시)이면 비공개("teams") 프로젝트를 뺀다."""
    if viewer is None:
        return org.projects.filter(visibility="org")
    return visible_projects(viewer, org)


def _open_qs(org, viewer=None):
    """조직 합계용 미완료. 태스크당 한 번 센다(연결 프로젝트가 여럿이어도) — tasks_visible_in."""
    return tasks_visible_in(org, viewer).filter(
        project__is_archived=False,
        status__in=Task.OPEN,
        is_template=False,
    )


STATS = {
    "open": Q(status__in=Task.OPEN),
    "review": Q(status="review"),
    "blocked": Q(status="blocked"),
    "done": Q(status="done"),
    "total": ~Q(status="cancelled"),
}


def _per_project(pids, base, extra) -> dict:
    """프로젝트별 집계 = 주 프로젝트 + 확정 연결(연결 태스크는 여러 프로젝트에 센다).
    조인 곱을 피해 두 번 묶어 더한다. base는 Task 조건, extra는 {이름: Q}(태스크 기준).
    잎만 센다(R8) — 조직 합계(tasks_visible_in)·프로젝트 지표(project_stats_bulk)와 같은 규칙."""
    leaves = leaf_only(Task.objects.all())
    aggs = {k: Count("id", filter=q) for k, q in extra.items()}
    out = defaultdict(lambda: dict.fromkeys(extra, 0))
    for key, qs in (
        ("project_id", leaves.filter(base, project__in=pids)),
        (
            "project_links__project_id",
            leaves.filter(base, project_links__project__in=pids, project_links__status="active"),
        ),
    ):
        for r in qs.values(key).order_by().annotate(**aggs):
            row = out[r.pop(key)]
            for k, v in r.items():
                row[k] += v
    return out


def org_status(org, *, viewer=None) -> dict:
    """조직 지표. 키: counts, by_project, by_assignee, capacity, projects_without_owner

    capacity의 팀 소속은 viewer가 볼 수 있는 팀만 담는다(`visible_teams`). viewer가 None(봇·
    조직 채널 게시 등)이면 비공개 팀과 비공개 프로젝트를 뺀다. 프로젝트·태스크 집계도
    viewer가 볼 수 있는 프로젝트만 센다(`visible_projects`).
    """
    shown_projects = _projects(org, viewer)
    today = today_kst()
    # 초과 판정만 유예(task.overdue_grace_days, 프로젝트가 덮어쓸 수 있다)를 본다.
    # 화면 배지·알림과 같은 기준이다.
    live = list(shown_projects.filter(is_archived=False).select_related("org"))
    is_overdue = overdue_q(live)
    monday, sunday = week_bounds(today)
    open_qs = _open_qs(org, viewer)
    counts = {
        "open": open_qs.count(),
        "doing": open_qs.filter(status="doing").count(),
        "review": open_qs.filter(status="review").count(),
        "blocked": open_qs.filter(status="blocked").count(),
        "overdue": open_qs.filter(is_overdue).count(),
        "due_this_week": open_qs.filter(due_date__gte=monday, due_date__lte=sunday).count(),
        "no_due": open_qs.filter(due_date__isnull=True).count(),
        "done": tasks_visible_in(org, viewer)
        .filter(project__is_archived=False, status="done")
        .count(),
    }

    # 프로젝트별 수치는 연결 포함(각주 "연결 태스크는 여러 프로젝트에 셉니다"). 초과는 태스크의
    # 주 프로젝트 유예를 따르므로 조직의 모든 진행 프로젝트로 판정한다.
    projects = list(shown_projects.filter(is_archived=False).prefetch_related("owners", "teams"))
    org_live = list(org.projects.filter(is_archived=False).select_related("org"))
    stats = _per_project(
        [p.pk for p in projects],
        Q(),
        {**STATS, "overdue": Q(status__in=Task.OPEN) & overdue_q(org_live)},
    )
    by_project = [
        {
            "id": p.pk,
            "name": p.name,
            "status": p.status,
            "owners": [user_brief(u) for u in p.owners.all()],
            "teams": [{"id": t.pk, "name": t.name} for t in p.teams.all()],
            **{
                k: stats[p.pk][k] for k in ("open", "overdue", "review", "blocked", "done", "total")
            },
        }
        for p in projects
    ]

    by_assignee = list(
        open_qs.values("assignee_id", "assignee__display_name")
        .annotate(
            open=Count("id"),
            doing=Count("id", filter=Q(status="doing")),
            overdue=Count("id", filter=is_overdue),
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
        shown_projects.filter(is_archived=False, owners__isnull=True).values("id", "name")
    )
    return {
        "counts": counts,
        "by_project": by_project,
        "by_assignee": by_assignee,
        "capacity": capacity,
        "projects_without_owner": projects_without_owner,
    }


def weekly(org, week_start: date, *, viewer=None) -> dict:
    """주간 집계. week_start는 월요일이어야 한다.

    viewer가 None(봇 토큰·조직 채널 게시)이면 비공개 프로젝트를 뺀다. 사람은 viewer=user.
    """
    if week_start.weekday() != 0:
        raise ValueError("week_start must be a Monday")
    start, end = kst_week_range(week_start)
    period_end = week_start + timedelta(days=7)
    this_monday, this_sunday = week_bounds(period_end)

    shown_projects = _projects(org, viewer)
    org_task_ids = tasks_visible_in(org, viewer).values("id")
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
            .select_related("project", "assignee", "reviewer")
            .order_by("project__name", "id")
        )
        return [task_brief(t) for t in attach_group_visible(list(qs), viewer)]

    open_qs = _open_qs(org, viewer).select_related("project", "assignee", "reviewer")
    due_this_week = [
        task_brief(t)
        for t in attach_group_visible(
            list(
                open_qs.filter(due_date__gte=this_monday, due_date__lte=this_sunday).order_by(
                    "due_date", "id"
                )
            ),
            viewer,
        )
    ]
    shown = list(shown_projects.filter(is_archived=False).select_related("org").order_by("name"))
    is_overdue = overdue_q(shown)  # 화면 배지와 같은 유예 기준(프로젝트별)
    overdue = [
        task_brief(t)
        for t in attach_group_visible(
            list(open_qs.filter(is_overdue).order_by("due_date", "id")), viewer
        )
    ]
    blocked = [
        task_brief(t)
        for t in attach_group_visible(list(open_qs.filter(status="blocked").order_by("id")), viewer)
    ]

    # 프로젝트 수와 무관하게 쿼리 몇 번: 바뀐 태스크의 프로젝트(주 + 연결), 미완료 집계.
    # 프로젝트별 수치는 연결 포함, 위 counts는 태스크당 한 번.
    changed = completed_ids | reopened_ids
    projects_of = defaultdict(set)
    for tid, pid in Task.objects.filter(pk__in=changed).values_list("id", "project_id"):
        projects_of[tid].add(pid)
    for tid, pid in TaskProject.objects.filter(task_id__in=changed, status="active").values_list(
        "task_id", "project_id"
    ):
        projects_of[tid].add(pid)
    org_live = list(org.projects.filter(is_archived=False).select_related("org"))
    open_by = _per_project(
        [p.pk for p in shown],
        Q(status__in=Task.OPEN, is_template=False, project__is_archived=False),
        {
            "open": Q(),
            "overdue": overdue_q(org_live),
            "blocked": Q(status="blocked"),
        },
    )
    by_project = [
        {
            "project": {"id": p.pk, "name": p.name, "status": p.status},
            "completed": sum(1 for i in completed_ids if p.pk in projects_of[i]),
            "reopened": sum(1 for i in reopened_ids if p.pk in projects_of[i]),
            **open_by[p.pk],
        }
        for p in shown
    ]

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
        "github": weekly_metrics(shown_projects.filter(is_archived=False), start, end),
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
