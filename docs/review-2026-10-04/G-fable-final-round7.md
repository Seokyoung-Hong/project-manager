# G — 라운드 6·7 최종 승인 검토 (Fable, 2026-10-05, 기준 8d0be51 → HEAD babf2d9)

검토 방식: 코드·git 수정 없음. 테스트 3벌 실행, 핵심은 코드로 직접 확인, 3갈래(가시성 우회 전수 조사 / GitHub·Discord 결정 반영 / Sol 반려 회귀 테스트 실효성) 병렬 조사 후 핵심 주장은 재확인. 스크래치에 PoC 1건 작성·실행(저장소 밖).

## 판정: **조건부 승인** — 아래 "반드시 고칠 것" 2건(각각 1~3줄 수정 + 테스트)을 넣은 뒤 main 병합.

## 실행 결과
- `core`: 1260 passed (197.5초). `discord_service`: 171 passed. `mcp_server`: 50 passed.
- `makemigrations --check`: 변경 없음. `ruff check`: 깨끗함.
- 새 마이그레이션 7개(accounts 0005, orgs 0009, projects 0010, tasks 0005~0008) 전부 additive. 기존 행 기본값 안전: `Team.dev_tools=True`, `Team.is_private=False`, `Project.visibility="org"`, `Task.is_template=False`(제약 `task_template_is_todo`는 `NOT is_template OR status=todo`라 기존 행 전부 참). 데이터 마이그레이션 없음.

## 1. Sol 반려 6건(F) + 이전 반려 3건 — 전부 근본 수정, 회귀 테스트 실효 있음
- 수정 전 커밋(f8b3ccd) 사본에 신규 테스트 9개를 넣어 돌리면 9개 모두 실패(400 기대에 201, 응답에 비밀 제목 잔존, ServiceError/IntegrityError 미발생). HEAD에서는 42개 통과.
- Idempotency 재생: `_idem_replay`(tasks/services.py:230-240)가 사전 조회(:268)와 IntegrityError 복구(:323) 두 경로에 다 걸림. `duplicate_task`·웹 폼도 `create_task` 경유.
- 계열: `_series`(web/views/tasks.py:128-136) `visible_tasks`로 뿌리·회차 거름, API `children_count`도 viewer 기준(api/serialize.py:33-37). `_series.html`은 첫 행을 뿌리로 다루지 않아 뿌리가 숨어도 안 깨짐.
- 문서: 이동 시 `task.docs.remove(...)`(:428-431) + 출력 필터. 비공개 팀: `_team_out`/`_shown_team_ids`(serialize.py:74-96). 웹은 원래부터 `visible_teams`(orgs.py:113).
- 첨부: 조직·대상·원본 행 `select_for_update` + 저장 뒤 `_check_room(…, 0, None)` 재확인(attachments.py:118-145), 경계값(50개째·정확히 quota) 허용 맞음. `attachment_single_successor` 유니크 제약(tasks 0008) + IntegrityError→ServiceError, 모든 실패에 파일 삭제.
- 이전 반려: 설치 소유 검증은 `/app/installations/{id}` 계정 대조 + 조직이면 `/user/memberships/orgs` admin(github/services.py:87-139), 콜백·재시도 경로 모두 `save_installation` 경유, 설치 버튼은 GitHub 연결 전 차단. 유예일은 프로젝트별 `effective(..., project=)`(orgs/discord.py:122-126). Discord 콜백은 `compare_digest`+code 교환, 실패는 안내로 종료(web/views/discord.py:123-146).

## 2. 반드시 고칠 것(병합 전)
| 심각도 | 위치 | 내용 | 수정 |
|---|---|---|---|
| **중** | `core/config/urls.py:7` | `/admin/login/`이 Django 기본 `AdminAuthenticationForm`을 그대로 써서 `accounts/auth.authenticate_password`(LoginLock)를 **우회**. PoC 재현: `/login` 5회 실패로 잠긴 계정이 `/admin/login/` 20회 실패에도 LoginLock 행 0건, 올바른 비밀번호로 302 로그인, `auth_method` 세션 값 없음(login_user 미경유 → OIDC 로그아웃 분기도 못 탐). 라운드 목표(로그인 시도 제한)가 superuser 계정에서 무효 | `admin.site.login = login_required(admin.site.login)` 한 줄(미인증 admin 접근은 `/login`으로) + 테스트 1개. admin logout도 같은 방식으로 `logout_user`로 돌리면 OIDC 대비 완결 |
| **중(조건부)** | `core/tasks/services.py:186-188` | 검토자(reviewer)는 조직 멤버인지만 보고 `_require_viewer`는 담당자에만(:389, :403). 비공개 프로젝트를 못 보는 사람을 검토자로 지정 가능 → 검토 독촉 DM(discord_service/escalate.py:69-93)이 프로젝트 이름·태스크 제목을 그 사람에게 보냄. 발생 조건: CORE_TOKEN 사용자가 그 비공개 프로젝트를 볼 때 | `_validate`에 `_require_viewer(reviewer, project)` 한 줄, 프로젝트 이동 시 재검사(담당자와 같은 꼴) + 테스트 1개 |

