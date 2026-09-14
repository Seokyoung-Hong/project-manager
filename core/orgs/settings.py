"""설정 레지스트리. 모든 설정의 키·형·기본값·범위·층·편집 권한이 이 표 하나에 있다.

화면·API·MCP·검증이 전부 이 표를 읽는다. 항목을 추가한다 = 표에 한 줄 + services 강제 지점 한 곳.
저장은 Organization/Project/User 의 settings JSONField. 키가 없으면 기본값이다.
설정을 읽는 경로는 effective() 하나뿐이다 — JSON을 직접 읽지 않는다.
근거: docs/IMPL-PLAN-4.md §4·§6.
"""

from dataclasses import dataclass

from common.errors import ServiceError

LOCKED = "_locked"  # Organization.settings 안의 예약 키: 프로젝트 덮어쓰기를 막은 키 목록


@dataclass(frozen=True)
class Spec:
    key: str
    kind: str  # bool | int | choice | set | text
    default: object
    scope: str  # org | user
    label: str
    group: str  # task | project | org | ai | notify | user
    overridable: bool = False  # org 항목을 프로젝트가 덮어쓸 수 있는가
    help: str = ""
    choices: tuple = ()  # choice·set: (값, 표기)
    lo: int = 0
    hi: int = 0
    ai_only: bool = False  # source == "mcp" 에만 적용


GROUPS = [
    ("task", "태스크 규칙"),
    ("project", "프로젝트 권한"),
    ("org", "조직 운영"),
    ("ai", "AI 정책"),
    ("notify", "알림"),
    ("user", "내 설정"),
]

_LEVELS3 = (("member", "멤버"), ("owner", "프로젝트 관리자"), ("admin", "조직 관리자만"))
_LEVELS2 = (("owner", "프로젝트 관리자"), ("admin", "조직 관리자만"))
_AI = (("allow", "허용"), ("deny", "금지"))  # pending 은 승인 대기 큐(IMPL-PLAN-5)에서 연다
_KINDS = (("d3", "D-3"), ("d1", "D-1"), ("d0", "당일"), ("overdue", "초과"))
_EVENTS = (
    ("created", "생성"),
    ("done", "완료"),
    ("blocked", "막힘"),
    ("overdue_daily", "초과 일일"),
    ("milestone_due", "마일스톤"),
)


def _t(key, label, help="", **kw):
    return Spec(key, scope="org", group="task", label=label, help=help, **kw)


def _p(key, label, help="", **kw):
    return Spec(key, scope="org", group="project", label=label, help=help, **kw)


def _o(key, label, help="", **kw):
    return Spec(key, scope="org", group="org", label=label, help=help, **kw)


def _a(key, label, help="", **kw):
    return Spec(key, scope="org", group="ai", label=label, help=help, ai_only=True, **kw)


def _n(key, label, help="", **kw):
    return Spec(key, scope="org", group="notify", label=label, help=help, **kw)


def _u(key, label, help="", **kw):
    return Spec(key, scope="user", group="user", label=label, help=help, **kw)


