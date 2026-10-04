from django.db import transaction
from django.utils import timezone

from common.errors import ServiceError

from .models import Invite, Organization, OrgMembership, Team, TeamMembership
from .settings import LOCKED, SPECS, clean, display, effective

# ---------- 조직 ----------


def orgs_of(user):
    """user가 속한 조직 queryset."""
    return Organization.objects.filter(memberships__user=user).distinct()


def is_member(user, org) -> bool:
    return OrgMembership.objects.filter(org=org, user=user).exists()


def is_admin(user, org) -> bool:
    return OrgMembership.objects.filter(org=org, user=user, role="admin").exists()


def require_admin(user, org):
    if not is_admin(user, org):
        raise ServiceError({"org": "조직 관리자만 할 수 있습니다."})


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
    cleaned = clean("org", data, allow_locked=True)
    old = org.settings or {}
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
        raise ServiceError({"name": "조직 이름을 입력하세요."})
    org = Organization.objects.create(
        name=name[:100], purpose=purpose.strip()[:200], created_by=actor
    )
    OrgMembership.objects.create(org=org, user=actor, role="admin")
    return org


def create_invite(org, actor, days: int | None = None, *, source: str = "web") -> Invite:
    require_admin(actor, org)
    require_ai_enabled(org, source, "초대 링크 만들기")
    if days is None:
        days = effective("org.invite_days", org=org)
    if not 1 <= days <= 90:
        raise ServiceError({"days": "만료일은 1~90일 사이여야 합니다."})
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
        raise ServiceError({"token": "초대 링크가 유효하지 않거나 만료되었습니다."})
    if invite.max_uses > 0 and invite.use_count >= invite.max_uses:
        raise ServiceError({"token": "초대 링크가 유효하지 않거나 만료되었습니다."})
    _, created = OrgMembership.objects.get_or_create(
        org=invite.org, user=user, defaults={"role": "member"}
    )
    if created:
        invite.use_count += 1
        invite.save(update_fields=["use_count"])
    return invite.org


@transaction.atomic
def change_role(membership, role: str, actor):
    require_admin(actor, membership.org)
    if role not in dict(OrgMembership.ROLES):
        raise ServiceError({"role": "알 수 없는 역할입니다."})
    _lock_org(membership.org)
    if membership.role == "admin" and role != "admin" and _admin_count(membership.org) <= 1:
        raise ServiceError({"role": "마지막 관리자의 역할은 바꿀 수 없습니다."})
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
        raise ServiceError({"member": "마지막 관리자는 제거할 수 없습니다."})
    TeamMembership.objects.filter(team__org=membership.org, user=membership.user).delete()
    membership.delete()


def _admin_count(org) -> int:
    return OrgMembership.objects.filter(org=org, role="admin").count()


def _lock_org(org):
    """마지막 관리자 검사를 직렬화한다. 관리자 둘이 동시에 서로를 내리면 둘 다 count=2를 보고
    통과해 관리자 0명이 되기 때문이다(그 조직은 설정도 승인도 영영 못 바꾼다)."""
    Organization.objects.select_for_update().filter(pk=org.pk).exists()


# ---------- 팀 ----------


def _validate_team_name(org, name: str, exclude_pk=None) -> str:
    name = (name or "").strip()
    if not name:
        raise ServiceError({"name": "팀 이름을 입력하세요."})
    name = name[:100]
    qs = Team.objects.filter(org=org, name=name)
    if exclude_pk is not None:
        qs = qs.exclude(pk=exclude_pk)
    if qs.exists():
        raise ServiceError({"name": "같은 이름의 팀이 이미 있습니다."})
    return name


def create_team(*, org, name: str, purpose: str = "", actor, source: str = "") -> Team:
    _check_ai_manage_teams(org, source)
    require_admin(actor, org)
    return Team.objects.create(
        org=org,
        name=_validate_team_name(org, name),
        purpose=(purpose or "").strip()[:200],
        created_by=actor,
    )


def update_team(team, *, name: str, purpose: str = "", actor) -> Team:
    require_admin(actor, team.org)
    team.name = _validate_team_name(team.org, name, exclude_pk=team.pk)
    team.purpose = (purpose or "").strip()[:200]
    team.save(update_fields=["name", "purpose"])
    return team


@transaction.atomic
def delete_team(team, *, actor, source: str = "web"):
    """팀만 지운다. 멤버는 조직에 그대로 남고 프로젝트도 지워지지 않는다(M2M 행만 사라진다).

    GitHub 팀 링크가 있으면 함께 사라진다(CASCADE) — 웹훅의 'team deleted' 처리와 같이
    링크만 지우고 GitHub 쪽 팀은 그대로 둔다.
    """
    require_admin(actor, team.org)
    _check_ai_delete(team.org, source)
    from tasks.models import ChangeLog

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
    self_join = actor == user and effective("org.team_join_self", org=team.org)
    if not self_join:
        require_admin(actor, team.org)
    if not is_member(user, team.org):
        raise ServiceError({"user": "먼저 조직에 초대해야 합니다."})
    if not user.is_active:
        raise ServiceError({"user": "비활성 사용자는 팀에 넣을 수 없습니다."})
    membership, _ = TeamMembership.objects.get_or_create(team=team, user=user)
    return membership


def remove_team_member(team, user, actor, source: str = ""):
    _check_ai_manage_teams(team.org, source)
    self_leave = actor == user and effective("org.team_join_self", org=team.org)
    if not self_leave:
        require_admin(actor, team.org)
    TeamMembership.objects.filter(team=team, user=user).delete()


def set_team_channel(team, channel_id: str, actor) -> Team:
    """봇이 만든 채널 id를 적는다. 빈 문자열이면 연결을 끊는다(Discord에서 지워졌을 때)."""
    require_admin(actor, team.org)
    team.discord_channel_id = (channel_id or "").strip()[:32]
    team.save(update_fields=["discord_channel_id"])
    return team


# ---------- 거버넌스 ----------


def set_governance(org, text: str, actor) -> Organization:
    """조직의 개발 거버넌스 본문 교체. 비우면 기본안으로 되돌아간다."""
    require_admin(actor, org)
    text = (text or "").strip()
    if len(text) > 20000:
        raise ServiceError({"governance": "2만 자를 넘을 수 없습니다."})
    org.governance = text
    org.save(update_fields=["governance"])
    return org
