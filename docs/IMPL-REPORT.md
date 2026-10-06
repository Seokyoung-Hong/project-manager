# 구현 완료 보고서

작성일: 2026-09-10
범위: [GUIDE-00](GUIDE-00-rules.md) ~ [GUIDE-04](GUIDE-04-deploy.md) 전부 (core Step 0~7, discord_service, mcp_server, 배포 산출물)
브랜치: `claude/project-folder-docs-impl-c997ff`

## 요약

| 파트 | 테스트 (SQLite) | 테스트 (Postgres 16) | ruff check | ruff format |
|---|---|---|---|---|
| `core/` | **145 passed**, skip 0 | 이 개정에서는 **부분**(아래) | 0 | 통과 |
| `discord_service/` | **58 passed**, skip 0 | (DB 미사용) | 0 | 통과 |
| `mcp_server/` | **16 passed**, skip 0 | (DB 미사용) | 0 | 통과 |

`/api/docs`에 [GUIDE-01-3](GUIDE-01-core-3-api.md) 5.7 표의 엔드포인트 25개가 모두 보인다.
MCP 서버 ↔ 실제 core E2E(헤더 인증·URL 토큰·도구 14개·`append_note`·이력 경로 `mcp`·폐기 토큰 오류)를 확인했다.
Docker 이미지 3개 빌드·기동, Postgres 16 테스트, discord 발송 경로까지 실행했다(Docker 검증 절).
그 뒤 독립 렌즈 6개로 심층 감사를 돌리고(확정 16건), 그 수정들을 다시 적대 검증해
**총 22건을 고쳤다**(심층 감사 절). 지시서 코드 블록 46곳도 함께 고쳤다.

그 뒤 **Discord 연동을 Webhook에서 봇으로 바꿨다** — 마감 알림이 담당자 개인 DM으로 가고,
봇에게 DM으로 보내는 평문 명령으로 태스크를 처리한다(마지막 절). 아래 '알림 채널 화면' 절은
그 전 단계의 기록이며, 그 화면·모델·API는 봇 전환에서 삭제됐다.

이어서 권한 검사(렌즈 5개 + 지적별 회의론자 3명, 에이전트 110개 → 확정 2건)를 돌리고,
그 결과를 반영해 **알림 채널 화면**(`/teams/<id>/webhooks`)과 **팀원 관리 화면 보강**
(`/teams/<id>/members`)을 만들었다. 마지막 절 참고.

---

## Step 별 보고

### Step 0~1. 저장소·환경·설정 (`step 1: django skeleton, settings, accounts.User`)

- 만든 파일: `core/pyproject.toml`, `core/config/settings.py`, `core/config/urls.py`,
  `core/common/{__init__,logging,errors,dates}.py`, `core/accounts/models.py`,
  `core/api/api.py`(임시), `core/web/urls.py`(임시), 앱 7개 골격
- 검증: `uv run python -c "import django; print(django.get_version())"` → `5.2.17`.
  `makemigrations accounts` → `migrate` → `check` 모두 오류 0. `/admin/` 로그인 화면 확인.
- 지시서와 다르게 한 것: `uv init`이 패키지형 프로젝트(`src/`, `[build-system]`)를 만들어 `uv add`가 실패했다.
  `pyproject.toml`을 애플리케이션형(빌드 백엔드 없음)으로 다시 쓰고 `src/`를 지웠다.
- 실패하거나 못 한 것: 없음

### Step 2. 데이터 모델과 admin (`step 2: models and admin`)

- 만든 파일: `teams/models.py`, `projects/models.py`, `tasks/models.py`, `api/models.py`,
  `{accounts,teams,projects,tasks,api}/admin.py`, 마이그레이션 5개
- 검증: `makemigrations` → `migrate` → `check` 오류 0.
  DB 제약 4개를 shell에서 확인: `status=doing`+기한 없음, `status=blocked`+사유 없음,
  `priority=11`, `status=done`+`completed_at` 없음 → 모두 `IntegrityError`.
- 지시서와 다르게 한 것: `startapp`이 만든 빈 스텁 중 쓰지 않는 것(`reports/models.py`, `web/models.py`,
  `reports/admin.py`, `web/admin.py`, `web/views.py`)을 지웠다. 남겨 두면 `ruff check`가 미사용 import로 잡는다.
- 실패하거나 못 한 것: 없음

### Step 3~4. 서비스 계층·리포트 (`step 3: services layer`)

- 만든 파일: `teams/services.py`, `projects/services.py`, `tasks/services.py`, `tasks/brief.py`,
  `reports/services.py`
- 검증: `manage.py check` 오류 0, `ruff check` 0.
  지시서 3.5의 shell 스크립트 출력이 기대와 같다 → `1`, `TASK-1 done 4 True True`.
- 지시서와 다르게 한 것: 없음 (`ruff format` 결과만 반영)
- 실패하거나 못 한 것: 없음. Step 4는 Step 3 커밋에 함께 들어갔다.

### Step 5. HTTP API (`step 5: http api`)

- 만든 파일: `api/{auth,context,schemas,serialize,api}.py`,
  `api/routers/{__init__,me,teams,projects,tasks,today,reports,integrations}.py`
- 검증: `check` 0, `ruff` 0. OpenAPI 경로 20개가 5.7 표와 일치.
- 지시서와 다르게 한 것: **2건** (아래 "지시서 수정 목록" 1·2번)
- 실패하거나 못 한 것: 없음

### Step 6. 웹 화면 (`step 6: web ui`)

- 만든 파일: `web/static/vendor/htmx.min.js`(2.0.4 다운로드), `web/static/app.css`, `web/static/app.js`,
  `web/urls.py`, `web/forms.py`, `web/context.py`, `web/templatetags/rows.py`,
  `web/views/{common,auth,today,me,teams,projects,tasks,search,settings,ops}.py`,
  템플릿 27개(`base.html`, `today*`, `me.html`, `teams/*`, `projects/*`, `tasks/*`, `auth/*`,
  `settings/*`, `search.html`, `ops.html`)
- 검증: `check` 0, `ruff` 0. 스모크 스크립트로 GET 41개·POST 13개 전부 200/204.
  브라우저에서 §6.10 목록을 실제로 확인했다 (아래 "수동 확인 결과").
- 지시서와 다르게 한 것: **3건** (3·4·5번)
- 실패하거나 못 한 것: 없음

### Step 7. 테스트 (`step 7: tests`)

- 만든 파일: `core/conftest.py`, `{teams,projects,tasks,reports,api,web}/tests.py`
- 검증: `uv run pytest -q` → **120 passed**, skip 0. `ruff check`·`ruff format --check` 통과.
  (지시서 목록 103개 + CSRF 회귀 2개 + 심층 감사 회귀 15개. 전부 지시서 §7 표에도 추가했다.
  지시서 표의 행 수와 `pytest --collect-only` 수집 수가 모두 **120**으로 일치한다)
- 지시서와 다르게 한 것: 지시서 7.6 목록에 없는 테스트 2개를 추가했다
  (`test_bearer_write_passes_csrf`, `test_session_write_still_needs_csrf`).
  아래 2번 수정이 회귀하지 않게 막는 테스트다.
- 실패하거나 못 한 것: 없음. SQLite와 **Postgres 16 모두 120개 통과**(Docker 검증 절).

### discord_service (`discord_service: notifications and weekly report`)

- 만든 파일: `pyproject.toml`, `Dockerfile`, `README.md`,
  `discord_service/{__init__,__main__,config,store,core_client,discord,messages,notify,weekly,summarize,scheduler}.py`,
  `tests/{conftest,test_notify,test_weekly,test_discord,test_store}.py`
- 검증: `uv run pytest -q` → **20 passed**(당시). `ruff check` 0.
  `grep -r "from core\|import django" discord_service/` 결과 없음(core 미의존 확인).
- 지시서와 다르게 한 것: **2건** (7·8번)
- 컨테이너에서 실제 core에 붙여 `deadlines`(sent 3 → 재실행 skipped 3)·`weekly --now`·`test`·`once`를
  전부 실행하고 메시지 본문까지 검증했다(Docker 검증 절). Webhook은 로컬 싱크를 썼다.
- 실패하거나 못 한 것: **실제 Discord 채널** 발송만 남았다(진짜 Webhook URL 필요).
- **이 절은 Webhook 시절의 기록이다.** 마지막 절('Discord 챗봇 전환')에서 `Webhook`·`Fanout`이
  봇 REST(`Bot`)로, 채널 알림이 담당자 개인 DM으로 바뀌었고 `listener.py`·`commands.py`가 생겼다.

### mcp_server (`mcp_server: tools and auth`)

- 만든 파일: `pyproject.toml`, `Dockerfile`, `README.md`,
  `mcp_server/{__init__,__main__,auth,core_client,server,app}.py`,
  `tests/{conftest,test_auth,test_tools}.py`
- 검증: `uv run pytest -q` → **16 passed**. `ruff check` 0. core 미의존 확인.
  **실제 core를 띄운 상태로 E2E 확인**:
  1. 헤더 인증 `initialize` → 200, 서버 이름 `udally`
  2. `tools/call list_teams` → 실제 팀 데이터 반환
  3. URL 토큰 경로 `/u/<TOKEN>/mcp` → `tools/list` 도구 **14개**
  4. `append_note` → 기존 메모 뒤에 줄 추가
  5. `transition_task` 뒤 core 변경 이력의 `source == "mcp"` (A05)
  6. 폐기·오류 토큰 → "토큰이 유효하지 않습니다" (A14)
- 컨테이너에서도 같은 E2E를 다시 확인했다: mcp 컨테이너 → `http://web:8000`(compose 네트워크) →
  Postgres. 도구 14개, 두 인증 방식 모두 동작(Docker 검증 절).
- 지시서와 다르게 한 것: **1건** (6번)
- 실패하거나 못 한 것: Claude Code·Codex CLI·커넥터 등록은 사용자 계정·공개 URL이 필요해 하지 못했다.

### 배포 (`deploy: compose, cloudflared, readme`)

- 만든 파일: `core/Dockerfile`, `core/entrypoint.sh`, `core/.dockerignore`, `compose.yml`,
  `.env.example`, `.gitattributes`, `README.md`의 실행 안내 절
- 지시서와 다르게 한 것: **2건** (9·10번)
- 검증: `docker compose build` 3개 성공, 스택 기동·`/healthz`·정적 파일·재시작 멱등까지 확인(Docker 검증 절).
- 실패하거나 못 한 것: Proxmox·Cloudflare 실제 배포는 사용자 인프라가 필요해 하지 못했다.

---

## 지시서 수정 목록

지시서 코드를 그대로 옮겼을 때 동작하지 않아 고친 것들이다. 고친 이유와 범위를 함께 적는다.

