# D — 승인 검토 (Fable, 2026-10-04, 기준 커밋 8d0be51)

검토 방식: 세 보고서의 핵심 주장을 코드에서 직접 확인. 코드·git 수정 없음. `uv run pytest github/tests.py` 실행 → 32 passed, 5 xfailed(A의 주장과 일치).

## 판정: 라운드 **조건부 승인**

| 보고서 | 판정 | 조건 |
|---|---|---|
| A 검증(개인 계정·다중 프로젝트) | 승인 | 작업트리의 `core/github/tests.py`(+273줄, 미커밋)를 1단계 첫 작업으로 커밋. 결함 수정은 C의 P0 S1과 같은 파일이라 한 단계로 묶음 |
| B 비개발 설계 | 조건부 승인 | 설정 키 방식 채택. v1 필수 6건 중 F7 달력(M)은 수요 근거 없음 → 사용자 결정. 결정 질문 10개 → 2개로 축소(나머지는 추천대로 진행) |
| C 개선 목록 | 조건부 승인 | P0 S1·O1·O5·Q1·S2 맞음. S2 수정은 `DISCORD_CLIENT_SECRET` env 신설·운영 `.env` 변경을 수반함(보고서 누락). N+1·커버리지 수치는 재측정 안 함 |

## 보고서별 확인 결과

### A — 맞음(전부 확인)
- `account_type`을 저장만 하고 읽지 않음: core/github/models.py:11, services.py:94 외 참조 없음. 맞음.
- S1-1 고정 URL: web/templates/orgs/github.html:11-12 `github.com/organizations/{login}/settings/...`. 맞음.
- S1-3/4 `/orgs/*` 호출: github/writes.py:65-75, orgs.py:198-217(`GITHUB_ENABLED`만 검사). 재시도 경로 github_retries.py:103-112도 `/orgs/` 고정. 맞음.
- M-1: services.py:490-491 루프에 예외 격리 없음. `create_task`는 보관 프로젝트에 ServiceError(tasks/services.py:131-132). `ATOMIC_REQUESTS` 설정 없음(grep 0건). 웹훅 라우터는 NinjaAPI 안(api/routers/github.py:37-43)이라 ServiceError→400(api/api.py:66-68). 재전송은 475의 접두어 검사로 duplicate. 맞음 — B 프로젝트 영구 누락 재현 경로 성립.
- 보완: M-1 수정은 "보관 프로젝트면 건너뛰기"(증상)가 아니라 연결별 `transaction.atomic()`+`except (ServiceError, ConflictError)`→`record_event(result=사유)`(원인)로 간다. 담당자 비활성 등 다른 ServiceError도 같은 경로로 터지기 때문.
- P-1(이슈 하나→프로젝트마다 태스크)은 설계상 연결별 격리(RepoIssue·TaskGitLink가 connection FK)와 일관. 정책 질문으로 올림.

### B — 맞음, 범위 조정
- 설정 체계 호환: `Spec(key, kind, default, scope, overridable, group, label, help)` 시그니처(core/orgs/settings.py:19-31)와 B의 제안 일치. `specs_for("project")`가 `scope=="org" and overridable` 항목을 자동 포함(settings.py:737-741) → 프로젝트 설정 화면(web/views/projects.py:372-393), API(api/routers/settings.py:105-115), MCP `get/update_project_settings`(mcp_server/server.py:673-680)에 **코드 추가 없이** 노출. `project.default_view`(settings.py:275-285)가 같은 패턴의 선례. **설정 키 방식이 맞다.**
- 모델 필드가 나은 경우는 "목록 필터·집계"인데 지금 요구 없음. 필요해지면 `Project.objects.filter(settings__contains={"project.dev_tools": False})`로 JSONField 조회 가능 → 필드 없이도 됨. Discord 봇은 프로젝트 유형을 알 필요 없음(명령은 태스크·프로젝트 단위). 모델 필드 반대.
- 주의: `effective()`(settings.py:822-842)는 조직이 `locked_keys`로 잠그면 프로젝트 재정의를 무시한다 — 의도된 동작이므로 그대로 둔다. 생성 대화상자 체크박스는 조직 기본과 다를 때만 `project.settings`에 저장.
- 1.1 표의 근거 확인: `_tabs.html:8`(API 문서 탭 무조건), `:10`(GitHub 탭 `github_enabled`만), `_panel.html:98`(GitHub 접이 블록 `github_enabled`만). 맞음.
- F6 반려 사유: `transition(reason=)`과 `task.reopen_reason_required` 패턴이 이미 있음(tasks/services.py:441-443) → `task.reject_reason_required` 추가는 같은 꼴. S 맞음.
- F2 `Link.KINDS` 추가(tasks/models.py:323-331): choices 변경은 DB 변경 없는 마이그레이션 1개. 맞음.
- 과함: F7 프로젝트 달력(M)을 "필수 v1"로 둔 근거가 없음(B 6절 스스로 "운영·마케팅 업무 사례 자료 없음"). F8 반복·F10 지정 검토자를 미룬 판단은 맞음.
- 부족한 것 없음. 기존 규칙(기한 필수·완료 조건·검토)은 저장소와 무관하게 그대로 쓰인다.

