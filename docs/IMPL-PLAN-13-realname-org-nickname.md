# IMPL-PLAN-13 — 계정 실명 + 조직 표시 이름

**판 v3 (2026-10-13)** — Fable 조건부 승인 반영. v2 대비 바뀐 점:
- 필수: 기존 시험 고정값(`core/conftest.py:41,55,63`, `core/orgs/test_member_profile.py:45,79`)을 A 갈래로(§9·§11). E의 프로필 화면이 `next`로 돌아감(§5.3). `display_for(user, org=None)` = 계정 표시 이름(§3).
- `member_info.definition()` 키 호환을 A로(§2.1). `order_by("display_name")` 담당을 B·D로 명시(§4.3·§4.4). `reports/services.py:114` ↔ `orgs/detail.html:60` 키 이름 합의(§4.2). `/표시이름` 성공 문구에 "잠시 뒤 반영"(§6.5).
- 뺌: `discord_service/commands.py:226` `real_name_required` 분기, `MeOut.real_name`, `names.scope()`, `/members` 조직별 이름.
- 시험 추가: GitHub 가입 claim 경로(`github/services.py:418-420`)도 실명 관문에 잡히는지(§11).

**판 v2 (2026-10-13)** — 사용자 결정 반영. v1 대비 바뀐 점:
- 조직 관리자는 모든 조직에서 구성원의 계정 실명을 항상 본다(실명으로 표시 옵션과 무관). §0·§6.2·§10.
- 조직 표시 이름을 Discord 명령 `/표시이름`으로도 바꾼다(본인 것만, 실명으로 표시 조직이면 거절). core 엔드포인트 하나 추가, 관리자 변경은 웹만. §6.5·§9 B.
- `set_nickname` 서비스를 갈래 A로 옮김(B·E가 같이 쓴다). §9.
- v1 §13 미결정은 모두 확정(§13 결정표). GitHub로 나가는 글은 계정 표시 이름 유지.

기준 커밋 `c9b28e4`. 코드 근거는 `파일:줄`. UI는 루트 `DESIGN.md`(토큰·컴포넌트·AI Slop 금지)를 따른다. 사용자에게 보일 글은 Sol이 쓴다 — 이 문서의 문구는 자리표시이며 §10 "문구 필요" 목록으로 넘긴다.

## 0. 요구(확정)와 한 줄 설계

| # | 요구 | 설계 |
|---|---|---|
| 1 | 가입 때 실명 필수(계정에 하나). 기존 사용자는 다음 로그인 때 입력해야 이용 | `User.real_name` 추가. 가입 폼 필수. 비어 있으면 실명 관문(웹 리다이렉트·API 403 `real_name_required`) |
| 2 | 조직 표시 이름(디스코드 서버 별명). 비면 계정 표시 이름. 본인·조직 관리자가 변경 | `OrgMembership.nickname` 추가. `orgs/names.py` 헬퍼 하나로만 읽는다 |
| 3 | 조직 옵션 "실명으로 표시": 켜면 그 조직 표시 이름 = 계정 실명(아무도 못 바꿈) | `Organization.member_fields["show_real_name"]: bool` (스키마 변경 없음) |
| 4 | 조직별 실명 폐지, 계정 실명으로 통합. 기존 값 이전 | 데이터 마이그레이션(§2.3). 추가 항목(`member_fields.fields`)은 그대로 |
| 5 (v2) | 조직 관리자는 구성원 실명을 항상 열람 | 관리자용 구성원 목록에 실명 열(§6.2). 옵션·옛 모드와 무관 |
| 6 (v2) | 본인 조직 표시 이름을 Discord 명령으로 변경 | `/표시이름` + `POST /api/integrations/discord/orgs/nickname`(§6.5) |

표시 이름 결정 규칙(유일한 규칙, `orgs/names.py`):

```
display_for(user, org=None):
  user is None                            → ""
  org is None                             → user.display_name   (v3: 조직 맥락이 없는 자리 — 계정 표시 이름)
  m = 그 조직 구성원 행(없으면 None)
  org.show_real_name and user.real_name  → user.real_name
  m and m.nickname                        → m.nickname
  else                                    → user.display_name   (탈퇴자는 "탈퇴한 사용자", accounts/services.py:291)
```

- 실명으로 표시 조직에서는 `nickname`을 무시한다(값은 지우지 않는다 — 옵션을 끄면 되살아난다).
- 실명 바꾸면 실명 표시 조직 이름도 즉시 바뀐다(저장된 사본이 없고 읽을 때 계산).
- 조직을 떠난 사람(구성원 행 없음)은 계정 표시 이름으로 보인다.

## 1. 현재 상태(근거)

- 계정 표시 이름: `core/accounts/models.py:14`(50자), 빈 값이면 username으로 채움 `:34-36`, `__str__`이 표시 이름 `:39-40`.
- 조직 실명: `core/orgs/models.py:78` `OrgMembership.real_name`(50자), 항목 정의 `core/orgs/models.py:51` `member_fields`, 모드 off/optional/required `core/orgs/member_info.py:22`, 필수 판정 `:115-121`, 저장 `:130-157`, 요약 `:109-112`. 탭 표시 조건 `core/orgs/models.py:59-63`.
- 실명이 보이는 곳: 관리자용 구성원 표 `core/web/templates/orgs/teams.html:32`, 입력 화면 `orgs/member_info.html:7-13`, 조직 설정 카드 `orgs/settings.html:35`, 뷰 `core/web/views/orgs.py:619,664,681,686,695`. API·MCP·AI·Discord에는 조직 실명이 나가지 않는다(grep `real_name` 결과 위가 전부).
- 차단 관문: 웹 `core/common/middleware.py:29-75`(MemberInfoGate, 열린 화면 `:23`), API `core/api/auth.py:12-24`, 403 응답 `core/api/api.py:85-98`. 소비처: `skills/pm/scripts/pm.py:152`, `mcp_server/mcp_server/core_client.py:47`, `discord_service/discord_service/commands.py:226`.
- API 사용자 직렬화는 거의 전부 `core/tasks/brief.py:6-10` `user_brief()` 한 곳을 지난다(호출처 `core/api/serialize.py:33,65,79,92,144,191,193,214`, `core/reports/services.py:104,145,293`, `core/api/routers/orgs.py:77`).
- 가입: `core/web/views/auth.py:102-120`(signup), `:140-168`(_claim, 같은 `SignupForm` 사용), 폼 `core/web/forms.py:48-62`. GitHub 가입 `core/github/services.py:420-428`, 확인 화면 `core/web/views/github.py:251`.
- 실시간: `orgs_orgmembership`·`accounts_user` 행 변경이 이미 조직 키(`O:`)를 낸다 `core/web/realtime/keys.py:106-116` → 새 열도 자동 반영, 변경 불필요.
- 처리방침 `core/web/content/privacy.md:18-20,52-54,100,137`, 약관 정의 `core/web/content/terms.html:22`, 제6조 `:42-54`, 문서 판 `core/accounts/consents.py:14`(terms v3, privacy v4).

