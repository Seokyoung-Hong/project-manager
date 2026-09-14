# 구현 계획 4: 옵션·설정과 권한 관리

버전: 0.1
작성일: 2026-09-14
기준 문서: [GOVERNANCE.md](GOVERNANCE.md) §"앞으로", [IMPL-PLAN-3.md](IMPL-PLAN-3.md), [GUIDE-00-rules.md](GUIDE-00-rules.md), 현재 코드(커밋 `96a7955`)
상태: **0~3단계 구현 완료 (2026-09-14, 브랜치 `worktree-settings`).** §12 미결 7건은 전부 기본값으로 진행했다. 4단계(승인 대기 큐)는 IMPL-PLAN-5로 분리한다. 구현하며 달라진 점은 §14.

---

## 0. 한 줄 요약

지금 코드에 굳어 있는 숫자·정책(중요도 상한 7, 동시 진행 2개, 알림 9시, 프로젝트는 누구나 생성…)을
**조직 → 프로젝트 → 개인** 세 층의 설정으로 꺼낸다. 값은 JSON 한 칸씩, 정의는 레지스트리 한 파일,
강제는 `services.py`의 기존 검증 함수 안. 편집 권한은 층마다 하나의 규칙으로 고정하고, 조직이
프로젝트 덮어쓰기를 항목별로 잠글 수 있게 한다. AI(MCP)는 설정을 **읽기만** 한다.

---

## 1. 지금 있는 것과 없는 것

### 1.1 지금 설정이라 부를 만한 것

| 자리 | 무엇 | 누가 | 저장 |
|---|---|---|---|
| `/today/settings` | 마감 기준 자동 담기(0·1·3·5·7·14일) | 본인 | `User.auto_pull_days` |
| `/settings/profile` | 표시 이름, Discord·GitHub 연결 | 본인 | `User` 필드 |
| `/settings/tokens` | API 토큰 발급·폐기 | 본인 | `ApiToken` |
| `/projects/<id>/repo` | 저장소 연결의 자동 전환 5규칙, 가져오기 라벨, 기본 담당자, 자동 가져오기 | **조직 멤버 누구나** | `RepoConnection.rule_*` 등 |
| `/orgs/<id>/governance` | 거버넌스 마크다운(서버는 검증하지 않음) | 조직 관리자 | `Organization.governance` |
| `.env.discord` | `SEND_HOUR`·`WEEKLY_WEEKDAY`·`WEEKLY_HOUR`·`DISCORD_CHANNEL_ID` | 운영자(재배포) | 환경 변수 |
| `.env` | 가입 개방 여부 등 사이트 값 | 운영자 | 환경 변수 |

### 1.2 코드에 굳어 있는 정책 (설정 후보)

| 정책 | 지금 값 | 어디 |
|---|---|---|
| 기본 중요도 | 5 | `Task.priority default`, `create_task(priority=5)` |
| 중요도 8 이상은 프로젝트 관리자만 | **문서에만** | `governance.py` §3 |
| AI 중요도 상한 7 | **문서에만** | `governance.py` §8 |
| 동시 `doing` 2개 | **문서에만** | `governance.py` §4 |
| 끝나면 `review`를 거친다 | **문서에만** | `governance.py` §4 |
| `blocked` 2영업일 초과 시 알림 | **문서에만** | `governance.py` §4 |
| 기본 기한 착수일 +3영업일 | **문서에만** | `governance.py` §2 |
| 프로젝트 생성 | 조직 멤버 누구나 | `projects/services.create_project` |
| 프로젝트 관리자 최소 1명 | **문서에만**. `owners`는 비워도 된다 | `projects/services._validate` |
| 프로젝트 보관·복원 | 조직 관리자 | `archive_project` |
| 마일스톤·의존성 편집 | 조직 멤버 누구나 | `projects/services` |
| 팀 생성·편집·멤버 | 조직 관리자 | `orgs/services` |
| 스킬 태그 | 조직 관리자 | `orgs/services.set_tags` |
| 초대 만료 | 7일(1~90), 사용 횟수 무제한 | `create_invite` |
| 마감 알림 종류 | D-3·D-1·당일·초과, 전부 | `discord_service/notify.py` |
| 알림·주간 보고 시각 | 09시, 월요일 09시 | `.env.discord` |
| AI 쓰기 범위 | **문서에만**. 코드는 `write` 토큰이면 전부 허용 | `mcp_server/server.py` INSTRUCTIONS |

**가장 큰 빈틈 둘.**

1. **`Project.owners`("프로젝트 관리자")는 이름표일 뿐 권한이 없다.** 보관은 조직 관리자, 그 밖은 멤버 누구나다.
   거버넌스 기본안이 "8 이상은 프로젝트 관리자가 정한다"고 써 놓고도 코드는 아무도 막지 않는다.
2. **AI에게 허용하는 범위가 글로만 있다.** 거버넌스 §8은 AI가 읽고 자발적으로 지키는 약속이다. 조직이
   "AI는 담당자를 못 바꾼다"고 정해도 기계가 막지 않는다.

이 둘을 설정으로 옮기면 거버넌스 문서는 **설명**, 설정은 **강제**로 역할이 갈린다(GOVERNANCE.md §"앞으로 2").

---

## 2. 설계 원칙 (이 라운드에서 지키는 것)

1. **레지스트리 하나.** 모든 설정의 키·형·기본값·범위·층·편집 권한을 `core/orgs/settings.py`의 표 하나에 둔다.
   화면·API·MCP·검증이 전부 이 표를 읽는다. 항목을 추가한다 = 표에 한 줄 + 강제 지점 한 곳.
2. **JSON 한 칸씩.** `Organization.settings`·`Project.settings`·`User.settings` 세 `JSONField`. 설정마다
   열을 파지 않는다. 값이 없으면 키가 없고, 키가 없으면 기본값이다. "기본값으로 되돌리기" = 키 삭제.
3. **강제는 services에만.** 설정을 읽어 막는 코드는 `tasks/services.py`·`projects/services.py`·`orgs/services.py`의
   기존 검증 함수 안에 들어간다. 뷰·라우터·MCP·Discord에는 규칙이 없다. 그래서 웹·API·AI·슬래시 명령이
   같은 규칙에 같은 문구로 막힌다.
4. **세 층, 한 방향.** 개인 > 프로젝트 > 조직 > 기본값 순으로 가까운 값이 이긴다. 단, 조직은 프로젝트 덮어쓰기를
   항목별로 잠글 수 있고, 개인 설정은 규칙이 아니라 취향(알림·표시)에만 있다. 규칙을 개인이 풀 수는 없다.
5. **편집 권한은 층마다 한 규칙.** 조직 설정은 조직 관리자, 프로젝트 설정은 프로젝트 관리자(조직이 정한 범위 안에서),
   개인 설정은 본인. 항목별 권한 매트릭스는 만들지 않는다(SPEC §2 "세부 필드별 권한" 제외 유지).
6. **AI는 설정을 읽기만.** 쓰기 도구를 만들지 않는다. AI가 자기 제약을 풀 수 있으면 제약이 아니다.
7. **설정 변경은 이력이다.** 조직·프로젝트 설정 변경은 `ChangeLog`에 남긴다(누가 언제 무엇을 얼마에서 얼마로).
   개인 설정은 남기지 않는다(개인 계획과 같은 원칙).
