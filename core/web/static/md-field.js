// 마크다운 긴 글 칸 공용 모듈(시안 design-concepts/editor-2026-10-09/claude-a2.html).
// 마크업
//   입력 칸  textarea[data-md][data-toolbar="top|bottom"]  → 옆에 Tiptap 칸(.mdf)을 만들고 textarea는 숨긴 채 값을 맞춘다.
//            폼 제출·HTMX(hx-trigger="change")·required는 원래 textarea가 그대로 맡는다. JS가 없으면 textarea가 보인다.
//   보기     .md-view > textarea.md-src                     → 같은 렌더러로 읽기 전용(JS가 없으면 원문이 보인다)
//   문서     doc-tiptap.js가 저장 큐를 갖고, 서식 줄은 여기 toolbar()를 쓴다.
// 모든 칸은 같은 기능·같은 우선순위다. 다른 것은 서식 줄 위치(위/아래)뿐이고, 모바일은 위치와 무관하게 화면 키보드 위에 붙는다.
// 열기만으로는 값을 바꾸지 않는다(실제 입력·조작 뒤, 불러온 직후와 내용이 다를 때만). 한글 조합 중에는 동기화·저장을 미룬다.
let bundle = null;
export const load = () => (bundle ??= import(new URL("vendor/tiptap.bundle.js", import.meta.url).href));

const sv = (d) => `<svg viewBox="0 0 24 24" aria-hidden="true" focusable="false">${d}</svg>`;
const H = "M4 12h8M4 18V6M12 18V6";
const TBL = '<rect x="3" y="4" width="18" height="16" rx="2"/>';
// [키, 이름, 단축키, 아이콘, 표 안에서만]. 순서가 곧 우선순위다(왼쪽이 먼저, 좁아지면 뒤에서부터 [더보기]로).
const TOOLS = [
  ["bold", "굵게", "Ctrl+B", sv('<path d="M6 12h8a4 4 0 0 1 0 8H6zM6 4h7a4 4 0 0 1 0 8H6z"/>')],
  ["italic", "기울임", "Ctrl+I", sv('<path d="M19 4h-9M14 20H5M15 4 9 20"/>')],
  ["h2", "제목", "Ctrl+Alt+2", sv(`<path d="${H}M21 18h-4c0-4 4-3 4-6 0-1.5-2-2.5-4-1"/>`)],
  ["h3", "소제목", "Ctrl+Alt+3", sv(`<path d="${H}M17.5 10.5c1.7-1 3.5 0 3.5 1.5a2 2 0 0 1-2 2M17 17.5c2 1.5 4 .3 4-1.5a2 2 0 0 0-2-2"/>`)],
  ["bullet", "목록", "Ctrl+Shift+8", sv('<path d="M9 6h11M9 12h11M9 18h11"/><circle cx="4.5" cy="6" r="1"/><circle cx="4.5" cy="12" r="1"/><circle cx="4.5" cy="18" r="1"/>')],
  ["ordered", "번호 목록", "Ctrl+Shift+7", sv('<path d="M10 6h11M10 12h11M10 18h11M4 10h2M4 6h1v4M6 18H4c0-1 2-2 2-3s-1-1.5-2-1"/>')],
  ["task", "체크 목록", "Ctrl+Shift+9", sv('<rect x="3.5" y="4" width="16" height="16" rx="3"/><path d="M7.5 12l3 3 5-6"/>')],
  ["link", "링크", "Ctrl+K", sv('<path d="M10 14a4 4 0 0 0 5.7 0l3-3a4 4 0 0 0-5.7-5.7l-1 1M14 10a4 4 0 0 0-5.7 0l-3 3a4 4 0 0 0 5.7 5.7l1-1"/>')],
  ["quote", "인용", "Ctrl+Shift+B", sv('<path d="M4 5v14M9 8h11M9 12h11M9 16h7"/>')],
  ["code", "코드 블록", "Ctrl+Alt+C", sv('<path d="M8 7l-5 5 5 5M16 7l5 5-5 5"/>')],
  ["table", "표 넣기", "", sv(TBL + '<path d="M3 10h18M9 4v16"/>')],
  ["row+", "행 추가", "", sv('<rect x="3" y="3" width="18" height="10" rx="2"/><path d="M3 8h18M12 16v6M9 19h6"/>'), true],
  ["col+", "열 추가", "", sv('<rect x="3" y="3" width="10" height="18" rx="2"/><path d="M8 3v18M16 12h6M19 9v6"/>'), true],
  ["row-", "행 삭제", "", sv('<rect x="3" y="3" width="18" height="10" rx="2"/><path d="M3 8h18M9 19h6"/>'), true],
  ["col-", "열 삭제", "", sv('<rect x="3" y="3" width="10" height="18" rx="2"/><path d="M8 3v18M16 12h6"/>'), true],
  ["table-", "표 삭제", "", sv(TBL + '<path d="M9 9l6 6M15 9l-6 6"/>'), true],
  ["image", "그림", "", sv('<rect x="3" y="4" width="18" height="16" rx="2"/><circle cx="9" cy="10" r="2"/><path d="M21 17l-5-5-9 8"/>')],
  ["hr", "구분선", "", sv('<path d="M3 12h18M8 7h8M8 17h8"/>')],
  ["h1", "큰 제목", "Ctrl+Alt+1", sv(`<path d="${H}M17 12l3-2v8"/>`)],
  ["undo", "실행 취소", "Ctrl+Z", sv('<path d="M3 7v6h6M21 17a9 9 0 0 0-15-6.7L3 13"/>')],
  ["redo", "다시 실행", "Ctrl+Shift+Z", sv('<path d="M21 7v6h-6M3 17a9 9 0 0 1 15-6.7l3 2.7"/>')],
];
const MORE = sv('<circle cx="5" cy="12" r="1.2"/><circle cx="12" cy="12" r="1.2"/><circle cx="19" cy="12" r="1.2"/>');
const EDIT = sv('<path d="M12 20h9M16.5 3.5a2.1 2.1 0 0 1 3 3L7 19l-4 1 1-4z"/>');
const UNLINK = sv('<path d="M18.8 12.3l1.7-1.7a4.8 4.8 0 0 0-6.8-6.8L12 5.5M5.2 11.7l-1.7 1.7a4.8 4.8 0 0 0 6.8 6.8l1.7-1.7M8 2v3M2 8h3M16 22v-3M22 16h-3"/>');
const INFO = Object.fromEntries(TOOLS.map(([k, label, key, icon, inTable]) => [k, { label, key, icon, inTable }]));
const tip = (k) => INFO[k].label + (INFO[k].key ? " " + INFO[k].key : "");

