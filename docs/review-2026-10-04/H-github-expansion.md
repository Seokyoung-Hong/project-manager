# GitHub 연동 확장 후보 (HEAD 5d9b7bc, 읽기 전용 조사)

경로는 저장소 루트 기준. `services` = `core/github/services.py`.

## 1. 현재 GitHub 연동

| 영역 | 있는 것 | 근거 |
|---|---|---|
| 앱 설치 | 조직당 설치 1개, 정지·해제·삭제 웹훅 반영 | `core/github/models.py:5-20`, services:647-672 |
| 사용자 연결 | OAuth, 토큰 Fernet 암호화 보관, 접근 저장소 목록 6시간 갱신, GitHub 로그인 | `core/github/models.py:23-44`, services:145-307 |
| 저장소 연결 | 프로젝트당 저장소 1개, 규칙 5개(issue·branch·commit·pr·merge), 가져오기 라벨, auto_import | `core/github/models.py:47-75` |
| 웹훅 | create·push·pull_request·issues·membership·team·installation(_repositories)만 처리, 나머지는 202 무시 | services:547-589 |
| 자동 전환 | 브랜치→진행, 커밋 `TASK-n:k`→체크, PR opened→검토, 병합→완료, 이슈 닫힘→완료. 닫힌 태스크는 다시 열지 않음 | services:693-712, 816-875, 900-927 |
| PR 처리 범위 | **opened·closed만**. reopened·synchronize·ready_for_review 등은 "무시"로 기록 | services:823-834 |
| 이슈 | RepoIssue 사본(제목·상태·담당·라벨·본문), 수동/자동 가져오기, 10분 지나면 재동기화 | `core/github/models.py:78-100`, services:984-1110 |
| 태스크 쓰기 | 이슈 만들기·닫기, 브랜치 만들기, PR 작성 링크(`Closes #N`) — 모두 사용자 토큰 | `core/github/writes.py:152-212`, services:1157 |
| 팀·조직 | 팀 링크·생성·이름·멤버 양방향, 조직 초대·제거 | `core/github/writes.py:68-150`, `core/github/models.py:144-163` |
| PR 맥락 | 태스크 결정 기록으로 PR 설명 맥락 생성 | `core/github/pr_context.py:1` |
| 앱 권한 | Contents R/W, Issues R/W, **Pull requests R**, Metadata R, Members R/W. Administration 없음 | `docs/IMPL-PLAN-2.md:97-108` |
| 범위 결정 | 쓰기는 사용자 토큰만, 설치 토큰은 읽기만; PR 병합·PM 커밋·저장소 생성·팀 저장소 권한 부여 제외 | `docs/IMPL-PLAN-2.md:14, 60-61, 113-118, 434` |
| 권한 추가 비용 | 권한을 늘리면 설치 조직마다 재승인 필요, 승인 전 동작 안 함 | `docs/GITHUB-APP-SETUP.md:168` |

## 2. Discord 대비 대칭 비교

| Discord 기능 | 근거 | GitHub 쪽 대응 | 빈 곳 |
|---|---|---|---|
| 조직↔서버 연결 | `core/orgs/discord.py:175-227` | 앱 설치 | 없음 |
| 사용자 계정 연결 | `slash.py:276-285` | OAuth 연결 | 없음 |
| 채널 관리(프로젝트 채널 생성·지정·권한) | `discord_service/.../control.py:132-336`, `channels.py` | 팀·멤버 동기화(채널 대신 팀) | 저장소 접근 권한은 딥링크만(의도된 제외) |
| 프로젝트 채널 사건 게시(새·완료·막힘·초과) | `channels_post.py:30-32` | **없음** — PR 열림·병합·CI 실패·이슈 유입을 채널에 올리지 않음 | **큼** |
| 마감 DM | `notify.py:27`, `core/orgs/discord.py:103-160` | 없음(GitHub는 알림 채널 아님) | 해당 없음 |
| 에스컬레이션(막힘·검토 지연 → 관리자 DM) | `escalate.py:35-60`, `core/orgs/settings.py:627` | 검토 지연은 **PM 상태 `review` 기준**만. GitHub 리뷰 요청·승인 정보 없음 | 중간 |
| 주간 보고 | `weekly.py`, `scheduler.py:129` | GitHub 지표(병합 PR 수·리뷰 소요) 없음 | 작음 |
| 슬래시 명령 15개(오늘·완료·연장·태스크만들기·요청…) | `slash.py:258-438` | GitHub 동작(브랜치·이슈 만들기)은 웹에서만 | 중간 |
| 요청 접수(요청·수락·거절) | `slash.py:361-438`, `core/orgs/requests.py` | 이슈 가져오기가 사실상 외부 요청 접수 | 작음 |
| (Discord엔 없음) 검토자 | `core/tasks/models.py:72-79` | PR 리뷰어와 연동 안 됨 | 중간 |

