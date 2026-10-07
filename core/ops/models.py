from django.conf import settings
from django.db import models


class OpsAuditLog(models.Model):
    """서비스 운영자가 한 일. append-only — save()는 삽입만, update()·delete()는 DB 트리거가 막는다."""

    ACTIONS = [
        ("user.suspend", "사용자 정지"),
        ("user.reactivate", "사용자 재활성"),
        ("user.reset_link", "비밀번호 재설정 링크 발급"),
        ("user.unlock", "로그인 잠금 해제"),
        ("user.grant_staff", "운영자 권한 부여"),
        ("user.revoke_staff", "운영자 권한 회수"),
        ("token.revoke", "토큰 폐기"),
        ("export.json", "운영 데이터 내보내기"),
        ("audit.export", "감사 기록 내보내기"),
        ("admin.access", "Django 관리 화면 접근"),
        ("backup.record", "백업 결과 기록"),
    ]
    created_at = models.DateTimeField(auto_now_add=True)
    actor = models.ForeignKey(
        settings.AUTH_USER_MODEL, on_delete=models.PROTECT, null=True, related_name="+"
    )
    actor_username = models.CharField(max_length=150)  # 계정이 바뀌어도 당시 이름이 남는다
    action = models.CharField(max_length=30, choices=ACTIONS)
    target_type = models.CharField(max_length=20, blank=True)  # user|token|login|admin|backup|audit
    target_id = models.PositiveBigIntegerField(null=True, blank=True)
    target_label = models.CharField(max_length=200, blank=True)
    reason = models.CharField(max_length=300, blank=True)  # 사람이 한 변경은 필수(services가 검사)
    # {"before": …, "after": …, "method": "POST"} 등. 비밀값 금지(services.FORBIDDEN_DETAIL_KEYS)
    detail = models.JSONField(default=dict, blank=True)
    ip = models.CharField(max_length=45, blank=True)

    class Meta:
        ordering = ["-id"]
        default_permissions = ()  # Django 관리 화면에 등록하지 않는다
        indexes = [
            models.Index(fields=["created_at"]),
            models.Index(fields=["action"]),
            models.Index(fields=["target_type", "target_id"]),
        ]

    def save(self, *a, **kw):
        if self.pk:
            raise RuntimeError("감사 기록은 고칠 수 없습니다.")
        super().save(*a, **kw)

    def delete(self, *a, **kw):
        raise RuntimeError("감사 기록은 지울 수 없습니다.")
