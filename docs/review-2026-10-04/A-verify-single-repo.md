# 검증 A — 개인 계정 설치 · 저장소 하나에 프로젝트 여럿

작성 2026-10-04. 제품 코드 수정 없음. 테스트만 `core/github/tests.py`에 추가(커밋 안 함).

## 실행

- 명령: `cd core && uv run pytest -q -p no:cacheprovider` (SQLite, 외부 GitHub 호출은 monkeypatch)
- 추가 전: **708 passed**
- 추가 후: **714 passed, 5 xfailed** (`ruff check`·`ruff format` 통과)
- xfail 사유 확인: `uv run pytest github/tests.py -k "user_install or archived" --runxfail` → 5건 모두 의도한 assert에서 실패(NameError 같은 우연한 실패 아님)
- 관례: 저장소에 xfail/expectedFailure 선례가 없어 pytest 함수 스타일에 맞춰 `@pytest.mark.xfail(strict=True, reason="결함: …")` 사용. 고치면 XPASS→실패로 표시 제거를 강제한다.

## 시나리오 1 — 개인 계정(User) 설치

판정: **핵심 흐름은 동작, 조직 전용 기능은 숨김·안내 없음(500은 없음)**

동작 확인(통과 테스트 `test_user_account_install_and_single_repo_flow`, tests.py:437):
- `save_installation`이 `account.type="User"`를 `account_type`에 저장(services.py:77-102)
- `/user/installations/{id}/repositories`로 접근 저장소 동기화 → 후보 1개 표시 → URL 연결 302
- 저장소 탭: `/repos/{repo}/teams` 404를 `_repo_teams`가 잡아 200(web/views/github.py:273-286)
- 웹훅 `create`(브랜치 `feat/x(TASK-n)`) → 태스크 doing, TaskGitLink 연결
- 팀 상세 화면: `list_org_teams` 404를 잡아 200(`test_user_install_team_page_does_not_500`, teams.py:140-145)

핵심 원인: `GitHubInstallation.account_type`을 **저장만 하고 어디서도 읽지 않는다**(grep 결과 models.py:11, services.py:94 뿐).

### 결함 S1-1 설정 링크 404
- 위치: web/templates/orgs/github.html:12 — `https://github.com/organizations/{login}/settings/installations/{id}` 고정
- 영향: 개인 계정 설치에선 이 경로가 없다(개인은 `https://github.com/settings/installations/{id}`). 설치 설정 화면 진입 불가.
- 재현: `test_user_install_settings_link_points_to_user_settings` (xfail)
- 권장: `install.account_type == "User"`면 `/settings/installations/{id}`로 분기.

### 결함 S1-2 GitHub 팀 연결·생성 UI가 그대로 노출
- 위치: web/templates/orgs/team_detail.html:18-40 (`gh_install`만 확인), web/views/teams.py:140-145
- 영향: 빈 선택 목록과 [GitHub 팀 만들고 연결] 버튼이 보임. 누르면 `POST /orgs/{login}/teams` 404 → "다시 만들기 전에 GitHub에 같은 팀이 이미 생성됐는지 확인하세요" 라는 오해 소지 안내(teams.py:252-266). 500은 아님.
- 재현: `test_user_install_hides_github_team_ui` (xfail)
- 권장: 뷰 컨텍스트에 `gh_is_org = inst.account_type == "Organization"`을 넣고 섹션 숨김 또는 "개인 계정 설치에서는 GitHub 팀을 쓸 수 없습니다" 안내. `list_org_teams` 호출도 생략.

### 결함 S1-3 조직 초대가 /orgs API를 부름
- 위치: web/views/orgs.py:198-217(초대), github/writes.py:65-71, 초대 폼 체크박스 web/templates/orgs/teams.html:66-69(`github_enabled`만 확인)
- 영향: `PUT /orgs/{user}/memberships/{login}` → 404 → "GitHub에 반영하지 못했습니다(HTTP 404)…연동 문제 해결에서 복구 방법을 확인하세요" 경고 + 재시도 항목 생성. 재시도해도 영원히 404.
- 재현: `test_user_install_invite_skips_org_api` (xfail)
- 권장: User 설치면 체크박스 숨김(또는 "저장소 협업자 초대는 GitHub에서 직접" 안내), 서버도 호출 생략.

