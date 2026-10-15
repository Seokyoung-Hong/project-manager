# 유달리 디자인 시스템 — 03 「모여서, 한 걸음」 · 장식 강

토큰·규칙·이유를 이 파일 하나에 둔다. 값의 기준은 `core/web/static/app.css`이고, 이 문서의 토큰 이름·값은 그 파일과 1:1이다
(`core/web/test_design_system.py`가 app.css의 모든 토큰이 여기 적혀 있는지 검사한다). 실제 렌더링 견본은 staff 전용
**`/ops/design`**(운영 콘솔 → 디자인 시스템)에서 본다. 그 화면의 토큰 표는 app.css를 직접 읽어 그린다.

확정: 2026-10-05 사용자 결정(1차 시안 03 · 장식 강). 이전 TASK-41 teal 규칙은 이 문서로 대체됐다(git 이력에 남아 있다).

## 목차

1. 원칙 · 2. 토큰 · 3. 컴포넌트 · 4. 업무 부품 · 5. 그림·장식 · 6. 연동 화면 패턴 · 7. AI Slop 금지 규칙 ·
8. 접근성 · 9. 반응형 · 10. 다크 모드 · 11. 새 화면 체크리스트 · 12. 용어표

---

## 1. 원칙

**성격.** 작은 팀의 작업실. 크림 바탕에 세이지·노랑·코랄 색면, 동글동글한 Jua 제목, 표정 있는 화분과 테이프 붙인 메모로
손맛을 낸다. 그래도 **업무가 먼저 읽힌다** — 장식은 업무를 감싸지, 덮지 않는다.

**장식 '강'을 쓰는 곳**

| 쓰는 곳 | 무엇을 |
|---|---|
| 오늘 화면 머리 | 맨 위 코랄 메모(지금 할 한 가지)와 노란 집계 면. 환영 슬로건·큰 화분은 두지 않는다(매일 볼 필요가 없다 — 슬로건은 로그인·랜딩에 있다) |
| 프로젝트 | 대표 지표 세이지 면, 위험 지표 코랄 면, 결과 선반(책·체크 그림) |
| 페이지 제목 | `.page-head > h1` 아래 노란 붓질 |
| 빈 상태 | 화면에서 가장 큰 빈 목록 하나에만 화분(76px) |
| 완료 순간 | 새싹 알림 3초 |
| 인증 화면 | 로그인 카드 위 작은 화분 |

**쓰지 않는 곳**: 입력 폼·설정·표·연동 관리 화면의 본문(색면·화분을 반복하지 않는다), 같은 화면에 두 번째 메모,
모든 카드, 작은 빈 상태(`.empty.compact`), 달력 빈 날짜.

**왜:** 장식을 아무 데나 반복하면 '강'이 아니라 소음이 된다. 한 화면에 초점 장식은 하나, 나머지는 색과 타이포로 성격을 낸다.

---

## 2. 토큰

모든 값은 `:root`에 있다(다크 값은 `prefers-color-scheme: dark`, 10절). 템플릿에 색·크기를 직접 적지
않는다(`#RRGGBB`는 테스트가 막는다). 예외: 데이터에서 나오는 퍼센트 폭·위치(`style="width: N%"`)와 `/ops/design`의 견본.

### 2.1 색

| 토큰 | 라이트 | 다크 | 역할 |
|---|---|---|---|
| `--c-bg` | `#F8F5EE` | `#1C1B18` | 페이지 바탕 |
| `--c-surface` | `#FFFDF8` | `#25231F` | 카드·패널·입력 |
| `--c-soft` | `#EFE9DC` | `#302D27` | 약한 면: 배지·보드 열·표 머리 |
| `--c-fill` | `#E6E0D1` | `#3C382F` | 진행 막대 바탕·이니셜 |
| `--c-line` | `#E2DFD4` | `#484339` | 구분선·카드 테두리 |
| `--c-line-strong` | `#8A8677` | `#928A7B` | 입력·셀렉트·편집 칸 테두리 전용(바탕·표면·soft 위 3:1 이상) |
| `--c-ink` | `#33372D` | `#F1EBDD` | 본문·제목 |
| `--c-muted` | `#64655A` | `#BCB3A3` | 보조 글자(메타·도움말) |
| `--c-faint` | `#8A8A7C` | `#908879` | 장식·placeholder·비활성 전용 — 읽어야 하는 글자에 쓰지 않는다 |
| `--c-accent` | `#A63E2E` | `#E99782` | 하나뿐인 강조: 주 버튼·링크·선택·초점 |
| `--c-accent-strong` | `#873022` | `#F4B39E` | 주 버튼 hover |
| `--c-accent-soft` | `#F6E1D6` | `#482E27` | 선택된 행·초점 링 |
| `--c-on-accent` | `#FFFDF6` | `#2B1711` | 강조 위 글자 |
| `--c-on-yellow` | `#33372D` | `#33372D` | 노란 면 전용 글자·기호(로고 먹색 유지) |
| `--c-yellow` | `#F5D575` | `#F5D575` | 집계 면·검토 대기·붓질 |
| `--c-yellow-strong` | `#E3B53C` | `#E3B53C` | 반짝이·검토 점 |
| `--c-sage` | `#DCE8D5` | `#30352B` | 진행 중·대표 지표·현재 위치 |
| `--c-sage-strong` | `#8CAA73` | `#8CAA73` | 진행 점·잎 |
| `--c-coral` | `#F4C1AC` | `#51382F` | 메모·막힘·위험 지표 |
| `--c-tape` | `rgba(255, 255, 255, .55)` | `rgba(255, 243, 220, .16)` | 메모 테이프 |
| `--c-danger` / `--c-danger-soft` | `#A52F2B` / `#FBE3DE` | `#F2A297` / `#442824` | 실패·삭제·기한 초과 |
| `--c-success` / `--c-success-soft` | `#2F6B3A` / `#DCE8D5` | `#B1CD9B` / `#2C3528` | 완료·연결됨 |
| `--c-warning` / `--c-warning-soft` | `#84520A` / `#FBEFCB` | `#E7C183` / `#3D3120` | 확인 필요·오늘 마감 |
| `--c-info` / `--c-info-soft` | `#285480` / `#E3ECF5` | `#ADC9E6` / `#283440` | 정보·PR 열림·GET |
| `--c-violet` / `--c-violet-soft` | `#4B2A7B` / `#ECE2F7` | `#CFB8E9` / `#362B43` | PR 병합(GitHub 관례) 전용 |
| `--c-github` / `--c-on-github` | `#1F2328` / `#FFFFFF` | `#FFFFFF` / `#1F2328` | GitHub 마크(Copilot 자리 포함), GitHub로 로그인 버튼 바탕/글자(6.1) |
| `--c-discord` | `#5865F2` | `#5865F2` | Discord 마크(Blurple, 6.1) |
| `--c-openrouter` | `#03080A` | `#FCFCFE` | OpenRouter 마크(Ink/Cloud, 6.1) |
| `--c-brand-on-accent` | `#FFFFFF` | `#000000` | 주 버튼 위 브랜드 마크(흑·백, 6.1) |

식물 그림 전용(라이트/다크): `--plant-pot` `#BD7250`/`#BD7250`,
`--plant-rim` `#DBA87D`/`#DBA87D`,
`--plant-soil` `#635A43`/`#635A43`,
`--plant-stem` `#60774D`/`#8CAA73`,
`--plant-leaf` `#8CAA73`/`#8CAA73`,
`--plant-leaf-2` `#ABC18C`/`#ABC18C`,
`--plant-vein` `#DCE8D5`/`#DCE8D5`,
`--plant-face` `#594A37`/`#594A37`,
`--plant-shadow` `rgba(38, 58, 48, .10)`/`rgba(12, 10, 8, .22)`.
빈 상태용 데이터 URI는 `--art-plant`(라이트 색 고정, 다크에서도 그대로 — 테라코타 화분은 양쪽에서 읽힌다).

**대비(WCAG, 계산값)** — 라이트 / 다크

