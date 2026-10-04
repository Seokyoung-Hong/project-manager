# 백업·복구

운영 서버(LXC 호스트)에서 `scripts/backup.sh`를 매일 돌립니다. 이 문서는 절차만 적습니다.

## 설치
```
15 4 * * * /opt/project-manager/scripts/backup.sh >> /var/log/pm-backup.log 2>&1
```
`chmod +x scripts/*.sh` 후 root cron에 등록합니다. 실패하면 비0으로 끝나므로 로그·cron 메일로 드러납니다.

## 환경변수(모두 선택)
| 이름 | 기본값 | 뜻 |
|---|---|---|
| `PM_DIR` | `/opt/project-manager` | compose.yml 위치 |
| `BACKUP_DIR` | `/srv/pm-backups` | 백업 저장 위치 |
| `KEEP_DAYS` | `30` | 보존 일수 |
| `OFFSITE_DIR` | 빈 값 | rsync 대상(마운트 경로 또는 `user@host:/path`). 비면 생략 |
| `PM_PROJECT` | `PM_DIR` 폴더명 | compose 프로젝트명(볼륨 이름 접두사) |

## 내용·보존
- `db-<시각>.dump`(pg_dump -Fc), `media_data`·`discord_data`·`discord_bot_data` 볼륨 `.tgz`, `SHA256-<시각>.txt`.
- 30일이 지난 파일은 삭제합니다. 같은 장비에만 두지 말고 `OFFSITE_DIR`로 다른 저장소에 둡니다.
- `discord_*` 볼륨을 복원하지 않으면 과거 알림이 다시 발송될 수 있습니다.
- 아직 없는 볼륨(예: 첨부 도입 전 `media_data`)은 경고만 하고 건너뜁니다.

## 복구 절차
1. `docker compose stop web discord discord-bot mcp`
2. `docker compose exec -T db dropdb -U pm pm && docker compose exec -T db createdb -U pm pm`
3. `docker compose exec -T db pg_restore -U pm -d pm --no-owner < $BACKUP_DIR/db-<시각>.dump`
4. 볼륨 복원(볼륨마다): `docker run --rm -v <프로젝트>_<볼륨>:/v -v $BACKUP_DIR:/b alpine sh -c "rm -rf /v/* && tar xzf /b/<볼륨>-<시각>.tgz -C /v"`
5. `docker compose up -d` 후 `/healthz` 확인, 로그인·태스크 목록·첨부 열기를 눈으로 확인합니다.

## 복구 시험
`scripts/restore-test.sh`가 최신 덤프를 임시 컨테이너에 복원해 `OK <파일> tasks=<n> users=<m>`을 출력합니다(운영 DB 무영향).
첫 배포 때 1회, 이후 분기 1회 실행하고 행 수가 운영과 비슷한지 봅니다.
