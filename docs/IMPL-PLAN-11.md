# P — 라운드 11 설계: Notion 가져오기 · 담당자 1명 안내 · 태스크 다중 프로젝트 연결 · 문서 확장 (Fable, 2026-10-07)

기준: main `988d588`. 근거 표기는 `파일:줄`. 코드·git은 손대지 않았다(읽기만).

---

## 0. 전제

### 0.1 사용자 결정(2026-10-07, 확정 — 이 설계보다 우선)
1. Notion은 **링크로 가져오거나 MD를 불러올 수 있게**. 선택지 비교·추천은 §1.
2. **태스크 담당자는 한 명**. 여러 명처럼 보이면 역할을 쪼개도록 유도(§2).
3. **태스크 하나를 여러 프로젝트에 연결**(§3).
4. **문서 기능을 적극 추가**(§4). 범위가 크면 v1/v2.
5. (추가) **개발일지는 거의 안 쓴다** → 전용 기능 없음. 가져올 때 진행 메모에 날짜 줄로 보존하는 정도(§1.5, §4.1).
6. (추가) **Notion DB 동기화는 하지 않는다** → 일회성 가져오기. 열(속성)은 사람이 고르는 범용 방식(§1.3).

### 0.2 동시 진행 중인 다른 에이전트(겹치지 않게 한다)
다른 Fable이 `docs/IMPL-PLAN-10.md`(운영 콘솔 `/ops`·감사 로그·Django admin 잠금)를 설계 중이다. 아직 파일이 없어 소유 파일은 추정이다.

| 추정 소유 파일(IMPL-PLAN-10) | 이 설계에서 닿는 곳 | 처리 |
|---|---|---|
| `web/views/ops.py`, `templates/ops.html`, `config/urls.py`, `accounts/admin.py` | 닿지 않음 | — |
| `web/urls.py` | 새 경로 추가(§7 각 단계) | **끝에 덧붙이기만** |
| `config/settings.py` | `INSTALLED_APPS`에 `imports` 한 줄(N1) | 끝에 덧붙이기 |
| `tasks/models.py`·`tasks/migrations` | `0010`(P1)·`0011`(D2) | 감사 로그가 `tasks`에 마이그레이션을 만들면 **번호를 당겨 조정**(병합 때 대조) |
| `templates/base.html`(주 메뉴), `templates/orgs/_tabs.html` | 문서 탭 한 줄(D2) | 그들 병합 뒤 덧붙임 |

### 0.3 공통 원칙(이 라운드)
- 새 규칙은 전부 `services`(또는 같은 앱의 서비스 모듈)에 두고 웹·API·MCP·Discord는 부르기만 한다(`docs/GUIDE-00-rules.md:72-82`).
- 새 의존성 없음. ZIP·CSV·마크다운 처리는 표준 라이브러리(`zipfile`·`csv`·`re`)로만 한다(`docs/GUIDE-00-rules.md:54-60`). 마크다운 렌더는 지금처럼 클라이언트 `notes.js`.
- 메모리 512MB: 가져오기는 ZIP 항목을 하나씩 읽고(전체를 메모리에 펼치지 않음), 파일 상한을 둔다(§1.6). 백그라운드 작업·큐 없음 — 행 수천 건은 요청 하나 안에서 끝난다.
- 가시성은 기존 관문 함수를 넓히지 않는다: `visible_projects`(`projects/services.py:73-89`) → `visible_tasks`(`tasks/services.py:219-223`) → `visible_notes`(`notes/services.py:34-48`). 새 개념도 이 관문을 지난다.
- 마이그레이션 번호 고정(§7): `tasks 0010`(P1) · `projects 0012`(D1) · `tasks 0011`(D2) · `imports 0001`(N1). `orgs`·`notes`·`accounts`는 바꾸지 않는다.

---

## 1. Notion 가져오기

### 1.1 선택지 비교

| | (a) Notion 공식 API | (b) 공개 페이지 비공식 긁기 | (c) 내보내기 ZIP(Markdown & CSV) 업로드 | (d) `.md` 낱개/여러 개 업로드 |
|---|---|---|---|---|
| 사용자가 하는 일 | 조직 관리자가 integration 만들기 → 토큰 입력 → **페이지마다 integration에 공유** → 링크 입력 | 링크 입력(공개 페이지만) | Notion에서 "내보내기 → Markdown & CSV, 하위 페이지 포함" 3번 클릭 → ZIP 올리기 | 파일 선택 |
| 본문 변환 | 블록 JSON → 우리가 마크다운으로 변환(블록 20여 종, 표·토글·콜아웃·수식·동기 블록 각각 처리). 이미지는 1시간짜리 서명 URL이라 즉시 내려받아야 함 | 내부 API 응답(비공개 형식) 파싱 | **Notion이 변환한 마크다운**을 그대로 받음. 하위 페이지는 폴더, DB는 CSV, 이미지는 같은 폴더 | 그대로 |
| DB 속성 | 완전(속성 형식·사람 id·관계 id·생성/완료 시각) | 부분 | CSV 열(문자열). 사람은 이름, 관계는 제목, 날짜는 문자열 → 사람 매칭·날짜 파싱 필요 | 없음 |
| 지속 동기화 | 가능(이번 범위 밖 — 결정 6) | 불가 | 불가(일회성) | 불가 |
| 비용·위험 | 규모 **L**(변환기 + 페이지네이션 + 3req/s 제한 + 토큰 저장·마스킹). 공유 안 한 페이지는 안 보여 "링크만 있으면"이 성립하지 않음 | 약관 위반·언제든 깨짐·로그인 쿠키 필요 → **제외** | 규모 **M**. 표준 라이브러리만. 토큰 없음. 변환 품질은 Notion 몫 | 규모 S(이미 있음: `projects/docs.py:88-103`, `notes/services.py:136-148`) |

**추천: (c)+(d)를 한 기능 "가져오기"로.** 근거: 결정 6(일회성)에서 API의 유일한 장점(동기화)이 사라지고, 남는 건 "링크 입력" 편의뿐인데 그것도 페이지마다 integration 공유가 필요해 ZIP 내보내기 3클릭보다 쉽지 않다. 변환 품질도 Notion 자체 내보내기가 우리가 만들 변환기보다 낫다. (a)는 **v2 확장 지점**으로만 남긴다: 토큰은 `Spec("notion.token", "secret", …)` 한 줄로 기존 비밀값 방식(`orgs/settings.py:56-58`, `merge_secrets` `:1012-1040`, Fernet `github/crypto.py`)을 그대로 쓰면 되고, 파서는 §1.4의 같은 중간 형식으로 넣으면 된다.

결정 6을 반영한 범위: **DB 가져오기는 "CSV 범용 가져오기"**(열을 사람이 고름), **페이지는 "Markdown 가져오기"**(폴더 = 하위 문서). Notion ZIP은 이 둘을 한 번에 찾아 주는 포장일 뿐이다. 따라서 Notion이 아닌 CSV(스프레드시트 내보내기)나 Obsidian 폴더 ZIP도 같은 화면으로 들어온다.

### 1.2 Notion 내보내기 형식(설계 전제 — 실제 내보내기로 검증 필요, §9)
- 페이지: `제목 <32자리 hex>.md`. 하위 페이지는 같은 이름의 폴더 안. 페이지 간 링크는 상대 경로(URL 인코딩, 같은 hex 포함).
- DB: `DB이름 <hex>.csv`(현재 보기) + `DB이름 <hex>_all.csv`(전체 행, 최근 내보내기). 행 페이지는 `DB이름 <hex>/행제목 <hex>.md`. 행 안 인라인 DB(개발일지)는 그 폴더 안의 또 다른 CSV.
- CSV: 첫 열이 제목 속성. 사람·관계·다중 선택은 `, `로 이은 문자열. 날짜는 영문("October 5, 2026 3:00 PM") 또는 로캘 형식.
- 큰 내보내기는 ZIP 안에 ZIP이 들어 있기도 하다(한 단계만 풀어 준다).
- hex id는 **중복 방지 키**(§1.5). hex가 없는 CSV(일반 스프레드시트)는 `sha1(파일명 + 제목 + 생성일시)`를 대신 쓴다.

### 1.3 화면 흐름(조직 관리자만, `/orgs/<id>/import`)
가져오기는 조직 관리자만 한다 — 담당자를 남에게 바로 맡길 수 있어야 담당 요청(REQ)이 수십 건 튀지 않는다(`tasks/services.py:287`, `work_requests.can_assign_directly`).

