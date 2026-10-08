// 문서·회의록 편집기와 Markdown 보기(이슈 본문·거버넌스). 화면에 그릴 것이 있을 때만 Tiptap 번들을 불러온다.
// 마크업
//   편집기  .md-editor[data-url][data-version] > textarea.md-src   (docs/_editor.html, 같은 .card 안에 도구 막대)
//   보기    .md-view > textarea.md-src                              (JS가 없으면 원문이 그대로 보인다)
// 저장 규약: 입력이 멈추고 800ms 뒤 저장, 요청은 하나씩, 응답의 X-Note-Version을 다음 요청이 이어 쓴다,
// 409(충돌)면 저장을 멈추고 알린다. 한글 IME 조합 중에는 저장을 미룬다. 열기만으로는 절대 저장하지 않는다.
// 링크·이미지 주소 검사(safeUrl)와 Markdown 보정은 번들(tools/tiptap-bundle/entry.js) 한곳에 있다.
let bundle = null;
const load = () => (bundle ??= import(new URL("vendor/tiptap.bundle.js", import.meta.url).href));

function init(root) {
  const found = [...(root.querySelectorAll?.(".md-view, .md-editor") || [])];
  if (root.matches?.(".md-view, .md-editor")) found.push(root);
  const todo = found.filter((el) => !el.dataset.ready);
  if (!todo.length) return;
  todo.forEach((el) => { el.dataset.ready = "loading"; });
  load().then((T) => todo.forEach((el) => (el.classList.contains("md-editor") ? editor(T, el) : view(T, el))));
}
init(document);
// HTMX가 나중에 끼워 넣은 조각(이슈 패널 등)에도 붙인다.
document.addEventListener("htmx:load", (e) => init(e.target));

function view(T, el) {
  const src = el.querySelector(".md-src");
  new T.Editor({ element: el, editable: false, extensions: T.extensions(), content: T.preprocess(src.value), contentType: "markdown" });
  src.hidden = true;
  el.dataset.ready = "1";
}

