import ipaddress
import json
import socket
from datetime import date
from urllib.error import URLError
from urllib.parse import urlparse
from urllib.request import HTTPRedirectHandler, Request, build_opener

from django.db import transaction
from django.db.models import Count, Exists, F, OuterRef, Q
from django.utils import timezone

from common.dates import fmt_md, overdue_q, today_kst
from common.errors import ConflictError, ServiceError
from orgs.services import (
    ai_denied,
    is_admin,
    is_member,
    orgs_of,
    require_admin,
    require_ai_enabled,
)
from orgs.settings import SPECS, clean, display, effective, locked_keys

from .models import ApiSpec, Milestone, Project, ProjectDependency

EDITABLE = {"name", "purpose", "owners", "status", "teams"}

SPEC_MAX = 5 * 1024 * 1024
SPEC_TIMEOUT = 10
METHOD_COLOR = {
    "get": "#1F6F82",
    "post": "#12793F",
    "patch": "#A85B00",
    "put": "#2F6FBF",
    "delete": "#C92A37",
}


def _log(project, field, old, new, actor, source, token=None, note=""):
    from tasks.models import ChangeLog

    ChangeLog.objects.create(
        target_type="project",
        target_id=project.pk,
        field=field,
        old_value=_s(old),
        new_value=_s(new),
        note=note[:200],
        actor=actor,
        source=source,
        token=token,
    )


def _s(v) -> str:
    if v is None:
        return ""
    if hasattr(v, "pk"):
        return str(v.pk)
    return str(v)


def _ids(users) -> str:
    """관리자 목록을 이력에 남길 때 쓰는 문자열: '1,4'."""
    return ",".join(str(pk) for pk in sorted(u.pk for u in users))


def is_owner(user, project) -> bool:
    return project.owners.filter(pk=user.pk).exists()


def visible_projects(user, org=None):
    """user가 볼 수 있는 프로젝트. 보관 여부는 거르지 않는다(호출자가 거른다).
    Exists 서브쿼리로 쓴다 — M2M 조인 + distinct는 annotate·count와 어긋난다.

    공개 범위가 "teams"면 조직 관리자·프로젝트 관리자·담당 팀 멤버만 본다(IMPL-PLAN-7 F).
    """
    from orgs.models import OrgMembership, TeamMembership

    if not getattr(user, "is_authenticated", False):
        return Project.objects.none()
    qs = Project.objects.filter(org__in=orgs_of(user))
    if org is not None:
        qs = qs.filter(org=org)
    admin = OrgMembership.objects.filter(user=user, role="admin", org_id=OuterRef("org_id"))
    owner = Project.owners.through.objects.filter(project_id=OuterRef("pk"), user_id=user.pk)
    member = TeamMembership.objects.filter(user=user, team__projects=OuterRef("pk"))
    return qs.filter(Q(visibility="org") | Exists(admin) | Exists(owner) | Exists(member))


def can_view_project(user, project) -> bool:
    """이 사람이 프로젝트(와 그 태스크·문서·첨부)를 볼 수 있는가. 접근 검사는 여기 한 곳이다."""
    return visible_projects(user, project.org).filter(pk=project.pk).exists()


@transaction.atomic
def set_visibility(project, visibility: str, *, actor, source="web", token=None) -> Project:
    """공개 범위 바꾸기. 조직 관리자만."""
    require_admin(actor, project.org)
    require_ai_enabled(project.org, source, "공개 범위 바꾸기")
    if visibility not in dict(Project.VISIBILITIES):
        raise ServiceError({"visibility": "알 수 없는 공개 범위입니다."})
    if visibility == project.visibility:
        return project
    old = project.visibility
    Project.objects.filter(pk=project.pk).update(
        visibility=visibility, version=F("version") + 1, updated_at=timezone.now()
    )
    project.refresh_from_db()
    _log(project, "visibility", old, visibility, actor, source, token)
    return project


def require_level(actor, project, level: str, key: str):
    """level: member|owner|admin. 부족하면 ServiceError({key: ...}).

    조직 관리자는 항상 통과한다. member는 이미 다른 곳에서 멤버 여부를 검사하므로
    여기서는 더 볼 것이 없다.
    """
    if is_admin(actor, project.org):
        return
    if level == "admin":
        raise ServiceError({key: "이 작업은 조직 관리자만 할 수 있습니다."})
    if level == "owner" and not is_owner(actor, project):
        raise ServiceError({key: "이 작업은 프로젝트 관리자만 할 수 있습니다."})


