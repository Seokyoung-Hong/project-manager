# IMPL-PLAN-11·12 배포 전 최종 승인 검토 (Fable, 2026-10-07)

- 판정: **반려(배포 불가)**. 운영 Postgres에서 `migrate`가 반드시 실패하는 마이그레이션 2개와, 이번 라운드가 새로 연 열람 누출 1건(상)을 먼저 고쳐야 한다. 그 뒤 조건부 승인 — 아래 §5 순서로 배포한다.
- 기준: 브랜치 `Seokyoung-Hong/Ochestration` HEAD `af55469`, 범위 `4eecd77..HEAD`(IMPL-PLAN-11 P1a·P1b·S1·D1·D2·D3·P2, IMPL-PLAN-12 G1·G2·G3, Sol R1~R9 수정 `8798bfa`·`391d4d9`·`d79efaa`). 사용자 결정(IMPL-PLAN-11 결정 1·2·3, IMPL-PLAN-12 결정) 우선.
- 방법: 코드·git 수정 없음(`git status` 깨끗). 작성자 보고는 쓰지 않고 diff·코드·실행으로 확인했다. 서브에이전트 2갈래(가시성 전수·불변식 전수, 둘 다 SQLite 메모리 재현)와 내가 직접 돌린 Postgres 리허설(임시 `postgres:16-alpine`, 포트 55432, 운영·로컬 DB 무관)을 합쳤다. 수정 실험은 저장소 밖 사본(스크래치 `corecopy`)에서만 했다.

## 1. 실행 결과

| 실행 | 결과 |
|---|---|
| `cd core; uv run pytest -q` | 1597 passed, 2 skipped(Postgres 전용), 64.6초 |
| `cd discord_service; uv run pytest -q` | 181 passed |
| `cd mcp_server; uv run pytest -q` | 57 passed |
| `DATABASE_URL=postgres… pytest tasks/test_group_review.py`(R4 두 연결 barrier 경쟁 포함) | 9 passed — skip 없음 |
| 수정 전 커밋 `e76aa9f` 사본에 새 회귀 테스트 3파일(`projects/test_review_r11.py`·`tasks/test_group_review.py`·`github/test_git_project_privacy.py`) 복사 후 실행 | **13 failed**, 4 passed, 2 skipped — 회귀 테스트가 실제 결함을 잡는다 |
| Postgres 전체 마이그레이션(빈 DB, HEAD) | 72개 5.3초 OK — 그러나 **데이터가 있으면 실패**(§3) |

## 2. Sol R1~R9 — 근본 원인으로 고쳐졌는가

