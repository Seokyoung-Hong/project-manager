# IMPL-PLAN-11·12 Sol 교차 검토

- 판정: **반려**. 비공개 문서·회의록의 열람 확대 및 태스크 상태 불변식 위반을 먼저 수정해야 한다.
- 검토 기준: HEAD `e76aa9f`, `git log --oneline 4eecd77..HEAD`; IMPL-PLAN-11 끝 사용자 결정 1·2·3, IMPL-PLAN-12 끝 사용자 결정 우선.
- 실행일: 2026-10-07. 작성자는 Claude, 검토자는 Sol. 코드 수정·git 상태 변경·외부 게시 없음. 이 보고서만 신규 작성.
- 결함: 상 4건, 중 5건. 각 재현은 운영 DB 대신 독립 프로세스의 SQLite `:memory:` DB에서 실행했다.

## 검증 결과

| 실행 | 결과 |
|---|---|
| `cd core; uv run pytest -q` | 1580 passed, 1213 warnings, 60.94초 |
| `cd mcp_server; uv run pytest -q` | 57 passed, 0.47초 |
| `cd discord_service; uv run pytest -q` | 181 passed, 37 warnings, 3.16초 |
| 추가 격리 재현 | 아래 R1~R9. 기존 테스트에는 빠진 경우가 있다. |

기존 테스트 경고는 Django 6 URLField 전환, staticfiles 디렉터리 부재, Pydantic/Ninja 비권장 API와 Discord/aiohttp 경고다. 테스트 통과는 아래 권한 경계의 안전성을 보장하지 않는다.

## R1 — 상: 연결 태스크가 비공개 주 프로젝트 문서의 제목·ID를 노출

- 근거: `core/api/serialize.py:66`의 문서 목록은 `project_id=t.project_id`만 검사한다. `core/web/views/tasks.py:111`, `:112`, `:501`, `:503`도 `visible_docs` 없이 연결 문서 및 주 프로젝트의 문서 후보 전체를 반환한다. 실제 제목·ID 출력은 `core/web/templates/tasks/_refs.html:14`와 후보 select다.
- 재현: 일반 멤버 U가 못 보는 비공개 프로젝트 P의 태스크 T를 공개 프로젝트 Q에 관리자 승인으로 연결한다. P의 문서 D를 T에 연결하고, 연결하지 않은 P 문서 E도 만든다. U의 `GET /api/tasks/T`는 200과 D의 `{id,title}`을 반환한다. U의 `GET /tasks/T` HTML에는 D뿐 아니라 E의 제목도 나타난다. D 자체는 `can_view_doc(U,D)=False`다.
- 관찰: `doc_can_view=False`, `task_response=200 docs=[{id:3,title:...}]`, `task_web=200 linked_secret_title=True unlinked_secret_title=True`.
- 영향: 태스크 연결 승인이 프로젝트 문서 열람 승인으로 확대된다. MCP `get_task`도 API의 누출을 그대로 받는다. 문서 본문 직접 GET은 차단되지만 제목·존재·ID는 이미 노출된다.
- 권장 수정: API·패널 최초 렌더·참고자료 조각 모두 `visible_docs(viewer).filter(tasks=t)` 및 가시 문서 후보로 통일한다. 내부 문서를 산출물 Link로 만든 경우에도 일반 `links`에 제목을 복사하므로 별도로 가시성 검사를 적용한다(`core/projects/docs.py:400`).

## R2 — 상: 비공개 프로젝트·팀 삭제가 남은 문서를 조직 전체에 공개

