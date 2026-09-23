# 산돌이 태스크

팀의 태스크를 한곳에서 보고, 오늘 할 일을 고르고, 마감·주간 현황을 자동으로 알리는 업무 관리 웹앱.
세 파트로 나뉘며 서로 HTTP API로만 통신한다.

| 파트 | 역할 | 스택 |
|---|---|---|
| [`core/`](core) | 웹 화면·데이터·HTTP API. 업무 규칙은 전부 여기 `services.py`에 있다 | Django 5.2, Django Ninja, PostgreSQL, HTMX |
| [`discord_service/`](discord_service) | 마감 알림과 DM·슬래시 명령, 프로젝트 채널 연결 및 내부 MCP 채널 제어를 제공한다 | httpx, discord.py, SQLite |
| [`mcp_server/`](mcp_server) | Claude·ChatGPT 등 AI 클라이언트가 태스크를 읽고 고치는 MCP 서버 | mcp, httpx, uvicorn |

## 문서

| 문서 | 내용 |
|---|---|
| [PLAN.md](PLAN.md) | 기획 배경과 전체 계획 |
| [docs/SPEC.md](docs/SPEC.md) | 원래 요구사항 |
| [docs/IMPL-PLAN.md](docs/IMPL-PLAN.md) | 지시서와 목업의 정합 결정표 (2026-09-10) |
| [docs/IMPL-PLAN-2.md](docs/IMPL-PLAN-2.md) | 조직·팀 재구성과 GitHub 통합 결정 (2026-09-11) |
| [docs/GUIDE-V2-00-overview.md](docs/GUIDE-V2-00-overview.md) ~ [V2-08](docs/GUIDE-V2-08-github-write.md) | 지금 진행 중인 라운드의 구현 지시서 |
| [docs/GUIDE-00-rules.md](docs/GUIDE-00-rules.md) | 공통 규칙 (가장 먼저 읽는다) |
| [docs/GUIDE-01-core-1-setup-models.md](docs/GUIDE-01-core-1-setup-models.md) ~ [01-5](docs/GUIDE-01-core-5-tests.md) | core 구현 지시서 |
| [docs/GUIDE-02-discord.md](docs/GUIDE-02-discord.md) | discord_service 구현 지시서 |
| [docs/GUIDE-03-mcp.md](docs/GUIDE-03-mcp.md) | mcp_server 구현 지시서 |
| [docs/GUIDE-04-deploy.md](docs/GUIDE-04-deploy.md) | 배포 절차 (Proxmox + Docker Compose + Cloudflare Tunnel) |
| [docs/OPERATIONS-DEPLOYMENT.md](docs/OPERATIONS-DEPLOYMENT.md) | 운영 서버 SSH 신뢰 확인, 서비스 범위별 배포, Discord 프로젝트 채널 관리 |

## 브라우저 안 AI 에이전트 (WebMCP)

