#!/usr/bin/env bash
# 복구 시험: 최신 db-*.dump를 임시 Postgres에 복원해 핵심 표 행 수를 찍는다. 운영 DB는 건드리지 않는다.
set -euo pipefail

BACKUP_DIR=${BACKUP_DIR:-/srv/pm-backups}
PM_DIR=${PM_DIR:-/opt/project-manager}

# 결과를 core(운영 콘솔)에 알린다. 보고가 실패해도 시험 결과는 바꾸지 않는다.
report() { docker compose -f "$PM_DIR/compose.yml" exec -T web python manage.py record_backup --job restore-test "$@" >/dev/null || true; }
trap 'report --fail' ERR
DUMP=$(ls -1t "$BACKUP_DIR"/db-*.dump 2>/dev/null | head -n1 || true)
[ -n "$DUMP" ] || { echo "백업 없음: $BACKUP_DIR" >&2; exit 1; }

NAME=pm-restore-test-$$
trap 'docker rm -f "$NAME" >/dev/null 2>&1 || true' EXIT
docker run -d --name "$NAME" -e POSTGRES_DB=pm -e POSTGRES_USER=pm -e POSTGRES_PASSWORD=test postgres:16-alpine >/dev/null
for _ in $(seq 1 30); do
  docker exec "$NAME" pg_isready -U pm -d pm >/dev/null 2>&1 && break
  sleep 1
done
docker exec "$NAME" pg_isready -U pm -d pm >/dev/null

docker exec -i "$NAME" pg_restore -U pm -d pm --no-owner < "$DUMP"
q() { docker exec "$NAME" psql -U pm -d pm -tA -c "SELECT count(*) FROM $1"; }
tasks=$(q tasks_task); users=$(q accounts_user)
trap - ERR
report --ok --detail "dump=$(basename "$DUMP") tasks=$tasks users=$users"
echo "OK $(basename "$DUMP") tasks=$tasks users=$users"