### 결함 S1-4 멤버 제거가 /orgs API를 부름
- 위치: web/views/orgs.py:260-278, github/writes.py:74-75
- 영향: PM 제거는 성공하지만 `DELETE /orgs/{user}/members/{login}` 404 경고 + 무의미한 재시도 항목.
- 재현: `test_user_install_member_remove_skips_org_api` (xfail)
- 권장: S1-3과 같은 가드. 재시도 경로(web/views/github_retries.py:103-164)에도 같은 가드.

### 경미(테스트 없음)
- 저장소 탭의 팀 조회 실패 안내 문구(web/views/github.py:341-348)가 "Repository Administration 읽기 권한"을 원인 후보로 제시 — 개인 저장소는 팀 개념 자체가 없어 404가 정상. User 설치면 팀 표 자체를 숨기는 편이 맞다.
- github.html:17 "이 앱이 할 수 있는 것: … 조직 멤버와 팀 관리" 문구도 User 설치엔 해당 없음.

## 시나리오 2 — 저장소 하나에 프로젝트 여럿

판정: **설계상 대비돼 있고 정상 경로는 올바름. 부분 실패 1건이 결함, 중복 가져오기는 정책 결정 필요**

동작 확인(통과 테스트):
- `test_shared_repo_task_ref_moves_only_own_project` (tests.py:535): 브랜치·PR 이벤트가 TASK-n 소유 프로젝트만 움직이고 다른 연결엔 "연결 안 됨" 기록. `_find_task`가 `project=conn.project`로 거름(services.py:567-574). 같은 delivery 재전송은 `duplicate` 200, IntegrityError 없음 — delivery_id가 `{delivery}:{conn.pk}`(services.py:429, 475). 두 번째 연결의 full_name을 `O/R`로 대소문자만 다르게 해 `iexact` 매칭(services.py:468)도 확인.
- `test_shared_repo_issues_are_per_project` (tests.py:553): 이슈 이벤트가 연결마다 `RepoIssue` 사본 생성, B에서 가져오면 B 프로젝트 태스크·B 연결 링크, A 사본은 미가져옴 유지. `org_issues`는 2줄(프로젝트명 표시). `build_pr_context`가 태스크 프로젝트 연결 기준 URL. 이슈 closed → 가져온 태스크 done, 다른 사본도 closed.
- `test_shared_repo_create_branch_and_disconnect` (tests.py:629): `create_branch`가 자기 프로젝트 연결의 `full_name`으로 refs 생성, 링크 connection 올바름. 한 프로젝트 연결 해제 시 다른 연결·링크 유지(RepoIssue/GitEvent/TaskGitLink 모두 connection FK CASCADE라 연결별 격리).
- 기존 `test_same_repo_two_projects`(test_rules.py:55)와 `_pickable_repos`의 "이미 연결됨 · 프로젝트" 표시(test_repo_picker.py:112)도 통과.
- 프로젝트 하나만 연결된 경우: 기존 test_rules.py 전체(브랜치·커밋·PR·이슈 규칙)가 단일 연결 경로이며 통과.

### 결함 M-1 한 연결의 예외가 웹훅 전체를 깨고 나머지는 영영 처리 안 됨
- 위치: github/services.py:490-491 (`for conn in conns: handler(...)`에 예외 격리 없음), 원인 예외 services.py:835 `create_task`(보관 프로젝트면 `ServiceError`, tasks/services.py:131), 트랜잭션 없음(`ATOMIC_REQUESTS` 미설정, 웹훅 api/routers/github.py:38-43), ServiceError → 400(api/api.py:66-68)
- 재현 경로: 같은 저장소를 A(활성)·B(보관) 프로젝트에 연결, 둘 다 `auto_import=True`, 배정된 멤버가 있는 이슈 `opened` → 응답 400. A는 태스크 생성·이벤트 기록까지 커밋, B는 이벤트 없음. 이후 재전송은 services.py:475의 접두어 검사로 `duplicate` 처리되어 B는 영구 누락.
- 단일 프로젝트에서도 보관 프로젝트 + 자동 가져오기면 같은 400(RepoIssue 행만 저장되고 이벤트 기록 없음).
- 재현 테스트: `test_shared_repo_archived_project_does_not_break_delivery` (xfail)
- 권장: 연결별 `transaction.atomic()` + `try/except (ServiceError, ConflictError)`로 감싸 실패를 그 연결의 `record_event(result=사유)`로 남기고 200. 또는 `_on_issues`에서 `create_task` 실패를 `_apply`처럼 사유로 기록. 보관 프로젝트 연결은 자동 가져오기 건너뛰기.

