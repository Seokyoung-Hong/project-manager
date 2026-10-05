# 구현 지시서 00: 공통 규칙

이 문서는 구현 담당 AI가 **가장 먼저** 읽는다. 계획의 배경은 [PLAN.md](../PLAN.md), 원래 요구사항은 [SPEC.md](SPEC.md)에 있다. 두 문서와 이 지시서가 충돌하면 **지시서가 우선**한다.

### 지시서는 두 묶음이다

| 묶음 | 무엇인가 | 지금 할 일인가 |
|---|---|---|
| `GUIDE-01-core-*` · `GUIDE-02` · `GUIDE-03` · `GUIDE-04` | **이미 만든 것의 기록.** 아무것도 없는 상태에서 core·discord·mcp·배포를 만드는 전체 코드다. 이 작업은 2026-09-10에 끝났다(커밋 `3b2fbee`) | 아니다. 기존 코드의 근거를 찾을 때 읽는다. **이 묶음의 용어는 개명 전 기준**이라 `GUIDE-V2-01`의 대조표를 함께 본다 |
| **`GUIDE-V2-00` ~ `GUIDE-V2-08`** | **지금 할 일.** 이미 있는 코드를 고쳐 조직·팀 계층과 GitHub 통합을 넣는다 | **그렇다.** `GUIDE-V2-00`부터 읽고 01 → 08 순서로 진행한다 |

근거 문서는 [IMPL-PLAN.md](IMPL-PLAN.md)(2026-09-10 목업 정합)와 [IMPL-PLAN-2.md](IMPL-PLAN-2.md)(2026-09-11 조직·팀 재구성과 GitHub 통합)다. 이 지시서와 다르면 지시서가 우선한다.

---

## 1. 작업 방식

1. 지시서의 Step 순서를 지킨다. Step 안의 항목 순서도 지킨다. 건너뛰지 않는다.
2. 각 Step 끝의 **검증** 항목을 실제로 실행하고, 기대 결과와 다르면 다음 Step으로 가지 않는다.
3. 지시서에 코드가 적혀 있으면 **그대로** 옮긴다. 이름, 필드, 시그니처, 문자열을 바꾸지 않는다. 오타를 발견하면 고치되 무엇을 고쳤는지 완료 보고에 적는다.
4. 지시서에 없는 기능, 필드, 화면, 옵션, 설정을 추가하지 않는다. "있으면 좋을 것"은 만들지 않는다.
5. 모호하면 **테스트가 통과하는 가장 단순한 구현**을 고른다. 질문하지 않는다.
6. 각 Step이 끝나면 git commit 한다. 메시지 형식: `step N: 요약` (예: `step 3: tasks services + tests`).
7. 완료 보고는 다음 형식으로 쓴다.

```
## Step N 완료
- 만든 파일: ...
- 실행한 검증 명령과 결과: ...
- 지시서와 다르게 한 것: (없으면 "없음")
- 실패하거나 못 한 것: (없으면 "없음")
```

---

## 2. 도구와 명령

| 항목 | 값 |
|---|---|
| Python | 3.12 |
| 패키지 관리 | `uv` (각 파트 디렉터리마다 독립 `pyproject.toml`) |
| 실행 | `uv run <명령>` (예: `uv run python manage.py migrate`, `uv run pytest`) |
| 린터 | `ruff` (`uv run ruff check .` 와 `uv run ruff format .`) |
| 테스트 | `pytest` (core는 `pytest-django`) |
| 컨테이너 | Docker + Docker Compose (GUIDE-04) |
| git | 저장소 루트 `project-manager/`에서 `git init`. 원격 없음 |

`uv`가 없으면 먼저 설치한다: Windows PowerShell `powershell -ExecutionPolicy ByPass -c "irm https://astral.sh/uv/install.ps1 | iex"`, Linux/macOS `curl -LsSf https://astral.sh/uv/install.sh | sh`.

---

## 3. 코드 규칙

### 허용 의존성 (이 외에는 추가 금지)

| 파트 | 실행 의존성 | 개발 의존성 |
|---|---|---|
| `core/` | django, django-ninja, psycopg[binary], dj-database-url, gunicorn, whitenoise, **cryptography** | pytest, pytest-django, ruff |
| `discord_service/` | httpx, discord.py | pytest, ruff |
| `mcp_server/` | mcp, httpx, uvicorn | pytest, ruff |

