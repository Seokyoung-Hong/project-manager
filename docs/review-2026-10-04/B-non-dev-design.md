# 비개발 팀·저장소 미연결 프로젝트 설계안 (초안 B)

- 작성: 2026-10-04 · 기준 커밋 `8d0be51` · 읽기 전용 조사(코드 수정 없음)
- 범위: 운영팀·마케팅팀 등이 **GitHub 저장소를 연결하지 않은 프로젝트**로 일할 때의 프로세스·기능. GitHub 연동 결함과 일반 개선은 다루지 않음.
- 원칙: 기존 기능 재사용 우선, 새 모델은 꼭 필요할 때만.

---

## 0. 한 줄 결론

핵심 흐름(태스크 상태·검토 대기·완료 조건·체크리스트·외부 링크·문서·요청·Discord·MCP)은 **이미 저장소와 무관하게 동작**한다. GitHub 자동 규칙은 웹훅 경로에서만 돈다(core/github/services.py:627, 670, 727, 815). 깨지는 곳은 없고 **어색한 곳**(늘 보이는 GitHub·API 문서 탭, 패널의 "저장소 미연결" 접이 블록, 개발 용어)과 **없는 기능**(반복 업무, 복제·템플릿, 팀·프로젝트 일정 달력, 요청의 희망 기한, 반려 흐름)이 문제다.
"프로젝트 유형" 새 필드 대신 **기존 설정 레지스트리에 항목 하나**(`project.dev_tools`, 조직 기본값 + 프로젝트 덮어쓰기)를 추가하는 방식을 추천한다. 마이그레이션이 없다.

---

## 1. 현황: 저장소 미연결 프로젝트에서 각 화면

### 1.1 GitHub 전제가 드러나는 지점

| # | 위치 | 지금 동작 | 비개발 관점 문제 | 심각도 |
|---|---|---|---|---|
| 1 | core/web/templates/projects/_tabs.html:10 | `github_enabled`이면 **GitHub 탭 항상 표시** | 쓰지 않는 탭. 눌러도 저장소 연결 폼만 나옴(projects/repo.html:8-20) | 중 |
| 2 | projects/_tabs.html:8 | **API 문서 탭 항상 표시** | OpenAPI 업로드 화면(projects/api.html:19-27) — 비개발과 무관 | 중 |
| 3 | projects/_tabs.html:9 | 이슈 탭은 `project.repo`가 있을 때만 | 문제 없음(이미 조건부) | - |
| 4 | core/web/templates/tasks/_panel.html:98 | 모든 태스크 패널에 `GitHub · 저장소 미연결` 접이 블록 | 매 태스크마다 무의미한 블록 | 중 |
| 5 | core/web/views/tasks.py:56-58, tasks/_git.html:4-5 | 요약 "저장소 미연결", 펼치면 "저장소 연결" 링크 | 연결을 권유하는 문구 | 중 |
| 6 | core/web/views/tasks.py:36-41 | 패널 렌더마다 `repo_state()` 호출 | 불필요한 조회(성능 영향은 작음, 확인 불가) | 하 |
| 7 | tasks/_refs.html:47 | "PR·커밋은 저장소 연결이 자동으로 붙입니다" | 개발 문구 | 하 |
| 8 | core/tasks/models.py:324-332, core/web/forms.py:135 | 링크 종류 `문서/이슈/대시보드/기타` | "이슈"는 개발 용어, "산출물"·"증빙" 종류 없음 | 하 |
| 9 | core/projects/models.py:20-24 | 상태 설명 "개발 또는 구현 진행 중", "유지보수 외 별도 작업 없음", "지원 종료" | 개발 용어. 프로젝트 만들기 대화상자에 그대로 노출(projects/_dialog.html:17) | 하 |
| 10 | core/orgs/governance.py:11, 16-17 / orgs/models.py:23 / orgs/governance.html:1,19 | "개발 거버넌스", 예시 "로그인 고치기" | 조직 전체 문서인데 이름이 개발 한정. 9절(:62)은 "저장소를 연결했을 때"로 이미 조건부 | 하 |
| 11 | core/web/templates/orgs/_tabs.html:10 | 조직 "이슈" 탭은 `github_enabled`이면 표시 | 비개발 멤버에게도 보임(조직 단위라 숨기기 어려움) | 하 |
| 12 | skills/pm-start/SKILL.md:48 | 착수 시 **무조건** 브랜치 이름 제안 | 저장소 없는 프로젝트에서 엉뚱한 제안 | 중(AI) |
| 13 | skills/pm-done/SKILL.md:22 | 완료 점검에서 **무조건** "PR이 있는가" 확인, 없으면 /pm-pr 제안 | 같은 문제 | 중(AI) |
| 14 | mcp_server/skill/SKILL.md:56-62 | "태스크·브랜치·PR" 절. 조건 문구 없음 | AI가 비개발 태스크에 PR 흐름을 적용할 여지 | 하(AI) |

