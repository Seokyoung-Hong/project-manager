// 문서·회의록 본문 편집기. 서식 줄·보기 렌더는 md-field.js(공용)를 쓰고, 여기는 저장 큐와 보기↔편집만 맡는다.
// 마크업  .mdf > .md-editor[data-url][data-version] > textarea.md-src   (docs/_editor.html)
// 저장 규약: 입력이 멈추고 800ms 뒤 저장, 요청은 하나씩, 응답의 X-Note-Version을 다음 요청이 이어 쓴다,
// 409(충돌)면 저장을 멈추고 알린다. 한글 IME 조합 중에는 저장을 미룬다. 열기만으로는 절대 저장하지 않는다.
// 링크·이미지 주소 검사(safeUrl)와 Markdown 보정은 번들(tools/tiptap-bundle/entry.js) 한곳에 있다.
import { load, toolbar } from "./md-field.js";

function init(root) {
  const found = [...(root.querySelectorAll?.(".md-editor") || [])];
  if (root.matches?.(".md-editor")) found.push(root);
  const todo = found.filter((el) => !el.dataset.ready);
  if (!todo.length) return;
  todo.forEach((el) => { el.dataset.ready = "loading"; });
  load().then((T) => todo.forEach((el) => editor(T, el)));
}
init(document);
document.addEventListener("htmx:load", (e) => init(e.target));

