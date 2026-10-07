# 운영 콘솔(IMPL-PLAN-10 O0~O4 + Sol 반려 수정) 최종 승인 검토 — Fable, 2026-10-07

- 판정: **승인(배포 가능)**. 반드시 고칠 결함 없음. 아래 "배포 전 확인"의 운영 1회 확인은 배포 직후에 한다.
- 대상: `Seokyoung-Hong/Ochestration` HEAD `3663bdb` (`git log --oneline 6a11b1f..HEAD` 21건, 운영 콘솔 커밋 `244aab0`~`3663bdb`; IMPL-PLAN-11은 문서만 있고 코드 없음 — 범위 밖).
- 방법: 읽기·테스트만, 코드·git 변경 없음(`git status` 깨끗). 작성자 보고는 쓰지 않고 코드·실행으로 확인했다.
  - `cd core && uv run pytest -q` → **1475 passed**(SQLite). `discord_service` 179 passed, `mcp_server` 50 passed.
  - `ruff check` 0, `ruff format --check` 0, `makemigrations --check` 변경 없음(수용 기준 10.2-1).
  - 수정 전 커밋 `f917a8e`를 `git archive`로 임시 폴더에 풀고 새 회귀 테스트 `core/ops/test_review_fixes.py`(import 한 줄만 보정)를 돌림 → **14 failed / 6 passed**. 통과한 6개는 기존에도 막히던 `=1+1`과 평문 케이스뿐. 5건 모두 수정 전 코드에서 실제로 잡힌다.
  - 임시 `postgres:16-alpine` 컨테이너(포트 55432, 운영·로컬 DB와 무관)에 `migrate` 적용 후 `ops_opsauditlog`에 UPDATE·DELETE·TRUNCATE·`INSERT … ON CONFLICT DO UPDATE`·QuerySet `update()`/`delete()` 6종 시도 → **전부 `ops_opsauditlog is append-only`로 거부**, 행 보존. `pg_trigger`에 `ops_audit_no_update`·`ops_audit_no_truncate` 둘 다 활성(`O`). 같은 Postgres로 `ops`·`web/test_ops_*`·`api/test_record_backup.py` → 60 passed, 1 skipped(SQLite 전용).

## 1. Sol 반려 5건 — 근본 원인 수정 여부

