# E — 라운드 7 설계: 비개발 프로젝트·팀 View 권한·파일 첨부·인증 리팩토링·백업 (Fable, 2026-10-05)

기준 커밋 `dfa2b91`. 기준선 `cd core && uv run pytest -q` → **714 passed, 5 xfailed**(github/tests.py의 xfail은 1단계 GitHub 묶음이 푼다).
이 문서는 구현 지시서다. GUIDE-00의 규칙(업무 규칙은 `services`에만, 함수형 뷰, 새 의존성 없음, signals 금지, 테스트 skip 금지)이 그대로 적용된다.
형식·밀도는 `docs/IMPL-PLAN-5.md`를 따른다. 코드 조각은 **그대로 옮긴다**(이름·시그니처 변경 금지).

## 0. 전제

### 0.1 사용자 결정(2026-10-05, 확정)
- 비개발 구분 = 설정 항목 `project.dev_tools`. **생성 대화상자에서 저장소를 연결하면 자동으로 켬.**
- 비개발 **팀**이 있어야 하고, 그 팀에는 GitHub Teams 기능이 노출되지 않는다. 대신 조직 관리자가 **팀의 View 권한**을 정한다(§2에서 해석과 추천).
- 비개발 1차 범위 = 구현 가능한 전체. **파일 첨부 포함.** 산출물은 `ProjectDoc` 또는 파일.
- 반복 주기 없음 → 비주기 반복(템플릿·회차)으로 지원. 스케줄러 없음.
- 로그인 대대적 리팩토링(OIDC/Keycloak 대비) + 로그인 시도 제한(앱 코드).
- 운영 서버 작업은 범위 밖. 백업은 저장소 안 스크립트·문서만.
- P1(N+1·SSE·테스트 공백)도 이 라운드.

### 0.2 동시 진행 중인 다른 에이전트(겹치지 않게 한다)
| 에이전트 | 소유 파일(이 라운드에서 내 단계가 건드리면 안 되거나, 그들 병합 뒤에 건드리는 파일) |
|---|---|
| GitHub 묶음(1단계) | `core/github/**`, `web/views/github.py`, `web/views/github_retries.py`, `web/views/orgs.py`(초대·제거 198-217·260-278), `web/views/teams.py`(S1-2 GitHub 팀 UI), `templates/orgs/github.html`, `templates/orgs/team_detail.html`, `templates/orgs/_tabs.html`, `api/routers/github.py` |
| Discord·알림 묶음(2단계) | `web/views/discord.py`, `orgs/discord.py`, `config/settings.py`(`DISCORD_CLIENT_SECRET` 한 줄), `.env.example`, `discord_service/**`, `orgs/settings.py`(알림 항목 숨김), `templates/orgs/discord.html`, `api/routers/discord.py`(길드 보고 등) |

→ 내 단계 중 `teams.py`·`team_detail.html`·`orgs.py`·`api/routers/discord.py`·`discord_service`를 만지는 조각은 **그들 병합 뒤**로 미룬다(§7 표의 "선후"). `orgs/settings.py`·`config/settings.py`는 **그룹 끝에 덧붙이기만** 하면 충돌이 사소하다.

### 0.3 공통 원칙(이 라운드)
- 새 개념은 "필드 하나 + 서비스 함수 하나"로 시작한다. 별도 모델은 파일 첨부(`Attachment`)와 로그인 잠금(`LoginLock`)뿐이다.
- 마이그레이션 번호를 단계별로 고정한다(§7). 같은 앱의 마이그레이션을 두 단계가 동시에 만들지 않는다.
- 모든 새 규칙은 `services`에 두고 웹·API·MCP·Discord는 부르기만 한다.

---

## 1. (a) 비개발 프로젝트·기능 전체

### 1.1 예시 태스크 → 필요한 기능 유추

| 예시 | 필요한 것 | 기능 ID |
|---|---|---|
| 인스타그램 계정 생성 | 일회성 태스크. 결과는 계정 링크(링크 종류 "산출물"). **비밀번호는 적지 않는다**(거버넌스 문구·도움말) | F2 |
| 카드뉴스 템플릿 만들기 | 산출물 = 파일(시안)·문서. 이것이 뒤 회차의 **템플릿** | F12, F9 |
| 10월 1주차·2주차 카드뉴스 올리기 | 템플릿에서 **회차 만들기**(체크리스트·완료 조건 복사), 게시일 = 기한, 게시 증빙 = 링크/파일, 다음 회차는 끝난 뒤 사람이 만든다(주기 없음) | F4, F9, F12, F7 |
| 광고 부착물 미팅 | 태스크 + 회의록 연결(이미 있음) | - |
| 랜딩페이지·캐릭터 디자인 | 시안 파일 **버전**(v1→v2), 피드백은 진행 메모·반려 사유, 승인은 검토 대기→완료(지정 검토자 선택) | F12, F6, F10 |
| 굿즈(인형)·굿즈(키링) | 같은 계열 변형 묶음 = 원본 태스크를 **복제**하면 `parent`로 묶인다 | F4 |

과설계를 피한 것: 댓글 모델(피드백은 진행 메모·반려 사유로), 다단계 결재선(검토 1단계 + 지정 검토자로 충분, F13 제외), 고정 주기 스케줄러, 자격증명 저장소.

### 1.2 기능 범위(확정)

| ID | 기능 | 규모 | 단계 |
|---|---|---|---|
| F1 | `project.dev_tools` 스위치 + 조건부 표시 + 생성 대화상자(체크박스·저장소 입력) | S | A1 |
| F2 | 문구 일반화, 링크 종류 "산출물", "업무 거버넌스", 비개발 거버넌스 절 | S | A1 |
| F3 | 스킬·MCP 가이드 조건화 | S | A1 |
| F4 | 태스크 복제(`duplicate_task`) + 계열(`Task.parent`) | S | B |
| F5 | 요청 희망 기한(`WorkRequest.due_date`) | S | B(열)·C(나머지) |
| F6 | 반려 사유(`task.reject_reason_required`) | S | B |
| F7 | 프로젝트 달력(기한 + 마일스톤) | M | G |
| F8 | 비주기 반복 = F9 템플릿 + F4 회차. 자동 생성 없음 | - | B |
| F9 | 템플릿(`Task.is_template`) | S | B |
| F10 | 지정 검토자(`Task.reviewer`) | S~M | B(+J Discord) |
| F11 | 팀 단위 기본값 | - | **하지 않음**(조직 기본값 + 대화상자 체크박스로 충분) |
| F12 | 파일 첨부(`Attachment`, 버전) | M | D |
| F13 | 다단계 결재선 | - | 하지 않음 |

### 1.3 모델 변경

**orgs/settings.py** — `task` 그룹 끝, `project` 그룹 끝에 덧붙인다.
```python
Spec("task.reject_reason_required", "bool", False, "org", True, "task", "반려 사유 필수",
     "켜면 검토 대기에서 시작 전·진행 중으로 되돌릴 때 사유를 입력해야 합니다."),
Spec("project.dev_tools", "bool", True, "org", True, "project", "개발 도구 사용",
     "끄면 GitHub·API 문서 탭과 태스크의 GitHub 블록을 숨깁니다. 저장소가 연결된 프로젝트는 끌 수 없습니다."),
```
`project.default_view`의 choices에 `("calendar", "달력")` 추가(G 단계).

**projects/models.py** — 필드 없음. 속성 하나:
```python
@property
def dev_tools(self) -> bool:
    """개발 화면을 보일지. 저장소가 연결돼 있으면 설정과 무관하게 켬(데이터 숨김 방지)."""
    from orgs.settings import effective
    if getattr(self, "repo", None) is not None:
        return True
    return effective("project.dev_tools", org=self.org, project=self)
```
`STATUS_DESC` 일반화: `active` → "작업 진행 중", `done` → "계획한 작업을 모두 마침(유지 작업만 남음)". 나머지 그대로.

