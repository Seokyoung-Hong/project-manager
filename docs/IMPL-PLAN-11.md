# P — 라운드 11 설계(개정 2): Notion 가져오기 · 담당자 1명 안내 · 태스크 다중 프로젝트 연결 · 문서·회의록 통합 (Fable, 2026-10-07)

기준: Ochestration `f917a8e`(운영 콘솔 O0~O4 병합됨). 근거 표기는 `파일:줄`. 코드·git은 손대지 않았다(읽기만).
개정 2: 문서 끝 **"사용자 결정 결과 (2026-10-07)"** 4건을 본문에 반영했다(Notion API 경로 추가, 다중 연결의 GitHub 수동 선택, 열람 범위 = 주 ∪ 연결(동의 후), 회의록 편집 통합).

---

## 0. 전제

### 0.1 사용자 결정(2026-10-07, 확정 — 이 설계보다 우선)
1. Notion은 **파일 올리기(ZIP·CSV·md)와 공식 API + 링크, 둘 다** v1. 일회성, 동기화 없음, 토큰은 Fernet 암호화·마스킹. 두 경로가 같은 열 지정·미리보기·중복 방지 파이프라인을 쓴다(§1).
2. **태스크 담당자는 한 명**. 여러 명처럼 보이면 역할을 쪼개도록 유도(§2).
3. **태스크 하나를 여러 프로젝트에 연결**. 연결 프로젝트가 있으면 **GitHub 자동 연동은 끄고 사용자가 연동 프로젝트를 직접 고른다**(§3.3). **열람 범위 = 주 프로젝트 ∪ 연결 프로젝트**, 열람자가 늘어나는 연결은 경고·확인을 거친다. MCP·스킬은 명시 허용 인자 없이는 거부(§3.4).
4. **문서 기능 확장**과 **회의록 편집 통합**(같은 편집기·올리기·이전 버전·백링크·첨부). 회의록 고유 규칙(음성 회의·진행자·초안/확정·참여자, IMPL-PLAN-9)은 유지(§4).
5. 개발일지는 거의 안 쓴다 → 전용 기능 없음. 가져올 때 진행 메모 날짜 줄로 보존(§1.6).
6. Notion DB 동기화 없음 → 일회성 가져오기, 열(속성)은 사람이 고르는 범용 방식(§1.4).

### 0.2 운영 콘솔(IMPL-PLAN-10) 병합 뒤 실제 충돌 지점
O0~O4가 병합됐다(`core/ops/`, `ops 0001_initial`, `web/views/ops*.py`, `templates/ops/*`, `web/urls.py` ops 블록 `:204-`, `config/settings.py` `INSTALLED_APPS "ops"` `:42`, `base.html` 블록 2개, `settings/_tabs.html`). 남은 O5는 검토뿐이라 **동시 수정 에이전트는 없다**. 이 라운드의 모든 단계는 `f917a8e` 위에서 시작한다.

| 파일 | 운영 콘솔이 바꾼 것 | 이 설계가 하는 것 |
|---|---|---|
| `web/urls.py` | ops 블록 추가 | 각 단계가 **자기 블록을 파일 끝에** 덧붙인다(ops 블록을 건드리지 않음) |
| `config/settings.py` | `INSTALLED_APPS "ops"`, `DJANGO_ADMIN_ENABLED` 등 | `"imports"`를 `"ops"` 다음 줄에(N1) |
| `templates/base.html` | 블록 2개 | 주 메뉴 "문서" 한 줄(D2) |
| `templates/settings/_tabs.html` | 운영 링크 제거 | 손대지 않음(가져오기 입구는 조직 설정 화면·조직 탭) |
| `tasks/migrations` | 없음(`ops`는 자기 앱) | `0010`(P1a)·`0011`(D2) 번호 그대로 |

### 0.3 공통 원칙(이 라운드)
- 새 규칙은 전부 `services`(같은 앱의 서비스 모듈)에 두고 웹·API·MCP·Discord는 부르기만 한다(`docs/GUIDE-00-rules.md:72-82`).
- 새 의존성 없음. ZIP·CSV·마크다운·Notion API는 표준 라이브러리(`zipfile`·`csv`·`re`·`json`·`urllib`)로만(`docs/GUIDE-00-rules.md:54-60`; `urllib` 사용 선례 `projects/services.py:748-766`). 마크다운 렌더는 지금처럼 클라이언트 `notes.js`.
- 메모리 512MB·gunicorn `--timeout 90`(`core/entrypoint.sh:10`): 가져오기는 요청 하나가 15초 안에 끝나는 조각으로 나누고(§1.5), 큐·워커는 두지 않는다.
- 가시성 관문은 세 개뿐: `visible_projects`(`projects/services.py:73-89`) → **`visible_tasks`(이번에 "주 ∪ 연결"로 확장, §3.4)** → `visible_docs`(문서·회의록 공통, §4.4). 새 개념도 이 관문을 지난다.
- 마이그레이션 번호 고정(§7): `tasks 0010`(P1a) · `projects 0012`(D1) · `notes 0004`(D3) · `tasks 0011`(D2) · `imports 0001`(N1). `orgs`·`accounts`·`ops`·`github`는 바꾸지 않는다.

---

## 1. 가져오기(Notion 파일·Notion 링크·CSV·Markdown)

### 1.1 두 입구, 한 파이프라인
```
입구 A  파일 올리기: Notion 내보내기 ZIP / CSV 여러 개 / .md 여러 개      → imports/parse.py
입구 B  Notion 링크: 조직 통합 토큰 + 페이지·DB 링크(하위 페이지 포함)     → imports/notion.py
                                      ↓ 같은 중간 형식 Bundle (§1.3)
               열 지정 → 값 대응 → 사람 매칭 → 미리보기 → 실행 → 보고   → imports/services.py
                                      ↓
               ImportRecord(org, source_ref)로 중복 방지 — 두 입구가 같은 "notion:<hex>" 키를 쓴다
```
입구 A가 기본이고(토큰 없음, 변환은 Notion 몫), 입구 B는 "페이지를 integration에 공유해 둔" 조직이 링크만으로 들여오는 길이다. 둘 다 **일회성**이다: 같은 페이지를 다시 들여오면 건너뛴다(갱신·동기화 없음).

### 1.2 Notion 통합 토큰(입구 B)
- `orgs/settings.py` `org` 그룹 끝: `Spec("notion.token", "secret", SECRET_UNSET, "org", False, "org", "Notion 통합 토큰", "Notion 내부 통합(integration)의 토큰입니다. 암호화해 저장하며 화면에는 설정 여부만 보입니다. 가져올 페이지를 통합에 공유해 두어야 합니다.")`. 저장·마스킹·"안 보내면 유지"는 기존 비밀값 규칙 그대로(`orgs/settings.py:56-58`, `merge_secrets` `:1012-1040`, `secret_value` `:1042-1047`).
- `secret_value()` 주석 "봇 API에서만 부른다"를 "봇 API와 `imports/notion.py`(조직 관리자 세션)에서만"으로 넓힌다. 평문은 요청 안에서만 쓰고 로그·`ImportJob`·보고 어디에도 남기지 않는다.
- 토큰이 없으면 입구 B 폼에 `.notice` "조직 설정 → 조직 운영에서 Notion 통합 토큰을 먼저 등록해 주세요."

### 1.3 중간 형식과 Notion 읽기(`imports/notion.py`)
```python
Bundle(csvs=[CsvTable(name, source_ref, columns, rows=[{col: str}], row_pages={row_ref: md})],
       pages=[Page(title, source_ref, body_md, path=("필독", "Ground Rule"), images=[ImageRef])])
```
- 링크 → id: URL 경로 끝 32자리 hex(하이픈 제거). `GET /v1/pages/{id}`가 404면 `GET /v1/databases/{id}`를 시도. 둘 다 실패 → "통합에 공유되지 않았거나 없는 페이지입니다."
- 페이지: `GET /v1/blocks/{id}/children`(100개씩, `has_children`이면 재귀). `child_page`는 하위 `Page`, `child_database`는 `CsvTable`(`POST /v1/databases/{id}/query` 100개씩, 속성 → 문자열).
- 블록 → 마크다운 표(변환기는 이 표 밖을 만들지 않는다): paragraph · heading_1~3 · bulleted/numbered_list · to_do(`- [ ]`) · toggle(제목 줄 + 들여쓴 하위) · quote · callout(인용) · code(펜스 + 언어) · divider · table(마크다운 표) · image/file/pdf(§1.6 첨부 또는 링크) · bookmark/embed/link_preview(링크) · equation(`$…$`) · synced_block/column_list/column(하위만) · 그 밖 → `[지원하지 않는 블록: type]`. 리치 텍스트: 굵게·기울임·코드·취소선·링크·멘션(페이지 → 2차 패스에서 `/docs/<id>`, 사람 → 이름, 날짜 → 문자열).
- 속성 → 문자열(CSV와 같은 꼴이 되도록): title/rich_text 그대로, select/status 이름, multi_select·people·files `", "` 연결, date `start[ → end]`, number/checkbox/url/email 문자열, relation은 제목(페이지 조회 1회·캐시, 예산 초과 시 id), created_time/last_edited_time ISO, formula/rollup 값 문자열.
- 사람 매칭용: `GET /v1/users`(통합에 "사용자 정보" 권한이 있을 때만 이메일이 온다 — 없으면 이름만, §6 질문 2).
- 요청 규칙: `Notion-Version: 2022-06-28`, 초당 3회 제한 → 호출 간 0.35초, 429는 `Retry-After` 한 번 대기 후 재시도, 5xx는 1회 재시도. 호스트는 `api.notion.com` 고정(`_check_public` 불필요).
- 예산(작업당): 페이지 500 · DB 행 5,000 · 블록 20,000 · 이미지 합계 30MB · 요청 3,000회. 넘으면 그 지점에서 멈추고 보고에 "예산 초과 — 하위 페이지를 나눠 다시 들여오세요".

