# 유달리 개선 사항 목록 (2026-10-04, 기준 커밋 8d0be51)

범위 밖: 개인 계정·단일 저장소 조직·한 저장소 다중 프로젝트 검증, 비개발 팀·저장소 미연결 프로젝트 설계.
측정: N+1은 SQLite 테스트 DB에서 데이터 규모를 2→10으로 늘려 쿼리 수를 셈. 커버리지는 core 708 / discord 164 / mcp 46 테스트 통과 상태에서 측정
(스크립트·결과: scratchpad `qtest\test_nplus1.py`, `core_report.txt`, `core.json`, `discord_service.json`, `mcp_server.json`).
P0 = 즉시, P1 = 다음 라운드, P2 = 그 이후.

## 상위 10개 요약

| # | 우선 | 분류 | 항목 | 규모 |
|---|---|---|---|---|
| 1 | P0 | 보안 | GitHub 앱 설치 콜백이 설치 소유자를 확인하지 않음 → 남의 설치(비공개 저장소 목록)를 가로챌 수 있음 | S |
| 2 | P0 | 운영 | 운영에서 발송 서비스 `discord`가 실행되지 않음 → 마감 DM·주간 보고·에스컬레이션·채널 게시가 전혀 나가지 않음 | S |
| 3 | P0 | 운영 | 자동 백업 없음. SPEC은 v1 범위로 "매일·30일 보존·복구 시험"을 요구함 | M |
| 4 | P1 | 기능/버그 | 알림 설정 6개가 화면에서 저장은 되지만 효과가 없음. 초과 유예일도 DM에는 적용되지 않음 | M |
| 5 | P1 | 보안 | Discord 설치 콜백이 `code`를 교환하지 않고 `guild_id`를 그대로 믿음 → 남의 서버를 선점할 수 있음 | S |
| 6 | P1 | 보안 | 로그인·가입에 시도 횟수 제한이 없음 | S |
| 7 | P1 | 성능/가용성 | SSE 연결 하나가 스레드 하나를 50초 붙잡는데 슬롯이 32개뿐 → 한 사용자가 탭을 여럿 열면 사이트가 멈춤 | M |
| 8 | P1 | 성능 | N+1: `/me` 26→98, `/today` 23→47, `/api/orgs/{o}` 17→49, `/api/projects` 11→35, 팀 목록 13→29 | M |
| 9 | P1 | 테스트 | 결정 기록(16%)·포트폴리오(15~38%)·PR 컨텍스트(21%) 커버리지가 낮고, 웹의 상태 변경·권한 경로가 테스트되지 않음 | M |
| 10 | P1 | 운영 | 운영 서버 Git HEAD가 배포본과 다름(파일 단위 수동 반영) → 배포 버전을 추적할 수 없음 | M |

---

## 1. 보안

### S1. GitHub 앱 설치 가로채기 — P0, S
- 문제: 설치 콜백이 쿼리의 `installation_id`를 받고, 앱 JWT로 그 설치가 존재하는지만 확인한다. 조직 관리자가 URL의 id를 남의 설치 id로 바꾸면 자기 조직에 등록된다. 그러면 피해자 저장소 목록(비공개 포함)이 보이고, 진짜 주인은 "이미 다른 조직이 사용" 오류로 막힌다.
- 근거: core/web/views/github.py:103-108 (state만 확인하고 id는 GET 값을 그대로 씀) · core/github/services.py:77-98 `save_installation` (선점 검사만 하고 소유 확인은 없음) · 노출 경로 core/api/routers/orgs.py:213 (보안 감사 에이전트 보고, 앞의 두 곳은 직접 확인)
- 제안: 연결된 사용자 토큰으로 `GET /user/installations`를 불러 그 id가 목록에 있을 때만 저장한다.

### S2. Discord 길드 선점 — P1, S
- 문제: 콜백이 `guild_id` 쿼리를 그대로 저장한다. 함께 오는 `code`를 토큰으로 교환해 확인하지 않는다.
- 근거: core/web/views/discord.py:118-131 · core/orgs/discord.py:48 (형식과 중복만 검사)
- 영향: 봇이 이미 들어가 있는 남의 서버를 자기 조직에 묶어, 진짜 주인의 연결을 막을 수 있다.
- 제안: `code`를 교환하고 응답의 `guild.id`로 확정한다. state 비교는 None이면 거부하고 `secrets.compare_digest`를 쓴다(:121).

