"""Discord 계정 연결.

두 신원을 맞바꿔야 연결된다: **코드**는 로그인한 웹 세션에서만 나오고(= PM 쪽 신원),
**snowflake**는 게이트웨이가 채운 `author.id`에서만 나온다(= Discord 쪽 신원).
어느 한쪽만으로는 소유가 증명되지 않는다. 사용자가 직접 입력하는 경로는 두지 않는다.
"""

import secrets
import unicodedata
from datetime import timedelta

from django.conf import settings
from django.db import transaction
from django.urls import reverse
from django.utils import timezone

from common.errors import ServiceError
from github.models import GitHubIdentity
from orgs.settings import clean

from .consents import DOC_VERSIONS, NOTICES, POLICY_VERSION, TARGETS
from .identity import resolve
from .models import ApiToken, Consent, IdempotencyKey, LoginLock, OAuthCode, TermsAgreement, User

CODE_TTL = timedelta(minutes=10)

# 이름에 글자 말고 허용하는 기호. 숫자·@<>/:#\·이모지·제어 문자는 막는다(아이디·주소·멘션 흉내 방지).
_NAME_PUNCT = set(" .-'·")


def clean_real_name(value, *, field: str = "real_name", required: bool = True) -> str:
    """실명·조직 표시 이름 검증(IMPL-PLAN-13 §5.2). 공백 정리 후 1~50자, 글자 하나 이상.

    진짜 실명인지는 확인하지 않는다(본인인증 없음). 실패하면 ServiceError({field: 문구}).
    required=False면 빈 값을 ""로 돌려준다(조직 표시 이름: 비우면 계정 표시 이름).
    """
    v = " ".join(str(value or "").split())
    if not v:
        if required:
            raise ServiceError({field: "실명을 입력해 주세요."})  # COPY:real_name.required
        return v
    if len(v) > 50:
        raise ServiceError({field: "50자 이내로 입력해 주세요."})  # COPY:real_name.too_long
    ok = all(c in _NAME_PUNCT or unicodedata.category(c)[0] in "LM" for c in v)
    if not ok or not any(unicodedata.category(c)[0] == "L" for c in v):
        # COPY:real_name.invalid_chars
        raise ServiceError(
            {
                field: "글자를 포함해 입력해 주세요. 공백·마침표(.)·하이픈(-)·작은따옴표(')·가운뎃점(·) 외의 기호와 숫자는 사용할 수 없습니다."
            }
        )
    return v


def set_real_name(user, value) -> User:
    """계정 실명 저장(프로필·조직 설정 내 정보가 함께 쓴다). 실명 이력은 남기지 않는다(IMPL-PLAN-13 결정 5).

    orgs 0014가 남긴 충돌 후보는 저장하면 끝이다. 바뀌면 실명으로 표시하는 조직들의 이름 캐시를 비운다.
    """
    from orgs.names import forget_all

    new = clean_real_name(value)
    changed = new != user.real_name
    user.real_name = new
    user.settings.pop("real_name_candidates", None)
    user.save(update_fields=["real_name", "settings"])
    if changed:
        forget_all()
    return user


class RealNameRequired(Exception):
    """계정 실명이 비어 있다. API가 403 real_name_required로 돌려준다(api/api.py). 웹은 MemberInfoGate."""

    def __init__(self):
        self.url = settings.SITE_URL + reverse("profile")
        # COPY:real_name.gate_api
        super().__init__(f"유달리를 이용하려면 먼저 실명을 입력해 주세요: {self.url}")


def issue_link_code(user) -> str:
    """1회용 연결 코드. 다시 발급하면 이전 코드는 그 순간 무효다.

    연결은 이 코드로만 이뤄지므로 국외 이전 동의는 여기서 확인하면 봇 경로까지 막힌다."""
    require_consent(user, "discord")
    code = secrets.token_hex(4).upper()
    User.objects.filter(pk=user.pk).update(
        discord_link_code=code, discord_link_expires_at=timezone.now() + CODE_TTL
    )
    return code


