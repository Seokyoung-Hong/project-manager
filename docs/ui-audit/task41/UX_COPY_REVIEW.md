# ProjectManager UI·UX 문구 전체 검토

2026-10-04 · 현재 작업 브랜치의 소스와 독립 Docker 미리보기 기준. 이번 작업은 검토이며 앱 코드·사용자 문구는 수정하지 않았다.

## 결론

표현을 다듬는 것보다 실패·성공·저장 상태를 정확히 알려 주는 작업이 먼저다. 실패를 숨기거나 실패 후 성공 문구를 내보내는 경로가 있다. 그다음 실제 범위와 다른 라벨, 저장 시점, 용어를 정리해야 한다.

P2는 잘못된 판단이나 행동을 유발할 수 있는 항목, P3는 이해·일관성 개선이다. 아래 문구는 수정 제안이며, 동작 변경이 필요한 경우를 따로 표시했다. 서버 오류는 소스 분기 확인 결과이고 실제 오류를 모두 재현한 결과는 아니다.

## 범위와 근거

- `core/web/templates`의 HTML 62개 전체: 본문, 버튼, 빈 상태, placeholder, title, aria-label, 확인 메시지. 목록은 아래 부록에 있다.
- `core/orgs/settings.py`의 설정 58개 라벨·도움말·선택지, 태스크·프로젝트·마일스톤·의사결정·토큰 모델의 표시 이름.
- 웹 뷰 21개, 폼 1개, 사용자 메시지 JS 2개(24파일·4,754줄): 메시지 후보 144줄. 앱별 서비스·공통 오류는 별도 보고서의 203개 ServiceError 색인을 기준으로 노출 경로를 대조했다. 모든 API/서비스 코드를 줄마다 감사한 범위는 아니다.
- 실제 화면: 기존 Astra가 오늘·태스크 상세를 직접 확인했고, 부모가 설정 및 나머지 화면 18개 경로의 AX 문구를 수집해 Astra에게 전달했다. 조직·프로젝트 설정은 접힌 섹션도 펼쳐 확인했다. 문서·회의록 편집 도움말도 별도로 확인했다.
- 브라우저 근거: 같은 폴더의 `copy-screen-*.txt`. 서버·JS 근거: `ux-copy-messages-review.md`. Astra 근거: `ux-copy-astra-review.md`.
- 원본 기준 경로: `C:/Users/tjrdu/Desktop/Coding/ai/project-manager/`. 아래 파일명은 이 경로에 대한 상대 경로이며 줄번호는 현재 소스 기준이다.

## A. 실패·성공 안내: 먼저 처리

| ID | 우선순위 | 문제와 제안 | 근거 |
|---|---|---|---|
| A01 | P2 | 문서·회의록 생성/업로드/삭제에서 ServiceError를 버리고 목록으로 돌아간다. 실패 원인을 표시하고 업로드 형식·크기·UTF-8 조건을 전달해야 한다. 문구 추가와 오류 전달 동작 수정이 함께 필요하다. | `core/web/views/docs.py:54`, `core/web/views/docs.py:102`, `core/web/views/notes.py:87`, `core/web/views/notes.py:147`; `core/projects/docs.py:91`, `core/notes/services.py:96` |
| A02 | P2 | 초대 만료 기간의 폼 검증 실패 시 7일로 조용히 대체해 링크를 발급한다. 권장: **만료 기간은 1~90일로 입력하세요. 초대 링크는 만들지 않았습니다.** 검증 실패 시 생성 중단이 먼저다. | `core/web/views/orgs.py:166`, `core/web/forms.py:33` |
| A03 | P2 | 모든 HTMX HTTP 오류를 저장 실패로 안내한다. 상세 조회 실패까지 저장 실패로 오해한다. 저장·조회·상태 변경에 맞는 메시지로 구분하고 공통 fallback은 **요청을 처리하지 못했습니다. 다시 시도하세요.** | `core/web/static/app.js:102`, `core/web/static/app.js:109`, `core/web/static/app.js:113` |
| A04 | P2 | 자동 저장 실패 시 응답의 구체 원인을 버리고 새로고침만 권한다. 길이 제한·권한·네트워크 오류별 원인과 해결을 표시해야 한다. 미저장 내용 보존 안내도 필요하다. | `core/web/static/notes.js:565`, `core/web/static/notes.js:578`, `core/web/static/notes.js:583`; `core/web/views/docs.py:91`, `core/web/views/notes.py:138` |
| A05 | P2 | 클립보드 실패 후 수동 복사 prompt를 취소해도 복사 성공을 표시한다. fallback 안내는 **아래 내용을 선택해 직접 복사하세요.** 성공 문구는 clipboard API 성공 분기에서만 표시한다. | `core/web/static/app.js:135`, `core/web/static/app.js:145` |
| A06 | P2 | 일부 저장소 이슈 동기화 실패에도 전체 성공처럼 읽히는 성공 메시지를 함께 표시한다. 권장: **일부 저장소만 확인했습니다. 열린 이슈 N건을 확인했고, F곳은 확인하지 못했습니다.** 전부 실패는 별도 실패 안내. | `core/web/views/github.py:323`, `core/github/services.py:833` |
| A07 | P3 | 링크 폼 오류를 일반 오류 한 줄로 치환해 제목/URL 중 무엇을 고칠지 알기 어렵다. 필드별 기존 검증 메시지를 해당 입력 아래에 보여 준다. | `core/web/views/projects.py:302`, `core/web/views/tasks.py:385`, `core/web/forms.py:111` |