### S3. 로그인·가입 무차별 대입 — P1, S
- 근거: core/web/urls.py:40-48 (LoginView와 signup에 제한이 없음). API의 60/m 제한(core/api/api.py:56)은 이 경로에 걸리지 않는다.
- 제안: 코드를 늘리지 않으려면 NPM에서 `/login`·`/signup`에 속도 제한을 건다. 확인 불가: 현재 NPM에 이미 걸려 있는지.

### S4. 낮은 위험 묶음 — P2, S
- 업로드를 통째로 읽은 뒤에 256KB를 검사한다(core/web/views/docs.py:74, notes.py:115) → `f.size`를 먼저 본다.
- `set_api_spec`이 `project.settings_by` 등급을 검사하지 않는다(core/projects/services.py:591). 다른 프로젝트 설정은 모두 `require_level`을 거친다.
- `repo_event_link`에 등급 검사가 없다(core/web/views/github.py:528).
- OAuth 발급 토큰에 만료가 없다(core/web/views/oauth.py:180).
- 이미 알려진 ponytail 한계: DNS 리바인딩(core/projects/services.py:573), `/oauth/register` 무인증(oauth.py:95). 현행 유지.

## 2. 운영

### O1. 발송 서비스 미기동 — P0, S
- 근거: docs/ui-audit/task41/DEPLOYMENT-INTEGRATIONS-2026-10-04.md:10 ("발송 `discord` 서비스는 원래 실행 중이지 않아 이번에도 시작하지 않았다") · compose.yml의 `discord` 서비스(60초 틱: 마감 DM·주간 보고)
- 영향: 마감 DM·주간 보고·에스컬레이션(escalate.py)·프로젝트 채널 게시(channels_post.py)가 운영에서 하나도 동작하지 않는다. 운영 조직의 Discord 서버 연결도 0이다(같은 문서 :27).
- 제안: 의도한 중단인지 사용자가 결정한다. 켤 거라면 `docker compose up -d discord`를 하고 `/ops` 하트비트를 확인한다. 길드 연결이 0이면 켜도 보낼 대상이 없다.

### O2. 자동 백업 없음 — P0, M
- 근거: docs/SPEC.md:33 (백업은 v1 포함 범위) · SPEC.md:463-471 (매일, 30일 보존, 분리 보관, 복구 시험) · PLAN.md:32,487 · GUIDE-04-deploy.md:333 (후속으로 미루고, 그때까지 Proxmox vzdump 예약)
- 현재 백업은 배포 때 수동으로 만든 `.deploy-backups/.../database-before.dump`뿐이다(DEPLOYMENT-INTEGRATIONS:39-44).
- 제안: LXC 호스트 cron에서 `docker compose exec -T db pg_dump -Fc`를 실행해 다른 스토리지에 저장하고 30일이 지나면 지운다. 복구 시험을 한 번 한다. 확인 불가: Proxmox vzdump 예약이 실제로 잡혀 있는지(SSH·VPN 필요).

### O3. 서버 Git HEAD와 배포본 불일치 — P1, M
- 근거: DEPLOYMENT-INTEGRATIONS-2026-10-04.md:9 ("오래된 Git HEAD에 … 기존 파일 117개·새 파일 30개를 반영", "Git HEAD 자체는 배포 버전 표식이 아니다") · DEPLOYMENT-2026-10-04.md:9
- 영향: 매 배포가 수동 diff 작업이 되고, 롤백 기준도 불분명하다.
- 제안: 서버 변경분을 한 번 정리해 커밋하고, 이후에는 `git fetch && git checkout <sha>`로 배포한다. `/healthz`나 `/ops`에 커밋 SHA를 보여 준다.

### O4. compose 수동 편집 전제 — P2, S
- compose.yml:16-17 ("서버에서는 이 두 줄을 지운다", DB 5432 포트)는 서버에서 매번 손으로 지워야 해 O3의 불일치를 만든다 → `compose.override.yml`(로컬 전용)로 옮긴다. `cloudflare/cloudflared:latest`(:96)는 버전을 고정한다.

