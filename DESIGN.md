# 유달리 디자인 시스템 — 03 「모여서, 한 걸음」 · 장식 강

토큰·규칙·이유를 이 파일 하나에 둔다. 값의 기준은 `core/web/static/app.css`이고, 이 문서의 토큰 이름·값은 그 파일과 1:1이다
(`core/web/test_design_system.py`가 app.css의 모든 토큰이 여기 적혀 있는지 검사한다). 실제 렌더링 견본은 staff 전용
**`/ops/design`**(설정 → 디자인 시스템)에서 본다. 그 화면의 토큰 표는 app.css를 직접 읽어 그린다.

확정: 2026-10-05 사용자 결정(1차 시안 03 · 장식 강). 이전 TASK-41 teal 규칙은 이 문서로 대체됐다(git 이력에 남아 있다).

## 목차

1. 원칙 · 2. 토큰 · 3. 컴포넌트 · 4. 업무 부품 · 5. 그림·장식 · 6. 연동 화면 패턴 · 7. AI Slop 금지 규칙 ·
8. 접근성 · 9. 반응형 · 10. 다크 모드 · 11. 새 화면 체크리스트

---

## 1. 원칙

**성격.** 작은 팀의 작업실. 크림 바탕에 세이지·노랑·코랄 색면, 동글동글한 Jua 제목, 표정 있는 화분과 테이프 붙인 메모로
손맛을 낸다. 그래도 **업무가 먼저 읽힌다** — 장식은 업무를 감싸지, 덮지 않는다.

**장식 '강'을 쓰는 곳**

| 쓰는 곳 | 무엇을 |
|---|---|
| 오늘 화면 머리 | 큰 인사(Jua 46px), 약 200px 화분 SVG, 반짝이, 세이지 환영 면(데스크톱 화면 높이 약 1/4), 노란 집계 면, 코랄 메모(지금 할 일) |
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

모든 값은 `:root`(라이트)와 `@media (prefers-color-scheme: dark) { :root {…} }`(다크)에 있다. 템플릿에 색·크기를 직접 적지
않는다(`#RRGGBB`는 테스트가 막는다). 예외: 데이터에서 나오는 퍼센트 폭·위치(`style="width: N%"`)와 `/ops/design`의 견본.

### 2.1 색

| 토큰 | 라이트 | 다크 | 역할 |
|---|---|---|---|
| `--c-bg` | `#F8F5EE` | `#242921` | 페이지 바탕 |
| `--c-surface` | `#FFFDF8` | `#30362C` | 카드·패널·입력 |
| `--c-soft` | `#EFE9DC` | `#3C4434` | 약한 면: 배지·보드 열·표 머리 |
| `--c-fill` | `#E6E0D1` | `#465040` | 진행 막대 바탕·이니셜 |
| `--c-line` | `#E2DFD4` | `#4A5143` | 구분선·테두리 |
| `--c-ink` | `#33372D` | `#F5F0DF` | 본문·제목 |
| `--c-muted` | `#64655A` | `#BDC2B3` | 보조 글자(메타·도움말) |
| `--c-faint` | `#8A8A7C` | `#8F9984` | 장식·placeholder·비활성 전용 — 읽어야 하는 글자에 쓰지 않는다 |
| `--c-accent` | `#A63E2E` | `#FFC3AD` | 하나뿐인 강조: 주 버튼·링크·선택·초점 |
| `--c-accent-strong` | `#873022` | `#FFD8C8` | 주 버튼 hover |
| `--c-accent-soft` | `#F6E1D6` | `#533B30` | 선택된 행·초점 링 |
| `--c-on-accent` | `#FFFDF6` | `#3A1E16` | 강조 위 글자 |
| `--c-yellow` | `#F5D575` | `#675723` | 집계 면·검토 대기·붓질 |
| `--c-yellow-strong` | `#E3B53C` | `#C9A63E` | 반짝이·검토 점 |
| `--c-sage` | `#DCE8D5` | `#3D563C` | 환영 면·진행 중·대표 지표·현재 위치 |
| `--c-sage-strong` | `#8CAA73` | `#8CAA73` | 진행 점·잎 |
| `--c-coral` | `#F4C1AC` | `#654638` | 메모·막힘·위험 지표 |
| `--c-tape` | `rgba(255, 255, 255, .55)` | `rgba(255, 255, 255, .16)` | 메모 테이프 |
| `--c-danger` / `--c-danger-soft` | `#A52F2B` / `#FBE3DE` | `#FFB2A6` / `#4A2A26` | 실패·삭제·기한 초과 |
| `--c-success` / `--c-success-soft` | `#2F6B3A` / `#DCE8D5` | `#A9D99A` / `#34472F` | 완료·연결됨 |
| `--c-warning` / `--c-warning-soft` | `#84520A` / `#FBEFCB` | `#F5CA86` / `#4A3D22` | 확인 필요·오늘 마감 |
| `--c-info` / `--c-info-soft` | `#285480` / `#E3ECF5` | `#A9CDF4` / `#2A3A4C` | 정보·PR 열림·GET |
| `--c-violet` / `--c-violet-soft` | `#4B2A7B` / `#ECE2F7` | `#D9C4F5` / `#3D3150` | PR 병합(GitHub 관례) 전용 |

