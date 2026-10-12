# U. 오픈소스 마크다운/블록 편집기 조사 (2026-10-08)

목적: 유달리 문서 기능을 자체 구현 대신 오픈소스 편집기로 "노션급"(A)으로 올릴 수 있는지, 아니면 외부 링크+회의 기록(C)만 남길지 판단 근거.

제약 요약: Django 5.2+HTMX, npm 빌드 없음(CDN 또는 1회 번들한 vendored 파일), 저장=body_md(마크다운), 한글 IME·모바일·표·체크리스트·코드·슬래시·문서 링크·이미지 업로드 훅·onChange 훅. 동시 편집 불필요.

조사 기준일 수치는 GitHub API(`api.github.com/repos/...`)와 npm 레지스트리(`registry.npmjs.org/<pkg>/latest`)를 2026-10-08에 직접 조회한 값이다.

## 1. 결론

1. **1순위: Milkdown Crepe** (MIT). 마크다운이 1급 저장 형식인 ProseMirror 편집기이고, 슬래시 메뉴·표·이미지 블록·코드 블록·툴바가 기본 포함된다. `getMarkdown()`과 `markdownUpdated` 리스너가 우리의 body_md·자동 저장 구조와 그대로 맞는다. 단점은 UMD 번들이 없다는 점이다(ESM만 있음). esm.sh로 바로 쓰거나 esbuild로 한 번 번들해 vendored 파일로 커밋해야 한다. 개발자 풀이 작다(스타 1.2만).
2. **2순위: Tiptap 3 + @tiptap/markdown** (코어·표·리스트·드래그 핸들·suggestion·file-handler 모두 MIT). 생태계와 유지보수(스타 3.9만, 9월 말 v3.31.4)는 가장 강하고, 공식 문서에 jsDelivr `+esm` 무빌드 예제가 있다. 다만 마크다운 확장이 "early release"이고 슬래시 메뉴 UI를 직접 만들어야 한다. Notion형 템플릿은 유료(Start 플랜)이다.
3. **최소 비용 대안: Vditor** (MIT, CDN 단일 스크립트, Typora식 IR 모드, 한국어 i18n). 1~2주면 붙일 수 있지만 블록·슬래시 UX가 아니라 "옵시디언/Typora 수준"에서 멈춘다.
4. 탈락: Toast UI Editor(2026-09-02 아카이브), BlockNote(React 전용, md 변환이 공식적으로 lossy, xl 패키지 GPL), Novel(React, 2025-01 이후 푸시 없음), Plate(React), Editor.js(JSON 모델, md 아님), BlockSuite(MPL, 무거움), Lexical(MIT·활발하지만 UI를 전부 직접 만들어야 함), HyperMD(2021 정지).

### 규모 비교(A 기준, 편집기 부분만)

| 방안 | 편집기 통합 규모 | 비고 |
|---|---|---|
| 자체 구현(이전 추정) | 편집기 포함 A 전체 6~12인월 | |
| Milkdown Crepe | **약 1인 3~5주** | 번들 1회, `[[` 문서 링크 플러그인, 업로드 훅, 자동 저장·version 충돌, md 왕복 회귀 테스트, 한글·모바일 실기 QA |
| Tiptap 3 | **약 1인 4~7주** | 위 항목 + 슬래시 메뉴·블록 메뉴 UI 직접 구현, md 확장 경계 사례 보완 |
| Vditor | 약 1인 1~2주 | 블록 UX 없음 |

- 편집기를 가져오면 "편집 경험" 부분은 6~12인월에서 1~2인월로 줄어든다고 본다(추정). 문서 트리·권한·검색·백링크·공유 같은 편집기 바깥 기능은 그대로 남으므로, A 전체는 대략 **2~4인월**로 다시 잡는 것이 타당하다(추정, 범위 정의에 따라 다름).

## 2. 비교표

