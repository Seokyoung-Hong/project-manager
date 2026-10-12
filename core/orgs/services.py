import secrets

from django.db import transaction
from django.db.models import Exists, OuterRef, Q
from django.utils import timezone

from common.errors import ServiceError

from .models import Invite, Organization, OrgMembership, Team, TeamMembership
from .settings import LOCKED, SPECS, clean, display, effective, merge_secrets

# ---------- 조직 ----------


def orgs_of(user):
    """user가 속한 조직 queryset."""
    return Organization.objects.filter(memberships__user=user).distinct()


def usable_orgs(user):
    """user가 지금 쓸 수 있는 조직: 필수 구성원 정보가 빈 조직을 뺀다(orgs/member_info.py).

    태스크·프로젝트·문서·작업 요청 열람 관문이 이것을 쓴다. 조직 전환·목록은 orgs_of 그대로.
    """
    from .member_info import blocked_orgs

    return orgs_of(user).exclude(pk__in=[o.pk for o in blocked_orgs(user)])


def is_member(user, org) -> bool:
    return OrgMembership.objects.filter(org=org, user=user).exists()


def is_admin(user, org) -> bool:
    return OrgMembership.objects.filter(org=org, user=user, role="admin").exists()


def require_admin(user, org):
    if not is_admin(user, org):
        raise ServiceError(
            {"org": "조직 관리자만 할 수 있는 작업입니다. 조직 관리자에게 요청해 주세요."}
        )


# AI용 토큰으로 막힌 사람에게 원인을 알려 준다. 기존 토큰은 전부 AI용으로 옮겨졌다(accounts 0004).
TOKEN_HINT = "사람이 쓰는 스크립트라면 설정 → API 토큰에서 '사람용' 토큰을 새로 발급해 주세요."


def ai_denied(action: str) -> str:
    return f"이 조직 설정에서 AI의 {action}이 꺼져 있습니다. 사람이 웹에서 해 주세요. " + TOKEN_HINT


def require_ai_enabled(org, source: str, action: str = "쓰기"):
    """AI를 끈 조직(`ai.enabled=false`)이면 AI(source=mcp)의 모든 쓰기를 막는다.

    세부 키(ai.create_task 같은 것)가 없는 쓰기 경로도 전부 이 하나를 거친다 — 설정 도움말이
    "끄면 AI의 모든 쓰기를 막습니다"라고 약속하기 때문이다.
    """
    if source == "mcp" and not effective("ai.enabled", org=org):
        raise ServiceError({"ai": ai_denied(action)})


def _check_ai_manage_teams(org, source: str):
    """source가 mcp인데 AI 정책이 팀 관리를 막아 뒀으면 거부한다."""
    if source != "mcp":
        return
    if not effective("ai.enabled", org=org) or effective("ai.manage_teams", org=org) == "deny":
        raise ServiceError({"ai": ai_denied("팀 만들고 사람 넣기")})


def _check_ai_delete(org, source: str):
    """source가 mcp인데 AI 정책이 삭제를 막아 뒀으면 거부한다. 기본값이 막기다."""
    if source != "mcp":
        return
    if not effective("ai.enabled", org=org) or effective("ai.delete", org=org) == "deny":
        raise ServiceError({"ai": ai_denied("삭제")})


def _display_setting(key: str, value) -> str:
    """이력에 남기는 사람이 읽는 문구. 값이 없으면(=기본값) 기본값을 보여 준다."""
    if key == LOCKED:
        return ", ".join(SPECS[k].label if k in SPECS else k for k in sorted(value or [])) or "없음"
    spec = SPECS[key]
    return display(key, spec.default if value is None else value)