| 글자 / 바탕 | 라이트 | 다크 |
|---|---|---|
| ink / bg · surface | 11.2 · 12.0 | 14.5 · 13.2 |
| muted / bg · surface · soft | 5.4 · 5.8 · 4.9 | 8.3 · 7.6 · 6.6 |
| accent / surface | 6.2 | 6.9 |
| on-accent / accent · accent-strong | 6.2 · 8.3 | 7.5 · 9.6 |
| on-yellow / yellow · ink / sage · coral | 8.5 · 9.6 · 7.6 | 8.5 · 10.6 · 9.0 |
| danger / danger-soft · success / success-soft · warning / warning-soft · info / info-soft | 5.6 · 5.0 · 5.7 · 6.6 | 6.6 · 7.3 · 7.4 · 7.4 |
| faint / surface (장식 전용) | 3.4 | 4.5 |
| line-strong / bg · surface · soft (입력 경계, 비텍스트 3:1) | 3.4 · 3.6 · 3.0 | 5.0 · 4.6 · 4.0 |

노란 면의 모든 글자는 `--c-on-yellow`를 쓴다. coral·fill 위 보조 글자는 잉크로 표시하며, danger / coral 조합은 쓰지 않는다.

### 2.2 글자

- `--f-display`: `'Jua', Pretendard, sans-serif` — 제목·큰 숫자·인사. 굵기 400 하나(Jua는 한 굵기뿐). 클래스 `.display`.
- `--f-body`: `Pretendard, -apple-system, 'Apple SD Gothic Neo', 'Noto Sans KR', sans-serif` — 나머지 전부. 본문 14px · 줄 높이 1.55.
- `--f-mono`: `ui-monospace, SFMono-Regular, Menlo, Consolas, monospace` — id·브랜치·커밋·경로.
- 외부 글꼴은 Pretendard(jsDelivr)와 Google Fonts Jua 둘뿐. 새 글꼴을 들이지 않는다.

| 토큰 | 값 | 쓰임 |
|---|---|---|
| `--fs-2xs` | 11px | 모바일 캡션 |
| `--fs-xs` | 12px | 배지·도움말·표 머리 |
| `--fs-sm` | 13px | 메타·보조 문장 |
| `--fs-md` | 14px | 본문 |
| `--fs-task` | 15px | 태스크 제목·문서 본문 |
| `--fs-lg` | 16px | 강조 본문·모바일 입력(확대 방지) |
| `--fs-lead` | 17px | 목표일 값 |
| `--fs-xl` | 20px | 작은 Jua 제목 |
| `--fs-h3` | 22px | 메모 제목(모바일)·문서 h2 |
| `--fs-2xl` | 24px | 카드 제목(h2)·로고 |
| `--fs-h2` | 28px | 상세 제목·선반 제목·작은 지표 숫자 |
| `--fs-3xl` | 30px | 모바일 페이지 제목·인사 |
| `--fs-stat` | 34px | 지표 타일 숫자 |
| `--fs-page` | 38px | 페이지 제목(`.page-head > h1`) |
| `--fs-hero` | 46px | 랜딩 첫 화면 제목(데스크톱) |
| `--fs-tally` | 64px | 오늘 완료 수 |

숫자(지표·기한·표 숫자 열)는 `font-variant-numeric: tabular-nums`. 제목은 `text-wrap: balance`, 문단은 `pretty`.

### 2.3 간격 · 모서리 · 그림자

- 간격 4px 단위: `--sp-1` 4px · `--sp-2` 8px · `--sp-3` 12px · `--sp-4` 16px · `--sp-5` 20px · `--sp-6` 24px · `--sp-8` 32px · `--sp-10` 40px.
  카드 안 24px(모바일 18px), 본문 섹션 사이 24px(모바일 16px), 보드 열 사이 16px.
- 모서리는 **역할로 다르게**(전부 같은 둥글기는 slop): `--r-xs` 6px 배지·기한·태그·코드·연결 상태 / `--r-sm` 8px 작은 면 /
  `--r-md` 12px 입력·지표 타일·셀렉트 / `--r-lg` 18px 카드·패널·카드형 행 / `--r-xl` 24px 초점 면(집계·메모·선반·보드 열) /
  `--r-pill` 999px 버튼·탭·칩·상태 알약·진행 막대.
- 그림자는 바탕색 계열로 물들인다(검정 금지): `--sh-1` `0 2px 0 rgba(51, 55, 45, .04)` 눌린 면 / `--sh-2` `0 6px 15px rgba(51, 55, 45, .08)`
  hover·선택 탭 / `--sh-pop` `0 16px 36px rgba(34, 41, 31, .16)` 메뉴·대화상자·알림. 다크는 각각 따뜻한 먹색 `rgba(12, 10, 8, .12/.22/.40)`.
  `--scrim` `rgba(36, 41, 33, .38)`/`rgba(12, 10, 8, .64)`: 대화상자 뒤·넓은 패널 뒤·표 스크롤 끝 그림자.

### 2.4 쌓임(z-index)

`--z-sticky` 4(설정 저장 막대·모바일 상세 막대) < `--z-header` 10 < `--z-overlay` 20(넓은 패널·/ 메뉴) < `--z-dropdown` 30(메뉴·프로젝트 선택)
< `--z-toast` 60 < `--z-skip` 100(본문 바로가기). 지역 쌓임(-1·0·1, 붓질·표 첫 열)만 숫자를 쓴다. 다른 숫자를 새로 만들지 않는다.

### 2.5 모션

| 토큰 | 값 | 쓰임 |
|---|---|---|
| `--dur-fast` | 180ms | hover·색 전환·카드 2px 들림 |
| `--dur-base` | 200ms | 알림·대화상자 등장 |
| `--dur-slow` | 800ms | 진행 막대 차오름 |
| `--dur-leaf` | 4s | 랜딩 그림 잎 흔들림(2회, 무한 반복 없음) |
| `--ease` | `ease` | 기본 |
| `--ease-out` | `cubic-bezier(.2, .8, .2, 1)` | 등장·차오름 |

드래그 중 카드 불투명도 .4, 놓을 곳 점선. 움직임은 `transform`·`opacity`만. `prefers-reduced-motion: reduce`에서는 모든
animation·transition을 끈다(파일 맨 끝 규칙).

### 2.6 셸

`--header-h` 80px(모바일 115px, 실측). 패널·고정 막대의 `top`은 이 토큰으로만 계산한다.

**패널** `aside#panel`은 레이아웃 흐름 밖(`position: fixed`)에 뜬다. 데스크톱은 머리줄 아래 오른쪽에 480px로 겹치고, 700px 이하는 머리줄 아래 전체를 덮는 시트다.
본문 폭·높이를 바꾸지 않으므로 패널을 열고 닫아도 누른 행이 같은 자리에 있다(목록 스크롤 유지). 열 때 초점은 `data-focus` 칸 또는 패널 첫 컨트롤로
`focus({ preventScroll: true })`, 닫으면 연 행으로 돌아간다. 패널을 열 때 본문을 숨기거나 `scrollTo`로 페이지를 옮기지 않는다.
패널 내용은 미리 받는다(`app.js` 태스크 패널 미리 받기): 화면에 보이는 행과 마우스·초점이 간 행의 `/tasks/N/panel`을 동시 2개씩 받아 두고, 열 때 받아 둔 것을 바로 넣은 뒤
최신본인지 다시 물어 바뀌었고 손대기 전이면 갈아 끼운다. `task-changed`·`task-updated`·`rt-stale`(실시간)이 오면 그 태스크 것을 낡음으로 표시하고 다시 묻는다.
물을 때는 가진 것의 ETag(`If-None-Match`)를 보내 같으면 서버가 본문 없이 304를 준다(`task_panel`). Postgres에서는 ETag가 데이터 버전(`web/data_version.py`, 모든 표의 쓰기 트리거)·보는 사람·오늘·주소·배포본이라 패널을 그리지 않고 비교한다.
실시간 반영은 `realtime.js`가 맡는다(`design-concepts/realtime/DESIGN-v2.md` 4절): 탭 하나만 `/rt/`에 붙어(WebSocket→SSE→폴링) 열린 패널·보이는 행(`T:`)과 `body[data-rt-keys]`(오늘 `U:`, 프로젝트 `P:`)를 구독하고, 받은 키를 위 HTMX 이벤트와 `project-changed`로 바꿔 쏜다.
패널 접이 섹션 `<details>`에는 `data-section`(table-map 1절 이름)을 단다. 접힌 섹션의 변경은 보류했다가 펼 때 패널을 다시 받으며, 같은 패널을 다시 받을 때 펼쳐 둔 섹션은 그대로 편다. 화면에 연결 상태를 표시하지 않는다(`body[data-rt]`만).
패널 안 고정 막대(`.panel-bar`)는 패널이 스크롤 상자라 `top: 0`이다.