def _check_ai_delete(org, source: str):
    """source가 mcp인데 AI 정책이 삭제를 막아 뒀으면 거부한다. 기본값이 막기다."""
    if source != "mcp":
        return
    if not effective("ai.enabled", org=org) or effective("ai.delete", org=org) == "deny":
        raise ServiceError({"ai": ai_denied("삭제")})


def _validate(org, name, owners, status):
    errors = {}
    if not name or not name.strip():
        errors["name"] = "프로젝트 이름을 입력하세요."
    for u in owners:
        if not u.is_active or not is_member(u, org):
            errors["owners"] = "관리자는 이 조직의 활성 멤버여야 합니다."
            break
    if status not in dict(Project.STATUSES):
        errors["status"] = "알 수 없는 상태입니다."
    if errors:
        raise ServiceError(errors)


@transaction.atomic
def create_project(
    *,
    org,
    name,
    actor,
    source="web",
    token=None,
    purpose="",
    owners=(),
    status="preparing",
    teams=(),
    dev_tools: bool | None = None,
    visibility: str = "org",
):
    if not is_member(actor, org):
        raise ServiceError({"org": "이 조직의 멤버가 아닙니다."})
    if visibility not in dict(Project.VISIBILITIES):
        raise ServiceError({"visibility": "알 수 없는 공개 범위입니다."})
    if visibility != "org":
        require_admin(actor, org)
    if effective("project.create_by", org=org) == "admin" and not is_admin(actor, org):
        raise ServiceError({"org": "프로젝트 생성은 조직 관리자만 할 수 있습니다."})
    owners = list(owners)
    teams = list(teams)
    require_ai_enabled(org, source, "프로젝트 만들기")
    if effective("project.owner_required", org=org) and not owners:
        raise ServiceError({"owners": "프로젝트 관리자가 최소 1명 있어야 합니다."})
    _validate(org, name, owners, status)
    for t in teams:
        if t.org_id != org.pk:
            raise ServiceError({"teams": "다른 조직의 팀은 담당으로 지정할 수 없습니다."})
    # 저장할 값과 같은 값으로 검사해야 한다. 자르기 전 값으로 검사하면
    # 앞 100자가 같은 두 이름이 둘 다 통과해 INSERT에서 unique 제약에 걸린다.
    name = name.strip()[:100]
    if Project.objects.filter(org=org, name=name).exists():
        raise ServiceError({"name": "같은 이름의 프로젝트가 이미 있습니다."})
    # dev_tools가 None이면 조직 기본값을 따른다. 조직 값과 다를 때만 프로젝트 설정에 남는다.
    proj_settings = {}
    if dev_tools is not None:
        proj_settings = clean("project", {"project.dev_tools": dev_tools}, org=org)
    project = Project.objects.create(
        org=org,
        name=name,
        purpose=purpose.strip()[:200],
        status=status,
        created_by=actor,
        settings=proj_settings,
        visibility=visibility,
    )
    project.owners.set(owners)
    project.teams.set(teams)
    _log(project, "created", "", project.name, actor, source, token)
    return project