1. **`api/routers/today.py` 라우트 순서** — `/order`, `/settings`를 `/{task_id}`보다 **먼저** 등록했다.
   django-ninja는 `{task_id}`에 Django `int` 변환기를 붙이지 않아 `/api/today/order`가 `DELETE /{task_id}`에
   먼저 잡혀 **405**가 났다. 지시서 5.6도 "고정 경로를 먼저 등록한다"고 적고 있어 그 의도대로 맞췄다.
   (지시서가 전제한 "`task_id`는 int 변환기" 부분만 사실과 다르다.)

2. **`api/auth.py` 세션 인증** — `django_auth`를 `BrowserSessionAuth`(세션 쿠키가 있을 때만 동작)로 바꿨다.
   django-ninja의 `SessionAuth`는 쿠키를 읽기 **전에** CSRF를 검사하고 실패하면 403을 던진다. 인증 목록
   첫 번째라서 쿠키가 없는 Bearer 요청(MCP·Discord)의 모든 쓰기가 `{"detail": "CSRF check Failed"}` 403으로
   막혔다. Django 테스트 클라이언트는 기본적으로 CSRF를 강제하지 않아 테스트에서는 드러나지 않았다.
   쿠키가 없으면 곧바로 `TokenAuth`로 넘기고, 쿠키가 있으면 CSRF 검사는 그대로 둔다(브라우저 보호 유지).
   회귀 테스트 2개를 `api/tests.py`에 추가했다.

3. **`web/forms.py` `ProjectForm.name`을 `required=False`로** — 지시서 7.7의
   `test_project_dialog_and_create`는 이름 없이 제출했을 때 **"이름을 입력하세요"**(services 메시지)를
   기대하는데, 폼이 필수면 Django 기본 문구가 나온다. 업무 규칙은 services에만 둔다는 GUIDE-00 §3과도 맞다.

4. **`settings/tokens.html` 앞자리 표시에서 `pm_` 제외** (`{{ t.prefix|slice:"3:" }}…`) — 지시서 7.7의
   `test_token_shown_once`는 두 번째 GET 본문에 `pm_`이 없어야 한다고 요구한다. 토큰 원문은 발급 직후
   1회만 보이고, 목록에는 접두사를 뺀 앞자리만 남는다.

5. **`projects/detail.html`의 `<div id="task-form">` 래퍼 제거** — 래퍼와 그 안의 `<form id="task-form">`이
   같은 id를 써서 HTML이 중복 id가 되고, `data-action="toggle"`이 바깥 div만 토글해 폼이 계속 숨겨져 있었다.
   include만 남겨 id가 폼 하나에만 있게 했다.

6. **`mcp_server` 의존성 `mcp>=1.10` → `mcp>=1.10,<2`** — mcp 2.x에서 `FastMCP`가 `MCPServer`로 개명되어
   지시서 코드가 import부터 실패한다. 지시서 코드를 그대로 쓰기 위해 v1로 고정했다.

7. **`discord_service`·`mcp_server` pytest에 `pythonpath = ["."]` 추가** — 두 패키지를 설치하지 않는 구성이라
   `tests/`에서 `import discord_service`가 실패했다.

8. **`discord_service` 테스트의 시간대** — `ZoneInfo("Asia/Seoul")` 대신 고정 오프셋(`UTC+9`)을 쓴다.
   Windows에는 IANA tzdata가 없고 허용 의존성 표에 `tzdata`가 없다. **운영 코드(`config.py`)는 그대로**이며,
   Docker 이미지(`python:3.12-slim`)에는 tzdata가 있다. 이 제약을 `discord_service/README.md`에 적었다.

9. **`.gitattributes` 추가** — Windows 체크아웃에서 `core/entrypoint.sh`가 CRLF로 바뀌면 컨테이너가 뜨지 않는다.
   `*.sh`, `Dockerfile`을 LF로 고정했다.

10. **`.claude/launch.json`에 `core` 항목 추가** — 목업(`mockup`, 8765)과 개발 서버(8000)를 나란히 띄워
    비교하기 위해서다. 기존 `mockup` 항목은 그대로 뒀다.

11. **사소** — `tests/test_discord.py`의 긴 문자열이 정확히 3000자라 `len(text) > 3000`이 실패했다.
    줄 길이를 늘려 조건을 만족시켰다(검증 내용은 그대로).

12. **이 보고서 파일** — `docs/IMPL-REPORT.md`는 GUIDE-00 §6의 파일 목록에 없다. 완료 보고를 남기라는
    §1.7·§7 요구를 충족하려고 만들었다.

---

## 수동 확인 결과 (GUIDE-01-4 §6.10)

브라우저(개발 서버 `http://127.0.0.1:8000`)에서 직접 확인했다.

| # | 항목 | 결과 |
|---|---|---|
| 1~3 | 가입 → 초대 링크 → 참여 | 통과 (`web/tests.py`, `teams/tests.py`가 같은 경로를 검증) |
| 4 | 빠른 추가 → 오늘 목록·지금 할 일 카드 | 통과 |
| 5 | 자동 담기 / 오늘 제외 / 복원 / 끄기 | 통과 ("마감 3일 이내 자동 추가 3건." 문구 확인) |
| 6 | 행 상태 변경이 행만 갱신 | 통과 |
| 7 | 기한 없는 태스크를 진행 중으로 → 안내 문구 | 통과 (services·web 테스트) |
| 8 | 막힘 선택 → 패널 사유 박스 → 빈 값 오류 → 확정 | 통과 ("막힘 사유를 입력하세요." → 저장 후 pill·사유 표시) |
| 9 | 행 클릭 → 패널, 주소 `/tasks/N`, 크게 보기/닫기 | 통과 |
| 10 | 자동 저장 "저장 중…" → "자동 저장됨", `version` 불변 | 통과 (version 3 → 3) |
| 11 | 목표일 연장: 앞 날짜 거부·사유 필수·이력 note | 통과 (이력 `기한: 9월 11일 → 9월 16일 (연장: 승인 지연)`) |
| 12 | 체크리스트·링크 추가, 링크 복사 | 통과 |
| 13 | 낙관적 잠금 충돌 문구 | 통과 ("먼저 수정했습니다") |
| 14 | `/me` 그룹·필터·팀 전체 읽기 전용 | 통과 (묶음 버튼이 hidden `group`을 덮어씀도 확인) |
| 15 | `/team` 지표 6개·프로젝트 표·새 프로젝트 모달 | 통과 |
| 16 | `/projects/N` 인라인 폼·모달·목록/보드 | 통과 |
| 17 | `/search` 번호·제목·프로젝트 이름 | 통과 |
| 18 | 일정 카드(시간표/캘린더, 마감 ●n) | 통과 |
| 19 | 1150px 이하 패널 전용, 700px 이하 메뉴 두 줄·레일 가로 스크롤·지표 2열 | 통과 |
| 20 | 토큰 1회 표시, `/ops`, `/ops/export.json`, 로그인 리다이렉트 | 통과 |

## 목업 대조 (GUIDE-01-5 §7.9)

목업(`python -m http.server 8765` → `유달리 업무 목업 v2.dc.html`)을 실제로 띄우고, 다섯 화면의
화면 문구를 목업·내 구현 양쪽에서 기계적으로 뽑아 대조했다.

**일치한 것.** 상세 패널이 거의 그대로 일치한다 — `목표일` / `2026년 9월 4일 (초과)` /
`목표일 연장하기` / `완료 조건` / `진행 메모` / `내용을 수정하면 자동 저장됩니다.` /
`문서·PR 링크` / `링크 추가` / `변경 이력` / `더보기` /
`일시정지: 개인 사유 또는 다른 작업 · 막힘: 외부 요인으로 진행 불가`.
프로젝트 인라인 폼도 `담당자 (1명)` · `중요도 (1~10)` · `기한 미정 사유 (기한이 없을 때만)` ·
`{프로젝트}에 태스크 만들기`까지 같다. 내 태스크의 그룹·기한·상태·중요도 필터 값,
팀 현황 지표 6개와 표 열 구성, 검색 placeholder, TaskRow2의 배지·버튼 라벨도 같다.

**차이 9건.** 전부 지시서가 다르게 지정했거나, 목업에만 있고 README·지시서에는 없는 것이다.
GUIDE-01-4의 지시("이 문서와 README가 다르면 README를 따르고 완료 보고에 적는다")대로 기록한다.

| # | 목업 | 내 구현 | 판단 |
|---|---|---|---|
| 1 | 프로젝트 레일 항목에 미완료 수(4, 2, 0 …) | 이니셜 + 이름만 | README 셸 문단·GUIDE base.html 모두 숫자를 말하지 않는다. GUIDE-00 §1.4(지시서에 없는 것 추가 금지) → 유지 |
| 2 | `지금 할 일` / `중요도 9/10 · 오늘 목록 기준` 두 줄 | `지금 할 일 · 중요도 5/10 · 오늘 목록 기준` 한 줄 | README §1은 "메타"만 적고 구성은 미지정. GUIDE가 준 템플릿 그대로 → 유지 |
| 3 | 포커스 메타: 제목 · 프로젝트 · 기한 · `체크리스트` | `TASK-2 · 학식 API · 9월 15일 · 제목` | 목업은 TASK 번호 없음, 체크리스트 있음. README 미지정 → 유지 |
| 4 | 자동 담기 select `1일 이내` … `14일 이내` | `1일` … `14일` | GUIDE-01-1 `AUTO_PULL_CHOICES` 코드 그대로. README §1도 "1/3/5/7/14일" → 유지 |
| 5 | `개별 태스크를 오늘 목록에서 제외할 수 있습니다.` 안내 | 없음 | README §1에 없는 문구 → 유지 |
| 6 | 내 태스크 필터에 보이는 라벨(`팀원`·`그룹`·`기한`) | `aria-label`만 | README §2는 컨트롤을 나열하지만 라벨 표시는 미지정 → 유지 |
| 7 | 중요도 필터 `높음 (8~10)` | `높음 8~10` | **README §2가 괄호 없이 "높음 8~10"으로 적었다 → 내 구현이 README와 일치** |
| 8 | 팀 현황 상단에 팀 목적 + `프로젝트 만들기` 버튼 | 팀 이름 + `멤버·초대` | README §3은 지표·프로젝트 표·담당자별만. `새 프로젝트`는 표 헤더에 있다(구현됨) → 유지 |
| 9 | 프로젝트 상태 라벨에 이모지 없음, 상태 힌트 `착수 전` | `🚧 진행 중`, `아직 손대지 않았어요.` | GUIDE-00 §5와 GUIDE-01-1 `STATUS_HINT`가 명시한 값 → 유지 |

