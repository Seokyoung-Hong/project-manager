// 유달리 문서 화면의 Tiptap 시험 편집기. 확장 구성과 md 왕복 보정을 여기 한곳에 둔다 —
// 브라우저(doc-tiptap.js)와 왕복 시험(roundtrip.mjs)이 같은 번들을 쓰게 하기 위해서다.
// 보정 근거: docs/review-2026-10-08/W-tiptap-roundtrip.md(운영 문서 81개 왕복 시험)
import { Editor, Mark, Node } from "@tiptap/core";
import StarterKit from "@tiptap/starter-kit";
import CodeBlock from "@tiptap/extension-code-block";
import Link from "@tiptap/extension-link";
import { Markdown } from "@tiptap/markdown";
import { TableKit } from "@tiptap/extension-table";
import { TaskList, TaskItem } from "@tiptap/extension-list";
import Image from "@tiptap/extension-image";
import { Placeholder } from "@tiptap/extensions";
import { Marked } from "marked";
import { DragHandle } from "@tiptap/extension-drag-handle";
import { NodeSelection, TextSelection } from "@tiptap/pm/state";

export { Editor };

// 주소 검사. 브라우저가 해석하는 대로(new URL) 보고 판단한다 — 정규식만 보면 /\evil.example 같은 주소가
// "같은 사이트 경로"로 통과하지만 브라우저는 http://evil.example로 연다.
// 링크: http(s)·mailto·같은 사이트 경로. 그림(image: true): http(s)·같은 사이트 경로만.
// 역슬래시·제어문자·공백이 든 주소는 해석이 브라우저마다 달라 받지 않는다. 통과하면 원래 문자열(앞뒤 공백만 뺀)을 돌려준다.
const HERE = globalThis.location?.origin && globalThis.location.origin !== "null" ? globalThis.location.origin : "https://udally.invalid";
export function safeUrl(u, { image = false } = {}) {
  u = (u || "").trim();
  if (!u || /[\\\s\u0000-\u001f\u007f]/.test(u)) return null;
  let url;
  try { url = new URL(u, HERE); } catch { return null; }
  if (u.startsWith("/")) return !u.startsWith("//") && url.origin === HERE ? u : null;
  if (!/^[a-z][a-z0-9+.-]*:/i.test(u)) return null; // 상대 주소(docs/3, ./a)는 받지 않는다
  if (url.protocol === "http:" || url.protocol === "https:") return /^https?:\/\/[^/]/i.test(u) ? u : null;
  if (!image && url.protocol === "mailto:") return u;
  return null;
}