| # | 판정 | 근거(코드로 확인) |
|---|---|---|
| R1 문서 제목·ID 노출 | 고침 | 태스크의 문서는 `projects/docs.py:429 task_docs`·`:434 task_doc_choices`(둘 다 `visible_docs(viewer)`) 하나로 통일. API `api/serialize.py:65`, 패널 최초 렌더·조각 `web/views/tasks.py:112,502` 모두 이것만 쓴다. 산출물 링크 복사는 `_all_task_viewers_see`(`docs.py:415`)가 조직 전체 확정 문서 또는 연결 없는 주 프로젝트 문서일 때만 허용 |
| R2 범위 삭제가 문서 공개 | 고침 | `Doc.project/team` RESTRICT(`projects/models.py:146-151`, `0013`), `delete_project`가 문서·리비전·문서 첨부를 명시적으로 지움(`projects/services.py:383-392`), `delete_team`은 팀 문서가 있으면 거절(`orgs/services.py:334-342`) |
| R3 회의록 ∩ 범위 확대 | 고침 | `notes/migrations/0004:21-32` 프로젝트·팀 둘 다인 행이 있으면 **DML 전에** RuntimeError. Postgres 리허설에서 중단·무변경(회의록 4건 그대로, `notes_voicerecording.note_id` 그대로) 확인. `test_migrate_doc.py:77-81` 기대값도 바뀜 |
| R4 상위·하위 경쟁 | 고침 | `_lock_family`(`tasks/services.py:466-475`)가 DB의 현재 `group_id`를 다시 읽어 태스크·상위를 pk 순 `select_for_update`, 잠그는 사이 관계가 바뀌면 `ConflictError`. `transition` 닫기·재개(`:918-934`)·옮기기(`:739`)·`set_group`(`:493`)·`create_task`(`:576`)·`duplicate_task`(`:1050`)가 모두 상위 행을 잠근다. Postgres 두 연결 barrier 테스트 2건 통과 |
| R5 숨긴 상위 번호 | 고침 | `brief.py:53` `group_id`는 `attach_group_visible`(`services.py:316-334`)로 확인된 때만. 이력은 `hidden_task_refs`·`mask_task_refs`(`:340-365`)를 API·웹 공통 적용. 단 **오류 문구**는 남았다(§4 S6, 하) |
| R6 `task_ids` | 고침 | `api/routers/docs.py:28 visible_task_ids`, `doc_out`·`note_out`에 viewer 필수(목록·단건·쓰기·409) |
| R7 연동 프로젝트 노출 | 고침 | `git_project_choices(task, viewer)`(`services.py:1833`), `task_repo_state` `hidden`(`github/services.py:96`), `task_out.git_project_id` 가림(`serialize.py:96-98`), 이력 `projects`·`git_project` id 가림(`routers/tasks.py:278-298`), PR 맥락 거절(`pr_context.py:117`). 단 같은 이력의 **`project`(옮기기) 필드는 빠졌다**(§4 S2, 중) |
| R8 프로젝트별 집계 | 고침 | `reports/services.py:41-59 _per_project` 두 queryset 모두 `leaf_only` |
| R9 ZIP 상한 | 고침 | `_read_import_files`(`docs.py:659-709`): 요청 전체 입력 크기 → 메타데이터(개수·풀린 합·개별) → 파일마다 `MAX_BODY+1` 스트리밍 읽기(`_read_capped`). 웹·API는 업로드 객체를 그대로 넘긴다(`routers/docs.py:346`) |

## 3. 운영 데이터 마이그레이션 — **차단 결함 2건(상)**

### 3.1 `projects 0012_doc`·`notes 0004_merge_into_doc`가 데이터 있는 Postgres에서 실패한다
- 재현(운영 유사 데이터: 조직 1·프로젝트 2·`ProjectDoc` 2·`MeetingNote` 4(초안·음성·녹음 1·태스크 연결·참여자)·태스크 7(계열·S1 split 이력·체크리스트)·첨부 2 — 스크래치 `seed_pre.py`):
  - `projects.0012_doc`: `OperationalError: cannot CREATE INDEX "projects_doc" because it has pending trigger events` — `schema_editor.__exit__`(`django/db/backends/base/schema.py:169`)에서 미뤄 둔 인덱스 생성이 같은 트랜잭션의 `seed_rest`(템플릿 INSERT, `0012_doc.py:23-42`)·`fill_org`(UPDATE, `:15-20`)가 남긴 지연 FK 트리거에 막힌다. **조직이 하나라도 있으면 반드시 실패**(빈 DB에서는 템플릿을 넣지 않아 통과 — 그래서 from-scratch 테스트와 SQLite 테스트가 못 잡는다).
  - `notes.0004_merge_into_doc`: 0012를 고쳐 통과시킨 뒤 `cannot ALTER TABLE "projects_doc" because it has pending trigger events` — RunPython이 넣은 `Doc` 행의 지연 트리거가 남은 채 `AlterField voicerecording.note`(FK → `projects_doc`)를 실행한다(`0004:93-104`). **회의록이 한 건이라도 있으면 실패**(녹음 유무 무관).
  - `tasks.0012_task_group`은 split 행 2건을 갱신해도 통과했다(실측).
