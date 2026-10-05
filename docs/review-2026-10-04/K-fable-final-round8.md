# K — 라운드 8 최종 승인 검토 (Fable, 2026-10-05)

- 대상: `Seokyoung-Hong/Ochestration` HEAD `2b729a3`, 기준 `c902e17`(49커밋, 128파일, +6882/−1108). 코드·git 변경 없음.
- 실행: `core` 1362 passed(36s), `discord_service` 179 passed, `mcp_server` 50 passed, `makemigrations --check` 변경 없음.
- 갈래 2개 위임: (A) 템플릿 기능 훅 대조, (B) Sol 결함 6건을 수정 전 커밋 `fed48c3` 사본(git archive)에서 재현. 나머지는 직접 코드로 확인.

## 판정: **조건부 승인**
아래 "반드시 고칠 것" 3건(모두 작은 수정)을 반영하면 main 병합 가능.

## 반드시 고칠 것
1. **[중] 저장소 연결 해제가 Discord 권한에 잠긴다.** `core/github/services.py:536-543` → `hooks.remove` → `core/github/hooks.py:152-154 _require` → `require_discord(actor, org, "webhooks")`. 훅 상태가 `pending`·`error`(GitHub 훅이 없는 상태)여도, 또 관리자가 Discord를 연결하지 않았거나 봇 권한 보고가 15분 넘게 오래됐으면 **저장소 연결 해제·오류 지우기가 모두 거절**된다. 봇이 Manage Webhooks가 없어 `error`가 난 프로젝트는 같은 권한이 없는 사람이 풀 수 없다. 수정: `disconnect_repo`는 `state == "active"`일 때만 `hooks.remove`를 부르고(그 밖은 `conn.delete()`만 — `on_created`가 연결 행 없음을 보고 `delete_webhook=True`로 되돌린다), `remove()`의 `require_discord`도 `active`에만 적용.
2. **[중·문서] `docs/GITHUB-APP-SETUP.md` §1이 옛 목록이다.** Permissions 표(40-50줄)에 Checks Read·Commit statuses Read·Webhooks Read and write가 없고, Subscribe to events(60줄)에 `pull_request_review`·`check_suite`·`status`·`milestone`·`release`가 없다. §7만 Webhooks를 언급. 새 앱을 이 문서로 만들면 라운드 8 기능이 전부 조용히 꺼진다. `docs/IMPL-PLAN-8.md` §1.1·§1.2 표를 §1에 옮기고 §6에 재승인 한 줄 추가.
3. **[하] 재승인 뒤 Webhooks 권한 캐시가 1시간 남는다.** `core/github/services.py:776`의 `new_permissions_accepted`가 `gh-app-caps:`만 지우고 `gh-app-hooks:{installation_id}`(`hooks.py:97`)는 안 지운다. 승인 직후 1시간 동안 버튼 대신 "권한 없음"이 보인다. `cache.delete(f"gh-app-hooks:{inst_id}")` 한 줄.