### O5. SSE 스레드 고갈 — P1, M
- 근거: core/web/views/events.py:63-71 (연결당 최대 50초 점유) · core/entrypoint.sh:9 (2 워커 × 16 스레드 = 32)
- 제안: 가장 작은 수정은 사용자당 동시 연결 수 제한 또는 점유 시간 단축이다. 근본 해결은 이벤트 스트림을 비동기 워커로 분리하는 것이다.

## 3. 기능 공백

### F1. 알림 설정 6개가 효과 없음 + 유예일 불일치 — P1, M
- 문제: 조직 설정 `notify.deadline_kinds`·`notify.overdue_repeat`·`notify.quiet_weekend`·`notify.team_channel_weekly`, `notify.project_channel_events`의 `milestone_due` 값, 개인 설정 `user.notify_kinds`는 저장되고 core가 봇에 전달까지 하지만, discord_service가 이 값을 쓰지 않는다.
- 근거:
  - 정의: core/orgs/settings.py:518, 541, 557, 629, 633, 654
  - 계획: docs/IMPL-PLAN-4.md:281-292 (읽는 곳 = `notify.run_deadlines`·`scheduler`·`weekly`) · §8.3 (`notify.py`에서 deadline_kinds ∩ user.notify_kinds로 거름)
  - 구현: discord_service/discord_service/notify.py:60 (ponytail 주석이 "core가 이미 걸렀다고 믿는다"고 하지만 core에서 이 키를 읽는 곳은 settings.py 밖에 0건) · notify.py:80 (`open_tasks`는 거르지 않음) · core/api/routers/tasks.py:56-82 (due_to 필터만 있음) · weekly.py:32, channels_post.py:15 (ponytail로 미룸) · scheduler.py에 주말 검사 없음(:135는 주간 보고 요일만 봄)
  - 유예일: notify.py:15 `classify`는 `delta<0`이면 바로 초과로 본다. core/common/dates.py:50-56은 "화면·집계·알림이 전부 이 함수로 판정한다"며 `task.overdue_grace_days`를 더한다 → 웹에서는 초과가 아닌데 DM은 "기한 초과"로 나간다.
  - 테스트: discord_service/tests/conftest.py:32에 `notify_kinds` 픽스처는 있지만 거르는 동작을 검증하는 테스트는 없다.
- 영향: 관리자가 설정을 꺼도 DM이 그대로 나간다. 설정 화면을 믿을 수 없게 된다. O1 때문에 운영에서는 아직 드러나지 않았다.
- 제안: `run_deadlines`에 `kinds`(조직 ∩ 개인)·`overdue_repeat`·`quiet_weekend`·`grace_days` 인자를 받아 `classify` 앞에서 거른다. 주석이 말한 "파라미터 하나 더" 수준이다. `team_channel_weekly`·`milestone_due`는 구현하거나, 구현 전까지 설정 화면에서 숨긴다(숨기는 쪽이 S).

### F2. 주간 요약 LLM 분기가 비어 있음 — P2, S
- 근거: discord_service/discord_service/summarize.py:71-73 (`_llm`이 항상 NotImplementedError) · config.py:40 `LLM_PROVIDER` · README.md:184
- 영향: 값을 넣어도 조용히 고정 형식으로 돌아간다. 해는 없지만 문서가 기능이 있는 것처럼 보이게 한다.
- 제안: 제공업체를 정하기 전까지 README에 "미구현"이라고 적거나 env를 지운다.

### F3. 기타 계획상 후속 (참고, 근거만)
- 공개 포트폴리오·블로그 발행: DESIGN-AI-DECISIONS-PORTFOLIO.md:24,220
- 조직 알림 채널 웹 선택, 팀 채널 웹 연결: ui-audit/task41/INTEGRATION-EXPANSION-2026-10-04.md:16-17
- 시간 블록·타이머·AI 다음 업무 추천·Discord OAuth: PLAN.md:67 (코드에 흔적 없음)
→ 사용 요구가 확인되기 전에는 넣지 않는다(P2).

## 4. 코드 품질

### Q1. `auto_import` "죽은 열" 주석이 사실과 반대 — P1, S
- 근거: core/github/models.py:56-58의 주석은 "더 이상 읽지 않는 열… 마이그레이션과 함께 지운다"라고 하지만, 실제로는 core/github/services.py:820이 웹훅 이슈 자동 가져오기 조건으로 읽고, 화면 체크박스도 있다(core/web/templates/projects/repo.html:73, settings.html:40,52). 저장 경로는 services.py:355와 web/views/github.py:394다.
- 영향: 주석대로 열을 지우면 이슈 자동 가져오기가 깨진다.
- 제안: 주석만 고친다. 열은 유지한다.