## 3. 배포 전 확인 사항(코드 변경 없음, 문서·운영)
- **`docs/OPERATIONS-DEPLOYMENT.md:58` 문구 정정**: 현재는 "Discord 앱(Developer Portal) 소유자"를 말하는데, 실제 조건은 **`.env.discord`의 `CORE_TOKEN`을 발급한 PM 계정이 조직 관리자**여야 비공개 프로젝트의 막힘·검토 독촉이 나간다(`/api/orgs/{id}/tasks` → `list_tasks` → `visible_tasks(request.auth)`; api/routers/orgs.py:223-250, tasks.py:68). 마감 DM은 담당자 가시성 기준(orgs/discord.py:140-143)이라 무관. 문서 :38은 "전용 discord-bot 계정"이라고만 적혀 있어 관리자가 아니면 **비공개 프로젝트 에스컬레이션이 조용히 빠진다**.
- **방화벽**: `compose.yml` `web`은 `0.0.0.0:${WEB_PORT:-8000}`, gunicorn `--forwarded-allow-ips="*"`, `client_ip`는 XFF 맨 오른쪽. 프록시 IP만 8000을 열어 두지 않으면 직접 접속으로 XFF를 지어내 **IP 잠금만** 우회(아이디 잠금은 유지). README:114에만 있고 라운드 7 절에는 없음 → 한 줄 추가.
- 운영 DB 점검 2건: ① 소유 검증 이전에 저장된 `GitHubInstallation` 행은 재검증하지 않음 → 행이 있으면 설치 계정 확인. ② 0c0a9fc 이전에 생긴 "다른 프로젝트 문서 연결"은 출력에서 걸러지지만 복제(services.py:656)가 그대로 복사 → `tasks_task_docs`에서 `doc.project_id != task.project_id`인 행 유무 확인.
- 라운드 7 절에 추가할 것: `/ops` 잠금 표·`manage.py unlock_login <아이디|IP>`, gunicorn threads 16→32(메모리 여유), 마이그레이션 7개 additive·롤백 불필요, 서버 `.env`에 `DISCORD_CLIENT_SECRET` 없으면 Discord 연결 거절(fail closed, 의도), `COMPOSE_PROFILES=mcp` 유지, NPM 본문 한도 26m(이미 있음).
- 배포 순서는 D 문서 그대로(F1 수정 배포 → `discord` 기동).

## 4. 사용자 요구 반영(2026-10-05)
- 운영 서버 작업 없음(문서·스크립트만): 맞음. 로그인 리팩토링: `login_user` 단일 진입·`identity.resolve` facade·`LoginForm` 분리·`auth_method` 세션·OAuth 토큰 90일 — §4.4 OIDC는 "공급자 모듈 + 표"로 붙일 수 있는 구조. 예외는 위 admin 1건.
- 비개발 팀/프로젝트(`Team.dev_tools`, `project.dev_tools`), 팀 View 권한 = 프로젝트 공개 범위 + `Team.is_private`(결정 1 c), 첨부 25MB/조직 2GB(`MAX_BYTES`, `org.attachment_quota_mb` 2048, org 전용·프로젝트 재정의 불가), 지정 검토자+관리자 예외(결정 2; 계획 §1.4-3 그대로 **완료만** 제한, 반려는 누구나 — 아래 5), 저장소 연결 시 dev_tools 자동(`connect_repo` 한 곳, services.py:419-421; 저장소 있으면 끄기 불가 projects/services.py:401), 같은 저장소 다중 연결 경고(웹 재확인·API/MCP `warning`), 개인 계정 조직 자동 가져오기 금지(설정 강제 off·웹훅·폼·API 4곳), Discord 알림에 제목·프로젝트·마감·상태·링크(`alert_line` 공용) — 전부 반영.

## 5. 이후로 미뤄도 되는 것(하)
- 반려(review→todo/doing)는 검토자 확인 없음 — 계획 문서와 일치하나 결정 2를 "승인·반려"로 읽으면 빠짐. 사용자 확인.
- 요청 상세(requests/detail.html:17)가 수락된 태스크 번호·링크 노출(제목은 요청자 본인 텍스트). 변경 이력의 옛 프로젝트 이름(web/views/common.py:211), 조직 이슈 화면의 프로젝트 이름·태스크 번호(web/views/github.py:466-470).
- 웹훅 격리가 `ServiceError`·`ConflictError`만 잡음(GitHubError 등은 500). `create_request` 키 재생 미검사(requests.py:116-118); 요청에 쓴 키로 태스크 생성 시 복구 경로 `.get(target_type="task")` DoesNotExist→500(롤백되어 데이터 무손상).
- 초과 판정 두 벌: `common/dates.overdue_before`와 `orgs/discord.py:124` 내부 함수(의미 동일, 날짜 인자만 다름). 통합 가능.
- 검토자 지정 묶음 독촉이 막히면 관리자에게 넘기지 않음. `orgs/github.html:25` 안내 문구 낡음. 생성 폼의 공유 저장소 경고가 실패 문구로 보임.
- 죽은 코드 없음(ruff 깨끗, 새 함수 전부 사용처 있음).

## 6. 확인 불가
- Postgres 실제 병렬 업로드·잠금 순서(교착) — 테스트는 SQLite 결정적 교차.
- 운영 서버 상태(방화벽 규칙, NPM 본문 한도·속도 제한, DB의 설치 행·문서 연결 행, CORE_TOKEN 계정의 역할) — SSH·VPN 필요.
- 실제 GitHub API 응답(mock).
