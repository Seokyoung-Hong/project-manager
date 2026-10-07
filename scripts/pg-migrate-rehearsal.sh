#!/bin/sh
# 마이그레이션 리허설(Postgres). 임시 컨테이너에 라운드 시작 상태를 만들고 HEAD까지 migrate해 데이터 보존을 본다.
# SQLite 테스트가 못 잡는 Postgres 전용 실패(지연 FK 트리거 등)를 배포 전에 잡는다. Docker가 필요하다.
# 사용: scripts/pg-migrate-rehearsal.sh [추가 pytest 인자]   (포트는 PG_PORT, 기본 55433)
set -eu
NAME="pm-pg-rehearsal-$$"
PORT="${PG_PORT:-55433}"
if ! docker version >/dev/null 2>&1; then
  echo "Docker가 없어 리허설을 건너뜁니다." >&2
  exit 0
fi
docker run -d --rm --name "$NAME" -e POSTGRES_PASSWORD=pw -e POSTGRES_DB=pm -p "$PORT:5432" postgres:16-alpine >/dev/null
trap 'docker stop "$NAME" >/dev/null 2>&1 || true' EXIT
# 이미지 초기화 중 한 번 재시작하므로 연속 두 번 준비될 때까지 기다린다.
ok=0
for _ in $(seq 1 60); do
  if docker exec "$NAME" pg_isready -U postgres -h 127.0.0.1 >/dev/null 2>&1; then ok=$((ok + 1)); else ok=0; fi
  [ "$ok" -ge 2 ] && break
  sleep 1
done
cd "$(dirname "$0")/../core"
DATABASE_URL="postgres://postgres:pw@127.0.0.1:$PORT/pm" uv run pytest -q \
  projects/test_pg_rehearsal.py notes/test_migrate_doc.py \
  projects/test_docs.py::test_migration_0012_keeps_project_docs \
  tasks/test_group_review.py "$@"