- 근거: `core/projects/models.py:144`, `:147`의 `Doc.project/team`은 `SET_NULL`이다. `core/projects/docs.py:94`~`:95`는 두 값이 null이면 조직 전체 문서로 판정한다. `core/projects/services.py:388`과 `core/orgs/services.py:343`에서 삭제하며 문서의 기존 비공개 범위를 보존하지 않는다.
- 재현 A: 비공개 팀 문서 D에 대해 일반 멤버 U는 열람 불가다. `delete_team(team,actor=admin)` 후 D가 살아 있고 `team_id=None`, U의 열람이 True가 된다.
- 재현 B: 비공개 프로젝트 문서 D에 대해 U는 열람 불가다. `archive_project(P,actor=admin); delete_project(P,actor=admin)` 후 D가 살아 있고 `project_id=None`, U의 열람이 True가 된다.
- 관찰: 두 경우 모두 `before=False`, `after=True`.
- 영향: 본문·이전 버전·문서 첨부가 목록·검색·ZIP·다운로드에 모두 나타날 수 있다. 다운로드도 새 `can_view_doc` 결과를 사용한다(`core/tasks/attachments.py:99`). 프로젝트 삭제 설명은 문서가 함께 사라진다고 하지만 실제 FK는 보존 후 공개한다.
- 권장 수정: 범위 삭제를 `PROTECT`로 막고 문서를 명시적으로 옮기거나, 승인된 삭제 정책에 따라 문서를 함께 삭제한다. null을 조직 공개로 해석하는 현재 모델에서 비공개 범위의 자동 `SET_NULL`은 사용하지 않는다. 팀·프로젝트 삭제 회귀 테스트에 본문·첨부 접근을 포함한다.

## R3 — 상: notes 0004가 기존 회의록의 프로젝트∩팀 제한을 프로젝트만으로 확대

- 근거: `core/notes/migrations/0004_merge_into_doc.py:23`~`:27`은 프로젝트와 팀이 모두 있는 옛 회의록에서 비공개 프로젝트이면 팀을 버린다. 이전 `4eecd77:core/notes/services.py:46`~`:50`의 확정 회의록은 프로젝트와 팀 가시성을 AND로 검사했다. 새 제한 `doc_scope_one`이 두 범위를 허용하지 않는다고 해서 기존 비공개 제한을 임의 제거해서는 안 된다.
- 재현: 실제 `MigrationExecutor`로 notes 0003 상태에 프로젝트 P와 비공개 팀 X가 모두 지정된 확정 회의록 N을 넣는다. U는 P의 프로젝트 관리자지만 X의 멤버는 아니다. 이전 규칙에서는 U가 N을 볼 수 없다. notes 0004 실행 후 N의 Doc는 `project_id=P,team_id=None`이며 U가 볼 수 있다.
- 관찰: `migration_before_project_allowed=True team_allowed=False`, `migration_after_visible=True project_id=3 team_id=None`.
- 영향: 운영 데이터가 이전과 동시에 더 넓은 사람들에게 공개된다. 이 동작은 기존 테스트 `core/notes/test_migrate_doc.py:95`에서도 새 team null을 기대하여 누출을 검출하지 못한다.
- 권장 수정: 기존 교집합 제한을 보존할 별도 ACL 또는 회의록 전용 다중 범위를 둔다. 지원하지 못하는 양쪽 범위 행이 있으면 사전 점검으로 마이그레이션을 중단하고 명시적 관리자 결정을 받는다. 무조건 팀을 제거하지 않는다.

## R4 — 상: 상위 완료와 하위 재개·생성 경쟁이 불변식을 깨뜨림

- 근거: `core/tasks/services.py:851`~`:860`에서 상위의 열린 하위 수 및 하위의 상위 상태를 읽지만, `transition`은 공통 상위 행을 잠그지 않는다. `:860`은 이미 캐시된 `task.group` 객체도 사용한다. 쓰기는 `:917`→`:216`의 **변경 대상 한 행의 version**만 검사한다. `create_task`/`set_group`의 상위 잠금과도 같은 잠금 규약을 공유하지 않는다.
- 재현: 열린 상위 G 아래 S를 완료한다. `stale=Task.objects.select_related('group').get(pk=S.pk)`로 열린 G를 캐시한다. 다른 요청처럼 G를 완료한다. 그 뒤 `transition(stale,'todo',expected_version=stale.version,actor=admin,source='web')`이 성공한다. S 자체 version은 바뀌지 않아 충돌이 없다.
- 관찰: `cached_top_before=todo`, 최종 `G.status=done`, `S.status=todo`.
- 영향: 순차 호출의 오래된 상위 캐시로도 재현된다. Postgres 두 요청이 각각 열린 G/닫힌 S를 검사한 다음 서로 다른 행을 갱신하는 경쟁에도 같은 문제가 있다. 웹·API·MCP·Discord·GitHub 모두 같은 서비스에 의존한다.
- 권장 수정: 상위 닫기·하위 재개·하위 생성/넣기·상위 이동에서 관련 행을 같은 순서로 잠그고, 잠금 뒤 최신 관계와 상태를 다시 검사한다. Postgres의 별도 연결 두 개와 barrier로 재개↔완료 및 생성↔완료를 검증한다. 새로 조회만 하는 것으로 경쟁을 해결하지 않는다.

