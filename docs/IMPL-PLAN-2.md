# 구현 계획 v2 — 조직·팀 재구성과 GitHub 통합 (NewMock 라운드)

작성일: 2026-09-11
기준: `NewMock/README.md`(핸드오프), `NewMock/유달리 신규 기능 목업.dc.html`, 현재 코드(커밋 `3b2fbee`, core 테스트 145개), 2026-09-11 대화에서 확정한 결정
선행 문서: [IMPL-PLAN.md](IMPL-PLAN.md)(09-10 정합 결정, 1~3단계 완료), [GUIDE-00](GUIDE-00-rules.md)

---

## 1. 결론

NewMock은 개발업무 통합 기능 묶음이지만, 대화에서 확정된 두 결정 때문에 **이번 라운드의 본체는 도메인 한 층 추가**가 되었다.

1. **계층이 바뀐다.** `조직 → 팀 → 멤버`. 멤버는 여러 팀에 속한다. 지금의 `Team`이 조직 자리로 올라가고, 팀은 그 안의 사람 묶음으로 새로 생긴다. 팀은 가시성을 제한하지 않고, GitHub 조직의 Team과 짝이 될 수 있다(연결하지 않는 팀도 많다).
2. **GitHub는 App으로 붙인다.** 조직 관리자가 PM 화면에서 앱을 설치하고, 각 사용자는 자기 GitHub 계정을 연결한다. PM은 저장소를 읽고, 자주 쓰는 관리 작업(조직 초대·팀·팀 멤버·이슈·브랜치)만 쓴다. 저장소 권한 부여와 PR 병합은 GitHub에 남긴다.

이 둘이 정해지면서 앞선 초안의 PAT·폴링·`github_service` 별도 파트는 전부 폐기되었다(§4).

목업의 화면 6개(부하 현황·로드맵·회의록·연동 키·저장소 연결·API 문서)와 IA 정리는 그대로 들어온다. 다만 목업이 "팀"이라 부른 화면들은 전부 **조직** 화면이 되고, "연동 키" 탭은 **GitHub** 탭으로 대체된다.

---

## 2. NewMock 번들 확인 결과

| 파일 | 상태 | 처리 |
|---|---|---|
| `README.md` | **신규** 핸드오프. 이 계획의 1차 근거 | 저장소 루트 README의 디자인 핸드오프 절 뒤에 "2026-09-11 개발업무 통합" 절로 붙인다 |
| `유달리 신규 기능 목업.dc.html` | **신규**. 신규 6화면 + IA 정리된 기존 화면 | 저장소 루트로 복사 **완료**(2026-09-11). `.claude/launch.json`의 `mockup` 서버로 나란히 비교 |
| `유달리 업무 목업 v2.dc.html`, `TaskRow2.dc.html` | 저장소 사본보다 **오래된 판**이다. NewMock 판에는 09-10에 지운 `--brand-grad` 헤더·진행률 바·그림자가 남아 있고 반응형 CSS와 `.task-row2` 클래스가 없다 | **무시.** 저장소 사본을 유지한다. README도 "이전 라운드 참고용"이라 적었다 |
| `support.js` | 공백 차이뿐 | 무시 |

목업의 `class Component` 상태(`tasksByProject`, `gitLinks`, `notes`, `keys`, `spec`)는 전부 서버 상태다. 09-10 라운드와 같은 원칙으로 뷰가 context를 만들고 템플릿이 그린다. React·빌드 도구 금지는 그대로다.

---

## 3. v1 정의

**v1 = 이 라운드를 끝내고 팀이 실제 업무를 PM에서 시작하는 상태.** PLAN의 4단계(배포·2주 시범)에 투입할 수 있으면 v1이다.

한 줄 기준: **PM에서 GitHub를 읽고, 태스크 흐름이 자동으로 따라가고, 사람마다 볼 수 있는 것만 보이고, 자주 하는 관리 작업이 PM 안에서 끝난다.**

### v1에 들어가는 것

| 단계 | 내용 |
|---|---|
| 1. 조직·팀 재구성 | 조직 → 팀 → 멤버, 프로젝트는 조직 소속 + 담당 팀 여럿. 개명과 마이그레이션 초기화, Discord·MCP·API 용어 갱신 |
| 2. 셸·IA·집계 | 헤더 5영역, 조직 하위 탭 6개, 프로젝트 하위 탭 3개, 레일 조건부 표시와 접기, 집계를 한 함수로 |
| 3. 기존 화면 보강 | 칸반 드래그, 일정 캘린더 월 이동과 시간표 삭제, 타일 교체 |
| 4. 부하 현황·로드맵 | 스킬 태그, 팀별 필터, 마일스톤, 프로젝트 의존성 |
| 5. 회의록 | 목록·인라인 편집기·마크다운 업로드·태스크 참조 |
| 6. API 문서 | 스펙 업로드와 주소 가져오기, 태그별 렌더, 검색 |
| 7. GitHub 읽기 | 앱 설치, 사용자 계정 연결, 권한 필터, 웹훅 수신, 자동 전환 5규칙, 저장소 연결 탭, 패널 생애주기 블록 |
| 8. GitHub 쓰기·관리 | 조직 초대·팀 CRUD·팀 멤버 동기화, 이슈 만들기·닫기, 브랜치 만들기, 조직 GitHub 탭 |

완료 조건은 기존 기준 그대로다. 테스트 전부 통과(SQLite·Postgres), `ruff` 오류 0, 목업과 나란히 화면 대조, 검수 시나리오 통과, 실제 저장소에서 브랜치부터 머지까지 한 사이클이 태스크를 끝까지 옮기는 것.