8. **기본값은 지금 동작.** 설정을 하나도 건드리지 않은 조직은 이 라운드 전과 똑같이 움직인다. 테스트가 그것을 지킨다.

---

## 3. 권한 모델

### 3.1 행위자 다섯

| 행위자 | 판정 | 지금 코드 |
|---|---|---|
| 본인 | `request.user == user` | 오늘 목록·프로필·토큰 |
| 조직 멤버 | `orgs.services.is_member` | 모든 업무 데이터 읽기·쓰기 |
| **프로젝트 관리자** | `user in project.owners` — **새 헬퍼 `projects.services.is_owner(user, project)`** | 없음(이름표만) |
| 조직 관리자 | `orgs.services.is_admin` / `require_admin` | 초대·역할·팀·보관·거버넌스 |
| superuser | `user.is_superuser` | `/ops`·Django admin |

**세 번째 조직 역할(뷰어 등)은 만들지 않는다**(§12-1). 프로젝트 관리자가 "조직 관리자와 멤버 사이"의 자리를
채우고, 그것으로 지금 요구가 다 덮인다. 역할을 늘리면 모든 `is_member` 호출을 다시 봐야 한다.

### 3.2 설정 층과 편집 권한

| 층 | 저장 | 읽기 | 편집 | 화면 |
|---|---|---|---|---|
| 사이트 | 환경 변수 | superuser(`/ops`에 표시) | 운영자(재배포) | `/ops` 읽기 전용 표 |
| 조직 | `Organization.settings` | 조직 멤버 전원(**읽기 전용으로 보인다**) | 조직 관리자 | `/orgs/<id>/settings` |
| 프로젝트 | `Project.settings` | 조직 멤버 전원 | 프로젝트 관리자 **또는** 조직 관리자. 조직 설정 `project.settings_by`가 `admin`이면 조직 관리자만 | `/projects/<id>/settings` |
| 개인 | `User.settings` | 본인 | 본인 | `/settings/preferences` |

멤버가 조직·프로젝트 설정을 **읽을 수 있어야 하는 이유**: "왜 진행 중으로 못 바꾸지?"의 답이 설정에 있다.
오류 문구가 설정 화면으로 링크한다(§7.3).

### 3.3 조직이 프로젝트를 잠그는 방식

레지스트리의 각 항목은 `scope ∈ {org, project, user}`와 `overridable: bool`을 갖는다.
`overridable=True`인 조직 항목은 프로젝트가 같은 키로 덮어쓸 수 있다.

조직 설정 화면에서 그런 항목마다 **[프로젝트가 바꿀 수 있음]** 체크가 붙는다. 끄면
`Organization.settings["_locked"]`(키 목록)에 들어가고, 프로젝트 설정 화면에서 그 항목은 조직값과
"조직에서 잠금"으로 읽기 전용이 된다. 이미 프로젝트에 저장된 값은 지우지 않고 **무시**한다(잠금을 풀면 되살아난다).

```
effective(key, project=None, user=None):
    spec = SPEC[key]
    if spec.scope == "user":            return user.settings.get(key, spec.default)
    if project and spec.overridable and key not in org.settings["_locked"]
       and key in project.settings:     return project.settings[key]
    return org.settings.get(key, spec.default)
```

한 함수다. 이것 말고 설정을 읽는 경로는 없다.

### 3.4 권한 표 (이 라운드 뒤의 최종 모습)

| 기능 | 멤버 | 프로젝트 관리자 | 조직 관리자 | 설정 키 |
|---|---|---|---|---|
| 태스크 조회·생성·수정·댓글·링크·체크리스트 | ○ | ○ | ○ | — |
| 중요도를 상한 넘게 지정 | ✕ | ○ | ○ | `task.priority_cap` |
| 프로젝트 생성 | 기본 ○ | ○ | ○ | `project.create_by` |
| 프로젝트 이름·목적·담당 팀 수정 | 기본 ○ | ○ | ○ | `project.edit_by` |
| 프로젝트 상태 변경 | 기본 ○ | ○ | ○ | `project.status_by` |
| 프로젝트 관리자 지정·해제 | ✕ | ○ | ○ | 고정 |
| 프로젝트 보관·복원 | ✕ | 기본 ✕ | ○ | `project.archive_by` |
| 프로젝트 설정 편집 | ✕ | 기본 ○ | ○ | `project.settings_by` |
| 저장소 연결·해제·자동 전환 규칙 | **지금 ○ → ✕** | ○ | ○ | 고정(프로젝트 설정의 일부가 된다) |
| 마일스톤·의존성 편집 | 기본 ○ | ○ | ○ | `project.roadmap_by` |
| 팀 생성·편집·멤버 | ✕ | ✕ | ○ | 고정 |
| 내 스킬 태그 수정 | 기본 ✕ | — | ○ | `org.tags_by` |
| 초대 발급·폐기, 역할 변경, 멤버 제거 | ✕ | ✕ | ○ | 고정 |
| 거버넌스 본문 | 읽기 | 읽기 | ○ | 고정 |
| 프로젝트 거버넌스 추가 문단 | 읽기 | ○ | ○ | 프로젝트 설정 편집 권한과 같다 |
| 조직 설정 | 읽기 | 읽기 | ○ | 고정 |
| 개인 설정 | 본인 | 본인 | 본인 | 고정 |
| 설정 변경 이력 보기 | ○ | ○ | ○ | — |

"기본 ○"는 조직이 설정으로 `owner`(프로젝트 관리자 이상)나 `admin`(조직 관리자만)으로 좁힐 수 있다는 뜻이다.
**넓히는 방향의 설정은 없다.** 조직 관리자만 할 수 있는 일을 멤버에게 여는 키는 두지 않는다.

`저장소 연결` 행이 유일하게 **권한이 줄어드는** 항목이다. 지금은 조직 멤버 누구나 자동 전환 규칙을 끄고 켤 수 있는데,
프로젝트 설정의 일부로 옮기면서 프로젝트 관리자·조직 관리자로 좁힌다. 근거: 규칙을 끄면 웹훅이 태스크를 안 옮기므로
프로젝트 전체의 동작이 바뀐다. 이것은 설정이지 데이터 편집이 아니다.

### 3.5 AI(MCP)·Discord·API 토큰의 위치

| 경로 | 행위자 | 설정에 대한 권한 |
|---|---|---|
| 웹 세션 | 그 사람 | 위 표 그대로 |
| API `write` 토큰 | 토큰 주인 | 위 표 그대로 + `PUT /settings`도 가능(자기가 웹에서 할 수 있는 만큼) |
| API `read`·`bot` 토큰 | — | `GET /settings`만 |
| MCP | 토큰 주인, `source="mcp"` | **읽기만.** `get_settings` 도구. 쓰기 도구 없음. 그리고 `ai.*` 항목이 이 경로에만 추가로 적용된다 |
| Discord 슬래시·DM | 연결된 그 사람, `source="dc"` | 설정 명령 없음. `ai.*`는 적용되지 않는다(사람이다) |
| GitHub 웹훅 | `actor=None`, `source="gh"` | 자동 전환 규칙(`rule_*`)만 본다. `task.*` 규칙(동시 진행 한도 등)은 **적용하지 않는다** — 머지가 태스크를 완료로 옮기는데 "review를 거치지 않았다"고 막으면 GitHub와 PM이 어긋난다 |

