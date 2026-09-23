"""설정 레지스트리. IMPL-PLAN-4 §6.1.

모든 설정의 키·형·기본값·범위·층·편집 가능 여부가 이 파일의 표 하나에 있다.
화면·API·MCP·검증이 전부 이 표를 읽는다. **이 파일 밖에서 settings JSON을 직접 읽지 않는다.**

세 층은 개인 > 프로젝트 > 조직 > 기본값 순으로 가까운 값이 이긴다. 단 규칙(`task.*`·`project.*`·
`org.*`·`ai.*`)은 개인이 풀 수 없고, 조직이 `_locked`로 잠근 항목은 프로젝트가 덮어쓸 수 없다.
기본값은 전부 "이 라운드 전의 동작"이다 — 설정을 건드리지 않은 조직은 달라지는 것이 없다.
"""

from dataclasses import dataclass

from common.errors import ServiceError

LOCKED = "_locked"  # 설정 JSON 안의 예약 키. 레지스트리에 없는 키 중 유일하게 허용된다.


@dataclass(frozen=True)
class Spec:
    key: str
    kind: str  # bool | int | choice | set | text
    default: object
    scope: str  # org | user
    overridable: bool = False  # 조직 항목을 프로젝트가 덮어쓸 수 있는가
    group: str = ""
    label: str = ""
    help: str = ""
    choices: tuple = ()
    lo: int = 0
    hi: int = 0
    ai_only: bool = False  # source == "mcp" 에만 적용


def _s(*a, **kw):
    return Spec(*a, **kw)


ALARM_KINDS = (("d3", "3일 전"), ("d1", "하루 전"), ("d0", "당일"), ("overdue", "기한 초과"))
ALLOW_DENY = (("allow", "허용"), ("deny", "막기"))
LEVELS = (("member", "멤버 누구나"), ("owner", "프로젝트 관리자"), ("admin", "조직 관리자만"))