### v1에서 빠지는 것

| 빠지는 것 | 왜, 언제 |
|---|---|
| **팀에 저장소 권한 부여** | 저장소 Administration 쓰기가 필요하다(§4.3). 읽기 전용 표 + GitHub 딥링크로 대체 |
| PR 병합, PM에서 커밋 | 리뷰·CI 맥락이 GitHub에 있다 |
| 저장소 생성·삭제, 브랜치 보호, 시크릿·Actions 설정 | 드물거나 되돌리기 어렵다 |
| 개인에게 저장소 권한 직접 부여 | 권한은 팀에 붙는다. 예외는 GitHub에서 |
| 배포 키 | git SSH 전용이라 이슈·PR·웹훅 어디에도 못 쓴다 |
| 회의록 버전 이력·이미지 첨부 | 열린 질문에서 제외 |
| 마일스톤에 태스크 연결, 로드맵 기간 전환 | 진행률은 프로젝트 통계로 충분 |
| PR 리뷰 승인 수 | PR마다 요청이 하나 더 붙는다 |
| 부하 계산의 중요도 가중치 | 계산이 한 줄이라 언제든 |
| 조직 초대 시 팀 자동 배정 | 초대 후 팀 화면에서 넣는다 |

---

## 4. 확정된 설계 결정

### 4.1 계층: 조직 → 팀 → 멤버

- **조직**이 가시성 경계다. 지금 `Team`이 하던 역할 전부(초대, 관리자 역할, 프로젝트 소유, 태스크 범위)를 그대로 물려받는다.
- **팀**은 사람 묶음이다. 가시성을 **제한하지 않는다.** 조직 멤버는 조직의 프로젝트를 다 본다. 팀은 부하 현황 필터, 프로젝트 담당 표시, GitHub 팀 연결에 쓰인다.
- **멤버는 여러 팀에 속한다.** 백엔드이면서 QA일 수 있다.
- **프로젝트는 조직 소속이고 담당 팀을 여럿 가진다**(0개도 가능).
- 팀이 가시성을 자르지 않는 이유: 자르면 태스크 가시성의 출처가 조직·팀·GitHub 셋이 되고, 목업의 "조직 전체 부하 현황"과 "담당자별 표"가 사람마다 다르게 보인다. GitHub 데이터만 GitHub 권한으로 자른다(§4.5).

**운영 데이터가 아직 없으므로 마이그레이션을 처음부터 다시 쓴다.** 개명이 core 거의 모든 파일에 걸치고, 배포 뒤에 하면 데이터 이전이 붙는다. dev DB는 폐기한다.

### 4.2 GitHub App (PAT·폴링·별도 파트 폐기)

| 항목 | 내용 |
|---|---|
| 왜 App인가 | 조직마다 웹에서 연결해야 하고(PAT 붙여넣기 대신 설치 버튼), 조직 전체 저장소를 읽어야 하고, 사용자 토큰을 보관해야 한다. 셋 다 App이 정확히 해 주는 일이다 |
| 비밀 | PM 운영자의 앱 개인키 하나(`.env`). 조직마다 저장하는 비밀은 없다(설치 id만) |
| 토큰 | 설치 토큰은 1시간. 필요할 때 개인키로 서명해 발급하고 캐시한다. 만료·교체 문제가 없다 |
| 이벤트 | 앱 등록 때 웹훅 주소를 한 번 적으면 모든 설치에서 온다. 저장소마다 수동 등록하던 문제가 사라져 **폴링 대신 웹훅**이 기본이 된다 |
| 수신 주소 | 기존 호스트 아래 경로 하나. `POST https://pm.<도메인>/api/integrations/github/webhook`. 새 공개 호스트 없음 |
| 별도 파트 | **없다.** 폴링 루프가 없어져 `github_service`도 워커 컨테이너도 필요 없다. 웹훅 수신·토큰 발급·권한 확인이 전부 요청 시점에 core 안에서 끝난다. 자격증명이 core DB에 있기로 한 이상 밖으로 뺄 이유가 없다 |
| 새 의존성 | `cryptography` 하나(사용자 토큰 Fernet 암호화 + 앱 JWT의 RS256 서명) |

### 4.3 앱 권한 (최종)

| 종류 | 권한 | 쓰는 곳 |
|---|---|---|
| 저장소 | Contents 읽기·쓰기 | 브랜치 목록·기본 브랜치 sha 읽기, **브랜치 만들기** |
| 저장소 | Issues 읽기·쓰기 | 이슈 목록·상태, 이슈 만들기·닫기 |
| 저장소 | Pull requests 읽기 | PR 정보 |
| 저장소 | Metadata 읽기 | 필수 |
| 조직 | Members 읽기·쓰기 | 조직 초대·제거, 팀 CRUD, 팀 멤버 추가·제거 |
| 이벤트 | push · create · pull_request · issues · membership · team · installation · installation_repositories | |

**저장소 Administration은 받지 않는다.** 이 권한은 저장소 삭제, 설정 변경(공개·비공개 전환 포함), 브랜치 보호 규칙, 배포 키, 개인 협업자, 저장소 웹훅을 전부 포함한다. 팀에 저장소 권한을 주는 API가 이걸 요구한다는 것을 문서로 확인했다. 팀과 저장소를 잇는 일은 저장소를 만들 때 한 번뿐인데, 그것 때문에 조직의 모든 저장소를 지울 수 있는 권한을 설치 토큰에 쥐여 주게 된다. 대신 **읽기 전용 표 + GitHub 딥링크**로 대체한다(§6.4).