식물 그림 전용: `--plant-pot` `#BD7250`/`#B5684A`, `--plant-rim` `#DBA87D`/`#C9946B`, `--plant-soil` `#635A43`/`#4A4334`,
`--plant-stem` `#60774D`/`#7F9A69`, `--plant-leaf` `#8CAA73`/`#7E9E66`, `--plant-leaf-2` `#ABC18C`/`#9AB37E`,
`--plant-vein` `#DCE8D5`/`#3D563C`, `--plant-face` `#594A37`/`#3A2E22`, `--plant-shadow` `rgba(38, 58, 48, .10)`/`rgba(0, 0, 0, .22)`.
빈 상태용 데이터 URI는 `--art-plant`(라이트 색 고정, 다크에서도 그대로 — 테라코타 화분은 양쪽에서 읽힌다).

**대비(WCAG, 계산값)** — 라이트 / 다크

| 글자 / 바탕 | 라이트 | 다크 |
|---|---|---|
| ink / bg · surface | 11.2 · 12.0 | 13.0 · 10.9 |
| muted / bg · surface · soft | 5.4 · 5.8 · 4.9 | 8.2 · 6.8 · 5.6 |
| accent / surface | 6.2 | 8.1 |
| on-accent / accent | 6.2 | 9.9 |
| ink / yellow · sage · coral | 8.5 · 9.6 · 7.6 | 6.2 · 7.1 · 7.4 |
| danger / danger-soft · success / success-soft · warning / warning-soft · info / info-soft | 5.6 · 5.0 · 5.7 · 6.6 | 7.4 · 6.3 · 6.9 · 7.0 |
| faint / surface (장식 전용) | 3.4 | 4.2 |
| danger / coral — **쓰지 않는다** | 4.3 | 4.9 |

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
| `--fs-hero` | 46px | 오늘 인사(데스크톱) |
| `--fs-tally` | 64px | 오늘 완료 수 |

숫자(지표·기한·표 숫자 열)는 `font-variant-numeric: tabular-nums`. 제목은 `text-wrap: balance`, 문단은 `pretty`.

### 2.3 간격 · 모서리 · 그림자

- 간격 4px 단위: `--sp-1` 4px · `--sp-2` 8px · `--sp-3` 12px · `--sp-4` 16px · `--sp-5` 20px · `--sp-6` 24px · `--sp-8` 32px · `--sp-10` 40px.
  카드 안 24px(모바일 18px), 본문 섹션 사이 24px(모바일 16px), 보드 열 사이 16px.