### 1.4 열 지정·값 대응·사람 매칭(두 입구 공통, 결정 6)
열 지정 표(태스크 대상. 프로젝트·회의록·문서도 같은 꼴):

| 유달리 항목 | 필수 | 자동 추천(이름이 같으면 미리 고름) | 비고 |
|---|---|---|---|
| 제목 | ○ | 업무 제목 / Name / 첫 열 | 200자 자름 |
| 상태 | | 상태 / Status | 고유값 대응. 미대응 → `todo` + 경고 |
| 담당자 | | 담당자 / Assignee | 여러 명이면 **첫 매칭 = 담당자**, 나머지는 설명 첫 줄 "함께: A, B" + §2 나누기 후보. 못 찾으면 "기본 담당자"(기본 = 나) |
| 프로젝트 | | 소속 프로젝트 / Project | 여러 개면 첫 = 주, 나머지 = 연결(§3). 없으면 "기본 프로젝트"(기존 선택 또는 새로 만들기 "가져온 항목") |
| 목표 기한 | | 목표 기한 / Due | 미완료인데 없으면 `no_due_reason="가져오기(기한 없음)"` |
| 완료일시 | | 완료일시 / Completed | 완료인데 없으면 **생성일시**로 채우고 설명에 "완료일시 미상"(제약 `task_done_requires_completed_at`. 새 날짜를 지어내지 않는다) |
| 생성일시 | | 생성 일시 / Created | 없으면 가져온 시각 |
| 중요도 | | 중요도 / Priority | 높음 9 · 중간 5 · 낮음 2, 숫자는 1~10 자름 |
| 설명 | | 상세 설명 / Description | 행 페이지 본문이 있으면 뒤에 붙임 |
| 원본 링크 | 자동 | — | `Link(kind="other", title="Notion 원본", url=https://www.notion.so/<hex>)` |

안 고른 열은 `속성명: 값` 줄로 설명 끝에 보존한다. 사람 매칭 순서: ① 이메일 ② `display_name`(공백·대소문자 무시) ③ Team Members 표(사람 매칭표 대상)의 "이름 → 이메일" 간접 ④ 4단계에서 선택. 사람을 **만들지는 않는다**.

### 1.5 작업 모델과 화면 흐름(조직 관리자만, `/orgs/<id>/import`)
입구 B는 요청 하나로 끝나지 않는다(500페이지 ≈ 1,000회 ≈ 5분 > 90초). 그래서 **작업 행 하나**에 진행 상태를 두고 브라우저가 2초마다 "계속"을 누른다(워커 없음).

```python
# imports/models.py — 0001_initial
class ImportJob(models.Model):
    """가져오기 한 번. 입구 A는 올린 ZIP을, 입구 B는 받아 온 내용을 bundle에 둔다. 24시간 뒤 지운다."""
    KINDS = [("upload", "파일"), ("notion", "Notion 링크")]
    STATUSES = [("fetching", "가져오는 중"), ("ready", "열 지정"), ("done", "완료"), ("failed", "실패")]
    org = FK("orgs.Organization", CASCADE, related_name="+"); created_by = FK(AUTH_USER_MODEL, PROTECT, related_name="+")
    kind = CharField(max_length=6, choices=KINDS); status = CharField(max_length=8, choices=STATUSES, default="fetching")
    source_label = CharField(max_length=300)          # 파일 이름 또는 링크(토큰 없음)
    file = FileField(upload_to="imports/", max_length=200, blank=True)   # 입구 A의 ZIP(이미지 재독용). 완료·만료 시 삭제
    bundle = JSONField(default=dict)                  # Bundle(JSON ≤ 20MB). 이미지는 참조만
    cursor = JSONField(default=dict)                  # 입구 B 진행: {"queue": [...], "done": n, "requests": n}
    mapping = JSONField(default=dict); report = JSONField(default=dict); error = CharField(max_length=300, blank=True)
    created_at = DateTimeField(auto_now_add=True); finished_at = DateTimeField(null=True, blank=True)

class ImportRecord(models.Model):
    """가져온 원본 하나 → 유달리 객체 하나. 같은 원본은 건너뛴다(동기화 없음)."""
    org = FK(...); job = FK(ImportJob, SET_NULL, null=True, related_name="records")
    source_ref = CharField(max_length=80)             # "notion:<hex>" | "csv:<sha1>" | "md:<sha1>"
    target_type = CharField(max_length=10)            # task | project | doc  (회의록은 doc, §4)
    target_id = PositiveBigIntegerField(); created_at = DateTimeField(auto_now_add=True)
    class Meta: constraints = [UniqueConstraint(fields=["org", "source_ref"], name="importrecord_org_ref")]
```
- 청소: 새 작업을 만들 때 그 조직의 24시간 지난 작업(파일 포함)을 지운다. `# ponytail: 요청 시 청소, 조직이 많아지면 관리 명령으로`.
- 입구 B의 이미지는 서명 URL이 1시간이라 **받는 즉시** `MEDIA_ROOT/imports/<job>/<n>.<ext>`에 둔다(허용 확장자 `tasks/attachments.py:26-45`, 파일 25MB). 실행 때 문서 첨부로 옮기고 폴더를 지운다.

화면 단계(한 화면, HTMX로 아래쪽만 바뀐다):
```
1 입구     [파일 올리기] 또는 [Notion 링크] (토큰 없으면 안내)            → ImportJob 생성
2 진행     "페이지 37 / 120 · 요청 410회" 진행 막대, 2초마다 조각 실행(≤ 40회 요청/조각)  ※ 입구 A는 즉시 ready
3 대상     찾은 표마다: 태스크 | 프로젝트 | 회의록 | 문서 | 사람 매칭표 | 건너뛰기 · 찾은 페이지 묶음(트리): 문서(조직 / 프로젝트 X / 팀 Y) | 건너뛰기
4 열 지정·값 대응·사람 매칭 (§1.4)                                          → ImportJob.mapping
5 미리보기  만들 N · 건너뛸 N(이미 가져옴) · 경고 목록(§1.7) — 아무것도 쓰지 않는다
6 실행     한 트랜잭션 → 보고 + [사람별로 나누기] 바로가기 → status=done
```
탭을 닫아도 작업은 남는다. 다시 열면 그 단계부터 이어진다(`/orgs/<id>/import?job=`).

### 1.6 실행 규칙(`imports/services.py`)
- `plan(job, *, actor) -> Plan`(쓰지 않음), `run(job, *, actor, split_multi_assignee=False) -> Report`. 둘 다 `require_admin`.
- 순서: 프로젝트 → 사람 매칭 → 태스크(주 프로젝트 먼저, 연결은 두 번째 패스 — 가져오기의 연결은 **열람 확대 경고 없이** 관리자가 실행하는 것으로 본다. 미리보기에 "연결로 열람자가 늘어나는 태스크 n건"을 경고로 보여 준다) → 문서·회의록(트리 순, 두 번째 패스에서 페이지 간 링크를 `/docs/<id>`로 재작성) → `ImportRecord` 일괄 생성.
- 태스크는 `create_task(... source="web", notify_assignee=False)`로 규칙(기한·완료 조건·중요도 상한)을 태운 뒤 **원본 시각·상태만** `Task.objects.filter(pk).update(created_at, status, completed_at, status_since)`로 덮는다(imports/services.py 안에서만 — 규칙을 우회하지 않고 시각만 보존). `ChangeLog(field="imported", note=source_ref)` 한 줄. 담당 요청·Discord 알림은 만들지 않는다.
- 완료 조건 필수 조직은 `done_when="가져오기"`를 넣고 경고로 알린다.
- 개발일지(행 안 인라인 DB)는 진행 메모에 `YYYY-MM-DD — 내용` 줄로(결정 5). 다중 담당·다중 프로젝트는 §1.4 + 옵션 "담당자가 여러 명인 행은 사람별 태스크로 나누기"(기본 꺼짐).
- 문서는 `projects.docs.create_doc`·`move_doc`(§4.4), 회의록은 `create_doc(kind="meeting", created_on=날짜 열, tags=분류·태그 열)`. 이미지는 그 문서의 첨부(`Attachment.doc`).

### 1.7 상한·보안·보고
- ZIP 50MB · 항목 3,000 · 압축 해제 합계 200MB(항목 `file_size` 합산으로 zip bomb 차단) · CSV 5,000행 · 본문 256KB · 경로 `..`·절대 경로 거부 · 중첩 ZIP 한 단계.
- 조직 관리자 + 로그인 세션만. 토큰·MCP·스킬로는 열지 않는다(AI가 수십 건을 만드는 경로를 열지 않는다). API는 세션 전용 `POST /api/orgs/{id}/import/jobs`(파일 또는 `{url}`), `POST /api/import/jobs/{id}/continue`, `PUT …/mapping`, `GET …/plan`, `POST …/run`. 처리량 조직당 분당 3회(기존 `UserRateThrottle` 방식). Notion 토큰 평문은 `continue` 조각 안에서만 복호화.
- 미리보기 표(`table.grid`, `.table-scroll`): 종류 / 제목 / 담당자 / 프로젝트 / 상태 / 기한 / 처리 / 경고. 경고 종류(`SPEC.md:425-436`): 담당자 못 찾음 · 2명 이상 · 프로젝트 없음·2개 이상 · 완료인데 완료일시 없음 · 완료일시 < 생성일시 · 미완료인데 기한 없음/오래됨 · 상태 미대응 · 날짜 파싱 실패(원문 보존) · 이미지 건너뜀 · **열람 확대**(연결로 늘어남) · 예산 초과.
- 보고: 종류별 만든 수·건너뛴 수·경고 수·나누기 후보(각 행 [사람별로 나누기] → §2.4)·원본 링크 수. 조직 전체 태스크 화면에 `imported=<job>` 칩 하나.

