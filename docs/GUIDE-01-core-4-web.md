# 구현 지시서 01-4: core — 웹 화면 (Step 6)


> **이 문서는 2026-09-10에 끝난 최초 구축의 기록이다.** 지금 할 일은 [GUIDE-V2-00-overview.md](GUIDE-V2-00-overview.md)부터 시작하는 묶음이다. 이 문서에 나오는 `Team`·`teams`·"팀"은 2026-09-11 개명 전 용어로 **조직**을 뜻한다. 대조표는 [GUIDE-V2-01](GUIDE-V2-01-org-teams.md) §1에 있다.

이전: [01-3](GUIDE-01-core-3-api.md). Django 템플릿 + HTMX + 직접 쓴 CSS. SPA 없음. 뷰는 전부 함수형이고 업무 규칙은 services만 부른다.

개정 2026-09-10: 목업(`README.md`, `유달리 업무 목업 v2.dc.html`, `TaskRow2.dc.html`) 기준으로 전면 재작성. 색·크기·문구는 README 표가 원본이다. 이 문서와 README가 다르면 README를 따르고 완료 보고에 적는다.

개정 2026-09-10 (Discord 봇): 프로필의 Discord ID 입력칸 → `[Discord 연결]` 코드 발급 카드, 알림 채널 화면·웹훅 뷰·라우트 삭제, `/ops` 내보내기 필드 조정.

화면 5개(오늘·내 태스크·팀 현황·프로젝트·검색) + 상세 패널 + 프로젝트 모달이 목업 범위다. 로그인·가입·초대·멤버·프로필·토큰·ops는 목업 밖이며 같은 CSS로 단순하게 만든다.

파일 구성:

```
core/web/
  urls.py
  forms.py
  context.py                 셸 context processor (현재 팀, 프로젝트 레일, nav)
  templatetags/__init__.py  templatetags/rows.py   {% task_row %} inclusion tag
  views/
    __init__.py  common.py  auth.py  today.py  me.py  teams.py  projects.py
    tasks.py  search.py  settings.py  ops.py
  templates/
    base.html
    auth/login.html  auth/signup.html  auth/join.html
    today.html  today/_head.html  today/_quick.html  today/_list.html  today/_schedule.html
    me.html  search.html  ops.html
    teams/list.html  teams/new.html  teams/detail.html  teams/members.html
    projects/detail.html  projects/_dialog.html  projects/_task_form.html
    tasks/detail.html  tasks/edit.html
    tasks/_row.html  tasks/_panel.html  tasks/_stop.html  tasks/_extend.html
    tasks/_checklist.html  tasks/_links.html  tasks/_history.html
    settings/profile.html  settings/tokens.html
  static/
    vendor/htmx.min.js
    app.css  app.js
```

동작 원칙:

- 목록 상태(필터·그룹·보기·팀원·일정 열림)는 **쿼리 파라미터**다. 새로고침해도 유지된다.
- 상세 패널은 `<aside id="panel">`에 `hx-get`으로 넣고 주소를 `/tasks/{id}`로 바꾼다. 목록은 다시 그리지 않는다.
- 행은 자기 자신만 갱신한다. 패널에서 팀 데이터가 바뀌면 응답 헤더 `HX-Trigger`로 `task-changed`를 쏘고, 그 태스크의 행만 `/tasks/{id}/row`를 다시 받는다. 행에서 상태를 바꾸면 `task-updated`를 쏘고 패널·오늘 화면 머리가 갱신된다.
- 제목·설명·완료 조건·다음 행동·진행 메모는 `change`(메모는 입력 후 600ms)마다 `/tasks/{id}/text/<field>`로 저장하고 `204 + HX-Trigger: saved`를 받는다. 화면 갱신 없음.
- 상태 select에서 `막힘`을 고르면 바로 보내지 않고 패널을 열어 사유 박스를 보여 준다(`app.js`). 사유와 함께 확정 버튼으로 전환한다.
- `# ponytail: 내 태스크·프로젝트의 그룹 개수("완료 n/m")는 행 갱신 뒤에도 낡아 있을 수 있다. 새로고침이 고친다.`

---

## 6.1 정적 파일

`core/web/static/vendor/htmx.min.js`를 내려받는다 (CDN 링크를 HTML에 쓰지 않는다):

```bash
curl -L -o core/web/static/vendor/htmx.min.js https://unpkg.com/htmx.org@2.0.4/dist/htmx.min.js
```

### `core/web/static/app.css` (전체)

README "Design Tokens" 표를 그대로 옮긴 것이다. 값을 바꾸지 않는다.

```css
:root {
  --bg-page: #EEF3F5; --bg-surface: #FFFFFF; --bg-secondary: #F5F8F9; --bg-fill: #F0F4F6;
  --text-primary: #191F28; --text-secondary: #636D7A; --text-disabled: #B0B8C1; --border: #E5E8EB;
  --primary: #1F6F82; --primary-pressed: #155463; --primary-bg: #E3F1F4; --on-primary: #FFFFFF;
  --danger: #C92A37; --danger-bg: #FEF0F1; --success: #12793F; --success-bg: #EDF9F2;
  --warning: #A85B00; --warning-bg: #FEF6EA;
}
@media (prefers-color-scheme: dark) {
  :root {
    --bg-page: #17171C; --bg-surface: #202027; --bg-secondary: #26262E; --bg-fill: #2E2E38;
    --text-primary: #E7E9EE; --text-secondary: #9FA4AF; --text-disabled: #5B5F6B; --border: #33333E;
    --primary: #5CC1D2; --primary-pressed: #8AD5E1; --primary-bg: #1B3A42; --on-primary: #17171C;
    --danger: #FF6B6B; --danger-bg: #3A2226; --success: #34C77B; --success-bg: #1E3328;
    --warning: #F5A93F; --warning-bg: #3A2F1E;
  }
}

/* ---- 기본 ---- */
* { box-sizing: border-box; }
html {
  font-family: Pretendard, -apple-system, 'Apple SD Gothic Neo', 'Noto Sans KR', sans-serif;
  font-size: 14px; line-height: 20px; color: var(--text-primary); background: var(--bg-page);
  word-break: keep-all;
}
body { margin: 0; }
button, input, select, textarea { font: inherit; color: inherit; }
a { color: var(--primary); }
h1, h2, h3 { margin: 0; font-weight: 700; letter-spacing: -0.02em; }
p { margin: 0; }
.t12 { font-size: 12px; line-height: 16px; } .t13 { font-size: 13px; line-height: 19px; }
.t15 { font-size: 15px; line-height: 22px; } .t16 { font-size: 16px; line-height: 24px; }
.t17 { font-size: 17px; line-height: 26px; } .t20 { font-size: 20px; line-height: 28px; }
.t22 { font-size: 22px; line-height: 30px; } .t24 { font-size: 24px; line-height: 33px; }
.t28 { font-size: 28px; line-height: 38px; }
.muted { color: var(--text-secondary); } .danger { color: var(--danger); } .warning { color: var(--warning); }
.error { color: var(--danger); font-size: 15px; line-height: 22px; }
.row { display: flex; flex-wrap: wrap; gap: 8px 16px; align-items: center; }
.stack { display: flex; flex-direction: column; gap: 8px; }
[hidden] { display: none !important; }

/* ---- 셸 ---- */
.header {
  position: sticky; top: 0; z-index: 10; height: 64px; display: flex; align-items: center; gap: 16px;
  padding: 0 24px; background: var(--bg-surface); border-bottom: 1px solid var(--border);
}
.logo { font-size: 20px; font-weight: 700; color: var(--text-primary); text-decoration: none; }
.nav { display: flex; gap: 4px; }
.nav a {
  display: inline-flex; align-items: center; height: 44px; padding: 0 14px; border-radius: 8px;
  color: var(--text-secondary); font-weight: 500; text-decoration: none;
}
.nav a[aria-current="page"] { background: var(--primary-bg); color: var(--primary); font-weight: 700; }
.spacer { flex: 1; }
.menu { position: relative; }
.menu > summary { list-style: none; cursor: pointer; }
.menu > summary::-webkit-details-marker { display: none; }
.avatar {
  width: 36px; height: 36px; border-radius: 999px; background: var(--primary-bg); color: var(--primary);
  display: inline-flex; align-items: center; justify-content: center; font-weight: 700;
}
.menu-list {
  position: absolute; right: 0; top: 44px; min-width: 180px; padding: 8px; display: flex; flex-direction: column;
  gap: 4px; background: var(--bg-surface); border: 1px solid var(--border); border-radius: 8px;
  box-shadow: 0 8px 32px rgba(15,50,60,.2);
}
.menu-list a, .menu-list button {
  display: block; width: 100%; text-align: left; padding: 8px 10px; border: 0; background: none;
  border-radius: 6px; color: var(--text-primary); text-decoration: none; cursor: pointer;
}
.menu-list a:hover, .menu-list button:hover { background: var(--bg-secondary); }
.frame { display: flex; align-items: flex-start; }
.rail {
  position: sticky; top: 64px; flex: none; width: 190px; max-height: calc(100vh - 64px); overflow: auto;
  padding: 16px 8px; display: flex; flex-direction: column; gap: 2px;
}
.rail a {
  display: flex; align-items: center; gap: 8px; height: 40px; padding: 0 10px; border-radius: 8px;
  color: var(--text-primary); text-decoration: none; font-size: 13px; white-space: nowrap; overflow: hidden;
}
.rail a[aria-current="page"] { background: var(--primary-bg); color: var(--primary); font-weight: 700; }
.rail .initial {
  flex: none; width: 24px; height: 24px; border-radius: 6px; background: var(--bg-fill);
  display: inline-flex; align-items: center; justify-content: center; font-size: 12px; font-weight: 700;
}
.layout { flex: 1; min-width: 0; display: flex; align-items: flex-start; gap: 16px; padding: 24px; }
.layout > main { flex: 1 1 0; min-width: 0; display: flex; flex-direction: column; gap: 16px; }
aside#panel { flex: 1 1 380px; max-width: 480px; position: sticky; top: 88px; max-height: calc(100vh - 112px); overflow: auto; }
aside#panel:empty { display: none; }
.layout.wide > main { display: none; }
.layout.wide aside#panel { flex: 9999 1 480px; max-width: none; }
.layout.wide .panel-body { display: grid; grid-template-columns: repeat(auto-fit, minmax(380px, 1fr)); gap: 24px; }

/* ---- 카드 · 버튼 · 입력 ---- */
.card {
  background: var(--bg-surface); border: 1px solid var(--border); border-radius: 12px; padding: 24px;
  display: flex; flex-direction: column; gap: 16px;
}
.card > h2, .card-head h2 { font-size: 17px; line-height: 26px; }
.card-head { display: flex; flex-wrap: wrap; align-items: center; justify-content: space-between; gap: 8px 16px; }
.btn {
  display: inline-flex; align-items: center; justify-content: center; gap: 6px; height: 44px; padding: 0 16px;
  border-radius: 8px; border: 1px solid var(--border); background: var(--bg-surface); color: var(--text-primary);
  font-weight: 600; cursor: pointer; text-decoration: none; white-space: nowrap;
}
.btn:hover { background: var(--bg-secondary); }
.btn.primary { background: var(--primary); border-color: var(--primary); color: var(--on-primary); }
.btn.primary:hover { background: var(--primary-pressed); }
.btn.tint { background: var(--primary-bg); border-color: var(--primary-bg); color: var(--primary); }
.btn.sm { height: 36px; padding: 0 12px; font-size: 13px; border-radius: 6px; }
.btn.icon { width: 36px; padding: 0; }
.btn.link { height: auto; padding: 0; border: 0; background: none; color: var(--primary); font-weight: 600; }
.btn[aria-pressed="true"] { background: var(--primary-bg); border-color: var(--primary-bg); color: var(--primary); }
.input, .select, .textarea {
  width: 100%; height: 44px; padding: 0 12px; border: 1px solid var(--border); border-radius: 6px;
  background: var(--bg-surface); color: var(--text-primary);
}
.input.lg { height: 52px; font-size: 16px; }
.select.auto { width: auto; }
.textarea { height: auto; padding: 10px 12px; resize: vertical; }
.input:focus, .select:focus, .textarea:focus { outline: 2px solid var(--primary-bg); border-color: var(--primary); }
label.field { display: flex; flex-direction: column; gap: 6px; font-size: 13px; color: var(--text-secondary); }
label.field > .input, label.field > .select, label.field > .textarea { color: var(--text-primary); }
label.check { display: inline-flex; align-items: center; gap: 6px; min-height: 44px; cursor: pointer; }

/* ---- 지표 ---- */
.stats { display: flex; flex-wrap: wrap; gap: 8px 24px; }
.stat {
  display: inline-flex; align-items: baseline; gap: 6px; padding: 0; border: 0; background: none;
  color: var(--text-primary); text-decoration: none; cursor: pointer;
}
.stat b { font-size: 19px; line-height: 26px; font-weight: 700; }
.stat span { font-size: 13px; color: var(--text-secondary); }
.tiles { display: grid; grid-template-columns: repeat(6, 1fr); gap: 12px; }
.tiles.five { grid-template-columns: repeat(5, 1fr); }
.tile {
  display: flex; flex-direction: column; gap: 4px; padding: 16px; background: var(--bg-surface);
  border: 1px solid var(--border); border-radius: 12px; color: var(--text-primary); text-decoration: none; text-align: left;
}
.tile b { font-size: 26px; line-height: 32px; font-weight: 700; }
.tile span { font-size: 13px; color: var(--text-secondary); }

/* ---- 태스크 행 (TaskRow2) ---- */
ul.tasks { list-style: none; margin: 0; padding: 0; display: flex; flex-direction: column; gap: 8px; }
.task-row {
  display: flex; flex-wrap: wrap; gap: 8px 16px; align-items: center; justify-content: space-between;
  min-height: 56px; padding: 10px 14px; border: 1px solid var(--border); border-radius: 8px;
  background: var(--bg-surface); cursor: pointer; transition: background 150ms cubic-bezier(0.3,0,0.2,1);
}
.task-row:hover { background: var(--bg-secondary); }
.task-row.selected { box-shadow: inset 3px 0 0 var(--primary); }
.task-row .main { min-width: 0; flex: 1 1 240px; display: flex; flex-direction: column; gap: 4px; }
.task-row .next { font-size: 16px; line-height: 24px; font-weight: 600; }
.task-row .proj { font-size: 12px; line-height: 16px; color: var(--text-secondary); }
.task-row .title { font-size: 16px; line-height: 24px; font-weight: 600; }
.task-row.closed .title { text-decoration: line-through; }
.task-row .has-next .title { font-size: 14px; font-weight: 500; }
.task-row .meta { display: flex; flex-wrap: wrap; gap: 4px 8px; align-items: center; font-size: 13px; line-height: 19px; color: var(--text-secondary); }
.badge {
  display: inline-block; white-space: nowrap; padding: 0 6px; border-radius: 4px; font-size: 12px; line-height: 18px;
  border: 1px solid var(--border); color: var(--text-secondary);
}
.badge.high { font-weight: 700; }
.task-row .actions { display: flex; flex-wrap: wrap; gap: 8px; align-items: center; max-width: 100%; }
.due { font-size: 13px; line-height: 19px; white-space: nowrap; color: var(--text-secondary); }
.due.overdue { color: var(--danger); }
.pill {
  height: 36px; padding: 0 10px; border-radius: 999px; border: 0; font-size: 13px; font-weight: 700; cursor: pointer;
  background: var(--bg-fill); color: var(--text-primary);
}
.pill.doing { background: #F5A623; color: #1F1400; }
.pill.paused, .pill.cancelled { color: var(--text-secondary); }
.pill.blocked { background: #F6C9C4; color: #6B1410; }
.pill.review { background: #CFE3F7; color: #0B3A66; }
.pill.done { background: #B9E6CB; color: #0B3D22; }
.pill.sm { height: 24px; font-size: 12px; padding: 0 8px; }
.pill:disabled { cursor: default; opacity: .7; }
.today-btn.in { background: var(--bg-fill); color: var(--text-secondary); }
.today-btn.auto { background: var(--primary-bg); border-color: var(--primary-bg); color: var(--primary); }

/* ---- 그룹 · 표 · 보드 ---- */
.group { display: flex; flex-direction: column; gap: 12px; }
.subgroup { display: flex; flex-direction: column; gap: 8px; }
.subgroup .head { display: flex; align-items: center; gap: 12px; }
.subgroup .bar { flex: 1; height: 8px; border-radius: 999px; background: var(--bg-fill); overflow: hidden; }
.subgroup .bar i { display: block; height: 100%; background: var(--primary); }
.subgroup ul.tasks { border-left: 2px solid var(--border); padding-left: 12px; }
table.grid { width: 100%; border-collapse: collapse; }
table.grid th, table.grid td { text-align: left; padding: 10px 8px; border-bottom: 1px solid var(--border); vertical-align: top; }
table.grid th { font-size: 13px; font-weight: 600; color: var(--text-secondary); }
table.grid .num { text-align: right; }
.board { display: grid; grid-auto-flow: column; grid-auto-columns: minmax(260px, 1fr); gap: 12px; overflow-x: auto; }
.board .col { display: flex; flex-direction: column; gap: 8px; }
.board .col h3 { font-size: 15px; line-height: 22px; }

/* ---- 상세 패널 ---- */
.panel { background: var(--bg-surface); border: 1px solid var(--border); border-radius: 12px; padding: 20px; display: flex; flex-direction: column; gap: 16px; }
.panel-bar { display: flex; align-items: center; gap: 8px; }
.panel-bar .status { flex: 1; font-size: 13px; color: var(--text-secondary); }
.panel .number { font-size: 13px; color: var(--text-secondary); }
.panel .title-input { width: 100%; padding: 0; border: 0; border-bottom: 1px solid transparent; background: none; font-size: 20px; line-height: 28px; font-weight: 600; }
.panel .title-input:focus { outline: none; border-bottom-color: var(--primary); }
.panel .meta { display: flex; flex-wrap: wrap; gap: 6px 12px; align-items: center; font-size: 13px; color: var(--text-secondary); }
.panel .meta .select { height: 24px; width: auto; padding: 0 6px; font-size: 12px; }
.section { display: flex; flex-direction: column; gap: 8px; }
.section > .label { font-size: 13px; font-weight: 600; color: var(--text-secondary); }
.stop-box { display: flex; flex-direction: column; gap: 8px; padding: 12px; background: var(--bg-secondary); border: 1px solid var(--border); border-radius: 8px; }
.due-block .value { font-size: 17px; line-height: 26px; font-weight: 600; }
.checklist { list-style: none; margin: 0; padding: 0; display: flex; flex-direction: column; gap: 6px; }
.checklist li { display: flex; align-items: center; gap: 8px; }
.checklist li .text { flex: 1; }
.checklist li.done .text { text-decoration: line-through; color: var(--text-secondary); }
.checklist .btn.icon { width: 30px; height: 30px; font-size: 13px; }
.notes { min-height: 120px; }
.links { list-style: none; margin: 0; padding: 0; display: flex; flex-direction: column; gap: 6px; }
details > summary { cursor: pointer; font-weight: 600; }
.history { list-style: none; margin: 8px 0 0; padding: 0; display: flex; flex-direction: column; gap: 8px; font-size: 13px; }
.history .who { color: var(--text-secondary); }
.focus h2 { font-size: 28px; line-height: 38px; }
.today-columns { display: flex; flex-wrap: wrap; gap: 16px; align-items: flex-start; }
.today-columns > * { flex: 1 1 380px; }
.today-columns > .schedule { flex: 1 1 280px; max-width: 360px; }

/* ---- 모달 · 칩 · 라디오 ---- */
dialog { width: calc(100% - 32px); max-width: 520px; padding: 24px; border: 0; border-radius: 12px; background: var(--bg-surface); color: var(--text-primary); box-shadow: 0 8px 32px rgba(15,50,60,.2); }
dialog::backdrop { background: rgba(15,50,60,.35); }
.chips { display: flex; flex-wrap: wrap; gap: 8px; }
.chip { display: inline-flex; align-items: center; height: 44px; padding: 0 14px; border: 1px solid var(--border); border-radius: 999px; cursor: pointer; }
.chip input { display: none; }
.chip:has(input:checked) { border-color: var(--primary); background: var(--primary-bg); color: var(--primary); }
.radios { display: flex; flex-direction: column; gap: 8px; }
.radio-card { display: flex; flex-direction: column; gap: 2px; padding: 10px 12px; border: 1px solid var(--border); border-radius: 8px; cursor: pointer; }
.radio-card input { display: none; }
.radio-card:has(input:checked) { border-color: var(--primary); background: var(--primary-bg); }
.radio-card b { font-size: 15px; line-height: 22px; font-weight: 600; }
.radio-card span { font-size: 13px; color: var(--text-secondary); }

/* ---- 일정 ---- */
.cal { display: grid; grid-template-columns: repeat(7, 1fr); gap: 4px; }
.cal a, .cal span { display: flex; flex-direction: column; align-items: center; justify-content: center; height: 44px; border: 1px solid transparent; border-radius: 6px; font-size: 13px; color: var(--text-primary); text-decoration: none; }
.cal a.today { background: var(--primary); color: var(--on-primary); }
.cal a.sel { border-color: var(--primary); background: var(--primary-bg); }
.cal a small { font-size: 10px; color: var(--primary); }
.cal a.today small { color: var(--on-primary); }
.hours div { height: 32px; border-top: 1px solid var(--border); font-size: 12px; color: var(--text-secondary); }

/* ---- 반응형 ---- */
@media (max-width: 1150px) {
  .layout.has-panel > main { display: none; }
  .layout.has-panel aside#panel { flex: 1 1 auto; max-width: none; }
  .tiles { grid-template-columns: repeat(3, 1fr); }
}
@media (max-width: 700px) {
  .header { flex-wrap: wrap; height: auto; padding: 8px 12px; row-gap: 4px; }
  .nav { order: 3; width: 100%; }
  .frame { flex-direction: column; }
  .rail { position: static; width: 100%; max-height: none; flex-direction: row; overflow-x: auto; padding: 8px 12px; gap: 4px; }
  .rail a { flex: none; }
  .layout { padding: 12px; }
  .layout.has-panel aside#panel { position: fixed; inset: 0; z-index: 20; max-height: none; overflow: auto; }
  .layout.has-panel .panel { border-radius: 0; min-height: 100%; }
  .tiles, .tiles.five { grid-template-columns: repeat(2, 1fr); }
  .pill, .btn.sm, .btn.icon { height: 40px; }
  .today-columns > .schedule { max-width: none; }
}
@media (prefers-reduced-motion: reduce) { * { transition: none !important; } }
```