**tasks/models.py**
- 마이그레이션 `0005_link_kind_out`(A1): `Link.KINDS`에 `("out", "산출물")`을 `("doc", "문서")` 다음에 추가(열 길이 5 이내, choices만 바뀜).
- 마이그레이션 `0006_task_series_reviewer_request_due`(B):
```python
# Task
parent = models.ForeignKey("self", on_delete=models.SET_NULL, null=True, blank=True,
                           related_name="children", verbose_name="원본")
is_template = models.BooleanField("템플릿", default=False)
reviewer = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.SET_NULL, null=True,
                             blank=True, related_name="reviewing_tasks", verbose_name="검토자")
# WorkRequest
due_date = models.DateField("희망 기한", null=True, blank=True)
```
  - 제약 추가: `CheckConstraint(condition=~Q(is_template=True) | Q(status="todo"), name="task_template_is_todo")`.
  - 계열은 **평평하다**: 회차·변형의 `parent`는 항상 계열의 뿌리(뿌리의 `parent`는 None). 두 단계 이상 만들지 않는다.

**orgs/models.py** — `0009_team_dev_tools_and_wording`(A2):
```python
# Team
dev_tools = models.BooleanField("개발 도구(GitHub 팀 연결)", default=True)
```
같은 마이그레이션에 `Organization.governance` verbose_name "업무 거버넌스", `ChangeRequest.KINDS`의 `("governance", "업무 거버넌스")`를 담는다(AlterField뿐, DB 변경 없음).

### 1.4 서비스 함수

**projects/services.py**
```python
def create_project(*, org, name, actor, source="web", token=None, purpose="", owners=(),
                   status="preparing", teams=(), dev_tools: bool | None = None, visibility="org"):
    # dev_tools가 None이면 조직 기본값. 값이 있고 조직 기본값과 다를 때만
    # project.settings = clean("project", {"project.dev_tools": dev_tools}) 로 저장한다.
    # visibility는 §2.
```
- `set_project_settings`: `"project.dev_tools"`가 False로 들어왔고 `getattr(project, "repo", None)`이 있으면 `ServiceError({"project.dev_tools": "저장소가 연결된 프로젝트는 개발 도구를 끌 수 없습니다. 먼저 저장소 연결을 해제하세요."})`.
- **github/services.py `connect_repo`**(GitHub 에이전트 소유 파일 → A1에서는 손대지 않고, J 단계에서 3줄): 연결 성공 뒤 `effective("project.dev_tools", org=project.org, project=project)`가 False면 `set_project_settings(project, {**project.settings, "project.dev_tools": True}, actor=actor, source=source)`. 그 전까지는 `Project.dev_tools` 속성이 표시를 보장하므로 기능상 차이 없음(설정 화면 표기만 "끔"으로 남는다).

**tasks/services.py**
```python
@transaction.atomic
def duplicate_task(task, *, actor, source, token=None, title=None, due_date=None,
                   no_due_reason="", assignee=None, idempotency_key=None) -> Task:
    """복제·회차·변형 공통. 설명·완료 조건·다음 행동·중요도·체크리스트(전부 미완료)·링크·문서 연결을
    복사한다. 첨부 파일은 복사하지 않는다(회차는 새 파일을 만든다). 상태는 todo, 템플릿 아님.
    parent = task.parent or task (계열은 평평하다). create_task를 부르므로 ai.create_task·담당 규칙이 그대로 걸린다."""

def set_template(task, on: bool, *, actor, source="web", token=None) -> Task:
    """켤 때: status가 todo가 아니면 ServiceError({"is_template": "시작 전 상태에서만 템플릿으로 바꿀 수 있습니다."}),
    due_date=None, no_due_reason="템플릿". ChangeLog field="is_template". 끌 때: 플래그만 내린다."""
```
- `transition` 추가 규칙(기존 순서 안에서):
  1. `if task.is_template: raise ServiceError({"status": "템플릿은 상태를 바꾸지 않습니다. 회차를 만들어 진행하세요."})` — 맨 앞.
  2. 반려: `rejecting = task.status == "review" and new_status in ("todo", "doing")`. `if rejecting and effective("task.reject_reason_required", org=org, project=task.project) and not reason: raise ServiceError({"reason": "반려 사유를 입력하세요."})`. 이력 note는 기존처럼 reason.
  3. 지정 검토자: `if new_status == "done" and task.status == "review" and task.reviewer_id and actor.pk != task.reviewer_id and not is_admin(actor, org) and not is_owner(actor, task.project): raise ServiceError({"status": f"검토자 {task.reviewer.display_name}님 또는 프로젝트 관리자만 완료 처리할 수 있습니다."})`. 기존 self_review 규칙은 그대로.
- `update_task`: `LOCKED_FIELDS`·`TRACKED`에 `"reviewer"` 추가. `_validate`에 reviewer 검사: 조직 활성 멤버, `task.self_review`가 꺼져 있으면 `reviewer != assignee`.
- `_validate`: `is_template`인 태스크는 `due_date` 필수가 아니다(`task.due_required` 예외).
- 템플릿 제외 지점(각 한 줄 `.filter(is_template=False)`): `today_view`·`me_view`의 기본 쿼리, `search`, `reports.services._open_qs`, `projects.services.project_stats`·`roadmap`, `api/routers/tasks.list_tasks`(`include_templates: bool = False`), `web/views/projects.board_context`(템플릿은 별도 접이 목록 "템플릿 N"). `get_visible_task`는 그대로(템플릿 패널을 열 수 있어야 한다).

**tasks/work_requests.py**
- `create_request(..., due_date=None)` 저장. `accept(..., due_date=None)`: `due_date or req.due_date`로 `_task_from_request`. 알림 문구에 `· 희망 기한 10월 7일` 덧붙임(`fmt_md`).

### 1.5 API · 웹 · Discord · MCP · 스킬

**API(core/api)**
| 변경 | 내용 |
|---|---|
| `project_out` | `dev_tools: bool`, `visibility` 추가 |
| `task_brief`/`task_out` | `is_template`, `parent_id`, `reviewer: user_brief|None`, `children_count` 추가 |
| `POST /api/tasks/{id}/duplicate` | 본문 `{title?, due_date?, no_due_reason?, assignee_id?}` + `Idempotency-Key` → 201 `TaskOut`. 서비스 `duplicate_task` |
| `PATCH /api/tasks/{id}` | `is_template: bool|None`(→ `set_template`), `reviewer_id: int|None` |
| `GET /api/tasks` | `include_templates: bool = False`, `parent: int|None` |
| `POST /api/projects` | `dev_tools: bool|None`, `visibility` |
| `POST /api/requests`, `RequestOut` | `due_date` |
| `POST /api/requests/{id}/accept` | 기존 `due_date?`가 비면 요청의 희망 기한 사용 |

