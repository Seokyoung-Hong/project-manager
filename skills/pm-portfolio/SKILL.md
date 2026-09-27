---
name: pm-portfolio
description: 내 확인된 결정 기록을 근거로 비공개 개인 포트폴리오 초안을 쓴다. 출처를 고르고, 근거를 연결하고, 추측을 넣지 않는다.
argument-hint: "[주제·기간·프로젝트]"
disable-model-invocation: true
---

# 포트폴리오 초안

`../pm/SKILL.md`를 이 세션에서 읽지 않았다면 먼저 읽는다.

요청: $ARGUMENTS

1. `GET /api/me/portfolio-sources`로 본인의 `captured`·`confirmed` 기록과 프로젝트 맥락을 읽는다(필터는 `PM spec /portfolio`).
   다른 사람의 입력이나 AI 판단을 사용자의 결정으로 귀속하지 않는다.
2. 쓸 출처를 목록으로 보여 주고 고르게 한다.
3. 초안: 고른 출처만 쓴다. 기록의 요지, 태스크·프로젝트, 시점, 확인 수준을 근거로 잇는다.
   `captured`는 "세션에서 수집한 입력", 확인 기록은 그 확인 수준을 그대로 표시한다. AI 판단은 AI 판단으로 적는다.
   사용자가 밝히지 않은 이유·역할·성과·숙련도·날짜를 추측해 넣지 않는다.
4. 확인받은 뒤 `POST /api/me/portfolio-drafts`로 **비공개 초안**을 저장하고, 원하면
   `GET /api/me/portfolio-drafts/{id}/markdown`으로 Markdown을 준다. 공개 페이지나 블로그에 직접 게시하지 않는다.