### `core/web/static/app.js` (전체)

```js
// 유달리 — 표시 보조만. 상태와 규칙은 서버에 있다.
(function () {
  var body = document.body;
  var t1, t2;

  function flash(text, after) {
    var el = document.getElementById("save-status");
    if (!el) return;
    clearTimeout(t1); clearTimeout(t2);
    el.textContent = text;
    if (after) t1 = setTimeout(function () { el.textContent = after; }, 400);
    t2 = setTimeout(function () { el.textContent = ""; }, 2500);
  }

  function openPanel(url, pushUrl) {
    htmx.ajax("GET", url, { target: "#panel", swap: "innerHTML" });
    if (pushUrl) history.pushState(null, "", pushUrl);
  }

  // 자동 저장 상태 표시
  body.addEventListener("htmx:beforeRequest", function (e) {
    if (e.target.hasAttribute && e.target.hasAttribute("data-autosave")) flash("저장 중…");
  });
  body.addEventListener("saved", function () { flash("자동 저장됨"); });
  body.addEventListener("htmx:responseError", function (e) {
    alert("저장하지 못했습니다. 페이지를 새로고침한 뒤 다시 시도하세요. (" + e.detail.xhr.status + ")");
  });

  // 행 전체 클릭 → 패널. 행 안의 컨트롤은 제외.
  body.addEventListener("click", function (e) {
    var row = e.target.closest(".task-row");
    if (!row || e.target.closest("button, select, a, input, textarea, form")) return;
    openPanel(row.dataset.panel, "/tasks/" + row.dataset.id);
  });
  body.addEventListener("keydown", function (e) {
    if (!e.target.classList || !e.target.classList.contains("task-row")) return;
    if (e.key === "Enter" || e.key === " ") { e.preventDefault(); e.target.click(); }
  });

  // 링크 복사
  body.addEventListener("click", function (e) {
    var b = e.target.closest("[data-copy]");
    if (!b) return;
    e.preventDefault(); e.stopPropagation();
    var id = b.dataset.copy, url = location.origin + "/tasks/" + id;
    var done = function () { flash("TASK-" + id + " 링크 복사됨"); };
    (navigator.clipboard ? navigator.clipboard.writeText(url) : Promise.reject())
      .then(done, function () { prompt("링크를 복사하세요", url); done(); });
  });

  // 상태 select에서 '막힘' 선택 → 보내지 않고 패널의 사유 박스를 연다. (HTMX는 hx-trigger 필터로 이미 막혀 있다)
  body.addEventListener("change", function (e) {
    var s = e.target;
    if (!s.matches || !s.matches("select[data-status]")) return;
    if (s.value === "blocked" && s.dataset.status !== "blocked") {
      openPanel(s.dataset.panel + "?block=1", "/tasks/" + s.dataset.id);
      s.value = s.dataset.status;
    }
  });

  // 패널·다이얼로그 스왑 후 처리
  body.addEventListener("htmx:afterSwap", function (e) {
    var layout = document.querySelector(".layout");
    if (e.target.id === "panel" && layout) {
      var open = e.target.children.length > 0;
      layout.classList.toggle("has-panel", open);
      layout.classList.toggle("wide", open && localStorage.getItem("panel-wide") === "1");
      var w = e.target.querySelector("[data-action='toggle-wide']");
      if (w) w.textContent = layout.classList.contains("wide") ? "옆으로 보기" : "크게 보기";
      var f = e.target.querySelector("[data-focus]");
      if (f) f.focus();
    }
    if (e.target.id === "dialog" && e.target.children.length) e.target.showModal();
  });

  // data-action 버튼
  body.addEventListener("click", function (e) {
    var b = e.target.closest("[data-action]");
    if (!b) return;
    var layout = document.querySelector(".layout"), panel = document.getElementById("panel"), dlg = document.getElementById("dialog");
    var a = b.dataset.action;
    if (a === "close-panel") {
      panel.innerHTML = ""; layout.classList.remove("has-panel", "wide");
      history.replaceState(null, "", body.dataset.pageUrl || "/today");
    } else if (a === "toggle-wide") {
      var on = !layout.classList.contains("wide");
      layout.classList.toggle("wide", on); localStorage.setItem("panel-wide", on ? "1" : "0");
      b.textContent = on ? "옆으로 보기" : "크게 보기";
    } else if (a === "close-dialog") {
      dlg.close(); dlg.innerHTML = "";
    } else if (a === "toggle") {
      var el = document.querySelector(b.dataset.target);
      el.hidden = !el.hidden;
      if (b.dataset.alt) { var t = b.textContent; b.textContent = b.dataset.alt; b.dataset.alt = t; }
      if (!el.hidden) { var i = el.querySelector("input:not([type=hidden]), textarea"); if (i) i.focus(); }
    }
  });
  var dlg = document.getElementById("dialog");
  if (dlg) dlg.addEventListener("click", function (e) { if (e.target === dlg) { dlg.close(); dlg.innerHTML = ""; } });

  // #task-N 해시로 진입하면 패널을 연다 (생성 직후 리다이렉트, 공유 링크 호환)
  function openHash() {
    var m = /#task-(\d+)/.exec(location.hash);
    if (m) openPanel("/tasks/" + m[1] + "/panel", null);
  }
  openHash();
  window.addEventListener("hashchange", openHash);
})();
```

---

## 6.2 `core/web/urls.py`

```python
from django.contrib.auth import views as auth_views
from django.urls import path

from .views import auth, me, ops, projects, search, settings, tasks, teams, today

urlpatterns = [
    path("", auth.root, name="root"),
    path("healthz", ops.healthz, name="healthz"),
    path("login", auth_views.LoginView.as_view(template_name="auth/login.html", redirect_authenticated_user=True), name="login"),
    path("logout", auth_views.LogoutView.as_view(), name="logout"),
    path("signup", auth.signup, name="signup"),
    path("join/<str:token>", auth.join, name="join"),

    path("today", today.today, name="today"),
    path("today/quick", today.quick_add, name="today_quick"),
    path("today/add/<int:task_id>", today.add, name="today_add"),
    path("today/exclude/<int:task_id>", today.exclude, name="today_exclude"),
    path("today/restore", today.restore, name="today_restore"),
    path("today/move/<int:task_id>/<str:direction>", today.move, name="today_move"),
    path("today/settings", today.auto_pull, name="today_settings"),

    path("me", me.me, name="me"),

    path("team", teams.team_current, name="team"),
    path("teams", teams.team_list, name="team_list"),
    path("teams/new", teams.team_new, name="team_new"),
    path("teams/<int:team_id>", teams.team_detail, name="team_detail"),
    path("teams/<int:team_id>/members", teams.members, name="team_members"),
    path("teams/<int:team_id>/invites", teams.invite_create, name="invite_create"),
    path("teams/invites/<int:invite_id>/revoke", teams.invite_revoke, name="invite_revoke"),
    path("teams/memberships/<int:membership_id>/role", teams.member_role, name="member_role"),
    path("teams/memberships/<int:membership_id>/remove", teams.member_remove, name="member_remove"),

    path("projects/new", projects.project_new, name="project_new"),
    path("projects/<int:project_id>", projects.project_detail, name="project_detail"),
    path("projects/<int:project_id>/edit", projects.project_edit, name="project_edit"),
    path("projects/<int:project_id>/tasks", projects.task_create, name="project_task_create"),
    path("projects/<int:project_id>/archive", projects.project_archive, name="project_archive"),
    path("projects/<int:project_id>/restore", projects.project_restore, name="project_restore"),
    path("projects/<int:project_id>/links", projects.link_add, name="project_link_add"),

    path("tasks/<int:task_id>", tasks.task_detail, name="task_detail"),
    path("tasks/<int:task_id>/panel", tasks.task_panel, name="task_panel"),
    path("tasks/<int:task_id>/row", tasks.task_row, name="task_row"),
    path("tasks/<int:task_id>/edit", tasks.task_edit, name="task_edit"),
    path("tasks/<int:task_id>/status", tasks.task_status, name="task_status"),
    path("tasks/<int:task_id>/text/<str:field>", tasks.task_text, name="task_text"),
    path("tasks/<int:task_id>/priority", tasks.task_priority, name="task_priority"),
    path("tasks/<int:task_id>/extend", tasks.task_extend, name="task_extend"),
    path("tasks/<int:task_id>/stop-reason", tasks.task_stop_reason, name="task_stop_reason"),
    path("tasks/<int:task_id>/checklist", tasks.checklist_add, name="checklist_add"),
    path("tasks/checklist/<int:item_id>/<str:action>", tasks.checklist_action, name="checklist_action"),
    path("tasks/<int:task_id>/links", tasks.link_add, name="task_link_add"),
    path("tasks/links/<int:link_id>/delete", tasks.link_delete, name="link_delete"),

    path("search", search.search, name="search"),

    path("settings/profile", settings.profile, name="profile"),
    path("settings/profile/discord", settings.discord_link, name="discord_link"),
    path(
        "settings/profile/discord/unlink", settings.discord_unlink, name="discord_unlink"
    ),
    path("settings/tokens", settings.tokens, name="tokens"),
    path("settings/tokens/<int:token_id>/revoke", settings.token_revoke, name="token_revoke"),

    path("ops", ops.ops, name="ops"),
    path("ops/export.json", ops.export_json, name="export_json"),
]
```

`/tasks/new`, `/projects/new` 페이지는 없다. 태스크는 오늘 화면의 빠른 추가와 프로젝트 화면의 인라인 폼으로, 프로젝트는 모달로 만든다. `projects/new`·`projects/<id>/edit` URL은 모달 부분 템플릿을 돌려준다.

---

## 6.3 `core/web/forms.py`