- 운영 영향: `entrypoint.sh` `set -e`라 web 컨테이너가 migrate에서 죽고 재시작 루프. 마이그레이션은 각각 원자적이라 DB는 `tasks 0010`까지 적용된 채 남는다(그 상태의 코드는 뜨지 않음).
- 수정(둘 중 하나, 저장소 밖 사본으로 **검증 완료**):
  1. Django 문서대로 **RunPython을 스키마 변경과 다른 마이그레이션으로 분리**(0012 → 스키마 / `fill_org` / NOT NULL·제약·인덱스·`DocRevision` / `seed_rest`; 0004 → `AddField doc` / RunPython / 나머지 DDL).
  2. 최소 diff: 각 RunPython forward 첫 줄에 `if schema_editor.connection.vendor == "postgresql": schema_editor.execute("SET CONSTRAINTS ALL IMMEDIATE")`. vendor 가드가 없으면 **SQLite(전체 테스트)가 `near "SET": syntax error`로 깨진다**(실측). 사본에 이 수정을 넣고 위 데이터로 전체 migrate 통과·검증(§3.2).
  3. 어느 쪽이든 `DATABASE_URL`이 Postgres일 때만 도는 마이그레이션 테스트 1개(조직·문서·회의록을 넣고 `MigrationExecutor`로 0011→HEAD)를 `test_group_review.py`와 같은 꼴로 둔다. 운영 전 리허설을 테스트가 대신한다.

### 3.2 수정 뒤 리허설 결과(사본, Postgres)
- 순서: `migrate projects 0011`·`tasks 0009`·`ops zero`로 되돌린 "운영 전" 상태 → 시드 → migrate. ∩ 회의록 1건으로 **0004 중단·무변경** 확인 → 행 수정 → 재실행 전부 OK(적용 시간 수 초; 표가 작아 잠금은 문제 아님).
- 검증(스크래치 `verify_post.py`): 문서 2건 제목·version·org 유지 / 회의록 4건 `kind=meeting`으로 이전(초안·`origin=voice`·태그·프로젝트·팀 보존) / 템플릿 2건(회의록·설계 문서) 시드 / `org` 전부 채움 / 리비전 6건 = 비템플릿 문서 수, 회의록 리비전 version·본문 일치 / 녹음 → 회의록 Doc / 참여자 2·태스크 연결 2 복사 / 문서↔태스크 M2M 유지(`projects_projectdoc_tasks`→`projects_doc_tasks`, `projectdoc_id`→`doc_id`) / S1 split 2건 `group`=원본·`parent` 해제, 진짜 계열(회차)은 그대로, 상위의 `TASK-n` 체크리스트만 삭제 / 첨부 2건·제약 6개·ops 트리거 2개.
- 되돌리기: `migrate notes 0003` 거부(회의록 있음). **주의**: `migrate projects 0011`은 거부 전에 `tasks 0012`·`0011`·`projects 0013`을 **먼저 되돌리고** 0004에서 멈춘다 — `Task.group`이 사라진다(RunPython 역방향 noop). 운영에서 역방향 migrate를 돌리지 말고 **되돌리기 = 백업 복구**로 못 박는다(`docs/BACKUP.md` 절차).

### 3.3 그 밖
- `tasks 0012` RunPython은 원본이 닫혔는지 보지 않아 "닫힌 상위 아래 열린 하위"(I2 위반)를 만들 수 있다(`0012_task_group.py:15-25`, SQLite 재현). 운영은 S1 이전이라 0건 예상 — 한 줄(`status__in=OPEN` 조건) 추가 권장, 차단 아님.
- 이미 적용된 마이그레이션 4개(`accounts 0004`·`orgs 0005`·`portfolio 0001`·`tasks 0003`)가 범위 안에서 바뀌었으나 **포맷뿐**(diff 확인) — 무해.
- 운영이 메모리대로 main `ba4c3a1`이면 미적용 마이그레이션은 이번 7개가 아니라 **약 30개**(라운드 7~10 포함). 운영 `showmigrations`로 먼저 확인한다(§5).