function editor(T, root) {
  const safeUrl = T.safeUrl;
  const scope = root.closest(".card") || document;
  const src = root.querySelector(".md-src");
  const bar = scope.querySelector(".tt-bar");
  const tableBar = bar.querySelector(".tt-table");
  const linkBar = scope.querySelector(".tt-linkbar");
  const hrefEl = linkBar.querySelector(".tt-href");
  const editStart = scope.querySelector(".md-edit-start");
  const statusEl = scope.querySelector("#note-status");
  const conflictEl = scope.querySelector("#note-conflict");
  const fields = [...scope.querySelectorAll("[data-note-field]")];
  const csrf = scope.querySelector("[name=csrfmiddlewaretoken]").value;

  let version = Number(root.dataset.version);
  let dead = false, timer = null, bodyDirty = false, worker = null, seq = 0, navigating = false;
  const pending = Object.create(null);
  const saved = Object.fromEntries(fields.map((f) => [f.dataset.noteField, f.value]));

  const ed = new T.Editor({
    element: root,
    editable: false,
    extensions: T.extensions({ placeholder: "여기에 씁니다.", checkInView: true }),
    content: T.preprocess(src.value),
    contentType: "markdown",
    onUpdate: () => { if (touched) schedule(); },
    onTransaction: syncBar,
  });
  T.setupMarkdown(ed);
  src.hidden = true;
  const dom = ed.view.dom;
  dom.setAttribute("aria-label", "본문");
  // 열기만으로는 저장하지 않는다: (1) 사용자의 실제 입력·조작이 있어야 하고(touched),
  // (2) 저장 직전 md가 마지막 기준(불러온 직후 또는 마지막 저장)과 달라야 한다(baseline).
  let touched = false;
  let baseline = ed.getMarkdown();
  const touch = () => { touched = true; };
  for (const ev of ["beforeinput", "paste", "drop", "compositionstart"]) dom.addEventListener(ev, touch);
  dom.addEventListener("keydown", (e) => { if (e.ctrlKey || e.metaKey || e.key.length === 1 || /^(Enter|Backspace|Delete|Tab)$/.test(e.key)) touch(); });
  // 조합이 끝나면 그때 저장을 예약한다. 조합 중 onUpdate가 와도 schedule이 타이머를 걸지 않는다.
  dom.addEventListener("compositionend", () => { if (bodyDirty) schedule(); });

  // ---------- 저장 ----------
  function flash(text, state) {
    if (!statusEl) return;
    statusEl.textContent = text;
    statusEl.dataset.state = state || "saved";
  }

  const fieldDirty = () => fields.some((f) => f.value !== saved[f.dataset.noteField]);
  const hasUnsaved = () => Boolean(timer || bodyDirty || worker || Object.keys(pending).length || fieldDirty());

  async function requestSave(field, value) {
    const data = new FormData();
    data.append("field", field);
    data.append("value", value);
    data.append("version", String(version));
    flash("저장 중…", "saving");
    let r;
    try {
      r = await fetch(root.dataset.url, { method: "POST", headers: { "X-CSRFToken": csrf }, body: data, credentials: "same-origin" });
    } catch {
      flash("네트워크 연결을 확인하세요. 작성 중인 내용은 이 화면에 남아 있습니다.", "error");
      return false;
    }
    if (!r.ok) {
      if (r.status === 409) {
        dead = true;
        if (conflictEl) conflictEl.hidden = false;
      }
      const body = await r.json().catch(() => ({}));
      const reason = (body && typeof body.error === "string" && body.error) ||
        (r.status === 403 ? "저장 권한을 확인하세요." : "요청을 처리하지 못했습니다. (" + r.status + ")");
      flash(reason + (r.status === 409 ? " 작성 중인 내용을 복사한 뒤 새로고침하세요." : " 작성 중인 내용은 이 화면에 남아 있습니다."), "error");
      return false;
    }
    const v = Number(r.headers.get("X-Note-Version"));
    if (r.redirected || r.status !== 204 || !Number.isInteger(v) || v <= 0) {
      flash("저장 완료를 확인하지 못했습니다. 로그인 상태를 확인하세요.", "error");
      return false;
    }
    version = v;
    root.dataset.version = String(v);
    saved[field] = value;
    // 제목을 바꾸면 목록·트리의 이름도 바로 바꾼다.
    if (field === "title") document.querySelectorAll(".doc-node.sel, .note-item.sel > b").forEach((n) => { n.textContent = value; });
    return true;
  }

  function nextPending() {
    let next = null;
    for (const k in pending) if (!next || pending[k].seq < next.seq) next = pending[k];
    return next;
  }

  // 필드별 최신 값만 남긴다. 실패한 항목은 지우지 않는다.
  function stage(field, value) {
    pending[field] = { field, value, seq: ++seq };
    if (dead) return Promise.resolve(false);
    flash("저장 대기…", "pending");
    return runQueue();
  }

  function runQueue() {
    if (dead) return Promise.resolve(false);
    if (worker) return worker;
    if (!nextPending()) { if (!hasUnsaved()) flash("저장됨 · v" + version, "saved"); return Promise.resolve(true); }
    worker = (async () => {
      for (let item = nextPending(); item; item = nextPending()) {
        if (!(await requestSave(item.field, item.value))) { worker = null; return false; }
        if (pending[item.field] === item) delete pending[item.field];
      }
      worker = null;
      if (!hasUnsaved()) flash("저장됨 · v" + version, "saved");
      return true;
    })();
    return worker;
  }

  function schedule() {
    bodyDirty = true;
    clearTimeout(timer);
    timer = null;
    if (ed.view.composing) { flash("입력 중…", "pending"); return; } // compositionend가 다시 부른다
    flash("저장 대기…", "pending");
    timer = setTimeout(stageBody, 800);
  }

  function stageBody() {
    clearTimeout(timer);
    timer = null;
    if (ed.view.composing) return Promise.resolve(false); // 조합이 끝나면 compositionend → schedule
    if (!bodyDirty) return runQueue();
    bodyDirty = false;
    const md = ed.getMarkdown();
    if (md === baseline) return runQueue(); // 바뀐 내용이 없다(정규화·커서 이동만)
    baseline = md;
    return stage("body_md", md);
  }

  // 남은 입력을 모두 보낸다. 보내는 사이 새 입력이 생기면 다시 돈다.
  async function flushAll() {
    for (const f of fields) if (f.value !== saved[f.dataset.noteField]) stage(f.dataset.noteField, f.value);
    const ok = await (bodyDirty ? stageBody() : runQueue());
    if (!ok || dead) return false;
    return hasUnsaved() && !ed.view.composing ? flushAll() : true;
  }

  // 메타 필드(제목·프로젝트·회의 일시·태그). 제목은 입력을 멈추면 저장하고, 그 사이에는 "저장 대기"를 보인다.
  const fieldTimers = {};
  for (const f of fields) {
    const name = f.dataset.noteField;
    f.addEventListener("change", () => { clearTimeout(fieldTimers[name]); if (f.value !== saved[name]) stage(name, f.value); });
    if (f.tagName === "INPUT" && f.type === "text") {
      f.addEventListener("input", () => {
        clearTimeout(fieldTimers[name]);
        flash("저장 대기…", "pending");
        fieldTimers[name] = setTimeout(() => stage(name, f.value), 800);
      });
    }
  }
  document.addEventListener("visibilitychange", () => { if (document.hidden && hasUnsaved()) flushAll(); });
  window.addEventListener("beforeunload", (e) => {
    if (navigating || !hasUnsaved()) return;
    e.preventDefault();
    e.returnValue = "";
  });

  async function go(href) {
    await flushAll();
    navigating = !hasUnsaved();
    location.assign(href);
  }

  // 모바일 ‘목록으로’: 저장을 마치고 나서 떠난다.
  const back = scope.querySelector(".note-back");
  if (back) back.addEventListener("click", (e) => {
    if (!hasUnsaved()) return;
    e.preventDefault();
    if (back.getAttribute("aria-disabled") === "true") return;
    back.setAttribute("aria-disabled", "true");
    go(back.href).finally(() => back.removeAttribute("aria-disabled"));
  });

  // 파일 묶음의 [본문에 넣기]: 첨부 이미지를 본문 끝에 붙이고 저장한다.
  scope.addEventListener("click", (e) => {
    const b = e.target.closest?.("[data-insert-md]");
    if (!b || !scope.contains(b)) return;
    e.preventDefault();
    const m = b.dataset.insertMd.match(/^!\[([^\]]*)\]\(([^)\s]+)\)$/);
    if (!m || !safeUrl(m[2])) return;
    touch();
    ed.chain().insertContentAt(ed.state.doc.content.size, { type: "image", attrs: { alt: m[1], src: m[2] } }).run();
    flash("본문 끝에 이미지를 넣었습니다.", "pending");
  });

  // ---------- 보기 ↔ 편집 ----------
  function setEditing(on) {
    ed.setEditable(on);
    bar.hidden = !on;
    root.classList.toggle("editing", on);
    if (editStart) editStart.parentElement.hidden = on;
    if (!on) { linkBar.hidden = true; stageBody(); }
    dock();
  }
  if (editStart) editStart.addEventListener("click", () => { setEditing(true); ed.commands.focus("end"); });

  root.addEventListener("click", (e) => {
    const a = e.target.closest("a[href]");
    if (a) {
      e.preventDefault();
      const href = a.getAttribute("href");
      if (!safeUrl(href)) return;
      if (e.ctrlKey || e.metaKey) window.open(href, "_blank", "noopener");
      else if (!ed.isEditable) go(href);
      return; // 편집 중 그냥 클릭: 커서만 놓고 아래 링크 막대에서 연다
    }
    if (!ed.isEditable && !e.target.closest("input")) {
      const at = ed.view.posAtCoords({ left: e.clientX, top: e.clientY });
      setEditing(true);
      ed.chain().focus(at ? at.pos : "end").run();
    }
  });
  dom.addEventListener("keydown", (e) => {
    if (e.key !== "Escape") return;
    setEditing(false);
    if (editStart) editStart.focus();
  });
  // 보기 상태의 체크: TaskItem은 콜백만 부르고 문서는 바꾸지 않는다. 체크 상자가 속한 항목을 찾아 직접 바꾼다.
  root.addEventListener("change", (e) => {
    if (ed.isEditable || e.target.type !== "checkbox") return;
    touch();
    const $pos = ed.state.doc.resolve(ed.view.posAtDOM(e.target.closest("li"), 0));
    for (let d = $pos.depth; d > 0; d--) {
      if ($pos.node(d).type.name !== "taskItem") continue;
      ed.view.dispatch(ed.state.tr.setNodeMarkup($pos.before(d), undefined, { ...$pos.node(d).attrs, checked: e.target.checked }));
      return;
    }
  });

  // ---------- 도구 막대 ----------
  const cmds = {
    h1: (c) => c.toggleHeading({ level: 1 }),
    h2: (c) => c.toggleHeading({ level: 2 }),
    h3: (c) => c.toggleHeading({ level: 3 }),
    bold: (c) => c.toggleBold(),
    bullet: (c) => c.toggleBulletList(),
    ordered: (c) => c.toggleOrderedList(),
    task: (c) => c.toggleTaskList(),
    quote: (c) => c.toggleBlockquote(),
    code: (c) => c.toggleCodeBlock(),
    table: (c) => c.insertTable({ rows: 3, cols: 3, withHeaderRow: true }),
    "row+": (c) => c.addRowAfter(),
    "col+": (c) => c.addColumnAfter(),
    "row-": (c) => c.deleteRow(),
    "col-": (c) => c.deleteColumn(),
    "table-": (c) => c.deleteTable(),
    undo: (c) => c.undo(),
    redo: (c) => c.redo(),
    unlink: (c) => c.extendMarkRange("link").unsetLink(),
  };
  const active = {
    h1: () => ed.isActive("heading", { level: 1 }),
    h2: () => ed.isActive("heading", { level: 2 }),
    h3: () => ed.isActive("heading", { level: 3 }),
    bold: () => ed.isActive("bold"),
    bullet: () => ed.isActive("bulletList"),
    ordered: () => ed.isActive("orderedList"),
    task: () => ed.isActive("taskList"),
    quote: () => ed.isActive("blockquote"),
    code: () => ed.isActive("codeBlock"),
    link: () => ed.isActive("link"),
  };

  function editLink() {
    const prev = ed.getAttributes("link").href || "";
    const input = window.prompt("링크 주소(https://… 또는 /docs/번호). 비우면 링크를 지웁니다.", prev);
    if (input === null) return;
    const href = input.trim();
    const chain = ed.chain().focus().extendMarkRange("link");
    if (!href) { chain.unsetLink().run(); return; }
    if (!safeUrl(href)) { window.alert("https://, mailto: 또는 /로 시작하는 주소만 넣을 수 있습니다."); return; }
    if (ed.state.selection.empty && !ed.isActive("link")) {
      chain.insertContent({ type: "text", text: href, marks: [{ type: "link", attrs: { href } }] }).run();
    } else {
      chain.setLink({ href }).run();
    }
  }

  for (const el of [bar, linkBar]) {
    el.addEventListener("mousedown", (e) => { if (!e.target.closest("a")) e.preventDefault(); }); // 포커스·모바일 키보드 유지
    el.addEventListener("click", (e) => {
      const b = e.target.closest("[data-cmd]");
      if (!b) return;
      const cmd = b.dataset.cmd;
      if (cmd === "done") { setEditing(false); if (editStart) editStart.focus(); return; }
      touch();
      if (cmd === "link") editLink();
      else cmds[cmd](ed.chain().focus()).run();
    });
  }
  hrefEl.addEventListener("click", (e) => {
    e.preventDefault();
    const href = hrefEl.getAttribute("href");
    if (safeUrl(href)) go(href);
  });

  function syncBar() {
    if (!ed.isEditable) return;
    for (const b of bar.querySelectorAll("[data-cmd]")) {
      const f = active[b.dataset.cmd];
      if (f) b.setAttribute("aria-pressed", String(f()));
    }
    tableBar.hidden = !ed.isActive("table");
    const href = ed.isActive("link") ? ed.getAttributes("link").href : "";
    linkBar.hidden = !href;
    if (href) { hrefEl.textContent = href; hrefEl.setAttribute("href", href); }
  }

  // 모바일: 도구 막대를 화면 키보드 바로 위에 붙인다(visualViewport가 키보드만큼 줄어든다).
  const vv = window.visualViewport;
  function dock() {
    const kb = vv ? Math.max(0, window.innerHeight - vv.height - vv.offsetTop) : 0;
    bar.style.setProperty("--tt-kb", kb + "px");
  }
  if (vv) { vv.addEventListener("resize", dock); vv.addEventListener("scroll", dock); }

  root.dataset.ready = "1";
  window.udallyEditor = ed; // 콘솔·브라우저 시험용
}