- 모서리는 **역할로 다르게**(전부 같은 둥글기는 slop): `--r-xs` 6px 배지·기한·태그·코드·연결 상태 / `--r-sm` 8px 작은 면 /
  `--r-md` 12px 입력·지표 타일·셀렉트 / `--r-lg` 18px 카드·패널·카드형 행 / `--r-xl` 24px 초점 면(환영·집계·메모·선반·보드 열) /
  `--r-pill` 999px 버튼·탭·칩·상태 알약·진행 막대.
- 그림자는 바탕색 계열로 물들인다(검정 금지): `--sh-1` `0 2px 0 rgba(51, 55, 45, .04)` 눌린 면 / `--sh-2` `0 6px 15px rgba(51, 55, 45, .08)`
  hover·선택 탭 / `--sh-pop` `0 16px 36px rgba(34, 41, 31, .16)` 메뉴·대화상자·알림. 다크는 각각 `rgba(0, 0, 0, .12/.22/.40)`.
  `--scrim` `rgba(36, 41, 33, .38)`/`rgba(0, 0, 0, .52)`: 대화상자 뒤·넓은 패널 뒤·표 스크롤 끝 그림자.

### 2.4 쌓임(z-index)

`--z-sticky` 4(설정 저장 막대·모바일 상세 막대) < `--z-header` 10 < `--z-overlay` 20(넓은 패널·/ 메뉴) < `--z-dropdown` 30(메뉴·프로젝트 선택)
< `--z-toast` 60 < `--z-skip` 100(본문 바로가기). 지역 쌓임(-1·0·1, 붓질·표 첫 열)만 숫자를 쓴다. 다른 숫자를 새로 만들지 않는다.

### 2.5 모션

| 토큰 | 값 | 쓰임 |
|---|---|---|
| `--dur-fast` | 180ms | hover·색 전환·카드 2px 들림 |
| `--dur-base` | 200ms | 알림·대화상자 등장 |
| `--dur-slow` | 800ms | 진행 막대 차오름 |
| `--dur-leaf` | 4s | 오늘 화분 잎 흔들림(2회, 무한 반복 없음) |
| `--ease` | `ease` | 기본 |
| `--ease-out` | `cubic-bezier(.2, .8, .2, 1)` | 등장·차오름 |

드래그 중 카드 불투명도 .4, 놓을 곳 점선. 움직임은 `transform`·`opacity`만. `prefers-reduced-motion: reduce`에서는 모든
animation·transition을 끈다(파일 맨 끝 규칙).

### 2.6 셸

`--header-h` 80px(모바일 115px, 실측). 패널·고정 막대의 `top`은 이 토큰으로만 계산한다.

---

## 3. 컴포넌트 (클래스 · 규칙 · 하지 말 것)

