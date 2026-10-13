# 전사 용어집 · 임시 문구 모음

2026-10-13 core 구현에서 넣은 **임시 문구**다. 최종 문구는 다른 모델이 이 표를 보고 정해 해당 위치를 바꾼다.
위치의 코드·템플릿에는 같은 키가 `# COPY:키` / `{# COPY:키 #}` 주석으로 붙어 있다(`grep -rn "COPY:.*glossary" core`).
말투: 격식체("…입니다", 요청만 "…해 주세요"). 줄 번호는 커밋 시점 기준(바뀌면 키로 찾는다).

| 키 | 위치 | 임시 문구 | 맥락 |
|---|---|---|---|
| setting_glossary_label | core/orgs/settings.py:821 | 전사 용어집 | 조직 설정·프로젝트 설정 "회의 녹음" 묶음의 항목 이름 |
| setting_glossary_help | core/orgs/settings.py:822 | 전사 정확도를 높이려고 전사 서버에 미리 알려 주는 용어입니다. 쉼표나 줄바꿈으로 구분해 주세요. 프로젝트 설정의 용어는 조직 용어와 합쳐지며 프로젝트 용어가 먼저 들어갑니다. 참여자·구성원 이름 다음, 자동으로 뽑은 용어보다 먼저 들어가고, 한도를 넘는 용어는 빠집니다. | 같은 항목 도움말. 조직·프로젝트 화면이 같은 문구를 쓴다. 조직 화면의 "프로젝트 변경 허용"은 이 항목에서 "프로젝트가 용어를 더할 수 있음"이라는 뜻 |
| menu_glossary_label | core/web/templates/orgs/_glossary_field.html:2 | 이번 전사 용어집 | 전사 메뉴 다시 전사 패널·회의록 화면 [전사 시작] 폼의 입력칸 라벨 |
| menu_glossary_help | core/web/templates/orgs/_glossary_field.html:4 | 전사 서버에 미리 알려 줄 이름과 용어입니다. 쉼표나 줄바꿈으로 구분해 주세요. 비우면 용어집 없이 전사합니다. 한도를 넘으면 전사를 시작하지 않습니다. | 입력칸 아래 도움말. 미리 채운 값은 요청자가 볼 수 있는 자료로만 만든다 |
| menu_glossary_dropped | core/web/templates/orgs/_glossary_field.html:4 | 한도를 넘어 빠진 용어: {용어, …} | 미리 채울 때 이름·직접 입력 용어가 한도(224토큰)를 넘어 빠졌을 때만 |
| glossary_too_long | core/notes/transcription.py:816 | 용어집은 {GLOSSARY_MAX}자를 넘을 수 없습니다. | 고친 값이 1000자 초과(입력칸 maxlength와 같은 값) |
| glossary_over_budget | core/notes/transcription.py:822 | 용어집이 전사 서버 한도를 넘습니다. 다음 용어를 빼거나 줄여 주세요: {용어, …} | 고친 값이 224토큰을 넘으면 작업을 만들지 않는다. 패널은 고친 값을 칸에 남긴다 |