**웹**
- `projects/_tabs.html`: API 문서 탭 `{% if project.dev_tools %}`, GitHub 탭 `{% if github_enabled and project.dev_tools %}`.
- `tasks/_panel.html:98`: `{% if github_enabled and task.project.dev_tools %}`. `web/views/tasks.py::_panel_ctx`: `_git_ctx`는 `task.project.dev_tools`일 때만(아니면 `gh`·`gh_summary` 생략).
- `projects/_dialog.html`: "개발 도구 사용" 체크박스(초기값 `effective("project.dev_tools", org=org)`), 그 아래 `github_enabled and 사용자 GitHub 연결됨`일 때만 "GitHub 저장소(선택)" 입력(`repo.html`의 datalist `_pickable_repos` 재사용). `ProjectForm`에 `dev_tools = BooleanField(required=False)`, `repo_url = CharField(required=False, max_length=300)`. `project_new`: 생성 뒤 `repo_url`이 있으면 `gh_services.connect_repo(project=p, url=..., actor=request.user, source="web")`; `ServiceError`·`GitHubError`면 `messages.warning`(프로젝트는 이미 만들어짐)하고 저장소 탭으로 보낸다. 수정 대화상자에는 저장소 입력을 두지 않는다(GitHub 탭 몫).
- `tasks/_refs.html`: 마지막 안내 문구를 `{% if task.project.dev_tools %}PR·커밋은 저장소 연결이 자동으로 붙입니다. {% endif %}여기에는 …`로. `LinkForm(dev_tools: bool)` — False면 `issue` 종류 제외, `out` 포함.
- 패널 "더보기"에 [복제] 버튼 → `GET/POST tasks/<id>/duplicate` 대화상자(`tasks/_duplicate.html`: 제목(기본 원본 제목)·기한·담당). 템플릿이면 버튼 이름 "회차 만들기", 완료된 회차면 "다음 회차 만들기"(같은 끝점). 패널 메타에 "템플릿" 토글(`task_meta`가 `is_template`을 받아 `set_template`), "검토자" select(`task_meta` → `update_task({"reviewer": …})`).
- 패널 "같은 계열" 접이 블록: `task.parent or task`를 뿌리로 `children` 목록(번호·제목·상태·기한). `tasks/_series.html`.
- 반려 사유 입력: `task_status`가 `ServiceError`의 키가 `reason`이고 원 상태가 review일 때 `_stop.html`의 `block_pending` 패턴 그대로 `reject_pending=True`로 패널을 다시 그린다(숨은 `status` 값 유지, 제목 "반려 사유"). 새 템플릿 없이 `_stop.html`에 분기 추가.
- 요청 폼 `requests/new.html`: `<input type="date" name="due_date">`(선택). 상세·목록에 "희망 기한".
- 프로젝트 보드·목록: 템플릿은 기본 숨김, 상단 칩 "템플릿 N"으로 펼침.
- `orgs/governance.py` `DEFAULT_GOVERNANCE`: 제목 "업무 거버넌스 (기본안)", 1절 예시 "로그인 고치기" → "홍보물 만들기"(X) → "10월 1주차 카드뉴스 게시(인스타 링크 첨부)"(O)로 하나 교체, **9절 "비개발 프로젝트" 추가**: 권장 설정(검토 필수·본인 검토 금지·완료 조건 필수·독촉 2일·반려 사유 필수), 템플릿→회차 관례, 산출물은 문서·파일·"산출물" 링크, **계정 비밀번호·API 키는 태스크·문서·첨부에 적지 않는다**(공유 금고를 쓴다). 조직 화면 문구 "개발 거버넌스" → "업무 거버넌스"(`orgs/governance.html`, `_tabs.html`은 GitHub 에이전트 소유라 J 단계).

**Discord(discord_service, 2단계 병합 뒤 J)**: `/요청`에 선택 인자 `기한:YYYY-MM-DD`(`create_request.due_date`), `/상태`·`/완료` 응답에 반려·검토자 오류 문구 그대로 전달(core 메시지라 추가 작업 없음), `escalate.py` 검토 독촉 대상 = `task.reviewer`가 있으면 그 사람, 없으면 현행(owners).

**MCP(mcp_server/server.py)**: `duplicate_task(task_id, title=None, due_date=None, no_due_reason="", assignee_id=None, request_id=None)`, `update_task(... reviewer_id: int|None=None, is_template: bool|None=None)`, `list_tasks(... include_templates: bool=False)`, `create_request(... due_date: str|None=None)`, `create_project(... dev_tools: bool|None=None)`. WebMCP(`webmcp.js`)에 같은 이름. 도구 설명에 "템플릿은 상태를 바꾸지 않는다. 회차는 duplicate_task".

**스킬**: `skills/pm-start/SKILL.md:48` → "**저장소가 연결된 프로젝트(`GET /api/projects/{id}/repo`의 `connected: true`)일 때만** 브랜치 이름을 제안한다. 아니면 이 단계를 건너뛴다." `skills/pm-done/SKILL.md:22` → PR 확인도 같은 조건. `mcp_server/skill/SKILL.md:56` 절 첫 줄에 "`get_project`의 `dev_tools`가 false이거나 저장소가 없으면 이 절은 적용하지 않는다." `skills/pm/SKILL.md` 표에 duplicate·템플릿·검토자·요청 기한·첨부 끝점 추가.

### 1.6 테스트(핵심만, 파일 = 기존 모듈)
- `projects/tests.py`: dev_tools 조직 기본/프로젝트 재정의/저장소 연결 시 끌 수 없음/생성 시 dev_tools 저장(기본값과 같으면 settings 비어 있음).
- `web/tests.py`: dev_tools 끈 프로젝트에서 GitHub·API 탭·패널 GitHub 블록 없음, 저장소 연결 시 강제 표시, 생성 대화상자 체크박스·저장소 입력 흐름, 반려 사유 입력 패널, 복제 대화상자, 템플릿 칩.
- `tasks/tests.py`: duplicate(체크리스트 미완료 복사·링크·문서·parent 평평·AI 정책), set_template 규칙, 템플릿 transition 거부, 템플릿 집계 제외(project_stats·me·today·list_tasks), 반려 사유 필수, 검토자 완료 제한·관리자 예외, reviewer 검증.
- `tasks/test_work_requests.py`·`api/test_requests_api.py`: due_date 저장·수락 기본값.
- `mcp_server/tests`: 새 도구 4개 호출 모양.

**수용 기준**: 위 테스트 통과, 기존 714 전부 통과, `ruff` 0. dev_tools 끈 프로젝트의 태스크 패널 렌더에서 `repo_state()`가 호출되지 않는다(테스트에서 mock 호출 수 0).

---

## 2. (b) 비개발 팀 · 팀 View 권한

### 2.1 비개발 팀 = `Team.dev_tools`
- `TeamForm`에 `dev_tools = BooleanField(required=False, initial=True)`; `create_team(..., dev_tools=True)`, `update_team(..., dev_tools)`.
- `dev_tools=False`인 팀: `team_detail`에서 `gh_install=None`로 넘겨 GitHub 섹션 숨김, 멤버 표의 GitHub 열 `{% if team.dev_tools %}`, `_sync_member`·`team_edit`의 rename 호출 `if not team.dev_tools: return`, `team_github_link/create/unlink/reconcile`는 `Http404`, `github/writes.reconcile_team`은 `ServiceError({"team": "개발 도구를 끈 팀입니다."})`. 웹훅 `_on_team`·`_on_membership`은 `GitHubTeamLink`가 없으니 자연히 무시된다.
- 팀 목록 GitHub 열: 비개발 팀은 "—". API `_team_out`에 `dev_tools`.
- 팀 기반 프로젝트 기본값(F11)은 하지 않는다.

### 2.2 "팀에 대한 View 권한" 해석과 추천
| 해석 | 내용 | 비용 |
|---|---|---|
| **(A) 프로젝트 가시성 제한(추천)** | 프로젝트에 `visibility`를 두고 "담당 팀만"이면 **조직 관리자·프로젝트 관리자·담당 팀 멤버만** 본다. 관리자가 팀 화면에서 "이 팀이 볼 수 있는 비공개 프로젝트"를 체크해 View 권한을 준다. GitHub Teams가 저장소 접근을 주던 자리를 PM 안에서 대신한다("대신"이라는 결정 문구와 맞음) | M |
| (B) 팀 화면 비공개 | 팀 페이지(멤버·채널)를 팀원·관리자만 본다 | S, 그러나 비개발 팀에 주는 효용이 적음 |
| (C) 둘 다 | | M+S |

(A)로 설계한다. 질문 1에서 확인한다. (B)가 필요하면 `Team.is_private` 한 열로 나중에 더한다.

### 2.3 모델·서비스
**projects/models.py** — `0010_project_visibility`(F):
```python
VISIBILITIES = [("org", "조직 전체"), ("teams", "담당 팀만")]
visibility = models.CharField("공개 범위", max_length=5, choices=VISIBILITIES, default="org")
```
`teams` M2M의 뜻이 "담당 팀 = 보는 팀"이 된다. `visibility="org"`에서는 지금처럼 표시용이다.