### 정책 결정 필요 P-1 같은 이슈가 프로젝트마다 태스크로 중복
- 두 연결 모두 자동 가져오기면 이슈 하나가 태스크 둘(`test_shared_repo_auto_import_creates_a_task_in_each_project`, 현재 동작 기록용 통과 테스트). 조직 이슈 뷰어(web/views/github.py:439-470)에서도 프로젝트별 줄이 따로 있어 수동으로 각각 가져올 수 있다.
- 이후 이슈 closed는 두 태스크를 모두 done으로 만든다. 의도라면 유지, 아니라면 조직 단위 중복 방지(같은 full_name+number가 이미 가져와졌으면 안내) 필요.

### 경미(테스트 없음)
- 조직 이슈 뷰어 저장소 드롭다운이 `full_name`만 표시(web/templates/github/issues.html:11-12) → 같은 저장소가 구분 안 되는 동일 항목 두 개.
- `sync_org_issues`(services.py:965-984)가 같은 저장소를 연결 수만큼 GitHub에 다시 조회하고 `total`을 중복 합산 → "열린 이슈 N건" 과대.
- `_on_issues`의 `conn.auto_import` 검사(services.py:820) — 모델 주석(models.py:57-59)은 "더 이상 읽지 않는 열"이라 하지만 실제로 자동 가져오기 문턱으로 읽힌다. 문서·코드 불일치(이번 범위 밖, 참고).
- 대시보드·포트폴리오·리포트에서 RepoConnection/GitEvent 집계는 grep 결과 없음 → 해당 집계 위험 없음(api/routers/tasks.py:123,211은 태스크 단위).

## 추가한 테스트(core/github/tests.py)

| 줄 | 이름 | 상태 |
|---|---|---|
| 437 | test_user_account_install_and_single_repo_flow | 통과 |
| 470 | test_user_install_settings_link_points_to_user_settings | xfail(S1-1) |
| 478 | test_user_install_team_page_does_not_500 | 통과 |
| 484 | test_user_install_hides_github_team_ui | xfail(S1-2) |
| 493 | test_user_install_invite_skips_org_api | xfail(S1-3) |
| 504 | test_user_install_member_remove_skips_org_api | xfail(S1-4) |
| 535 | test_shared_repo_task_ref_moves_only_own_project | 통과 |
| 553 | test_shared_repo_issues_are_per_project | 통과 |
| 582 | test_shared_repo_auto_import_creates_a_task_in_each_project | 통과(현재 동작 기록, P-1) |
| 607 | test_shared_repo_archived_project_does_not_break_delivery | xfail(M-1) |
| 629 | test_shared_repo_create_branch_and_disconnect | 통과 |

그 밖에 import에 `RepoIssue`, `TaskGitLink` 추가, 픽스처 `fake_user_github`·`shared`, 헬퍼 `_user_install`·`_login`·`_repo` 추가.

## 확인 불가
- 실제 GitHub에서 개인 계정 설치 시 협업자(소유자 외)의 `/user/installations/{id}/repositories` 응답 — mock으로만 확인.
- 실제 GitHub의 개인 계정 대상 `/orgs/*` 응답 코드(404 가정, 404 외 코드여도 PM 쪽은 경고로 처리됨).
- 운영 서버 DB(Postgres)에서의 동작 — 테스트는 SQLite.