마지막 행이 중요하다. 설정은 **사람의 입력**을 막는 것이다. 외부 사실(머지됐다)을 받아 적는 경로는 막지 않는다.
`_require_member(actor=None)`이 이미 그 경계를 표시하고 있으므로 같은 자리에서 분기한다.

---

## 4. 설정 항목 전체 목록

표기: **키** · 형(범위) · 기본값 · 층 · P=프로젝트 덮어쓰기 가능 · 강제 지점.
기본값은 전부 "지금 동작"이다. `0`·`off`·`member`가 대부분인 이유다.

### 4.1 태스크 규칙 (`task.*`) — 조직, 대부분 P

| 키 | 형 | 기본 | P | 무엇 | 강제 지점 |
|---|---|---|---|---|---|
| `task.default_priority` | int 1~10 | 5 | ○ | 생성 폼·API·MCP·슬래시의 초기 중요도 | `create_task` 기본값, 폼 initial, MCP `create_task` 설명에 "기본값은 조직 설정" |
| `task.priority_cap` | int 0~10 (0=없음) | 0 | ○ | 이 값 초과 중요도는 프로젝트 관리자·조직 관리자만 지정 | `tasks.services._validate` — `priority > cap and not (is_owner or is_admin)` → `{"priority": "중요도 N 이상은 프로젝트 관리자만 정할 수 있어요."}` |
| `task.require_done_when` | bool | off | ○ | 완료 조건 없이는 생성 불가 | `create_task` |
| `task.due_required` | bool | off | ○ | 기한 미정 사유로 대신할 수 없다. 기한 필수 | `_validate` — `due_date is None` → 오류 |
| `task.default_due_days` | int 0~30 (0=없음) | 0 | ○ | 생성 폼과 `doing` 전환 대화상자의 기한 **초기값**을 오늘+N영업일로 제안. 자동으로 채우지 않는다 | 폼 initial만. API·MCP는 제안하지 않는다(값을 안 주면 지금처럼 사유 필수) |
| `task.doing_limit` | int 0~10 (0=없음) | 0 | ✕ | 한 사람이 동시에 `doing`으로 둘 수 있는 수. 사람 단위라 프로젝트 덮어쓰기 없음 | `transition(new="doing")` — 담당자의 조직 내 `doing` 수 ≥ 한도 → 오류. 모드는 아래 |
| `task.doing_limit_mode` | `warn`\|`block` | `warn` | ✕ | `warn`이면 막지 않고 행·패널에 "동시 진행 3/2" 경고 배지 | `block`만 services. `warn`은 `today_view`·패널 컨텍스트에 숫자 |
| `task.review_required` | bool | off | ○ | `done`은 `review`에서만 진입 | `transition(new="done")` — `old != "review"` → `{"status": "검토 대기를 거쳐야 완료할 수 있어요."}` |
| `task.self_review` | bool | on | ○ | off면 `review → done`을 담당자 본인이 못 한다 | `transition` — `actor == task.assignee` → 오류. `review_required`가 off면 무의미하므로 화면에서 비활성 |
| `task.reopen_reason_required` | bool | off | ○ | 완료·취소 → 재개 시 사유 필수 | `transition` — 이미 `reason`을 받는다. 빈 값 검사만 추가 |
| `task.cancel_reason_required` | bool | off | ○ | 취소 시 사유 필수 | `transition(new="cancelled")` |
| `task.assignee_change_reason` | bool | off | ○ | 담당자 변경 시 사유 필수(이력 note에 남는다) | `update_task` — `changes`에 `assignee`가 있으면 `reason` 인자 필수. **`update_task`에 `reason=""` 인자 추가**, 웹 패널 담당자 선택에 사유 칸(조건부), API·MCP `reason` 필드 |
| `task.due_change_reason` | bool | off | ○ | 기한 변경(연장 외 단축·삭제 포함) 시 사유 필수 | `update_task` — `due_date` 변경. `extend_due`는 이미 필수 |
| `task.overdue_grace_days` | int 0~14 | 0 | ○ | 초과 N일까지는 화면 "기한 초과" 강조와 알림 `overdue` 종류에서 제외 | `Task.is_overdue`는 그대로(사실). 화면 배지·`notify.classify`·`org_status.overdue`가 `today - grace`로 판정. **집계 세 곳이 한 함수(`common.dates.overdue_before(org)`)를 쓴다** |

**넣지 않는 것**: 체크리스트 전부 완료 시 자동 완료(PLAN §3에서 명시적으로 배제), 사용자 정의 상태·전이(SPEC §2 제외),
태스크 번호 접두어(§12-2), 중요도 티어 경계 변경(화면·Discord·문서 전부에 8/4가 박혀 있어 값어치보다 비싸다).

### 4.2 프로젝트 규칙 (`project.*`) — 조직, P 없음

권한을 정하는 항목이라 프로젝트가 스스로 덮어쓸 수 없다.

| 키 | 형 | 기본 | 무엇 | 강제 지점 |
|---|---|---|---|---|
| `project.create_by` | `member`\|`admin` | `member` | 프로젝트 생성 | `create_project` |
| `project.edit_by` | `member`\|`owner`\|`admin` | `member` | 이름·목적·담당 팀 수정 | `update_project` — `owners`·`status` 변경은 별도 키 |
| `project.status_by` | `member`\|`owner`\|`admin` | `member` | 프로젝트 상태 변경 | `update_project` — `"status" in changes` |
| `project.archive_by` | `owner`\|`admin` | `admin` | 보관·복원 | `archive_project`·`restore_project` |
| `project.settings_by` | `owner`\|`admin` | `owner` | 프로젝트 설정(저장소 규칙·거버넌스 추가 문단 포함) 편집 | `set_project_settings`, `repo_settings` 뷰, `connect_repo`·`disconnect` |
| `project.roadmap_by` | `member`\|`owner`\|`admin` | `member` | 마일스톤·의존성 생성·수정·삭제 | `create_milestone` 등 6개 |
| `project.owner_required` | bool | off | 관리자 0명인 프로젝트를 만들거나 마지막 관리자를 뺄 수 없다 | `_validate(owners)`. 기존 0명 프로젝트는 그대로 두고 조직 개요의 "관리자 없는 프로젝트" 표가 경고한다 |
| `project.default_view` | `list`\|`board` | `list` | 프로젝트 화면 첫 진입 보기 | 뷰. **P ○** (이것만 덮어쓰기 가능) |

`owner`는 "프로젝트 관리자 이상"(조직 관리자 포함)이다. 판정 헬퍼 하나:

```python
# projects/services.py
def require_level(actor, project, level: str, key: str):
    """level: member|owner|admin. 부족하면 ServiceError({key: ...}).
    조직 관리자는 항상 통과한다."""
```

### 4.3 조직 운영 (`org.*`) — 조직, P 없음

| 키 | 형 | 기본 | 무엇 | 강제 지점 |
|---|---|---|---|---|
| `org.invite_days` | int 1~90 | 7 | 초대 링크 기본 만료일(발급 폼 초기값) | `create_invite(days=None)` → 설정값 |
| `org.invite_max_uses` | int 0~100 (0=무제한) | 0 | 초대 링크 1개의 최대 사용 횟수 | **`Invite.max_uses` 필드 추가**(발급 시 설정값 복사). `join_by_token` — `use_count >= max_uses` → 만료 문구 |
| `org.tags_by` | `admin`\|`self` | `admin` | 스킬 태그를 본인이 고칠 수 있는지 | `set_tags` — `self`면 `actor == membership.user`도 통과 |
| `org.team_join_self` | bool | off | 멤버가 스스로 팀에 들어가고 나갈 수 있다 | `add_team_member`·`remove_team_member` — `actor == user`면 통과. GitHub 팀 연결이 있으면 동기화가 그 사람 토큰으로 나간다(V2-08 원칙 그대로) |

