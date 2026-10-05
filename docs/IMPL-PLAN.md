# 구현 계획 v1 — 지시서와 목업 정합, 실행 순서

작성일: 2026-09-10
기준 문서: [PLAN.md](../PLAN.md) v0.3, [GUIDE-00](GUIDE-00-rules.md)~[04](GUIDE-04-deploy.md), [README.md](../README.md)(목업 핸드오프, 2026-09-10), `유달리 업무 목업 v2.dc.html`, `TaskRow2.dc.html`
현재 상태: 코드 없음. git 미초기화. 로컬 도구 준비됨(uv 0.12, git 2.52, Docker 29, Python 3.14 — uv가 3.12를 받아 쓴다).

---

## 1. 결론

지시서(09-09)와 목업(09-10)이 도메인 모델과 화면에서 갈라진다. 목업이 하루 뒤에 확정된 최종안이므로:

- **무엇을 만드나(데이터 모델·규칙·화면·문구·토큰)는 목업과 README를 따른다.**
- **어떻게 만드나(스택·파트 분리·코드 규칙·API 계약 형식·테스트 방식·배포)는 지시서를 그대로 둔다.**
- 지시서를 먼저 개정한다(0단계). 개정 없이 구현에 들어가면 구현 담당 모델이 두 문서 사이에서 헤맨다. 개정 뒤에는 GUIDE-00의 규칙 "지시서 우선"이 다시 유효하다.

우선순위: 목업·README > GUIDE > PLAN > SPEC. 이 문서는 개정이 끝날 때까지만 GUIDE에 우선한다.

### SPA로 가지 않는 이유

목업의 `class Component`는 상태 + `renderVals()`(순수 파생 계산)다. `renderVals()`는 Django 뷰가 context를 만드는 일과 같고, 상태 항목은 URL 파라미터·DB·작은 JS 셋으로 1:1 대응된다(§5). React·빌드 도구 금지는 확정 결정이다. HTMX + 템플릿으로 충분하다.

---

## 2. 바꾸지 않는 것

| 항목 | 유지 내용 |
|---|---|
| 스택 | Python 3.12, Django 5.2, Django Ninja, PostgreSQL 16, HTMX, 함수형 뷰, `services.py` 단일 규칙, 낙관적 잠금(`version`), 멱등 키, ChangeLog |
| 파트 분리 | `core/`, `discord_service/`, `mcp_server/`. HTTP API로만 통신 |
| 코드 규칙 | GUIDE-00 §1·§3 전부. 허용 의존성 표(예외 1건은 §4.1) |
| 시간 규칙 | GUIDE-00 §4 그대로. 기한은 날짜만 |
| 목업 밖 화면 | 로그인·가입·초대·팀 멤버·프로필·토큰·ops·admin. 지시서대로 만들고 새 CSS 토큰으로만 스타일 |
| 팀 계층 | Team → Project → Task → Checklist. 목업은 팀 하나만 보여 주므로 화면은 "현재 팀" 기준 |
| 배포 | GUIDE-04 전부 |
| 검수 시나리오 | A01~A14, A18, B01~B05. 막힘 관련은 상태 기반으로 문구만 바뀜 |

---

## 3. 정합 결정표 (지시서 → 목업)

