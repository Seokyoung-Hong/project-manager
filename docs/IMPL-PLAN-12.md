# G — 라운드 12 설계: 상위·하위 태스크(한 겹) (Fable, 2026-10-07)

기준: Ochestration `ae68df5`(P1a·D1·D3·S1·P1b 병합). 근거 표기는 `파일:줄`(S1 기준 `a9885bb`에서 읽었고 P1b는 `github/*`·`_git_ctx`만 바꿨다). 코드·git은 손대지 않았다(읽기만).
사용자 요구(확정): **"태스크를 그룹화하는 기능. 중첩 형태의 태스크. 단 태스크 중첩은 한 겹까지만."** 그리고 **"'사람별로 나누기'를 하위 태스크를 만드는 방식으로 바꾸자는 게 내 목적이다."** → 상위 태스크 ↔ 하위 태스크(하위의 하위 없음), 나누기 결과 = 원래 태스크의 하위 태스크(계열 아님).

---

## 0. 결론 한 줄

새 열 `Task.group`(상위 태스크, 자기 참조 FK, `SET_NULL`)을 더한다. 기존 `Task.parent`(계열 = 복제·회차의 원본, `tasks/models.py:63-71`)는 복제·회차용으로만 남긴다. **"사람별로 나누기"(S1)는 계열이 아니라 하위 태스크를 만든다**(원본 = 상위, 체크리스트 흉내는 진행률로 대체 — 사용자 확정). 한 겹 제한은 DB(자기 참조·템플릿 금지)와 서비스(`set_group` 한 곳)가 지킨다. 상위는 진행률(하위 완료 비율)만 보이고, 하위가 모두 끝나면 **완료를 제안**할 뿐 자동 완료하지 않는다. 집계는 **잎만 센다**(하위가 있는 상위는 뺀다).

---

## 1. 현황(코드로 확인)

| 항목 | 근거 |
|---|---|
| `Task.parent` = 계열. "평평하다 — parent는 항상 계열의 뿌리" | `tasks/models.py:62-71` |
| 계열을 만드는 곳: `duplicate_task`(복제·회차, `parent = task.parent or task`) | `tasks/services.py:731-784` |
| S1 `split_by_assignees`: `duplicate_task`로 사람별 태스크를 만들고 **원본 체크리스트를 'TASK-n 이름' 목록으로 바꾸고** 진행 메모에 한 줄 | `tasks/split.py:44-97` |
| 계열 화면: 패널 `_series.html`("같은 계열 n"), `_series()`는 `visible_tasks`로 거름 | `web/views/tasks.py:138-146`, `templates/tasks/_series.html` |
| API `parent_id`·`children_count`·`?parent=` / MCP `list_tasks(parent_id)` / 스킬 "같은 계열로 묶는다" | `api/serialize.py:33-37,67`, `api/schemas.py:48,96`, `api/routers/tasks.py:74-84`, `mcp_server/.../server.py:362-384`, `skills/pm/SKILL.md:105-106` |
| 낡은 안내 "core에는 상위·하위 태스크 관계가 없다 … `상위: TASK-N`" | `skills/pm/SKILL.md:195-196`, `skills/pm-split/SKILL.md` 4·5단계 |
| 용어표: "하위 태스크·부모 태스크·에픽"은 쓰지 않는 말 | `docs/IMPL-PLAN-11.md` §5 "사람별로 나누기", "계열 / 원본" 행 |
| 열람 = 주 ∪ 확정 연결(`visible_tasks`), 집계용 `tasks_visible_in`(태스크당 한 행) | `tasks/services.py:224-264` |
| 상태 전이 규칙(완료 조건·검토 필수·검토자·본인 검토 금지·동시 진행 한도) | `tasks/services.py:559-729` |
| 집계: `project_stats_bulk`(프로젝트 지표·레일·API), `reports._open_qs`·`weekly`(조직 현황·주간 보고·봇) | `projects/services.py:475-503`, `reports/services.py:23-28,179-250` |
| 보드 = 미완료 5열 + 결과 선반, 달력, 오늘, 내 태스크(`me_view` groups) | `web/views/projects.py:55-115,268-300`, `tasks/services.py:1065-1130,1147-` |
| 마이그레이션: 최신 `tasks 0010`, `0011`은 D2(첨부 `doc`)에 예약 | `docs/IMPL-PLAN-11.md:34` |

---

## 2. 모델

### 2.1 대안 비교

| | A. `parent` 의미를 상위·하위로 재정의 | **B. 새 열 `group` + `parent`(계열) 유지** | C. 별도 표 `TaskGroup` |
|---|---|---|---|
| 회차(템플릿 → 회차) | 회차가 템플릿의 "하위"가 돼 템플릿에 진행률이 생기고(템플릿은 진행하지 않음, `set_template`), 한 겹 때문에 회차는 하위를 못 가짐 → 어긋남 | 회차·복제는 계열 그대로. 상위·하위와 직교(둘 다 가질 수 있음) | 표 하나·행 하나를 더 읽어야 함. 한 겹에 표는 과함 |
| 데이터 이전 | 기존 회차 행 전부 해석이 바뀜(API `parent_id` 호환 깨짐) | S1 결과(아직 운영 미배포)만 선택적으로 전환 | — |
| 판단 | 비추천 | **추천** | 비추천 |

이름: `group`(상위 태스크). `parent_task`는 `parent`(계열)와 한눈에 안 갈려 쓰지 않는다. related_name `subtasks`.

