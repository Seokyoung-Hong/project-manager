# 운영 콘솔 O0~O4 교차 검토

- 판정: **반려**. 재설정 자격증명의 접속 로그 노출과 감사 기록 append-only 우회를 먼저 수정해야 한다.
- 대상: `f917a8e2bdba9f8b361c8deb22b8deacafa306d3` (`git log --oneline -12` 확인, 최상단 운영 콘솔 O1 병합).
- 방법: 읽기·테스트 실행만 수행. 저장소 코드 및 git 상태 변경 없음. 추가 재현은 Django 설정의 DB를 SQLite `:memory:`로 바꾼 별도 프로세스에서 실행했다.
- 전체 테스트: `cd core && uv run pytest -q` → **1455 passed, 1152 warnings in 37.98s**, 종료 코드 0. 경고는 Django 6 전환, staticfiles 디렉터리 부재, Pydantic·Ninja 사용 중단 예정 API 등이었다.

## 결함

### 1. 상 — Gunicorn 접속 로그에 최초 재설정 토큰이 남는다

- 위치: `core/entrypoint.sh:11`, `core/config/settings.py:141`, `core/web/views/auth.py:114`.
- 근거: 운영 명령은 `--access-logfile -`를 켠다. Django 설정은 root의 console handler에만 `SecretFilter`를 붙이고, Gunicorn의 기존 access handler에는 붙이지 않는다. 설치된 Gunicorn 소스 `core/.venv/Lib/site-packages/gunicorn/glogging.py:187`에서 access logger의 `propagate=False`가 확인되고, 같은 파일 `:223`, `:437`에서 별도 StreamHandler를 만든다.
- 재현: Gunicorn과 같은 기존 `gunicorn.access` logger(독립 handler, propagate=False)에 프로젝트의 `LOGGING`을 적용한 뒤 테스트용 `GET /reset/Mg/cxyz12-0123456789abcdef0123456789abcdef HTTP/1.1`를 기록했다. handler 출력에 토큰 원문이 그대로 남았다. 실제 Gunicorn 서버 실행 대신 로깅 구성과 설치 소스에 근거한 재현이다.
- 영향: `/set-password`로의 리다이렉트는 최초 요청 로그를 지우지 않는다. 아직 사용하지 않은 24시간 재설정 자격증명을 로그 열람자가 획득할 수 있다. `SecretFilter` 단위 테스트(`core/web/test_ops_users.py:134`)는 필터의 실행 여부를 검증하지 않는다.
- 권장 수정: Gunicorn access handler에도 필터를 직접 적용하는 logger class 또는 Gunicorn용 logconfig를 사용하거나, 접근 로그의 reset 경로를 구조적으로 제거한다. 최초 요청과 Referer atom을 포함한 실제 배포 로깅 구성 테스트를 추가한다. 앞단 프록시 로그는 별도로 확인한다.

### 2. 상 — SQLite REPLACE로 기존 감사 기록을 덮어쓸 수 있다

- 위치: `core/ops/migrations/0001_initial.py:18` (`SQLITE_UP`), `core/ops/models.py:44`.
- 근거: UPDATE·DELETE 트리거는 있지만 동일 PK를 다시 삽입하는 경로를 차단하지 않는다. SQLite REPLACE가 수행하는 암묵적 삭제는 기본 `recursive_triggers=0`에서 DELETE 트리거를 거치지 않는다. ORM save 제한도 raw SQL에는 적용되지 않는다.
- 재현: 전체 마이그레이션을 적용한 격리 SQLite DB에서 감사 행을 하나 만들고, `PRAGMA recursive_triggers`가 `(0,)`임을 확인했다. 다음 SQL 실행 후 `refresh_from_db()`의 reason이 `original`에서 `tampered`로 바뀌었다. 오류는 발생하지 않았다.

```sql
INSERT OR REPLACE INTO ops_opsauditlog
SELECT id, created_at, actor_username, action, target_type, target_id,
       target_label, 'tampered', detail, ip, actor_id
FROM ops_opsauditlog WHERE id = 1;
```