### 1.8 테스트(`imports/tests.py`)
- 파서: Notion 이름 규칙(hex·URL 디코드), 폴더 → 트리, `_all.csv` 우선, 중첩 ZIP 한 단계, 상한·zip bomb·경로 탈출 거부, 날짜 형식 3종 + 실패 보존.
- Notion 클라이언트(응답 픽스처, 네트워크 없음): 링크 → id, 페이지/DB 판별, 블록 변환 표 전부(지원 안 하는 블록 문구), 리치 텍스트, 속성 → 문자열, 페이지네이션, 429 대기, 예산 초과 중단, 조각당 요청 ≤ 40·cursor 이어가기, 이미지 즉시 저장, 토큰이 로그·job·보고에 없음(문자열 검사).
- 서비스: 열 지정·값 대응 → 필드, 시각 보존, 완료일시 없음 처리, 재실행 0건(`ImportRecord`, 두 입구 교차), 다중 담당·다중 프로젝트, 사람 매칭 3단계, 기본 담당자·프로젝트, 멤버 403, `plan`이 아무것도 안 씀, 링크 재작성, 첨부, 개발일지 → 메모 줄, 24시간 청소.
- 웹: 단계 이어가기(`?job=`), 진행 폴링, 미리보기 경고, 보고.

### 1.9 수용 기준
- O 분석의 실제 데이터(Projects 15·Tasks 약 46·문서 정리 약 27·위키 8)를 ZIP 한 번 **또는** 루트 페이지 링크 한 번으로 미리보기 → 실행 → 재실행 0건. 두 입구를 번갈아 써도 중복이 없다.
- 원본 생성·완료 시각이 보존되고 주간 보고의 "이번 주 완료"가 부풀지 않는다. 담당 요청·알림 0건. 토큰이 어디에도 남지 않는다.

---

## 2. 담당자 1명 고정과 "사람별로 나누기"

### 2.1 원칙
모델은 그대로(`Task.assignee` FK 1개, `tasks/models.py:32-37`). 둘 이상이 들어오려 하면 **막지 않고 안내**한다 — 여러 사람이 하는 일은 사람별 태스크로 나눠 **계열**로 묶는다(`Task.parent` 평평한 계열, `tasks/models.py:54-62`).

### 2.2 판정(`tasks/split.py` 새 파일)
```python
def looks_multi_assignee(task_or_fields, org) -> list[User]:
    """제목·설명에 조직 활성 멤버 display_name이 2명 이상 보이면 그 사람들. 아니면 [].
    # ponytail: '같이·함께·공동·전원' 키워드는 이름이 1명 이상 보일 때만 힌트 — 오탐 방지."""
```
안내는 막지 않는 `.notice`(글리프 없음): "이 일은 여러 사람이 맡는 것처럼 보입니다. 사람별로 나누면 담당·기한·완료가 또렷해집니다. [사람별로 나누기]".

### 2.3 서비스
```python
@transaction.atomic
def split_by_assignees(task, users, *, actor, source, token=None, title_pattern="{title} — {name}") -> list[Task]:
    """사람마다 태스크 하나. duplicate_task(설명·완료 조건·체크리스트·링크·문서 연결·연결 프로젝트 복사, parent=계열 뿌리) 재사용.
    원본은 지우거나 취소하지 않는다. 원본 체크리스트를 'TASK-n 이름' 목록으로 바꾸고 진행 메모에 한 줄(pm-split 규칙과 같다).
    담당 권한이 없는 사람에겐 create_task 규칙대로 담당 요청이 간다."""
```
2~10명. 연동 프로젝트(§3.3)는 복사하지 않는다(새 태스크는 GitHub 연결 없음). 권한은 `duplicate_task` → `create_task`의 `_require_member`. 이력 `ChangeLog(field="split", new_value="TASK-a,TASK-b")`.

### 2.4 경로별 동작

| 경로 | 바꿀 것 |
|---|---|
| 웹 만들기 폼(`templates/projects/_task_form.html:6`) | 그대로. 저장 뒤 패널에 §2.2 안내 |
| 웹 패널(`templates/tasks/_panel.html:47-52`) | 담당자 줄 아래 `[사람별로 나누기]`(`.btn.sm`) → `dialog` `templates/tasks/_split.html`(멤버 체크 목록, 판정된 사람 미리 체크, 제목 규칙 미리보기, [나누기] `.primary`). 결과: 계열 섹션 갱신, 토스트 "3건으로 나눴습니다." |
| 가져오기 | §1.4·1.7 |
| API | `TaskCreateIn`·`TaskPatchIn`에 `assignee_ids: list[int] | None`을 **받되 400**: `{"assignee_ids": "담당자는 한 명입니다. 사람별로 나누려면 만든 뒤 POST /api/tasks/{id}/split 을 쓰세요."}`. 새 `POST /api/tasks/{id}/split {assignee_ids, title_pattern?}` → 201 `{tasks}` |
| MCP(`server.py:541`) | `create_task` docstring "담당자 한 명", 새 `split_task(task_id, assignee_ids)`, `get_guide` 조합표 "여러 사람이 할 일 → create_task 1건 → split_task" |
| 스킬 | `pm/SKILL.md` 한 줄, `pm-split` "사람별 모드"(담당 열이 모두 다르면 `/split` 한 번) |
| Discord `/태스크만들기`(`slash.py:292-319`) | 그대로. 판정되면 응답 끝 한 줄 "담당자는 한 명입니다. 사람별로 나누려면 웹에서 [사람별로 나누기]를 누르세요." 새 명령 없음 |

### 2.5 테스트·수용 기준
- 판정 4건(2명·1명·키워드만·비활성), 나누기(3명 → 3건·parent·체크리스트·원본 교체·이력·담당 요청·1명/11명 거절·연결 프로젝트 복사·연동 프로젝트 미복사), API 400 문구·`/split` 201·404, 대화상자, Discord 문구.
- 어떤 경로로도 담당자가 둘 이상 저장되지 않고, 시도한 사람은 **한 번**의 클릭/호출로 사람별 태스크를 만든다.

---

## 3. 태스크 하나를 여러 프로젝트에 연결

### 3.1 대안 비교(결론 유지)
| | A. `Task.project` → M2M | **B. 주 프로젝트 FK + 연결 표 `TaskProject`** | C. 프로젝트마다 복제 |
|---|---|---|---|
| 판단 | 번호·규칙·알림의 소유자가 없어짐, 조회 97곳 전부 수정 → 비추천 | **추천**. 소유자는 주 프로젝트, 열람은 주 ∪ 연결 | "따로 하는 일"은 §2 나누기가 이미 이것 |

안내 문구(스킬·guide 공통): **한 작업이 여러 프로젝트에 "관련"되면 연결, 프로젝트마다 "따로 하는" 작업이면 나누기.**

### 3.2 모델 — `tasks 0010_taskproject_git_project`
```python
class TaskProject(models.Model):
    """연결 프로젝트. 주 프로젝트(Task.project)는 번호·규칙·알림의 소유자이고 여기엔 들어가지 않는다."""
    task = FK(Task, CASCADE, related_name="project_links"); project = FK("projects.Project", CASCADE, related_name="task_links")
    created_by = FK(AUTH_USER_MODEL, PROTECT, related_name="+"); created_at = DateTimeField(auto_now_add=True)
    # 연결 시 열람 확대를 확인한 기록. 누가 열람자를 늘렸는지 남는다(ChangeLog note에도).
    widened = BooleanField(default=False)
    class Meta: constraints = [UniqueConstraint(fields=["task", "project"], name="taskproject_task_project")]

# Task
extra_projects = ManyToManyField("projects.Project", through="TaskProject", related_name="linked_tasks", blank=True)
# 연동 프로젝트(GitHub). 연결 프로젝트가 하나라도 있을 때만 뜻이 있다. None이면 자동 연동 끔(§3.3).
git_project = FK("projects.Project", SET_NULL, null=True, blank=True, related_name="+", verbose_name="연동 프로젝트")
```
"주 ≠ 연결", "git_project ∈ {주} ∪ 연결"은 서비스가 검사한다. 데이터 마이그레이션 없음.

### 3.3 GitHub 규칙(결정 2)
**연동 프로젝트(실효)** `effective_git_project(task)`:
- 연결 프로젝트 0개 → 주 프로젝트(지금 동작, `git_project` 무시).
- 연결 1개 이상 → `task.git_project`가 설정돼 있고 {주} ∪ 연결 안에 있으며 그 프로젝트에 저장소가 있으면 그것, 아니면 **None = 자동 연동 끔**.

| 지점 | 지금 | 바꿀 것 |
|---|---|---|
| 웹훅 `TASK-n` 매칭 `_find_task`(`github/services.py:798-803`, `project=conn.project`) | 주 프로젝트 안에서만 | `Task.objects.filter(pk=n).filter(git_project_q(conn))` — `git_project_q(conn) = (Q(project=conn.project) & ~Exists(TaskProject(task=OuterRef("pk")))) | Q(git_project=conn.project)`. 브랜치·푸시·PR·리뷰·머지 모두 이 한 함수를 지난다 |
| 손 연결 `link_event`(`:517-520`) | `task.project_id == project` | `effective_git_project(task) == project`, 아니면 "이 태스크의 연동 프로젝트가 아닙니다." |
| 이슈 → 태스크 생성 `_on_issues`(`:1321-`) | `project=conn.project` | 그대로(새 태스크는 연결 0개) |
| `writes.create_issue`·`create_branch`(`github/writes.py:152-153,184`) `conn = task.project.repo` | 주 저장소 | `conn = repo_of(effective_git_project(task))`; None이면 `ServiceError({"github": "연동 프로젝트를 먼저 선택하세요."})` |
| PR 맥락 `pr_context.py:74-75` | `task.project.repo` | `effective_git_project` 저장소. 선택 전이면 저장소 메타 없이 태스크·결정만 |
| `get_task_github`·패널 `_git_ctx`(`web/views/tasks.py:42`) | 주 저장소 | 선택 전: `.conn-state.off` "연동 프로젝트를 선택하세요" + select(주 ∪ 연결 중 저장소 있는 것) + [선택]. 선택 후: 기존 `ol.git-steps` |
| 연결 추가로 0→1 | — | 이미 `TaskGitLink`(이슈·브랜치)가 있으면 `git_project = 주`로 자동 지정(진행 중인 작업을 끊지 않는다), 없으면 None |
| 연결 해제로 `git_project`의 프로젝트가 빠짐 | — | `git_project = None` + 이력 + 패널 `.notice.warn` |
| 저장소 연결 해제(`disconnect_repo`) | — | 그 프로젝트를 `git_project`로 둔 태스크는 None으로(한 쿼리) |