**projects/services.py**
```python
def visible_projects(user, org=None):
    """user가 볼 수 있는 프로젝트. 보관 여부는 거르지 않는다(호출자가 거른다).
    Exists 서브쿼리로 쓴다 — M2M 조인 + distinct는 annotate·count와 어긋난다."""
    from orgs.models import OrgMembership, TeamMembership
    qs = Project.objects.filter(org=org) if org is not None else Project.objects.filter(org__in=orgs_of(user))
    admin = OrgMembership.objects.filter(user=user, role="admin", org_id=OuterRef("org_id"))
    owner = Project.owners.through.objects.filter(project_id=OuterRef("pk"), user_id=user.pk)
    member = TeamMembership.objects.filter(user=user, team__projects=OuterRef("pk"))
    return qs.filter(Q(visibility="org") | Exists(admin) | Exists(owner) | Exists(member))

def can_view_project(user, project) -> bool:
    return visible_projects(user, project.org).filter(pk=project.pk).exists()

def set_visibility(project, visibility: str, *, actor, source="web", token=None) -> Project:
    """조직 관리자만(require_admin). ChangeLog field="visibility"."""
```
- `create_project(visibility=...)`: `"teams"`면 `require_admin(actor, org)`.
- `update_project`의 `teams` 변경은 지금 `project.edit_by` 등급을 탄다(projects/services.py:156-157). 담당 팀 편집이 곧 View 권한 편집이 되므로, **`visibility="teams"`인 프로젝트의 `teams` 변경은 그 검사 앞에 `require_admin(actor, project.org)`를 더한다.** `visibility` 자체의 변경은 `set_visibility`로만(관리자).
- **tasks/services.py** `visible_tasks(user)` → `Task.objects.filter(project__in=visible_projects(user))`(select_related 유지). 태스크 경로(내 태스크·오늘·검색·API 목록·Discord 명령·MCP)가 전부 이 함수를 지나므로 **한 줄로 닫힌다**.
- `_validate`(create/update): `assignee`가 `can_view_project(assignee, project)`가 아니면 `ServiceError({"assignee": "담당자가 볼 수 없는 프로젝트입니다. 담당 팀에 넣거나 공개 범위를 바꾸세요."})`.
- `web/views/common.project_or_404` → `is_member` 대신 `can_view_project`. API `projects._project_or_404`(및 `docs`·`requests`·`settings` 라우터의 같은 검사) 동일. `projects/docs.get_visible_doc`, `notes/services.visible_notes`(프로젝트 회의록은 그 프로젝트를 볼 수 있을 때만), `work_requests.projects_for`(수락 시 프로젝트 후보), `QuickTaskForm`·`notes` 프로젝트 선택지, `context.shell` 레일, `project_index`, `org_detail`, `roadmap`(마일스톤·의존성도 보이는 프로젝트만), `capacity`, `portfolio.sources`, `api/routers/orgs.get_org`의 projects 목록, `api/routers/projects.list`, `api/routers/today`, `api/routers/discord.py`의 프로젝트 자동완성(`_actor` 기준) — **모두 `visible_projects`로 바꾼다.** 기준: `grep -rn "org\.projects\|Project\.objects\|\.projects\.filter\|\.projects\.all" core --include=*.py`(테스트·마이그레이션 제외 46곳)를 전부 훑어 "사람이 보는 목록"이면 바꾸고, 관리자 전용(`/ops`, `channels.py`의 허용 집합 계산, 웹훅)은 그대로 둔다.
- 보고서: `reports.services.org_status(org, *, viewer=None)`, `weekly(org, week_start, *, viewer=None)` — `viewer`가 None(봇 토큰·조직 채널 게시)이면 `visibility="teams"` 프로젝트를 **제외**한다. 웹·스킬은 `viewer=user`.
- 봇 토큰 주인(`CORE_TOKEN`)은 조직 관리자여야 비공개 프로젝트의 마감 DM이 나간다. `docs/OPERATIONS-DEPLOYMENT.md`에 한 줄 적는다(코드 변경 없음).

### 2.4 화면
- 프로젝트 대화상자: "공개 범위" 라디오(조직 관리자에게만 보임). "담당 팀만: 조직 관리자·프로젝트 관리자·담당 팀 멤버만 봅니다."
- 팀 상세(관리자) 새 섹션 "이 팀이 볼 수 있는 비공개 프로젝트": `org.projects.filter(visibility="teams", is_archived=False)` 체크박스 → `POST teams/<id>/visible-projects` → 각 프로젝트의 `teams`를 `update_project`로 갱신. 팀원 화면(`team_view.html`)에는 없음.
- 레일·목록에서 비공개 프로젝트에 🔒 배지.
- 조직 멤버가 아닌 사람에게는 지금처럼 404, 조직 멤버인데 볼 수 없으면 **404**(존재를 드러내지 않는다).

### 2.5 테스트·수용 기준
- 비공개 프로젝트: 담당 팀 아닌 멤버 → 웹 상세·레일·목록·검색·내 태스크·API `GET /api/projects/{id}`·`/api/tasks?project=`·문서·회의록·요청 수락 후보에서 보이지 않음(404/빈 목록). 담당 팀 멤버·프로젝트 관리자·조직 관리자는 보임. 바깥 사람을 담당자로 지정하면 ServiceError. `weekly(viewer=None)`에서 제외, `viewer=관리자`면 포함. 비개발 팀 상세에 GitHub 섹션·열 없음, GitHub 팀 끝점 404.
- 기존 테스트 전부 통과(기본값 `org`라 동작 불변).

---

## 3. (c) 파일 첨부·산출물

### 3.1 모델 — `tasks/models.py` `0007_attachment`(D)
```python
class Attachment(models.Model):
    KINDS = [("file", "파일"), ("out", "산출물"), ("proof", "증빙")]
    project = models.ForeignKey("projects.Project", on_delete=models.CASCADE, null=True, blank=True, related_name="attachments")
    task = models.ForeignKey(Task, on_delete=models.CASCADE, null=True, blank=True, related_name="attachments")
    file = models.FileField(upload_to=attachment_path)   # att/<org_id>/<uuid4 hex><ext>
    name = models.CharField("파일 이름", max_length=200)   # 원래 이름(표시·다운로드용)
    size = models.PositiveBigIntegerField()
    content_type = models.CharField(max_length=100)       # 확장자 표에서 정한 값. 업로드 헤더를 믿지 않는다
    sha256 = models.CharField(max_length=64)
    kind = models.CharField(max_length=5, choices=KINDS, default="file")
    note = models.CharField("메모", max_length=200, blank=True)   # "v2 — 색 수정"
    version = models.PositiveSmallIntegerField(default=1)
    replaces = models.ForeignKey("self", on_delete=models.SET_NULL, null=True, blank=True, related_name="replaced_by")
    created_by = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.PROTECT, related_name="+")
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ["-id"]
        constraints = [models.CheckConstraint(
            condition=(Q(project__isnull=False) & Q(task__isnull=True)) | (Q(project__isnull=True) & Q(task__isnull=False)),
            name="attachment_exactly_one_target")]
```
`attachment_path(instance, filename)`은 확장자만 원래 것을 쓰고 이름은 `uuid4().hex`다(경로 조작·이름 충돌 차단).

