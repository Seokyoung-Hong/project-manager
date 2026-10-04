# UI-UX 구현 및 검증 기록

2026-10-04 · 구현 기준 `Seokyoung-Hong/UI-UX`, 시작 HEAD `134ae90`.

이전 세션은 디자인·문구·버튼 검토까지 마쳤으며 앱 구현은 미완료였다.
이번에는 원본 미커밋 디자인 10파일의 diff만 UI-UX로 이전하고,
[문구 검토 40항목](UX_COPY_REVIEW.md)과 [버튼 검토 27항목](UX_BUTTON_PURPOSE_REVIEW.md)을 구현했다.
원본 워크트리의 다른 커밋·미커밋 변경과 과거 transcript는 수정하지 않았다.
검토 당시 인벤토리·스크린샷·보고서는 과거 증거로 보존한다. 구현 후 상태는 이 문서를 따른다.

## 사용자에게 달라지는 결과

- 문서·회의록 생성/업로드/삭제 실패가 메시지로 남고 자동 저장 실패는 실제 이유와 내용 보존 방법을 알린다.
- 로그인 화면으로 리다이렉트되거나 저장 버전 응답이 없으면 저장 완료로 처리하지 않는다. 편집기 outbox와 내용은 남는다.
- 잘못된 초대 만료 기간은 발급을 중단한다. 이슈 동기화의 전체 성공·일부 실패·전체 실패를 구분한다.
- 링크 입력 오류는 필드별로 표시하며 제목·URL·종류 입력을 유지한다.
- 설정한 기본 영업일 수의 목표일을 생성 폼에서 제안한다. 월~금 기준이며 자동 입력하지 않는다.
  오늘 빠른 생성은 선택한 프로젝트 설정에 맞춰 제안을 바꾼다. 0이면 제안하지 않는다.
- 버튼은 코드 발급, 본인 결정 확인, GitHub 멤버 추가, 태스크 가져오기, 연결 해제, 오늘 목록 제외처럼 실제 결과를 설명한다.
- 날짜 최초 지정과 연장을 구분하고, 취소·보관 확인에 프로젝트와 미완료 태스크 개수를 보여 준다.
- 포트폴리오는 외부 AI에 전달할 작성 요청과 비공개 초안 저장을 구분하고, 다운로드가 저장한 내용만 내보냄을 알린다.
- 복사 성공은 clipboard API 성공 때만 안내한다. 수동 복사 창을 열거나 취소한 경우 성공으로 표시하지 않는다.

## 검토 항목과 구현 근거

아래 경로는 `core/` 기준이다. ID 범위는 여러 항목이 같은 구현에 겹친다는 뜻이며 별도 기능 개수를 뜻하지 않는다.

