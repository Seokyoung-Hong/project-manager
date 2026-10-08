// Tiptap 시험 편집기 — 문서 화면에서 ?editor=tiptap일 때만 붙는다. 정식 편집기는 notes.js다.
// 저장 규칙은 notes.js와 같다: 입력이 멈추고 800ms 뒤 저장, 요청은 하나씩, 응답의
// X-Note-Version을 다음 요청이 이어 쓴다, 409(충돌)면 저장을 멈추고 알린다.
// 한글 IME: 조합 중에는 저장(getMarkdown)을 미루고, 본문을 다시 그리지 않는다(setContent는 처음 한 번뿐).
const root = document.getElementById("doc-tiptap");
if (root) start(root);

let safeUrl; // 번들의 safeUrl(notes.js와 같은 규칙)

// /docs/N 링크를 따라가도 시험 화면에 남게 한다(서버 doc_home이 editor 값을 넘겨준다).
function keepMode(href) {
  const u = new URL(href, location.href);
  if (u.origin === location.origin && (u.searchParams.has("doc") || /^\/docs\/\d+$/.test(u.pathname))) {
    u.searchParams.set("editor", "tiptap");
  }
  return u.href;
}

async function start(root) {
  const T = await import(root.dataset.bundle);
  const scope = root.closest(".card");
  const src = scope.querySelector("#doc-src");
  const bar = scope.querySelector(".tt-bar");
  const tableBar = bar.querySelector(".tt-table");
  const linkBar = scope.querySelector(".tt-linkbar");
  const hrefEl = linkBar.querySelector(".tt-href");
  const statusEl = scope.querySelector("#note-status");
  const conflictEl = scope.querySelector("#note-conflict");
  const titleEl = scope.querySelector('[data-note-field="title"]');
  const csrf = scope.querySelector("[name=csrfmiddlewaretoken]").value;

  document.querySelectorAll('#doc-list a[href*="doc="], .doc-path a').forEach((a) => { a.href = keepMode(a.href); });

  let version = Number(root.dataset.version);
  let dead = false, timer = null, bodyDirty = false, worker = null, seq = 0, navigating = false;
  const pending = Object.create(null);
  const saved = { title: titleEl ? titleEl.value : "" };

  safeUrl = T.safeUrl;
  // 확장 구성·md 보정은 번들(tools/tiptap-bundle/entry.js) 한곳에 있다.
  const editor = new T.Editor({
    element: root,
    editable: false,
    extensions: T.extensions({ placeholder: "여기에 씁니다." }),
    content: T.preprocess(src.value),
    contentType: "markdown",
    onUpdate: () => { if (touched) schedule(); },
    onTransaction: syncBar,
  });
  T.setupMarkdown(editor);
  const dom = editor.view.dom;
  dom.setAttribute("aria-label", "문서 본문");
  // 열기만으로는 절대 저장하지 않는다: (1) 사용자의 실제 입력·조작이 있어야 하고(touched),
  // (2) 저장 직전 md가 마지막 기준(불러온 직후 또는 마지막 저장)과 달라야 한다(baseline).
  let touched = false;
  let baseline = editor.getMarkdown();
  const touch = () => { touched = true; };
  for (const ev of ["beforeinput", "paste", "drop", "compositionstart"]) dom.addEventListener(ev, touch);
  dom.addEventListener("keydown", (e) => { if (e.ctrlKey || e.metaKey || e.key.length === 1 || /^(Enter|Backspace|Delete|Tab)$/.test(e.key)) touch(); });
  // 조합이 끝나면 그때 저장을 예약한다. 조합 중 onUpdate가 와도 schedule이 타이머를 걸지 않는다.
  dom.addEventListener("compositionend", () => { if (bodyDirty) schedule(); });

  // ---------- 저장(notes.js와 같은 큐) ----------
  function flash(text, state) {
    if (!statusEl) return;
    statusEl.textContent = text;
    statusEl.dataset.state = state || "saved";
  }

  function hasUnsaved() {
    const titleDirty = titleEl && titleEl.value !== saved.title;
    return Boolean(timer || bodyDirty || worker || Object.keys(pending).length || titleDirty);
  }

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
    if (editor.view.composing) { flash("입력 중…", "pending"); return; } // compositionend가 다시 부른다
    flash("저장 대기…", "pending");
    timer = setTimeout(stageBody, 800);
  }

  function stageBody() {
    clearTimeout(timer);
    timer = null;
    if (editor.view.composing) return Promise.resolve(false); // 조합이 끝나면 compositionend → schedule
    if (!bodyDirty) return runQueue();
    bodyDirty = false;
    const md = editor.getMarkdown();
    if (md === baseline) return runQueue(); // 바뀐 내용이 없다(정규화·커서 이동만)
    baseline = md;
    return stage("body_md", md);
  }

  if (titleEl) titleEl.addEventListener("change", () => stage("title", titleEl.value));
  document.addEventListener("visibilitychange", () => { if (document.hidden && bodyDirty) stageBody(); });
  window.addEventListener("beforeunload", (e) => {
    if (navigating || !hasUnsaved()) return;
    e.preventDefault();
    e.returnValue = "";
  });

  async function go(href) {
    await stageBody();
    if (worker) await worker;
    navigating = !hasUnsaved();
    location.assign(keepMode(href));
  }

  // ---------- 보기 ↔ 편집 ----------
  function setEditing(on) {
    editor.setEditable(on);
    bar.hidden = !on;
    root.classList.toggle("editing", on);
    if (!on) { linkBar.hidden = true; stageBody(); }
    dock();
  }

  root.addEventListener("click", (e) => {
    const a = e.target.closest("a[href]");
    if (a) {
      e.preventDefault();
      const href = a.getAttribute("href");
      if (!safeUrl(href)) return;
      if (e.ctrlKey || e.metaKey) window.open(keepMode(href), "_blank", "noopener");
      else if (!editor.isEditable) go(href);
      return; // 편집 중 그냥 클릭: 커서만 놓고 아래 링크 막대에서 연다
    }
    if (!editor.isEditable && !e.target.closest("input")) {
      const at = editor.view.posAtCoords({ left: e.clientX, top: e.clientY });
      setEditing(true);
      editor.chain().focus(at ? at.pos : "end").run();
    }
  });
  dom.addEventListener("keydown", (e) => { if (e.key === "Escape") setEditing(false); });
  // 보기 상태의 체크: TaskItem은 콜백만 부르고 문서는 바꾸지 않는다. 체크 상자가 속한 항목을 찾아 직접 바꾼다.
  root.addEventListener("change", (e) => {
    if (editor.isEditable || e.target.type !== "checkbox") return;
    touch();
    const $pos = editor.state.doc.resolve(editor.view.posAtDOM(e.target.closest("li"), 0));
    for (let d = $pos.depth; d > 0; d--) {
      if ($pos.node(d).type.name !== "taskItem") continue;
      editor.view.dispatch(editor.state.tr.setNodeMarkup($pos.before(d), undefined, { ...$pos.node(d).attrs, checked: e.target.checked }));
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
    h1: () => editor.isActive("heading", { level: 1 }),
    h2: () => editor.isActive("heading", { level: 2 }),
    h3: () => editor.isActive("heading", { level: 3 }),
    bold: () => editor.isActive("bold"),
    bullet: () => editor.isActive("bulletList"),
    ordered: () => editor.isActive("orderedList"),
    task: () => editor.isActive("taskList"),
    code: () => editor.isActive("codeBlock"),
    link: () => editor.isActive("link"),
  };

  function editLink() {
    const prev = editor.getAttributes("link").href || "";
    const input = window.prompt("링크 주소(https://… 또는 /docs/번호). 비우면 링크를 지웁니다.", prev);
    if (input === null) return;
    const href = input.trim();
    const chain = editor.chain().focus().extendMarkRange("link");
    if (!href) { chain.unsetLink().run(); return; }
    if (!safeUrl(href)) { window.alert("https://, mailto: 또는 /로 시작하는 주소만 넣을 수 있습니다."); return; }
    if (editor.state.selection.empty && !editor.isActive("link")) {
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
      if (cmd !== "done") touch();
      if (cmd === "done") setEditing(false);
      else if (cmd === "link") editLink();
      else cmds[cmd](editor.chain().focus()).run();
    });
  }
  hrefEl.addEventListener("click", (e) => {
    e.preventDefault();
    const href = hrefEl.getAttribute("href");
    if (safeUrl(href)) go(href);
  });

  function syncBar() {
    if (!editor.isEditable) return;
    for (const b of bar.querySelectorAll("[data-cmd]")) {
      const f = active[b.dataset.cmd];
      if (f) b.setAttribute("aria-pressed", String(f()));
    }
    tableBar.hidden = !editor.isActive("table");
    const href = editor.isActive("link") ? editor.getAttributes("link").href : "";
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
  window.udallyTiptap = editor; // 시험용: 콘솔에서 확인
}