```python
from django import forms
from django.contrib.auth.forms import UserCreationForm

from accounts.models import User
from projects.models import Project
from tasks.models import Link, Task

PRIORITY_CHOICES = [(n, str(n)) for n in range(10, 0, -1)]


class SignupForm(UserCreationForm):
    class Meta:
        model = User
        fields = ("username", "display_name")
        labels = {"username": "아이디", "display_name": "표시 이름"}


class TeamForm(forms.Form):
    name = forms.CharField(label="팀 이름", max_length=100)
    purpose = forms.CharField(label="목적 한 줄", max_length=200, required=False)


class InviteForm(forms.Form):
    days = forms.IntegerField(label="만료(일)", min_value=1, max_value=90, initial=7)


class ProjectForm(forms.Form):
    """프로젝트 모달. 관리자는 체크 칩, 상태는 카드형 라디오로 템플릿이 직접 그린다."""

    # 빈 이름 검사는 services.create_project/update_project가 한다(업무 규칙은 services에만).
    name = forms.CharField(label="이름", max_length=100, required=False)
    purpose = forms.CharField(label="목적", max_length=200, required=False, widget=forms.Textarea(attrs={"rows": 2}))
    owners = forms.ModelMultipleChoiceField(label="관리자", queryset=User.objects.none(), required=False)
    status = forms.ChoiceField(label="상태", choices=Project.STATUSES, initial="preparing")
    version = forms.IntegerField(widget=forms.HiddenInput, required=False)

    def __init__(self, *args, team, **kwargs):
        super().__init__(*args, **kwargs)
        self.fields["owners"].queryset = team.members.filter(is_active=True).order_by("display_name")


class TaskForm(forms.Form):
    """전체 수정 화면(/tasks/{id}/edit). 담당자·프로젝트·기한 미정 사유는 여기서만 바꾼다."""

    project = forms.ModelChoiceField(label="프로젝트", queryset=Project.objects.none())
    title = forms.CharField(label="제목", max_length=200)
    assignee = forms.ModelChoiceField(label="담당자", queryset=User.objects.none())
    priority = forms.TypedChoiceField(label="중요도", choices=PRIORITY_CHOICES, coerce=int, initial=5)
    due_date = forms.DateField(label="목표 기한", required=False, widget=forms.DateInput(attrs={"type": "date"}))
    no_due_reason = forms.CharField(label="기한 미정 사유", max_length=200, required=False)
    description = forms.CharField(label="설명", required=False, widget=forms.Textarea(attrs={"rows": 4}))
    done_when = forms.CharField(label="완료 조건", max_length=300, required=False)
    next_action = forms.CharField(label="다음 행동", max_length=200, required=False)
    version = forms.IntegerField(widget=forms.HiddenInput)

    def __init__(self, *args, team, **kwargs):
        super().__init__(*args, **kwargs)
        self.fields["project"].queryset = Project.objects.filter(team=team, is_archived=False).order_by("name")
        self.fields["assignee"].queryset = team.members.filter(is_active=True).order_by("display_name")


class TaskInlineForm(forms.Form):
    """프로젝트 화면의 태스크 만들기 인라인 폼."""

    title = forms.CharField(max_length=200)
    assignee = forms.ModelChoiceField(queryset=User.objects.none())
    priority = forms.TypedChoiceField(choices=PRIORITY_CHOICES, coerce=int, initial=5)
    due_date = forms.DateField(required=False, widget=forms.DateInput(attrs={"type": "date"}))
    no_due_reason = forms.CharField(max_length=200, required=False)
    # IdempotencyKey.key는 varchar(100)이다. 클라이언트가 보내는 값이므로 폼에서 막는다.
    idem = forms.CharField(widget=forms.HiddenInput, required=False, max_length=100)

    def __init__(self, *args, team, **kwargs):
        super().__init__(*args, **kwargs)
        self.fields["assignee"].queryset = team.members.filter(is_active=True).order_by("display_name")


class QuickTaskForm(forms.Form):
    """오늘 화면의 빠른 추가: 제목·프로젝트·중요도·기한(없으면 사유). 담당자는 본인."""

    title = forms.CharField(max_length=200)
    project = forms.ModelChoiceField(queryset=Project.objects.none())
    priority = forms.TypedChoiceField(choices=PRIORITY_CHOICES, coerce=int, initial=5)
    due_date = forms.DateField(required=False, widget=forms.DateInput(attrs={"type": "date"}))
    no_due_reason = forms.CharField(max_length=200, required=False)
    idem = forms.CharField(widget=forms.HiddenInput, required=False)

    def __init__(self, *args, user, **kwargs):
        super().__init__(*args, **kwargs)
        from teams.services import teams_of

        self.fields["project"].queryset = (
            Project.objects.filter(team__in=teams_of(user), is_archived=False)
            .select_related("team").order_by("team__name", "name")
        )


class LinkForm(forms.Form):
    title = forms.CharField(label="제목", max_length=100)
    url = forms.URLField(label="URL", max_length=500)
    kind = forms.ChoiceField(label="종류", choices=Link.KINDS, initial="doc")


class ProfileForm(forms.Form):
    """Discord 사용자 ID 입력칸은 없다 — 연결은 코드 교환으로만 이뤄진다(GUIDE-00 §3)."""

    display_name = forms.CharField(label="표시 이름", max_length=50)


class TokenForm(forms.Form):
    name = forms.CharField(label="이름", max_length=50)
    scope = forms.ChoiceField(label="범위", choices=[("read", "읽기"), ("write", "읽기·쓰기")], initial="read")
```

`ProfileForm`에 `discord_user_id`가 없고, `TokenForm`의 범위에 `bot`이 없다. 둘 다 **위조·자기 발급 경로를 남기지 않으려고** 빠진 것이다(GUIDE-00 §3). 그 이름으로 POST가 와도 폼에 필드가 없으니 무시된다.

---

## 6.4 공통: `views/common.py`, `context.py`, `templatetags/rows.py`

### `core/web/views/common.py`

```python
import json
import uuid
from datetime import date, timedelta
from urllib.parse import urlencode

from django.http import Http404, HttpResponse
from django.shortcuts import redirect
from django.utils import timezone

from accounts.models import User
from common.dates import fmt_md, today_kst
from common.errors import ServiceError
from projects.models import Project
from tasks.models import Task
from tasks.services import get_visible_task, today_flag, today_membership
from teams.models import Team
from teams.services import is_admin, is_member, teams_of

CONFLICT_MSG = "다른 사람이 먼저 수정했습니다. 최신 내용을 다시 확인하세요."


def task_or_404(user, task_id):
    task = get_visible_task(user, task_id)
    if task is None:
        raise Http404
    return task


def _pk_or_404(value) -> int:
    """URL·쿼리에서 온 id를 정수로. 숫자가 아니면 404.

    filter(pk="abc")는 Django가 ValueError를 던져 500이 된다. 공유 헬퍼에서 한 번 막는다.
    """
    try:
        return int(value)
    except (TypeError, ValueError):
        raise Http404 from None


def team_or_404(user, team_id):
    team = Team.objects.filter(pk=_pk_or_404(team_id)).first()
    if team is None or not is_member(user, team):
        raise Http404
    return team


def project_or_404(user, project_id):
    p = Project.objects.filter(pk=_pk_or_404(project_id)).select_related("team").prefetch_related("owners").first()
    if p is None or not is_member(user, p.team):
        raise Http404
    return p


def current_team(request):
    """세션의 team_id가 내 팀이면 그 팀, 아니면 이름순 첫 팀. 팀이 없으면 None."""
    teams = list(teams_of(request.user).order_by("name"))
    if not teams:
        return None
    tid = request.session.get("team_id")
    for t in teams:
        if t.pk == tid:
            return t
    return teams[0]


def apply_service_error(form, exc: ServiceError):
    """ServiceError의 {필드: 메시지}를 폼 오류로 옮긴다. 폼에 없는 필드는 non_field로."""
    for field, msg in exc.errors.items():
        form.add_error(field if field in form.fields else None, msg)


def new_idem() -> str:
    return uuid.uuid4().hex


def can_admin(user, team) -> bool:
    return is_admin(user, team)


def hx_redirect(request, url: str):
    """HTMX 요청이면 204 + HX-Redirect, 아니면 일반 302."""
    if request.headers.get("HX-Request"):
        return HttpResponse(status=204, headers={"HX-Redirect": url})
    return redirect(url)


def trigger(response, event: str, task=None):
    """응답에 HX-Trigger 헤더를 붙인다. task를 주면 {"event": {"id": n}} 형식."""
    response["HX-Trigger"] = json.dumps({event: {"id": task.pk}}) if task else event
    return response


def version_of(request) -> int:
    try:
        return int(request.POST.get("version", 0))
    except ValueError:
        return 0


# ---------- 표시 문자열 ----------

def due_label(task) -> str:
    """행 우측 기한 라벨: '오늘 마감' / '9월 12일' / '기한 미정', 초과면 ' 초과'."""
    if not task.due_date:
        return "기한 미정"
    label = "오늘 마감" if task.due_date == today_kst() else fmt_md(task.due_date)
    return label + " 초과" if task.is_overdue else label


def due_full(task) -> str:
    """패널 목표일 블록: '2026년 9월 12일 (초과)' / '기한 미정 · 사유'."""
    if task.due_date:
        return f"{task.due_date.year}년 {fmt_md(task.due_date)}" + (" (초과)" if task.is_overdue else "")
    return "기한 미정" + (f" · {task.no_due_reason}" if task.no_due_reason else "")


FIELD_LABELS = {
    "created": "생성", "status": "상태", "assignee": "담당자", "due_date": "기한", "project": "프로젝트",
    "priority": "중요도", "stop_reason": "사유", "completed_at": "완료 시각", "owners": "관리자", "is_archived": "보관",
}


def _display(field, raw: str) -> str:
    if raw == "":
        return "없음"
    if field == "status":
        return dict(Task.STATUSES).get(raw, raw)
    if field == "priority":
        return f"{raw}/10"
    if field == "due_date":
        return fmt_md(date.fromisoformat(raw))
    if field == "completed_at":
        return raw[:10]
    if field == "assignee":
        u = User.objects.filter(pk=raw).first()
        return u.display_name if u else raw
    if field == "project":
        p = Project.objects.filter(pk=raw).first()
        return p.name if p else raw
    if field == "owners":
        names = [u.display_name for u in User.objects.filter(pk__in=raw.split(","))]
        return ", ".join(names) or raw
    return raw


def history_rows(logs) -> list[dict]:
    """ChangeLog → 패널 표시용. 최신이 먼저."""
    rows = []
    for log in logs:
        to = _display(log.field, log.new_value)
        if log.note:
            to += f" ({log.note})"
        at = timezone.localtime(log.created_at)
        rows.append({
            "field": FIELD_LABELS.get(log.field, log.field),
            "from": _display(log.field, log.old_value),
            "to": to,
            "time": f"{at.month}월 {at.day}일 {at:%H:%M}",
            "actor": log.actor.display_name,
            "source": log.get_source_display(),
        })
    return rows


# ---------- 태스크 행 ----------

ROW_OPTS = ("next", "move", "noassignee", "notoday", "ro", "today")


def row_ctx(user, task, opts: str = "", membership: dict | None = None, selected_id=None) -> dict:
    """tasks/_row.html 렌더링 context.
    opts: 쉼표 구분. next(다음 행동 표시) move(↑↓) noassignee(담당자 숨김) notoday(오늘 버튼 숨김)
          ro(상태 select 비활성) today(오늘 화면 안: 목록 전체를 갱신, 자기 갱신 없음)."""
    o = {x for x in opts.split(",") if x in ROW_OPTS}
    m = membership or today_membership(user)
    flag = today_flag(task, m)
    items = list(task.checklist.all())
    opts = ",".join(sorted(o))
    return {
        "task": task,
        "row_opts": opts,
        "row_query": urlencode({"opts": opts}),
        "show_next": "next" in o and bool(task.next_action),
        "show_move": "move" in o and flag == "manual",
        "hide_assignee": "noassignee" in o,
        "hide_today": "notoday" in o,
        "read_only": "ro" in o,
        "in_today_page": "today" in o,
        "row_target": "#today-list" if "today" in o else f"#task-{task.pk}",
        "in_today": flag != "",
        "auto_pulled": flag == "auto",
        "selected": task.pk == selected_id,
        "checklist_done": sum(1 for i in items if i.is_done),
        "checklist_total": len(items),
        "due_label": due_label(task),
    }


def rows_for(user, tasks, opts: str = "", selected_id=None) -> list[dict]:
    m = today_membership(user)
    return [row_ctx(user, t, opts, m, selected_id) for t in tasks]


def render_row(request, task, error=None):
    """행 하나를 다시 그린다. opts는 요청의 POST 또는 GET `opts`에서 읽는다."""
    from django.shortcuts import render

    opts = request.POST.get("opts") or request.GET.get("opts", "")
    ctx = row_ctx(request.user, task, opts)
    ctx["error"] = error
    return render(request, "tasks/_row.html", ctx)


def week_days(day: date) -> list[date | None]:
    """월간 달력 셀. 그 달 1일 앞의 빈칸(None) + 날짜. 월요일 시작."""
    first = day.replace(day=1)
    if first.month == 12:
        # date.max(9999-12-31)에서 다음 달을 계산하면 OverflowError가 난다.
        nxt = date(first.year, 12, 31) if first.year == date.max.year else date(first.year + 1, 1, 1)
    else:
        nxt = date(first.year, first.month + 1, 1)
    cells: list[date | None] = [None] * first.weekday()
    d = first
    while d < nxt:
        cells.append(d)
        d += timedelta(days=1)
    return cells
```

`core/web/views/__init__.py`는 빈 파일.

### `core/web/context.py` (context processor)

```python
from .views.common import current_team

NAV_BY_URL = {
    "today": "today", "today_quick": "today",
    "me": "me",
    "team": "team", "team_list": "team", "team_detail": "team", "team_members": "team", "team_new": "team",
    "search": "search",
}


def shell(request):
    """base.html 셸: 현재 팀, 프로젝트 레일, nav 강조, 닫기 후 돌아갈 주소."""
    if not request.user.is_authenticated:
        return {}
    team = current_team(request)
    match = request.resolver_match
    url_name = match.url_name if match else ""
    return {
        "current_team": team,
        "nav_projects": team.projects.filter(is_archived=False).order_by("name") if team else [],
        "nav": NAV_BY_URL.get(url_name, ""),
        "current_project_id": match.kwargs.get("project_id") if match else None,
        "page_url": request.get_full_path(),
        "team_count": request.user.teams.count(),
    }
```

`config/settings.py`의 `TEMPLATES[0]["OPTIONS"]["context_processors"]`에 `"web.context.shell"`을 추가한다.

### `core/web/templatetags/rows.py`

```python
from django import template

register = template.Library()


@register.inclusion_tag("tasks/_row.html")
def task_row(ctx: dict):
    """{% task_row r %} — r은 views.common.row_ctx()가 만든 dict."""
    return ctx
```

`core/web/templatetags/__init__.py`는 빈 파일. 템플릿 맨 위에서 `{% load rows %}`.

---

## 6.5 `core/web/views/auth.py`

```python
from django.contrib import messages
from django.contrib.auth import login
from django.contrib.auth.decorators import login_required
from django.shortcuts import redirect, render

from common.errors import ServiceError
from teams.services import join_by_token

from ..forms import SignupForm


def root(request):
    return redirect("today" if request.user.is_authenticated else "login")


def signup(request):
    if request.user.is_authenticated:
        return redirect("today")
    form = SignupForm(request.POST or None)
    if request.method == "POST" and form.is_valid():
        user = form.save()
        login(request, user)
        messages.info(request, "가입되었습니다. 팀에 참여하려면 초대 링크가 필요합니다.")
        return redirect(request.GET.get("next") or "today")
    return render(request, "auth/signup.html", {"form": form})


@login_required
def join(request, token):
    if request.method == "POST":
        try:
            team = join_by_token(request.user, token)
        except ServiceError as e:
            return render(request, "auth/join.html", {"error": e.errors["token"]})
        request.session["team_id"] = team.pk
        messages.success(request, f"{team.name} 팀에 참여했습니다.")
        return redirect("today")
    return render(request, "auth/join.html", {"token": token})
```

`login_required`는 비로그인 사용자를 `/login?next=/join/<token>`으로 보낸다. 로그인 화면에는 "계정이 없으면 가입" 링크를 `?next=` 를 유지한 채 `/signup?next=...`로 둔다.

---

## 6.6 `core/web/views/today.py` (전체 코드)