`discord.py`는 게이트웨이(WebSocket) 수신 전용이다 — 하트비트·RESUME·close code 처리를 직접 쓰지 않기 위해 산다(`discord_service/listener.py`). 발송은 계속 `httpx`로 한다.

core는 Discord로 나가는 요청을 한 곳도 하지 않는다(발송은 `discord_service` 전담). Discord 봇을 붙일 때 core의 의존성이 하나도 늘지 않은 이유이기도 하다.

**`cryptography`는 GitHub 통합에서 딱 두 가지에 쓴다**(`GUIDE-V2-07`): 사용자 GitHub 토큰의 Fernet 암호화, GitHub App 설치 토큰을 받기 위한 JWT의 RS256 서명. 다른 용도로 쓰지 않는다. GitHub 통합에는 **네 번째 파트도 새 컨테이너도 새 공개 호스트도 없다** — 앱 수준 웹훅이라 수신 경로가 기존 `pm.<도메인>` 아래 하나뿐이기 때문이다.

프론트엔드: HTMX를 **파일로 내려받아** `core/web/static/vendor/`에 둔다. CSS 프레임워크 없음. 디자인 토큰과 컴포넌트 스타일은 `core/web/static/app.css` 한 파일에 직접 쓴다(GUIDE-01-4). CDN 링크 금지. **예외 한 줄:** Pretendard 폰트 CSS(`https://cdn.jsdelivr.net/gh/orioncactus/pretendard@v1.3.9/dist/web/static/pretendard.min.css`)는 `<link>`로 쓴다. npm, Tailwind, React, 빌드 도구 금지.

디자인 원본: `README.md`(핸드오프)와 `유달리 업무 목업 v2.dc.html`, `TaskRow2.dc.html`, 그리고 이번 라운드의 **`유달리 신규 기능 목업.dc.html`**. 색·크기·문구는 README 표를 따른다. 목업의 `class Component`는 참고용이며 옮겨 쓰지 않는다. `NewMock/` 폴더 안의 `v2`·`TaskRow2` 사본은 저장소 사본보다 오래된 판이므로 보지 않는다.

### 하지 말 것

- Django REST Framework, Celery, Redis, django-allauth, 기타 미허용 패키지 사용 금지.
- Django signals 사용 금지. 변경 이력은 `services.py`가 명시적으로 쓴다.
- 클래스 기반 뷰, 추상 기반 클래스, 리포지토리 패턴, 인터페이스, 팩토리 금지. 함수형 뷰와 평범한 함수만 쓴다.
- 구현체가 하나뿐인 추상화 금지. 설정값이 될 이유가 없는 상수를 설정으로 빼지 않는다.
- `Task`, `Project`를 `services.py` 밖에서 `save()`나 `update()`로 수정하지 않는다. (읽기는 어디서나 가능)
- `ChangeLog`를 `services.py` 밖에서 만들지 않는다. 어디서도 수정·삭제하지 않는다.
- 뷰와 API 라우터에 업무 규칙(검증, 상태 전이, 이력)을 쓰지 않는다. 항상 services 함수를 부른다.
- core가 `discord_service`나 `mcp_server`를 import하지 않는다. 반대도 마찬가지다. 세 파트는 HTTP로만 통신한다.
- 로그에 토큰·비밀키·Discord 봇 토큰을 남기지 않는다.
- `DISCORD_BOT_TOKEN`과 `CORE_TOKEN`은 `.env.discord`에만 둔다. core DB·화면·오류 메시지·로그·`/ops` 내보내기·`ChangeLog` 어디에도 넣지 않는다. core는 Discord로 나가는 요청을 하지 않는다(발송은 `discord_service` 전담).
- **Discord 사용자 ID를 사용자가 직접 입력하게 하지 않는다.** 연결은 웹에서 발급한 1회용 코드와 게이트웨이가 채운 `author.id`의 교환으로만 이뤄진다(어느 한쪽만으로는 소유가 증명되지 않는다).
- **`bot` 범위 토큰은 웹에서 발급하지 않는다**(자기 발급은 권한 상승이다). `TokenForm`의 범위 선택에 `bot`을 넣지 않고, 발급은 서버 셸 한 줄로만 한다(GUIDE-04 Step 7).
- 테스트를 지우거나 `skip`으로 통과시키지 않는다.
- 새 파일을 만들 때 지시서의 디렉터리 구조 밖에 두지 않는다.