SPECS: dict[str, Spec] = {
    s.key: s
    for s in [
        # ---- 태스크 규칙 ----
        _t(
            "task.default_priority",
            "기본 중요도",
            kind="int",
            default=5,
            lo=1,
            hi=10,
            overridable=True,
        ),
        _t(
            "task.priority_cap",
            "중요도 상한",
            "이 값을 넘는 중요도는 프로젝트 관리자·조직 관리자만 정할 수 있어요. 0=없음",
            kind="int",
            default=0,
            lo=0,
            hi=10,
            overridable=True,
        ),
        _t(
            "task.require_done_when",
            "완료 조건 필수",
            "완료 조건 없이는 태스크를 만들 수 없어요",
            kind="bool",
            default=False,
            overridable=True,
        ),
        _t(
            "task.due_required",
            "기한 필수",
            "기한 미정 사유로 대신할 수 없어요",
            kind="bool",
            default=False,
            overridable=True,
        ),
        _t(
            "task.default_due_days",
            "기한 제안(영업일)",
            "생성 폼의 기한 초기값을 오늘+N영업일로 제안해요. 자동으로 채우지는 않아요. 0=없음",
            kind="int",
            default=0,
            lo=0,
            hi=30,
            overridable=True,
        ),
        _t(
            "task.doing_limit",
            "동시 진행 한도",
            "한 사람이 동시에 진행 중으로 둘 수 있는 수. 0=없음",
            kind="int",
            default=0,
            lo=0,
            hi=10,
        ),
        _t(
            "task.doing_limit_mode",
            "한도 초과 시",
            kind="choice",
            default="warn",
            choices=(("warn", "경고만"), ("block", "차단")),
        ),
        _t(
            "task.review_required",
            "검토 대기 필수",
            "완료는 검토 대기에서만 들어갈 수 있어요",
            kind="bool",
            default=False,
            overridable=True,
        ),
        _t(
            "task.self_review",
            "본인 검토 허용",
            "끄면 담당자 본인이 검토 대기 → 완료를 못 해요",
            kind="bool",
            default=True,
            overridable=True,
        ),
        _t(
            "task.reopen_reason_required",
            "재개 사유 필수",
            kind="bool",
            default=False,
            overridable=True,
        ),
        _t(
            "task.cancel_reason_required",
            "취소 사유 필수",
            kind="bool",
            default=False,
            overridable=True,
        ),
        _t(
            "task.assignee_change_reason",
            "담당자 변경 사유 필수",
            kind="bool",
            default=False,
            overridable=True,
        ),
        _t(
            "task.due_change_reason",
            "기한 변경 사유 필수",
            "연장 외 단축·삭제에도 사유를 받아요",
            kind="bool",
            default=False,
            overridable=True,
        ),
        _t(
            "task.overdue_grace_days",
            "초과 유예(일)",
            "이 기간까지는 화면 강조와 초과 알림에서 빼요",
            kind="int",
            default=0,
            lo=0,
            hi=14,
            overridable=True,
        ),
        # ---- 프로젝트 권한 ----
        _p(
            "project.create_by",
            "프로젝트 생성",
            kind="choice",
            default="member",
            choices=(("member", "멤버"), ("admin", "조직 관리자만")),
        ),
        _p(
            "project.edit_by",
            "이름·목적·담당 팀 수정",
            kind="choice",
            default="member",
            choices=_LEVELS3,
        ),
        _p(
            "project.status_by",
            "프로젝트 상태 변경",
            kind="choice",
            default="member",
            choices=_LEVELS3,
        ),
        _p("project.archive_by", "보관·복원", kind="choice", default="admin", choices=_LEVELS2),
        _p(
            "project.settings_by",
            "프로젝트 설정 편집",
            "저장소 규칙·프로젝트 거버넌스 포함",
            kind="choice",
            default="owner",
            choices=_LEVELS2,
        ),
        _p(
            "project.roadmap_by",
            "마일스톤·의존성 편집",
            kind="choice",
            default="member",
            choices=_LEVELS3,
        ),
        _p("project.owner_required", "프로젝트 관리자 최소 1명", kind="bool", default=False),
        _p(
            "project.default_view",
            "프로젝트 첫 화면",
            kind="choice",
            default="list",
            choices=(("list", "목록"), ("board", "보드")),
            overridable=True,
        ),
        # ---- 조직 운영 ----
        _o("org.invite_days", "초대 링크 만료(일)", kind="int", default=7, lo=1, hi=90),
        _o(
            "org.invite_max_uses",
            "초대 링크 최대 사용 횟수",
            "0=무제한",
            kind="int",
            default=0,
            lo=0,
            hi=100,
        ),
        _o(
            "org.tags_by",
            "스킬 태그 수정",
            kind="choice",
            default="admin",
            choices=(("admin", "조직 관리자만"), ("self", "본인도")),
        ),
        _o(
            "org.team_join_self",
            "팀 자율 참여",
            "멤버가 스스로 팀에 들어가고 나갈 수 있어요",
            kind="bool",
            default=False,
        ),
        # ---- AI 정책 (MCP 경로에만) ----
        _a(
            "ai.enabled",
            "AI 사용",
            "끄면 이 조직에 대한 모든 AI 쓰기를 막아요. 읽기는 남아요",
            kind="bool",
            default=True,
        ),
        _a("ai.create_task", "태스크 생성", kind="choice", default="allow", choices=_AI),
        _a(
            "ai.edit_text",
            "제목·설명·메모·체크리스트 수정",
            kind="choice",
            default="allow",
            choices=_AI,
        ),
        _a("ai.change_assignee", "담당자 변경", kind="choice", default="allow", choices=_AI),
        _a("ai.change_due", "기한 변경", kind="choice", default="allow", choices=_AI),
        _a("ai.change_priority", "중요도 변경", kind="choice", default="allow", choices=_AI),
        _a(
            "ai.priority_cap",
            "AI 중요도 상한",
            "AI가 정할 수 있는 최대 중요도. 0=없음",
            kind="int",
            default=7,
            lo=0,
            hi=10,
        ),
        _a(
            "ai.transition_open",
            "미완료 상태 사이 전이",
            kind="choice",
            default="allow",
            choices=_AI,
        ),
        _a("ai.close_task", "완료·취소 처리", kind="choice", default="allow", choices=_AI),
        _a("ai.reopen_task", "완료·취소 재개", kind="choice", default="allow", choices=_AI),
        _a(
            "ai.manage_teams",
            "팀 만들기·팀원 넣고 빼기",
            kind="choice",
            default="allow",
            choices=_AI,
        ),
        # ---- 알림 (discord_service 가 읽는다) ----
        _n(
            "notify.deadline_kinds",
            "보내는 마감 알림",
            kind="set",
            default=["d3", "d1", "d0", "overdue"],
            choices=_KINDS,
        ),
        _n(
            "notify.send_hour",
            "마감 DM 시각",
            "비우면 봇 환경 변수 SEND_HOUR",
            kind="int",
            default=None,
            lo=0,
            hi=23,
        ),
        _n(
            "notify.overdue_repeat",
            "초과 알림 반복",
            kind="choice",
            default="daily",
            choices=(
                ("daily", "매일"),
                ("weekdays", "평일만"),
                ("weekly", "주 1회"),
                ("never", "안 함"),
            ),
        ),
        _n("notify.quiet_weekend", "주말에는 보내지 않기", kind="bool", default=False),
        _n("notify.weekly_enabled", "주간 보고", kind="bool", default=True),
        _n(
            "notify.weekly_weekday",
            "주간 보고 요일",
            "0=월 … 6=일. 비우면 환경 변수",
            kind="int",
            default=None,
            lo=0,
            hi=6,
        ),
        _n(
            "notify.weekly_hour",
            "주간 보고 시각",
            "비우면 환경 변수",
            kind="int",
            default=None,
            lo=0,
            hi=23,
        ),
        _n(
            "notify.blocked_escalate_days",
            "막힘 에스컬레이션(일)",
            "막힘이 N일 넘으면 프로젝트 관리자에게 DM. 0=끄기",
            kind="int",
            default=0,
            lo=0,
            hi=14,
            overridable=True,
        ),
        _n(
            "notify.review_nudge_days",
            "검토 독촉(일)",
            "검토 대기가 N일 넘으면 프로젝트 관리자에게 DM. 0=끄기",
            kind="int",
            default=0,
            lo=0,
            hi=14,
            overridable=True,
        ),
        _n(
            "notify.project_channel_events",
            "프로젝트 채널 게시",
            "채널이 연결된 프로젝트만",
            kind="set",
            default=[],
            choices=_EVENTS,
            overridable=True,
        ),
        _n("notify.team_channel_weekly", "팀 채널에도 주간 보고", kind="bool", default=False),
        # ---- 개인 ----
        _u(
            "user.notify_dm",
            "Discord DM 받기",
            "끄면 마감·에스컬레이션 DM을 받지 않아요. 주간 보고(채널)는 그대로",
            kind="bool",
            default=True,
        ),
        _u(
            "user.notify_kinds",
            "받을 마감 알림",
            "조직이 끈 종류는 켤 수 없어요",
            kind="set",
            default=["d3", "d1", "d0", "overdue"],
            choices=_KINDS,
        ),
        _u(
            "user.notify_hour",
            "내 DM 시각",
            "비우면 조직 기본",
            kind="int",
            default=None,
            lo=0,
            hi=23,
        ),
        _u(
            "user.start_page",
            "첫 화면",
            kind="choice",
            default="today",
            choices=(("today", "오늘"), ("me", "내 태스크")),
        ),
        _u(
            "user.me_group",
            "내 태스크 기본 묶음",
            kind="choice",
            default="due",
            choices=(
                ("due", "기한별"),
                ("project", "프로젝트별"),
                ("status", "상태별"),
                ("none", "묶지 않음"),
            ),
        ),
        _u(
            "user.me_sort",
            "내 태스크 기본 정렬",
            kind="choice",
            default="due",
            choices=(("due", "기한"), ("priority", "중요도"), ("updated", "최근 수정")),
        ),
        _u("user.board_default", "프로젝트를 보드로", kind="bool", default=False),
    ]
}


