---
name: pm-start
description: 태스크 착수. 인자로 받은 태스크나 이슈, 또는 대화 내용에 맞는 태스크를 찾거나 만들어 거버넌스·결정 기록을 읽고, 미결정 사항을 묻고, doing으로 바꾸고 브랜치를 정한다.
argument-hint: "[TASK-N | #이슈번호]"
disable-model-invocation: true
---

# 태스크 착수

`../pm/SKILL.md`를 이 세션에서 읽지 않았다면 먼저 읽는다(호출법·공통 규칙·태스크 만들기 절차).

인자: $ARGUMENTS

## 1. 대상 태스크 정하기

- **`TASK-N`**: `GET /api/tasks/N`.
- **`#N`(이슈 번호)**: 프로젝트를 정한 뒤(모르면 현재 저장소 이름과 `GET /api/projects/{id}/repo`로 맞춰 보고 확인받는다)
  `POST /api/projects/{id}/issues/{N}/import`. 이미 가져온 이슈면 기존 태스크가 200으로 온다.
  새로 가져오면 담당자는 나, 기한은 비어 있다(4단계에서 정한다).
- **인자 없음**: 지금까지의 대화에서 하려는 작업을 한두 문장으로 요약한다. 요약할 게 없으면 무엇을 할지 묻고 멈춘다.
  1. 내 열린 태스크(`GET /api/tasks?assignee=<내 id>&status=todo,doing,paused,blocked,review`)와
     핵심어 검색(`q=`)으로 후보를 찾는다. 연결된 이슈 제목도 비교한다.
  2. 후보가 있으면 번호·제목·상태·기한을 보여 주고 고르게 한다. 목록 끝에 "새로 만들기"를 둔다.
  3. 후보가 없거나 "새로 만들기"면 `../pm/SKILL.md`의 "태스크 만들기" 절차로 만든다.
     이때 반드시 묻는다: **(a) GitHub 이슈를 만들고 그 이슈를 태스크로 연결해 진행 / (b) 태스크만 만들어 진행.**
     저장소가 연결되지 않은 프로젝트면 (a)를 빼고 그 이유를 한 줄로 알린다.
     제안하는 제목·프로젝트·완료 조건을 같은 질문에 함께 보여 준다.

## 2. 읽기

- `GET /api/orgs/{org}/governance`, `GET /api/orgs/{org}/settings` (세션에서 이미 읽었으면 생략)
- `GET /api/tasks/{id}` — 목표·완료 조건·체크리스트·메모·기한
- `GET /api/tasks/{id}/github` — 연결된 이슈의 최신 본문
- `GET /api/tasks/{id}/decisions` — 이미 정해진 것
- 관련 프로젝트 문서가 있으면 `GET /api/project-docs?project=`

## 3. 미결정 사항 묻기

구현에 실질적인 영향을 주는데 아직 정해지지 않은 것만 모아 **한 번에** 묻는다(형식은 `../pm/SKILL.md`).
이미 정해진 것은 다시 묻지 않는다. 답을 받으면 `/pm-decide`의 규칙대로 요지를 기록한다.

## 4. 착수

1. 기한이 없으면 먼저 정한다. 거버넌스가 요구하면 확인받고 `PATCH`로 `due_date`를 넣는다.
2. 담당자가 내가 아니면 바꿀지 확인받는다. 임의로 바꾸지 않는다.
3. `POST /api/tasks/{id}/transition` `{"status": "doing", "version": <최신>}`.
4. 브랜치 이름을 제안한다. 조직·저장소 규칙이 있으면 그것을, 없으면 `task-<N>-<짧은-영문-요지>`.
   지금 작업 폴더가 그 저장소면 브랜치를 만들지 묻는다.
5. 태스크의 `next_action`을 첫 작업으로 삼아 한 줄로 보고한다: `TASK-N 착수 — <다음 행동>`.