const CMD = {
  bold: (c) => c.toggleBold(), italic: (c) => c.toggleItalic(),
  h1: (c) => c.toggleHeading({ level: 1 }), h2: (c) => c.toggleHeading({ level: 2 }), h3: (c) => c.toggleHeading({ level: 3 }),
  bullet: (c) => c.toggleBulletList(), ordered: (c) => c.toggleOrderedList(), task: (c) => c.toggleTaskList(),
  quote: (c) => c.toggleBlockquote(), code: (c) => c.toggleCodeBlock(), hr: (c) => c.setHorizontalRule(),
  table: (c) => c.insertTable({ rows: 3, cols: 3, withHeaderRow: true }),
  "row+": (c) => c.addRowAfter(), "col+": (c) => c.addColumnAfter(), "row-": (c) => c.deleteRow(), "col-": (c) => c.deleteColumn(),
  "table-": (c) => c.deleteTable(), undo: (c) => c.undo(), redo: (c) => c.redo(), unlink: (c) => c.extendMarkRange("link").unsetLink(),
};
const ACTIVE = { bold: ["bold"], italic: ["italic"], bullet: ["bulletList"], ordered: ["orderedList"], task: ["taskList"], quote: ["blockquote"],
  code: ["codeBlock"], link: ["link"], h1: ["heading", { level: 1 }], h2: ["heading", { level: 2 }], h3: ["heading", { level: 3 }] };