### C — 대부분 맞음, 보완 2건
- **P0 S1 맞음**: `github_installed`(web/views/github.py:93-113)는 `state`만 검사하고 `installation_id`는 GET 값 그대로. `save_installation`(github/services.py:77-99)은 "다른 조직 선점" 검사뿐, 설치 계정과 요청자의 관계를 확인하지 않음. 설치 id는 순차 정수라 추측 가능. 가로채면 `installation_repos`(api/routers/orgs.py:205-213)로 앱 권한만큼 비공개 저장소 목록·이슈 쓰기·브랜치 생성이 가능 → P0 맞음.
  - 보완: 제안대로 `GET /user/installations`로 확인하면 **설치자가 GitHub 계정을 먼저 연결해야** 한다. 현재 github.html:15의 설치 버튼은 연결 없이 눌린다 → 버튼에 "먼저 GitHub 계정 연결" 가드 추가. 대안(설치 웹훅 `sender` 대조)은 비동기라 더 복잡. 제안 채택.
- S2 Discord 맞음: web/views/discord.py:122-129가 `guild_id`를 그대로 `link_guild`(orgs/discord.py:48-56)에 넘기고 형식·중복만 검사. 보완: `code` 교환에는 client_secret이 필요한데 core/config/settings.py:155에 `DISCORD_CLIENT_ID`만 있음 → env 신설 + 운영 `.env` 반영이 배포 조건.
- S3 맞음(코드 없이 NPM 속도 제한이 가장 작음; 현재 NPM 상태 확인 불가).
- O1 맞음: docs/ui-audit/task41/DEPLOYMENT-INTEGRATIONS-2026-10-04.md:10 확인. 단 **F1(알림 설정 무효)을 고치기 전에 켜면 관리자가 끈 설정을 무시한 DM이 나간다** → 순서는 F1 수정·배포 → O1 기동.
- O5 맞음: entrypoint.sh 2워커×16스레드=32, STREAM 50초.
- Q1 맞음: models.py:56-58 주석과 달리 services.py:820이 `conn.auto_import`를 읽음. 주석만 고침.
- 확인 불가: N+1 쿼리 수, 커버리지 %(재측정 안 함), O2 vzdump 예약 여부(SSH 필요).

## 우선순위 검토
제안 순서(P0 보안·운영 → 결함 → 비개발 v1 → P1)는 맞다. 조정 2건:
1. O1(발송 서비스 기동)은 P1 F1 뒤로. 이유 위.
2. GitHub 쪽 작업은 전부 한 묶음: C-S1(github.py:93-113, services.py:77), A-S1-1~4(github.html, team_detail.html, teams.py, orgs.py, writes.py, github_retries.py), A-M-1(services.py:490), C-Q1(models.py:56), C-S4 `repo_event_link` 등급(github.py:528), B-Q10 조직 이슈 탭(orgs/_tabs.html:10). 파일이 겹치므로 담당 하나.

같은 파일 충돌:
- B 3a(F1+F2+F3)와 3b(F4+F6)가 모두 web/views/tasks.py·tasks/_panel.html을 건드림 → 순차(3a→3b) 또는 같은 담당. 3c(F5, work_requests)는 독립.
- 2단계(discord_service, web/views/discord.py)는 1·3단계와 파일이 겹치지 않음 → 병렬.
- 4단계 N+1은 tasks/services.py:932·orgs.py:91·serialize.py → 3b(tasks/services.py)와 겹침 → 3 뒤에.

## 확정 라운드 구성