| 영역 | 지시서(09-09) | 결정(목업 기준) |
|---|---|---|
| 태스크 상태 | 5개 + `is_blocked` 플래그 | **7개** `todo/doing/paused/blocked/review/done/cancelled`. 미완료 5개. `is_blocked`·`blocked_reason`·`blocked_at` 삭제 → `stop_reason`(300자, blocked·paused 공용) + `stopped_at` |
| 막힘 규칙 | `set_blocked()` 별도 | `transition(blocked)`에 사유 필수. paused는 선택. blocked·paused 밖으로 나가면 `stop_reason=''`. 이미 멈춘 태스크의 사유 수정은 `update_task(stop_reason)`(blocked면 공백 불가) |
| 재개 | done·cancelled → todo·doing, 사유 **필수** | 사유 **선택**. 있으면 ChangeLog note에 기록. 목업 상태 select에는 사유 입력이 없다 (SPEC 6.3과 다름, 근거: README 규칙 4) |
| 중요도 | `high/mid/low` | **정수 1~10**, 기본 5. 티어: 8~10 높음(굵게)·4~7 중간·1~3 낮음. 필터는 티어로 |
| 기한 연장 | `update_task(due_date)` | `extend_due(task, new_date, reason)` 추가: 새 날짜 > 현 기한, 사유 필수, ChangeLog `due_date` note `연장: 사유`, `no_due_reason=''`. 기한 없던 태스크의 "목표일 정하기"도 같은 함수(비교 생략). API `PATCH due_date`는 MCP용으로 유지 |
| 진행 메모 | `Comment` 모델, 댓글 CRUD·이력 | **`Task.notes` 텍스트 하나**. `Comment` 모델·서비스·API·템플릿 삭제. 자동 저장. ChangeLog 없음 |
| 부속 필드 저장 | `update_task`가 version 증가 | `title/description/done_when/next_action/notes`는 **version을 올리지 않는다**(`update_text()`; 자동 저장이 행의 hidden version을 낡게 만드는 문제 방지). version은 상태·담당자·기한·중요도·프로젝트·사유 변경에만 |
| 프로젝트 상태 | 4개 | **8개** `preparing/on_hold/waiting/active/paused/done/stopped/eol`. 라벨·설명은 README 표 그대로(이모지 포함) |
| 프로젝트 담당 | `owner` FK 1명 | **`owners` M2M 여러 명**. 빈 값 "미지정"(경고색). `projects_without_owner`는 M2M 비어 있음 |
| 프로젝트 목표일·저장소 | `target_date`, `repo_url` | **둘 다 삭제**. 저장소·설계 문서는 `Link(project, kind=repo/doc)`로. 헤더 메타 줄에 프로젝트 링크를 종류별로 표시 |
| 프로젝트 집계 | `total`=전체 | `total`은 **취소 제외**. 완료 `done/total`. 진행률 %는 내 태스크의 프로젝트 하위 묶음에서만 |
| 오늘 목록 | `TodayItem(user, task, date, position)` 매일 빈 상태 + "어제 남은 일" + "진행 중" 섹션 | `TodayItem`에 **`excluded` bool 추가**(같은 모델로 직접 담기·오늘 제외 둘 다). `User.auto_pull_days`(0/1/3/5/7/14, 기본 5). 오늘 목록 = 직접 담은 것 ∪ (미완료·기한 ≤ 오늘+N·제외 아님). "어제 남은 일"·"진행 중" 섹션 삭제 |
| 오늘 정렬 | 담은 순서 | 닫힌 것 뒤로 → 중요도 desc → 기한 asc → id. ↑↓는 직접 담은 항목끼리만 |
| 오늘 화면 | 상단·빠른 추가·선택 업무·어제·진행 중·완료·보조 | README §1: 날짜+힌트, 지표 3개(오늘 완료·지난 7일 완료·남은 내 태스크), 빠른 추가(제목·프로젝트·중요도·기한·사유), **지금 할 일 카드**, 오늘 태스크(자동 담기 select, 제외 복원), 오늘 완료(접힘), 요약 링크 줄, **일정 카드**(기본 닫힘) |
| 내 업무 | 5그룹 고정, 필터 4개 | README §2: `member`(팀 전체 0/나/타인), `group`(due/project/status), `due` 7종, `project`, `status` 7종(+doneToday/done7), `priority` 티어. 기한별 그룹은 프로젝트 하위 묶음(완료 n/m + 8px 진행률 바). 타인·팀 전체는 행 read-only |
| 타인 태스크 | 팀원 누구나 수정 | **화면 규칙만**: 타인 행의 상태 select disabled, 오늘 버튼 숨김. 상세 패널·API·MCP는 팀원 누구나 수정(SPEC 3.2 유지, 이력 기록) |
| 팀 화면 | `/teams/{id}` 표 여러 개 | README §3: 지표 6개 버튼(→ 내 태스크 팀 전체 + 같은 필터), 프로젝트 표(관리자 쉼표, 상태 배지+설명, 미완료, 완료 x/y, 보관 포함, 새 프로젝트 모달), 담당자별 표 |
| 프로젝트 화면 | 별도 `/tasks/new` 페이지 | README §4: 헤더+메타, **인라인 태스크 폼**(담당자 기본 나·변경 가능, 중요도, 기한, 사유), 지표 5개, 목록/보드, 완료·취소 포함. `/tasks/new` 페이지는 삭제. 생성 후 패널 오픈 |
| 프로젝트 생성·수정 | `/projects/new`, `/edit` 페이지 | **모달**(`<dialog>`, HTMX로 로드). 이름·목적·관리자 칩·상태 라디오 8개. 같은 URL을 유지하되 응답이 다이얼로그 부분 템플릿 |
| 상세 패널 | 닫기·다음 행동·메타·완료 조건·체크리스트·댓글·링크·이력·더보기·멈추기 | README §7 순서. 자동 저장 상태 텍스트, 링크 복사, 크게/옆으로 보기, 제목 input, 상태 select+설명, **사유 박스**(막힘 필수·일시정지 선택, 확정 버튼), 설명, 목표일 블록+연장 폼, 완료 조건, 체크리스트, 진행 메모(단일), 링크(+링크 추가 인라인 폼), 변경 이력 details, 더보기 details(안내 문구 + `수정` 링크→`/tasks/{id}/edit`, 담당자 변경 경로) |
| 태스크 행 | `_row.html` 한 종류 | `TaskRow2` 그대로: 옵션 `show_next/show_move/hide_assignee/hide_today/read_only`. 상태 pill select(색 표), 오늘 버튼 3상태 라벨, 링크 복사, ↑↓ |
| 검색 | `/search` | 동일. placeholder "예: TASK-121, 메뉴, 챗봇" |
| 일정 카드 | 없음(후속) | **포함, 1단계 마지막**. 월간 달력(이번 달 grid, 마감 ●n, 선택일 목록) + 시간표(09~18시 눈금, "종일"에 오늘 마감 목록만). 기한에 시각이 없으므로 시간 배치 없음 |
| 스타일 | Pico CSS | **Pico 삭제.** README 토큰(Light/Dark)·타이포 스케일·간격·radius를 `app.css`로. 다크는 `prefers-color-scheme`로 자동, 토글 없음 |
| 폰트 | 없음 | Pretendard. **CDN 예외 1건**(jsDelivr `pretendard.min.css`). 자체 호스팅 파이프라인이 없고 동적 서브셋은 파일 100여 개라 벤더링이 비현실적 |
| 반응형 | Pico | 1150px 이하: 상세 열림 시 본문 대신 상세. 700px 이하: 메뉴 두 줄, 프로젝트 레일 가로 스크롤, 상세 전체 화면, 팀 지표 2열. `prefers-reduced-motion` 시 트랜지션 제거 |
| 변경 이력 표시 | 표 | 목록: `항목: 이전 → 이후` / `시각 · 행위자 · 경로`. 항목·값은 한국어 라벨로 변환해 표시(저장은 코드값) |
| 주간 집계 | `commented` 포함 12키 | `Comment` 삭제로 **`commented`·`counts.commented` 제거**. 11키, counts 8개. `blocked`=`status=blocked` |
| Discord | `is_blocked`, 상태 5 | 상태 7 라벨, `OPEN` 5개, 막힘 표시는 `status=='blocked'` |
| MCP | 15개 도구(`set_blocked`, `add_comment`) | **14개**: `set_blocked` 삭제(`transition_task`가 blocked·paused 사유 처리), `add_comment` → **`append_note(task_id, text)`**(get_task → notes 끝에 줄 추가 → PATCH, 충돌 시 안내). 나머지 동일 |

