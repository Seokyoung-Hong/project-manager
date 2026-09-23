from datetime import date, datetime
from typing import Annotated, Literal

from ninja import Schema
from pydantic import Field

Status = Literal["todo", "doing", "paused", "blocked", "review", "done", "cancelled"]
Priority = Annotated[int, Field(ge=1, le=10)]
ProjectStatus = Literal[
    "preparing", "on_hold", "waiting", "active", "paused", "done", "stopped", "eol"
]


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
    status: Status
    priority: int
    due_date: date | None
    stop_reason: str
    # 막힘·검토 에스컬레이션이 경과일을 재는 기준.
    stopped_at: datetime | None = None
    updated_at: datetime | None = None
    next_action: str
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
    purpose: str
    member_count: int


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


class ProjectPatchIn(Schema):
    version: int
    name: str | None = None
    purpose: str | None = None
    owner_ids: list[int] | None = None
    team_ids: list[int] | None = None
    status: ProjectStatus | None = None


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


class ProjectDiscordChannelIn(Schema):
    channel_id: str = ""
