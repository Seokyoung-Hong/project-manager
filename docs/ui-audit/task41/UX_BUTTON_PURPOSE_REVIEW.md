# UI-UX 버튼 목적성 검토

2026-10-04 · `Seokyoung-Hong/UI-UX` · HEAD `134ae90320d01dcb64131a0dc33df78cc44a8e7a`

## 결과와 적용 범위

**버튼 목적성 검토 단계를 완료했다. 앱 문구·동작 수정은 아직 하지 않았다.**
현재 UI-UX의 템플릿 62개 전체에서 컨트롤 위치 304곳과 URL 이름 118개를 목록화하고,
사용자 목적 → 예상 결과 → 실제 route/POST/HTMX/JS 결과 → 권장 문구를 대조했다.
웹페이지 판단은 GPT-6 Astra가 UI-UX 코드로 실행한 새 Docker 미리보기에서 담당했다.
외부 연동과 샘플 데이터가 없는 분기는 소스 판정 또는 미확정 후보로 남긴다.

근거와 개별 판정은 [전체 인벤토리](UX_BUTTON_PURPOSE_INVENTORY.md)와
[원시 속성·라우트 JSON](button-purpose-inventory.json)에 있다.
기존 [전체 문구 검토 40건](UX_COPY_REVIEW.md)은 원본 저장소의 기록이다.
아래 소스 줄번호와 버튼 ID는 이번 UI-UX 조사 기준이며, 기존 보고서의 줄번호를 재사용하지 않았다.

| 조사 단위 | 수 | 의미 |
| --- | ---: | --- |
| HTML 템플릿 | 62 | 공통 셸·부분 템플릿·인증·OAuth·운영 화면 포함 |
| `<a>` / `<button>` | 105 / 146 | 반복 렌더링 개수 대신 소스 위치를 센다 |
| `<summary>` | 19 | 펼치기와 데이터 변경을 구분한다 |
| 자동 제출 입력·선택·textarea / 파일 선택 label | 31 / 3 | HTMX 또는 inline change가 있는 입력도 포함한다 |
| 합계 | 304 | 조건부 문구·권한 분기·반복 항목은 같은 위치에 병기한다 |
| 사용된 Django URL 이름 | 118 | 클릭·제출에 연결된 이름; API 전체 라우트 수가 아니다 |

표에 없는 일반 폼 입력은 제출 버튼의 문맥으로 확인했다. JS로 만들어지는 편집 메뉴,
문서 메타 자동 저장, 역할이 버튼인 태스크 행은 아래 별도 표에 포함했다.
데이터마다 생성되는 링크·제목을 전수 열어 본 결과로 해석하지 않는다.

## 원본 저장소와 UI-UX의 실제 차이

이번 비교에서 UI-UX HEAD는 `134ae90320d01dcb64131a0dc33df78cc44a8e7a`, 원본은
`2572bf5747fa5aea18bab3487e9b9c14605b62a0`이다. **두 HEAD의 커밋 내용이 18개 파일에서 다르고,
원본에는 별도의 미커밋 디자인 변경 10개가 있다.** 10개 모두 현재 UI-UX 파일과 다르다.
HEAD 간 차이는 조직 변경 요청·모델·마이그레이션·서비스·API·MCP 등에도 있어,
원본 화면 기록을 UI-UX의 현재 동작으로 그대로 인용할 수 없다.
이번 인벤토리와 서버는 UI-UX 소스로 대조했다.

