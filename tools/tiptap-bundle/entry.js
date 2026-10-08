// 유달리 문서 화면의 Tiptap 시험 편집기. 확장 구성과 md 왕복 보정을 여기 한곳에 둔다 —
// 브라우저(doc-tiptap.js)와 왕복 시험(roundtrip.mjs)이 같은 번들을 쓰게 하기 위해서다.
// 보정 근거: docs/review-2026-10-08/W-tiptap-roundtrip.md(운영 문서 81개 왕복 시험)
import { Editor, Node } from "@tiptap/core";
import StarterKit from "@tiptap/starter-kit";
import CodeBlock from "@tiptap/extension-code-block";
import Link from "@tiptap/extension-link";
import { Markdown } from "@tiptap/markdown";
import { TableKit } from "@tiptap/extension-table";
import { TaskList, TaskItem } from "@tiptap/extension-list";
import Image from "@tiptap/extension-image";
import { Placeholder } from "@tiptap/extensions";

export { Editor };

// notes.js의 safeUrl과 같은 규칙: http(s)·mailto·같은 사이트 경로만. //evil.com은 걸러진다.
export function safeUrl(u) {
  u = (u || "").trim();
  if (/^(https?:\/\/|mailto:)/i.test(u)) return u;
  if (/^\/[^/]/.test(u)) return u;
  return null;
}

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

export function extensions({ placeholder = "" } = {}) {
  return [
    StarterKit.configure({ codeBlock: false, link: false }),
    CodeBlockFixed,
    LinkBare.configure({
      openOnClick: false,
      autolink: true,
      HTMLAttributes: { target: null, rel: "noopener noreferrer nofollow" },
      isAllowedUri: (u) => Boolean(safeUrl(u)),
    }),
    HtmlBlock,
    Markdown,
    TableKit.configure({ table: { resizable: false } }),
    TaskList,
    TaskItem.configure({
      nested: true,
      onReadOnlyChecked: () => true, // 보기 상태 체크 허용(문서 반영은 doc-tiptap.js의 change 처리기)
      a11y: { checkboxLabel: (node, checked) => (checked ? "완료: " : "할 일: ") + (node.firstChild?.textContent || "빈 항목") },
    }),
    Image,
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

// (5) 불러올 때: 홑물결 ~는 marked가 취소선으로 읽는다(notes.js는 ~~만 취소선). 코드 밖에서만 \~로 막는다.
export const preprocess = (md) =>
  md
    .replace(/\r\n/g, "\n")
    .split(/(```[\s\S]*?```|`[^`\n]*`)/)
    .map((p, i) => (i % 2 ? p : p.replace(/(?<![~\\])~(?!~)/g, "\\~")))
    .join("");