## R5 — 중: 숨긴 상위의 번호가 API·이력·Discord에 남음

- 근거: `core/tasks/brief.py:53`은 viewer와 무관하게 `group_id`를 반환한다. `core/api/serialize.py:73`의 `group:null`만으로 숨김이 끝나지 않는다. `core/api/routers/tasks.py:275`→`core/api/serialize.py:17`은 raw ChangeLog old/new 값 전체를 반환한다. `discord_service/discord_service/messages.py:37`은 group_id로 `↳ TASK-N`을 만든다. MCP `get_task`/`get_task_history`는 이 응답을 그대로 받는다(`mcp_server/mcp_server/server.py:396`, `:543`).
- 재현: 비공개 주 프로젝트의 G·S 중 S에만 공개 프로젝트 연결을 승인한다. U의 `/api/tasks/S`는 `group:null`이지만 `group_id=G.pk`를 반환한다. `/api/tasks/S/history`에도 `field=group,new_value=TASK-G`가 남는다.
- 관찰: `group_json=None group_id=3 top_visible=False`, `group_history=[('group','TASK-3')]`.
- 권장 수정: brief/serializer에 viewer를 전달해 숨긴 상위의 ID도 null로 내고, 이력의 group/split 참조를 viewer별로 가린다. 봇 공개 응답에서도 상위 태스크 자체의 공개 가시성을 검사한다. 웹 이력의 `_display`는 일부 숨김을 이미 수행하지만 API에는 적용되지 않는다(`core/web/views/common.py:240`).

## R6 — 중: 문서·회의록 응답의 task_ids가 비공개 태스크 존재를 공개

- 근거: `core/api/routers/docs.py:42`와 `core/api/routers/notes.py:37`의 `task_ids`는 연결 관계 전체다. document/note serializer에는 viewer 인자가 없다. 웹의 extras는 `visible_tasks(user)`로 걸러 서로 동작이 다르다(`core/web/views/docs.py:99` 인근).
- 재현: 관리자가 조직 전체 Doc D를 같은 조직의 비공개 태스크 T와 연결한다. U는 D를 볼 수 있지만 T를 볼 수 없다. U의 `GET /api/project-docs/D`가 200과 `task_ids=[T.pk]`를 반환한다.
- 관찰: `doc_response=200 task_ids=[2] hidden_task_visible=False`.
- 권장 수정: doc_out/note_out에 viewer를 전달하고 가시 태스크만 직렬화한다. 목록·단건·생성/수정 응답·409 최신 문서 응답에도 일관되게 적용한다.

## R7 — 중: GitHub 선택기가 숨겨진 연결 프로젝트·저장소 이름을 노출

- 근거: `core/tasks/services.py:1833`~`:1839`의 `git_project_choices`는 연결 프로젝트 전체를 대상으로 하고 viewer 검사가 없다. `core/web/views/tasks.py:70`에서 패널에 전달하며 `core/web/templates/tasks/_git.html:13`에서 프로젝트 이름·저장소 full_name을 출력한다. 별도의 `linked_projects`는 viewer 필터를 적용하므로 그 숨김을 우회한다.
- 재현: 공개 주 프로젝트 T에 비공개 프로젝트 Q를 연결한다(태스크는 이미 공개라 확대 없음). Q에 `RepoConnection(full_name='secret/repo')`를 둔다. `GITHUB_ENABLED=True`, 주 프로젝트 dev_tools=True인 상태에서 Q를 못 보는 U가 `/tasks/T`를 연다.
- 관찰: `private_project_visible=False linked_projects=[] web_status=200 hidden_project_name_in_html=True hidden_repo_in_html=True`.
- 권장 수정: `git_project_choices(task,viewer)`로 바꾸어 `visible_projects(viewer)`와 저장소 접근 규칙으로 후보를 거른다. 선택하지 못하는 프로젝트 ID·저장소 정보를 응답의 다른 GitHub 블록에서도 점검한다.