참고로 이미 잘 처리된 곳: projects/settings.html:32(저장소 규칙은 연결됐을 때만), skills/pm/SKILL.md:167(이슈 생성은 `connected: true`일 때만 묻기), projects/docs.html:67("GitHub 저장소를 연결하지 않아도 그대로 씁니다").

### 1.2 저장소 없이도 그대로 쓰는 기능(재사용 후보)

| 기능 | 근거 | 비개발 용도 |
|---|---|---|
| 상태 7단계, 검토 대기 | core/tasks/models.py:9-17; 전이 규칙 core/tasks/services.py:397-480 — PR 전제 없음 | 승인/검토 흐름의 뼈대 |
| 검토 필수·본인 검토 금지(프로젝트별 덮어쓰기 가능) | core/orgs/settings.py:134-152 (`task.review_required`, `task.self_review`, overridable=True) / services.py:466-480 | 결재형 승인 |
| 검토 독촉 DM(프로젝트 관리자에게) | settings.py:604-614 `notify.review_nudge_days` | 승인 지연 알림 |
| 완료 조건 필수 | settings.py:79-87 `task.require_done_when`, services.py:235-238 | 완료 기준 |
| 체크리스트(+AI 일괄 교체) | tasks/models.py:295-302, services.py:631-686 | 업무 절차 |
| 외부 링크(태스크·프로젝트) | tasks/models.py:323-356 | 산출물·증빙 URL(드라이브, 게시물, 광고 대시보드) |
| 프로젝트 문서(.md 업로드 포함) | projects/models.py:106-138, web/urls.py:123-128 | 운영 매뉴얼·캠페인 브리프 |
| 회의록 | web/urls.py:200-205 | 그대로 |
| 요청(작업/담당/일반) → 수락 시 태스크 생성 | tasks/models.py:390-461, work_requests.py:264-311 | 타 팀 업무 접수 |
| 마일스톤·로드맵·의존 | projects/models.py:69-90, web/urls.py:184-195 | 캠페인 주요 일정 |
| 보드/목록 기본 화면 | settings.py:276-286 `project.default_view` | 칸반 |
| 프로젝트 채널 게시·Discord 명령 | settings.py:616-631, discord_service/slash.py:253-356 | 그대로 |
| 프로젝트 설정 JSON | projects/models.py:49, settings.py:822-842 `effective()` | 유형 플래그 저장소 |

### 1.3 없는 것

| 없는 것 | 근거 |
|---|---|
| 반복(정기) 업무 | Task에 반복 필드 없음(tasks/models.py:33-57). 스케줄러는 Discord 서비스에만 있음(discord_service/scheduler.py:86-) |
| 태스크 복제·템플릿 | web/urls.py:134-173에 복제 경로 없음 |
| 프로젝트·팀 일정 달력 | 달력은 "오늘" 화면의 **내 마감**만(core/web/views/today.py:71-84) |
| 요청의 희망 기한·대상 프로젝트 | requests/new.html:13-31(종류·받는 쪽·제목·내용만), 수락 시 기한 미정으로 생성(work_requests.py:307) |
| 반려(검토 → 되돌리기) 사유 | 재개 사유는 완료·취소에서 다시 열 때만(services.py:439-441). review→doing은 사유 없이 가능 |
| 지정 검토자 | Task에 reviewer 없음. 독촉은 프로젝트 관리자에게만 |
| 파일 첨부 | SPEC.md:29에서 범위 밖으로 명시 — 링크로 대체하는 것이 기존 결정 |
| 팀 단위 설정 | Team 모델에 settings 없음(core/orgs/models.py:80-97). `effective()`는 개인>프로젝트>조직>기본값(settings.py:823) |

---

## 2. 프로젝트 유형 설계

### 2.1 선택지