### 스타일

- 줄 길이 100. `ruff format` 결과를 그대로 둔다.
- 함수는 짧게. 한 함수가 화면 한 페이지를 넘기면 나눈다.
- 주석은 "왜"만 쓴다. "무엇"은 코드가 말한다.
- 한국어 UI 문자열은 지시서에 적힌 것을 그대로 쓴다. 지시서에 없는 문자열은 짧고 평이한 한국어로 쓴다.
- 의도적으로 단순화한 곳(한계가 있는 구현)에는 `# ponytail: <한계>, <업그레이드 경로>` 주석을 남긴다.

---

## 4. 시간과 날짜 규칙 (모든 파트 공통)

- 저장은 UTC (`USE_TZ=True`). 표시·판정은 `Asia/Seoul`.
- 기한(`due_date`)은 **날짜만**. 시각 없음.
- "오늘" = `Asia/Seoul` 기준 오늘 날짜.
- 기한 초과 = 미완료이고 `due_date < 오늘`. 당일은 초과가 아니다.
- 이번 주 = 이번 주 월요일부터 일요일까지.
- 주간 보고 기간 = `week_start`(월요일) 00:00 KST부터 다음 월요일 00:00 KST 직전까지.

---

## 5. 상태·중요도·역할 값 (모든 파트 공통)

| 종류 | 코드 값 | 화면 표기 |
|---|---|---|
| 태스크 상태 | `todo` / `doing` / `paused` / `blocked` / `review` / `done` / `cancelled` | 시작 전 / 진행 중 / 일시정지 / 막힘 / 검토 대기 / 완료 / 취소 |
| 미완료 상태 | `todo`, `doing`, `paused`, `blocked`, `review` | |
| 멈춤 상태 | `paused`, `blocked` | 사유(`stop_reason`)를 가질 수 있다. `blocked`는 사유 필수 |
| 닫힌 상태 | `done`, `cancelled` | 제목 취소선 |
| 중요도 | 정수 `1`~`10`, 기본 `5` | `n/10`. 티어: 8~10 높음(굵게) / 4~7 중간 / 1~3 낮음 |
| 프로젝트 상태 | `preparing` / `on_hold` / `waiting` / `active` / `paused` / `done` / `stopped` / `eol` | 🧪 준비 중 / 🕓 보류 중 / 🗂️ 대기 중 / 🚧 진행 중 / ⏸️ 일시 중단 / ✅ 완료 / 🛑 정지 / ⚰️ 지원 종료 (설명 문구는 모델의 `STATUS_DESC`) |
| 조직 역할 | `admin` / `member` | 관리자 / 멤버 |
| 팀 | 조직 안의 사람 묶음. 역할 없음. **가시성을 제한하지 않는다** | 팀 |
| 마일스톤 상태 | `planned` / `active` / `done` | 준비 중 / 진행 중 / 완료 |
| 이슈 상태 | `open` / `closed` | 열림 / 닫힘 |
| PR 상태 | `open` / `merged` / `closed` | 열림 / 머지됨 / 닫힘 |
| 링크 종류 | `doc` / `pr` / `repo` / `issue` / `dash` / `other` | 문서 / PR / 저장소 / 이슈 / 대시보드 / 기타 (`pr`·`repo`는 남은 데이터용이고 새 폼에서는 고르지 못한다) |
| 토큰 범위 | `read` / `write` / `bot` | 읽기 / 읽기·쓰기 / Discord 봇 |
| 변경 경로 | `web` / `api` / `mcp` / `dc` / `gh` | 웹 / API / AI / Discord / GitHub |

`ChangeLog.source`가 `discord`가 아니라 `dc`인 이유: 컬럼이 `max_length=4`다(7자는 Postgres `DataError`). 화면은 `get_source_display()`로 "Discord"를 그리고, API 응답만 코드 `"dc"`를 그대로 준다.

태스크 번호 표기: `TASK-{id}` (예: `TASK-12`). 별도 번호 컬럼 없음.