| 컴포넌트 | 클래스 | 규칙 | 하지 말 것 |
|---|---|---|---|
| 버튼 | `.btn` + `.primary` `.tint` `.sm` `.icon` `.link` `.danger`, `[aria-pressed]` | 화면당 주 버튼(`.primary`) 하나. 되돌릴 수 없는 행동은 `.danger`. 누르면 1px 내려간다 | 주 버튼 둘, 링크를 버튼처럼 칠하기, 아이콘만 있는 버튼에 `aria-label` 빠뜨리기 |
| 입력 | `label.field` > `.input`/`.select`/`.textarea`, `.helptext`, `label.check` | 라벨은 위, 도움말·오류는 아래. 클래스 없는 Django 위젯도 `:where()` 기본 규칙으로 같은 모양 | placeholder로 라벨 대신하기, 입력을 알약 모양으로 |
| 카드 | `.card`, `.card-head`, `.card > h2`, `.box`, `.card.compact`, `.card.alert` | 묶음에 의미가 있을 때만. 제목은 Jua 24px | 카드 안 카드, 한 줄짜리 묶음마다 카드 쌓기(→ `.group-stack` 구분선) |
| 배지 | `.badge` + `.high` `.primary` `.ok` `.warn` `.danger` `.info`, `.tag`, GitHub용 `.pr-open` `.pr-merged` `.pr-closed` `.pr-draft` | 6px 모서리의 납작한 표식. 상태·수량·종류 | 알약 배지 남발, 배지에 클릭 동작 |
| 칩 | `.chips .chip`(체크박스·버튼·링크) | 필터·토글. 눌림은 잉크 색 채움 + ✓ | 칩으로 주 행동 |
| 선택 카드 | `.radios .radio-card` | 설명이 필요한 선택지(프로젝트 상태 등) | 2개뿐인 선택에 쓰기 |
| 탭 | `nav.tabs a[aria-current="page"]`, `.view-switch` | 화면 안 이동. 현재 탭은 표면색 + 그림자 | 탭으로 동작 실행 |
| 대화상자 | 네이티브 `dialog` + `#dialog` HTMX 대상 | 생성·수정 폼. 긴 폼은 하단 버튼 줄이 붙는다 | 확인 한 번이면 될 일을 대화상자로 |
| 패널 | `aside#panel .panel`, `.panel-bar`(상태 메뉴·저장 표시·복사·닫기) | 상태는 고정 막대에서 바꾼다. 저장 표시 `#save-status`는 숨기지 않는다 | 상태 폼 복제 |
| 표 | `table.grid`, `.num`, `.table-scroll`(+`.table-scroll-hint`), `td.empty-cell` | 모바일은 카드 안에서 가로 스크롤 | 페이지 전체가 가로로 흔들리게 두기 |
| 빈 상태 | `.empty`(화분 76px), `.empty.compact`(글자만), `td.empty-cell` | 다음 행동을 한 문장으로. 큰 화분은 화면당 하나 | 모든 빈 곳에 화분 |
| 알림 | `.notice`(세이지) `.notice.warn` `.notice.bad`, `.toast` | 경고·실패는 ⚠ 글리프를 앞에 둔다(색 외 단서). 일반 알림엔 글리프 없음. 토스트는 3초 | ⓘ 같은 장식 글리프, 감탄부호 |
| 지표 | `.tiles .tile`, `.stats .stat`, `.bar` | 첫 칸(대표)만 세이지, 위험 수치(`b.danger`)는 코랄, 나머지 바탕색 | 의미 없는 색 돌림 |

## 4. 업무 부품

- **상태 알약 7종** `.pill.{todo|doing|review|blocked|paused|done|cancelled}` — select와 읽기 전용(`.pill.static`) 공용, 글자 앞에 상태 기호
  (`status_mark`)를 붙여 색 없이도 읽힌다. 색: 시작 전 soft · 진행 중 sage · 검토 대기 yellow · 막힘 coral · 일시정지/취소 soft+muted · 완료 success-soft.
- **기한** `.due` + `.today`(warning) `.overdue`(danger, 앞에 "!") `.none`(점선) `.closed`(중립 "목표일 …", 닫힌 태스크는 초과로 표시하지 않는다).
- **태스크 행** `ul.tasks > li.task-row` — 목록에서는 구분선 행, 보드 열에서는 흰 카드(18px). 링크 복사는 hover 때만(터치는 항상).
- **보드 열** `.board-track > .col[data-status]` + `.col-dot` — 미완료 5열만. 막힘·일시정지 열은 점선 테두리 + 투명 바탕(별도 상태임을 드러낸다).
- **결과 선반** `.shelf` `.shelf-head` `.shelf-tabs` `.shelf-filters` `.shelf-list` `.shelf-more` — 완료·취소 전체 건수, 기간·검색, 10건씩 더 보기.
- **달력** `.pcal-grid .pcal-cell`(+`.today`, `.is-empty`) `.pcal-task`(+`.closed`: 보조색+취소선, 투명도 금지) `.pcal-ms`(◆ 마일스톤). 오늘 일정 `.cal`.
- **오늘** `.today-grid` → `.hero` `.tally` `.focus-memo.memo` `.today-list-card` `.today-schedule-card`. 모바일: 환영 → 집계(가로 한 줄) → 목록 → 메모 → 일정.

