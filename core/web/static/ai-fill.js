// AI 자동완성 공통 부품(IMPL-PLAN-12 §7.1·§7.3·§7.4). 서버 조각은 web/templates/assist/*.html.
// 마크업
//   칸   [data-ai="칸 키"][data-ai-target="종류:id"]  → 칸 안 오른쪽 끝(긴 글은 오른쪽 위)에 반짝이 아이콘 버튼(템플릿이 {% if ai_on %} 안에서만 단다).
//        data-ai-target-from="종류:폼 칸 이름"         → 그 칸(예: 프로젝트 select)에 값이 있으면 그것을 대상으로 쓴다.
//   모드 button[data-ai-mode="doc.fill" 등][data-ai-target][data-ai-title]  (+ data-ai-select="#템플릿 select") → 대화상자
// 칸은 대화상자 없이 그 자리에서 진행한다(아이콘이 스피너, 다시 누르면 취소). 결과 반영:
//   저장 버튼으로 저장하는 폼 칸  → 칸에 바로 채우고 [되돌리기](한 줄 후보가 여럿이면 ‹ ›)
//   자동 저장 칸(data-autosave·hx-trigger·data-note-field) → 칸 아래 미리보기 [적용]·[뒤에 붙이기]·[버리기]
//   체크 항목(list)               → 칸 아래 고르기 목록 [고른 항목 추가]
// 결과는 글로만 넣는다. 칸은 값을 넣고 input·change를 쏴 기존 저장 경로가 맡는다.
// 민감 칸(비밀번호·키·토큰·코드·확인 입력)에는 data-ai가 있어도 버튼을 붙이지 않는다(두 번째 관문).
const dlg = document.getElementById("ai-dlg");
const body = dlg?.querySelector("#ai-dlg-body");
const title = dlg?.querySelector("#ai-dlg-title");
const SENSITIVE = /key|token|secret|code|confirm/i;
const LABEL = "AI로 쓰기"; // COPY:ai_write (칸 안 아이콘 버튼의 aria-label·title)
const LABEL_CANCEL = "AI 자동완성 취소"; // COPY:ai_autocomplete_cancel
// 반짝이(장식 아님: 이 버튼이 AI 자동완성이라는 표시). 색은 currentColor
const SPARK = '<svg class="ai-ico" viewBox="0 0 16 16" width="16" height="16" aria-hidden="true" focusable="false"><path fill="currentColor" d="M6.5 1.5 7.7 5a2 2 0 0 0 1.3 1.3l3.5 1.2-3.5 1.2A2 2 0 0 0 7.7 10l-1.2 3.5L5.3 10A2 2 0 0 0 4 8.7L.5 7.5 4 6.3A2 2 0 0 0 5.3 5zM13 .5l.5 1.5L15 2.5l-1.5.5L13 4.5 12.5 3 11 2.5l1.5-.5zM13 10.5l.4 1.1 1.1.4-1.1.4-.4 1.1-.4-1.1-1.1-.4 1.1-.4z"/></svg>';
const SPIN = '<svg class="ai-spin" viewBox="0 0 16 16" width="16" height="16" aria-hidden="true" focusable="false"><circle cx="8" cy="8" r="6" fill="none" stroke="currentColor" stroke-width="2" stroke-dasharray="26 12" stroke-linecap="round"/></svg>';
let cur = null; // 대화상자 모드 요청 {el, field, target, options, opener}

const sensitive = (el) => el.type === "password" || /password/i.test(el.autocomplete || "") || SENSITIVE.test(el.name || "");
const autosaves = (el) => el.hasAttribute("data-autosave") || el.hasAttribute("hx-trigger") || el.hasAttribute("data-note-field");
const isList = (el) => el.dataset.ai === "task.checklist"; // ponytail: list 칸이 하나뿐이라 키로 본다

function labelOf(el) {
  const l = el.labels?.[0];
  const text = el.getAttribute("aria-label") || (l && [...l.childNodes].filter((n) => n.nodeType === 3).map((n) => n.textContent).join(" ").trim());
  return text || el.placeholder || "";
}

function targetOf(el) {
  const [kind, name] = (el.dataset.aiTargetFrom || "").split(":");
  const v = name && el.form?.elements[name]?.value;
  return v ? `${kind}:${v}` : el.dataset.aiTarget || "";
}

function esc(s) {
  const d = document.createElement("div");
  d.textContent = s;
  return d.innerHTML;
}