## 확인한 것(통과)
- **가시성 관문**: 릴리스는 `can_see_releases`(`sync.py:104`, 선반·API)와 같은 규칙의 `releases_by_milestone`(`sync.py:119`, 로드맵)만 지난다. 포트폴리오 PR 근거는 `can_view_repo`(`portfolio/sources.py:46-60`), 번호·URL·병합일만. DM은 `is_member`+`can_see`+조직/개인 설정(`notify.py:32-43`). 재개 태스크·`continued_by`는 같은 프로젝트(`services.py:550-574`). 주간 지표는 `shown_projects`(viewer 가시성) 범위(`reports/services.py:242`). 보드·선반은 `visible_tasks`로 바뀜(`web/views/projects.py`).
- **쓰기 토큰**: GitHub 훅 POST/PATCH/DELETE·마일스톤 POST/PATCH 전부 누른 사람 토큰(`hooks.py:247,272,295,459`, `writes.py:225-243`). 설치 토큰 쓰기 없음.
- **비밀 비노출**: DB에는 `webhook_id`·`hook_id`·상태만(`models.py:71`), `status()`가 `****` 마스킹(`hooks.py:327`), 로그 스크럽 패턴 추가(`common/logging.py:12`), GitHub 오류 메시지도 `mask`(`hooks.py:88`), 봇은 토큰을 메모리에만(`github_hooks.py:18`). API 응답에 토큰 없음(`api/routers/discord.py:623-627`).
- **봇↔core 인증**: 새 4개 엔드포인트가 `Router(auth=BotTokenAuth())` 아래(`discord.py:61`).
- **메아리 루프**: PM→GH 마일스톤은 체크박스일 때만, GH→PM은 GitHub에 다시 쓰지 않음. `sync_milestone`이 gh_number·이름으로 잇고 "변경 없음" 처리(`projects/services.py:561-607`). 이슈 양방향은 §10-1대로 미구현. Discord 훅은 GitHub→Discord 직결이라 PM 경유 없음.
- **재전송·역순·동시성**: delivery 중복 검사·연결별 atomic 유지(`services.py:662,676`). 리뷰 역순은 `(at,id)` 비교+링크 행 잠금(`services.py:1137-1160`). 재개 동시 생성은 원 태스크 행 `select_for_update`(`services.py:1189`). 웹훅 설정은 세대 `job`+조건부 갱신+보상 삭제 목록(`hooks.py:417-493`), 재보고 멱등(`hooks.py:435-437`).
- **Sol 결함 6건**: 전부 근본 수정. 회귀 테스트가 `fed48c3`에서 FAIL, HEAD에서 PASS(결함 5·6은 인터페이스 차이로 import 실패라 job 인자를 뺀 사본으로 동작 실패까지 재현). 상세는 갈래 B 보고.
- **템플릿 리팩터링**: 56개 템플릿의 hx-*·name·id·data-action·`{% url %}`·app.js 셀렉터 전수 대조, 끊어진 훅 없음. 유일한 제거 `data-include-closed`는 의도된 것(보드→선반). `/ops/design`은 `@staff_member_required`(`ops.py:94`).
- **마이그레이션**: 5개(github 0006·0007, tasks 0009, projects 0011, portfolio 0002) 모두 열 추가·제약만, RunPython 없음. `status_since`·`gh_number` null 허용이라 옛 행 영향 없음.
- **권한 없을 때**: 이벤트가 안 오면 아무 일 없음, 점검 표가 "구독 아님/권한 없음"을 그림(`services.py:166-192`, `web/views/github.py:60-88`).
- **지정 검토자 반려**: `can_reject`(`tasks/services.py:468-484`)가 `transition` 입구에서 적용, 웹훅 경로(actor=None)는 설계대로 통과.

## 미뤄도 되는 것
- 코멘트 리뷰가 `at`를 최신으로 올려, 역순 도착한 변경 요청(승인보다 늦고 코멘트보다 이른)이 무시됨(`services.py` `_on_pr_review` `kept`/`at`). 코멘트면 이전 `at` 유지로 해결.
- `_on_pr`의 `link.save()`(전체 필드)가 동시 리뷰 JSON 갱신을 덮을 수 있음 — 잠금 없음, 창 매우 짧음.
- `hooks.remove()`가 상태를 잠금 밖에서 읽음(`hooks.py:289`). `registering`→`active` 전환과 겹치면 hook_id를 잃고 GitHub 훅이 남을 수 있음(수 ms 창).
- core가 `registering` 중 죽으면 사용자가 해제할 때까지 멈춤. `_sweep`은 토큰 만료 시 틱마다 GitHub DELETE 재시도(횟수 제한 없음, ponytail 주석 있음).
- 죽은 참조 `includeClosed`(`web/static/app.js:371`, `tasks/_row.html:31`).
- 설계 메모의 미해결 3건 그대로: 비공개 저장소 릴리스 채널 알림(기본 꺼짐), SQLite에서는 `select_for_update` 무효(운영 Postgres), 봇 재시작 시 `_UNREPORTED` 유실.

## 사용자가 해야 할 일
- GitHub 앱 설정: Permissions에 **Checks Read**, **Commit statuses Read**, **Webhooks Read and write** 추가 → 설치 계정(조직·개인)마다 **재승인**. Subscribe to events에 **Pull request review, Check suite, Status, Milestone, Release** 추가. 끝나면 PM 조직 GitHub 탭의 점검 표가 전부 ✓인지 확인.
- Discord: 봇 역할에 **웹후크 관리**, 설정 버튼을 누르는 사람도 서버에서 웹후크 관리 권한 필요.
- 배포 시 마이그레이션 5개 적용(데이터 이동 없음).

## 확인 불가
- 실제 GitHub·Discord와의 왕복(훅 등록·재승인 이벤트·Discord 50013), Postgres에서의 동시 reopen·동시 리뷰, 운영 로그의 비밀 비노출.
- 이벤트 구독만 추가할 때 재승인 필요 여부(IMPL-PLAN-8 §1.3 "확인 불가" 그대로).