## 5. 그림 · 장식

| 자산 | 파일·클래스 | 크기 규칙 | 쓰는 곳 |
|---|---|---|---|
| 화분(표정) | `templates/art/_plant.html`, 칠은 `.art-*` 클래스 | 환영 210×200(태블릿 160, 모바일 150×144 절대배치) | 오늘 환영, 스타일 가이드 |
| 화분(작은) | `--art-plant` 데이터 URI | 빈 상태 76px, 표 빈 칸 52px, 로그인 82px | `.empty`, `td.empty-cell`, `.auth-card` |
| 선반 | `templates/art/_shelf.html` | 108×66(모바일 72×44) | 결과 선반 머리 |
| 새싹 알림 | `app.js celebrate()` | 40px | 완료 성공 직후 |
| 메모·테이프 | `.memo`(코랄, -1.2°, 모바일 -0.8°) + `::before` 테이프 64×18 | 화면당 하나 | 오늘 '지금 할 한 가지' |
| 붓질 | `.page-head > h1::after` 노랑 14px(모바일 10px), -1° | 페이지 제목에 자동 | 프로젝트·조직·설정·요청 제목 |
| 반짝이 | 화분 SVG 안 `.spark`, 집계 면 `.tally-badge` | 2.4s 2회 | 오늘만 |
| 로고(워드마크) | `static/brand/udally.svg` — 글자 `--c-ink`, 얼굴(ll = 눈, y = 웃는 입) `--c-accent`, 다크 값은 파일 안 `prefers-color-scheme` | 헤더 높이 34px | 파비콘, 로그인 전 헤더, README |
| 로고(아이콘) | `static/brand/udally-icon.svg` — 얼굴만 잘라 `--c-yellow` 바탕에 `--c-ink` | 16px까지 읽힘 | 조직 전환 `.studio-mark`, Discord 봇 프로필 |

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

## 7. AI Slop 금지 규칙

출처: Taste Skill 원문(`design-concepts-astra/design-concepts/v4-critic/refs/tasteskill/skills/`). 대시보드 앱에 맞는 항목만
채택했다(마케팅 페이지용 규칙 — 스크롤 애니메이션·글래스·자석 버튼·폰트 교체 — 은 03 결정과 충돌하므로 따르지 않는다).

| 금지 | 출처 | 이 앱의 규칙 · 2026-10-05 정리 내용 |
|---|---|---|
| 모든 요소 같은 둥글기 | redesign-skill/SKILL.md:53 | 역할별 모서리(2.3). 배지·기한·태그·코드·연결 상태를 알약 → 6px, 입력류 알약(필터 셀렉트·검색) → 12px, 카드·패널 24 → 18px |
| 알약 모양 배지 남발 | redesign-skill/SKILL.md:95 | 위와 같음. 알약은 누를 수 있는 것(버튼·탭·칩·상태 select)만 |
| 장식용 그라데이션·광원 원(orb) | taste-skill/SKILL.md:101, soft-skill/SKILL.md:25 | 환영 면 오른쪽 위 반투명 원 제거. 식물·반짝이(1차 원본)만 남김 |
| 의미 없는 아이콘·이모지 | redesign-skill/SKILL.md:107-108 | 일반 알림의 ⓘ 글리프 전부 제거(⚠만 남김), "자동 추가" 앞 ✦(AI '마법' 반짝이) 제거 → 기울임 글자 |
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

**의도적으로 유지한 것**: 오늘 인사의 큰 Jua 제목(taste-skill/SKILL.md:109 "Oversized H1" 금지와 다르게, 사용자가 고른 '강'의 핵심 장식이라
오늘 화면에만 둔다), 메모의 기울기, 버튼의 알약 모양(03 README "버튼 캡슐").