## 2. 데이터 모델·마이그레이션

### 2.1 스키마

| 모델 | 변경 |
|---|---|
| `accounts.User` | `real_name = CharField("실명", max_length=50, blank=True)` |
| `orgs.OrgMembership` | `nickname = CharField("조직 표시 이름", max_length=50, blank=True)`. `real_name`은 **이번 판에는 남기고 쓰지 않는다**(되돌리기용). 다음 판에서 삭제 |
| `orgs.Organization.member_fields` | JSON 모양 변경: `{"show_real_name": bool, "fields": [...]}`. 옛 `real_name` 키는 `_legacy_real_name`으로 옮겨 둔다(되돌리기용, 다음 판에서 삭제) |

`Organization.member_info_on`(`orgs/models.py:59-63`)은 `bool(fields)`만 보도록 바꾼다. 단, §6.3에서 구성원 정보 화면이 "내 조직 표시 이름" 편집 자리도 겸하므로 탭은 항상 보인다.

(v3, 갈래 A) 키 호환은 **읽는 쪽 한 곳**에서 한다: `member_info.definition()`(`orgs/member_info.py:39-41`)이 `{"show_real_name": bool, "fields": [...]}`를 돌려주고, 마이그레이션 전 모양(`real_name` 키만 있는 행)이면 `real_name == "required"`를 `show_real_name`으로 읽는다. 그래서 0014 적용 전후·되돌리기 중에도 화면·`names.org_names`가 깨지지 않는다. `names.org_names`도 이 함수로 옵션을 읽는다. `set_definition`·`summary`·`missing`의 실명 조건 정리(§6.1)도 A가 같은 파일에서 한다 — `orgs/member_info.py`는 A 독점, E는 뷰·템플릿만.

### 2.2 마이그레이션 파일(한 갈래 A만 만든다)

Postgres에서 DML 뒤 같은 트랜잭션의 DDL은 지연 트리거 오류가 난다(전례 `core/notes/migrations/0004_merge_into_doc.py:6`, `0005_merge_into_doc_data.py:13`). 스키마와 데이터를 파일로 나눈다(마이그레이션마다 트랜잭션 하나).

1. `accounts/0010_user_real_name.py` — AddField.
2. `orgs/0013_orgmembership_nickname.py` — AddField, 의존: accounts 0010.
3. `orgs/0014_real_name_to_account.py` — RunPython(forward, backward)만.
4. (다음 판) `orgs/0015_drop_membership_real_name.py` — RemoveField + `_legacy_real_name` 정리. 이번 배포에 넣지 않는다.

### 2.3 데이터 이전 규칙(0014 forward)

조직 정의:
- `real_name == "required"` → `show_real_name = True`
- `"optional"`, `"off"`, 키 없음 → `False`
- 옛 값은 `_legacy_real_name`에 보관.

계정 실명(`User.real_name`이 빈 사람만):
- 그 사람의 `OrgMembership.real_name`을 모은다. 앞뒤 공백 제거·연속 공백 하나로 줄인 뒤 빈 값 제외, 중복 제거.
- **한 가지** → 그 값을 `User.real_name`에 넣는다.
- **두 가지 이상(충돌)** → 계정 실명은 비워 둔다(관문이 입력을 요구). 후보를 `user.settings["real_name_candidates"]`에 가입 시각 최신순으로 넣는다. 입력 화면이 후보를 고르기 버튼으로 보여 주고, 저장하면 이 키를 지운다.
  - 제안 이유: 어느 값이 맞는지 서버가 고르면 틀린 실명이 실명 표시 조직 전체에 퍼진다. 본인이 한 번 고르게 한다.
- 이전한 사람·충돌한 사람 수를 `print`로 남겨 리허설·배포 로그에서 확인한다.
- `bulk_update(batch_size=500)`, `.iterator()`.

backward: `member_fields`를 `_legacy_real_name`에서 복원하고 `show_real_name`을 지운다. `real_name_candidates` 키를 지운다. `User.real_name`은 0010 되돌리기로 열과 함께 사라진다. `OrgMembership.real_name`은 그대로 있어 손실 없음.

### 2.4 Postgres 리허설(배포 전 필수)

메모 규칙 "마이그레이션 Postgres 리허설": SQLite 테스트로는 지연 트리거 실패를 못 잡는다.
1. 임시 Postgres 컨테이너에 운영 최신 덤프(예: `db-20261013-081547.dump` 이후 것)를 복원.
2. `uv run python manage.py migrate` → 0010·0013·0014 통과, 출력의 이전·충돌 수 기록.
3. 표본 확인: 실명 required 조직 → `show_real_name` True, 한 가지 실명 사용자 이전, 충돌 사용자 후보 저장.
4. `migrate orgs 0012` → `migrate accounts 0009` 되돌리기 → 다시 앞으로. 두 번 모두 통과해야 배포.

## 3. 표시 이름 헬퍼(`core/orgs/names.py`, 새 파일)

```python
_scope: ContextVar[dict | None]           # 요청 하나 동안의 조직별 이름표
def org_names(org_id) -> dict[int, str]   # 쿼리 1회: 구성원 행 + user.real_name/display_name + 조직 플래그
def display_for(user, org=None) -> str    # org는 객체·id·None. None → 계정 표시 이름. user None → ""
def sort_by_name(users, org) -> list      # 이름순 목록(아래 order_by 대체)
def forget(org_id)                        # 표시 이름·실명·옵션을 바꾼 서비스가 부른다
```