---

## 4. 지시서 개정 목록 (0단계 산출물)

개정은 코드가 적힌 부분을 실제 코드로 다시 쓴다. 아래는 무엇이 바뀌는지의 목록이다.

### 4.1 GUIDE-00
- §3 허용 의존성 표에서 Pico CSS 제거. "CDN 금지" 아래 예외 한 줄: Pretendard 폰트 CSS(jsDelivr).
- §5 값 표: 태스크 상태 7개, 미완료 5개, 중요도 `1~10 정수`(티어 표기), 프로젝트 상태 8개.

### 4.2 GUIDE-01-1 (모델)
- `User`: `auto_pull_days = PositiveSmallIntegerField(default=5)`.
- `Project`: `STATUSES` 8개(라벨·설명은 `PSTATUS` dict로 함께), `owner` → `owners = ManyToManyField(User, blank=True, related_name="owned_projects")`, `target_date`·`repo_url` 삭제.
- `Task`: `STATUSES` 7개 + `STATUS_HINT` dict, `OPEN` 5개, `STOPPED = ("paused", "blocked")`, `priority = PositiveSmallIntegerField(default=5)` + CheckConstraint 1~10, `is_blocked/blocked_reason/blocked_at` → `stop_reason`(300)·`stopped_at`, `notes = TextField(blank=True)`. 제약: `doing→due`, `blocked→stop_reason≠''`, `done→completed_at`. 프로퍼티 `is_blocked`(status=='blocked')·`is_stopped`·`priority_tier`.
- `TodayItem`: `excluded = BooleanField(default=False)`.
- `Comment` 삭제. `ChangeLog.TARGETS`에서 `comment` 제거.
- admin: `list_filter`의 `is_blocked` 제거, `Comment` 등록 제거.