**바닥글** `_site_footer.html` `.site-footer > .foot-in`. 좌우 끝선은 바로 위 본문 내용과 같다: 앱은 레일을 뺀 본문 열(`.frame-main`) 안에 두고
`.layout`과 같은 여백(32px, 700px 이하 16px), 인증 화면은 카드 폭(440px, 문서 카드 760px), 랜딩은 `.wrap` 콘텐츠 폭(1180 − 좌우 24px, 700px 이하 16px).
왼쪽 묶음(서비스 이름·정책 제목·상호·대표·사업자번호)은 왼쪽 끝, 오른쪽 묶음(저작권·개인정보 처리방침·주소·이메일)은 오른쪽 끝에 붙여 오른쪽 정렬한다.
700px 이하는 한 열로 쌓는다(소개·저작권은 가운데, 나머지는 왼쪽).

---

## 3. 컴포넌트 (클래스 · 규칙 · 하지 말 것)

| 컴포넌트 | 클래스 | 규칙 | 하지 말 것 |
|---|---|---|---|
| 버튼 | `.btn` + `.primary` `.tint` `.sm` `.icon` `.link` `.danger`, `[aria-pressed]` | 화면당 주 버튼(`.primary`) 하나. 폼을 여는 주 버튼은 `data-hide-open`을 붙여 열린 동안 숨긴다(폼의 제출 버튼이 주 버튼으로 남는다). 카드가 여럿인 화면은 저장 하나만 주 버튼, 파일 올리기·연결은 `.btn`. 되돌릴 수 없는 행동은 `.danger`. 누르면 1px 내려간다 | 주 버튼 둘, 열면 [닫기]로 바뀌는 주 버튼(토글형 주 버튼), 카드마다 주 버튼, 링크를 버튼처럼 칠하기, 아이콘만 있는 버튼에 `aria-label` 빠뜨리기 |
| 입력 | `label.field` > `.input`/`.select`/`.textarea`, `.helptext`, `label.check` | 라벨은 위, 도움말·오류는 아래. 테두리는 `--c-line-strong`. 한 줄 필터·추가 칸처럼 라벨 자리가 없으면 `.seg-label` 라벨을 앞에 두거나 `aria-label`을 단다. 클래스 없는 Django 위젯도 `:where()` 기본 규칙으로 같은 모양 | placeholder로 라벨 대신하기, 입력을 알약 모양으로 |
| AI 자동완성 | `.ai-spark` `.ai-inline` `.ai-wrap` | `[data-ai]` 칸 → `ai-fill.js`가 칸 안 오른쪽 끝(긴 글은 오른쪽 위)에 `.ai-spark`(반짝이 SVG, `aria-label`·`title` "AI 자동완성")를 붙이고, 칸 아래 `.ai-inline`(aria-live)에 결과를 둔다. 누르면 스피너, 다시 누르면 취소. 저장 버튼 폼 칸은 바로 채우고 [되돌리기](후보 여럿이면 ‹ ›), 자동 저장 칸은 미리보기 [적용]·[뒤에 붙이기]·[버리기]. 칸이 아닌 기능(`[data-ai-mode]`)은 글자 버튼 앞에 같은 아이콘 | 반짝이를 AI 기능 표시 밖(장식·"자동 추가" 표시)에 쓰기, 칸 바깥 [AI로 쓰기] 글자 버튼, 칸에 포커스가 있을 때의 단축키 |
| 마크다운 긴 글 | `.md-field` > `label` + `textarea[data-md][data-toolbar="top\|bottom"]` → `md-field.js`가 `.mdf` 칸(Tiptap)을 붙인다. 읽기 전용은 `.md-view` | 모든 칸이 같은 기능·같은 우선순위. 서식 줄은 초점이 있을 때만, 아이콘만(이름은 `title`·`aria-label`, [더보기] 메뉴만 아이콘+글씨). 큰 칸은 위(sticky), 작은 칸은 아래, 모바일은 화면 키보드 위 40px 한 줄. 고정 제목·라벨은 칸 밖, 칸 안 제목은 그보다 작게 | 칸마다 기능 빼기, 글자 버튼, 테두리 없는 편집 영역, 열기만으로 저장 |
| 카드 | `.card`, `.card-head`, `.card > h2`, `.box`, `.card.compact`, `.card.alert` | 묶음에 의미가 있을 때만. 제목은 Jua 24px | 카드 안 카드, 한 줄짜리 묶음마다 카드 쌓기(→ `.group-stack` 구분선) |
| 배지 | `.badge` + `.high` `.primary` `.ok` `.warn` `.danger` `.info`, `.tag`, GitHub용 `.pr-open` `.pr-merged` `.pr-closed` `.pr-draft` | 6px 모서리의 납작한 표식. 상태·수량·종류 | 알약 배지 남발, 배지에 클릭 동작 |
| 칩 | `.chips .chip`(체크박스·버튼·링크) | 필터·토글. 눌림은 잉크 색 채움 + ✓ | 칩으로 주 행동 |
| 선택 카드 | `.radios .radio-card` | 설명이 필요한 선택지(프로젝트 상태 등) | 2개뿐인 선택에 쓰기 |
| 탭 | `nav.tabs a[aria-current="page"]`, `.view-switch` | 화면 안 이동. 현재 탭은 표면색 + 그림자 | 탭으로 동작 실행 |
| 대화상자 | 네이티브 `dialog` + `#dialog` HTMX 대상 | 생성·수정 폼. 긴 폼은 하단 버튼 줄이 붙는다. 닫는 버튼은 [닫기] | 확인 한 번이면 될 일을 대화상자로, 닫는 버튼을 "취소"로(상태 '취소'와 겹친다) |
| 확인 창 | `data-confirm="결과 문장"` + `data-confirm-ok="대상+동사"`(+ `data-confirm-cancel`, 기본 [그대로 두기]) → `base.html` `dialog#confirm`, `app.js` `askConfirm` | 되돌리기 어려운 행동 앞에 한 번. 일반 폼은 `<form>`에, 버튼 하나만 확인할 때는 그 제출 버튼에, HTMX 요소는 그 요소에 단다. 누른 버튼이 `.danger`면(모양을 바꾸기 어려운 아이콘 버튼은 `data-confirm-danger`) 행동 버튼도 위험 스타일. 초점은 [그대로 두기]에서 시작, Esc·바깥은 취소. JS가 없으면 확인 없이 제출되므로 되돌릴 수 없는 일(탈퇴·운영 콘솔)은 서버가 이름 재입력으로 한 번 더 막는다. `<dialog>`를 못 쓰는 브라우저만 기본 `confirm()`으로 대신한다 | `confirm()`·`hx-confirm`·`onsubmit="return confirm"`(테스트가 막는다), "확인/취소/OK" 버튼, 결과 없이 "…할까요?"만 묻기 |
| 패널 | `aside#panel .panel`, `.panel-bar`(상태 메뉴·저장 표시·복사·닫기), `.panel-meta`(라벨 \| 값 2열), `.panel-folds > details.fold` | 상태는 고정 막대에서 바꾼다. 저장 표시 `#save-status`는 늘 보인다(저장 안내 문단을 따로 두지 않는다). 1단(펼침): 제목·상태 설명·프로젝트·담당·검토자·기한·중요도·다음 행동·진행 메모·완료 조건. 2단(접힘, 머리에 개수): 설명·체크리스트·하위 태스크·연결 프로젝트. 3단(접힘): 자료·첨부·산출물·변경 이력·결정 기록·더보기. 기한은 한 곳에만. 고르기 셀렉트는 빈 첫 옵션("…고르기…") + `required` | 상태 폼 복제, 같은 값 두 번 표시, 옵션 문구에 라벨 끼워 넣기, 미리 골라 둔 연결 대상 |
| 표 | `table.grid`, `.num`, `.table-scroll`(+`.table-scroll-hint`), `td.empty-cell` | 모바일은 카드 안에서 가로 스크롤. `.table-scroll`에는 항상 `role="region"`·aria-label("좌우로 스크롤 가능")과 힌트를 붙인다. 폭 440px 이하 카드(인증 카드, `w-sm`)에는 표 대신 정의 목록 카드(`dl.consent-recipient`) | 페이지 전체가 가로로 흔들리게 두기, 좁은 카드에 6열 표 |
| 빈 상태 | `{% include "_empty.html" with what= why= href=/hx_get=/toggle= label= locked= locked_text= %}` → `.empty`(화분 76px) `.empty-what`, `.empty.compact`(글자만), `td.empty-cell` | 무엇이 비었나 + 가치 한 줄 + 행동 하나. 권한이 없으면 행동 대신 `locked_text`. 원인이 여럿이면(조직 없음 → 프로젝트 없음 → 태스크 없음) 앞의 원인 하나만. 빈 표는 머리줄 없이 빈 상태로. 큰 화분은 화면당 하나 | 모든 빈 곳에 화분, 갈 수 없는 곳을 가리키는 안내, 필터 줄만 남은 빈 화면 |
| 알림 | `.notice`(세이지) `.notice.warn` `.notice.bad`, `.toast` | 경고·실패는 ⚠ 글리프를 앞에 둔다(색 외 단서). `messages.warning`은 `.notice.warn`, `messages.error`는 `.notice.bad` + `role="alert"`로 그린다(base.html). 일반 알림엔 글리프 없음. 토스트는 3초 | ⓘ 같은 장식 글리프, 감탄부호 |
| 지표 | `.tiles .tile`, `.stats .stat`, `.bar` | 첫 칸(대표)만 세이지, 위험 수치(`b.danger`)는 코랄, 나머지 바탕색 | 의미 없는 색 돌림 |