로그인한 화면이 [WebMCP](https://github.com/webmachinelearning/webmcp) 도구를 등록한다. 브라우저에 붙은
AI 에이전트가 지금 보고 있는 사람의 세션 그대로 태스크를 읽고 고칠 수 있다. 토큰을 따로 발급하지 않고,
원격 MCP(`mcp_server`)와 같은 이름·같은 규칙의 도구를 쓴다.

| | `mcp_server` | WebMCP |
|---|---|---|
| 누구를 위한 것인가 | Claude·ChatGPT 등 **밖에 있는** AI | **브라우저 안에서** 이 화면을 보고 있는 AI |
| 인증 | API 토큰(`/settings/tokens`) | 지금 로그인한 세션 쿠키 |
| 코드 | [`mcp_server/mcp_server/server.py`](mcp_server/mcp_server/server.py) | [`core/web/static/webmcp.js`](core/web/static/webmcp.js) |

도구는 13개다. 읽기는 `list_orgs` `list_members` `list_projects` `list_tasks` `get_task` `get_today`
`get_org_status` `get_governance`, 쓰기는 `create_task` `update_task` `transition_task` `append_note`
`add_to_today`. 전부 `/api`를 그대로 부르므로 권한·낙관적 잠금(version)·검증은 서버 규칙 그대로다.
쓰기가 끝나면 화면 본문만 다시 그려서 사람이 보는 것과 어긋나지 않게 한다.

### 규약

- 진입점은 표준대로 `document.modelContext`다(`navigator.modelContext`는 폴리필용 대비책).
- `execute`가 돌려준 값은 **브라우저가 JSON으로 직렬화해** 에이전트에게 준다. 그래서 감싸지 않고 API 응답을 그대로 돌려준다.
- 실패는 프라미스를 거부하는 대신 `{ok: false, error}`로 돌려준다. 스펙상 거부하면 결과가 `null`이 되어
  서버가 알려 준 이유(충돌 시 최신 `version`, 검증 실패 사유)가 통째로 사라지기 때문이다
  ([스펙도 열어 둔 문제](https://webmachinelearning.github.io/webmcp/)).
- 태스크·메모 본문은 남이 쓴 글이라 모든 도구에 `untrustedContentHint`를, 읽기 도구에는 `readOnlyHint`를 붙였다.

### 켜지는 조건 (둘 다 필요하다)

1. **오리진 트라이얼 토큰** — 크롬 149·엣지 150은 아직 실험 단계라 `WEBMCP_ORIGIN_TRIAL`이 비어 있으면
   `document.modelContext` 자체가 없다. 로컬에서 시험만 할 때는 `about:flags#enable-webmcp-testing`을 켠다.
2. **오리진 키 에이전트 클러스터** — 스펙이 요구한다. `common.middleware.origin_agent_cluster`가
   모든 응답에 `Origin-Agent-Cluster: ?1`을 붙인다. 없으면 `registerTool()`이 `SecurityError`로 죽는다.

지원하지 않는 브라우저에서는 아무 일도 하지 않는다(`document.modelContext`가 없으면 즉시 빠져나온다).

## 로컬 개발 빠른 시작

```bash
cd core
uv sync
uv run python manage.py migrate
uv run python manage.py createsuperuser
uv run python manage.py runserver
```

`http://127.0.0.1:8000/login` 으로 접속한다. API 문서는 로그인 후 `/api/docs`.

테스트와 린트:

```bash
cd core            && uv run pytest -q && uv run ruff check . && uv run ruff format --check .
cd discord_service && uv run pytest -q && uv run ruff check .
cd mcp_server      && uv run pytest -q && uv run ruff check .
```

Postgres로도 한 번 돌린다(아래 Docker 실행으로 `db`만 띄운 상태에서):

```bash
cd core && DATABASE_URL=postgres://pm:pm@127.0.0.1:5432/pm uv run pytest -q
```

## Docker 로컬 실행 (기본)

```bash
cp .env.example .env
cp .env.discord.example .env.discord   # 비어 있어도 된다. 없으면 compose가 파일 전체를 못 읽는다
```

`.env`에서 네 줄만 로컬용으로 바꾼다:

```
DEBUG=1
ALLOWED_HOSTS=localhost,127.0.0.1,web
CSRF_TRUSTED_ORIGINS=http://localhost:8000,http://127.0.0.1:8000
SITE_URL=http://localhost:8000
```

```bash
docker compose up -d --build              # db·web·mcp만 뜬다
docker compose exec web python manage.py createsuperuser
```

- 웹: **http://localhost:8000** (`web`이 `0.0.0.0:8000`에 붙는다)
- MCP: **http://localhost:8080** · Postgres: `127.0.0.1:5432`
- `web`의 8000번만 **바깥에 열려 있다.** 다른 장비의 리버스 프록시(NginxProxyManager)가 여기로 붙기 때문이다. 방화벽에서 **프록시 장비 IP만** 8000번을 열어 둔다 — 직접 오는 요청은 평문 HTTP다. Cloudflare Tunnel만 쓴다면 `compose.yml`의 `web` 포트를 `"127.0.0.1:8000:8000"`으로 되돌린다.
- MCP와 Postgres는 루프백만 바인딩한다.

`discord`·`discord-bot`·`cloudflared`는 **프로필**로 빼 두었다. 시크릿이 없으면 기동에 실패하므로
기본 `up`에서 뜨지 않고, 필요할 때만 켠다:

```bash
docker compose --profile discord up -d    # .env.discord를 채운 뒤
docker compose --profile tunnel up -d     # CLOUDFLARE_TUNNEL_TOKEN을 채운 뒤
```

이름을 직접 대면(`docker compose up -d discord`) 프로필과 무관하게 뜬다 — 배포 명령은 그대로 쓴다.

SQLite로 개발하던 데이터를 Docker(Postgres)로 옮기려면:

```bash
uv run --project core python core/manage.py dumpdata --natural-foreign --natural-primary   --exclude contenttypes --exclude auth.permission --exclude sessions -o devdata.json
docker compose exec -T web python manage.py loaddata --format=json - < devdata.json
```

## 서버 배포 요약

1. Proxmox에 Debian 12 LXC(`nesting=1`, `keyctl=1`)를 만들고 Docker를 설치한다.
2. 저장소를 `/opt/project-manager`에 복사한다(`.venv/`, `db.sqlite3` 제외).
3. `.env`와 `.env.discord`를 실제 값으로 채운다(포트는 셋 다 루프백이라 그대로 둔다).
4. Cloudflare Zero Trust에서 터널을 만들고 공개 호스트 **두 개**를 연결한다: `pm.<도메인>` → `web:8000`, `mcp.<도메인>` → `mcp:8080`. Discord 봇은 밖으로 나가는 연결만 쓰므로 공개 경로가 필요 없다.
5. `docker compose up -d --build db web mcp cloudflared` 후 superuser 생성.
6. 팀 생성 → 초대 링크 배포.
7. Discord Developer Portal에서 봇을 만들어(`[Reset Token]`) 팀 서버에 설치하고, 토큰과 채널 id를 `.env.discord`에 넣는다. 특권 인텐트는 켜지 않는다. 팀원 전원이 서버에 참여하고 '서버 멤버의 DM 허용'을 켠다.
8. `discord-bot` 계정을 팀 **팀원**으로 넣고(관리자 승격 불필요) `bot` 범위 토큰을 셸로 발급해 `CORE_TOKEN`에 넣는다:

   ```bash
   docker compose exec web python manage.py shell -c "from accounts.models import ApiToken,User; print(ApiToken.issue(User.objects.get(username='discord-bot'),'Discord 봇','bot')[1])"
   ```

9. `docker compose up -d discord discord-bot` → `python -m discord_service test`로 채널 확인, `docker compose logs -f discord-bot`으로 리스너 확인.
10. 각자 웹 `/settings/profile`의 **[Discord 연결]**로 코드를 받아 봇에게 DM `연결 <코드>`. 연결하기 전에는 개인 DM 알림이 가지 않는다.

자세한 절차는 [docs/GUIDE-04-deploy.md](docs/GUIDE-04-deploy.md)에 있다.

## 환경 변수

파일이 둘이다. `web`은 `.env`만, `discord`·`discord-bot`은 `.env.discord`만 읽는다 — Discord 봇 토큰과 `CORE_TOKEN`이 사용자 요청을 처리하는 프로세스의 환경에 들어가지 않게 나눠 두었다. 둘 다 git에 올리지 않는다.

`.env.example` → `.env`

| 이름 | 파트 | 설명 |
|---|---|---|
| `SECRET_KEY` | core | Django 비밀키. `python3 -c "import secrets;print(secrets.token_urlsafe(50))"` |
| `DEBUG` | core | 운영은 `0` |
| `ALLOWED_HOSTS` | core | 쉼표로 구분한 호스트 목록 |
| `CSRF_TRUSTED_ORIGINS` | core | 쉼표로 구분한 오리진(스킴 포함) |
| `SITE_URL` | core | 링크·초대 URL을 만들 때 쓰는 기준 주소 |
| `MCP_URL` | core | `/settings/tokens`의 AI 클라이언트 연결 예시에 쓰는 MCP 공개 주소. 기본 `https://project.sio2.kr` |
| `WEBMCP_ORIGIN_TRIAL` | core | WebMCP 오리진 트라이얼 토큰. 비우면 브라우저 도구 등록만 빠진다 |
| `POSTGRES_PASSWORD` | db·core | Postgres 비밀번호 |
| `CLOUDFLARE_TUNNEL_TOKEN` | cloudflared | 터널 토큰 |

`.env.discord.example` → `.env.discord`

| 이름 | 설명 |
|---|---|
| `CORE_TOKEN` | `discord-bot` 계정의 **`bot` 범위** API 토큰. 웹에서는 발급할 수 없다(서버 셸 한 줄로만) |
| `ORG_ID` | 알림 대상 조직 id |
| `DISCORD_BOT_TOKEN` | Developer Portal → Bot → `[Reset Token]`. 이 파일 밖으로 내보내지 않는다 |
| `DISCORD_CHANNEL_ID` | 주간 보고와 'DM을 보낼 수 없다' 통보가 갈 채널 id |
| `TZ` | 기본 `Asia/Seoul` |
| `SEND_HOUR` | 마감 알림 시각(시). 기본 9 |
| `WEEKLY_WEEKDAY` / `WEEKLY_HOUR` | 주간 보고 요일(0=월)·시각. 기본 0, 9 |
| `LLM_PROVIDER` | 비우면 고정 형식 보고서 |
| `SITE_NAME` | 확인 메시지에 쓰는 이름 |

`CORE_URL`·`DB_PATH`는 compose가 넣어 준다. `mcp_server`는 `CORE_URL`과 `PORT`만 쓴다.

## 목업 보는 법

저장소 루트에서:

```bash
python -m http.server 8765
```

`http://127.0.0.1:8765/산돌이 업무 목업 v2.dc.html` 을 연다. 화면 문구·색·크기의 원본은 아래 디자인 핸드오프 절이다.

---

# 디자인 핸드오프: 산돌이 태스크 (팀 태스크 관리 웹앱)

> 여기의 팀은 개명 전 용어로 조직을 뜻한다.

## 최신 목업 동작 (2026-09-10)

- 통계 클릭은 표시된 대상과 동일한 목록으로 이동한다. 팀 지표는 팀 전체 + 해당 필터, 개인 완료 지표는 오늘/지난 7일 완료 목록이다. 기간은 목업 기준일을 포함한 7일이다.
- 내 태스크의 팀원 선택에 팀 전체를 추가했다. 팀 전체 목록에는 담당자 이름을 표시한다.
- 마감 기준 자동 추가 및 중요도순 추천은 유지한다. 사용자가 명시적으로 '오늘 제외'한 태스크만 제외하며 복원할 수 있다. 제외는 이 목업의 현재 날짜 세션 기준이다.
- 체크리스트가 있는 태스크만 체크리스트 완료율을 표시한다. 상태를 임의의 40%·80%로 환산하지 않는다.
- 첫 화면은 상세 패널과 일정이 닫힌다. 일정 보기로 시간표/캘린더를 열 수 있다. 상세는 태스크 선택 시 연다.
- 그라데이션(`--brand-grad` 토큰 삭제)·카드 그림자·코칭 문구를 없앴다. 색은 상태 배지와 주요 버튼에만 쓴다. 완료/잔여 수치는 작은 요약 링크로 표시한다.
- 700px 이하: 메뉴 두 줄, 프로젝트 가로 스크롤, 상세 전체 화면, 팀 지표 2열. 1150px 이하 상세 열림 시 본문 대신 상세를 표시한다.
- 진행 메모는 기존처럼 단일 자동 저장 메모장이다. 막힘 사유 필수 처리도 유지한다.
- 서버 저장은 구현하지 않은 인터랙티브 목업이다.

## Overview
산돌이 서비스(학식 API, 카카오톡 챗봇, 서버 운영 등) 개발팀이 쓰는 내부 태스크 관리 도구. 개발자와 비개발 직군이 함께 쓴다는 전제로, 상태 이름과 안내 문구를 평이한 한국어로 통일했다. 핵심 원칙:

- 태스크 담당자는 **항상 1명**. 프로젝트 관리자는 **여러 명** 가능.
- 태스크 기한이 없으면 **기한 미정 사유** 필수. 기한 연장 시 **연장 사유** 필수.
- "막힘" 상태는 **사유 필수**, "일시정지"는 사유 선택.
- 설명·완료 조건·진행 메모는 **자동 저장**. 막힘 전환과 사유 수정은 사유 입력 후 버튼으로 확정한다.
- 오늘 할 일은 사용자가 직접 고르되, 마감이 N일 이내로 들어오면 **자동으로 담김**. 자동 담긴 항목은 '오늘 제외'로 개별 제외할 수 있다.

## About the Design Files
이 번들의 `.dc.html` 파일은 **HTML로 만든 디자인 레퍼런스(프로토타입)**다. 의도한 모양과 동작을 보여주는 것이 목적이며, 그대로 프로덕션에 복사하는 코드가 아니다. 대상 코드베이스의 기존 환경(React, Vue, SwiftUI 등)과 패턴·라이브러리로 **다시 구현**해야 한다. 아직 환경이 없다면 프로젝트에 가장 적합한 프레임워크를 선택해 구현한다.

- `산돌이 업무 목업 v2.dc.html` — 전체 앱 (템플릿 + 상태 로직 클래스). 색·간격·타이포는 인라인 스타일이 기준이고, 상단 `<style>`은 그리드·sticky·반응형(1150px/700px) 레이아웃만 담는다. 하단 `<script data-dc-script>` 안의 `class Component`가 상태·파생값·핸들러의 단일 진실 원천이다. 구현 시 이 클래스의 `renderVals()`를 읽으면 화면에 필요한 모든 파생 데이터를 알 수 있다.
- `TaskRow2.dc.html` — 태스크 행(카드) 컴포넌트.
- `support.js` — 프로토타입 런타임. 구현과 무관, 무시.

브라우저에서 `산돌이 업무 목업 v2.dc.html`을 열면 동작을 직접 확인할 수 있다.

## Fidelity
**High-fidelity.** 색·타이포·간격·상태·문구가 최종안이다. 코드베이스의 컴포넌트 라이브러리로 픽셀 단위로 재현하되, 아래 토큰을 그대로 매핑한다. 데스크톱 우선(~1280px 기준)이며 flex-wrap 기반으로 좁은 폭에서도 깨지지 않게 흐른다. 700px 이하 모바일 레이아웃 적용: 두 줄 상단 메뉴, 가로 스크롤 프로젝트 메뉴, 단독 상세 화면.

## Domain Model

### Member
`{ id, name }` — 예시 4명: 김민준(나, id 1), 이서연, 박지호, 최수아.

### Project
```
{ id, name, purpose, owners: number[], status }
```
- `owners`: 관리자 여러 명. 빈 배열이면 "미지정" (경고색으로 표시).
- **목표일 없음** (의도적으로 제거).
- `status` (8단계, 이모지 포함 레이블과 설명을 UI에 그대로 노출):

| code | label | desc |
|---|---|---|
| preparing | 🧪 준비 중 | 기획/기초 구상 중 |
| on_hold | 🕓 보류 중 | 기능 추가 예정이나 우선순위 낮아 대기 중 |
| waiting | 🗂️ 대기 중 | 착수 예정이지만 아직 명확하지 않음 |
| active | 🚧 진행 중 | 개발 또는 구현 진행 중 |
| paused | ⏸️ 일시 중단 | 외부 사유나 리소스 부족으로 잠시 멈춤 |
| done | ✅ 완료 | 유지보수 외 별도 작업 없음 |
| stopped | 🛑 정지 | 모든 작업이 완료되어 현재 상태로 종료 가능하지만, 다른 프로젝트와의 연계 가능성이 높아 추후 재개될 여지가 많은 상태 |
| eol | ⚰️ 지원 종료 | 프로젝트가 더 이상 필요하지 않거나 대체되어, 유지보수·재개 가능성 모두 없는 상태 |

### Task
```
{ id, title, project, assignee (1명), status, priority (1~10), due (YYYY-MM-DD | null),
  noDueReason, stopReason, completedAt, description, doneWhen, nextAction,
  checklist: [{text, done}], notes: string, links: [{kind,title,url}],
  history: [{field, from, to, time, actor, source}] }
```
- 표시 번호: `TASK-{id}`.
- `status` (7단계) + 한 줄 설명 (상세 패널의 상태 셀렉트 아래에 표시):

| code | label | hint | pill bg / text |
|---|---|---|---|
| todo | 시작 전 | 아직 손대지 않았어요. | `--bg-fill` / `--text-primary` |
| doing | 진행 중 | 지금 하고 있어요. | `#F5A623` / `#1F1400` |
| paused | 일시정지 | 개인 사유나 다른 작업 때문에 잠시 멈췄어요. 다시 시작하면 진행 중으로 바꿔 주세요. | `--bg-fill` / `--text-secondary` |
| blocked | 막힘 | 운영상 문제 등 외부 요인으로 멈췄어요. 팀이 함께 풀어야 하는 상태예요. | `#F6C9C4` / `#6B1410` |
| review | 검토 대기 | 다 했고, 다른 사람의 확인을 기다려요. | `#CFE3F7` / `#0B3A66` |
| done | 완료 | 끝났어요. | `#B9E6CB` / `#0B3D22` |
| cancelled | 취소 | 하지 않기로 했어요. | `--bg-fill` / `--text-secondary` |

- 열린 상태(open) = todo, doing, paused, blocked, review. 닫힌 상태 = done, cancelled (제목 취소선).
- 진행률: 체크리스트가 있을 때만 `체크리스트 done/total` 텍스트로 표시한다. 체크리스트가 없으면 진행률을 표시하지 않는다(상태를 %로 환산하지 않음).
- 중요도 티어: 8~10 높음(굵게 표시), 4~7 중간, 1~3 낮음.
- 기한 초과 = open && due < 오늘. 라벨 뒤에 " 초과", 색 `--danger`.

### Business Rules
1. `todo → doing` 전환 시 `due`가 없으면 거부, 행에 오류 표시: "목표 기한이 없어서 진행 중으로 바꾸지 못했어요. 기한을 먼저 정해 주세요."
2. `blocked` 선택 시 사유 입력을 열고 기존 상태를 유지한다. 공백이 아닌 사유와 상태를 함께 확정한다. 취소 시 상태와 이력은 바뀌지 않으며, 기존 막힘 사유도 빈 값으로 저장할 수 없다.
3. blocked/paused 외 상태로 바꾸면 `stopReason` 초기화.
4. `done`으로 바꾸면 `completedAt = 오늘`; 다시 열면 null.
5. 모든 상태 변경은 `history`에 `{field:'상태', from, to, time, actor, source:'웹'}` 기록.
6. 기한 연장: 새 날짜는 현 기한보다 뒤여야 하고 사유 필수. history에 `기한 from→to (연장: 사유)` 기록, 진행 메모는 변경하지 않는다.
7. 태스크 생성: 제목 필수. 기한 없으면 기한 미정 사유 필수. 상태 `todo`.
8. 프로젝트 생성/수정: 이름 필수.
9. 다른 팀원의 태스크는 **읽기 전용** (상태 셀렉트 disabled, '오늘 하기' 숨김).

## Screens / Views

공통 셸: 상단 헤더 64px, `--bg-surface` 배경 + 하단 1px `--border`. 좌측 로고 "산돌이 태스크" 20px/700. 내비 버튼 4개(오늘, 내 태스크, 팀 현황, 검색) 44px 높이, radius 8, 기본 `--text-secondary`, 선택 시 `--primary-bg` 배경 + `--primary` 글자 + weight 700. 우측 '빠른 추가' 버튼(`--primary-bg`/`--primary`)과 아바타. 좌측 프로젝트 레일 190px(sticky). 본문은 `--bg-page` 위에 24px 여백, 흰 카드(`--bg-surface`, radius 12, 1px `--border`, 그림자 없음, padding 24). 우측에 상세 패널(aside 380px, sticky, padding 20)이 붙고, "크게 보기" 시 본문을 숨기고 패널이 전체 폭(2열 grid `repeat(auto-fit, minmax(380px,1fr))`)을 차지한다. 1150px 이하에서는 상세가 열리면 본문 대신 상세만 표시한다.

### 1. 오늘 (Today)
- **상단**: 날짜 22px/700 ("2026년 9월 9일 (수)") + `todayHint`("오늘 태스크 N건", `--text-secondary`). 아래 지표 3개를 한 줄 텍스트 버튼(값 19px/700 + 라벨 13px `--text-secondary`)으로: 오늘 완료, 지난 7일 완료, 남은 내 태스크. 각각 내 태스크 화면의 해당 목록(상태 필터 `doneToday` / `done7` / 전체 미완료)으로 이동하므로 숫자와 목록 건수가 일치한다.
- **빠른 추가 폼** (토글): 제목(52px input), 프로젝트, 중요도 1~10, 목표 기한, 기한 미정 사유. 제출 → `todo`로 생성 후 오늘 목록에 추가.
- **지금 할 일 카드**: 오늘 목록 중 첫 항목(중요도 최고, 막힘·검토 대기도 마감 기준이면 포함). 헤드라인 28px/700 (`nextAction || title`), 메타, 주 버튼 "진행 중으로 시작"/"완료로 표시", 보조 "진행 메모 열기", "자세히 보기".
- **오늘 태스크**: 제목 17px/700 + 개수. 우측 "중요도순" + **마감 기준 자동 담기** select (끄기/1/3/5/7/14일, 기본 5). 자동 추가 항목이 있으면 "마감 N일 이내 자동 추가 n건." 안내. '오늘 제외'한 항목이 있으면 "오늘 제외 n건" + '제외한 태스크 복원' 버튼. 정렬: 닫힌 것 뒤로 → priority desc → due asc → id. 행에는 ↑↓ 이동 버튼 노출(`show-move`), 담당자 숨김.
- **오늘 완료** (details 접이식), 요약 링크 줄(오늘 마감 n, 기한 초과 n, 검토 대기 n, 막힘 n → 내 태스크 필터로 이동).
- **일정** 카드: 기본 닫힘. 목록 위 우측 '일정 보기' 버튼(`scheduleOpen`)으로 목록 옆에 연다. 시간표/캘린더 토글. 월간 달력은 30일 grid, 오늘은 `--primary` 채움, 선택일은 `--primary-bg` + 테두리, 마감 개수 ●n. 선택일 마감 태스크 목록.

### 2. 내 태스크 (Me)
- 헤더: 제목 `내 태스크` / `{이름}의 태스크` / `팀 전체 태스크` 24px/700. 우측 **팀원 select**(팀 전체/나/이서연/박지호/최수아). 힌트: "미완료 N건 · 결과 M건", 타인·팀 전체는 " · 보기 전용"을 덧붙인다. 완료 필터(오늘 완료/지난 7일 완료)일 때는 "완료 N건 · 결과 M건".
- 필터 줄 (모두 44px, radius 6): 그룹(기한별·프로젝트별·상태별, primary 톤), 기한(모든 기한/기한 초과/오늘 마감/이번 주 남은 마감/이번 주 전체 마감/그 이후/기한 미정), 프로젝트, 상태(시작 전/진행 중/일시정지/막힘/검토 대기/오늘 완료/지난 7일 완료), 중요도(높음 8~10/중간 4~7/낮음 1~3), 필터 지우기. 완료 필터는 단일 평면 목록으로 보여 준다.
- 그룹 섹션: 제목 17px/700 + 개수. 기한별 그룹은 프로젝트별 하위 묶음(프로젝트 이름 버튼, "완료 N/M", 진행률 바 8px, 하위 목록은 좌측 2px 보더 들여쓰기). 빈 그룹은 안내 문구.
- 행: 본인 조회 시 담당자 숨김. 타인·팀 전체 조회 시 담당자 표시, `read-only`, `hide-today`.

### 3. 팀 현황 (Team)
- 지표 6개 버튼 grid: 미완료, 기한 초과, 이번 주 마감, 검토 대기, 막힘, 기한 미정 (값 26px/700, 흰 카드 + 1px `--border`, 700px 이하 2열). 클릭 시 내 태스크 화면을 **팀 전체**(`viewMember` 0)로 열고 같은 필터(기한 초과 / 이번 주 전체 마감 / 검토 대기 / 막힘 / 기한 미정)를 적용하므로 표시된 숫자와 목록 건수가 일치한다.
- **프로젝트 표**: 열 = 이름(+목적 13px), 관리자(쉼표 구분, 미지정은 `--warning`), 상태(배지 + 아래 설명 13px, max-width 220), 미완료, 완료 x/y. 우측 상단 "보관 포함" 체크 + **새 프로젝트** 버튼(primary).
- **담당자별 표**: 이름(버튼 → 해당 팀원의 태스크 화면), 미완료, 기한 초과, 검토 대기, 막힘.

### 4. 프로젝트 (Project)
- 헤더: 뒤로("산돌이 서비스" 13px), 이름 24px/700, 목적, 메타 줄(관리자 · 상태 배지 · 저장소 · 설계 문서), 상태 설명 13px. 우측 버튼: **프로젝트 수정**(outline), **태스크 만들기**(primary, 열리면 "닫기").
- **태스크 만들기 인라인 폼** (`--bg-secondary`, radius 12, border): 제목(52px, autofocus), 담당자 select **기본값 나(김민준), 변경 가능**, 중요도, 목표 기한, 기한 미정 사유. 버튼 "태스크 만들기" / "취소". 안내 "상태는 시작 전으로 저장돼요. 담당자는 한 명만 정할 수 있어요." 생성 후 상세 패널 오픈.
- 지표 5개: 완료 x/y, 미완료, 기한 초과, 검토 대기, 막힘.
- 보기 토글 목록/보드 + "완료·취소 포함" 체크. 보드 컬럼 = 열린 상태 5개(+포함 시 완료·취소).

### 5. 검색 (Search)
- 52px 검색 input (placeholder "예: TASK-121, 메뉴, 챗봇"), 체크 "완료·취소 포함", "보관 포함". 결과 개수 + 행 목록. 빈 결과 문구.

### 6. 프로젝트 생성/수정 다이얼로그 (모달)
- 오버레이 `rgba(15,50,60,.35)`, 카드 max-width 520, radius 12, padding 24, shadow `0 8px 32px rgba(15,50,60,.2)`. 바깥 클릭·취소로 닫힘.
- 필드: 이름(필수), 목적(textarea 2줄), **관리자 체크 칩**(pill 44px, 선택 시 `--primary` 테두리 + `--primary-bg`), **상태 라디오 8개**(각 카드형 라벨: 레이블 15px/600 + 설명 13px, 선택 시 primary 테두리/배경).
- 제출 라벨: "프로젝트 만들기" / "변경 내용 저장". 생성 후 해당 프로젝트 화면으로 이동.

### 7. 태스크 상세 패널 (Aside)
- 상단 바: 자동 저장 상태 텍스트("저장 중…" → 400ms 후 "자동 저장됨" → 2.5s 후 사라짐), 🔗 링크 복사(`#task-{id}` URL, 클립보드), 크게 보기/옆으로 보기 토글, 닫기.
- 번호 `TASK-121` 13px, 제목 input 20px/600 (blur 시 저장).
- 메타 줄: 프로젝트(링크), 담당자, **상태 select**(24px, 배지 스타일), 기한 배지, 중요도 select 1~10 "/10".
- 상태 설명 13px `--text-secondary`.
- blocked/paused 사유 박스: 사유 초안 입력과 확정 버튼. 막힘 사유는 필수, 일시정지 사유는 선택. 실패 시 기존 저장값을 유지하고 입력 영역에 오류를 표시한다.
- 설명 textarea, 목표일 블록(값 17px/600, 초과 시 `--danger`) + "목표일 연장하기" 토글 폼(새 목표일, 연장 사유 필수).
- 완료 조건 textarea, 체크리스트(토글·↑↓·삭제·추가 input, 진행률), 진행 메모(태스크별 단일 메모장, 줄바꿈·수정·비우기 자동 저장, 등록 버튼 및 댓글 목록 없음), 링크 목록(종류 배지), 변경 이력 details, 더보기 details(담당자 변경 안내 문구).

### TaskRow2 (태스크 행)
- `<li>` 카드: min-height 56, padding 10 14, radius 8, border `--border`, 그림자 없음, hover 배경 `--bg-secondary`, 전체 클릭 → 선택. 선택 시 `inset 3px 0 0 var(--primary)` 좌측 강조선.
- 좌측: (옵션) nextAction 16px/600, 프로젝트명 12px, 제목 16px/600(닫힘 시 취소선), 메타 13px(담당자[옵션], "중요도 n/10" 배지 — 8 이상 굵게, blocked/paused 사유 텍스트 — blocked는 `--danger`, 체크리스트 x/y[체크리스트가 있을 때만]). 진행률 바 없음.
- 우측(클릭 전파 차단, max-width 100%): 기한 라벨, **상태 select pill**(36px, radius 999, 색은 상태표 참고, read-only 시 disabled), **오늘 버튼** 36px(라벨: "오늘 추가" / 담긴 항목은 "오늘 제외" / 자동 추가 항목은 "자동 추가 · 오늘 제외" primary 톤, hide-today면 숨김), 🔗 36×36, (옵션) ↑↓ 36×36. 700px 이하에서는 40px.
- props: `task, showNext, showMove, hideAssignee, hideToday, readOnly, onSelect, onStatus, onToday, onCopyLink, onMove`.

## Interactions & Behavior
- 내비/지표 버튼은 화면 이동 + 필요한 필터 프리셋(`meFilter.status = 'review' | 'blocked'`, `viewMember = ME`).
- URL 해시 `#task-{id}` 진입/변경 시 해당 태스크 선택·패널 오픈.
- 상태 select 변경 → 규칙 1~5 적용. 행 오류는 해당 행 아래 `--danger` 15px로 표시.
- 편집 필드는 `onChange`(프로토타입에서는 blur/Enter 커밋 의미) 시 저장 → 자동 저장 상태 표시.
- 오늘 목록 ↑↓는 직접 고른 항목 순서만 바꿈(자동 추가는 정렬 규칙을 따름). '오늘 제외' 클릭 → `todayIds`에서 빼고 `excludedToday`에 추가해 자동 담기에서도 빠진다. '오늘 추가' 클릭 → `todayIds`에 추가하고 `excludedToday`에서 뺀다. '제외한 태스크 복원' → `excludedToday`를 비운다.
- 트랜지션: 행 배경 150ms `cubic-bezier(0.3,0,0.2,1)`. `prefers-reduced-motion`이면 모두 제거.
- 접근성: 모든 컨트롤 최소 44px(행 내부 소형 컨트롤 30~36px), `aria-current`, `aria-pressed`, `aria-live`(저장 상태), 카드 `role=button` + Enter/Space.

## State Management
```
screen: 'today'|'me'|'team'|'project'|'search'
projectId, selectedId, panelOpen (기본 false), wide, focusNotes
view: 'list'|'board', includeClosed
viewMember (기본 ME), autoPullDays (기본 5)
meFilter: { project, status, priority, due }, groupBy: 'due'|'project'|'status'
calMode: 'time'|'month', calDay
q, searchClosed
todayIds: number[]   // 직접 고른 오늘 목록 (순서 유지)
excludedToday: number[]  // '오늘 제외'한 자동 추가 항목. 오늘 날짜에만 유효
scheduleOpen: boolean    // 일정 카드 열림
quick / taskForm / projForm / extend: 폼 상태 + error
projects: Project[], tasks: Task[], errors: {taskId: msg}, saveStatus
```
파생값(오늘 목록, 자동 담김, 그룹, 지표, 보드 컬럼, 프로젝트 통계)은 모두 `renderVals()`에서 계산한다. 서버 연동 시 tasks/projects는 fetch, 나머지는 클라이언트 상태. 오늘 목록(`todayIds`), `excludedToday`(사용자+날짜별), `autoPullDays`는 사용자별로 저장.

## Design Tokens
폰트: **Pretendard** (fallback -apple-system, 'Apple SD Gothic Neo', 'Noto Sans KR', sans-serif). `word-break: keep-all`.

Light
```
--bg-page #EEF3F5   --bg-surface #FFFFFF   --bg-secondary #F5F8F9   --bg-fill #F0F4F6
--text-primary #191F28   --text-secondary #636D7A   --text-disabled #B0B8C1   --border #E5E8EB
--primary #1F6F82   --primary-pressed #155463   --primary-bg #E3F1F4   --on-primary #FFFFFF
--danger #C92A37   --danger-bg #FEF0F1   --success #12793F   --success-bg #EDF9F2
--warning #A85B00   --warning-bg #FEF6EA
```
Dark (`[data-theme=dark]`)
```
--bg-page #17171C   --bg-surface #202027   --bg-secondary #26262E   --bg-fill #2E2E38
--text-primary #E7E9EE   --text-secondary #9FA4AF   --text-disabled #5B5F6B   --border #33333E
--primary #5CC1D2   --primary-pressed #8AD5E1   --primary-bg #1B3A42   --on-primary #17171C
--danger #FF6B6B   --danger-bg #3A2226   --success #34C77B   --success-bg #1E3328
--warning #F5A93F   --warning-bg #3A2F1E
```
타이포 스케일 (size/line-height): 12/16, 13/19, 14/20, 15/22, 16/24, 17/26, 20/28, 22/30, 24/33, 26/32, 28/38. 제목류 letter-spacing -0.02em, weight 700; 라벨 600.

간격: 4, 8, 12, 16, 20, 24, 32. Radius: 4(배지), 6(input/select), 8(카드·버튼), 12(패널·카드), 999(pill).
그림자: 카드·행은 그림자 없이 1px `--border`. 모달만 `0 8px 32px rgba(15,50,60,.2)`.

## Assets
- 폰트: Pretendard (jsDelivr CDN, `pretendard.min.css`). 코드베이스에 폰트 파이프라인이 있으면 자체 호스팅.
- 아이콘: 링크 복사 아이콘만 인라인 SVG(16 viewBox, stroke 1.6). 그 외 아이콘 없음. 프로젝트 상태 이모지는 텍스트로 포함.

## Files
- `산돌이 업무 목업 v2.dc.html` — 전체 앱 프로토타입 (템플릿 + `class Component` 로직 + 예시 데이터)
- `TaskRow2.dc.html` — 태스크 행 컴포넌트
- `support.js` — 프로토타입 런타임 (참고용, 구현 대상 아님)

## 2026-09-10 수정 사항

- 마감 기준 자동 담기와 추천 카드의 대상 선정은 유지한다. 막힘은 기한을 자동 연장하거나 추천에서 제외하는 조건이 아니다.
- 진행 메모는 `notes` 문자열 하나를 편집한다. 포커스 이동 시 내용을 지우거나 별도 항목으로 등록하지 않는다. 기존 예시 메모 본문은 메모장 초기 내용으로 보존한다.
- 목표일 연장 사유는 변경 이력에만 기록하여 사용자가 작성 중인 메모를 덮어쓰지 않는다.