**넣지 않는 것**: 기본 역할(항상 `member`), 초대 발급 권한(항상 관리자), 팀 CRUD 권한(항상 관리자), 시간대·주 시작 요일(§12-3).

### 4.4 AI 정책 (`ai.*`) — 조직, P 없음, `source="mcp"`에만 적용

거버넌스 §8 "사람에게 확인받고 하는 것"을 기계 규칙으로 옮긴다. 값은 `allow`·`deny` 둘이고,
**`pending`(승인 대기)은 4단계(§10)에서 열린다.** 레지스트리에는 처음부터 세 값을 적어 두되 `pending`은
4단계 전까지 화면에서 고를 수 없다.

| 키 | 기본 | 막는 것 | 강제 지점 |
|---|---|---|---|
| `ai.create_task` | `allow` | `create_task` | `create_task(source="mcp")` |
| `ai.edit_text` | `allow` | 제목·설명·완료 조건·다음 행동·메모·체크리스트 | `update_text`·`replace_checklist` |
| `ai.change_assignee` | `allow` | 담당자 변경 | `update_task` — `"assignee" in changes` |
| `ai.change_due` | `allow` | 기한 변경·연장·삭제 | `update_task`·`extend_due` |
| `ai.change_priority` | `allow` | 중요도 변경 | `update_task` |
| `ai.priority_cap` | int 0~10, 기본 7 | 이 값 초과 중요도 지정(생성·수정) | `_validate` — `source == "mcp" and priority > cap`. `task.priority_cap`과 별개로 **둘 다** 본다 |
| `ai.transition_open` | `allow` | 미완료 5개 사이 전이 | `transition` |
| `ai.close_task` | `allow` | `done`·`cancelled` 진입 | `transition` |
| `ai.reopen_task` | `allow` | 완료·취소 → 재개 | `transition` |
| `ai.manage_teams` | `allow` | 팀 생성·팀원 넣고 빼기 | `create_team`·`add_team_member`·`remove_team_member` |
| `ai.enabled` | `on` | off면 이 조직에 대한 **모든 MCP 쓰기**를 막는다. 읽기는 남는다 | 위 전부의 앞단. 한 함수 `_ai_check(org, action, source)` |

거부 문구는 하나의 형식이다: `"이 조직 설정에서 AI의 {행동}이 꺼져 있어요. 사람이 웹에서 해 주세요."`
MCP 도구는 이 문구를 그대로 돌려주고, INSTRUCTIONS에 "설정에 막힌 일은 우회하지 말고 사람에게 넘긴다"를 넣는다.

기본값이 전부 `allow`인 이유: 지금 동작을 바꾸지 않는다(원칙 8). 거버넌스 기본안 §8은 "확인받고 하는 것"을
권하지만 코드는 막지 않았다. 조직이 `deny`로 바꾸는 순간부터 기계가 막는다. **단, `ai.priority_cap=7`은
기본값부터 강제한다** — 거버넌스 기본안이 이미 숫자를 못 박았고, AI가 전부 10을 찍는 것이 실제로 관찰된 문제다.

`source` 값은 이미 있다. MCP 서버는 모든 요청에 `X-Source: mcp` 헤더를 보내고(`mcp_server/core_client.py`),
core의 `api/context.py: ctx()`가 그것을 `source="mcp"`로 바꿔 services에 넘긴다. 사람이 API `write` 토큰으로
직접 부르면 헤더가 없어 `source="api"`라 `ai.*`가 걸리지 않는다. **새 필드도 새 토큰 종류도 필요 없다.**
`# ponytail: 헤더는 자기 신고다. 같은 토큰을 헤더 없이 쓰면 ai.* 를 피할 수 있다. 자기 권한 안에서만 움직이므로 권한 상승은 아니다. 조직이 그것까지 막으려면 OAuth 2.1 + 클라이언트 등록이 필요하다(후속).`

### 4.5 알림 (`notify.*`) — 조직(일부 P), 개인 덮어쓰기는 §4.6

`discord_service`가 매 틱 core에서 읽는다. `.env.discord`의 `SEND_HOUR`·`WEEKLY_*`는 **조직이 값을 안 정했을 때의
기본값**으로 남긴다(설정 레지스트리의 default가 아니라 서비스 쪽 fallback).

| 키 | 형 | 기본 | P | 무엇 | 읽는 곳 |
|---|---|---|---|---|---|
| `notify.deadline_kinds` | set ⊆ {d3,d1,d0,overdue} | 전부 | ✕ | 보내는 마감 알림 종류 | `notify.run_deadlines` — 종류 필터 |
| `notify.send_hour` | int 0~23 | (env) | ✕ | 마감 DM 시각 | `scheduler` |
| `notify.overdue_repeat` | `daily`\|`weekdays`\|`weekly`\|`never` | `daily` | ✕ | 초과 알림 반복 | `run_deadlines` — 요일 검사 |
| `notify.quiet_weekend` | bool | off | ✕ | 토·일에는 마감 DM을 보내지 않는다(월요일에 몰아서) | `scheduler` |
| `notify.weekly_enabled` | bool | on | ✕ | 주간 보고 | `scheduler` |
| `notify.weekly_weekday` · `notify.weekly_hour` | int | (env) | ✕ | 주간 보고 시각 | `scheduler` |
| `notify.blocked_escalate_days` | int 0~14 (0=끄기) | 0 | ○ | `blocked`가 N일 넘으면 프로젝트 관리자에게 DM(하루 1건, 프로젝트별 묶음) | **새 틱 작업 `escalate.py`**. `stopped_at` 기준. 관리자가 0명이면 조직 관리자 |
| `notify.review_nudge_days` | int 0~14 (0=끄기) | 0 | ○ | `review`가 N일 넘으면 프로젝트 관리자에게 DM | 같은 파일 |
| `notify.project_channel_events` | set ⊆ {created, done, blocked, overdue_daily, milestone_due} | ∅ | ○ | 프로젝트 Discord 채널에 게시할 사건. 채널이 연결된 프로젝트만 | **새 틱 작업 `channels_post.py`**. IMPL-PLAN-3 §13이 후속으로 미룬 "채널 라우팅"이 이것이다 |
| `notify.team_channel_weekly` | bool | off | ✕ | 주간 보고를 조직 채널 외에 팀 채널에도(팀 담당 프로젝트만 추려서) | `weekly` |

채널 게시는 **개인 정보가 아닌 것만** 올린다. `created`·`done`·`blocked`는 태스크 번호·제목·담당자 표시 이름까지.
멘션은 넣지 않는다(마감 DM 원칙과 같다).

`escalate`·`channels_post`는 `notify`와 같은 SQLite `sent` 표에 `(kind, key, day)`로 중복을 막는다. 새 표를 만들지 않는다.

### 4.6 개인 설정 (`user.*`) — 본인만