| 파일·범위 | UI-UX 현재 상태와 원본의 차이 | 검토 영향 |
| --- | --- | --- |
| `core/web/static/app.css:2` | UI-UX 밝은 배경 `#EEF3F5`, primary `#1F6F82`; 원본은 `#F5F7F8`, `#176B78`과 새 간격·반경·목록·모바일 스타일 | 복사한 `DESIGN.md`가 UI-UX 구현 상태를 뜻하지 않는다. 8018은 UI-UX 화면이다. |
| `core/web/templates/projects/docs.html:14` | UI-UX의 상단 새 문서 버튼은 항상 존재. 원본은 `{% if docs %}`로 문서가 있을 때만 표시 | UI-UX 빈 상태에는 하단 첫 문서 만들기와 생성 액션이 겹친다. 아래 F27로 별도 기록. |
| `core/web/templates/orgs/capacity.html:14`, `:31` | UI-UX는 가로 스크롤 안내와 기본 텍스트; 원본은 안내 제거·기한 초과 강조 | 원본의 위험 강조·KPI 화면 합격을 UI-UX로 승계하지 않는다. |
| `core/web/templates/orgs/detail.html:5`, `projects/detail.html:23` | UI-UX KPI aria-label에 가로 스크롤 안내; 원본은 제거 | 현재 접근성 문구는 이번 인벤토리·실행 근거를 따른다. |
| `core/web/templates/orgs/roadmap.html:11` | UI-UX 오늘 선은 aria-hidden; 원본은 오늘 텍스트 라벨 추가 | 원본의 오늘 라벨 개선은 미적용이다. |
| `core/web/templates/settings/_tabs.html:3`, `tasks/_panel.html:64`, `today/_head.html:15` | 원본에만 `settings-tabs`, `task-due-row`, `today-focus` 스타일 훅 추가 | 설정 폭·목표일 행·집중 영역의 원본 스타일을 UI-UX에 적용했다고 보고하지 않는다. |
| `core/web/tests.py` | 원본은 KPI aria 문구에 맞게 2개 테스트 수정 | 이전 원본 145개 통과를 이번 UI-UX 테스트 실행 결과로 재사용하지 않는다. |
| 커밋 차이 18파일 | `core/orgs/requests.py`, 모델·0006 마이그레이션, `core/web/views/orgs.py`, `orgs/change_request.html`, 조직·프로젝트 API 및 MCP 등이 다름 | 이 보고서는 현재 UI-UX의 route/뷰에 한정한다. 코드 이전은 디자인 diff뿐 아니라 커밋 차이도 대조해야 한다. |

전체 경로·양쪽 해시·현재 디자인 diff는 [워크트리 비교 근거](button-purpose-worktree-diff.json)에 저장했다.
원본 코드 파일은 수정·이전하지 않았다.

## 판단 기준

- 짧은 탭·필터·제목 링크는 주변 문맥이 충분하면 유지한다.
- 입력 폼 열기, 실제 생성·저장, 외부 서비스 시작, 후속 단계 완료를 구분한다.
- 삭제·연결 해제·오늘 목록 제외·태스크 취소·프로젝트 보관은 서로 다른 결과다.
- 권장 문구는 후보다. 실제 동작은 소스 근거로 확정할 수 있어도 최종 화면 배치는 구현 후 다시 확인한다.
- P2는 상태·범위·부작용을 오해할 위험, P3는 이해·검색·일관성 개선이다.
- 실패를 성공처럼 보이게 하는 문제는 문구만으로 해결하지 않는다.

`design:ux-copy`의 명확성·간결성·일관성·실제 결과 기준을 적용했다.
태스크/문서와 조직/외부 연결은 별도 에이전트가 소스를 검토했고, 부모가 근거와 최종 표를 통합했다.

## 우선 수정할 목적·결과 불일치

