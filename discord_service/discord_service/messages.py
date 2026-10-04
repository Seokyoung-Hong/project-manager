from datetime import date

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
• `/요청` · `/요청수락` · `/요청거절` · `/요청완료` · `/요청목록` — 팀·사람에게 일 부탁하기
• `/팀채널` · `/프로젝트채널` — 조직 관리자만
번호·프로젝트·팀·담당자는 입력하면 목록이 뜹니다. 숫자를 외울 필요는 없습니다."""


def mention(assignee: dict) -> str:
    """팀 채널 게시용. 개인 DM에는 쓰지 않는다(받는 사람 본인이다)."""
    did = assignee.get("discord_user_id")
    return f"<@{did}>" if did else assignee.get("display_name", "?")


def task_line(t: dict, org_names: dict | None = None) -> str:
    """개인 DM용 한 줄. 담당자는 받는 사람 본인이라 넣지 않는다.

    `org_names`가 있으면(사람이 조직 둘 이상에 걸쳐 있을 때만, §8.4) 조직 이름을 덧붙인다.
    """
    reason = f" ({t['stop_reason']})" if t.get("stop_reason") else ""
    org_tag = ""
    if org_names:
        name = org_names.get(t["project"].get("org_id"))
        if name:
            org_tag = f" · {name}"
    return (
        f"• **{t['number']}** {t['title']} — {t['project']['name']}{org_tag}"
        f" — {STATUS.get(t['status'], t['status'])}{reason}\n  {t['url']}"
    )


def team_task_line(t: dict) -> str:
    """팀 채널용 한 줄. 누구 일인지 보여야 한다."""
    reason = f" ({t['stop_reason']})" if t.get("stop_reason") else ""
    return (
        f"• **{t['number']}** {t['title']} — {t['project']['name']} — {mention(t['assignee'])}"
        f" — {STATUS.get(t['status'], t['status'])}{reason}\n  {t['url']}"
    )


OPEN = ("todo", "doing", "paused", "blocked", "review")
KIND_LEAD = {
    "d3": "기한이 3일 남았습니다.",
    "d1": "기한이 내일입니다.",
    "d0": "기한이 오늘입니다.",
    "overdue": "기한이 지났습니다.",
}


def due_label(due: str | None, today: str) -> str:
    """'D-3 (9월 12일)' · '오늘 마감 (9월 9일)' · '2일 초과 (9월 7일)' · '기한 없음'."""
    if not due:
        return "기한 없음"
    d, t = date.fromisoformat(due), date.fromisoformat(today)
    delta = (d - t).days
    when = f"{d.month}월 {d.day}일"
    if delta > 0:
        return f"D-{delta} ({when})"
    if delta == 0:
        return f"오늘 마감 ({when})"
    return f"{-delta}일 초과 ({when})"


def _link_text(t: dict) -> str:
    """`[TASK-12 제목](<url>)`. `<>`로 감싸 링크 미리보기(embed)가 붙지 않게 한다."""
    title = t["title"].replace("[", "\\[").replace("]", "\\]")
    return f"[{t['number']} {title}](<{t['url']}>)"


def alert_line(t: dict, today: str, *, who: bool = False, reason: bool = True) -> str:
    """알림 한 줄: 번호·제목(웹 링크) · 기한(D-n/초과 n일) · 상태(사유) [· 담당자].

    완료·취소된 태스크는 기한을 적지 않는다. `who`는 채널 게시용(누구 일인지 보여야 한다).
    `reason=False`면 막힘 사유를 뺀다(공유 채널에 사유를 올리지 않는다).
    """
    status = STATUS.get(t["status"], t["status"])
    if reason and t.get("stop_reason"):
        status += f"({t['stop_reason']})"
    parts = [_link_text(t)]
    if t["status"] in OPEN:
        parts.append(due_label(t.get("due_date"), today))
    parts.append(status)
    if who:
        parts.append(mention(t.get("assignee") or {}))
    return "• " + " · ".join(parts)


def by_project(tasks: list[dict], today: str, **line_kw) -> str:
    """프로젝트별로 묶은 본문. 프로젝트 순서는 처음 나온 순서(보통 기한 순)를 따른다."""
    groups: dict[str, list[str]] = {}
    for t in tasks:
        groups.setdefault(t["project"]["name"], []).append(alert_line(t, today, **line_kw))
    return "\n".join(f"**{name}**\n" + "\n".join(lines) for name, lines in groups.items())


def deadline_message(kind: str, tasks: list[dict], today: str) -> str:
    head = f"📌 마감 알림 · {KIND_TITLE[kind]} · {today}\n담당하신 태스크 {len(tasks)}건의 {KIND_LEAD[kind]}"
    tail = "\n답장으로 처리할 수 있습니다: `완료 12` · `연장 12 2026-09-20 사유` · `도움`"
    return head + "\n" + by_project(tasks, today) + tail


def dm_blocked_message(assignee: dict) -> str:
    """DM이 막힌 사람에게 팀 채널로 알리는 문구. 태스크 내용은 넣지 않는다."""
    return (
        f"{mention(assignee)} 마감 알림 DM을 보낼 수 없습니다. 서버 우클릭 → 개인정보 보호 설정 →"
        " '서버 멤버의 DM 허용'을 켜 주세요."
    )


def today_message(view: dict, org_names: dict | None = None) -> str:
    """`오늘` 답장. 오늘 화면과 같은 내용."""
    c = view["counts"]
    head = f"🗓 오늘 · {view['date']} · 미완료 {c['my_open']}건 · 오늘 완료 {c['done_today']}건"
    items = view["items"][:15]
    if not items:
        return head + "\n담은 일이 없습니다. 웹 `/today`에서 담아 보세요."
    more = len(view["items"]) - len(items)
    body = "\n".join(task_line(t, org_names) for t in items)
    return head + "\n" + body + (f"\n… 그리고 {more}건 더" if more > 0 else "")


def test_message(site_name: str) -> str:
    return f"✅ {site_name} Discord 봇 연결 테스트"