### 4.3 GUIDE-01-2 (서비스)
- `projects.services`: `EDITABLE = {name, purpose, owners, status}`, `TRACKED = (owners, status)`, `_validate`의 owner 검사를 owners 전원으로, `owners` 갱신은 `project.owners.set()`(M2M라 `update()` 밖). `project_stats`: `total`은 취소 제외, `blocked`는 `status="blocked"`.
- `tasks.services`:
  - `EDITABLE = {title, description, done_when, next_action, notes, assignee, priority, due_date, no_due_reason, project, stop_reason}`, `TRACKED = (assignee, due_date, project, priority, stop_reason)`.
  - `_validate`: priority 1~10, `stop_reason` 규칙(blocked면 필수, 멈춤 상태 아니면 빈 값 강제).
  - `update_text(task, field, value, actor)` 추가: `title/description/done_when/next_action/notes`만, version 불변, ChangeLog 없음.
  - `update_task`: 위 다섯 필드는 `update_text`로 보내고 나머지만 잠금 갱신.
  - `transition`: `ALLOWED` 재정의(미완료 5개끼리 자유, 미완료→done·cancelled, done→done noop, done·cancelled→todo·doing). blocked 진입 `reason` 필수, paused 선택, 둘 밖으로 나가면 `stop_reason=''`·`stopped_at=None`, 진입 시 `stopped_at=now`. 재개 사유 선택. 오류 문구는 README 규칙 1 문장.
  - `set_blocked` 삭제. `extend_due(task, new_date, reason, *, actor, source, token, expected_version)` 추가.
  - 댓글 함수 4개 삭제.
  - `today_add/today_remove` → `today_add`(excluded 해제 포함), `today_exclude`(직접 담기 삭제 + excluded 행), `today_restore_excluded`, `today_set_auto_pull(user, days)`. `today_view`: `items`(auto_pulled 플래그 포함, 정렬 규칙), `excluded_count`, `auto_pull_days`, `done_today`, `done_7d`, `focus`(첫 미완료), `counts`(due_today, overdue, review, blocked, my_open). `leftover`·`doing` 삭제.
  - `my_tasks_grouped` → `me_view(user, *, member, group, due, project, status, priority)`: 필터·그룹·프로젝트 하위 묶음·완료 뷰(doneToday/done7)까지 계산. 반환 `{title, hint, groups:[{title, count, empty_text, flat, projects:[{project, done, total, pct, tasks}], tasks}], read_only}`.
  - `search`: 미완료 판정을 `OPEN` 5개로.
- `tasks.brief.task_brief`: `is_blocked` → `stop_reason` 추가, `priority` int.
- `reports.services`: `blocked` 필터를 `status="blocked"`로, `commented` 제거, `by_project`에 `status`·`owners` 추가, `open` 판정 `OPEN` 5개.

