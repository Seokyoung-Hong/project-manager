from django.db import transaction
from django.utils import timezone

from common.errors import ServiceError

from . import settings as S
from .models import Invite, Organization, OrgMembership, Team, TeamMembership

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


def create_invite(org, actor, days: int | None = None) -> Invite:
    require_admin(actor, org)
    if days is None:
        days = S.effective("org.invite_days", org=org)
    if not 1 <= days <= 90:
        raise ServiceError({"days": "만료일은 1~90일 사이여야 합니다."})
    expires_at = timezone.now() + timezone.timedelta(days=days)
    return Invite.objects.create(
        org=org,
        created_by=actor,
        expires_at=expires_at,
        max_uses=S.effective("org.invite_max_uses", org=org),
    )


def revoke_invite(invite, actor):
    require_admin(actor, invite.org)
    if invite.revoked_at is None:
        invite.revoked_at = timezone.now()
        invite.save(update_fields=["revoked_at"])


@transaction.atomic
def join_by_token(user, token: str) -> Organization:
    invite = Invite.objects.select_for_update().select_related("org").filter(token=token).first()
    if invite is None or not invite.is_usable:
        raise ServiceError({"token": "초대 링크가 유효하지 않거나 만료되었습니다."})
    _, created = OrgMembership.objects.get_or_create(
        org=invite.org, user=user, defaults={"role": "member"}
    )
    if created:
        invite.use_count += 1
        invite.save(update_fields=["use_count"])
    return invite.org


def change_role(membership, role: str, actor):
    require_admin(actor, membership.org)
    if role not in dict(OrgMembership.ROLES):
        raise ServiceError({"role": "알 수 없는 역할입니다."})
    if membership.role == "admin" and role != "admin" and _admin_count(membership.org) <= 1:
        raise ServiceError({"role": "마지막 관리자의 역할은 바꿀 수 없습니다."})
    membership.role = role
    membership.save(update_fields=["role"])


def set_tags(membership, tags, actor):
    """스킬 태그. 관리자 또는(설정이 허락하면) 본인이 고친다. 공백 제거·중복 제거·20자·최대 10개."""
    self_edit = (
        actor == membership.user and S.effective("org.tags_by", org=membership.org) == "self"
    )
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
    if membership.role == "admin" and _admin_count(membership.org) <= 1:
        raise ServiceError({"member": "마지막 관리자는 제거할 수 없습니다."})
    TeamMembership.objects.filter(team__org=membership.org, user=membership.user).delete()
    membership.delete()


def _admin_count(org) -> int:
    return OrgMembership.objects.filter(org=org, role="admin").count()


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


def create_team(*, org, name: str, purpose: str = "", actor) -> Team:
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


def delete_team(team, actor):
    """팀만 지운다. 멤버는 조직에 그대로 남고 프로젝트도 지워지지 않는다."""
    require_admin(actor, team.org)
    team.delete()


def _self_join(team, user, actor) -> bool:
    return actor == user and S.effective("org.team_join_self", org=team.org)


def add_team_member(team, user, actor) -> TeamMembership:
    if not _self_join(team, user, actor):
        require_admin(actor, team.org)
    if not is_member(user, team.org):
        raise ServiceError({"user": "먼저 조직에 초대해야 합니다."})
    if not user.is_active:
        raise ServiceError({"user": "비활성 사용자는 팀에 넣을 수 없습니다."})
    membership, _ = TeamMembership.objects.get_or_create(team=team, user=user)
    return membership


def remove_team_member(team, user, actor):
    if not _self_join(team, user, actor):
        require_admin(actor, team.org)
    TeamMembership.objects.filter(team=team, user=user).delete()


def set_team_channel(team, channel_id: str, actor) -> Team:
    """봇이 만든 채널 id를 적는다. 빈 문자열이면 연결을 끊는다(Discord에서 지워졌을 때)."""
    require_admin(actor, team.org)
    team.discord_channel_id = (channel_id or "").strip()[:32]
    team.save(update_fields=["discord_channel_id"])
    return team


def teams_of(user, org):
    """org 안에서 user가 속한 팀 queryset. 가시성 계산에 쓰지 않는다."""
    return Team.objects.filter(org=org, memberships__user=user).distinct()


# ---------- 설정 ----------


def _log_settings(target_type, target_id, old: dict, new: dict, actor, source):
    """바뀐 키마다 ChangeLog 한 줄. 값은 JSON 문자열 그대로."""
    import json

    from tasks.models import ChangeLog

    for key in sorted(set(old) | set(new)):
        if old.get(key) != new.get(key):
            ChangeLog.objects.create(
                target_type=target_type,
                target_id=target_id,
                field=key,
                old_value=json.dumps(old.get(key), ensure_ascii=False) if key in old else "",
                new_value=json.dumps(new.get(key), ensure_ascii=False) if key in new else "",
                actor=actor,
                source=source,
            )


@transaction.atomic
def set_org_settings(org, data: dict, actor, *, source="web", locked=None) -> Organization:
    """조직 설정 전체 교체(폼과 같다). locked 를 주면 잠금 목록도 교체한다."""
    require_admin(actor, org)
    new = S.clean("org", data)
    if locked is None:
        locked = S.locked_keys(org)
    else:
        bad = [k for k in locked if k not in S.SPECS or not S.SPECS[k].overridable]
        if bad:
            raise ServiceError({S.LOCKED: "잠글 수 없는 항목이에요: " + ", ".join(bad)})
        locked = sorted(set(locked))
    if locked:
        new[S.LOCKED] = locked
    old = dict(org.settings)
    if old == new:
        return org
    org.settings = new
    org.save(update_fields=["settings"])
    _log_settings("org", org.pk, old, new, actor, source)
    return org


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