## B. 실제 동작·범위와 맞지 않거나 중요한 설명이 빠진 문구

| ID | 우선순위 | 현재 문제 → 권장 방향 | 근거 |
|---|---|---|---|
| B01 | P2 | 초대의 로그인/가입 후 바로 참여한다는 안내는 실제 POST 참여 확인 단계와 다르다. **로그인하거나 가입한 뒤 이 조직에 참여할 수 있습니다.** 로그인된 참여 화면에는 조직 이름도 표시한다. | `core/web/templates/auth/join.html:7`, `core/web/templates/auth/join.html:23`; `core/web/views/auth.py:36` |
| B02 | P3 | OAuth 토큰이 아래 목록에 나타난다고 하지만 토큰 목록은 위쪽에 있다. **허용하면 API 토큰 목록에 자동으로 추가됩니다.** | `core/web/templates/settings/tokens.html:62`; 실제 `/settings/tokens` |
| B03 | P2 | 토큰 포함 URL의 인증 없음은 접근 인증 자체가 없다는 오해를 만든다. **클라이언트의 별도 인증 설정은 필요하지 않습니다. URL에 포함된 토큰으로 인증합니다.** | `core/web/templates/settings/tokens.html:75`, `core/web/templates/settings/tokens.html:80`; 실제 `/settings/tokens` |
| B04 | P2 | 읽기·쓰기 권한 설명이 태스크 생성·수정만 설명하지만 문서 등 다른 쓰기도 가능한 범위다. **허용된 조직 정책과 계정 권한 안에서 태스크·프로젝트·문서 등을 조회하고 변경할 수 있습니다.** 실제 허용 작업 목록을 도움말에서 설명한다. | `core/web/templates/oauth/authorize.html:11`, `core/web/templates/oauth/authorize.html:12`; `core/api/routers/docs.py:92`, `core/api/auth.py` |
| B05 | P2 | 토큰 용도 AI/사람은 단순 분류처럼 보이지만 `for_ai`는 AI 정책 적용에 영향을 준다. 발급 폼에 **AI 도구에는 AI용 토큰을 사용하세요. AI용 토큰에는 조직의 AI 정책이 적용됩니다.** | `core/web/templates/settings/tokens.html:42`; `core/accounts/models.py`의 `ApiToken.for_ai`와 `issue` |
| B06 | P2 | 기본 기한(영업일) 도움말이 생성 화면의 날짜 제안을 약속하지만 해당 설정 키의 소비가 현재 생성 폼/뷰에서 확인되지 않는다. 도움말만 바꿔 정상 기능처럼 보이게 하지 말고 날짜 제안 구현 여부를 정리해야 한다. | `core/orgs/settings.py:91`, `core/orgs/settings.py:98`; `core/web/views/projects.py:203`, `core/web/views/today.py:150` 및 앱 소스의 키 사용 검색 |
| B07 | P2 | 충돌 안내가 곧바로 새로고침을 권해 미저장 편집을 잃을 수 있다. **다른 사람이 먼저 수정해 저장하지 못했습니다. 작성 중인 내용을 복사한 뒤 새로고침하고 변경 내용을 확인하세요.** 자동 병합을 보장하는 문구는 쓰지 않는다. | `core/web/templates/projects/docs.html:38`, `core/web/templates/notes/list.html:82`; `core/web/static/notes.js:572` |
| B08 | P2 | 문서·회의록 삭제 확인은 대상과 되돌릴 수 없음이 부족하다. **이 문서를 삭제할까요? 본문과 태스크 연결이 삭제되며 되돌릴 수 없습니다.** 회의록도 같은 패턴. 태스크의 참고자료 연결 해제와 실제 문서 삭제를 구분한다. | `core/web/templates/projects/docs.html:61`, `core/web/templates/notes/list.html:106`; `core/projects/docs.py:102`, `core/notes/services.py:107` |
| B09 | P2 | 태스크 자동 저장 안내가 진행 메모 아래에만 있고 저장 시점을 설명하지 않는다. 공통 안내에 **입력 후 다른 칸으로 이동하면 자동 저장됩니다. 저장 완료 표시를 확인하세요.** 선택 항목은 즉시 저장됨을 구분. 문서 본문은 별도 자동 저장 규칙을 설명한다. | `core/web/templates/tasks/_panel.html:20`, `core/web/templates/tasks/_panel.html:88`, `core/web/templates/tasks/_panel.html:94`; `hx-trigger="change"` |
| B10 | P2 | 목표일이 없는 태스크의 목표일 정하기도 연장 사유/왜 미루나요를 표시한다. 최초 지정은 **목표일 지정 사유**, 연장은 **목표일 연장 사유**로 구분한다. | `core/web/templates/tasks/_panel.html:69`, `core/web/templates/tasks/_extend.html:4`; `core/web/views/tasks.py:98` |
| B11 | P2 | 프로젝트 의존성의 시작 프로젝트/의존 프로젝트/차단만으로 방향과 실제 효과를 알기 어렵다. 두 프로젝트 역할을 정의하고 **이 프로젝트가 다른 프로젝트에 의존합니다** 예시를 붙인다. `is_blocking`은 표시 데이터이므로 자동으로 착수를 막는다고 안내해서는 안 된다. | `core/web/templates/orgs/roadmap.html:35`, `core/web/templates/orgs/roadmap.html:52`, `core/web/templates/orgs/roadmap.html:58`, `core/web/templates/orgs/roadmap.html:69`; `core/projects/services.py:412` |
| B12 | P2 | 회의록의 팀 공통은 실제 팀별 범위가 아니다. 프로젝트를 지정하지 않은 조직 회의록이므로 **조직 공통(프로젝트 미지정)**으로 바꾼다. | `core/web/templates/notes/list.html:22`, `core/web/templates/notes/list.html:65`; `core/notes/models.py:6`, `core/web/views/notes.py:38` |
| B13 | P2 | 조직 멤버 제거 시 GitHub에서도 빠진다고 단정하지만 GitHub 연결/사용자 연결이 있을 때만 별도 요청한다. **연결된 GitHub 조직에서도 제거를 요청합니다. 처리 결과를 확인하세요.** 외부 연동 조건과 실패 결과를 구분한다. | `core/web/templates/orgs/teams.html:35`; `core/web/views/orgs.py:225` |
| B14 | P3 | 거버넌스 기본안과 시스템 강제 설정의 역할 구분이 약하다. **이 문서는 사람과 AI가 따를 합의입니다. 앱이 자동으로 적용하는 제한은 설정에서 확인하세요.** 기본안과 설정 수치가 다른 것은 그 자체로 버그로 판정하지 않는다. | `core/web/templates/orgs/governance.html:7`, `core/web/templates/orgs/governance.html:23`; `core/orgs/governance.py:3`; 실제 `/orgs/1/governance`, `/orgs/1/settings` |
| B15 | P3 | 오늘 빈 상태에서 아래 목록에서 담으라고 하지만 그 목록도 비어 있다. **오늘 할 일이 없습니다. 내 태스크에서 오늘 목록에 추가하거나 새 태스크를 만드세요.** | `core/web/templates/today/_head.html:36`, `core/web/templates/today/_list.html:32` |
| B16 | P2 | 꺼진 규칙의 도움말도 현재 강제되는 것처럼 단정한다. **켜면 완료 조건을 입력해야 태스크를 만들 수 있습니다**, **켜면 검토 대기를 거쳐야 완료할 수 있습니다**처럼 옵션 효과를 조건문으로 쓴다. | `core/orgs/settings.py:78`, `core/orgs/settings.py:133`, `core/orgs/settings.py:263`; Astra 조직 설정 전체 AX |
| B17 | P2 | 포트폴리오 소개는 초안을 직접 생성하는 것처럼 읽히지만 버튼은 AI 작성 요청을 만든다. **기록을 골라 AI에 전달할 포트폴리오 작성 요청을 만듭니다. AI가 작성한 내용을 붙여 넣어 비공개 초안으로 저장하세요.** 실제 노출 기록의 필터와 귀속 조건은 별도 도움말에 유지한다. | `core/web/templates/portfolio/index.html:9`, `core/web/templates/portfolio/index.html:98`, `core/web/templates/portfolio/index.html:104`; Astra `/portfolio` |
| B18 | P2 | 검색 전에도 검색 결과 없음과 필터 확대 안내가 나온다. 빈 입력은 **태스크 번호·제목·프로젝트 이름으로 검색하세요.** 입력 후 0건일 때만 결과 없음과 범위 확대 방법을 표시한다. 본문 검색은 현재 지원하지 않으므로 암시하지 않는다. | `core/web/templates/search.html:16`; `core/tasks/services.py:957`, `core/tasks/services.py:966`; Astra `/search` |
| B19 | P2 | 부하의 0/8은 개인 상한으로 보이지만 분모는 조직 내 최대 진행·검토 개수다. **진행·검토 N건 · 조직 내 최대 M건**으로 풀고 과부하 이유를 병기한다. 현재 기준은 진행+검토 4건 이상 또는 기한 초과 2건 이상이다. 팀 필터를 골라도 KPI는 조직 전체이므로 요약 범위도 명시한다. | `core/web/templates/orgs/capacity.html:29`; `core/reports/services.py:107`, `core/reports/services.py:110`; `core/web/views/roadmap.py:34`, `core/web/views/roadmap.py:49`; Astra `/orgs/1/capacity` |
| B20 | P3 | API 문서의 파일 버튼은 업로드 대상을 알기 어렵다. **OpenAPI JSON 파일 올리기**, **OpenAPI 문서 URL**로 명시하고 지원 형식 JSON·UTF-8 조건을 안내한다. 지원하지 않는 YAML을 약속하지 않는다. | `core/web/templates/projects/api.html:22`, `core/web/templates/projects/api.html:24`; `core/projects/services.py:496` |
| B21 | P2 | 미완료까지 취소하고 보관은 취소 대상이 생략되어 있다. **미완료 태스크를 모두 취소하고 프로젝트 보관**. 확인 단계에서 대상 개수를 보여 주고 기존 취소·보관 결과 설명은 유지한다. | `core/web/templates/projects/settings.html:85`, `core/web/templates/projects/settings.html:87`; Astra 프로젝트 설정 전체 AX |