SPECS: dict[str, Spec] = {
    s.key: s
    for s in [
        # --- 4.1 태스크 규칙 ---
        _s(
            "task.default_priority",
            "int",
            5,
            "org",
            True,
            "task",
            "기본 중요도",
            "생성 화면·API·AI가 중요도를 주지 않았을 때 쓰는 값입니다.",
            lo=1,
            hi=10,
        ),
        _s(
            "task.priority_cap",
            "int",
            0,
            "org",
            True,
            "task",
            "중요도 상한",
            "이 값을 넘는 중요도는 프로젝트 관리자만 정할 수 있습니다. 0이면 제한하지 않습니다.",
            lo=0,
            hi=10,
        ),
        _s(
            "task.require_done_when",
            "bool",
            False,
            "org",
            True,
            "task",
            "완료 조건 필수",
            "완료 조건을 적지 않으면 태스크를 만들 수 없습니다.",
        ),
        _s(
            "task.due_required",
            "bool",
            False,
            "org",
            True,
            "task",
            "기한 필수",
            "기한 미정 사유로 대신할 수 없습니다.",
        ),
        _s(
            "task.default_due_days",
            "int",
            0,
            "org",
            True,
            "task",
            "기본 기한(영업일)",
            "생성 화면의 기한 초기값을 오늘+N영업일로 제안합니다. 자동으로 채우지는 않습니다. 0이면 제안하지 않습니다.",
            lo=0,
            hi=30,
        ),
        _s(
            "task.doing_limit",
            "int",
            0,
            "org",
            False,
            "task",
            "동시 진행 한도",
            "한 사람이 동시에 진행 중으로 둘 수 있는 태스크 수입니다. 0이면 제한하지 않습니다.",
            lo=0,
            hi=10,
        ),
        _s(
            "task.doing_limit_mode",
            "choice",
            "warn",
            "org",
            False,
            "task",
            "한도 초과 처리",
            "경고면 숫자만 보여 주고, 차단이면 진행 중으로 바꾸지 못하게 막습니다.",
            choices=(("warn", "경고만"), ("block", "차단")),
        ),
        _s(
            "task.review_required",
            "bool",
            False,
            "org",
            True,
            "task",
            "검토 대기 필수",
            "완료는 검토 대기를 거쳐서만 할 수 있습니다.",
        ),
        _s(
            "task.self_review",
            "bool",
            True,
            "org",
            True,
            "task",
            "본인 검토 허용",
            "끄면 담당자 본인이 검토 대기에서 완료로 바꿀 수 없습니다.",
        ),
        _s(
            "task.reopen_reason_required",
            "bool",
            False,
            "org",
            True,
            "task",
            "재개 사유 필수",
            "완료·취소한 태스크를 되돌릴 때 사유를 적게 합니다.",
        ),
        _s("task.cancel_reason_required", "bool", False, "org", True, "task", "취소 사유 필수", ""),
        _s(
            "task.assignee_change_reason",
            "bool",
            False,
            "org",
            True,
            "task",
            "담당자 변경 사유 필수",
            "사유는 이력에 남습니다.",
        ),
        _s(
            "task.due_change_reason",
            "bool",
            False,
            "org",
            True,
            "task",
            "기한 변경 사유 필수",
            "연장은 이미 사유를 받습니다. 단축·삭제에도 사유를 받게 합니다.",
        ),
        _s(
            "task.overdue_grace_days",
            "int",
            0,
            "org",
            True,
            "task",
            "초과 유예(일)",
            "기한이 지나도 N일까지는 초과로 강조하지 않고 초과 알림도 보내지 않습니다.",
            lo=0,
            hi=14,
        ),
        # --- 4.2 프로젝트 규칙 ---
        _s(
            "project.create_by",
            "choice",
            "member",
            "org",
            False,
            "project",
            "프로젝트 생성",
            "",
            choices=(("member", "멤버 누구나"), ("admin", "조직 관리자만")),
        ),
        _s(
            "project.edit_by",
            "choice",
            "member",
            "org",
            False,
            "project",
            "이름·목적·담당 팀 수정",
            "",
            choices=LEVELS,
        ),
        _s(
            "project.status_by",
            "choice",
            "member",
            "org",
            False,
            "project",
            "프로젝트 상태 변경",
            "",
            choices=LEVELS,
        ),
        _s(
            "project.archive_by",
            "choice",
            "admin",
            "org",
            False,
            "project",
            "보관·복원",
            "",
            choices=(("owner", "프로젝트 관리자"), ("admin", "조직 관리자만")),
        ),
        _s(
            "project.settings_by",
            "choice",
            "owner",
            "org",
            False,
            "project",
            "프로젝트 설정 편집",
            "저장소 규칙과 프로젝트 거버넌스 문단을 포함합니다.",
            choices=(("owner", "프로젝트 관리자"), ("admin", "조직 관리자만")),
        ),
        _s(
            "project.roadmap_by",
            "choice",
            "member",
            "org",
            False,
            "project",
            "마일스톤·의존성",
            "",
            choices=LEVELS,
        ),
        _s(
            "project.owner_required",
            "bool",
            False,
            "org",
            False,
            "project",
            "프로젝트 관리자 1명 이상",
            "관리자가 없는 프로젝트를 만들거나 마지막 관리자를 뺄 수 없습니다. 이미 관리자가 없는 프로젝트는 그대로 둡니다.",
        ),
        _s(
            "project.default_view",
            "choice",
            "list",
            "org",
            True,
            "project",
            "프로젝트 첫 화면",
            "",
            choices=(("list", "목록"), ("board", "보드")),
        ),
        # --- 4.3 조직 운영 ---
        _s("org.invite_days", "int", 7, "org", False, "org", "초대 링크 만료(일)", "", lo=1, hi=90),
        _s(
            "org.invite_max_uses",
            "int",
            0,
            "org",
            False,
            "org",
            "초대 링크 사용 횟수",
            "0이면 무제한입니다.",
            lo=0,
            hi=100,
        ),
        _s(
            "org.tags_by",
            "choice",
            "admin",
            "org",
            False,
            "org",
            "스킬 태그 편집",
            "",
            choices=(("admin", "조직 관리자만"), ("self", "본인도 가능")),
        ),
        _s(
            "org.team_join_self",
            "bool",
            False,
            "org",
            False,
            "org",
            "팀 자율 참여",
            "멤버가 스스로 팀에 들어가고 나갈 수 있습니다.",
        ),
        # --- 4.4 AI 정책 (source == "mcp" 에만) ---
        _s(
            "ai.enabled",
            "bool",
            True,
            "org",
            False,
            "ai",
            "AI 쓰기 허용",
            "끄면 이 조직에 대한 AI의 모든 쓰기를 막습니다. 읽기는 남습니다.",
            ai_only=True,
        ),
        _s(
            "ai.create_task",
            "choice",
            "allow",
            "org",
            False,
            "ai",
            "태스크 만들기",
            "",
            choices=ALLOW_DENY,
            ai_only=True,
        ),
        _s(
            "ai.edit_text",
            "choice",
            "allow",
            "org",
            False,
            "ai",
            "본문 고치기",
            "제목·설명·완료 조건·다음 행동·메모·체크리스트입니다.",
            choices=ALLOW_DENY,
            ai_only=True,
        ),
        _s(
            "ai.record_work",
            "choice",
            "allow",
            "org",
            False,
            "ai",
            "AI 작업 기록",
            "태스크에 사용자 입력과 AI의 주요 판단을 의사 요지로 기록합니다. 대화 원문은 사용자가 명시적으로 요청하지 않는 한 전송하지 않습니다.",
            choices=ALLOW_DENY,
            ai_only=True,
        ),
        _s(
            "ai.change_assignee",
            "choice",
            "allow",
            "org",
            False,
            "ai",
            "담당자 바꾸기",
            "",
            choices=ALLOW_DENY,
            ai_only=True,
        ),
        _s(
            "ai.change_due",
            "choice",
            "allow",
            "org",
            False,
            "ai",
            "기한 바꾸기",
            "",
            choices=ALLOW_DENY,
            ai_only=True,
        ),
        _s(
            "ai.change_priority",
            "choice",
            "allow",
            "org",
            False,
            "ai",
            "중요도 바꾸기",
            "",
            choices=ALLOW_DENY,
            ai_only=True,
        ),
        _s(
            "ai.priority_cap",
            "int",
            7,
            "org",
            False,
            "ai",
            "AI 중요도 상한",
            "AI는 이 값을 넘는 중요도를 정할 수 없습니다. 0이면 제한하지 않습니다.",
            lo=0,
            hi=10,
            ai_only=True,
        ),
        _s(
            "ai.transition_open",
            "choice",
            "allow",
            "org",
            False,
            "ai",
            "미완료 상태 바꾸기",
            "",
            choices=ALLOW_DENY,
            ai_only=True,
        ),
        _s(
            "ai.close_task",
            "choice",
            "allow",
            "org",
            False,
            "ai",
            "완료·취소 처리",
            "",
            choices=ALLOW_DENY,
            ai_only=True,
        ),
        _s(
            "ai.reopen_task",
            "choice",
            "allow",
            "org",
            False,
            "ai",
            "완료·취소 되돌리기",
            "",
            choices=ALLOW_DENY,
            ai_only=True,
        ),
        _s(
            "ai.delete",
            "choice",
            "deny",
            "org",
            False,
            "ai",
            "팀·프로젝트·태스크 삭제",
            "삭제는 되돌릴 수 없어 기본값이 막기입니다. 사람이 화면에서 지우는 길은 그대로 있습니다.",
            choices=ALLOW_DENY,
            ai_only=True,
        ),
        _s(
            "ai.manage_repo",
            "choice",
            "allow",
            "org",
            False,
            "ai",
            "저장소 연결·해제",
            "AI가 프로젝트에 GitHub 저장소를 잇거나 끊는 것입니다.",
            choices=ALLOW_DENY,
            ai_only=True,
        ),
        _s(
            "ai.manage_teams",
            "choice",
            "allow",
            "org",
            False,
            "ai",
            "팀 만들고 사람 넣기",
            "",
            choices=ALLOW_DENY,
            ai_only=True,
        ),
        # --- 4.5 알림 ---
        _s(
            "notify.deadline_kinds",
            "set",
            ("d3", "d1", "d0", "overdue"),
            "org",
            False,
            "notify",
            "보내는 마감 알림",
            "",
            choices=ALARM_KINDS,
        ),
        _s(
            "notify.send_hour",
            "int",
            -1,
            "org",
            False,
            "notify",
            "마감 알림 시각",
            "-1이면 서버 기본값(.env.discord의 SEND_HOUR)을 씁니다.",
            lo=-1,
            hi=23,
        ),
        _s(
            "notify.overdue_repeat",
            "choice",
            "daily",
            "org",
            False,
            "notify",
            "초과 알림 반복",
            "",
            choices=(
                ("daily", "매일"),
                ("weekdays", "평일만"),
                ("weekly", "주 1회"),
                ("never", "한 번만"),
            ),
        ),
        _s(
            "notify.quiet_weekend",
            "bool",
            False,
            "org",
            False,
            "notify",
            "주말에는 보내지 않기",
            "토·일에는 마감 DM을 보내지 않습니다.",
        ),
        _s("notify.weekly_enabled", "bool", True, "org", False, "notify", "주간 보고", ""),
        _s(
            "notify.weekly_weekday",
            "int",
            -1,
            "org",
            False,
            "notify",
            "주간 보고 요일",
            "0=월요일. -1이면 서버 기본값입니다.",
            lo=-1,
            hi=6,
        ),
        _s(
            "notify.weekly_hour",
            "int",
            -1,
            "org",
            False,
            "notify",
            "주간 보고 시각",
            "-1이면 서버 기본값입니다.",
            lo=-1,
            hi=23,
        ),
        _s(
            "notify.blocked_escalate_days",
            "int",
            0,
            "org",
            True,
            "notify",
            "막힘 에스컬레이션(일)",
            "막힘이 N일을 넘으면 프로젝트 관리자에게 DM을 보냅니다. 0이면 보내지 않습니다.",
            lo=0,
            hi=14,
        ),
        _s(
            "notify.review_nudge_days",
            "int",
            0,
            "org",
            True,
            "notify",
            "검토 독촉(일)",
            "검토 대기가 N일을 넘으면 프로젝트 관리자에게 DM을 보냅니다. 0이면 보내지 않습니다.",
            lo=0,
            hi=14,
        ),
        _s(
            "notify.project_channel_events",
            "set",
            (),
            "org",
            True,
            "notify",
            "프로젝트 채널 게시",
            "채널이 연결된 프로젝트만 해당합니다. 멘션은 넣지 않습니다.",
            choices=(
                ("created", "태스크 생성"),
                ("done", "완료"),
                ("blocked", "막힘"),
                ("overdue_daily", "기한 초과 요약"),
                ("milestone_due", "마일스톤 임박"),
            ),
        ),
        _s(
            "notify.team_channel_weekly",
            "bool",
            False,
            "org",
            False,
            "notify",
            "팀 채널 주간 보고",
            "조직 채널 외에 팀 채널에도 그 팀 담당 프로젝트만 추려 보냅니다.",
        ),
        # --- 4.6 개인 설정 ---
        _s(
            "user.notify_dm",
            "bool",
            True,
            "user",
            False,
            "user",
            "개인 DM 받기",
            "끄면 마감·에스컬레이션 DM을 받지 않습니다. 채널 주간 보고는 그대로입니다.",
        ),
        _s(
            "user.notify_kinds",
            "set",
            ("d3", "d1", "d0", "overdue"),
            "user",
            False,
            "user",
            "받을 마감 알림",
            "조직이 끈 종류는 켤 수 없습니다.",
            choices=ALARM_KINDS,
        ),
        _s(
            "user.notify_hour",
            "int",
            -1,
            "user",
            False,
            "user",
            "내 마감 알림 시각",
            "-1이면 조직 설정을 따릅니다.",
            lo=-1,
            hi=23,
        ),
        _s(
            "user.start_page",
            "choice",
            "today",
            "user",
            False,
            "user",
            "로그인 후 첫 화면",
            "",
            choices=(("today", "오늘"), ("me", "내 태스크")),
        ),
        _s(
            "user.me_group",
            "choice",
            "due",
            "user",
            False,
            "user",
            "내 태스크 기본 묶음",
            "",
            choices=(
                ("due", "기한"),
                ("project", "프로젝트"),
                ("status", "상태"),
                ("none", "묶지 않음"),
            ),
        ),
        _s(
            "user.me_sort",
            "choice",
            "due",
            "user",
            False,
            "user",
            "내 태스크 기본 정렬",
            "",
            choices=(("due", "기한"), ("priority", "중요도"), ("updated", "최근 수정")),
        ),
        _s(
            "user.board_default",
            "bool",
            False,
            "user",
            False,
            "user",
            "프로젝트를 항상 보드로",
            "프로젝트 설정보다 우선합니다.",
        ),
    ]
}