### 2.2 `tasks 0012_task_group`(D2의 `0011` 뒤. D2보다 먼저 가면 `0011`을 쓰고 D2가 `0012`)
```python
# Task
# 상위 태스크(한 겹). 하위는 상위와 같은 주 프로젝트에 있고, 하위의 하위는 없다(services.set_group이 지킨다).
# parent(계열)와는 다른 관계다 — 회차·복제의 원본은 parent, 묶음은 group.
group = models.ForeignKey(
    "self", on_delete=models.SET_NULL, null=True, blank=True,
    related_name="subtasks", verbose_name="상위 태스크",
)
# Meta.constraints 추가
models.CheckConstraint(condition=Q(group__isnull=True) | ~Q(group=F("id")), name="task_group_not_self"),
models.CheckConstraint(condition=~Q(is_template=True) | Q(group__isnull=True), name="task_template_no_group"),
# Meta.indexes 추가
models.Index(fields=["group"]),
```
- 한 겹("하위의 하위 금지", "하위가 있는 태스크를 하위로 못 넣음")은 두 행을 봐야 해서 CheckConstraint로 못 쓴다. `set_group`이 `select_for_update`로 상위 행을 잠그고 검사한다(§3.1). `# ponytail: 한 겹은 서비스 한 곳에서 지킨다. DB 트리거는 두지 않는다.`
- RunPython(안전망, 멱등): `ChangeLog(target_type="task", field="split")` 행마다 `new_value`("TASK-a,TASK-b")의 태스크를 `group=target_id, parent=None`으로 바꾸고, 그 상위의 체크리스트가 전부 `"TASK-n …"` 꼴이면 지운다(S1이 바꿔 놓은 것, `split.py:85-87`). 운영 서버는 S1 이전이라 보통 0건. 역방향 `noop`.

### 2.3 상수·직렬화
- `LOCKED_FIELDS`에 `"group"`, `TRACKED`에 `"group"`(`tasks/services.py:24-35`) → `update_task(changes={"group": ...})`가 version 검사·이력을 그대로 탄다. 단 검사는 `set_group`이 한다(§3.1).
- `FIELD_LABELS["group"] = "상위 태스크"`, `_display("group", raw)` → `TASK-{raw}`(`web/views/common.py:185-198`).
- `task_brief`에 `group_id`(`tasks/brief.py:51` 옆). `task_out`에 `group: {id, number, title} | None`(보는 사람이 볼 수 없으면 `None`, `group_id`는 그대로)·`subtasks: [{id, number, title, status, assignee, due_date}]`(보이는 것만)·`subtask_done`·`subtask_total`(전체 수, §4.1).

---

## 3. 규칙(전부 `tasks/services.py`. 웹·API·MCP·Discord는 부르기만)

### 3.1 넣기·떼어내기·하위 만들기
```python
ONE_LEVEL = "태스크 중첩은 한 겹까지입니다."

def subtask_progress(task) -> tuple[int, int]:
    """(완료 수, 취소를 뺀 하위 수). 하위가 없으면 (0, 0)."""

@transaction.atomic
def set_group(task, group, *, actor, source="web", token=None, expected_version) -> Task:
    """group=None이면 떼어내기. 검사 순서(실패는 ServiceError {"group": …}):
    자기 자신 · 템플릿(양쪽) · 다른 주 프로젝트("하위는 상위와 같은 프로젝트에 있어야 합니다") ·
    group.group_id is not None(ONE_LEVEL) · task.subtasks.exists()(ONE_LEVEL) · group.is_closed("완료·취소된 태스크 아래에는 넣을 수 없습니다") ·
    계열 무관(parent가 있어도 됨). 권한 _require_task(actor, task)와 _require_task(actor, group). AI 키 ai.create_task(새 키 없음).
    Task.objects.select_for_update().get(pk=group.pk)로 상위를 잠근 뒤 검사 → _apply(task, expected_version, {"group": group}) → _log(task, "group", old, new)."""
```
- `create_task(..., group=None)`: `group`이 있으면 `project = group.project`로 강제(API에서 `project_id`가 다르면 400 `{"project_id": "하위는 상위와 같은 프로젝트에 만듭니다."}`), 담당자 기본값은 **상위 담당자가 아니라 actor**(지금 규칙 유지, 폼이 상위 담당자를 미리 고른다), `set_group`과 같은 검사(상위 열림·한 겹·템플릿), 상위의 **확정 연결 프로젝트를 복사**(`duplicate_task`와 같은 이유 — 같은 열람자 집합, `services.py:775-779`). `_log(new, "group", "", group.number)`.
- `duplicate_task(..., group=None)`: `group`을 주면 `parent`를 **쓰지 않고** `group`으로 묶는다(S1용, §3.5). 주지 않으면 지금처럼 계열. 상위를 복제하면 하위는 복사하지 않는다(대화상자 문구 "하위 태스크는 복사하지 않습니다").
- `set_template(on=True)`: `task.group_id or task.subtasks.exists()`면 거절 "상위·하위 관계가 있는 태스크는 템플릿으로 둘 수 없습니다."
- `delete_task(상위)`: FK `SET_NULL`로 하위는 남는다. 웹 확인 문구에 "하위 n건은 남고 상위 연결만 풀립니다." 하위마다 `_log(sub, "group", 상위번호, "", note="상위 삭제")`.

