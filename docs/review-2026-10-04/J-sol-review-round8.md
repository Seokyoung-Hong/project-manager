- **판정: 반려.** HEAD `fed48c3`, G1·G4·G5′와 겹치는 G2/G8/G9 경로를 교차 검토했다. 코드·git 변경 없음. `core: uv run pytest -q` 1,353개 통과(40.94초), `discord_service: uv run pytest -q tests/test_github_hooks.py` 4개 통과. 별도 메모리 SQLite DB에서 아래 1~5를 재현했다.

- **결함 1 / 상 — 저장소 접근 권한 없이 릴리스 노출.** `core/web/views/roadmap.py:77`, `core/web/templates/orgs/roadmap.html:18`. 프로젝트는 볼 수 있지만 GitHub 미연결인 조직 멤버로 로드맵 조회 → `PRIVATE_TAG`, 릴리스 이름·URL이 응답 컨텍스트에 포함됨. 선반의 `releases_for`와 달리 `repo_state==ok` 검사가 없다(`core/github/sync.py:104`, 설계 `docs/IMPL-PLAN-8.md:392`). 권장: 저장소 가시성 통과 프로젝트의 릴리스만 로드맵에 주입.

- **결함 2 / 중 — 재개 DM 두 통.** `core/github/services.py:1209`, `:1252`; `core/tasks/services.py:321`. 원 담당자와 다른 관리자가 닫힌 PR을 재개 → 복제 생성의 담당 지정 DM + 담당 요청 DM, `Notice` 2개. 권장: 재개 복제의 기본 지정 알림을 억제하고 담당 요청 한 통으로 통합. 현재 테스트는 존재만 확인(`core/github/test_pr_round8.py:260`).

- **결함 3 / 중 — PR 제목 변경으로 기존 연결 상실.** `core/github/services.py:973`. 연결된 PR에서 TASK 번호를 제목에서 삭제(본문·브랜치에도 없음) → `edited` 캐시 미갱신, 이후 merged도 태스크가 `review`에 남음. 권장: 기존 `connection+pr_number` 링크 우선, 최초 연결에만 번호 탐색(설계 `docs/IMPL-PLAN-8.md:281`).

- **결함 4 / 중 — 오래된 리뷰가 최신 승인 덮어씀.** `core/github/services.py:1137`, `:1143`. 동일 리뷰어의 10/5 승인 뒤 지연된 10/4 변경 요청 수신 → `changes_requested` 및 `doing` 전환. 권장: 리뷰어별 review id·시각 저장, 역순 이벤트 거부; 연결/링크 잠금으로 동시 JSON 갱신 유실도 방지.

- **결함 5 / 상 — 설정 중 취소가 무시됨.** `core/github/hooks.py:300`, `:326`. GitHub POST 진행 중 pending을 취소해 DB `{}`로 변경 → 완료 콜백이 오래된 상태를 `active`로 되살림. 작업 식별자 없이 project_id만 써 취소 후 재설정에도 오래된 콜백이 적용됨(`:275`, `:293`). 권장: 요청 세대 식별자·상태 조건부 갱신, 취소된 생성의 양쪽 훅 보상 삭제.

- **결함 6 / 중 — 성공 응답 유실 시 영구 고장.** `discord_service/discord_service/github_hooks.py:40`, `:43`; `core/github/hooks.py:295`, `:326`. core가 GitHub 등록·active 저장 후 응답만 유실 → 봇이 Discord 훅 삭제, PM은 active 유지·재시도 작업 없음. 권장: 동일 작업/id로 결과 재조회·멱등 보고 후 삭제 결정; 양쪽 삭제를 내구성 있는 작업으로 유지.

- **근거:** 사용자 토큰 쓰기(`core/github/writes.py:41`, `core/github/hooks.py:314`), 봇 전용 인증(`core/api/routers/discord.py:61`), 리뷰어 가시성 검사(`core/tasks/services.py:198`), 연결별 atomic(`core/github/services.py:676`)는 확인됨. 이슈 양방향 동기화 취소는 설계 §10 적용(`docs/IMPL-PLAN-8.md:542`).

- **확인 불가:** 실제 GitHub/Discord 권한·웹훅 동작, 운영 로그의 비밀 비노출, 다중 프로세스 동시 reopen 중복 생성은 실환경 미검증. 재개 열린 링크 조회에는 잠금·원자적 고유 제약이 없어 동시 생성 방지는 입증되지 않음(`core/github/services.py:1189`).