GROUPS = [
    ("task", "태스크 규칙"),
    ("project", "프로젝트 권한"),
    ("org", "조직 운영"),
    ("ai", "AI 정책"),
    ("notify", "알림"),
    ("user", "내 설정"),
]


def specs_for(scope: str) -> list[Spec]:
    """그 층에서 편집할 수 있는 항목. 화면과 API가 이 순서로 그린다."""
    if scope == "project":
        return [s for s in SPECS.values() if s.scope == "org" and s.overridable]
    return [s for s in SPECS.values() if s.scope == scope]


def _coerce(spec: Spec, value):
    """형과 범위를 본다. 맞지 않으면 (None, 문구)를 돌려준다."""
    if spec.kind == "bool":
        if isinstance(value, bool):
            return value, ""
        if value in ("on", "true", "1", 1):
            return True, ""
        if value in ("off", "false", "0", 0, "", None):
            return False, ""
        return None, "켜기/끄기 값이어야 합니다."
    if spec.kind == "int":
        try:
            n = int(value)
        except (TypeError, ValueError):
            return None, "숫자여야 합니다."
        if not spec.lo <= n <= spec.hi:
            return None, f"{spec.lo}~{spec.hi} 사이여야 합니다."
        return n, ""
    if spec.kind == "choice":
        allowed = [c[0] for c in spec.choices]
        if value not in allowed:
            return None, "고를 수 없는 값입니다."
        return value, ""
    if spec.kind == "set":
        if isinstance(value, str):
            value = [v for v in value.split(",") if v]
        if not isinstance(value, (list, tuple, set)):
            return None, "목록이어야 합니다."
        allowed = {c[0] for c in spec.choices}
        bad = [v for v in value if v not in allowed]
        if bad:
            return None, "모르는 값이 섞여 있습니다."
        # 순서는 레지스트리 순으로 고정한다 — 기본값과 비교할 때 순서로 달라지면 안 된다.
        chosen = set(value)
        return [c[0] for c in spec.choices if c[0] in chosen], ""
    if spec.kind == "text":
        return str(value), ""
    return None, "알 수 없는 형입니다."