- 영향: 요구한 raw SQL까지의 append-only 불변식이 깨진다. HTTP 사용자에게 raw SQL 접근 경로를 발견했다는 뜻은 아니며, DB 수준 보호 계약의 결함이다.
- 권장 수정: SQLite BEFORE INSERT 트리거에서 기존 PK 존재 시 거부하도록 해 REPLACE를 차단한다. 연결별 recursive_triggers 설정에만 의존하지 않는 편이 안전하다. 기존 UPDATE·DELETE 및 bulk_update 검증과 별개로 REPLACE 회귀 검증이 필요하다.
- 추가 정적 결함: PostgreSQL 트리거(`core/ops/migrations/0001_initial.py:11`)도 UPDATE·DELETE 행 트리거뿐이어서 TRUNCATE를 막지 않는다. PostgreSQL에서 실행 검증하지 않았으며 운영 DB 역할의 TRUNCATE 권한은 확인 불가다. BEFORE TRUNCATE statement trigger와 실행 역할 권한 제한을 검토한다.

### 3. 중 — 백업 상태 변경과 감사 기록이 하나의 트랜잭션이 아니다

- 위치: `core/api/management/commands/record_backup.py:25`, `:28`.
- 근거: `update_or_create()`는 먼저 자체 트랜잭션을 끝내고 이후 `audit()`가 호출된다. 두 동작을 감싸는 `transaction.atomic()`이 없다.
- 재현: 별도 메모리 DB에서 해당 명령의 `audit`을 RuntimeError로 대체한 후 `record_backup --ok`를 실행했다. 명령은 실패했으나 `IntegrationStatus.objects.filter(name='backup', ok=True).exists()`가 True였다.
- 영향: 감사 기록이 없는 백업 성공 상태가 남는다. `scripts/backup.sh:14`는 보고 명령 실패를 무시하므로 이 불일치가 백업 실행자에게도 드러나지 않는다.
- 권장 수정: 상태 갱신과 감사 기록을 하나의 atomic 블록으로 감싼다. 실제 백업 성공과 상태 보고 성공의 구분은 유지하되, 보고 실패 시 stderr에 비밀 없는 운영 메시지를 남기는 것을 검토한다.

### 4. 중 — 시스템 화면이 임의 통합 detail을 그대로 노출한다

- 위치: `core/web/views/ops.py:146`, `core/web/templates/ops/system.html:10`, `:23`.
- 근거: 모든 IntegrationStatus 행을 가져와 detail의 모든 키와 값을 렌더링한다. 상태 보고 API는 봇 토큰만 허용하지만, `core/api/schemas.py:296`의 detail은 임의 dict이며 `core/api/routers/integrations.py:22`에서 그대로 저장한다. `record_backup --detail`도 임의 키를 저장한다(`core/api/management/commands/record_backup.py:23`).
- 재현: 격리 DB에 Discord 상태 detail로 `{'error': 'REVIEW_PRIVATE_TASK_BODY', 'token': 'REVIEW_SECRET_TOKEN'}`를 넣고 서비스 운영자로 `/ops/system`을 GET했다. 두 시험 문자열이 응답 본문에 모두 나타났다.
- 영향: 집계만 표시한다는 계약을 화면 경계에서 강제하지 않는다. 봇이 오류에 업무 문구·자격증명을 포함하면 그대로 운영 콘솔에 나타날 수 있다. 현재 운영 DB에 실제 민감값이 존재한다는 증거는 없다.
- 권장 수정: 상태별 집계 항목 allowlist로 표시용 dict를 만들고 임의 오류 메시지·중첩 dict·비밀 키를 렌더링하지 않는다. 저장 시 입력 스키마도 좁힌다. 백업 detail 표시 경로에도 동일하게 적용한다.

### 5. 하 — CSV 수식 방어가 선행 제어문자를 처리하지 않는다