| 안 | 내용 | 장점 | 단점 |
|---|---|---|---|
| A. 저장소 연결 여부로만 판단 | `project.repo` 유무로 GitHub 블록·탭 표시 | 새 개념 없음, 코드 최소 | 저장소를 **아직** 안 붙인 개발 프로젝트에서 연결 입구가 사라짐. API 문서 탭 기준이 안 됨 |
| B. Project에 `kind` 필드(dev/general) | 모델 필드 + 마이그레이션 | 명시적, 목록 필터·통계 쉬움 | 마이그레이션·폼·API·MCP 스키마 모두 수정. 유형마다 다른 동작을 기대하게 만들어 과설계 유도 |
| **C. 설정 레지스트리에 `project.dev_tools`(bool) 추가** | `Spec("project.dev_tools", "bool", True, "org", overridable=True, group="project")` | **마이그레이션 없음**(projects/models.py:49 JSON), 프로젝트 설정 화면·`get/update_project_settings` MCP·API가 자동으로 다룸(settings.py:737-741), 조직 기본값으로 "비개발 조직"도 한 번에 | 프로젝트 목록에서 유형 필터를 하려면 JSON 조회가 필요(지금 요구 없음) |
| D. 팀 단위 기본값 | Team에 설정 추가, 프로젝트 생성 시 담당 팀 값을 따름 | 운영팀이 만든 프로젝트가 자동으로 비개발 | Team 마이그레이션 + `effective()` 계층 추가. 프로젝트가 여러 팀(M2M)이면 충돌 규칙 필요 |

### 2.2 추천: C (+ A의 보조 규칙)

- 표시 규칙: `dev_tools = effective("project.dev_tools", project=p) or p.repo 존재`
  - 꺼져 있으면: GitHub 탭·API 문서 탭·패널 GitHub 블록 숨김, `repo_state()` 호출 생략.
  - 저장소가 연결돼 있으면 설정과 무관하게 표시(데이터 숨김 방지).
- 기본값 `True` → 기존 프로젝트 동작 불변.
- 팀 단위 기본값(D)은 **v1 제외**. 대신 프로젝트 만들기 대화상자에 "개발 도구 사용" 체크박스 하나(초기값 = 조직 설정)를 두면 생성 시점에 정해진다. 팀 기본값이 실제로 필요해지면 그때 "담당 팀이 전부 X면 기본 끔" 정도로 추가.
- 이름은 "유형"이 아니라 **기능 스위치**로 둔다. 유형이 생기면 "일반 프로젝트는 상태가 달라야 한다" 같은 분기 요구가 따라오는데, 상태 흐름은 공통으로 충분하다(1.2).

---

## 3. 비개발 프로세스·기능 제안

### 3.1 권장 프로세스(제품이 아니라 운영 합의 + 기본 설정)

1. 접수: 다른 팀은 **요청(/requests)**으로 일을 보낸다(희망 기한 포함 — F5). 운영팀이 수락하며 프로젝트·담당·기한을 정한다.
2. 착수: 완료 조건 필수(`task.require_done_when`), 체크리스트로 절차를 적는다(반복 업무는 복제·반복으로 자동).
3. 산출물: 결과물 URL을 링크 종류 "산출물"로 붙인다(파일 업로드는 하지 않음 — SPEC.md:29).
4. 승인: `검토 대기`로 올리고, 프로젝트 관리자(또는 지정 검토자, 이후)가 완료 처리. `task.review_required=켬`, `task.self_review=끔`, `notify.review_nudge_days=2` 를 비개발 프로젝트 권장 설정으로 안내.
5. 반려: 검토 대기에서 진행 중으로 돌릴 때 사유를 남긴다(F6).
6. 일정: 캠페인 주요 일자는 마일스톤, 개별 게시·발송일은 태스크 기한 → 프로젝트 달력에서 한눈에(F7).

### 3.2 기능 제안 표