### 3.2 상태 전이 — 불변식 **"닫힌 상위 아래에 열린 하위는 없다"**
`transition()`(`services.py:559-`)에 세 줄 추가:
| 전이 | 규칙 |
|---|---|
| 상위 → `done`/`cancelled` | 열린 하위가 있으면 거절 `{"status": "하위 태스크 n건이 아직 열려 있습니다. 먼저 끝내거나 취소하거나 떼어내세요."}` |
| 하위 → `todo`/`doing`(재개) | 상위가 닫혀 있으면 거절 `{"status": "상위 TASK-N이 완료·취소 상태입니다. 상위를 먼저 다시 열거나 떼어내세요."}` |
| 하위 → 닫힘 | 성공 뒤 `_suggest_group_done(task.group)` (§3.3) |
| 상위 재개, 하위 미완료 간 이동, 그 밖 | 변경 없음. 상위 상태는 사람이 바꾼다(자동 전이 없음 — 자동 `doing`은 기한 필수·동시 진행 한도와, 자동 `done`은 검토 필수·검토자·본인 검토 금지·완료 조건과 충돌) |

### 3.3 완료 제안(자동 완료 아님)
`_suggest_group_done(group)`: 상위가 열려 있고 `subtask_progress`의 분모 > 0이고 열린 하위가 0이면 → `wr.notify(org, text, user=group.assignee)`(`work_requests.py:47-53`) 한 통: "TASK-N «제목»의 하위 태스크가 모두 끝났습니다. 상위를 완료로 표시해 주세요. {url}". 저장 플래그 없음 — 패널은 같은 조건을 그때그때 계산해 `.notice`를 그린다(§5.2). 마지막 하위를 다시 열었다 닫으면 또 보낸다(드물다, 받아들임). `# ponytail: 제안은 DM 한 통. 자동 완료가 필요하면 조직 설정 task.auto_close_group을 그때 추가.`

### 3.4 담당자·기한·옮기기
- 담당자: 상위·하위 각각 1명(S1 유지). 하위 만들기 폼의 기본값 = 상위 담당자.
- 기한: 막지 않고 **경고**. `due_after_group(task) -> bool` = `task.group and both due and task.due_date > task.group.due_date`. 하위 패널 `.notice.warn` "⚠ 목표일이 상위 TASK-N(10월 12일)보다 늦습니다.", 상위의 하위 목록 행에 `.badge.warn` "상위 기한 초과". API `task_out.subtasks[].due_after_group`.
- 옮기기(`update_task(project=)`): 상위를 옮기면 **하위도 함께**(같은 트랜잭션, 하위마다 `_require_viewer(assignee)`·검토자 `can_see` 검사, 하나라도 못 보면 전체 거절 `{"project": "하위 TASK-M의 담당자가 볼 수 없는 프로젝트입니다."}`, 하위 각각에 `_log("project")`, 하위의 연결 중 새 주와 같은 것 삭제·`_drop_stale_git_project`를 하위에도). 하위 단독 옮기기는 거절 `{"project": "하위 태스크는 상위와 같은 프로젝트에 있어야 합니다. 먼저 떼어내세요."}`.
- 보관(`archive`)·공개 범위 변경: 변경 없음(프로젝트 단위).

### 3.5 "사람별로 나누기"(S1) 변경 — 하위 태스크 생성(사용자 확정)
원본은 지금 "체크리스트 = 만든 태스크 목록 + 진행 메모 한 줄"로 상위 노릇을 흉내 낸다(`split.py:85-91`). 하위 관계가 생기면 흉내를 걷어내고 **원본 = 상위, 사람별 태스크 = 하위**로 둔다.

| 지점 | 지금(`a9885bb`) | 바꿀 것 |
|---|---|---|
| `tasks/split.py` `split_by_assignees` | `duplicate_task(...)` → `parent=계열 뿌리`; 원본 체크리스트를 `TASK-n 이름` 목록으로 교체(`:85-87`); 진행 메모에 "사람별로 나눴습니다: …"(`:88-92`) | `duplicate_task(..., group=task)`(§3.1, `parent`를 쓰지 않음). **체크리스트 교체·진행 메모 줄 삭제** — 상위 진행률(§5.2 "하위 n/m")이 대신한다. 원본 체크리스트는 그대로 남고 하위에 복사된다(지금과 같음). 거절 추가: 원본이 하위면 `{"task": ONE_LEVEL}`, 원본이 닫혀 있으면 `{"task": "완료·취소된 태스크는 나눌 수 없습니다."}`. `_log(task, "split", "", "TASK-a,TASK-b")`와 `MIN/MAX_PEOPLE`·`roles`·`title_pattern`·멱등 키는 그대로 |
| 모듈 docstring·`ONE_ASSIGNEE`·`SPLIT_NOTE`(`split.py:1,11-14`) | "계열로 묶는다" | "하위 태스크로 만든다". API 400 문구: "담당자는 한 명입니다. 사람별로 나누려면 만든 뒤 POST /api/tasks/{id}/split 으로 하위 태스크를 만드세요." |
| 대화상자 `templates/tasks/_split.html:2-3` | "같은 계열로 묶습니다. … 체크리스트는 만든 태스크 목록으로 바뀝니다." | "고른 사람마다 {{ task.number }}의 설명·완료 조건·체크리스트(미완료로)·링크·문서 연결·기한을 복사한 **하위 태스크**를 만듭니다. {{ task.number }}는 상위 태스크가 되어 진행률을 보여 줍니다." |
| 안내 `_split_hint.html`·패널 버튼(`_panel.html:53`) | 열린 태스크면 표시 | 하위(`task.group_id`)면 숨김(한 겹). 안내 문구 끝 "사람별로 나누면 담당·기한·완료가 또렷해집니다." 유지 |
| 토스트(`web/views/split.py:38`) | "n건으로 나눴습니다." | "하위 태스크 n건을 만들었습니다." + 리다이렉트는 상위 상세 그대로(하위 섹션이 바로 보인다) |
| API `POST /api/tasks/{id}/split`(`routers/tasks.py:475-`) | 201 `{tasks}` | 모양 그대로. 만든 태스크의 `group_id == id`, `parent_id == null`. 하위에 부르면 400 ONE_LEVEL |
| MCP `split_task`(`server.py:724-737`) docstring | "계열(parent_id)로 묶는다" | "원래 태스크를 상위로 두고 사람마다 하위 태스크를 만든다(group_id). 하위 태스크는 더 나눌 수 없다(한 겹)." |
| 스킬 `pm/SKILL.md:106`, `pm-split` "사람별 모드" | "같은 계열로 묶는다 … 원본 체크리스트는 만든 태스크 목록으로 바뀐다" | "하위 태스크로 만든다. 원본은 상위가 되어 진행률을 보여 준다" |
| Discord `/태스크만들기` 응답 끝 한 줄(`SPLIT_NOTE`) | "웹에서 [사람별로 나누기]를 누르세요." | 그대로(문구에 계열이 없다). 새 명령 없음 |

