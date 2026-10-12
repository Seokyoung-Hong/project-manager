// npm install && npm run build
// entry.js를 ESM 단일 파일로 묶어 core/web/static/vendor/tiptap.bundle.js에 쓴다.
// 실제로 번들에 들어간 패키지만 골라 맨 위 고지와 THIRD_PARTY_LICENSES.txt를 만든다.
import { build } from "esbuild";
import { readFileSync, writeFileSync, readdirSync } from "node:fs";
import { dirname, join } from "node:path";
import { fileURLToPath } from "node:url";

const here = dirname(fileURLToPath(import.meta.url));
const out = join(here, "../../core/web/static/vendor/tiptap.bundle.js");

// 업스트림 버그 보정(B): 번호 목록 항목의 이어지는 줄 들여쓰기를 `구분자 길이 + 1`로 세서
// 구분자 뒤 공백을 1칸 덜 걷어낸다 → 번호 목록 안 코드가 저장할 때마다 1칸씩 밀린다.
// 정규식이 잡은 실제 접두부 길이(line - content)로 센다. 패턴이 없으면 빌드를 멈춘다(버전이 바뀐 것).
const BUG = "const contentIndent = indentLevel + marker.length + 1;";
const patchList = {
  name: "patch-ordered-list-indent",
  setup(b) {
    b.onLoad({ filter: /@tiptap[\\/]extension-list[\\/]dist[\\/]index\.js$/ }, (args) => {
      const src = readFileSync(args.path, "utf8");
      if (!src.includes(BUG)) throw new Error("extension-list 보정 지점을 찾지 못했습니다: " + args.path);
      return { contents: src.replace(BUG, "const contentIndent = line.length - content.length;"), loader: "js" };
    });
  },
};

// 끌어 옮기기(extension-drag-handle)는 공동 편집(Yjs)용 모듈을 import하지만, 공동 편집을 켜지 않으면 쓰지 않는다
// (ySyncPluginKey.getState가 null이면 바로 돌아간다). yjs를 통째로 싣지 않도록 빈 대역으로 바꾼다.
const noCollab = {
  name: "no-collaboration",
  setup(b) {
    b.onResolve({ filter: /^@tiptap\/(extension-collaboration|y-tiptap)$/ }, (args) => ({ path: args.path, namespace: "no-collab" }));
    b.onLoad({ filter: /.*/, namespace: "no-collab" }, () => ({
      contents:
        "export const isChangeOrigin = () => false;\n" +
        "export const ySyncPluginKey = { getState: () => null };\n" +
        "export const absolutePositionToRelativePosition = () => null;\n" +
        "export const relativePositionToAbsolutePosition = () => null;\n",
      loader: "js",
    }));
  },
};

const result = await build({
  plugins: [patchList, noCollab],
  entryPoints: [join(here, "entry.js")],
  bundle: true,
  format: "esm",
  minify: true,
  target: "es2020",
  legalComments: "none", // 고지는 아래에서 한 번에 모아 붙인다
  metafile: true,
  write: false,
});

const pkgs = new Map();
for (const input of Object.keys(result.metafile.inputs)) {
  const m = input.match(/node_modules\/((?:@[^/]+\/)?[^/]+)\//);
  if (!m || pkgs.has(m[1])) continue;
  const dir = join(here, "node_modules", m[1]);
  const meta = JSON.parse(readFileSync(join(dir, "package.json"), "utf8"));
  const lic = readdirSync(dir).find((f) => /^(licen[cs]e|copying)/i.test(f));
  pkgs.set(m[1], { version: meta.version, license: meta.license, text: lic ? readFileSync(join(dir, lic), "utf8") : null });
}
const names = [...pkgs.keys()].sort();
const bad = names.filter((n) => pkgs.get(n).license !== "MIT");
if (bad.length) throw new Error("MIT가 아닌 패키지: " + bad.join(", "));

const header =
  "/*! 유달리 Tiptap 시험 번들 — tools/tiptap-bundle에서 생성(npm run build). 직접 고치지 않는다.\n" +
  " * 포함 패키지(모두 MIT, 전문은 tools/tiptap-bundle/THIRD_PARTY_LICENSES.txt):\n" +
  names.map((n) => ` *   ${n}@${pkgs.get(n).version}`).join("\n") +
  "\n */\n";
writeFileSync(out, header + result.outputFiles[0].text);

const missing = names.filter((n) => !pkgs.get(n).text);
writeFileSync(
  join(here, "THIRD_PARTY_LICENSES.txt"),
  names
    .map((n) => {
      const p = pkgs.get(n);
      // 라이선스 파일을 싣지 않은 패키지는 MIT 표준 문안을 남긴다(저작권자는 package.json 기준).
      return `==== ${n}@${p.version} (${p.license}) ====\n\n${p.text || mitFallback(n)}\n`;
    })
    .join("\n"),
);
console.log(`${out}\n${names.length}개 패키지${missing.length ? ", 라이선스 파일 없음: " + missing.join(", ") : ""}`);

function mitFallback(name) {
  const meta = JSON.parse(readFileSync(join(here, "node_modules", name, "package.json"), "utf8"));
  const author = typeof meta.author === "string" ? meta.author : meta.author?.name || name + " authors";
  return MIT.replace("{who}", author);
}
const MIT = `MIT License

Copyright (c) {who}

Permission is hereby granted, free of charge, to any person obtaining a copy
of this software and associated documentation files (the "Software"), to deal
in the Software without restriction, including without limitation the rights
to use, copy, modify, merge, publish, distribute, sublicense, and/or sell
copies of the Software, and to permit persons to whom the Software is
furnished to do so, subject to the following conditions:

The above copyright notice and this permission notice shall be included in all
copies or substantial portions of the Software.

THE SOFTWARE IS PROVIDED "AS IS", WITHOUT WARRANTY OF ANY KIND, EXPRESS OR
IMPLIED, INCLUDING BUT NOT LIMITED TO THE WARRANTIES OF MERCHANTABILITY,
FITNESS FOR A PARTICULAR PURPOSE AND NONINFRINGEMENT. IN NO EVENT SHALL THE
AUTHORS OR COPYRIGHT HOLDERS BE LIABLE FOR ANY CLAIM, DAMAGES OR OTHER
LIABILITY, WHETHER IN AN ACTION OF CONTRACT, TORT OR OTHERWISE, ARISING FROM,
OUT OF OR IN CONNECTION WITH THE SOFTWARE OR THE USE OR OTHER DEALINGS IN THE
SOFTWARE.
`;