// ---------- 칸 안 아이콘 ----------

function attach(root) {
  const found = [...(root.querySelectorAll?.("[data-ai]") || [])];
  if (root.matches?.("[data-ai]")) found.push(root);
  for (const el of found) {
    if (el.dataset.aiReady || sensitive(el)) continue;
    el.dataset.aiReady = "1";
    const b = document.createElement("button");
    b.type = "button";
    b.className = "ai-spark";
    b.innerHTML = SPARK;
    b.title = LABEL;
    b.setAttribute("aria-label", `${labelOf(el)} ${LABEL}`.trim());
    const panel = document.createElement("div");
    panel.className = "ai-inline";
    panel.setAttribute("aria-live", "polite");
    const st = { el, b, panel, job: null, cancel: false };
    panel._ai = st;
    b.addEventListener("click", () => (b.classList.contains("busy") ? stop(st) : start(st)));
    if (el.matches("[data-md]")) {
      // 마크다운 칸: 편집기(.mdf, position:relative)가 붙은 뒤 그 안 오른쪽 위에 둔다
      const place = (n) => {
        const box = el.nextElementSibling?.classList.contains("mdf") ? el.nextElementSibling : null;
        if (box) { box.classList.add("ai-has"); box.append(b); (el.closest(".md-field") || box).after(panel); }
        else if (n < 20) requestAnimationFrame(() => place(n + 1));
      };
      place(0);
    } else {
      const wrap = document.createElement("span");
      wrap.className = el.tagName === "TEXTAREA" ? "ai-wrap tall" : "ai-wrap";
      el.before(wrap);
      wrap.append(el, b);
      el.classList.add("ai-has");
      // 체크 항목 고르기는 폼(체크 상자)을 담으므로 바깥 폼 뒤에 둔다(폼 안 폼 금지)
      (isList(el) && el.form ? el.form : wrap).after(panel);
    }
  }
  for (const m of root.querySelectorAll?.("[data-ai-mode]") || []) {
    if (!m.querySelector(".ai-ico")) m.insertAdjacentHTML("afterbegin", SPARK);
  }
}

function busy(st, on) {
  st.b.classList.toggle("busy", on);
  st.b.innerHTML = on ? SPIN : SPARK;
  st.b.title = on ? LABEL_CANCEL : LABEL;
  st.b.setAttribute("aria-label", `${labelOf(st.el)} ${on ? LABEL_CANCEL : LABEL}`.trim());
}

function start(st) {
  st.job = null;
  st.cancel = false;
  st.prev = st.el.value;
  busy(st, true);
  st.panel.innerHTML = "";
  htmx.ajax("POST", dlg.dataset.url, {
    source: dlg, target: st.panel, swap: "innerHTML",
    values: { field: st.el.dataset.ai, target: targetOf(st.el), input: st.el.value, options: "{}" },
  });
}

function stop(st) {
  const active = st.panel.querySelector("[data-ai-active]");
  if (active) htmx.ajax("POST", active.dataset.aiActive, { source: dlg, swap: "none" });
  else st.cancel = true; // 요청이 아직 안 돌아왔다 — 돌아오면 취소
  st.panel.innerHTML = '<p class="sr-only">AI 자동완성을 취소했습니다.</p>'; // COPY:ai_cancelled
  busy(st, false);
}

// 서버 조각이 패널에 들어올 때마다(폴링 포함)
function onFragment(st) {
  const p = st.panel;
  const active = p.querySelector("[data-ai-active]");
  if (active) {
    if (st.cancel) stop(st);
    return;
  }
  if (st.cancel) { p.innerHTML = ""; return; } // 취소한 뒤 늦게 온 결과는 버린다
  if (!st.b.classList.contains("busy")) return; // 이미 처리했다
  busy(st, false);
  const opts = [...p.querySelectorAll("[data-ai-value]")].map((x) => x.dataset.aiValue);
  const text = p.querySelector("[data-ai-result]")?.value;
  if (p.querySelector("form[data-ai-done]")) {
    p.querySelector(".row")?.insertAdjacentHTML("beforeend", '<button type="button" class="btn" data-ai-drop>버리기</button>'); // COPY:ai_discard
    return;
  }
  if (!opts.length && text == null) return; // 오류·빈 결과는 조각 그대로([다시 쓰기]·[버리기])
  st.src = p.querySelector("[data-ai-source]")?.textContent.trim() || ""; // 패널을 다시 그려도 "사용한 AI" 줄을 남긴다
  st.opts = opts.length ? opts : [text];
  st.i = 0;
  st.text = !opts.length;
  if (autosaves(st.el)) preview(st);
  else {
    put(st.el, st.opts[0]);
    filled(st);
  }
}

