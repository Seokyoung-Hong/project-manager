---
name: pm-triage
description: 기한 넘김·막힘·기한 없는 진행 중 태스크를 모아 정리안을 만들고, 확인받아 일괄 반영한다. "밀린 것 정리", "막힌 것 정리"에 쓴다.
argument-hint: "[프로젝트 이름 | 조직 전체]"
disable-model-invocation: true
---

# 밀린 것 정리

`../pm/SKILL.md`를 이 세션에서 읽지 않았다면 먼저 읽는다.

범위: $ARGUMENTS (비어 있으면 `../pm/SKILL.md`의 "작업 범위"로 정한 **현재 프로젝트**. 담당자는 가리지 않는다. 조직 전체는 사용자가 명시하고 그 권한이 있을 때만.)

## 흐름

1. 거버넌스·설정을 읽는다. AI가 바꿀 수 없는 항목(`ai.*`)은 정리안에서 "사람이 할 일"로 분리한다.
2. 모은다(`GET /api/tasks?org=&project=` — 둘 다 항상 넣는다):
   - 기한 넘김: `status=todo,doing,paused,blocked,review&due_to=<어제>`
   - 막힘·멈춤: `status=blocked,paused`
   - 기한 없는 진행 중: `status=doing` 중 `due_date`가 빈 것
   - 오래 검토 대기: `status=review` 중 오래된 것(이력 `GET /api/tasks/{id}/history`로 확인)
3. 건마다 제안 하나: 기한 연장(새 날짜·사유), 상태 변경(사유), 담당 확인 요청, 분할(`/pm-split`), 취소 제안.
   근거가 없는 날짜·사유를 지어내지 않는다. 모르면 "사용자 입력 필요"로 둔다.
4. **표로 확인**: `TASK-N | 문제 | 제안 | 바꿀 값`. 사용자가 고른 건만 반영한다.
5. 반영: 기한은 `POST /api/tasks/{id}/extend`, 상태는 `/transition`, 그 밖은 `PATCH`. 모두 최신 `version`.
   409가 나면 그 건만 다시 읽고 다시 확인받는다.
6. 보고: 반영한 건, 건너뛴 건과 이유, 사람이 할 일.