- 이미 나누기로 만든 계열 데이터: **운영에는 S1이 배포되지 않았다**(서버 = main `ba4c3a1`, 메모리). 따라서 **이전은 필요 없다**. 다만 개발 DB·테스트 데이터에 있을 수 있어 §2.2의 RunPython을 **안전망**으로 둔다(`field="split"` 이력이 있는 것만, 멱등, 0건이면 아무 일도 없음). 운영 배포 전 확인은 사용자 몫.
- `test_split.py` 갱신: `parent` → `group`, "원본 체크리스트가 `TASK-n …` 목록으로 바뀐다" 단언 삭제 → "원본 체크리스트가 그대로다 + `subtask_progress == (0, n)`" 단언, 하위 나누기 거절 1건 추가.

### 3.6 그 밖의 접점
| 지점 | 영향 |
|---|---|
| GitHub(`_find_task` `github/services.py:798`, `TaskGitLink`, 규칙·PR 맥락) | **하위마다 따로**. 상위와 무관. 머지로 하위가 완료되면 §3.3 제안이 나간다(actor=None이라도 `wr.notify`는 된다) |
| 다중 프로젝트 연결(`link_project`) | 하위·상위 각각. 하위 생성 시 상위의 확정 연결을 복사(§3.1). 넣기는 복사하지 않는다 |
| 검토자·반려·체크리스트·첨부·결정 기록·오늘 목록·요청 | 태스크 단위 그대로 |
| 템플릿 | 상위·하위 관계 없음(§3.1) |
| 계열(`parent`) | 그대로. 복제·회차만 만든다 |

---

## 4. 열람·프로젝트

### 4.1 규칙
- **하위는 상위와 같은 주 프로젝트**(§3.1·3.4). 따라서 주 프로젝트 열람자는 상위·하위를 똑같이 본다.
- 연결 프로젝트는 태스크마다라 두 경우가 남는다. 둘 다 **보이는 것만 그리고, 숨긴 쪽의 번호·제목을 내지 않는다**:
  | 경우 | 처리 |
  |---|---|
  | 하위만 보이고 상위는 못 봄(하위에만 연결된 프로젝트의 열람자) | 하위 패널·행에 상위 줄을 **그리지 않는다**(`can_view_task(viewer, task.group)` 거짓). API `group: null`(`group_id`는 숫자 그대로 — 번호는 비밀이 아니다, `?parent=`와 같은 선택) |
  | 상위만 보이고 하위 일부를 못 봄(상위에만 연결된 프로젝트의 열람자) | 하위 목록은 `visible_tasks(viewer).filter(group=task)`. 진행률 "2/5"는 **전체 수**(개수는 노출로 보지 않는다, `children_count`와 같은 수준), 차이가 있으면 `.muted` "볼 수 없는 하위 n건" |
- `visible_tasks`·`tasks_of`·`can_view_task`는 바꾸지 않는다. 하위 생성이 상위의 확정 연결을 복사하므로 보통은 두 경우가 생기지 않는다.
- 하위를 만들 수 있는 사람 = 상위를 볼 수 있는 조직 멤버(`_require_task`). 넣기는 두 태스크 모두 볼 수 있어야 한다.

### 4.2 집계 — **잎만 센다**
하위가 있는 상위를 지표에 넣으면 완료·초과가 두 번 센다(하위 5건 + 상위 1건). 규칙: **집계(조직 현황·주간 보고·프로젝트 지표·레일·API stats·Discord 봇)는 `subtasks`가 있는 태스크를 뺀다. 목록·보드·달력·오늘·내 태스크에는 둘 다 보인다.**
```python
def leaf_only(qs):
    """집계용. 하위가 있는 상위는 뺀다(하위가 대표한다)."""
    return qs.filter(~Exists(Task.objects.filter(group_id=OuterRef("pk"))))
```
적용 두 곳: `tasks_visible_in`(`services.py:253-264`, docstring이 이미 "조직 집계용") → `reports._open_qs`·`org_status`·`weekly`(완료·재개 id도 `org_task_ids` 안이라 함께 빠진다)·봇이 한 번에 바뀐다. `project_stats_bulk`(`projects/services.py:487`)에 `leaf_only`. 오늘 화면 `counts`(`services.py:1098-1115`)는 개인 목록이라 그대로(상위·하위 모두 "내 일"). 각주: 조직 현황·주간 보고 머리에 `.muted` "하위가 있는 상위 태스크는 세지 않습니다"(하위가 1건이라도 있을 때만).