### 3.2 서비스 — 새 파일 `tasks/attachments.py`
```python
MAX_BYTES = 25 * 1024 * 1024          # 질문 3. 상수 하나로 둔다
MAX_PER_TARGET = 50
ALLOWED = {  # 확장자 → 저장 content_type. 여기 없는 확장자는 거부한다
    ".png": "image/png", ".jpg": "image/jpeg", ".jpeg": "image/jpeg", ".gif": "image/gif", ".webp": "image/webp",
    ".pdf": "application/pdf", ".txt": "text/plain", ".md": "text/markdown", ".csv": "text/csv",
    ".docx": "application/vnd.openxmlformats-officedocument.wordprocessingml.document",
    ".xlsx": "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
    ".pptx": "application/vnd.openxmlformats-officedocument.presentationml.presentation",
    ".hwp": "application/x-hwp", ".hwpx": "application/hwp+zip", ".zip": "application/zip",
    ".ai": "application/postscript", ".psd": "image/vnd.adobe.photoshop", ".mp4": "video/mp4",
}
INLINE = {"image/png", "image/jpeg", "image/gif", "image/webp", "application/pdf"}  # 브라우저에서 바로 보여도 되는 것. svg·html은 목록에 없다(스크립트 실행)

def add_attachment(*, actor, upload, kind="file", note="", task=None, project=None, replaces=None, source="web") -> Attachment
    # 순서: 대상 하나 검사 → _require_member(actor, 대상 프로젝트) → can_view_project → upload.size > MAX_BYTES 먼저(읽기 전) →
    # 확장자 허용 → 개수 상한 → 조직 할당량(org_usage_bytes + size > quota) → sha256을 chunks()로 계산 → 저장.
    # replaces가 있으면 같은 대상이어야 하고 version = replaces.version + 1.
def delete_attachment(att, *, actor)            # 올린 사람 또는 조직 관리자(문서와 같은 규칙). 파일도 지운다(att.file.delete)
def attachments_of(target) -> list[Attachment]  # 최신 버전만 앞에, 이전 버전은 replaced_by 체인으로 접어서
def can_download(user, att) -> bool             # can_view_project(user, 대상 프로젝트)
def org_usage_bytes(org) -> int                 # Attachment.objects.filter(Q(task__project__org=org)|Q(project__org=org)).aggregate(Sum("size"))
```
설정 항목(orgs/settings.py `org` 그룹 끝):
```python
Spec("org.attachment_quota_mb", "int", 2048, "org", False, "org", "첨부 파일 용량(MB)",
     "조직 전체 첨부 파일의 합계 상한입니다. 0이면 업로드를 막습니다.", lo=0, hi=102400),
```

### 3.3 저장 위치·설정·배포 파일
- `config/settings.py`: `MEDIA_ROOT = Path(os.environ.get("MEDIA_ROOT", BASE_DIR / "media"))`. `MEDIA_URL`은 두지 않는다(정적 서빙 금지, 아래 뷰로만 내려준다). `STORAGES.default`는 이미 `FileSystemStorage`.
- `compose.yml` `web`: `volumes: - media_data:/data/media`, `environment: MEDIA_ROOT: /data/media`; `volumes:`에 `media_data:`. `.gitignore`에 `/core/media/`.
- 운영 서버 반영(볼륨 생성)은 배포 단계 몫이며 이 라운드 범위 밖. 백업 스크립트(§5)가 이 볼륨을 포함한다.

### 3.4 웹·API·MCP
- URL(`web/urls.py`): `tasks/<id>/attachments`(POST), `projects/<id>/attachments`(POST), `attachments/<id>/delete`(POST), `attachments/<id>/<str:name>`(GET 다운로드). 뷰 파일 `web/views/attachments.py`(새 파일).
- 다운로드 뷰: `login_required` → `can_download` 아니면 404 → `FileResponse(att.file.open("rb"), as_attachment=att.content_type not in INLINE, filename=att.name, content_type=att.content_type)` + `X-Content-Type-Options: nosniff` + (인라인일 때) `Content-Security-Policy: sandbox`. URL의 `name`은 무시한다(보기 좋게만).
- `tasks/_refs.html`에 "첨부 파일" 블록: 목록(종류 배지·이름·크기·v번호·메모·올린 사람), [새 버전](같은 폼에 `replaces` 숨김값), [삭제], 업로드 폼(`enctype="multipart/form-data"` + `hx-encoding`). 프로젝트 파일은 `projects/docs.html` 옆 "파일" 섹션(같은 조각 템플릿 `tasks/_attachments.html`을 `target`만 바꿔 include).
- 도움말 한 줄: "비밀번호·API 키가 든 파일은 올리지 않습니다."
- API: `GET /api/tasks/{id}/attachments`, `POST /api/tasks/{id}/attachments`(multipart: `file`, `kind`, `note`, `replaces`), `GET /api/projects/{id}/attachments`, `POST …`, `DELETE /api/attachments/{id}`, `GET /api/attachments/{id}/download`(토큰 인증, 스킬이 받는다). `task_out`에 `attachments: [{id, name, size, kind, version, note, url, created_by, created_at}]`(최신 버전만).
- MCP: `list_attachments(task_id)`만(읽기). 업로드는 두지 않는다(이진 전송은 MCP 커넥터 쓰임새가 없다 — 필요해지면 base64 하나 추가). 스킬 `pm/SKILL.md` 표에 끝점 추가. Discord: 없음.

### 3.5 보안 점검표(테스트로 고정)
크기는 읽기 전에 `upload.size`로 거부(C-S4의 지적과 같은 꼴) · 확장자 허용 목록 밖 거부 · 저장 이름은 uuid · content_type은 서버 표 · 비이미지는 `attachment` 강제 · `nosniff` · 다운로드는 가시성 검사(조직 밖·비공개 프로젝트 → 404) · 삭제는 올린 사람·관리자 · 할당량 · 로그에 파일 이름만(경로·토큰 없음).

### 3.6 테스트·수용 기준
`tasks/test_attachments.py`(새): 정상 업로드(sha256·size·content_type), 25MB 초과 거부, `.svg`·`.html` 거부, 51번째 거부, 할당량 초과 거부, 새 버전 체인(version=2, `attachments_of`가 최신만), 삭제 권한, 다운로드 헤더(png 인라인+nosniff / zip attachment), 외부인·비공개 프로젝트 404, API 멀티파트 업로드·토큰 다운로드, `task_out.attachments`. 수용: 전부 통과 + 기존 통과.

---

## 4. (d) 인증 리팩토링 · 로그인 시도 제한

### 4.1 현황 한 장
| 층 | 지금 있는 것 | 위치 |
|---|---|---|
| 인증(누구인가) | 아이디·비밀번호(Django `LoginView` CBV + `ModelBackend`), GitHub OAuth 로그인·가입(`login_with_github`) | `web/urls.py:41`, `web/views/github.py:138-165`, `github/services.py:233` |
| 외부 식별자 매핑 | GitHub: `GitHubIdentity.github_id`(+토큰·저장소 목록). Discord: `User.discord_user_id`(코드 교환으로만 채움) | `github/models.py:23`, `accounts/models.py:18`, `accounts/services.py` |
| 세션 | DB 세션(기본), 쿠키 Secure(운영) | `config/settings.py` |
| 토큰 | `ApiToken`(read/write/bot, `for_ai`), OAuth 2.1 인가 서버가 같은 `ApiToken`을 발급(MCP 커넥터), 봇 토큰(`bot` 범위, 셸 발급) | `accounts/models.py:43`, `web/views/oauth.py`, `api/auth.py` |
| 인가(무엇을 할 수 있나) | 조직 역할(`is_member/is_admin/require_admin`), 프로젝트 등급(`is_owner/require_level`), 설정 레지스트리(`project.*_by`), AI 정책(`_ai_check`), 토큰 범위(`TokenAuth`), 본인 여부(`self_review` 등) | `orgs/services.py`, `projects/services.py`, `tasks/services.py`, `api/auth.py` |

문제: 인증 코드가 세 곳(`urls.py` CBV, `views/auth.py`, `views/github.py`)에 흩어져 있고 식별자 매핑이 두 모양(`GitHubIdentity` 행, `User` 열)이다. 로그인 제한이 없다. OIDC를 붙이려면 "외부 subject → User"를 찾는 자리와 "로그인 완료 처리" 자리가 하나여야 한다.