설정·API·MCP: `update_task(... git_project=)`(버전 검사·이력 `field="git_project"`), `PATCH /api/tasks/{id} {git_project_id}`, MCP `update_task(git_project_id=)`. `TaskGitLink`는 그대로 태스크당 하나(연동 프로젝트가 하나이므로 모순 없음).

### 3.4 열람 범위 = 주 ∪ 연결(결정 3)
```python
def visible_tasks(user):
    vp = visible_projects(user)
    linked = TaskProject.objects.filter(task_id=OuterRef("pk"), project__in=vp)
    return Task.objects.filter(Q(project__in=vp) | Exists(linked)).select_related("project", "project__org", "assignee", "reviewer")

def can_view_task(user, task) -> bool:  # 태스크 단위 접근 검사는 이 한 곳
    return visible_tasks(user).filter(pk=task.pk).exists()
```
`distinct`가 아니라 `Exists`라 기존 `count()`·`annotate`가 그대로 맞는다(`visible_projects`와 같은 선택, `projects/services.py:74-76` 주석).

**연결 권한과 열람 확대 확인**
- 연결할 수 있는 사람: `can_view_task(actor, task)` **그리고** `can_view_project(actor, 대상)`. 주 프로젝트가 비공개("teams")면 **프로젝트 관리자·조직 관리자만**(§6 질문 1 — 추천값으로 가정). 연결 해제는 연결할 수 있는 사람과 같다(좁히는 것이라 확인 없음).
- 열람 확대 판정 `widening(task, project) -> list[User]`: `viewers(project) − ⋃ viewers(주 ∪ 기존 연결)`. `viewers(p)`는 `visibility == "org"`면 조직 활성 멤버 전원, 아니면 조직 관리자 ∪ `owners` ∪ 담당 팀 멤버(`visible_projects`의 조건을 사람 쪽에서 센 것). 쿼리 3~4개, 연결 대화상자에서만 돈다.
- 결과가 비어 있지 않으면 `link_project(..., confirm_widening=False)`는 `ServiceError({"confirm": WIDENING_MSG, "widening": [{id, display_name}][:5], "widening_count": n})`을 낸다. `WIDENING_MSG`(용어표 적용): **"주의: {대상 프로젝트}를 볼 수 있는 사람 중 지금 이 태스크를 볼 수 없는 {n}명(A, B 외)이 연결 뒤 이 태스크를 보게 됩니다."** 주 프로젝트가 비공개이고 대상이 조직 전체 공개면 "조직 전체 n명".
- `confirm_widening=True`로 다시 부르면 연결하고 `TaskProject.widened=True`, `ChangeLog(field="projects", note="열람 확대 확인: n명")`.
- 웹: 연결 대화상자(`templates/tasks/_link_project.html`)가 400을 받으면 같은 대화상자에 `.notice.warn` + 체크 "확인했습니다" + [연결](`.danger`가 아니라 `.primary` — 되돌릴 수 있다). 연결 뒤 패널 상단에 한 줄 "연결 프로젝트의 열람자도 이 태스크를 봅니다."
- API: `POST /api/tasks/{id}/projects {project_id, confirm_visibility_widening: false}` → 400 `{"error": "visibility_widening", "message": WIDENING_MSG, "widening_count": n, "widening": [...]}`; `true`면 201.
- MCP `link_task_project(task_id, project_id, confirm_visibility_widening: bool = False)`: 인자가 거짓이고 확대가 있으면 도구는 **거부**하고 반환: `{"refused": "visibility_widening", "message": WIDENING_MSG, "next": "사용자에게 위 문구를 그대로 보여 주고 허락을 받은 뒤 confirm_visibility_widening=true로 다시 부르세요. 허락 없이 true를 넣지 마세요."}`. `get_guide`·`mcp_server/skill/SKILL.md`에 같은 규칙. 스킬 `pm/SKILL.md`: `pm.py` 호출에 `--confirm-widening` 플래그, 사용자 확인 없이는 붙이지 않는다.
- 프로젝트 공개 범위 변경(`set_visibility`, 관리자만)은 그 프로젝트의 연결 태스크 열람자도 함께 바꾼다 — 설정 화면 도움말에 한 줄.

**노출 경로 전수(열람 = 주 ∪ 연결로 바뀌는 곳 / 그대로인 곳)**

| 경로 | 지금 | 개정 |
|---|---|---|
| 웹 패널·행·상세(`task_or_404` → `get_visible_task`, `web/views/common.py:26-30`) | 주 | 자동 반영(`visible_tasks`) |
| 검색(`tasks/services.py:1202`), 내 태스크·오늘(`me_view`·`today_view`), 조직 전체 태스크, API `list_tasks`, MCP | `visible_tasks` | 자동 반영 |
| 보드·달력·결과 선반·템플릿(`web/views/projects.py:278,346,353` `project.tasks`) | 주만 | `tasks_of(project)`. P를 볼 수 있는 사람은 P에 연결된 태스크를 모두 볼 수 있으므로(정의상) 추가 거름 없음 |
| 담당자·검토자 지정 `_require_viewer`(`tasks/services.py:119-122`) | 담당자가 주 프로젝트를 봐야 함 | 생성 시엔 그대로(태스크가 없음). 변경 시 `can_view_task(assignee, task)`. 문구 `ASSIGNEE_CANT_SEE` 유지 |
| 담당 요청·작업 요청(`work_requests`) | 받는 사람이 주를 봐야 함 | `can_view_task` |
| 첨부 다운로드(`tasks/attachments.py:79-88` `can_view_project(att.target_project)`) | 주 | 태스크 첨부는 `can_view_task`, 프로젝트·문서 첨부는 그대로 |
| 결정 기록(`decision_services.py:42-45` `is_member`) | 조직 멤버 | 그대로(웹·API는 `task_or_404`를 먼저 지난다) |
| 포트폴리오 출처(`portfolio/sources.py:33-37` `task__project__in=visible_projects`) | 주 | `task__in=visible_tasks(user)` |
| PR 맥락(`pr_context.py:70` `is_member`) | 조직 멤버 + `can_view_repo` | 그대로 |
| SSE(`web/views/events.py:60-70` `project__in=visible_projects`) | 주 | `visible_tasks(user).filter(project__org=org, updated_at__gt=since)`. `link_project`·`unlink_project`가 `updated_at`·`version`을 올려 새 열람자의 화면에 바로 나타난다 |
| 조직 현황·주간 보고 `_open_qs`(`reports/services.py:21-28`) | `project__in=_projects(org, viewer)` | `tasks_visible_in(org, viewer)`: viewer가 있으면 `visible_tasks(viewer).filter(project__org=org)`, 봇(None)이면 `Q(project__visibility="org") | Exists(연결 중 visibility="org")`. **태스크당 한 번** 센다 |
| `org_status.by_project`·레일(`web/context.py:63`)·`project_stats_bulk`(`projects/services.py:475-503`) | `Count("tasks")` | 주 집계 + 연결 집계(`task_links`) 두 annotate의 합(조인 곱 방지). 프로젝트별 수치는 연결 포함, 각주 "연결 태스크는 여러 프로젝트에 셉니다" |
| 알림: 담당자·검토자 DM | 사람 기준 | 그대로. 프로젝트 채널 알림(`github/notify.py:25-28`)은 **주 프로젝트 채널만**(`# ponytail`) |
| Discord `/오늘`·에스컬레이션(`escalate.py`, 봇 = viewer None) | 공개 프로젝트 | 봇 규칙(위 `_open_qs`)과 같음 |
| 회의록·문서의 태스크 연결 칩 | `visible_tasks` | 자동 반영 |
| GitHub 웹훅(viewer 없음) | — | §3.3 |
| 패널의 연결 칩 | — | 보는 사람이 볼 수 있는 프로젝트만 그린다(못 보는 연결은 개수도 숨김 — 비공개 프로젝트 이름 노출 방지) |

**성능**: `visible_tasks`가 `visible_projects` 서브쿼리를 두 번 품는다(주 `IN`, 연결 `Exists`). Postgres는 같은 서브쿼리를 두 번 계획하지만 프로젝트 수십 건 규모라 문제없다. `test_perf.py`에 "연결 100건 있어도 목록 쿼리 수 불변"을 넣고, 느려지면 요청당 한 번 `list(visible_projects(user).values_list("pk", flat=True))`로 바꾼다(`# ponytail`). 연결 칩은 `rows_for`(`web/views/common.py:289-294`)에서 `prefetch_related_objects(tasks, "extra_projects")` 한 줄.