---

## 5. 화면(`DESIGN.md` 준수: 토큰만, 격식체, 감탄부호·장식 글리프 없음, ⚠는 경고에만)

### 5.1 행(`templates/tasks/_row.html`, `row_ctx` `web/views/common.py:262-287`)
- 상위 행: `.meta`에 `<span class="sub-count">하위 {{ done }}/{{ total }}</span>`(체크리스트 n/m과 같은 자리·같은 모양). 보드 카드에서는 그 아래 `.bar` 한 줄(진행 막대 토큰 그대로, 퍼센트는 `style="width: N%"` 허용 예외).
- 하위 행: `.proj` 줄 끝에 `<span class="sub-of">↳ TASK-N</span>`(상위를 볼 수 있을 때만). 제목은 넣지 않는다(행이 길어진다; 패널에 있다).
- `rows_for`(`common.py:289-294`): `prefetch_related_objects(tasks, "group")` + 쿼리 두 번(상위 중 보이는 id 집합, 하위 수·완료 수 `values("group_id").annotate`). 행당 쿼리 증가 없음(`test_perf` 고정).
- `app.css`: `.sub-count`·`.sub-of`는 `.task-row .meta span` 기본 스타일(토큰) 재사용, `.task-row.sub`(아래 5.3)만 추가 → `DESIGN.md` 4장에 한 줄.

### 5.2 패널(`templates/tasks/_panel.html`, `_panel_ctx` `web/views/tasks.py:87-136`)
- 하위일 때, 번호 바로 아래 한 줄: `<p class="t13">상위 <a href=…>TASK-N 제목</a> <button class="btn link">떼어내기</button></p>`(볼 수 있을 때만). 기한 경고 `.notice.warn`(§3.4).
- 상위일 때(하위가 1건 이상이거나 열려 있을 때), 계열 섹션(`:77`) 아래 새 섹션 `templates/tasks/_subtasks.html`:
  ```
  <details class="section" open><summary>하위 태스크 {{ done }}/{{ total }}</summary>
    <div class="bar"><i style="width: N%"></i></div>
    {% if all_closed_open_parent %}<div class="notice"><span class="grow">하위 태스크가 모두 끝났습니다. 상위를 완료로 표시해 주세요.</span>
      <form hx-post="{% url 'task_status' task.pk %}"><input type=hidden name=status value=done><input type=hidden name=version …><button class="btn sm">완료로 표시</button></form></div>{% endif %}
    <ul class="stack">{% for s in subtasks %}<li class="row"><a>{{ s.number }} {{ s.title }}</a> <span class="muted t13">{{ s.assignee.display_name }}</span> <span class="pill sm {{ s.status }}">…</span>{% if s.due_date %}<span class="muted t13">n월 j일</span>{% endif %}{% if s.due_after_group %}<span class="badge warn">상위 기한 초과</span>{% endif %} <button class="btn sm" hx-post="{% url 'task_ungroup' s.pk %}">떼어내기</button></li>{% endfor %}</ul>
    {% if hidden_count %}<p class="muted t13">볼 수 없는 하위 {{ hidden_count }}건</p>{% endif %}
    {% if task.is_open and not task.group_id %}
    <form class="row" hx-post="{% url 'subtask_create' task.pk %}" hx-target="#panel">제목 .input(required) · 담당자 .select(기본 상위 담당자) · 기한 .input[type=date](기본 상위 기한) · [하위 만들기] .btn.sm</form>
    <form class="row" hx-post="{% url 'task_group' task.pk %}" hx-target="#panel"><select class="select" name="task">같은 주 프로젝트의 열린 태스크 중 group 없고 subtasks 없고 템플릿 아닌 것(최대 50, 제목순)</select> [기존 태스크 넣기] .btn.sm</form>
    {% endif %}
  </details>
  ```
  - 주 버튼(`.primary`)은 패널에 이미 없으므로 모두 `.btn.sm`. "완료로 표시"는 기존 `task_status` 끝점을 그대로 부른다(검토 필수 등 규칙이 그대로 걸리고 실패 문구가 패널 `error`로 온다).
  - 하위 만들기 폼의 완료 조건 필수(`task.require_done_when`) 조직에서는 `done_when` 칸을 함께 보인다(설정값은 `_panel_ctx`가 읽는다).
  - "더보기"의 복제 문구(`:119`)에 상위면 "하위 태스크는 복사하지 않습니다" 한 줄.
  - 삭제 확인(`:128`)에 하위 수.
- 사람별로 나누기 버튼(`:53`): 하위면 숨긴다(한 겹).
- 새 뷰 `web/views/subtasks.py`(새 파일, S1의 `split.py`와 같은 꼴): `subtask_create`·`task_group`(넣기)·`task_ungroup`(떼어내기). 전부 `task_or_404` → 서비스 → `trigger("task-updated")` + 패널 재렌더. `urls.py` 끝에 세 줄.

