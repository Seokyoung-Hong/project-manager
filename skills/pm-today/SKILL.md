---
name: pm-today
description: 지금 작업 중인 프로젝트에서 내 오늘 할 일과 밀린·막힌 태스크를 요약하고 다음 행동을 추천한다. "오늘 뭐 해야 해", "내 할 일" 같은 요청에 쓴다. 읽기만 한다.
argument-hint: "[프로젝트 이름 | 전체]"
---

# 오늘 할 일

`../pm/SKILL.md`를 이 세션에서 읽지 않았다면 먼저 읽는다. 이 명령은 읽기만 한다.

1. `../pm/SKILL.md`의 "작업 범위"대로 조직·프로젝트를 정한다(인자: $ARGUMENTS). 인자가 "전체"일 때만 그 조직의 모든 프로젝트를 본다.
2. 읽기(목록은 조직 경로, `project` 포함):
   - `GET /api/today` — 오늘 목록. 여러 조직·프로젝트가 섞여 오므로 **범위 밖 항목은 버린다**
   - `GET /api/orgs/{org}/tasks?project=&assignee=<내 id>&status=todo,doing,paused,blocked,review&due_to=<오늘>` — 오늘까지 기한
   - `GET /api/orgs/{org}/tasks?project=&assignee=<내 id>&status=blocked,paused` — 멈춘 것
   - `GET /api/requests?box=received&status=pending` — 내가 답할 요청. 건수와 `REQ-N 제목 — 보낸 사람`만 보여 준다(답은 사람이 한다)
   - 범위 밖에 기한 넘김이 있으면 건수만 한 줄로 알린다(`/api/today`의 `counts`). 내용은 보여 주지 않는다.
3. 요약(짧게, 서버가 준 값만):
   - **오늘**: `TASK-N 제목 — 다음 행동`
   - **기한 넘김**: 며칠 넘었는지
   - **멈춤**: 멈춘 사유
   - **답할 요청 N건**: 0건이면 줄을 빼고, 있으면 번호·제목·보낸 사람
   - **검토 대기**(`review`): 누가 확인해야 하는지
   - 하위 태스크는 상위와 함께 보인다(`group_id`가 있으면 "↳ TASK-N"으로 상위를 밝힌다).
4. 다음 행동 추천 한두 개와 이유. 기한 넘김·막힘 해소를 먼저 권한다.
   바꿀 일이 보이면(기한 연장, 상태 정리) 직접 바꾸지 말고 `/pm-triage`나 구체적인 요청을 제안한다.