### 4.2 결정: OIDC는 **확장 지점만**, 지금 구현하지 않는다
근거: ① 연동할 IdP(Keycloak)가 아직 없다 — 검증할 대상 없이 짜면 설정값·클레임 매핑을 추측하게 된다. ② `mozilla-django-oidc` 같은 의존성은 GUIDE-00 허용 목록 밖이고, 그 라이브러리가 하는 일(디스커버리·code 교환·클레임→User)은 이미 GitHub 로그인이 같은 모양으로 하고 있어 필요할 때 `urllib`(github/client.py와 같은 방식)로 200~250줄이면 된다(ID 토큰은 토큰 끝점과의 TLS 직접 통신이라 서명 검증 대신 `iss·aud·exp·nonce` 검사로 충분, OIDC Core 3.1.3.7). ③ 지금 바꿀 가치가 있는 것은 **구조**(인증 모듈 하나, 식별자 매핑 함수 하나, 로그인 완료 함수 하나)이고, 그것이 끝나면 OIDC 추가는 "공급자 모듈 하나 + 표 하나 + 버튼 하나"가 된다. 인가는 Keycloak으로 옮기지 않는다 — 조직·프로젝트·팀 권한은 PM 데이터이고 Keycloak 역할과 동기화하면 두 곳이 진실이 된다.

### 4.3 지금 바꾸는 구조(E 단계)

**`accounts/auth.py`(새 파일) — 인증·로그인 완료·시도 제한**
```python
LOCK_POLICY = {          # kind: (실패 횟수, 창(분), 잠금(분))
    "user": (5, 15, 15),       # 같은 아이디(소문자) 기준. 존재하지 않는 아이디도 센다(존재 여부를 숨긴다)
    "ip": (30, 15, 60),        # 같은 IP 기준
    "signup_ip": (10, 60, 60), # 가입 생성 수
}

class LockedOut(Exception):
    def __init__(self, retry_after_minutes: int): ...

def client_ip(request) -> str:
    """X-Forwarded-For의 **맨 오른쪽** 값(앞단 프록시 하나가 덧붙인 값), 없으면 REMOTE_ADDR.
    왼쪽 값은 클라이언트가 지어낼 수 있다. compose는 web 포트를 프록시 IP에만 연다."""

def check_lock(kind: str, key: str) -> None          # 잠겨 있으면 LockedOut
def record_failure(kind: str, key: str) -> None      # 창이 지났으면 1부터, 한도에 닿으면 locked_until 설정. 하루 지난 행은 이때 지운다
def record_success(kind: str, key: str) -> None      # 행 삭제
def authenticate_password(request, username: str, password: str):
    """check_lock(user)·check_lock(ip) → django authenticate → 실패면 record_failure 둘 다, 성공이면 record_success(user). User 또는 None."""
def login_user(request, user, method: str) -> None:
    """django.contrib.auth.login + request.session["auth_method"] = method ("password" | "github" | 나중에 "oidc").
    모든 로그인 경로가 이 함수를 지난다 — OIDC 로그아웃(RP-initiated)이 method를 봐야 한다."""
def logout_user(request) -> None
def active_locks() -> list[LoginLock]                 # /ops 표시용
```
모델 `accounts/models.py` `0005_loginlock`:
```python
class LoginLock(models.Model):
    kind = models.CharField(max_length=10)
    key = models.CharField(max_length=150)
    failures = models.PositiveSmallIntegerField(default=0)
    window_started_at = models.DateTimeField()
    locked_until = models.DateTimeField(null=True, blank=True)
    updated_at = models.DateTimeField(auto_now=True)
    class Meta:
        constraints = [models.UniqueConstraint(fields=["kind", "key"], name="loginlock_kind_key")]
```
캐시가 아니라 표인 이유: 캐시 백엔드가 LocMem이라 gunicorn 워커(2개)마다 따로 센다. 표는 워커 공통·재시작에 살아남고 `/ops`에서 볼 수 있다. 관리 명령 `accounts/management/commands/unlock_login.py <username|ip>`(행 삭제).

**`accounts/identity.py`(새 파일) — 외부 식별자 매핑 facade**
```python
PROVIDERS = ("github", "discord")

def resolve(provider: str, subject: str):
    """subject(GitHub id·Discord snowflake)로 활성 User를 찾는다. 없으면 None.
    github → GitHubIdentity.github_id, discord → User.discord_user_id(+discord_linked_at not null).
    # ponytail: 저장은 두 곳에 그대로 둔다. 세 번째 공급자(oidc)가 생기면 ExternalIdentity 표(§4.4)를 만들고
    # 이 함수만 그 표를 먼저 보게 바꾼다."""
def identities(user) -> dict[str, str]     # {"github": "@login", "discord": "111…"} 프로필 화면용
```
호출 지점 교체: `accounts/services.user_by_discord_id` → `identity.resolve("discord", …)` 위임, `github/services.login_with_github`의 조회 → `identity.resolve("github", str(github_id))`(GitHub 에이전트 파일이므로 J 단계에서 한 줄). 연결·해제 함수(`link_discord`, GitHub callback)는 그대로.

**웹 뷰** `web/views/auth.py`
- `login_view(request)`(함수형, CBV 제거 — GUIDE-00 "클래스 기반 뷰 금지"와도 맞춘다): GET은 `LoginForm` 렌더; POST는 `authenticate_password` → `LockedOut`이면 폼 오류 "로그인 시도가 너무 많습니다. {n}분 뒤 다시 시도해 주세요." → None이면 "아이디 또는 비밀번호가 맞지 않습니다."(같은 문구) → 성공 시 `login_user(request, user, "password")`, `next`(`url_has_allowed_host_and_scheme`) 또는 `user.settings["user.start_page"]`. `LoginForm`은 `forms.Form(username, password)`로 바꾼다(`AuthenticationForm.clean`이 먼저 인증해 버려 잠금 순서를 어긴다). 템플릿 `auth/login.html`은 `_fields.html` 그대로.
- `logout_view`(POST만) → `logout_user`. `urls.py`의 `LoginView`·`LogoutView`를 바꾼다.
- `signup`: 생성 전에 `check_lock("signup_ip", ip)`, 생성 뒤 `record_failure("signup_ip", ip)`(생성 횟수를 세는 용도), `login_user(request, user, "password")`.
- `github._finish_login`: `login(...)` → `login_user(request, identity.user, "github")`(GitHub 에이전트 파일 → J 단계).
- `/ops`(superuser): 활성 잠금 표(kind·key·locked_until) + [해제] 버튼(`POST ops/unlock`).

**토큰·세션 소소**
- OAuth 2.1로 발급한 `ApiToken`은 `expires_at = now + 90일`(C-S4). 커넥터는 만료 뒤 다시 '연결'한다(refresh_token은 두지 않는다).
- `config/settings.py`: `SESSION_COOKIE_AGE = 14 * 24 * 3600`, `SESSION_COOKIE_HTTPONLY = True`(기본값 명시), 주석으로 "세션은 Django DB 세션. OIDC를 붙여도 세션은 그대로이고 로그아웃만 IdP로 넘긴다".
- 봇 토큰·MCP Bearer·API 토큰은 **서비스 자격**으로 분류만 하고 바꾸지 않는다. 32바이트 난수라 시도 제한 대상이 아니다(문서에 적는다).

**인가 지도(코드 이동 없음)**: 아래 표를 `docs/`가 아니라 `accounts/auth.py` 모듈 docstring에 적는다. 조직 역할(orgs/services) → 프로젝트 등급(projects/services.require_level) → 가시성(projects/services.visible_projects, §2) → 토큰 범위(api/auth) → AI 정책(services `_ai_check`). "Keycloak이 와도 이 표는 PM에 남는다. IdP는 1행(인증)만 맡는다."

### 4.4 나중 단계(OIDC) 명세 — 이 라운드에 구현하지 않음
- `accounts/models.ExternalIdentity(user FK, provider: "oidc", subject: str, email, display, linked_at, claims JSON)` unique(provider, subject). 이때 `identity.resolve`가 이 표를 먼저 본다.
- `accounts/providers/oidc.py`: `OIDC_ISSUER`·`OIDC_CLIENT_ID`·`OIDC_CLIENT_SECRET` env, 디스커버리 문서 캐시, auth code + PKCE + state + nonce, `urllib`로 토큰 끝점, ID 토큰 `iss·aud·exp·nonce` 검사, `userinfo`로 보강. 첫 로그인은 `User(set_unusable_password)` 생성, **같은 이메일 자동 연결 금지**(GitHub와 같은 규칙), 기존 계정은 로그인 뒤 프로필에서 연결.
- 로그인 화면 "SSO로 로그인" 버튼, `AUTH_PASSWORD_LOGIN=0`이면 비밀번호 폼 숨김, 로그아웃은 `auth_method == "oidc"`면 `end_session_endpoint`로.
- MCP OAuth: PRM의 `authorization_servers`에 Keycloak을 넣을지는 그때 결정(지금 인가 서버는 core).

