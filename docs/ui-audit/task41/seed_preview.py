"""Disposable Docker preview data; never run against a shared database."""
import os
from datetime import timedelta

assert os.environ.get("DATABASE_URL") == "sqlite:////data/design.sqlite3"

from accounts.models import User
from common.dates import today_kst
from orgs.models import OrgMembership
from orgs.services import create_org, create_team, add_team_member
from projects.services import create_project, create_milestone
from tasks.services import create_task, transition, today_add, checklist_add
from notes.models import MeetingNote

if User.objects.filter(username="design_demo").exists():
    print("Preview already seeded")
else:
    user = User.objects.create_user("design_demo", password="DemoReview41!", display_name="김하늘")
    org = create_org("산돌이", "학생의 하루를 돕는 서비스", user)
    member = User.objects.create_user("design_member", password="DemoReview41!", display_name="이서준")
    OrgMembership.objects.create(org=org, user=member, role="member")
    team = create_team(org=org, name="서비스 개발", actor=user)
    add_team_member(team, user, user)
    add_team_member(team, member, user)
    day = today_kst()
    titles = ["메뉴 누락 안내 개선", "모바일 업무 화면 정리", "새 학기 시간표 검증", "연결 오류 안내 작성", "프로젝트 문서 정리", "배포 전 점검"]
    for pi, name in enumerate(["ProjectManager", "학식 API", "강의실 시간표", "공지 알림"]):
        project = create_project(org=org, name=name, actor=user, owners=[user], status="active", purpose=["팀의 업무와 결정을 한 곳에서 관리합니다.", "오늘의 식단과 운영 시간을 안내합니다.", "강의실 이용 가능 시간을 확인합니다.", "학생에게 필요한 공지를 전달합니다."][pi])
        project.teams.add(team)
        create_milestone(project=project, name="사용성 개선", target_date=day+timedelta(days=14), start_date=day, actor=user, status="active")
        for ti, title in enumerate(titles[:6 if pi == 0 else 3]):
            task = create_task(project=project, title=title, actor=user, source="web", assignee=user if ti % 3 else member, description="사용자가 현재 상황과 다음 행동을 쉽게 알 수 있도록 화면과 안내를 정리합니다.", done_when="모바일과 데스크톱에서 안내 및 동작 확인", next_action="실제 화면에서 안내 문구와 흐름 확인" if ti % 2 else "", due_date=day+timedelta(days=ti-1), priority=7-ti)
            status = ["todo", "doing", "review", "blocked", "done", "paused"][ti]
            if status != "todo":
                task = transition(task, status, actor=user, source="web", expected_version=task.version, reason="외부 API 응답 확인 대기" if status == "blocked" else "")
            if pi == 0:
                checklist_add(task, "데스크톱 화면 확인", actor=user)
                checklist_add(task, "모바일 화면 확인", actor=user)
                if task.assignee_id == user.pk and status != "done":
                    today_add(user, task)
        MeetingNote.objects.create(org=org, project=project, title=name+" 주간 회의", body_md="# 이번 주 목표\n업무 흐름과 안내를 명확하게 정리합니다.\n\n## 결정 사항\n- 주요 화면의 일관성을 우선합니다.\n- 변경 후 실제 동작을 확인합니다.", created_by=user)
    print("Seeded disposable preview")