function editLink(T, ed) {
  const v = window.prompt("링크 주소(https://… 또는 /로 시작). 비우면 링크를 지웁니다.", ed.getAttributes("link").href || "");
  if (v === null) return;
  const href = v.trim(), ch = ed.chain().focus().extendMarkRange("link");
  if (!href) return ch.unsetLink().run();
  if (!T.safeUrl(href)) return window.alert("https://, mailto: 또는 /로 시작하는 주소만 넣을 수 있습니다.");
  if (ed.state.selection.empty && !ed.isActive("link")) ch.insertContent({ type: "text", text: href, marks: [{ type: "link", attrs: { href } }] }).run();
  else ch.setLink({ href }).run();
}
function addImage(T, ed) {
  const v = window.prompt("그림 주소(https://… 또는 /로 시작)");
  if (!v) return;
  if (!T.safeUrl(v, { image: true })) return window.alert("https:// 또는 /로 시작하는 주소만 넣을 수 있습니다.");
  ed.chain().focus().setImage({ src: v.trim(), alt: "" }).run();
}
// 초점을 즉시 옮긴다(chain().focus는 한 프레임 늦어 첫 글자를 놓칠 수 있다)
function run(T, ed, k) {
  ed.view.focus();
  if (k === "link") editLink(T, ed);
  else if (k === "image") addImage(T, ed);
  else CMD[k](ed.chain().focus()).run();
}

// 모바일: 화면 키보드 높이(visualViewport가 줄어든 만큼)를 --md-kb로. 서식 줄과 [더보기]가 이 값 위에 선다.
const vv = window.visualViewport;
function dock() {
  const kb = vv ? Math.max(0, window.innerHeight - vv.height - vv.offsetTop) : 0;
  document.documentElement.style.setProperty("--md-kb", kb + "px");
}
if (vv) { vv.addEventListener("resize", dock); vv.addEventListener("scroll", dock); }

let pointerDown = false;
document.addEventListener("pointerdown", () => { pointerDown = true; }, true);
document.addEventListener("pointerup", () => { pointerDown = false; }, true);