| 검토 ID | 구현 | 주요 파일 |
| --- | --- | --- |
| A01 | 생성·업로드·삭제 ServiceError 메시지, 파일 누락 안내 | `web/views/docs.py`, `web/views/notes.py` |
| A02 | 잘못된 기간 발급 중단 | `web/views/orgs.py:invite_create` |
| A03 | HTMX 조회/변경/네트워크 실패 구분, JSON 오류 원인 | `web/static/app.js:requestError`, `web/views/tasks.py:task_text` |
| A04, B07 | 구체 오류·충돌·로그인 만료 안내 및 편집 내용/outbox 유지 | `web/static/notes.js:requestSave`, 문서·회의록 템플릿, 저장 JSON 응답 |
| A05, F14 | 복사 성공 분기와 수동 fallback 분리 | `web/static/app.js:copyText`, `web/templates/portfolio/index.html` |
| A06 | 전체/부분/실패 메시지 분리 | `web/views/github.py:org_issues_sync` |
| A07 | bound form·오류·입력 보존 | `web/views/projects.py:link_add`, `web/views/tasks.py:_refs`, 링크 템플릿 |
| B01, F15 | 로그인/가입 이후 조직 참여 확인 단계 | `web/templates/auth/join.html` |
| B02–B05 | OAuth 목록 위치·URL 토큰 인증·권한 범위·AI 정책 설명 | `web/templates/settings/tokens.html`, `oauth/authorize.html` |
| B06 | 실제 목표일 제안(월~금, 0은 비활성), 사용자 적용 버튼 | `web/forms.py:suggested_due_date`, `projects/_task_form.html`, `today/_quick.html`, `app.js` |
| B08 | 문서·회의록 삭제 범위, 참조 해제와 구별 | `projects/docs.html`, `notes/list.html`, `tasks/_refs.html` |
| B09 | 태스크 change 저장, 진행 메모 600ms, 문서/회의록 본문 800ms 안내 | `tasks/_panel.html`, 문서·회의록 도움말 |
| B10, F08 | 최초 목표일과 연장 문구 분기 | `tasks/_extend.html` |
| B11 | 의존 방향·관계 표시와 자동 착수 제한 구별 | `orgs/roadmap.html` |
| B12 | 조직 공통(프로젝트 미지정) 범위 | `notes/list.html`, `web/views/notes.py` |
| B13, F12 | 조직 제거 시 담당 유지·조건부 외부 제거 요청 | `orgs/teams.html` |
| B14, B16 | 합의문과 자동 설정 구별, 켜면/끄면 조건부 설명 | `orgs/governance.html`, `orgs/settings.py` |
| B15 | 오늘 빈 상태의 실행 가능한 안내 | `today/_head.html`, `today/_list.html` |
| B17, F17 | 외부 AI 작성 요청과 초안 준비/저장 구분 | `portfolio/index.html` |
| B18 | 검색 전 안내와 검색 결과 없음 분리 | `search.html` |
| B19 | 조직 KPI 범위, 진행·검토 분모, 과부하 사유 | `orgs/capacity.html` |
| B20, F13 | OpenAPI JSON·Markdown 형식, UTF-8·즉시 제출·256KB 본문 상한 | `projects/api.html`, `projects/docs.html`, `notes/list.html` |
| B21, F10 | 미완료 모두 취소·프로젝트 보관, 대상 개수 확인 | `projects/settings.html`, `web/views/projects.py` |
| C01, C05 | 목표일·목표일 미정·다음 행동 입력 목적 | 태스크/생성 폼 템플릿 |
| C02–C03, F19 | 최근 7일 완료·오늘 목록 추가/제외/복원·자동 추가 N일 이내 | `today/*`, `tasks/_row.html`, `web/views/today.py` |
| C04, F02 | 결정 내용과 이유, 본인 사용자 입력 확인 | `tasks/_decisions.html` |
| C06–C07, F22–F24 | 담당자·참조·체크리스트 접근성 이름과 저장/연결 대상 | `me.html`, `tasks/_refs.html`, `tasks/_checklist.html`, 설정 템플릿 |
| C08, F06 | 가져온 이슈 필터·내 태스크로 가져오기·PR 생성/병합 | `github/issues.html`, `projects/repo.html`, `projects/settings.html` |
| C09 | 시각/요일 의미 선택지(숫자 매핑 유지), 서버/조직 기본값, 0의 의미 | `orgs/settings.py:Spec.input_choices/display`, `settings/_setting_control.html` |
| C10 | /알림채널 안내·보유 기술 태그·막힘 관리자 알림 | `orgs/discord.html`, `orgs/capacity.html`, `orgs/settings.py` |
| C11 | 프로젝트의 화면 기본값 그룹(조직 권한 그룹은 유지) | `web/views/projects.py:project_settings` |
| C12 | 목록 선택·본문 편집 기본 안내, 키보드 사용법 별도 도움말 | `notes/list.html`, `projects/docs.html` |
| F01 | Discord 코드 발급 라벨 | `settings/profile.html` |
| F03–F05 | 추가만 하는 reconcile, 외부 반영 조건, 기존 팀 연결/새 팀 생성 구별·CSRF | `orgs/team_detail.html` |
| F07 | 저장한 내용만 다운로드 안내 | `portfolio/index.html` |
| F09 | focus 전체 태스크 상태 전환 라벨 | `today/_head.html` |
| F11 | 계정·팀·저장소·태스크 참조별 해제 범위 | 프로필·팀·저장소·태스크 템플릿 |
| F16 | 저장소 재확인 후 프로필로 이동 안내 | `orgs/github.html` |
| F18 | 패널 폭 넓히기/좁히기 | `tasks/_panel.html`, `app.js` |
| F20 | 초기화가 유지하는 담당자/정렬/묶음 범위 | `me.html` |
| F21 | 현재 소스의 compare URL을 기준으로 GitHub PR 생성 준비 안내 | `tasks/_git.html`, `web/views/tasks.py:pr_compare_url` |
| F25 | 입력값을 유지하는 토글은 입력 닫기, 실제 dialog 취소 유지 | 태스크/오늘 생성 폼 |
| F26 | 내보내는 모델과 제외 자료, 전체 백업 아님 안내 | `web/templates/ops.html`, `web/views/ops.py` |
| F27 | 문서 빈 상태의 중복 생성 버튼 제거 | `projects/docs.html` |