```
1 올리기      ZIP / CSV 여러 개 / .md 여러 개 선택 → [열어 보기]
2 대상 정하기  찾은 CSV마다: 가져올 곳 = 태스크 | 프로젝트 | 회의록 | 문서 | 사람 매칭표 | 건너뛰기
              찾은 .md 묶음(폴더 트리): 가져올 곳 = 문서(위치: 조직 / 프로젝트 X / 팀 Y) | 건너뛰기
3 열 지정     대상별로 어느 열이 제목·상태·담당자·기한·…인지 선택(아래 표). 안 고른 열 → "속성명: 값" 줄로 설명에 보존
4 값 대응     상태 열의 고유값 → 유달리 상태, 중요도 고유값 → 1~10, 사람 이름 → 조직 멤버(이메일·이름 자동, 못 찾으면 선택)
5 미리보기    만들 것 N건 · 건너뛸 것(이미 가져옴) N건 · 경고 목록(§1.7) — 아무것도 쓰지 않는다
6 가져오기    같은 요청으로 실행 → 결과 보고(§1.7) + "사람별로 나누기" 바로가기
```
- 파일은 서버에 임시 저장하지 않는다. 폼의 `<input type=file>`을 HTMX 교체 대상 밖에 두면 단계마다 같은 파일이 다시 올라간다(최대 50MB, 6번까지 — 운영 서버 대역폭에서 문제없음). 임시 저장·작업 모델·만료 청소가 모두 사라진다. `# ponytail: 단계마다 재업로드, 100MB 넘는 내보내기가 생기면 MEDIA_ROOT/import 임시 저장으로`.
- 폼 보존: 2~4단계 선택값은 hidden 필드로 다음 단계에 실린다(`mapping` JSON 하나).

열 지정 표(태스크 대상). 프로젝트·회의록·문서도 같은 꼴이다.

| 유달리 항목 | 필수 | Notion 열 자동 추천(이름이 같으면 미리 고름) | 비고 |
|---|---|---|---|
| 제목 | ○ | 업무 제목 / Name / 첫 열 | 200자 자름 |
| 상태 | | 상태 / Status | 고유값 대응(4단계). 미대응 값 → `todo` + 경고 |
| 담당자 | | 담당자 / Assignee / 사람 | 여러 명이면 **첫 매칭 = 담당자**, 나머지는 설명 첫 줄 "함께: A, B" + §2 나누기 후보. 아무도 못 찾으면 "기본 담당자"(5단계에서 고름, 기본 = 나) |
| 프로젝트 | | 소속 프로젝트 / Project | 여러 개면 첫 = 주 프로젝트, 나머지 = 연결 프로젝트(§3, P1 병합 뒤). 없거나 못 찾으면 "기본 프로젝트"(기존 선택 또는 새로 만들기 — 기본 이름 "가져온 항목") |
| 목표 기한 | | 목표 기한 / Due / Date | 미완료인데 없으면 `no_due_reason="Notion에서 가져옴(기한 없음)"` |
| 완료일시 | | 완료일시 / Completed | 완료인데 없으면 **생성일시**로 채우고 설명에 "완료일시 미상(Notion)"(제약 `task_done_requires_completed_at` 때문. 새 날짜를 지어내지는 않는다) |
| 생성일시 | | 생성 일시 / Created | 없으면 가져온 시각 |
| 중요도 | | 중요도 / Priority | 고유값 대응(높음 9 · 중간 5 · 낮음 2, 숫자는 그대로 1~10 자름) |
| 설명 | | 상세 설명 / Description | 행 페이지 `.md` 본문이 있으면 그 뒤에 붙임 |
| 원본 링크 | 자동 | — | `Link(kind="other", title="Notion 원본", url=https://www.notion.so/<hex>)` — 사람이 원문을 찾아갈 수 있게 |

