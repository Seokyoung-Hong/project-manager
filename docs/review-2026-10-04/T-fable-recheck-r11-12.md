# IMPL-PLAN-11·12 반려 항목 재검토 (Fable, 2026-10-08)

- 판정: **조건부 승인(배포 가능)**. 반려 사유(차단 1·상 1·중 1)와 권장 5건이 모두 고쳐졌음을 diff·실행으로 확인했다. 조건은 §4의 배포 전 확인 2가지뿐이며 코드 수정은 필요 없다.
- 범위: `e0e9816..1f73e86`(4커밋, 25파일). 코드·git 수정 없음. 비교 기준은 `S-fable-final-r11-12.md` §5 "반드시 고칠 것".

## 1. 실행 결과

| 실행 | 결과 |
|---|---|
| SQLite `pytest tasks/test_group_final.py tasks/test_group.py tasks/test_group_review.py notes/test_migrate_doc.py projects/test_docs.py projects/test_pg_rehearsal.py projects/test_review_r11.py tasks/test_work_requests.py web/` | 590 passed, 3 skipped(Postgres 전용) |
| `makemigrations --check --dry-run` | No changes detected(모델·마이그레이션 일치) |
| Linux 컨테이너(`postgres:16-alpine` + `uv:python3.12`, 같은 docker network, 포트 포워딩 없음) `test_pg_rehearsal.py`·`test_migrate_doc.py`·`test_docs.py::test_migration_0012…`·`test_group_review.py`(R4 두 연결 포함)·`test_work_requests.py` 3회 | 28 passed ×3, skip 0 |

## 2. 지적 항목별 확인

| 항목 | 판정 | 근거 |
|---|---|---|
| 차단 ① `projects 0012`·`notes 0004` pending trigger | 고침 | RunPython은 `projects/0013_doc_fill_org.py:24`, `0015_doc_seed.py:39`, `notes/0005_merge_into_doc_data.py:83`, `tasks/0013_task_group_data.py:44`에만 있고 각 파일에 DDL 없음(전수 grep). DDL 파일(`0012`·`0014`·`0016`·`notes 0004`·`0006`·`tasks 0012`)에는 RunPython 없음. 의존 순서 `0012→0013→0014(org NOT NULL)→0015→0016→notes 0004→0005→0006`, `tasks 0011`은 `projects 0016`으로 올림(`0011_attachment_doc.py:10`). 데이터 있는 Postgres에서 HEAD까지 migrate 통과(§1) |
| 차단 ① Postgres 조건부 마이그레이션 테스트 | 고침 | `projects/test_pg_rehearsal.py:16-20` BEFORE가 운영 `07a9821`의 `projects 0011`·`tasks 0009`·`notes 0003`과 정확히 일치(`git ls-tree 07a9821` 확인). 조직 2·문서 2·회의록 4(음성·녹음)·split 이력·첨부 2를 넣고 leaf까지 migrate, `:110-133` 보존 검증. `scripts/pg-migrate-rehearsal.sh:22-25` |
| 차단 ② S1 하위 후보 | 고침 | `web/views/subtasks.py:32` `ts.visible_tasks(user).filter(project_id=…)`. 회귀 `tasks/test_group_final.py:52-60` |
| 차단 ③ S2 이력 `project` | 고침 | `tasks/services.py:360-391 history_masker`가 `("project","projects","git_project")` id를 `visible_projects`로 걸러 `HIDDEN_PROJECT`로 바꿈. API `api/routers/tasks.py:286`, 웹 `web/views/common.py:248` 둘 다 이것 하나. `_display`는 숫자가 아니면 조회하지 않음(`common.py:235`). 회귀 `test_group_final.py:63-77`(웹·API) |
| 권장 S3 완료 제안 DM | 고침 | `services.py:540` `can_view_task(group.assignee, group)`. 담당자 None이면 `visible_projects`가 빈 queryset(`projects/services.py:81`)이라 조용히 건너뜀. 회귀 `test_group_final.py:80` |
| 권장 S6 재개 거절 문구 | 고침 | `services.py:963-966`. 회귀 `test_group_final.py:93` |
| 권장 `tasks 0012` 닫힌 원본 | 고침 | `tasks/0013_task_group_data.py:21` `status__in=(열린 5개)`. 회귀 `test_group_final.py:108` |
| 권장 `OPERATIONS-DEPLOYMENT.md:71` 쿼리 | 고침 | `Doc.tasks.through … doc__kind="doc"`로 교체, 라운드 11·12 절(리허설·사전 점검·순서·역방향 금지) 추가(`:76-93`) |
| 권장 MCP `get_task` 설명문 | **미반영** | `mcp_server/mcp_server/server.py:399` "group_id는 항상" 그대로. 코드 동작은 R5대로 가려지므로 설명문만 틀림(하) |
| 보고서 밖 `select_for_update(of=("self",))` | 타당 | `tasks/work_requests.py:265,362`. nullable FK `select_related` 외부 조인은 Postgres가 `FOR UPDATE` 거부 — `self`만 잠그면 됨. Postgres에서 `test_work_requests.py` 통과(§1) |