| ID | 기능 | 필요성 | 기존 재사용 | 데이터 모델 변경 | 화면 변경 | Discord / MCP 영향 | 규모 | 우선순위 |
|---|---|---|---|---|---|---|---|---|
| F1 | 개발 도구 스위치(`project.dev_tools`) + 조건부 표시 | 1.1 #1·2·4·5·6 해소 | 설정 레지스트리, 프로젝트 설정 화면 | 없음(Spec 1개, JSON) | _tabs.html:8·10, _panel.html:98 조건, tasks.py `_git_ctx` 생략, _dialog.html 체크박스 | MCP `get/update_project_settings`로 자동 노출. Discord 없음 | S | **필수 v1** |
| F2 | 문구 일반화 | 1.1 #7·8·9·10 | - | Link.KINDS에 `("out","산출물")` 추가(choices 변경 = 마이그레이션 1개, 열 길이 5 이내). "이슈" 종류는 dev_tools 꺼진 프로젝트 폼에서 숨김 | _refs.html:47, projects/models.py:20-24 상태 설명, "개발 거버넌스"→"업무 거버넌스", 기본안 예시 교체 | MCP 가이드 문구 일부 | S | **필수 v1** |
| F3 | AI 스킬·가이드 조건화 | 1.1 #12·13·14 | `GET /api/projects/{id}/repo`의 `connected` (이미 pm/SKILL.md:167이 씀) | 없음 | 없음 | skills/pm-start:48, pm-done:22, mcp_server/skill/SKILL.md:56 에 "저장소 연결 시에만" 조건 | S | **필수 v1** |
| F4 | 태스크 복제(체크리스트·완료 조건·설명·링크 복사, 상태는 시작 전) | 반복·템플릿의 공통 부품. 매주 같은 절차 재입력 제거 | `create_task`, `replace_checklist` | 없음 | 패널 "더보기"에 [복제] 버튼, 새 기한 입력 | MCP `duplicate_task` 도구 1개(선택), Discord 없음 | S | **필수 v1** |
| F5 | 요청 양식 보강: 희망 기한, (선택)대상 프로젝트 | 접수 품질. 지금은 수락 시 "기한 미정"으로 생김(work_requests.py:307) | WorkRequest, 수락 흐름 | WorkRequest에 `due_date`(null) 1열 | requests/new.html 칸 추가, 수락 폼 기본값으로 채움 | Discord `/요청`에 선택 인자 `기한`, MCP `create_request`에 `due_date` | S | **필수 v1** |
| F6 | 반려 사유: 검토 대기 → 진행 중/시작 전 시 사유 입력 | 승인 흐름의 근거 기록 | `transition(reason=)`, ChangeLog note, 기존 사유 입력 UI(_stop.html 패턴) | 없음 | 상태 선택에서 review→doing/todo일 때 사유 칸. 설정 `task.reject_reason_required`(overridable) 추가 | Discord `/상태`·MCP `transition_task` 모두 reason 인자가 이미 있음(discord_service/slash.py:345-351, mcp_server/server.py:611) — 설명 문구만 보강 | S | **필수 v1** |
| F7 | 프로젝트 달력(월간, 태스크 기한 + 마일스톤) | 캠페인·발행 일정. 지금 달력은 개인용뿐 | today.py `_schedule()`·`week_days()`(common.py:286) | 없음 | 프로젝트 화면 보기 전환에 "달력" 추가(`project.default_view` choices에 `calendar`) | 없음 | M | **필수 v1** |
| F8 | 반복 업무(완료 시 다음 회차 생성) | 주간 보고·월 마감·정기 게시 등 운영 업무의 핵심 | F4 복제 함수, `transition()`의 done 분기 | Task에 `repeat`(choice: 없음/매주/격주/매월, 1열) | 패널에 "반복" 선택, 목록 행에 반복 표시 | MCP `update_task`에 `repeat`, Discord `/완료` 응답에 "다음 회차 TASK-N 생성" | M | 이후(v1.1) — 결정 질문 Q4 |
| F9 | 체크리스트·태스크 템플릿 | 같은 절차를 여러 프로젝트에서 재사용 | F4 복제 + 프로젝트 하나를 "템플릿 보관함"으로 쓰는 관례 | v1은 없음(관례). 필요 시 이후 `is_template` 1열 | v1은 없음 | 없음 | S(관례) / M(전용) | 관례는 v1 안내, 전용은 이후 |
| F10 | 지정 검토자 | 관리자 아닌 사람(팀장·법무 등)이 승인 | WorkRequest `general`(검토 부탁 용도라고 모델 주석에 있음, tasks/models.py:395) 또는 Task 필드 | 재사용안: 없음 / 필드안: Task `reviewer` 1열 | 검토 대기로 올릴 때 검토자 선택 | 독촉 DM 대상 변경, MCP 필드 추가 | M | 이후 — Q5 |
| F11 | 팀 단위 기본값 | 운영팀 프로젝트 자동 설정 | - | Team settings + `effective()` 계층 | 팀 화면 설정 | - | M | 이후(필요 확인 시) |
| F12 | 파일 첨부 | 이미지·PDF 산출물 | - | 저장소·백업·용량 정책 필요 | 업로드 UI | - | L | **하지 않음**(SPEC.md:29 결정 유지, 링크로 대체) |
| F13 | 외부 승인 서명·다단계 결재선 | - | - | - | - | - | L | 하지 않음(SPEC.md:33 "복잡한 승인 체계" 범위 밖) |

