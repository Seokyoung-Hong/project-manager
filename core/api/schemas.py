from datetime import date, datetime
from typing import Annotated, Literal

from ninja import Schema
from pydantic import Field

Status = Literal["todo", "doing", "paused", "blocked", "review", "done", "cancelled"]
Priority = Annotated[int, Field(ge=1, le=10)]
ProjectStatus = Literal[
    "preparing", "on_hold", "waiting", "active", "paused", "done", "stopped", "eol"
]
ProjectVisibility = Literal["org", "teams"]


class UserBrief(Schema):
    id: int
    display_name: str
    discord_user_id: str | None = None


class ProjectBrief(Schema):
    id: int
    name: str
    org_id: int
    # 프로젝트 채널 게시(IMPL-PLAN-4 §4.5)가 목적지를 여기서 읽는다.
    discord_channel_id: str = ""


class TaskBriefOut(Schema):
    id: int
    number: str
    title: str
    project: ProjectBrief
    assignee: UserBrief
    reviewer: UserBrief | None = None
    status: Status
    priority: int
    due_date: date | None
    stop_reason: str
    # 막힘·검토 에스컬레이션이 경과일을 재는 기준.
    stopped_at: datetime | None = None
    updated_at: datetime | None = None
    next_action: str
    is_template: bool = False
    parent_id: int | None = None
    url: str


class ChecklistItemOut(Schema):
    id: int
    text: str
    is_done: bool
    position: int


class ChecklistItemIn(Schema):
    text: str
    is_done: bool = False


class LinkOut(Schema):
    id: int
    title: str
    url: str
    kind: str


class DocBrief(Schema):
    id: int
    title: str


class TaskOut(TaskBriefOut):
    description: str
    done_when: str
    notes: str
    no_due_reason: str
    stopped_at: datetime | None
    completed_at: datetime | None
    version: int
    created_by: UserBrief
    created_at: datetime
    updated_at: datetime
    checklist: list[ChecklistItemOut]
    checklist_done: int
    checklist_total: int
    links: list[LinkOut]
    # 걸린 참고 문서. 본문은 /projects/{project_id}/docs/{id}에서 읽는다.
    docs: list[DocBrief]
    pending_assignee: UserBrief | None = None
    # 지정 검토자. 있으면 검토 대기 → 완료는 이 사람이나 프로젝트·조직 관리자만 한다.
    reviewer: UserBrief | None = None
    children_count: int = 0  # 이 태스크를 뿌리로 하는 회차·변형 수
    attachments: list[
        "AttachmentOut"
    ] = []  # 최신 버전만. 이전 버전은 /tasks/{id}/attachments?all=true


class TaskCreateIn(Schema):
    project_id: int
    title: str
    assignee_id: int | None = None
    description: str = ""
    done_when: str = ""
    next_action: str = ""
    priority: Priority | None = None  # 없으면 조직 설정의 기본 중요도
    due_date: date | None = None
    no_due_reason: str = ""
    checklist: list[ChecklistItemIn] | None = None


class TaskPatchIn(Schema):
    version: int
    title: str | None = None
    description: str | None = None
    done_when: str | None = None
    next_action: str | None = None
    notes: str | None = None
    assignee_id: int | None = None
    project_id: int | None = None
    priority: Priority | None = None
    due_date: date | None = None
    no_due_reason: str | None = None
    stop_reason: str | None = None
    checklist: list[ChecklistItemIn] | None = None
    reviewer_id: int | None = None  # null이면 검토자 해제
    is_template: bool | None = None


class TaskDuplicateIn(Schema):
    """복제·회차 만들기. 비운 값은 원본을 따른다(기한은 따르지 않는다)."""

    title: str | None = None
    due_date: date | None = None
    no_due_reason: str = ""
    assignee_id: int | None = None


class TransitionIn(Schema):
    status: Status
    reason: str = ""
    version: int


class ExtendIn(Schema):
    due_date: date
    reason: str
    version: int


