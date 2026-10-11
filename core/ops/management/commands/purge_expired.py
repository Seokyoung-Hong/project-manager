from datetime import timedelta

from django.core.management import call_command
from django.core.management.base import BaseCommand
from django.db.models import Q
from django.utils import timezone

from accounts.models import ApiToken, Consent, LoginLock, OAuthCode


def purge_tokens():
    """만료된 AI용 토큰. 철회만 된 토큰은 목록 표시용이라 남긴다."""
    return ApiToken.objects.filter(expires_at__lt=timezone.now()).delete()[0]


def purge_oauth_codes():
    """인가 코드는 10분짜리다. 하루 지나면 쓴 것이든 안 쓴 것이든 지운다."""
    return OAuthCode.objects.filter(created_at__lt=timezone.now() - timedelta(days=1)).delete()[0]


def purge_login_locks():
    """로그인 실패 기록(아이디·IP 포함) 하루 보관. 아직 잠겨 있는 행은 남긴다."""
    now = timezone.now()
    return (
        LoginLock.objects.filter(updated_at__lt=now - timedelta(days=1))
        .filter(Q(locked_until__isnull=True) | Q(locked_until__lt=now))
        .delete()[0]
    )


def purge_withdrawn_consents():
    """탈퇴자의 국외 이전 동의 기록은 분쟁 대비로 1년 보관한다(DECISIONS 2차 1번).

    탈퇴 시각 칸이 없어 탈퇴 때 찍은 철회 시각으로 센다. 탈퇴 전에 철회한 행은 더 일찍 지워진다.
    """
    return Consent.objects.filter(
        user__is_active=False,
        user__username__startswith="deleted-",
        withdrawn_at__lt=timezone.now() - timedelta(days=365),
    ).delete()[0]


class Command(BaseCommand):
    help = "기한이 지난 개인정보 행을 지운다(compose의 purge 서비스가 하루 한 번 부른다). 한 작업이 실패해도 나머지는 돈다."

    def handle(self, *a, **kw):
        jobs = [
            ("감사 기록", lambda: call_command("purge_audit_log", stdout=self.stdout)),  # 365일
            ("만료 세션", lambda: call_command("clearsessions")),
            ("만료 토큰", purge_tokens),
            ("인가 코드", purge_oauth_codes),
            ("로그인 잠금 기록", purge_login_locks),
            ("탈퇴자 동의 기록", purge_withdrawn_consents),
        ]
        failed = []
        for name, job in jobs:
            try:
                n = job()
                self.stdout.write(f"{name}: {'완료' if n is None else f'{n}건 삭제'}")
            except Exception as e:  # 하나가 죽어도 다음 작업은 돈다
                failed.append(name)
                self.stderr.write(f"{name} 실패: {e!r}")
        if failed:
            raise SystemExit(f"실패: {', '.join(failed)}")