## 3. 추가 기능 후보

권한 표기: "없음" = 현재 권한으로 가능, "구독" = 앱 설정에서 이벤트 구독만 추가, "재승인" = 권한 추가로 설치 조직 재승인 필요.

| # | 이름 | 사용자 가치(개발 팀) | 권한 변경 | 데이터 모델 | 웹훅 이벤트 | 규모 | 위험 | 추천 |
|---|---|---|---|---|---|---|---|---|
| 1 | PR 상태 처리 확장 | draft·reopened·ready_for_review·synchronize가 태스크 패널에 반영. 지금은 "무시"(services:823) | 없음 | `TaskGitLink.pr_draft`(bool) 정도 | pull_request(기존) | S | 낮음. reopened 시 닫힌 태스크 재개 여부는 정책 결정 필요(services:697) | **1차** |
| 2 | PR 리뷰 상태 표시·반영 | 패널에 "승인 2 / 변경 요청 1". 변경 요청 → 태스크를 진행 중으로 되돌리기(규칙 스위치) | 구독(pull_request_review). PR R로 수신 가능 | `TaskGitLink.review_state`, `RepoConnection.rule_review` | pull_request_review | M | 중. 상태 자동 되돌림은 규칙 스위치로 끄게 | **1차** |
| 3 | 리뷰 요청 ↔ 태스크 검토자 | GitHub에서 리뷰어 지정 시 태스크 `reviewer` 자동 설정(읽기). PM→GitHub 리뷰 요청은 별도 | 읽기만: 없음(구독). PM→GH 요청: **PR W 재승인** | 없음(`Task.reviewer` 재사용) | pull_request(review_requested) | S(읽기) / M(쓰기) | 쓰기 쪽은 권한 확대 | **1차(읽기만)** |
| 4 | 프로젝트 채널에 GitHub 사건 게시 | PR 열림·병합, 이슈 자동 가져옴, (CI 실패)을 Discord 프로젝트 채널로 | 없음 | 게시 종류 추가(`channels_post.py:30`), 조직 설정 키 | 기존 이벤트 재사용 | M | 소음. 종류별 on/off 필요. core→discord 전달 경로(`scheduler.py:189 deliver_notices`) 재사용 검토 | **1차** |
| 5 | 리뷰 지연 독촉(GitHub 기준) | 리뷰 요청 후 N일 응답 없으면 검토자 DM. 현 에스컬레이션은 PM `review` 상태·관리자 대상(`escalate.py:20-60`) | 없음 | 리뷰 요청 시각 저장(`TaskGitLink.review_requested_at`) | #2·#3에 의존 | S | 낮음. 기존 `notify.review_nudge_days` 재사용 | **1차** |
| 6 | CI(Checks) 결과 배지 | 패널·보드 카드에 ✓/✗/진행 중, 병합 전 실패를 PM에서 보임 | **재승인**: Checks R, Commit statuses R | `TaskGitLink.ci_state`, `ci_url` | check_suite(completed), status | M | 재승인 동안 기능 꺼짐. head sha 매칭 필요 | 2차 |
| 7 | CI 실패 알림 | 실패 시 담당자 DM 또는 채널 게시 | #6과 같음(Actions R 추가 시 워크플로 이름까지) | #6 재사용 | check_suite / workflow_run | S(#6 뒤) | 소음 | 2차 |
| 8 | 이슈 ↔ 태스크 필드 동기화 | 이슈 제목·담당자 변경 → 태스크 반영, 태스크 제목·담당 변경 → 이슈 반영 | 없음(Issues W 보유). 단 PM→GH는 사용자 토큰 원칙 유지 | 동기화 기준 시각 | issues(edited·assigned·reopened) | M | 루프·충돌. 지금 원칙 "PM 먼저, GH는 다음"(`writes.py:11-14`)과 충돌 소지 | 2차 |
| 9 | 마일스톤 동기화 | GitHub 마일스톤 ↔ PM `Milestone`(`core/projects/models.py:81`) | 없음(Issues 권한 범위) | `Milestone.gh_number` | milestone, issues(milestoned) | M | 이름·기한 충돌 규칙 필요 | 2차 |
| 10 | 릴리스·태그 → 마일스톤 완료·결과 선반 | 릴리스 발행 시 해당 마일스톤 완료 제안, 결과 선반(`projects/_shelf.html`)에 릴리스 표시 | 구독(release, Contents R 범위) | 릴리스 기록 모델 1개 | release(published) | M | 낮음 | 3차 |
| 11 | 주간 보고에 GitHub 지표 | 병합 PR 수, 평균 리뷰 소요, 열린 PR 수 | 없음 | 없음(GitEvent 집계) | 기존 | S | 낮음 | 2차 |
| 12 | Discord 슬래시로 GitHub 동작 | `/브랜치`, `/이슈만들기`, `/pr` (writes.py 재사용, 사용자 토큰) | 없음 | 없음 | 없음 | M | 중. Discord 사용자→PM→GitHub 신원 3단 확인 | 3차 |
| 13 | 커밋·PR 활동을 포트폴리오·결정 기록에 연결 | 포트폴리오 근거에 병합 PR 링크. 지금 포트폴리오는 git을 쓰지 않음(`core/portfolio/sources.py` grep 결과 없음) | 없음 | 소스 종류 추가 | 없음 | M | 낮음 | 3차 |
| 14 | 브랜치 규칙 상태 읽기 | 기본 브랜치에 리뷰 필수·CI 필수가 걸렸는지 저장소 탭에 표시 | 규칙셋 조회 API는 Metadata R로 가능(확인 필요), 전통 브랜치 보호 조회는 Administration R 필요 | 없음(조회 시점 표시) | 없음 | S | 낮음, 가치도 낮음 | 보류 |
| 15 | GitHub Projects(v2) 연동 | 보드 이중 관리 해소 | **재승인**: Organization projects R/W, GraphQL | 큼 | projects_v2_item | L | 높음. PM 보드와 역할 중복 | 비추천 |