낙관적 잠금(`version`)은 팀 데이터(상태·담당자·기한·중요도·프로젝트·사유·프로젝트 필드)에만 걸린다. 제목·설명·완료 조건·다음 행동·진행 메모는 자동 저장되며 `version`을 올리지 않는다(`# ponytail: 부속 텍스트는 last-write-wins`).

---

## 6. 저장소 최상위 구조

```
project-manager/
  PLAN.md
  docs/
    SPEC.md
    GUIDE-00-rules.md     ← 이 문서
    IMPL-PLAN.md          2026-09-10 목업 정합 결정
    IMPL-PLAN-2.md        2026-09-11 조직·팀 재구성과 GitHub 통합 결정. GUIDE-V2-*의 근거
    GUIDE-V2-00-overview.md     ← 지금 할 일은 여기부터
    GUIDE-V2-01-org-teams.md
    GUIDE-V2-02-shell-ia.md
    GUIDE-V2-03-board-calendar.md
    GUIDE-V2-04-capacity-roadmap.md
    GUIDE-V2-05-notes.md
    GUIDE-V2-06-api-docs.md
    GUIDE-V2-07-github-read.md
    GUIDE-V2-08-github-write.md
    GUIDE-01-core-1-setup-models.md   ┐
    GUIDE-01-core-2-services.md       │
    GUIDE-01-core-3-api.md            │ 이미 만든 것의 기록.
    GUIDE-01-core-4-web.md            │ 용어는 개명 전 기준이다
    GUIDE-01-core-5-tests.md          │
    GUIDE-02-discord.md               │
    GUIDE-03-mcp.md                   │
    GUIDE-04-deploy.md                ┘
  README.md               목업 핸드오프(디자인 원본) + 실행 안내
  유달리 업무 목업 v2.dc.html, TaskRow2.dc.html, 유달리 신규 기능 목업.dc.html, support.js
                          디자인 참고 파일. 구현 대상 아님
  compose.yml             GUIDE-04. 이번 라운드에서 바뀌지 않는다
  .env.example            GUIDE-04 + GUIDE-V2-07(GitHub App 설정 5개, CREDENTIAL_KEY)
  .env.discord.example    GUIDE-04. `TEAM_ID` → `ORG_ID`로 바뀐다
  .gitignore
  core/
    accounts/  orgs/  projects/  tasks/  notes/  github/  reports/  api/  web/  config/  common/
  discord_service/        GUIDE-02
  mcp_server/             GUIDE-03
```

`orgs/`는 기존 `teams/`를 개명한 것이고 `notes/`·`github/`는 이번에 새로 만든다(`GUIDE-V2-01`·`05`·`07`).

이 개정(웹훅 → 봇)에서 새로 생긴 파일:

| 파일 | 하는 일 | 지시서 |
|---|---|---|
| `core/accounts/services.py` | Discord 연결(코드 발급·교환·해제·행위자 조회) | GUIDE-01-2 |
| `core/api/routers/discord.py` | 봇 명령 5개 엔드포인트(`BotTokenAuth`) | GUIDE-01-3 |
| `discord_service/discord_service/listener.py` | 게이트웨이 DM 수신(discord.py) | GUIDE-02 |
| `discord_service/discord_service/commands.py` | DM 평문 명령 해석과 답장 문구 | GUIDE-02 |
| `.env.discord.example` | 봇 컨테이너 전용 환경 변수 견본 | GUIDE-04 |

같이 사라진 것: `teams.DiscordWebhook` 모델과 `core/web/templates/teams/webhooks.html`(알림 채널 화면), `teams/services.py`의 웹훅 함수 8개, `GET /api/integrations/discord/webhooks`.

`.gitignore` 내용 (Step 0에서 만든다):

```
.venv/
__pycache__/
*.pyc
*.sqlite3
*.sqlite
.env
.env.discord
staticfiles/
.pytest_cache/
.ruff_cache/
/data/
```

---

## 7. 완료 정의

한 파트가 "완료"이려면:

1. 해당 GUIDE의 모든 Step 검증이 통과한다.
2. `uv run ruff check .` 오류 0.
3. `uv run pytest` 전부 통과. skip 0.
4. GUIDE 마지막 절의 완료 체크리스트에 전부 체크된다.
5. 완료 보고서를 작성했다.