## C. 용어·버튼·도움말의 일관성

| ID | 우선순위 | 권장 방향 | 근거 |
|---|---|---|---|
| C01 | P3 | 같은 `due_date`의 목표일/목표 기한/기한/마감 혼용을 정리한다. 입력 라벨은 **목표일**, 미정 상태는 **목표일 미정**, 기한 초과·오늘 마감은 상태 설명으로 사용한다. 마일스톤 목표일과도 맞춘다. | `core/tasks/models.py:47`, `core/web/templates/projects/_task_form.html:8`, `core/web/templates/today/_quick.html:8`, `core/web/templates/tasks/_panel.html:65` |
| C02 | P3 | **7일 완료 → 최근 7일 완료**, **오늘 제외 → 오늘 목록에서 빼기**, **오늘 추가 → 오늘 목록에 추가**. 삭제·취소와 구별되는 목록 작업임을 명시한다. | `core/web/templates/today/_head.html:8`, `core/web/templates/tasks/_row.html:39`, `core/web/templates/tasks/_row.html:43`; Astra 실제 오늘 화면 |
| C03 | P3 | **마감 자동 담기 → 목표일 기준 자동 추가**, 선택값은 **N일 이내**. 직접 담기/자동 담김/추가/복원도 목록 작업 용어로 통일한다. | `core/web/templates/today/_list.html:17`, `core/web/templates/today/_list.html:29`; Astra 실제 오늘 화면 |
| C04 | P3 | **의사의 요지 → 결정 내용과 이유**, **AI 세션에서 MCP로 기록 → AI와 논의한 결정 내용과 이유를 기록하면 여기에 표시됩니다.** 기술적 기록 방법은 펼치는 도움말에 둔다. AI 판단과 사용자 결정의 구분은 유지한다. | `core/web/templates/tasks/_decisions.html:5`, `core/web/templates/tasks/_decisions.html:85`, `core/web/templates/portfolio/index.html:104`; Astra 실제 태스크 상세 |
| C05 | P3 | 다음 행동의 멈출 때 한 줄로 고쳐 씁니다는 입력 목적을 설명하지 않는다. **다음에 할 일을 한 문장으로 적으세요.** 사유 입력의 왜 미루나요는 **목표일을 변경하는 이유를 적으세요.** | `core/web/templates/tasks/_panel.html:88`, `core/web/templates/tasks/_extend.html:4` |
| C06 | P3 | 내 태스크의 담당 범위 선택 aria-label은 팀원이 아니라 **담당자**, 태스크별 삭제/연결 해제 아이콘은 대상을 포함한 접근성 이름을 제공한다. | `core/web/templates/me.html:6`, `core/web/templates/tasks/_refs.html:7`, `core/web/templates/tasks/_refs.html:12`, `core/web/templates/tasks/_checklist.html:13` |
| C07 | P3 | 단독 추가/저장/복사/삭제는 반복 컨트롤에서 대상을 명시한다. 예: **문서 연결**, **회의록 연결**, **문서 저장**, **주소 복사**, **설정 명령 복사**. 모든 버튼을 무조건 길게 만들지는 않는다. | `core/web/templates/tasks/_refs.html:25`, `core/web/templates/tasks/_refs.html:33`, `core/web/templates/settings/tokens.html:61`, `core/web/templates/settings/tokens.html:67` |
| C08 | P3 | 이슈의 안 가져온 것/가져온 것/전부는 **태스크로 가져오지 않음 / 태스크로 가져옴 / 전체**. PR 오픈/머지는 **PR 생성 / PR 병합**으로 맞춘다. | `core/web/templates/github/issues.html:16`, `core/web/templates/github/issues.html:18`, `core/web/templates/projects/settings.html:45`, `core/web/templates/projects/repo.html:56` |
| C09 | P3 | 설정의 N, -1, .env, SEND_HOUR, 0=월요일는 사용자가 원하는 상태로 풀어 설명한다. -1은 **조직 설정 따름/서버 기본값**, 0은 **제한 없음/사용 안 함**처럼 항목별 의미로 표시. 숫자/옵션 매핑을 바꾸려면 폼 처리도 함께 점검해야 한다. | `core/orgs/settings.py:500`, `core/orgs/settings.py:539`, `core/orgs/settings.py:551`, `core/orgs/settings.py:636` |
| C10 | P3 | Discord 연결은 채널에서 **/알림채널**을 실행한다는 방법에 집중한다. 웹 프로세스·봇 토큰 설명은 사용자 설정 판단에 필요하지 않으므로 운영 문서로 옮긴다. 부하의 스킬 태그는 **보유 기술 태그**, 막힘 에스컬레이션은 **막힘 관리자 알림**처럼 이해하기 쉬운 보조 설명을 제공한다. | `core/web/templates/orgs/discord.html:30`, `core/web/templates/orgs/discord.html:32`, `core/web/templates/orgs/capacity.html:42`, `core/orgs/settings.py:562` |
| C11 | P3 | 프로젝트 설정에서 유일한 항목이 프로젝트 첫 화면인 프로젝트 권한 섹션은 **화면 기본값**으로 구분한다. 조직 설정의 실제 프로젝트 권한 항목들은 기존 이름을 유지한다. | `core/orgs/settings.py:272`, `core/orgs/settings.py:693`; 실제 `/projects/1/settings` 전체 펼친 AX |
| C12 | P3 | 문서/회의록에서 왼쪽에서 고르세요, Enter로 시작·Esc로 나가기 등은 모바일·키보드 사용을 구분한다. **목록에서 회의록을 선택하세요**, **본문 편집을 누르세요**를 기본 안내로 사용하고 단축키는 별도 도움말로 둔다. | `core/web/templates/notes/list.html:111`, `core/web/templates/notes/list.html:89`, `core/web/templates/projects/docs.html:45` |