### 3.5 서비스(`tasks/services.py`)
```python
def tasks_of(project)                       # Q(project=p) | Exists(TaskProject(project=p)) — 프로젝트 기준 화면 전부
def effective_git_project(task)             # §3.3
def widening(task, project) -> list[User]
@transaction.atomic
def link_project(task, project, *, actor, source="web", token=None, confirm_widening=False) -> Task
@transaction.atomic
def unlink_project(task, project, *, actor, source="web", token=None) -> Task
```
- `update_task(project=새 주)`: 새 주가 연결에 있으면 그 행 삭제, 옛 주는 연결로 남기지 않는다. `git_project`가 더는 {주} ∪ 연결에 없으면 None.
- `duplicate_task`: 연결 복사(`widened`는 복사하지 않고 `widening` 재검사 없이 복사 — 같은 열람자 집합), `git_project`는 복사하지 않음.
- `create_task(..., linked_project_ids=())`: 생성 직후 `link_project` 반복(확대는 `confirm_widening` 인자 전달).

### 3.6 웹
- 패널 "프로젝트" 줄: 주 select(지금) + 연결 칩(`.tag` + ×, `aria-label="연결 해제"`) + `[연결 추가]`(select → 대화상자, §3.4). 행(`_row.html`): 연결 있으면 프로젝트 이름 뒤 `↔ n`(툴팁에 이름), 다른 프로젝트 화면에서 보면 "↔ 주 프로젝트명". 보드·선반 머리 각주(연결 1건 이상일 때만).
- GitHub 블록: §3.3.

### 3.7 API·MCP·스킬·Discord
- `task_out`: `project_id` 유지 + `linked_projects: [{id, name}]`(보는 사람 기준) + `git_project_id`. `GET /api/tasks?project=` 연결 포함(`primary_only=1`로 주만). `POST/DELETE /api/tasks/{id}/projects`, `TaskCreateIn.linked_project_ids`, `PATCH git_project_id`.
- MCP: `link_task_project`·`unlink_task_project`(§3.4), `create_task(linked_project_ids, confirm_visibility_widening)`, `update_task(git_project_id)`, `get_task`에 `linked_projects`·`git_project_id`.
- 스킬 `pm/SKILL.md`·`pm-new`(3단계 "여러 프로젝트" → 나누기/연결 선택, 확대는 사용자 확인 뒤 `--confirm-widening`).
- Discord: 새 명령 없음. 태스크 메시지에 연결이 있으면 "↔ A, B" 한 줄.

### 3.8 테스트
- 연결·해제·멱등·주=연결·다른 조직·보관·권한(양쪽 가시성, 비공개 주는 관리자만)·이력·옮기기·복제.
- 열람: 비공개 주 + 공개 연결 → 확대 400/거부 → `confirm` 뒤 바깥 멤버에게 보임(목록·패널·검색·SSE·첨부·포트폴리오 출처·`list_tasks?project=`); 주 공개 + 비공개 연결 → 확대 없음(400 없음), 바깥 멤버에게 칩·개수 숨김; 해제 뒤 다시 안 보임; MCP 인자 없이 거부 + 안내 문구; `widening` 계산(조직 전체·팀·관리자 중복 제거).
- GitHub: 연결 0 → 기존 동작 전부 통과; 연결 1 + 미선택 → 브랜치·PR·커밋이 상태를 안 바꾸고 `GitEvent` 미매칭으로 남음, `create_branch` 거절; 선택 → 그 저장소만 매칭; 연결 추가 시 `TaskGitLink` 있으면 자동 주; 해제·저장소 해제 → None.
- 집계: `project_stats_bulk`·`by_project`·레일 연결 포함, `org_status.counts`·주간 보고 태스크당 1회, 봇(None) 규칙.
- 성능: 목록 쿼리 수 불변.

### 3.9 수용 기준
- "Swagger 노출 문제" 태스크를 주 1 + 연결 3으로 만들면 네 보드에 모두 보이고 조직 미완료 합계는 1만 늘며, 연동 프로젝트를 고르기 전엔 어느 저장소의 `TASK-n`도 상태를 바꾸지 않는다.
- 열람자가 늘어나는 연결은 웹에서 확인 없이, MCP·스킬에서 명시 인자 없이 만들어지지 않는다(테스트로 고정).

---

## 4. 문서·회의록 통합

### 4.1 결정: 모델 하나 `Doc(kind="doc" | "meeting")`
편집 경로만 공유하면 이전 버전·첨부·백링크·올리기·템플릿·검색마다 두 모델을 분기해야 한다(`Attachment`에 FK가 넷). **모델을 합치고 회의록은 `kind="meeting"`인 문서**로 둔다. 회의록 고유 열(회의 일시·태그·초안/확정·출처·참여자·녹음)은 `Doc`에 nullable로 들어가고 규칙은 `kind`로만 갈린다. 기존 회의록 데이터는 D3가 옮긴다(§4.3).

| v1(이번) | v2(안 함) |
|---|---|
| 공개 범위 3종(조직·프로젝트·팀), 하위 문서 트리(회의록 제외), 템플릿 2개 시드(회의록·설계 문서), 이전 버전·되돌리기, 백링크(본문 검색), 태스크·프로젝트 연결, 통합 검색, `.md`·ZIP 가져오기/내보내기, 문서 첨부(이미지 본문 삽입), 버전 잠금(기존), 회의록 통합·초안 띠·확정 | 댓글·멘션, 공개 공유 링크, 백링크 색인 표, 동시 편집 표시, 개발일지 |

### 4.2 모델 — `projects 0012_doc`(RenameModel `ProjectDoc`→`Doc` + 필드 + `DocRevision` + 템플릿 시드)
```python
class Doc(models.Model):
    KINDS = [("doc", "문서"), ("meeting", "회의록")]
    ORIGINS = [("web", "웹"), ("voice", "음성 회의"), ("import", "가져오기")]
    org = FK("orgs.Organization", CASCADE, related_name="docs")                 # 새 열. 기존 행은 project.org(RunPython)
    kind = CharField(max_length=7, choices=KINDS, default="doc")
    project = FK(Project, CASCADE → SET_NULL, null=True, blank=True, related_name="docs")  # 필수 → 선택(회의록과 같게 SET_NULL)
    team = FK("orgs.Team", SET_NULL, null=True, blank=True, related_name="docs")
    parent = FK("self", CASCADE, null=True, blank=True, related_name="children"); position = PositiveIntegerField(default=0)
    is_template = BooleanField(default=False)
    # 회의록 열(kind="meeting"에서만 뜻이 있다)
    status = CharField(max_length=5, choices=[("draft", "초안"), ("final", "확정")], default="final")
    origin = CharField(max_length=6, choices=ORIGINS, default="web")
    created_on = DateTimeField("회의 일시", null=True, blank=True); tags = JSONField(default=list, blank=True)
    attendees = ManyToManyField(AUTH_USER_MODEL, blank=True, related_name="+")
    title, body_md, version, tasks(M2M related_name="docs"), created_by, updated_by, updated_source, created_at, updated_at  # 그대로
    class Meta:
        ordering = ["position", "created_at", "id"]
        constraints = [CheckConstraint(condition=Q(project__isnull=True) | Q(team__isnull=True), name="doc_scope_one"),
                       CheckConstraint(condition=~Q(kind="meeting") | Q(parent__isnull=True), name="doc_meeting_no_parent")]
        indexes = [Index(fields=["org", "kind", "parent"]), Index(fields=["org", "kind", "created_on"])]

class DocRevision(models.Model):
    """저장 이력. 자동 저장(0.8초)마다 쌓이지 않게 같은 사람·10분 안은 마지막 행을 덮어쓴다."""
    doc = FK(Doc, CASCADE, related_name="revisions"); version = PositiveIntegerField()
    title = CharField(max_length=200); body_md = TextField()
    saved_by = FK(AUTH_USER_MODEL, SET_NULL, null=True, related_name="+"); source = CharField(max_length=4, choices=Doc.SOURCES)
    saved_at = DateTimeField()
    class Meta: ordering = ["-version"]; constraints = [UniqueConstraint(fields=["doc", "version"], name="docrevision_doc_version")]
```
- 공개 범위는 **뿌리 문서에만 뜻이 있고 하위는 뿌리를 따른다**(모든 행에 복사해 조회를 평평하게; `move_doc`이 하위를 다시 쓴다. 깊이 ≤ 6).
- 이전 버전 보존 50개/문서. 템플릿 시드(`projects/doc_templates.py` 상수 2개: **회의록**(회의 주제/내용/결정/할 일), **설계 문서**(배경/결정/대안/영향)) — RunPython으로 기존 조직에, `orgs.services.create_org`에서 새 조직에. 개발일지 템플릿은 없음(결정 5).
- `Task.docs`가 문서·회의록 둘 다 가리킨다. `task_out["docs"]`(`api/serialize.py:61-63`, `project_id` 필터)는 `visible_docs(viewer)` 기준으로 바뀌고 `kind`를 함께 낸다.

### 4.3 회의록 이전 — `notes 0004_merge_into_doc`(의존: `projects 0012`)
1. `VoiceRecording.doc = FK("projects.Doc", CASCADE, null=True)` 추가.
2. RunPython: `MeetingNote` 행마다 `Doc(kind="meeting", org, project, team, status, origin=source, title, body_md, version, created_on, tags, created_by, updated_by=None, updated_source="web", created_at, updated_at)` 생성(id 대응표), `tasks`·`attendees` M2M 복사, `VoiceRecording.doc` 채움. 역방향은 "지원 안 함"(`RunPython.noop`이 아니라 예외 — 되돌리려면 백업).
3. `VoiceRecording.note` 제거 → `doc`을 `note`로 이름 변경(`related_name="recording"` 유지 → 코드의 `doc.recording`·`rec.note`가 그대로 맞는다).
4. `MeetingNote` 삭제. `notes/admin.py` 등록 제거.
- 옛 회의록 id ≠ 새 문서 id다. 회의록 URL `/orgs/<id>/notes?note=<옛 id>`가 북마크돼 있을 수 있으나 2주 전 기능이라 **리다이렉트 표를 두지 않는다**(§9).
- 백업·복구 리허설(`scripts/restore-test.sh`)을 D3 병합 전 한 번 돈다(운영 적용은 사용자 몫).