Contents 쓰기는 받는다. 브랜치 만들기가 목업의 "브랜치 이름 규칙을 강제하지 않는다"를 실제로 해결하고(PM이 만들면 이름에 태스크 번호가 자동으로 들어간다), 브랜치 보호 규칙은 여전히 GitHub가 강제하며, 파괴적 작업은 불가능하기 때문이다.

### 4.4 토큰 두 종류와 쓰기 원칙

- **설치 토큰**(서버 단독): 읽기에만 쓴다. 웹훅 처리 중 이슈·PR 보강, 이슈 목록 동기화. 코드 규칙으로 고정하고 테스트로 지킨다.
- **사용자 토큰**(그 사람 것): **모든 쓰기는 이것으로 나간다.** GitHub 쪽 기록이 그 사람 이름으로 남고, 그 사람이 GitHub에서 못 하는 일은 GitHub가 거부한다. PM이 권한 규칙을 따로 구현하지 않고 거부 사유를 그대로 보여 준다.
- PM 쪽에서 한 겹 더: 관리 버튼은 조직 관리자에게만 보인다.
- GitHub에 반영할 수 없는 경우(상대가 GitHub 미연결, 팀이 GitHub 미연결)는 PM 안에서만 처리하고 "GitHub 연결 후 반영"으로 표시했다가 연결 시점에 맞춘다.
- 되돌리기 어려운 것(조직에서 제거, 팀 삭제)은 확인 대화상자를 거친다.

### 4.5 사용자 신원과 저장소 접근 권한

- 사용자는 프로필에서 GitHub를 연결한다. PM은 GitHub id·로그인과 **토큰·갱신 토큰을 암호화해 저장**한다. 토큰을 버리지 않는 이유는 사용자가 없을 때도 권한 변화를 확인해야 하기 때문이다.
- 연결 직후와 **PM 로그인 때마다**(마지막 확인이 오래됐으면) `GET /user/installations/{id}/repositories`로 "앱이 설치된 저장소 ∩ 이 사람이 볼 수 있는 저장소"를 받아 저장한다. GitHub에서 권한이 바뀌면 다음 로그인에 자동 반영된다.
- **태스크 데이터는 조직 규칙으로, GitHub에서 온 데이터는 GitHub 권한으로 보인다.** 한 화면에 두 규칙이 겹친다.

| 화면 | 접근 권한 없음 또는 GitHub 미연결일 때 |
|---|---|
| 패널 GitHub 블록 | "저장소 접근 권한 없음" 또는 "GitHub를 연결하면 보입니다" 한 줄. 브랜치·PR·커밋·체크리스트 sha 숨김 |
| 프로젝트 저장소 탭 | "연결됨(접근 권한 없음)"만. 저장소 이름·이슈 목록·이벤트 표 숨김 |
| 저장소 연결하기 | 그 저장소에 권한 있는 사람만 |
| API·MCP | v1에서는 git 필드를 노출하지 않는다(같은 필터를 두 번 만들지 않는다) |

`github/services.py`의 `can_view_repo(user, full_name)` 한 곳을 패널·탭·연결 폼이 전부 지난다.

### 4.6 이력의 행위자

- 웹훅의 `sender.id`를 GitHub id로 매핑해 **실제 사람**을 행위자로 남긴다. "박서연 · GitHub · 검토 대기 → 완료".
- 매핑되지 않으면 `ChangeLog.actor`를 비우고 `external_actor`에 GitHub 로그인을 넣는다. 화면에는 "@minwoo-choi (GitHub)". 그 사람이 나중에 연결하면 GitHub id로 과거 이력의 행위자를 채운다.
- `ChangeLog.SOURCES`에 `("gh", "GitHub")` 추가(`max_length=4` 안에 든다).

### 4.7 이슈 닫기는 GitHub에 맡긴다