## 3. 불일치·누락(배포 차단 아님)

- `pg_flushable` fixture가 `core/conftest.py:135`와 `tasks/test_group_review.py:113`에 중복(후자가 우선, vendor 가드 없음). 테스트 전용·동작 영향 없음.
- `web/views/common.py:19` `can_view_project` import는 `:67`에서 여전히 쓰여 미사용 아님(문제 없음).
- 이전 보고 §4 "보완 하나"(승인 화면 "주 프로젝트 이름도 보입니다" 문구)는 미반영 — 권장이었고 차단 아님.
- **운영 격차**: `07a9821`에는 `ops` 앱 자체가 없다. 이번 배포로 새로 적용되는 마이그레이션은 라운드 11·12의 10개가 아니라 **13개**(`ops 0001`·`tasks 0010`·`0011` 포함). `ops 0001`은 CreateModel+RunSQL(트리거 DDL)뿐이라 pending trigger 문제 없음. 리허설 테스트는 `tasks 0010·0011`을 함께 적용하므로 이 격차를 덮는다.

## 4. 조건(배포 전·중, 코드 수정 없음)

1. 운영에서 `showmigrations | grep "\[ \]"`가 **13건**인지 확인(다르면 운영 커밋이 `07a9821`이 아니다 — 멈추고 보고).
2. `OPERATIONS-DEPLOYMENT.md:84` 사전 점검 SQL(프로젝트∩팀 회의록 0건) → `backup.sh` → `restore-test.sh OK` → 배포. migrate 실패 시 재시도 금지·백업 복구(문서 `:89-93`대로).

## 5. Windows R4 간헐 실패 판단에 대해

- 오케스트레이터 판단(환경 문제)은 **타당한 쪽**이다. 근거: `_race`(`test_group_review.py:88-108`)는 스레드마다 새 DB 연결을 열고 `ServiceError`·`ConflictError` 외 모든 예외를 실패로 모은다. 연결 단계에서 끊기면 `OperationalError`로 바로 실패하고 서버 로그엔 아무것도 남지 않는다 — "FATAL 없음"과 맞는다. 포트 포워딩 없는 Linux 네트워크에서는 3회(각 15반복×2테스트) 모두 통과했다.
- 단 **예외 문구를 확인하지 못했다**(확인 불가). 문구가 `server closed the connection unexpectedly`/`Connection reset`류면 환경, `deadlock detected`/`could not serialize`/`_invariant_ok` assert면 코드 결함이다. 후자였다면 이 승인은 무효다.

## 6. 확인 불가

- 운영 DB 실제 상태(마이그레이션·회의록·split 행 수) — 서버 미접속. §4-1로 대신한다.
- Windows 간헐 실패의 실제 예외 문구(§5).
- 운영 규모 성능·브라우저 XSS는 이전 검토와 같이 보지 않았다.