총 40개 항목이다. 하나의 항목이 여러 파일에 걸친 반복 문구를 포함하므로 수정할 문자열 개수와 같지 않다. Astra의 중요도와 서버 검토 갈래의 중요도는 사용자 영향·재현 범위를 고려해 부모가 위 기준으로 통합했다.

## 유지할 표현과 기본 규칙

- 상태 코드·의미를 바꾸지 않는다. 시작 전/진행 중/일시정지/막힘/검토 대기/완료/취소의 역할 차이는 보존한다.
- 태스크, 프로젝트, 조직, 팀, 회의록, 문서는 서로 다른 개체이므로 용어를 편의상 합치지 않는다.
- 본문·안내는 `-합니다/-하세요`, 버튼은 대상+행동, 상태는 저장 중/저장 완료/저장 실패로 맞춘다.
- 오류는 무엇이 실패했는지와 다음 행동을 알려 주되 원인을 확인하지 못하면 추정하지 않는다. 서버 상태코드는 보조 상세로 둔다.
- 삭제, 연결 해제, 목록에서 빼기, 보관, 취소는 서로 다른 결과이므로 문구와 확인 메시지를 구분한다.
- 포트폴리오의 비공개 초안과 AI 판단/사용자 기록 구분, 업로드의 파일·이미지 미보관 설명, 프로젝트 보관의 데이터 유지 설명은 유효하므로 유지한다.