| ID·우선순위 | 현재 문구·사용자 목적 | 예상과 실제 결과의 차이 | 권장 문구·필요한 보조 안내 | 근거·판정 |
| --- | --- | --- | --- | --- |
| F01 · P2 · B214 | Discord 연결 · 개인 계정 연결 | 첫 POST는 연결 코드 발급뿐이며 실제 연결은 봇 DM 이후다. 현재 실화면에서 첫 클릭의 결과가 드러나지 않는다. | **Discord 연결 코드 받기**. 다음 단계에서 DM 방법·코드 만료 안내. | `core/web/views/settings.py:34`; `core/web/templates/settings/profile.html:25`; Astra `button-purpose-browser/390--settings-profile.png`. 동작 확정, 표현 후보. |
| F02 · P2 · B228 | 확인 / 웹에서 확인 · 수집된 결정을 검토 | 읽기나 AI 작업 승인이 아니라, 본인에게 귀속된 사용자 입력의 확인 상태를 저장한다. | **내 의사결정으로 확인**. AI 판단 승인으로 표현하지 않는다. | `core/web/templates/tasks/_decisions.html:47`; `core/web/views/decisions.py:56`; `core/tasks/decision_services.py:351`. 소스 확정, POST 미실행. |
| F03 · P2 · B118 | GitHub에 반영 · PM 팀과 외부 팀 일치 기대 | 활성 PM 멤버 추가만 요청하며 GitHub에만 있는 멤버는 제거하지 않는다. | **GitHub에 멤버 추가**. “GitHub에만 있는 멤버는 제거하지 않습니다.” | `core/web/templates/orgs/team_detail.html:24`; `core/github/writes.py:107`. Astra 소스 보조 후보, 외부 화면 미검증. |
| F04 · P2 · B122–B123 | 제거 / 추가 · PM 팀 구성 변경 | 연결 조건이 맞으면 외부 GitHub 팀에도 추가·제거를 요청한다. PM 변경만으로 예상하면 부작용을 놓친다. | **팀에서 제거 / 팀 멤버 추가**. 조건부 외부 반영과 처리 결과 안내. | `core/web/views/teams.py:131`, `:149`, `:161`; `core/web/templates/orgs/team_detail.html:48`, `:58`. 소스 확정, 외부 요청 미실행. |
| F05 · P2 · B120–B121 | 연결 / GitHub에 새 팀 만들기 · 외부 팀 준비 | 기존 팀 연결은 연결 레코드만 만들며 멤버 동기화는 별도다. 새 팀 생성은 외부 생성 후 PM 연결까지 한다. | **선택한 GitHub 팀 연결 / GitHub 팀 만들고 연결**. 멤버 반영 별도 안내. | `core/web/views/teams.py:181`, `:198`; `core/web/templates/orgs/team_detail.html:33`, `:35`. 소스 확정. |
| F06 · P2 · B191 | 태스크로 가져오기 · 이슈 담당 업무 등록 | GitHub 담당자를 그대로 쓰지 않고 클릭한 사용자에게 담당 태스크를 만든다. | **내 태스크로 가져오기**. 다른 이슈 화면의 동일 동작 문구와 맞춘다. | `core/web/templates/projects/repo.html:73`; `core/github/services.py:781`; `core/web/templates/github/issues.html:55`. 소스 확정, 생성 미실행. |
| F07 · P2 · B140 | Markdown 다운로드 · 편집 결과 확보 | 편집 폼의 미저장 본문은 제출하지 않고 서버에 저장된 초안만 GET으로 내보낸다. | **Markdown 다운로드** 유지 + “저장한 내용만 내려받습니다. 변경 후 먼저 저장하세요.” 후보. 이름을 늘리는 대안은 **저장된 초안 다운로드**. | `core/web/templates/portfolio/index.html:28`, `:36`; `core/web/views/portfolio.py:287`. Astra 보조 판단; 샘플 초안이 없어 실화면 미검증. |
| F08 · P2 · B232·B255 | 목표일 정하기 / 저장 · 최초 목표일 지정 | 같은 폼에서 최초 지정에도 “연장 사유 / 왜 미루나요?”가 나타난다. | 최초는 **목표일 저장 / 지정 사유**, 기존 날짜가 있으면 **목표일 연장 / 연장 사유**. 폼을 여는 버튼과 저장 버튼을 구분. | `core/web/templates/tasks/_panel.html:68`; `core/web/templates/tasks/_extend.html:3`; `core/web/views/tasks.py:264`. 소스 확정. |
| F09 · P2 · B286 | 완료로 표시 · 다음 행동을 마침 | focus 태스크 전체를 완료로 전환한다. 다음 행동 한 줄만 완료하는 것과 다르다. 서버 규칙에 따라 실패할 수도 있다. | **태스크 완료로 표시 / 태스크 진행 시작** 후보. 기존 상태 규칙은 유지. | `core/web/templates/today/_head.html:25`; `core/web/views/tasks.py:207`. 화면 노출 확인, 상태 POST 미실행. |
| F10 · P2 · B203 | 미완료까지 취소하고 보관 · 프로젝트 종료 | 모든 미완료 태스크의 취소와 프로젝트 보관을 함께 수행한다. | **미완료 태스크를 취소하고 프로젝트 보관**. 확인에 프로젝트·대상 개수·데이터 유지 안내. | `core/web/templates/projects/settings.html:87`; `core/web/views/projects.py:252`. 소스 확정. |
| F11 · P2 · B119·B187·B213·B215·B244 | 연결 해제 · 연동 중단 | 개인 계정, 프로젝트 저장소, 팀 연결, 태스크 참조 해제의 범위가 다르다. 태스크 전체 해제는 계정·저장소 해제가 아니다. | 대상에 따라 **GitHub 계정 / 저장소 / GitHub 팀 / Discord 계정 연결 해제**, **이 태스크의 GitHub 연결 모두 해제**. 외부 객체 유지 범위 안내. | `core/web/views/settings.py:42`; `core/web/views/github.py:154`, `:229`, `:485`; `core/web/views/teams.py:221`. 소스 확정. |
| F12 · P2 · B127 | 제거 · 조직 구성원 제외 | 태스크 담당자는 유지되며, 연결 조건이 맞으면 GitHub 조직에도 제거를 요청한다. 외부 처리 성공을 보장하지 못한다. | **조직에서 제거**. 태스크 담당 유지·조건부 GitHub 요청을 확인 메시지에 명시. | `core/web/templates/orgs/teams.html:35`; `core/web/views/orgs.py:213`. 소스 확정. |
| F13 · P2 · B161–B162·B050–B051·B174–B175 | 파일 / .md 올리기 · 가져올 파일 선택 | 선택 직후 별도 확인 없이 제출·등록된다. API는 JSON을 읽어 기존 정의를 저장한다. | **OpenAPI JSON 파일 올리기 / Markdown 문서 올리기 / Markdown 회의록 올리기**. “파일을 선택하면 바로 등록합니다.” | `core/web/templates/projects/api.html:23`; `core/web/views/projects.py:323`; `core/web/templates/projects/docs.html:11`; `core/web/templates/notes/list.html:11`. 소스 확정; 업로드 미실행. |
| F14 · P2 · B129·B144·B221–B222·B278 | 복사 · 전달할 내용을 확보 | 공통 복사 fallback은 취소 후에도 성공 안내 가능. 포트폴리오는 성공·실패 안내와 fallback 자체가 없다. | **초대 링크 / 서버 주소 / 설정 명령 / 태스크 링크 / 프롬프트 복사**. 성공 분기와 수동 복사 상태를 구분하는 동작 수정 필요. | `core/web/static/app.js:131`; `core/web/templates/portfolio/index.html:103`; `core/web/templates/settings/tokens.html:61`, `:67`. 소스 확정, 실패 미재현. |
| F15 · P2 · B001 | 가입하고 참여하기 · 조직 가입 | 가입 뒤 초대 참여 확인 POST가 따로 필요하다. 첫 클릭으로 참여 완료되지 않는다. | **계정 만들기** 또는 **가입 후 참여하기** + “가입 후 조직 참여를 확인하세요.” | `core/web/templates/auth/join.html:9`; `core/web/views/auth.py:15`, `:29`. 소스 확정, 가입 미실행. |