```python
from datetime import date

from django.contrib.auth.decorators import login_required
from django.db.models import Count
from django.shortcuts import render
from django.urls import reverse
from django.views.decorators.http import require_POST

from accounts.models import User
from common.dates import fmt_md
from common.errors import ServiceError
from tasks import services as ts
from tasks.models import Task

from ..forms import QuickTaskForm
from .common import (
    apply_service_error, due_label, hx_redirect, new_idem, render_row, rows_for, task_or_404, trigger,
    week_days,
)

ROW_OPTS = "next,move,noassignee,today"
WEEKDAYS = "월화수목금토일"
HOURS = [f"{h:02d}:00" for h in range(9, 19)]


def _ctx(request):
    v = ts.today_view(request.user)
    day = v["date"]
    v["date_label"] = f"{day.year}년 {day.month}월 {day.day}일 ({WEEKDAYS[day.weekday()]})"
    v["today_hint"] = f"오늘 태스크 {v['counts']['today']}건" if v["focus"] else "오늘 태스크 없음"
    v["rows"] = rows_for(request.user, v["items"], ROW_OPTS)
    v["done_rows"] = rows_for(request.user, v["done_today"], "noassignee,notoday,today")
    v["auto_pull_choices"] = User.AUTO_PULL_CHOICES
    v["schedule_open"] = request.GET.get("schedule") == "1"
    v["focus_due"] = due_label(v["focus"]) if v["focus"] else ""
    return v


def _schedule(request, day: date) -> dict:
    """일정 카드. cal=time|month, day=YYYY-MM-DD. 기한에 시각이 없으므로 시간표는 눈금과 '종일' 목록만."""
    mode = "month" if request.GET.get("cal") == "month" else "time"
    try:
        sel = date.fromisoformat(request.GET.get("day", "")) if request.GET.get("day") else day
    except ValueError:
        sel = day
    # today_view와 같은 범위(팀 소속 태스크만)를 쓴다.
    my_open = ts.visible_tasks(request.user).filter(assignee=request.user, status__in=Task.OPEN)
    counts = dict(
        my_open.filter(due_date__year=sel.year, due_date__month=sel.month)
        .values_list("due_date").annotate(n=Count("id"))
    )
    cells = [
        None if d is None else {
            "day": d.day, "n": counts.get(d, 0), "today": d == day, "sel": d == sel,
            "url": f"{reverse('today')}?schedule=1&cal=month&day={d.isoformat()}",
            "aria": f"{d.month}월 {d.day}일 마감 {counts.get(d, 0)}건",
        }
        for d in week_days(sel)
    ]
    sel_tasks = sorted(my_open.filter(due_date=sel), key=ts.by_due)
    return {
        "cal_mode": mode,
        "cal_title": f"{sel.year}년 {sel.month}월" if mode == "month" else f"{fmt_md(day)} ({WEEKDAYS[day.weekday()]})",
        "cal_cells": cells,
        "cal_sel_label": f"{fmt_md(sel)} 마감 {len(sel_tasks)}건",
        "cal_sel_tasks": sel_tasks,
        "due_today_tasks": sorted(my_open.filter(due_date=day), key=ts.by_due),
        "hours": HOURS,
    }


@login_required
def today(request):
    v = _ctx(request)
    part = request.GET.get("part")
    if part == "head":
        return render(request, "today/_head.html", v)
    if part == "list":
        return render(request, "today/_list.html", v)
    v["quick_open"] = request.GET.get("quick") == "1"
    v["form"] = QuickTaskForm(user=request.user, initial={"idem": new_idem(), "priority": 5})
    if v["schedule_open"]:
        v.update(_schedule(request, v["date"]))
    return render(request, "today.html", v)


def head(request, error=None):
    """오늘 화면 머리(날짜·지표·지금 할 일 카드). tasks.task_status가 from=head일 때도 부른다."""
    v = _ctx(request)
    v["error"] = error
    return render(request, "today/_head.html", v)


def _list(request):
    return render(request, "today/_list.html", _ctx(request))


def _after_change(request, task):
    """오늘 화면 안이면 목록 전체, 다른 화면이면 그 행만 돌려준다. 머리는 today-changed로 갱신된다."""
    if "today" in request.GET.get("opts", ""):
        return trigger(_list(request), "today-changed")
    return trigger(render_row(request, task), "today-changed")


@login_required
@require_POST
def quick_add(request):
    form = QuickTaskForm(request.POST, user=request.user)
    if form.is_valid():
        d = form.cleaned_data
        try:
            task = ts.create_task(
                project=d["project"], title=d["title"], actor=request.user, source="web",
                priority=d["priority"], due_date=d["due_date"], no_due_reason=d["no_due_reason"],
                idempotency_key=d["idem"] or None,
            )
            ts.today_add(request.user, task)
            return hx_redirect(request, reverse("today"))
        except ServiceError as e:
            apply_service_error(form, e)
    return render(request, "today/_quick.html", {"form": form, "quick_open": True})


@login_required
@require_POST
def add(request, task_id):
    task = task_or_404(request.user, task_id)
    ts.today_add(request.user, task)
    return _after_change(request, task)


@login_required
@require_POST
def exclude(request, task_id):
    task = task_or_404(request.user, task_id)
    ts.today_exclude(request.user, task)
    return _after_change(request, task)


@login_required
@require_POST
def restore(request):
    ts.today_restore_excluded(request.user)
    return trigger(_list(request), "today-changed")


@login_required
@require_POST
def move(request, task_id, direction):
    ts.today_move(request.user, task_or_404(request.user, task_id), direction)
    return _list(request)


@login_required
@require_POST
def auto_pull(request):
    try:
        ts.today_set_auto_pull(request.user, int(request.POST.get("auto_pull_days", "5")))
    except (ValueError, ServiceError):
        pass
    return trigger(_list(request), "today-changed")
```

---

## 6.7 `core/web/views/tasks.py` (전체 코드)

```python
from datetime import date, timedelta

from django.contrib.auth.decorators import login_required
from django.http import Http404, HttpResponse
from django.shortcuts import get_object_or_404, redirect, render
from django.views.decorators.http import require_POST

from common.dates import today_kst
from common.errors import ConflictError, ServiceError
from tasks import services as ts
from tasks.models import ChangeLog, ChecklistItem, Link

from ..forms import LinkForm, TaskForm
from .common import (
    CONFLICT_MSG, apply_service_error, due_full, due_label, history_rows, project_or_404,
    render_row, task_or_404, trigger, version_of,
)


def _panel_ctx(request, task, **extra):
    logs = (
        ChangeLog.objects.filter(target_type="task", target_id=task.pk)
        .select_related("actor").order_by("-created_at", "-id")
    )
    checklist = list(task.checklist.all())
    ctx = {
        "task": task,
        "checklist": checklist,
        "checklist_done": sum(1 for i in checklist if i.is_done),
        "links": task.links.all(),
        "link_form": LinkForm(),
        "history": history_rows(logs),
        "priorities": range(10, 0, -1),
        "due_label": due_label(task),
        "due_full": due_full(task),
        "extend_min": task.due_date + timedelta(days=1) if task.due_date else today_kst(),
        "desc_rows": max(2, -(-len(task.description) // 40)),
        "stop_draft": task.stop_reason,
        "block_pending": request.GET.get("block") == "1",
        "focus_notes": request.GET.get("focus") == "notes",
        "full_page": False,
        "error": None, "stop_error": None, "extend_error": None, "extend_open": False,
    }
    ctx.update(extra)
    return ctx


def _panel(request, task, **extra):
    return render(request, "tasks/_panel.html", _panel_ctx(request, task, **extra))


def _respond(request, task, origin, error=None):
    """origin: 'row'(기본) | 'panel' | 'head'(오늘 화면 지금 할 일 카드)."""
    if origin == "panel":
        return _panel(request, task, error=error)
    if origin == "head":
        from .today import head

        return head(request, error=error)
    return render_row(request, task, error=error)


@login_required
def task_detail(request, task_id):
    task = task_or_404(request.user, task_id)
    return render(request, "tasks/detail.html", _panel_ctx(request, task, full_page=True))


@login_required
def task_panel(request, task_id):
    return _panel(request, task_or_404(request.user, task_id))


@login_required
def task_row(request, task_id):
    return render_row(request, task_or_404(request.user, task_id))


@login_required
def task_edit(request, task_id):
    task = task_or_404(request.user, task_id)
    initial = {
        "project": task.project, "title": task.title, "assignee": task.assignee,
        "priority": task.priority, "due_date": task.due_date, "no_due_reason": task.no_due_reason,
        "description": task.description, "done_when": task.done_when,
        "next_action": task.next_action, "version": task.version,
    }
    form = TaskForm(request.POST or None, team=task.project.team, initial=initial)
    if request.method == "POST" and form.is_valid():
        d = form.cleaned_data
        changes = {k: d[k] for k in ("project", "title", "assignee", "priority", "due_date",
                                      "no_due_reason", "description", "done_when", "next_action")}
        try:
            ts.update_task(task, changes, actor=request.user, source="web", expected_version=d["version"])
            return redirect("task_detail", task_id=task.pk)
        except ServiceError as e:
            apply_service_error(form, e)
        except ConflictError:
            form.add_error(None, CONFLICT_MSG)
    return render(request, "tasks/edit.html", {"form": form, "task": task})


@login_required
@require_POST
def task_status(request, task_id):
    task = task_or_404(request.user, task_id)
    origin = request.POST.get("from", "row")
    try:
        task = ts.transition(
            task, request.POST.get("status", ""), actor=request.user, source="web",
            reason=request.POST.get("reason", ""), expected_version=version_of(request),
        )
    except ServiceError as e:
        return _respond(request, task, origin, error=" ".join(e.errors.values()))
    except ConflictError as e:
        return _respond(request, e.latest, origin, error=CONFLICT_MSG)
    event = "task-changed" if origin == "panel" else "task-updated"
    return trigger(_respond(request, task, origin), event, task)


@login_required
@require_POST
def task_text(request, task_id, field):
    """자동 저장. 성공 204 + HX-Trigger: saved. 실패 400(본문은 메시지)."""
    task = task_or_404(request.user, task_id)
    try:
        ts.update_text(task, field, request.POST.get("value", ""), actor=request.user)
    except ServiceError as e:
        return HttpResponse(" ".join(e.errors.values()), status=400)
    return trigger(HttpResponse(status=204), "saved")


@login_required
@require_POST
def task_priority(request, task_id):
    task = task_or_404(request.user, task_id)
    try:
        priority = int(request.POST.get("priority", "0"))
    except ValueError:
        priority = 0
    try:
        task = ts.update_task(task, {"priority": priority}, actor=request.user, source="web", expected_version=version_of(request))
    except ServiceError as e:
        return _panel(request, task, error=" ".join(e.errors.values()))
    except ConflictError as e:
        return _panel(request, e.latest, error=CONFLICT_MSG)
    return trigger(_panel(request, task), "task-changed", task)


@login_required
@require_POST
def task_extend(request, task_id):
    task = task_or_404(request.user, task_id)
    raw = request.POST.get("due_date", "")
    try:
        new_date = date.fromisoformat(raw) if raw else None
    except ValueError:
        new_date = None
    try:
        task = ts.extend_due(task, new_date, request.POST.get("reason", ""), actor=request.user, source="web", expected_version=version_of(request))
    except ServiceError as e:
        return _panel(request, task, extend_open=True, extend_error=" ".join(e.errors.values()))
    except ConflictError as e:
        return _panel(request, e.latest, error=CONFLICT_MSG)
    return trigger(_panel(request, task), "task-changed", task)


@login_required
@require_POST
def task_stop_reason(request, task_id):
    """confirm_block=1이면 '막힘으로 변경'(transition), 아니면 이미 멈춘 태스크의 사유 저장(update_task)."""
    task = task_or_404(request.user, task_id)
    reason = request.POST.get("reason", "")
    pending = request.POST.get("confirm_block") == "1"
    try:
        if pending:
            task = ts.transition(task, "blocked", actor=request.user, source="web", reason=reason, expected_version=version_of(request))
        else:
            task = ts.update_task(task, {"stop_reason": reason}, actor=request.user, source="web", expected_version=version_of(request))
    except ServiceError as e:
        return _panel(request, task, block_pending=pending, stop_draft=reason, stop_error=" ".join(e.errors.values()))
    except ConflictError as e:
        return _panel(request, e.latest, error=CONFLICT_MSG)
    return trigger(_panel(request, task), "task-changed", task)


def _checklist(request, task, error=None):
    checklist = list(task.checklist.all())
    return render(request, "tasks/_checklist.html", {
        "task": task, "checklist": checklist,
        "checklist_done": sum(1 for i in checklist if i.is_done), "error": error,
    })


@login_required
@require_POST
def checklist_add(request, task_id):
    task = task_or_404(request.user, task_id)
    try:
        ts.checklist_add(task, request.POST.get("text", ""), actor=request.user)
    except ServiceError as e:
        return _checklist(request, task, error=" ".join(e.errors.values()))
    return trigger(_checklist(request, task), "task-changed", task)


@login_required
@require_POST
def checklist_action(request, item_id, action):
    item = get_object_or_404(ChecklistItem, pk=item_id)
    task = task_or_404(request.user, item.task_id)
    if action == "toggle":
        ts.checklist_toggle(item, actor=request.user)
    elif action == "delete":
        ts.checklist_delete(item, actor=request.user)
    elif action in ("up", "down"):
        ts.checklist_move(item, action, actor=request.user)
    else:
        raise Http404
    return trigger(_checklist(request, task), "task-changed", task)


def _links(request, task, error=None):
    return render(request, "tasks/_links.html", {
        "task": task, "links": task.links.all(), "link_form": LinkForm(), "error": error, "link_open": bool(error),
    })


@login_required
@require_POST
def link_add(request, task_id):
    task = task_or_404(request.user, task_id)
    form = LinkForm(request.POST)
    if not form.is_valid():
        return _links(request, task, error="링크 입력이 올바르지 않습니다.")
    d = form.cleaned_data
    try:
        ts.add_link(actor=request.user, task=task, title=d["title"], url=d["url"], kind=d["kind"])
    except ServiceError as e:
        return _links(request, task, error=" ".join(e.errors.values()))
    return _links(request, task)


@login_required
@require_POST
def link_delete(request, link_id):
    link = get_object_or_404(Link, pk=link_id)
    if link.task_id:
        task = task_or_404(request.user, link.task_id)
        ts.delete_link(link, actor=request.user)
        return _links(request, task)
    project_or_404(request.user, link.project_id)
    ts.delete_link(link, actor=request.user)
    return redirect("project_detail", project_id=link.project_id)
```

---

## 6.8 `core/web/views/projects.py` (전체 코드)

```python
from django.contrib import messages
from django.contrib.auth.decorators import login_required
from django.shortcuts import redirect, render
from django.urls import reverse
from django.views.decorators.http import require_POST

from common.errors import ConflictError, ServiceError
from projects.models import Project
from projects.services import (
    archive_project, create_project, project_stats, restore_project, update_project,
)
from tasks import services as ts
from tasks.models import Task

from ..forms import LinkForm, ProjectForm, TaskInlineForm
from .common import (
    CONFLICT_MSG, apply_service_error, can_admin, hx_redirect, new_idem, project_or_404, rows_for,
    team_or_404,
)


def _dialog(request, form, team, project=None):
    """프로젝트 생성·수정 모달 부분 템플릿."""
    return render(request, "projects/_dialog.html", {
        "form": form, "team": team, "project": project,
        "members": team.members.filter(is_active=True).order_by("display_name"),
        "checked_owner_ids": {int(x) for x in (form["owners"].value() or [])},
        "status_options": [(code, label, Project.STATUS_DESC[code]) for code, label in Project.STATUSES],
        "status_value": form["status"].value() or "preparing",
    })


@login_required
def project_new(request):
    team = team_or_404(request.user, request.GET.get("team") or request.POST.get("team"))
    form = ProjectForm(request.POST or None, team=team)
    if request.method == "POST" and form.is_valid():
        d = form.cleaned_data
        try:
            p = create_project(
                team=team, name=d["name"], purpose=d["purpose"], owners=list(d["owners"]),
                status=d["status"], actor=request.user, source="web",
            )
            request.session["team_id"] = team.pk
            return hx_redirect(request, reverse("project_detail", args=[p.pk]))
        except ServiceError as e:
            apply_service_error(form, e)
    return _dialog(request, form, team)


@login_required
def project_edit(request, project_id):
    project = project_or_404(request.user, project_id)
    initial = {
        "name": project.name, "purpose": project.purpose, "status": project.status,
        "owners": list(project.owners.all()), "version": project.version,
    }
    form = ProjectForm(request.POST or None, team=project.team, initial=initial)
    if request.method == "POST" and form.is_valid():
        d = form.cleaned_data
        changes = {"name": d["name"], "purpose": d["purpose"], "owners": list(d["owners"]), "status": d["status"]}
        try:
            update_project(project, changes, actor=request.user, source="web", expected_version=d["version"] or 0)
            return hx_redirect(request, reverse("project_detail", args=[project.pk]))
        except ServiceError as e:
            apply_service_error(form, e)
        except ConflictError:
            form.add_error(None, CONFLICT_MSG)
    return _dialog(request, form, project.team, project)


@login_required
def project_detail(request, project_id):
    project = project_or_404(request.user, project_id)
    request.session["team_id"] = project.team_id
    view = "board" if request.GET.get("view") == "board" else "list"
    include_closed = request.GET.get("include_closed") == "1"
    qs = project.tasks.select_related("project", "assignee")
    if not include_closed:
        qs = qs.filter(status__in=Task.OPEN)
    rows = rows_for(request.user, sorted(qs, key=ts.by_due))
    columns = [
        (code, label, [r for r in rows if r["task"].status == code])
        for code, label in Task.STATUSES
        if code in Task.OPEN or include_closed
    ]
    form = TaskInlineForm(team=project.team, initial={"assignee": request.user.pk, "priority": 5, "idem": new_idem()})
    return render(request, "projects/detail.html", {
        "project": project, "owners": list(project.owners.all()), "links": project.links.all(),
        "stats": project_stats(project), "view": view, "include_closed": include_closed,
        "rows": rows, "columns": columns, "form": form, "form_open": request.GET.get("new") == "1",
        "is_admin": can_admin(request.user, project.team), "link_form": LinkForm(),
    })


@login_required
@require_POST
def task_create(request, project_id):
    """인라인 태스크 폼. 성공하면 프로젝트 화면으로 돌아가며 #task-{id}로 패널을 연다."""
    project = project_or_404(request.user, project_id)
    form = TaskInlineForm(request.POST, team=project.team)
    if form.is_valid():
        d = form.cleaned_data
        try:
            task = ts.create_task(
                project=project, title=d["title"], actor=request.user, source="web",
                assignee=d["assignee"], priority=d["priority"], due_date=d["due_date"],
                no_due_reason=d["no_due_reason"], idempotency_key=d["idem"] or None,
            )
            return hx_redirect(request, reverse("project_detail", args=[project.pk]) + f"#task-{task.pk}")
        except ServiceError as e:
            apply_service_error(form, e)
    return render(request, "projects/_task_form.html", {"form": form, "project": project, "form_open": True})


@login_required
@require_POST
def project_archive(request, project_id):
    project = project_or_404(request.user, project_id)
    try:
        archive_project(project, actor=request.user, source="web")
        messages.success(request, "프로젝트를 보관했습니다.")
    except ServiceError as e:
        msg = e.errors.get("tasks")
        messages.error(request, f"미완료 태스크가 있어 보관할 수 없습니다: {msg}" if msg else " ".join(e.errors.values()))
    return redirect("project_detail", project_id=project.pk)


@login_required
@require_POST
def project_restore(request, project_id):
    project = project_or_404(request.user, project_id)
    try:
        restore_project(project, actor=request.user, source="web")
    except ServiceError as e:
        messages.error(request, " ".join(e.errors.values()))
    return redirect("project_detail", project_id=project.pk)


@login_required
@require_POST
def link_add(request, project_id):
    project = project_or_404(request.user, project_id)
    form = LinkForm(request.POST)
    if form.is_valid():
        d = form.cleaned_data
        try:
            ts.add_link(actor=request.user, project=project, title=d["title"], url=d["url"], kind=d["kind"])
        except ServiceError as e:
            messages.error(request, " ".join(e.errors.values()))
    else:
        messages.error(request, "링크 입력이 올바르지 않습니다.")
    return redirect("project_detail", project_id=project.pk)
```