@transaction.atomic
def set_org_settings(
    org, data: dict, actor, *, note: str = "", source: str = "web", token=None
) -> Organization:
    """조직 설정을 통째로 교체한다(병합이 아니다 — 키 없음 = 기본값이 규칙이기 때문이다).

    바뀐 키마다 이력을 남긴다.
    """
    require_admin(actor, org)
    old = org.settings or {}
    cleaned = clean("org", merge_secrets(data, old), allow_locked=True)
    if old != cleaned:
        from tasks.models import ChangeLog

        for key in set(old) | set(cleaned):
            old_v, new_v = old.get(key), cleaned.get(key)
            if old_v == new_v:
                continue
            ChangeLog.objects.create(
                target_type="org",
                target_id=org.pk,
                field=key,
                old_value=_display_setting(key, old_v),
                new_value=_display_setting(key, new_v),
                actor=actor,
                source=source,
                note=note,
                token=token,
            )
    org.settings = cleaned
    org.save(update_fields=["settings"])
    return org


@transaction.atomic
def set_locks(org, keys: list[str], actor) -> Organization:
    """덮어쓸 수 있는(overridable) 항목만 잠근다. 그 밖의 키는 조용히 걸러진다."""
    require_admin(actor, org)
    # 승인 반영(_approve)·설정 저장과 동시에 돌면 옛 settings로 덮어쓰므로 행을 잠그고 다시 읽는다.
    org = Organization.objects.select_for_update().get(pk=org.pk)
    old = org.settings or {}
    old_locked = old.get(LOCKED) or []
    new_locked = clean("org", {LOCKED: keys}, allow_locked=True).get(LOCKED, [])
    if old_locked != new_locked:
        from tasks.models import ChangeLog

        ChangeLog.objects.create(
            target_type="org",
            target_id=org.pk,
            field=LOCKED,
            old_value=_display_setting(LOCKED, old_locked),
            new_value=_display_setting(LOCKED, new_locked),
            actor=actor,
            source="web",
        )
    new_settings = dict(old)
    if new_locked:
        new_settings[LOCKED] = new_locked
    else:
        new_settings.pop(LOCKED, None)
    org.settings = new_settings
    org.save(update_fields=["settings"])
    return org


@transaction.atomic
def create_org(name: str, purpose: str, actor) -> Organization:
    name = name.strip()
    if not name:
        raise ServiceError({"name": "조직 이름을 입력해 주세요."})
    org = Organization.objects.create(
        name=name[:100], purpose=purpose.strip()[:200], created_by=actor
    )
    OrgMembership.objects.create(org=org, user=actor, role="admin")
    from projects.doc_templates import seed
    from projects.models import Doc

    seed(Doc, org.pk, actor.pk)  # 문서 템플릿 2개(회의록·설계 문서)
    return org


def create_invite(org, actor, days: int | None = None, *, source: str = "web") -> Invite:
    require_admin(actor, org)
    require_ai_enabled(org, source, "초대 링크 만들기")
    if days is None:
        days = effective("org.invite_days", org=org)
    if not 1 <= days <= 90:
        raise ServiceError(
            {"days": "초대 링크의 만료 기간이 범위를 벗어났습니다. 1~90일로 입력해 주세요."}
        )
    expires_at = timezone.now() + timezone.timedelta(days=days)
    return Invite.objects.create(
        org=org,
        created_by=actor,
        expires_at=expires_at,
        max_uses=effective("org.invite_max_uses", org=org),
    )


def revoke_invite(invite, actor):
    require_admin(actor, invite.org)
    if invite.revoked_at is None:
        invite.revoked_at = timezone.now()
        invite.save(update_fields=["revoked_at"])


def invite_org(token: str):
    """로그인 전에도 "어느 조직 초대인지"만 알려 준다. 참여는 join_by_token이 한다."""
    invite = Invite.objects.select_related("org").filter(token=token).first()
    return invite.org if invite and invite.is_usable else None


