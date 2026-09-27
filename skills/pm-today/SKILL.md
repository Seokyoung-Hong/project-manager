---
name: pm-today
description: 내 오늘 할 일과 밀린·막힌 태스크를 요약하고 다음 행동을 추천한다. "오늘 뭐 해야 해", "내 할 일" 같은 요청에 쓴다. 읽기만 한다.
argument-hint: "[조직 이름]"
---

# 오늘 할 일

`../pm/SKILL.md`를 이 세션에서 읽지 않았다면 먼저 읽는다. 이 명령은 읽기만 한다.

1. `GET /api/me`로 내 id와 조직. 조직이 여럿이면 인자($ARGUMENTS)나 대화로 고르고, 없으면 전부 본다.
2. 읽기:
   - `GET /api/today` — 오늘 목록(사용자가 웹에서 고른 것 포함)
   - `GET /api/tasks?assignee=<내 id>&status=todo,doing,paused,blocked,review&due_to=<오늘>` — 오늘까지 기한
   - `GET /api/tasks?assignee=<내 id>&status=blocked,paused` — 멈춘 것
3. 요약(짧게, 서버가 준 값만):
   - **오늘**: `TASK-N 제목 — 다음 행동`
   - **기한 넘김**: 며칠 넘었는지
   - **멈춤**: 멈춘 사유
   - **검토 대기**(`review`): 누가 확인해야 하는지
4. 다음 행동 추천 한두 개와 이유. 기한 넘김·막힘 해소를 먼저 권한다.
   바꿀 일이 보이면(기한 연장, 상태 정리) 직접 바꾸지 말고 `/pm-triage`나 구체적인 요청을 제안한다.