class ChangeLogOut(Schema):
    id: int
    field: str
    old_value: str
    new_value: str
    note: str
    actor: UserBrief
    source: str
    created_at: datetime


class TaskListOut(Schema):
    items: list[TaskBriefOut]
    total: int
    limit: int
    offset: int


class ProjectStats(Schema):
    total: int
    open: int
    overdue: int
    review: int
    blocked: int
    done: int


class TeamOut(Schema):  # 새 의미: 조직 안의 사람 묶음
    id: int
    name: str
    purpose: str | None  # 볼 수 없는 비공개 팀이면 null
    member_count: int | None  # 볼 수 없는 비공개 팀이면 null
    dev_tools: bool = True
    is_private: bool = False


class ProjectOut(Schema):
    id: int
    org_id: int
    name: str
    purpose: str
    discord_channel_id: str = ""
    owners: list[UserBrief]
    teams: list[TeamOut]
    status: ProjectStatus
    status_label: str
    is_archived: bool
    dev_tools: bool  # false면 비개발 프로젝트 — GitHub·브랜치·PR 안내를 건너뛴다
    visibility: ProjectVisibility = "org"  # teams면 관리자·프로젝트 관리자·담당 팀 멤버만 본다
    version: int
    stats: ProjectStats
    links: list[LinkOut]
    url: str


class ProjectCreateIn(Schema):
    org_id: int
    name: str
    purpose: str = ""
    owner_ids: list[int] = []
    team_ids: list[int] = []
    status: ProjectStatus = "preparing"
    dev_tools: bool | None = None  # 비우면 조직 기본값(project.dev_tools)
    visibility: ProjectVisibility = "org"  # teams는 조직 관리자만


class ProjectPatchIn(Schema):
    version: int
    name: str | None = None
    purpose: str | None = None
    owner_ids: list[int] | None = None
    team_ids: list[int] | None = None
    status: ProjectStatus | None = None
    visibility: ProjectVisibility | None = None  # 조직 관리자만


class OrgBrief(Schema):
    id: int
    name: str
    purpose: str
    role: str


class MeOut(Schema):
    id: int
    username: str
    display_name: str
    discord_user_id: str | None
    auto_pull_days: int
    token_scope: str = "write"
    orgs: list[OrgBrief]


class OrgOut(Schema):  # 기존 TeamOut
    id: int
    name: str
    purpose: str
    role: str
    discord_guild_id: str | None = None
    projects: list[ProjectOut]
    teams: list[TeamOut]


class InviteIn(Schema):
    days: int = 7


class InviteOut(Schema):
    id: int
    url: str
    expires_at: datetime
    use_count: int
    revoked_at: datetime | None


class TodayItemOut(TaskBriefOut):
    auto_pulled: bool


class TodayOut(Schema):
    date: date
    items: list[TodayItemOut]
    focus: TaskBriefOut | None
    done_today: list[TaskBriefOut]
    auto_pull_days: int
    counts: dict


class TodayAddIn(Schema):
    task_id: int


class TodayOrderIn(Schema):
    task_ids: list[int]


class TodaySettingsIn(Schema):
    auto_pull_days: int


class StatusIn(Schema):
    ok: bool
    detail: dict = {}


# ---------- Discord 봇 ----------
# discord_user_id는 게이트웨이가 채운 author.id다. 클라이언트가 고르는 값이 아니다.


class DiscordLinkIn(Schema):
    code: str
    discord_user_id: str


class RepoConnectIn(Schema):
    url: str


class DiscordActorIn(Schema):
    discord_user_id: str


class DiscordOrgChannelIn(Schema):
    """길드 안에서 `/알림채널`을 실행했을 때. 길드에 붙은 조직의 알림 채널을 정한다."""

    discord_user_id: str
    guild_id: str
    channel_id: str


class DiscordExtendIn(Schema):
    discord_user_id: str
    due_date: date
    reason: str = ""