## 8. 접근성

- 글자 대비 4.5:1 이상(2.1 표). `--c-faint`는 읽어야 하는 글자에 쓰지 않는다. 코랄 위에는 잉크 글자.
- 초점: `:focus-visible { outline: 3px solid var(--c-accent); outline-offset: 2px }`, 입력은 테두리 + 3px `--c-accent-soft` 링. 초점 표시를 지우지 않는다.
- 터치 44px: 모바일(≤700px)에서 버튼·상태 select·입력·패널 안 링크형 버튼·지표 링크 모두 44px 이상.
- 상태는 색 + 글자(+ 기호)로. 경고는 ⚠. 장식 SVG는 `aria-hidden="true"`.
- 본문 바로가기 `.skip-link`, 알림 `role="status"`, 저장 표시 `aria-live="polite"`, 표 스크롤 영역 `tabindex="0" role="region" aria-label`.
- 모션 감소 설정을 존중한다(2.5).

## 9. 반응형 기준점

| 기준 | 바뀌는 것 |
|---|---|
| ≤1150px | 패널이 열리면 본문을 숨기고 패널만. 지표 3열. 태블릿 머리 간격 축소 |
| ≤960px | 오늘 그리드 1열(환영 → 집계 → 목록 → 메모 → 일정) |
| ≤850px | 회의록 목록/편집 전환, 설정 행 세로 카드 |
| ≤720px | 프로젝트 달력이 날짜 목록으로(빈 날짜 숨김) |
| ≤700px | 머리줄 2줄(`--header-h` 115px), 레일 → 프로젝트 선택기, 보드 열 스냅 스크롤, 지표 가로 스크롤 한 줄, 집계 가로 한 줄, 터치 44px, 입력 16px |
| ≤360px | 회의록 메타 1열, 설정 선택지 1열 |

## 10. 다크 모드

- 운영체제 설정(`prefers-color-scheme`)을 따른다. 별도 토글을 두지 않는다.
- 검정으로 뒤집지 않는다: 바탕 `#242921`, 표면 `#30362C`의 따뜻한 올리브. 색면은 같은 이름의 어두운 값(노랑 `#675723` 등).
- 강조는 밝은 살구 `#FFC3AD`, 강조 위 글자는 진한 갈색. 그림자는 검정 계열로 더 짙게.
- 새 색 토큰을 만들면 **반드시 다크 값도** 넣는다(테스트가 라이트에만 있는 색 토큰을 막는다).

## 11. 새 화면 체크리스트

1. 정보 구조는 기존 메뉴·URL을 따른다. 제목은 `.page-head`(붓질 자동) 또는 `.card > h2`.
2. 색·크기·간격·모서리·그림자·z-index는 토큰으로만. 템플릿에 `style`·`#RRGGBB`를 쓰지 않는다(데이터 퍼센트 제외).
3. 기존 컴포넌트를 먼저 쓴다(3·4장). 새 클래스가 필요하면 app.css 해당 절에 추가하고 이 문서 표에 한 줄 적는다.
4. 장식은 화면당 초점 하나. 카드 안 카드·한 줄짜리 카드 반복·색 돌림·장식 글리프 금지(7장).
5. 빈 상태·오류·저장 중·권한 없음 상태를 그린다. 문구는 격식체, 감탄부호 없이.
6. 연동 상태는 `.conn-state`, 조치 필요 경고는 `.notice.warn`.
7. 기능 훅(`hx-*`, `name`, `id`, `data-action`, URL)은 바꾸지 않는다.
8. 390×844·1440×1050, 라이트·다크 네 장을 찍어 본다(첫 업무가 첫 화면에 들어오는지, 44px, 가로 넘침).
9. `/ops/design`에 새 부품 견본을 추가한다.
10. `uv run pytest -q`(디자인 시스템 테스트 포함)와 ruff를 통과한다.
