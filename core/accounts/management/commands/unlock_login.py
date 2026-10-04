from django.core.management.base import BaseCommand

from accounts.auth import unlock


class Command(BaseCommand):
    help = "로그인·가입 잠금을 푼다. 인자는 아이디 또는 IP."

    def add_arguments(self, parser):
        parser.add_argument("key")

    def handle(self, *args, key, **options):
        self.stdout.write(f"{unlock(key)}개 행을 지웠습니다.")
