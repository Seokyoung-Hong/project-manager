#!/bin/sh
set -e
python manage.py migrate --noinput
python manage.py collectstatic --noinput
# SSE(/events)는 연결을 열어 둔다. 기본 sync 워커는 연결 하나가 워커 하나를 통째로 막으므로
# 스레드 워커를 쓴다 — 동시에 볼 수 있는 사람 수는 workers × threads다.
# --timeout은 스트림 수명(events.STREAM_SECONDS=50초)보다 길어야 한다.
# 스트림은 워커당 events.MAX_STREAMS(24)개까지 — 나머지 스레드는 페이지 요청 몫이다.
# 접속 로그도 SecretFilter를 거친다(config/gunicorn_logging.py) — 재설정 링크 토큰이 남지 않게.
exec gunicorn config.wsgi:application \
  --bind 0.0.0.0:8000 --worker-class gthread --workers 2 --threads 32 --timeout 90 \
  --forwarded-allow-ips="*" --access-logfile - --error-logfile - \
  --logger-class config.gunicorn_logging.SecretLogger