@transaction.atomic
def update_project(
    project, changes: dict, *, actor, source="web", token=None, expected_version: int
):
    if not is_member(actor, project.org):
        raise ServiceError({"org": "이 조직의 멤버가 아닙니다."})
    require_ai_enabled(project.org, source, "프로젝트 고치기")
    unknown = set(changes) - EDITABLE
    if unknown:
        raise ServiceError({k: "수정할 수 없는 항목입니다." for k in sorted(unknown)})
    if "teams" in changes and project.visibility != "org":
        # 비공개 프로젝트의 담당 팀 = 보는 팀이라 담당 팀 편집이 곧 View 권한 편집이다.
        require_admin(actor, project.org)
    if {"name", "purpose", "teams"} & set(changes):
        require_level(actor, project, effective("project.edit_by", org=project.org), "name")
    if "owners" in changes:
        # 관리자 목록은 project.settings_by로 보호되는 모든 설정의 열쇠라 같은 등급(기본 owner)으로 지킨다.
        # 멤버 누구나 자기를 넣을 수 있으면 등급 설정 전체가 무의미해진다.
        require_level(actor, project, effective("project.settings_by", org=project.org), "owners")
    if "status" in changes:
        require_level(actor, project, effective("project.status_by", org=project.org), "status")
    old_owners = list(project.owners.all())
    new_owners = list(changes.get("owners", old_owners))
    if (
        "owners" in changes
        and not new_owners
        and effective("project.owner_required", org=project.org)
    ):
        raise ServiceError({"owners": "프로젝트 관리자가 최소 1명 있어야 합니다."})
    old_teams = list(project.teams.all())
    new_teams = list(changes.get("teams", old_teams))
    new = {f: changes.get(f, getattr(project, f)) for f in ("name", "purpose", "status")}
    # 새로 넣는 관리자만 검사한다. 이미 있던 사람이 조직에서 빠지면 그 프로젝트의
    # 이름·상태조차 못 고치게 되기 때문이다(태스크 담당자와 같은 이유).
    old_ids = {u.pk for u in old_owners}
    _validate(
        project.org, new["name"], [u for u in new_owners if u.pk not in old_ids], new["status"]
    )
    for t in new_teams:
        if t.org_id != project.org_id:
            raise ServiceError({"teams": "다른 조직의 팀은 담당으로 지정할 수 없습니다."})
    new["name"] = new["name"].strip()[:100]
    new["purpose"] = (new["purpose"] or "").strip()[:200]
    if (
        new["name"] != project.name
        and Project.objects.filter(org=project.org, name=new["name"]).exists()
    ):
        raise ServiceError({"name": "같은 이름의 프로젝트가 이미 있습니다."})
    old = {f: getattr(project, f) for f in ("name", "purpose", "status")}
    fields = {f: v for f, v in new.items() if v != old[f]}
    owners_changed = {u.pk for u in new_owners} != {u.pk for u in old_owners}
    teams_changed = {t.pk for t in new_teams} != {t.pk for t in old_teams}
    if not fields and not owners_changed and not teams_changed:
        return project
    updated = Project.objects.filter(pk=project.pk, version=expected_version).update(
        version=expected_version + 1, updated_at=timezone.now(), **fields
    )
    if updated != 1:
        project.refresh_from_db()
        raise ConflictError(project)
    if owners_changed:
        project.owners.set(new_owners)
        _log(project, "owners", _ids(old_owners), _ids(new_owners), actor, source, token)
    if teams_changed:
        project.teams.set(new_teams)
        _log(project, "teams", _ids(old_teams), _ids(new_teams), actor, source, token)
    project.refresh_from_db()
    if "status" in fields:
        _log(project, "status", old["status"], fields["status"], actor, source, token)
    return project


@transaction.atomic
def set_team_private_projects(team, project_ids, *, actor, source="web", token=None):
    """팀 화면에서 "이 팀이 볼 수 있는 비공개 프로젝트"를 정한다. 조직 관리자만.

    고른 비공개 프로젝트에는 이 팀을 담당 팀으로 넣고, 고르지 않은 것에서는 뺀다(update_project).
    """
    require_admin(actor, team.org)
    wanted = {int(pk) for pk in project_ids}
    for p in team.org.projects.filter(visibility="teams", is_archived=False):
        teams = list(p.teams.all())
        has = any(t.pk == team.pk for t in teams)
        if (p.pk in wanted) == has:
            continue
        new = [t for t in teams if t.pk != team.pk] + ([team] if p.pk in wanted else [])
        update_project(
            p, {"teams": new}, actor=actor, source=source, token=token, expected_version=p.version
        )