사람 매칭 규칙(순서): ① 이메일 정확히 ② `display_name` 공백·대소문자 무시 정확히 ③ Team Members CSV(사람 매칭표 대상)에서 "이름 → 계정(이메일)" 간접 매칭 ④ 못 찾음 → 4단계에서 선택(또는 "기본 담당자"). 사람을 **만들지는 않는다**(초대 링크로 가입해야 한다 — `O-notion-migration.md` §2 #1).

### 1.4 데이터 모델·구조 — 새 앱 `core/imports/`
`tasks`·`projects` 마이그레이션 번호를 건드리지 않으려고 작은 앱 하나를 둔다(`INSTALLED_APPS` 한 줄).

```python
# imports/models.py — 0001_initial
class ImportRecord(models.Model):
    """가져온 원본 하나 → 유달리 객체 하나. 같은 원본을 다시 올리면 건너뛴다(동기화 없음)."""
    org = FK("orgs.Organization", CASCADE, related_name="+")
    batch = UUIDField()                      # 한 번의 가져오기. 결과 보고·검색에 쓴다
    source_ref = CharField(max_length=80)    # "notion:<hex>" | "csv:<sha1>" | "md:<sha1>"
    target_type = CharField(max_length=10)   # task | project | note | doc
    target_id = PositiveBigIntegerField()
    created_by = FK(AUTH_USER_MODEL, PROTECT, related_name="+")
    created_at = DateTimeField(auto_now_add=True)
    class Meta:
        constraints = [UniqueConstraint(fields=["org", "source_ref"], name="importrecord_org_ref")]
        indexes = [Index(fields=["batch"])]
```

```
imports/
  models.py         ImportRecord
  parse.py          ZIP·CSV·MD 읽기 → 중간 형식(아래). Notion 이름 규칙(hex 제거)·날짜 파싱·링크 재작성
  services.py       plan(미리보기) · run(실행) · 사람 매칭 · 값 대응 추천
  tests.py
```
중간 형식(파서가 만들고 services가 소비. API로 받는 형식도 같다):
```python
Bundle(csvs=[CsvTable(name, source_ref, columns, rows=[{col: str}], row_pages={row_ref: md})],
       pages=[Page(title, source_ref, body_md, path=("필독", "Ground Rule"), images=[(name, bytes_ref)])])
```
서비스 함수(모두 `actor`는 조직 관리자, `require_admin`):
- `plan(org, bundle, mapping, *, actor) -> Plan` — 아무것도 쓰지 않는다. `Plan.items=[{kind, action: create|skip, title, fields, warnings}]`, `Plan.summary`.
- `run(org, bundle, mapping, *, actor, split_multi_assignee=False) -> Report` — `transaction.atomic`. 순서: 프로젝트 → 사람 매칭 → 태스크(주 프로젝트 먼저, 연결은 그다음 패스) → 회의록 → 문서(트리 순, 두 번째 패스에서 페이지 간 링크를 `/docs/<id>`로 재작성) → `ImportRecord` 일괄 생성.
- 태스크 생성은 `create_task(... source="web", notify_assignee=False)`로 규칙(기한·완료 조건·중요도 상한·AI 정책)을 그대로 태운 뒤, **원본 시각·상태만** `Task.objects.filter(pk).update(created_at=, status=, completed_at=, status_since=)`로 덮는다. 이 `update`는 `services` 안(imports/services.py)에서만 한다(`GUIDE-00` "Task를 services 밖에서 update 금지"의 취지 준수 — 규칙을 우회하지 않고 시각만 보존). `ChangeLog(field="imported", note=source_ref)` 한 줄.
- 완료 조건 필수(`task.require_done_when`)가 켜진 조직은 가져올 때 `done_when="Notion에서 가져옴"`을 넣는다(경고로 알림).
- 문서는 `projects.docs.create_doc`(§4) + `move_doc`로 트리를 만든다. 회의록은 `notes.services.create_note`(날짜 열 → `created_on`, 선택·태그 열 → `tags`).
- 이미지: 페이지 폴더의 `.png/.jpg/.gif/.webp`(허용 표 `tasks/attachments.py:26-45`) ≤ 25MB → 그 문서의 첨부(`Attachment.doc`, §4.3)로 저장하고 본문의 상대 경로를 다운로드 URL로 바꾼다. 그 밖 파일은 건너뛰고 보고에 적는다. 첨부 조직 상한(2GB)은 기존 검사 그대로.

### 1.5 개발일지·다중 담당·다중 프로젝트 행의 처리(결정 5·6)
- 행 페이지 안 인라인 DB(개발일지)는 **진행 메모**에 `YYYY-MM-DD — 내용` 줄로 보존한다(전용 기능 없음). 행이 0건이면 아무것도 안 한다.
- 다중 담당자: §1.3 규칙 + 옵션 체크박스 "담당자가 여러 명인 행은 사람별 태스크로 나눠서 가져오기"(기본 꺼짐). 켜면 생성 직후 `tasks.split.split_by_assignees`(§2.3)를 부른다.
- 다중 프로젝트: 첫 = 주, 나머지 = 연결(`tasks.services.link_project`, §3). P1 병합 전이면 설명 줄 "관련 프로젝트: B, C"로.

### 1.6 상한·보안
- ZIP 50MB · 항목 3,000개 · 압축 해제 합계 200MB(zip bomb 차단: 항목 `file_size` 합산 검사) · CSV 5,000행 · 문서 본문 256KB(`MAX_BODY`와 같음) · 경로에 `..`·절대 경로 거부 · 중첩 ZIP 한 단계만.
- CSV 셀 앞의 `= + - @`는 그대로 문자열이다(우리가 스프레드시트로 내보내지 않으므로 위험 없음). 본문은 기존 편집기 규칙대로 클라이언트에서 안전하게 렌더된다(`notes.js:40-65`의 URL 검사).
- 조직 관리자만, 로그인 세션만(토큰·MCP로 가져오기 없음 — AI가 수십 건을 만드는 경로를 열지 않는다). API는 **미리보기 결과 조회**와 **실행**을 세션 인증으로만 연다(`POST /api/orgs/{id}/import/plan`, `/run`; 스킬·MCP 노출 없음).
- 처리량 제한: 조직당 분당 3회(기존 `UserRateThrottle` 방식).

### 1.7 미리보기·결과 보고
미리보기 표(`table.grid`, `.table-scroll`): 종류 / 제목 / 담당자 / 프로젝트 / 상태 / 기한 / 처리(만듦·건너뜀) / 경고. 경고 종류(`SPEC.md:425-436` 검토 목록을 그대로 옮김):
담당자 못 찾음 · 담당자 2명 이상 · 프로젝트 없음·못 찾음 · 프로젝트 2개 이상 · 완료인데 완료일시 없음 · 완료일시가 생성일시보다 앞섬 · 미완료인데 기한 없음/오래됨 · 상태값 미대응 · 날짜 파싱 실패(원문을 설명에 보존) · 이미지 건너뜀.
결과 보고: 만든 수(종류별) · 건너뛴 수(이미 가져옴) · 경고 수 · 나누기 후보 목록(각 행에 [사람별로 나누기] 링크 → §2.4 대화상자) · 원본 링크 수. 보고는 화면에만(저장 안 함). `ImportRecord.batch`로 "이번에 가져온 태스크" 검색 필터(`/me?batch=`는 두지 않음 — 조직 전체 태스크 화면에서 `imported=<batch>` 칩 하나).

### 1.8 API·MCP·스킬·Discord 영향
- API: `POST /api/orgs/{id}/import/plan`(multipart: files + mapping JSON) → Plan, `POST …/import/run` → Report. 세션 인증 + 관리자. 그 밖 변경 없음.
- MCP·스킬·Discord: **없음**(의도). 스킬 `pm/SKILL.md`에 "가져오기는 웹에서 관리자가 한다" 한 줄.

### 1.9 테스트(`imports/tests.py`)
- 파서: Notion 이름 규칙(hex 분리·URL 디코드), 폴더 → 트리, `_all.csv` 우선, 중첩 ZIP 한 단계, 상한(크기·항목 수·zip bomb·경로 탈출) 거부, 날짜 형식 3종 + 실패 보존.
- 서비스: 열 지정·값 대응 → 태스크 필드, 생성·완료 시각 보존, 완료일시 없음 → 생성일시 + 설명 줄, 재실행 시 0건 생성(`ImportRecord`), 다중 담당자 → 첫 + "함께:" 줄(+ 옵션 켜면 나누기), 다중 프로젝트 → 주 + 연결, 사람 매칭 3단계, 기본 담당자·기본 프로젝트, 멤버는 403(관리자만), `plan`은 DB에 아무것도 쓰지 않음(쿼리 수·행 수 불변), 페이지 간 링크 재작성, 이미지 첨부·초과 건너뜀, 개발일지 → 진행 메모 줄.
- 웹: 단계 폼이 hidden `mapping`을 이어 나르는지, 미리보기 표 경고 표시, 실행 뒤 보고 화면.

### 1.10 수용 기준
- O 분석의 실제 데이터(Projects 15·Tasks 약 46·문서 정리 약 27·위키 8)를 ZIP 한 번으로 미리보기 → 실행 → 재실행 시 0건 생성.
- 원본 생성·완료 시각이 보존되고 주간 보고의 "이번 주 완료"가 가져온 과거 태스크로 부풀지 않는다.
- 가져오기 중 담당 요청·Discord 알림이 한 건도 생기지 않는다.

---

## 2. 담당자 1명 고정과 "사람별로 나누기"

### 2.1 원칙
모델은 그대로(`Task.assignee` FK 1개, `tasks/models.py:32-37`). 어디서든 **둘 이상이 들어오려 하면 막지 않고 안내**한다 — 담당자는 한 명이고, 여러 사람이 하는 일은 사람별 태스크로 나눠 **계열**로 묶는다(이미 있는 `Task.parent` 평평한 계열, `tasks/models.py:54-62`).

### 2.2 "여러 명처럼 보인다"의 판정(`tasks/split.py` 새 파일 — `tasks/services.py`와 충돌 피함)
```python
def looks_multi_assignee(task_or_fields, org) -> list[User]:
    """제목·설명에 조직 멤버 display_name이 2명 이상 보이면 그 사람들. 아니면 [].
    # ponytail: 키워드('같이','함께','공동','전원','다 같이')는 이름이 1명 이상 보일 때만 힌트로 더한다 — 오탐 방지.
    """
```
- 안내는 **막지 않는** `.notice`(글리프 없음, `DESIGN.md` §3 알림)다: "이 일은 여러 사람이 맡는 것처럼 보입니다. 사람별로 나누면 담당·기한·완료가 또렷해집니다. [사람별로 나누기]".
- 거짓 양성이 있어도 비용이 없다(안내만). 제목에 사람 이름을 쓰지 않는 조직이면 안내가 안 뜰 뿐이다.

### 2.3 서비스 — `tasks/split.py`
```python
@transaction.atomic
def split_by_assignees(task, users, *, actor, source, token=None, title_pattern="{title} — {name}") -> list[Task]:
    """사람마다 태스크 하나. duplicate_task(설명·완료 조건·체크리스트·링크·문서 연결 복사, parent=계열 뿌리)를 그대로 쓴다.
    원본은 지우거나 취소하지 않는다. 원본 체크리스트를 'TASK-n 이름' 목록으로 바꾸고 진행 메모에 한 줄 남긴다(pm-split 규칙과 같다).
    담당 권한이 없는 사람에겐 create_task의 기존 규칙대로 담당 요청이 간다(만든 사람이 임시 담당)."""
```
- 2~10명. 원본 담당자도 목록에 넣을 수 있다(원본은 "묶음"으로 남고 자기 몫은 새 태스크).
- 기한·중요도·기한 미정 사유는 원본 복사. 연결 프로젝트(§3)도 복사.
- 권한: 원본을 볼 수 있는 조직 멤버(`duplicate_task` → `create_task`의 `_require_member`).
- 이력: 원본에 `ChangeLog(field="split", new_value="TASK-a,TASK-b")`, 새 태스크는 `duplicate_task`가 남기는 `parent` 이력.

### 2.4 경로별 동작

| 경로 | 지금 | 바꿀 것 |
|---|---|---|
| 웹 만들기 폼(`templates/projects/_task_form.html:6` "담당자 (1명)") | 단일 select | 그대로. 저장 뒤 패널에 §2.2 안내가 뜬다(제목으로 판정) |
| 웹 패널(`templates/tasks/_panel.html:47-52`) | 담당자 select | 담당자 줄 아래 `[사람별로 나누기]` 버튼(`.btn.sm`) → `dialog` `templates/tasks/_split.html`: 멤버 체크 목록(판정된 사람은 미리 체크) + 제목 규칙 미리보기 + [나누기](`.primary`). 결과: 계열 섹션(`_series.html`) 갱신, 토스트 "3건으로 나눴습니다." |
| 가져오기(§1) | — | 미리보기 경고 "담당자 2명 이상" + 옵션 체크박스 + 보고의 바로가기 |
| API | `assignee_id: int` | `TaskCreateIn`·`TaskPatchIn`에 `assignee_ids: list[int] | None = None`을 **받되 거절**: 400 `{"assignee_ids": "담당자는 한 명입니다. 사람별로 나누려면 만든 뒤 POST /api/tasks/{id}/split 을 쓰세요."}`. 새 `POST /api/tasks/{id}/split {assignee_ids:[…], title_pattern?}` → 201 `{tasks:[…]}` |
| MCP(`mcp_server/server.py:541` `create_task`) | — | docstring에 "담당자 한 명" 명시, 새 도구 `split_task(task_id, assignee_ids)`, `get_guide` 조합표에 "여러 사람이 할 일 → create_task 1건 → split_task" |
| 스킬 | `pm-new` 3단계가 이미 "필요한 담당자가 서로 다르면 분할 후보"(`skills/pm-new/SKILL.md:16-27`) | `pm/SKILL.md`에 규칙 한 줄, `pm-split`에 "사람별 모드"(표의 담당 열이 다 다르면 `POST /tasks/{id}/split` 한 번으로) |
| Discord `/태스크만들기`(`slash.py:292-319`) | 담당자 1명 autocomplete | 그대로. 응답 끝에 판정이 걸리면 한 줄: "담당자는 한 명입니다. 사람별로 나누려면 웹에서 [사람별로 나누기]를 누르세요." + 태스크 링크. 새 명령 없음 |
| Notion 다중 담당 행 | — | §1.5 |

### 2.5 테스트
- `looks_multi_assignee`: 이름 2명 → 목록, 1명 → [], 키워드만 → [], 비활성 멤버 제외.
- `split_by_assignees`: 3명 → 태스크 3건·parent=원본 뿌리·체크리스트 복사·원본 체크리스트 교체·이력, 권한 없는 담당 → 담당 요청 1건, 1명/11명 거절, 연결 프로젝트 복사(P1 뒤).
- API `assignee_ids` → 400 문구, `/split` 201, 볼 수 없는 태스크 404.
- 웹 대화상자 렌더·제출, Discord 응답 문구(기존 `test_discord_slash.py` 패턴).

### 2.6 수용 기준
- 어떤 경로로도 담당자가 둘 이상 저장되는 길이 없고, 둘 이상을 시도한 사람은 **한 번의 클릭/호출**로 사람별 태스크를 만들 수 있다.

---

## 3. 태스크 하나를 여러 프로젝트에 연결

### 3.1 대안 비교

| | A. `Task.project` FK → M2M로 교체 | **B. 주 프로젝트 FK 유지 + 연결 표 `TaskProject`** | C. 프로젝트마다 복제 태스크(미러) |
|---|---|---|---|
| 모델 | 큰 변경. 번호·설정·알림 "소유자"가 없어짐 | 열 추가 없음. 새 표 하나 | 변경 없음 |
| 영향 범위 | `project=`·`project__in` 조회 97곳 전부 | 집계·보드·달력 등 **프로젝트 기준 화면만**(§3.6), `visible_tasks` 불변 | 없음. 대신 상태가 N벌로 갈라짐 |
| 가시성 | 어느 프로젝트 기준으로 볼지 규칙을 새로 만들어야 함 | 주 프로젝트 규칙 그대로 | 각자 |
| 판단 | 비추천 | **추천** | "저장소마다 따로 하는 일"이면 §2의 나누기가 이미 이것이다 → 기능으로 안 만듦 |

사용 안내(스킬·guide에 그대로): **하나의 작업이 여러 프로젝트에 "관련"되면 연결, 프로젝트마다 "따로 하는" 작업이면 나누기.**

### 3.2 모델 — `tasks 0010_taskproject`
```python
class TaskProject(models.Model):
    """연결 프로젝트. 주 프로젝트(Task.project)는 번호·규칙·알림·저장소의 소유자이고 여기엔 들어가지 않는다."""
    task = FK(Task, CASCADE, related_name="project_links")
    project = FK("projects.Project", CASCADE, related_name="task_links")
    created_by = FK(AUTH_USER_MODEL, PROTECT, related_name="+")
    created_at = DateTimeField(auto_now_add=True)
    class Meta:
        constraints = [UniqueConstraint(fields=["task", "project"], name="taskproject_task_project")]

# Task
extra_projects = ManyToManyField("projects.Project", through="TaskProject", related_name="linked_tasks", blank=True)
```
- "주 프로젝트 ≠ 연결 프로젝트"는 서비스가 검사한다(DB 제약은 두 표에 걸쳐 못 건다). 같은 조직만.
- 데이터 마이그레이션 없음(기존 태스크는 연결 0개).

### 3.3 규칙(설정 상속·소유)
| 항목 | 기준 |
|---|---|
| 번호 `TASK-n`, 생성·이동·삭제, 담당자·검토자 가시성 검사(`_require_viewer`) | 주 프로젝트 |
| 설정(`effective(..., project=)`: 기한 필수·완료 조건·중요도 상한·초과 유예·기본 보기) | 주 프로젝트만. 연결 프로젝트 설정은 보지 않는다(규칙이 둘이면 사용자가 어느 쪽인지 알 수 없다) |
| Discord 프로젝트 채널 알림 | 주 프로젝트 채널만(v1). `# ponytail: 연결 채널에도 보내려면 notify에서 extra_projects 순회` |
| GitHub `TASK-n` 매칭(`github/services.py:794-803` `_find_task`는 `project=conn.project`) | **주 프로젝트 저장소만**(v1, 질문 2). 연결 저장소의 브랜치·PR이 번호를 적어도 움직이지 않는다 — `TaskGitLink`가 태스크당 하나(`github/models.py:TaskGitLink` OneToOne)라 여러 저장소를 받으면 연결이 마지막 저장소로 튄다 |
| 보관(`archive_project`) | 주 프로젝트 보관 때만 `cancel_open` 적용. 연결 프로젝트 보관은 그 화면에서 안 보일 뿐 |
| 프로젝트 삭제 | `Task.project`는 PROTECT 그대로, `TaskProject`는 CASCADE(연결만 사라짐) |

### 3.4 가시성(정보 누출 없음)
- **태스크는 주 프로젝트를 볼 수 있을 때만 보인다.** `visible_tasks`(`tasks/services.py:219-223`)를 바꾸지 않는다. 연결은 가시성을 넓히지도 좁히지도 않는다.
- 연결 **만들기**: 행위자가 **양쪽 프로젝트를 모두 볼 수 있어야** 한다(`can_view_project` 둘 다). 조직 멤버 누구나(추가 설정 없음. 필요해지면 `task.link_project_level` Spec 한 줄).
- 연결 **표시**: 태스크 패널·행의 연결 칩은 **보는 사람이 볼 수 있는 프로젝트만** 그린다(`visible_projects(viewer)`로 거름). 못 보는 연결은 개수도 보이지 않는다(이름 노출 = 비공개 프로젝트 존재 노출).
- 프로젝트 P의 보드·달력에 연결 태스크가 나오려면 보는 사람이 그 태스크의 주 프로젝트를 볼 수 있어야 한다(`visible_tasks` 안에 있어야 함). 즉 비공개 주 프로젝트의 태스크를 공개 프로젝트에 연결해도 바깥 사람에겐 **없는 것처럼** 보인다. 넓히려면 주 프로젝트 공개 범위를 바꾸거나 태스크를 옮긴다 — 패널 도움말 한 줄로 알린다.
- API `list_tasks?project=P`: `visible_tasks(user)` ∩ (주=P ∪ 연결=P). 같은 규칙.
- 담당자 변경 규칙 `ASSIGNEE_CANT_SEE`(`tasks/services.py:108`)는 주 프로젝트 기준 그대로.

### 3.5 서비스(`tasks/services.py`)
```python
def tasks_of(project):            # 주 + 연결. 프로젝트 기준 화면이 전부 이것을 쓴다
    return Task.objects.filter(Q(project=project) | Q(project_links__project=project)).distinct()

@transaction.atomic
def link_project(task, project, *, actor, source="web", token=None) -> Task:
    # 같은 조직, 주≠연결, 보관 안 됨, 행위자가 양쪽 볼 수 있음, ai.update_task 정책. 중복은 무시(멱등).
    # _log(task, "projects", old_ids, new_ids, ...)
@transaction.atomic
def unlink_project(task, project, *, actor, source="web", token=None) -> Task
```
- `update_task(project=새 주)`(옮기기): 새 주가 연결 목록에 있으면 그 행을 지우고, 옛 주를 연결로 남기지 **않는다**(묵시적 연결은 놀람). 옛 주를 남기고 싶으면 사용자가 연결을 누른다.
- `duplicate_task`(`tasks/services.py:659-706`): 연결도 복사(`TaskProject.objects.bulk_create`).
- `delete_task`: CASCADE라 할 일 없음.
- `create_task(..., linked_project_ids=())`: 생성 직후 `link_project` 반복(API·MCP·가져오기용. 웹 폼엔 칸을 안 둔다 — 만든 뒤 패널에서 연결).

### 3.6 집계·화면(중복 집계 방지 원칙)
**조직 합계는 태스크당 한 번(주 프로젝트), 프로젝트별 수치는 연결 포함.** 프로젝트별 수치의 합이 조직 합계보다 클 수 있음을 화면 각주 한 줄로 밝힌다("연결 태스크는 여러 프로젝트에 셉니다").

| 화면·함수 | 지금 | 바꿀 것 |
|---|---|---|
| 프로젝트 보드·결과 선반·달력·템플릿 목록(`web/views/projects.py:278,346,353`) | `project.tasks` | `tasks_of(project)`. 연결 태스크 행에는 작은 글자 "↔ {주 프로젝트}"(`.muted.t13`, 색 아님) |
| `project_stats_bulk`(`projects/services.py:475-503`, 진척률·로드맵·레일) | `project__in` | 주 집계 + 연결 집계(`TaskProject` 기준) 두 쿼리를 더한다(조인 곱 방지). 로드맵 "완료 n/m"에 연결 포함 |
| 레일 미완료 수(`web/context.py:63`) | `Count("tasks")` | `Count("tasks", distinct)` + `Count("task_links", filter=…, distinct)` → 두 annotate 합. 쿼리 1개 유지 |
| 조직 현황 `org_status` `counts`(`reports/services.py:49-61`) | `_open_qs` 주 기준 | **그대로**(한 번만 센다) |
| `org_status.by_project`(`:63-82`) | `Count("tasks")` | 연결 포함(위와 같은 두 annotate). 열 이름 뒤 "(연결 포함)" |
| 주간 보고(`reports/services.py` 주간, Discord `weekly.py`) | 프로젝트별 항목 | 프로젝트별 목록에 연결 태스크 포함하되 "↔" 표시, 합계는 주 기준 |
| 내 태스크 `me_view` 프로젝트 묶기(`tasks/services.py:1065-1100`), 오늘, 검색, 포트폴리오 | 담당자 기준 | **변경 없음**(태스크당 한 번). 행에 연결 칩만 |
| GitHub 주간 지표(`github/metrics.py:6-13`) | 저장소 기준 | 변경 없음 |
| 조직 전체 태스크 `project` 필터 | 주 기준 | `tasks_of` |

N+1: 연결 칩을 그리는 모든 목록은 `prefetch_related("extra_projects")` 한 줄(`rows_for`, `web/views/common.py:289-294`에서 `prefetch_related_objects(tasks, "extra_projects")` 추가 — 이미 `checklist`를 같은 방식으로 붙인다). 가시성 거름은 메모리에서(보는 사람의 `visible_projects` id 집합을 요청당 한 번 구해 `row_ctx`에 넘김).

### 3.7 웹
- 패널 "프로젝트" 줄: 주 프로젝트 select(지금) 옆에 연결 칩들(`.tag` + × 버튼, `aria-label="연결 해제"`) + `[연결 추가]` select(볼 수 있는 프로젝트 − 주 − 이미 연결). HTMX로 패널 부분 갱신, `HX-Trigger`로 행 갱신(기존 `trigger`).
- 태스크 행(`_row.html`): 연결이 있으면 프로젝트 이름 뒤 `↔ n`(툴팁에 이름). 주 프로젝트가 아닌 화면에서 보면 "↔ 주 프로젝트명".
- 보드 드래그(상태 전이)는 그대로.
- 보드·선반 머리에 각주(연결 태스크가 1건 이상일 때만): "연결 태스크 n건 포함".

### 3.8 API·MCP·스킬·Discord
- 응답(`api/serialize.py` task_out): `project_id`(주) 유지 + `linked_projects: [{id, name}]`(보는 사람 기준 거름).
- `POST /api/tasks/{id}/projects {project_id}` · `DELETE /api/tasks/{id}/projects/{project_id}`. `TaskCreateIn.linked_project_ids: list[int] = []`. `GET /api/tasks?project=` 연결 포함(문서에 명시; 주만 보려면 `primary_only=1`).
- MCP: `link_task_project(task_id, project_id)`, `unlink_task_project`, `create_task(..., linked_project_ids)`. `get_task`에 `linked_projects`. `get_guide`: "관련이면 연결, 따로 하면 나누기".
- 스킬 `pm/SKILL.md`·`pm-new`(3단계 "여러 프로젝트에 걸친다" → 나누기/연결 중 고르게).
- Discord: 새 명령 없음. 태스크를 보여 주는 메시지(`/오늘`·알림)에 연결이 있으면 "↔ A, B" 한 줄.

### 3.9 테스트
- 모델·서비스: 연결·해제·멱등·주=연결 거절·다른 조직 거절·보관 프로젝트 거절·양쪽 가시성 없으면 거절·이력·옮기기 때 연결에서 제거·복제 때 복사.
- 가시성: 비공개 주 + 공개 연결 → 바깥 멤버에게 `list_tasks?project=공개`에 안 나옴, 패널 404; 주 공개 + 비공개 연결 → 바깥 멤버에게 칩 안 보임(개수도).
- 집계: `project_stats_bulk` 연결 포함, `org_status.counts` 불변, `by_project` 연결 포함, 레일 수, 로드맵 pct.
- 성능: 100건 목록 렌더 쿼리 수가 연결 유무와 무관(기존 `test_perf.py` 패턴).
- GitHub: 연결 저장소의 `TASK-n` 브랜치가 상태를 바꾸지 않음.

### 3.10 수용 기준
- Swagger 노출 문제(4개 서비스) 같은 태스크를 주 1 + 연결 3으로 만들면 네 프로젝트 보드에 모두 보이고, 조직 미완료 합계는 1만 는다.
- 비공개 프로젝트 이름이 연결을 통해 바깥 멤버에게 드러나는 경로가 없다(테스트로 고정).

---

## 4. 문서

### 4.1 범위와 v1/v2
기존 `ProjectDoc`(`projects/models.py:127-160`)을 **조직 단위 문서 `Doc`으로 일반화**한다. 회의록(`MeetingNote`)은 음성·초안·참여자가 있어 **합치지 않는다**(v2 후보). 개발일지 전용 기능은 **없음**(결정 5).

| v1(이번) | v2(안 함) |
|---|---|
| 공개 범위 3종(조직·프로젝트·팀, 기존 가시성 규칙과 동일), 하위 문서 트리, 템플릿, 이전 버전·되돌리기, 백링크(본문 검색), 태스크·프로젝트 연결, 통합 검색, `.md`·ZIP 가져오기/내보내기, 문서 첨부(이미지), 버전 잠금(기존) | 회의록을 문서로 통합, 댓글·멘션, 공개 공유 링크, 백링크 색인 표, 동시 편집 표시, 개발일지 |

### 4.2 모델 — `projects 0012_doc`(RenameModel + 필드 + DocRevision + 템플릿 시드)
```python
class Doc(models.Model):                      # ProjectDoc에서 이름 바꿈. related_name "docs"(Task.docs) 유지
    org = FK("orgs.Organization", CASCADE, related_name="docs")        # 새 열. 기존 행은 project.org로 채움(RunPython)
    project = FK(Project, CASCADE, null=True, blank=True, related_name="docs")   # 필수 → 선택
    team = FK("orgs.Team", SET_NULL, null=True, blank=True, related_name="docs")  # 새 열
    parent = FK("self", CASCADE, null=True, blank=True, related_name="children")  # 트리. 부모를 지우면 하위도 지움(확인 문구에 명시)
    position = PositiveIntegerField(default=0)
    is_template = BooleanField("템플릿", default=False)
    title, body_md, version, tasks, created_by, updated_by, updated_source, created_at, updated_at  # 그대로
    class Meta:
        ordering = ["position", "created_at", "id"]
        constraints = [CheckConstraint(condition=Q(project__isnull=True) | Q(team__isnull=True), name="doc_scope_one")]
        indexes = [Index(fields=["org", "parent"])]

class DocRevision(models.Model):
    """저장 이력. 자동 저장(0.8초)마다 쌓이지 않게 같은 사람·10분 안은 마지막 행을 덮어쓴다."""
    doc = FK(Doc, CASCADE, related_name="revisions")
    version = PositiveIntegerField()           # 저장 직후 Doc.version
    title = CharField(max_length=200); body_md = TextField()
    saved_by = FK(AUTH_USER_MODEL, SET_NULL, null=True, related_name="+")
    source = CharField(max_length=4, choices=Doc.SOURCES)
    saved_at = DateTimeField()
    class Meta:
        ordering = ["-version"]
        constraints = [UniqueConstraint(fields=["doc", "version"], name="docrevision_doc_version")]
```
- 공개 범위는 **뿌리 문서에만 뜻이 있고 하위는 뿌리를 따른다**(저장은 모든 행에 복사 — 조회를 평평하게 유지). `move_doc`이 하위 전체의 `org/project/team`을 다시 쓴다(트리는 작다; 깊이 ≤ 6).
- 보존 상한: 문서당 이전 버전 50개(넘으면 가장 오랜 것 삭제). 256KB × 50 = 최대 12.8MB/문서.
- 템플릿 시드(`projects/doc_templates.py` 상수 2개: **회의록**(회의 주제/내용/결정/할 일 — Notion 틀과 같은 뼈대), **설계 문서**(배경/결정/대안/영향)). 마이그레이션 `RunPython`으로 기존 조직에, `orgs.services.create_org`에서 새 조직에 만든다(`created_by=org.created_by`, 조직 범위, `is_template=True`). 개발일지 템플릿은 **넣지 않는다**(결정 5) — 사용자가 템플릿으로 만들면 된다.
- `Attachment.doc`는 §4.3(`tasks 0011`).

### 4.3 첨부 — `tasks 0011_attachment_doc`
```python
# Attachment
doc = FK("projects.Doc", CASCADE, null=True, blank=True, related_name="attachments")
# 제약 attachment_exactly_one_target → project·task·doc 중 정확히 하나
```
- `attachment_path`: `instance.doc.org_id` 분기. `target_project`는 doc이면 `doc.project`(None 가능).
- 다운로드 권한(`web/views/attachments.py`): doc이면 `can_view_doc(user, doc)`.
- 편집기 이미지: 문서 화면 "파일" 카드에 올린 이미지의 다운로드 URL을 `![]()`로 넣는 버튼 하나(`notes.js`의 기존 `![]()` 삽입 명령 재사용, `notes.js:99`).

### 4.4 서비스(`projects/docs.py` 확장. 함수 이름은 유지해 호출부 수정을 줄인다)
```python
def visible_docs(user, org=None)        # 관문. 회의록과 같은 식: (project None | project in visible_projects) & (team None | team in visible_teams)
def project_docs(project)                # 옛 visible_docs(project). 호출부 2곳 교체
def can_view_doc(user, doc) -> bool
def create_doc(*, org, actor, title="제목 없는 문서", body_md="", project=None, team=None, parent=None, template=None, source="web")
    # parent가 있으면 범위는 parent 것(인자 무시), template이 있으면 body_md = template.body_md. 템플릿은 볼 수 있는 것만
def update_doc(doc, field, value, *, actor, expected_version, source="web")   # 기존 + 저장 뒤 _record_revision
def _record_revision(doc, actor, source)   # 같은 사람·10분 안 → 마지막 행 덮어쓰기, 아니면 새 행. 50개 넘으면 삭제
def revert_doc(doc, revision, *, actor, expected_version, source="web")   # update_doc 두 번(title, body_md)이 아니라 한 트랜잭션에서 두 열을 바꾸고 version +1, 리비전 1개
def move_doc(doc, *, parent=None, position=None, project=None, team=None, actor)   # 순환·깊이 검사, 하위 범위 재기록, 다른 조직 거절
def set_template(doc, on, *, actor)
def delete_doc(doc, actor)              # 기존 규칙(작성자·관리자) + 하위 문서 수를 돌려줘 확인 문구에 씀
def backlinks(doc, viewer) -> {"docs": [...], "tasks": [...]}
    # docs: visible_docs(viewer).filter(body_md__icontains=f"/docs/{doc.pk}")  # ponytail: 본문 스캔, 문서 1,000개 넘으면 DocRef 표로
    # tasks: doc.tasks(M2M) ∩ visible_tasks(viewer)
def link_task(doc, task, actor, *, as_output=False)   # 제약 완화: 같은 조직이면 됨(프로젝트 문서는 주·연결 프로젝트 중 하나와 같을 때만)
def upload_doc(*, org, actor, filename, raw, project=None, team=None, parent=None)   # 기존 + 범위
def export_md(doc) -> (filename, bytes)
def export_zip(org, viewer, *, root=None) -> bytes      # 트리 = 폴더. 제목 충돌 " (2)". 첨부는 넣지 않음(v1)
def import_zip(*, org, actor, raw, project=None, team=None, parent=None) -> Report   # §1 파서(imports/parse.py)를 재사용
def search_docs(user, q, org=None)       # 제목·본문 icontains, 템플릿 제외, 50건
```
- 편집 권한: 범위를 볼 수 있는 조직 멤버(지금과 같음 `projects/docs.py:39-41`). 템플릿 수정도 같음.
- `notes.services.create_note(..., template=None)`: 템플릿 본문 복사(새 회의록 대화상자에 "템플릿" select 하나). `MeetingNote` 열 변경 없음.
- `ChangeLog`는 문서에 쓰지 않는다(이전 버전 표가 이력이다). 삭제만 `ChangeLog(target_type="org", field="doc_deleted", note=제목)` 한 줄 — 되돌릴 수 없는 행동의 흔적.

### 4.5 웹(`DESIGN.md` 준수)
- 경로: `/orgs/<id>/docs`(조직 문서 홈, 조직 탭 "문서" — 회의록 탭 옆), `/docs/<id>`(정식 주소 → 홈으로 리다이렉트 + `?doc=`), 프로젝트 "문서" 탭(`/projects/<id>/docs`)은 **같은 화면을 프로젝트 범위로 거른 것**. 팀 상세에 "팀 문서" 카드.
- 배치: 기존 `notes-columns`(목록 카드 + 편집기 카드, `templates/projects/docs.html:4`)를 유지하되 목록 카드가 **트리**가 된다: `ul.doc-tree` 안 `details`(현재 문서의 조상은 열림), 들여쓰기 12px, 행마다 제목 + 범위 표식(조직은 없음 / 프로젝트·팀은 `.badge` 글자). 모바일(≤850px)은 회의록과 같이 목록/편집 전환.
- 머리: 범위 칩(`.chips .chip` — 전체·조직·프로젝트별·팀별 필터), 검색 입력(`.input`, 12px 모서리), 주 버튼 **"새 문서"** 하나(`.primary`), 보조 `[Markdown 올리기]`·`[ZIP 가져오기]`·`[내보내기]`(`.btn.sm`).
- 새 문서 `dialog`: 제목 · 위치(상위 문서 select, 기본 = 지금 보는 문서) · 공개 범위 라디오 카드(조직 / 프로젝트 / 팀 — 상위가 있으면 비활성 + "상위 문서의 공개 범위를 따릅니다") · 템플릿 select(없음 / 템플릿들).
- 편집기 카드: 상단 경로(breadcrumb, 상위 문서 링크) · 제목 입력 · 메타 줄(만든 사람·마지막 수정·`v`) · 본문(기존 `#doc` 편집기·자동 저장·`X-Note-Version` 충돌 띠 그대로) · 하단 `details` 3개: **이전 버전**(표: v / 저장한 사람 / 시각 / [이 버전으로 되돌리기] `.btn.sm`, 미리보기 토글) · **연결**(태스크 칩 + 추가, 백링크 목록) · **파일**(첨부 카드 재사용, 이미지면 [본문에 넣기]).
- 하위 문서가 있는 문서를 지울 때 확인 문구: "하위 문서 n개가 함께 삭제됩니다." 되돌릴 수 없음 → `.danger`.
- 빈 상태: `.empty.compact` "첫 문서를 만들어 팀의 규칙·가이드·설계를 모아 두세요."
- 검색 화면(`search.html`): 결과를 태스크 / 문서 / 회의록 세 묶음(`.group-stack`), 문서는 제목 + 본문 일치 줄 1개(120자).
- 격식체. 감탄부호 없음. 아이콘·이모지 없음(`DESIGN.md` §7).

### 4.6 API·MCP·스킬
- 새 라우터 `/api/docs`(옛 `/api/project-docs`는 **얇은 별칭으로 유지**, 응답에 `org_id·project_id·team_id·parent_id` 추가):
  `GET /orgs/{id}/docs?project=&team=&q=&tree=1` · `POST /orgs/{id}/docs` · `GET/PATCH/DELETE /docs/{id}` · `GET /docs/{id}/revisions` · `POST /docs/{id}/revert {revision_id, version}` · `POST /docs/{id}/move {parent_id, position, project_id, team_id}` · `GET /docs/{id}/backlinks` · `GET /docs/{id}/export.md` · `GET /orgs/{id}/docs/export.zip` · `POST /orgs/{id}/docs/import`(multipart ZIP/md).
- MCP(`server.py:827-877` 문서 도구 4개 확장): `list_docs(org_id, project_id=None, team_id=None, q="")`, `create_doc(org_id, title, body_md="", project_id=None, team_id=None, parent_id=None, template_id=None)`, `update_doc`, `get_doc`, 새 `list_doc_revisions`, `revert_doc`, `move_doc`. 삭제·가져오기는 MCP에 두지 않는다(AI 정책 `ai.delete` 취지).
- 스킬 `pm/SKILL.md`: "문서" 절(조직 문서 찾기 → 읽기 → 설계 문서 템플릿으로 만들기). `pm-decide`·`pm-pr`가 결정 기록과 함께 설계 문서 링크를 찾도록 한 줄.
- Discord: 변경 없음(회의록 흐름은 IMPL-PLAN-9 그대로).

### 4.7 테스트
- 가시성: 조직 문서는 멤버 전원, 프로젝트 문서는 `visible_projects`, 팀 문서는 `visible_teams`; 바깥 멤버는 API 404·목록 제외·백링크 제외·검색 제외.
- 트리: 하위 범위 상속, 이동 때 재기록, 순환 거절, 깊이 7 거절, 부모 삭제 → 하위 삭제.
- 이전 버전: 자동 저장 연속 3번(같은 사람, 10분 안) → 리비전 1개, 다른 사람 → 새 행, 51번째 → 가장 오랜 것 삭제, 되돌리기 → version +1 + 리비전 1개, 버전 충돌 409.
- 템플릿: 시드 2개, 새 문서·새 회의록에 본문 복사, 템플릿은 검색·트리에서 분리 표시.
- 가져오기·내보내기: 폴더 → 트리 → ZIP → 다시 가져오면 같은 트리, 제목 충돌 " (2)".
- 첨부: 문서 첨부 다운로드 권한, 조직 상한 합산에 포함.
- 기존 `ProjectDoc` 테스트 전부 통과(이름만 바뀜), `/api/project-docs` 별칭 응답 호환.
- 검색: 세 묶음, 템플릿 제외.

### 4.8 수용 기준
- Notion 위키 8개(필독 4·온보딩 2·정보처 메모·신기능 투표)를 조직 문서 트리로 가져와 **링크로 남길 이유가 없어진다**(O 분석 §4.1의 "부분 이전" 조건 해소).
- 문서 저장 10회 뒤 이전 버전 표가 10줄이 아니라 사람·시간 묶음으로 보이고, 되돌리기가 한 번에 된다.

---

## 5. 사용자 노출 용어표(명령·화면·API 설명·문서·스킬 모두 이 표만 쓴다)

| 표준 용어 | 뜻 | 쓰지 않는 말 |
|---|---|---|
| **문서** | 조직·프로젝트·팀 범위의 마크다운 글 하나(옛 "프로젝트 문서" 포함) | 위키, 페이지, 노트, 위키 페이지, 포스트 |
| **하위 문서 / 상위 문서** | 트리의 자식/부모 | 서브페이지, 자식 문서, 섹션 |
| **공개 범위**(조직 전체 / 프로젝트 / 팀) | 문서·프로젝트가 보이는 범위(IMPL-PLAN-7과 같은 말) | 권한, 스코프, 가시성(코드 용어), 비공개 설정 |
| **템플릿** | 새 문서·회의록·태스크의 본문 틀(태스크 템플릿과 같은 말) | 틀, 양식, 서식, 보일러플레이트 |
| **이전 버전 / 되돌리기** | 저장 이력과 그 시점으로 복원 | 리비전, 히스토리, 롤백, 복구 |
| **연결**(문서↔태스크, 태스크↔프로젝트) / **연결 해제** | 참조 관계 만들기·끊기 | 링크(외부 URL "링크"와 구분), 첨부, 매핑, 관계 |
| **백링크** | 이 문서를 가리키는 문서·태스크 목록 | 역링크, 참조됨, 인바운드 |
| **회의록** | IMPL-PLAN-9 용어표 그대로 | 미팅 노트, 노트 |
| **가져오기 / 내보내기** | 여러 항목을 열 지정·미리보기를 거쳐 들여오기 / ZIP·md로 받기 | 임포트, 익스포트, 마이그레이션, 이전(문서 제목에서만), 동기화 |
| **올리기** | 파일 하나를 그대로 등록(기존 "Markdown 문서 올리기") | 업로드(버튼 문구에서), 첨부(파일 카드에서만) |
| **미리보기** | 가져오기 실행 전 결과 확인(쓰지 않음) | 드라이런, 시뮬레이션, 검증 실행 |
| **열 지정 / 값 대응** | 어느 열이 제목·상태인지 / 상태값·중요도값을 유달리 값으로 | 매핑, 필드 매핑, 컬럼 매핑 |
| **사람 매칭** | 원본의 사람 이름 → 조직 멤버 | 사용자 매핑, 어사이니 매핑 |
| **원본 링크** | 가져온 항목에 붙는 Notion 주소 | 소스, 출처 URL |
| **담당자**(한 명) | 태스크를 맡은 사람 | 담당자들, 공동 담당, 어사이니, 책임자 |
| **사람별로 나누기 / 사람별 태스크** | 담당자마다 태스크를 만들어 계열로 묶는 동작/결과 | 분배, 할당 나누기, 서브태스크, 하위 태스크(트리가 아님) |
| **계열 / 원본** | 나눈 태스크들의 묶음 / 그 뿌리(기존 용어, `_series.html:1`) | 부모 태스크, 상위 태스크, 에픽 |
| **주 프로젝트** | 태스크 번호·규칙·알림·저장소를 소유하는 프로젝트(`Task.project`) | 소속 프로젝트, 대표 프로젝트, 메인 |
| **연결 프로젝트** | 태스크가 추가로 걸린 프로젝트 | 관련 프로젝트, 부 프로젝트, 서브 프로젝트, 다중 프로젝트 |
| **옮기기** | 주 프로젝트 바꾸기(기존 동작) | 이동, 이관, 재배정 |
| **첨부 / 파일** | 문서·태스크·프로젝트에 붙은 파일(기존 용어) | 어태치먼트, 미디어 |

코드 식별자는 영문 그대로(`Doc`, `DocRevision`, `TaskProject`, `ImportRecord`, `split_by_assignees`). 사용자에게 보이는 글에만 적용.

---

## 6. 사용자에게 물을 것(4개)

| # | 질문 | 선택지 | 추천 |
|---|---|---|---|
| 1 | Notion을 어떻게 들여올까 | (a) 공식 API + 토큰(링크 입력, 페이지마다 integration 공유 필요, 규모 L) (b) **내보내기 ZIP·CSV·md 올리기 + 열 지정**(규모 M, 토큰 없음) (c) 둘 다 | **(b)** — 일회성(결정 6)에선 API의 이점이 없고 변환 품질은 Notion 내보내기가 낫다. (a)는 확장 지점만 남김(§1.1) |
| 2 | 연결 프로젝트 저장소의 `TASK-n` 자동 규칙 | (a) **주 프로젝트 저장소만**(연결 저장소 PR은 번호를 적어도 상태 안 바뀜) (b) 연결 저장소도(단, GitHub 연결 정보는 첫 저장소에 고정) | **(a)** v1 — `TaskGitLink`가 태스크당 하나라 (b)는 연결이 튄다. 저장소마다 따로 하는 일은 "사람별/저장소별 나누기"가 맞다 |
| 3 | 비공개 주 프로젝트의 태스크를 공개 프로젝트에 연결했을 때 | (a) **주 프로젝트를 못 보면 안 보임**(연결은 가시성을 안 넓힘) (b) 연결 프로젝트를 볼 수 있으면 보임(비공개 프로젝트 이름·태스크가 새어 나감) | **(a)** — 누출 없음, `visible_tasks` 불변 |
| 4 | 문서 범위 | (a) **`ProjectDoc`을 조직 문서로 확장, 회의록은 별도 유지**(v1 §4) (b) 회의록까지 문서로 통합(음성·초안·참여자 이관, 규모 +M) | **(a)** — IMPL-PLAN-9 흐름을 건드리지 않는다. 통합은 v2 |

묻지 않고 추천대로 확정: 가져오기는 조직 관리자·웹 세션만 · 파일 임시 저장 없음(재업로드) · 완료일시 없는 완료 태스크는 생성일시 + 설명 줄 · 새 앱 `imports` · 담당자 안내는 막지 않는 `.notice` · 나누기는 `duplicate_task` 재사용(계열) · 연결 권한은 양쪽을 볼 수 있는 멤버(설정 없음) · 집계 원칙(조직 합계 1회, 프로젝트별 연결 포함) · 문서 공개 범위는 뿌리 상속 · 이전 버전 10분 묶음·50개 · 백링크는 본문 스캔 · 템플릿 시드 2개(개발일지 없음) · Discord 새 명령 없음 · Notion API 토큰 Spec은 지금 안 만듦.

---

## 7. 구현 단계 표

| 단계 | 내용 | 담당 | 선후 | 마이그레이션 | 주로 고치는 파일 | 충돌 주의 |
|---|---|---|---|---|---|---|
| **P1** 다중 프로젝트 모델·서비스·API·MCP | §3.2·3.3·3.5·3.8(응답·끝점·MCP·스킬 문구) | Opus | 바로 시작 | `tasks 0010` | `tasks/models.py`, `tasks/services.py`(tasks_of·link·unlink·update_task·duplicate_task·create_task), `api/routers/tasks.py`, `api/schemas.py`, `api/serialize.py`, `mcp_server/mcp_server/server.py`, `mcp_server/skill/SKILL.md`, `skills/pm/SKILL.md`, `skills/pm-new/SKILL.md` | `tasks/models.py`는 D2(0011)도 만진다 → P1 먼저. IMPL-PLAN-10이 `tasks`에 마이그레이션을 내면 번호 조정 |
| **D1** 문서 모델·서비스·API·MCP | §4.2·4.4·4.6(웹 제외), `notes.services.create_note(template=)`, `orgs.services.create_org` 시드 | Opus | 바로 시작, P1과 병렬 | `projects 0012` | `projects/models.py`, `projects/docs.py`, `projects/doc_templates.py`(새), `projects/migrations/0012`, `api/routers/docs.py`, `api/schemas.py`(Doc* 끝에 덧붙임), `api/api.py`(라우터 한 줄), `notes/services.py`, `orgs/services.py`(create_org 끝), `mcp_server/mcp_server/server.py`(문서 도구 블록만) | `api/schemas.py`·`server.py`를 P1도 만진다 → 서로 다른 블록, 순차 병합(P1 → D1) |
| **S1** 담당자 1명 안내·사람별로 나누기 | §2 전부(웹 대화상자·API·MCP·스킬·Discord 문구) | Sonnet | P1 병합 뒤(연결 복사 때문) | 없음 | `tasks/split.py`(새), `web/views/split.py`(새), `web/urls.py`(끝), `templates/tasks/_split.html`(새), `templates/tasks/_panel.html`(버튼 한 줄), `api/routers/tasks.py`(끝에 `/split`·`assignee_ids` 거절), `api/schemas.py`, `mcp_server/.../server.py`(`split_task`), `skills/pm/SKILL.md`, `skills/pm-split/SKILL.md`, `discord_service/discord_service/slash.py`(`_create` 응답 한 줄) | `_panel.html`·`routers/tasks.py`를 P2도 만진다 → **S1 먼저 병합** |
| **P2** 다중 프로젝트 화면·집계 | §3.6·3.7, Discord "↔" 줄 | Opus(P1과 같은 담당) | P1·S1 뒤 | 없음 | `web/views/{projects,common,tasks,roadmap,me}.py`, `web/context.py`, `templates/tasks/{_panel,_row}.html`, `templates/projects/{_board,calendar,_shelf,detail}.html`, `projects/services.py`(stats_bulk), `reports/services.py`, `discord_service/.../{weekly,messages}.py`, `web/test_perf.py` | `reports/services.py`·`projects/services.py`는 D2가 안 만짐. `base.html`은 안 만짐 |
| **D2** 문서 화면·검색·첨부·회의록 템플릿 select | §4.3·4.5, 검색 세 묶음, 조직 탭·주 메뉴 | Opus | D1·P1 뒤(0011 번호) | `tasks 0011` | `tasks/models.py`(Attachment.doc), `tasks/attachments.py`, `web/views/{docs,search,notes,attachments,teams}.py`, `web/urls.py`(끝), `templates/docs/{index,_tree,_editor,_new_dialog,_revisions}.html`(새, `projects/docs.html`은 이것을 include), `templates/search.html`, `templates/notes/list.html`, `templates/orgs/_tabs.html`, `templates/orgs/team_detail.html`, `templates/base.html`(메뉴 한 줄 — IMPL-PLAN-10 병합 뒤), `web/static/app.css`(`.doc-tree`), `web/static/notes.js`(이미지 삽입 버튼) | `base.html`·`orgs/_tabs.html`은 IMPL-PLAN-10도 만질 수 있음 → 그들 병합 뒤 한 줄 덧붙임 |
| **N1** 가져오기 파서·서비스·API | §1.2~1.6·1.8 | Opus | 파서는 바로, 서비스는 P1·D1 뒤 | `imports 0001` | `imports/{__init__,apps,models,parse,services,tests}.py`(새), `imports/migrations/0001`, `config/settings.py`(`INSTALLED_APPS` 끝 한 줄), `api/routers/imports.py`(새), `api/api.py`(한 줄) | `config/settings.py`는 IMPL-PLAN-10도 만질 수 있음 → 끝에 덧붙임 |
| **N2** 가져오기 화면·보고 | §1.3·1.7, 조직 설정에 "가져오기" 링크, `imported=<batch>` 칩 | Sonnet | N1·D2·S1 뒤 | 없음 | `web/views/imports.py`(새), `web/urls.py`(끝), `templates/orgs/import/{index,_mapping,_preview,_report}.html`(새), `templates/orgs/settings.html`(링크 한 줄), `web/views/me.py`(칩), `projects/docs.py`(`import_zip`이 `imports/parse` 사용) | `me.py`를 P2가 만짐 → P2 뒤 |
| **F** 마무리 | `docs/SPEC-FUNCTIONAL.md`(2·4·7장 갱신, "프로젝트는 정확히 하나" 문장 수정), `skills/README.md`, `mcp_server/skill/SKILL.md` 조합표, `docs/GUIDE-00-rules.md` 6절 구조에 `imports/` 추가, 전체 테스트 재실행 | Sonnet | 전부 병합 뒤 | 없음 | 문서만 | 없음 |

병렬 묶음: **{P1, D1, N1(파서만)} → {S1, D2} → {P2, N1(서비스)} → N2 → F.**
검토(Sol, GPT 사용량 확인 뒤): §3.4 가시성(P1·P2)과 §1.6 상한·권한(N1) 두 번으로 제한. 승인(Fable): 단계 표와 질문 4개.

마이그레이션 번호 고정: `tasks 0010`(P1) · `projects 0012`(D1) · `tasks 0011`(D2) · `imports 0001`(N1). 기존 최신: `tasks 0009_task_status_since`, `projects 0011_milestone_gh_number`.

---

## 8. 위험

| 위험 | 대응 |
|---|---|
| Notion 내보내기 형식(열 이름·날짜 형식·`_all.csv`·중첩 ZIP)이 전제와 다름 | 범용 열 지정이 흡수한다. 파서는 "모르는 것은 보존"(설명 줄)이 원칙. N1 첫 작업이 **실제 내보내기 ZIP 1개로 파서 픽스처 만들기** |
| 가져온 과거 완료 태스크가 통계에 섞임 | 원본 시각 보존 + `imported` 이력. 완료일시 미상은 생성일시(새 날짜를 만들지 않음) |
| 연결 태스크 집계가 조직 합계와 안 맞아 보임 | 원칙(§3.6)과 각주 한 줄. 테스트로 고정 |
| `ProjectDoc` 이름 변경이 넓게 퍼짐(`Task.docs` M2M, `/api/project-docs`, MCP 도구) | RenameModel은 표 이름만 바꾸고 related_name은 유지. API 별칭 유지. MCP 도구 이름 유지 |
| 이전 버전 저장으로 DB가 커짐 | 10분 묶음·50개 상한. 256KB 상한은 그대로 |
| 백링크 본문 스캔 | 문서 수백 건 규모에서 충분. `# ponytail` 주석과 v2 표 |
| `tasks` 마이그레이션 번호가 IMPL-PLAN-10과 겹침 | 병합 시점에 §0.2 표 대조, 번호 당김 |
| 단계마다 ZIP 재업로드(≤50MB × 6) | 운영 대역폭에서 문제없음. 커지면 임시 저장으로(주석) |

## 9. 확인 불가
- Notion "Markdown & CSV" 내보내기의 정확한 파일 규칙(`_all.csv` 유무, 날짜·사람·관계 셀의 문자열 형식, 중첩 ZIP 조건) — 읽기 전용 지시로 실행하지 않음(`O-notion-migration.md` §5). N1 착수 때 실제 파일로 확정.
- IMPL-PLAN-10의 실제 소유 파일·마이그레이션(아직 파일 없음) — §0.2는 추정.
- Postgres에서 `body_md__icontains` 백링크 스캔과 `tasks_of`의 `distinct` 성능 — SQLite로만 테스트. 수십~수백 건 규모라 문제없을 것으로 보나 실측 없음.
- 이 팀의 실제 다중 담당·다중 프로젝트 행 수(최소 3·2건만 확인) — 가져오기 미리보기가 알려 준다.
