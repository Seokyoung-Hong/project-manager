# AI 의사결정 기록·포트폴리오 병렬 구현 계획

작성일: 2026-09-23
근거: [상세 설계](DESIGN-AI-DECISIONS-PORTFOLIO.md), 현재 체크아웃의 Django Core·MCP·GitHub·웹 코드
상태: 구현 중. 실제 이슈·태스크는 아래 표에 기록하며, 배포 결과는 완료 후 별도로 확인한다.

## 1. 에이전트 역할

| 역할 | 모델·노력 | 책임 |
|---|---|---|
| 통합 담당 | 현재 주 에이전트 | 실제 프로젝트 매니저 작업 절차 확인, 계약 고정, 작업 배정, 공용 진입 파일 연결, 충돌 해결, 통합 결과 확인 |
| 구현 담당 | GPT-6 Luna · high | 한 번에 함수·작은 클래스·스키마·템플릿 하나씩 구현. 각 작업에 파일 소유권, 입력·출력 계약, 완료 조건을 명시 |
| 최종 리뷰 담당 | GPT-6 Sol · high | 전체 변경을 통합한 뒤 설계와 실제 코드 대조. 권한, 데이터 정합성, 대화 요약·원문 경계, PR·포트폴리오 출처를 리뷰 |

Luna는 서로 다른 파일에서 동시에 작업한다. 공용 파일의 연결은 통합 담당이 한 번에 처리한다. Sol은 구현자가 아니며 발견 사항을 영향도와 파일·함수 위치가 있는 수정 지시로 반환한다. 수정은 해당 파일 소유 Luna가 하고 Sol이 다시 확인한다.

각 Luna에게 보내는 작업 지시에는 **소유 파일, 구현할 함수·스키마, 호출 계약, 금지된 공용 파일, 다룰 경계 사례, 보고 형식**을 넣는다. Sol에게는 통합된 diff와 설계 문서만 검토 대상으로 주고 **파일 수정 없이 우선순위·근거·수정 기준**을 보고하게 한다. 검토 결과가 없으면 “지적 없음”과 확인 범위를 명시하게 한다.

## 2. 착수 조건과 공통 계약

1. 실제 구현 요청이 오면 현재 PM MCP 연결·도구·조직 거버넌스·설정을 다시 읽는다. GitHub 이슈를 만들고 그 이슈에서 실제 PM 태스크를 생성한다. 태스크 번호를 확인한 뒤 그 번호가 포함된 브랜치를 만든다. 번호를 추측하지 않는다. 기능을 여러 이슈로 나누면 각 이슈와 PM 태스크의 의존성을 기록한다.
2. 현재 작업 트리 상태와 설계 문서를 확인하고 기존의 관련 없는 파일을 건드리지 않는다. 병렬 작업 전 아래 계약을 통합 담당이 고정해 모든 Luna에 전달한다.
3. 계약: `user_input`/`ai_judgment`, `captured`/`proposed`/`confirmed` 등의 상태, `input_type`, `evidence_basis`, 확정자·출처, 같은 태스크 내 정정, 중복 방지 키, 길이 제한. MCP 요청에는 요지 필드만 있고 대화 원문·배열·`verbatim_text` 입력이 없다.
4. Luna는 기존 공용 파일을 여러 명이 동시에 편집하지 않는다. 각자 맡은 파일만 수정하고 커밋·브랜치 전환·마이그레이션 번호 선점은 통합 담당과 조율한다. 공용 Git 인덱스는 통합 담당만 사용한다.

구현 이슈와 PM 태스크는 다음 네 결과 단위로 나눈다. 번호는 실제 생성 후에만 적는다.