- (v3) `org=None` 규칙은 조직을 정할 수 없는 호출처를 위한 것이다: `web/views/common.py:231-233`(태스크 이력 담당자·검토자), `:240`(owners), `:262`(이력 행위자)는 `history_rows(logs, viewer, org=None)`로 조직을 받되, 조직 없이 부르는 기존 호출은 계정 표시 이름 그대로 나온다(동작 불변).
- (v3) `scope()` 컨텍스트 매니저는 두지 않는다. 요청 밖(assist 워커 등)에서는 `ContextVar` 기본값 None → 캐시 없이 매번 조회한다(워커 호출은 작업당 몇 번뿐).

- 캐시: 요청 단위 `ContextVar` 하나. 미들웨어(`common/middleware.py`에 함수형 `names_scope` 한 개 추가, `config/settings.py:55-68` 목록에 등록)가 요청마다 비운다. 프로세스 간 캐시(Django cache)는 두지 않는다 — 무효화 비용이 이득보다 크다. `# ponytail: 요청 단위 캐시. 조직 수천 명이면 org_names를 필요한 user_id만 읽게 바꾼다.`
- N+1: 목록 화면은 `org_names(org_id)` 한 번(조직당 쿼리 1개)이면 행 수와 무관. 여러 조직 화면(오늘·검색·요청함)은 화면에 나온 조직 수만큼.
- 템플릿 필터: `core/web/templatetags/names.py` — `{{ u|name_in:org }}`(org는 객체·id 모두). `user.display_name` 직접 출력은 계정 화면 말고는 금지(§4.6 grep 검사).
- `order_by("display_name")` / `order_by("user__display_name")`는 표시 이름이 바뀌면 순서가 어긋난다 → `sort_by_name`으로 파이썬 정렬(구성원 수 수백 이하 가정).
- `User.__str__`(`accounts/models.py:39`)은 그대로 계정 표시 이름(관리자 화면·로그용).

## 4. 이름 표시 지점 전수와 규칙

### 4.1 맥락 규칙

| 화면·출력 | 쓰는 이름 |
|---|---|
| 조직 화면(조직·프로젝트·태스크·팀·문서·회의록·요청 등) | 그 조직의 표시 이름 |
| 여러 조직 화면(오늘·내 할 일·검색·요청함) | **행마다 그 객체가 속한 조직**의 표시 이름. 머리말 인사·내 메뉴처럼 조직이 없는 자리는 계정 표시 이름 |
| 개인 설정·계정·내 메뉴(`base.html:58,60`) | 계정 표시 이름(+ 설정에서 본인 실명) |
| 운영 콘솔(`/ops/`) | 계정 표시 이름 + 실명 + 아이디 |
| API·MCP·Discord(조직에 묶인 응답) | 그 조직의 표시 이름(§7, 키 이름 유지) |
| 외부 서비스로 나가는 글(GitHub) | 계정 표시 이름 유지(실명이 GitHub로 나가지 않게) — 확정 |
| 이미 저장된 기록 문자열(ChangeLog 값 등) | 저장 당시 문자열 그대로(소급 안 함) |

### 4.2 템플릿(`display_name` 65곳 / 33개 파일, `grep -rn display_name core/web/templates`)

조직 맥락 → `|name_in:<org>`로 교체:

| 파일:줄 | 조직 값 |
|---|---|
| `assist/_candidates.html:29` | `job.org` |
| `auth/claim.html:5` | `invite.org`(가입 전 계정이라 대개 계정 이름과 같음) |
| `docs/index.html:75,76` · `docs/_extras.html:13,61` | `doc.org_id` |
| `me.html:9` | 현재 조직 |
| `notes/list.html:45,72,83,88,94` | `note.org_id` |
| `orgs/capacity.html:24,59` · `orgs/change_request.html:14,52` · `orgs/detail.html:40,60` · `orgs/discord.html:9,46` · `orgs/teams.html:16,19,24,37,44` · `orgs/teams_member.html:14` · `orgs/team_detail.html:51,61` · `orgs/team_view.html:17` · `orgs/_pending_requests.html:6` | `org` |
| `projects/detail.html:9` · `projects/_dialog.html:9` · `projects/_task_form.html:6` | `project.org_id` |
| `requests/detail.html:12,13,23,25,43` · `requests/index.html:25,48,50` · `requests/new.html:26` | `req.org_id` / 행의 `org_id` / 고른 조직 |
| `tasks/_attachments.html:9` · `tasks/_decisions.html:29,31` · `tasks/_duplicate.html:8` · `tasks/_panel.html:62,63,65,74,75` · `tasks/_row.html:12` · `tasks/_split.html:7` · `tasks/_split_hint.html:1` · `tasks/_subtasks.html:21,42` | `task.project.org_id` |

바꾸지 않음(계정 맥락): `base.html:58,60`, `today/_head.html:5`, `oauth/authorize.html:6`(`{{ user }}`).
운영 콘솔: `ops/user.html:7`, `ops/users.html:19` → 계정 표시 이름 옆에 실명 열 추가.
그대로(Discord 쪽 이름): `orgs/discord.html:63,65,68`은 `DiscordChannelAlert.display_name`(`orgs/models.py:232`, Discord 닉네임)이라 대상 아님.
`orgs/detail.html:60`은 `values("assignee__display_name")`(`reports/services.py:114`) 결과 → 서비스에서 이름을 채워 넘긴다. (v3 키 합의) B가 `reports/services.py:114`의 `by_assignee` 행에 **`assignee_name`**(조직 표시 이름) 키를 새로 넣고 `assignee__display_name` 키는 남긴다(API·다른 소비처 호환). C는 `orgs/detail.html:60`을 `{{ a.assignee_name }}`으로 바꾼다. 두 갈래는 이 키 이름만 공유한다.
`orgs/teams.html:52`는 "가입 전 구성원 추가"의 계정 표시 이름 입력칸 — 유지.

### 4.3 뷰·서비스(파이썬)

