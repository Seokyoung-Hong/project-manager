---
name: pm-done
description: 태스크 마무리. 빠진 결정 기록과 체크리스트를 점검하고, 진행 메모를 남기고, review로 넘긴다. done은 확인하는 사람이 바꾼다.
argument-hint: "[TASK-N]"
disable-model-invocation: true
---

# 태스크 마무리

`../pm/SKILL.md`를 이 세션에서 읽지 않았다면 먼저 읽는다.
작업 범위(조직·프로젝트)를 먼저 정하고 그 범위의 태스크만 다룬다(`../pm/SKILL.md` "작업 범위").

대상: $ARGUMENTS (비어 있으면 이 세션의 `TASK-N`. 없거나 여럿이면 묻는다.)

## 흐름

1. `GET /api/tasks/{id}`, `/decisions`, `/github`을 읽는다.
2. **점검** (한 목록으로 보여 준다):
   - 완료 조건을 이번 작업이 채웠는가 — 근거(변경·테스트)를 한 줄씩. 채우지 못했으면 무엇이 남았는지.
   - 체크리스트 중 끝났는데 표시 안 된 것 / 안 끝난 것
   - 이번 세션의 결정 중 기록되지 않은 것 → 있으면 `/pm-decide` 흐름을 먼저 제안한다
   - PR이 있는가(`github.pull_request`). 없으면 `/pm-pr`을 제안한다
   - 범위 밖으로 미룬 일 → `/pm-followup` 제안
3. **확인**: 체크리스트 갱신, 남길 진행 메모 한 줄(무엇을 끝냈고 어디서 확인하는지), review로 넘길지를 한 번에 묻는다.
   완료 조건을 못 채웠으면 review 대신 그대로 두기를 권한다.
4. **반영**: 체크리스트·메모는 `PATCH`(최신 `version`, 메모는 덧붙이기), 그다음
   `POST /api/tasks/{id}/transition` `{"status": "review", "version": <최신>}`.
   **`done`으로 바꾸지 않는다.** 거버넌스가 작성자 완료를 명시적으로 허용하고 사용자가 요청할 때만 예외.
5. 보고: `TASK-N → review`, 확인할 사람(프로젝트 관리자 등 거버넌스 기준).
