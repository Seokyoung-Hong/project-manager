# 블록 이동·인라인 HTML·좁은 화면 교차 검토

- 검토일: 2026-10-09. 대상: `93933e1..6173308`, 검토 HEAD `61733082f38f9239b243105d4f4f59d4ec26d216`.
- 작성자 Claude, 교차 검토 Codex/Sol. 코드 수정·커밋 없이 이 보고서만 작성했다.
- **판정: 조건부. 상 0건, 중 2건, 하 1건.** M1 원문/링크 보존과 M2 깨끗한 의존성 설치를 해결하고, 아래 미완료 끌기 시험을 완료한 뒤 배포한다. 현재 결과만으로 무조건 승인을 주지 않는다.
- 지난 `X-sol-review-md-editor.md` 항목을 재등록하지 않았다. CDATA 등은 이전 번들도 비교해 기존 누락임을 구분했다.

## 검증 결과

- 최종 `cd core && uv run pytest -q`: **1611 passed, 3 skipped, 1226 warnings, 62.55초**. 첫 실행은 happy-dom 미설치로 번들 회귀 1개가 추가로 건너뛰어 1610 passed/4 skipped였다. 의존성 설치 뒤 최종 전체 시험에 번들 회귀도 포함했다.
- `node tools/tiptap-bundle/check.mjs`: **tiptap bundle check OK**. 의존성 설치 후 `uv run pytest -q web/test_md_field.py`도 7 passed였다. 경고는 Django URL 기본 스킴, staticfiles 디렉터리, Pydantic/Ninja 사용 중단 예정 API였다.
- Chromium에서 저장소의 실제 번들·`md-field.js`·`doc-tiptap.js`·CSS를 실행했다. `http://review.local`을 Playwright 메모리 응답으로 제공하고 문서 저장은 204와 증가하는 `X-Note-Version`으로 모의했다. 서버·실제 DB는 사용하지 않았다. 스크립트는 stdin으로 실행했고 별도 검증 파일은 만들지 않았다.

## 지적 사항

### M1 — 중: HTML 인라인 노드의 서식/링크 직렬화와 특수 HTML 보존에 빈틈

- 위치: `tools/tiptap-bundle/entry.js:95`, `:109`, `:115`, **`:116`**; 기본 HTML fallback `:89`; 링크 직렬화 `:71`.
- 재현: `[<br>](https://a.example)`를 열고 다른 위치를 수정하여 저장한다. `getMarkdown()`은 `<br>`만 반환하여 링크 주소를 잃는다. `[<kbd>x</kbd>](https://a.example)`는 `<kbd>[x](https://a.example)</kbd>`가 되어 원래 링크 범위가 달라지고, `**<br>**`는 `<br>`가 된다. 원자 HTML 노드의 JSON에는 link/bold mark가 있어도 `renderMarkdown`이 raw만 반환한다.
- 영향: 새 HTML 노드는 태그 자체를 보존하지만, 그 태그에 적용된 링크·서식을 저장하지 않는다. 태그만 있는 링크는 주소 전체를 잃는다. HTML 보존을 주장하는 새 경로의 결함이다. **태그만 있는 링크의 주소 유실 자체는 이전 번들에서도 발생했으며, 이번에 새로 발생한 XSS/회귀라고 주장하지 않는다.** 이전 `[<kbd>x</kbd>](...)`는 태그를 버리고 `[x](...)`로 저장했지만, 새 구현은 HTML 노드와 mark를 함께 보존해야 하는 책임이 생겼다.
- 추가 경계: `p <![CDATA[hello]]> q`, `p <?target data?> q`, `p <!DOCTYPE html> q`는 모두 `p  q`가 된다. CDATA 입력 `p <![CDATA[<img src=x onerror="window.xss++">]]> q`는 `p ]]> q`가 된다. 정규식은 일반 태그·완결 주석만 잡고, 나머지 inline html 토큰은 HtmlBlock fallback에서 버린다. CDATA 누락은 `93933e1`에서도 동일했으므로 기존 미지원 범위다. 잘린 일반 태그는 삭제되지 않고 `<`가 `&lt;`로 저장됐다.
- 고칠 방향: htmlInline의 mark를 보존하는 직렬화를 적용하고 링크 범위를 포함한 재열기 시험을 한다. 특수 HTML 토큰도 안전한 raw 텍스트 노드로 받거나, 보존 기능의 지원 범위를 명확히 정한 뒤 누락 대신 원문을 유지한다. 다른 문단을 수정한 후 저장·재열기에서도 링크 주소와 태그 문자열이 유지되는지 검사한다.