| 위치 | 변경 |
|---|---|
| `web/views/common.py:232,240,262` 이력 표시 | `history_rows`에 조직 id를 받아 `display_for` |
| `web/views/orgs.py:537` 조직 이력 actor | `display_for(actor, org)` |
| `web/views/orgs.py:209` · `ops_orgs.py:49` · `me.py:90` · `projects.py:176` · `tasks.py:131,186` · `split.py:16` · `teams.py:144,165,169` · `work_requests.py:97,128` · `assist.py:127` · `web/forms.py:113,135` | `order_by(display_name)` → `sort_by_name` |
| `web/views/orgs.py:332,350` 안내 메시지 | 조직 이름 |
| `web/views/transcribe.py:46` PC 이름 | 회의록 조직 이름 |
| `web/views/ops_users.py:109` 운영 검색 | `real_name__icontains` 추가 |
| `tasks/services.py:992,1077` 검토자 안내 · `:1723` "OO의 태스크" · `:1799` 열람 확대 경고 · `:1927,1981,2000` Discord 알림 | 태스크 조직 이름 |
| `tasks/work_requests.py:75,89,111,357` 요청 알림 | `req.org_id` |
| `tasks/split.py:28-30,87` 본문에서 사람 찾기·라벨 | 조직 표시 이름 + 계정 표시 이름 둘 다 찾기, 라벨은 조직 이름 |
| `notes/services.py:278` 화자, `:483` 이름 목록, `:809,909,957` 진행자 안내 | `note.org` |
| `notes/services.py:431-433` **전사 용어집 구성원 이름**(`:432` `order_by("display_name")`은 D 담당) | `sort_by_name` 후 조직 표시 이름. 실명 표시 조직이면 실명이 용어집으로 전사 모델(STT 서버)에 간다 → 처리방침 §10 |
| `api/routers/stt.py:171` 화자 이름 | 위 `speaker_names` 결과 그대로 |
| `assist/context.py:197` 작성자, `assist/prompts.py:113-118` "구성원 표시 이름" | 조직 표시 이름. **실명 표시 조직에서는 실명이 AI로 간다** → §10 |
| `assist/extract.py:107-110` AI 결과의 담당자 이름 매칭 | 조직 표시 이름 + 계정 표시 이름 + 아이디 셋 다 키로 |
| `github/services.py:1198`, `github/writes.py:153,159` | 1198은 GitHub 쪽 결과 문자열 → 계정 이름 유지(확정). writes.py는 웹 경고 → 조직 이름 |
| `orgs/services.py:257,277,315` 가입 전 구성원·초대 기록 | 기록 문자열은 그대로 |
| `accounts/services.py:291` 탈퇴 | `user.real_name = ""` 추가, `settings={}`라 후보도 지워짐. 구성원 행은 이미 삭제(`:282`) |
| `reports/services.py:114,137,293` | 이름 채우기·정렬을 조직 기준으로 |

### 4.4 API·MCP·Discord

- `tasks/brief.py:6` `user_brief(u, org=None)` — `org`가 오면 `display_name`에 그 조직 표시 이름. 호출처(§1)는 모두 객체의 조직을 안다: 태스크 `t.project.org_id`, 프로젝트 `p.org_id`, 요청 `r.org_id`, 첨부·문서 `org_id`, 리포트 `org`.
- 직접 만드는 곳: `api/routers/discord.py:113,128,226,239,268,278`, `docs.py:51,172`, `notes.py:35,40`, `decisions.py:62`, `tasks.py:306` → 같은 규칙. `order_by("display_name")`/`order_by("user__display_name")` 정리 담당(v3): `api/routers/discord.py:218,268,278`·`api/routers/orgs.py:77` = **B**, `notes/services.py:432` = **D**.
- (v3) `discord.py:319-327` `/members`(여러 조직에 걸친 자동완성)는 바꾸지 않는다 — 계정 표시 이름 그대로(`display_for(u)`와 같음).
- `api/routers/me.py:18` — 바꾸지 않는다(v3: `MeOut.real_name` 추가 뺌). `display_name`은 계정 표시 이름.
- 응답 키는 **`display_name` 유지, 뜻만 "이 조직에서 보이는 이름"**으로 바꾼다 → `discord_service`(`messages.py:48,135-137`, `commands.py:101,134,182,187`, `notify.py:91`, `slash.py:239`, `summarize.py:61`), `mcp_server/server.py:1207,1256`, `skills/pm` 코드 변경 없음. `api/schemas.py:16-19` `UserBrief` 문서 주석만 고친다. `discord_service/watch.py:30,215`는 Discord 회원 이름이라 무관.
- 새 403: `{"error": "real_name_required", "detail", "message", "url"}` — `profile_required`와 같은 모양(`api/api.py:85-98`). `pm.py:152`가 `profile_required`만 알므로 한 곳에 코드 하나 추가(detail 문자열을 그대로 보이기). `discord_service/commands.py:226`은 손대지 않는다(v3) — 봇 경로 `/api/integrations/`는 실명 관문 제외라 이 오류를 받지 않는다. MCP는 detail을 그대로 넘기므로(`mcp_server/tests/test_tools.py:159`) 변경 없음, 시험만 추가.

### 4.5 검색·멘션·이메일

- 검색 `web/views/search.py`에는 사람 이름 조건이 없다(grep `display_name` 0건) → 변경 없음.
- 멘션: Discord `<@id>`만 쓴다(`discord_service/messages.py:48`, `notes/services.py:908`) → 이름과 무관.
- 이메일 발송 코드 없음(`send_mail`·`EmailMessage` grep 0건).

### 4.6 회귀 방지 검사

시험 하나로 `core/web/templates` 아래 `\.display_name` 출현을 허용 목록(`base.html`, `today/_head.html`, `ops/`, `orgs/discord.html` Discord 행, `orgs/teams.html:52`)과 대조한다. 파이썬은 `order_by("display_name")`/`user__display_name` 0건을 확인.

## 5. 가입·로그인·실명 관문

### 5.1 실명 받기