@transaction.atomic
def link_discord(code: str, discord_user_id: str) -> User:
    code = (code or "").strip().upper()
    did = (discord_user_id or "").strip()
    if not did.isdecimal():
        raise ServiceError(
            {
                "discord_user_id": "Discord 사용자 ID 형식이 올바르지 않습니다. Discord에서 사용자 ID를 복사해 입력해 주세요."
            }
        )
    now = timezone.now()
    user = User.objects.filter(
        discord_link_code=code, discord_link_expires_at__gt=now, is_active=True
    ).first()
    if user is None:
        raise ServiceError({"code": "코드가 틀렸거나 만료됐습니다. 웹에서 다시 발급해 주세요."})

    # 이 snowflake를 들고 있던 옛 행에서 가져온다. 코드와 snowflake가 둘 다 증명된 이 순간,
    # 남의 행에 남아 있는 값이 틀린 것이다. 선점당해 영구히 잠기는 경로를 없앤다.
    User.objects.filter(discord_user_id=did).exclude(pk=user.pk).update(
        discord_user_id=None, discord_linked_at=None
    )
    # 코드 1회용: 조건부 UPDATE의 rowcount로 보장한다. 비울 때는 반드시 None
    # (""로 비우면 두 번째 사용자가 unique 제약에 걸린다).
    updated = User.objects.filter(pk=user.pk, discord_link_code=code).update(
        discord_user_id=did,
        discord_linked_at=now,
        discord_link_code=None,
        discord_link_expires_at=None,
    )
    if updated != 1:
        raise ServiceError(
            {"code": "이미 사용한 연결 코드입니다. 프로필에서 새 코드를 발급해 주세요."}
        )
    user.refresh_from_db()
    return user


def unlink_discord(user) -> None:
    User.objects.filter(pk=user.pk).update(
        discord_user_id=None,
        discord_linked_at=None,
        discord_link_code=None,
        discord_link_expires_at=None,
    )


def unlink_discord_by_id(discord_user_id: str) -> bool:
    """봇의 `연결해제`. 알림 수신 거부 수단을 겸한다."""
    n = User.objects.filter(discord_user_id=(discord_user_id or "").strip()).update(
        discord_user_id=None, discord_linked_at=None
    )
    return n == 1


def user_by_discord_id(discord_user_id: str):
    """봇 명령의 행위자. 연결이 증명된 활성 사용자만 돌려준다."""
    return resolve("discord", discord_user_id)


# ---------- 국외 이전 동의 ----------


GITHUB_ONLY_MSG = (
    "GitHub로만 로그인하는 계정입니다. 비밀번호를 먼저 설정하거나(운영자에게 비밀번호 재설정 "
    "링크를 요청해 주세요) 회원 탈퇴를 해 주세요."
)


def has_consent(user, target: str) -> bool:
    return Consent.objects.filter(user=user, target=target, withdrawn_at__isnull=True).exists()


CONSENT_GRACE = timedelta(days=30)


def consent_deadline():
    """동의 없는 기존 연결이 멈추는 날. 유예 시작일(settings.CONSENT_GRACE_START)이 없으면 None."""
    start = settings.CONSENT_GRACE_START
    return start + CONSENT_GRACE if start else None


def consent_active(user, target: str) -> bool:
    """이 사용자의 이 연결을 지금 써도 되는가. 연결을 쓰는 모든 경로가 이 함수 하나로 판정한다.

    유예 시작일이 없거나 유예 중이면 동의가 없어도 쓴다. 유예가 끝나면 동의가 있어야 쓴다.
    연결 정보는 지우지 않는다 — 동의하면 그 순간부터 다시 쓴다.
    """
    deadline = consent_deadline()
    if deadline is None or timezone.localdate() < deadline:
        return True
    return has_consent(user, target)


def paused_message(target: str) -> str:
    """유예가 끝나 멈춘 연결의 오류 문구. 동의 화면 주소를 함께 안내한다."""
    url = f"{settings.SITE_URL}{reverse('consent', args=[target])}"
    return (
        f"국외 이전 동의가 없어 {dict(TARGETS)[target]} 연결을 멈췄습니다. "
        f"{url} 에서 동의해 주세요."
    )


def discord_dm_id(user):
    """봇에게 넘기는 DM 수신자 ID. 동의 없이 멈춘 사람은 None — 봇은 미연결로 보고 보내지 않는다."""
    if user is None or not user.discord_user_id:
        return None
    # ponytail: 사람마다 동의를 한 번씩 묻는다(유예 뒤에만). 목록이 커서 느리면 요청 단위로 모아 묻는다.
    return user.discord_user_id if consent_active(user, "discord") else None


def require_consent(user, target: str) -> None:
    if not has_consent(user, target):
        raise ServiceError(
            {
                "consent": "국외 이전에 동의하지 않아 연결할 수 없습니다. 동의 내용을 확인하고 연결해 주세요."
            }
        )