### Q2. 1000줄 넘는 파일 — P2, L
- core/github/services.py (1055줄, 함수 49개), core/tasks/services.py (1016줄), mcp_server/mcp_server/server.py (1033줄, 함수 76개). 모두 `# ---------- 구획 ----------` 주석으로 나뉘어 있어 지금 읽기에 큰 문제는 없다.
- 제안: 병합 충돌이 실제로 생길 때 구획 단위로 떼어 낸다(github: webhook 규칙 :455-끝 → `webhooks.py`). 미리 쪼개지 않는다.

## 5. 성능 (N+1)

### P1-a. 체크리스트를 행마다 조회 — P1, S
- 근거: core/web/views/common.py:246. `/me`는 태스크마다 행을 두 번 그린다(me.py:61,63).
- 측정: `/me` 26→98(체크리스트 조회 60회), `/today` 23→47. 프로젝트 보드는 23이지만 태스크 수에 비례해 늘어난다.
- 제안: 목록 쿼리에 `prefetch_related("checklist")`를 붙이고 행 정보는 한 번만 만든다.

### P1-b. 통계·카운트를 루프 안에서 조회 — P1, M
- `project_stats()`를 묶음마다 다시 부른다: core/tasks/services.py:932 (`/me`에서 30회), core/web/views/orgs.py:91 (`/orgs/{o}` 31→39), core/projects/services.py:502 (로드맵, 측정은 안 함).
- 팀 목록: orgs.py:108-109, 140-141 (`/orgs/{o}/teams` 13→29).
- API `project_out`: core/api/serialize.py:65,72,74 (`/api/projects` 11→35, `/api/orgs/{o}` 17→49).
- 제안: `values("project").annotate(Count…)` 한 번으로 바꾸고, 링크는 Prefetch로 가져온다.
- 문제가 아니었던 곳: discord.py:159-196의 `effective()`는 메모리 dict만 읽는다. `/requests`·`/tasks/{id}`·`/teams/{t}`·`/api/today`는 규모가 커져도 쿼리 수가 그대로다.

## 6. 테스트 공백

### T1. 결정 기록·포트폴리오 — P1, M
- core/tasks/decision_services.py 16% (`create_record`·`confirm_record`·`reject_record`·`list_records`가 실행되지 않음), api/routers/decisions.py 29%, portfolio/drafts.py 15%, sources.py 20%, mcp portfolio_tools.py 15%, github/pr_context.py 21%.

### T2. 웹의 상태 변경·권한 경로 — P1, M
- 프로젝트 보관·복원·삭제 (web/views/projects.py:255-292), 멤버 역할 변경·제거 (orgs.py:237,249), 체크리스트·링크 (tasks.py:352-413), 마일스톤·의존성 (roadmap.py:136-209).
- mcp server.py 71%: `plan_project_channel_assignments` (:121), `_discord_control` (:87), `update_project` (:287)가 실행되지 않음. discord control.py 64%.
- F1을 고칠 때 거르는 동작의 테스트도 함께 넣는다.

## 7. UX (docs/ui-audit)
- ui-audit/task41의 Astra 문구 검토와 버튼 목적 검토(UX_BUTTON_PURPOSE_REVIEW.md:66-85, 169-180)에서 지적한 항목을 표본으로 확인했다. 대부분 이미 반영돼 있다: 검색 빈 상태(search.html:16), 보관 버튼 문구와 개수 확인(projects/settings.html:85-87), 선행 프로젝트(roadmap.html:59), GitHub 팀 폼 CSRF(team_detail.html:37), 클립보드 수동 복사 시 성공 표시 안 함(app.js:16-28), HTMX 오류 분기(app.js:163-167), 문서 생성 오류(docs.py:59-61).
- 남은 것: 알림 시각의 `-1` 노출(core/orgs/settings.py:536 도움말 "-1이면 서버 기본 시각")과 포트폴리오의 "의사 요지" 용어(templates/portfolio/index.html:105). P2, S.
- 전체 F01~F15를 다시 대조하지는 않았다(확인 불가).