7번은 목업이 아니라 README를 따른 결과이므로, 우선순위 규칙(README > 목업 프로토타입)이 실제로 지켜졌다는 확인이기도 하다.

---

## 검수 시나리오 대응

SPEC §12의 A 시나리오와 GUIDE 표의 B 시나리오를 테스트에 하나씩 매핑했다.

| 시나리오 | 대응 테스트 |
|---|---|
| A01 미승인 사용자 조회 불가 | `test_outsider_cannot_see_org_data_via_api`, `test_outsider_cannot_open_project_page`, `test_today_view_is_scoped_to_org_membership`, `test_today_view_manual_item_also_scoped`, `test_schedule_card_is_scoped_to_org_membership` |
| A02 프로젝트 화면에서 생성 → 자동 연결 | `test_project_inline_task_create` (`t.project == project`, `status == "todo"` 단정) |
| A03 담당자 없이 생성 거부 | `test_assignee_is_required`, `test_create_rejects_non_member_assignee` |
| A04 웹에서 완료 → 상태·완료 시각·이력 | `test_transition_flow_records_completed_at_and_log`, `test_status_change_returns_row` |
| A05 AI에서 완료 = 웹과 동일 | `test_transition_done_via_api_matches_web`, MCP E2E(이력 `source == "mcp"`) |
| A06 완료 재시도 → 완료 시각 유지 | `test_done_again_is_noop` |
| A07 완료 재개 → 완료 시각 해제, 이력 보존 | `test_reopen_clears_completed_at_reason_optional`, `test_reopen_then_done_sets_new_completed_at` |
| A09 발송 전 기한 변경 → 미발송 | `test_due_changed_before_send_not_sent` |
| A10 발송 전 완료 → 제외 | `test_completed_before_send_not_sent` |
| A11 중복 실행 방지 | `test_sends_each_kind_once`, `test_claim_is_exclusive`, `test_claim_daily` + 컨테이너 재실행 `skipped 3` |
| A12 AI 장애 → 고정 형식 | `test_summarize_falls_back_when_provider_fails` |
| A13 동시 수정 | `test_optimistic_lock_conflict`, `test_patch_conflict_409_with_latest`, `test_status_change_conflict_shows_message` |
| A14 토큰 폐기 → 호출 차단 | `test_revoked_token_401`, `test_bad_token_message`(MCP) |
| A18 모바일에서 완료 | 375×812 뷰포트에서 오늘 화면 행의 상태 컨트롤로 완료 처리 → `done`·`completed_at`·이력 `todo→done/web` 확인 |
| B01 오늘 담기가 태스크를 건드리지 않음 | `test_today_add_does_not_touch_task` |
| B02 오늘 목록은 개인·날짜별 | `test_today_is_private_and_not_carried` |
| B03 체크리스트 완료 ≠ 태스크 완료 | `test_checklist_replace_and_done_does_not_complete_task` |
| B04 초대 사용 횟수·만료·폐기 | `test_join_by_token_creates_membership_and_counts`, `test_join_expired_or_revoked_invite_rejected` |
| B05 관리자 없는 프로젝트 허용 | `test_project_without_owner_allowed` |

A08(한 태스크를 여러 프로젝트에 연결), A15~A17(Notion 가져오기·완료 시각 미상 이전·백업 복원)은
이번 범위 밖이다. A08은 IMPL-PLAN §3에서 태스크가 프로젝트 하나에 속하도록 확정했고,
A15~A17은 GUIDE에 구현 지시가 없는 후속 과제다.

## Docker 검증 (2026-09-10 재실행, 전부 통과)

첫 시도에서는 Docker 엔진이 먹통이어서 미실행으로 남겼다. 이후 엔진이 정상 기동해 전부 실행했다.
Docker 29.1.2 / linux / overlayfs.

### Postgres 16에서 core 테스트

```bash
docker compose up -d db     # postgres:16-alpine, healthcheck healthy
cd core && DATABASE_URL=postgres://pm:pm@127.0.0.1:5432/pm uv run pytest -q
```

**120 passed, skip 0.** SQLite 결과와 동일하다. GUIDE-01-5 §7.9의 "SQLite·Postgres 모두 통과" 충족.
(처음 실행은 105개였고, 심층 감사·검증 수정과 함께 120개가 됐다.)

### 이미지 3개 빌드

```bash
docker compose build web discord mcp     # exit 0
```

| 이미지 | 크기 |
|---|---|
| `…-web` | 376MB |
| `…-mcp` | 308MB |
| `…-discord` | 269MB |

### 스택 기동과 실제 동작

`docker compose up -d web mcp` 후 확인한 것:

| 확인 | 결과 |
|---|---|
| `entrypoint.sh` migrate | Postgres에 마이그레이션 14개 적용 OK |
| `entrypoint.sh` collectstatic | 130개 수집·후처리 (whitenoise 압축) |
| gunicorn | `Listening at: http://0.0.0.0:8000`, worker 2개 |
| `/healthz` | `{"ok": true}` |
| `manage.py check` (컨테이너 안) | 오류 0 |
| `/login` | 200, 로그인 폼·`/static/app.css` 링크 포함 |
| 정적 파일 서빙 | `app.css` 16,619B · `app.js` 4,970B · `vendor/htmx.min.js` 50,917B 모두 200 |
| `docker compose restart web` | 재기동에서도 migrate·collectstatic 멱등, `/healthz` OK |
| mcp 컨테이너 | uvicorn `0.0.0.0:8080`, StreamableHTTP 세션 매니저 시작 |
| discord 이미지 | `status` 명령으로 설정 파싱·`/data` 볼륨에 SQLite 생성 확인 |

### MCP: 컨테이너에서 compose 네트워크로 core 호출

Postgres에 팀·프로젝트·태스크를 심고 쓰기 토큰을 발급한 뒤, **mcp 컨테이너 안에서** 확인했다.
`CORE_URL=http://web:8000` 경로가 실제로 동작한다.

| # | 확인 | 결과 |
|---|---|---|
| 1 | `tools/list` | 도구 **14개** |
| 2 | `list_teams` (mcp → web:8000) | `['산돌이 서비스']` |
| 3 | `list_tasks(team_id=1)` | total 1, `TASK-1 배포 확인 태스크` |
| 4 | `get_task` | version 1, priority 8 |
| 5 | `append_note` | `'컨테이너 배포 확인'` |
| 6 | `transition_task` | `doing` |
| 7 | `get_team_status` | `{open:1, overdue:0, due_this_week:1, review:0, blocked:0, no_due:0}` |
| 8 | 잘못된 토큰 | "토큰이 유효하지 않습니다" (A14) |
| 9 | URL 토큰 경로 `/u/<TOKEN>/mcp` | 도구 14개 |

### Discord: 실제 core + 로컬 Webhook 싱크

컨테이너 안에 204를 돌려주는 임시 HTTP 싱크를 띄우고 발송 경로 전체를 태웠다(실제 Discord 채널은 쓰지 않았다).
태스크를 D-3 / D-1(막힘) / 기한 초과로 심어 두고 실행했다.

| 명령 | 결과 |
|---|---|
| `deadlines` | `{'sent': 3, 'skipped': 0, 'failed': 0, 'unknown': 0}` |
| `deadlines` 재실행 | `{'sent': 0, 'skipped': 3, ...}` — 중복 방지 (A11) |
| `weekly --now` | `{'status': 'sent', 'period_start': '2026-08-31', 'source': 'fixed'}` (A12 고정 형식) |
| `test` | `sent` |
| `once` (tick) | core `/api/integrations/discord/status` → **204**. `/ops`에 보고되는 경로 확인 |

싱크가 받은 메시지 5건을 그대로 검증했다.

- D-3 / D-1 / 기한 초과가 각각 지시서 문구대로 온다:
  `📌 마감 알림 · D-1 · 2026-09-10` / `• **TASK-4** … — 막힘 (서류 대기)` / 기한 초과에는 `(기한 2026-09-08)`
- 주간 보고 고정 형식에 `이번 주 마감`·`기한 초과`·`막힘`·`프로젝트별`·`검토 대기 n건 · 기한 미정 n건`이 모두 있다
- 모든 payload의 `allowed_mentions == {'parse': ['users']}` — `@everyone`·역할 멘션 차단
- `discord_user_id`가 없는 담당자는 `display_name`으로 표시된다(멘션 fallback)

### 운영 설정(`DEBUG=0`) + 프록시 뒤 동작

Cloudflare Tunnel 뒤에 놓였을 때를 흉내 내 `.env`를 `DEBUG=0`,
`ALLOWED_HOSTS=pm.example.com,localhost,web`, `CSRF_TRUSTED_ORIGINS=https://pm.example.com`,
`SITE_URL=https://pm.example.com`로 바꿔 컨테이너를 다시 만들고, `Host: pm.example.com` +
`X-Forwarded-Proto: https`로 요청했다. 확인 후 dev 설정으로 되돌렸다.

| 확인 | 결과 |
|---|---|
| `/healthz` | 200 `{"ok": true}` |
| `/login` | 200, `csrfmiddlewaretoken` 포함, `/static/app.css` 링크 포함 |
| `csrftoken` 쿠키 | `Secure` 플래그 붙음 (`CSRF_COOKIE_SECURE`가 `DEBUG=0`에서 켜짐) |
| 허용되지 않은 Host(`evil.example.com`) | **400** — `ALLOWED_HOSTS` 동작 |
| `/static/app.css` (whitenoise, `DEBUG=0`) | 200, 16,543B (압축본) |
| 비로그인 리다이렉트 | `/` → `/login` · `/today` → `/login?next=/today` · `/tasks/1` → `/login?next=/tasks/1` · `/me`·`/team` 동일 |
| 비로그인 `/api/me` | **401** |
| 비로그인 `/ops` | `/admin/login/?next=/ops` (staff 전용) |

`manage.py check --deploy` 경고 3건은 모두 설계상 정상이다.

- `security.W004`(HSTS)·`security.W008`(SSL 리다이렉트): TLS를 Cloudflare가 끝내는 구조라 엣지에서 처리한다.
  Django가 직접 강제하길 원하면 `SECURE_HSTS_SECONDS`·`SECURE_SSL_REDIRECT`를 켜면 된다.
- `security.W009`(SECRET_KEY 길이): 이 검사에 쓴 임시 키가 44자여서 난 경고다.
  GUIDE-04 Step 7이 `secrets.token_urlsafe(50)`(약 67자)로 만들라고 지시하고 있어 실제 배포에서는 나지 않는다.

### 배포 파일 무결성

