from django.contrib import admin
from django.contrib.auth.admin import UserAdmin

from .models import ApiToken, User


@admin.register(User)
class CustomUserAdmin(UserAdmin):
    """discord_user_id는 admin에서도 손으로 넣지 못한다.

    증명 없이 심을 수 있으면 코드 교환 연결이 무의미해진다. 연결은 웹의 [Discord 연결] →
    DM `연결 <코드>`로만, 해제는 웹의 [연결 해제]로.
    """

    list_display = ("username", "display_name", "discord_user_id", "is_active", "is_superuser")
    readonly_fields = ("discord_user_id", "discord_linked_at")
    fieldsets = UserAdmin.fieldsets + (
        (
            "프로필",
            {"fields": ("display_name", "auto_pull_days", "discord_user_id", "discord_linked_at")},
        ),
    )


@admin.register(ApiToken)
class ApiTokenAdmin(admin.ModelAdmin):
    list_display = ("prefix", "user", "name", "scope", "for_ai", "created_at", "expires_at", "revoked_at")
    readonly_fields = ("prefix", "key_hash", "for_ai", "created_at", "last_used_at")