## 4. 가시성 — Sol 수정 밖에서 찾은 누출(재현 확정, SQLite 메모리)

| # | 등급 | 내용 | 근거 | 이번 라운드 |
|---|---|---|---|---|
| S1 | **상** | 하위 "기존 태스크 넣기" 후보 목록이 주 프로젝트의 열린 태스크를 **가시성 검사 없이** 보여 준다. 비공개 주 프로젝트의 태스크를 승인된 연결로 보는 사람에게 그 프로젝트의 다른 비공개 태스크 번호·제목이 패널에 뜬다 | `web/views/subtasks.py:31-40` `Task.objects.filter(project_id=…)`. 수정: `ts.visible_tasks(user).filter(...)` | **새로 생김**(`a3e9a24`) |
| S2 | 중 | 옮기기 이력의 `project` 필드: 웹 `_display`가 옛 비공개 프로젝트 이름을 그대로, API 이력은 id 그대로(R7 마스킹에 `project`가 빠짐) | `web/views/common.py:233-235`, `api/routers/tasks.py:280 pfields` | 표시 코드는 기존, 못 보는 열람자(연결 승인)는 이번 라운드가 만듦 |
| S3 | 하 | 완료 제안 DM이 상위 담당자의 열람 권한을 다시 보지 않음(프로젝트가 비공개로 바뀐 뒤) | `tasks/services.py:508-513`. 마감 알림(`orgs/discord.py:145`)에는 같은 검사가 있음 | 새 기능 |
| S4 | 하 | 산출물 링크에 복사된 문서 제목은 문서를 비공개 팀으로 옮긴 뒤에도 남음 | `projects/docs.py:412`(R1은 연결 시점만 검사) | 새 기능 |
| S5 | 중 | 조직 설정 이력 화면(멤버 누구나)에 비공개 태스크 삭제 기록 "TASK-n 제목"이 보임 | `web/views/orgs.py:418-434`, `tasks/services.py` `field="delete"` | **기존**(`a2d6133`에도 있음) |
| S6 | 하 | 하위 재개 거절 문구에 못 보는 상위 번호 | `tasks/services.py:931` | 새 기능 |
| 의심 | 하 | `portfolio/sources.py:59 pr_evidence`가 `can_view_project`를 안 봄(R7 기준과 다름); GitHub 재개 담당 요청(`github/services.py:1315`)이 원래 담당자의 열람을 재확인 안 함 | 코드만 | — |

- 문제 없음으로 확인: 검색·백링크·문서 목록·문서 검색·ZIP 내보내기(`docs.py:538-569`, 못 보는 부모는 경로에 안 넣음)·첨부 다운로드·SSE·주간 보고·봇 `group_id`·"↔ A, B" 연결 이름·보드(확정 연결만)·승인/거절 알림·`git_project_choices`·`_git.html`·`doc_out.task_ids`.
- 남겨 둔 예외(확대 승인된 연결 열람자에게 비공개 주 프로젝트 이름): **타당**. 관리자가 열람자를 넓힌다는 것을 알고 승인한다. 보완 하나 — 공개 프로젝트에 연결되면 봇 주간 보고가 비공개 주 프로젝트 이름을 조직 채널에 올리므로(`reports/services.py:191`→`task_brief`) 승인 화면 문구에 "주 프로젝트 이름도 보입니다" 한 줄.
- 불변식(한 겹·닫힌 상위 아래 열린 하위 없음): 웹·API·MCP·Discord·GitHub 웹훅·보관(하위 먼저 취소 `projects/services.py:313-329`)·삭제·복제·나누기·옮기기·재개 12경로 중 11경로가 `transition`·`set_group`·`create_task` 관문만 지남. 우회는 §3.3의 0012 RunPython뿐. `set_template`(`services.py:1104`)은 행을 안 잠가 하위 만들기와 경쟁하면 "하위를 가진 템플릿"이 생길 수 있음(의심, 하).

## 5. 반드시 고칠 것(배포 전)과 배포 순서