// 저장 전 폼 칸: 이미 채웠다. 되돌리기 + 후보 넘기기
function filled(st) {
  const n = st.opts.length;
  st.panel.innerHTML = `<div class="ai-bar t13"><span class="sr-only">AI가 칸을 채웠습니다. 내용을 확인한 뒤 저장해 주세요.</span>${
    n > 1 ? `<button type="button" class="btn link" data-ai-step="-1" aria-label="이전 후보">‹</button><span>${st.i + 1}/${n}</span><button type="button" class="btn link" data-ai-step="1" aria-label="다음 후보">›</button>` : ""
  }<button type="button" class="btn link" data-ai-undo>되돌리기</button>${srcLine(st)}</div>`; // COPY:ai_filled·ai_undo
}

// 자동 저장 칸: 적용 전엔 저장하지 않는다
function preview(st) {
  const n = st.opts.length;
  const v = st.opts[st.i];
  const shown = st.text
    ? `<textarea class="textarea" rows="5" readonly aria-label="AI가 쓴 글 미리보기">${esc(v)}</textarea>`
    : `<p class="ai-preview">${esc(v)}</p>`;
  st.panel.innerHTML = `<div class="ai-bar t13 stack"><span class="sr-only">${st.text ? "AI 결과 미리보기입니다. [적용] 또는 [뒤에 붙이기]를 눌러야 저장됩니다." : "AI 결과 미리보기입니다. [적용]을 눌러야 저장됩니다."}</span>${shown}<div class="row">${
    n > 1 ? `<button type="button" class="btn link" data-ai-step="-1" aria-label="이전 후보">‹</button><span>${st.i + 1}/${n}</span><button type="button" class="btn link" data-ai-step="1" aria-label="다음 후보">›</button>` : ""
  }<button type="button" class="btn sm primary" data-ai-use="replace">적용</button>${
    st.text ? '<button type="button" class="btn sm" data-ai-use="append">뒤에 붙이기</button>' : ""
  }<button type="button" class="btn sm" data-ai-drop>버리기</button></div>${srcLine(st)}</div>`; // COPY:ai_preview·ai_apply·ai_append·ai_discard
}

const srcLine = (st) => (st.src ? `<span class="ai-src t12">${esc(st.src)}</span>` : "");

function inlineClick(e) {
  const p = e.target.closest(".ai-inline");
  const b = e.target.closest("button");
  if (!p || !b || !p._ai) return;
  const st = p._ai;
  if (b.hasAttribute("data-ai-retry")) start(st);
  else if (b.hasAttribute("data-ai-drop")) p.innerHTML = "";
  else if (b.hasAttribute("data-ai-undo")) {
    put(st.el, st.prev);
    p.innerHTML = "";
    st.el.focus();
  } else if (b.dataset.aiStep) {
    st.i = (st.i + Number(b.dataset.aiStep) + st.opts.length) % st.opts.length;
    if (autosaves(st.el)) preview(st);
    else {
      put(st.el, st.opts[st.i]);
      filled(st);
    }
    p.querySelector(`[data-ai-step="${b.dataset.aiStep}"]`)?.focus();
  } else if (b.dataset.aiUse) {
    const v = st.opts[st.i];
    const old = st.el.value.trim();
    put(st.el, b.dataset.aiUse === "append" && old ? `${old}\n\n${v}` : v);
    p.innerHTML = "";
  }
}

// ---------- 대화상자(문서·회의록·후보 뽑기 모드) ----------

function open(req, heading) {
  cur = req;
  title.textContent = heading;
  body.innerHTML = '<p role="status">AI에 요청을 보내는 중입니다.</p>'; // COPY:ai_sending
  if (!dlg.open) dlg.showModal();
  send();
}

function send() {
  const { el, field, options } = cur;
  const target = cur.target || targetOf(el);
  htmx.ajax("POST", dlg.dataset.url, {
    source: dlg, target: body, swap: "innerHTML",
    values: { field, target, input: el ? el.value : "", options: JSON.stringify(options || {}) },
  });
}