// 예전 문서의 영상 문법 ![제목](YouTube·Vimeo·영상 파일). iframe은 되살리지 않고 새 탭으로 여는 링크로 보인다(md는 그대로).
const VIDEO = /(?:youtube\.com\/(?:watch\?|shorts\/|embed\/)|youtu\.be\/|vimeo\.com\/|\.(?:mp4|webm|ogv|ogg|mov|m4v)(?:[?#]|$))/i;
const SafeImage = Image.extend({
  parseHTML() {
    return [{ tag: "img[src]", getAttrs: (el) => (safeUrl(el.getAttribute("src"), { image: true }) ? null : false) }]; // 붙여넣기: 위험한 그림은 버린다
  },
  renderHTML({ node, HTMLAttributes }) {
    const src = node.attrs.src || "", alt = node.attrs.alt || "";
    if (VIDEO.test(src) && safeUrl(src, { image: true })) {
      return ["a", { href: src, class: "md-video", target: "_blank", rel: "noopener noreferrer nofollow", title: src }, alt || "영상 보기"];
    }
    // 불러온 md의 위험한 그림 주소는 불러오지 않고 글자로만 보인다(저장 md는 그대로)
    if (!safeUrl(src, { image: true })) return ["span", { class: "md-img-blocked", title: "열 수 없는 그림 주소" }, alt || "그림"];
    return ["img", HTMLAttributes];
  },
});

// (5) 홑물결 ~는 marked(GFM)가 취소선으로 읽는다(예전 보기 화면은 ~~만 취소선). 원문을 고치지 않고 토큰 규칙에서 막는다 —
// 그러면 코드(펜스·들여쓰기)와 HTML 원문은 손대지 않는다. ~~는 원래 규칙(false → 기본 처리)으로 넘긴다.
const marked = new Marked({ gfm: true });
marked.use({ tokenizer: { del: (src) => (/^~(?!~)/.test(src) ? undefined : false) } });

// (1) 목록 안 들여쓴 ``` 코드 블록이 사라지는 문제: 원본은 raw.startsWith('```')만 본다.
const CodeBlockFixed = CodeBlock.extend({
  parseMarkdown: (token, h) => {
    const raw = (token.raw || "").trimStart();
    if (!raw.startsWith("```") && !raw.startsWith("~~~") && token.codeBlockStyle !== "indented") return [];
    return h.createNode("codeBlock", { language: token.lang || null }, token.text ? [h.createTextNode(token.text)] : []);
  },
});

// (2) 맨 URL은 [url](url)로 바꾸지 않고 원래대로 url만 쓴다.
const unesc = (s) => s.replace(/\\([\\`*_[\]~])/g, "$1");
const LinkBare = Link.extend({
  renderMarkdown: (node, h, ctx) => {
    const href = node.attrs?.href ?? "", title = node.attrs?.title ?? "", text = h.renderChildren(node);
    const plain = unesc(ctx?.meta?.markText ?? text);
    // GFM이 다시 링크로 읽는 절대 주소만 맨 URL로 둔다(/docs/3 같은 상대 경로는 [t](u)가 있어야 링크다)
    if (!title && /^(https?:|mailto:)/i.test(href) && (plain === href || "mailto:" + plain === href)) return text;
    return title ? `[${text}](${href} "${title}")` : `[${text}](${href})`;
  },
});

// (3) 블록 HTML(노션 <aside> 등)은 스키마에 없어 태그가 버려진다. 원문 그대로 들고 있다가 그대로 쓴다.
const HtmlBlock = Node.create({
  name: "htmlBlock",
  group: "block",
  atom: true,
  selectable: true,
  addAttributes: () => ({ raw: { default: "" } }),
  parseHTML: () => [{ tag: "pre[data-html-block]", getAttrs: (el) => ({ raw: el.textContent }) }],
  renderHTML: ({ node }) => ["pre", { "data-html-block": "", class: "tt-html", title: "HTML 원문(그대로 보존)" }, node.attrs.raw],
  markdownTokenName: "html",
  parseMarkdown: (token, h) => (token.block ? h.createNode("htmlBlock", { raw: (token.raw || "").replace(/\n+$/, "") }) : []),
  renderMarkdown: (node) => node.attrs.raw,
});

// (6) 문장 속 HTML 태그(<span>, <kbd>, <!-- … -->, CDATA, <?…?>, <!DOCTYPE>)는 기본 처리에서 버려진다.
// 태그 원문을 글자로 두고 "HTML 원문" 표시(mark)를 붙인다 — 글자이므로 링크·굵게 같은 다른 표시가 함께 붙고 그대로 저장된다
// ([<br>](주소), **<br>**, [<kbd>x</kbd>](주소)). 화면에는 실행하지 않고 글자로만 보인다. 코드처럼 이스케이프하지 않는다.
const INLINE_TAG = new RegExp(
  "^(?:<!--[\\s\\S]*?-->|<!\\[CDATA\\[[\\s\\S]*?\\]\\]>|<\\?[\\s\\S]*?\\?>|<![A-Za-z][^>]*>" +
    "|<\\/[A-Za-z][A-Za-z0-9-]*\\s*>" +
    "|<[A-Za-z][A-Za-z0-9-]*(?:\\s+[A-Za-z_:][\\w:.-]*(?:\\s*=\\s*(?:\"[^\"]*\"|'[^']*'|[^\\s\"'=<>`]+))?)*\\s*\\/?>)",
);
const HtmlInline = Mark.create({
  name: "htmlInline",
  code: true, // 저장할 때 이스케이프하지 않는다(setupMarkdown의 codeTypes)
  inclusive: false, // 태그 바로 뒤에 이어 쓰는 글은 원문 표시가 아니다
  parseHTML: () => [{ tag: "span[data-html-inline]" }],
  renderHTML: () => ["span", { "data-html-inline": "", class: "tt-html-inline", title: "HTML 원문(그대로 보존)" }, 0],
  markdownTokenName: "htmlInline",
  markdownTokenizer: {
    name: "htmlInline",
    level: "inline",
    start: (src) => src.search(/<[A-Za-z!/?]/),
    tokenize: (src) => {
      const m = INLINE_TAG.exec(src);
      return m ? { type: "htmlInline", raw: m[0] } : undefined;
    },
  },
  parseMarkdown: (token, h) => h.applyMark("htmlInline", [{ type: "text", text: token.raw }]),
  renderMarkdown: (node, h) => h.renderChildren(node.content),
});

// 블록 손잡이(끌어 옮기기). 칸 왼쪽 여백 안에 선다. 터치 기기에서는 CSS로 숨기고 Alt+↑/↓(md-field.js)를 쓴다.
function dragHandle() {
  return DragHandle.configure({
    render() {
      const el = document.createElement("div");
      el.className = "drag-handle";
      el.title = "끌어서 옮기기 (키보드: Alt+↑/↓)";
      el.setAttribute("aria-hidden", "true");
      el.style.visibility = "hidden"; // 블록 위에 마우스가 올 때까지 숨긴다(플러그인이 처음에는 숨기지 않는다)
      el.innerHTML = '<svg viewBox="0 0 24 24" focusable="false"><circle cx="9" cy="6" r="1.5"/><circle cx="15" cy="6" r="1.5"/><circle cx="9" cy="12" r="1.5"/><circle cx="15" cy="12" r="1.5"/><circle cx="9" cy="18" r="1.5"/><circle cx="15" cy="18" r="1.5"/></svg>';
      return el;
    },
    computePositionConfig: { placement: "left-start", strategy: "absolute" },
    nested: { edgeDetection: "none" }, // 목록 항목도 하나씩 옮긴다(가장자리 근처에서 바깥 목록으로 바뀌지 않게)
  });
}