**고칠 것(차단)**: ① §3.1 `projects 0012`·`notes 0004`(분리 또는 vendor 가드 `SET CONSTRAINTS ALL IMMEDIATE`) + Postgres 조건부 마이그레이션 테스트. ② S1 후보 목록 `visible_tasks`. ③ S2 이력 `project` 마스킹(웹·API 두 줄). 권장(같은 커밋에 넣어도 작음): `tasks 0012` 닫힌 원본 건너뛰기, S3·S6 한 줄씩, `docs/OPERATIONS-DEPLOYMENT.md:71`의 `ProjectDoc` 점검 쿼리(모델이 `Doc`으로 바뀌어 **지금은 import 오류**) 교체, MCP `get_task` 설명문(`server.py:399` "group_id는 항상") 갱신.

**배포 순서(수정·재검토 뒤)**
1. 운영 상태 확인(읽기): `docker compose exec web python manage.py showmigrations | grep "\[ \]"` — `ba4c3a1`이면 라운드 7~10 조건(`DISCORD_CLIENT_SECRET`, `COMPOSE_PROFILES=mcp`, 8000 방화벽, NPM `client_max_body_size 26m`, `media_data`·`discord_bot_data` 볼륨)이 전부 이번 배포에 들어간다(`OPERATIONS-DEPLOYMENT.md` 라운드 7 절, `Q-fable-final-ops.md` §6).
2. 사전 점검 SQL(읽기): `select count(*) from notes_meetingnote where project_id is not null and team_id is not null`(0이어야 — 있으면 관리자가 회의록마다 하나를 비운 뒤), `select count(*) from tasks_changelog where target_type='task' and field='split'`(0 예상), 그리고 대조용 `notes_meetingnote`·`projects_projectdoc`·`notes_voicerecording`·`orgs_organization` 행 수를 적어 둔다.
3. `scripts/backup.sh` → `scripts/restore-test.sh`가 `OK`.
4. `git pull` → `docker compose build web` → `docker compose up -d`(entrypoint가 migrate). web 로그에서 `Applying … OK` 7건(또는 30건)과 gunicorn 기동(`--logger-class` import 실패면 첫 줄에 죽는다). migrate 실패 시 재시도하지 말고 백업 복구.
5. 직후 확인(읽기): `showmigrations` 미적용 0 / `/ops/system` 미적용 0·트리거(`Q-fable-final-ops.md` §6) / `Doc(kind="meeting", is_template=False)` 수 = 2의 회의록 수, `DocRevision` 수 = 비템플릿 `Doc` 수, 조직마다 템플릿 2, `VoiceRecording.objects.filter(note__isnull=True)` 0, `Task.objects.filter(group__isnull=False)` 0(split 0건일 때) / `docker stats` web·db 메모리(512MB — 프로세스·의존성 추가 없음: `pyproject`·`uv.lock`·`compose.yml`·`entrypoint.sh` 운영 콘솔 승인 `a2d6133` 이후 변경 없음, 새 볼륨 없음) / SSE·패널·문서 화면 한 번씩.
6. 역방향 `migrate`는 쓰지 않는다(§3.2). 되돌리기 = 백업 복구.

## 6. 확인 불가
- 운영 DB의 실제 마이그레이션 상태·회의록/문서/녹음/split 행 수(VPN·SSH 미사용). 리허설 데이터는 운영과 비슷하게 꾸민 것이다.
- Postgres에서 `visible_tasks` 2중 서브쿼리·`leaf_only` `Exists`·백링크 `icontains` 성능 — 운영 규모(수십 건)에서는 문제없다고 본다.
- S4·S5는 함수 단위 재현(HTTP 단위 아님). 악성 md의 브라우저 XSS 실행은 Sol과 마찬가지로 하지 않았다(정적 점검만).
- 운영이 `ba4c3a1`보다 뒤라면 §5-1의 라운드 7~10 조건은 이미 끝났을 수 있다.