// 서식 줄. box(테두리 칸) 안, body(편집 영역) 위나 아래에 붙인다. 초점이 칸 안에 있고 편집 중일 때만 보인다.
// opts: position "top|bottom", touch() 실제 조작 알림, openLink(href) 링크 열기(없으면 새 탭)
export function toolbar(T, ed, box, body, { position = "bottom", touch = () => {}, openLink = null } = {}) {
  box.classList.add("mdf");
  box.dataset.toolbar = position;
  const name = ed.view.dom.getAttribute("aria-label") || "본문";
  const bar = document.createElement("div");
  bar.className = "mdf-bar";
  bar.setAttribute("role", "toolbar");
  bar.setAttribute("aria-label", name + " 서식");
  bar.innerHTML = TOOLS.map(([k]) =>
    `<button type="button" class="btn sm icon" data-k="${k}" aria-label="${INFO[k].label}" title="${tip(k)}"${ACTIVE[k] ? ' aria-pressed="false"' : ""}>${INFO[k].icon}</button>`).join("") +
    `<button type="button" class="btn sm icon more" aria-haspopup="menu" aria-expanded="false" aria-label="더보기" title="더보기">${MORE}</button>`;
  const menu = document.createElement("div");
  menu.className = "mdf-menu";
  menu.setAttribute("role", "menu");
  menu.setAttribute("aria-label", name + " 더보기");
  menu.hidden = true;
  const linkRow = document.createElement("div");
  linkRow.className = "mdf-link t13";
  linkRow.hidden = true;
  linkRow.innerHTML = `<a class="mdf-href" href="#" target="_blank" rel="noopener noreferrer"></a>` +
    `<button type="button" class="btn sm icon" data-k="link" aria-label="링크 수정" title="링크 수정 Ctrl+K">${EDIT}</button>` +
    `<button type="button" class="btn sm icon" data-k="unlink" aria-label="링크 해제" title="링크 해제">${UNLINK}</button>`;
  const hrefEl = linkRow.querySelector("a");
  if (position === "top") body.before(bar, linkRow);
  else body.after(linkRow, bar);
  box.append(menu);
  const more = bar.querySelector(".more");
  const tools = [...bar.querySelectorAll("[data-k]")];
  let shown = [], rest = [];

  // 우선순위 넘김: 줄의 실제 폭에 들어가는 만큼 앞에서부터 두고, 나머지는 [더보기]로
  function layout() {
    if (!bar.getClientRects().length) return; // 숨어 있으면 재지 않는다
    const inTable = ed.isActive("table");
    const cand = tools.filter((b) => inTable || !INFO[b.dataset.k].inTable);
    tools.forEach((b) => { b.hidden = !cand.includes(b); });
    more.hidden = false;
    const cs = getComputedStyle(bar);
    const avail = bar.clientWidth - parseFloat(cs.paddingLeft) - parseFloat(cs.paddingRight);
    const gap = parseFloat(cs.columnGap) || 0;
    const ws = cand.map((b) => b.offsetWidth);
    let n = cand.length;
    if (ws.reduce((a, w) => a + w, 0) + gap * (n - 1) > avail) {
      let used = more.offsetWidth;
      n = 0;
      for (const w of ws) { if (used + gap + w > avail) break; used += gap + w; n++; }
    }
    cand.forEach((b, i) => { b.hidden = i >= n; });
    shown = cand.slice(0, n);
    rest = cand.slice(n).map((b) => b.dataset.k);
    more.hidden = !rest.length;
    if (rest.length) more.setAttribute("aria-label", "더보기: " + rest.map((k) => INFO[k].label).join(", "));
    else closeMenu();
  }
  function openMenu() {
    menu.innerHTML = rest.map((k) =>
      `<button type="button" role="menuitem" data-k="${k}">${INFO[k].icon}<span class="grow">${INFO[k].label}</span><kbd>${INFO[k].key}</kbd></button>`).join("");
    menu.hidden = false;
    const r = more.getBoundingClientRect(), h = menu.offsetHeight, w = menu.offsetWidth;
    const floor = window.innerHeight - (parseFloat(getComputedStyle(document.documentElement).getPropertyValue("--md-kb")) || 0);
    menu.style.top = (r.bottom + 4 + h < floor ? r.bottom + 4 : r.top - h - 4) + "px"; // 키보드가 있으면 위로 연다
    menu.style.left = Math.max(8, Math.min(r.right - w, window.innerWidth - w - 8)) + "px";
    more.setAttribute("aria-expanded", "true");
    menu.querySelector("button")?.focus();
  }
  function closeMenu(refocus) {
    if (menu.hidden) return;
    menu.hidden = true;
    more.setAttribute("aria-expanded", "false");
    if (refocus) ed.view.focus();
  }
  function act(k) {
    touch();
    if (k === "unlink") CMD.unlink(ed.chain().focus()).run();
    else run(T, ed, k);
  }
  for (const el of [bar, menu, linkRow]) el.addEventListener("mousedown", (e) => { if (!e.target.closest("a")) e.preventDefault(); }); // 초점·모바일 키보드 유지
  bar.addEventListener("click", (e) => {
    const b = e.target.closest("button");
    if (!b) return;
    if (b === more) return menu.hidden ? openMenu() : closeMenu(true);
    act(b.dataset.k);
  });
  linkRow.addEventListener("click", (e) => {
    const b = e.target.closest("[data-k]");
    if (b) return act(b.dataset.k);
    if (openLink && e.target.closest("a")) { e.preventDefault(); openLink(hrefEl.getAttribute("href")); }
  });
  menu.addEventListener("click", (e) => { const b = e.target.closest("[data-k]"); if (b) { closeMenu(); act(b.dataset.k); } });
  menu.addEventListener("keydown", (e) => {
    const items = [...menu.querySelectorAll("button")], i = items.indexOf(document.activeElement);
    if (e.key === "ArrowDown") { e.preventDefault(); items[(i + 1) % items.length].focus(); }
    if (e.key === "ArrowUp") { e.preventDefault(); items[(i - 1 + items.length) % items.length].focus(); }
    if (e.key === "Escape") { e.preventDefault(); e.stopPropagation(); closeMenu(true); }
  });
  // ProseMirror보다 먼저 받는다(조상에서 캡처): Ctrl+K 링크, Alt+F10 서식 줄로, Alt+↑/↓ 블록 옮기기(끌어 옮기기의 키보드 대안)
  const onKey = (e) => {
    if (e.isComposing || !ed.isEditable) return;
    if ((e.ctrlKey || e.metaKey) && e.key.toLowerCase() === "k") { e.preventDefault(); e.stopPropagation(); act("link"); }
    if (e.altKey && e.key === "F10") { e.preventDefault(); shown[0]?.focus(); }
    if (e.altKey && !e.ctrlKey && !e.metaKey && (e.key === "ArrowUp" || e.key === "ArrowDown")) {
      e.preventDefault();
      e.stopPropagation();
      touch();
      T.moveBlock(ed, e.key === "ArrowUp" ? -1 : 1);
    }
  };
  body.addEventListener("keydown", onKey, true);
  // Ctrl/Cmd+클릭은 링크를 연다(편집 중 그냥 클릭은 커서만 놓는다)
  body.addEventListener("click", (e) => {
    const a = e.target.closest("a[href]");
    if (!a || !ed.isEditable) return;
    e.preventDefault();
    const href = a.getAttribute("href");
    if ((e.ctrlKey || e.metaKey) && T.safeUrl(href)) window.open(href, "_blank", "noopener");
  });

  let wasTable = false;
  function sync() {
    for (const b of tools) if (ACTIVE[b.dataset.k]) b.setAttribute("aria-pressed", String(ed.isActive(...ACTIVE[b.dataset.k])));
    const href = box.classList.contains("on") && ed.isActive("link") ? ed.getAttributes("link").href : "";
    linkRow.hidden = !href;
    if (href) { hrefEl.textContent = href; hrefEl.setAttribute("href", T.safeUrl(href) || "#"); }
    const t = ed.isActive("table");
    if (t !== wasTable) { wasTable = t; layout(); }
  }
  function refresh() {
    const on = ed.isEditable && box.contains(document.activeElement);
    box.classList.toggle("on", on);
    if (on) { dock(); layout(); } else closeMenu();
    sync();
  }
  ed.on("transaction", sync);
  const onIn = () => refresh();
  // 누른 채 초점이 빠지면(다른 버튼을 누르는 중) 손을 뗀 뒤에 접는다. 바로 접으면 아래 버튼이 밀려 클릭이 빗나간다.
  const hide = () => { if (box.contains(document.activeElement)) return; box.classList.remove("on"); closeMenu(); sync(); };
  const onOut = (e) => {
    if (box.contains(e.relatedTarget)) return;
    if (pointerDown) document.addEventListener("pointerup", () => setTimeout(hide), { once: true, capture: true });
    else hide();
  };
  box.addEventListener("focusin", onIn);
  box.addEventListener("focusout", onOut);
  const ro = new ResizeObserver(() => layout());
  ro.observe(bar);
  sync();
  return { refresh, destroy: () => { ro.disconnect(); ed.off("transaction", sync); } };
}