| # | 결함 | 수정 | 근본 원인인가 | 회귀 테스트 |
|---|---|---|---|---|
| 1 | Gunicorn 접속 로그에 재설정 토큰 | `core/config/gunicorn_logging.py:14-19` `SecretLogger.setup()`이 `gunicorn.error`·`gunicorn.access` **로거 자체**에 `SecretFilter`를 단다. `core/entrypoint.sh:13` `--logger-class config.gunicorn_logging.SecretLogger`. 정규식도 `core/common/logging.py:13`에서 토큰 꼴과 무관하게 `/reset/<uid>/` 뒤를 통째로 가림(`set-password`만 제외) | 예. 핸들러가 아니라 로거에 필터를 달아 stdout·syslog·logconfig 어느 핸들러로 나가든 먼저 가린다. Gunicorn 소스 확인: `glogging.py:366-381` `access()`가 `self.access_log.info(fmt, atoms)`로 로거에 직접 쓰고, `setup()`은 자기 핸들러만 제거(`:203-206`)하므로 reload(`arbiter.py:120`) 때도 필터가 남고 가드(`any(isinstance…)`)로 중복되지 않는다 | `test_gunicorn_access_log_masks_reset_token`이 entrypoint.sh의 실제 플래그를 읽어 진짜 `gunicorn.config.Config`+`SecretLogger`로 요청 줄·Referer·error 로그를 찍고 토큰 부재와 `[redacted]`를 확인. 수정 전 FAIL 확인 |
| 2 | SQLite REPLACE·Postgres TRUNCATE | `core/ops/migrations/0001_initial.py:19-20` `BEFORE TRUNCATE … FOR EACH STATEMENT`, `:30-32` SQLite `BEFORE INSERT WHEN NEW.id IS NOT NULL AND EXISTS(같은 id)` ABORT. DOWN에 둘 다 추가 | 예. SQLite는 `recursive_triggers` 설정에 기대지 않고 같은 PK 삽입을 원천 거부. Postgres는 TRUNCATE 문장 트리거. `ON CONFLICT DO UPDATE`는 UPDATE 행 트리거에 걸림(실측) | `test_sqlite_insert_or_replace_cannot_overwrite_audit`(SQLite 실행), `test_postgres_trigger_blocks_truncate`(문자열). Postgres 실동작은 내가 위에서 실측 |
| 3 | record_backup 원자성 | `core/api/management/commands/record_backup.py:21-31` `transaction.atomic()` 안에서 `select_for_update()`→`update_or_create`→`audit()`. 실패 시 예외 종류만 담은 `CommandError`(`from None`). `scripts/backup.sh:14`·`restore-test.sh:9`는 stderr를 더는 버리지 않음 | 예 | `test_record_backup_is_atomic_and_error_has_no_secret`: audit에 `RuntimeError("postgres://pm:SECRETPW@…")` 주입 → 상태 행 없음·메시지에 비밀 없음. 수정 전 FAIL |
| 4 | IntegrationStatus.detail 임의 노출 | `core/api/models.py:6-37` `DETAIL_KEYS` allowlist + `clean_detail()`(스칼라만, 글은 `[A-Za-z0-9_.:+\-]{1,40}`). 저장 경로 2곳(`api/routers/integrations.py:26`, `record_backup.py:46`)과 표시 경로 2곳(`web/views/ops.py:65,149`, `templates/ops/system.html:10,23`) 모두 적용 | 예. 저장과 표시 양쪽. 이전에 저장된 행도 화면에서 걸러짐 | `test_status_detail_is_allowlisted_on_store_and_screen`(봇 토큰 POST→저장값 `{"job","sent"}`만, 오염 행 심고 `/ops/system` 본문에 5개 문자열 부재), `test_clean_detail_rejects_nested_and_free_text` |
| 5 | CSV 선행 제어문자 | `core/web/views/ops_audit.py:84-91` `lstrip(" \t\r\n")` 뒤 첫 글자와 TAB·CR 시작을 모두 위험으로 판정 | 예 | 8개 위험·5개 평문 파라미터 테스트. 수정 전 7개 FAIL |

- allowlist와 실제 보고 키 대조: Discord 봇(`discord_service/scheduler.py:121,150`)이 보내는 `job·org_id·hour·status·period_start·sent·skipped·failed·unknown·unlinked·opted_out·open_failed·recheck_failed·send_retry·reopened`는 모두 허용 목록에 있다. `error: str(e)`(`:126,155`)만 의도적으로 버려진다. `backup.sh:48`의 `stamp·files·bytes·offsite`, `restore-test.sh:29`의 `dump·tasks·users`도 허용. `IntegrationStatus.detail`의 다른 소비자 없음(grep).

## 2. 권한·감사·안전장치 — 코드로 확인