| 키 | 형 | 기본 | 무엇 | 읽는 곳 |
|---|---|---|---|---|
| `user.notify_dm` | bool | on | off면 **모든** 개인 DM(마감·에스컬레이션)을 받지 않는다. 주간 보고(채널)는 그대로 | `discord_service` — 멤버 목록의 `notify` 필드 |
| `user.notify_kinds` | set ⊆ {d3,d1,d0,overdue} | 조직값 | 조직이 켠 종류 중 내가 받을 것. 조직이 끈 종류는 켤 수 없다(교집합) | 같음 |
| `user.notify_hour` | int 0~23 \| null | null(조직값) | 내 마감 DM 시각 | `scheduler`가 사람별로 시각을 본다. 틱이 60초라 가능하다 |
| `user.start_page` | `today`\|`me` | `today` | 로그인 후 첫 화면 | `auth.root` |
| `user.me_group` · `user.me_sort` | 기존 옵션 값 | `due`·`due` | 내 태스크 기본 묶음·정렬 | `me` 뷰 initial |
| `user.board_default` | bool | off | 프로젝트 화면을 항상 보드로 | 프로젝트 뷰(프로젝트 설정보다 우선) |
| (기존) `auto_pull_days` | 필드 그대로 | 5 | 옮기지 않는다 | — |

**개인 설정에 규칙은 없다.** `task.*`를 개인이 완화하는 키는 어떤 것도 두지 않는다.

### 4.7 사이트 설정 — 환경 변수, `/ops` 표시

| 변수 | 기본 | 무엇 |
|---|---|---|
| `SIGNUP_OPEN` | `1` | 0이면 `/signup` 닫힘. 초대 링크로 들어온 사람만 가입(링크에 가입 폼) |
| `ORG_CREATE_BY` | `anyone` | `superuser`면 `/orgs/new`가 superuser에게만. PLAN §12-1 미결의 답 |
| `SITE_NAME` | `산돌이 업무` | 이미 있다 |

DB에 두지 않는 이유: 바꾸는 사람이 운영자 한 명이고, 바꾸는 일이 연 1회다. `/ops`에 현재 값을 표로 보여 주기만 한다.

### 4.8 개수

| 층 | 항목 수 |
|---|---|
| 조직 `task.*` | 14 |
| 조직 `project.*` | 8 |
| 조직 `org.*` | 4 |
| 조직 `ai.*` | 11 |
| 조직 `notify.*` | 11 |
| 개인 `user.*` | 7 (+ 기존 1) |
| 사이트 | 2 (+ 기존 1) |
| **합** | **57** |

많아 보이지만 레지스트리 한 줄 + 강제 지점 한 곳이 규칙이라 항목당 비용은 작다. 화면은 레지스트리를 돌며
그리므로 항목 수와 무관하게 템플릿 하나다.

---

## 5. 데이터 모델

새 앱 없음. 새 표 없음. 필드 다섯(JSON 셋 + 텍스트 하나 + 정수 하나).

```python
# orgs.Organization
settings = models.JSONField("설정", default=dict, blank=True)
#   {"task.priority_cap": 7, "_locked": ["task.review_required"], ...}

# projects.Project
settings = models.JSONField("설정", default=dict, blank=True)
governance_extra = models.TextField("프로젝트 거버넌스", blank=True)   # GOVERNANCE.md §3

# accounts.User
settings = models.JSONField("설정", default=dict, blank=True)

# orgs.Invite
max_uses = models.PositiveIntegerField("최대 사용 횟수", default=0)      # 0=무제한

# tasks.ChangeLog
TARGETS += ("org", "org")            # max_length=10 안. 설정 변경 이력용
```

`RepoConnection.rule_*` 다섯과 `import_label`·`assignee_default`·`auto_import`는 **옮기지 않는다.**
이미 열이 있고 웹훅 처리기가 직접 읽는다. 프로젝트 설정 화면이 그 폼을 **같은 페이지에** 그리고,
편집 권한만 `project.settings_by`로 좁힌다. 저장 경로는 지금 `repo_settings` 뷰 그대로에 권한 검사 한 줄.

`_locked`는 설정 JSON 안의 예약 키다. 레지스트리에 없는 키는 `_`로 시작하는 예약 키 외에는 거부한다.

---

## 6. 레지스트리와 서비스

### 6.1 `core/orgs/settings.py` (새 파일)

```python
from dataclasses import dataclass, field

@dataclass(frozen=True)
class Spec:
    key: str
    kind: str                 # bool | int | choice | set | text
    default: object
    scope: str                # org | user
    overridable: bool = False # org 항목을 프로젝트가 덮어쓸 수 있는가
    group: str = ""           # 화면 묶음: task | project | org | ai | notify | user
    label: str = ""
    help: str = ""
    choices: tuple = ()       # choice·set
    lo: int = 0               # int 범위
    hi: int = 0
    ai_only: bool = False     # source == "mcp" 에만 적용

SPECS: dict[str, Spec] = {s.key: s for s in [
    Spec("task.default_priority", "int", 5, "org", True, "task", "기본 중요도", lo=1, hi=10),
    Spec("task.priority_cap", "int", 0, "org", True, "task", "중요도 상한(초과는 프로젝트 관리자만)", lo=0, hi=10),
    ...
]}
GROUPS = [("task", "태스크 규칙"), ("project", "프로젝트 권한"), ("org", "조직 운영"),
          ("ai", "AI 정책"), ("notify", "알림"), ("user", "내 설정")]

def clean(scope: str, data: dict, *, allow_locked=False) -> dict:
    """알 수 없는 키·형·범위 → ServiceError({key: 문구}). 기본값과 같은 값은 지운다(키 없음 = 기본값)."""

def effective(key: str, *, org=None, project=None, user=None):
    """§3.3의 그 함수. 이 파일 밖에서 settings JSON을 직접 읽지 않는다."""

def enforced(org, project=None) -> list[dict]:
    """거버넌스 화면 상단 '설정에서 강제 중' 표. 기본값이 아닌 항목만 [{label, value, where}]."""
```

`Spec`은 데이터 표다. 구현체 하나짜리 추상화가 아니라 57줄의 상수를 담는 그릇이다.

### 6.2 서비스 함수 (기존 파일에 추가)

```python
# orgs/services.py
def set_org_settings(org, data: dict, actor) -> Organization     # require_admin. clean("org"). 바뀐 키마다 ChangeLog(target="org")
def set_locks(org, keys: list[str], actor)                        # require_admin. overridable 키만
# projects/services.py
def is_owner(user, project) -> bool
def require_level(actor, project, level, key)                     # §4.2
def set_project_settings(project, data, actor) -> Project         # require_level(settings_by). 잠긴 키 거부. ChangeLog(target="project")
def set_governance_extra(project, text, actor) -> Project         # 같은 권한. 5000자
# accounts/services.py
def set_user_settings(user, data) -> User                         # clean("user"). 이력 없음
```

### 6.3 강제를 심는 자리 (전부 기존 함수 안)