// ---------- 입력 칸: textarea[data-md] ----------
function labelOf(ta) {
  const l = ta.labels?.[0];
  return ta.getAttribute("aria-label") || (l && [...l.childNodes].filter((n) => n.nodeType === 3 || n.tagName === "SPAN").map((n) => n.textContent).join(" ").trim()) || "본문";
}

function field(T, ta) {
  const autosave = ta.hasAttribute("data-autosave");
  const box = document.createElement("div");
  const body = document.createElement("div");
  body.className = "mdf-body md";
  body.style.setProperty("--rows", ta.rows || 3);
  box.append(body);
  ta.after(box);
  const ed = new T.Editor({
    element: body,
    extensions: T.extensions({ placeholder: ta.placeholder || "", checkInView: true, drag: true }),
    content: T.preprocess(ta.value),
    contentType: "markdown",
  });
  T.setupMarkdown(ed);
  ta.hidden = true;
  const dom = ed.view.dom;
  dom.setAttribute("aria-label", labelOf(ta));
  dom.setAttribute("aria-multiline", "true");
  if (ta.required) dom.setAttribute("aria-required", "true");

  // 열기만으로는 값을 바꾸지 않는다: 실제 조작(touched)이 있고 불러온 직후(base)와 다를 때만 textarea에 쓴다.
  let touched = false;
  const touch = () => { touched = true; };
  for (const ev of ["beforeinput", "paste", "drop", "compositionstart"]) dom.addEventListener(ev, touch, true); // 캡처: 편집기가 처리(→ update)하기 전에 표시
  dom.addEventListener("keydown", (e) => { if (e.ctrlKey || e.metaKey || e.key.length === 1 || /^(Enter|Backspace|Delete|Tab)$/.test(e.key)) touch(); });
  dom.addEventListener("click", (e) => { if (e.target.type === "checkbox") touch(); }, true);
  const orig = ta.value, base = ed.getMarkdown();
  let sent = orig, timer = null, err = null;
  const sync = () => {
    if (!touched || ed.view.composing) return false;
    const md = ed.getMarkdown();
    ta.value = md === base ? orig : md;
    return true;
  };
  // change를 쏘면 hx-trigger="change" 자동 저장이 그대로 돈다
  const commit = () => {
    clearTimeout(timer);
    timer = null;
    if (!sync() || ta.value === sent) return;
    sent = ta.value;
    ta.dispatchEvent(new Event("change", { bubbles: true }));
  };
  const later = () => {
    if (!sync() || !autosave) return;
    clearTimeout(timer);
    timer = setTimeout(commit, 800);
  };
  ed.on("update", () => { if (touched) { box.classList.remove("bad"); err?.remove(); err = null; later(); } });
  dom.addEventListener("compositionend", () => setTimeout(later)); // 조합이 끝난 뒤의 트랜잭션까지 기다린다
  box.addEventListener("focusout", (e) => { if (!box.contains(e.relatedTarget)) commit(); });
  ta._mdCommit = commit;

  // 초점 위임: app.js의 data-focus·toggle과 라벨 클릭이 숨은 textarea 대신 편집기로 간다
  ta.focus = () => ed.commands.focus("end");
  for (const l of ta.labels || []) l.addEventListener("click", (e) => { e.preventDefault(); ta.focus(); });
  body.addEventListener("mousedown", (e) => { if (e.target === body) { e.preventDefault(); ta.focus(); } });
  // required: 숨은 textarea 대신 칸에 오류를 보인다
  ta.addEventListener("invalid", (e) => {
    e.preventDefault();
    box.classList.add("bad");
    if (!err) { err = document.createElement("div"); err.className = "error t13"; err.setAttribute("role", "alert"); err.textContent = "내용을 적어 주세요."; box.after(err); }
    ed.commands.focus();
  });
  // Ctrl/Cmd+Enter: 제출형 폼이면 바로 보낸다(자동 저장 칸은 해당 없음)
  body.addEventListener("keydown", (e) => {
    if (e.isComposing || !(e.ctrlKey || e.metaKey) || e.key !== "Enter" || autosave || !ta.form) return;
    e.preventDefault();
    e.stopPropagation();
    commit();
    ta.form.requestSubmit();
  }, true);

  const position = ta.dataset.toolbar === "top" ? "top" : "bottom";
  const tb = toolbar(T, ed, box, body, { position, touch });
  if (position === "top") {
    const cue = document.createElement("div");
    cue.className = "mdf-cue";
    cue.setAttribute("aria-hidden", "true");
    cue.textContent = "본문을 누르면 고칠 수 있습니다. 서식 줄은 그때 이 자리에 나타납니다.";
    cue.addEventListener("mousedown", (e) => { e.preventDefault(); ta.focus(); });
    box.prepend(cue);
  }
  if (ta.hasAttribute("data-focus") && (!document.activeElement || document.activeElement === document.body || document.activeElement === ta)) ta.focus();
  ta.dataset.ready = "1";
  ta._mdDestroy = () => { commit(); tb.destroy(); ed.destroy(); };
}

