// 번들 회귀 검사: node tools/tiptap-bundle/check.mjs  (npm install 뒤. happy-dom으로 DOM을 흉내 낸다)
// core/web/test_md_field.py가 node와 happy-dom이 있으면 함께 돌린다.
// H1: 다른 문단을 고쳐도 코드(물결표 펜스·들여쓴 코드)와 HTML 원문의 내용이 그대로인지
// M2: 주소 검사(역슬래시·제어문자 우회, 그림은 http(s)·같은 사이트만)
// M3: 예전 영상 문법은 새 탭 링크로 보이고 md는 그대로인지
import assert from "node:assert/strict";
import { Window } from "happy-dom";

const win = new Window({ url: "https://udally.example/" });
for (const k of ["window", "document", "navigator", "location", "Node", "HTMLElement", "Element", "DocumentFragment", "MutationObserver", "getComputedStyle", "requestAnimationFrame"]) {
  if (!(k in globalThis) || k === "location") Object.defineProperty(globalThis, k, { value: k === "window" ? win : win[k], configurable: true, writable: true });
}
const T = await import(new URL("../../core/web/static/vendor/tiptap.bundle.js", import.meta.url).href);

function open(md) {
  const el = document.createElement("div");
  document.body.append(el);
  const ed = new T.Editor({ element: el, extensions: T.extensions(), content: T.preprocess(md), contentType: "markdown" });
  T.setupMarkdown(ed);
  return { ed, el };
}
// 맨 앞 문단 끝에 한 글자를 넣고 저장 md를 돌려준다
function editFirstParagraph(md) {
  const { ed } = open(md);
  ed.commands.setTextSelection(1 + ed.state.doc.firstChild.content.size);
  ed.commands.insertContent("!");
  return ed.getMarkdown();
}

// ---- H1 ----
const cases = [
  ["물결표 펜스", "앞 문단\n\n~~~text\n~3000 ~a~ \\~\n~~~\n", "~3000 ~a~ \\~"],
  ["들여쓴 코드", "앞 문단\n\n    ~3000 ~a~\n", "~3000 ~a~"],
  ["HTML 원문", "앞 문단\n\n<aside>~3000 ~a~</aside>\n", "<aside>~3000 ~a~</aside>"],
];
for (const [name, md, body] of cases) {
  const out = editFirstParagraph(md);
  assert.ok(out.startsWith("앞 문단!"), name + ": 편집 반영 " + JSON.stringify(out));
  assert.ok(out.includes(body), name + ": 원문 보존 " + JSON.stringify(out));
  assert.ok(!/\\~3000/.test(out), name + ": 역슬래시 추가 없음");
}
// 일반 글의 홑물결은 취소선이 아니다(예전 보기와 같음), ~~는 취소선
{
  const { ed, el } = open("약 ~3000원 ~5000원, ~~지움~~");
  assert.equal(el.querySelectorAll("s, del").length, 1);
  assert.equal(el.querySelector("s, del").textContent, "지움");
  assert.ok(ed.getMarkdown().includes("~3000원 ~5000원"));
}

// ---- M2 ----
const ok = ["https://a.example/x", "http://a.example", "mailto:a@b.example", "/docs/3", "/tasks/1?x=1#y"];
const bad = ["/\\evil.example/p", "//evil.example", "/\tevil", "java\nscript:alert(1)", "javascript:alert(1)", "data:text/html,x", "docs/3", "https:/x", " /\\x"];
for (const u of ok) assert.equal(T.safeUrl(u), u, "허용 " + u);
for (const u of bad) assert.equal(T.safeUrl(u), null, "거부 " + JSON.stringify(u));
assert.equal(T.safeUrl("mailto:a@b.example", { image: true }), null);
assert.equal(T.safeUrl("https://a.example/i.png", { image: true }), "https://a.example/i.png");
{
  const { el } = open("[x](/\\evil.example/p) ![a](javascript:alert(1)) ![b](data:image/svg+xml,%3Csvg%3E) ![c](/media/a.png)");
  assert.ok(![...el.querySelectorAll("a")].some((a) => a.getAttribute("href")?.includes("evil")), "역슬래시 링크 막힘");
  const srcs = [...el.querySelectorAll("img")].map((i) => i.getAttribute("src"));
  assert.deepEqual(srcs, ["/media/a.png"], "위험한 그림 src 없음");
  assert.equal(el.querySelectorAll(".md-img-blocked").length, 2);
}

// ---- M3 ----
{
  const md = "![회의 영상](https://youtu.be/dQw4w9WgXcQ)\n\n![](https://cdn.example/a.mp4)\n";
  const { ed, el } = open(md);
  const links = [...el.querySelectorAll("a.md-video")];
  assert.equal(links.length, 2);
  assert.equal(links[0].getAttribute("href"), "https://youtu.be/dQw4w9WgXcQ");
  assert.equal(links[0].getAttribute("target"), "_blank");
  assert.equal(links[0].textContent, "회의 영상");
  assert.equal(el.querySelectorAll("img, iframe").length, 0);
  assert.equal(ed.getMarkdown().trim(), md.trim(), "영상 md 그대로");
}

console.log("tiptap bundle check OK");
process.exit(0);