| 함수 | 추가되는 검사 |
|---|---|
| `tasks.services._validate` | `task.priority_cap`(actor 등급), `ai.priority_cap`(source), `task.require_done_when`, `task.due_required` |
| `tasks.services.create_task` | `ai.create_task`, `task.default_priority`(priority 인자 기본 None → 설정값) |
| `tasks.services.update_text` · `replace_checklist` | `ai.edit_text` |
| `tasks.services.update_task` | `ai.change_assignee`·`ai.change_due`·`ai.change_priority`, `task.assignee_change_reason`·`task.due_change_reason` (**새 인자 `reason=""`**) |
| `tasks.services.transition` | `task.doing_limit`(block), `task.review_required`, `task.self_review`, `task.reopen_reason_required`, `task.cancel_reason_required`, `ai.transition_open`·`ai.close_task`·`ai.reopen_task` |
| `tasks.services.extend_due` | `ai.change_due` |
| `projects.services.create_project` · `update_project` · `archive_project` · `restore_project` · 마일스톤·의존성 6개 | `project.*_by`, `project.owner_required` |
| `orgs.services.create_invite` · `join_by_token` · `set_tags` · `add/remove_team_member` · `create_team` | `org.*`, `ai.manage_teams` |
| `github.services._apply` (`actor=None`) | **아무것도 추가하지 않는다** (§3.5) |

검사는 전부 `_validate`류 함수 맨 앞의 두 줄 형태다:

```python
if source == "mcp" and effective("ai.close_task", org=org) == "deny":
    raise ServiceError({"status": ai_denied("완료·취소 처리")})
```

`source`·`actor`·`org`는 이미 모든 서비스 함수에 들어온다. **시그니처가 늘어나는 것은 `update_task(reason=)` 하나다.**

### 6.4 이력

설정 변경 = `ChangeLog(target_type="org"|"project", target_id, field=키, old, new, actor, source)`.
`_locked` 변경도 `field="_locked"`로 한 줄. 조직 설정 화면 하단에 최근 20건. 프로젝트는 기존 이력 블록에 섞인다.

---

## 7. 화면

빌드 도구 없음, HTMX + `app.css` 규칙 그대로. 템플릿 셋.

### 7.1 `/orgs/<id>/settings` — 조직 탭에 "설정" 추가

```
[개요] [팀] [부하 현황] [로드맵] [거버넌스] [회의록] [GitHub] [설정]
                                                                ^ 관리자만 탭 노출. 멤버는 URL로 열면 읽기 전용

태스크 규칙                                              [저장]
  기본 중요도            [5 ▾]                   ☑ 프로젝트가 바꿀 수 있음
  중요도 상한            [0 ▾]  0=없음           ☑
  완료 조건 필수         ☐                       ☑
  기한 필수              ☐                       ☑
  기한 제안(영업일)      [0  ]                   ☑
  동시 진행 한도         [0  ]  ( ) 경고  ( ) 차단
  검토 대기 필수         ☐                       ☑
    └ 본인 검토 허용     ☑  (검토 대기 필수가 켜졌을 때만)
  …
프로젝트 권한
  프로젝트 생성          ( ) 멤버  ( ) 관리자만
  …
AI 정책
  ⚠ 아래 항목은 MCP(AI 에이전트) 경로에만 적용됩니다. 사람이 API로 직접 부르면 걸리지 않습니다.
  AI 사용                ☑
  태스크 생성            ( ) 허용  ( ) 금지
  …
알림
  …
설정 변경 이력 (최근 20건)
  09-14 14:02  홍석영  중요도 상한  0 → 7
```

- 폼 한 개, `POST`, 전부 한 번에 저장. 항목별 저장 버튼 없음.
- "프로젝트가 바꿀 수 있음" 체크는 `overridable` 항목에만 붙고 `_locked`로 저장된다.
- 기본값이 아닌 항목은 값 옆에 작은 "기본 5" 배지. 기본값으로 되돌리기 = 그 값을 다시 고르면 된다(키가 지워진다).
- 각 항목의 `help`는 레지스트리 문구를 `<small class="muted">`로.
- 잠금 항목의 상태가 프로젝트에 미치는 영향은 "프로젝트 N개가 이 값을 덮어쓰고 있습니다"로 옆에 표시(잠그기 전에 본다).

### 7.2 `/projects/<id>/settings` — 프로젝트 탭 "설정"

```
[태스크] [API 문서] [저장소 연결] [설정]

이 프로젝트의 규칙  (조직 기본값과 다른 것만 저장됩니다)
  기본 중요도            ( ) 조직값 5   ( ) 직접: [7 ▾]
  검토 대기 필수         조직에서 잠금 · 켜짐            ← 잠긴 항목
  기한 제안(영업일)      ( ) 조직값 0   ( ) 직접: [3 ]
  첫 화면                ( ) 조직값 목록 ( ) 보드
  프로젝트 채널 게시     ☐ 생성  ☑ 완료  ☑ 막힘  ☐ 초과 일일  ☐ 마일스톤   (채널 미연결이면 회색 + 안내)
  막힘 에스컬레이션      ( ) 조직값 0   ( ) 직접: [2 ]

저장소 자동 전환   (저장소 연결 탭의 폼을 여기서도 그린다. 저장은 기존 repo_settings 경로)
  ☑ 이슈  ☑ 브랜치  ☑ 커밋  ☑ PR  ☑ 머지   가져오기 라벨 [task]  …

프로젝트 거버넌스 (조직 규칙 뒤에 덧붙는 문단)
  [textarea]                                       AI는 조직 거버넌스 + 이 문단을 함께 읽습니다.
```

- 편집 가능 여부는 `require_level(project.settings_by)`. 아니면 전부 읽기 전용 + "프로젝트 관리자만 바꿀 수 있습니다".
- "조직값 / 직접" 라디오가 덮어쓰기 유무다. 조직값을 고르면 키가 지워진다.
- 저장소 연결 탭은 남긴다(이슈 목록·이벤트 표가 거기 있다). 규칙 폼만 두 곳에서 같은 partial(`projects/_repo_rules.html`)로 그린다.

### 7.3 오류 문구 → 설정 링크

설정 때문에 막힌 오류는 문구 끝에 `(조직 설정)` 링크를 붙인다. `ServiceError`에 `hint_url` 같은 필드를 늘리지 않고,
**문구에 마커 `[설정]`을 넣고** 템플릿 필터가 그것을 링크로 바꾼다. API·MCP는 마커 없는 문구를 받는다(마커 제거는 `ServiceError.__init__`이 아니라 웹 뷰의 필터가 한다 — 서비스 문구에 마커를 넣고 API 직렬화가 `[설정]`을 벗긴다).
`# ponytail: 문자열 마커. 오류에 구조화된 힌트가 여럿 필요해지면 ServiceError(hints=) 로.`

### 7.4 `/settings/preferences` — 개인

프로필 화면 아래 카드 하나가 아니라 **별도 경로**로 둔다. 프로필은 계정 연결(Discord·GitHub) 화면이고,
취향 설정은 자주 열지 않는다. 헤더 사용자 메뉴에 "설정" 항목.

```
알림
  Discord DM 받기        ☑
  받을 마감 알림         ☑ D-3  ☑ D-1  ☑ 당일  ☑ 초과       (조직이 끈 종류는 회색)
  DM 시각                ( ) 조직 기본(09시)  ( ) 직접 [08 ▾]
화면
  첫 화면                ( ) 오늘  ( ) 내 태스크
  내 태스크 기본 묶음    [기한별 ▾]   정렬 [기한 ▾]
  프로젝트를 보드로      ☐
오늘
  마감 기준 자동 담기    (기존 폼 그대로 옮긴다. `/today/settings`는 유지)
```

### 7.5 거버넌스 화면 상단

```
설정에서 강제 중 (이 항목은 글이 아니라 기계가 막습니다)
  · 중요도 8 이상은 프로젝트 관리자만        조직 설정
  · 완료는 검토 대기를 거쳐야 함             조직 설정 · 프로젝트 3개 예외
  · AI: 담당자 변경 금지, 중요도 상한 7      조직 설정
[조직 설정으로]
```