@transaction.atomic
def archive_project(project, *, actor, source="web", token=None, cancel_open=False):
    """미완료 태스크가 있으면 ServiceError. errors['tasks']에 'TASK-1, TASK-2' 형식.

    `cancel_open=True`면 그 미완료를 **취소로 닫고** 보관한다. 그만두기로 한 프로젝트에는
    손대지 않은 태스크가 남기 마련이라, 그것 때문에 숨길 수 없으면 보관이 쓸모없어진다.
    지우지 않고 취소로 닫는 이유는 이력이 남아야 하기 때문이다.
    """
    from tasks.models import Task
    from tasks.services import transition

    require_level(actor, project, effective("project.archive_by", org=project.org), "project")
    require_ai_enabled(project.org, source, "프로젝트 보관")
    # 템플릿은 진행하지 않으므로 보관을 막지 않고 그대로 남는다.
    open_tasks = list(
        Task.objects.filter(project=project, status__in=Task.OPEN, is_template=False).order_by("id")
    )
    if open_tasks and not cancel_open:
        raise ServiceError({"tasks": ", ".join(t.number for t in open_tasks)})
    for task in open_tasks:
        transition(
            task,
            "cancelled",
            actor=actor,
            source=source,
            token=token,
            reason="프로젝트를 보관하면서 함께 취소했습니다.",
            expected_version=task.version,
        )
    if project.is_archived:
        return project
    # 메모리의 version에 1을 더하면 그사이 오른 DB 값을 되돌려 오래된 PATCH가 통과한다.
    Project.objects.filter(pk=project.pk).update(
        is_archived=True, archived_at=timezone.now(), version=F("version") + 1
    )
    project.refresh_from_db()
    _log(project, "is_archived", False, True, actor, source, token)
    return project


@transaction.atomic
def restore_project(project, *, actor, source="web", token=None):
    require_level(actor, project, effective("project.archive_by", org=project.org), "project")
    require_ai_enabled(project.org, source, "프로젝트 복원")
    if not project.is_archived:
        return project
    Project.objects.filter(pk=project.pk).update(
        is_archived=False, archived_at=None, version=F("version") + 1
    )
    project.refresh_from_db()
    _log(project, "is_archived", True, False, actor, source, token)
    return project


@transaction.atomic
def delete_project(project, *, actor, source: str = "web"):
    """조직 관리자만. 보관된 프로젝트만 지울 수 있다. 태스크·마일스톤·문서가 함께 사라진다."""
    require_admin(actor, project.org)
    _check_ai_delete(project.org, source)
    if not project.is_archived:
        raise ServiceError({"project": "먼저 보관한 뒤에 지울 수 있습니다."})
    from tasks.models import ChangeLog, Task, TaskDecisionRecord

    if TaskDecisionRecord.objects.filter(task__project=project).exists():
        raise ServiceError(
            {
                "project": "의사결정 기록이 있는 프로젝트는 삭제할 수 없습니다. 보관 상태로 유지해 주세요."
            }
        )

    ChangeLog.objects.create(
        target_type="org",
        target_id=project.org_id,
        field="delete",
        old_value="",
        new_value=f"프로젝트 {project.name}({project.pk})",
        actor=actor,
        source=source,
    )
    from tasks.attachments import purge_files
    from tasks.models import Attachment

    purge_files(
        Attachment.objects.filter(Q(project=project) | Q(task__project=project))
    )  # 행은 CASCADE로 지워지고, 파일은 커밋 뒤에 지운다
    # Task.project는 PROTECT라 먼저 지운다. 체크리스트·오늘 목록·태스크 링크는 CASCADE.
    Task.objects.filter(project=project).delete()
    project.delete()  # 마일스톤·문서·API 스펙·의존성·저장소 연결은 CASCADE


def _display_or_default(key: str, value, org=None) -> str:
    """값이 없으면 따르는 값(조직 값, 없으면 기본값)을 보인다."""
    if value is None:
        value = effective(key, org=org) if org is not None else SPECS[key].default
    return display(key, value)