def give_consent(user, target: str) -> Consent:
    """이미 동의했으면 그 기록을 그대로 둔다(처음 동의한 시각과 판이 남는다)."""
    if target not in NOTICES:
        raise ServiceError(
            {"target": "연결할 서비스를 확인하지 못했습니다. 동의 화면을 다시 열어 주세요."}
        )
    consent, _ = Consent.objects.get_or_create(
        user=user, target=target, withdrawn_at__isnull=True, defaults={"version": POLICY_VERSION}
    )
    return consent


def agree_terms(user) -> None:
    """로그인·가입 = 그때 시행 중인 이용약관·처리방침에 동의(로그인 화면에 고지). 판마다 한 행."""
    for doc, version in DOC_VERSIONS.items():
        TermsAgreement.objects.get_or_create(user=user, doc=doc, version=version)


def missing_consents(user) -> list[str]:
    """연결은 있는데 동의 기록이 없는 대상. 이 기능 전에 연결한 사용자다."""
    connected = {
        "github": GitHubIdentity.objects.filter(user=user).exists(),
        "discord": bool(user.discord_user_id),
        "ai": user.tokens.filter(for_ai=True, revoked_at__isnull=True).exists(),
    }
    return [t for t, on in connected.items() if on and not has_consent(user, t)]


@transaction.atomic
def withdraw_consent(user, target: str) -> bool:
    """동의를 철회하고 그 연결을 끊는다. 철회할 동의가 없었으면 False."""
    if target == "github" and not user.has_usable_password():
        # GitHub로만 가입한 사람은 연결을 끊으면 로그인할 길이 없다.
        raise ServiceError({"github": GITHUB_ONLY_MSG})
    now = timezone.now()
    if not Consent.objects.filter(user=user, target=target, withdrawn_at__isnull=True).update(
        withdrawn_at=now
    ):
        return False
    if target == "github":
        GitHubIdentity.objects.filter(user=user).delete()
    elif target == "discord":
        unlink_discord(user)
    elif target == "ai":
        # 사람용 토큰은 사용자 자신의 스크립트로 가므로 국외 이전이 아니다. 봇 토큰도 남긴다.
        for token in user.tokens.filter(for_ai=True, revoked_at__isnull=True):
            token.revoke()
        user.oauth_codes.filter(used_at__isnull=True).update(used_at=now)
    return True


# ---------- 개인 설정 ----------


def set_user_settings(user, data: dict) -> User:
    """개인 설정을 통째로 교체한다. 이력은 남기지 않는다."""
    user.settings = clean("user", data)
    user.save(update_fields=["settings"])
    return user


# ---------- 회원 탈퇴 ----------

DELETED_NAME = "탈퇴한 사용자"


def last_admin_orgs(user, orgs=None) -> list:
    """user가 유일한 관리자인 조직들. 이런 조직이 있으면 탈퇴할 수 없다(화면은 미리 알린다)."""
    from orgs.models import Organization, OrgMembership

    if orgs is None:
        orgs = Organization.objects.filter(memberships__user=user).distinct().order_by("pk")
    return [
        org
        for org in orgs
        if OrgMembership.objects.filter(org=org, user=user, role="admin").exists()
        and not OrgMembership.objects.filter(org=org, role="admin").exclude(user=user).exists()
    ]