def _same_as_default(spec: Spec, value) -> bool:
    if spec.kind == "set":
        return list(value) == list(spec.default)
    return value == spec.default


def clean(scope: str, data: dict, *, allow_locked: bool = False) -> dict:
    """알 수 없는 키·형·범위는 ServiceError. 기본값과 같은 값은 지운다(키 없음 = 기본값)."""
    editable = {s.key for s in specs_for(scope)}
    out, errors = {}, {}
    for key, raw in (data or {}).items():
        if key == LOCKED:
            if not allow_locked:
                errors[key] = "여기서 바꿀 수 없는 항목입니다."
                continue
            keys = [k for k in (raw or []) if k in SPECS and SPECS[k].overridable]
            if keys:
                out[LOCKED] = sorted(keys)
            continue
        spec = SPECS.get(key)
        if spec is None or key not in editable:
            errors[key] = "이 층에서 바꿀 수 없는 설정입니다."
            continue
        value, err = _coerce(spec, raw)
        if err:
            errors[key] = err
            continue
        if not _same_as_default(spec, value):
            out[key] = value
    if errors:
        raise ServiceError(errors)
    return out


def locked_keys(org) -> set:
    return set((getattr(org, "settings", None) or {}).get(LOCKED) or [])


def effective(key: str, *, org=None, project=None, user=None):
    """개인 > 프로젝트 > 조직 > 기본값. 규칙은 개인이 풀 수 없고, 잠긴 항목은 프로젝트가 못 바꾼다."""
    spec = SPECS[key]
    if spec.scope == "user":
        if user is not None:
            got = (getattr(user, "settings", None) or {}).get(key)
            if got is not None:
                return got
        return spec.default
    if project is not None:
        if org is None:
            org = project.org
        if spec.overridable and key not in locked_keys(org):
            got = (project.settings or {}).get(key)
            if got is not None:
                return got
    if org is not None:
        got = (getattr(org, "settings", None) or {}).get(key)
        if got is not None:
            return got
    return spec.default


def display(key: str, value) -> str:
    """사람이 읽는 값. 화면과 이력이 같은 문구를 쓴다."""
    spec = SPECS[key]
    if spec.kind == "bool":
        return "켬" if value else "끔"
    if spec.kind == "choice":
        return dict(spec.choices).get(value, str(value))
    if spec.kind == "set":
        names = dict(spec.choices)
        return ", ".join(names.get(v, v) for v in value) or "없음"
    if spec.kind == "int" and value == -1:
        return "서버 기본값"
    return str(value)


def enforced(org, project=None) -> list[dict]:
    """거버넌스 화면 상단 '설정에서 강제 중' 표. 기본값이 아닌 항목만."""
    rows = []
    for spec in SPECS.values():
        if spec.scope != "org":
            continue
        value = effective(spec.key, org=org, project=project)
        if _same_as_default(spec, value):
            continue
        where = "조직"
        if project is not None and spec.overridable and spec.key in (project.settings or {}):
            where = "프로젝트"
        rows.append(
            {
                "key": spec.key,
                "label": spec.label,
                "value": display(spec.key, value),
                "where": where,
            }
        )
    return rows