## 문맥·일관성 개선 후보

| ID·우선순위 | 현재 문구·목적 | 실제 결과 | 권장 방향 | 근거 |
| --- | --- | --- | --- | --- |
| F16 · P3 · B098·B216 | 다시 확인 · 접근 가능한 저장소 갱신 | 개인 저장소 캐시 갱신 후 프로필 이동. 조직 화면에서도 같은 목적지다. | **접근 가능한 저장소 다시 확인**. 조직 화면의 복귀 동작은 구현 시 별도 결정. | `core/web/views/github.py:139`; `core/web/templates/orgs/github.html:25` |
| F17 · P3 · B137·B139 | 새 초안 만들기 / 저장 · 포트폴리오 준비 | 앞 버튼은 GET 출처 선택; 뒤 버튼은 기존 초안 POST 저장. | **새 초안 준비하기 / 초안 저장**. **선택한 출처로 AI 프롬프트 만들기**는 Astra 판단에 따라 유지. | `core/web/templates/portfolio/index.html:11`, `:35`, `:98`; `core/web/views/portfolio.py:157`, `:189` |
| F18 · P3 · B247 | 크게 보기 / 작게 보기 · 상세 읽기 공간 확보 | 글자 크기 대신 패널 폭 변경. | **패널 넓히기 / 패널 줄이기** 후보. | `core/web/static/app.js:188`; `core/web/templates/tasks/_panel.html:11` |
| F19 · P3 · B275–B277·B295·B297 | 오늘 제외 / 추가 / 복원 / 추가 · 오늘 계획 관리 | 목록 제외·기존 태스크 등록·제외 항목 복원·새 태스크 생성은 다른 결과. | **오늘 목록에서 빼기 / 오늘 목록에 추가 / 오늘 목록에 복원 / 태스크 만들고 오늘에 추가**. | `core/web/views/today.py:176`, `:200`, `:208`, `:216`; `core/web/templates/tasks/_row.html:39` |
| F20 · P3 · B048 | 필터 지우기 · 선택 조건 초기화 | 담당자·묶음·정렬은 유지하고 나머지 필터만 제거. | **추가 필터 지우기** 또는 유지되는 조건을 보조 안내. | `core/web/templates/me.html:35`; `core/web/views/me.py:15` |
| F21 · P3 · B242 | PR 열기 · 연결된 PR 읽기 | 외부 PR 페이지를 여는 링크이며 PR 생성·닫힌 PR 재개가 아니다. | **GitHub에서 PR 보기**. | `core/web/templates/tasks/_git.html:59` |
| F22 · P3 · B193–B194·B270–B271 | 연결 · 기존 자료를 업무에 붙이기 | 이벤트 선택창 열기와 연결 POST, 문서와 회의록 연결을 구분. | **연결할 태스크 선택 → 태스크에 이벤트 연결**, **문서 연결 / 회의록 연결**. | `core/web/templates/projects/repo.html:89`, `:96`; `core/web/views/github.py:353`; `core/web/templates/tasks/_refs.html:25`, `:33` |
| F23 · P3 · B212·B126·B102 | 저장 · 표시 이름/기술/조직 합의 기록 | 프로필은 표시 이름만, 각각 별도 데이터만 저장. | **표시 이름 저장 / 기술 태그 저장 / 거버넌스 저장**. | `core/web/views/settings.py:16`; `core/web/views/orgs.py:146`, `:235` |
| F24 · P3 · B224–B226·B265·B267 | ↑ / ↓ / ✕ · 순서/삭제/참조 해제 | 반복 아이콘은 대상과 결과를 읽기 어렵다. 참조 해제는 문서 삭제가 아니다. | 대상명을 포함한 **체크 항목 위로·아래로·삭제**, **문서·회의록 연결 해제** aria-label. | `core/web/templates/tasks/_checklist.html:11`; `core/web/templates/tasks/_refs.html:7`, `:12` |
| F25 · P3 · B159·B298 | 취소 · 입력 작업 중단 | JS는 폼을 숨길 뿐 기존 입력을 초기화하지 않는다. | **입력 닫기** 후보. 다이얼로그의 제출 전 취소와 구분. | `core/web/static/app.js:213`; `core/web/templates/projects/_task_form.html:15`; `core/web/templates/today/_quick.html:13` |
| F26 · P3 · B066 | JSON 내보내기 · 운영 자료 확보 | 지정 모델만 포함하며 문서·회의록 등은 빠진다. 전체 백업으로 보장할 수 없다. | **운영 데이터 JSON 내보내기** + 포함 범위 안내. | `core/web/views/ops.py:26`; `core/web/templates/ops.html:5` |
| F27 · P3 · B176·B182 | 새 문서 / 첫 문서 만들기 · 문서 작성 시작 | 현재 UI-UX는 빈 상태에서 동일 doc_new POST가 두 곳에 나타난다. 원본의 중복 제거 변경은 미적용이다. | 빈 상태에서는 **첫 문서 만들기** 하나, 문서가 있으면 목록의 **새 문서** 유지 후보. | `core/web/templates/projects/docs.html:14`, `:68`; `button-purpose-worktree-diff.json`. 소스 확정, 이번 빈 상태 실화면 제외. |