### 4.5 테스트(`accounts/tests.py`, `web/tests.py`)
5회 실패 → 6번째는 올바른 비밀번호여도 잠김 문구·로그인 안 됨 / 성공하면 카운터 삭제 / 15분 지나면 창 초기화 / 존재하지 않는 아이디도 셈 / IP 30회 잠금 / `X-Forwarded-For: a, b` → `b` / 가입 11번째 거부 / 로그아웃 GET 405 / `/ops` 잠금 표·해제 / `identity.resolve` 두 공급자 / OAuth 발급 토큰 `expires_at` 90일 / `auth_method` 세션 값. 수용: 통과 + 기존 로그인·가입·GitHub 로그인 테스트 통과.

---

## 5. (e) 백업 스크립트(저장소 안, 운영 반영은 범위 밖)

새 파일 3개(Sonnet, I 단계):
- `scripts/backup.sh`(bash, LXC 호스트 cron용. `set -euo pipefail`):
  - 입력 env: `PM_DIR=/opt/project-manager`, `BACKUP_DIR=/srv/pm-backups`, `KEEP_DAYS=30`, `OFFSITE_DIR=`(비면 생략; 다른 스토리지 마운트 경로).
  - `docker compose -f $PM_DIR/compose.yml exec -T db pg_dump -U pm -d pm -Fc > $BACKUP_DIR/db-$STAMP.dump`
  - 볼륨 tar: `media_data`, `discord_data`, `discord_bot_data`(발송 이력 — SPEC 11.2 "복원 후 과거 알림 재발송 방지")를 `docker run --rm -v <vol>:/v:ro -v $BACKUP_DIR:/b alpine tar czf /b/<vol>-$STAMP.tgz -C /v .`
  - `sha256sum` 기록, `find $BACKUP_DIR -type f -mtime +$KEEP_DAYS -delete`, `OFFSITE_DIR`이 있으면 `rsync -a --delete`.
  - 실패하면 비0 종료(cron 메일/로그로 드러남). 토큰·비밀번호를 출력하지 않는다.
- `scripts/restore-test.sh`: 최신 `db-*.dump`를 임시 `postgres:16-alpine` 컨테이너에 `pg_restore`하고 `SELECT count(*) FROM tasks_task, accounts_user`를 찍은 뒤 컨테이너를 지운다. 성공 시 `OK <dump> tasks=<n> users=<m>`.
- `docs/BACKUP.md`: cron 한 줄(`15 4 * * * /opt/project-manager/scripts/backup.sh >> /var/log/pm-backup.log 2>&1`), 보존 30일·분리 보관 원칙, **전체 복구 절차**(web 중지 → `dropdb/createdb` → `pg_restore` → 볼륨 tar 풀기 → 기동 → `/healthz`), 복구 시험은 분기 1회 + 첫 배포 때 1회, 확인 목록(SPEC 11.2 항목 대조).
- 테스트: `bash -n` 문법 검사만(셸 스크립트는 CI 없음). 수용: 문서에 SPEC 11.2 8개 항목이 전부 대응된다.

---

## 6. P1 개선 배치(H 단계)

| 항목 | 내용 | 담당 |
|---|---|---|
| N+1 | `common.rows_for/row_ctx`: 호출자가 `prefetch_related("checklist")`, `me.py`가 행 정보를 한 번만 만든다. `project_stats` 루프 3곳(`orgs.org_detail`은 이미 계산한 `org_status()["by_project"]`를 쓴다, `me_view`·`roadmap`은 새 `project_stats_bulk(project_ids) -> dict[int, dict]` 한 번), `orgs.org_teams/_member_teams`는 `annotate(Count("members"), Count("projects"))`+팀장 prefetch, `serialize.project_out(p, stats=None)`에 미리 계산값 전달. 테스트: `CaptureQueriesContext`로 데이터 2개와 10개의 쿼리 수가 같음을 고정 | Opus |
| SSE 상한 | `events.py`: 모듈 전역 `_active: dict[int, int]` + `threading.Lock`, `MAX_STREAMS_PER_USER = 3`. 초과면 `retry: 30000\n\n`만 보내고 닫는다(브라우저가 30초 뒤 재시도). `finally`에서 감소. `entrypoint.sh` `--threads 32`. 테스트: 같은 사용자 4번째 스트림이 즉시 끝남 | Opus |
| 테스트 공백 T1 | `tasks/decision_services.py`(create·confirm·reject·list·supersede), `portfolio/drafts.py`·`sources.py`, `github/pr_context.py` — 서비스 단위 테스트 | Sonnet |
| 테스트 공백 T2 | 웹 상태 변경·권한: 프로젝트 보관·복원·삭제, 멤버 역할·제거, 체크리스트·링크, 마일스톤·의존성, 설정 등급 거부. 이 라운드 새 화면(복제·템플릿·첨부·비공개 프로젝트) 권한 경로 포함 | Sonnet |

---

## 7. 구현 단계 표

