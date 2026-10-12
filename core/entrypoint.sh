#!/bin/sh
set -e
python manage.py migrate --noinput
python manage.py collectstatic --noinput
# SSE(/events)는 연결을 열어 둔다. 기본 sync 워커는 연결 하나가 워커 하나를 통째로 막으므로
# 스레드 워커를 쓴다 — 동시에 볼 수 있는 사람 수는 workers × threads다.
# 실시간 연결(WebSocket·SSE)은 realtime 컨테이너가 받으므로 web은 스트림을 열어 두지 않는다.
# 스트림은 워커당 events.MAX_STREAMS(24)개까지 — 나머지 스레드는 페이지 요청 몫이다.
# 접속 로그는 끈다(처리방침: 앱에는 IP를 남기지 않고 접속 로그는 NPM이 90일 보관). 오류 로그는 SecretFilter를 거쳐 유지한다.
exec gunicorn config.wsgi:application \
  --bind 0.0.0.0:8000 --worker-class gthread --workers 2 --threads 32 --timeout 90 \
  --forwarded-allow-ips="*" --error-logfile - \
  --logger-class config.gunicorn_logging.SecretLogger
