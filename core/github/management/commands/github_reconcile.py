from django.core.management.base import BaseCommand

from github.services import reconcile


class Command(BaseCommand):
    help = (
        "GitHub 보정: 10분 지난 연결의 이슈, 6시간 지난 identity의 저장소 권한을 맞춘다(5분마다)."
    )

    def handle(self, *args, **options):
        done = reconcile()
        self.stdout.write(
            f"github_reconcile 이슈 {done['issues']} 권한 {done['repos']} 실패 {done['failed']}"
        )
