"""외부 계정 식별자(subject) → PM 사용자. 공급자가 늘어도 찾는 자리는 여기 하나다.

연결·해제(accounts/services.link_discord, GitHub 콜백)는 각자 자리에 그대로 있다.
"""

from .models import User

PROVIDERS = ("github", "discord")


def resolve(provider: str, subject: str):
    """subject(GitHub id·Discord snowflake)로 활성 User를 찾는다. 없으면 None.

    github → GitHubIdentity.github_id, discord → User.discord_user_id(+discord_linked_at not null).
    # ponytail: 저장은 두 곳에 그대로 둔다. 세 번째 공급자(oidc)가 생기면 ExternalIdentity 표(§4.4)를 만들고
    # 이 함수만 그 표를 먼저 보게 바꾼다.
    """
    subject = (subject or "").strip()
    if not subject:
        return None
    if provider == "github":
        from github.models import GitHubIdentity  # github 앱이 accounts에 기대므로 여기서만 부른다

        if not subject.isdecimal():
            return None
        identity = (
            GitHubIdentity.objects.select_related("user")
            .filter(github_id=int(subject), user__is_active=True)
            .first()
        )
        return identity.user if identity else None
    if provider == "discord":
        return User.objects.filter(
            discord_user_id=subject, discord_linked_at__isnull=False, is_active=True
        ).first()
    raise ValueError(f"모르는 공급자: {provider}")


def identities(user) -> dict[str, str]:
    """{"github": "@login", "discord": "111…"} 프로필 화면용."""
    out = {}
    gh = getattr(user, "github", None)  # 역방향 OneToOne이 없으면 AttributeError 계열
    if gh:
        out["github"] = f"@{gh.login}"
    if user.discord_user_id and user.discord_linked_at:
        out["discord"] = user.discord_user_id
    return out