@transaction.atomic
def join_by_token(user, token: str) -> Organization:
    invite = Invite.objects.select_for_update().select_related("org").filter(token=token).first()
    if invite is None or not invite.is_usable:
        raise ServiceError(
            {
                "token": "초대 링크가 만료되었거나 폐기되었습니다. 조직 관리자에게 새 초대 링크를 요청해 주세요."
            }
        )
    if invite.max_uses > 0 and invite.use_count >= invite.max_uses:
        raise ServiceError(
            {
                "token": "초대 링크가 만료되었거나 폐기되었습니다. 조직 관리자에게 새 초대 링크를 요청해 주세요."
            }
        )
    if invite.for_user_id:
        raise ServiceError({"token": PERSONAL_LOGGED_IN})
    _, created = OrgMembership.objects.get_or_create(
        org=invite.org, user=user, defaults={"role": "member"}
    )
    if created:
        invite.use_count += 1
        invite.save(update_fields=["use_count"])
    return invite.org


# ---------- 사람별 초대(가입 전 구성원 인계) ----------

PERSONAL_LOGGED_IN = "이 초대 링크는 새 계정용입니다. 로그아웃한 뒤 링크를 다시 열어 주세요."
PERSONAL_GONE = (
    "초대 링크가 만료되었거나 이미 사용되었습니다. 조직 관리자에게 새 초대 링크를 요청해 주세요."
)


def is_pending(user) -> bool:
    """가입 전: 비밀번호도 GitHub 연결도 로그인 기록도 없다. 셸로 만든 계정도 여기에 든다."""
    return (
        not user.has_usable_password() and user.last_login is None and not hasattr(user, "github")
    )


def _org_log(org, actor, field, value):
    from tasks.models import ChangeLog

    ChangeLog.objects.create(
        target_type="org", target_id=org.pk, field=field, new_value=value, actor=actor, source="web"
    )


@transaction.atomic
def add_pending_member(org, actor, display_name: str) -> OrgMembership:
    """표시 이름만으로 가입 전 구성원을 만든다. 사람별 초대 링크로 실제 사람에게 넘긴다."""
    from accounts.models import User

    require_admin(actor, org)
    name = (display_name or "").strip()[:50]
    if not name:
        raise ServiceError({"display_name": "표시 이름을 입력해 주세요."})
    user = User(username=f"pending-{secrets.token_hex(6)}", display_name=name)
    user.set_unusable_password()
    user.save()
    _org_log(org, actor, "member_add_pending", f"{name}({user.pk})")
    return OrgMembership.objects.create(org=org, user=user, role="member")


@transaction.atomic
def create_personal_invite(membership, actor) -> Invite:
    """가입 전 구성원 한 사람용 1회용 링크. 다시 만들면 그 사람의 이전 링크는 취소된다."""
    org, user = membership.org, membership.user
    require_admin(actor, org)
    if not is_pending(user):
        raise ServiceError(
            {
                "member": "이미 가입한 사람입니다. 사람별 초대 링크는 가입 전 구성원에게만 만들 수 있습니다."
            }
        )
    now = timezone.now()
    Invite.objects.filter(org=org, for_user=user, revoked_at__isnull=True).update(revoked_at=now)
    _org_log(org, actor, "invite_personal", f"{user.display_name}({user.pk})")
    return Invite.objects.create(org=org, created_by=actor, for_user=user, max_uses=1)


def personal_invite(token: str, *, lock=False):
    """쓸 수 있는 사람별 초대. 아니면 None. lock=True는 transaction.atomic 안에서만 쓴다."""
    qs = Invite.objects.select_related("org", "for_user").filter(
        token=token, for_user__isnull=False
    )
    if lock:
        qs = qs.select_for_update(of=("self",))
    invite = qs.first()
    if (
        invite is None
        or not invite.is_usable
        or invite.use_count >= invite.max_uses
        or not is_pending(invite.for_user)
    ):
        return None
    return invite


def claim_invite(token: str, set_up) -> Invite:
    """가입 전 계정을 넘겨받는다. set_up(user)가 아이디·비밀번호나 GitHub 연결을 붙이고 user를 돌려준다.

    호출부의 transaction.atomic 안에서 부른다. 초대 행을 잠그고 다시 확인하므로 같은 링크로
    두 번 넘겨받을 수 없다.
    """
    invite = personal_invite(token, lock=True)
    if invite is None:
        raise ServiceError({"token": PERSONAL_GONE})
    invite.for_user = set_up(invite.for_user)
    invite.use_count += 1
    invite.save(update_fields=["use_count"])
    _org_log(
        invite.org,
        invite.for_user,
        "invite_claimed",
        f"{invite.for_user.display_name}({invite.for_user.pk})",
    )
    return invite