| 단계 | 내용 | 근거 | 규모 | 담당 | 검토 | 선후 |
|---|---|---|---|---|---|---|
| 0 | 사용자 결정 5건(아래) | - | - | 사용자 | - | 시작 |
| 1 | **GitHub 묶음**: tests.py 커밋 → P0 설치 소유 검증(`/user/installations`, 설치 버튼 가드) → S1-1~4 `account_type=="User"` 분기(UI 숨김·`/orgs/*` 호출·재시도 생략) → M-1 연결별 atomic+예외 격리·사유 기록 → Q1 주석 → `repo_event_link` 등급 → 조직 이슈 탭 조건. xfail 5개가 XPASS로 바뀌면 표시 제거 | C §1 S1, A S1-1~4·M-1, C Q1·S4 | M | Opus | Sol(보안·교차 제조사) | 0 뒤. 2·3a와 병렬 |
| 2 | **Discord·알림 묶음**: S2 `code` 교환(`DISCORD_CLIENT_SECRET` 신설, `compare_digest`) → F1 `run_deadlines`에 kinds∩user·overdue_repeat·quiet_weekend·grace_days 적용 + 거름 테스트, 미구현 설정 2개(`team_channel_weekly`·`milestone_due`)는 화면에서 숨김 → F2 README "미구현" 표기 | C S2, F1, F2 | M | Opus | Sol(1과 묶어 1회) | 1과 병렬 |
| 3a | **비개발 v1-A**: `project.dev_tools` Spec, `dev_tools or project.repo` 표시 규칙(탭·패널·`_git_ctx` 생략), 생성 대화상자 체크박스, 문구 일반화(상태 설명·"업무 거버넌스"·_refs 문구), `Link.KINDS` "산출물", 스킬 3곳 조건화 | B F1·F2·F3 | S~M | Opus | Sol(3 전체 1회) | 0 뒤 |
| 3b | **비개발 v1-B**: 태스크 복제(services→API→웹 버튼→MCP), 반려 사유(`task.reject_reason_required`) | B F4·F6 | S | Opus(3a와 같은 담당) | 〃 | 3a 뒤(tasks.py·_panel 충돌) |
| 3c | **비개발 v1-C**: `WorkRequest.due_date` 마이그레이션, 요청 폼·수락 기본값, Discord `/요청` 기한 인자, MCP `create_request.due_date` | B F5 | S | Sonnet | 〃 | 3a와 병렬 |
| 3d | (사용자 결정) 프로젝트 달력(today.py `_schedule()` 재사용, `default_view` choice 추가) | B F7 | M | Sonnet | 〃 | 3a 뒤 |
| 4 | **P1 개선**: N+1(common.py:246 prefetch, project_stats 집계 1회, serialize.py) · 테스트 공백(T1 결정 기록·포트폴리오, T2 웹 상태 변경·권한) · SSE 사용자당 연결 상한 · 비개발 권장 설정 묶음을 거버넌스 기본안에 추가 | C §5·§6·O5, B 4단계 6 | M | N+1·SSE Opus, 테스트 Sonnet 2갈래 병렬 | Sol 1회 | 3 뒤(tasks/services.py 충돌) |
| 5 | **배포**: main 병합 → 서버 `.env`에 `DISCORD_CLIENT_SECRET`(COMPOSE_PROFILES=mcp 유지) → 배포 → O1 `docker compose up -d discord`·`/ops` 하트비트 → O2 백업 cron+복구 시험 1회 → O3 서버 git 정리·SHA 노출 → S3 NPM 속도 제한 | C O1·O2·O3·S3 | M | Opus(SSH·VPN) | Fable 승인 | 1~4 통합 후 |

병렬 묶음: {1, 2, 3a→3b, 3c} 동시 → 4 → 5. GPT(Sol) 투입은 검토 3회(1+2, 3, 4)로 제한하고 투입 전 사용량 확인.

## 사용자 결정 질문(5개)

| # | 질문 | 선택지 | 추천 |
|---|---|---|---|
| 1 | 운영 발송 서비스 `discord` | (a) 2단계 F1 수정 배포 후 켬 (b) 지금 켬 (c) 계속 끔 | **(a)** — 지금 켜면 꺼 둔 알림 설정을 무시하고 DM이 나감. 길드 연결 0이라 (b)도 당장 피해는 없음 |
| 2 | 자동 백업 방식 | (a) LXC cron `pg_dump -Fc` + 별도 스토리지 30일 보존 (b) Proxmox vzdump 예약만 (c) 둘 다 | **(a)**(vzdump가 이미 있으면 c). SPEC 요구(매일·30일·분리 보관·복구 시험)를 채우는 건 (a) |
| 3 | 비개발 프로젝트 구분 | (a) 설정 키 `project.dev_tools`(조직 기본·프로젝트 재정의, 마이그레이션 없음) (b) `Project.kind` 모델 필드 | **(a)** — 설정 화면·API·MCP에 자동 노출, 선례 `project.default_view`. 필터가 필요해지면 JSON 조회로 됨 |
| 4 | 비개발 v1 범위 | (a) F1~F6(스위치·문구·스킬·복제·반려 사유·요청 기한) (b) +F7 프로젝트 달력 (c) +F8 반복 업무 | **(a)** — 운영·마케팅 실제 사례가 없음. 복제로 반복을 대신해 보고 수요가 보이면 F8(완료 시 다음 회차)·F7 추가 |
| 5 | 같은 저장소를 여러 프로젝트가 자동 가져올 때 이슈 하나→태스크 여럿(P-1) | (a) 현행 유지 + 이슈 뷰어에 "다른 프로젝트에서 가져옴" 표시 (b) 조직 단위 중복 방지 | **(a)** — 연결별 격리 설계와 일관. (b)는 어느 프로젝트가 우선인지 규칙이 또 필요 |

묻지 않고 추천대로 진행(되돌리기 쉬움): B-Q2 조직 기본값 켬, Q3 생성 대화상자 체크박스, Q5 지정 검토자 없음, Q6 파일 첨부 없음, Q7 "업무 거버넌스", Q8 상태 설명 일반화, Q9·Q10.

## 확인 불가
- C의 N+1 쿼리 수·커버리지 %(재측정 안 함, 방향은 코드로 타당).
- Proxmox vzdump 예약·NPM 속도 제한 현황(SSH·VPN 필요).
- 실제 GitHub의 개인 계정 `/orgs/*` 응답 코드(A와 동일, mock).