### 4.4 GUIDE-01-3 (API)
- 스키마: `Status` 7개, `Priority = int`(1~10 검증), `ProjectStatus` 8개. `ProjectOut.owners: list[UserBrief]`, `target_date`·`repo_url` 삭제, `ProjectCreateIn/PatchIn.owner_ids: list[int]`. `TaskBriefOut.stop_reason`, `is_blocked` 삭제. `TaskOut`: `stop_reason`, `stopped_at`, `notes`; `blocked_*`·`comments` 삭제. `TaskPatchIn`: `notes`, `stop_reason` 추가. `BlockIn`·`CommentIn`·`CommentOut` 삭제. `ExtendIn {due_date, reason, version}`. `TodayOut` 재정의(§4.3 `today_view`), `TodaySettingsIn {auto_pull_days}`.
- 라우터: `POST /tasks/{id}/block`·`/comments` 삭제, `POST /tasks/{id}/extend` 추가. `list_tasks`의 `blocked` 파라미터 삭제(`status=blocked`로). today: `POST /today`(담기), `DELETE /today/{task_id}`(오늘 제외), `DELETE /today/excluded`(복원), `PATCH /today/order`, `PATCH /today/settings`.
- 5.7 표와 예시 갱신.

### 4.5 GUIDE-01-4 (웹) — 사실상 다시 쓴다
- 정적 파일: Pico 삭제. `app.css`에 토큰·타이포·간격·셸·레일·카드·행·pill·패널·모달·반응형 전부. `app.js`(바닐라, 100줄 안팎): 자동 저장 상태 텍스트(HX-Trigger `saved` 수신, 400ms/2.5s), 링크 복사, `#task-{id}` 해시 진입, 크게 보기 토글, `<dialog>` 열기·닫기, 상태 select에서 `blocked` 선택 시 즉시 전송 대신 패널 열고 사유 박스 표시, `htmx:responseError` 알림.
- URL: `/tasks/new`·`/projects/new` 페이지 삭제(프로젝트 인라인 폼·모달로). 추가: `tasks/<id>/row`(행 재렌더), `tasks/<id>/text/<field>`(자동 저장), `tasks/<id>/extend`, `tasks/<id>/stop-reason`, `today/exclude/<id>`, `today/restore`, `today/settings`, `team`(현재 팀으로 redirect), `projects/<id>/tasks`(인라인 생성). `tasks/<id>/block`·댓글 4개 삭제.
- 뷰: `today.py`(지표·빠른 추가·포커스 카드·목록·일정), `me.py`(`me_view` 호출만), `teams.py`(팀 현황), `projects.py`(모달·인라인 폼·목록·보드), `tasks.py`(패널·행·자동 저장·상태·연장·사유·체크리스트·링크). 규칙: 패널에서 팀 데이터가 바뀌면 응답에 `HX-Trigger: task-changed`, 행은 `hx-trigger="task-changed from:body" hx-get=".../row"`로 스스로 갱신(낡은 version 방지).
- 템플릿: `base.html`(셸 64px 헤더·내비 4개·빠른 추가·아바타 메뉴·프로젝트 레일 190px·본문·aside), `today.html`, `me.html`, `team.html`, `projects/detail.html`, `projects/_dialog.html`, `search.html`, `tasks/_row.html`(TaskRow2), `tasks/_panel.html`, `tasks/_checklist.html`, `tasks/_links.html`, `tasks/_stop.html`, `tasks/_extend.html`, `today/_list.html`, `today/_schedule.html`. 문구·크기·색은 README 표를 그대로 옮긴다.
- 6.10 수동 확인 목록을 새 화면 기준으로 다시 쓴다(목업 `python -m http.server 8765`와 나란히 비교, `.claude/launch.json`의 `mockup`).

### 4.6 GUIDE-01-5 (테스트)
- 삭제: 댓글·`set_blocked` 테스트. 개명: `test_done_clears_blocked_flag_and_logs` → `test_done_from_blocked_clears_stop_reason`. `test_reopen_requires_reason...` → `test_reopen_clears_completed_at_reason_optional`.
- 추가: `test_transition_blocked_requires_reason_paused_optional`, `test_leaving_stopped_clears_reason`, `test_priority_range_1_to_10`, `test_extend_due_rules`(뒤 날짜·사유 필수·이력 note), `test_update_text_does_not_bump_version`, `test_today_auto_pull_and_exclude`(N일 이내 자동, 제외, 복원, 정렬), `test_today_settings`, `test_me_view_filters_and_groups`, `test_project_owners_many_and_none`, `test_project_stats_total_excludes_cancelled`. API: `test_extend_endpoint`, `test_today_exclude_restore_settings`, `test_patch_notes_no_version_bump`.
- `test_weekly_shape`: 키 11개, counts 8개.