### M2 — 중: 기본 `npm ci`가 실패하여 깨끗한 설치·검증이 재현되지 않음

- 위치: `tools/tiptap-bundle/package-lock.json:588`, **`:600`**; `tools/tiptap-bundle/package.json:13`; 대역 치환 `tools/tiptap-bundle/build.mjs:27`.
- 재현: node_modules 없는 `tools/tiptap-bundle`에서 `npm ci --ignore-scripts` 실행. exit 1/EUSAGE이며 lockfile에 `@tiptap/extension-collaboration@3.31.4`, `@tiptap/y-tiptap@3.0.9`, `yjs@13.6.33`, `y-protocols`, `lib0`, `isomorphic.js`가 없다고 출력한다.
- 관찰: 새 drag-handle의 peer 의존성이 lockfile에 선언되지만 해당 패키지 항목이 없다. `npm ci --ignore-scripts --legacy-peer-deps`는 62개 설치·취약점 0으로 성공했고, 그 설치로 번들 회귀 시험은 통과했다. 저장소에 이 설치 정책을 고정하는 `.npmrc`는 없다. esbuild의 대역은 런타임 번들 포함을 막는 설정이며 npm의 peer 해석을 대신하지 않는다.
- 고칠 방향: 기본 npm 정책으로 lockfile을 재생성하거나, 의도적으로 peer를 제외한다면 프로젝트 설치 정책을 명시적으로 고정한다. 깨끗한 `npm ci`→회귀 검사→번들 빌드가 같은 정책으로 성공하게 한다. 이번 검토에서는 lockfile·번들을 고치거나 재생성하지 않았다.

### L1 — 하: 원자 블록을 선택한 상태에서는 Alt 이동이 동작하지 않음

- 위치: `tools/tiptap-bundle/entry.js:138`–`:141`; `core/web/static/md-field.js:194`.
- 재현: `<aside>hello</aside>\n\nend`를 연 뒤 첫 HtmlBlock을 NodeSelection으로 선택하고 `T.moveBlock(ed, 1)`을 호출하면 false, 순서는 그대로다. 실제 키보드 경로도 같은 함수에 연결된다. atom 블록의 선택 시작점은 문서 깊이 0이어서 `d < 1`에 걸린다.
- 영향: 블록 HTML 같은 원자 블록에는 손잡이 끌기의 키보드 대안이 제공되지 않는다. 내용 손실/예외는 없었다. 텍스트 커서를 둔 표·코드·목록 이동과 구분한다.
- 고칠 방향: NodeSelection이면 선택된 블록의 위치·부모·인덱스로 이동 대상을 계산한다. 블록 HTML 및 이미지 선택에서도 위·아래 이동, 저장, 실행 취소를 확인한다.

## XSS와 HTML 클립보드

- 보기/편집 각각 11개 Markdown 입력을 시험했다: img onerror, javascript 링크, svg onload, iframe srcdoc, style, 완결 주석, CDATA, 잘린 태그, 백틱 코드 안 태그, 링크 텍스트 안 태그, script. **실행 카운터 0, 실제 script/iframe/style/svg·onerror/onload·javascript anchor 0**이었다. CDATA의 문자열 누락은 M1에 별도로 기록했다.
- 일반 인라인 이벤트 태그·script·style·iframe도 원문 글자로 렌더됐다. HtmlInline/HtmlBlock의 `renderHTML`이 raw를 문자열 자식으로 주므로 DOMSerializer가 텍스트로 삽입한다(`tools/tiptap-bundle/entry.js:87`, `:104`). 손잡이의 innerHTML은 고정 SVG 상수이며 외부 원문을 넣지 않는다(`:128`).
- 실제 ClipboardEvent/DataTransfer의 `text/html`로 img onerror, javascript 링크, svg, iframe, style 및 `span[data-html-inline]`을 붙였다. 실행 카운터와 위험 DOM 수는 0이었다. 일반 HTML 클립보드는 스키마에 따라 서식을 해석하거나 태그를 버리므로, Markdown HTML 태그의 raw 보존 경로와는 다르다. `data-html-inline` 래퍼 안에 이스케이프한 공격 문자열도 실행 없이 텍스트로 남았다(`:103`).
- 이번 입력들에서 새 XSS 실행 경로는 발견하지 못했다. 외부 GitHub 이슈의 공용 보기 렌더도 동일 번들/스키마를 사용한다(`core/web/static/md-field.js:339`). 실제 GitHub 이슈 동기화·DB 저장·다른 사용자 열기의 종단 시험은 하지 않았다.

