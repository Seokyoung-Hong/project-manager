#!/usr/bin/env bash
# 유달리 일일 백업: DB 덤프 + 볼륨 tar + 보존 정리 + 오프사이트 복사.
# env: PM_DIR, BACKUP_DIR, KEEP_DAYS, OFFSITE_DIR(비면 생략), PM_PROJECT(compose 프로젝트명, 볼륨 접두사)
set -euo pipefail

PM_DIR=${PM_DIR:-/opt/project-manager}
BACKUP_DIR=${BACKUP_DIR:-/srv/pm-backups}
KEEP_DAYS=${KEEP_DAYS:-30}
OFFSITE_DIR=${OFFSITE_DIR:-}
PM_PROJECT=${PM_PROJECT:-$(basename "$PM_DIR")}
STAMP=$(date +%Y%m%d-%H%M%S)

mkdir -p "$BACKUP_DIR"
cd "$BACKUP_DIR"

# 실패한 덤프가 남아 복구 시험에 뽑히지 않도록 임시 이름으로 받고 성공하면 바꾼다.
docker compose -f "$PM_DIR/compose.yml" exec -T db pg_dump -U pm -d pm -Fc > "db-$STAMP.dump.part"
[ -s "db-$STAMP.dump.part" ]
mv "db-$STAMP.dump.part" "db-$STAMP.dump"
files=("db-$STAMP.dump")

for vol in media_data discord_data discord_bot_data; do
  full="${PM_PROJECT}_${vol}"
  if ! docker volume inspect "$full" >/dev/null 2>&1; then
    echo "건너뜀: 볼륨 없음 $full" >&2   # 아직 배포 전인 볼륨(예: media_data)
    continue
  fi
  docker run --rm -v "$full:/v:ro" -v "$BACKUP_DIR:/b" alpine tar czf "/b/$vol-$STAMP.tgz" -C /v .
  files+=("$vol-$STAMP.tgz")
done

sha256sum "${files[@]}" > "SHA256-$STAMP.txt"

find "$BACKUP_DIR" -maxdepth 1 -type f -mtime +"$KEEP_DAYS" -delete

if [ -n "$OFFSITE_DIR" ]; then
  # OFFSITE_DIR은 rsync 대상(로컬 마운트 경로 또는 user@host:/path).
  rsync -a --delete "$BACKUP_DIR/" "$OFFSITE_DIR/"
fi

echo "OK $STAMP ${files[*]}"