### 4.7 GUIDE-02 (Discord)
- `messages.STATUS` 7개, `notify.OPEN` 5개, `open_tasks`의 status 문자열, 막힘 플래그를 `status=="blocked"`로. `summarize`에서 `commented` 줄 삭제. conftest `task()` 헬퍼에서 `is_blocked` → `status`. 테스트 `test_blocked_task_included`는 `status="blocked"`로.
- (이후 개정) 웹훅 발송 전체가 봇으로 대체되었다. §8 마지막 항목을 본다.

### 4.8 GUIDE-03 (MCP)
- 도구 14개(§3 표). `set_blocked` 삭제, `add_comment` → `append_note`. `transition_task` 설명에 blocked 사유 필수. `create_task/update_task` priority int, `notes`·`stop_reason` 추가. 테스트 `test_tool_names_registered` 집합 갱신, `test_append_note_appends_with_version` 추가.

### 4.9 PLAN.md
- 상단에 "v0.4: 도메인·화면은 docs/IMPL-PLAN.md §3 결정표를 따른다" 한 줄. §3·§5·§6은 요약이므로 바꾸지 않고 결정표로 대체.

---

## 5. 목업 상태 → 서버 대응표

| 목업 `state` | 대응 |
|---|---|
| `screen`, `projectId` | URL (`/today`, `/me`, `/team`, `/projects/{id}`, `/search`) |
| `selectedId`, `panelOpen` | `hx-get /tasks/{id}/panel` + `hx-push-url /tasks/{id}`. 해시 `#task-{id}`도 동일 처리 |
| `wide` | 클라이언트(`app.js` + `localStorage`) |
| `focusNotes` | 패널 URL 쿼리 `?focus=notes` |
| `scheduleOpen`, `calMode`, `calDay` | 쿼리 파라미터 `schedule=1&cal=month&day=` |
| `view`, `includeClosed`, `q`, `searchClosed` | 쿼리 파라미터 |
| `viewMember`, `meFilter.*`, `groupBy` | 쿼리 파라미터 `member, due, project, status, priority, group` |
| `todayIds`, `excludedToday` | `TodayItem(excluded)` 날짜별 |
| `autoPullDays` | `User.auto_pull_days` |
| `quick`, `taskForm`, `projForm`, `extend`, `blockRequest/stopDraft` | 서버 폼. 오류는 부분 템플릿으로 되돌림 |
| `errors[taskId]` | 행 부분 템플릿의 `error` |
| `saveStatus` | `HX-Trigger: saved` → `app.js` |
| `tasks`, `projects`, `history` | DB |
| `T`, `WEEK_END`, `Y` | `common.dates` |

---

## 6. 실행 순서와 완료 조건

| 단계 | 담당 | 내용 | 완료 조건 |
|---|---|---|---|
| **0. 지시서 개정** | 상위 모델(이 세션 또는 다음 세션) | §4 항목 전부. 01-4는 새로 쓴다. 코드 블록은 실행 가능한 코드로 | GUIDE-00~03 diff 리뷰 완료. 결정표와 지시서 사이 모순 0 |
| **1. core** | 구현 모델, GUIDE-01 순서 | Step 0 git init·uv → 1 설정 → 2 모델·마이그레이션 → 3 services → 4 reports → 5 API → 6 web → 7 tests | `pytest` SQLite·Postgres 통과, `ruff` 0, `/api/docs` 전 엔드포인트, 수동 확인 목록 통과, 목업과 나란히 놓고 화면 비교 |
| **2. discord_service** | 구현 모델, GUIDE-02 | 그대로 | 테스트 통과, 실제 채널 test·deadlines·weekly 1회 |
| **3. mcp_server** | 구현 모델, GUIDE-03 | 그대로 | 테스트 통과, Claude Code·Codex CLI에서 `list_teams`, 배포 후 커넥터 2종 |
| **4. 배포·시범** | 사용자 + 구현 모델, GUIDE-04 | 그대로 | `pm.<도메인>/healthz`, 팀 생성·초대, Discord 계정 토큰, 2주 시범 |

1단계 안 Step 6(web) 권장 순서: `base.html`+`app.css` 셸 → `_row.html` → 오늘 → 상세 패널 → 내 태스크 → 프로젝트(인라인 폼·모달) → 팀 현황 → 검색 → 일정 카드 → 목업 밖 화면 스타일 정리.