27개 묶음은 304개 컨트롤의 모든 변경 개수와 같지 않다. 전체 행의 유지 판단과 후보는 인벤토리에 있다.
이 보고서는 문자열 교체 목록이 아니라 동작·문맥을 함께 개선하기 위한 검토 결과다.

## 유지할 표현과 JS 추가 컨트롤

Astra가 실제 클릭으로 확인한 **진행 메모 열기**, **자세히 보기**, **프로젝트별**, **보드**, **쓰는 법**은 유지한다.
진행 메모는 메모 textarea로 스크롤·포커스하고, 자세히 보기는 상세 패널을 연다.
상태 코드의 시작 전·진행 중·일시정지·막힘·검토 대기·완료·취소 의미는 바꾸지 않는다.
근거: [Astra 클릭 기록](button-purpose-browser/actions.json), [포커스·선택자 보정](button-purpose-browser/supplement.json),
[모바일 회의록 도움말](button-purpose-browser/notes-supplement.json).

| 추가 컨트롤 | 사용자 목적 → 실제 결과 | 권장 판단·근거 |
| --- | --- | --- |
| 슬래시 메뉴 제목 1·2·3 | 제목 블록 삽입 → `# ` / `## ` / `### ` 문법 삽입 | 유지. `core/web/static/notes.js:90`, `:91`, `:92` |
| 글머리 목록 / 번호 목록 | 목록 삽입 → `- ` / `1. ` 삽입 | 유지. `core/web/static/notes.js:93`, `:94` |
| 할 일 | 본문 체크 항목 삽입 → `- [ ] ` 삽입; 앱 태스크 생성 아님 | **체크 목록** 후보. `core/web/static/notes.js:95` |
| 인용 / 구분선 / 코드 블록 | 서식 블록 삽입 → 인용 문법 / 구분선 / 코드 울타리 삽입 | 유지. `core/web/static/notes.js:96`, `:97`, `:98` |
| 이미지 / 영상 | 자료 넣기 → URL을 채울 Markdown 틀 삽입; 파일 업로드 아님 | **이미지 주소 / 영상 주소 넣기** 후보; 지원 주소만 임베드. `core/web/static/notes.js:99`, `:100`, `:40` |
| 링크 | 관련 주소 추가 → `[]()` 틀 삽입 | 유지 + 주소 입력 안내. `core/web/static/notes.js:101`, `:378` |
| 본문 링크 / 영상 재생 | 관련 자료 열기·재생 → 허용 URL 이동/임베드 재생; 편집 클릭과 분리 | 데이터별 링크 대상은 미검증. `core/web/static/notes.js:14`, `:54`, `:70` |
| 본문 체크박스 / 줄 클릭 | 본문 완료 표시·편집 → Markdown 변경 후 자동 저장; readonly 문서는 편집 안함 | 태스크 상태 변경과 구분. `core/web/static/notes.js:143`, `:276`, `:454` |
| 문서 제목 자동 저장 | 문서 이름 변경 → change를 저장 큐에 넣고 doc_save POST | 제목 라벨 유지 + 저장 상태 안내. `core/web/templates/projects/docs.html:30`; `core/web/static/notes.js:663` |
| 회의록 제목·프로젝트·회의 일시·태그 자동 저장 | 메타 변경 → change를 저장 큐에 넣고 note_save POST | **조직 공통(프로젝트 미지정)** 범위 정정 별도. `core/web/templates/notes/list.html:60`, `:64`, `:75`, `:79`; `core/web/static/notes.js:663` |
| 역할이 버튼인 태스크 행 | 태스크 상세 확인 → 클릭·Enter·Space로 GET 패널 | 기존 “제목 상세 보기” 접근성 이름 유지. `core/web/templates/tasks/_row.html:3`; `core/web/static/app.js:114` |
| 칸반 카드 드래그 | 상태 열로 옮기기 → 상태 POST; 막힘은 사유 패널 먼저 | 단순 위치 정렬이 아닌 상태 전환임을 안내. `core/web/templates/tasks/_row.html:5`; `core/web/static/app.js:280` |