PR 본문에 `Closes #84`가 있으면 머지 시 GitHub가 이슈를 닫고 주체도 정확하다. PM의 [PR 열기]는 GitHub PR 작성 화면을 열면서 제목과 본문(연결된 이슈가 있으면 `Closes #n`)을 미리 채운다. PM에서 손으로 완료했는데 이슈가 열려 있는 경우에만 패널에 [이슈 #84 닫기] 버튼이 뜬다(그 사람 토큰으로).

### 4.8 09-10 라운드에서 이어지는 결정 (유지)

| 항목 | 결정 |
|---|---|
| 회의록 렌더링 | 서버 `markdown`+`bleach` 대신 **클라이언트 단일 렌더러**. 편집기가 어차피 줄 단위로 그려야 하고, `createElement`/`textContent`만 쓰면 XSS가 원천적으로 없다. 의존성 2개를 0개로 |
| API 스펙 수신 | 브라우저 fetch 경로 없이 **서버 프록시 + 파일 업로드**만. 로컬 주소는 파일로, CI는 API `PUT`으로 |
| 보드 열 | 미완료 5 + **완료 상시** + 취소(포함 시). 완료 열이 없으면 드래그로 완료를 못 한다 |
| 일시정지 드롭 | 막힘만 사유 패널을 거친다. 일시정지 사유는 선택이라는 09-10 결정을 드래그가 바꾸지 않는다 |
| 집계 | `project_stats`·`today_view`를 옮기지 않는다. 어긋날 위험이 있는 조직 개요·부하 현황·담당자별만 `org_status()` 한 호출에서 나오게 한다 |

### 4.9 폐기된 초안

PAT 기반 viewer, 60초 폴링 루프, `github_service` 4번째 파트, `.env.github`, `gh.<도메인>` 공개 호스트, `OrgCredential` 암호화 저장과 연동 키 등록 폼, 배포 키. 전부 App 설치로 대체되거나 §3에서 제외되었다.

---

## 5. 데이터 모델

### 5.1 개명과 재구성 (마이그레이션 0001부터 다시)

```
Organization                      # 기존 Team
  name 100 · purpose 200 · created_by · created_at
  members M2M(User, through=OrgMembership)

OrgMembership                     # 기존 Membership
  org FK · user FK · role admin|member · tags JSON(list, 스킬 태그) · joined_at
  unique(org, user)

Invite                            # team → org
  org FK · token · created_by · expires_at · revoked_at · use_count

Team                              # 신규. 사람 묶음. 가시성 제한 없음
  org FK · name 100 · purpose 200 blank · created_by · created_at
  unique(org, name)
  members M2M(User, through=TeamMembership)

TeamMembership                    # 신규
  team FK · user FK · joined_at
  unique(team, user).  user는 그 팀의 org 멤버여야 한다(services 검사)

Project
  org FK(기존 team) · teams M2M(Team, blank, 담당 팀) · 나머지 동일
  unique(org, name)

ChangeLog
  actor FK **nullable** · external_actor 100 blank(GitHub 로그인)
  SOURCES += ("gh", "GitHub")

Link
  KINDS += ("issue", "이슈"), ("dash", "대시보드")   # max_length=5 안
```

`Task`는 바뀌지 않는다. `TodayItem`·`ChecklistItem`도 그대로다.

### 5.2 `projects` 앱 추가

```
Milestone
  project FK(CASCADE) · name 100 · start_date null · target_date · status planned|active|done
  created_by · created_at         ordering: target_date, id
  # 진행률은 project_stats(project). 태스크-마일스톤 연결은 후속

ProjectDependency
  from_project FK · to_project FK · note 200 blank · is_blocking bool
  created_by · created_at
  unique(from, to), Check(from ≠ to). 같은 조직인지는 services에서

ApiSpec
  project OneToOne · source_url 500 blank · spec JSON · fetched_at · uploaded_by
```

### 5.3 `notes` 앱 (신규)

```
MeetingNote
  org FK · project FK null(같은 조직, services 검사) · title 200 · body_md Text
  created_on Date(default=today_kst, 수정 가능) · version PositiveInteger(1)
  created_by · created_at auto · updated_at auto
  tasks M2M(tasks.Task, blank, related_name="notes")
  ordering: -created_on, -id
```

`version`은 제목·프로젝트·생성일·본문 저장마다 +1. 자동 저장이 `version`을 보내고 다르면 409(태스크·프로젝트와 같은 `_apply` 패턴).

### 5.4 `github` 앱 (신규)

```
GitHubInstallation
  org OneToOne · installation_id BigInt unique · account_login 100 · account_type
  repo_selection all|selected · installed_by · installed_at · suspended_at null

GitHubIdentity
  user OneToOne · github_id BigInt unique · login 100
  token_enc · refresh_enc · token_expires_at · refresh_expires_at   # Fernet
  repos JSON(list "owner/repo") · repos_checked_at · connected_at

GitHubTeamLink
  team OneToOne · github_team_id BigInt · slug 100 · synced_at

RepoConnection
  project OneToOne · url 300(입력 원문) · full_name 200("owner/repo")
  import_label 50(default "task") · assignee_default issue|none · auto_import bool(False)
  rule_issue · rule_branch · rule_commit · rule_pr · rule_merge  bool(True)
  last_event_at null · created_by · created_at

RepoIssue
  connection FK · number int · title 300 · state open|closed · assignee_login 100 blank
  labels JSON · task FK null · updated_at
  unique(connection, number)

TaskGitLink                       # 4단계 모두 선택적. 없는 단계는 빈 값
  task OneToOne · connection FK
  issue_number null · issue_title 300 · issue_state ''|open|closed
  branch 200 blank
  pr_number null · pr_title 300 · pr_state ''|open|merged|closed · merged_at null
  commits JSON [{sha, message, item, at}]

GitEvent
  connection FK · delivery_id 64 unique · occurred_at
  kind push|branch|pr_opened|pr_merged|pr_closed|issue_opened|issue_closed|membership|team
  actor_login 100 · actor_user FK null · summary 200 · task FK null · result 100
  저장 시 연결당 50건 초과분 삭제
  # ponytail: 표 하나에 잘라 둠. 감사 로그가 필요해지면 보관 정책으로
```

`GitHubIdentity`·`GitHubTeamLink`·`GitHubInstallation`을 `github` 앱에 두어 `accounts`·`teams`가 GitHub를 모르게 한다.

---

## 6. 화면

### 6.1 셸

| 항목 | 내용 |
|---|---|
| 헤더 5영역 | 오늘 · 내 태스크 · **프로젝트** · **조직** · 검색 + 빠른 추가 + 아바타 |
| `/projects` | 세션의 마지막 프로젝트 → 없으면 현재 조직 첫 프로젝트 → 없으면 빈 화면 + [새 프로젝트] |
| 프로젝트 레일 | **프로젝트 영역에서만.** 200px ↔ 56px 접기(« »), 목록 `max-height: calc(100vh - 248px)`·`min-height 120`·말줄임, 항목 오른쪽에 미완료 건수, 하단 [＋ 새 프로젝트]. 접기 상태는 `localStorage` |
| 조직 하위 탭 | 개요 · **팀** · 부하 현황 · 로드맵 · 회의록 · **GitHub** (팀·GitHub 탭은 관리자만) |
| 프로젝트 하위 탭 | 태스크 · 저장소 연결 · API 문서 |
| 패널 | 목록 화면에서만. 크게 보기는 전체 오버레이 + 중앙 820px 카드 ↔ 작게 보기 |

### 6.2 조직 → 개요·부하 현황·로드맵·회의록

| 화면 | 현재와의 차이 |
|---|---|
| 개요 | 타일 6개를 미완료·**진행 중**·검토 대기·기한 초과·막힘·**완료**로 교체(현재는 이번 주 마감·기한 미정이 들어 있다). 프로젝트 표에 **담당 팀** 칩 추가. 담당자별 표는 그대로 |
| 부하 현황 | 신규. 타일 5개(진행 중·검토 대기·막힘·기한 초과·1인 평균 진행). 담당자 행 = 이름·부하 막대·요약·스킬 태그·판정. 막대는 `(진행 중 + 검토 대기) / 조직 최대치`, 과부하면 빨강. 판정은 부하 ≥ 4 또는 기한 초과 ≥ 2 → 과부하, ≤ 1 → 여유, 그 외 적정. **팀별 필터** 추가. 스킬 태그 칩 다중 선택 → "태그 → 후보 (N명)" |
| 로드맵 | 신규. 3개월 타임라인(이번 달 1일부터), 막대는 `left/width %`로 창에 클리핑, 채움은 프로젝트 완료율, 준비 중은 점선 트랙. 마일스톤 생성·수정은 `<dialog>`. 의존성은 `A → B` + 메모 + 차단 배지, 인라인 폼 |
| 회의록 | 신규. 좌측 목록(범위 칩 전체/팀 공통/프로젝트별 → 그룹 헤딩 + 항목, 선택 항목 `inset 3px 0 0 accent`), 우측 편집기. [.md 올리기](`.md`·`.markdown`만, UTF-8 검증, 256KB 상한, 본문 텍스트만) [새 회의록]. 편집기 메타 = 제목 인라인 · 프로젝트 select · 작성자 · 생성일 `<input type=date>` · 저장 상태. 본문은 Notion식 줄 단위 편집(§6.6). 삭제는 작성자·관리자만 |

부하 현황의 담당자 행은 **미완료가 없는 사람도 나와야 한다.** 지금 `by_assignee`는 집계라 미완료가 있는 사람만 나온다. `org_status()`에 활성 멤버 전원을 기준으로 하는 `capacity` 키를 추가한다.

### 6.3 조직 → 팀 (신규)

- **조직 멤버 표**: 이름 · 역할 select · 소속 팀 칩 · 스킬 태그 · GitHub 연결 여부 · 미완료 건수 · [제거]
- **초대**: 기존 초대 링크 폼 + "GitHub 조직에도 초대" 체크(관리자가 GitHub 연결돼 있을 때만 활성)
- **팀 목록**: 이름 · 멤버 수 · GitHub 팀 배지 · 담당 프로젝트 수 · [새 팀]
- **팀 상세**: 멤버 표(추가·제거) · [GitHub 팀 연결](조직의 GitHub 팀 select) · 접근 저장소 표(읽기 전용) + [GitHub에서 변경]

### 6.4 프로젝트 → 저장소 연결 (신규)

| 블록 | 내용 |
|---|---|
| 연결 | `.git` 링크 또는 저장소 주소를 붙여넣으면 `owner/repo`를 뽑아 저장한다(`https://github.com/o/r.git`, `git@github.com:o/r.git`, `https://github.com/o/r` 모두). 권한 있는 사람만. 카드에 저장소 링크 · 마지막 이벤트 시각 · 연결됨 배지 · [저장소 변경] [연결 해제] |
| 접근 팀 | **읽기 전용 표**(팀 · 권한 수준) + [GitHub에서 변경] → `https://github.com/orgs/{org}/teams/{slug}/repositories` |
| 이슈 가져오기 | 라벨 필터 · 담당자 기본값(이슈 assignee / 비워 두기) · 자동 가져오기 토글(기본 꺼짐) · 열린 이슈 목록(가져온 것은 `TASK-###로 가져옴`, 나머지 [태스크로 가져오기]) |
| 자동 전환 규칙 5개 | 이슈 → 태스크 / 브랜치 연결 → 진행 중 / 커밋 → 체크리스트 / PR 오픈 → 검토 대기 / 머지 → 완료. 각각 켜기·끄기 |
| 최근 이벤트 | 시각 · 이벤트 · 태스크 · 결과. 미매칭 커밋은 "연결 안 됨" + [태스크에 연결] |
| 참고 자료 | 기존 `Link` 재사용. 종류에 이슈·대시보드 추가, `pr`·`repo`는 폼에서 숨김 |

브랜치 이름 규칙은 강제하지 않는다. `TASK-(\d+)`를 브랜치 이름·PR 제목·PR 본문·커밋 메시지에서 찾고, 체크리스트 항목은 `TASK-147:2`(콜론 + 순번)로 지정한다.

### 6.5 프로젝트 → API 문서 (신규)

주소 입력 + [주소에서 불러오기](Enter) 또는 [파일] `.json`. **서버가 받는다**(`urllib`, http/https만, 10초, 5MB, `paths` 없으면 거부). 태그별 그룹 → 메서드 배지(GET `#1F6F82` · POST `#12793F` · PATCH `#A85B00` · PUT `#2F6FBF` · DELETE `#C92A37`) + 경로 + 요약 + 인증 배지 + `<details>` 펼침(설명·파라미터·요청 본문 example·응답 코드 배지). 경로·요약 검색은 `hx-trigger="keyup changed delay:300ms"` 부분 렌더. `$ref`는 풀지 않고 문자 그대로 표시한다.

### 6.6 회의록 편집기 (`notes.js`)

렌더된 문서에서 줄을 누르면 그 줄만 원문 `textarea`가 되고 나머지는 렌더 상태를 유지한다. Enter는 캐럿에서 분할(목록·체크박스 접두어 자동 이어짐), Backspace(offset 0)는 앞 줄과 병합, ↑/↓는 줄 이동, Esc는 편집 종료, 빈 영역 클릭은 마지막에 새 줄. 800ms 디바운스 자동 저장(`{field, value, version}` → 204 + `HX-Trigger: saved`, 409면 배너).

문법은 `#`~`###`, `-`/`*`, `1.`, `- [ ]`/`- [x]`(클릭 토글 → 원문 갱신), `>`, `---`, 인라인 `**` `*` `` ` `` `~~`. 목업 `renderVals()`의 `docBlocks`·`inline` 로직을 옮긴다. **`innerHTML`을 쓰지 않는다.**

### 6.7 태스크 패널

| 블록 | 내용 |
|---|---|
| GitHub 생애주기 | 저장소 이름은 프로젝트 연결에서 파생. 4단계(이슈·브랜치·PR·머지) 각 상태는 연결됨(✓, accent) · 진행 중(•, `#E3F1F4`) · 없음(빈 원, 회색). 없는 단계에 [이슈 연결] [이슈 만들기] [브랜치 만들기] [PR 열기]. PR 줄은 Open `#CFE3F7`/`#0B3A66`, Merged `#E7DBF7`/`#3B1A66` 배지 + 커밋 수. 커밋 목록은 sha · 메시지 · "항목 N 체크". 프로젝트 미연결이면 "저장소 미연결 + [저장소 연결]" 한 줄, 권한 없으면 §4.5 문구 |
| 참고 자료 | 회의록은 드롭다운에서 골라 내부 참조(클릭 시 이동), 외부 주소는 접힌 [＋ 외부 주소 추가]. 항목마다 연결 해제. PR·커밋은 자동으로 붙으므로 수동 추가에서 제외 |
| 체크리스트 | 항목 옆에 커밋 sha 칩. "커밋 메시지에 `TASK-147:2`처럼 적으면 그 항목이 자동으로 체크됩니다" 안내. ↑↓✕는 유지 |
| 상태 힌트 | 진행 중이고 브랜치가 연결됐으면 "연결된 브랜치 X에서 작업 중입니다." |

### 6.8 오늘·프로젝트 태스크 (기존 화면 보강)

- **일정**: 시간표 뷰와 `HOURS`를 삭제하고 월 캘린더만 남긴다. `‹` "2026년 9월" `›` + 이번 달이 아니면 [이번 달]. 월요일 시작, 셀 28/35/42. 마감 `●N`은 태스크 기한에서(완료·취소 제외). 선택일 라벨은 3분기(마감 N건 / 마감 없음 / "날짜를 누르면 그날 마감이 보입니다").
- **칸반 드래그**: 카드 `draggable`, 드래그 중 `opacity .4`, 드롭 대상 열은 `#E3F1F4` + accent 테두리, 빈 열은 "여기로 끌어다 놓기". 드롭은 기존 `POST tasks/{id}/status`를 부르고 응답으로 보드를 다시 그린다(`?view=board&part=board`). 행은 `_row.html`을 그대로 쓴다(모바일은 드래그가 안 되므로 상태 select가 남아 있어야 한다).
- **프로젝트 타일**: 기한 초과·막힘이 0보다 클 때만 `#C92A37`.

---

## 7. URL·API

### 7.1 web

| 경로 | 비고 |
|---|---|
| `/orgs/<id>` `/orgs/<id>/teams` `/teams/<tid>` `/orgs/<id>/capacity?tags=&team=` `/orgs/<id>/roadmap` `/orgs/<id>/notes?scope=` `/orgs/<id>/github` | 기존 `/teams/*`를 대체. 팀·GitHub 탭은 관리자만 |
| `/orgs/<id>/invites` · `/orgs/<id>/members/<mid>/role` · `/remove` · `/tags` | 조직 멤버 |
| `/orgs/<id>/teams/new` · `/teams/<tid>/edit` · `/delete` · `/members` · `/members/<uid>/remove` · `/github` | 팀 |
| `/orgs/<id>/milestones/*` · `/orgs/<id>/dependencies/*` | 로드맵 |
| `/orgs/<id>/notes/new` · `/notes/<nid>` · `/save` · `/upload` · `/delete` | 회의록 |
| `/projects` · `/projects/<id>?part=board` · `/projects/<id>/repo*` · `/projects/<id>/api` | 프로젝트 |
| `/tasks/<id>/notes` · `/notes/<nid>/unlink` · `/git/issue` · `/git/branch` · `/git/unlink` · `/git/close-issue` | 패널 |
| `/settings/github` · `/settings/github/callback` · `/settings/github/unlink` | 사용자 연결 |
| `/orgs/<id>/github/install` · `/github/installed` | 앱 설치 |
| `/today?schedule=1&month=YYYY-MM&day=` | `cal=` 삭제 |

### 7.2 API

- 기존 `/api/teams/*` → `/api/orgs/*`. `MeOut.teams` → `orgs`. `TeamBrief` → `OrgBrief`. 새로 `GET /api/orgs/{id}/teams`.
- `GET/PUT /api/projects/{id}/api-spec` (write 토큰). CI가 openapi.json을 밀어 넣는다.
- `POST /api/integrations/github/webhook` — 인증은 `X-Hub-Signature-256`의 `hmac.compare_digest`뿐이다. 라우터 auth를 서명 검증으로 대체해 세션·토큰이 들어오지 못하게 한다.
- `IntegrationStatus.ALLOWED += "github"`.
- `BotTokenAuth` 오류 문구를 "서비스 계정 토큰이 필요합니다."로 일반화.

---

## 8. 실행 순서

| 단계 | 내용 | 완료 조건 | 추가 테스트 |
|---|---|---|---|
| **0. 문서** | 이 계획 확정, §10 지시서 개정, 목업 파일 복사 | 결정표와 지시서 사이 모순 0 | — |
| **1. 조직·팀 재구성** | 마이그레이션 초기화, `Organization`·`OrgMembership`·`Team`·`TeamMembership`, `Project.org`+`teams`, 전 계층 개명(services·views·templates·api·discord·mcp), `org_status()` 확장 | 기존 145개가 새 이름으로 전부 통과. `/api/docs` 정상 | `test_team_member_must_be_org_member`, `test_user_in_multiple_teams`, `test_project_teams_same_org`, `test_org_visibility_unchanged`, `test_capacity_includes_members_without_tasks` |
| **2. 셸·IA** | 헤더 5영역, `/projects` index, 조건부 레일 + 접기 + 건수, 조직·프로젝트 탭, 조직 → 팀 화면 | 모든 기존 화면이 새 셸에서 동작 | `test_project_index_redirects`, `test_rail_only_in_project_area`, `test_teams_tab_admin_only`, `test_team_crud` |
| **3. 기존 화면 보강** | 칸반 드래그, 캘린더 월 이동, 타일 색, 크게 보기 오버레이 | 드롭으로 상태가 바뀌고 이력이 남는다. 막힘 드롭은 사유 패널 | `test_board_part_renders_all_columns`, `test_status_from_board_returns_board`, `test_schedule_month_nav_cells` |
| **4. 부하 현황·로드맵** | 스킬 태그, 팀 필터, `Milestone`·`ProjectDependency` | 타일 숫자가 개요와 같다. 막대가 창 밖 날짜에서 안 깨진다 | `test_capacity_verdicts`, `test_skill_filter_intersection`, `test_milestone_bar_clipping`, `test_dependency_same_org_no_self` |
| **5. 회의록** | `notes` 앱, 목록·편집기·업로드·삭제, `notes.js`, 패널 참고 자료 개편 | 동시 편집 시 뒤늦은 쪽이 409. 렌더러가 `innerHTML`을 안 쓴다 | `test_note_save_version_conflict`, `test_note_project_same_org`, `test_upload_md_only_utf8_size_cap`, `test_task_note_link_unlink` |
| **6. API 문서** | `ApiSpec`, url·file 수신, 그룹 변환·렌더·검색, API `PUT` | 이 프로젝트의 `openapi.json`을 올리면 태그별로 보인다 | `test_spec_rejects_without_paths`, `test_spec_fetch_scheme_and_size`, `test_endpoint_groups` |
| **7. GitHub 읽기** | 앱 등록·설치 흐름, `GitHubInstallation`·`GitHubIdentity`, 사용자 연결·권한 목록·로그인 갱신, 웹훅 수신·서명 검증, 자동 전환 5규칙, `RepoConnection`·`RepoIssue`·`TaskGitLink`·`GitEvent`, 저장소 탭, 패널 블록, `ChangeLog.external_actor` | 실제 저장소에서 브랜치 → PR → 머지 한 사이클이 태스크를 끝까지 옮긴다. 권한 없는 사람에게 git 정보가 안 보인다 | `test_webhook_signature_reject`, `test_event_dedupe_by_delivery`, `test_branch_rule_sets_doing_or_records_failure`, `test_commit_rule_checks_item`, `test_pr_open_review`, `test_merge_done`, `test_actor_mapping_and_external_actor`, `test_backfill_actor_on_connect`, `test_can_view_repo_filters_panel`, `test_installation_token_read_only` |
| **8. GitHub 쓰기·관리** | 조직 초대·제거, 팀 CRUD·멤버 동기화(양방향), `GitHubTeamLink`, 이슈 만들기·닫기, 브랜치 만들기, 조직 GitHub 탭, 접근 팀 읽기 표 + 딥링크 | PM에서 팀에 사람을 넣으면 GitHub 팀에도 들어간다. GitHub에서 빼면 PM에서도 빠진다 | `test_writes_use_user_token`, `test_write_denied_shows_github_reason`, `test_team_sync_both_directions`, `test_unlinked_user_pm_only_then_backfill`, `test_create_issue_and_branch`, `test_repo_permission_is_read_only_link` |

병렬: 4·5·6은 서로 독립이라 2가 끝나면 동시에 갈 수 있다. 7·8은 앱 등록이 선행된다.

**중간 검토 지점 셋.** 1단계 끝(개명이 끝나고 기존 테스트가 전부 통과하는 상태), 6단계 끝(GitHub 전까지 완결된 상태), 8단계 끝. 각 지점에서 멈추고 사용자가 본다. 1단계는 파일 대부분을 건드려 되돌리기 비싸므로 그 뒤에 바로 확인하는 것이 중요하다.

**GitHub App 등록은 사용자만 할 수 있다.** 1~6단계가 진행되는 동안 운영용과 개발용 앱을 미리 등록해 둔다. 절차는 [GITHUB-APP-SETUP.md](GITHUB-APP-SETUP.md) 한 장이다.

각 단계 끝: `uv run pytest -q`(SQLite·Postgres), `uv run ruff check .`, 목업 대조, 커밋.

---

## 9. 운영자 1회 설정

1. GitHub에서 App을 등록한다. 권한은 §4.3, 웹훅 주소는 `https://pm.<도메인>/api/integrations/github/webhook`, "설치 중 사용자 인가 요청"과 "사용자 토큰 만료"를 켠다. 설치 대상은 모든 계정.
2. `.env`에 앱 ID, 개인키, client id·secret, 웹훅 secret, `CREDENTIAL_KEY`(Fernet)를 넣는다.
3. 조직 관리자가 PM에서 [GitHub 앱 설치]를 누르고 GitHub에서 조직과 저장소 범위(권장: All repositories)를 고른다.
4. 각자 프로필에서 [GitHub 연결].

`compose.yml`은 바뀌지 않는다. 새 컨테이너도 새 공개 호스트도 없다.

---

## 10. 지시서 (2026-09-11 개정 완료)

기존 `GUIDE-01`~`04`는 **아무것도 없는 상태에서 만드는** 문서였고 그 작업은 끝났다. 이번 라운드는 있는 코드를 고치는 일이라 같은 형식으로 다시 쓰면 대부분이 이미 있는 코드를 옮겨 적는 일이 된다. 그래서 **단계별 수정 지시서 묶음을 새로 썼다.**

| 문서 | 내용 |
|---|---|
| `GUIDE-00-rules.md` | 개정. 지시서가 두 묶음이라는 것, `cryptography` 1건 추가, 값 표(조직 역할·팀·링크 종류·변경 경로 `gh`·마일스톤·이슈·PR 상태), 저장소 구조 |
| **`GUIDE-V2-00-overview.md`** | 이번 라운드 개요. 수정 라운드 규칙, 단계 순서, 공통 검증 절차, v1 범위, 자주 틀리는 것 |
| **`GUIDE-V2-01-org-teams.md`** | 1단계. 개명 대조표, `orgs` 앱 모델·서비스 전체, 마이그레이션 초기화, `org_status()` 확장, API·web·discord·mcp 변경 |
| **`GUIDE-V2-02-shell-ia.md`** | 2단계. 헤더 5영역, `/projects`, 접이식 레일, 하위 탭 partial, 조직 개요 타일, 조직 → 팀 화면 |
| **`GUIDE-V2-03-board-calendar.md`** | 3단계. 칸반 드래그, 월 캘린더(시간표 삭제), 프로젝트 타일 경고색 |
| **`GUIDE-V2-04-capacity-roadmap.md`** | 4단계. 부하 현황, 스킬 태그, `Milestone`·`ProjectDependency`, 타임라인 계산 |
| **`GUIDE-V2-05-notes.md`** | 5단계. `notes` 앱, 낙관적 잠금 저장, `.md` 업로드, `notes.js` 전체, 패널 참고 자료 |
| **`GUIDE-V2-06-api-docs.md`** | 6단계. `ApiSpec`, 서버 프록시·파일 업로드, `spec_view()`, 렌더와 검색 |
| **`GUIDE-V2-07-github-read.md`** | 7단계. 앱 등록 절차와 권한, `cryptography` 사용처, 모델 6개, JWT·설치 토큰·사용자 토큰, 권한 필터, 웹훅과 서명 검증, 자동 전환 5규칙, 저장소 탭, 패널 블록 |
| **`GUIDE-V2-08-github-write.md`** | 8단계. 쓰기 원칙 둘, 쓰기 목록과 필요 권한, 팀 양방향 동기화, 이슈·브랜치 만들기, 오류 문구, v1 완료 조건 |
| **`GITHUB-APP-SETUP.md`** | 운영자·다른 에이전트용 GitHub App 등록 한 장. 앱 두 개(운영·개발), 주소 셋, 권한, 옵션, `.env` 매핑, 확인 방법 |
| `GUIDE-01`~`04` (8개) | 머리말만 추가. "최초 구축의 기록이고 여기의 `Team`은 조직을 뜻한다" |
| `SPEC.md` | Notion 회의록 저장소 폐기, 범위 표(회의록 포함·파일 업로드 제외), 조직·팀 계층과 GitHub 통합 |
| `PLAN.md` · `IMPL-PLAN.md` · `README.md` | 이 라운드로 이어지는 포인터 |
| `GUIDE-04-deploy.md` · `.env.example` | GitHub App 설정 6개와 `CREDENTIAL_KEY`. `compose.yml`은 **바뀌지 않는다**(새 컨테이너·새 호스트 없음) |

계획 초안에 있던 `GUIDE-05-github.md` 한 편은 `GUIDE-V2-07`·`08` 둘로 나뉘었다.

## 11. 열린 질문

1. **저장소 생성** — 프로젝트를 만들면서 GitHub 저장소도 만드는 흐름이 자연스럽지만 권한이 한 단계 무거워진다. v1 제외로 두었다.
2. **체크리스트 커밋 표기** `TASK-147:2` — 팀이 커밋 메시지에 쓸 형식이라 합의가 필요하다.
3. **로그인 시 권한 갱신의 지연** — 요청 경로에서 GitHub를 한 번 부른다. 느껴지면 첫 GitHub 화면 진입 때로 미룬다. `# ponytail:` 주석을 남긴다.
4. ~~팀 삭제 시 GitHub 팀~~ — **확정: PM 팀만 지운다.** GitHub 팀에는 PM이 모르는 저장소 권한이 붙어 있을 수 있다(2026-09-11 검토).
5. **부하 계산의 중요도 가중치**, **회의록 이미지·버전 이력**, **로드맵 기간 전환** — 전부 v1 제외.
6. **GitHub 미연결 사용자의 초대** — 조직 초대 링크와 GitHub 조직 초대를 한 번에 보낼지, PM 가입 후 각자 연결하게 할지. 지금은 체크박스로 선택.