병렬: 2·3단계는 1단계 Step 5(API)가 끝나면 로컬 core를 상대로 시작할 수 있다.

---

## 7. 기본값으로 채운 결정 (틀리면 0단계 전에 말해 줄 것)

1. 재개 사유는 선택(§3). SPEC 6.3은 필수라고 적혀 있다.
2. 프로젝트 `target_date`·`repo_url` 삭제. 저장소는 프로젝트 링크로.
3. Pretendard는 CDN 예외. 오프라인 환경이면 `PretendardVariable.woff2` 한 파일(약 2MB) 벤더링으로 바꾼다.
4. 다크 모드는 시스템 설정 자동, 토글 없음.
5. 타인 태스크 읽기 전용은 행의 빠른 동작만. 패널·API는 수정 가능.
6. 일정 카드는 1단계에 넣되 마지막. 시간표는 눈금+종일 목록만.
7. 부속 필드(제목·설명·완료 조건·다음 행동·진행 메모) 자동 저장은 version을 올리지 않는 last-write-wins.
8. 오늘 목록의 직접 담기는 날짜별(매일 초기화). 자동 담기가 이월 역할을 한다.
9. `/tasks/new` 페이지 삭제. 빠른 추가(오늘)와 인라인 폼(프로젝트) 두 경로만.
10. 팀이 둘 이상이면 아바타 메뉴에서 전환, 세션에 현재 팀 저장. 목업은 팀 하나 전제.
11. 오늘 목록 순서: 직접 담은 것(↑↓ 순서) → 자동 담긴 것(중요도 desc → 기한 asc → id) → 닫힌 것 뒤로. 지금 할 일 = 첫 미완료 항목. 목업은 전부 중요도순이라 ↑↓가 사실상 무효였는데, README의 "↑↓는 직접 고른 항목 순서만 바꿈"을 살리는 쪽으로 정했다.
12. 재개(done·cancelled → todo·doing)는 상태 select에서 바로 한다. 사유 입력 없음.
13. 담당자·프로젝트·기한 미정 사유 변경은 `/tasks/{id}/edit` 페이지(패널 더보기의 "수정 화면" 링크). 목업에 없는 화면이지만 SPEC의 담당자 변경 경로가 필요하다.
14. 팀 화면 URL은 `/team`(현재 팀으로 redirect) + `/teams/{id}`. 세션 `team_id`로 현재 팀을 기억한다.

---

## 8. 진행 상태

- **0단계 지시서 개정: 완료 (2026-09-10).** GUIDE-00·01-1·01-2·01-3·01-5·02·03·04 개정, 01-4 전면 재작성.
- **1단계 core: 완료.** Step 0~7. `pytest` SQLite·Postgres 16 통과(skip 0), `ruff` 0,
  `/api/docs` 엔드포인트, §6.14 수동 확인, 목업 다섯 화면 대조.
  (수치는 아래 '웹훅 → 봇 전환' 이후 기준으로 갱신: 테스트 145개, 엔드포인트 25개, 수동 21항목.)
- **2단계 discord_service: 완료(실제 채널 제외).** 29 passed. 컨테이너에서 실제 core에 붙여
  `deadlines`(중복 방지 포함)·`weekly`·`test`·`once`를 로컬 Webhook 싱크로 검증, 메시지 본문까지 확인.
  진짜 `DISCORD_WEBHOOK_URL`만 남았다. **→ 아래 '웹훅 → 봇 전환'으로 대체되었다.**
- **3단계 mcp_server: 완료(공개 커넥터 제외).** 16 passed. 도구 14개, 헤더·URL 두 인증 방식,
  `append_note`가 웹 패널에 이어 붙는 것, 이력 경로 `mcp`, 폐기 토큰 오류까지 확인.
  Claude Code는 `claude mcp list` → ✔ Connected, Codex CLI는 설정 형식 수용을 확인했다.
- **배포 산출물: 완료.** 이미지 3개 빌드, `db`·`web`·`mcp` 기동, `/healthz`, 정적 파일,
  `DEBUG=0` + 프록시 뒤 동작, 가입·초대·참여 플로우.