## R8 — 중: 조직 현황·주간 보고의 프로젝트별 집계가 상위를 더 센다

- 근거: `core/reports/services.py:41`~`:59`의 `_per_project`는 직접 `Task.objects`를 사용하여 leaf_only를 적용하지 않는다. 조직 현황 `:94`와 주간 보고 `:237`이 이 함수를 호출한다. 프로젝트 개별 stats는 leaf_only를 적용한다(`core/projects/services.py:507`).
- 재현: 프로젝트 1개에 열린 상위 1개와 하위 2개만 둔다. 일반 멤버 기준 `project_stats(P).open=2`, `org_status.counts.open=2`지만 `org_status.by_project[0].open=3`, `weekly.by_project[0].open=3`이다.
- 영향: 동일 화면의 합계와 프로젝트별 지표가 어긋나며 Discord 보고도 같은 보고 서비스 결과를 받는다.
- 권장 수정: `_per_project`의 두 queryset에 leaf_only를 동일 적용한다. 조직 counts뿐 아니라 by_project·weekly.by_project를 직접 검증한다.

## R9 — 중: ZIP 가져오기 상한을 압축 해제 이후/ZIP별로만 검사

- 근거: `core/projects/docs.py:635`의 20MB 검사는 한 ZIP에만 적용된다. `:637`에서 모든 md를 먼저 해제해 raw_entries에 누적하고 `:642`에서야 500개 상한을 검사한다. 개별 256KB 검사도 그 뒤 `:651`→`:465`다. 웹/API는 업로드 전체를 먼저 `read()`한다(`core/web/views/docs.py:277`, `core/api/routers/docs.py` import_docs).
- 재현 A: md 501개 ZIP을 만들고 `ZipFile.read`를 spy로 감싼다. 500개 상한으로 거절되지만 `read` 호출이 이미 501회다.
- 재현 B: 동일 로직의 `ZIP_MAX_TOTAL`만 1000바이트로 축소해 서로 다른 600바이트 md ZIP 두 개를 한 요청으로 가져오면 1200바이트 합계를 허용한다. 기본값에서도 ZIP별 허용 크기의 합계가 요청 총량 상한을 넘을 수 있다.
- 관찰: `zip_read_before_501_file_rejection=501`, `zip_total_1200_limit_1000_accepted=2`.
- 권장 수정: 모든 파일의 metadata를 먼저 모아 요청 전체 파일 수·비압축 총량·개별 file_size를 확인한다. 압축 해제는 스트리밍·읽기 한도로 수행하고 압축 입력 자체에도 상한을 둔다. 500개 거절은 실제 본문 read 전에 끝나야 한다.

## 결함으로 확정하지 않은 경로와 확인 불가