- `core/uv.lock`, `discord_service/uv.lock`, `mcp_server/uv.lock`, 세 `Dockerfile`, `entrypoint.sh`,
  `.dockerignore`, `compose.yml`, `.env.example`, `.gitattributes` 모두 git에 추적된다
  (`uv sync --frozen`이 락파일을 요구한다).
- `core/entrypoint.sh`는 git blob·작업 트리 모두 **CR 바이트 0개**, `git check-attr` → `text: set`, `eol: lf`.
  Windows에서 클론해도 컨테이너가 뜬다.

### 알아 둘 것

- `collectstatic`이 `app.css`·`app.js`·`vendor/htmx.min.js`에 대해
  "Found another file with the destination path" 경고를 낸다. `web`이 `INSTALLED_APPS`에 있어
  `web/static/`이 `STATICFILES_DIRS`와 앱 static 디렉터리로 **두 번** 잡히기 때문이다.
  같은 파일이라 결과는 정상이고, 지시서가 지정한 설정 그대로여서 고치지 않았다.
- (이후 변경) `web`·`mcp`도 `127.0.0.1`에 포트를 연다(`8000`·`8080`). Docker가 기본 로컬 실행
  경로가 되면서 브라우저·AI 클라이언트가 호스트에서 바로 붙어야 했다. 루프백만 바인딩하므로
  밖에서는 들어올 수 없고, 서버에서도 지우지 않는다.

---

## 심층 감사 (Postgres 정합 · 배포 · 계약 · 권한)

"테스트가 통과한다"와 "Postgres에서 옳다"는 다른 문제라서, 테스트가 놓칠 수 있는 것만 겨냥해
독립 렌즈 6개로 코드를 훑고 각 발견을 적대적으로 검증했다.

- 렌즈: `orm-multijoin`(다중 조인 집계 부풀림) · `pg-semantics`(SQLite가 관용하는 PG 의미) ·
  `constraints-migrations`(제약·마이그레이션) · `deploy-runtime`(컨테이너가 실제로 뜨는가) ·
  `contract-drift`(파트 간 필드 계약) · `security-authz`(권한·데이터 격리)
- 검증: 발견 1건당 회의론자 3명(correctness / reachability / already-handled)이 **반박을 시도**하고,
  2명 이상이 반박하면 폐기. 회의론자들은 실제로 프로브 테스트를 작성해 라이브 Postgres 16에 돌렸다.
- 규모: 에이전트 87개, 도구 호출 1,576회, 오류 0.

**결과: 확정 16건, 반박 11건.**

### 고쳤다 (1차, 15건)

확정 16건 중 15건을 고쳤다(1건은 admin — 아래 별도 절). 처음에는 HIGH 4건만 고쳤고,
사용자 확인 뒤 나머지도 전부 고쳤다. 각각 회귀 테스트를 붙였고 지시서에도 반영했다.
이 묶음을 다시 적대 검증한 결과 **7건이 더 나왔고 그것도 전부 고쳤다**(아래 '수정을 다시 검증했다').

**A. `varchar` 초과 → Postgres에서 `DataError` → 500** (SQLite는 조용히 저장한다)

| 위치 | 문제 | 고친 것 |
|---|---|---|
| `core/tasks/services.py` (생성·수정) | `no_due_reason`이 `varchar(200)`에 절단 없이 들어간다. 형제 필드는 모두 자른다(`title[:200]`, `done_when[:300]`, `next_action[:200]`, `stop_reason[:300]`). API·MCP 스키마에 길이 제한이 없어 LLM이 쓴 긴 사유가 그대로 온다 | `.strip()[:200]` 두 곳 |
| `core/accounts/models.py` | `User.save()`가 `username`(150자)을 `display_name`(50자)에 복사한다. 50자 넘는 아이디로 가입하면 Postgres에서 500 | `self.username[:50]` |
| `core/projects/services.py` (생성·수정) | `name`(100자)·`purpose`(200자)를 자르지 않는다 | `[:100]`, `[:200]` 네 곳 |

**B. 검증 안 된 요청 값 → 400·404여야 할 곳에서 500**

| 위치 | 문제 | 고친 것 |
|---|---|---|
| `core/api/routers/tasks.py` | `due_from`/`due_to`가 `str`로 선언돼 `DateField` 조회에 그대로 간다. MCP가 `due_from="next week"`를 보내면 `ValidationError` → 500 | `date \| None`로 선언 (이제 **422**) |
| `core/web/views/common.py` | `filter(pk="abc")`가 `ValueError` → 500. `/projects/new?team=abc`로 도달 | `_pk_or_404()` 헬퍼를 만들어 `team_or_404`·`project_or_404`가 공유. **공유 헬퍼 한 곳**을 막아 모든 호출자가 함께 보호된다 |
| `core/tasks/services.py` (search) · `core/web/views/me.py` (2곳) | `str.isdigit()`은 `²`·`①`에도 True인데 `int()`는 실패한다. `/search?q=²`, `/me?member=²`, `/me?project=²` 모두 500 | `isdecimal()` |

**C. 처리 안 된 `IntegrityError` → 500**

| 위치 | 문제 | 고친 것 |
|---|---|---|
| `core/web/views/settings.py` | 남이 쓰는 `discord_user_id`를 넣으면 `unique=True`에 걸려 500. 폼이 `forms.Form`이라 `validate_unique`가 돌지 않는다 | 저장 전 중복 검사 → 필드 오류 "다른 사용자가 이미 쓰는 Discord 사용자 ID입니다." |

**D. 데이터 격리**

| 위치 | 문제 | 고친 것 |
|---|---|---|
| `core/tasks/services.py` (`today_view`) · `core/web/views/today.py` (`_schedule`) | 다른 모든 읽기 경로는 `visible_tasks(user)`를 쓰는데 이 둘만 `Task.objects.filter(assignee=user)`. 팀에서 제거된 뒤에도 담당으로 남은 태스크의 제목·기한·완료 수가 계속 보인다 | `visible_tasks(user).filter(assignee=user)` |

**E. 배포 산출물**

| 위치 | 문제 | 고친 것 |
|---|---|---|
| `.env.example` | `ALLOWED_HOSTS=pm.example.com`에 `web`이 없다. compose가 mcp·discord에 `CORE_URL=http://web:8000`을 주므로 그 요청의 Host는 `web` → **DisallowedHost 400**. 내가 컨테이너 검증할 때 실제로 `web`을 넣어야 통과했다 | `pm.example.com,web` + 이유 주석 |
| `compose.yml` | `db`에만 `restart` 정책이 없다(나머지 넷은 `unless-stopped`). 호스트 재부팅 시 Postgres만 안 올라오고 web이 `migrate`에서 크래시 루프 | `restart: unless-stopped` |

**F. discord 복원력**

| 위치 | 문제 | 고친 것 |
|---|---|---|
| `discord_service/discord_service/notify.py` | `store.claim()`과 발송 사이의 `core.task()`가 무방비다. core가 일시적으로 429/502를 주면 예외가 `run_deadlines`를 벗어나 `sending` 행이 남고 **그 마감 알림은 영구히 안 나간다** | 개별 알림은 `store.release()`, 기한 초과 묶음은 `store.release_daily()` 후 다음 tick에 재시도 |

**G. 개발/운영 정렬 차이** (내가 직접 양쪽에서 측정)

`core/api/routers/tasks.py`의 `order_by("due_date", "id")`는 NULL 위치가 백엔드마다 다르다.

| | SQL 정렬 | Python `by_due()` | 일치 |
|---|---|---|---|
| SQLite (수정 전) | `undated0, undated1, dated0…` | `dated0, dated1, dated2, undated0…` | ✗ |
| Postgres 16 (수정 전) | `dated0, dated1, dated2, undated0…` | 같음 | ✓ |

운영(Postgres)에서는 이미 옳았고 개발용 SQLite에서만 어긋났다.
`order_by(F("due_date").asc(nulls_last=True), "id")`로 명시해 양쪽을 맞췄다.

### admin: 처음엔 안 고쳤다가, 반박을 받고 고쳤다

`core/tasks/admin.py`에서 상태를 `done`으로 바꾸면 DB CHECK에 걸려 500이 나는 건을
처음에는 "지시서가 허용한다"며 남겼다. 완결성 비평이 이 근거를 조목조목 반박했고, 그 반박이 맞다.

내 근거와 반박:

| 내가 든 근거 | 반박 |
|---|---|
| GUIDE-01-1 §2.6이 "admin에서 500이 떠도 정상"이라고 적었다 | 그 문장은 **잘못된 입력 3가지**(`doing`+기한 없음, `blocked`+사유 없음, `priority=11`)에 한정되고 **"이 단계에서는"**으로 범위가 묶여 있다. 목적도 "제약이 동작한다는 확인"이다. `done`은 **정상 선택지**이고, `completed_at`이 `readonly_fields`라 폼에 없으므로 **operator가 무슨 값을 넣어도 저장이 불가능하다**. 성질이 다르다 |
| 고치면 생명주기 규칙을 admin에 쓰게 되어 GUIDE-00 §3 위반이다 | GUIDE-00 §3은 이미 **"`Task`·`Project`를 `services.py` 밖에서 `save()`·`update()`로 수정하지 않는다"**고 적고 있다. **admin 등록 자체가 그 규칙 위반**이고 500은 증상일 뿐이다 |

게다가 더 큰 문제가 있었다. **성공하는 admin 수정**(`status=review`, 담당자 변경, 중요도 변경)은
`ChangeLog`도 `version`도 남기지 않는다. `reports.weekly`는 완료 수를 `ChangeLog`의
`field="status", new_value="done"` 행에서 세므로, admin 수정은 **주간 보고를 조용히 틀리게 하고
낙관적 잠금을 무력화한다.** 500은 오히려 잘못된 쓰기를 막아 주던 쪽이었다.

그래서 GUIDE-00 §3이 실제로 요구하는 대로 고쳤다. `ChangeLogAdmin`이 이미 쓰던
`has_*_permission` 패턴을 `ReadOnlyAdmin`으로 뽑아 `TaskAdmin`·`ProjectAdmin`에 적용했다.

- 목록·상세는 **200**으로 남는다(Django가 조회 전용 페이지를 그린다)
- `add/`·`delete/`는 **403**
- `change/`에 POST하면 **403**이고 값이 바뀌지 않는다 (테스트로 확인)

GUIDE-01-1 §2.6의 제약 검증 절차도 shell 기준으로 다시 썼다(실제로 내가 그렇게 검증했다).

**되돌리려면**: `core/tasks/admin.py`의 `ReadOnlyAdmin` 상속을 `admin.ModelAdmin`으로 바꾸면 된다.
다만 그러면 위의 ChangeLog·version 문제가 함께 돌아온다.

### 확인

