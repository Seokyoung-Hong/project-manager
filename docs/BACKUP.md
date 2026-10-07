# 백업·복구

운영 서버(LXC 호스트)에서 `scripts/backup.sh`를 매일 돌립니다. 이 문서는 절차만 적습니다.

## 설치
```
15 4 * * * /opt/project-manager/scripts/backup.sh >> /var/log/pm-backup.log 2>&1
```
`chmod +x scripts/*.sh` 후 root cron에 등록합니다. 실패하면 비0으로 끝나므로 로그·cron 메일로 드러납니다.

## 결과 보고
`backup.sh`·`restore-test.sh`는 끝에서 `docker compose exec -T web python manage.py record_backup --job backup|restore-test --ok|--fail [--detail "k=v ..."]`로 core에 결과를 알립니다(`IntegrationStatus`, 운영 콘솔 시스템 카드에 표시). 성공이면 `detail.last_ok_at`, 실패면 `last_fail_at`을 갱신하며 실패해도 이전 `last_ok_at`은 남습니다. 보고가 실패(core 중단 등)해도 백업·시험 결과는 바뀌지 않습니다. 기록은 감사 기록 `backup.record`(actor `system`)로도 남습니다.

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

## SPEC 11.2 대응
| 항목(docs/SPEC.md 11.2) | 어떻게 충족 | 운영에서 할 일 |
|---|---|---|
| 마지막 백업 성공 시각 | `record_backup` → 운영 콘솔 시스템 카드 | 26시간 넘으면 로그 확인 |
| 매일 자동 백업 | `backup.sh` + cron | cron 등록, 로그 확인 |
| 보존 30일 | `KEEP_DAYS=30` 삭제 | 기본값 유지 |
| 운영 DB와 분리 보관 | `BACKUP_DIR`·`OFFSITE_DIR` | 다른 장비·스토리지 지정 |
| 사용자·프로젝트·태스크·댓글·이력·알림 설정 복구 | 전체 `pg_dump` | 복구 시험 때 행 수 대조 |
| 운영 전 복구 시험 1회 | `restore-test.sh` | 첫 배포 때 실행 |
| 복구 목표 = 최근 성공 일일 백업 | 일 1회 덤프 | 없음 |
| 구조화된 내보내기 | 이 스크립트 범위 밖(앱 기능) | 별도 구현 필요 |
| 복원 후 알림 재발송 방지 | `discord_*` 볼륨 tar | 복구 시 두 볼륨도 복원 |