- 기본 pending 가시성: `visible_tasks`/`project_q`/SSE가 active 연결만 사용한다(`core/tasks/services.py:232`, `:249`, `core/web/views/events.py:76`). 새로 연결한 pending 프로젝트의 열람자는 기본 조회에서 제외된다. 승인·거절은 can_approve_widening을 지나고 MCP source는 금지한다(`core/tasks/services.py:1624`, `:1728`). 직접 PATCH group_id는 set_group으로 전달되며 일반 update_task의 편집 가능 필드에는 group이 없다. 이번 검토에서 별도의 승인 우회는 확정하지 않았다.
- 백링크 본문 스캔은 가시 문서·태스크에 먼저 제한된다(`core/projects/docs.py:429`, `:442`). ZIP 내보내기도 visible_docs를 사용하고 숨긴 부모를 경로에 넣지 않는다(`:504`, `:515`). 직접 첨부 다운로드는 can_view_doc/can_view_task를 사용한다. 다만 R2·R3 이후에는 이 관문 자체의 가시성 결과가 확대된다.
- md는 파일시스템에 추출하지 않고 본문을 저장하므로 실제 디스크 zip slip 경로는 발견하지 않았다. 상대 md 링크 대상은 이번 import의 made 목록에서만 찾는다(`core/projects/docs.py:687`, `:604`); 다른 조직 문서를 조회해 자동 연결하는 경로는 발견하지 않았다.
- 클라이언트 렌더러는 DOM 생성과 textContent를 사용하고 safeUrl이 javascript/data scheme을 거절한다(`core/web/static/notes.js:15`, `:81`). 정적 코드 점검에서 실행 가능한 XSS는 확정하지 않았다. 실제 브라우저 자동화로 악성 md를 실행해 보지는 않았다.
- projects 0012의 기존 Doc ID·M2M·본문은 RenameModel로 유지하며 revision을 시드한다. notes 0004의 본문·시각·작성자·참여자·태스크 연결·녹음 보존은 기존 migration test도 통과했다. **공개 범위 보존은 R3 때문에 실패**한다.
- notes 0004는 회의록이 있으면 backward에서 복구를 거절한다(`core/notes/migrations/0004_merge_into_doc.py:63`). 운영 데이터가 있는 상태의 전체 downgrade·백업 복구는 실행하지 않았다. projects 0012와 tasks 0012도 RunPython 역방향이 noop이므로 신규 템플릿/조직 문서 및 변환된 parent·체크리스트의 원상복구를 보장하지 않는다. 배포 롤백 수단은 사전 백업 복구로 명시해야 한다.
- 운영 Postgres 연결·SQL 실행·경쟁 트랜잭션·실제 운영의 양쪽 범위 회의록 건수는 확인 불가다. R4는 SQLite에서 캐시된 상위 상태로 실제 위반을 재현했으며 Postgres 동시 실행 자체는 하지 않았다.

## 재현 환경의 공통 시작 코드

아래를 core 작업 디렉터리에서 PowerShell here-string으로 `uv run python -`에 전달했다. 운영 DB 이름이나 환경을 사용하지 않고 `django.setup()` 전에 DB를 메모리 DB로 바꿨다. 각 재현 프로세스는 종료와 함께 DB가 사라졌다.

```python
import os
os.environ['DJANGO_SETTINGS_MODULE'] = 'config.settings'
from django.conf import settings
settings.DATABASES = {'default': {'ENGINE': 'django.db.backends.sqlite3', 'NAME': ':memory:'}}
settings.ALLOWED_HOSTS = ['testserver']
import django
django.setup()
from django.core.management import call_command
call_command('migrate', verbosity=0)
```

일반 사용자와 조직은 `User.objects.create_user`, `create_org`, `OrgMembership(role='member')`로 만들었고, 비공개 프로젝트는 `create_project(..., visibility='teams', owners=[admin])`로 만들었다. API 재현은 `ApiToken.issue(user,'review','read',for_ai=False)` 및 Django `Client(HTTP_AUTHORIZATION='Bearer '+raw)`를 사용했고 웹 재현은 같은 사용자를 force_login했다. 상태 경쟁 재현은 다음 순서다.

```python
# G와 S는 열린 상위와 그 하위. 배우는 같은 관리자.
ts.transition(S, 'done', actor=admin, source='web', expected_version=S.version)
stale = Task.objects.select_related('group').get(pk=S.pk)
ts.transition(G, 'done', actor=admin, source='web', expected_version=G.version)
ts.transition(stale, 'todo', actor=admin, source='web', expected_version=stale.version)
G.refresh_from_db(); S.refresh_from_db()
assert (G.status, S.status) == ('done', 'todo')  # 현재 코드에서 성립하는 불변식 위반
```

마이그레이션 재현은 빈 최신 DB를 notes 0003으로 되돌린 뒤 historical MeetingNote로 project/team 양쪽 범위의 행을 넣고 notes 0004로 전진했다. 기존 파일·실제 데이터베이스·브랜치에는 쓰지 않았다.