- `SignupForm`(`web/forms.py:48-62`) `fields`에 `real_name` 추가, 필수. signup·_claim 둘 다 이 폼이라 한 번에 해결(`web/views/auth.py:105,149`).
- `ProfileForm`(`web/forms.py:190-193`)에 `real_name` 추가, 설정 → 프로필(`web/views/settings.py:38-43`)에서 바꾼다.
- GitHub 가입(`github/services.py:422-428`)은 손대지 않는다: 새 계정은 실명이 비어 있으니 첫 화면 이동 때 관문이 입력 화면으로 보낸다. GitHub `name`으로 미리 채우지 않는다(실명이 아닐 수 있음 — 확정).
- 가입 전 구성원(`orgs/services.py:249-277`)은 실명 없이 만들어지고, 인계(_claim) 때 받는다.

### 5.2 검증(`accounts/services.py`에 `clean_real_name` 하나)

- 앞뒤 공백 제거, 연속 공백 하나로. 1~50자(기존 조직 실명과 같은 길이 `orgs/models.py:78`).
- 글자(유니코드 문자)가 하나 이상. 숫자·`@ < > / : # \` ·제어 문자·이모지 거절(아이디·주소·멘션 흉내 방지).
- 진짜 실명인지 확인하지 않는다(본인인증 없음) — 약관에 본인 책임 문구(§10).

### 5.3 관문

- 웹: `MemberInfoGate.process_view`(`common/middleware.py:61-75`) 앞부분에 실명 검사 추가. 순서: (1) 경로로 먼저 거른다 — `/rt/`·`/static/`·`/api/`는 `request.user`를 읽지 않는다(`:63` 주석의 SSE 연결 문제 유지). (2) 로그인했고 `real_name`이 비면 열린 화면이 아니면 `profile?next=`로 `hx_redirect`.
  - 실명 관문 열린 화면: `profile`, `logout`, `login`, `privacy`, `terms`, 동의 화면(`consent`, `consents`), 비밀번호 재설정, `account`(탈퇴), OAuth 승인은 막는다(로그인한 사람이 MCP 커넥터를 붙이는 것도 서비스 이용).
- API: `api/auth.py:12` `member_info_gate`에 같은 검사(먼저) → `RealNameRequired` 예외 → 403 `real_name_required`. `/api/integrations/`(봇·웹훅·전사 서버)는 기존처럼 제외(`:18`). `/api/me`도 막지 않는다(스킬이 안내를 띄우려면 읽어야 함).
- Discord 알림 수신자에서 빼기: `blocked_user_ids`(`orgs/member_info.py:179`)는 구성원 정보용이다. 실명 미입력자는 알림에서 빼지 않는다(확정 — 알림은 계속 받고 웹에 오면 입력).
- 입력 화면: 프로필 화면 맨 위에 실명 입력 카드(관문으로 왔을 때만 경고 공지 + 충돌 후보 고르기 버튼). 새 화면을 만들지 않는다.
- (v3, 갈래 E) `next` 복귀: 지금 `web/views/settings.py:38-46` `profile`은 저장 후 `redirect("profile")`로 `next`를 읽지 않는다. 관문은 `profile?next=<원래 경로>`로 보내므로, `profile`이 GET의 `next`를 폼 hidden으로 넘기고 POST 성공 시 `_safe_next(request, next)`(`web/views/auth.py:35`)를 통과한 값으로 돌려보낸다(없거나 위험하면 지금처럼 `profile`). `_safe_next`는 auth 모듈에서 import(복사 금지).

## 6. 화면

### 6.1 조직 설정 → 구성원 정보 카드(`orgs/settings.html:30-35`)
- "실명 입력" 선택(off/optional/required) 삭제 → 체크박스 "구성원 이름을 실명으로 표시". 켜면 설명: 모든 구성원의 이 조직 표시 이름이 계정 실명으로 바뀌고 본인·관리자가 바꿀 수 없음.
- 저장: `member_info.set_definition(org, show_real_name: bool, fields, actor)`(`member_info.py:72`) 시그니처 변경, 요약 `summary()`(`:109`)도 "실명으로 표시 켬/끔". ChangeLog 그대로. 저장 후 `names.forget(org.pk)`.
- 이 옵션은 관문을 만들지 않는다(계정 실명은 이미 모두에게 필수) → `missing()`(`:115`)에서 실명 조건 삭제.

### 6.2 구성원 목록(관리자, `orgs/teams.html:16-44`)
- 이름 칸: 조직 표시 이름(큰 글씨) + 아래 `계정 표시 이름 · 아이디`(지금 `:16`의 username 자리).
- 관리자 행마다 "표시 이름 바꾸기" 인라인 폼(스킬 태그 `:37` 방식과 같은 select/input + 저장). 실명으로 표시 조직이면 폼 대신 "실명으로 표시 중" 배지.
- **(v2) 관리자 실명 열람**: 모든 조직에서 관리자는 구성원의 계정 실명을 본다(옵션·옛 모드와 무관). `:32` 조직 실명 줄을 계정 실명(`r.m.user.real_name`) 한 줄로 바꾸고, 구성원 정보 열이 없는 조직이라도 이름 칸 아래에 `실명 OOO`를 보인다. 미입력이면 "실명 미입력" 배지.
- 관리자에게 실명이 보이는 화면은 **이 구성원 목록(`org_teams` 관리자 분기, `web/views/orgs.py:199-228`) 하나**다. 일반 구성원 분기(`_member_teams`, `orgs/teams_member.html`)·다른 조직 화면·API·MCP·Discord에는 관리자에게도 실명을 따로 내지 않는다(실명으로 표시 조직은 표시 이름 자체가 실명). 운영 콘솔(`ops/user.html`, `ops/users.html`)은 운영자용으로 별도.
- 실명 열은 뷰에서 `can_admin` 확인 뒤에만 넘긴다(`web/views/orgs.py:202-203`이 이미 관리자만 이 분기로 보냄). 시험으로 일반 구성원 응답에 실명 문자열이 없음을 확인.

### 6.3 본인 편집 위치
- 조직 탭 "구성원 정보"(`orgs/_tabs.html:15`)를 항상 보이게 하고, 화면(`orgs/member_info.html`) 맨 위에 "이 조직 표시 이름" 입력(빈 값 = 계정 표시 이름 사용, placeholder로 계정 이름 보여 주기). 실명 표시 조직이면 읽기 전용 + 이유. 실명 입력칸(`:11-14`) 삭제.
- 탭 이름이 바뀔지(예: "내 정보")는 문구 필요(§10).

### 6.4 서비스

`orgs/services.py`에 `set_nickname(membership, value, actor, source="web")` (v2: 갈래 A가 만든다 — B의 Discord 엔드포인트와 E의 웹이 같이 쓴다):
- 허용: `actor == membership.user` 또는 `can_admin(actor, org)`. 그 밖은 `Forbidden`.
- 실명 표시 조직이면 `ServiceError`(웹·Discord 같은 메시지).
- 값: 공백 정리, 0~50자(빈 값 = 계정 표시 이름 사용), 실명 검증과 같은 금지 문자. 같은 조직 안 중복 허용(확정).
- ChangeLog `target_type="org"`, `field="nickname"`, 값은 `이름(user_id)`, `source`는 `web`/`dc`. `names.forget`.
- 웹 외 경로는 Discord `/표시이름`(§6.5)만. 일반 API·MCP 엔드포인트는 만들지 않는다.

### 6.5 (v2) Discord `/표시이름` — 본인 조직 표시 이름

- 명령: `/표시이름 [이름]` — 길드 전용(`app_commands.guild_only`), 응답은 본인에게만(ephemeral). 이름을 비우면 조직 표시 이름을 지워 계정 표시 이름으로 돌아간다. 대상 조직 = 그 길드에 연결된 조직(`orgs/discord.py:176` `org_by_guild`, `/알림채널`의 `:249-257`과 같은 방식).
- core: `POST /api/integrations/discord/orgs/nickname` `{discord_user_id, guild_id, nickname}` → `_actor()`(`api/routers/discord.py:89-95`, 미연결 404·동의 정지 403) → `org_by_guild` → 실행자의 구성원 행 → `set_nickname(m, nickname, actor, source="dc")`. 응답 `{org_id, org_name, display_name}`(바뀐 뒤 그 조직 표시 이름). 오류: 길드 미연결·구성원 아님·실명으로 표시 조직 → 400 `ServiceError` 문구. 스키마 `DiscordNicknameIn`(`api/schemas.py:387-395` 옆).
- (v3) 봇 캐시: 자동완성 캐시(`discord_service/slash.py:59` `CACHE_TTL = 30`, `:69-92`)는 무효화하지 않는다 — `/members`는 계정 이름이라(§4.4) 표시 이름 변경과 무관하고, 조직별 이름은 알림 때마다 core에서 새로 읽는다. 성공 응답에 "잠시 뒤 반영될 수 있습니다" 문구(Sol, §10)만 붙인다.
- 실행자 권한 확인(메모 "Discord 관리 = 실행자 권한 확인"): 그 규칙은 **다른 사람·조직 설정을 바꾸는 관리 동작**용(예: `/알림채널`은 `channels.py:163` `can_manage_channels` + core 관리자 확인). `/표시이름`은 **실행자 본인의 조직 행만** 바꾸므로 관리 동작이 아니다 → Discord 서버 권한은 보지 않는다. 대신 본인 확인은 `discord_user_id`(봇이 게이트웨이에서 읽은 실행자 id, 위조 불가)로 하고, 엔드포인트에 대상 사용자 인자를 **두지 않아** 남의 것을 바꿀 길을 구조로 막는다.
- 관리자가 남의 표시 이름을 바꾸는 것은 **웹만**(§6.2). Discord에 열면 Discord 권한 + 유달리 관리자 이중 확인과 대상 고르기가 필요해 요구 대비 비용이 크다.
- 실명 관문: `/api/integrations/`는 관문 제외(§5.3)라 실명 미입력자도 명령은 된다(봇 경로 일관성). 실명으로 표시 조직이면 서비스가 거절하므로 실명이 우회되지 않는다.
- 봇 쪽 파일: `discord_service/slash.py`(명령 등록, `/알림채널` `:580-` 형식), `discord_service/commands.py`(`nickname_reply`, 오류 문구는 `_error_reply` `:220` 재사용), `discord_service/core_client.py`(호출 한 개), `discord_service/messages.py`(`SLASH_HELP`에 한 줄). 새 명령은 `command_sync.py`가 동기화한다 — 배포 후 명령 목록 반영 확인.

## 7. API·MCP·스킬 하위 호환

- 응답 키 추가·삭제·이름 변경 없음(v3: `MeOut.real_name` 뺌). 리포트 행의 `assignee_name`만 새 키(§4.2).
- `display_name` 값이 조직마다 달라질 수 있다 — 같은 사람이 다른 조직 태스크에서 다른 이름. 담당자 지정은 계속 `id`로 한다(`mcp_server/server.py:1207` 설명에 "이름은 조직마다 다를 수 있으니 id로 지정" 한 줄).
- `skills/pm/SKILL.md`·`docs/GUIDE-V2-06-api-docs.md`에 `display_name` 뜻과 `real_name_required` 한 줄씩.

## 8. 사용자 노출 용어표(초안 — 최종 문구는 Sol)

| 표준 용어 | 뜻 | 금지어(쓰지 않음) |
|---|---|---|
| 실명 | 계정에 하나 있는 본인의 실제 이름 | 본명, 이름(실명 뜻으로), 조직 실명 |
| 표시 이름 | 계정 기본 이름(조직 표시 이름이 없을 때 쓰임) | 계정 이름, 프로필 이름 |
| 조직 표시 이름 | 한 조직 안에서만 쓰는 이름 | 닉네임, 별명, 서버 별명, 조직 닉네임 |
| 실명으로 표시 | 조직 옵션: 조직 표시 이름을 실명으로 고정 | 실명 필수, 실명 입력, 실명 받지 않음/선택/필수 |
| 구성원 정보 | 조직이 정한 추가 항목(실명 제외) | — |

금지어 grep 대상: 템플릿, `core/**/*.py` 메시지, `discord_service`, `mcp_server`, `skills`, 약관·처리방침.

## 9. 갈래 분할(worktree 병렬, 파일 겹침 없음)

선행: **A가 먼저 끝나 병합**되어야 B~E가 헬퍼·필드를 쓴다. A는 작다(반나절).

| 갈래 | 파일(독점) | 내용 |
|---|---|---|
| A 모델·헬퍼·마이그레이션 | `accounts/models.py`, `orgs/models.py`, `accounts/migrations/0010*`, `orgs/migrations/0013*,0014*`, `orgs/names.py`(새), `web/templatetags/names.py`(새), `common/middleware.py`, `config/settings.py`, `accounts/services.py`(clean_real_name·탈퇴), `orgs/services.py`(v2: `set_nickname`만), `orgs/member_info.py`(v3: definition 호환·실명 조건 삭제), **`core/conftest.py:41,55,63`(v3: 고정 사용자에 `real_name` 채움 — 관문을 넣는 순간 기존 웹 시험이 프로필로 튕긴다)**, **`core/orgs/test_member_profile.py:45,79`(v3: 실명 모드 기대값 정리)** | §2·§3·§5.2·§5.3 관문·§6.1 서비스 부분·§6.4 서비스 + Postgres 리허설 |
| B API·Discord·MCP·스킬 | `tasks/brief.py`, `api/serialize.py`, `api/routers/*.py`, `api/schemas.py`, `api/api.py`, `api/auth.py`, `reports/services.py`, `discord_service/{slash,commands,core_client,messages}.py`(v2), `skills/pm/scripts/pm.py`, `skills/pm/SKILL.md`, `mcp_server/server.py`(설명 한 줄) | §4.4·§7·§6.5 `/표시이름`(core 엔드포인트 + 봇 명령) |
| C 웹 템플릿·뷰(조직 화면 이름) | §4.2 표의 템플릿 전부, `web/views/{common,me,projects,tasks,split,teams,work_requests,assist,transcribe,ops_orgs,ops_users}.py`, `web/forms.py`의 `:113,135`, `ops/*.html` | §4.2·§4.3 웹 부분, 회귀 검사 시험 |
| D 서비스 문자열·AI·전사 | `tasks/services.py`, `tasks/work_requests.py`, `tasks/split.py`, `notes/services.py`, `assist/context.py`, `assist/prompts.py`, `assist/extract.py`, `github/writes.py` | §4.3 서비스 부분 |
| E 가입·설정·조직 화면 | `web/forms.py`의 Signup·Profile, `web/views/{auth,settings}.py`, `settings/profile.html`, `auth/signup.html`, `web/views/orgs.py`, `web/urls.py`, `orgs/settings.html`, `orgs/member_info.html`, `orgs/_tabs.html`, `orgs/teams.html` | §5.1·§5.3 프로필 `next` 복귀·§6 화면 |

겹침 처리: `web/forms.py`는 C(`:113,135` 정렬)와 E(폼 필드)가 함께 건드림 → C의 두 줄을 E가 맡는다. `orgs/teams.html`은 E만(C 표에서 제외하고 E가 `|name_in` 교체도 한다). `web/views/orgs.py`도 E만(`:209,332,350,537` 포함).
문구(약관·처리방침·화면 글)는 Sol 별도 갈래 F — `core/web/content/*`, `accounts/consents.py` 판 올림.

## 10. 개인정보·약관(문구 필요 목록 — Sol)

계정 실명은 조직이 정하던 "구성원 정보"가 아니라 **서비스가 직접 받는 가입 필수 항목**이 된다. 처리 주체·목적·제공 범위가 바뀌므로 약관 v4·처리방침 v5로 판을 올린다(확정). 재동의는 기존 방식 그대로 — 로그인할 때 시행 판 동의를 기록한다(`TermsAgreement`, `accounts/migrations/0009_termsagreement.py`). 별도 동의 화면을 새로 만들지 않는다.

1. 처리방침 요약표 처리 항목 `privacy.md:18`: "실명" 추가, 조직별 구성원 정보에서 실명 삭제(`:20`, `:54`).
2. 처리방침 제2조 가입 필수 행 `privacy.md:52`: 실명 + 목적(조직 안 본인 식별, 실명으로 표시하는 조직에서 이름 표시).
3. **(v2) 조직 관리자에게 실명 제공**: 이용자가 속한 모든 조직의 관리자가 구성원 목록에서 계정 실명을 열람한다(옵션과 무관). 제3자 제공·열람 범위 문장(`privacy.md:20,137`)과 약관 제6조(`terms.html:42-44`)에 반영. 조직 가입 = 그 조직 관리자에게 실명이 보인다는 사실을 가입·초대 수락 화면 안내 문구에도 한 줄.
3-1. 공개 범위: 실명은 본인·운영자·소속 조직 관리자에게 보이고, "실명으로 표시" 조직에서는 그 조직 구성원 전원과 그 조직의 AI·MCP·Discord·전사 용어집 출력에 표시 이름으로 나간다(`privacy.md:91,145` 문장 보완).
4. 보유 기간 `privacy.md:100`: 탈퇴 시 삭제.
5. 조직 표시 이름: 업무 기능 이용 항목(`privacy.md:55`)에 추가.
6. 약관 정의 `terms.html:22` "구성원 정보"에서 실명 삭제, "실명"·"조직 표시 이름" 정의 추가. 제6조 `terms.html:43` 첫 문장(실명 필수·선택·받지 않음) → "실명으로 표시" 옵션 설명. 실명은 본인이 정확히 입력할 책임 문구.
7. 판 올림: `accounts/consents.py:14` terms v4·privacy v5, 시행일.
8. 화면 글: 가입 실명 칸 도움말, 실명 관문 공지, 충돌 후보 안내, 구성원 정보 카드 옵션 설명, 조직 표시 이름 칸 도움말·읽기 전용 이유, 구성원 표 배지·"실명 미입력" 배지, API 403 `real_name_required` 메시지, Discord 봇 안내, 탭 이름, (v2) `/표시이름` 명령 설명·성공·거절(실명으로 표시 조직·길드 미연결·구성원 아님) 문구와 `SLASH_HELP` 한 줄, 초대 수락 화면의 "관리자에게 실명이 보입니다" 안내.

## 11. 시험 계획

`uv run pytest`(core 안). 새 시험 파일은 갈래별:
- A `orgs/test_names.py`: 규칙 표(실명 표시 켬/끔 × 실명 유무 × 별명 유무 × 구성원 아님 × 탈퇴자), 캐시 무효화(`forget`), 쿼리 수(`django_assert_num_queries`: 구성원 30명 표 1쿼리). `orgs/test_migration_0014.py`(migrator 픽스처 또는 `MigrationExecutor`): 한 가지 실명 이전, 충돌 시 빈 값+후보, 정의 변환, backward 복원.
- A 관문: 실명 빈 사용자 → 조직 화면·오늘·설정 외 화면이 프로필로, 열린 화면 통과, `/rt/`에서 `request.user` 안 읽음(기존 시험 패턴), API 403 `real_name_required`, `/api/integrations/`·`/api/me` 통과. `display_for(u)`(org 없음) = 계정 표시 이름.
- A(v3) GitHub 가입 claim 경로: `github/services.py:418-420`(`claim_invite`로 가입 전 계정을 넘겨받음 — 실명 없음)로 로그인한 직후 조직 화면 요청이 프로필로 가는지. 새 GitHub 가입(`:422-428`)도 같은 확인.
- E(v3): 관문 → `profile?next=/orgs/1` → 실명 저장 → `/orgs/1`로 복귀, 외부 주소 `next`는 무시하고 `profile`로.
- B: `user_brief` 조직 이름, Discord 라우터 이름(`/members`는 계정 이름 그대로), 리포트 `assignee_name` 키, `pm.py`의 `real_name_required` 메시지, MCP 통과 시험(`mcp_server/tests/test_tools.py:159` 방식). (v2) `/표시이름` 엔드포인트: 본인 변경·빈 값 되돌리기·실명으로 표시 조직 거절·길드 미연결·구성원 아님·미연결 404·ChangeLog `source="dc"`; 요청 본문에 대상 사용자 인자가 없음을 확인. 봇: `discord_service/tests/test_slash.py`·`test_commands.py`에 명령 등록·응답 문구.
- C: §4.6 회귀 검사, 태스크 패널·구성원 표·회의록 목록 렌더에 조직 이름, 여러 조직 오늘 화면에서 행마다 다른 이름.
- D: 용어집·AI 맥락에 조직 이름, 실명 표시 조직이면 실명, extract가 별명·계정 이름 둘 다 매칭.
- E: 가입·인계에 실명 필수·검증, 프로필 실명 변경 → 실명 표시 조직 이름 즉시 변경, 설정 카드 저장 ChangeLog, (v2) 관리자 구성원 목록에 실명 보임(옛 off·optional 조직 포함)·일반 구성원 화면 응답에는 실명 문자열 없음.
- A(v2): `set_nickname` 권한(본인·관리자 허용, 다른 구성원 거절, 실명 표시 조직 거절).
- 기존 시험 수정(v3: **A 갈래 담당**, 관문과 같은 커밋): `orgs/test_member_profile.py:45,79`(실명 모드), `conftest.py:41,55,63` 사용자에 `real_name` 채우기(안 채우면 관문이 기존 웹 시험을 다 깬다). A 병합 시점에 core 전체 시험이 통과해야 B~E가 출발한다.
- 전체: `uv run pytest` core·`discord_service`·`mcp_server`·`skills/test_pm.py`.

## 12. 배포 순서

1. A 병합 → B·C·D·E·F 병렬 → 통합 브랜치에서 전체 시험.
2. 검토: 코드 Sol + Fable/Opus 독립, 화면 Astra + Claude(모바일 포함) — 메모 "검토는 GPT·Claude 둘 다".
3. §2.4 Postgres 리허설(운영 덤프, 앞으로·되돌리기·앞으로).
4. 배포 직전 DB 백업, 코드 사본 보관(기존 절차 `docs/OPERATIONS-DEPLOYMENT.md`).
5. 배포(마이그레이션 0010·0013·0014) → 실명 미입력 사용자 수·충돌 수 확인.
6. 약관·처리방침 v4/v5 시행일과 같은 배포에 묶는다(실명 수집 시작 전에 고지).
7. 한 판 뒤 0015(옛 열·키 삭제) — 되돌릴 필요가 없음을 확인한 다음.

되돌리기: 코드 이전 판 + `migrate orgs 0012` + `migrate accounts 0009`. 조직 실명 원본(`OrgMembership.real_name`)은 이번 판에서 지우지 않으므로 손실 없음. 되돌린 뒤 새로 입력된 계정 실명은 사라진다(감수).

## 13. 결정(v2, 사용자 확정 — v1 미결정 전부 닫음)

| # | 항목 | 결정 |
|---|---|---|
| 1 | GitHub로 나가는 글의 이름 | 계정 표시 이름 유지 |
| 2 | 옛 "선택"·"받지 않음" 조직 | 표시는 "실명으로 표시 끔". 단 관리자 실명 열람은 모든 조직에서 가능(§6.2) |
| 3 | 조직 표시 이름 중복 | 허용 |
| 4 | 실명 미입력자 Discord 알림 | 빼지 않음 |
| 5 | 실명 변경 제한·기록 | 없음(값 이력 안 남김) |
| 6 | GitHub `name`으로 실명 미리 채우기 | 하지 않음 |
| 7 | 표시 이름 변경 경로 | 웹(본인·관리자) + Discord `/표시이름`(본인만). 일반 API·MCP는 만들지 않음 |
| 8 | 실명 검증 | 숫자·특수 기호 거절, 한 글자 허용(§5.2) |
| 9 | 실명 충돌 이전 | 비워 두고 본인이 후보에서 고름(§2.3) |
| 10 | 약관·처리방침 | 약관 v4·처리방침 v5. 재동의는 기존 "로그인 = 시행 판 동의" 방식 |

남은 미결정: 없음. 화면 글은 Sol(§10).

## 14. 확인 불가

- 운영 DB의 조직별 실명 입력 현황(충돌 사용자 수): 운영 데이터는 API로만 본다는 규칙상 리허설 덤프에서 확인.
- 실명 수집·관리자 제공의 법적 근거(판 올림과 로그인 동의 방식으로 충분한지는 법률 검토 영역).
- `discord_service/core_client.py`의 정확한 메서드 이름 규칙 — B 갈래가 기존 `set_org_channel` 계열 호출을 보고 맞춘다.