### 3.1 폼·설정 페이지 레이아웃

**원칙: 페이지 폭은 채우고, 입력 하나는 읽기 좋은 폭에서 멈춘다.** 폼을 640px 상자에 넣어 왼쪽에 붙이고 오른쪽을 비우지 않는다
(2026-10-06 사용자 지적). 페이지·섹션·목록에 고정 `max-width`를 두지 않는다 — 폭 제한은 입력 요소에만 둔다.

| 화면 유형 | 배치 | 클래스 |
|---|---|---|
| 섹션이 여럿인 설정(조직·프로젝트 설정) | 왼쪽 섹션 목차 220px(고정 위치, 스크롤에 따라 현재 섹션 표시) + 오른쪽 넓은 본문. 저장 막대는 본문 위에 붙는다 | `form.settings-form.with-nav` 또는 카드 안 `.settings-split` → `.settings-jump` + `.settings-main` |
| 설정 행 | "라벨·도움말 \| 입력 \| (조직) 프로젝트 변경 허용" 3단 그리드 `minmax(260px, 1.4fr) minmax(200px, 1fr) minmax(170px, 220px)`. 셀렉트·글 입력은 최대 420px, 숫자는 84px, 도움말은 70ch | `.setting-row`, `.setting-row-with-override` |
| 탭이 여럿인 조직 설정(IMPL-PLAN-14, 시안 A) | 왼쪽 세로 탭 240px("나"/"조직 관리" 묶음, 현재 탭 표면색+그림자) + 본문. 탭 안은 `.settings-jump` 칩 줄 + `details.settings-section`(id `settings-<탭>-<섹션>`). ≤700px는 탭 목록 화면 → 누르면 탭 화면(`?tab=`가 있을 때 `.in-tab`, [‹ 설정]으로 복귀). 구성원 관리는 목록 + 오른쪽 `.member-panel`(≤1100px 아래, ≤700px 목록 대신 전체 폭), 항목 정의는 `.field-card` + `.field-preview` | `.settings-shell` > `nav.settings-tabs` `.settings-tab` + `.settings-body`, `.member-split` `.member-panel` `.fields-split` `.field-card` |
| 짧은 그룹 여럿(개인 환경설정) | 그룹을 나란히: `repeat(auto-fit, minmax(520px, 1fr))` | `.settings-groups` |
| 카드 몇 장(프로필·연결) | 카드를 2~3열: `repeat(auto-fit, minmax(440px, 1fr))` | `.card-grid` |
| 하나의 일을 하는 독립 폼(새 요청·조직 만들기) | 읽기 폭 카드 760px를 **가운데**에 | `.card.form-card` |
| 표가 주인 화면(토큰·운영·팀 멤버) | 카드가 본문 폭을 채우고 표가 넓게 | 기본 `.card` |
| 대화상자 | 네이티브 `dialog` 640px(폭 문제 없음) | `dialog` |

- 1100px 이하: 목차 사이드는 위쪽 가로 칩 줄로 접힌다. 850px 이하: 설정 행이 세로 카드(라벨 → 입력 → 잠금)로. 700px 이하: 모두 1열.
- 목차 링크는 `data-action="open-settings-group"`(누르면 그 섹션만 펼침)을 그대로 쓰고, 현재 섹션은 `aria-current="true"`.

### 3.2 운영 콘솔 레이아웃

`/ops` 아래 화면은 조직 셸이 아니라 `ops/base.html`을 상속한다. 헤더 메뉴는 운영 콘솔 메뉴(개요·시스템·감사 기록·디자인 시스템)만 그리고, 본문은 제목 줄 아래 `.card` 여러 장을 세로로 쌓는다. 표가 주인이라 카드가 본문 폭을 채우며, 표는 `.table-scroll`로 감싼다. 변경은 `ops/_confirm.html` 대화상자(사유 필수, 위험 작업은 확인값 재입력)로만 하고, 감사 기록처럼 읽기 전용 화면의 행에는 버튼을 두지 않는다. 견본은 `/ops/design`의 "운영 콘솔 부품".

### 3.3 랜딩 화면

로그인 전 `/`는 앱 셸 없이 `landing.html` 한 장이다(원본 시안 `design-concepts/landing/concept-b-v6.html`). `app.css` 위에 `landing.css`·`landing.js`(팀 유형 ARIA 탭)를 얹는다. app.css와 이름이 겹치는 랜딩 부품은 `lp-` 접두어(`.lp-hero`·`.lp-board`·`.lp-pill` 등)를 쓴다. 바닥글은 `_site_footer.html`을 앱과 공유하고 소개 문장만 `footer_line`으로 바꾼다(끝선은 2.6 바닥글). 홍보 문구는 해요체를 섞는 예외라 12절 용어 검사에서 빠지며, 문구는 시안 원본(copy-v6.md)을 고치지 않는다. 외부 글꼴·스크립트 요청은 두지 않는다.

## 4. 업무 부품

- **상태 알약 7종** `.pill.{todo|doing|review|blocked|paused|done|cancelled}` — select와 읽기 전용(`.pill.static`) 공용, 글자 앞에 상태 기호
  (`status_mark`)를 붙여 색 없이도 읽힌다. 색: 시작 전 soft · 진행 중 sage · 검토 대기 yellow · 막힘 coral · 일시정지/취소 soft+muted · 완료 success-soft.
- **기한** `.due` + `.today`(warning) `.overdue`(danger, 앞에 "!") `.none`(점선) `.closed`(중립 "목표일 …", 닫힌 태스크는 초과로 표시하지 않는다).
- **태스크 행** `ul.tasks > li.task-row` — 목록에서는 구분선 행, 보드 열에서는 흰 카드(18px). 링크 복사·오늘 목록 버튼·↑↓는 hover·초점 때만(터치는 항상).
  맥락 옵션(`views.common.row_ctx`의 opts): 프로젝트 화면은 `noproject`(프로젝트 이름 숨김), 보드는 `board`(상태 칸 없음 — 열이 상태다),
  '자동 추가' 표시는 오늘 화면(`today`)에서만.