### 4.4 서비스 — `projects/docs.py`가 공통 편집기, `notes/services.py`는 회의 고유
```python
# projects/docs.py
def visible_docs(user, org=None)   # 관문. (project None | in visible_projects) & (team None | in visible_teams)
                                   # & (status final | recording.host == user | 조직 관리자)  ← 옛 visible_notes의 초안 규칙
def project_docs(project)          # 옛 visible_docs(project)
def can_view_doc(user, doc) -> bool
def create_doc(*, org, actor, kind="doc", title=None, body_md="", project=None, team=None, parent=None, template=None,
               created_on=None, tags=None, origin="web", source="web")
    # kind=meeting: parent 거절, 제목 기본 "제목 없는 회의록", created_on 기본 now_kst(옛 create_note)
def update_doc(doc, field, value, *, actor, expected_version, source="web")
    # EDITABLE = {"title","body_md"} ∪ (kind=meeting: {"created_on","tags","project"}). 초안은 진행자·관리자만(옛 _check_edit),
    # source=mcp는 ai.edit_text. 저장 뒤 _record_revision
def _record_revision(doc, actor, source)   # 같은 사람·10분 안 덮어쓰기, 50개 상한
def revert_doc(doc, revision, *, actor, expected_version, source="web")   # 한 트랜잭션, version +1, 리비전 1개
def move_doc(doc, *, parent=None, position=None, project=None, team=None, actor)   # 순환·깊이·다른 조직·회의록 parent 거절, 하위 범위 재기록
def set_template(doc, on, *, actor); def delete_doc(doc, actor)   # 기존 규칙(작성자·관리자; 초안은 진행자·관리자). 하위 수 반환
def backlinks(doc, viewer) -> {"docs": [...], "tasks": [...]}   # body_md__icontains "/docs/<id>"  # ponytail: 1,000건 넘으면 DocRef 표
def link_task(doc, task, actor, *, as_output=False)   # 같은 조직이면 됨. 프로젝트 문서는 태스크의 주·연결 프로젝트 중 하나와 같을 때만
def upload_doc(*, org, actor, filename, raw, kind="doc", project=None, team=None, parent=None)   # 회의록 올리기도 여기
def export_md(doc); def export_zip(org, viewer, *, root=None, kind="doc"); def import_zip(...)   # §1 파서 재사용
def search_docs(user, q, org=None, kind=None)

# notes/services.py (남는 것) — create_note/update_note/upload_note/delete_note/link_task는 docs 함수에 kind="meeting"을 넣는 얇은 별칭(호출부 수정 최소화)
def finalize_note(doc, *, actor, source, project=None, team=None)   # 그대로. doc.status·project·team 갱신
def meeting_scope / start_recording / update_recording / transfer_host / request_host / answer_host_request / speaker_names / meeting_glossary   # 그대로(`rec.note`가 Doc)
```
- 편집 권한: 범위를 볼 수 있는 조직 멤버(지금과 같음). 템플릿도 같음.
- `ChangeLog`는 문서에 쓰지 않는다(이전 버전 표가 이력). 삭제만 `ChangeLog(target_type="org", field="doc_deleted", note=제목)`.

### 4.5 첨부 — `tasks 0011_attachment_doc`
`Attachment.doc = FK("projects.Doc", CASCADE, null=True, blank=True, related_name="attachments")`; 제약 `attachment_exactly_one_target` → project·task·doc 중 하나. `attachment_path`는 `doc.org_id`. 다운로드 권한: task → `can_view_task`(§3.4), doc → `can_view_doc`, project → `can_view_project`. 편집기 "파일" 카드의 이미지에 [본문에 넣기](`notes.js:99`의 `![]()` 삽입 재사용).

### 4.6 웹(`DESIGN.md` 준수)
- 경로: `/orgs/<id>/docs`(조직 탭 "문서"), `/docs/<id>`(정식 주소 → 홈 + `?doc=`), 프로젝트 "문서" 탭 = 같은 화면을 프로젝트로 거른 것, 팀 상세 "팀 문서" 카드. **회의록은 `/orgs/<id>/notes` URL을 유지**하고 같은 화면을 `kind=meeting`으로 거른 것(목록은 회의 일시 역순, 트리 없음, 범위 select·태그 칩은 지금 `notes/list.html:18-37` 그대로).
- 공통 템플릿 `templates/docs/{index,_list,_tree,_editor,_new_dialog,_revisions,_links}.html`. `projects/docs.html`·`notes/list.html`은 이것을 include하는 얇은 껍데기.
- 편집기 카드: 경로(상위 문서) · 제목 · 메타(만든 사람·마지막 수정·`v`) · **회의록 막대**(kind=meeting: 회의 일시 입력·태그·참여자 칩·초안이면 `.notice` "초안 — 진행자와 조직 관리자만 봅니다" + 공개 범위 라디오(조직 공통/프로젝트/팀) + [확정](`.primary`) — IMPL-PLAN-9 M4의 확정 화면이 여기로 온다) · 본문(기존 `#doc` 편집기·자동 저장·`X-Note-Version` 충돌 띠) · 전사문 `details`(녹음이 있을 때, `transcript_md`) · `details` 3개: **이전 버전**(표 v/사람/시각/[이 버전으로 되돌리기], 미리보기 토글) · **연결**(태스크 칩 + 추가, 백링크) · **파일**.
- 새 문서 `dialog`: 제목 · 위치(상위 문서 select) · 공개 범위 라디오 카드(상위가 있으면 비활성) · 템플릿 select. 새 회의록 버튼은 템플릿 select만(기본 "회의록" 템플릿).
- 머리: 범위 칩 · 검색 `.input` · 주 버튼 "새 문서"/"새 회의록" 하나 · 보조 `[Markdown 올리기]`·`[ZIP 가져오기]`·`[내보내기]`(`.btn.sm`).
- 삭제 확인 "하위 문서 n개가 함께 삭제됩니다." → `.danger`. 빈 상태 `.empty.compact`. 검색 화면 세 묶음(태스크/문서/회의록, `.group-stack`). 격식체·감탄부호 없음·아이콘 없음(`DESIGN.md` §7).

### 4.7 API·MCP·스킬·Discord
- 새 `/api/docs`: `GET /orgs/{id}/docs?kind=doc|meeting|all&project=&team=&q=&tree=1` · `POST /orgs/{id}/docs` · `GET/PATCH/DELETE /docs/{id}` · `GET /docs/{id}/revisions` · `POST /docs/{id}/revert` · `POST /docs/{id}/move` · `GET /docs/{id}/backlinks` · `GET /docs/{id}/export.md` · `GET /orgs/{id}/docs/export.zip` · `POST /orgs/{id}/docs/import`.
- **별칭 유지**: `/api/project-docs`(응답에 `org_id·team_id·parent_id·kind` 추가), `/api/orgs/{id}/notes`·`/api/notes/{id}`·`/finalize`(`api/routers/notes.py` — `note_out` 모양 유지 + `kind`; 내부는 Doc). 봇 API(`api/routers/discord.py`의 회의 끝점 — 페이로드 불변, Node 게이트웨이(IMPL-PLAN-9 M3) 영향 없음).
- MCP: 문서 도구 확장(`list_docs(org_id, kind, project_id, team_id, q)`, `create_doc(... parent_id, template_id)`, `update_doc`, `get_doc`, 새 `list_doc_revisions`·`revert_doc`·`move_doc`). IMPL-PLAN-9 M4의 `list_meeting_notes`·`get_meeting_note`·`update_meeting_note`는 **같은 문서 도구의 `kind="meeting"` 별칭**으로 M4에서 만든다(확정 도구 없음 유지). 삭제·가져오기는 MCP에 없음.
- 스킬 `pm/SKILL.md` "문서" 절, `pm-meeting`(M4)은 `/api/notes` 별칭 그대로.
- Discord: 변경 없음.

### 4.8 IMPL-PLAN-9와의 접점
| IMPL-PLAN-9 | 상태 | 이 설계와의 관계 |
|---|---|---|
| M2 core(회의록 열·`VoiceRecording`·봇 API·사용자 API) | 구현됨 | D3가 모델을 옮긴다. 봇·사용자 API 모양 유지 |
| M3 음성·전사(게이트웨이, Node) | 미구현 | 봇 API만 부르므로 **영향 없음**. D3 뒤에 해도, 전에 해도 된다 |
| M4 MCP 도구 3개·`pm-meeting`·확정 화면 | 미구현 | 확정 화면·초안 띠·공개 범위는 **D2(공통 편집기)로 이동**. M4는 MCP 별칭 3개 + 스킬만 남고 **D3 뒤**에 한다 |

### 4.9 테스트
- 가시성: 조직·프로젝트·팀 문서, 초안(진행자·관리자만), 바깥 멤버 API 404·목록·백링크·검색 제외. 기존 `visible_notes` 테스트 전부 통과(별칭).
- 트리·이동·순환·깊이·부모 삭제; 회의록 parent 거절.
- 이전 버전 묶음·상한·되돌리기·409. 템플릿 시드·복사. 가져오기/내보내기 왕복. 첨부 권한·상한.
- 이전(D3): 회의록 N건 → 문서 N건(필드·태스크·참여자·녹음 대응), `test_voice.py` 전부 통과, `/api/notes` 응답 모양 불변, 옛 `ProjectDoc` 테스트 통과.

### 4.10 수용 기준
- Notion 위키 8개를 조직 문서 트리로, 회의록 15건을 `kind=meeting`으로 들여와 링크로 남길 이유가 없어진다.
- 회의록에서 문서와 같은 편집기·올리기·이전 버전·첨부·백링크가 되고, 음성 회의 초안 → 확정 흐름이 그대로 돈다.

---

## 5. 사용자 노출 용어표(명령·화면·API 설명·문서·스킬 모두 이 표만 쓴다)

