---
name: pm-decide
description: 이번 세션의 사용자 결정과 AI의 중요한 판단을 요지로 정리해 태스크의 결정 기록으로 남긴다. 기존 기록과 중복을 확인하고, 남기기 전에 목록을 확인받는다.
argument-hint: "[TASK-N]"
disable-model-invocation: true
---

# 결정 기록

`../pm/SKILL.md`를 이 세션에서 읽지 않았다면 먼저 읽는다. 특히 "결정 기록" 규칙을 그대로 따른다.

대상: $ARGUMENTS (비어 있으면 이 세션에서 다룬 `TASK-N`. 없거나 여럿이면 묻는다.)

## 흐름

1. `GET /api/orgs/{org}/settings`에서 `ai.record_work`가 막혀 있으면 기록할 수 없다고 알리고 멈춘다.
2. `GET /api/tasks/{id}/decisions`로 이미 있는 기록을 읽는다.
3. 이번 세션을 훑어 후보를 뽑는다.
   - 사용자가 직접 답하거나 지시한 것 → `user_input`, `explicit_reply`/`explicit_instruction`
   - AI가 맥락에서 추론한 사용자 선택 → `user_input`, `inferred` (확인 전까지 제안 상태)
   - AI가 사용자 결정 없이 내린 중요한 기술·구현·운영 판단 → `ai_judgment`
   - 구현에 의미 없는 잡담·사소한 세부는 뺀다. 기존 기록과 같은 내용은 뺀다.
     바뀐 결정은 새로 쓰고 이전 기록 id를 `supersedes_id`로 잇는다.
4. **확인**: 표로 보여 준다 — 종류, 요지, 이유, 근거(명시 답변·명시 지시·추론·AI 판단), 대체하는 기록.
   **대화 원문을 옮기지 않았는지** 스스로 점검한 뒤 보여 준다. 수정·제외를 받는다.
5. **기록**: 건마다 `POST /api/tasks/{id}/decisions`. 본문에 `client_request_id`(예: `dec-<id>-<YYYYMMDD>-<순번>`)를 넣고
   같은 값을 `--key`로 준다. 입력 스키마는 `PM spec /decisions`로 확인한다. `client_name`은 `"claude-code"`.
6. 보고: 기록한 건수와 상태(`captured`·`proposed` 등 응답 값 그대로).