### 5.3 목록(프로젝트 "목록" 보기 `web/views/projects.py:353-358`·내 태스크·검색·오늘)
- **프로젝트 목록 보기만 묶어 그린다**(기한순 평면 목록 안에서 상위 바로 아래에 보이는 하위를 `li.task-row.sub`(왼쪽 들여쓰기 `--sp-6`, 세로 선 `--c-line`)로 붙인다). `nest_rows(rows)`(`common.py`): 상위 행의 위치는 자기 기한, 하위는 상위 뒤에 기한순. 상위가 목록에 없으면(닫힘·거름) 하위는 평면 행 그대로(§5.1 `↳` 표시가 길을 알려 준다).
- 접기: 상위 행의 "하위 n/m"을 `button`으로 두고 `data-action="toggle-subtasks"`(app.js 6줄: 형제 `li[data-group="N"]` `hidden` 토글, `aria-expanded`). 기본 펼침. 상태는 저장하지 않는다. `# ponytail: 접힘 기억은 필요해지면 localStorage.`
- 내 태스크·검색·오늘: 묶지 않는다(이미 묶음·정렬 기준이 있다). 행의 `↳ TASK-N`·"하위 n/m"만.
- 보드: **묶지 않는다**(열 = 상태, 상위와 하위의 상태가 달라 같은 열에 있을 수 없다). 상위 카드에 진행 막대, 하위 카드에 `↳`. 드래그는 태스크마다. 결과 선반: 같은 행 템플릿이라 그대로.
- 달력: 변경 없음(기한이 있는 태스크는 각자 점). 

### 5.4 문구(격식체)
| 자리 | 문구 |
|---|---|
| 한 겹 거절 | "태스크 중첩은 한 겹까지입니다." |
| 상위 완료 거절 | "하위 태스크 n건이 아직 열려 있습니다. 먼저 끝내거나 취소하거나 떼어내세요." |
| 하위 재개 거절 | "상위 TASK-N이 완료·취소 상태입니다. 상위를 먼저 다시 열거나 떼어내세요." |
| 완료 제안 | "하위 태스크가 모두 끝났습니다. 상위를 완료로 표시해 주세요." |
| 기한 경고 | "⚠ 목표일이 상위 TASK-N(n월 j일)보다 늦습니다." |
| 토스트 | "하위 태스크를 만들었습니다." / "TASK-M을 하위로 넣었습니다." / "떼어냈습니다." |

---

## 6. API·MCP·스킬·Discord

| 경로 | 바꿀 것 |
|---|---|
| `GET /api/tasks` | `group: int`(그 상위의 하위만), `leaf_only: bool`(집계용) 필터. `parent`는 그대로 |
| `POST /api/tasks` | `TaskCreateIn.group_id: int | None` → `create_task(group=)`. `project_id`가 상위와 다르면 400 |
| `PATCH /api/tasks/{id}` | `TaskPatchIn.group_id: int | None`(null = 떼어내기) → `set_group`. `project_id`와 함께 오면 옮기기 규칙(§3.4) |
| `task_out` | `group`·`subtasks`·`subtask_done`·`subtask_total`(§2.3). `TaskBriefOut.group_id` |
| `POST /api/tasks/{id}/split` | 응답 모양 그대로(`{tasks}`), 만든 태스크의 `group_id = id` |
| MCP `create_task(group_id)`·`update_task(group_id, clear_group)`·`list_tasks(group_id, leaf_only)`·`get_task`(`group`·`subtasks` 포함)·`split_task` docstring "하위 태스크로 묶는다". 새 도구 없음. `get_guide` 조합표: "큰 일 → 상위 1건 → 하위 n건(한 겹). 여러 사람이 할 일 → create_task → split_task" |
| 스킬 `pm/SKILL.md` | `:105-106` 복제는 계열, 나누기는 하위. `:195-196` 낡은 안내 → "상위·하위는 한 겹. `group_id`로 잇는다. 설명 첫 줄 `상위: TASK-N`은 쓰지 않는다." 집계 규칙 한 줄(잎만) |
| `pm-split/SKILL.md` | 3단계 "원래 태스크를 어떻게 할지" 선택지 → "원래 태스크를 상위로 두고 조각을 하위로 만든다(기본)" / "그대로 둔다". 4단계 `description` 첫 줄 `상위:` 삭제 → `group_id`. 5단계(체크리스트 교체) 삭제. 조각이 또 나뉘면 "한 겹이라 더 못 나눈다 — 체크리스트로" |
| `pm-today`·`pm-weekly` | 집계 각주 한 줄 |
| Discord | 새 명령 없음. `task_line`(`messages.py:35`)에 `group_id`가 있으면 ` ↳ TASK-N` 덧붙임(brief에 있는 값만 쓴다). 완료 제안 DM은 core `Notice`로 간다(봇 변경 없음) |
| 웹 MCP(`webmcp.js`) | 변경 없음 |

---

## 7. 마이그레이션·테스트·수용 기준

### 7.1 마이그레이션
`tasks 0012_task_group`(§2.2). 기존 계열 데이터는 손대지 않는다. S1 결과 전환 RunPython은 안전망(운영 0건 예상).

