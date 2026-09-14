STATUS = {
    "todo": "시작 전",
    "doing": "진행 중",
    "paused": "일시정지",
    "blocked": "막힘",
    "review": "검토 대기",
    "done": "완료",
    "cancelled": "취소",
}
KIND_TITLE = {"d3": "D-3", "d1": "D-1", "d0": "오늘 마감", "overdue": "기한 초과"}

HELP = """이렇게 보내면 됩니다.
• `오늘` — 오늘 할 일
• `완료 12` — 12번(TASK-12) 태스크를 완료로
• `연장 12 2026-09-20 QA 지연` — 목표일을 미루고 사유 남기기
• `연결 <코드>` — 웹 설정 → 프로필에서 받은 코드로 계정 연결
• `연결해제` — 연결 끊기(DM 알림도 멈춥니다)"""

SLASH_HELP = """슬래시 명령으로도 됩니다. 답장은 나에게만 보입니다.
• `/오늘` · `/완료` · `/연장` · `/연결` · `/연결해제`
• `/태스크만들기` · `/태스크수정` · `/메모` · `/상태`
• `/팀채널` · `/프로젝트채널` — 조직 관리자만
번호·프로젝트·팀·담당자는 입력하면 목록이 뜹니다. 숫자를 외울 필요 없어요."""


def mention(assignee: dict) -> str:
    """팀 채널 게시용. 개인 DM에는 쓰지 않는다(받는 사람 본인이다)."""
    did = assignee.get("discord_user_id")
    return f"<@{did}>" if did else assignee.get("display_name", "?")


def task_line(t: dict) -> str:
    """개인 DM용 한 줄. 담당자는 받는 사람 본인이라 넣지 않는다."""
    reason = f" ({t['stop_reason']})" if t.get("stop_reason") else ""
    return (
        f"• **{t['number']}** {t['title']} — {t['project']['name']}"
        f" — {STATUS.get(t['status'], t['status'])}{reason}\n  {t['url']}"
    )


def team_task_line(t: dict) -> str:
    """팀 채널용 한 줄. 누구 일인지 보여야 한다."""
    reason = f" ({t['stop_reason']})" if t.get("stop_reason") else ""
    return (
        f"• **{t['number']}** {t['title']} — {t['project']['name']} — {mention(t['assignee'])}"
        f" — {STATUS.get(t['status'], t['status'])}{reason}\n  {t['url']}"
    )


def deadline_message(kind: str, tasks: list[dict], today: str) -> str:
    head = f"📌 마감 알림 · {KIND_TITLE[kind]} · {today}"
    lines = [
        task_line(t) + (f"  (기한 {t['due_date']})" if kind == "overdue" else "") for t in tasks
    ]
    tail = "\n답장으로 처리할 수 있어요: `완료 12` · `연장 12 2026-09-20 사유` · `도움`"
    return head + "\n" + "\n".join(lines) + tail


def dm_blocked_message(assignee: dict) -> str:
    """DM이 막힌 사람에게 팀 채널로 알리는 문구. 태스크 내용은 넣지 않는다."""
    return (
        f"{mention(assignee)} 마감 알림 DM을 보낼 수 없어요. 서버 우클릭 → 개인정보 보호 설정 →"
        " '서버 멤버의 DM 허용'을 켜 주세요."
    )


def today_message(view: dict) -> str:
    """`오늘` 답장. 오늘 화면과 같은 내용."""
    c = view["counts"]
    head = f"🗓 오늘 · {view['date']} · 미완료 {c['my_open']}건 · 오늘 완료 {c['done_today']}건"
    items = view["items"][:15]
    if not items:
        return head + "\n담은 일이 없습니다. 웹 `/today`에서 담아 보세요."
    more = len(view["items"]) - len(items)
    body = "\n".join(task_line(t) for t in items)
    return head + "\n" + body + (f"\n… 그리고 {more}건 더" if more > 0 else "")


def escalate_message(kind: str, project_name: str, tasks: list[dict]) -> str:
    """막힘·검토 지연 에스컬레이션. 프로젝트 관리자에게 프로젝트별로 묶어 하루 1건."""
    title = "막힘 경과" if kind == "blocked" else "검토 대기 경과"
    head = f"⏱ {title} · {project_name}"
    lines = [f"• **{t['number']}** {t['title']}" for t in tasks]
    return head + "\n" + "\n".join(lines)


def channel_event_message(event: str, task: dict) -> str:
    """프로젝트 Discord 채널 게시. 멘션은 만들지 않는다(마감 DM과 같은 원칙)."""
    title = {"created": "생성", "done": "완료", "blocked": "막힘"}.get(event, event)
    assignee = (task.get("assignee") or {}).get("display_name", "미배정")
    return f"📋 {title} · **{task['number']}** {task['title']} — {assignee}"


def test_message(site_name: str) -> str:
    return f"✅ {site_name} Discord 봇 연결 테스트"