@transaction.atomic
def set_project_settings(project, data: dict, *, actor, source="web", token=None) -> Project:
    """저장소 규칙 등 프로젝트 설정을 통째로 교체한다. 조직이 잠근 키는 거부한다."""
    require_level(actor, project, effective("project.settings_by", org=project.org), "settings")
    require_ai_enabled(project.org, source, "프로젝트 설정 변경")
    cleaned = clean("project", data, org=project.org)
    if cleaned.get("project.dev_tools") is False and getattr(project, "repo", None) is not None:
        raise ServiceError(
            {
                "project.dev_tools": "저장소가 연결된 프로젝트는 개발 도구를 끌 수 없습니다. "
                "먼저 저장소 연결을 해제하세요."
            }
        )
    locked = locked_keys(project.org)
    bad = {k: "조직에서 잠근 설정입니다." for k in cleaned if k in locked}
    if bad:
        raise ServiceError(bad)
    old = project.settings or {}
    for key in sorted(set(old) | set(cleaned)):
        old_v, new_v = old.get(key), cleaned.get(key)
        if old_v == new_v:
            continue
        _log(
            project,
            key,
            _display_or_default(key, old_v, project.org),
            _display_or_default(key, new_v, project.org),
            actor,
            source,
            token,
        )
    project.settings = cleaned
    project.save(update_fields=["settings"])
    return project


def set_governance_extra(project, text: str, *, actor) -> Project:
    """프로젝트 전용 거버넌스 추가 문단. 프로젝트 설정 편집과 같은 등급 검사를 쓴다."""
    require_level(
        actor, project, effective("project.settings_by", org=project.org), "governance_extra"
    )
    text = (text or "").strip()
    if len(text) > 5000:
        raise ServiceError({"governance_extra": "5000자를 넘을 수 없습니다."})
    project.governance_extra = text
    project.save(update_fields=["governance_extra"])
    return project


def set_project_channel(
    project, channel_id: str, actor, *, checked: bool = False, managed=None, source: str = "web"
) -> Project:
    """봇이 만든 채널 id를 적는다. 빈 문자열이면 연결을 끊는다(Discord에서 지워졌을 때).

    새 채널로 바꾸는 것은 `orgs.channels.connect`(권한 밖 인원 확인)만 `checked=True`로 한다.
    """
    from orgs.channels import CHECK_REQUIRED, clear_alerts

    require_admin(actor, project.org)
    require_ai_enabled(project.org, source, "Discord 채널 연결")
    new = (channel_id or "").strip()[:32]
    fields = {"discord_channel_id": new}
    if new != project.discord_channel_id:
        if new and not checked:
            raise ServiceError({"channel_id": CHECK_REQUIRED})
        clear_alerts(project.discord_channel_id, "project", project.pk)
        fields["discord_channel_managed"] = bool(managed)
    elif managed is not None:
        fields["discord_channel_managed"] = managed
    Project.objects.filter(pk=project.pk).update(**fields)
    project.refresh_from_db()
    return project


def project_stats(project) -> dict:
    """{'total','open','overdue','review','blocked','done'}. total은 취소를 뺀 수.
    초과는 화면 배지와 같은 유예 기준(`overdue_before`)이다."""
    return project_stats_bulk([project])[project.pk]


def project_stats_bulk(projects) -> dict:
    """여러 프로젝트의 `project_stats`를 쿼리 한 번으로. {project_id: stats}.
    projects는 org를 함께 읽어 둔 목록이 좋다(아니면 org를 프로젝트마다 읽는다)."""
    from tasks.models import Task

    projects = list(projects)
    keys = ("total", "open", "overdue", "review", "blocked", "done")
    out = {p.pk: dict.fromkeys(keys, 0) for p in projects}
    if not projects:
        return out
    rows = (
        Task.objects.filter(project__in=list(out), is_template=False)
        .values("project_id")
        .order_by()
        .annotate(
            total=Count("id", filter=~Q(status="cancelled")),
            open=Count("id", filter=Q(status__in=Task.OPEN)),
            overdue=Count("id", filter=Q(status__in=Task.OPEN) & overdue_q(projects)),
            review=Count("id", filter=Q(status="review")),
            blocked=Count("id", filter=Q(status="blocked")),
            done=Count("id", filter=Q(status="done")),
        )
    )
    for r in rows:
        out[r.pop("project_id")] = r
    return out


# ---------- 로드맵: 마일스톤 · 프로젝트 의존성 ----------