| 단계 | 내용 | 담당 | 선후 | 마이그레이션 | 주로 고치는 파일 | 충돌 주의 |
|---|---|---|---|---|---|---|
| **A1** 비개발 기반(프로젝트 쪽) | F1(Spec·속성·탭·패널·대화상자·저장소 입력)·F2(문구·Link out·STATUS_DESC·거버넌스 기본안 9절)·F3(스킬 3곳) | Opus | 바로 시작 | `tasks 0005` | `orgs/settings.py`(task·project 그룹 끝), `projects/models.py`, `projects/services.py`(create_project·set_project_settings), `tasks/models.py`(KINDS), `web/forms.py`, `web/views/projects.py`, `web/views/tasks.py`(`_panel_ctx`), `templates/projects/{_tabs,_dialog}.html`, `tasks/{_panel,_refs}.html`, `orgs/governance.py`, `orgs/governance.html`, `api/serialize.py`, `api/schemas.py`, `api/routers/projects.py`, `mcp_server/server.py`(create_project), `skills/*` | `orgs/settings.py`는 2단계(Discord)도 만진다 → 그룹 끝 덧붙이기만. `_tabs.html`(orgs)·`connect_repo`는 손대지 않는다(J) |
| **E** 인증 리팩토링·로그인 제한 | §4.3 전부(`github.py` 한 줄 제외) | Opus | 바로 시작, A1과 병렬 | `accounts 0005` | `accounts/{auth,identity,models,services}.py`, `accounts/management/commands/unlock_login.py`, `web/views/auth.py`, `web/views/ops.py`, `web/urls.py`(login·logout·ops 줄), `web/forms.py`(LoginForm), `web/views/oauth.py`(expires_at), `config/settings.py`(세션 2줄), `templates/{auth/login,ops}.html` | `web/forms.py`는 A1도 만진다(다른 클래스; 순차 병합). `config/settings.py`는 2단계가 한 줄 추가 → 끝에 덧붙임 |
| **C** 요청 희망 기한(열 제외) | F5의 서비스·웹·API·MCP(열은 B가 만든다 → **B의 마이그레이션 뒤에 테스트 실행**) | Sonnet | B 마이그레이션 커밋 뒤 | 없음 | `tasks/work_requests.py`, `web/views/work_requests.py`, `templates/requests/{new,detail,index}.html`, `api/routers/requests.py`, `api/schemas.py`(RequestIn/Out), `mcp_server/server.py`(create_request) | Discord `/요청` 인자는 J |
| **I** 백업 | §5 | Sonnet | 바로 시작 | 없음 | `scripts/backup.sh`, `scripts/restore-test.sh`, `docs/BACKUP.md` | 없음 |
| **B** 태스크 확장 | F4·F6·F8/F9·F10 + `WorkRequest.due_date` 열 | Opus(A1과 같은 담당) | A1 뒤 | `tasks 0006` | `tasks/models.py`, `tasks/services.py`, `api/routers/tasks.py`, `api/schemas.py`, `api/serialize.py`, `web/views/tasks.py`, `web/urls.py`(duplicate), `templates/tasks/{_panel,_stop,_duplicate,_series}.html`, `templates/projects/{detail,_board}.html`(템플릿 칩), `reports/services.py`(`_open_qs`), `projects/services.py`(stats 제외), `mcp_server/server.py`, `web/static/webmcp.js`, `skills/pm/SKILL.md` | `tasks/services.py`는 F·H도 만진다 → B→F→H 순차 |
| **A2** 비개발 팀 | `Team.dev_tools`·팀 대화상자·팀 상세/목록 GitHub 숨김·끝점 404·API | Opus | **GitHub 묶음(1단계) 병합 뒤** | `orgs 0009` | `orgs/models.py`, `orgs/services.py`(create/update_team), `web/forms.py`(TeamForm), `web/views/teams.py`, `templates/orgs/{_team_dialog,team_detail,teams}.html`, `github/writes.py`(reconcile 가드), `api/routers/orgs.py`(_team_out) | 1단계가 `teams.py`·`team_detail.html`을 고친다 → 반드시 그 뒤 |
| **G** 프로젝트 달력 | F7 | Sonnet | A1 뒤 | 없음 | `web/views/projects.py`(새 뷰 1개), `web/urls.py`, `templates/projects/calendar.html`, `templates/projects/detail.html`(보기 전환), `orgs/settings.py`(default_view choice) | `projects.py`·`urls.py`를 B·D도 만진다 → 순차 병합(작은 추가) |
| **D** 파일 첨부 | §3 | Opus | B 뒤 | `tasks 0007` | `tasks/models.py`, `tasks/attachments.py`(새), `web/views/attachments.py`(새), `web/urls.py`, `templates/tasks/{_refs,_attachments}.html`, `templates/projects/docs.html`, `api/routers/tasks.py`·`projects.py`·새 `attachments.py`, `api/serialize.py`, `config/settings.py`(MEDIA_ROOT), `compose.yml`, `.gitignore`, `orgs/settings.py`(org 그룹 끝), `mcp_server/server.py`(list_attachments), `skills/pm/SKILL.md` | `config/settings.py`·`compose.yml`은 2단계 배포 조건(`DISCORD_CLIENT_SECRET`)과 같은 파일 → 덧붙이기 |
| **F** 팀 View 권한 | §2.3~2.4 | Opus | B·A2 뒤(1단계 병합 뒤) | `projects 0010` | `projects/{models,services}.py`, `tasks/services.py`(visible_tasks·_validate), `web/views/common.py`, `web/views/{projects,orgs,roadmap,me,today,notes,docs,work_requests,search,portfolio,teams}.py`, `web/context.py`, `web/forms.py`(QuickTaskForm), `api/routers/{projects,orgs,docs,requests,settings,today,discord}.py`, `reports/services.py`, `notes/services.py`, `projects/docs.py`, `tasks/work_requests.py`, `templates/projects/_dialog.html`, `templates/orgs/team_detail.html`, `templates/base.html`(레일 🔒) | 가장 넓음. `orgs.py`·`api/routers/discord.py`는 1·2단계 병합 뒤. H(N+1)와 같은 파일이므로 H는 F 뒤 |
| **H** P1 | §6 | N+1·SSE Opus, T1·T2 Sonnet 2갈래 병렬 | F 뒤 | 없음 | `web/views/{common,me,orgs,roadmap,events}.py`, `projects/services.py`, `api/serialize.py`, `api/routers/projects.py`, `entrypoint.sh`, 테스트 파일들 | T1·T2는 테스트 파일만 → 서로·H와 충돌 없음 |
| **J** 병합 뒤 마무리 | `connect_repo` dev_tools 켜기(3줄), `login_with_github`·`_finish_login` 교체(2줄), `orgs/_tabs.html` "업무 거버넌스", Discord `/요청 기한`, `escalate.py` 검토자 우선, 운영 문서 한 줄(봇 토큰 주인=관리자) | Opus | 1·2단계와 A~H 전부 병합 뒤 | 없음 | `github/services.py`, `web/views/github.py`, `templates/orgs/_tabs.html`, `discord_service/{slash,escalate}.py`, `docs/OPERATIONS-DEPLOYMENT.md` | 다른 에이전트 소유 파일만 모아 마지막에 |

병렬 묶음: **{A1, E, I} → {B, G} → C(B 마이그레이션 뒤) → {A2(1단계 병합 뒤), D} → F → H → J.**
전체 테스트 재실행과 병합은 오케스트레이터가 한다. 검토(Sol)는 §4(E)·§2(F)·§3(D) 세 번으로 제한하고 투입 전 사용량을 확인한다.

마이그레이션 번호 고정: `accounts 0005`(E) · `orgs 0009`(A2) · `tasks 0005`(A1) · `tasks 0006`(B) · `tasks 0007`(D) · `projects 0010`(F). 1·2단계 에이전트가 같은 앱에 마이그레이션을 만들면 번호를 당겨 조정한다(지금 계획엔 없음).

---

## 8. 사용자에게 물을 것(3개)

| # | 질문 | 선택지 | 추천 |
|---|---|---|---|
| 1 | "팀에 대한 View 권한"의 뜻 | (a) 프로젝트 공개 범위 "담당 팀만"(관리자·담당 팀 멤버만 봄, 팀 화면에서 볼 프로젝트 체크) (b) 팀 화면 자체를 팀원·관리자만 보게 (c) 둘 다 | **(a)** — "GitHub Teams 대신"이라는 결정과 맞고, 비개발 팀의 실제 요구(남의 프로젝트가 안 보임/내 프로젝트를 가림)를 해결한다. (b)는 나중에 열 하나 |
| 2 | 시안 승인자 | (a) 프로젝트 관리자만(현행) (b) 태스크별 지정 검토자 + 관리자 예외(F10) | **(b)** — 디자인 시안은 요청한 팀(마케팅)이 승인하는 경우가 많다. 열 하나·규칙 한 줄 |
| 3 | 첨부 파일 상한 | (a) 파일 25MB · 조직 2GB(기본, 설정에서 변경) (b) 파일 100MB · 조직 10GB (c) 원본(.ai·.psd)은 드라이브 링크, PM엔 미리보기·PDF만(25MB) | **(a)** — LXC 디스크와 백업 크기를 생각하면 원본 디자인 파일은 드라이브에 두고 PM엔 검토용을 올리는 쪽이 운영이 쉽다. 수치는 상수·설정이라 바꾸기 쉽다 |

묻지 않고 추천대로 확정: OIDC는 확장 지점만(§4.2) · 잠금 정책 5회/15분→15분, IP 30회/15분→1시간, 가입 IP 10회/시간 · 템플릿·회차는 `Task.parent`+`is_template`(별도 모델 없음) · 댓글 모델 없음 · 다단계 결재 없음 · 팀 기반 기본값 없음 · MCP 업로드 없음 · 첨부 허용 확장자 표(§3.2) · 비공개 프로젝트는 조직 채널 주간 보고에서 제외 · 비공개 프로젝트를 못 보는 멤버에게 404.

## 9. 확인 불가
- 운영 LXC의 디스크 여유·볼륨 위치(첨부 상한·백업 보관 위치의 실제 값) — SSH·VPN 필요, 범위 밖.
- 1·2단계 에이전트가 실제로 바꾼 파일 목록(진행 중) — 병합 시점에 §0.2 표를 다시 대조한다.
- 마케팅·디자인 팀의 실제 승인자 구성과 파일 크기 분포 — 질문 2·3으로 확인.
- Postgres에서의 `Exists` 서브쿼리 성능(SQLite로만 테스트) — 프로젝트 수가 수십이라 문제 없을 것으로 보나 실측은 하지 않았다.