- 권한 경계: 모든 `/ops*` 뷰가 `ops_required`(`core/ops/access.py:7-16`, `is_staff` 아니면 404; `login_required`+`ModelBackend.get_user`가 비활성 계정을 거르므로 `is_active`도 암묵 충족) 또는 `superuser_required`(`:19-28`, export). 운영자 부여·회수는 뷰(`ops_users.py:122-123` root_only→404)와 services(`ops/services.py:111,117` `_require_superuser`) 2겹. 정지·재설정 대상이 운영자면 superuser만(`:97,140`), 자기 정지·자기 회수·superuser 회수 거부(`:95,118-122`). 조직 관리자는 `OrgMembership.role`이라 같은 데코레이터에 걸린다. 테스트 `test_only_staff_reaches_screens`(9개 URL 302/404/200), `test_user_pages_are_ops_only`.
- 감사 기록 append-only: Python `save()`/`delete()`(`ops/models.py:44-50`) + DB 트리거(위 실측) + `default_permissions=()`·admin 미등록. 금지 키 `FORBIDDEN_DETAIL_KEYS`(`services.py:19-35`)를 중첩까지 검사(`:40-48`), 테스트 4건. `actor` PROTECT.
- 변경 = 사유 5~300자(`:66-70`) + 위험 작업 재입력(`:73-75`) + `transaction.atomic` 안에서 audit(`_set_user:86`, `unlock_login:168`, `revoke_token:191`). 실패 시 되돌림은 Sol이 주입 재현. 확인 대화상자 `templates/ops/_confirm.html`에 `{% csrf_token %}`.
- 집계 전용: `ops_orgs.py`·`ops_access.py`·`ops_integrations.py`·`ops.py:system`이 `values()/annotate/aggregate`만 쓰고, 토큰 표(`_tokens.html`)는 `prefix[3:]`만. 런타임 테스트 `test_screens_show_no_work_content`가 태스크 제목·설명·프로젝트명·첨부 이름·알림 문구·토큰 라벨을 심어 모든 화면 본문 부재를 확인. export.json은 결정 Q2대로 superuser+사유+`export` 재입력+기록(`ops.py:200-216`), 조직 설정 비밀값은 설정됨/미설정으로(`:188-196`).
- Django admin: `config/urls.py:49` `has_permission = is_active and is_superuser`; `admin_view` 덮어쓰기(`:27-45`)가 `urlpatterns`보다 먼저라 모든 admin 뷰가 `admin.access`를 남김(jsi18n 제외, 거부 시도도 `allowed=False`); 스위치 `DJANGO_ADMIN_ENABLED` 기본 `"1"`(`settings.py:113`) → 기존 동작 유지, `0`이면 경로 자체 없음. 테스트 `test_admin_is_superuser_only_and_logged`·`test_admin_switch_off_is_404`. `ApiTokenAdmin.readonly_fields`에 `user·scope·expires_at`(`accounts/admin.py:38-47`).
- 재설정 링크: 발급은 사유+아이디 재입력, 정지 사용자 거부, 운영자 대상은 superuser(`services.py:131-150`); 링크는 감사 detail에 없고 운영자 세션에서 1회만 꺼냄(`ops_users.py:128-131`). 수신 측 `web/views/auth.py:109-131`: 토큰을 세션으로 옮기고 `set-password` 주소로 redirect(주소·Referer·이후 로그에 토큰 없음), `is_active=True`만 조회, `check_token`(비밀번호 해시 변경으로 1회용, `PASSWORD_RESET_TIMEOUT` 24h), 자동 로그인 없음, 성공 시 로그인 잠금도 해제. 테스트 `test_reset_link_is_shown_once_not_logged_and_single_use`·`test_reset_link_expires`.
- 설정 탭에서 운영 항목 제거(`settings/_tabs.html`), 아바타 메뉴 "운영 콘솔"만(`base.html:64`). 옛 `templates/ops.html` 삭제, 다른 템플릿에서 `ops_design`·`export_json`을 참조하는 곳 없음(grep). 기존 사용자 흐름이 깨지는 링크 없음.

## 3. 운영 배포 위험 평가

| 항목 | 평가 |
|---|---|
| `ops 0001` 트리거 | Postgres 16에서 실측 정상. `plpgsql`은 PG16 기본 설치. 트리거·함수 생성은 테이블 소유자(= migrate 실행 역할 `pm`)면 충분하고, compose의 `pm`은 컨테이너 DB의 superuser라 권한 문제 없음. 역방향(DROP) 포함 |
| `--logger-class` | gunicorn 26.2(`uv.lock`). `app/base.py:83-90` `chdir()`가 `/app`을 `sys.path`에 넣은 뒤(`:163,199`) CLI 인자를 `cfg.set`하므로 `config.gunicorn_logging` import는 `config.wsgi`와 같은 경로로 된다. `common/logging.py`는 Django 의존 없음(arbiter 단계에서 settings를 건드리지 않음). import 실패면 gunicorn이 기동 시 바로 죽으므로 배포 직후 로그 1줄로 판별 가능, 되돌리기는 플래그 한 줄 삭제 |
| `DJANGO_ADMIN_ENABLED` | 기본 켬. 변경점은 "staff만 있는 계정은 /admin 불가"뿐(사용자 결정 4) |
| 사용자 흐름 | 설정 탭·메뉴 외 변경 없음. 비운영자에게 `/ops*`는 전부터 접근 불가였음(403→404) |
| 문서 | `docs/BACKUP.md`에 결과 보고 절·SPEC 표 행, `OPERATIONS-DEPLOYMENT.md:73`에 admin 스위치, `.env.example:58-59`. 충분하나 아래 보완 권장 |