// 현재 블록(목록 안이면 그 항목)을 위(-1)·아래(+1)로 한 칸 옮긴다. 옮겼으면 true.
// 블록 HTML·그림처럼 통째로 선택된 블록(NodeSelection)은 그 블록을 옮기고 옮긴 뒤에도 선택을 유지한다.
export function moveBlock(editor, dir) {
  const { state } = editor, sel = state.selection;
  let node, start, parent, idx;
  if (sel instanceof NodeSelection && sel.node.isBlock) {
    const $s = state.doc.resolve(sel.from);
    [node, start, parent, idx] = [sel.node, sel.from, $s.parent, $s.index()];
  } else {
    const $f = sel.$from;
    let d = $f.depth;
    while (d > 1 && !/^(listItem|taskItem)$/.test($f.node(d).type.name)) d--;
    if (d < 1) return false;
    [node, start, parent, idx] = [$f.node(d), $f.before(d), $f.node(d - 1), $f.index(d - 1)];
  }
  const j = idx + dir;
  if (j < 0 || j >= parent.childCount) return false;
  const offset = sel.from - start;
  const tr = state.tr.delete(start, start + node.nodeSize);
  const at = dir < 0 ? start - parent.child(j).nodeSize : start + parent.child(j).nodeSize;
  tr.insert(at, node);
  if (sel instanceof NodeSelection) tr.setSelection(NodeSelection.create(tr.doc, at));
  else tr.setSelection(TextSelection.near(tr.doc.resolve(Math.min(at + offset, tr.doc.content.size))));
  editor.view.dispatch(tr.scrollIntoView());
  return true;
}

// checkInView: 보기 상태에서도 체크 상자를 바꿀 수 있게 한다(문서 반영은 doc-tiptap.js). 끄면 읽기 전용 그대로.
// drag: 편집기에만 손잡이를 붙인다(읽기 전용 보기에는 없다).
export function extensions({ placeholder = "", checkInView = false, drag = false } = {}) {
  return [
    ...(drag ? [dragHandle()] : []),
    HtmlInline,
    StarterKit.configure({ codeBlock: false, link: false }),
    CodeBlockFixed,
    LinkBare.configure({
      openOnClick: false,
      autolink: true,
      HTMLAttributes: { target: null, rel: "noopener noreferrer nofollow" },
      isAllowedUri: (u) => Boolean(safeUrl(u)),
    }),
    HtmlBlock,
    Markdown.configure({ marked }),
    TableKit.configure({ table: { resizable: false } }),
    TaskList,
    TaskItem.configure({
      nested: true,
      onReadOnlyChecked: checkInView ? () => true : undefined,
      a11y: { checkboxLabel: (node, checked) => (checked ? "완료: " : "할 일: ") + (node.firstChild?.textContent || "빈 항목") },
    }),
    SafeImage,
    Placeholder.configure({ placeholder }),
  ];
}

// (4) 저장할 때 이스케이프 최소화: 지금 보기 화면(notes.js)은 \_ 와 &gt; 를 풀지 않아 기호가 그대로 보인다.
// 엔티티는 HTML로 오인될 때만, _는 단어 경계에서만, ~는 ~~일 때만, [ ]는 링크로 읽힐 때만.
const minimalEscape = (t) =>
  t
    .replace(/&(?=#?\w+;)/g, "&amp;")
    .replace(/<(?=[A-Za-z/!?])/g, "&lt;")
    .replace(/([\\`*])/g, "\\$1")
    .replace(/\[(?=[^\]]*\]\s*[([:])|\](?=\s*[([:])/g, "\\$&")
    .replace(/~~/g, "\\~\\~")
    .replace(/_/g, (m, i, s) => (/[\p{L}\p{N}]/u.test(s[i - 1] || "") && /[\p{L}\p{N}]/u.test(s[i + 1] || "") ? "_" : "\\_"))
    .replace(/^>/, "\\>");

export function setupMarkdown(editor) {
  const m = editor.storage.markdown.manager;
  m.encodeTextForMarkdown = function (text, node, parent) {
    const inCode = (parent?.type && this.codeTypes.has(parent.type)) ||
      (node.marks || []).some((x) => this.codeTypes.has(typeof x === "string" ? x : x.type));
    return inCode ? text : minimalEscape(text);
  };
}

// 불러올 때: 줄바꿈만 맞춘다. 물결표 보정은 위 marked 규칙(5)이 한다.
export const preprocess = (md) => md.replace(/\r\n/g, "\n");