- **생성 폼 기본값**(빠른 추가·태스크 만들기·하위 만들기): 지금 보는 프로젝트(없으면 마지막으로 쓴 프로젝트), 담당은 나, 기한은 설정의 제안 기한을
  미리 채운다. 사유 칸은 [기한 없이 만들기]를 눌렀을 때만 펼치고 자주 쓰는 사유를 고르게 한다(`projects/_due_fields.html`).
  빠른 추가는 다른 화면에서 대화상자로 열고 끝나면 그 화면으로 돌아온다.
- **보드 열** `.board-track > .col[data-status]` + `.col-dot` — 미완료 5열만. 1280px 이상은 5열이 한 화면에 들어온다. 그보다 좁으면 막힌 태스크가 있을 때 보드 위 `.notice.warn` 한 줄 + [막힘 열 보기]. 막힘·일시정지 열은 점선 테두리 + 투명 바탕(별도 상태임을 드러낸다).
- **결과 선반** `.shelf` `.shelf-head` `.shelf-tabs` `.shelf-filters` `.shelf-list` `.shelf-more` — 완료·취소 전체 건수, 기간·검색, 10건씩 더 보기.
- **달력** `.pcal-grid .pcal-cell`(+`.today`, `.is-empty`) `.pcal-task`(+`.closed`: 보조색+취소선, 투명도 금지) `.pcal-ms`(◆ 마일스톤). 오늘 일정 `.cal`.
- **전사 메뉴** (조직 탭 `전사`, 구성원 누구나 — 볼 수 있는 회의록의 녹음만, "전사 서버" 보기는 관리자, IMPL-PLAN-10-transcribe-menu 시안 B) `.view-switch`(전사 작업 / 전사 서버) · 작업 목록 `.group-stack` > `ul.tjob-list` > `button.tjob`(이름 | 상태 칸 `.tjob-state`: `.bar.tjob-bar` + `.tjob-eta` "약 N분 남음", 또는 `.conn-state`) → 누르면 `#panel` 패널(`.tjob-big` 남은 시간, [전사 취소], 모델 `.radios` 카드마다 예상 시간, [다시 전사 시작]·[취소하고 다시 전사], 접힘 "세부 정보" `dl.tjob-meta`·"전사 기록" `ol.tjob-history`). 장치·정밀도·처리 배수는 세부 정보에만. 모델 이름은 서버가 준 제작자·계열(display_name 등)만, 없으면 id 그대로 + "· 로컬 서버"/"· OpenAI API".
- **내 PC 연결** (설정 탭 `내 PC 연결` `/settings/stt`, `/link` 기기 인증, IMPL-PLAN-11-local-stt-link) OS별 설치 한 줄 `details[name]` + 복사 버튼 · 서버 행 = 이름 + `.conn-state` 켜짐/꺼져 있음 + 모델 select [모델 적용](받는 중 3초 폴링) + 접힘 세부 정보 + [연결 끊기](`data-confirm`). `/link`는 빈 코드 칸 → 확인 카드(`.notice.warn` 경고, `.panel-meta`) → [연결 허용]·[연결 거절]. 전사 선택지의 내 PC는 "내 PC · {모델 표시 이름}", 꺼진 PC는 disabled 한 줄. 참여자별 녹음은 zip 링크 하나 + 개별 링크는 `details.fold`.
- **연결 프로젝트** `.linked-mark`(행의 "↔ n", 이름은 툴팁) `.project-links`(패널 연결 칸: `.tag` 칩 + 연결 해제 `.btn.sm.icon` + "승인 대기" `.badge.warn`). 열람 확대는 `.notice.warn` ⚠ 문구 + 승인 요청 버튼. 프로젝트 화면에는 연결이 있을 때만 각주 "연결 태스크는 여러 프로젝트에 셉니다".
- **상위·하위 태스크** `.sub-of`(하위 행의 "↳ TASK-N", 상위를 볼 수 있을 때만) `.sub-count`(상위 행의 "하위 n/m", 프로젝트 목록 보기에서는 접기 버튼) `.task-row.sub`(목록 보기에서 상위 아래 하위 행: 들여쓰기 + 왼쪽 세로선) — 보드는 묶지 않고 상위 카드에 `.bar`만. 패널 `#task-subtasks`(`.bar` 진행률, 완료 제안 `.notice`, 기한 경고 `.notice.warn` ⚠, 하위 행 `.subtask-list`).
- **오늘** `.today-grid` → `.today-line` `.focus-memo.memo` `.tally` `.today-list-card` `.today-schedule-card`. `h1`은 짧은 "오늘", 옆에 작은 날짜·이름 한 줄(`.today-line`).
  데스크톱: 제목 줄 → 메모(지금 할 한 가지) | 집계 → 목록 | 일정. 모바일(≤960px): 제목 줄 → 메모 → 집계(가로 한 줄) → 목록 → 일정.
  패널을 열어도 배치는 그대로다(패널은 겹쳐 뜬다). 자동 담기 설정은 목록 안 한 줄 결과 + 접힌 [설정 바꾸기].

## 5. 그림 · 장식

| 자산 | 파일·클래스 | 크기 규칙 | 쓰는 곳 |
|---|---|---|---|
| 화분(표정) | `templates/art/_plant.html`, 칠은 `.art-*` 클래스 | 210×200 | 스타일 가이드(오늘 화면에서는 뺐다) |
| 화분(작은) | `--art-plant` 데이터 URI | 빈 상태 76px, 표 빈 칸 52px, 로그인 82px | `.empty`, `td.empty-cell`, `.auth-card` |
| 선반 | `templates/art/_shelf.html` | 108×66(모바일 72×44) | 결과 선반 머리 |
| 새싹 알림 | `app.js celebrate()` | 40px | 완료 성공 직후 |
| 메모·테이프 | `.memo`(코랄, -1.2°, 모바일 -0.8°) + `::before` 테이프 64×18 | 화면당 하나 | 오늘 '지금 할 한 가지' |
| 붓질 | `.page-head > h1::after` 노랑 14px(모바일 10px), -1° | 페이지 제목에 자동 | 프로젝트·조직·설정·요청 제목 |
| 반짝이 | 집계 면 `.tally-badge`(화분 SVG 안 `.spark`) | 2.4s 2회 | 오늘 집계 |
| 로고(워드마크) | `static/brand/udally.svg` — 파비콘과 같은 `--c-yellow` 바탕, 얼굴(ll = 눈, y = 웃는 입) `--c-ink`, Uda는 한 톤 물러난 황토 #7A5C16(바탕 대비 4.3:1). 바탕이 있어 다크 모드도 같은 고정 색(노랑 위 글자는 `--c-on-yellow` 계열) | 헤더 높이 38px | 상단 바(로그인 전·후), README |
| 로고(아이콘) | `static/brand/udally-icon.svg` — 얼굴만 잘라 `--c-yellow` 바탕에 `--c-ink` | 16px까지 읽힘 | 파비콘 |
| 로고(아바타) | `static/brand/udally-avatar.svg` — 아이콘과 같은 색, 원형으로 잘려도 얼굴이 다 들어가게 여백을 둠 | 512px PNG로 올림 | Discord 봇 아바타·앱 아이콘 |

SVG 칠은 `fill="#…"`이 아니라 `.art-pot` `.art-leaf` 같은 클래스로 — 다크에서 함께 바뀐다. 새 그림을 만들면 `templates/art/`에 둔다.

## 6. 연동 화면 패턴 (Discord · GitHub)

공통 문법 — 모든 연결 상태는 **`.conn` 줄 + `.conn-state` 표식**(점 + 글자)으로 시작한다. 색만으로 상태를 말하지 않는다.

| 상태 | 클래스 | 예 |
|---|---|---|
| 정상·연결됨·지정됨 | `.conn-state.on` | Discord 서버 연결됨, GitHub 앱 연결됨, 채널 정상 |
| 미연결·미설치·미지정 | `.conn-state.off`(점선 점) | 서버 미연결, 계정 미연결, 저장소 미연결 |
| 확인 필요 | `.conn-state.warn` | 감시 꺼짐 |
| 문제 | `.conn-state.bad` | 권한 밖 N명, 저장소 접근 권한 없음 |