문서·회의록 HTML의 **저장**은 JS 초기화 후 숨겨지는 fallback 버튼이다.
본문은 입력 후 800ms 저장 큐에 들어가며, 회의록 목록 복귀는 미저장 내용 flush 성공을 기다린다.
태스크 진행 메모는 별도로 keyup 600ms와 change를 사용한다. 모든 자동 저장을 동일 시점으로 설명하지 않는다.
근거: `core/web/static/notes.js:149`, `:655`, `:686`; `core/web/templates/tasks/_panel.html:92`.

## Astra 웹페이지 검증과 실행 환경

| 항목 | 이번 확인 결과 |
| --- | --- |
| 미리보기 | `http://127.0.0.1:8018`, 컨테이너 `pm-uiux-button-task41` |
| 코드 | UI-UX `core` 전체를 `/source`에 읽기 전용 마운트; 작업 디렉터리 `/source` |
| 서버 | 기존 의존 이미지 `pm-design-audit:20261003`의 Python으로 UI-UX `manage.py runserver --noreload` 실행 |
| 데이터 | 기존 독립 디자인 샘플 DB의 SQLite backup을 새 TEMP DB로 복제. 운영 DB·기존 미리보기 DB에 쓰지 않음 |
| DB 위치 | `%TEMP%/task41-uiux-review-20261004/design.sqlite3` → `/data/design.sqlite3` |
| 기존 미리보기 | 8017은 계속 원본 저장소 마운트. 이번 UI-UX 검증의 근거로 사용하지 않음 |
| 외부 연동 | 자격증명을 주입하지 않음. GitHub/조직 Discord 관련 일부 UI는 숨겨짐 |