| 항목 | 결과 |
|---|---|
| core 테스트 (SQLite) | **120 passed**, skip 0 |
| core 테스트 (Postgres 16) | **120 passed**, skip 0 |
| discord_service | **20 passed** |
| mcp_server | **16 passed** |
| `ruff check` · `ruff format --check` | 세 파트 모두 통과 |
| 라이브 컨테이너 API + Postgres | 250자 `no_due_reason`으로 `POST /api/tasks` → **201, 저장값 200자** (수정 전 500) |

신규 회귀 테스트 15개를 지시서 §7.1a·7.3·7.4·7.6·7.7 표에도 추가했고,
§7.8의 Postgres 실행을 "권장"에서 **"반드시"**로 격상했다(varchar 초과·NULL 정렬은 SQLite에서 안 드러난다).


### 수정을 다시 검증했다 (에이전트 9개)

"고쳤다"를 믿지 않기 위해, 수정 묶음마다 회의론자를 붙여 **재현이 실제로 사라졌는지 직접 실행**하게 했다.
추가로 (a) 지시서 126개 코드 블록 전체를 실제 파일과 대조, (b) 완결성 비평(무엇이 아직 빠졌나)을 돌렸다.

결과: **효과 없음 1건, 지시서 불일치 4건, 회귀 0건**. 그리고 새 findings 7건이 나와 전부 고쳤다.

| 검증이 찾은 것 | 왜 중요한가 | 고친 것 |
|---|---|---|
| **`today_view` 수정이 절반만 됐다** | `mine`(자동 담기)만 팀 범위로 바꾸고, 바로 세 줄 위의 `manual`(직접 담은 `TodayItem`)은 그대로였다. `items = manual + auto`라 **직접 담은 태스크는 여전히 새어 나갔다.** 내 회귀 테스트는 fixture가 `TodayItem`을 만들지 않아 auto 분기만 밟아 통과했다 — 거짓 안심 | `today_items()` 헬퍼를 만들어 `today_membership`·`today_view` 두 경로가 같은 범위를 쓴다. 테스트를 `auto_pull=0`으로 두고 manual 분기를 밟게 다시 썼다 |
| **내 절단 수정이 새 500을 만들었다** | `create_project`가 중복 검사는 **자르기 전** 이름으로, INSERT는 **자른** 이름으로 했다. 앞 100자가 같은 두 이름이 둘 다 검사를 통과해 `UniqueViolation` → 500. `DataError` 500을 `IntegrityError` 500으로 바꾼 셈. `update_project`는 순서가 맞아서 대비가 드러났다 | 자른 뒤 검사한다 |
| `IdempotencyKey.key`(varchar 100)를 웹 경로가 자르지 않는다 | API는 `idem_key()`가 `[:100]`인데 웹 폼의 `idem` hidden 필드는 `max_length`가 없다. `POST /today/quick`에 300자 → Postgres `DataError` → 500 | 폼에 `max_length=100`, 서비스에서도 `[:100]`(조회·저장 같은 값으로) |
| `week_days()`가 `date.max` 근처에서 `OverflowError` | `/today?schedule=1&cal=month&day=9999-12-01` → 500. 수정한 파라미터 검증과 같은 클래스인데 유일하게 남아 있었다 | 12월을 특수 처리해 `replace(day=28)+4일` 트릭 제거 |
| `projects.py`의 `{int(x) for x in form["owners"].value()}` | bound form의 `value()`는 **raw 문자열**을 준다. 모달에 조작된 `owners` 값이 오면 `int()`가 터져 500 | `_owner_ids()`로 감싸 못 읽는 값은 무시 |
| `create_team`·`ApiToken.issue`·`projects._log`의 절단 누락 | 지금은 폼이 막아 도달 불가지만, 같은 클래스이고 형제 코드는 자른다. API가 하나 늘면 되살아난다 | 방어적으로 `[:100]`/`[:200]`/`[:50]`/`[:200]` |
| **admin "안 고침" 근거가 틀렸다** | 아래 참고 | admin을 조회 전용으로 |

### 반박된 11건

회의론자 2명 이상이 반박해 폐기한 것들이다. 참고용으로 남긴다.

- 다중 조인 집계 부풀림 — `Count(filter=...)`가 여러 개여도 부풀지 않음(3표 반박)
- 보관된 프로젝트에서 태스크 재개 — `transition()`에 `is_archived` 검사 없음(3표 반박)
- `Idempotency-Key` check-then-insert 경합(3표 반박)
- 프로젝트 이름 중복 check-then-write 경합(3표 반박)
- `SECRET_KEY` 누락 시 하드코딩 키로 폴백(3표 반박)
- 체크리스트만 PATCH할 때 `version` 무시(3표 반박)
- 초대 링크가 발급자의 관리자 권한보다 오래 남음(3표 반박 — 재가입해도 `member`로만 들어간다)
- `archive_project`/`restore_project`의 stale version(2표), `DATABASE_URL` 비밀번호 이스케이프(2표),
  일정 카드가 프로젝트 이름을 노출(2표 — 템플릿은 제목만 그린다), NULL 정렬 중복 보고(2표)

### 지시서 반영 (46곳)

고친 것은 모두 지시서가 그대로 적어 준 코드·값에서 왔다. 이 문서로 다시 구현했을 때 같은 버그가
되살아나지 않도록 **지시서의 해당 코드 블록도 함께 고쳤다** (1차 17곳 + 검증 이후 29곳 = 46곳).
구현 초기의 6개 이탈(CSRF·라우트 순서·`ProjectForm`·중복 id·`mcp<2`·`pythonpath`)도 이번에 지시서에 넣었다.
지시서 §7 테스트 표의 행 수와 `pytest --collect-only` 수집 수가 모두 **120**으로 일치한다.

핵심 대조 지점 28곳을 지시서·코드 양쪽에서 자동 확인했다 — **불일치 0건**.

| 지시서 | 고친 내용 |
|---|---|
| GUIDE-01-1 §1.6 `User.save` | `display_name = self.username[:50]` |
| GUIDE-01-2 §3.2 `create_project`/`update_project` | `name[:100]`, `purpose[:200]` (4곳) |
| GUIDE-01-2 §3.3 `create_task`/`update_task` | `no_due_reason` `[:200]` (2곳) |
| GUIDE-01-2 §3.3 `today_view` | `mine = visible_tasks(user).filter(assignee=user)` |
| GUIDE-01-2 §3.3 `search` | `isdigit()` → `isdecimal()` |
| GUIDE-01-3 §5.6 tasks 라우터 | `due_from`/`due_to`를 `date`로, `order_by`에 `nulls_last`, import에 `date`·`F` 추가 |
| GUIDE-01-4 §6.4 `common.py` | `_pk_or_404()` 추가, `team_or_404`·`project_or_404`가 사용 |
| GUIDE-01-4 §6.6 `_schedule` | `ts.visible_tasks(...)` 범위로 |
| GUIDE-01-4 §6.9 `me.py` | `isdigit()` → `isdecimal()` (2곳) |
| GUIDE-01-5 §7.1a·7.3·7.4·7.6·7.7 | 신규 회귀 테스트 12행 추가 |
| GUIDE-01-5 §7.8 | Postgres 실행을 "권장" → **"반드시"** |
| GUIDE-04 Step 2 `compose.yml` | `db`에 `restart: unless-stopped` |
| GUIDE-04 Step 3 `.env.example` | `ALLOWED_HOSTS=pm.example.com,web` + 이유 주석 |

`core/web/views/settings.py`의 중복 `discord_user_id` 검사는 GUIDE-01-4 §6.11이 산문 명세라
코드 블록이 없어 문서 수정 대상이 아니다. 동작은 "폼 오류로 돌려준다"는 그 절의 서술과 어긋나지 않는다.

---

## 권한 검사와 관리 화면 2개 (2026-09-10, 추가 작업)

요청: "권한 검사가 끝나면, 디스코드 웹훅을 관리하는 페이지, 팀장이 팀원을 관리하는 페이지를
만들고 구성하기 위한 계획을 세우고 실행해". 순서대로 권한 검사를 먼저 돌리고, 그 결과를 반영해
두 화면을 만들었다.

### 1. 권한 검사 (에이전트 110개)

렌즈 5개(관리자 전용 경로 · 팀 간 id 혼동 · 토큰 범위와 인증 순서 · 멤버십 생애주기 ·
비밀 취급)로 찾고, 각 지적마다 회의론자 3명(정확성 · 도달 가능성 · 이미 막혀 있나)을 붙여
2명 이상이 반박하면 버렸다. 회의론자는 판정 근거를 프로브로 실행해 확인했다.

**지적 35건 → 확정 2건, 반박 33건.** 확정 2건은 고쳤다.

권한 모델은 2층이고, 짐을 지는 쪽은 **뷰가 아니라 서비스**다. 렌즈 다섯 개가 같은 결론을 냈다.

1. **범위(멤버)**: 모든 읽기가 `teams_of(user)`에서 출발한다 — `tasks.services.visible_tasks`,
   `web/views/common.py`의 `task_or_404`/`team_or_404`/`project_or_404`(+ 숫자가 아닌 id는
   `_pk_or_404`가 404), `api/context.py`의 같은 헬퍼. 전부 **멤버** 기준이고 역할은 보지 않는다.
2. **역할(관리자)**: `teams.services.require_admin(actor, team)`을 **서비스 함수 첫 줄**에서 부른다
   (`create_invite`·`revoke_invite`·`change_role`·`remove_member`, `archive_project`·`restore_project`,
   그리고 이번에 추가한 웹훅 함수 전부). 템플릿의 `{% if is_admin %}`은 장식일 뿐이다.

렌즈들이 팀원 세션·팀원 쓰기 토큰·외부인 토큰으로 관리자 전용 경로 전부(웹 POST 6개, API 2개)와
id를 받는 모든 경로(교차 팀 `assignee_id`·`owner_ids`·`project_id`·`task_id`·`membership_id`·
`invite_id`·`link_id`·`item_id`·`webhook_id`·`?member=`·`?project=`)를 찔러 봤고, 전부 404/400에
상태 변화 0이었다. 즉 **기존 권한 경계에는 구멍이 없었다.**

#### 확정 2건 (고쳤다)