F21의 이전 보고서에는 PR 조회 링크라는 판단이 있었으나 현재 소스는 PR 미연결 시 compare URL로 이동한다.
따라서 “GitHub에서 PR 만들기”로 수정했다. 외부 페이지 이동만으로 PR이 생성되지는 않는다.
Markdown 업로드는 `.md/.markdown`이며 JSON은 OpenAPI 파일에만 해당한다.

## 검증

- `core/.venv/Scripts/python.exe -m pytest core -q`: **587 passed**.
  새 서버 회귀 18개는 잘못된 초대 발급 중단, 문서·회의록 실패 전달, 저장 JSON 오류/충돌,
  링크 입력 보존, 주말 제외 목표일 제안, 알림 숫자 매핑, 동기화 결과 분기를 검사한다.
- `node core/web/test_browser_feedback.cjs`: 성공/취소 복사, GET/POST/네트워크 오류,
  저장 오류/충돌, 로그인 HTML 200, 버전 없는 응답, 정상 204 버전 확인 PASS.
- `ruff check core`, `manage.py check`, `git diff --check`: 통과.
- 전체 테스트에서 기존 main의 GitHub 문제 두 건을 발견해 함께 해결했다.
  repository picker mock이 이슈 API에도 repositories 객체를 돌려주던 문제는 mock 응답을 분리했고,
  labeled/edited 이벤트가 닫힌 이슈를 다시 열던 실제 버그는 payload state를 우선하도록 수정했다.
- 독립 코드 검증에서 세션 만료 HTML 200의 거짓 저장 성공을 발견해 수정했다.
  작성한 에이전트에게 자체 결과 검증을 맡기지 않았다.
- Astra 실제 브라우저 검증: 16경로 × 1280/390px **32회 HTTP 200**, 조회 중 console/pageerror·전체 가로 넘침 0.
  문서 생성/제목·본문 저장/reload, 오류 400/409 사유·내용 보존, 세션 만료 시 회의록 복귀 차단,
  최초 목표일/연장 POST, 프로젝트별 제안 적용, 잘못된 초대 차단,
  포트폴리오 저장/다운로드/충돌 편집 보존 및 clipboard 실패·수동 취소를 확인했다.
  400/409/로그인 HTML과 clipboard 거절은 브라우저 mock으로 재현했다.
  증거는 `implementation-browser/`의 JSON·PNG에 보존하며 인증 세션 파일은 포함하지 않는다.

## 환경과 제한

- `pm-uiux-button-task41`, `http://127.0.0.1:8018`은 UI-UX core 전체를 읽기 전용 마운트한다.
  테스트 데이터와 Astra seed는 TEMP의 독립 SQLite 복제본에만 쓴다.
- 8017의 원본 디자인 미리보기 및 원본 워크트리는 유지했다.
- Discord 운영 설명은 사용자 설정 도움말에서 제외했다. 채널 목록 조회에는 봇 토큰이 필요하지만
  웹 프로세스에 봇 토큰을 두지 않는 기존 구조를 유지하며, 사용자 채널 지정은 봇의 `/알림채널`로 한다.
- 운영 배포·실제 GitHub/OAuth/Discord 외부 요청 성공은 검증하지 않았다.
  CI 경고는 staticfiles 미수집 및 기존 라이브러리 deprecation이며 테스트 실패는 없다.
- 사용자 승인에 따라 테스트한 변경을 main에 병합·푸시한다. TASK-41은 검토 대기 상태를 유지한다.
- 미추적 `%SystemDrive%/` Windows 캐시는 수정·삭제·커밋하지 않는다.