| 표준 용어 | 뜻 | 쓰지 않는 말 |
|---|---|---|
| **문서** | 조직·프로젝트·팀 범위의 마크다운 글 하나. 회의록도 문서의 한 종류 | 위키, 페이지, 노트, 포스트 |
| **회의록** | `kind=meeting`인 문서(IMPL-PLAN-9 용어표 그대로) | 미팅 노트, 노트, 회의 기록 |
| **하위 문서 / 상위 문서** | 트리의 자식/부모 | 서브페이지, 자식 문서, 섹션 |
| **공개 범위**(조직 전체 / 프로젝트 / 팀) | 문서·프로젝트가 보이는 범위 | 권한, 스코프, 가시성(코드 용어) |
| **열람자 / 열람 확대** | 태스크를 볼 수 있는 사람 / 연결로 열람자가 늘어나는 것 | 뷰어, 노출 확대, 권한 누출 |
| **템플릿** | 새 문서·회의록·태스크의 본문 틀 | 틀, 양식, 서식 |
| **이전 버전 / 되돌리기** | 저장 이력과 그 시점으로 복원 | 리비전, 히스토리, 롤백 |
| **연결 / 연결 해제** | 문서↔태스크, 태스크↔프로젝트 참조 만들기·끊기 | 링크(외부 URL과 구분), 매핑, 관계 |
| **백링크** | 이 문서를 가리키는 문서·태스크 목록 | 역링크, 참조됨 |
| **가져오기 / 내보내기** | 열 지정·미리보기를 거쳐 들여오기 / ZIP·md로 받기 | 임포트, 익스포트, 마이그레이션, 동기화 |
| **Notion 링크 가져오기 / 통합 토큰** | 공식 API로 들여오기 / 조직이 등록한 integration 토큰 | 커넥터, API 키, 인테그레이션 |
| **올리기** | 파일 하나를 그대로 등록 | 업로드(버튼 문구), 첨부(파일 카드에서만) |
| **미리보기** | 실행 전 결과 확인(쓰지 않음) | 드라이런, 시뮬레이션 |
| **열 지정 / 값 대응 / 사람 매칭** | 어느 열이 무엇인지 / 상태·중요도 값 대응 / 사람 이름 → 멤버 | 매핑, 필드 매핑, 사용자 매핑 |
| **원본 링크** | 가져온 항목에 붙는 Notion 주소 | 소스, 출처 URL |
| **담당자**(한 명) | 태스크를 맡은 사람 | 담당자들, 공동 담당, 책임자 |
| **사람별로 나누기 / 사람별 태스크** | 담당자마다 태스크를 만들어 계열로 묶기 | 분배, 서브태스크, 하위 태스크 |
| **계열 / 원본** | 나눈 태스크의 묶음 / 그 뿌리(`_series.html:1`) | 부모 태스크, 에픽 |
| **주 프로젝트** | 번호·규칙·알림을 소유하는 프로젝트(`Task.project`) | 소속 프로젝트, 대표 프로젝트, 메인 |
| **연결 프로젝트** | 태스크가 추가로 걸린 프로젝트 | 관련 프로젝트, 부 프로젝트, 다중 프로젝트 |
| **연동 프로젝트** | GitHub 자동 규칙이 따르는 프로젝트(저장소). 연결이 있을 때 사용자가 고른다 | 저장소 선택, 기준 저장소, 깃 프로젝트 |
| **옮기기** | 주 프로젝트 바꾸기 | 이동, 이관 |
| **첨부 / 파일** | 문서·태스크·프로젝트에 붙은 파일 | 어태치먼트, 미디어 |

코드 식별자는 영문 그대로(`Doc`, `DocRevision`, `TaskProject`, `git_project`, `ImportJob`, `ImportRecord`, `split_by_assignees`, `confirm_widening`).

---

## 6. 사용자에게 물을 것(2개)

| # | 질문 | 선택지 | 추천 |
|---|---|---|---|
| 1 | 열람 확대를 **확인할 수 있는 사람** | (a) 태스크를 볼 수 있는 멤버 누구나 (b) **주 프로젝트가 비공개("담당 팀만")면 프로젝트 관리자·조직 관리자만, 공개면 누구나** (c) 항상 관리자만 | **(b)** — 비공개 프로젝트의 열람자를 늘리는 결정은 그 프로젝트 관리자의 몫. 공개 프로젝트끼리는 확대가 생기지 않으므로 누구나 |
| 2 | Notion 링크 가져오기의 사람 매칭에 **이메일**을 쓰려면 통합에 "사용자 정보(이메일 포함)" 권한이 필요 | (a) **권한을 켜도록 안내하고 이메일 우선 매칭** (b) 이름만 | **(a)** — 동명이인·표시 이름 차이를 피한다. 권한이 없으면 자동으로 (b)로 떨어진다 |

묻지 않고 추천대로 확정: 회의록은 `Doc(kind=meeting)`으로 모델 통합 + 데이터 이전(옛 id 리다이렉트 없음) · 가져오기는 조직 관리자·웹 세션만 · `ImportJob`(24시간 보존, 입구 B는 2초 폴링 조각) · 완료일시 미상은 생성일시 · 담당자 안내는 막지 않는 `.notice` · 나누기는 `duplicate_task` 재사용 · 연결 프로젝트 0→1일 때 진행 중 GitHub 연결은 주 프로젝트로 자동 지정 · 집계 원칙(조직 1회, 프로젝트별 연결 포함) · 프로젝트 채널 알림은 주만 · 문서 공개 범위는 뿌리 상속 · 이전 버전 10분 묶음·50개 · 백링크 본문 스캔 · 템플릿 시드 2개 · Discord 새 명령 없음.

---

## 7. 구현 단계 표(기준 `f917a8e`)

| 단계 | 내용 | 담당 | 선후 | 마이그레이션 | 주로 고치는 파일 | 충돌 주의 |
|---|---|---|---|---|---|---|
| **P1a** 다중 프로젝트 모델·열람·서비스·API·MCP | §3.2·3.4(열람 전수표의 `tasks`·`reports`·`portfolio`·`events`·`attachments`·`work_requests`)·3.5·3.7(API·MCP·스킬 문구) | Opus | 바로 시작 | `tasks 0010` | `tasks/{models,services,attachments,work_requests}.py`, `reports/services.py`, `portfolio/sources.py`, `web/views/events.py`, `api/routers/tasks.py`, `api/{schemas,serialize}.py`, `mcp_server/mcp_server/server.py`, `mcp_server/skill/SKILL.md`, `skills/pm/SKILL.md`, `skills/pm-new/SKILL.md`, `web/test_perf.py` | `api/schemas.py`·`server.py`를 D1도 만진다 → 다른 블록, 순차 병합(P1a → D1) |
| **D1** 문서 모델·서비스·API·MCP | §4.2·4.4·4.7(웹 제외), `projects/doc_templates.py`, `create_org` 시드 | Opus | 바로 시작(P1a와 병렬) | `projects 0012` | `projects/{models,docs,doc_templates}.py`, `projects/migrations/0012`, `api/routers/docs.py`, `api/schemas.py`(끝), `api/api.py`(한 줄), `orgs/services.py`(create_org 끝), `mcp_server/.../server.py`(문서 블록) | `tasks/services.py`는 손대지 않음(`Task.docs` 쿼리는 serialize에서) |
| **N1a** 파서·Notion 클라이언트 | §1.3·1.7 상한, `imports/{parse,notion}.py` + 픽스처 테스트 | Opus | 바로 시작 | 없음(모델은 N1b) | `imports/{__init__,apps,parse,notion}.py`, `imports/tests.py`, `imports/fixtures/*` | 없음 |
| **P1b** GitHub 연동 프로젝트 규칙 | §3.3 전부 | Opus | P1a 뒤 | 없음 | `github/{services,writes,pr_context,sync}.py`, `web/views/tasks.py`(`_git_ctx`), `templates/tasks/_git.html`, `api/routers/github.py`, `mcp_server/.../server.py`(`get_task_github`) | `web/views/tasks.py`는 S1·P2도 만진다 → P1b → S1 → P2 순차 |
| **S1** 담당자 1명 안내·사람별로 나누기 | §2 전부 | Sonnet | P1a 뒤 | 없음 | `tasks/split.py`(새), `web/views/split.py`(새), `web/urls.py`(끝), `templates/tasks/{_split,_panel}.html`, `api/routers/tasks.py`(끝), `api/schemas.py`, `mcp_server/.../server.py`(`split_task`), `skills/pm/SKILL.md`, `skills/pm-split/SKILL.md`, `discord_service/discord_service/slash.py`(응답 한 줄) | `_panel.html`·`routers/tasks.py`를 P2도 만진다 → S1 먼저 |
| **D3** 회의록 이전 | §4.3, `notes/services.py` 별칭화, `routers/notes.py`·`routers/discord.py` 회의 끝점 내부 교체, `notes/admin.py`, `test_voice.py` 갱신 | Opus | D1 뒤 | `notes 0004` | `notes/{models,services,admin,test_voice,tests}.py`, `notes/migrations/0004`, `api/routers/{notes,discord}.py`, `api/serialize.py`(`task_out.docs`) | `api/serialize.py`를 P1a가 먼저 만진다 → D3는 P1a 병합 뒤 |
| **P2** 다중 프로젝트 화면·집계·연결 대화상자 | §3.4 웹(확대 확인)·3.6, 집계(`project_stats_bulk`·`by_project`·레일·주간 보고), Discord "↔" | Opus(P1 담당) | P1b·S1 뒤 | 없음 | `web/views/{projects,common,tasks,roadmap,me,orgs}.py`, `web/context.py`, `templates/tasks/{_panel,_row,_link_project}.html`, `templates/projects/{_board,calendar,_shelf,detail}.html`, `projects/services.py`(stats), `reports/services.py`(by_project), `discord_service/.../{weekly,messages}.py` | `reports/services.py`는 P1a가 `_open_qs`를 먼저 바꿈(다른 함수) |
| **D2** 공통 문서 화면·회의록 막대·검색·첨부 | §4.5·4.6, 검색 세 묶음, 조직 탭·주 메뉴, `notes.js` 이미지 삽입 | Opus | D3·P1a 뒤 | `tasks 0011` | `tasks/{models,attachments}.py`, `web/views/{docs,notes,search,attachments,teams}.py`, `web/urls.py`(끝), `templates/docs/*`(새), `templates/projects/docs.html`, `templates/notes/list.html`, `templates/search.html`, `templates/orgs/{_tabs,team_detail}.html`, `templates/base.html`(한 줄), `web/static/{app.css,notes.js}` | `base.html`·`urls.py`는 운영 콘솔이 이미 바꿈 → `f917a8e` 기준으로 덧붙임. `tasks/models.py`는 P1a(0010) 뒤 |
| **N1b** 가져오기 모델·서비스·API | §1.2(Spec)·1.5·1.6·1.7 API | Opus(N1a 담당) | N1a·P1a·D1·D3 뒤 | `imports 0001` | `imports/{models,services}.py`, `imports/migrations/0001`, `config/settings.py`(`"imports"` 한 줄), `orgs/settings.py`(org 그룹 끝 `notion.token`, `secret_value` 주석), `api/routers/imports.py`(새), `api/api.py`(한 줄) | `orgs/settings.py`는 다른 단계가 안 만짐 |
| **N2** 가져오기 화면·보고 | §1.5 화면 6단계·진행 폴링·보고, 조직 설정·조직 탭 입구, `imported=<job>` 칩 | Sonnet | N1b·D2·S1·P2 뒤 | 없음 | `web/views/imports.py`(새), `web/urls.py`(끝), `templates/orgs/import/*`(새), `templates/orgs/{settings,_tabs}.html`(링크), `web/views/me.py`(칩), `projects/docs.py`(`import_zip`) | `me.py`·`_tabs.html`은 P2·D2 뒤 |
| **F** 마무리 | `docs/SPEC-FUNCTIONAL.md`(2·4·6·7장: 연결·연동 프로젝트·문서·회의록·가져오기), `skills/README.md`, `mcp_server/skill/SKILL.md`, `docs/GUIDE-00-rules.md` 6절(`imports/`), `docs/IMPL-PLAN-9.md`에 M4 범위 변경 메모, 전체 테스트 재실행 | Sonnet | 전부 병합 뒤 | 없음 | 문서만 | 없음 |