- 식별자(서버·채널 id, `@계정`, `owner/repo`, 브랜치, `#이슈`, 커밋 sha)는 `<code>` 알약(6px, soft 바탕).
- 조치가 필요한 경고(봇 권한 갱신, 서버 멤버 인텐트 꺼짐, 공유 저장소, 접근 팀 조회 실패)는 `.notice.warn` + ⚠, 오른쪽에 해결 버튼 하나.
- 정보성 차이(개인 계정 설치·개인 저장소에는 팀 없음)는 `.notice`(글리프 없음).
- **Discord**: 서버 카드(연결 상태 → 연결/해제) · 팀·프로젝트 채널 표(대상 / `<code>`채널 / 상태 / 자동 관리 켜기·끄기, 경고·허용·사라짐 하위 행,
  모바일 가로 스크롤) · 알림 채널 카드(지정됨/미지정 + `/알림채널` 안내). 채널 선택·생성은 웹에서 하지 않고 Discord 명령으로 안내한다.
  알림 미리보기 화면은 아직 없다 — 만들 때는 `.box` 안에 실제 문구를 본문 글꼴로, 상태는 `.conn-state`로.
- **GitHub**: 설치 카드(`.conn-state` + `<code>`계정 + 배지 "개인 계정"/"GitHub 조직" + "전체/선택된 저장소") · 내 계정 카드 ·
  저장소 연결 현황 표 · 프로젝트 저장소(연결 상태, 접근 팀 표, 이슈 가져오기 규칙 체크박스, 이슈 표, 이벤트 타임라인 표 시각/이벤트/태스크/결과).
  - 태스크 흐름은 `ol.git-steps`: 이슈 → 브랜치 → PR → 머지. 점 `.dot`은 완료 `li.done`(세이지 채움), 진행 `li.progress`(노랑).
  - 같은 `ol.git-steps`를 조직 개요의 "시작하기" 카드에도 쓴다(관리자, 태스크 0개일 때만): 첫 프로젝트 → 팀원 초대 → 저장소 연결 → Discord 알림. 단계마다 얻는 가치 한 줄과 버튼, 다 끝나면 카드를 숨긴다.
- **동의·연결 흐름**: 동의 화면은 가치 한 줄 → 법정 고지(`dl.consent-recipient`) → [동의하고 ○○ 연결 계속]/[연결하지 않고 돌아가기](`next`). 동의 직후 하던 일(연결 코드, 토큰 발급)을 마저 끝낸다.
  철회·연결 해제·토큰 폐기는 끊기는 것을 적은 확인을 먼저 받는다.
  - 배지 색: PR 열림 `.badge.pr-open`(info) · 병합 `.badge.pr-merged`(violet, GitHub 관례) · 닫힘 `.badge.pr-closed`(soft) · 가져온 이슈 `.badge.ok`.
  - 개인 계정 설치는 팀·조직 멤버 관리·이슈 자동 가져오기가 없음을 `.notice`로 밝힌다(조직 설치와 같은 화면에 섞지 않는다).
  - PR 부가 정보(라운드 8): draft는 테두리만 있는 `.badge.pr-draft`, CI는 `a.ci.ci-{success|failure|pending}`(점 + "CI 통과/실패/진행 중",
    누르면 GitHub 체크 화면, 결과가 없으면 그리지 않는다), 리뷰는 글자 요약 `.review-sum` "리뷰 승인 n · 변경 요청 n"(0·0이면 생략).
  - 재개 계열: 닫힌 원 태스크에는 `.notice` "이 작업은 … TASK-x로 이어졌습니다", 새 태스크에는 보조 글자 "TASK-y에서 이어진 작업입니다".
  - 릴리스: 태그는 고정폭 `.release-chip`(사전 배포 `.pre`는 점선 + `badge warn` "pre"). 결과 선반 위 `.release-strip`(최근 5건,
    저장소를 볼 수 있는 사람만), 로드맵 마일스톤 이름 아래 칩 + 완료 전이면 `[완료로 표시]`(`.btn.sm.tint`).
  - 규칙 스위치는 체크박스 목록(이슈→태스크, 브랜치→진행 중, 커밋→체크리스트, PR→검토 대기, 머지→완료, 리뷰, 마일스톤).
    이슈 양방향 동기화 스위치는 두지 않는다(IMPL-PLAN-8 §10-1).
  - 앱 권한·이벤트 점검 표(조직 GitHub 탭, 관리자): 기능 / `.conn-state` 켜짐·꺼짐 / 꺼지면 사라지는 것 / 필요한 권한·구독(`.badge.warn`).
    꺼진 기능이 있으면 표 아래 `.notice.warn` 하나로 "권한 추가 → 설치 계정에서 재승인"을 안내한다. GitHub에 묻지 못하면 `.conn-state.warn` "확인 불가".
  - GitHub 알림 → Discord 채널(저장소 탭): 상태 `.conn-state`(설정됨·봇 처리 대기·해제 중·미설정), 보낼 이벤트는 `.chips .chip`,
    막힌 이유는 버튼 대신 `.notice.warn`(이유 + 해결 방법). 저장소 연결을 해제하면 GitHub 쪽 훅을 먼저 지우고 안내한다.
- API 문서 메서드 `.method.m-{get|post|patch|put|delete}`: info · success · warning · violet · danger 의 soft 면 + 진한 글자. 응답 `.badge.resp-{2|4|5}`.

### 6.1 외부 브랜드 (로고 · GitHub로 로그인)

외부 서비스로 가거나 그 서비스와 잇는 버튼·카드 제목·AI 행에는 그 서비스 로고를 이름 글자 **앞에** 둔다. 로고는 장식이라
`aria-hidden`, 이름은 글자가 말한다. 기존 문구는 그대로 두고 로고만 더한다. 로고는 우리 로고·이름보다 작게(글자 크기 1em), 변형·그림자·그라데이션 없이.