| 후보 | 라이선스 | 빌드 없이 붙이기 | md 왕복 | 한글 IME | 표 | 슬래시 | 문서 링크 | 모바일 | 유지보수(2026-10-08) | 출처 |
|---|---|---|---|---|---|---|---|---|---|---|
| **Milkdown Crepe** | MIT | ESM만 있음(UMD 없음). esm.sh 또는 1회 번들 | 좋음. md가 원본 모델(remark), `getMarkdown()`/`markdownUpdated` | ProseMirror 기반. 저장소 한글 이슈 0건(사례 부족, 확인 불가) | 기본 포함 | 기본 포함(BlockEdit) | 기본 없음. 플러그인 직접 작성 | ProseMirror 수준, 실기 확인 필요 | 스타 12.0k, v7.22.2(09-23) | github.com/Milkdown/milkdown, milkdown.dev/docs/guide/using-crepe |
| **Tiptap 3 + @tiptap/markdown** | 코어·확장 MIT. 협업·댓글·변환·AI·Notion 템플릿은 유료 | 공식 CDN 가이드(jsDelivr `+esm`) | 가능하지만 "early release". 표 셀당 자식 노드 1개 제한, 댓글 미지원 | IME 수정 PR이 계속 들어옴(#7450, #7626, #8189) | MIT 확장 | 직접 구현(Suggestion 유틸 MIT) | Suggestion으로 `[[` 구현 가능 | 양호(실기 확인 필요) | 스타 38.7k, v3.31.4(09-30) | tiptap.dev/docs/editor/markdown, tiptap.dev/docs/editor/getting-started/install/cdn, tiptap.dev/pricing |
| **Vditor** | MIT | 가능(UMD/CDN, `cdn` 옵션) | 좋음. md 원본(Lute 엔진) | 2020 한글 입력 이슈 #511(닫힘). 이후 확인 불가 | 있음 | 블록 슬래시 없음. `hint.extend`로 키워드 자동완성 | `hint.extend`로 `[[` 가능 | "mobile friendly", 모바일 툴바 옵션 | 스타 11.4k, v4.0.0(08-30). 사실상 1인 메인테이너 | github.com/Vanessa219/vditor |
| BlockNote | 코어 MPL-2.0, `xl-*` GPL-3.0 또는 상용 | React 전제 | 공식적으로 "lossy" | IME 관련 수정 있음(#2361) | 있음 | 있음 | 직접 | 양호 | 스타 10.3k, v0.55.0(09-22) | blocknotejs.org/docs/foundations/supported-formats |
| Lexical | MIT | 바닐라 가능하지만 UI 전부 직접 | `@lexical/markdown` 트랜스포머 | 한글 관련 이슈·수정 다수(#9289, #8834 열림) | 직접 | 직접 | 직접 | 양호 | 스타 23.9k, v0.52.0(09-28) | github.com/facebook/lexical |
| Toast UI Editor | MIT | UMD CDN 가능 | 좋음 | 국산이라 양호했음 | 있음 | 없음 | 없음 | 보통 | **2026-09-02 아카이브** | github.com/nhn/tui.editor |
| ink-mde (CM6) | MIT | esm.sh | 무손실(텍스트 그대로) | CodeMirror 6 수준 | 원문 표시 | 없음 | 직접 | 모바일 툴바 옵션 | 스타 304, 07-31 푸시 | github.com/davidmyersdev/ink-mde |
| EasyMDE | MIT | CDN 가능 | 무손실(텍스트) | CM5 기반 | 원문 | 없음 | 없음 | 약함 | 스타 3.1k, v2.21.0 | github.com/Ionaru/easy-markdown-editor |
| ByteMD | MIT | Svelte 번들, 분할 화면 | 무손실(텍스트) | 확인 불가 | 원문 | 없음 | 없음 | 확인 불가 | 2025-02 이후 정지 | github.com/pd4d10/bytemd |
| HyperMD | MIT | CM5 | 무손실 | 확인 불가 | 일부 | 없음 | 없음 | 확인 불가 | 2021 정지 | github.com/laobubu/HyperMD |
| Novel | Apache-2.0 | React(Tiptap) | Tiptap 따름 | Tiptap 따름 | 있음 | 있음 | 직접 | 양호 | 2025-01 이후 정지 | github.com/steven-tey/novel |
| Plate | MIT(+유료 Pro) | React 전용 | 직렬화기 있음 | 확인 안 함 | 있음 | 있음 | 있음 | 양호 | 스타 16.6k, 활발 | github.com/udecode/plate |
| Editor.js | Apache-2.0 | CDN 가능 | JSON 모델, md는 변환 필요(손실) | 확인 안 함 | 플러그인 | 툴박스 | 직접 | 보통 | 스타 32.0k | github.com/codex-team/editor.js |
| BlockSuite | MPL-2.0 | 무거운 웹컴포넌트 | 자체 모델(손실) | 확인 안 함 | 있음 | 있음 | 있음 | 보통 | 스타 6.0k | github.com/toeverything/blocksuite |

### 통째 앱(임베드·연동 가능성만)

- Outline: 라이선스가 BSL 계열(GitHub 표기 NOASSERTION). 별도 서비스로 띄워 API·링크로 연동할 수는 있지만 편집기만 떼어 쓰기는 어렵다. github.com/outline/outline
- Docmost: AGPL-3.0, 별도 서비스로만 가능. github.com/docmost/docmost
- SiYuan: AGPL-3.0, 데스크톱 중심. github.com/siyuan-note/siyuan
- AFFiNE: BlockSuite 기반, 별도 서비스.
- 공통: 계정·권한 이중화와 AGPL 부담이 있어, 유달리 안에 넣는 A안의 대안이 아니라 C안의 "외부 자료 연결" 대상으로 보는 것이 맞다.

## 3. 통합 메모(추천 후보 공통)

- 배포: `esbuild`로 한 번 번들한 `static/vendor/editor-<버전>.js`를 커밋한다. 이렇게 하면 런타임에 npm이 필요 없다. 업그레이드 때만 다시 번들한다.
- HTMX: `hx-swap` 뒤 `htmx:afterSettle`에서 마운트하고, 교체 전에 destroy한다.
- 자동 저장: `markdownUpdated`(Crepe) 또는 `onUpdate`→`getMarkdown()`(Tiptap)에 디바운스를 걸고 PATCH(body_md, version)를 보낸다. 409가 나면 기존 충돌 처리를 탄다.
- 문서 링크: 저장 형식은 표준 md 링크 `[제목](/docs/<id>)`로 둔다. 그래야 MCP·AI가 그대로 읽는다. `[[` 입력은 UI 단축으로만 처리한다.
- md 왕복 회귀 테스트: 기존 body_md 표본을 불러와 바로 내보낸 결과가 원문과 같은지 비교한다(정규화 차이 허용 목록 포함). 도입 결정 전에 1~2일짜리 PoC로 먼저 확인할 것을 권한다.

## 4. 불일치·누락

- 사용자 브리프는 Toast UI를 후보로 적었지만, 이미 아카이브됐다(2026-09-02).
- Tiptap 문서 검색 결과에 Drag Handle이 "Pro Extension"이라는 옛 문구가 남아 있다. 그러나 npm `@tiptap/extension-drag-handle` 3.31.4는 MIT다.
- `ProseMirror/prosemirror-markdown` GitHub 저장소는 아카이브 표시가 있다(본 저장소가 다른 곳으로 옮겨간 것으로 추정되며, 확인 불가).

## 5. 확인 불가

- 각 후보의 한글 IME·모바일(iOS Safari, Android Gboard) 실제 품질. 이슈 검색으로는 판단이 부족해 PoC 실기 테스트가 필요하다.
- Milkdown Crepe의 이미지 업로드 콜백 정확한 옵션명(문서 본문을 가져오지 못함).
- Crepe를 esm.sh로 바로 쓸 때의 동작과 번들 크기.