## 4. 반드시 고칠 것

- 없음.

## 5. 권장(배포를 막지 않음, 다음 커밋에서)

1. `docs/OPERATIONS-DEPLOYMENT.md:60` — 로그인 잠금 표 위치가 `/ops`가 아니라 `/ops/access`이고 해제에 사유가 필요하다. 한 줄 수정.
2. 같은 문서에 "운영 1회 확인"(아래 §6) 세 줄과, `--logger-class` 기동 실패 시 되돌리는 법(플래그 삭제) 한 줄.
3. 설계 §5.3(2)의 템플릿 정규식 테스트 `test_ops_templates_touch_no_content_fields`가 없다(수용 기준 10.2-4 "테스트 2종" 중 1종). 런타임 테스트가 대표 문자열로 같은 보장을 하고 있어 배포는 막지 않지만, 새 화면이 추가될 때 regex 테스트가 더 싸게 잡는다. 10줄.
4. Discord 봇 오류 문구(`error`)는 의도적으로 버려지므로 운영자는 `ok=false`만 본다. 시스템 카드 또는 BACKUP/OPERATIONS 문서에 "원인은 `docker compose logs discord` 확인" 한 줄.

## 6. 배포 전·직후 확인(운영에서 1회)

1. `docker compose up -d web` 후 `docker compose logs --tail 50 web`에 `class uri … invalid` 없이 `Booting worker`가 찍히고 `/healthz` 200.
2. `migrate`가 `ops.0001_initial`을 적용했는지(`web` 로그 또는 `/ops/system` "미적용 마이그레이션 0"). 그 뒤 psql에서 1회: `UPDATE ops_opsauditlog SET reason='x' WHERE id=(SELECT min(id) FROM ops_opsauditlog);` → `ERROR: ops_opsauditlog is append-only` (행이 없으면 `/admin/`에 한 번 들어가 `admin.access` 1건을 만든 뒤). `\d ops_opsauditlog`에 트리거 2개.
3. 시험 계정에 재설정 링크를 발급해 열고 `docker compose logs web | grep reset` → 요청 줄이 `GET [redacted] HTTP/1.1`, 토큰 원문 없음.
4. `scripts/backup.sh`를 수동 1회 실행 → `/ops/system` "마지막 백업 성공 시각"이 채워지고 `backup.record` 감사 기록 1건(actor `system`). cron이 `/opt/project-manager/scripts/backup.sh`(저장소 최신)를 가리키는지.
5. 운영 DB에 `is_staff and is_superuser`인 계정이 최소 1개 있는지(`/ops` 개요 타일 "운영 콘솔 권한 없는 최고 운영자" 0 권장). staff만 있던 계정은 이제 `/admin` 대신 `/ops`를 쓴다.
6. `.env`에 `DJANGO_ADMIN_ENABLED`를 넣지 않으면 켜진 상태다(기존과 같음).

## 7. 확인 불가·한계

- 운영 앞단(cloudflared·NPM)의 접속 로그에 재설정 URL이 남는지 — 앱 밖. 기존 로그에 이미 찍힌 토큰 유무도 미확인(토큰은 24시간·1회용이라 노출 창은 짧다).
- DB 트리거는 DB 소유자·superuser(`pm`)의 `ALTER TABLE … DISABLE TRIGGER`/`DROP TRIGGER`를 막지 못한다. 설계 §4.2의 계약은 "앱·raw SQL 경로"까지이며 DB 관리자 경로는 범위 밖. 운영 DB 역할 권한은 compose와 같다고 가정(실측은 컨테이너 기본 설정).
- Excel·LibreOffice에서 CSV `'` 접두 처리 실제 동작 미검증(OWASP 표준 방식).
- 운영 서버의 현재 `backup.sh` 버전·cron 등록 상태.
- 운영 DB의 기존 `IntegrationStatus.detail`에 민감값이 있는지 — 있더라도 화면에서는 allowlist로 걸러진다.