### 7.2 테스트(`core/tasks/test_group.py` 새 파일 + 기존 갱신)
- `set_group`: 넣기·떼어내기·이력, 자기 자신·템플릿(양쪽)·다른 프로젝트·닫힌 상위·하위의 하위·하위가 있는 태스크를 하위로(ONE_LEVEL)·다른 조직·권한(둘 다 볼 수 있어야)·version 충돌·동시 넣기(잠금).
- `create_task(group=)`: 프로젝트 강제·연결 복사·담당 요청 규칙 그대로·AI 키.
- 전이: 열린 하위 있는 상위 완료·취소 거절, 닫힌 상위의 하위 재개 거절, 상위 재개 허용, 마지막 하위 닫힘 → Notice 1통(담당자 DM, 문구), 취소된 하위는 분모 제외, GitHub 머지(actor None)로도 제안.
- 옮기기: 상위 → 하위 함께·이력·연결 정리·연동 프로젝트 해제, 하위 담당자가 못 보면 전체 거절, 하위 단독 옮기기 거절.
- 템플릿: 관계 있는 태스크 템플릿화 거절, 템플릿을 하위로 거절. 복제: 하위 미복사. 삭제: 하위 `group=None`·이력.
- 열람: 하위에만 연결 → 그 열람자에게 상위 줄 없음·API `group: null`; 상위에만 연결 → 하위 목록은 보이는 것만, 전체 수 유지, "볼 수 없는 하위 n건".
- 집계: `tasks_visible_in`·`project_stats_bulk`·`org_status`·`weekly`·봇(viewer None)이 상위를 빼는지(하위 5 + 상위 1 → 5), 하위 없는 상위는 세는지, 오늘 counts는 그대로.
- S1 갱신(`test_split.py`): `group` 묶음, 체크리스트 유지, 하위 나누기 거절, RunPython 전환.
- API(`api/tests.py`): `group_id` 생성·PATCH·null·400 문구·`?group=`·`?leaf_only=`·`task_out` 모양. MCP(`mcp_server/tests/test_tools.py`): 인자 전달. 스킬(`skills/test_pm.py`): 안내 문구 grep("상위: TASK-N" 없음).
- 웹(`web/tests.py`): 패널 하위 섹션·만들기·넣기·떼어내기·완료 제안 알림·기한 경고·목록 묶음과 접기 속성·보드 진행 막대·행 `↳`·삭제 확인 문구·`test_perf` 쿼리 수 불변·디자인 시스템 테스트(새 클래스 문서화).

### 7.3 수용 기준
- "행사 준비"를 상위로 두고 사람별로 나누면 3건의 하위가 생기고, 상위 패널에 "하위 0/3"과 진행 막대가 보이며, 하위 둘을 완료하면 "2/3", 셋째를 완료하면 담당자에게 DM 한 통과 패널의 완료 제안이 뜨고, 상위 완료는 사람이 누른다.
- 하위 아래에 또 넣으려 하면 웹·API·MCP 모두 "태스크 중첩은 한 겹까지입니다."로 거절된다.
- 조직 현황·주간 보고·프로젝트 지표의 미완료·완료 수에 상위가 더해지지 않는다(하위 3 + 상위 1 → 3).
- 하위에만 연결된 프로젝트의 열람자는 상위의 번호·제목을 어디서도 보지 못한다.

---

## 8. 용어표 갱신(`IMPL-PLAN-11` §5에 덧붙이고, 충돌 행은 아래가 우선)

| 표준 용어 | 뜻 | 쓰지 않는 말 |
|---|---|---|
| **상위 태스크 / 하위 태스크** | 묶음의 위/아래(`Task.group`). 한 겹만 | 부모 태스크, 자식 태스크, 서브태스크, 에픽, 그룹 태스크, 중첩 태스크 |
| **넣기 / 떼어내기** | 기존 태스크를 상위 아래로 / 상위에서 빼기 | 연결(프로젝트·문서용과 구분), 이동, 분리 |
| **하위 만들기** | 상위 패널에서 새 하위 태스크 생성 | 서브태스크 추가 |
| **진행률(하위 n/m)** | 취소를 뺀 하위 중 완료 비율 | 달성률, 퍼센트 |
| **완료 제안** | 하위가 모두 끝났을 때 상위 담당자에게 보내는 안내. 자동 완료 아님 | 자동 완료, 롤업 |
| **사람별로 나누기 / 사람별 태스크** | 담당자마다 **하위 태스크**를 만들기 / 그 하위 | 분배, 공동 담당 |
| **계열 / 원본** | 복제·회차의 묶음 / 그 뿌리(`Task.parent`). **사람별 태스크는 더는 계열이 아니다** | 부모 태스크, 에픽 |
| **잎만 센다** | 집계에서 하위가 있는 상위를 빼는 규칙 | 중복 제거, 롤업 집계 |

"하위 문서 / 상위 문서"(문서 트리)와 "하위 태스크 / 상위 태스크"는 같은 꼴의 말이라 설명 없이 통한다. 코드 식별자: `group`, `subtasks`, `set_group`, `subtask_progress`, `leaf_only`, `due_after_group`.

---

## 9. 구현 단계와 순서

| 단계 | 내용 | 담당 | 선후 | 마이그레이션 | 주로 고치는 파일 | 충돌 주의 |
|---|---|---|---|---|---|---|
| **G1** core | §2·§3·§4.2(`leaf_only`·`tasks_visible_in`·`project_stats_bulk`)·S1 전환(§3.5)·`brief.py`·테스트 | Opus | **P2·D2 병합 뒤**(P1b는 병합됨) | `tasks 0012` | `tasks/{models,services,split,brief}.py`, `tasks/migrations/0012`, `projects/services.py`(stats 한 줄), `tasks/test_group.py`(새), `tasks/test_split.py` | `tasks/services.py`·`projects/services.py`를 P2가 먼저 만진다 → 다른 함수지만 순차 병합. `tasks/models.py`는 D2(0011) 뒤 |
| **G2** 웹 | §5 전부, `web/views/subtasks.py`(새), `urls.py` 끝, `_subtasks.html`(새), `_panel/_row/_split.html`, `common.py`(`row_ctx`·`rows_for`·`nest_rows`·`FIELD_LABELS`), `projects.py`(목록 묶기), `app.css`·`app.js` 몇 줄, `DESIGN.md` 4장 한 줄, `/ops/design` 견본 | Opus | G1 뒤 | 없음 | 위 | `_panel.html`·`_row.html`·`common.py`·`projects.py`를 P2가 만진다 → P2 병합 뒤(G1 선후로 이미 보장) |
| **G3** API·MCP·스킬·Discord·문서 | §6, `SPEC-FUNCTIONAL.md` 2장 한 절, `skills/README.md`, `mcp_server/skill/SKILL.md` | Sonnet | G1 뒤(G2와 **병렬**, 파일 겹침 없음) | 없음 | `api/{schemas,serialize}.py`, `api/routers/tasks.py`, `api/tests.py`, `mcp_server/.../server.py`, `mcp_server/tests`, `skills/{pm,pm-split,pm-today,pm-weekly}/SKILL.md`, `skills/test_pm.py`, `discord_service/.../messages.py` | `api/schemas.py`·`server.py`를 P2는 안 만진다(P1a가 끝냄) |
| **G4** 마무리 | 전체 테스트, `IMPL-PLAN-11` §5 용어표에 §8 반영, 승인 | Opus → Fable 승인 | G2·G3 뒤 | 없음 | 문서 | 없음 |