## 6.9 `core/web/views/me.py` (전체 코드)

```python
from django.contrib.auth.decorators import login_required
from django.http import Http404
from django.shortcuts import render

from accounts.models import User
from projects.models import Project
from tasks import services as ts
from tasks.services import today_membership
from teams.services import teams_of

from .common import project_or_404, row_ctx


@login_required
def me(request):
    g = request.GET
    member, member_id = None, request.user.pk
    raw = g.get("member", "")
    if raw == "0":
        member, member_id = 0, 0
    elif raw.isdecimal() and int(raw) != request.user.pk:
        member = (
            User.objects.filter(pk=int(raw), is_active=True, memberships__team__in=teams_of(request.user))
            .distinct().first()
        )
        if member is None:
            raise Http404
        member_id = member.pk
    project = project_or_404(request.user, g["project"]) if g.get("project", "").isdecimal() else None
    group = g.get("group") if g.get("group") in dict(ts.GROUP_OPTIONS) else "due"
    f = {"due": g.get("due", ""), "project": g.get("project", ""), "status": g.get("status", ""), "priority": g.get("priority", "")}
    view = ts.me_view(
        request.user, member=member, group=group, due=f["due"], project=project,
        status=f["status"], priority=f["priority"],
    )
    opts = "ro,notoday" if member is not None else "noassignee"
    m = today_membership(request.user)
    for grp in view["groups"]:
        grp["rows"] = [row_ctx(request.user, t, opts, m) for t in grp["tasks"]]
        for p in grp["projects"]:
            p["rows"] = [row_ctx(request.user, t, opts, m) for t in p["tasks"]]
            p["count_label"] = f"완료 {p['done']}/{p['total']}"
    return render(request, "me.html", {
        "view": view, "groups": view["groups"], "group": group, "f": f, "has_filter": any(f.values()),
        "member_id": member_id,
        "members": User.objects.filter(is_active=True, memberships__team__in=teams_of(request.user)).distinct().order_by("display_name"),
        "projects": Project.objects.filter(team__in=teams_of(request.user), is_archived=False).order_by("name"),
        "due_options": ts.DUE_FILTERS, "status_options": ts.STATUS_FILTERS,
        "priority_options": ts.PRIORITY_FILTERS, "group_options": ts.GROUP_OPTIONS,
    })
```

## 6.10 `core/web/views/teams.py`

`team_current`와 `team_detail`은 전체 코드. 나머지는 동작 명세.

```python
from django.conf import settings
from django.contrib import messages
from django.contrib.auth.decorators import login_required
from django.http import Http404
from django.shortcuts import get_object_or_404, redirect, render
from django.urls import reverse
from django.views.decorators.http import require_POST

from common.errors import ServiceError
from projects.services import project_stats
from reports.services import team_status
from teams import services as tsv
from teams.models import Invite, Membership

from ..forms import InviteForm, TeamForm
from .common import apply_service_error, can_admin, current_team, team_or_404


@login_required
def team_current(request):
    team = current_team(request)
    if team is None:
        return redirect("team_list")
    return redirect("team_detail", team_id=team.pk)


@login_required
def team_detail(request, team_id):
    """팀 현황. README §3."""
    team = team_or_404(request.user, team_id)
    request.session["team_id"] = team.pk
    include_archived = request.GET.get("include_archived") == "1"
    st = team_status(team)
    c = st["counts"]
    me_url = reverse("me")
    tiles = [
        ("미완료", c["open"], f"{me_url}?member=0"),
        ("기한 초과", c["overdue"], f"{me_url}?member=0&due=overdue"),
        ("이번 주 마감", c["due_this_week"], f"{me_url}?member=0&due=this_week"),
        ("검토 대기", c["review"], f"{me_url}?member=0&status=review"),
        ("막힘", c["blocked"], f"{me_url}?member=0&status=blocked"),
        ("기한 미정", c["no_due"], f"{me_url}?member=0&due=none"),
    ]
    projects = team.projects.prefetch_related("owners").order_by("name")
    if not include_archived:
        projects = projects.filter(is_archived=False)
    return render(request, "teams/detail.html", {
        "team": team, "tiles": tiles,
        "project_rows": [(p, project_stats(p)) for p in projects],
        "by_assignee": st["by_assignee"], "me_url": me_url,
        "include_archived": include_archived, "is_admin": can_admin(request.user, team),
    })
```

- `team_list`: 내 팀 목록. 팀이 없으면 "초대 링크가 필요합니다" 안내와 "팀 만들기" 링크. 팀이 정확히 하나면 `team_detail`로 redirect.
- `team_new`: `TeamForm` → `tsv.create_team`. 성공 시 세션 `team_id` 저장 후 `team_detail`.
- 팀 관리자 전용 화면은 모두 이 관문을 지난다. 팀원에게는 403이 아니라 **404**로 감춘다.

```python
def _admin_only(request, team_id):
    """팀 관리자 전용 화면의 공통 관문. 팀원에게는 화면 자체를 숨긴다(404)."""
    team = team_or_404(request.user, team_id)
    if not can_admin(request.user, team):
        raise Http404
    return team


@login_required
def members(request, team_id):
    """팀원 관리. 역할·제거·초대에 더해, 제거 판단에 필요한 업무량을 함께 보여준다."""
    team = _admin_only(request, team_id)
    load = {r["assignee_id"]: r for r in team_status(team)["by_assignee"]}
    rows = [
        {"m": m, "load": load.get(m.user_id)}
        for m in team.memberships.select_related("user").order_by("user__display_name")
    ]
    return render(
        request,
        "teams/members.html",
        {
            "team": team,
            "rows": rows,
            "admin_count": sum(1 for r in rows if r["m"].role == "admin"),
            "invites": team.invites.filter(revoked_at__isnull=True),
            "form": InviteForm(),
            "site_url": settings.SITE_URL,
            "is_admin": True,
        },
    )
```

`rows`의 `load`는 `team_status(team)["by_assignee"]`를 담당자 id로 찾은 것이다(미완료·기한 초과 건수).
팀장이 제거·역할 변경을 판단할 때 필요한 숫자라 같은 화면에 둔다. 새 집계 함수를 만들지 않는다.

알림 채널 화면은 없다. 웹훅 뷰 7개(`webhooks`·`webhook_create`·`webhook_toggle`·`webhook_delete`·`webhook_test`와 헬퍼 `_webhook_or_404`·`_webhook_page`)와 라우트 5개, `teams/webhooks.html`이 함께 사라졌다. 대체 화면이 아니라 **대응 개념이 없다**: 봇 설치는 운영자가 포털에서 1회 하고(GUIDE-04 Step 7), 개인 연결은 각자 프로필에서 코드를 받아 DM으로 한다. 확인 발송은 `python -m discord_service test`다.

- `invite_create(team_id)` POST: `tsv.create_invite`. 성공 시 `messages.success`에 전체 URL(`settings.SITE_URL + invite.path`) 표시 후 `team_members`로.
- `invite_revoke(invite_id)` POST: `tsv.revoke_invite`.
- `member_role(membership_id)` POST `role`: `tsv.change_role`.
- `member_remove(membership_id)` POST: `tsv.remove_member`.
- 모든 `ServiceError`는 `messages.error(" ".join(e.errors.values()))`.

## 6.11 `views/search.py`, `views/settings.py`, `views/ops.py`

### `views/search.py`

- `search(request)`: 쿼리 `q`, `include_closed`, `include_archived`. `ts.search(...)` 결과를 `rows_for(request.user, results)`로 감싸 `search.html`에. context: `q`, `count`, `rows`, `include_closed`, `include_archived`.

### `views/settings.py`

- `profile`: `ProfileForm` → `user.display_name`만 저장(`save(update_fields=["display_name"])`). Discord는 이 폼이 만지지 않는다. GET 컨텍스트에 `link_code`를 담는다: `request.session.pop("discord_link_code", None)` — 토큰 화면의 `new_token`과 같은 방식으로 **발급 직후 한 번만** 보여 준다.
- `discord_link` POST(`@require_POST`): `request.session["discord_link_code"] = issue_link_code(request.user)` 후 `profile`로 redirect. 코드를 세션에 담는 이유는 redirect 뒤 한 번만 렌더하기 위해서다(주소창·이력에 남지 않는다).
- `discord_unlink` POST(`@require_POST`): `unlink_discord(request.user)` + `messages.success("Discord 연결을 끊었습니다. 마감 알림 DM도 멈춥니다.")`. 이것이 Discord에 못 들어가는 상황의 복구 경로이고, 봇의 `연결해제`와 같은 일을 한다.
- `tokens`: GET은 내 토큰 목록(폐기 포함, 폐기는 흐리게). POST `TokenForm` → `ApiToken.issue`. 발급 직후 원문을 세션에 넣고 redirect 후 한 번만 보여 준다: `request.session["new_token"] = raw` → GET에서 `pop`. 화면에 MCP 연결 안내 문구(GUIDE-03 Step 5 표의 네 가지 예시)를 표시한다.
- `token_revoke(token_id)` POST: 본인 토큰만. `token.revoke()`.

### `views/ops.py` (전체 코드)

```python
from django.contrib.admin.views.decorators import staff_member_required
from django.core import serializers
from django.db import connection
from django.http import HttpResponse, JsonResponse
from django.shortcuts import render

from accounts.models import User
from api.models import IntegrationStatus
from projects.models import Project
from tasks.models import ChangeLog, ChecklistItem, Link, Task, TodayItem
from teams.models import Invite, Membership, Team


def healthz(request):
    with connection.cursor() as c:
        c.execute("SELECT 1")
    return JsonResponse({"ok": True})


@staff_member_required
def ops(request):
    return render(request, "ops.html", {"statuses": IntegrationStatus.objects.order_by("name")})


@staff_member_required
def export_json(request):
    parts = [
        serializers.serialize(
            "json",
            User.objects.all(),
            # discord_link_code는 살아 있는 동안 자격증명이므로 넣지 않는다.
            fields=(
                "username",
                "display_name",
                "discord_user_id",
                "discord_linked_at",
                "is_active",
                "auto_pull_days",
            ),
        ),
        serializers.serialize("json", Team.objects.all()),
        serializers.serialize("json", Membership.objects.all()),
        serializers.serialize(
            "json",
            Invite.objects.all(),
            fields=("team", "expires_at", "revoked_at", "use_count"),
        ),
        serializers.serialize("json", Project.objects.all()),
        serializers.serialize("json", Task.objects.all()),
        serializers.serialize("json", ChecklistItem.objects.all()),
        serializers.serialize("json", TodayItem.objects.all()),
        serializers.serialize("json", Link.objects.all()),
        serializers.serialize("json", ChangeLog.objects.all()),
    ]
    body = "[" + ",".join(p[1:-1] for p in parts if len(p) > 2) + "]"
    resp = HttpResponse(body, content_type="application/json")
    resp["Content-Disposition"] = 'attachment; filename="export.json"'
    return resp
```

`staff_member_required`는 `is_staff`를 본다. superuser를 만들 때 `is_staff=True`이므로 그대로 쓴다.

User 필드 허용 목록이 곧 백업의 경계다. `discord_linked_at`은 넣고(연결 여부는 비밀이 아니다) **`discord_link_code`와 `discord_link_expires_at`은 넣지 않는다** — 유효한 10분 동안 그 코드는 그 계정에 Discord를 붙일 수 있는 자격증명이다. `DiscordWebhook` 블록은 모델과 함께 사라졌다.

---

## 6.12 템플릿 (1) 셸·행·패널

문구·크기는 README를 따른다. 아래 코드는 그대로 쓴다.

### `base.html` (전체)

```html
{% load static %}<!doctype html>
<html lang="ko">
<head>
  <meta charset="utf-8">
  <meta name="viewport" content="width=device-width, initial-scale=1">
  <title>{% block title %}유달리{% endblock %}</title>
  <link rel="stylesheet" href="https://cdn.jsdelivr.net/gh/orioncactus/pretendard@v1.3.9/dist/web/static/pretendard.min.css">
  <link rel="stylesheet" href="{% static 'app.css' %}">
  <script src="{% static 'vendor/htmx.min.js' %}"></script>
</head>
<body hx-headers='{"X-CSRFToken": "{{ csrf_token }}"}' data-page-url="{% block page_url %}{{ page_url }}{% endblock %}">
<header class="header">
  <a class="logo" href="{% url 'today' %}">유달리</a>
  {% if user.is_authenticated %}
  <nav class="nav" aria-label="주 메뉴">
    <a href="{% url 'today' %}"{% if nav == "today" %} aria-current="page"{% endif %}>오늘</a>
    <a href="{% url 'me' %}"{% if nav == "me" %} aria-current="page"{% endif %}>내 태스크</a>
    <a href="{% url 'team' %}"{% if nav == "team" %} aria-current="page"{% endif %}>팀 현황</a>
    <a href="{% url 'search' %}"{% if nav == "search" %} aria-current="page"{% endif %}>검색</a>
  </nav>
  <span class="spacer"></span>
  {% if nav == "today" %}
  <button type="button" class="btn sm tint" data-action="toggle" data-target="#quick" data-alt="닫기">빠른 추가</button>
  {% else %}
  <a class="btn sm tint" href="{% url 'today' %}?quick=1">빠른 추가</a>
  {% endif %}
  <details class="menu">
    <summary class="avatar" aria-label="내 메뉴">{{ user.display_name|slice:":1" }}</summary>
    <div class="menu-list">
      <span class="muted t13" style="padding:4px 10px">{{ user.display_name }}</span>
      <a href="{% url 'profile' %}">프로필</a>
      <a href="{% url 'tokens' %}">API 토큰</a>
      {% if team_count > 1 %}<a href="{% url 'team_list' %}">팀 전환</a>{% endif %}
      {% if user.is_staff %}<a href="{% url 'ops' %}">운영 상태</a>{% endif %}
      <form method="post" action="{% url 'logout' %}">{% csrf_token %}<button type="submit">로그아웃</button></form>
    </div>
  </details>
  {% endif %}
</header>
{% if user.is_authenticated %}
<div class="frame">
  <nav class="rail" aria-label="프로젝트">
    {% for p in nav_projects %}
    <a href="{% url 'project_detail' p.pk %}"{% if p.pk == current_project_id %} aria-current="page"{% endif %}><span class="initial">{{ p.name|slice:":1" }}</span><span>{{ p.name }}</span></a>
    {% empty %}<span class="muted t13" style="padding:0 10px">프로젝트 없음</span>{% endfor %}
  </nav>
  <div class="layout{% block layout_class %}{% endblock %}">
    <main>
      {% for m in messages %}<p class="{% if m.tags == 'error' %}error{% else %}muted{% endif %}">{{ m }}</p>{% endfor %}
      {% block main %}{% endblock %}
    </main>
    <aside id="panel">{% block panel %}{% endblock %}</aside>
  </div>
</div>
{% else %}
<main class="layout"><div class="card" style="max-width:420px;width:100%;margin:48px auto">{% block auth %}{% endblock %}</div></main>
{% endif %}
<dialog id="dialog"></dialog>
<script src="{% static 'app.js' %}"></script>
</body>
</html>
```

### `tasks/_row.html` (전체) — TaskRow2. 모든 목록이 `{% task_row r %}`로 이 템플릿을 그린다