- 위치: `core/web/views/ops_audit.py:84`.
- 근거: `_cell`은 첫 문자만 `=+-@`와 비교한다. TAB·CR·LF 뒤에 수식 시작 문자가 오는 값은 그대로 내보낸다. 사유는 strip되고 일반 아이디도 검증되므로, 현재 HTTP 경로에서 공격자가 이런 접두어를 가진 값을 넣는 경로는 확인하지 못했다. 다만 target_label 자체에는 정규화가 없고(`core/ops/services.py:63`), export helper는 해당 문자열을 안전하게 처리하지 않는다.
- 재현: `_cell('=1+1')`은 `"'=1+1"`이나 `_cell('\t=1+1')`, `_cell('\r=1+1')`, `_cell('\n=1+1')`은 입력을 그대로 반환했다. Excel·LibreOffice에서 실제 수식 실행은 검증하지 않았다.
- 영향: 선행 제어문자를 처리하는 스프레드시트의 CSV 가져오기 동작에 따라 방어가 우회될 수 있다. csv.writer의 quoting만으로 수식 의미가 없어지지는 않는다.
- 권장 수정: 제어문자와 선행 공백을 고려해 수식 시작 여부를 판단하고 텍스트 셀로 안전하게 내보낸다. 지원하는 실제 스프레드시트의 열기·가져오기 동작으로 한 번 검증한다.

## 확인한 보호 장치

- 모든 대상 ops 뷰는 ops_required 또는 superuser_required를 사용한다. 일반 사용자의 HTMX GET 13개 경로(목록·상세·변경 대화상자·CSV·JSON 포함)를 추가 확인했고 모두 404였다(`core/ops/access.py:7`, `core/web/urls.py:204`). 조직 관리자는 User.is_staff와 별개인 OrgMembership.role이므로 같은 데코레이터 경계를 적용받는다.
- Django admin은 is_active와 is_superuser를 요구하고, 스위치가 꺼지면 경로를 등록하지 않는다. admin.access는 원래 admin 뷰 실행 전에 기록된다(`core/config/urls.py:38`, `:53`, `:61`).
- 사용자 정지·권한 부여/회수·재설정 링크·토큰 폐기·JSON 내보내기는 서버에서 사유와 위험 확인값을 검사한다. 운영자 대상 정지·재설정에는 최고 운영자 검사가 있다(`core/ops/services.py:70`, `:105`, `:140`, `:186`, `:208`).
- 사용자 변경·잠금 해제·토큰 폐기는 transaction.atomic 안에서 기록된다. audit 실패를 주입한 정지 작업에서 is_active가 True로 보존됨을 추가 재현했다(`core/ops/services.py:91`, `:168`, `:191`).
- CSRF middleware와 폼 토큰이 있으며, enforce_csrf_checks=True로 토큰 없는 정지 POST가 403임을 확인했다(`core/config/settings.py:52`, `core/web/templates/ops/_confirm.html:2`).
- 순차 재설정은 해시 변경으로 1회용, 만료 검사, 정지 사용자 거부, 자동 로그인 없음, 토큰 없는 폼 주소 전환을 제공한다. 감사 detail에는 링크를 넣지 않고 운영자 세션에서 한 번 꺼낸다(`core/web/views/auth.py:112`, `:118`, `:122`, `:126`, `core/web/views/ops_users.py:129`).
- 업무 모델의 제목·본문을 직접 보여 주는 쿼리·템플릿 경로는 대상 화면에서 찾지 못했다. 다만 위 임의 detail 경로는 이 보장을 깨뜨린다.

## 확인 불가

- 실제 PostgreSQL의 트리거 실행 및 TRUNCATE 실행 권한. 기존 테스트도 PostgreSQL 부분은 SQL 문자열 검사만 한다(`core/ops/tests.py:59`).
- 운영 프록시·Cloudflare·Gunicorn 실제 컨테이너의 로그 설정과 기존 로그 내 토큰 유무. 로깅 결함은 저장소 시작 명령·설치 소스·동일 logger 구성 재현으로 확인했다.
- 실제 Excel·LibreOffice CSV 실행 결과와 운영 상태 detail에 민감 업무값이 이미 있는지.
- 동시 요청에서의 재설정 토큰 사용 경쟁과 세션 고정 공격의 종단 재현. 기본 로그인은 django.contrib.auth.login을 사용하며 성공한 재설정은 자동 로그인하지 않는다(`core/accounts/auth.py:104`, `core/web/views/auth.py:129`).
- 실제 Docker 백업·복구와 오프사이트 전송. 스크립트는 읽기 검토했고 명령의 DB 동작만 격리 재현했다.

