"""설정 레지스트리. IMPL-PLAN-4 §6.1.

모든 설정의 키·형·기본값·범위·층·편집 가능 여부가 이 파일의 표 하나에 있다.
화면·API·MCP·검증이 전부 이 표를 읽는다. **이 파일 밖에서 settings JSON을 직접 읽지 않는다.**

세 층은 개인 > 프로젝트 > 조직 > 기본값 순으로 가까운 값이 이긴다. 단 규칙(`task.*`·`project.*`·
`org.*`·`ai.*`)은 개인이 풀 수 없고, 조직이 `_locked`로 잠근 항목은 프로젝트가 덮어쓸 수 없다.
기본값은 전부 "이 라운드 전의 동작"이다 — 설정을 건드리지 않은 조직은 달라지는 것이 없다.
"""

import ipaddress
from dataclasses import dataclass
from urllib.parse import urlsplit

from common.errors import ServiceError

LOCKED = "_locked"  # 설정 JSON 안의 예약 키. 레지스트리에 없는 키 중 유일하게 허용된다.


@dataclass(frozen=True)
class Spec:
    key: str
    kind: str  # bool | int | choice | set | text | secret
    default: object
    scope: str  # org | user
    overridable: bool = False  # 조직 항목을 프로젝트가 덮어쓸 수 있는가
    group: str = ""
    label: str = ""
    help: str = ""
    choices: tuple = ()
    lo: int = 0
    hi: int = 0  # text는 최대 글자 수
    ai_only: bool = False  # source == "mcp" 에만 적용
    hidden: bool = (
        False  # 아직 동작하지 않는 설정. 화면·API·MCP에 내지 않는다(저장된 값은 무시된다)
    )
    validate: object = None  # text 추가 검증. 값 → 오류 문구("" = 통과)

    @property
    def input_choices(self):
        """시각·요일의 숫자 매핑을 유지하면서 입력 화면에서는 의미를 보여 준다."""
        if self.key in ("notify.send_hour", "notify.weekly_hour", "user.notify_hour"):
            fallback = "조직 설정 따름" if self.scope == "user" else "서버 기본값"
            return [(-1, fallback)] + [(n, f"{n:02d}:00") for n in range(24)]
        if self.key == "notify.weekly_weekday":
            return [(-1, "서버 기본 요일")] + [
                (n, day + "요일") for n, day in enumerate("월화수목금토일")
            ]
        return []


ALARM_KINDS = (("d3", "3일 전"), ("d1", "하루 전"), ("d0", "당일"), ("overdue", "기한 초과"))
ALLOW_DENY = (("allow", "허용"), ("deny", "막기"))
LEVELS = (("member", "멤버 누구나"), ("owner", "프로젝트 관리자"), ("admin", "조직 관리자만"))

# 비밀값(kind="secret")은 org.settings에 Fernet 암호문("enc:" 접두)으로만 들어간다. 화면·API·이력·
# 내보내기에는 이 두 문구만 나간다. 평문은 secret_value()로 봇 API 한 곳에서만 꺼낸다.
SECRET_SET, SECRET_UNSET = "설정됨", "미설정"
_ENC = "enc:"
_PRIVATE_NETS = [ipaddress.ip_network(n) for n in ("10.0.0.0/8", "172.16.0.0/12", "192.168.0.0/16")]


def validate_stt_url(url: str) -> str:
    """로컬 전사 서버 주소(IMPL-PLAN-9 v2 §3.4). gateway가 core·내부 서비스로 오디오를 쏘지 못하게 한다.

    http(s)만. localhost·루프백·링크 로컬(169.254)·점 없는 호스트(compose 서비스 이름 web·db 등)는
    거부. http는 사설 대역(10/8·172.16/12·192.168/16) IP일 때만, 그 밖은 https.
    """
    if not url:
        return ""
    try:
        parts = urlsplit(url)
        host = (parts.hostname or "").lower()
        _ = parts.port  # 잘못된 포트는 여기서 ValueError
    except ValueError:
        return "주소 형식이 올바르지 않습니다."
    if parts.scheme not in ("http", "https") or not host:
        return "http:// 또는 https://로 시작하는 주소여야 합니다."
    try:
        ip = ipaddress.ip_address(host)
    except ValueError:
        ip = None
    if ip is None:
        if host == "localhost" or host.endswith(".localhost") or "." not in host:
            return "localhost나 내부 서비스 이름은 쓸 수 없습니다."
    elif ip.is_loopback or ip.is_link_local or ip.is_unspecified or ip.is_multicast:
        return "루프백·링크 로컬 주소는 쓸 수 없습니다."
    if parts.scheme == "http" and not (ip is not None and any(ip in n for n in _PRIVATE_NETS)):
        return (
            "http는 사설 대역(10.x·172.16~31.x·192.168.x) 주소에만 쓸 수 있습니다. "
            "그 밖은 https를 써 주세요."
        )
    return ""