- 순서 근거: **P1b는 병합됐다**(`ae68df5`, `github/*`·`_git_ctx`·`_git.html`). 남은 **P2**는 `_panel.html`·`_row.html`·`common.py`·`web/views/{projects,tasks}.py`·`projects/services.py(stats)`·`reports/services.py`·프로젝트 채널 알림(연동 저장소 쪽 프로젝트)을 만지므로 G1·G2 모두 P2 뒤. **D2**는 `tasks/models.py`·`0011`이라 G1의 `0012`가 그 뒤. G1은 `transition`·`update_task`·`create_task`·`duplicate_task`·`tasks_visible_in`·`split.py`를 만진다 — P2와 함수는 다르지만 같은 파일을 두 에이전트가 동시에 쓰지 않는다(금지 7).
- 묶음: **{P2, D2} → G1 → {G2, G3} → G4.** P2가 늦어지면 G1을 먼저 하고 P2가 rebase(`tasks/services.py`·`projects/services.py`의 충돌 함수 없음)해도 된다 — 사용자 판단.
- 검토(Sol, GPT 사용량 확인 뒤) 한 번: §3.2 불변식과 §4.2 집계 규칙(G1). 승인(Fable): 이 표와 §10 질문.

---

## 10. 사용자에게 물을 것

**이미 확정(2026-10-07, 묻지 않음)**: "사람별로 나누기" 결과 = 원래 태스크의 **하위 태스크**(계열 아님). 원본의 체크리스트 교체는 **하위 진행률로 대체**. 계열(`parent`)은 복제·회차용으로만 남는다. 운영에 S1이 배포되지 않았으므로 데이터 이전 없음(§3.5).

| # | 질문 | 선택지 | 추천 |
|---|---|---|---|
| 1 | 하위가 모두 끝났을 때 상위를 | (a) **완료 제안만**(DM + 패널 버튼, 사람이 누름) (b) 자동 완료 | **(a)** — 자동 완료는 검토 필수·지정 검토자·본인 검토 금지·완료 조건 규칙(`transition`)을 우회한다. 필요해지면 조직 설정 하나로 (b)를 켠다 |
| 2 | 상위를 **취소**할 때 열린 하위가 있으면 | (a) **거절**(먼저 끝내거나 취소하거나 떼어내기) (b) 하위도 함께 취소(확인 한 번) | **(a)** — 규칙이 완료와 같아 외우기 쉽고, 하위 취소에도 사유 필수 설정(`task.cancel_reason_required`)이 그대로 걸린다. 하위가 보통 2~5건이라 손으로 닫을 만하다. (b)가 필요해지면 `transition(cascade=True)` 인자 하나 |

묻지 않고 추천대로 확정: 새 열 `group`(계열 `parent` 유지) · 하위 = 같은 주 프로젝트 · 상위 옮기면 하위 함께 · 집계는 잎만 · 보드는 묶지 않음(진행 막대만) · 목록 묶기는 프로젝트 목록 보기만 · 템플릿은 관계 없음 · 복제는 하위 미복사 · 새 MCP 도구·Discord 명령 없음.

---

## 11. 위험

| 위험 | 대응 |
|---|---|
| 한 겹 검사의 경쟁(두 사람이 동시에 A→B, B→C) | `set_group`이 상위 행 `select_for_update` + 자기 행 version 검사. 테스트로 고정 |
| 집계에서 상위가 빠져 "상위만 초과"가 안 보임 | 목록·보드·오늘에는 보인다. 각주 한 줄. 필요하면 `leaf_only=false` 보기 추가 |
| S1 전환으로 운영 데이터 꼬임 | 운영은 S1 이전. RunPython은 `field="split"` 이력이 있는 것만, 멱등 |
| 패널 쿼리 증가 | 하위 목록·진행률 쿼리 2개. 행 목록은 `rows_for`에서 2개 고정(`test_perf`) |
| 하위만 보이는 열람자에게 상위 노출 | 상위 줄은 `can_view_task`를 지나야 그린다. 테스트로 고정 |

## 12. 확인 불가
- 운영 DB에 S1(사람별로 나누기) 결과가 있는지 — 코디네이터 확인대로 운영은 S1 이전이라 0건으로 본다(이전 불필요, RunPython은 안전망). 배포 전 확인은 사용자 몫(운영 항목은 제안에서 제외).
- P2의 실제 변경 범위(아직 시작 전) — `tasks/services.py`·`projects/services.py` 충돌은 IMPL-PLAN-11 §7 표의 파일 목록으로만 추정.
- Postgres에서 `leaf_only`의 `Exists` 서브쿼리 성능 — SQLite로만 테스트. 규모가 작아 문제없다고 본다.