def _add_month(d: date, n: int) -> date:
    m = d.month - 1 + n
    return date(d.year + m // 12, m % 12 + 1, 1)


def _validate_milestone(name, target_date, start_date, status) -> dict:
    errors = {}
    if not (name or "").strip():
        errors["name"] = "마일스톤 이름을 입력하세요."
    if target_date is None:
        errors["target_date"] = "목표일을 선택하세요."
    if start_date and target_date and start_date > target_date:
        errors["start_date"] = "시작일은 목표일보다 앞이어야 합니다."
    if status not in dict(Milestone.STATUSES):
        errors["status"] = "알 수 없는 상태입니다."
    return errors


def create_milestone(*, project, name, target_date, actor, start_date=None, status="planned"):
    if not can_view_project(actor, project):
        raise ServiceError({"org": "이 조직의 멤버가 아닙니다."})
    require_level(actor, project, effective("project.roadmap_by", org=project.org), "roadmap")
    errors = _validate_milestone(name, target_date, start_date, status)
    if errors:
        raise ServiceError(errors)
    return Milestone.objects.create(
        project=project,
        name=name.strip()[:100],
        start_date=start_date,
        target_date=target_date,
        status=status,
        created_by=actor,
    )


def update_milestone(ms, changes: dict, *, actor):
    """마일스톤에는 version이 없다(동시 편집이 문제가 될 만큼 자주 고치지 않는다)."""
    if not can_view_project(actor, ms.project):
        raise ServiceError({"org": "이 조직의 멤버가 아닙니다."})
    require_level(actor, ms.project, effective("project.roadmap_by", org=ms.project.org), "roadmap")
    name = changes.get("name", ms.name)
    target_date = changes.get("target_date", ms.target_date)
    start_date = changes.get("start_date", ms.start_date)
    status = changes.get("status", ms.status)
    errors = _validate_milestone(name, target_date, start_date, status)
    if errors:
        raise ServiceError(errors)
    ms.name = name.strip()[:100]
    ms.target_date = target_date
    ms.start_date = start_date
    ms.status = status
    ms.save(update_fields=["name", "target_date", "start_date", "status"])
    return ms


def delete_milestone(ms, actor):
    if not can_view_project(actor, ms.project):
        raise ServiceError({"org": "이 조직의 멤버가 아닙니다."})
    require_level(actor, ms.project, effective("project.roadmap_by", org=ms.project.org), "roadmap")
    ms.delete()


def create_dependency(*, from_project, to_project, actor, note="", is_blocking=False):
    if not (can_view_project(actor, from_project) and can_view_project(actor, to_project)):
        raise ServiceError({"org": "이 조직의 멤버가 아닙니다."})
    require_level(
        actor, from_project, effective("project.roadmap_by", org=from_project.org), "roadmap"
    )
    if to_project.org_id != from_project.org_id:
        raise ServiceError({"to_project": "같은 조직의 프로젝트만 연결할 수 있습니다."})
    if to_project.pk == from_project.pk:
        raise ServiceError({"to_project": "자기 자신에게는 의존할 수 없습니다."})
    if ProjectDependency.objects.filter(from_project=from_project, to_project=to_project).exists():
        raise ServiceError({"to_project": "이미 있는 의존성입니다."})
    # ponytail: 순환은 막지 않는다. 표시만 하는 목록이라 해가 없다. 자동 일정 계산이
    # 생기면 그때 검사한다.
    return ProjectDependency.objects.create(
        from_project=from_project,
        to_project=to_project,
        note=(note or "").strip()[:200],
        is_blocking=bool(is_blocking),
        created_by=actor,
    )


def delete_dependency(dep, actor):
    if not (can_view_project(actor, dep.from_project) and can_view_project(actor, dep.to_project)):
        raise ServiceError({"org": "이 조직의 멤버가 아닙니다."})
    require_level(
        actor,
        dep.from_project,
        effective("project.roadmap_by", org=dep.from_project.org),
        "roadmap",
    )
    dep.delete()


def roadmap(org, today=None, *, viewer=None) -> dict:
    """3개월 창(이번 달 1일부터). 막대는 창에 잘라 맞춘 left/width %.

    viewer가 볼 수 있는 프로젝트의 마일스톤·의존성만. None이면 공개 프로젝트만(보고서와 같은 규칙).
    """
    shown = (
        visible_projects(viewer, org)
        if viewer is not None
        else org.projects.filter(visibility="org")
    )
    today = today or today_kst()
    start = today.replace(day=1)
    end = _add_month(start, 3)
    span = (end - start).days
    months = [_add_month(start, i) for i in range(3)]

    qs = list(
        Milestone.objects.filter(project__in=shown, project__is_archived=False).select_related(
            "project__org"
        )
    )
    stats = project_stats_bulk({ms.project_id: ms.project for ms in qs}.values())
    rows, hidden = [], 0
    for ms in qs:
        s = min(ms.start_date or ms.target_date, ms.target_date)
        if ms.target_date < start or s >= end:
            hidden += 1
            continue
        a, b = max(s, start), min(ms.target_date, end)
        st = stats[ms.project_id]
        rows.append(
            {
                "ms": ms,
                "meta": f"{ms.project.name} · {fmt_md(ms.target_date)} · 완료 {st['done']}/{st['total']}",
                "left": round((a - start).days / span * 100, 2),
                "width": round(max((b - a).days, 1) / span * 100, 2),
                "pct": round(st["done"] / st["total"] * 100) if st["total"] else 0,
                "ready": ms.status != "planned",
            }
        )
    rows.sort(key=lambda r: (r["ms"].target_date, r["ms"].pk))
    deps = list(
        ProjectDependency.objects.filter(
            from_project__in=shown, to_project__in=shown
        ).select_related("from_project", "to_project")
    )
    # 오늘이 창의 어디쯤인지 — 막대만 있으면 "지금 늦었는지"를 읽을 수 없다
    return {
        "months": months,
        "rows": rows,
        "deps": deps,
        "hidden": hidden,
        "today_pct": round((today - start).days / span * 100, 2),
    }


def parse_spec(raw: bytes, *, source: str) -> dict:
    if len(raw) > SPEC_MAX:
        raise ServiceError({"spec": "스펙이 너무 큽니다 (5MB 상한)."})
    try:
        spec = json.loads(raw.decode("utf-8"))
    except (UnicodeDecodeError, json.JSONDecodeError):
        raise ServiceError({"spec": f"{source}를 JSON으로 읽지 못했습니다."}) from None
    if not isinstance(spec, dict) or not isinstance(spec.get("paths"), dict):
        raise ServiceError({"spec": "OpenAPI 문서가 아닙니다 (paths 없음)."})
    return spec


def _check_public(url: str) -> str:
    """공개 인터넷 주소인지 본다. 아니면 ServiceError를 낸다.

    서버가 대신 받아 주는 요청이라, 막지 않으면 조직 멤버 누구나 이 서버를 발판 삼아
    사내 주소를 읽을 수 있다. 같은 도커 망에 web·mcp·db가 떠 있고 받아 온 내용이 화면에
    그대로 나오므로 실제로 새어 나간다.
    """
    parsed = urlparse((url or "").strip())
    if parsed.scheme not in ("http", "https") or not parsed.hostname:
        raise ServiceError({"spec": "http:// 또는 https:// 주소를 입력하세요."})
    try:
        infos = socket.getaddrinfo(parsed.hostname, parsed.port or 0, proto=socket.IPPROTO_TCP)
    except OSError:
        raise ServiceError({"spec": "주소를 찾지 못했습니다."}) from None
    for info in infos:
        ip = ipaddress.ip_address(info[4][0])
        if not ip.is_global or ip.is_multicast:
            raise ServiceError({"spec": "사내·사설 주소는 받아 올 수 없습니다."})
    return url


class _SafeRedirect(HTTPRedirectHandler):
    """따라가기 전에 옮겨 갈 주소도 검사한다. 안 하면 공개 주소가 사내로 되돌린다."""

    def redirect_request(self, req, fp, code, msg, headers, newurl):
        _check_public(newurl)
        return super().redirect_request(req, fp, code, msg, headers, newurl)


def fetch_spec(url: str) -> dict:
    """주소에서 OpenAPI JSON을 받는다. 브라우저가 아니라 서버가 받는다.

    # ponytail: 주소를 풀어 본 뒤 연결하므로 그사이 DNS가 바뀌면 뚫린다(DNS 리바인딩).
    # 거기까지 막아야 하면 IP로 직접 연결하고 Host 헤더를 세우는 방식으로 바꾼다.
    """
    url = _check_public(url)
    req = Request(url, headers={"Accept": "application/json", "User-Agent": "sandol-pm"})
    opener = build_opener(_SafeRedirect)
    try:
        with opener.open(req, timeout=SPEC_TIMEOUT) as r:  # noqa: S310 — 위에서 검사했다
            raw = r.read(SPEC_MAX + 1)
    except ServiceError:
        raise
    except URLError as e:
        raise ServiceError({"spec": f"주소를 읽지 못했습니다: {e.reason}"}) from None
    except OSError as e:
        raise ServiceError({"spec": f"주소를 읽지 못했습니다: {e}"}) from None
    return parse_spec(raw, source=url)


def set_api_spec(project, spec: dict, *, source_url: str, actor, source: str = "web") -> ApiSpec:
    if not is_member(actor, project.org):
        raise ServiceError({"org": "이 조직의 멤버가 아닙니다."})
    require_ai_enabled(project.org, source, "API 문서 등록")
    obj, _ = ApiSpec.objects.update_or_create(
        project=project,
        defaults={"spec": spec, "source_url": source_url[:500], "uploaded_by": actor},
    )
    return obj


def spec_view(spec: dict, q: str = "") -> dict:
    """OpenAPI 문서를 태그별 그룹으로 바꾼다. 화면에 필요한 것만 뽑는다."""
    q = (q or "").strip().lower()
    info = spec.get("info") or {}
    tag_desc = {
        t.get("name"): t.get("description", "")
        for t in (spec.get("tags") or [])
        if isinstance(t, dict)
    }
    groups, order = {}, []
    for path, ops in (spec.get("paths") or {}).items():
        if not isinstance(ops, dict):
            continue
        for method, op in ops.items():
            m = method.lower()
            if m not in METHOD_COLOR or not isinstance(op, dict):
                continue
            summary = op.get("summary") or ""
            if q and q not in f"{path} {summary} {m}".lower():
                continue
            tag = ((op.get("tags") or ["기타"]) or ["기타"])[0]
            if tag not in groups:
                groups[tag] = {"tag": tag, "desc": tag_desc.get(tag, ""), "ops": []}
                order.append(tag)
            body = None
            content = (op.get("requestBody") or {}).get("content") or {}
            for ctype, c in content.items():
                example = (c or {}).get("example")
                body = {
                    "type": ctype,
                    "example": json.dumps(example, ensure_ascii=False, indent=2) if example else "",
                }
                break
            params = []
            for pa in op.get("parameters") or []:
                if not isinstance(pa, dict):
                    continue
                sc = pa.get("schema") or {}
                bits = [pa.get("in", ""), sc.get("type", "string")]
                if pa.get("required"):
                    bits.append("필수")
                if sc.get("enum"):
                    bits.append(" | ".join(str(x) for x in sc["enum"]))
                if sc.get("default") is not None:
                    bits.append(f"기본 {sc['default']}")
                params.append(
                    {
                        "name": pa.get("name", ""),
                        "meta": " · ".join(b for b in bits if b),
                        "desc": pa.get("description", ""),
                    }
                )
            responses = []
            for code, r in (op.get("responses") or {}).items():
                code = str(code)
                responses.append(
                    {
                        "code": code,
                        "desc": (r or {}).get("description", ""),
                        "bg": "#B9E6CB"
                        if code.startswith("2")
                        else "#F6C9C4"
                        if code.startswith("4")
                        else "#F0F4F6",
                        "color": "#0B3D22"
                        if code.startswith("2")
                        else "#6B1410"
                        if code.startswith("4")
                        else "#636D7A",
                    }
                )
            groups[tag]["ops"].append(
                {
                    "method": m.upper(),
                    "color": METHOD_COLOR[m],
                    "path": path,
                    "summary": summary,
                    "desc": op.get("description", ""),
                    "auth": bool(op.get("security")),
                    "params": params,
                    "body": body,
                    "responses": responses,
                }
            )
    out = [groups[t] for t in order]
    return {
        "title": info.get("title") or "제목 없는 API",
        "version": f"v{info['version']}" if info.get("version") else "버전 없음",
        "openapi": spec.get("openapi") or spec.get("swagger") or "—",
        "server": ((spec.get("servers") or [{}])[0] or {}).get("url") or "서버 정보 없음",
        "desc": info.get("description", ""),
        "groups": out,
        "count": sum(len(g["ops"]) for g in out),
    }