@transaction.atomic
def change_role(membership, role: str, actor):
    require_admin(actor, membership.org)
    if role not in dict(OrgMembership.ROLES):
        raise ServiceError(
            {"role": "역할이 올바르지 않습니다. 화면에 표시된 역할 중에서 선택해 주세요."}
        )
    _lock_org(membership.org)
    if membership.role == "admin" and role != "admin" and _admin_count(membership.org) <= 1:
        raise ServiceError(
            {
                "role": "마지막 관리자의 역할은 바꿀 수 없습니다. 다른 멤버를 관리자로 지정한 뒤 변경해 주세요."
            }
        )
    membership.role = role
    membership.save(update_fields=["role"])


def set_tags(membership, tags, actor):
    """스킬 태그. 관리자만 고친다(조직이 본인도 허용했으면 본인도). 공백 제거·중복 제거·20자·최대 10개."""
    self_edit = actor == membership.user and effective("org.tags_by", org=membership.org) == "self"
    if not self_edit:
        require_admin(actor, membership.org)
    cleaned, seen = [], set()
    for t in tags:
        t = (t or "").strip()[:20]
        if t and t not in seen:
            seen.add(t)
            cleaned.append(t)
    membership.tags = cleaned[:10]
    membership.save(update_fields=["tags"])


@transaction.atomic
def remove_member(membership, actor):
    """조직에서 빼면 그 조직의 모든 팀에서도 빠진다.

    TeamMembership은 조직이 아니라 팀을 가리키므로 cascade가 닿지 않는다. 여기서 지우지
    않으면 조직에 없는 사람이 팀 화면에 남는다.
    """
    require_admin(actor, membership.org)
    _lock_org(membership.org)
    if membership.role == "admin" and _admin_count(membership.org) <= 1:
        raise ServiceError(
            {
                "member": "마지막 관리자는 제거할 수 없습니다. 다른 멤버를 관리자로 지정한 뒤 제거해 주세요."
            }
        )
    TeamMembership.objects.filter(team__org=membership.org, user=membership.user).delete()
    membership.delete()


def _admin_count(org) -> int:
    return OrgMembership.objects.filter(org=org, role="admin").count()


@transaction.atomic
def delete_org(org, actor):
    """조직과 그 안의 모든 데이터를 한 트랜잭션으로 지운다. 웹 전용(AI·API 경로 없음).

    대부분은 org CASCADE로 따라 지워지지만 PROTECT FK는 Django가 막으므로 잎부터 명시 순서로
    먼저 지운다. 새 PROTECT FK가 생기면 test_delete_org의 전 모델 픽스처가 실패해 알려 준다.
    GitHub 앱 설치·Discord 연결은 DB 행만 지운다(외부 쪽 해제는 사람이 따로 한다).
    """
    require_admin(actor, org)
    _lock_org(org)
    from portfolio.models import PortfolioDraft, PortfolioSource
    from tasks.attachments import purge_files
    from tasks.models import Attachment, ChangeLog, Task, TaskDecisionRecord

    # 삭제 기록. ChangeLog는 조직 FK가 없어 조직이 지워져도 남는다(팀·프로젝트 삭제와 같은 방식).
    ChangeLog.objects.create(
        target_type="org",
        target_id=org.pk,
        field="delete",
        old_value="",
        new_value=f"조직 {org.name}({org.pk})",
        actor=actor,
        source="web",
    )
    purge_files(
        Attachment.objects.filter(Q(project__org=org) | Q(task__project__org=org) | Q(doc__org=org))
    )  # 행은 CASCADE로 지워지고, 파일은 커밋 뒤에 지운다
    # PROTECT 사슬: 포트폴리오 출처 → 초안(org PROTECT) → 결정 기록(task PROTECT) → 태스크(project PROTECT)
    PortfolioSource.objects.filter(
        Q(draft__org=org) | Q(decision_record__task__project__org=org)
    ).delete()
    PortfolioDraft.objects.filter(org=org).delete()
    records = TaskDecisionRecord.objects.filter(task__project__org=org)
    records.update(supersedes=None)  # 자기 참조 PROTECT는 같은 묶음 안이어도 Django가 막는다
    records.delete()
    Task.objects.filter(project__org=org).delete()
    org.delete()  # 나머지(프로젝트·팀·문서·멤버십·초대·GitHub·Discord 등)는 CASCADE