```html
<li id="task-{{ task.pk }}"
    class="task-row{% if task.is_closed %} closed{% endif %}{% if selected %} selected{% endif %}"
    role="button" tabindex="0" aria-label="{{ task.title }} 상세 보기"
    data-id="{{ task.pk }}" data-panel="{% url 'task_panel' task.pk %}"
    {% if not in_today_page %}hx-get="{% url 'task_row' task.pk %}?{{ row_query }}" hx-trigger="task-changed[event.detail.id=={{ task.pk }}] from:body" hx-swap="outerHTML"{% endif %}>
  <div class="main{% if show_next %} has-next{% endif %}">
    {% if show_next %}<div class="next">{{ task.next_action }}</div>{% endif %}
    <div class="proj">{{ task.project.name }}</div>
    <div class="title">{{ task.title }}</div>
    <div class="meta">
      {% if not hide_assignee %}<span>{{ task.assignee.display_name }}</span>{% endif %}
      <span class="badge{% if task.priority >= 8 %} high{% endif %}">중요도 {{ task.priority }}/10</span>
      {% if task.is_stopped %}<span{% if task.is_blocked %} class="danger"{% endif %}>{{ task.stop_reason|default:"사유 없음" }}</span>{% endif %}
      {% if checklist_total %}<span>체크리스트 {{ checklist_done }}/{{ checklist_total }}</span>{% endif %}
    </div>
    {% if error %}<div class="error">{{ error }}</div>{% endif %}
  </div>
  <div class="actions">
    <span class="due{% if task.is_overdue %} overdue{% endif %}">{{ due_label }}</span>
    <form>
      <input type="hidden" name="version" value="{{ task.version }}">
      <input type="hidden" name="opts" value="{{ row_opts }}">
      <select name="status" class="pill {{ task.status }}" aria-label="상태"
              data-status="{{ task.status }}" data-id="{{ task.pk }}" data-panel="{% url 'task_panel' task.pk %}"
              hx-post="{% url 'task_status' task.pk %}" hx-target="#task-{{ task.pk }}" hx-swap="outerHTML"
              hx-trigger="change[!(this.value=='blocked' && this.dataset.status!='blocked')]"
              {% if read_only %}disabled{% endif %}>
        {% for code, label in task.STATUSES %}<option value="{{ code }}"{% if code == task.status %} selected{% endif %}>{{ label }}</option>{% endfor %}
      </select>
    </form>
    {% if not hide_today %}
      {% if auto_pulled %}
      <button type="button" class="btn sm today-btn auto" hx-post="{% url 'today_exclude' task.pk %}?{{ row_query }}" hx-target="{{ row_target }}" hx-swap="outerHTML" title="마감 기준 자동 추가. 누르면 오늘 목록에서만 제외합니다.">자동 추가 · 오늘 제외</button>
      {% elif in_today %}
      <button type="button" class="btn sm today-btn in" hx-post="{% url 'today_exclude' task.pk %}?{{ row_query }}" hx-target="{{ row_target }}" hx-swap="outerHTML" title="오늘 할 일 목록에서 빼기">오늘 제외</button>
      {% else %}
      <button type="button" class="btn sm today-btn" hx-post="{% url 'today_add' task.pk %}?{{ row_query }}" hx-target="{{ row_target }}" hx-swap="outerHTML" title="오늘 할 일 목록에 담기">오늘 추가</button>
      {% endif %}
    {% endif %}
    <button type="button" class="btn sm icon" data-copy="{{ task.pk }}" aria-label="바로가기 링크 복사" title="바로가기 링크 복사"><svg width="14" height="14" viewBox="0 0 16 16" fill="none" stroke="currentColor" stroke-width="1.6" stroke-linecap="round" aria-hidden="true"><path d="M6.5 9.5l3-3M7 4.5l1.2-1.2a2.8 2.8 0 014 4L11 8.5M9 11.5l-1.2 1.2a2.8 2.8 0 01-4-4L5 7.5"></path></svg></button>
    {% if show_move %}
    <button type="button" class="btn sm icon" hx-post="{% url 'today_move' task.pk 'up' %}" hx-target="#today-list" hx-swap="outerHTML" aria-label="위로">↑</button>
    <button type="button" class="btn sm icon" hx-post="{% url 'today_move' task.pk 'down' %}" hx-target="#today-list" hx-swap="outerHTML" aria-label="아래로">↓</button>
    {% endif %}
  </div>
</li>
```

상태 select의 `hx-post`는 form 안에 있으므로 HTMX가 hidden `version`·`opts`를 같이 보낸다. `hx-trigger` 필터는 '막힘'을 새로 고를 때만 요청을 막고, 그 경우 `app.js`가 패널의 사유 박스를 연다.

### `tasks/_panel.html` (전체) — README §7 순서

```html
<div class="panel" hx-get="{% url 'task_panel' task.pk %}" hx-trigger="task-updated[event.detail.id=={{ task.pk }}] from:body" hx-target="#panel" hx-swap="innerHTML">
  <div class="panel-bar">
    <span id="save-status" class="status" aria-live="polite"></span>
    <button type="button" class="btn sm icon" data-copy="{{ task.pk }}" aria-label="링크 복사" title="링크 복사"><svg width="14" height="14" viewBox="0 0 16 16" fill="none" stroke="currentColor" stroke-width="1.6" stroke-linecap="round" aria-hidden="true"><path d="M6.5 9.5l3-3M7 4.5l1.2-1.2a2.8 2.8 0 014 4L11 8.5M9 11.5l-1.2 1.2a2.8 2.8 0 01-4-4L5 7.5"></path></svg></button>
    {% if not full_page %}
    <button type="button" class="btn sm" data-action="toggle-wide">크게 보기</button>
    <button type="button" class="btn sm" data-action="close-panel">닫기</button>
    {% endif %}
  </div>
  {% if error %}<p class="error">{{ error }}</p>{% endif %}
  <div class="panel-body">
    <div class="stack">
      <div class="section">
        <div class="number">{{ task.number }}</div>
        <input class="title-input" name="value" value="{{ task.title }}" aria-label="제목" data-autosave
               hx-post="{% url 'task_text' task.pk 'title' %}" hx-trigger="change" hx-swap="none">
        <div class="meta">
          <a href="{% url 'project_detail' task.project_id %}">{{ task.project.name }}</a>
          <span>{{ task.assignee.display_name }}</span>
          <form>
            <input type="hidden" name="version" value="{{ task.version }}">
            <input type="hidden" name="from" value="panel">
            <select name="status" class="pill sm {{ task.status }}" aria-label="상태"
                    data-status="{{ task.status }}" data-id="{{ task.pk }}" data-panel="{% url 'task_panel' task.pk %}"
                    hx-post="{% url 'task_status' task.pk %}" hx-target="#panel" hx-swap="innerHTML"
                    hx-trigger="change[!(this.value=='blocked' && this.dataset.status!='blocked')]">
              {% for code, label in task.STATUSES %}<option value="{{ code }}"{% if code == task.status %} selected{% endif %}>{{ label }}</option>{% endfor %}
            </select>
          </form>
          <span class="badge{% if task.is_overdue %} danger{% endif %}">{{ due_label }}</span>
          <form class="row" style="gap:4px">
            <input type="hidden" name="version" value="{{ task.version }}">
            <select name="priority" class="select" aria-label="중요도"
                    hx-post="{% url 'task_priority' task.pk %}" hx-target="#panel" hx-swap="innerHTML" hx-trigger="change">
              {% for n in priorities %}<option value="{{ n }}"{% if n == task.priority %} selected{% endif %}>{{ n }}</option>{% endfor %}
            </select><span>/10</span>
          </form>
        </div>
        <p class="muted t13">{{ task.status_hint }}</p>
      </div>
      {% if task.is_stopped or block_pending %}{% include "tasks/_stop.html" %}{% endif %}
      <label class="field">설명
        <textarea class="textarea" name="value" rows="{{ desc_rows }}" data-autosave hx-post="{% url 'task_text' task.pk 'description' %}" hx-trigger="change" hx-swap="none">{{ task.description }}</textarea>
      </label>
      <div class="section due-block">
        <div class="label">목표일</div>
        <div class="value{% if task.is_overdue %} danger{% endif %}">{{ due_full }}</div>
        {% if task.is_open %}
        <button type="button" class="btn link" data-action="toggle" data-target="#extend-form"
                data-alt="{% if extend_open %}{% if task.due_date %}목표일 연장하기{% else %}목표일 정하기{% endif %}{% else %}취소{% endif %}">{% if extend_open %}취소{% elif task.due_date %}목표일 연장하기{% else %}목표일 정하기{% endif %}</button>
        <div id="extend-form"{% if not extend_open %} hidden{% endif %}>{% include "tasks/_extend.html" %}</div>
        {% endif %}
      </div>
    </div>
    <div class="stack">
      <label class="field">완료 조건
        <textarea class="textarea" name="value" rows="2" data-autosave hx-post="{% url 'task_text' task.pk 'done_when' %}" hx-trigger="change" hx-swap="none">{{ task.done_when }}</textarea>
      </label>
      <label class="field">다음 행동
        <input class="input" name="value" value="{{ task.next_action }}" placeholder="멈출 때 한 줄로 고쳐 씁니다" data-autosave hx-post="{% url 'task_text' task.pk 'next_action' %}" hx-trigger="change" hx-swap="none">
      </label>
      <div id="checklist">{% include "tasks/_checklist.html" %}</div>
      <label class="field">진행 메모
        <textarea class="textarea notes" name="value" data-autosave{% if focus_notes %} data-focus{% endif %} placeholder="지금까지 한 일, 막힌 점, 다음에 할 일"
                  hx-post="{% url 'task_text' task.pk 'notes' %}" hx-trigger="change, keyup changed delay:600ms" hx-swap="none">{{ task.notes }}</textarea>
        <span class="muted t13">내용을 수정하면 자동 저장됩니다.</span>
      </label>
      <div id="links">{% include "tasks/_links.html" %}</div>
      <details><summary>변경 이력 {{ history|length }}</summary>{% include "tasks/_history.html" %}</details>
      <details><summary>더보기</summary>
        <p class="muted t13">일시정지: 개인 사유 또는 다른 작업 · 막힘: 외부 요인으로 진행 불가</p>
        <p class="t13">담당자·프로젝트·기한 미정 사유를 바꾸려면 <a href="{% url 'task_edit' task.pk %}">수정 화면</a>에서 합니다.</p>
      </details>
    </div>
  </div>
</div>
```

### `tasks/_stop.html`

```html
<form class="stop-box" hx-post="{% url 'task_stop_reason' task.pk %}" hx-target="#panel" hx-swap="innerHTML">
  <input type="hidden" name="version" value="{{ task.version }}">
  {% if block_pending %}<input type="hidden" name="confirm_block" value="1">{% endif %}
  <div class="label">{% if block_pending %}막힘 사유{% elif task.is_blocked %}막힌 이유{% else %}멈춘 이유{% endif %}</div>
  <textarea class="textarea" name="reason" rows="2"{% if block_pending %} data-focus{% endif %}
            placeholder="{% if block_pending or task.is_blocked %}무엇 때문에 막혔나요? (필수){% else %}왜 잠시 멈췄나요? (선택){% endif %}">{{ stop_draft }}</textarea>
  {% if stop_error %}<div class="error">{{ stop_error }}</div>{% endif %}
  <div class="row">
    <button class="btn sm primary">{% if block_pending %}막힘으로 변경{% else %}사유 저장{% endif %}</button>
    {% if block_pending %}<button type="button" class="btn sm" hx-get="{% url 'task_panel' task.pk %}" hx-target="#panel" hx-swap="innerHTML">취소</button>{% endif %}
  </div>
</form>
```

### `tasks/_extend.html`

```html
<form class="stop-box" hx-post="{% url 'task_extend' task.pk %}" hx-target="#panel" hx-swap="innerHTML">
  <input type="hidden" name="version" value="{{ task.version }}">
  <label class="field">새 목표일<input class="input" type="date" name="due_date" min="{{ extend_min|date:'Y-m-d' }}" required></label>
  <label class="field">연장 사유<input class="input" name="reason" placeholder="왜 미루나요? (필수)"></label>
  {% if extend_error %}<div class="error">{{ extend_error }}</div>{% endif %}
  <button class="btn sm primary">저장</button>
</form>
```

### `tasks/_checklist.html`

```html
<div class="section">
  <div class="row" style="justify-content:space-between">
    <span class="label">체크리스트</span>
    {% if checklist %}<span class="muted t13">{{ checklist_done }}/{{ checklist|length }} 완료</span>{% endif %}
  </div>
  <ul class="checklist">
    {% for item in checklist %}
    <li{% if item.is_done %} class="done"{% endif %}>
      <input type="checkbox"{% if item.is_done %} checked{% endif %} aria-label="{{ item.text }}" hx-post="{% url 'checklist_action' item.pk 'toggle' %}" hx-target="#checklist" hx-swap="innerHTML">
      <span class="text">{{ item.text }}</span>
      <button type="button" class="btn sm icon" hx-post="{% url 'checklist_action' item.pk 'up' %}" hx-target="#checklist" hx-swap="innerHTML" aria-label="위로">↑</button>
      <button type="button" class="btn sm icon" hx-post="{% url 'checklist_action' item.pk 'down' %}" hx-target="#checklist" hx-swap="innerHTML" aria-label="아래로">↓</button>
      <button type="button" class="btn sm icon" hx-post="{% url 'checklist_action' item.pk 'delete' %}" hx-target="#checklist" hx-swap="innerHTML" hx-confirm="삭제할까요?" aria-label="삭제">✕</button>
    </li>
    {% endfor %}
  </ul>
  <form class="row" hx-post="{% url 'checklist_add' task.pk %}" hx-target="#checklist" hx-swap="innerHTML">
    <input class="input" name="text" placeholder="항목 추가" style="flex:1" required>
    <button class="btn sm">추가</button>
  </form>
  {% if error %}<div class="error">{{ error }}</div>{% endif %}
</div>
```

### `tasks/_links.html`

```html
<div class="section">
  <span class="label">문서·PR 링크</span>
  <ul class="links">
    {% for l in links %}
    <li class="row"><span class="badge">{{ l.get_kind_display }}</span><a href="{{ l.url }}" target="_blank" rel="noopener">{{ l.title }}</a>
      <button type="button" class="btn link danger" hx-post="{% url 'link_delete' l.pk %}" hx-target="#links" hx-swap="innerHTML" hx-confirm="링크를 지울까요?">삭제</button></li>
    {% empty %}<li class="muted t13">링크 없음</li>{% endfor %}
  </ul>
  <button type="button" class="btn link" data-action="toggle" data-target="#link-form" data-alt="취소">링크 추가</button>
  <form id="link-form" class="stack"{% if not link_open %} hidden{% endif %} hx-post="{% url 'task_link_add' task.pk %}" hx-target="#links" hx-swap="innerHTML">
    <select name="kind" class="select auto" aria-label="종류">{% for code, label in link_form.fields.kind.choices %}<option value="{{ code }}">{{ label }}</option>{% endfor %}</select>
    <input class="input" name="title" placeholder="제목" required>
    <input class="input" name="url" type="url" placeholder="https://" required>
    <button class="btn sm primary">추가</button>
  </form>
  {% if error %}<div class="error">{{ error }}</div>{% endif %}
</div>
```

### `tasks/_history.html`

```html
<ul class="history">
  {% for h in history %}
  <li><div>{{ h.field }}: {{ h.from }} → {{ h.to }}</div><div class="who">{{ h.time }} · {{ h.actor }} · {{ h.source }}</div></li>
  {% empty %}<li class="muted">변경 이력 없음</li>{% endfor %}
</ul>
```

### `tasks/detail.html` (전체 페이지: 링크 공유·모바일용)

```html
{% extends "base.html" %}{% block title %}{{ task.number }} {{ task.title }}{% endblock %}
{% block page_url %}{% url 'today' %}{% endblock %}
{% block layout_class %} has-panel wide{% endblock %}
{% block panel %}{% include "tasks/_panel.html" %}{% endblock %}
```

---

## 6.13 템플릿 (2) 화면

### `today.html` (전체)

```html
{% extends "base.html" %}{% load rows %}{% block title %}오늘{% endblock %}
{% block main %}
{% include "today/_head.html" %}
<div id="quick"{% if not quick_open %} hidden{% endif %}>{% include "today/_quick.html" %}</div>
<div class="today-columns">
  {% include "today/_list.html" %}
  {% if schedule_open %}{% include "today/_schedule.html" %}{% endif %}
</div>
{% endblock %}
```

### `today/_head.html` — 날짜·지표 3개·지금 할 일 카드

```html
<div id="today-head" class="card" hx-get="{% url 'today' %}?part=head" hx-trigger="task-changed from:body, task-updated from:body, today-changed from:body" hx-swap="outerHTML">
  <div class="card-head">
    <div><h1 class="t22">{{ date_label }}</h1><div class="muted t13">{{ today_hint }}</div></div>
    <div class="stats">
      <a class="stat" href="{% url 'me' %}?status=done_today"><b>{{ counts.done_today }}</b><span>오늘 완료</span></a>
      <a class="stat" href="{% url 'me' %}?status=done_7d"><b>{{ counts.done_7d }}</b><span>지난 7일 완료</span></a>
      <a class="stat" href="{% url 'me' %}"><b>{{ counts.my_open }}</b><span>남은 내 태스크</span></a>
    </div>
  </div>
  {% if error %}<p class="error">{{ error }}</p>{% endif %}
  {% if focus %}
  <section class="focus stack" aria-label="지금 할 일">
    <div class="muted t13">지금 할 일 · 중요도 {{ focus.priority }}/10 · 오늘 목록 기준</div>
    <h2>{{ focus.next_action|default:focus.title }}</h2>
    <div class="muted t13">{{ focus.number }} · {{ focus.project.name }} · {{ focus_due }}{% if focus.next_action %} · {{ focus.title }}{% endif %}</div>
    <div class="row">
      <form hx-post="{% url 'task_status' focus.pk %}" hx-target="#today-head" hx-swap="outerHTML">
        <input type="hidden" name="version" value="{{ focus.version }}">
        <input type="hidden" name="from" value="head">
        <input type="hidden" name="status" value="{% if focus.status == 'doing' %}done{% else %}doing{% endif %}">
        <button class="btn primary">{% if focus.status == 'doing' %}완료로 표시{% else %}진행 중으로 시작{% endif %}</button>
      </form>
      <button type="button" class="btn" hx-get="{% url 'task_panel' focus.pk %}?focus=notes" hx-target="#panel" hx-swap="innerHTML" hx-push-url="{% url 'task_detail' focus.pk %}">진행 메모 열기</button>
      <button type="button" class="btn" hx-get="{% url 'task_panel' focus.pk %}" hx-target="#panel" hx-swap="innerHTML" hx-push-url="{% url 'task_detail' focus.pk %}">자세히 보기</button>
    </div>
  </section>
  {% else %}
  <p class="muted">오늘 할 일이 없습니다. 아래 목록에서 담거나 빠른 추가로 만드세요.</p>
  {% endif %}
</div>
```

