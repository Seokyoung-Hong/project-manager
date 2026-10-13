// ai-fill.js 칸 안 AI 자동완성 흐름 검사(가짜 htmx): node tools/tiptap-bundle/check-ai-fill.mjs  (npm install 뒤)
// core/web/test_md_field.py가 node와 happy-dom이 있으면 함께 돌린다.
import assert from "node:assert/strict";
import { readFileSync, writeFileSync } from "node:fs";
import { tmpdir } from "node:os";
import { join } from "node:path";
import { pathToFileURL } from "node:url";
import { Window } from "happy-dom";

const win = new Window({ url: "https://u.example/" });
for (const k of ["window", "document", "Event", "HTMLElement", "requestAnimationFrame"]) globalThis[k] = k === "window" ? win : win[k];
document.body.innerHTML = `
<dialog id="ai-dlg" data-url="/assist/jobs"><h2 id="ai-dlg-title"></h2><div id="ai-dlg-body"></div></dialog>
<form id="f"><label class="field">할 일<input class="input" name="title" data-ai="newtask.title" data-ai-target="project:1"></label><button>만들기</button></form>
<label class="field">다음 행동<input class="input" name="value" data-autosave hx-trigger="change" data-ai="task.next_action" data-ai-target="task:1"></label>
<details><button type="button" data-ai-mode="doc.fill" data-ai-target="doc:1">AI로 본문 채우기</button></details>`;

const calls = [];
const done = (opts) => `<div class="stack" id="ai-job">${opts.map((o) => `<button type="button" class="btn" data-ai-value="${o}">${o}</button>`).join("")}</div>`;
const active = `<div class="stack" id="ai-job" data-ai-active="/assist/jobs/9/cancel"><p role="status">AI가 쓰는 중입니다.</p></div>`;
let next = active;
globalThis.htmx = {
  ajax(verb, url, o) {
    calls.push({ verb, url, values: o.values });
    if (o.target) {
      o.target.innerHTML = next;
      for (const c of o.target.children) c.dispatchEvent(new win.CustomEvent("htmx:load", { bubbles: true }));
    }
  },
};
// ai-fill.js는 type=module 스크립트지만 확장자가 .js라 .mjs로 복사해 불러온다
const copy = join(tmpdir(), "ai-fill-check.mjs");
writeFileSync(copy, readFileSync(new URL("../../core/web/static/ai-fill.js", import.meta.url), "utf8"));
await import(pathToFileURL(copy).href);

const [inp, auto] = document.querySelectorAll("[data-ai]");
const b1 = inp.parentElement.querySelector(".ai-spark");
assert.ok(b1 && inp.parentElement.classList.contains("ai-wrap"), "아이콘이 칸 안에");
assert.equal(b1.getAttribute("aria-label"), "할 일 AI로 쓰기"); // COPY:ai_write
assert.ok(!b1.textContent.trim(), "글자 없는 아이콘 버튼");
assert.ok(document.querySelector("[data-ai-mode] .ai-ico"), "모드 버튼 앞 아이콘");

// 1) 폼 칸: 누르면 스피너 → 결과가 오면 첫 후보로 채움, ‹ ›, 되돌리기
inp.value = "원래";
b1.click();
assert.ok(b1.classList.contains("busy") && b1.querySelector(".ai-spin"), "스피너");
assert.equal(calls[0].values.field, "newtask.title");
const panel1 = inp.closest(".ai-wrap").nextElementSibling;
assert.ok(panel1.classList.contains("ai-inline") && panel1.getAttribute("aria-live") === "polite");
panel1.innerHTML = done(["가", "나", "다"]);
panel1.firstElementChild.dispatchEvent(new win.CustomEvent("htmx:load", { bubbles: true }));
assert.equal(inp.value, "가");
assert.ok(!b1.classList.contains("busy"));
panel1.querySelector('[data-ai-step="1"]').click();
assert.equal(inp.value, "나");
panel1.querySelector("[data-ai-undo]").click();
assert.equal(inp.value, "원래");
assert.equal(panel1.innerHTML, "");

// 2) 다시 눌러 취소
b1.click();
b1.click();
assert.equal(calls.at(-1).url, "/assist/jobs/9/cancel");
assert.ok(!b1.classList.contains("busy"));

// 3) 자동 저장 칸: 미리보기, 적용 전엔 값 그대로, 적용하면 change
let changed = 0;
auto.addEventListener("change", () => changed++);
const b2 = auto.parentElement.querySelector(".ai-spark");
next = done(["하나", "둘"]);
b2.click();
const panel2 = auto.closest(".ai-wrap").nextElementSibling;
assert.equal(auto.value, "");
assert.ok(panel2.querySelector(".ai-preview").textContent === "하나");
panel2.querySelector('[data-ai-step="1"]').click();
panel2.querySelector('[data-ai-use="replace"]').click();
assert.equal(auto.value, "둘");
assert.equal(changed, 1);
b2.click();
panel2.querySelector("[data-ai-drop]").click();
assert.equal(auto.value, "둘");
console.log("ok");