def _lock_org(org):
    """마지막 관리자 검사를 직렬화한다. 관리자 둘이 동시에 서로를 내리면 둘 다 count=2를 보고
    통과해 관리자 0명이 되기 때문이다(그 조직은 설정도 승인도 영영 못 바꾼다)."""
    Organization.objects.select_for_update().filter(pk=org.pk).exists()


# ---------- 팀 ----------


def _validate_team_name(org, name: str, exclude_pk=None) -> str:
    name = (name or "").strip()
    if not name:
        raise ServiceError({"name": "팀 이름을 입력해 주세요."})
    name = name[:100]
    qs = Team.objects.filter(org=org, name=name)
    if exclude_pk is not None:
        qs = qs.exclude(pk=exclude_pk)
    if qs.exists():
        raise ServiceError({"name": "같은 이름의 팀이 있습니다. 다른 이름을 입력해 주세요."})
    return name


def create_team(
    *,
    org,
    name: str,
    purpose: str = "",
    actor,
    source: str = "",
    dev_tools: bool = True,
    is_private: bool = False,
) -> Team:
    _check_ai_manage_teams(org, source)
    require_admin(actor, org)
    return Team.objects.create(
        org=org,
        name=_validate_team_name(org, name),
        purpose=(purpose or "").strip()[:200],
        dev_tools=dev_tools,
        is_private=is_private,
        created_by=actor,
    )


def update_team(
    team, *, name: str, purpose: str = "", actor, dev_tools=None, is_private=None
) -> Team:
    """None인 값은 그대로 둔다. 비공개 여부도 조직 관리자만 바꾼다(require_admin)."""
    require_admin(actor, team.org)
    team.name = _validate_team_name(team.org, name, exclude_pk=team.pk)
    team.purpose = (purpose or "").strip()[:200]
    if dev_tools is not None:
        team.dev_tools = dev_tools
    if is_private is not None:
        team.is_private = is_private
    team.save(update_fields=["name", "purpose", "dev_tools", "is_private"])
    return team


def visible_teams(user, org=None):
    """세부(멤버·팀장·채널·인원)를 볼 수 있는 팀. 이름은 이 함수와 상관없이 누구나 본다.

    비공개 팀은 그 팀원(팀장 포함)과 조직 관리자만. org가 None이면 user의 모든 조직.
    """
    qs = (
        Team.objects.filter(org=org)
        if org is not None
        else Team.objects.filter(org__in=usable_orgs(user))
    )
    admin = OrgMembership.objects.filter(user=user, role="admin", org_id=OuterRef("org_id"))
    member = TeamMembership.objects.filter(user=user, team_id=OuterRef("pk"))
    return qs.filter(Q(is_private=False) | Exists(admin) | Exists(member))


def can_view_team(user, team) -> bool:
    return visible_teams(user, team.org).filter(pk=team.pk).exists()