| # | 곳 | 문제 | 고친 방법 |
|---|---|---|---|
| 1 | `tasks/services.py::_validate`, `projects/services.py::update_project` | 담당자를 팀에서 제거하면 그 사람이 담당인 태스크의 **중요도·기한조차** 못 고친다. `_validate`가 바뀌지 않은 담당자까지 다시 검사해 "담당자는 이 팀의 활성 멤버여야 합니다"로 막고, 화면에는 이미 나간 사람 이름이 담긴 오류만 뜬다. 프로젝트 관리자도 같다 | 바뀌는 것만 검사한다. `_validate(..., check_assignee=...)`에 `update_task`가 `"assignee" in changes`를 넘기고, `update_project`는 **새로 넣는** 관리자만 검사한다. 담당자·관리자 명단 자체는 그대로 남겨 "누가 하던 일인지"를 잃지 않는다 |
| 2 | `api/api.py` | 처리량 제한(60/m)이 `str(request.auth)` = `display_name`으로 센다. 본인이 바꿀 수 있고 유일하지도 않아, 남과 같은 이름으로 바꿔 두면 그 사람 몫까지 갉아먹는다 | `UserRateThrottle`이 사용자 id로 센다 |

#### 반박됐지만 같이 고친 2건 (이번에 내가 새로 쓴 코드의 결함이라)

회의론자들이 "권한 경계 문제는 아니다"라고 반박한 것 중, 내가 방금 쓴 `Fanout`의 의미가
어정쩡한 것 두 개는 그대로 두지 않았다.

- **채널을 전부 끄면 예비 주소로 새어 나갔다.** `if self._urls:`가 "채널 0개"와
  "core가 답을 안 했다"를 같은 것으로 취급했다. 이제 목록을 **읽는 데 성공했으면** 그 목록을
  그대로 쓴다(빈 목록이면 발송 없음, 실패로 기록). 예비 주소(`DISCORD_WEBHOOK_URL`)는
  core를 **못 읽었을 때**만 쓰고, core가 4xx로 답하면(토큰·권한·팀 설정) 감추지 않고 실패시킨다.
- **채널 하나가 죽으면 나머지 채널도 못 받았다.** 이제 전부 시도한 뒤 첫 예외를 다시 던진다.
  `store`가 자리를 잡아 두었으므로 살아 있는 채널에 중복으로 가지 않는다.

#### 반박 이유가 타당해서 안 고친 것 (주요 8건)

| 지적 | 반박 근거 |
|---|---|
| `SecretFilter`가 traceback(`exc_info`)은 가리지 못한다 | 기제는 사실이지만 core에 도달 경로가 없다. core에는 httpx가 아예 없고(`raise_for_status` 0건), 유일한 Discord 발송 `post_discord`는 `send_test_message`가 전부 catch해 예외가 새지 않으며, core 전체에 `.exception(`·`exc_info` 사용이 0건이다 |
| 마지막 관리자 보호가 원자적이지 않다(동시 요청이면 관리자 0명) | 권한 상승이 아니다. 두 관리자가 서로를 동시에 제거하는 경우뿐이고, 둘 다 이미 팀 전권을 가진 사람이다. 한 사람이 두 탭으로 하는 변형은 실제로 안 된다(두 번째 요청은 이미 지워진 행에 걸린다). 일상 작업(프로젝트·태스크·오늘·보고)은 멤버 권한이라 계속 돌아간다 |
| `_admin_count`가 비활성 사용자까지 센다 | 비활성화는 Django admin에서만 가능하고, 그 상태에서도 팀 데이터는 멤버 권한으로 돌아간다. 6명이 각각 반박 |
| 제거한 사람이 살아 있는 초대 링크로 다시 들어온다 | 초대 링크는 팀 전체용이고 발급·폐기 화면이 같은 페이지에 있다. 대신 **화면에 안내 한 줄을 넣었다**("제거한 사람이 링크를 가지고 있으면 다시 참여할 수 있으니 필요하면 폐기하세요") |
| `WRITE_EXEMPT_PREFIX`가 경로 접두사라 읽기 토큰이 `/api/integrations/` 아래 쓰기를 할 수 있다 | 지시서에 명시된 설계다(연동 계정이 읽기 토큰으로 상태를 보고한다). 그 아래 쓰기 엔드포인트는 `report_status` 하나뿐이고 팀 데이터를 건드리지 않는다. 이번에 추가한 웹훅 엔드포인트는 GET이다 |
| `ChangeLog.source`가 `X-Source` 헤더로 정해진다 | 지시서에 적힌 동작이고, 위조해도 남의 데이터에 접근하지 못한다 |
| 권한 거부가 API에서 400으로 나간다 | 기존 설계(`ServiceError` → 400). 새 웹훅 엔드포인트는 403을 명시적으로 낸다 |
| `active_webhook_urls`에 actor가 없어 권한 검사를 안 한다 | 유일한 호출부인 API 라우터가 `is_admin`으로 막고, 테스트가 팀원 403·외부인 404·무인증 401을 고정한다 |

감사 도중 드러난 문서 오류 2건도 고쳤다: `PLAN.md`의 초대 폐기 경로(`/api/invites/{id}` →
`/api/teams/invites/{id}`)와 "JSON 내보내기: 팀 관리자 가능" 표기(실제로는 모든 팀이 한 파일에
담기므로 superuser 전용).

### 2. 알림 채널 화면 (`/teams/<id>/webhooks`) — **이후 삭제됨**

> 이 화면·모델(`teams.DiscordWebhook`)·API(`GET /api/integrations/discord/webhooks`)는
> 다음 커밋의 봇 전환에서 전부 삭제됐다(마이그레이션 `teams/0003_delete_discordwebhook`).
> 봇에는 대응 개념이 없다 — 설치는 운영자가 포털에서 1회, 개인 쪽은 DM `연결`이다.
> 아래 기록은 그때 무엇을 만들고 무엇을 검증했는지 남기기 위한 것이다.

전에는 발송 대상이 `discord_service`의 환경 변수 `DISCORD_WEBHOOK_URL` 하나였다. 이제 팀 관리자가
웹에서 관리하고, discord 서비스가 그 목록을 HTTP로 읽어 간다. 세 파트는 여전히 HTTP로만 통신한다.

- `teams.DiscordWebhook(team, name, url, is_active, created_by, last_test_*)` + 마이그레이션
  `0002_discordwebhook`. `UniqueConstraint(team, url)`.
- **주소가 곧 비밀이다.** 아는 사람은 누구나 그 채널에 글을 쓸 수 있으므로
  화면·오류 메시지·`/ops` 내보내기에는 `masked`(`…/webhooks/<채널 id>/••••••••뒤4자`)만 쓴다.
  토큰이 짧으면 뒤 네 자도 감춘다. 원문을 주는 곳은 팀 관리자만 읽을 수 있는
  `GET /api/integrations/discord/webhooks` 하나다. 백업(`/ops/export.json`)에는 초대 token과
  같은 방식으로 `url`을 빼고 행만 넣는다.
- `add_webhook`은 `WEBHOOK_RE`(`https://discord(app).com/api/webhooks/<숫자>/<토큰>`)로 검사한다.
  이 검사가 곧 SSRF 방지다 — 통과한 주소만 `post_discord`가 연다.
- **테스트 발송**: core가 Discord로 직접 보내는 곳은 이 확인용 1건뿐이다(stdlib `urllib`, 5초).
  정기 알림은 discord 서비스의 일이다. 실패 사유는 `Discord 응답 404` 같은 짧은 문구로만 남기고
  예외 원문은 쓰지 않는다(주소가 섞이지 않게).
- 화면: 채널 표(이름·등록자·등록일, masked 주소, 사용 여부, 마지막 확인 결과,
  [테스트 발송][끄기/켜기][삭제]) + 등록 폼. 팀원에게는 403이 아니라 **404**로 감춘다.

### 3. 팀원 관리 화면 보강 (`/teams/<id>/members`)

있던 것(역할 select, 제거, 초대 발급·폐기)에 팀장이 판단할 때 필요한 것을 더했다.

- **미완료·기한 초과 건수**: 새 집계 함수를 만들지 않고 `reports.services.team_status`의
  `by_assignee`를 담당자 id로 찾아 쓴다. 누구를 제거하면 무엇이 남는지 보고 결정할 수 있다.
- **Discord 연동 여부**: 마감 알림의 멘션은 `discord_user_id`로 만든다. 없는 팀원은 멘션 대신
  이름만 나오므로 그 사실과 해결 방법(본인이 프로필에서 입력)을 화면에 적었다.
- **참여일**, **관리자 수**("관리자 1명. 마지막 관리자는 역할을 바꾸거나 제거할 수 없습니다"),
  제거 확인 문구("담당 중인 미완료 태스크는 담당자 그대로 팀에 남습니다"),
  초대 링크 재사용 안내, 알림 채널 화면 링크.
- 권한 관문은 `_admin_only`(= `team_or_404` + `can_admin` → 404) 하나로 모았고,
  객체별 경로는 `_webhook_or_404`처럼 **그 객체의 team_id**로 확인한다(URL·본문의 팀 id를 믿지 않는다).

### 4. discord_service 변경

- `CoreClient.webhook_urls(team_id)` → `GET /api/integrations/discord/webhooks?team=`.
- `Fanout`이 `Webhook` 자리를 대신한다(같은 `send(text)`). 켜져 있는 채널 **전부**로 보내고,
  목록은 60초 캐시한다. `notify`·`weekly`는 타입 힌트만 `Sender`(= `Webhook | Fanout`)로 바꿨고
  본문은 그대로다.
- `DISCORD_WEBHOOK_URL`은 **필수에서 예비로** 바뀌었다(`.env.example`은 빈 값).
  연동 계정은 이제 그 팀의 **관리자**여야 한다(주소를 읽어야 하므로). 토큰은 읽기여도 된다 —
  읽기 토큰은 `/api/integrations/` 밖의 쓰기를 못 한다.

### 5. 확인

- core 140 / discord 29 / mcp 16 전부 통과, ruff 0 (요약 표 참고). core는 SQLite와 Postgres 16 둘 다.
- **파트 간 계약을 실제 프로세스로 확인했다.** 실행 중인 core에 알림 채널 1건을 등록하고
  `discord_service`의 `CoreClient`·`Fanout`으로 붙였다:
  관리자 읽기 토큰 → 주소 1건, **팀원 읽기 토큰 → 403** `팀 관리자만 볼 수 있습니다.`,
  `Fanout.targets()` → core에서 읽은 주소, 403일 때 예비 주소로 숨기지 않고 예외.
  확인용으로 만든 웹훅·토큰은 지웠다.
- 브라우저(실행 중 dev 서버, 팀 관리자 세션)로 두 화면을 직접 확인했다:
  팀원 관리 화면의 새 열 3개(참여·Discord·미완료), 알림 채널 등록(잘못된 host → 필드 오류, 올바른 주소 → 등록되고
  화면에는 masked만), **테스트 발송을 실제 Discord로 보내 403 응답이 화면과 행에 표시되는 것**,
  끄기/켜기, 삭제. 팀원 세션으로는 두 화면 모두 404.