def specs(scope: str, group: str | None = None) -> list[Spec]:
    return [s for s in SPECS.values() if s.scope == scope and (group is None or s.group == group)]


def _coerce(spec: Spec, v):
    """폼(문자열)·API(JSON) 값을 저장형으로. 틀리면 ValueError."""
    if v is None or v == "":
        if spec.kind == "int" and spec.default is None:
            return None
        if spec.kind == "bool":
            return False
        raise ValueError
    if spec.kind == "bool":
        if isinstance(v, bool):
            return v
        return str(v).lower() in ("1", "true", "on", "yes")
    if spec.kind == "int":
        if isinstance(v, bool):
            raise ValueError
        n = int(v)
        if not spec.lo <= n <= spec.hi:
            raise ValueError
        return n
    if spec.kind == "choice":
        if v not in dict(spec.choices):
            raise ValueError
        return v
    if spec.kind == "set":
        if isinstance(v, str):
            v = [v]
        allowed = dict(spec.choices)
        vals = [x for x in dict.fromkeys(v)]
        if any(x not in allowed for x in vals):
            raise ValueError
        return [c for c, _ in spec.choices if c in vals]
    if spec.kind == "text":
        return str(v)
    raise ValueError


def clean(scope: str, data: dict, *, overridable_only=False) -> dict:
    """알 수 없는 키·형·범위 → ServiceError. 기본값과 같은 값은 지운다(키 없음 = 기본값).

    overridable_only: 프로젝트 층. org 항목 중 overridable 만 받는다.
    """
    out, errors = {}, {}
    for key, v in (data or {}).items():
        spec = SPECS.get(key)
        if spec is None or spec.scope != scope or (overridable_only and not spec.overridable):
            errors[key] = "알 수 없는 설정이에요."
            continue
        try:
            val = _coerce(spec, v)
        except (ValueError, TypeError):
            errors[key] = f"{spec.label}: 값이 올바르지 않아요."
            continue
        if val != spec.default:
            out[key] = val
    if errors:
        raise ServiceError(errors)
    return out