| 이슈·태스크 | 포함 범위 | 선행 관계 |
|---|---|---|
| 기록 기반 — [#3](https://github.com/Seokyoung-Hong/project-manager/issues/3), TASK-38 | 파동 A1, B1·B2·B4·B5와 공용 연결 | 다른 기능의 저장·권한 계약 |
| MCP 사용법과 기록 도구 — [#4](https://github.com/Seokyoung-Hong/project-manager/issues/4), TASK-35 | 파동 A2, B3와 MCP 공용 연결 | 기록 API 계약에 의존. 프롬프트 작성은 기록 기반과 병렬 가능 |
| 의사결정 기반 PR 맥락 — [#5](https://github.com/Seokyoung-Hong/project-manager/issues/5), TASK-36 | 파동 C1·C2 | 기록 기반의 유효 기록 조회가 필요 |
| 개인 포트폴리오 — [#6](https://github.com/Seokyoung-Hong/project-manager/issues/6), TASK-37 | 파동 C3, D1~D5 | 기록 기반의 모델·조회 계약이 필요. PR 맥락과 병렬 가능 |

각 이슈에서 나온 변경은 해당 PM 태스크 번호로 추적한다. 의존 작업이 합쳐진 뒤 다음 작업을 통합하며, 병렬 Luna의 파일 수정과 PR 병합 시점을 구분한다.

## 3. 구현 파동과 병렬 작업

### 파동 A — 기록의 기반

**순서상 먼저 끝낼 작업**: Luna A1이 `core/tasks/models.py`와 다음 태스크 마이그레이션의 `TaskDecisionRecord`를 맡는다. 포트폴리오 출처가 참조할 PK·상태·제약을 먼저 확정한다. 이 작업과 동시에 Luna A2는 `mcp_server/skill/SKILL.md`의 질문·요약 기록·PR·포트폴리오 프롬프트를 작성할 수 있다. A2는 확정된 필드·도구 이름만 사용한다.

| Luna 단위 | 소유 파일 | 결과 |
|---|---|---|
| A1 기록 모델 | `core/tasks/models.py`, 새 `core/tasks/migrations/` 파일 | 기록 종류·상태·귀속·근거·정정·시각·중복 키와 DB 제약. 기록이 있는 태스크 삭제를 막는 FK 보호 |
| A2 단일 프롬프트 | `mcp_server/skill/SKILL.md` | 여러 질문 한 번에 제시, 사용자 입력의 요지만 MCP로 전달, 원문 전송 금지, PR·포트폴리오 작성 규칙 |

**통합 관문**: 스키마 필드와 상태 전이를 설계와 비교한다. 기존 데이터는 사용자 의사결정으로 자동 변환하지 않는다.

### 파동 B — 기록 서비스와 접점

A1 모델이 고정되면 아래 작업을 병렬로 진행한다. API와 웹 담당은 통합 담당이 먼저 배포한 서비스 함수 시그니처를 계약으로 사용한다.

| Luna 단위 | 소유 파일 | 결과·경계 |
|---|---|---|
| B1 기록 서비스 | 새 `core/tasks/decision_services.py` | 기록·목록·확인·제외·정정·최신 유효 기록 조회 함수. 조직 권한, 개인 토큰 귀속, `ai.record_work`, 같은 태스크 정정, 중복 방지 검증 |
| B2 API 스키마·라우터 | 새 `core/api/decision_schemas.py`, `core/api/routers/decisions.py` | B1만 호출하는 Ninja 엔드포인트. 확인은 `X-Source`가 아니라 실제 브라우저 세션과 사용자 귀속으로 검증 |
| B3 MCP 도구 | 새 `mcp_server/mcp_server/decision_tools.py` | 기록 목록·요지 제출 도구. 스키마와 도구 설명에 원문 필드 금지·짧은 중립적 요약을 명시 |
| B4 태스크 UI | 새 `core/web/views/decisions.py`, `core/web/templates/tasks/_decisions.html` | 확인 대기·세션에서 수집·AI 판단 표시와 정정·제외 액션. 서비스 함수를 경유 |
| B5 조직 정책 | `core/orgs/settings.py`, `core/orgs/governance.py` | AI 기록 허용 정책과 기존 “결정은 회의록” 문구의 새 기록 규칙 반영. 두 파일은 B5만 편집 |

통합 담당이 `core/api/api.py`, `core/web/urls.py`, `core/web/views/tasks.py`, `core/web/templates/tasks/_panel.html`, `mcp_server/mcp_server/server.py`, `mcp_server/mcp_server/permissions.py`의 연결을 단독 처리한다. API와 MCP의 이름·형식이 어긋나면 해당 Luna에게 자기 소유 파일만 수정하도록 되돌린다.

**통합 관문**: 명시 답변은 `captured`, AI 추론은 `proposed`, 웹 확인만 `confirmed`가 된다. AI 판단을 사용자 입력으로 재분류할 수 없다. 웹·API·MCP에서 같은 태스크 권한이 적용된다.

### 파동 C — PR 맥락과 포트폴리오 저장 구조

파동 B의 유효 기록 조회 함수가 고정된 뒤 병렬로 진행한다. 현재 체크아웃에는 별도 `get_task_github` API가 없으므로, GitHub 읽기 권한은 현 코드의 `can_view_repo()` 기준으로 새 경로에서 처리한다. 파동 시작 전에 통합 담당이 빈 `portfolio` Django 앱을 만들고 `INSTALLED_APPS`에 등록한다. 그다음 C3이 모델과 마이그레이션을 맡는다. 이 파동에서 포트폴리오 모델을 확정하고 다음 파동의 함수 계약을 배포한다.

| Luna 단위 | 소유 파일 | 결과·경계 |
|---|---|---|
| C1 PR 맥락 함수 | 새 `core/github/pr_context.py` | 최신 유효 기록과 이슈·브랜치·PR 정보를 묶음. 태스크 조직 권한에 더해 GitHub 접근권 확인. 이슈가 없으면 코딩 작업의 PR 초안 중단 |
| C2 PR API·MCP | 새 `core/api/routers/pr_context.py`, 새 `mcp_server/mcp_server/pr_tools.py` | C1 함수 계약에 맞춘 읽기 경로와 `get_pr_context` 도구. 기존 `TASK-N`·`Closes #N` 보존 |
| C3 포트폴리오 모델 | 새 `core/portfolio/models.py`, 새 마이그레이션 | 소유자만 볼 수 있는 초안·출처 스냅샷·버전 필드. 출처 기록 FK 보호. 원문은 스냅샷에 복사하지 않음 |

통합 담당이 `core/config/settings.py`의 앱 등록, `core/api/api.py`의 PR 라우터, `mcp_server/mcp_server/server.py`의 PR 도구를 단독 연결한다. 기존 `pr_compare_url()`이 제공하는 `TASK-N`과 `Closes #N`는 PR 작성 흐름에서 유지한다. 코드 변경과 검증 결과는 PR 작성 세션이 현재 작업 환경에서 별도로 확인한다.

### 파동 D — 개인 포트폴리오 기능

C3 모델을 통합한 뒤 함수 시그니처를 고정하고 아래 작은 단위를 병렬 진행한다. 출처 조회와 초안 저장은 서로 다른 파일이지만 접근권 규칙은 같은 계약을 사용한다.

| Luna 단위 | 소유 파일 | 결과·경계 |
|---|---|---|
| D1 출처 조회 | 새 `core/portfolio/sources.py` | 본인의 `captured`·`confirmed` 입력, AI 판단, 프로젝트·기간·주제 필터, 요지만 담은 출처 묶음 |
| D2 초안 처리 | 새 `core/portfolio/drafts.py` | 초안 생성·편집·버전 충돌·Markdown 내보내기와 접근권 재검사. 정정된 출처 감지 |
| D3 API | 새 `core/portfolio/api.py`, 새 `core/portfolio/schemas.py` | D1·D2만 호출하는 개인 출처·초안 API. 서버에서 선택 출처의 소유자·조직 재검사 |
| D4 웹 UI | 새 `core/web/views/portfolio.py`, 새 `core/web/templates/portfolio/` | 조직·프로젝트·기간·주제 선택, 비공개 초안 편집·내보내기 |
| D5 MCP 도구 | 새 `mcp_server/mcp_server/portfolio_tools.py` | 출처 요지 읽기와 AI가 만든 초안 저장. 출처 밖의 성과를 만들지 않도록 도구 설명 |

통합 담당이 `core/api/api.py`의 포트폴리오 라우터, `core/web/urls.py`의 경로, 개인 메뉴의 진입점, `mcp_server/mcp_server/server.py`의 도구 등록을 단독 연결한다.

**통합 관문**: 포트폴리오에는 본인이 확정하거나 세션에서 수집한 입력만 본인 결정으로 들어간다. AI 판단과 AI 협업 방식 지시의 출처가 구분된다. 권한 상실 시 초안 조회·내보내기 정책을 적용한다.

## 4. 충돌과 권한을 특별히 확인할 파일

- `core/api/auth.py`는 브라우저 세션과 Bearer 토큰을 같은 API에서 받는다. `confirmed_by`는 `request.api_token is None`인 실제 세션에서만 설정해야 하며 `X-Source: mcp` 헤더로 판단하면 안 된다.
- `core/github/services.py`의 저장소 정보는 태스크 조직 접근권만으로 열리지 않는다. PR 맥락에서 `can_view_repo()`를 별도로 적용한다.
- `core/tasks/services.py`의 `delete_task()`는 현재 바로 `task.delete()`를 호출한다. 기록과 포트폴리오 출처가 생기면 참조 보호, 웹·API 오류 문구, 취소·보관 대안을 통합 담당이 함께 처리한다.
- `mcp_server/mcp_server/server.py`와 `permissions.py`는 도구 등록·목록 필터의 접점이다. 목록 필터만으로 권한이 강제되지는 않으므로 Core 서비스 검사를 기준으로 한다.
- 기존 `Task.notes`, `ChangeLog`, GitHub 이슈 본문을 사용자 결정으로 자동 승격하지 않는다.

## 5. Sol 최종 리뷰와 수정 루프

모든 Luna 결과를 통합한 후 **GPT-6 Sol · high** 한 명이 전체 diff와 상세 설계를 대조한다. 리뷰는 다음 항목을 우선한다.

1. 사용자 입력·AI 판단의 귀속, `captured`/`proposed`/`confirmed` 전이, 정정·중복 생성의 원자성.
2. MCP 요청·프롬프트·PR·포트폴리오 어느 경로에도 대화 전문과 사적 말투가 기본 전송되지 않는지.
3. API·웹·MCP의 실제 권한 경계, `X-Source` 위조, 타 조직 기록, 타인의 포트폴리오 접근.
4. GitHub 정보에 `can_view_repo()` 적용, 이슈·태스크 번호 유지, PR에 확인되지 않은 검증 결과가 들어가지 않는지.
5. 태스크 삭제·조직 탈퇴·출처 정정 뒤 기록과 초안의 접근·보존 동작.

Sol은 발견 사항을 우선순위·재현 경로·해당 파일·수정 기준으로 반환한다. 통합 담당이 이를 작은 함수 단위로 Luna에 다시 배정한다. 수정이 합쳐지면 Sol이 관련 부분만 재검토하고, 해결되지 않은 문제는 남은 한계로 명시한다. 최종 완료 보고는 Luna 구현 결과, 통합 확인, Sol 리뷰 결과를 구분한다.

## 6. 순서 요약

`실제 이슈·태스크·거버넌스 확인 → 계약 고정 → A1 모델 + A2 프롬프트 병렬 → B1~B5 병렬 → 통합 → C1~C3 병렬 → 통합 → D1~D5 병렬 → 통합 → Sol 전체 리뷰 → Luna 소단위 수정 → Sol 재검토`.

병렬성은 **같은 파일을 동시에 편집하는 것**이 아니라 독립적인 작은 산출물을 같은 계약 아래 동시에 만드는 데 사용한다. 전체 대화 기록 자동 수집, 서비스 내부 LLM 호출, 공개 포트폴리오·블로그 발행은 이번 구현 범위에 포함하지 않는다.