function editor(T, root) {
  const safeUrl = T.safeUrl;
  const scope = root.closest(".card") || document;
  const src = root.querySelector(".md-src");
  const editStart = scope.querySelector(".md-edit-start");
  const statusEl = scope.querySelector("#note-status");
  const conflictEl = scope.querySelector("#note-conflict");
  const fields = [...scope.querySelectorAll("[data-note-field]")];
  const csrf = scope.querySelector("[name=csrfmiddlewaretoken]").value;

  let version = Number(root.dataset.version);
  let destroyed = false, dead = false, timer = null, bodyDirty = false, worker = null, seq = 0, navigating = false;
  const pending = Object.create(null);
  const saved = Object.fromEntries(fields.map((f) => [f.dataset.noteField, f.value]));

  const ed = new T.Editor({
    element: root,
    editable: false,
    extensions: T.extensions({ placeholder: "여기에 씁니다.", checkInView: true, drag: true }),
    editorProps: { attributes: { tabindex: "0" } }, // 보기 상태에서도 탭으로 닿는다(setEditable이 DOM 속성을 다시 써도 남는다)
    content: T.preprocess(src.value),
    contentType: "markdown",
    onUpdate: () => { if (touched) schedule(); },
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
  for (const ev of ["beforeinput", "paste", "drop", "compositionstart"]) dom.addEventListener(ev, touch, true); // 캡처: 편집기가 처리(→ update)하기 전에 표시
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
    if (destroyed) return !hasUnsaved();
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
  const onHidden = () => { if (document.hidden && hasUnsaved()) flushAll(); };
  const onUnload = (e) => {
    if (navigating || !hasUnsaved()) return;
    e.preventDefault();
    e.returnValue = "";
  };
  document.addEventListener("visibilitychange", onHidden);
  window.addEventListener("beforeunload", onUnload);

  // 남은 저장을 모두 마쳤을 때만 true. 실패·409·한글 조합 중이면 false — 부르는 쪽은 화면에 머문다.
  async function settle() {
    const ok = await flushAll();
    if (ok && !hasUnsaved()) return true;
    if (ok && ed.view.composing) flash("입력을 마친 뒤 다시 눌러 주세요. 아직 저장하지 않았습니다.", "pending");
    return false;
  }

  async function go(href) {
    if (!(await settle())) return false;
    navigating = true;
    location.assign(href);
    return true;
  }

  // 회의록 확정처럼 같은 화면의 다른 폼([data-flush-first])은 본문·메타를 모두 저장한 뒤에만 보낸다.
  scope.addEventListener("submit", async (e) => {
    const form = e.target;
    if (!form.matches?.("[data-flush-first]") || e.defaultPrevented) return; // 확인 창에서 취소하면 그대로 멈춘다
    if (!hasUnsaved()) return;
    e.preventDefault();
    const btn = form.querySelector("button");
    if (btn) btn.disabled = true;
    try {
      if (!(await settle())) return;
      navigating = true;
      form.submit();
    } finally {
      if (btn) btn.disabled = false;
    }
  });

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
    if (!m || !safeUrl(m[2], { image: true })) return;
    touch();
    ed.chain().insertContentAt(ed.state.doc.content.size, { type: "image", attrs: { alt: m[1], src: m[2] } }).run();
    flash("본문 끝에 이미지를 넣었습니다.", "pending");
  });

  // ---------- 보기 ↔ 편집 ----------
  function setEditing(on) {
    ed.setEditable(on);
    root.classList.toggle("editing", on);
    if (editStart) editStart.parentElement.hidden = on;
    if (!on) stageBody();
    tb.refresh();
  }
  if (editStart) editStart.addEventListener("click", () => { setEditing(true); ed.commands.focus("end"); });

  root.addEventListener("click", (e) => {
    const a = e.target.closest("a[href]");
    if (a) {
      e.preventDefault();
      const href = a.getAttribute("href");
      if (!safeUrl(href)) return;
      if (a.classList.contains("md-video")) { // 예전 영상 문법: 보기 상태에서는 새 탭으로
        if (!ed.isEditable || e.ctrlKey || e.metaKey) window.open(href, "_blank", "noopener");
        return;
      }
      if (ed.isEditable) return; // 편집 중: Ctrl+클릭은 공용 서식 줄(md-field.js)이 열고, 그냥 클릭은 커서만 놓는다
      if (e.ctrlKey || e.metaKey) window.open(href, "_blank", "noopener");
      else go(href);
      return;
    }
    if (!ed.isEditable && !e.target.closest("input")) {
      const at = ed.view.posAtCoords({ left: e.clientX, top: e.clientY });
      setEditing(true);
      ed.chain().focus(at ? at.pos : "end").run();
    }
  });
  // 좁은 화면은 [본문 편집] 줄을 숨기므로 보기 상태의 본문도 탭으로 닿고(editorProps의 tabindex) Enter·Space로 편집을 시작한다.
  // Esc로 마치면 [본문 편집] 버튼이 보이면 그리로, 숨어 있으면 보기 상태의 본문으로 초점을 돌려 다시 Enter로 들어올 수 있다.
  dom.addEventListener("keydown", (e) => {
    if (!ed.isEditable && (e.key === "Enter" || e.key === " ") && e.target === dom) {
      e.preventDefault();
      setEditing(true);
      ed.commands.focus("end");
      return;
    }
    if (e.key !== "Escape") return;
    setEditing(false);
    if (editStart && editStart.getClientRects().length) editStart.focus();
    else dom.focus();
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

  // ---------- 서식 줄(공용) ----------
  const tb = toolbar(T, ed, root.parentElement, root, { position: "top", touch, openLink: (href) => { if (safeUrl(href)) go(href); } });

  // HTMX가 이 조각을 지울 때(md-field.js의 htmx:beforeCleanupElement): 남은 입력을 보내고 리스너·타이머·편집기를 정리한다.
  root._mdDestroy = () => {
    if (hasUnsaved()) flushAll();
    destroyed = true;
    clearTimeout(timer);
    for (const k in fieldTimers) clearTimeout(fieldTimers[k]);
    document.removeEventListener("visibilitychange", onHidden);
    window.removeEventListener("beforeunload", onUnload);
    tb.destroy();
    ed.destroy();
  };
  root.dataset.ready = "1";
  window.udallyEditor = ed; // 콘솔·브라우저 시험용
}