근거: 이번 `docker inspect pm-uiux-button-task41`, `docker inspect pm-design-task41`, `core/config/settings.py:50`.
`docker exec pm-uiux-button-task41 /app/.venv/bin/python manage.py check`는 문제 0건이었다.

Astra가 1280px·390px에서 아래 16개 경로를 각각 조회했다. **32회 HTTP 200,
조회 중 console/pageerror 0건, 문서 전체 가로 넘침 0건**이다.
이는 모든 컨트롤·모든 상태·전체 디자인의 합격 판정이 아니라 해당 샘플의 조회 결과다.

- `/today`, `/me`, `/projects/1`, `/projects/1?view=board`
- `/projects/1/docs`, `/projects/1/api`, `/projects/1/settings`
- `/orgs/1`, `/orgs/1/teams`, `/orgs/1/notes`, `/orgs/1/roadmap`, `/orgs/1/settings`
- `/settings/profile`, `/settings/preferences`, `/settings/tokens`, `/portfolio`

읽기 전용 클릭: 일정 보기, 프로젝트별 묶음, 보드 전환, 진행 메모·상세 패널,
데스크톱 프로젝트 목록 접기·모바일 프로젝트 전환 펼치기, 문서·회의록 도움말,
팀 상세, 로드맵 수정창, 포트폴리오 출처 필터.
초기 선택자 실패 3건은 정확한 접근성 이름과 모바일 회의록 선택 순서로 재확인했다.
초기 실패를 제품 오류로 집계하지 않았다.