@transaction.atomic
def delete_team(team, *, actor, source: str = "web"):
    """팀만 지운다. 멤버는 조직에 그대로 남고 프로젝트도 지워지지 않는다(M2M 행만 사라진다).

    GitHub 팀 링크가 있으면 함께 사라진다(CASCADE) — 웹훅의 'team deleted' 처리와 같이
    링크만 지우고 GitHub 쪽 팀은 그대로 둔다.
    """
    require_admin(actor, team.org)
    _check_ai_delete(team.org, source)
    from tasks.models import ChangeLog

    # 팀 문서는 범위가 비면 조직 전체 공개가 된다. 팀 삭제는 되돌릴 수 있는 일로 두고 싶으므로
    # 문서를 지우지 않고, 먼저 옮기라고 거절한다(Sol R2). Doc.team은 RESTRICT라 DB도 막는다.
    n = team.docs.count()
    if n:
        raise ServiceError(
            {
                "team": f"이 팀 범위의 문서·회의록 {n}개가 있습니다. 다른 공개 범위로 옮기거나 지운 뒤에 팀을 삭제해 주세요."
            }
        )
    ChangeLog.objects.create(
        target_type="org",
        target_id=team.org_id,
        field="delete",
        old_value="",
        new_value=f"팀 {team.name}({team.pk})",
        actor=actor,
        source=source,
    )
    team.delete()


def add_team_member(team, user, actor, source: str = "") -> TeamMembership:
    _check_ai_manage_teams(team.org, source)
    # 비공개 팀에 스스로 들어가면 세부를 보게 되므로 자기 가입을 막는다(나가기는 허용).
    self_join = (
        actor == user and not team.is_private and effective("org.team_join_self", org=team.org)
    )
    if not self_join:
        require_admin(actor, team.org)
    if not is_member(user, team.org):
        raise ServiceError(
            {"user": "조직에 속하지 않은 사람은 팀에 넣을 수 없습니다. 먼저 조직에 초대해 주세요."}
        )
    if not user.is_active:
        raise ServiceError(
            {
                "user": "정지된 사용자는 팀에 넣을 수 없습니다. 서비스 운영자에게 계정 상태를 문의해 주세요."
            }
        )
    membership, _ = TeamMembership.objects.get_or_create(team=team, user=user)
    return membership


def remove_team_member(team, user, actor, source: str = ""):
    _check_ai_manage_teams(team.org, source)
    self_leave = actor == user and effective("org.team_join_self", org=team.org)
    if not self_leave:
        require_admin(actor, team.org)
    TeamMembership.objects.filter(team=team, user=user).delete()


def set_team_lead(team, user, is_lead: bool, actor) -> TeamMembership:
    require_admin(actor, team.org)
    membership = TeamMembership.objects.filter(team=team, user=user).first()
    if membership is None:
        raise ServiceError(
            {
                "user": "팀에 속하지 않은 사람은 팀장으로 지정할 수 없습니다. 팀에 먼저 추가해 주세요."
            }
        )
    membership.is_lead = is_lead
    membership.save(update_fields=["is_lead"])
    return membership


def set_team_channel(team, channel_id: str, actor, *, checked: bool = False, managed=None) -> Team:
    """봇이 만든 채널 id를 적는다. 빈 문자열이면 연결을 끊는다(Discord에서 지워졌을 때).

    새 채널로 바꾸는 것은 `orgs.channels.connect`(권한 밖 인원 확인)만 `checked=True`로 한다.
    """
    from .channels import CHECK_REQUIRED, clear_alerts

    require_admin(actor, team.org)
    new = (channel_id or "").strip()[:32]
    if new != team.discord_channel_id:
        if new and not checked:
            raise ServiceError({"channel_id": CHECK_REQUIRED})
        clear_alerts(team.discord_channel_id, "team", team.pk)
        team.discord_channel_managed = bool(managed)
    elif managed is not None:
        team.discord_channel_managed = managed
    team.discord_channel_id = new
    team.save(update_fields=["discord_channel_id", "discord_channel_managed"])
    return team


# ---------- 거버넌스 ----------


def set_governance(org, text: str, actor) -> Organization:
    """조직의 업무 거버넌스 본문 교체. 비우면 기본안으로 되돌아간다."""
    require_admin(actor, org)
    text = (text or "").strip()
    if len(text) > 20000:
        raise ServiceError({"governance": "업무 규칙이 너무 깁니다. 2만 자 이내로 줄여 주세요."})
    org.governance = text
    org.save(update_fields=["governance"])
    return org