function close() {
  if (dlg.open) dlg.close();
}

// 칸에 넣기: 마크다운 칸은 편집기(_mdSet)로, 나머지는 값 + input·change(자동 저장·필수 검사가 그대로 돈다)
function put(el, value) {
  if (el._mdSet) return el._mdSet(value);
  el.value = value;
  el.dispatchEvent(new Event("input", { bubbles: true }));
  el.dispatchEvent(new Event("change", { bubbles: true }));
}

async function apply(url, mode) {
  const root = document.querySelector(".md-editor");
  if (root?._flush && !(await root._flush())) {
    body.insertAdjacentHTML("afterbegin", '<p class="error" role="alert"><span aria-hidden="true">⚠</span> 본문을 저장하지 못해 AI 결과를 적용하지 않았습니다. 저장 상태를 확인한 뒤 다시 적용해 주세요.</p>'); // COPY:ai_apply_unsaved
    return;
  }
  htmx.ajax("POST", url, { source: dlg, target: body, swap: "innerHTML", values: { version: root?.dataset.version || "", mode: mode || "replace" } });
}

if (dlg) {
  attach(document);
  document.addEventListener("htmx:load", (e) => {
    attach(e.target);
    const p = e.target.closest?.(".ai-inline");
    if (p?._ai) onFragment(p._ai);
  });
  document.addEventListener("click", inlineClick);

  document.addEventListener("click", (e) => {
    const m = e.target.closest("[data-ai-mode]");
    if (!m || m.disabled) return;
    const sel = m.dataset.aiSelect && document.querySelector(m.dataset.aiSelect);
    if (sel && !sel.value) { sel.focus(); return; }
    m.closest("details")?.removeAttribute("open");
    open({ el: null, field: m.dataset.aiMode, target: m.dataset.aiTarget, options: sel ? { template_id: Number(sel.value) } : {}, opener: m },
      m.dataset.aiTitle || m.textContent.trim());
  });

  dlg.addEventListener("click", (e) => {
    if (e.target === dlg) return close(); // 바깥 누르기
    const b = e.target.closest("button");
    if (!b) return;
    if (b.hasAttribute("data-ai-close")) close();
    else if (b.hasAttribute("data-ai-retry")) open(cur, title.textContent);
    else if (b.dataset.aiApply) apply(b.dataset.aiApply, b.dataset.aiHow);
    else if (b.hasAttribute("data-ai-drop")) close();
  });

  // 대화상자·칸 아래 패널 안의 거절 응답(400·403·409·429)도 그린다. 그 밖의 오류는 한 줄로 바꾼다(전체 오류 페이지를 넣지 않는다).
  document.body.addEventListener("htmx:beforeSwap", (e) => {
    const s = e.detail.xhr.status;
    const t = e.detail.target;
    if (s < 400 || !(dlg.contains(t) || t?.closest?.(".ai-inline"))) return;
    if (![400, 403, 409, 429].includes(s)) e.detail.serverResponse = '<p class="error" role="alert" id="ai-job"><span aria-hidden="true">⚠</span> 요청을 처리하지 못했습니다. 잠시 후 다시 시도해 주세요.</p>'; // COPY:ai_err_unknown
    e.detail.shouldSwap = true;
    e.detail.isError = false;
  });
  // 체크 항목 [고른 항목 추가]는 #checklist를 바꾸고 대화상자·패널을 닫는다
  document.body.addEventListener("htmx:afterRequest", (e) => {
    const f = e.detail.elt;
    if (!e.detail.successful || !f.matches?.("[data-ai-done]")) return;
    if (dlg.contains(f)) close();
    const p = f.closest(".ai-inline");
    if (p) p.innerHTML = "";
  });

  // Esc는 이 대화상자만 닫는다(app.js가 패널까지 닫지 않게)
  dlg.addEventListener("keydown", (e) => { if (e.key === "Escape") e.stopPropagation(); });
  // 닫을 때 진행 중인 작업은 취소하고 조각을 비운다(폴링도 멈춘다). 초점은 연 버튼으로.
  dlg.addEventListener("close", () => {
    const active = body.querySelector("[data-ai-active]");
    if (active) htmx.ajax("POST", active.dataset.aiActive, { source: dlg, swap: "none" });
    body.innerHTML = "";
    if (cur?.opener?.isConnected) cur.opener.focus();
  });
}