---

## 4. 단계별 구현 순서 초안

| 단계 | 묶음 | 내용 | 선행 |
|---|---|---|---|
| 1 | F1 + F2 + F3 | 스위치 Spec, 탭·패널 조건부 표시, 문구·Link 종류, 스킬 조건화. 테스트: dev_tools 끈 프로젝트에서 GitHub·API 탭 없음, 저장소 연결 시 강제 표시, 패널에 GitHub 블록 없음 | 없음 |
| 2 | F4 + F6 | 복제 서비스 함수(services.py) → API `POST /api/tasks/{id}/duplicate` → 웹 버튼 → MCP. 반려 사유 설정·검증 | 1 |
| 3 | F5 | WorkRequest.due_date 마이그레이션, 웹·Discord·MCP 인자 | 없음(병렬 가능) |
| 4 | F7 | 프로젝트 달력 보기. `_schedule()`에서 대상 쿼리만 바꿔 재사용 | 1 |
| 5 | F8 | 반복(완료 시 다음 회차). F4 함수 재사용, `transition()` done 분기에서 호출, 중복 생성 방지(같은 원본에서 한 번만) | 2 |
| 6 | 운영 안내 | 비개발 권장 설정 묶음(검토 필수·본인 검토 금지·완료 조건 필수·독촉 2일)을 거버넌스 기본안에 "비개발 프로젝트" 절로 추가 | 1 |

규칙: 업무 규칙은 `services.py`에만 둔다(GUIDE-V2-00-overview.md:47).

---

## 5. 결정 질문

| # | 질문 | 선택지 | 추천 |
|---|---|---|---|
| Q1 | 유형 구분 방식 | (a) 저장소 유무만 (b) `kind` 모델 필드 (c) 설정 스위치 `project.dev_tools` | **(c)** — 마이그레이션 없음, 기존 설정 화면·MCP 재사용 |
| Q2 | 스위치 조직 기본값 | (a) 켬(현행 유지) (b) 끔(비개발이 다수인 조직) | **(a)**. 비개발 위주 조직이면 조직 설정에서 끔 |
| Q3 | 팀 단위 기본값을 v1에 넣을지 | (a) 넣음 (b) 생성 대화상자 체크박스로 대체 | **(b)** |
| Q4 | 반복 업무 방식 | (a) 완료 시 다음 회차 생성(스케줄러 불필요) (b) 일정 시각에 자동 생성(스케줄러 필요 — 현재 Discord 서비스에만 있음) (c) v1은 복제만 | **(a)를 v1.1**, v1은 (c). 미완료면 다음 회차가 안 생기는 점을 수용할지 확인 필요 |
| Q5 | 지정 검토자 | (a) 프로젝트 관리자로 충분(현행) (b) WorkRequest 일반 요청으로 검토 부탁 연결 (c) Task.reviewer 필드 | **(a) v1**, 수요 확인 후 (c) |
| Q6 | 파일 첨부 | (a) 링크 유지(SPEC.md:29) (b) 업로드 추가 | **(a)** + 링크 종류 "산출물" |
| Q7 | "개발 거버넌스" 명칭 | (a) 유지 (b) "업무 거버넌스"로 변경 | **(b)**. 저장된 조직 글은 그대로, 기본안 제목과 화면 문구만 |
| Q8 | 프로젝트 상태 설명(개발 용어) | (a) 공통 문구로 일반화 (b) 스위치에 따라 다른 문구 | **(a)** — 분기 없이 "작업 진행 중" 등 |
| Q9 | 프로젝트 달력에 마일스톤 포함 | (a) 포함 (b) 태스크 기한만 | **(a)** |
| Q10 | 조직 "이슈" 탭(orgs/_tabs.html:10) | (a) 그대로 (b) 조직에 GitHub 설치가 있을 때만 | **(b)** — 단, 조직 탭은 GitHub 연동 담당 갈래와 조율 |

---

## 6. 확인 불가·미확인

- 패널마다 `repo_state()`를 부르는 비용의 실측치: 확인 불가.
- 실제 운영·마케팅 팀의 업무 사례(반복 주기, 승인자 구성): 저장소에 자료 없음 — 사용자 확인 필요.
- 포트폴리오(core/portfolio)가 비개발 사용자에게 의미 있는지: 이번 범위에서 보지 않음.