- `docker compose build web discord` 다시 통과(376MB · 269MB, 이전과 같음). 이미지 안에
  `web/templates/teams/webhooks.html`과 `teams/migrations/0002_discordwebhook.py`가 들어 있는 것도 확인했다.
- 목업에는 없는 화면이다. 핸드오프(README)의 7화면은 팀원 모두가 쓰는 화면이고, 이 둘은 팀
  관리자 전용 관리 화면이라 목업 대조 대상이 아니다. 색·크기·문구는 `app.css`의 기존 토큰과
  컴포넌트(카드·`table.grid`·`badge`·`btn sm`)만 써서 새 스타일을 만들지 않았다.
- 상단 내비게이션(오늘·내 태스크·팀 현황·검색)은 그대로 두고, 팀 현황 화면의 관리자 전용
  버튼 두 개로 들어간다.
- 지시서 반영: GUIDE-00 §3(비밀 취급 규칙 1줄), 01-1 §2.1(모델), 01-2 §3.1·§3.3(서비스·검증),
  01-3 §5.5·§5.6·§5.7(throttle·라우터·엔드포인트 표), 01-4 §6.2·§6.3·§6.10·§6.11·§6.13
  (URL·폼·뷰·ops·템플릿 표), 01-5 §7.2~§7.7(테스트 표), 02(config·Fanout·conftest·테스트 표),
  04 Step 3·Step 7·완료 체크, `README.md`, `discord_service/README.md`, `.env.example`, `PLAN.md`.

---

## Discord 챗봇 전환 (2026-09-10, 웹훅 삭제)

요청: "디스코드챗봇으로하자웹훅이아니라그래서일부관리기능도제공하고데드라인알림은개인디엠으로전송되도록".
Webhook을 지우고 봇 토큰으로 바꿨다. 마감 알림은 **담당자 개인 DM**으로 가고, 봇에게 DM으로
보내는 평문 명령으로 태스크를 처리한다. 하루 전에 만든 알림 채널 화면은 대응 개념이 없어 삭제했다.

### 1. 먼저 사실을 확인했다 (에이전트 15개)

문서에 대고 검증한 렌즈 5개(DM 발송 · HTTP 인터랙션 · 게이트웨이 대안 · 포털·배포 · 현재 코드 영향)로
Discord API 사실을 URL과 함께 모으고, 그 위에서 설계 3안을 짜 각 2명이 채점했다.
**C(게이트웨이) 36 / B(core에 인터랙션 엔드포인트) 35 / A(discord_service에 엔드포인트) 23.5** —
C와 B가 사실상 동점이라 심사가 찾은 결함(각 안 6~10건)을 합쳐 최종안을 만들었다.

설계를 가른 사실들:

| 사실 | 결과 |
|---|---|
| 봇에게 온 DM의 본문은 MESSAGE_CONTENT **특권 인텐트 예외**다 | 평문 DM 명령이 슬래시 명령보다 싸다. 등록 스크립트·하루 200 create 한도·`contexts`·중복 ACK(`40060`)가 전부 사라진다 |
| **3초 응답 시한**은 인터랙션에만 붙는다 (게이트웨이든 HTTP든) | 평문 DM에는 시한이 없다. 터널 + gunicorn + Postgres 왕복을 3초에 맞출 필요가 없다 |
| Python 표준 라이브러리에 **Ed25519가 없다** | HTTP 인터랙션은 pynacl을 강요한다. 게이트웨이를 고르면 **core의 의존성 표가 그대로다** |
| 게이트웨이와 HTTP 인터랙션은 **양립하지 않는다** | 하나를 고르는 갈림길이다. 나중에 바꾸려면 한쪽을 지워야 한다 |
| Cloudflare Tunnel은 인바운드 전용이고 게이트웨이는 봇이 **밖으로** 건다 | 공개 호스트네임·TLS·서명 검증·"Discord가 인터랙션 URL을 조용히 지움" 실패 모드가 없다 |
| 손으로 쓴 게이트웨이는 하트비트/ACK · `resume_gateway_url` RESUME · 재접속 불가 close code(4004·4010~4014) · IDENTIFY 예산을 전부 구현해야 한다 | `discord.py`를 쓴다. 우리 코드는 리스너 59줄 |
| `POST /users/@me/channels`는 봇 전체가 한 버킷이고 전용 오류 코드(`40003`)가 있다 | DM 채널 id를 SQLite에 캐시한다 |
| `50007`·`50278`·`10013`은 그 사람에 대해 영구적이다 | 재시도하지 않는다(403은 10분당 1만 invalid-request 예산을 태우고 LXC는 egress IP가 하나다) |
| Discord 문서가 이 제품을 직접 경고한다 — 서버 사람들에게 알리려고 이 엔드포인트를 쓰지 말 것, DM은 사용자 행동에서 시작되어야 한다 | 사용자가 직접 `연결`한 계정에만, 자기 담당 태스크만, 사람당 하루 최대 4건, `연결해제`가 즉시 opt-out |
| 봇 요청에 **User-Agent가 필수**다 | 없으면 Cloudflare가 `40333`으로 막는다. 상수로 박았다 |
| `ChangeLog.source`는 `max_length=4` | 코드는 `dc`, 표시는 "Discord". `discord`는 Postgres에서 DataError다 |

### 2. 계정 연결에 소유 증명을 넣었다 (이 전환의 전제)

전에는 프로필에서 `discord_user_id`를 **손으로 타이핑**했다. 봇이 "Discord id → PM 계정"으로
행위자를 정하는 순간 그 값은 로그인 자격증명이 된다 — 남의 아직 안 쓴 Discord id를 먼저 적어 두면
그 사람이 봇을 쓸 때 **내 계정으로** 동작한다.

이제 두 신원을 맞바꿔야 연결된다: **코드**는 로그인한 웹 세션에서만 나오고(`issue_link_code`),
**snowflake**는 게이트웨이가 채운 `author.id`에서만 나온다. 8자리 16진수 · 10분 · 1회용이고,
비울 때는 반드시 `None`이다(빈 문자열은 unique 충돌). 이미 그 snowflake를 들고 있는 옛 행이 있으면
**가져온다** — 양쪽이 증명된 이 순간 남의 행이 틀린 것이고, 선점당해 영구히 잠기는 경로가 없어진다.
`user_by_discord_id`는 `discord_linked_at`이 있고 활성인 사용자만 돌려준다.

마이그레이션 `accounts/0002_discord_link`의 `clear_unverified_links`가 **기존 값을 전부 비운다**.
검증 안 된 값을 자격증명으로 승격시키지 않는다. 배포 전 공지가 필요하다 — 전원이 `연결`을 하기
전까지 개인 DM 알림은 0건이다. 프로필의 입력칸은 삭제했고 admin에서도 읽기 전용이다.

### 3. 봇 명령이 사람으로서 움직이는 방법

`POST /api/integrations/discord/{link,unlink,today,tasks/{id}/done,tasks/{id}/extend}` 5개.
라우터 인증이 `BotTokenAuth()` **하나**라서 API 기본 인증(세션 쿠키 + 일반 토큰)이 이 경로에
아예 들어오지 못한다 — 엔드포인트마다 가드를 손으로 붙이면 다음 하나를 잊는다. 쓰기 게이트도
`scope == "read"` → `scope != "write"`로 좁혀 `bot` 범위가 `/api/integrations/` 밖에서 쓰지 못한다.

행위자는 봇이 아니라 **연결된 사람**이다. 태스크 범위도 그 사람의 팀(`get_visible_task(actor, …)`)이고,
변경 이력에는 행위자=사람 · 경로=`dc`(표시 "Discord") · 토큰=봇 토큰 세 줄이 남는다.

`expected_version`: 채팅 명령에는 버전이 없다. 의도는 "지금 완료로 바꿔라"이므로 서버가 **한 요청
안에서** 읽고 그 값으로 CAS를 건다. 그 사이(수 ms)에 웹 편집이 끼면 409로 알린다
("방금 다른 곳에서 바뀌었어요. 다시 보내 주세요."). 조용히 덮어쓰지 않고, 재시도 루프도 만들지 않는다.
같은 `완료` 재요청은 `transition`의 같은-상태 조기 반환으로 무해하고(이력 1줄), `연장`은
새 날짜가 현 기한보다 뒤가 아니면 거부해 이중 연장이 구조적으로 불가능하다.

명령: `오늘` · `완료 <번호>` · `연장 <번호> <YYYY-MM-DD> <사유>` · `연결 <코드>` · `연결해제` ·
그 밖의 텍스트는 도움말. 번호는 `12`와 `TASK-12` 둘 다 받는다.

### 4. 마감 알림을 개인 DM으로

`(종류, 담당자)`로 묶어 사람당 종류당 1건, **하루 최대 4건**을 보낸다. 태스크마다 한 통씩 보내면
아침 DM 폭탄이 되고 Developer Policy의 '원치 않는 반복 DM'에 걸린다. 중복 방지 키는
`(0, "<종류>:<사용자 id>", 날짜)`로 기존 `sent` 표를 그대로 쓴다(`kind`는 길이 제약 없는 TEXT) —
**스키마 변경 0**. 기존 볼륨의 옛 키는 아무도 읽지 않는 죽은 행이 되고, `claim_daily("deadline", …)`가
이미 하루 1회로 막으므로 **배포 시각 제약이 없다**.

실패 분기를 전부 다르게 처리한다:

| 상황 | 처리 |
|---|---|
| 담당자가 Discord 미연결 | 자리를 잡지 않는다(나중에 연결하면 다음 알림부터 정상). `unlinked` 카운트 + 이름, 주간 보고에 미연결 한 줄. **실패는 아니다** — 한 명 때문에 `/ops`가 영구 빨강이면 그 신호를 아무도 안 본다 |
| `50007`·`50278`·`10013` (DM 거부) | 즉시 포기, `failed`, 팀 채널에 하루 1회 통보(태스크 제목·URL 없이) |
| DM 채널 열기 실패(타임아웃·5xx·틀린 봇 토큰) | `ChannelOpenFailed` → 자리를 **놓아주고** 다음 틱에 재시도. 채널 열기는 멱등이라 '결과 불명확'이 아니다. `skipped`와 따로 세어(`open_failed`) `/ops`를 빨강으로 만든다 — 안 그러면 틀린 봇 토큰이 영원히 재시도만 하는데 화면은 초록이다 |
| 조각 여러 개 중 하나에서 채널이 죽음 | 캐시를 지우고 1회 재개설, **그 조각부터** 이어 보낸다(본문 전체를 다시 보내면 앞 조각이 두 번 도착한다) |
| `429`·`5xx` | `Retry-After`/본문 `retry_after` 기반 백오프 3회. 숫자 하드코딩 금지 |
| 타임아웃(발송) | `UnknownResult` → `unknown`. 중복 발송하지 않는다 |
| 발송 직전 재확인 실패(core 5xx·429·타임아웃) | `release` + **그날 문턱 다시 열기** → 다음 틱에 다시 훑는다(하루 3회까지). `recheck_failed`로 세어 `/ops`도 빨강 |