def locked_keys(org) -> list[str]:
    return list(org.settings.get(LOCKED, []))


def effective(key: str, *, org=None, project=None, user=None):
    """개인 > 프로젝트(잠기지 않은 덮어쓰기) > 조직 > 기본값."""
    spec = SPECS[key]
    if spec.scope == "user":
        return user.settings.get(key, spec.default) if user is not None else spec.default
    if project is not None:
        org = org or project.org
        if spec.overridable and key in project.settings and key not in locked_keys(org):
            return project.settings[key]
    if org is None:
        return spec.default
    return org.settings.get(key, spec.default)


def display(spec: Spec, value) -> str:
    if spec.kind == "bool":
        return "켜짐" if value else "꺼짐"
    if spec.kind == "choice":
        return dict(spec.choices).get(value, str(value))
    if spec.kind == "set":
        return ", ".join(dict(spec.choices)[c] for c in value) or "없음"
    if value is None:
        return "환경 변수"
    return str(value)


def enforced(org, project=None) -> list[dict]:
    """거버넌스 화면 상단 '설정에서 강제 중'. 기본값이 아닌 org·project 항목만."""
    rows = []
    for spec in specs("org"):
        if spec.group == "notify":
            continue
        val = effective(spec.key, org=org, project=project)
        if val == spec.default:
            continue
        where = (
            "프로젝트 설정"
            if project is not None
            and spec.key in project.settings
            and val != org.settings.get(spec.key, spec.default)
            else "조직 설정"
        )
        rows.append(
            {"key": spec.key, "label": spec.label, "value": display(spec, val), "where": where}
        )
    return rows