## 4. 추천 1차 묶음

- 구성: **#1 PR 상태 확장 + #2 리뷰 상태 + #3 리뷰어→검토자(읽기) + #4 채널 게시 + #5 리뷰 지연 독촉**
- 이유
  - 모두 **권한 추가 없음**(이벤트 구독 추가 정도) → 설치 조직 재승인(`docs/GITHUB-APP-SETUP.md:168`) 없이 배포 가능.
  - 이미 있는 부품 재사용: PM `review` 상태·`Task.reviewer`(`core/tasks/models.py:72`), 에스컬레이션(`escalate.py`), 채널 게시(`channels_post.py`). 새 모델은 `TaskGitLink` 필드 몇 개.
  - Discord 대비 가장 큰 빈 곳(GitHub 사건이 채널로 안 감)과 개발 팀이 가장 자주 막히는 곳(리뷰 대기)을 메움.
- 2차: #6·#7(CI, Checks R 재승인 한 번에 묶기), #8, #9, #11.

## 5. 확인 불가 / 정책 결정 필요

- 권한은 그대로 두고 **이벤트 구독만 추가할 때 재승인이 필요한지**: 문서(`GITHUB-APP-SETUP.md:168`)는 권한 추가만 언급. GitHub 공식 문서로 확인 필요.
- pull_request_review 이벤트가 Pull requests **읽기**만으로 수신되는지: 일반적으로 그렇다고 알려져 있으나 이 저장소 안에서는 확인 불가.
- 규칙셋 조회(`GET /repos/{o}/{r}/rules/branches/{b}`)의 필요 권한: 확인 불가.
- PR reopened·이슈 reopened 시 닫힌 태스크를 재개할지: 현재 코드는 재개하지 않음(services:697). 사용자 결정 필요.
- 운영 앱에 실제로 구독된 이벤트 목록: 서버·GitHub 설정은 보지 않았음.