(`_head.html`과 `_list.html`은 자기 id와 `hx-get`을 스스로 가진다. `today.html`은 감싸지 않고 include만 한다.)

### `today/_quick.html` — 빠른 추가 폼

```html
<form id="quick-form" class="card" hx-post="{% url 'today_quick' %}" hx-target="#quick" hx-swap="innerHTML">
  <h2>빠른 추가</h2>
  {{ form.idem }}
  <input class="input lg" name="title" value="{{ form.title.value|default:'' }}" placeholder="무엇을 할까요?" required autofocus>
  <div class="row">
    <label class="field">프로젝트<select class="select auto" name="project">{% for p in form.fields.project.queryset %}<option value="{{ p.pk }}"{% if form.project.value|stringformat:"s" == p.pk|stringformat:"s" %} selected{% endif %}>{{ p.name }}</option>{% endfor %}</select></label>
    <label class="field">중요도 (1~10)<select class="select auto" name="priority">{% for v, label in form.fields.priority.choices %}<option value="{{ v }}"{% if form.priority.value|stringformat:"s" == v|stringformat:"s" %} selected{% endif %}>{{ label }}</option>{% endfor %}</select></label>
    <label class="field">목표 기한<input class="input" type="date" name="due_date" value="{{ form.due_date.value|default:'' }}"></label>
  </div>
  <label class="field">기한 미정 사유 (기한이 없을 때만)<input class="input" name="no_due_reason" value="{{ form.no_due_reason.value|default:'' }}"></label>
  {% for e in form.non_field_errors %}<div class="error">{{ e }}</div>{% endfor %}
  {% for f in form %}{% for e in f.errors %}<div class="error">{{ f.label }}: {{ e }}</div>{% endfor %}{% endfor %}
  <div class="row"><button class="btn primary">추가</button><span class="muted t13">담당자 본인 · 시작 전 · 오늘 목록에 담깁니다</span></div>
</form>
```

### `today/_list.html` — 오늘 태스크 카드

```html
{% load rows %}
<section id="today-list" class="card" aria-label="오늘 태스크" hx-get="{% url 'today' %}?part=list" hx-trigger="task-changed from:body, task-updated from:body, today-changed from:body" hx-swap="outerHTML">
  <div class="card-head">
    <h2>오늘 태스크 <span class="muted">{{ counts.today }}</span></h2>
    <div class="row">
      <span class="muted t13">중요도순</span>
      <label class="muted t13">마감 기준 자동 담기
        <select name="auto_pull_days" class="select auto" style="height:36px" hx-post="{% url 'today_settings' %}" hx-target="#today-list" hx-swap="outerHTML" hx-trigger="change">
          {% for v, label in auto_pull_choices %}<option value="{{ v }}"{% if v == auto_pull_days %} selected{% endif %}>{{ label }}</option>{% endfor %}
        </select>
      </label>
      <a class="btn sm" href="{% url 'today' %}?schedule={% if schedule_open %}0{% else %}1{% endif %}" aria-pressed="{% if schedule_open %}true{% else %}false{% endif %}">일정 보기</a>
    </div>
  </div>
  {% if counts.auto_pulled %}<p class="muted t13">마감 {{ auto_pull_days }}일 이내 자동 추가 {{ counts.auto_pulled }}건.</p>{% endif %}
  {% if counts.excluded %}<p class="muted t13">오늘 제외 {{ counts.excluded }}건 · <button type="button" class="btn link" hx-post="{% url 'today_restore' %}" hx-target="#today-list" hx-swap="outerHTML">제외한 태스크 복원</button></p>{% endif %}
  <ul class="tasks">
    {% for r in rows %}{% task_row r %}{% empty %}<li class="muted">오늘 할 일을 골라 보세요. 내 태스크에서 "오늘 추가"를 누르면 여기에 옵니다.</li>{% endfor %}
  </ul>
  <details><summary>오늘 완료 ({{ done_rows|length }})</summary><ul class="tasks" style="margin-top:8px">{% for r in done_rows %}{% task_row r %}{% endfor %}</ul></details>
  <p class="t13">오늘 마감 <a href="{% url 'me' %}?due=today">{{ counts.due_today }}</a> · 기한 초과 <a href="{% url 'me' %}?due=overdue">{{ counts.overdue }}</a> · 검토 대기 <a href="{% url 'me' %}?status=review">{{ counts.review }}</a> · 막힘 <a href="{% url 'me' %}?status=blocked">{{ counts.blocked }}</a></p>
</section>
```

### `today/_schedule.html` — 일정 카드 (기본 닫힘, `?schedule=1`)

```html
<section class="card schedule" aria-label="일정">
  <div class="card-head">
    <h2>일정</h2>
    <div class="row" role="group" aria-label="일정 보기">
      <a class="btn sm" href="{% url 'today' %}?schedule=1&cal=time" aria-pressed="{% if cal_mode == 'time' %}true{% else %}false{% endif %}">시간표</a>
      <a class="btn sm" href="{% url 'today' %}?schedule=1&cal=month" aria-pressed="{% if cal_mode == 'month' %}true{% else %}false{% endif %}">캘린더</a>
    </div>
  </div>
  <div class="t15" style="font-weight:600">{{ cal_title }}</div>
  {% if cal_mode == 'month' %}
  <div class="cal">
    {% for w in "월화수목금토일" %}<span class="muted t12">{{ w }}</span>{% endfor %}
    {% for c in cal_cells %}{% if c %}<a href="{{ c.url }}" class="{% if c.today %}today{% endif %}{% if c.sel %} sel{% endif %}" aria-label="{{ c.aria }}">{{ c.day }}{% if c.n %}<small>●{{ c.n }}</small>{% endif %}</a>{% else %}<span></span>{% endif %}{% endfor %}
  </div>
  <div class="muted t13">{{ cal_sel_label }}</div>
  <ul class="stack">{% for t in cal_sel_tasks %}<li><button type="button" class="btn link" hx-get="{% url 'task_panel' t.pk %}" hx-target="#panel" hx-swap="innerHTML" hx-push-url="{% url 'task_detail' t.pk %}">{{ t.title }}</button></li>{% empty %}<li class="muted t13">마감 없음</li>{% endfor %}</ul>
  {% else %}
  <div class="stack">
    <span class="muted t13">종일</span>
    {% for t in due_today_tasks %}<button type="button" class="btn link" style="text-align:left" hx-get="{% url 'task_panel' t.pk %}" hx-target="#panel" hx-swap="innerHTML" hx-push-url="{% url 'task_detail' t.pk %}">{{ t.title }}</button>{% empty %}<span class="muted t13">오늘 마감 없음</span>{% endfor %}
  </div>
  <div class="hours">{% for h in hours %}<div>{{ h }}</div>{% endfor %}</div>
  {% endif %}
</section>
```

### `me.html` (전체)

```html
{% extends "base.html" %}{% load rows %}{% block title %}{{ view.title }}{% endblock %}
{% block main %}
<div class="card">
  <div class="card-head">
    <div><h1 class="t24">{{ view.title }}</h1><div class="muted t13">{{ view.hint }}</div></div>
    <select name="member" form="me-filter" class="select auto" aria-label="팀원" onchange="this.form.requestSubmit()">
      <option value="0"{% if member_id == 0 %} selected{% endif %}>팀 전체</option>
      {% for m in members %}<option value="{{ m.pk }}"{% if m.pk == member_id %} selected{% endif %}>{% if m.pk == user.pk %}나{% else %}{{ m.display_name }}{% endif %}</option>{% endfor %}
    </select>
  </div>
  <form id="me-filter" method="get" class="row">
    <input type="hidden" name="group" value="{{ group }}">
    <span class="row" role="group" aria-label="묶음" style="gap:4px">
      {% for code, label in group_options %}<button class="btn" name="group" value="{{ code }}" aria-pressed="{% if code == group %}true{% else %}false{% endif %}">{{ label }}</button>{% endfor %}
    </span>
    <select name="due" class="select auto" aria-label="기한" onchange="this.form.requestSubmit()">{% for code, label in due_options %}<option value="{{ code }}"{% if code == f.due %} selected{% endif %}>{{ label }}</option>{% endfor %}</select>
    <select name="project" class="select auto" aria-label="프로젝트" onchange="this.form.requestSubmit()"><option value="">모든 프로젝트</option>{% for p in projects %}<option value="{{ p.pk }}"{% if p.pk|stringformat:"s" == f.project %} selected{% endif %}>{{ p.name }}</option>{% endfor %}</select>
    <select name="status" class="select auto" aria-label="상태" onchange="this.form.requestSubmit()">{% for code, label in status_options %}<option value="{{ code }}"{% if code == f.status %} selected{% endif %}>{{ label }}</option>{% endfor %}</select>
    <select name="priority" class="select auto" aria-label="중요도" onchange="this.form.requestSubmit()">{% for code, label in priority_options %}<option value="{{ code }}"{% if code == f.priority %} selected{% endif %}>{{ label }}</option>{% endfor %}</select>
    {% if has_filter %}<a class="btn" href="{% url 'me' %}?member={{ member_id }}&group={{ group }}">필터 지우기</a>{% endif %}
  </form>
</div>
{% for g in groups %}
<section class="card group">
  <h2>{{ g.title }} <span class="muted">{{ g.count }}</span></h2>
  {% if g.count == 0 %}<p class="muted">{{ g.empty_text }}</p>
  {% elif g.flat %}<ul class="tasks">{% for r in g.rows %}{% task_row r %}{% endfor %}</ul>
  {% else %}
    {% for p in g.projects %}
    <div class="subgroup">
      <div class="head">
        <a class="btn link" href="{% url 'project_detail' p.project.pk %}">{{ p.project.name }}</a>
        <span class="muted t13">{{ p.count_label }}</span>
        <div class="bar" role="img" aria-label="{{ p.pct }}% 완료"><i style="width:{{ p.pct }}%"></i></div>
      </div>
      <ul class="tasks">{% for r in p.rows %}{% task_row r %}{% endfor %}</ul>
    </div>
    {% endfor %}
  {% endif %}
</section>
{% endfor %}
{% endblock %}
```

`member` select는 `form="me-filter"` 속성으로 아래 GET 폼에 묶인다. 묶음 버튼은 hidden `group`을 덮어쓴다(같은 이름의 마지막 값이 이긴다).

### `teams/detail.html` — 팀 현황 (전체)

```html
{% extends "base.html" %}{% block title %}팀 현황{% endblock %}
{% block main %}
<div class="card">
  <div class="card-head"><h1 class="t24">{{ team.name }}</h1>{% if is_admin %}<a class="btn sm" href="{% url 'team_members' team.pk %}">팀원 관리</a>{% endif %}</div>
  <div class="tiles">
    {% for label, value, url in tiles %}<a class="tile" href="{{ url }}"><b>{{ value }}</b><span>{{ label }}</span></a>{% endfor %}
  </div>
</div>
<section class="card">
  <div class="card-head">
    <h2>프로젝트</h2>
    <form method="get" class="row">
      <label class="check muted t13"><input type="checkbox" name="include_archived" value="1"{% if include_archived %} checked{% endif %} onchange="this.form.requestSubmit()"> 보관 포함</label>
      <button type="button" class="btn primary" hx-get="{% url 'project_new' %}?team={{ team.pk }}" hx-target="#dialog" hx-swap="innerHTML">새 프로젝트</button>
    </form>
  </div>
  <table class="grid">
    <thead><tr><th>이름</th><th>관리자</th><th>상태</th><th class="num">미완료</th><th class="num">완료</th></tr></thead>
    <tbody>
    {% for p, st in project_rows %}
    <tr>
      <td><a href="{% url 'project_detail' p.pk %}">{{ p.name }}</a>{% if p.is_archived %} <span class="badge">보관</span>{% endif %}<div class="muted t13">{{ p.purpose }}</div></td>
      <td>{% for u in p.owners.all %}{{ u.display_name }}{% if not forloop.last %}, {% endif %}{% empty %}<span class="warning">미지정</span>{% endfor %}</td>
      <td><span class="badge">{{ p.status_label }}</span><div class="muted t13" style="max-width:220px">{{ p.status_desc }}</div></td>
      <td class="num">{{ st.open }}</td>
      <td class="num">{{ st.done }}/{{ st.total }}</td>
    </tr>
    {% empty %}<tr><td colspan="5" class="muted">프로젝트가 없습니다.</td></tr>{% endfor %}
    </tbody>
  </table>
</section>
<section class="card">
  <h2>담당자별</h2>
  <table class="grid">
    <thead><tr><th>이름</th><th class="num">미완료</th><th class="num">기한 초과</th><th class="num">검토 대기</th><th class="num">막힘</th></tr></thead>
    <tbody>
    {% for a in by_assignee %}
    <tr><td><a href="{{ me_url }}?member={{ a.assignee_id }}">{{ a.assignee__display_name }}</a></td><td class="num">{{ a.open }}</td><td class="num">{{ a.overdue }}</td><td class="num">{{ a.review }}</td><td class="num">{{ a.blocked }}</td></tr>
    {% empty %}<tr><td colspan="5" class="muted">미완료 태스크가 없습니다.</td></tr>{% endfor %}
    </tbody>
  </table>
</section>
{% endblock %}
```

### `projects/detail.html` (전체)

```html
{% extends "base.html" %}{% load rows %}{% block title %}{{ project.name }}{% endblock %}
{% block main %}
<div class="card">
  <div class="card-head">
    <div class="stack">
      <a class="t13" href="{% url 'team_detail' project.team_id %}">{{ project.team.name }}</a>
      <h1 class="t24">{{ project.name }}</h1>
      {% if project.purpose %}<p class="muted">{{ project.purpose }}</p>{% endif %}
      <div class="row t13">
        <span>관리자 {% for u in owners %}{{ u.display_name }}{% if not forloop.last %}, {% endif %}{% empty %}<span class="warning">미지정</span>{% endfor %}</span>
        <span class="badge">{{ project.status_label }}</span>
        {% for l in links %}<a href="{{ l.url }}" target="_blank" rel="noopener">{{ l.get_kind_display }}: {{ l.title }}</a>{% endfor %}
        {% if project.is_archived %}<span class="badge">보관됨</span>{% endif %}
      </div>
      <p class="muted t13">{{ project.status_desc }}</p>
    </div>
    <div class="row">
      <button type="button" class="btn" hx-get="{% url 'project_edit' project.pk %}" hx-target="#dialog" hx-swap="innerHTML">프로젝트 수정</button>
      <button type="button" class="btn primary" data-action="toggle" data-target="#task-form" data-alt="닫기">{% if form_open %}닫기{% else %}태스크 만들기{% endif %}</button>
    </div>
  </div>
  {# _task_form.html의 form이 이미 id=task-form과 hidden을 가진다. 감싸면 id가 중복돼 토글이 겉만 열린다. #}
  {% include "projects/_task_form.html" %}
  <div class="tiles five">
    <div class="tile"><b>{{ stats.done }}/{{ stats.total }}</b><span>완료</span></div>
    <div class="tile"><b>{{ stats.open }}</b><span>미완료</span></div>
    <div class="tile"><b>{{ stats.overdue }}</b><span>기한 초과</span></div>
    <div class="tile"><b>{{ stats.review }}</b><span>검토 대기</span></div>
    <div class="tile"><b>{{ stats.blocked }}</b><span>막힘</span></div>
  </div>
</div>
<section class="card">
  <div class="card-head">
    <div class="row" role="group" aria-label="보기">
      <a class="btn sm" href="?view=list{% if include_closed %}&include_closed=1{% endif %}" aria-pressed="{% if view == 'list' %}true{% else %}false{% endif %}">목록</a>
      <a class="btn sm" href="?view=board{% if include_closed %}&include_closed=1{% endif %}" aria-pressed="{% if view == 'board' %}true{% else %}false{% endif %}">보드</a>
    </div>
    <div class="row">
      <form method="get" class="row"><input type="hidden" name="view" value="{{ view }}">
        <label class="check muted t13"><input type="checkbox" name="include_closed" value="1"{% if include_closed %} checked{% endif %} onchange="this.form.requestSubmit()"> 완료·취소 포함</label>
      </form>
      {% if is_admin %}
        {% if project.is_archived %}
        <form method="post" action="{% url 'project_restore' project.pk %}">{% csrf_token %}<button class="btn sm">복원</button></form>
        {% else %}
        <form method="post" action="{% url 'project_archive' project.pk %}" onsubmit="return confirm('보관할까요? 미완료 태스크가 있으면 거부됩니다.')">{% csrf_token %}<button class="btn sm">보관</button></form>
        {% endif %}
      {% endif %}
    </div>
  </div>
  {% if view == 'board' %}
  <div class="board">
    {% for code, label, col in columns %}<div class="col"><h3>{{ label }} <span class="muted">{{ col|length }}</span></h3><ul class="tasks">{% for r in col %}{% task_row r %}{% endfor %}</ul></div>{% endfor %}
  </div>
  {% else %}
  <ul class="tasks">{% for r in rows %}{% task_row r %}{% empty %}<li class="muted">태스크가 없습니다.</li>{% endfor %}</ul>
  {% endif %}
</section>
<section class="card">
  <h2>저장소·문서</h2>
  <ul class="links">{% for l in links %}<li class="row"><span class="badge">{{ l.get_kind_display }}</span><a href="{{ l.url }}" target="_blank" rel="noopener">{{ l.title }}</a><form method="post" action="{% url 'link_delete' l.pk %}">{% csrf_token %}<button class="btn link danger">삭제</button></form></li>{% empty %}<li class="muted t13">링크 없음</li>{% endfor %}</ul>
  <form method="post" action="{% url 'project_link_add' project.pk %}" class="row">{% csrf_token %}
    <select name="kind" class="select auto">{% for code, label in link_form.fields.kind.choices %}<option value="{{ code }}">{{ label }}</option>{% endfor %}</select>
    <input class="input" name="title" placeholder="제목" style="flex:1" required><input class="input" name="url" type="url" placeholder="https://" style="flex:2" required>
    <button class="btn sm">추가</button>
  </form>
</section>
{% endblock %}
```