def _check_assist_org_url(url: str) -> str:
    """조직 AI 주소 검사는 assist 관문이 한다(IMPL-PLAN-12 §11.1). assist가 이 모듈을 읽으므로 늦게 부른다."""
    from assist.net import check_org_url

    return check_org_url(url)


SPECS: dict[str, Spec] = {
    s.key: s
    for s in [
        # --- 4.1 태스크 규칙 ---
        Spec(
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
        Spec(
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
        Spec(
            "task.require_done_when",
            "bool",
            False,
            "org",
            True,
            "task",
            "완료 조건 필수",
            "켜면 완료 조건을 입력해야 태스크를 만들 수 있습니다.",
        ),
        Spec(
            "task.due_required",
            "bool",
            False,
            "org",
            True,
            "task",
            "기한 필수",
            "켜면 기한을 입력해야 하며, 기한 미정 사유로 대신할 수 없습니다.",
        ),
        Spec(
            "task.default_due_days",
            "int",
            0,
            "org",
            True,
            "task",
            "기본 기한(영업일)",
            "생성 화면에서 오늘 이후 설정한 영업일 수만큼 지난 기한을 제안합니다. 영업일은 월~금이며 공휴일은 따로 제외하지 않습니다. 자동으로 채우지는 않습니다. 0이면 제안하지 않습니다.",
            lo=0,
            hi=30,
        ),
        Spec(
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
        Spec(
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
        Spec(
            "task.review_required",
            "bool",
            False,
            "org",
            True,
            "task",
            "검토 대기 필수",
            "켜면 검토 대기를 거쳐야 완료할 수 있습니다.",
        ),
        Spec(
            "task.self_review",
            "bool",
            True,
            "org",
            True,
            "task",
            "본인 검토 허용",
            "끄면 담당자 본인이 검토 대기에서 완료로 바꿀 수 없습니다.",
        ),
        Spec(
            "task.reopen_reason_required",
            "bool",
            False,
            "org",
            True,
            "task",
            "재개 사유 필수",
            "켜면 완료·취소한 태스크를 되돌릴 때 사유를 입력해야 합니다.",
        ),
        Spec(
            "task.cancel_reason_required", "bool", False, "org", True, "task", "취소 사유 필수", ""
        ),
        Spec(
            "task.assignee_change_reason",
            "bool",
            False,
            "org",
            True,
            "task",
            "담당자 변경 사유 필수",
            "켜면 담당자 변경 사유를 입력해야 하며, 사유는 이력에 남습니다.",
        ),
        Spec(
            "task.due_change_reason",
            "bool",
            False,
            "org",
            True,
            "task",
            "기한 변경 사유 필수",
            "켜면 기한 단축·삭제에도 사유를 입력해야 합니다. 기한 연장은 이 설정과 관계없이 사유를 받습니다.",
        ),
        Spec(
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
        Spec(
            "task.reject_reason_required",
            "bool",
            False,
            "org",
            True,
            "task",
            "반려 사유 필수",
            "켜면 검토 대기에서 시작 전·진행 중으로 되돌릴 때 사유를 입력해야 합니다.",
        ),
        # --- 4.2 프로젝트 규칙 ---
        Spec(
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
        Spec(
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
        Spec(
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
        Spec(
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
        Spec(
            "project.settings_by",
            "choice",
            "owner",
            "org",
            False,
            "project",
            "프로젝트 설정 편집",
            "저장소 규칙과 프로젝트 업무 규칙 문단을 포함합니다.",
            choices=(("owner", "프로젝트 관리자"), ("admin", "조직 관리자만")),
        ),
        Spec(
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
        Spec(
            "project.owner_required",
            "bool",
            False,
            "org",
            False,
            "project",
            "프로젝트 관리자 1명 이상",
            "켜면 관리자가 없는 프로젝트를 만들거나 마지막 관리자를 뺄 수 없습니다. 이미 관리자가 없는 프로젝트는 그대로 둡니다.",
        ),
        Spec(
            "project.default_view",
            "choice",
            "list",
            "org",
            True,
            "project",
            "프로젝트 첫 화면",
            "",
            choices=(("list", "목록"), ("board", "보드"), ("calendar", "달력")),
        ),
        Spec(
            "project.dev_tools",
            "bool",
            True,
            "org",
            True,
            "project",
            "개발 도구 사용",
            "끄면 GitHub·API 문서 탭과 태스크의 GitHub 블록을 숨깁니다. 저장소가 연결된 프로젝트는 끌 수 없습니다.",
        ),
        # --- 4.3 조직 운영 ---
        Spec(
            "org.invite_days", "int", 7, "org", False, "org", "초대 링크 만료(일)", "", lo=1, hi=90
        ),
        Spec(
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
        Spec(
            "org.tags_by",
            "choice",
            "admin",
            "org",
            False,
            "org",
            "보유 기술 태그 편집",
            "",
            choices=(("admin", "조직 관리자만"), ("self", "본인도 가능")),
        ),
        Spec(
            "org.team_join_self",
            "bool",
            False,
            "org",
            False,
            "org",
            "팀 자율 참여",
            "켜면 멤버가 스스로 팀에 들어가고 나갈 수 있습니다.",
        ),
        Spec(
            "org.attachment_quota_mb",
            "int",
            2048,
            "org",
            False,
            "org",
            "첨부 파일 용량(MB)",
            "조직 전체 첨부 파일의 합계 상한입니다. 0이면 올리기를 막습니다.",
            lo=0,
            hi=102400,
        ),
        # --- 4.4 AI 정책 (source == "mcp" 에만) ---
        Spec(
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
        Spec(
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
        Spec(
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
        Spec(
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
        Spec(
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
        Spec(
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
        Spec(
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
        Spec(
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
        Spec(
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
        Spec(
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
        Spec(
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
        Spec(
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
        Spec(
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
        Spec(
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
        Spec(
            "ai.create_request",
            "choice",
            "allow",
            "org",
            False,
            "ai",
            "요청 보내기·취소",
            "",
            choices=ALLOW_DENY,
            ai_only=True,
        ),
        Spec(
            "ai.answer_request",
            "choice",
            "deny",
            "org",
            False,
            "ai",
            "요청 수락·거절·완료",
            "수락은 사람의 약속이고 태스크·담당이 바뀌므로 기본값이 막기입니다.",
            choices=ALLOW_DENY,
            ai_only=True,
        ),
        # --- 4.5 알림 ---
        Spec(
            "notify.deadline_kinds",
            "set",
            ("d3", "d1", "d0", "overdue"),
            "org",
            False,
            "notify",
            "보내는 기한 알림",
            "",
            choices=ALARM_KINDS,
        ),
        Spec(
            "notify.send_hour",
            "int",
            -1,
            "org",
            False,
            "notify",
            "기한 알림 시각",
            "0~23은 알림을 보낼 시각입니다. -1이면 서버에 설정된 기본 시각을 따릅니다.",
            lo=-1,
            hi=23,
        ),
        Spec(
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
        Spec(
            "notify.quiet_weekend",
            "bool",
            False,
            "org",
            False,
            "notify",
            "주말에는 보내지 않기",
            "켜면 토·일에는 기한 DM을 보내지 않습니다.",
        ),
        Spec("notify.weekly_enabled", "bool", True, "org", False, "notify", "주간 보고", ""),
        Spec(
            "notify.weekly_weekday",
            "int",
            -1,
            "org",
            False,
            "notify",
            "주간 보고 요일",
            "0=월요일, 1=화요일, 2=수요일, 3=목요일, 4=금요일, 5=토요일, 6=일요일입니다. -1이면 서버 기본 요일을 따릅니다.",
            lo=-1,
            hi=6,
        ),
        Spec(
            "notify.weekly_hour",
            "int",
            -1,
            "org",
            False,
            "notify",
            "주간 보고 시각",
            "0~23은 보고를 보낼 시각입니다. -1이면 서버 기본 시각을 따릅니다.",
            lo=-1,
            hi=23,
        ),
        Spec(
            "notify.blocked_escalate_days",
            "int",
            0,
            "org",
            True,
            "notify",
            "막힘 관리자 알림(일)",
            "막힘이 N일을 넘으면 프로젝트 관리자에게 DM을 보냅니다. 0이면 보내지 않습니다.",
            lo=0,
            hi=14,
        ),
        Spec(
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
        Spec(
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
                # "milestone_due"(마일스톤 임박)는 봇이 아직 보내지 못해 선택지에서 뺐다.
                # 마일스톤 목록 조회가 생기면 되살린다(channels_post.py 참고).
            ),
        ),
        Spec(
            "notify.team_channel_weekly",
            "bool",
            False,
            "org",
            False,
            "notify",
            "팀 채널 주간 보고",
            "켜면 조직 채널 외에 팀 채널에도 그 팀 담당 프로젝트만 추려 보냅니다.",
            hidden=True,  # 봇이 아직 팀 채널로 보내지 않는다(weekly.py 참고). 구현되면 푼다
        ),
        Spec(
            "notify.github_channel_events",
            "set",
            (),
            "org",
            True,
            "notify",
            "GitHub 사건 채널 게시",
            "채널이 연결된 프로젝트만 해당합니다. 멘션은 넣지 않습니다.",
            choices=(
                ("pr_opened", "PR 열림"),
                ("pr_merged", "PR 병합"),
                ("pr_changes", "PR 변경 요청"),
                ("ci_failed", "CI 실패"),
                ("issue_imported", "이슈 자동 가져옴"),
                ("release", "릴리스 발행"),
                ("reopened", "PR·이슈 재개로 새 태스크"),
            ),
        ),
        Spec(
            "notify.github_dm",
            "bool",
            True,
            "org",
            True,
            "notify",
            "GitHub 개인 DM",
            "리뷰 요청은 검토자에게, 변경 요청·CI 실패·재개는 담당자에게 DM을 보냅니다. "
            "개인 설정 '개인 DM 받기'를 끈 사람에게는 가지 않습니다.",
        ),
        # --- 회의 녹음 (IMPL-PLAN-9) ---
        Spec(
            "meeting.recording_enabled",
            "bool",
            False,
            "org",
            True,
            "meeting",
            "회의 녹음",
            "켜면 Discord에서 /회의시작으로 회의를 녹음해 전사문으로 회의록 초안을 만들 수 있습니다.",
        ),
        Spec(
            "meeting.audio_keep_days",
            "int",
            7,
            "org",
            False,
            "meeting",
            "오디오 보관(일)",
            "녹음 오디오를 보관하는 기간입니다. 0이면 전사가 끝나는 즉시 지웁니다. "
            "백업에는 넣지 않습니다.",
            lo=0,
            hi=30,
        ),
        Spec(
            "meeting.max_minutes",
            "int",
            180,
            "org",
            True,
            "meeting",
            "최대 녹음 길이(분)",
            "이 길이를 넘으면 녹음을 자동으로 마칩니다.",
            lo=10,
            hi=360,
        ),
        Spec(
            "meeting.leave_grace_s",
            "int",
            10,
            "org",
            False,
            "meeting",
            "진행자 퇴장 유예(초)",
            "회의 진행자가 음성 채널을 떠난 뒤 이 시간 안에 돌아오지 않으면 녹음을 마칩니다. "
            "순간 끊김에 대비한 값입니다.",
            lo=0,
            hi=120,
        ),
        Spec(
            "meeting.default_visibility",
            "choice",
            "project",
            "org",
            False,
            "meeting",
            "확정 시 기본 공개 범위",
            "회의록을 확정할 때 처음 선택되어 있는 공개 범위입니다.",
            choices=(("project", "프로젝트"), ("team", "팀"), ("org", "조직 전체")),
        ),
        # 덮어쓰지 않고 합친다(프로젝트 → 조직 순, notes.services.glossary_terms).
        # COPY:setting_glossary_label · COPY:setting_glossary_help (docs/drafts/glossary-copy.md)
        Spec(
            "meeting.glossary",
            "text",
            "",
            "org",
            True,
            "meeting",
            "전사 용어집",
            "전사 서버에 미리 알려 줄 이름과 용어입니다. 쉼표나 줄바꿈으로 구분해 주세요. "
            "조직과 프로젝트의 용어는 합쳐서 사용하며 프로젝트 용어가 먼저 들어갑니다. "
            "참여자·구성원 이름 다음에, 자동으로 찾은 용어보다 먼저 들어갑니다. 한도를 넘는 용어는 제외됩니다.",
            hi=1000,
        ),
        Spec(
            "meeting.stt_url",
            "text",
            "",
            "org",
            False,
            "meeting",
            "로컬 전사 서버 주소",
            "OpenAI 호환 전사 서버 주소입니다(예: http://172.30.1.50:8000). 주소가 없으면 조직의 OpenAI 키로 전사하는 방식이며, "
            "키도 없으면 녹음만 하는 방식입니다. http를 사용할 수 있는 주소는 사설 대역뿐입니다.",
            hi=200,
            validate=validate_stt_url,
        ),
        Spec(
            "meeting.stt_model",
            "text",
            "",
            "org",
            False,
            "meeting",
            "로컬 전사 모델",
            "로컬 서버에 보낼 모델 이름입니다. 비우면 whisper-1로 보냅니다.",
            hi=200,
        ),
        Spec(
            "meeting.stt_timeout_s",
            "int",
            120,
            "org",
            False,
            "meeting",
            "전사 응답 대기(초)",
            "구간 하나의 응답을 기다리는 최대 시간입니다.",
            lo=10,
            hi=600,
        ),
        Spec(
            "meeting.stt_api_key",
            "secret",
            SECRET_UNSET,
            "org",
            False,
            "meeting",
            "로컬 전사 서버 키",
            "로컬 서버의 Bearer 키입니다. 암호화해 저장하며 화면에는 설정 여부만 보입니다.",
        ),
        Spec(
            "meeting.openai_api_key",
            "secret",
            SECRET_UNSET,
            "org",
            False,
            "meeting",
            "OpenAI 키",
            "로컬 전사 서버가 없거나 연결되지 않을 때 OpenAI Whisper로 전사하는 데 사용하는 키입니다. 서버 주소와 키가 모두 없으면 "
            "녹음만 하는 방식입니다. 녹음 파일은 회의록 화면에서 내려받아 직접 전사해 주세요. 키는 암호화해 저장하는 값이며, "
            "화면에 표시되는 정보는 설정 여부뿐입니다.",
        ),
        # 내 PC 전사(IMPL-PLAN-11-local-stt-link §5). 문구는 임시(docs/drafts/local-stt-link-copy.md).
        Spec(
            "meeting.member_pc",
            "bool",
            True,
            "org",
            False,
            "meeting",
            "멤버 PC로 전사",
            "켜면 구성원이 자기 PC에 연결한 전사 서버로 이 조직 녹음을 전사할 수 있습니다. 끄면 대기 중인 PC 전사는 취소됩니다.",
        ),
        Spec(
            "meeting.transcribe_level",
            "choice",
            "member",
            "org",
            False,
            "meeting",
            "조직 전사 수단을 쓸 수 있는 사람",
            "조직 전사 서버와 조직 OpenAI 키로 전사를 시작할 수 있는 사람입니다. 멤버는 녹음마다 한 번만 쓸 수 있습니다.",
            choices=(("member", "멤버 누구나"), ("admin", "조직 관리자만")),
        ),
        # --- AI 자동완성(IMPL-PLAN-12 §3.4). 문구는 임시(docs/drafts/ai-assist-copy.md) ---
        # assist.enabled 기본 켬은 "기본값 = 이 라운드 전의 동작" 원칙의 예외다(사용자 결정, 계획서 §15).
        # 켜져 있어도 조직 AI 주소나 개인 AI를 누군가 등록해야 실제 전송이 시작된다.
        Spec(
            "assist.enabled",
            "bool",
            True,
            "org",
            False,
            "assist",
            "AI 자동완성 사용",  # COPY:assist_enabled_label
            "끄면 이 조직의 내용으로 조직 AI와 개인 AI를 모두 사용할 수 없으며, AI 자동완성과 태스크 후보 뽑기 버튼이 표시되지 않습니다.",  # COPY:assist_enabled_help
        ),
        Spec(
            "assist.org_url",
            "text",
            "",
            "org",
            False,
            "assist",
            "조직 AI 주소",  # COPY:assist_org_url_label
            "OpenAI 호환 AI 서버 주소입니다. 예: https://api.example.com/v1. 사설망 주소는 서비스 운영자의 허용 호스트 등록이 필요합니다.",  # COPY:assist_org_url_help
            hi=300,
            validate=_check_assist_org_url,
        ),
        Spec(
            "assist.org_model",
            "text",
            "",
            "org",
            False,
            "assist",
            "조직 AI 모델",  # COPY:assist_org_model_label
            "조직 AI 서버에서 사용할 모델 이름입니다.",  # COPY:assist_org_model_help
            hi=200,
        ),
        Spec(
            "assist.org_api_key",
            "secret",
            SECRET_UNSET,
            "org",
            False,
            "assist",
            "조직 AI 키",  # COPY:assist_org_api_key_label
            "키는 암호화하여 저장하며 화면에는 설정 여부만 표시됩니다.",  # COPY:assist_org_api_key_help
        ),
        Spec(
            "assist.org_level",
            "choice",
            "member",
            "org",
            False,
            "assist",
            "조직 AI 사용 권한",  # COPY:assist_org_level_label
            "",
            choices=(
                ("member", "구성원 누구나"),
                ("admin", "관리자만"),
            ),  # COPY:assist_org_level_choices
        ),
        Spec(
            "assist.org_daily_limit",
            "int",
            30,
            "org",
            False,
            "assist",
            "조직 AI 하루 한도(구성원 1명)",  # COPY:assist_org_daily_limit_label
            "구성원 1명이 하루에 조직 AI로 실행할 수 있는 작업 수입니다. 기본값은 30이며, 관리자는 한도에서 제외됩니다. 0이면 제한하지 않습니다.",  # COPY:assist_org_daily_limit_help
            lo=0,
            hi=1000,
        ),
        # --- 4.6 개인 설정 ---
        Spec(
            "user.notify_dm",
            "bool",
            True,
            "user",
            False,
            "user",
            "개인 DM 받기",
            "끄면 기한·막힘·검토 대기 관리자 알림·GitHub DM을 받지 않습니다. 채널 주간 보고는 그대로입니다.",
        ),
        Spec(
            "user.notify_kinds",
            "set",
            ("d3", "d1", "d0", "overdue"),
            "user",
            False,
            "user",
            "받을 기한 알림",
            "조직이 끈 종류는 켤 수 없습니다.",
            choices=ALARM_KINDS,
        ),
        Spec(
            "user.notify_hour",
            "int",
            -1,
            "user",
            False,
            "user",
            "내 기한 알림 시각",
            "0~23은 내 기한 알림 시각입니다. -1이면 조직 설정을 따릅니다.",
            lo=-1,
            hi=23,
        ),
        Spec(
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
        Spec(
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
        Spec(
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
        Spec(
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

# 덮어쓰지 않고 조직 값과 합치는 설정. 프로젝트 값은 조직 값이 아니라 기본값과 비교해 정규화한다
# (조직 값과 같다고 지우면 조직 값이 바뀔 때 프로젝트가 넣은 값이 사라진다).
MERGED_KEYS = ("meeting.glossary",)

# 전사 서버·모델 설정. 조직 설정 화면이 아니라 전사 메뉴에서 바꾼다(IMPL-PLAN-10-transcribe-menu).
STT_KEYS = (
    "meeting.stt_url",
    "meeting.stt_model",
    "meeting.stt_timeout_s",
    "meeting.stt_api_key",
    "meeting.openai_api_key",
    "meeting.member_pc",
    "meeting.transcribe_level",
)

GROUPS = [
    ("task", "태스크 규칙"),
    ("project", "프로젝트 권한"),
    ("org", "조직 운영"),
    ("ai", "AI 정책"),
    ("assist", "AI 자동완성"),  # COPY:assist_group
    ("notify", "알림"),
    ("meeting", "회의 녹음"),
    ("user", "내 설정"),
]


# 조직 설정 화면의 탭·섹션(IMPL-PLAN-14 §2·§3·§10.1 — 계약, 이름을 바꾸지 않는다).
# (탭 코드, 탭 라벨 COPY 키, [(섹션 코드, 섹션 라벨 COPY 키, 키들)]). org scope 77개가 정확히 한 번씩 든다
# (숨김 notify.team_channel_weekly 포함 — 자리만 예약, 저장 키는 tab_keys()가 거른다). 화면 id = settings-<탭>-<섹션>.
ORG_TABS: list[tuple[str, str, list[tuple[str, str, tuple[str, ...]]]]] = [
    ("me", "org_settings.tab.me", [
        ("name", "org_settings.section.me.name", ()),
        ("info", "org_settings.section.me.info", ()),
        ("links", "org_settings.section.me.links", ()),
    ]),
    ("members", "org_settings.tab.members", [
        ("list", "org_settings.section.members.list", ()),
        ("pending", "org_settings.section.members.pending", ()),
        ("invites", "org_settings.section.members.invites", ("org.invite_days", "org.invite_max_uses")),
        ("names", "org_settings.section.members.names", ()),
        ("fields", "org_settings.section.members.fields", ()),
        ("teams_tags", "org_settings.section.members.teams_tags", ("org.tags_by", "org.team_join_self")),
    ]),
    ("work", "org_settings.tab.work", [
        ("create", "org_settings.section.work.create", ("task.default_priority", "task.priority_cap", "task.require_done_when")),
        ("flow", "org_settings.section.work.flow", ("task.doing_limit", "task.doing_limit_mode", "task.review_required", "task.self_review")),
        ("reasons", "org_settings.section.work.reasons", ("task.reopen_reason_required", "task.cancel_reason_required", "task.assignee_change_reason", "task.due_change_reason", "task.reject_reason_required")),
        ("due", "org_settings.section.work.due", ("task.due_required", "task.default_due_days", "task.overdue_grace_days")),
        ("project_perm", "org_settings.section.work.project_perm", ("project.create_by", "project.edit_by", "project.status_by", "project.archive_by", "project.settings_by", "project.roadmap_by", "project.owner_required")),
        ("project_default", "org_settings.section.work.project_default", ("project.default_view", "project.dev_tools")),
    ]),
    ("notify", "org_settings.tab.notify", [
        ("deadline", "org_settings.section.notify.deadline", ("notify.deadline_kinds", "notify.send_hour", "notify.overdue_repeat", "notify.quiet_weekend")),
        ("nudge", "org_settings.section.notify.nudge", ("notify.blocked_escalate_days", "notify.review_nudge_days")),
        ("weekly", "org_settings.section.notify.weekly", ("notify.weekly_enabled", "notify.weekly_weekday", "notify.weekly_hour", "notify.team_channel_weekly")),
        ("channel", "org_settings.section.notify.channel", ("notify.project_channel_events",)),
        ("github", "org_settings.section.notify.github", ("notify.github_channel_events", "notify.github_dm")),
    ]),
    ("ai", "org_settings.tab.ai", [
        ("assist", "org_settings.section.ai.assist", ("assist.enabled", "assist.org_level")),
        ("org_ai", "org_settings.section.ai.org_ai", ("assist.org_url", "assist.org_model", "assist.org_api_key", "assist.org_daily_limit")),
        ("ai_write", "org_settings.section.ai.ai_write", ("ai.enabled",)),
        ("ai_task", "org_settings.section.ai.ai_task", ("ai.create_task", "ai.edit_text", "ai.record_work", "ai.change_assignee", "ai.change_due", "ai.change_priority", "ai.priority_cap", "ai.transition_open", "ai.close_task", "ai.reopen_task")),
        ("ai_org", "org_settings.section.ai.ai_org", ("ai.delete", "ai.manage_repo", "ai.manage_teams", "ai.create_request", "ai.answer_request")),
    ]),
    ("meeting", "org_settings.tab.meeting", [
        ("recording", "org_settings.section.meeting.recording", ("meeting.recording_enabled", "meeting.max_minutes", "meeting.leave_grace_s")),
        ("visibility", "org_settings.section.meeting.visibility", ("meeting.audio_keep_days", "meeting.default_visibility")),
        ("glossary", "org_settings.section.meeting.glossary", ("meeting.glossary",)),
        ("stt", "org_settings.section.meeting.stt", ("meeting.member_pc", "meeting.transcribe_level", "meeting.stt_url", "meeting.stt_model", "meeting.stt_timeout_s", "meeting.stt_api_key", "meeting.openai_api_key")),
    ]),
    ("integrations", "org_settings.tab.integrations", [
        ("github", "org_settings.section.integrations.github", ()),
        ("discord", "org_settings.section.integrations.discord", ()),
    ]),
    ("org", "org_settings.tab.org", [
        ("storage", "org_settings.section.org.storage", ("org.attachment_quota_mb",)),
        ("history", "org_settings.section.org.history", ()),
        ("danger", "org_settings.section.org.danger", ()),
    ]),
]  # fmt: skip
ADMIN_TABS = ("members", "work", "notify", "ai", "meeting", "integrations", "org")

# ORG_TABS 라벨의 임시 문구(최종은 docs/COPY-14.md, F 갈래). 화면은 COPY_DRAFT.get(키, 키)로 그린다.
COPY_DRAFT = {
    "org_settings.tab.me": "내 정보",
    "org_settings.tab.members": "구성원 관리",
    "org_settings.tab.work": "태스크·프로젝트",
    "org_settings.tab.notify": "알림",
    "org_settings.tab.ai": "AI",
    "org_settings.tab.meeting": "회의·전사",
    "org_settings.tab.integrations": "연동",
    "org_settings.tab.org": "조직 관리",
    "org_settings.section.me.name": "실명·조직 표시 이름",
    "org_settings.section.me.info": "구성원 정보",
    "org_settings.section.me.links": "다른 설정",
    "org_settings.section.members.list": "구성원 목록",
    "org_settings.section.members.pending": "가입 전 구성원",
    "org_settings.section.members.invites": "초대 링크·정책",
    "org_settings.section.members.names": "이름 표시 방식",
    "org_settings.section.members.fields": "요청할 정보 항목",
    "org_settings.section.members.teams_tags": "팀·기술 태그 정책",
    "org_settings.section.work.create": "생성 기본값",
    "org_settings.section.work.flow": "진행·검토",
    "org_settings.section.work.reasons": "변경 사유",
    "org_settings.section.work.due": "기한",
    "org_settings.section.work.project_perm": "프로젝트 권한",
    "org_settings.section.work.project_default": "프로젝트 기본값",
    "org_settings.section.notify.deadline": "기한 알림",
    "org_settings.section.notify.nudge": "막힘·검토 알림",
    "org_settings.section.notify.weekly": "주간 보고",
    "org_settings.section.notify.channel": "채널 게시",
    "org_settings.section.notify.github": "GitHub 알림",
    "org_settings.section.ai.assist": "AI 자동완성·이용 권한",
    "org_settings.section.ai.org_ai": "조직 AI 연결·한도",
    "org_settings.section.ai.ai_write": "외부 AI 쓰기 허용",
    "org_settings.section.ai.ai_task": "태스크 작업 권한",
    "org_settings.section.ai.ai_org": "조직·요청 관리 권한",
    "org_settings.section.meeting.recording": "녹음 운영",
    "org_settings.section.meeting.visibility": "공개·보관",
    "org_settings.section.meeting.glossary": "전사 용어",
    "org_settings.section.meeting.stt": "전사",
    "org_settings.section.integrations.github": "GitHub",
    "org_settings.section.integrations.discord": "Discord",
    "org_settings.section.org.storage": "저장 공간",
    "org_settings.section.org.history": "정책 변경 이력",
    "org_settings.section.org.danger": "위험 구역",
}


def tab_keys(tab: str, section: str | None = None) -> tuple[str, ...]:
    """그 탭(섹션)이 화면에 그리고 저장하는 키. 숨김 키는 뺀다(clean()이 거절하므로). 모르는 탭·섹션은 ()."""
    return tuple(
        k
        for code, _, sections in ORG_TABS
        if code == tab
        for sec, _, keys in sections
        if section in (None, sec)
        for k in keys
        if not SPECS[k].hidden
    )


def specs_for(scope: str) -> list[Spec]:
    """그 층에서 편집할 수 있는 항목. 화면과 API가 이 순서로 그린다."""
    shown = [s for s in SPECS.values() if not s.hidden]
    if scope == "project":
        return [s for s in shown if s.scope == "org" and s.overridable]
    return [s for s in shown if s.scope == scope]


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
        value = ("" if value is None else str(value)).strip()
        limit = spec.hi or 200
        if len(value) > limit:
            return None, f"{limit}자를 넘을 수 없습니다."
        err = spec.validate(value) if spec.validate else ""
        return (None, err) if err else (value, "")
    if spec.kind == "secret":
        # merge_secrets()를 거친 암호문만 저장된다. 평문이 여기까지 오면 저장하지 않는다.
        if isinstance(value, str) and value.startswith(_ENC):
            return value, ""
        return None, "저장할 수 없는 값입니다."
    return None, "알 수 없는 형입니다."


def merge_secrets(data: dict, old: dict) -> dict:
    """설정 PUT은 통째 교체지만 비밀값은 다시 보여 줄 수 없으므로 '안 보내면 유지'다.

    없음·None·""·"설정됨"/"미설정"(GET을 그대로 되돌린 값)은 기존 값 유지, False는 지우기,
    이미 암호문이면 그대로(AI 요청을 허용할 때), 그 밖의 문자열은 새 값으로 보고 암호화한다.
    """
    from github.crypto import encrypt

    out = dict(data or {})
    for spec in SPECS.values():
        if spec.kind != "secret":
            continue
        key, raw = spec.key, out.get(spec.key)
        if raw is False:
            out.pop(key, None)
        elif raw in (None, "", SECRET_SET, SECRET_UNSET):
            if (old or {}).get(key):
                out[key] = old[key]
            else:
                out.pop(key, None)
        elif isinstance(raw, str) and not raw.startswith(_ENC):
            try:
                out[key] = _ENC + encrypt(raw.strip())
            except ValueError:
                raise ServiceError(
                    {
                        key: "서버의 암호화 설정이 없어 키를 저장할 수 없습니다. 서비스 운영자에게 문의해 주세요."
                    }
                ) from None
    return out


def secret_value(key: str, org) -> str:
    """비밀값 평문. 봇 API(BotTokenAuth)와 조직 설정 [연결 시험](요청 헤더에만)에서 부른다. 복호화 실패면 빈 문자열."""
    from github.crypto import decrypt

    raw = (getattr(org, "settings", None) or {}).get(key) or ""
    return decrypt(raw[len(_ENC) :]) if raw.startswith(_ENC) else ""


def _same_as_default(spec: Spec, value) -> bool:
    if spec.kind == "set":
        return list(value) == list(spec.default)
    return value == spec.default


def clean(scope: str, data: dict, *, allow_locked: bool = False, org=None) -> dict:
    """알 수 없는 키·형·범위는 ServiceError. 기본값과 같은 값은 지운다(키 없음 = 기본값).

    프로젝트 층(org를 넘길 때)의 "기본값"은 레지스트리 기본값이 아니라 조직 값이다. 키가 없으면
    effective()가 조직 값을 쓰므로, 조직이 바꾼 값을 레지스트리 기본값으로 되돌리는 프로젝트 값은
    남겨야 한다(지우면 조직 값으로 돌아가 버린다).
    """
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
        if scope == "project" and org is not None and key not in MERGED_KEYS:
            base = effective(key, org=org)
            same = (list(value) == list(base)) if spec.kind == "set" else value == base
        else:
            same = _same_as_default(spec, value)
        if not same:
            out[key] = value
    if errors:
        raise ServiceError(errors)
    return out


def locked_keys(org) -> set:
    return set((getattr(org, "settings", None) or {}).get(LOCKED) or [])


def effective(key: str, *, org=None, project=None, user=None):
    """개인 > 프로젝트 > 조직 > 기본값. 규칙은 개인이 풀 수 없고, 잠긴 항목은 프로젝트가 못 바꾼다."""
    spec = SPECS[key]
    if spec.kind == "secret":
        # 암호문도 밖으로 내지 않는다. 평문은 secret_value().
        o = org if org is not None else getattr(project, "org", None)
        has = (getattr(o, "settings", None) or {}).get(key)
        return SECRET_SET if has else SECRET_UNSET
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


def project_value(key: str, project):
    """프로젝트 층에 저장한 값만(없거나 조직이 잠갔으면 None). 조직 값과 합치는 설정(meeting.glossary)용."""
    if key in locked_keys(project.org):
        return None
    return (project.settings or {}).get(key)


def display(key: str, value) -> str:
    """사람이 읽는 값. 화면과 이력이 같은 문구를 쓴다."""
    spec = SPECS[key]
    if spec.kind == "secret":
        return SECRET_UNSET if value in (None, "", SECRET_UNSET) else SECRET_SET
    if spec.kind == "text" and not value:
        return "없음"
    if spec.kind == "bool":
        return "켬" if value else "끔"
    if spec.kind == "choice":
        return dict(spec.choices).get(value, str(value))
    if spec.kind == "set":
        names = dict(spec.choices)
        return ", ".join(names.get(v, v) for v in value) or "없음"
    if spec.kind == "int" and value == -1:
        return "조직 설정 따름" if spec.scope == "user" else "서버 기본값"
    if spec.input_choices:
        return dict(spec.input_choices).get(value, str(value))
    if value == 0 and key in (
        "task.default_due_days",
        "notify.blocked_escalate_days",
        "notify.review_nudge_days",
    ):
        return "사용 안 함"
    if value == 0 and key in (
        "task.doing_limit",
        "task.priority_cap",
        "ai.priority_cap",
        "org.invite_max_uses",
    ):
        return "제한 없음"
    return str(value)


# 업무 규칙 화면(모든 구성원)에 서버 주소를 내지 않는다(IMPL-PLAN-14 §9.4). 키는 display()가 이미 가린다.
ENFORCED_SKIP = ("meeting.stt_url", "assist.org_url")


def enforced(org, project=None) -> list[dict]:
    """거버넌스 화면 상단 '설정에서 강제 중' 표. 기본값이 아닌 항목만."""
    rows = []
    for spec in SPECS.values():
        if spec.scope != "org" or spec.hidden or spec.key in ENFORCED_SKIP:
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