`settings.enforced(org)`가 만든다. 기본값이 아닌 항목만. 이것으로 GOVERNANCE.md §"앞으로 1" 마지막 문단
("이 항목은 설정에서 강제됩니다 표시")이 해결된다.

### 7.6 `/ops`

사이트 환경 변수 표(`SIGNUP_OPEN`·`ORG_CREATE_BY`·`SITE_NAME`) 읽기 전용 한 블록.

---

## 8. API · MCP · Discord

### 8.1 API

| 메서드·경로 | 인증 | 하는 일 |
|---|---|---|
| `GET /api/orgs/{id}/settings` | 멤버(세션·read·write·**bot**) | `{values: {key: 유효값}, locked: [...], defaults: {...}}`. `values`는 effective가 아니라 **조직 저장값**. |
| `PUT /api/orgs/{id}/settings` | 관리자, write | 본문 `{values, locked}`. 부분 갱신 아님, 전체 교체(폼과 같다) |
| `GET /api/projects/{id}/settings` | 멤버 | `{values, effective, locked}` — `effective`가 실제 적용값 |
| `PUT /api/projects/{id}/settings` | `settings_by` 등급, write | |
| `GET · PUT /api/projects/{id}/governance-extra` | 같음 | |
| `GET · PUT /api/me/settings` | 본인 | `user.*` |
| `GET /api/orgs/{id}/members` | (기존) | 항목에 `notify: {dm, kinds, hour}` 추가 — **bot 토큰일 때만** 실린다(개인 설정이 멤버 전원에게 보일 이유가 없다) |
| `GET /api/orgs/{id}/governance` | (기존) | `enforced: [...]` 추가. `project_id`를 주면 `governance_extra`를 붙여 돌려준다 |

기존 쓰기 엔드포인트의 본문 변화: `PATCH /api/tasks/{id}`에 `reason` 선택 필드.

### 8.2 MCP

| 도구 | 변화 |
|---|---|
| `get_settings(org_id, project_id=None)` | **새로.** effective 값과 잠금. 도구 설명: "쓰기 전에 get_governance와 함께 읽는다" |
| `get_governance(org_id, project_id=None)` | `project_id`가 있으면 프로젝트 문단이 붙는다. `enforced` 포함 |
| `update_task(reason=)` | 새 인자. 설명에 "담당자·기한 변경에 조직 설정이 사유를 요구할 수 있다" |
| INSTRUCTIONS | 두 줄 추가: "설정(get_settings)은 거버넌스 글보다 우선하고 서버가 강제한다. 설정에 막힌 일은 우회하지 말고 사람에게 요청하라고 답한다" |

설정 쓰기 도구는 없다. `create_team`이 `ai.manage_teams=deny`에 걸리면 같은 문구.

### 8.3 Discord 서비스

| 자리 | 변화 |
|---|---|
| `core_client.py` | `org_settings(org_id)` (틱마다 1회, 5분 캐시), `members()`의 `notify` 필드 |
| `scheduler.py` | 시각·요일 판단이 env 대신 `설정 → env` 순. 사람별 `notify_hour`가 있으면 그 사람 묶음은 그 시각에 |
| `notify.py` | `deadline_kinds` ∩ `user.notify_kinds`, `notify_dm=off`면 건너뛰고 `skipped`가 아니라 **`opted_out`** 으로 센다(`/ops` 빨강 아님, 주간 보고 명단에 넣지 않는다 — 본인이 끈 것이다) |
| `escalate.py` (새) | `blocked_escalate_days`·`review_nudge_days`. `GET /api/tasks?org=&status=blocked` → `stopped_at` 경과 → 프로젝트 관리자 DM. 하루 1건·프로젝트별 묶음 |
| `channels_post.py` (새) | `project_channel_events`. 사건 감지는 **`ChangeLog`가 아니라 폴링 차이**로: 이전 틱 이후 `updated_at`이 바뀐 태스크를 받아 상태를 비교한다. `# ponytail: 5분 폴링, 놓친 사건은 다음 틱에. 실시간이 필요하면 core에 아웃바운드 웹훅` |
| 슬래시 명령 | 설정 명령 없음. `/태스크만들기`의 `중요도` 기본값은 core가 채운다(인자 생략 시 None을 보낸다) |

`.env.discord`의 `SEND_HOUR`·`WEEKLY_*`는 남기되 README에 "조직 설정이 있으면 그것이 우선"이라 적는다.

---

## 9. 테스트

기존 방식 그대로(pytest, 픽스처 최소). 설정마다 테스트 하나가 아니라 **경로마다** 하나다.

| 파일 | 무엇 |
|---|---|
| `orgs/tests.py` | `clean`: 모르는 키·범위 밖·형 불일치 거부, 기본값은 지워짐. `effective`: 잠금·덮어쓰기·기본값 순서. `set_org_settings` 이력 |
| `projects/tests.py` | `require_level` 3등급 × 4키. `settings_by=admin`이면 관리자가 막힘. 잠긴 키 거부. `owner_required` |
| `tasks/tests.py` | `priority_cap`(멤버 막힘·관리자 통과), `doing_limit` block/warn, `review_required`·`self_review`, 사유 필수 셋, `ai.*` 전부 `source="mcp"`에서만 막히고 `"web"`·`"dc"`·`None`에서는 통과. **기본값 회귀**: 설정이 비어 있으면 기존 306개 테스트가 그대로 통과 |
| `api/tests.py` | 설정 GET/PUT 권한 4종, bot 토큰의 members `notify` 노출, `X-Source: mcp` 요청만 `ai.*`에 걸림 |
| `github/tests.py` | `actor=None` 경로가 `task.*`·`ai.*`에 걸리지 않는다 |
| `mcp_server/tests/` | `get_settings`, 거부 문구 전달 |
| `discord_service/tests/` | 설정 우선·env fallback, `opted_out` 집계, `escalate`·`channels_post` 하루 1건 |

---

## 10. 단계

각 단계 끝에 `uv run ruff check .`·`uv run pytest -q`·`makemigrations --check`가 통과해야 다음으로 간다.

| 단계 | 내용 | 완료 조건 |
|---|---|---|
| **0. 기반** | 필드 5개 + 마이그레이션, `orgs/settings.py` 레지스트리(전 항목 정의, 강제는 아직 3개), `effective`·`clean`·서비스 3개, ChangeLog target `org`, 조직 설정 화면, API GET/PUT. 강제 3개: `task.priority_cap`·`task.review_required`·`project.create_by` | 설정을 안 건드린 조직에서 기존 테스트 전부 통과. 세 규칙이 웹·API에서 같은 문구로 막힌다 |
| **1. 규칙 전부** | `task.*` 나머지, `project.*`·`org.*` 전부, `is_owner`·`require_level`, `update_task(reason=)`, `Invite.max_uses`, 프로젝트 설정 화면·잠금·거버넌스 문단, 저장소 규칙 폼 권한 좁히기, 오류 문구 링크 | §3.4 표의 모든 행에 테스트 |
| **2. AI 정책** | `ai.*` 전부(`source="mcp"` 분기), MCP `get_settings`·INSTRUCTIONS, 거버넌스 화면 "강제 중" 블록 | MCP 테스트가 거부 문구를 받는다. 헤더 없는 같은 토큰은 걸리지 않는다 |
| **3. 알림·개인** | `notify.*`·`user.*`, 개인 설정 화면, members `notify`, discord_service 4파일 | 설정을 안 건드리면 discord 테스트 58개 그대로. `escalate` 1건 발송을 가짜 transport로 |
| **4. 승인 대기 큐** | **별도 계획서(IMPL-PLAN-5).** `PendingChange` 모델, `ai.* = pending`, 승인 화면. 이 라운드는 값만 예약한다 | — |