`tick`은 `failed > 0`이면 `/ops`에 `ok: false`로 보고한다(예전엔 실패 수가 detail에만 있었다).

### 5. 프로세스·비밀

컨테이너가 하나 늘었다: `discord`(60초 발송 틱, SQLite 단일 writer)와 `discord-bot`(게이트웨이 수신,
**SQLite를 열지 않는다**). 리스너는 동기 httpx를 `asyncio.to_thread`로 부른다 — 이벤트 루프를 막으면
하트비트가 굶어 게이트웨이가 연결을 끊는다. 발신자별 분당 20회 한도도 걸었다(core의 60/m 버킷을
봇 계정 하나로 세므로 한 사람이 다 쓰면 남의 명령까지 429가 된다).

| 비밀 | 사는 곳 | 반경 |
|---|---|---|
| `DISCORD_BOT_TOKEN` (신규) | `.env.discord`만 | 봇으로서 DM·채널 게시. **core에는 아무 요청도 못 한다** |
| `CORE_TOKEN` (범위 `bot`으로 확대) | `.env.discord` | 연결된 사용자로 3개 동작(오늘·완료·연장), 그 사람 팀 범위 안에서만. `/api/integrations/` 밖 쓰기 403 |
| 연결 코드 (신규) | core DB, 화면에 1회 | 살아 있는 10분 안에 그 계정에 자기 Discord를 붙일 수 있다. `/ops` 내보내기 제외 |
| `DiscordWebhook.url` (삭제됨) | — | 채널 하나에 글쓰기 권한이 DB에 앉아 웹 UI로 편집됐다 |

`.env`와 `.env.discord`를 나눴다 — 예전 구성은 `web` 컨테이너에도 봇 토큰이 들어갔다.
`SecretFilter`에 `Bot <token>` · 봇 토큰 형태 · `DISCORD_BOT_TOKEN=` 패턴을 넣었다(기존 `bearer`
패턴은 `Bot ` 형태를 못 잡는다). **core는 이제 Discord로 나가는 요청이 0건이다.**

### 6. 확인

- core 145(SQLite) / discord_service 58 / mcp_server 16 전부 통과, ruff check·format 0.
- **Postgres 16: 이 개정에서는 전체 실행을 못 끝냈다.** `accounts`·`tasks` 테스트만 따로 돌려
  통과했고(이 변경에서 Postgres에 민감한 것 — `User`의 새 컬럼 3개와 unique·`None` 처리,
  `ChangeLog.source`가 varchar(4)에 들어가는지 — 는 그 두 파일에 다 들어 있다), 전체 스위트는
  db 컨테이너가 접속을 끊어 5회 시도 모두 중간에 멈췄다. 이 세션에서 에이전트를 180개 넘게
  돌린 호스트 상태 문제로 보이고, 직전 커밋(3e59b3b)의 140개는 같은 방법으로 통과했다.
  **남은 검증 1건**으로 아래 목록에 넣었다. 도중에 알아낸 것:
  `localhost`가 아니라 `127.0.0.1`을 써야 한다 — compose는 `127.0.0.1:5432`(IPv4)에만
  바인딩하는데 Windows에서 `localhost`는 `::1`을 먼저 시도해 **접속 하나가 130초** 걸린다
  (측정: `localhost` 130.6s / `127.0.0.1` 1.6s). 지시서·README의 명령을 고쳤다.
- **실행 중인 core에 실제로 붙여** 명령 전체를 돌렸다: 미연결 → 연결 안내, 웹에서 받은 코드로
  `연결` → "팀원 계정과 연결했습니다", `오늘` → 실제 목록(멘션·담당자 칼럼 없음),
  `완료` → 막힘에서 done으로 바뀌고 이력이 **source=dc · 행위자=사람 · 토큰=봇 토큰**,
  같은 명령 두 번 → 이력 증가 0, 없는 태스크·잘못된 날짜·잘못된 번호 → 각각의 한국어 안내.
- 권한 경계: 봇 토큰으로 `/api/tasks` POST → **403**, 세션 쿠키로 봇 경로 → **401**, 읽기 토큰 → **403**.
- 컨테이너: `discord` 이미지 287MB 빌드, 안에서 `import discord`·리스너 임포트 확인,
  `python -m discord_service bot`이 Discord 로그인까지 도달(가짜 토큰이라 `LoginFailure` — 배선 확인).
- 웹 화면: 프로필에 Discord 입력칸이 없고 `[Discord 연결]`이 코드를 1회 노출한다(브라우저 확인).
- 새 코드만 대상으로 적대 검토를 한 번 더 돌렸다(렌즈 5개 + 지적마다 회의론자 2명, 에이전트 51개).
  지적 23건 중 **확정 1건**(high)을 고쳤다 — 아래 6번.
- 내 코드에서 잡은 결함 6건을 고쳤다:
  1. `10003`이 즉시-포기 집합에 없어 **채널 재개설 분기가 죽은 코드**였다(404가 `RuntimeError`로 샜다).
  2. 조각 여러 개 중 하나가 실패하면 **본문 전체를 다시 보내** 앞 조각이 두 번 도착했다.
  3. 채널 열기 타임아웃을 '보냄 여부 불명'으로 기록해 **그날 알림을 잃었다**.
  4. 그 실패가 `/ops`에 초록으로 보였다(틀린 봇 토큰이면 영원히 조용히 재시도).
  5. `run`이 `Store`를 두 번 열었다.
  6. **`release()`만으로는 재시도되지 않았다.** 발송 직전 재확인이 실패하면 자리를 놓아주고
     "다음 틱에 재시도"라고 적어 뒀지만, `claim_daily("deadline", 날짜)`가 그날 문턱을 이미
     소비했으므로 그날 다시 돌지 않는다 — 그 사람들은 알림을 못 받고 `/ops`는 초록이었다.
     `skipped`에 섞여 있어 손실이 보이지도 않았다. 이제 `recheck_failed`로 따로 세고,
     놓아준 자리가 있으면 **그날 문턱을 다시 열어**(하루 3회까지) 아직 안 보낸 묶음만 다시 훑는다.
     중복 걱정은 없다 — 이미 보낸 묶음은 `sent` 행이 막는다. 이 결함은 웹훅 시절 코드에도
     같은 형태로 있었다(그때 '고쳤다'고 적은 것이 실은 절반만 고친 것이었다).

### 7. 일부러 빼둔 것

| 뺀 것 | 이유 |
|---|---|
| `메모` 명령 | `update_text`가 ChangeLog를 남기지 않아 내용을 바꾸는 명령이 감사 기록에서 사라진다. `services.py`에 이력 한 줄을 넣기로 결정한 뒤에 |
| `시작`·`막힘` 명령 | `완료`와 같은 호출 지점(`transition`)에 리터럴만 다르다. 5명에게 명령 6개는 과하다 |
| 슬래시 명령·버튼 | 등록 스크립트·3초 시한·`contexts`·중복 ACK가 딸려 온다. 평문 DM은 그 전부가 없다. 명령이 10개를 넘으면 다시 본다 |
| 자유 대화형(LLM) 응답 | 요청 범위 밖이다. `LLM_PROVIDER`는 주간 요약 자리로만 남아 있다 |
| 팀별 채널 모델 | 비밀도 아닌 숫자 하나를 위해 모델·마이그레이션·관리 화면을 다시 만드는 것이 방금 지운 그 화면이다. 팀이 둘 이상이 되면 `Team.discord_channel_id` 컬럼 하나 |
| 주간 보고를 개인 DM으로 | `weekly` PK가 `period_start` 하나이고 SQLite는 PK를 ALTER할 수 없다. 팀 보고는 공유물이다 |
| 리스너의 `/ops` 상태 행 | `report_status`가 경로를 하드코딩하고 `IntegrationStatus`는 `name` 단일 키라 틱의 행을 덮어쓴다. discord.py가 재접속을 맡으니 보고할 close code도 없다. `docker compose logs discord-bot`으로 본다 |

---

## 남은 것 (사용자 인프라가 필요한 것)

Docker 관련 항목은 위에서 모두 실행했다. 남은 것은 **사용자 계정·인프라가 있어야 하는 것들**뿐이다.
GUIDE-04 Step 5~8을 그대로 진행하면 된다.

- **Discord 앱 만들기**: Developer Portal에서 앱·봇 생성 → [Reset Token]으로 `DISCORD_BOT_TOKEN`,
  Guild Install(scope `bot`, permissions 3072)로 팀 서버에 추가, 주간 보고 채널 id를
  `DISCORD_CHANNEL_ID`에. **특권 인텐트는 켤 것이 없다**(APPLICATION ID·PUBLIC KEY도 필요 없다)
- **팀원 전원**: 그 서버에 참여 + 서버 우클릭 → 개인정보 보호 설정 → '서버 멤버의 DM 허용' 켜기,
  그리고 각자 웹 `/settings/profile` → [Discord 연결] → 봇에게 DM으로 `연결 <코드>`
  (안 하면 그 사람은 DM 알림을 받지 못한다 — 주간 보고에 이름이 나온다)
- **연동 계정**: `discord-bot` 계정을 팀에 넣고(**팀원이면 된다**) `bot` 범위 토큰을 셸 한 줄로
  발급해 `.env.discord`의 `CORE_TOKEN`에. 그 뒤 `docker compose up -d discord discord-bot`
- **core 테스트를 Postgres 16으로 전체 실행** (이 개정에서 못 끝낸 검증):
  `cd core && DATABASE_URL=postgres://pm:pm@127.0.0.1:5432/pm uv run pytest -q --create-db`
  → 145개. `localhost`를 쓰면 접속당 2분 걸린다
- Cloudflare Tunnel 토큰 발급과 공개 호스트 2개 등록 (`pm.<도메인>` → `web:8000`, `mcp.<도메인>` → `mcp:8080`)
- Proxmox LXC(`nesting=1`, `keyctl=1`) 생성·배포, `https://pm.<도메인>/healthz` 확인
- UptimeRobot 모니터 등록, Proxmox vzdump 예약
- Claude Code / Codex CLI / Claude 앱 / ChatGPT 커넥터 등록 (개인 토큰과 공개 MCP URL 필요)

포트는 `db`·`web`·`mcp` 모두 `127.0.0.1`에만 붙는다 — 서버에서도 지울 필요가 없다.