## 이동·자동 저장·실행 취소·화면

- 일반 목록 항목을 아래로 이동할 때 중첩 자식이 함께 남았다. 중첩 목록의 x/y 순서만 바뀌었고 체크 항목 이동은 checked 값과 중첩 체크 항목을 유지했다. 표의 전체 행/셀, 코드의 `~x <b>` 내용도 그대로 유지됐다. 각 이동 후 undo는 원래 JSON과 일치했다(`tools/tiptap-bundle/entry.js:137`). 표·코드 끝의 빈 문단 추가는 편집기의 trailing-node 정규화로 내용 유실은 아니었다.
- 실제 손잡이로 일반 문단을 끌어 second/first로 바꾸고 undo한 JSON이 원본과 일치했다. 300px 칸의 손잡이가 칸 안에 보이고 수평 페이지 넘침도 없었다(`core/web/static/app.css:963`). **목록·표·코드·HTML 블록의 실제 포인터 끌기는 아래 한계에 해당한다.**
- 390px 모바일 viewport(meta viewport 포함): Tab/Enter 진입, Escape 뒤 readonly 본문 초점과 tabindex=0, Shift+Tab→Tab→Enter 재진입을 확인했다. 터치 컨텍스트의 손잡이는 display:none이었다(`core/web/static/doc-tiptap.js:38`, `:280`; `core/web/static/app.css:970`).
- 실제 doc-tiptap 모듈에서 Alt+↓ 후 모의 POST 1회에 `second\n\nfirst`, Ctrl+Z 뒤 추가 POST 1회에 `first\n\nsecond`를 확인했다. touch를 처리 전에 잡는 캡처·툴바 경로가 저장을 예약한다(`core/web/static/doc-tiptap.js:52`, `core/web/static/md-field.js:197`).
- yjs 대역의 getState는 null이며 업스트림 getRelativePos/getAbsolutePos는 해당 결과에서 즉시 반환한다. isChangeOrigin은 false다(`tools/tiptap-bundle/build.mjs:35`). 시험한 생성·키보드 이동·undo·문단 끌기에서 관련 런타임 예외는 없었다. 공동 편집은 미사용 전제이며 향후 켜면 이 대역을 제거해야 한다.

## 라이선스

- 번들 머리말의 43개 런타임 패키지를 설치 package.json의 버전/MIT 값 및 THIRD_PARTY_LICENSES의 패키지 제목·실제 LICENSE 전문과 대조했다. CRLF/LF만 정규화했으며 **불일치 0**이었다.
- 새 `@floating-ui/core`, `dom`, `utils`의 전문은 `tools/tiptap-bundle/THIRD_PARTY_LICENSES.txt:1`, `:25`, `:49`; drag-handle은 `:223`, node-range는 `:423`에 있다. 번들 머리말도 각각 `core/web/static/vendor/tiptap.bundle.js:3`, `:4`, `:5`, `:12`, `:20`에 일치한다. 새 런타임 패키지의 non-MIT/Pro 혼입은 발견하지 못했다.
- lockfile 전체에는 happy-dom의 BSD-2-Clause가 있다(`tools/tiptap-bundle/package-lock.json:987`). 이는 개발용 DOM 시험 의존성이고 런타임 번들 머리말/입력 범위에는 없다. 설치 패키지 모두가 MIT라는 주장은 하지 않는다.

## 확인 불가·남은 배포 확인

- 목록(특히 중첩 자식 포함), 표, 코드, 블록 HTML의 **실제 포인터 끌기 완료·자동 저장·undo**. Playwright dragTo 및 마우스 입력 시도 일부가 완료되지 않아 중단했으며, 제품 정지/무한 루프라고 단정할 근거는 없다. 키보드 이동 시험이 실제 drag slice/drop 직렬화를 대신하지 않는다. 이 경로는 배포 전 다른 자동화 환경 또는 수동으로 완료해야 한다.
- 실제 로그인 Django 화면·SQLite DB의 저장 값 및 동시 저장, 외부인이 쓴 GitHub 이슈 본문을 다른 사용자 세션에서 열기. 클라이언트 모의와 pytest로 검증한 범위만 보고한다.
- 여러 실제 작은 입력 칸의 화면 검토, 실물 터치 기기/IME/화면 낭독기, Firefox/WebKit. 300px 칸과 Chromium 모바일 컨텍스트만 확인했다.
- 새 번들의 모든 바이트를 재빌드 산출물과 대조하는 공급망 검증은 미실행이다. 검토에 사용한 node_modules는 종료 전에 제거했으며 runserver를 띄우지 않았다.