### `projects/_task_form.html` — 인라인 태스크 만들기

```html
<form id="task-form" class="stack" style="background:var(--bg-secondary);border:1px solid var(--border);border-radius:12px;padding:16px" hx-post="{% url 'project_task_create' project.pk %}" hx-target="#task-form" hx-swap="outerHTML"{% if not form_open %} hidden{% endif %}>
  <h2 class="t17">{{ project.name }}에 태스크 만들기</h2>
  {{ form.idem }}
  <input class="input lg" name="title" value="{{ form.title.value|default:'' }}" placeholder="해야 할 일" required autofocus>
  <div class="row">
    <label class="field">담당자 (1명)<select class="select auto" name="assignee">{% for u in form.fields.assignee.queryset %}<option value="{{ u.pk }}"{% if form.assignee.value|stringformat:"s" == u.pk|stringformat:"s" %} selected{% endif %}>{% if u.pk == user.pk %}나 ({{ u.display_name }}){% else %}{{ u.display_name }}{% endif %}</option>{% endfor %}</select></label>
    <label class="field">중요도 (1~10)<select class="select auto" name="priority">{% for v, label in form.fields.priority.choices %}<option value="{{ v }}"{% if form.priority.value|stringformat:"s" == v|stringformat:"s" %} selected{% endif %}>{{ label }}</option>{% endfor %}</select></label>
    <label class="field">목표 기한<input class="input" type="date" name="due_date" value="{{ form.due_date.value|default:'' }}"></label>
  </div>
  <label class="field">기한 미정 사유 (기한이 없을 때만)<input class="input" name="no_due_reason" value="{{ form.no_due_reason.value|default:'' }}"></label>
  {% for e in form.non_field_errors %}<div class="error">{{ e }}</div>{% endfor %}
  {% for f in form %}{% for e in f.errors %}<div class="error">{{ f.label }}: {{ e }}</div>{% endfor %}{% endfor %}
  <div class="row">
    <button class="btn primary">태스크 만들기</button>
    <button type="button" class="btn" data-action="toggle" data-target="#task-form">취소</button>
    <span class="muted t13">상태는 시작 전으로 저장돼요. 담당자는 한 명만 정할 수 있어요.</span>
  </div>
</form>
```

### `projects/_dialog.html` — 프로젝트 생성·수정 모달 (`#dialog` 안에 들어간다)

```html
<form class="stack" hx-post="{% if project %}{% url 'project_edit' project.pk %}{% else %}{% url 'project_new' %}{% endif %}" hx-target="#dialog" hx-swap="innerHTML">
  <h2 class="t20">{% if project %}프로젝트 수정{% else %}새 프로젝트{% endif %}</h2>
  <input type="hidden" name="team" value="{{ team.pk }}">
  {{ form.version }}
  <label class="field">이름<input class="input" name="name" value="{{ form.name.value|default:'' }}" required autofocus></label>
  <label class="field">목적<textarea class="textarea" name="purpose" rows="2">{{ form.purpose.value|default:'' }}</textarea></label>
  <div class="section">
    <span class="label">관리자 (여러 명 가능)</span>
    <div class="chips">{% for u in members %}<label class="chip"><input type="checkbox" name="owners" value="{{ u.pk }}"{% if u.pk in checked_owner_ids %} checked{% endif %}>{{ u.display_name }}</label>{% endfor %}</div>
  </div>
  <div class="section">
    <span class="label">상태</span>
    <div class="radios">{% for code, label, desc in status_options %}<label class="radio-card"><input type="radio" name="status" value="{{ code }}"{% if code == status_value %} checked{% endif %}><b>{{ label }}</b><span>{{ desc }}</span></label>{% endfor %}</div>
  </div>
  {% for e in form.non_field_errors %}<div class="error">{{ e }}</div>{% endfor %}
  {% for f in form %}{% for e in f.errors %}<div class="error">{{ f.label }}: {{ e }}</div>{% endfor %}{% endfor %}
  <div class="row">
    <button class="btn primary">{% if project %}변경 내용 저장{% else %}프로젝트 만들기{% endif %}</button>
    <button type="button" class="btn" data-action="close-dialog">취소</button>
  </div>
</form>
```

### 나머지 템플릿 요점

| 템플릿 | 필수 요소 |
|---|---|
| `auth/login.html` | `{% block auth %}` 안에 Django `form`, "가입" 링크(`{% url 'signup' %}?next={{ request.GET.next }}`) |
| `auth/signup.html` | `form.as_p`, 제출 |
| `auth/join.html` | 팀 참여 확인 버튼(POST). `error`가 있으면 표시 |
| `search.html` | 52px 검색 input(`class="input lg"`, placeholder "예: TASK-121, 메뉴, 챗봇"), 체크 "완료·취소 포함", "보관 포함", 결과 개수 + `ul.tasks`, 빈 결과 문구 "검색 결과가 없습니다." |
| `teams/list.html` | 팀 목록(각각 `team_detail` 링크), 팀이 없으면 "아직 팀에 속해 있지 않습니다. 초대 링크가 필요합니다.", "팀 만들기" 링크 |
| `teams/new.html` | `TeamForm` |
| `teams/members.html` | 제목 "{팀} 팀원 관리", "관리자 N명" 안내, 멤버 표(이름, 역할 select POST, 참여일, Discord 연결 여부, 미완료·초과 건수, 제거 버튼), Discord 미연결 안내 한 줄(연결은 각자 프로필에서 한다), 초대 링크 표(제거한 사람이 링크로 다시 들어올 수 있다는 안내 포함)(URL, 만료, 사용 횟수, 폐기 버튼), `InviteForm` |
| `tasks/edit.html` | `TaskForm.as_p`(제목·프로젝트·담당자·중요도·기한·기한 미정 사유·설명·완료 조건·다음 행동), "저장"·"취소" |
| `settings/profile.html` | `ProfileForm`(표시 이름만) + **Discord 연결 카드**. 전체 코드는 아래 |
| `settings/tokens.html` | `new_token`이 있으면 `<code>`로 1회 표시 + "지금 복사하세요. 다시 볼 수 없습니다.", 토큰 표(이름, 앞자리, 범위, 만료, 폐기 버튼), `TokenForm`, MCP 연결 안내(GUIDE-03 Step 5 표) |
| `ops.html` | `IntegrationStatus` 표(이름, 마지막 실행, ok, detail JSON), "JSON 내보내기" 링크 |

상태·중요도는 항상 **텍스트**로 표시한다. 색상만으로 구분하지 않는다.

### `settings/profile.html` (전체)

```html
{% extends "base.html" %}{% block title %}프로필{% endblock %}
{% block main %}
<div class="card">
  <h1 class="t24">프로필</h1>
  <form method="post" class="stack">{% csrf_token %}
    {% for f in form %}<label class="field">{{ f.label }}{{ f }}</label>{% for e in f.errors %}<div class="error">{{ e }}</div>{% endfor %}{% endfor %}
    <button class="btn primary">저장</button>
  </form>
</div>
<div class="card">
  <h2>Discord 연결</h2>
  <p class="muted t13">연결하면 마감 알림(D-3 · D-1 · 당일 · 기한 초과)을 개인 DM으로 받고, 봇에게 DM으로 태스크를 처리할 수 있습니다.</p>
  {% if link_code %}
  <p>Discord에서 봇에게 <b>DM</b>으로 아래 한 줄을 <b>10분 안에</b> 보내세요.</p>
  <code>연결 {{ link_code }}</code>
  <p class="warning t13">이 코드는 지금 한 번만 보입니다. 놓치면 다시 발급하세요.</p>
  {% endif %}
  {% if user.discord_user_id %}
  <p class="row">연결됨 · {{ user.discord_linked_at|date:"Y-m-d H:i" }}
    <form method="post" action="{% url 'discord_unlink' %}">{% csrf_token %}<button class="btn sm">연결 해제</button></form>
  </p>
  <p class="muted t13">해제하면 DM 알림이 멈춥니다. Discord에서 봇에게 <code>연결해제</code>를 보내도 됩니다.</p>
  {% else %}
  <form method="post" action="{% url 'discord_link' %}">{% csrf_token %}<button class="btn primary">Discord 연결</button></form>
  <p class="muted t13">봇과 같은 서버에 있어야 하고, 서버 우클릭 → 개인정보 보호 설정에서 &lsquo;서버 멤버의 DM 허용&rsquo;이 켜져 있어야 DM이 도착합니다.</p>
  {% endif %}
</div>
{% endblock %}
```

- 코드는 `link_code`가 있을 때만, 즉 **발급 직후 한 번만** 그려진다(뷰에서 세션 `pop`). 새로고침하면 사라진다 — 토큰 화면의 `new_token`과 같은 규칙이다.
- snowflake 원문(`discord_user_id`)은 화면에 그리지 않는다. 연결 여부와 시각만 보여 준다.
- 입력칸이 없다는 것이 이 화면의 요점이다. 사용자가 남의 Discord id를 적어 넣을 수 있으면 연결 증명 전체가 무의미해진다(GUIDE-00 §3).

---

## 6.14 검증

```bash
uv run python manage.py check
uv run ruff check .
uv run python manage.py runserver
```

목업을 나란히 띄운다: 저장소 루트에서 `python -m http.server 8765` 후 `http://127.0.0.1:8765/유달리 업무 목업 v2.dc.html`. 브라우저에서 순서대로 해 본다. 전부 되면 통과.

1. `/signup`으로 새 계정 `u2` 가입 → `/today`로 이동하고 "초대 링크가 필요합니다" 안내가 보인다.
2. `u1`(Step 3에서 만든 계정)로 로그인 → `/teams/1/members`에서 초대 링크 발급 → 링크 복사.
3. `u2`로 로그인 후 초대 링크 열기 → 참여 버튼 → `/today`.
4. `/today` 헤더 "빠른 추가" → 제목·프로젝트·중요도 9·기한 오늘+2 → 추가 → 오늘 태스크에 "직접 담은" 행으로 보이고 지금 할 일 카드에 뜬다.
5. 기한이 오늘+3인 태스크를 하나 더 만들면(프로젝트 화면 인라인 폼) 오늘 목록에 "자동 추가 · 오늘 제외" 버튼으로 보이고 "마감 5일 이내 자동 추가 1건." 문구가 뜬다. 버튼을 누르면 사라지고 "오늘 제외 1건 · 제외한 태스크 복원"이 보인다. 복원하면 돌아온다. 자동 담기 select를 "끄기"로 바꾸면 자동 항목이 사라진다.
6. 행의 상태 select를 "진행 중"으로 바꾸면 행만 갱신되고 페이지가 새로고침되지 않는다. 지금 할 일 카드의 버튼이 "완료로 표시"로 바뀐다.
7. 기한 없는 태스크(사유 입력)의 상태를 "진행 중"으로 바꾸면 행 아래에 "목표 기한이 없어서 진행 중으로 바꾸지 못했어요. 기한을 먼저 정해 주세요."가 뜬다.
8. 행의 상태 select에서 "막힘"을 고르면 오른쪽 패널이 열리고 "막힘 사유" 박스에 포커스가 간다. 비운 채 "막힘으로 변경" → "막힘 사유를 입력하세요." 사유 입력 후 확정 → 행 pill이 막힘 색, 사유가 `--danger` 색으로 행에 보인다. "취소"를 누르면 상태가 그대로다.
9. 행 아무 곳이나 누르면 패널이 열리고 주소가 `/tasks/N`으로 바뀐다. 목록 스크롤 위치가 유지된다. "크게 보기"를 누르면 본문이 숨고 패널이 2열로 넓어진다. "닫기"로 주소가 목록으로 돌아온다.
10. 패널 제목을 고치고 포커스를 옮기면 "저장 중…" → "자동 저장됨"이 잠깐 보인다. 진행 메모에 여러 줄을 입력해도 저장된다. 새로고침해도 남아 있다. `/api/tasks/N`에서 `version`이 그대로다.
11. 패널 "목표일 연장하기" → 현재보다 앞 날짜를 고르면 "현재 목표일보다 뒤의 날짜를 선택하세요.", 사유 없이 저장하면 "연장 사유를 입력하세요.", 제대로 하면 목표일이 바뀌고 변경 이력에 "기한: 9월 12일 → 9월 15일 (연장: …)"이 맨 위에 보인다. 행의 기한 라벨도 바뀐다.
12. 패널에서 체크리스트 2개 추가, 하나 체크 → 행에 "체크리스트 1/2". 링크 추가 → 종류 배지와 함께 보인다. 🔗 버튼 → "TASK-N 링크 복사됨".
13. 다른 브라우저(또는 시크릿 창)에서 같은 태스크 상태를 바꾼 뒤, 원래 창에서 행의 상태를 바꾸면 "다른 사람이 먼저 수정했습니다" 오류가 행에 표시된다.
14. `/me`: 기한별 5그룹, 그룹 안에 프로젝트 하위 묶음(완료 n/m, 진행률 바). "프로젝트별"·"상태별" 버튼과 기한·프로젝트·상태·중요도 select가 URL 쿼리로 동작한다. 팀원 select에서 "팀 전체" → 제목 "팀 전체 태스크", 힌트에 "보기 전용", 행의 상태 select가 비활성이고 오늘 버튼이 없다. "오늘 완료"·"지난 7일 완료" 필터는 단일 목록이다.
15. `/team`(팀 현황): 지표 6개를 누르면 `/me?member=0&...`로 가고 숫자와 목록 건수가 같다. 프로젝트 표에 관리자(없으면 경고색 "미지정")·상태 배지+설명·미완료·완료 x/y. "새 프로젝트" → 모달 → 이름 없이 제출하면 모달 안에 "이름을 입력하세요.", 관리자 칩 2명·상태 라디오 선택 후 만들면 그 프로젝트 화면으로 간다.
16. `/projects/N`: "프로젝트 수정" 모달, "태스크 만들기" 인라인 폼(담당자 기본 "나", 변경 가능) → 만들면 새 태스크의 패널이 열린다. 목록/보드 전환, "완료·취소 포함" 체크 시 보드에 완료·취소 열이 생긴다.
17. `/search`: "TASK-1", 제목 일부, 프로젝트 이름으로 검색된다. "완료·취소 포함" 없이는 완료 태스크가 안 나온다.
18. `/today?schedule=1`: 일정 카드가 목록 옆에 열리고 시간표/캘린더 전환, 캘린더에서 마감 ●n, 날짜 클릭 시 그날 마감 목록.
19. 창 폭 1100px: 패널을 열면 본문 대신 패널만 보인다. 700px: 메뉴가 두 줄, 프로젝트 레일이 가로 스크롤, 패널이 전체 화면, 팀 지표가 2열.
20. `/settings/tokens`에서 토큰 발급 → 원문이 한 번만 보이고 새로고침하면 사라진다. 범위 select에는 "읽기"·"읽기·쓰기" 둘만 있다. superuser로 `/ops`가 열리고 `/ops/export.json`이 내려받아진다(본문에 `discord_link_code`가 없다). 로그아웃 상태에서 `/today` → `/login?next=/today`.
21. `/settings/profile`: Discord ID 입력칸이 없다. **[Discord 연결]** → 8자 코드가 한 번 보이고 새로고침하면 사라진다. `/admin`에서 그 사용자의 `discord_user_id`는 읽기 전용이다. `/teams/1` 헤더에 '알림 채널' 링크가 없고 `/teams/1/webhooks`는 404다.

커밋: `step 6: web ui`

다음: [GUIDE-01-core-5-tests.md](GUIDE-01-core-5-tests.md)