0 → 1 → 2는 순서대로. 3은 0 뒤면 언제든(다른 파트). 모델 분배는 기존 방식: 탐색은 Haiku, 1·3단계 구현은 Sonnet,
0(레지스트리 설계)·2(권한 경계)와 최종 검증은 Opus가 직접.

---

## 11. 하지 않는 것

| 빠지는 것 | 왜 |
|---|---|
| 항목별 편집 권한 매트릭스 | 층마다 한 규칙으로 충분. SPEC §2 "세부 필드별 권한" 제외 유지 |
| 세 번째 조직 역할(뷰어·게스트) | §12-1. 프로젝트 관리자가 그 자리를 채운다 |
| 사용자 정의 상태·전이·필드 | SPEC §2 제외 |
| 태스크 번호 접두어, 시간대, 주 시작 요일 | §12-2·3 |
| AI가 설정을 쓰는 도구 | 원칙 6 |
| 알림 문구 템플릿 편집 | 문구는 `messages.py`에 있고 조직마다 다를 이유가 아직 없다 |
| 아웃바운드 웹훅(Slack 등) | Discord 채널 게시로 대신. 요청이 오면 `channels_post`와 같은 자리 |
| 설정 가져오기·내보내기, 설정 템플릿 | 조직이 하나다 |
| 개인이 규칙을 완화하는 키 | 원칙 4 |
| `RepoConnection` 값을 JSON으로 이전 | 열이 이미 있고 웹훅이 읽는다. 옮기면 마이그레이션만 늘고 얻는 게 없다 |
| 설정 변경의 롤백 UI | 이력이 있으니 손으로 되돌린다 |

---

## 12. 미결 (기본값으로 진행 가능)

| # | 질문 | 기본 | 근거 |
|---|---|---|---|
| 1 | 조직 역할을 셋으로 늘릴까(뷰어) | **안 한다** | 모든 `is_member` 호출을 재검토해야 하고 요구가 없다. 프로젝트 관리자 등급이 먼저다 |
| 2 | 태스크 번호 접두어를 조직 설정으로 | **안 한다** | `Task.number`가 조직을 모르고, Discord 파서·검색·이력·문서가 `TASK-`를 안다. 조직이 하나다 |
| 3 | 시간대·주 시작 요일 | **안 한다** | `common/dates.py` 전체가 KST 고정. 조직이 하나다 |
| 4 | `project.settings_by` 기본값 | **`owner`** | 프로젝트 관리자에게 실제 권한을 주는 것이 이 라운드의 절반이다. `admin`이면 지금과 다를 게 없다 |
| 5 | 알림 시각을 조직 설정으로 옮길까 | **옮기되 env는 fallback** | 재배포 없이 바꿀 수 있어야 한다. env를 지우면 기존 배포가 깨진다 |
| 6 | `ai.priority_cap` 기본 7을 처음부터 강제할까 | **강제한다** | 거버넌스 기본안이 숫자를 정했고, AI가 전부 10을 찍는 문제가 실제다. 사람은 걸리지 않는다 |
| 7 | 저장소 규칙 편집 권한 축소(멤버 → 프로젝트 관리자) | **축소한다** | §3.4 근거. 지금 편집하는 사람도 사실상 프로젝트 관리자다 |

---

## 13. 다음 행동

미결 7건에 이의가 없으면 0단계부터 시작한다. 첫 작업 단위는
"필드 5개 마이그레이션 → `orgs/settings.py` 레지스트리 57항목 → `clean`·`effective` 테스트 → `task.priority_cap` 하나를 `_validate`에 심고 웹·API에서 같은 문구 확인".
이 시점에 화면은 조직 설정 하나뿐이다.

문서 갱신은 이 계획이 확정된 뒤 한 번에: GOVERNANCE.md §"앞으로 2"를 "→ IMPL-PLAN-4"로, PLAN.md 머리말에 한 줄,
GUIDE-00 §3 "설정값이 될 이유가 없는 상수를 설정으로 빼지 않는다"에 "레지스트리에 있는 것만 설정이다" 한 줄.

---

## 14. 구현하며 달라진 것 (2026-09-14)

| 계획 | 실제 | 이유 |
|---|---|---|
| §7.3 오류 문구에 `[설정]` 마커 → 링크 | **뺐다.** 문구만 남긴다 | 마커를 벗기는 자리가 API·MCP·웹 세 곳이라 값어치보다 비쌌다. 필요해지면 `ServiceError(hints=)` |
| §4.4 `ApiToken.kind` | **불필요.** MCP 서버가 이미 `X-Source: mcp`를 보내고 `api/context.py`가 `source="mcp"`로 바꾼다 | 기획 때 코드를 덜 읽었다 |
| §4.5 개인 시각(`user.notify_hour`) | 마감 작업이 **매시 1회** 돌고(`deadline-<hour>` 일일 키) 사람별 게이트가 발송을 정한다 | 최소 시각을 미리 계산하는 것보다 단순. HTTP 호출 하루 24회 |
| §4.5 팀 채널 주간 보고 | 조직 보고 전문을 담당 프로젝트가 있는 팀 채널에 그대로 게시 | 팀별 재요약은 LLM 재호출이 필요 |
| §4.5 `project_channel_events`의 `overdue_daily`·`milestone_due` | **미구현.** `created`·`done`·`blocked`만. 설정에서 고를 수는 있으나 무시된다 | 폴링 차이로 잡히지 않는 사건이라 별도 작업 |
| §6.3 `task.overdue_grace_days` | 내 태스크 화면의 "기한 초과" 묶음에만 적용. 조직 개요·부하 현황·Discord 초과 알림은 그대로 | 세 집계를 한 함수로 묶는 리팩터가 이 라운드 밖 |
| §4.6 `user.*` 6개 | 7개(`me_group`·`me_sort` 분리) | 표 오기 |
| 저장소 규칙 폼 | `projects/_repo_rules.html` partial로 뽑아 저장소 탭과 설정 탭 양쪽에서 그린다 | 계획대로 |
| 테스트 | core 385 · discord 94 · mcp 20 (SQLite). `test_me_view_sort_orders_inside_groups`는 전체 스위트에서만 간헐 실패 — §15 | |

## 15. 남은 것

- `test_me_view_sort_orders_inside_groups`: `updated_at` 정렬이 같은 시각 두 갱신에서 pk 역순으로 떨어지는 경우. 파일 단위·단독 실행은 통과하고 전체 스위트에서만 재현된다. 이 라운드 코드와 무관해 보이나 원인은 확정하지 못했다.
- Postgres에서 한 번 더 돌릴 것(`DATABASE_URL=postgres://...`). JSONField `settings__has_key` 조회가 두 DB 모두에서 동작해야 한다.
- 조직·프로젝트·개인 설정 화면을 실제 브라우저에서 한 번 볼 것(테스트는 200과 저장 결과만 본다).
- 4단계 승인 대기 큐 → IMPL-PLAN-5.
