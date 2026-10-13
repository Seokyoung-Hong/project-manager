// AI 자동완성 공통 부품(IMPL-PLAN-12 §7.1·§7.3·§7.4). 서버 조각은 web/templates/assist/*.html.
// 마크업
//   칸   [data-ai="칸 키"][data-ai-target="종류:id"]  → 옆에 [AI로 쓰기] 버튼을 붙인다(템플릿이 {% if ai_on %} 안에서만 단다).
//        data-ai-target-from="종류:폼 칸 이름"         → 그 칸(예: 프로젝트 select)에 값이 있으면 그것을 대상으로 쓴다.
//   모드 button[data-ai-mode="doc.fill" 등][data-ai-target][data-ai-title]  (+ data-ai-select="#템플릿 select")
// 결과는 글로만 넣는다. 칸은 값을 넣고 input·change를 쏴 기존 저장 경로(자동 저장·폼 제출)가 맡는다.
// 민감 칸(비밀번호·키·토큰·코드·확인 입력)에는 data-ai가 있어도 버튼을 붙이지 않는다(두 번째 관문).
const dlg = document.getElementById("ai-dlg");
const body = dlg?.querySelector("#ai-dlg-body");
const title = dlg?.querySelector("#ai-dlg-title");
const SENSITIVE = /key|token|secret|code|confirm/i;
let cur = null; // {el, field, target, options, opener}

const sensitive = (el) => el.type === "password" || /password/i.test(el.autocomplete || "") || SENSITIVE.test(el.name || "");

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

function attach(root) {
  const found = [...(root.querySelectorAll?.("[data-ai]") || [])];
  if (root.matches?.("[data-ai]")) found.push(root);
  for (const el of found) {
    if (el.dataset.aiReady || sensitive(el)) continue;
    el.dataset.aiReady = "1";
    const b = document.createElement("button");
    b.type = "button";
    b.className = "btn sm";
    b.textContent = "AI로 쓰기"; // COPY:ai_write
    b.setAttribute("aria-label", `${labelOf(el)} AI로 쓰기`.trim());
    b.addEventListener("click", () => open({ el, field: el.dataset.ai, opener: b }, "AI로 쓰기"));
    // 라벨·마크다운 칸 묶음 뒤에 둔다. 묶음이 없는 마크다운 칸은 편집기(.mdf)가 바로 뒤에 붙으므로 앞에 둔다.
    const host = el.closest(".md-field, label.field");
    if (host) host.after(b);
    else if (el.matches("[data-md]")) el.before(b);
    else el.after(b);
  }
}

function open(req, heading) {
  cur = req;
  title.textContent = heading;
  body.innerHTML = '<p role="status">AI에게 요청을 보내는 중입니다.</p>'; // COPY:ai_sending
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

async function apply(url) {
  const root = document.querySelector(".md-editor");
  if (root?._flush && !(await root._flush())) {
    body.insertAdjacentHTML("afterbegin", '<p class="error" role="alert"><span aria-hidden="true">⚠</span> 본문을 아직 저장하지 못해 적용하지 않았습니다. 저장 상태를 확인한 뒤 다시 눌러 주세요.</p>'); // COPY:ai_apply_unsaved
    return;
  }
  htmx.ajax("POST", url, { source: dlg, target: body, swap: "innerHTML", values: { version: root?.dataset.version || "" } });
}

if (dlg) {
  attach(document);
  document.addEventListener("htmx:load", (e) => attach(e.target));

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
    else if (b.dataset.aiValue != null) { put(cur.el, b.dataset.aiValue); close(); }
    else if (b.dataset.aiUse) {
      const v = body.querySelector("[data-ai-result]").value;
      const old = cur.el.value.trim();
      put(cur.el, b.dataset.aiUse === "append" && old ? `${old}\n\n${v}` : v);
      close();
    } else if (b.dataset.aiApply) apply(b.dataset.aiApply);
  });

  // 대화상자 안의 거절 응답(400·403·409·429)도 그린다. 그 밖의 오류는 한 줄로 바꾼다(전체 오류 페이지를 넣지 않는다).
  document.body.addEventListener("htmx:beforeSwap", (e) => {
    const s = e.detail.xhr.status;
    if (s < 400 || !dlg.contains(e.detail.target)) return;
    if (![400, 403, 409, 429].includes(s)) e.detail.serverResponse = '<p class="error" role="alert" id="ai-job"><span aria-hidden="true">⚠</span> 요청을 처리하지 못했습니다. 대화상자를 닫고 다시 시도해 주세요.</p>'; // COPY:ai_err_unknown
    e.detail.shouldSwap = true;
    e.detail.isError = false;
  });
  // 체크 항목 [고른 항목 추가]는 #checklist를 바꾸고 대화상자를 닫는다
  document.body.addEventListener("htmx:afterRequest", (e) => {
    if (e.detail.successful && e.detail.elt.matches?.("[data-ai-done]") && dlg.contains(e.detail.elt)) close();
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