function view(T, el) {
  const src = el.querySelector(".md-src");
  const ed = new T.Editor({ element: el, editable: false, extensions: T.extensions(), content: T.preprocess(src.value), contentType: "markdown" });
  src.hidden = true;
  el.dataset.ready = "1";
  el._mdDestroy = () => ed.destroy();
}

const SEL = "textarea[data-md], .md-view";
function init(root) {
  const found = [...(root.querySelectorAll?.(SEL) || [])];
  if (root.matches?.(SEL)) found.push(root);
  const todo = found.filter((el) => !el.dataset.ready);
  if (!todo.length) return;
  todo.forEach((el) => { el.dataset.ready = "loading"; });
  load().then((T) => todo.forEach((el) => (el.matches(".md-view") ? view(T, el) : field(T, el))));
}
init(document);
document.addEventListener("htmx:load", (e) => init(e.target));
// HTMX가 조각을 지우기 전에 남은 입력을 보내고 편집기를 정리한다(지워지는 요소마다 불린다)
document.addEventListener("htmx:beforeCleanupElement", (e) => {
  const el = e.target;
  if (el._mdDestroy) { el._mdDestroy(); el._mdDestroy = null; }
});
// 제출 직전 최신 값을 textarea에 넣는다(htmx의 submit 처리보다 먼저, 캡처 단계)
document.addEventListener("submit", (e) => {
  e.target.querySelectorAll?.("textarea[data-md]").forEach((ta) => ta._mdCommit?.());
}, true);