근거: [조회와 컨트롤·PNG 기록](button-purpose-browser/evidence.json),
[클릭 기록](button-purpose-browser/actions.json), [추가 확인](button-purpose-browser/supplement.json),
[회의록 추가 확인](button-purpose-browser/notes-supplement.json).
캡처와 JSON만 복사했으며 인증 세션과 로그인 스크립트는 산출물에서 제외했다.

## 동작 수정이 필요한 연관 문제

기존 전체 문구 보고서의 실패 안내 문제는 여전히 별도 구현 대상이다.
문서/회의록 생성·업로드·삭제 오류 누락, 초대 기간의 조용한 대체, 모든 HTMX 오류를 저장 실패로 표시,
클립보드 fallback의 잘못된 성공, 일부 이슈 동기화 실패의 전체 성공 인상은 라벨만 바꾸면 해결되지 않는다.
관련 현재 소스: `core/web/views/docs.py:54`, `:65`, `:102`; `core/web/views/notes.py:87`, `:98`, `:149`;
`core/web/views/orgs.py:166`; `core/web/static/app.js:109`, `:131`; `core/web/views/github.py:324`.

추가로 GitHub 새 팀 만들기 폼에는 `{% csrf_token %}`가 없다.
소스에서 누락을 확인했지만 실제 외부 팀 생성·CSRF 거절을 재현하지 않았으므로 실행 실패 확정으로 보고하지 않는다.
구현 시 기본 CSRF 보호와 함께 확인한다. 근거: `core/web/templates/orgs/team_detail.html:35`;
`core/web/views/teams.py:198`.

## 확인 불가·제외·다음 단계

- GitHub·Discord 외부 요청 성공/실패, OAuth 접근 허용·거절, 토큰 발급·폐기, 초대·삭제·저장 POST는 실행하지 않았다.
- 샘플 포트폴리오는 출처 0건이므로 프롬프트 생성 후 저장 초안·다운로드 화면은 소스로만 판단했다.
- 의사결정 확인/제외/정정의 실제 권한·상태 분기와 오류·저장 충돌·클립보드 실패는 소스 근거이며 브라우저 회귀 검증이 아니다.
- 비로그인/초대/OAuth/운영 화면은 소스 범위에 포함했으나 이번 Astra 16경로 실화면 범위 밖이다.
- 임의 사용자 입력 링크, 외부 AI 클라이언트의 최신 메뉴·명령, Discord 봇 메시지 전체, 운영 데이터·배포는 제외했다.
- 이번 요청은 검토 단계다. 디자인 코드 이전·문구 구현·커밋·푸시·배포는 수행하지 않았다.

검토 완료 기준인 전체 위치 목록·목적/동작 대조·권장 문구·범위와 미확정 항목 기록을 충족했다.
구현을 시작할 때 라이브 PM 규칙·TASK-41 상태를 조회해 작업과 브랜치를 정한다.
P2 동작/피드백과 위험 범위를 먼저 처리한 뒤 P3 표현을 적용하고,
변경한 분기의 테스트와 Astra의 새 실제 화면 검증을 수행한다.