- **4단계 배포·시범: 대기.** Proxmox LXC, Cloudflare Tunnel, UptimeRobot, vzdump, 2주 시범은
  사용자 인프라·계정이 필요하다. GUIDE-04 Step 5~8 그대로 진행하면 된다.

- **추가 작업: 권한 검사 + 관리 화면 2개 (완료).** 렌즈 5개·회의론자 3명씩(에이전트 110개)으로
  권한 모델을 검사해 확정 2건을 고치고, 팀 관리자용 **알림 채널** 화면과 **팀원 관리** 화면을
  만들었다. Discord 발송 대상이 환경 변수에서 웹 화면으로 옮겨졌다(discord 서비스는 core API로 읽는다).
  **이 중 알림 채널 화면은 다음 항목에서 삭제되었다.**

- **추가 작업: Discord 웹훅 → 봇 전환 (완료, 2026-09-10).** 알림이 "팀 채널에 웹훅으로 게시"에서
  "**담당자 개인 DM + DM 평문 명령**"으로 바뀌었다. 바뀐 것과 그 이유:

  | 항목 | 전 | 후 | 왜 |
  |---|---|---|---|
  | 발송 | 팀 채널 웹훅 1건/태스크 | 담당자 DM, (종류, 담당자)로 묶어 사람당 하루 최대 4건 | 아침 DM 폭탄과 Developer Policy의 '원치 않는 반복 DM' |
  | 수신 | 없음 | `discord-bot` 컨테이너(discord.py 게이트웨이), DM 평문 5종 | 마감 DM에 그 자리에서 답장해 처리 |
  | 계정 연결 | 프로필에 Discord ID 수동 입력 | 웹 1회용 코드(10분) ↔ 게이트웨이 `author.id` 교환 | 손입력 값은 소유 증명이 없다. 봇이 그 값으로 사람을 찾는 순간 자격증명이 된다 |
  | 저장 | `teams.DiscordWebhook` 모델 + 관리 화면 | `DISCORD_CHANNEL_ID` 환경 변수 하나 | 비밀도 아닌 값 하나에 모델·화면·마스킹·전용 API가 붙어 있었다 |
  | 권한 | 봇 계정이 팀 **관리자**(웹훅 주소를 읽어야 했다) | 팀 **팀원** + `bot` 범위 토큰 | 봇은 이제 사람을 대신해 3개 동작만 한다 |
  | 비밀 | 웹훅 URL이 Postgres에 원문으로 | 봇 토큰·`CORE_TOKEN`이 `.env.discord`에만 | core는 Discord로 나가는 요청이 0건이 되었다 |
  | core 의존성 | — | **변동 없음** | 인터랙션 엔드포인트를 만들지 않아 서명 검증(pynacl)·세 번째 공개 호스트네임이 필요 없다. 이 설계의 가장 큰 이득 |

  마이그레이션 3개(`accounts 0002`·`tasks 0002`·`teams 0003`). `accounts 0002`는 기존
  `discord_user_id`를 **전부 비운다**(증명되지 않은 값을 자격증명으로 승격시키지 않는다) →
  전원이 DM `연결`을 하기 전까지 개인 DM 알림은 0건이다. `teams 0003`은 되돌릴 수 없다.
  테스트: core 145개(웹훅 13개 삭제, 연결·봇·프로필 19개 추가), discord_service는 리스너·명령
  테스트가 추가되었다. 개정한 문서: GUIDE-00·01-1·01-2·01-3·01-4·01-5·02·04, SPEC §8·§11.4,
  PLAN, README, `compose.yml`, `.env.example`, 신규 `.env.discord.example`.

구현 중 발견해 고친 것(지시서 코드 자체의 결함 포함) 22건과 지시서 반영 46곳은
[IMPL-REPORT.md](IMPL-REPORT.md)에 있다. 이 문서는 이제 결정 근거로만 참고한다.


---

**후속:** 2026-09-11부터의 작업(조직·팀 재구성과 GitHub 통합)은 [IMPL-PLAN-2.md](IMPL-PLAN-2.md)와 [GUIDE-V2-00-overview.md](GUIDE-V2-00-overview.md)로 이어진다. 이 문서의 "팀"은 개명 전 용어이며 지금의 **조직**을 뜻한다.