class ApiSpecIn(Schema):
    spec: dict
    source_url: str = ""


class ErrorOut(Schema):
    detail: dict | str


class ConflictOut(Schema):
    detail: str
    latest: dict


class GovernanceOut(Schema):
    text: str
    is_default: bool  # True면 조직이 아직 고치지 않은 기본안


class GovernanceIn(Schema):
    text: str


class TeamCreateIn(Schema):
    name: str
    purpose: str = ""
    dev_tools: bool = True
    is_private: bool = False


class TeamMemberIn(Schema):
    user_id: int


# ---------- Discord 슬래시 명령 (IMPL-PLAN-3) ----------


class DiscordTaskCreateIn(Schema):
    discord_user_id: str
    project_id: int
    title: str
    due_date: date | None = None
    no_due_reason: str = ""
    priority: int | None = None  # 없으면 조직 설정의 기본 중요도
    assignee_id: int | None = None


class DiscordTaskUpdateIn(Schema):
    discord_user_id: str
    title: str | None = None
    priority: int | None = None
    due_date: date | None = None
    assignee_id: int | None = None
    next_action: str | None = None


class DiscordNoteIn(Schema):
    discord_user_id: str
    text: str


class DiscordStatusIn(Schema):
    discord_user_id: str
    status: str
    reason: str = ""


class DiscordChannelIn(Schema):
    discord_user_id: str
    channel_id: str = ""


class DiscordViewer(Schema):
    id: str
    name: str = ""


class DiscordChannelCheckIn(Schema):
    """채널 연결 전 확인. viewers=None이면 봇이 채널을 보는 사람을 알 수 없다(멤버 인텐트 꺼짐)."""

    discord_user_id: str
    guild_id: str  # 채널이 속한 서버. 조직의 연결 서버와 같아야 한다
    kind: str  # team | project
    target_id: int
    channel_id: str
    viewers: list[DiscordViewer] | None = None
    allow_outsiders: bool = False
    managed: bool | None = None
    created: bool = False  # 봇이 방금 비공개로 만든 채널


class DiscordAlertChannelIn(Schema):
    channel_id: str
    outsiders: list[DiscordViewer] = []
    missing: list[DiscordViewer] | None = None


class DiscordAlertsIn(Schema):
    guild_id: str
    channels: list[DiscordAlertChannelIn]


class DiscordGuildReportIn(Schema):
    guild_id: str
    permissions: int | None = None
    watching: bool = False
    intent_denied: bool = False  # 포털에서 멤버 인텐트가 꺼져 인텐트 없이 접속했다


class DiscordMemberPermissionsIn(Schema):
    """Discord를 연결한 PM 사용자들의 서버 권한 비트. 웹 관리 동작의 판정 근거다."""

    guild_id: str
    members: list[dict]  # {"discord_user_id": str, "permissions": int}


class ProjectDiscordChannelIn(Schema):
    channel_id: str = ""


class DiscordRequestIn(Schema):
    """`/요청`. 팀·사람을 안 고르면 명령을 친 채널에 연결된 팀으로 보낸다."""

    discord_user_id: str
    title: str
    body: str = ""
    kind: str = "work"  # work | general
    channel_id: str = ""
    team_id: int | None = None
    to_user_id: int | None = None
    due_date: date | None = None  # 희망 기한(/요청 기한)


class DiscordRequestAnswerIn(Schema):
    discord_user_id: str
    note: str = ""
    project_id: int | None = None
    assignee_id: int | None = None
    due_date: date | None = None


class DiscordNoticeAckIn(Schema):
    ids: list[int]


class AttachmentOut(Schema):
    id: int
    name: str
    size: int
    kind: str  # file | out(산출물) | proof(증빙)
    content_type: str
    version: int
    replaces_id: int | None = None
    note: str
    url: str  # GET 하면 파일(토큰 인증)
    created_by: UserBrief
    created_at: datetime