@transaction.atomic
def withdraw(user, confirm: str) -> None:
    """회원 탈퇴. 되돌릴 수 없다(개인정보 처리 결정 A).

    User 행은 지우지 않고 익명화한다 — 태스크·문서·이력이 PROTECT로 이 행을 가리키고, 그 기록은
    조직의 업무 기록으로 남아야 하기 때문이다. 화면은 display_name을 쓰므로 "탈퇴한 사용자"로 보인다.
    """
    from django.contrib.sessions.models import Session

    from orgs.models import DiscordMemberPermission, Organization, OrgMembership, TeamMembership
    from orgs.names import forget_all
    from portfolio.models import PortfolioDraft
    from tasks.models import Notice, TodayItem

    user = User.objects.select_for_update().get(pk=user.pk)
    _check_withdraw_confirm(user, confirm)
    # 마지막 관리자 검사는 orgs.services.change_role·remove_member와 같은 잠금으로 직렬화한다.
    # 속한 조직을 모두 pk 순서로 잠근다 — 검사와 소속 삭제 사이에 역할이 바뀌는 틈을 없앤다.
    my_orgs = list(
        Organization.objects.select_for_update()
        .filter(pk__in=OrgMembership.objects.filter(user=user).values("org"))
        .order_by("pk")
    )
    if blocked := last_admin_orgs(user, my_orgs):
        raise ServiceError(
            {
                "org": f"'{blocked[0].name}' 조직의 마지막 관리자입니다. "
                "다른 구성원에게 관리자를 넘긴 뒤 탈퇴해 주세요."
            }
        )

    old_username = user.username
    _scrub_recordings(user, my_orgs)
    ApiToken.objects.filter(user=user).delete()  # AI용·사람용·MCP OAuth로 받은 토큰 모두
    OAuthCode.objects.filter(user=user).delete()
    # 동의 기록은 분쟁 대비로 1년 남긴다(purge_expired가 지운다). 탈퇴 시각을 철회 시각으로 둔다.
    Consent.objects.filter(user=user, withdrawn_at__isnull=True).update(withdrawn_at=timezone.now())
    IdempotencyKey.objects.filter(user=user).delete()
    GitHubIdentity.objects.filter(user=user).delete()
    TodayItem.objects.filter(user=user).delete()
    PortfolioDraft.objects.filter(owner=user).delete()  # 출처 스냅샷은 CASCADE
    Notice.objects.filter(user=user).delete()
    DiscordMemberPermission.objects.filter(user=user).delete()
    TeamMembership.objects.filter(user=user).delete()
    OrgMembership.objects.filter(user=user).delete()
    forget_all()
    user.owned_projects.clear()
    LoginLock.objects.filter(kind="user", key=old_username.lower()[:150]).delete()

    username = f"deleted-{user.pk}"
    if User.objects.filter(username=username).exclude(pk=user.pk).exists():
        # 누군가 이 아이디로 먼저 가입했다. 탈퇴를 막지 않도록 뒤에 난수를 붙인다.
        username = f"{username}-{secrets.token_hex(4)}"
    user.username = username
    user.display_name = DELETED_NAME
    user.real_name = ""
    user.email = user.first_name = user.last_name = ""
    user.set_unusable_password()
    user.is_active = user.is_staff = user.is_superuser = False
    user.discord_user_id = user.discord_link_code = None
    user.discord_link_expires_at = user.discord_linked_at = None
    user.settings = {}
    user.save()

    # ponytail: 세션 전체를 풀어 본다(O(세션 수)). 탈퇴는 드물다. 느려지면 세션에 user 색인을 둔다.
    uid = str(user.pk)
    stale = [s.pk for s in Session.objects.all() if s.get_decoded().get("_auth_user_id") == uid]
    Session.objects.filter(pk__in=stale).delete()


def _scrub_recordings(user, orgs) -> None:
    """회의 녹음 JSON의 탈퇴자 Discord ID·이름 스냅샷을 지운다. 회의록 자체는 업무 기록으로 남는다.

    진행 중인 회의의 진행자면 봇이 진행자 퇴장을 보낸 것과 같은 경로로 끝낸다 — 진행자의 Discord ID가
    사라진 채 회의가 이어지면 넘겨받기 요청 멘션이 깨진다.
    """
    from notes.models import VoiceRecording
    from notes.services import update_recording

    for rec in VoiceRecording.objects.filter(status="recording", host=user):
        update_recording(rec, status="transcribing", end_reason="host_left", stopped_by=user)
    # ponytail: 조직의 녹음을 다 훑는다(SQLite에 JSON contains가 없다). 녹음이 많아지면 참여자 표를 둔다.
    for rec in VoiceRecording.objects.filter(note__org__in=orgs).select_for_update():
        changed = False
        for p in rec.participants:
            if p.get("user_id") == user.pk:
                p.update(discord_user_id="", display_name=DELETED_NAME, discord_name="")
                changed = True
        for r in rec.host_requests:
            if r.get("requester_user_id") == user.pk:
                r["requester_discord_user_id"] = ""
                changed = True
        if changed:
            rec.save(update_fields=["participants", "host_requests"])


def _check_withdraw_confirm(user, confirm: str) -> None:
    """비밀번호가 있으면 비밀번호를, GitHub로만 가입했으면(비밀번호 없음) 아이디를 다시 받는다."""
    if user.has_usable_password():
        if not user.check_password(confirm or ""):
            raise ServiceError(
                {"confirm": "비밀번호가 일치하지 않습니다. 비밀번호를 다시 입력해 주세요."}
            )
    elif (confirm or "").strip() != user.username:
        raise ServiceError(
            {"confirm": "아이디가 일치하지 않습니다. 표시된 아이디를 다시 입력해 주세요."}
        )