- 부품: `{% include "_brand_icon.html" with brand="github|discord|huggingface|openrouter" %}` → `.brand-icon.brand-icon-{brand}`. 공식 자산을 고치지 않고 쓴다: GitHub = primer/octicons `mark-github-16`(MIT) · Discord = simple-icons 16.35.0(CC0) · OpenRouter = openrouter.ai/brand `glyph-ink.svg`/`glyph-cloud.svg` 경로(원본 비율 1024:730, `width: auto`) · Hugging Face = huggingface.co/brand `hf-logo.svg` 원본 컬러 파일(`static/brand/huggingface-logo.svg`, `<img alt="">`). GitHub Copilot은 독립 Copilot 아이콘의 제3자 사용 범위가 확정되지 않아(<https://brand.github.com/brand-identity/copilot>) **GitHub 마크**를 쓰고 이름은 "GitHub Copilot" 그대로. 외부 CDN에서 불러오지 않는다.
- 색: GitHub 마크는 `--c-github`(라이트 검정 `#1F2328`, 다크 흰색) — 흑·백만. Discord는 `--c-discord` Blurple `#5865F2`(두 모드 같음). OpenRouter는 `--c-openrouter`(라이트 Ink `#03080A`, 다크 Cloud `#FCFCFE`). Hugging Face는 원본 컬러 그대로. `.btn.primary` 안의 마크는 `--c-brand-on-accent` — 라이트 흰색 `#FFFFFF`, 다크 검정 `#000000`(버튼 바탕·글자색은 그대로).
- **GitHub로 로그인·가입·계정 만들기**: `.btn.brand-github` — 라이트는 `--c-github` 바탕 + `--c-on-github` 흰 글자·마크, 다크는 반대(흰 바탕 + 검정). 크기·굵기·간격은 `.btn`과 같다. 이 버튼은 주 버튼(`.primary`)으로 세지 않는다(브랜드 버튼).
- OpenAI·Codex: 공식 로고 배포본을 확인하지 못했고(브랜드 페이지 접근 불가, simple-icons에서도 빠짐) 로고 수정·과한 노출을 금지하므로 **로고 없이 이름 글자만** 쓴다.
- 하지 말 것: 우리 서비스가 그 회사의 것이거나 보증받은 것처럼 보이게 하기, 연결 해제·위험 버튼에 로고, 장식으로 로고 반복.
- 출처: GitHub <https://brand.github.com/foundations/logo> · Discord <https://discord.com/branding> · OpenAI <https://openai.com/brand> ·
  Hugging Face <https://huggingface.co/brand>, <https://huggingface.co/docs/hub/oauth#branding> · OpenRouter <https://openrouter.ai/brand> (2026-10-15 확인).

## 7. AI Slop 금지 규칙

출처: Taste Skill 원문(`design-concepts-astra/design-concepts/v4-critic/refs/tasteskill/skills/`). 대시보드 앱에 맞는 항목만
채택했다(마케팅 페이지용 규칙 — 스크롤 애니메이션·글래스·자석 버튼·폰트 교체 — 은 03 결정과 충돌하므로 따르지 않는다).

| 금지 | 출처 | 이 앱의 규칙 · 2026-10-05 정리 내용 |
|---|---|---|
| 모든 요소 같은 둥글기 | redesign-skill/SKILL.md:53 | 역할별 모서리(2.3). 배지·기한·태그·코드·연결 상태를 알약 → 6px, 입력류 알약(필터 셀렉트·검색) → 12px, 카드·패널 24 → 18px |
| 알약 모양 배지 남발 | redesign-skill/SKILL.md:95 | 위와 같음. 알약은 누를 수 있는 것(버튼·탭·칩·상태 select)만 |
| 장식용 그라데이션·광원 원(orb) | taste-skill/SKILL.md:101, soft-skill/SKILL.md:25 | 환영 면 오른쪽 위 반투명 원 제거. 식물·반짝이(1차 원본)만 남김 |
| 의미 없는 아이콘·이모지 | redesign-skill/SKILL.md:107-108 | 일반 알림의 ⓘ 글리프 전부 제거(⚠만 남김), "자동 추가" 앞 ✦(AI '마법' 반짝이) 제거 → 기울임 글자. 반짝이는 AI 자동완성 버튼 표시(3. AI 자동완성)에만 |
| 획일적 카드 반복 | taste-skill/SKILL.md:52-54, redesign-skill/SKILL.md:93 | 내 태스크의 묶음별 카드(한 줄짜리 카드 4~5장) → 카드 한 장 안 구분선(`.group-stack`) |
| 의미 없는 색 돌림 | taste-skill/SKILL.md:45 (강조 하나) | 지표 타일 세이지·노랑·코랄 순환 → 대표 지표만 세이지, 위험 수치만 코랄 |
| 장식 텍스트(자간 벌린 머리글) | redesign-skill/SKILL.md:28 | 한글 eyebrow 자간 .14em → .02em, 페이지 머리 조직 링크 자간 제거 |
| 감탄부호 성공 문구 | redesign-skill/SKILL.md:83, :82 | "끝! 한 걸음 더 자랐어요." → "완료했습니다. 화분이 한 뼘 자랐습니다." 보드·선반 안내도 격식체 |
| 흐린 완료(투명도) | Astra 시각 검토 중5(`scratchpad/theme-review/REVIEW.md:63-68`) | 달력 완료 → 보조색+취소선 |
| 고아 단어·비례 숫자 | redesign-skill/SKILL.md:26, :29 | 제목 `text-wrap: balance`, 문단 `pretty`, 숫자 `tabular-nums` |
| 인라인 스타일·임의 z-index | redesign-skill/SKILL.md:115, :118; taste-skill/SKILL.md:77 | 인라인 style → 토큰 클래스, z-index → `--z-*` |
| 검은 그림자·1px 회색 테두리만으로 만든 카드 | soft-skill/SKILL.md:17, redesign-skill/SKILL.md:38 | 그림자는 잉크색(올리브)으로 물들임. 테두리는 `--c-line`(따뜻한 회색) |
| 빈 상태 없음 | taste-skill/SKILL.md:59 | `.empty`로 다음 행동 안내. 단, 화분은 화면당 하나 |
| 눌림 피드백 없음 | taste-skill/SKILL.md:61 | `.btn:active` 1px 내려감 |

**의도적으로 유지한 것**: 메모의 기울기(2026-10-12 오늘 화면의 큰 슬로건·화분은 뺐다 — 매일 볼 필요가 없고 맨 위는 '지금 할 한 가지'다), 버튼의 알약 모양(03 README "버튼 캡슐").

## 8. 접근성

- 글자 대비 4.5:1 이상(2.1 표). `--c-faint`는 읽어야 하는 글자에 쓰지 않는다. 코랄 위에는 잉크 글자.
- 초점: `:focus-visible { outline: 3px solid var(--c-accent); outline-offset: 2px }`, 입력은 테두리 + 3px `--c-accent-soft` 링. 초점 표시를 지우지 않는다.
- 터치 44px: 모바일(≤700px)에서 버튼·상태 select·입력·링크형 버튼(`.btn.link`, 알림 닫기 포함)·지표 링크 모두 44px 이상.
- 이름: 목록에 되풀이되는 [삭제]·[승인]·[거절] 같은 버튼은 `aria-label`에 대상 이름을 넣는다("첨부 {{ 이름 }} 삭제"). 아이콘만 있는 버튼도 같다.
- 상태는 색 + 글자(+ 기호)로. 경고는 ⚠. 장식 SVG는 `aria-hidden="true"`.
- 본문 바로가기 `.skip-link`, 알림 `role="status"`, 저장 표시 `aria-live="polite"`, 표 스크롤 영역 `tabindex="0" role="region" aria-label`.
- 모션 감소 설정을 존중한다(2.5).
- 자동 검사(`core/web/test_design_system.py`): `confirm()`·`hx-confirm` 재등장, "확인/취소/OK" 단독 버튼, 라벨 없는 입력, `aria-label` 없는 아이콘 버튼, 주요 글자·바탕 조합 대비(글자 4.5, 입력 경계 3.0, 라이트·다크)를 막는다. 새 색 조합을 쓰면 `CONTRAST_PAIRS`에 넣는다.

## 9. 반응형 기준점

| 기준 | 바뀌는 것 |
|---|---|
| ≤1150px | 지표 3열. 태블릿 머리 간격 축소(패널은 모든 폭에서 겹쳐 뜬다 — 본문을 숨기지 않는다) |
| ≤960px | 오늘 그리드 1열(제목 줄 → 메모 → 집계 → 목록 → 일정) |
| ≤850px | 회의록 목록/편집 전환, 설정 행 세로 카드 |
| ≤720px | 프로젝트 달력이 날짜 목록으로(빈 날짜 숨김) |
| ≤700px | 머리줄 2줄(`--header-h` 115px, 메뉴 줄 오른쪽 끝을 흐려 더 있음을 알린다), 레일 → 프로젝트 선택기, 보드 열 스냅 스크롤, 지표 가로 스크롤 한 줄, 집계 가로 한 줄, 터치 44px, 입력 16px |
| ≤360px | 회의록 메타 1열, 설정 선택지 1열 |

## 10. 다크 모드 — 따뜻한 먹색 작업실

- 운영체제의 `prefers-color-scheme: dark`를 따른다. app.css의 첫 라이트 `:root`는 유지하고, 미디어 쿼리 안 `:root`에서 모든 `--c-*`·`--plant-*`·그림자·`--scrim`을 덮어쓰며 `color-scheme: dark`를 선언한다.
- 바탕 `#1C1B18`, 표면 `#25231F`, 약한 면 `#302D27`은 따뜻한 먹색 계열이다. 상대 휘도는 각각 1.1%·1.7%·2.7%로, 모두 5% 아래를 유지한다. 올리브·초록을 넓은 바탕으로 쓰지 않는다.
- 라이트의 테라코타는 같은 색상 계열의 `#E99782`, 코랄 메모는 `#51382F`로 옮긴다. 세이지 `#30352B`·새싹 `#8CAA73`은 작은 상태·선택·그림에만 쓴다. 대표 지표·선반·소개 페이지의 넓은 면은 중성 `--c-soft`로 그린다.
- 로고 노랑 `--c-yellow: #F5D575`와 황토·먹색 로고는 그대로 유지한다. 집계 카드·검토 대기 알약·노란 배지·hover·랜딩 마무리 면은 `--c-on-yellow: #33372D`로 글자와 기호를 그린다. 이 토큰의 라이트 값은 기존 잉크와 같아서 라이트 모양은 바뀌지 않는다.
- 제목 아래 노란 붓질은 다크에서도 크기·위치가 라이트와 같고, 투명도만 .35로 낮춘다(밝은 글자 대비 5:1 이상). 글자 크기·굵기·간격은 두 모드가 같다. 제목 글자는 밝은 잉크, 노란 면 글자는 진한 잉크로 분리한다.
- Swagger의 `.swagger-card`는 `color-scheme: light`와 밝은 판을 유지한다. 주변 셸·폼은 다크 토큰을 따른다.
- `test_every_light_token_has_dark_value_for_colors`가 누락을, `test_dark_canvas_stays_dark_and_warm`이 밝거나 초록인 바탕을 막는다. `CONTRAST_PAIRS`의 모든 글자 조합은 양쪽 모드 AA 4.5:1 이상, 입력 경계·초점은 3:1 이상을 통과해야 한다.
- 화면 확인은 오늘(1440·390), 태스크 상세, 조직 설정 구성원 관리, 소개 랜딩, API 문서를 양쪽 모드에서 확인한다. `/ops/design`은 라이트·다크 값을 app.css에서 직접 읽어 나란히 표시한다.

## 11. 새 화면 체크리스트

1. 정보 구조는 기존 메뉴·URL을 따른다. 제목은 `.page-head`(붓질 자동) 또는 `.card > h2`.
2. 색·크기·간격·모서리·그림자·z-index는 토큰으로만. 템플릿에 `style`·`#RRGGBB`를 쓰지 않는다(데이터 퍼센트 제외).
3. 기존 컴포넌트를 먼저 쓴다(3·4장). 새 클래스가 필요하면 app.css 해당 절에 추가하고 이 문서 표에 한 줄 적는다.
4. 장식은 화면당 초점 하나. 카드 안 카드·한 줄짜리 카드 반복·색 돌림·장식 글리프 금지(7장).
5. 빈 상태·오류·저장 중·권한 없음 상태를 그린다. 문구는 격식체, 감탄부호 없이.
6. 연동 상태는 `.conn-state`, 조치 필요 경고는 `.notice.warn`.
7. 기능 훅(`hx-*`, `name`, `id`, `data-action`, URL)은 바꾸지 않는다.
8. 390×844·1440×1050 두 장을 찍어 본다(첫 업무가 첫 화면에 들어오는지, 44px, 가로 넘침).
9. `/ops/design`에 새 부품 견본을 추가한다.
10. `uv run pytest -q`(디자인 시스템 테스트 포함)와 ruff를 통과한다.

## 12. 용어표

사용자에게 보이는 화면·알림·오류에 아래 표준어를 쓴다. 코드 식별자·모델 필드명·주석·처리방침 원문에는 적용하지 않는다. 기존 용어표는 `docs/IMPL-PLAN-9.md`~`12.md`를 따르되 아래의 화면 문구가 우선한다.

| 표준어 | 뜻 | 쓰지 않는 말 |
|---|---|---|
| 기한 / 오늘까지 / 기한 알림 | 태스크·마일스톤 날짜 / 오늘이 기한인 칩 / 날짜 알림 | 목표일, 목표 기한, 마감, 오늘 마감, 마감 알림 |
| 사유 / 막힘 사유 / 일시정지 사유 / 기한 미정 사유 | 변경·중단·기한 미정의 이유를 적는 칸 | 변경 이유, 막힌 이유, 멈춘 이유 |
| 올리기 | 파일을 등록하는 행동 | 업로드 |
| 정지 / 재활성 | 계정 이용을 막기 / 다시 허용하기 | 비활성화된 계정, 비활성 사용자 |
| 사람별 할 일 양 | 담당자별 미완료·기한 초과 태스크 | 부하 현황 |
| 업무 규칙 / 프로젝트 추가 업무 규칙 | 사람과 AI가 함께 따르는 합의 | 업무 거버넌스, 개발 거버넌스, 거버넌스 |
| 끝난 일 / 찾은 결과 | 완료한 태스크 / 검색에 맞는 건수 | 결과 선반, 완료 조건 일치 |
| 이 문서를 가리키는 글 | 현재 문서를 참조하는 문서·태스크 | 백링크, 역링크 |
| 담당자별 태스크로 나누기 | 담당자마다 하위 태스크 만들기 | 사람별로 나누기, 분배, 공동 담당 |
| 상위 태스크 / 하위 태스크 | 한 겹의 태스크 묶음 | 부모 태스크, 자식 태스크, 서브태스크, 에픽 |
| 넣기 / 떼어내기 / 하위 만들기 | 상위 아래에 넣기 / 상위에서 빼기 / 새 하위 생성 | 서브태스크 추가, 그룹 태스크 |
| 계열 / 원본 | 복제·회차의 묶음 / 그 뿌리 | 부모 태스크, 에픽 |
| 주 프로젝트 / 연결 프로젝트 / 연동 프로젝트 | 번호·규칙 소유 / 추가 참조 / GitHub 상태 변경 기준 | 소속 프로젝트, 대표 프로젝트, 메인 |
| 문서 / 회의록 / 상위 문서 / 하위 문서 | 일반 글 / 회의 기록 / 문서 트리 | 위키, 미팅 노트, 서브페이지, 자식 문서 |
| 공개 범위 / 열람자 / 열람 확대 | 볼 수 있는 범위 / 사람 / 연결로 보는 사람이 늘어남 | 스코프, 뷰어, 노출 확대 |
| 템플릿 / 이전 버전 / 되돌리기 | 새 본문의 틀 / 저장 이력 / 이전 내용 복원 | 리비전, 히스토리, 롤백 |
| 연결 / 연결 해제 | 프로젝트·문서 참조 만들기 / 끊기 | 매핑, 관계 |
| 가져오기 / 내보내기 / 미리보기 | 자료 들여오기 / 파일 받기 / 실행 전 결과 확인 | 임포트, 익스포트, 드라이런 |
| 열 지정 / 값 대응 / 사람 매칭 / 원본 링크 | 가져올 열·값·사람 연결 / 원본 주소 | 필드 매핑, 사용자 매핑, 출처 URL |
| 조직 관리자 / 서비스 운영자 / 최고 운영자 / 운영 콘솔 / 감사 기록 / 토큰 폐기 | 조직·서비스 관리, 운영 기록과 자격증명 폐기 | 조직 운영자, 오너, 밴, 토큰 삭제 |
| 회의 진행자 / 넘겨받기 요청 / 전사 / 용어집 | 회의 책임자 / 진행자 인계 요청 / 음성을 글로 바꾸기 / 전사용 단어 목록 | 인수 요청, 이양 신청, 단어장 |
| 전사문 / 현재 전사문 / 다시 전사 / 전사 작업 | 녹음을 글로 옮긴 원문(회의록과 따로 저장, 시도마다 남음) / 회의록 화면에 보이는 전사문 / 다른 모델로 전사문 새로 만들기 / 전사 한 번 | 트랜스크립트, 재전사, 회의록 교체 |

요청은 “…해 주세요”, 서술은 격식체로 쓴다. 해요체·감탄부호·이모지는 쓰지 않는다. 상태·경고·접근성을 위한 기존 기호는 유지한다. 버튼은 대상과 행동을 함께 적는다(예: 요청 완료 처리, 회의록 확정, 팀 설정 저장). 공용 닫기·그대로 두기는 일관된 표준 문구를 유지한다.

오류는 무엇이 왜 안 됐는지와 다음 행동을 함께 적는다. 사용자가 할 행동이 없는 상태는 원인만 설명한다. 기술 예외·외부 서비스 오류 원문은 사용자에게 보여 주지 않고 로그에 남긴다. `core/web/test_design_system.py`는 템플릿과 Python 문구의 금지어·요청형 및 모호한 단독 동사 버튼을 검사한다.