병렬 묶음: **{P1a, D1, N1a} → {P1b, S1, D3} → {P2, D2} → N1b → N2 → F.**
검토(Sol, GPT 사용량 확인 뒤) 세 번으로 제한: §3.4 열람 확대(P1a·P2), §3.3 GitHub 규칙(P1b), §1.7 토큰·상한(N1b). 승인(Fable): 단계 표와 질문 2개. IMPL-PLAN-9 M3·M4는 이 표 밖(M4는 D3 뒤).

마이그레이션 번호 고정: `tasks 0010`(P1a) · `projects 0012`(D1) · `notes 0004`(D3) · `tasks 0011`(D2) · `imports 0001`(N1b). 기존 최신: `tasks 0009`, `projects 0011`, `notes 0003`, `ops 0001`.

---

## 8. 위험

| 위험 | 대응 |
|---|---|
| Notion 내보내기 형식·API 응답이 전제와 다름 | 범용 열 지정이 흡수. 파서·클라이언트는 "모르는 것은 보존". N1a 첫 작업 = 실제 내보내기 ZIP 1개 + API 응답 캡처로 픽스처 |
| 입구 B가 90초 타임아웃·3req/s에 걸림 | 조각(≤ 40회)·폴링·`cursor`. 탭을 닫아도 작업이 남는다 |
| 열람 확대가 실수로 일어남 | 서비스가 기본 거부(`confirm_widening=False`), 웹은 체크, MCP·스킬은 인자 없으면 거부, 이력에 "열람 확대 확인" |
| 연결 태스크가 GitHub에서 조용히 안 움직임 | 패널 `.conn-state.off` + 미매칭 `GitEvent`가 이벤트 표에 남음. 연결 0→1 때 진행 중 연결은 주로 자동 지정 |
| 회의록 모델 이전 실패·id 변경 | RunPython 대응표, 복구 리허설, API 모양 유지. 옛 id 북마크는 깨진다(§9) |
| `visible_tasks` 서브쿼리 2중 | 규모가 작다. `test_perf` 고정, 느려지면 id 목록 물질화(`# ponytail`) |
| 이전 버전으로 DB 증가 | 10분 묶음·50개 상한·256KB |
| `ProjectDoc` 이름 변경 파급 | related_name·API 별칭·MCP 도구 이름 유지 |

## 9. 확인 불가
- Notion "Markdown & CSV" 내보내기의 정확한 파일 규칙과 API 블록·속성 응답의 세부(실행하지 않음, `O-notion-migration.md` §5). N1a 착수 때 실제 파일·응답으로 확정.
- Notion 통합의 "사용자 정보" 권한이 이 조직 integration에 켜져 있는지(§6 질문 2).
- Postgres에서 `visible_tasks` 2중 서브쿼리·`body_md__icontains` 백링크 성능 — SQLite로만 테스트.
- 옛 회의록 URL(`?note=<id>`)이 외부에 공유돼 있는지 — 이전 뒤 깨진다.
- 이 팀의 실제 다중 담당·다중 프로젝트 행 수(최소 3·2건만 확인) — 가져오기 미리보기가 알려 준다.

---

## 사용자 결정 결과 (2026-10-07) — 위 설계보다 우선
1. **Notion 가져오기 = 둘 다**: (b) ZIP·CSV·md 올리기(범용 열 지정) **와** (a) Notion 공식 API + 링크 가져오기(조직이 integration 토큰 등록, 페이지를 integration에 공유, 링크로 페이지·하위 페이지·DB 일회성 가져오기 — 동기화 없음). 토큰은 Fernet 암호화·마스킹. 두 경로가 같은 매핑·미리보기·중복 방지(`ImportRecord`) 파이프라인을 쓴다.
2. **여러 프로젝트에 연결된 태스크는 GitHub 자동 연동(TASK-n 매칭·브랜치·PR 자동 반영)을 하지 않는다.** 연동할 프로젝트(그 저장소)를 사용자가 **직접 선택**한다(선택 전에는 자동 연동 없음, 선택은 태스크 화면·API·MCP에서). 연결 프로젝트가 하나뿐이면 기존 동작.
3. **비공개 연결은 연결 시 선택**: 열람 권한 목록이 서로 다른 프로젝트를 함께 연결하려 하면 경고 — "프로젝트 열람 권한이 없는 다른 연결하려는 프로젝트의 사용자도 이 태스크를 볼 수 있습니다. 주의하세요"(용어표에 맞게 다듬되 뜻 유지) — 를 띄우고 사용자가 확인해야 연결된다. 연결되면 **연결된 모든 프로젝트의 열람자가 그 태스크를 본다**(가시성 = 주 프로젝트 ∪ 연결 프로젝트, 명시 동의 후). **MCP와 스킬에서는 명시적 허용 인자(예: `confirm_visibility_widening=true`)가 없으면 거부**하고 사용자에게 허락을 받으라고 안내.
4. **회의록도 사실상 통합**: 문서 확장으로 생기는 작성 기능(편집기)·업로드·버전 이력·백링크·첨부 등 **같은 문서 편집 기능을 회의록에서도 쓴다**. 회의록 고유 규칙(음성 회의·진행자·초안/확정·참여자, IMPL-PLAN-9)은 유지하되, 편집·업로드 경로는 문서와 하나로 합친다(데이터 모델 통합 여부는 설계 판단 — 기존 데이터 이전 포함).

## 사용자 결정 결과 2 (2026-10-07) — 위 모든 내용보다 우선
1. **열람 확대 = 관리자 승인 요청.** 열람 권한 목록이 다른 프로젝트에 태스크를 연결하면 태스크 생성·수정 자체는 진행되지만, 그 연결은 **승인 대기(pending)**로 남고 **관리자(주 프로젝트가 비공개면 그 프로젝트 관리자 또는 조직 관리자, 그 밖에는 조직 관리자 — 설계 판단으로 확정) 승인 뒤에만 확정**된다. 승인 전에는 연결 프로젝트 쪽에서 보이지 않는다(열람 확대 없음). 요청·승인·거절은 알림과 이력(감사)으로 남긴다. 웹·API·MCP·스킬 모두 같은 흐름(MCP는 승인 요청까지만, 승인은 사람이 웹에서).
2. **Notion 동기화·DB 매핑은 구현하지 않는다**("페이지마다 양식이 다 다르다"). **Notion 공식 API 링크 가져오기 제외**, DB(Projects·Tasks·Team Members) 열·사람 매핑 제외. 가져오기는 **Markdown(`.md`)과 Notion 내보내기 ZIP 안의 페이지(.md·첨부)를 문서로 들여오는 것만** 남긴다(트리 구조 유지, 원본 시각은 알 수 있으면 보존, 중복 방지). `notion.token` Spec·`ImportJob` 폴링·사람 매칭은 만들지 않는다.
3. **(최종) Notion 가져오기 = MD 문서 가져오기.** 사용자: "단순하게 Notion 가져오기 기능은 MD 문서를 가져오는 거야." 별도 `imports` 앱·ZIP 파서·Notion API·DB 매핑·`ImportRecord`·`ImportJob` 없음. 문서 기능(D1)의 md 가져오기(여러 파일)에 Notion 내보내기 md 정리(파일·제목 id 해시 제거, 속성 줄 보존, 내부 링크 변환, 이미지 안내)와 간단한 중복 방지만 둔다. N1·N2 단계 삭제.