## 확인 불가와 검증 한계

- GitHub·Discord가 꺼진 독립 Docker 환경에서 외부 연동 성공/실패 상태는 실사용으로 재현하지 않았다. 해당 템플릿과 서비스는 소스로 검토했다.
- OAuth 승인과 토큰 발급/폐기, 초대 발급, 삭제를 실행하지 않았다. 메시지와 분기는 소스 검토다.
- 오류·충돌·권한 거절·만료·복사 fallback 전부를 실제 브라우저로 발생시키지 않았다. 따라서 이 문서는 문구 검토이며 동작 수정의 회귀 검증 결과가 아니다.
- 현재 클라이언트의 실제 메뉴명·설정 명령은 외부 제품에서 재검증하지 않았다. 클라이언트 설치 안내를 수정할 때 공식 문서로 별도 확인해야 한다.
- 실제 사용자 데이터, 운영 배포본, Discord 봇의 DM/알림 문구 전체는 이번 웹 UI 검토 범위 밖이다.

## 부록: 템플릿 조사 목록

공통: `_fields`, `base`, `dialog_page`, `me`, `ops`, `search`, `today`.

인증: `auth/join`, `auth/login`, `auth/signup`, `oauth/authorize`, `oauth/error`.

이슈·회의록: `github/issues`, `notes/list`.

조직: `orgs/_milestone_dialog`, `_pending_requests`, `_tabs`, `_team_dialog`, `capacity`, `change_request`, `detail`, `discord`, `github`, `governance`, `list`, `new`, `roadmap`, `settings`, `team_detail`, `teams`.

프로젝트: `projects/_board`, `_dialog`, `_endpoints`, `_tabs`, `_task_form`, `api`, `detail`, `docs`, `empty`, `repo`, `settings`.

설정: `settings/_setting_control`, `_setting_row`, `_tabs`, `preferences`, `profile`, `tokens`.

태스크: `tasks/_checklist`, `_decisions`, `_extend`, `_git`, `_history`, `_panel`, `_refs`, `_row`, `_stop`, `detail`.

오늘·포트폴리오: `today/_head`, `_list`, `_quick`, `_schedule`, `portfolio/index`. 모두 `.html` 파일이다.
