# Tiptap·공용 Markdown 편집기 교차 검토

- 검토일: 2026-10-09
- 대상: `37be542..ac43b10`; 검토 당시 HEAD `ac43b10b54f60a8a13344ab2df08d70645dd0b50`.
- 작성자는 Claude, 검토자는 Codex/Sol. 코드 수정·커밋 없이 이 보고서만 작성했다.
- **판정: 반려. 상 1건, 중 4건, 하 3건.** 중 4건 중 M4는 기존 코드에도 있던 확정 흐름 위험이며 신규 회귀로 세지 않는다. 신규·확장 범위 지적은 상 1건, 중 3건이다.
- 배포 조건: H1 원문 변형과 M1 저장 실패 후 이탈을 고치고, M2 URL 정책·M3 영상 지원 여부·M4 확정 전 저장을 결정 및 검증해야 한다.

## 검증 방법과 결과

`cd core && uv run pytest -q`: **1609 passed, 3 skipped, 1226 warnings, 66.29초**. 주요 경고는 Django 6.0 URL 기본 스킴 변경, staticfiles 디렉터리 없음, Pydantic/Ninja 사용 중단 예정 API였다. 실패 테스트는 없었다. 새 공용 필드 테스트는 주로 템플릿 문자열과 속성을 검사하므로 아래 브라우저 문제를 막지 못한다(`core/web/test_md_field.py:33`, `core/web/test_document_editor_accessibility.py:7`).

Playwright의 headless Chromium에서 실제 저장소의 `tiptap.bundle.js`, `md-field.js`, `doc-tiptap.js`, 필요한 경우 `htmx.min.js`·`app.js`를 읽어 실행했다. `http://review.local`의 응답을 메모리에서 제공하고 저장 응답은 204/버전 증가 또는 409로 모의했다. 테스트 스크립트는 stdin으로 실행했으며 추가 파일을 만들지 않았다. 실제 Django runserver·운영 DB는 사용하지 않았고 남긴 서버 프로세스도 없다. Django 인증·CSRF·저장 서비스 동작은 pytest 및 소스 검토로 확인했으며 브라우저 저장 경합 재현은 모의 응답 기준이다.

실제 `.md-view` 초기화에 HTML/스크립트·SVG·iframe·인라인 이벤트·`javascript:`·`data:` 페이로드 8개를 주입했을 때 실행 카운터 0, 이벤트 속성 0, 실제 script/iframe/svg 노드 0이었다. 직접 Tiptap 생성 시험도 같은 결과였다. **시험한 페이로드에서 저장형 XSS 실행은 재현되지 않았다.** HtmlBlock은 문자열을 `<pre>`의 텍스트 자식으로 직렬화하므로 `<aside><img src=x onerror="window.xss++"><script>window.xss++</script></aside>`가 이스케이프된 원문으로 표시된다(`tools/tiptap-bundle/entry.js:46`, `:53`). 인라인 HTML 이벤트는 스키마에 남지 않았다. 링크의 `javascript:`·`data:`는 빈 href로 직렬화됐다. 이 결과는 모든 브라우저·모든 입력에 대한 안전성 증명은 아니다.

정상 경로도 확인했다: 문서 열기 후 1초 동안 POST 0건; 일반 필수 필드 입력 후 버튼 제출 성공; Ctrl+Enter 제출 1회와 최신 textarea 값; 실제 HTMX swap 전 마지막 입력 저장 요청; 패널 Escape 닫기 후 최신 입력 저장 요청. 문서 제목·태그·본문의 직렬 저장에서 요청 버전은 10→11→12였다. ProseMirror 조합 상태를 모의한 동안 POST 0건, compositionend 후 본문 저장이었다. 물리 한글 IME 시험은 아래 확인 불가에 구분했다.

## 지적 사항

### H1 — 상: 무관한 부분을 편집해도 코드·보존 HTML의 원문이 바뀐다

- 위치: `tools/tiptap-bundle/entry.js:106`–`:110`; 저장 적용 `core/web/static/doc-tiptap.js:142`, `core/web/static/md-field.js:264`.
- 재현: 다음 원문을 문서 또는 일반 Markdown 칸에 넣고 연다. `~~~text` / `~3000` / `~~~`의 3줄 코드, 네 칸 들여쓴 `~3000`, `<aside>~3000</aside>`를 각각 시험한다. 코드·HTML 밖의 문장에 한 글자를 추가하고 저장한다.
- 관찰: `T.preprocess` 후 `ed.getMarkdown()`에서 틸드 펜스는 백틱 펜스로 정규화됐고, 두 코드 예시의 내용 줄은 `\~3000`, HTML 예시는 `<aside>\~3000</aside>`가 됐다. 코드 내용과 HTML raw에 실제 역슬래시 1개가 추가된다. 열기만으로는 저장되지 않지만 다른 곳을 한 번 고치면 정규화된 전체 본문이 저장되므로 해당 원문도 바뀐다.
- 원인: 보호하는 영역은 백틱 3개 펜스와 단일 백틱 인라인 코드뿐이다. 틸드 펜스·들여쓴 코드·HTML raw는 일반 텍스트처럼 물결표 보정을 받는다. HtmlBlock의 원문 보존은 전처리 이후부터라 이미 변형된 문자열을 보존한다.
- 방향: Markdown 토큰 단위로 일반 텍스트만 보정하고 코드 및 HTML raw를 그대로 전달한다. 세 입력에 대해 ‘다른 문단 수정 후에도 코드/HTML 내용이 동일한지’를 검증한다. 펜스 표기 변경과 코드 내용 변경을 구분해야 한다.

### M1 — 중: 저장 실패·409 뒤에도 목록으로 이동한다

- 위치: `core/web/static/doc-tiptap.js:182`–`:185`; 이전 구현 `37be542:core/web/static/notes.js:738`.
- 재현: 문서 본문을 수정하고 저장 요청을 409로 응답시킨다. 충돌 안내가 나온 후 `.note-back`을 누른다. 모의 브라우저에서 beforeunload 대화상자를 승인하면 `/list`로 이동했다.
- 관찰: `flushAll()`이 false를 반환해도 `go()`는 결과를 검사하지 않고 `location.assign`을 호출한다. beforeunload 경고는 있었으므로 무조건 조용히 유실되는 것은 아니다. 다만 저장 완료 후 복귀라는 동작이 실패해도 이탈을 시도하며, 사용자가 경고를 승인하면 편집 내용이 사라진다. 이전 구현은 저장 성공일 때만 이동했다.
- 방향: false·409·조합 중 미저장 상태면 화면에 머물고 복귀 버튼을 복구한다. 성공적으로 큐를 비운 경우에만 이동한다. HTTP 오류·네트워크 오류·409 각각에서 이탈하지 않는지 확인한다.

### M2 — 중: 같은 사이트 URL 검사 우회 및 이미지 URL 검사 누락

- 위치: `tools/tiptap-bundle/entry.js:17`–`:21`, `:68`, `:79`; 보기 렌더 `core/web/static/md-field.js:331`; 링크 이동 `core/web/static/doc-tiptap.js:225`.
- 재현: `[x](/\evil.example/path)`를 외부 GitHub 이슈 본문 또는 요청 상세 본문에 넣는다. Chromium에서 anchor의 literal href는 `/\evil.example/path`, 해석된 `.href`는 `http://evil.example/path`였다. `safeUrl`은 이를 허용한다. `![x](javascript:window.xss++)`, `![x](data:image/svg+xml,%3Csvg%20onload=alert(1)%3E)`도 시험한다.
- 관찰: 백슬래시를 브라우저가 슬래시처럼 해석하여 ‘같은 사이트 경로’가 외부 링크가 된다. 이미지 Markdown 경로는 툴바의 `safeUrl`을 거치지 않아 위 src들이 DOM에 남는다. 해당 이미지에서 스크립트 실행은 재현되지 않았으며 이것을 XSS 성공으로 판정하지 않는다. 링크 검사의 정규식은 이전 notes.js에도 있었지만 공용 렌더러의 확대 적용과 이미지 경로는 이번 배포에서도 점검해야 한다.
- 방향: URL을 브라우저와 같은 방식으로 정규화하여 허용 프로토콜·origin을 검사하고 제어문자/백슬래시 우회를 막는다. 이미지는 mailto까지 허용하는 링크 정책과 구분하여 http(s) 및 허용한 같은 사이트 경로만 받도록 로드·붙여넣기·Markdown 파싱 모두에서 검사한다. 외부 주소가 본래 허용되는 제품이므로 영향은 정책 우회/기만 링크이며 현재 증거로 임의 스크립트 실행을 주장할 수 없다. Tiptap의 링크 검사는 이미지의 검사를 대신하지 않는다([공식 Link 문서](https://tiptap.dev/docs/editor/extensions/marks/link)).

### M3 — 중: 기존 영상 임베드가 깨진 이미지로 바뀐다

- 위치: `tools/tiptap-bundle/entry.js:61`–`:81`; 삭제한 구현 `37be542:core/web/static/notes.js:21`, `:41`, `:45`.
- 재현: 기존 본문 `![회의 영상](https://youtu.be/dQw4w9WgXcQ)`를 연다. 새 스키마는 image 노드를 만들며 YouTube iframe을 만들지 않는다. Vimeo·mp4/webm도 기존 media 변환 경로가 없어졌다.
- 관찰: 예전 문서는 영상 주소를 이미지 문법으로 저장했다. 새 구현은 이를 실제 `<img src="https://youtu.be/...">`로 표시하므로 동영상이 재생되지 않고 깨진 이미지가 된다. URL은 남으나 영상 노드나 대체 링크가 없다.
- 방향: 기존 문법을 안전한 영상 노드로 처리하거나 클릭 가능한 링크로 제공한다. 기능을 없애기로 했다면 기존 문서 변환 및 사용자 안내가 필요하다. YouTube/Vimeo 재생까지는 외부 네트워크 시험을 하지 않았지만 iframe→img 구조 회귀는 코드와 실제 렌더로 확인했다.

### M4 — 중, 기존 위험: 회의록 확정이 미저장 본문·메타 큐를 기다리지 않는다

- 위치: `core/web/templates/notes/list.html:102`, `core/web/static/doc-tiptap.js:139`, `:155`, `core/web/views/notes.py:215`, `core/notes/services.py:126`, `:145`.
- 재현: 본문 변경 후 0.8초 안에 확정 버튼을 누른다. 브라우저 모의에서는 확정 submit이 발생할 때 저장 POST 0건, 상태 ‘저장 대기…’, `.md-src`는 이전 값이고 편집기는 새 값이었다. 확정 폼에는 새 본문을 보내는 필드도 없다.
- 영향: 서버 확정은 현재 DB 내용을 공개하고 버전을 올린다. 미저장 변경이 늦게 도착하면 버전 경합/409가 나거나 이동으로 저장이 중단될 수 있다. 새 제목의 0.8초 debounce에도 같은 경계가 있다. beforeunload 경고가 있어야 할 경로이며 실제 서버의 동시 요청 순서는 확인하지 않았다.
- 구분: 확정 폼이 별도 POST인 구조와 본문 debounce는 이전에도 있었다. 이번 diff의 신규 회귀라고 단정하지 않는다. 요청한 음성 회의록 확정 흐름의 배포 위험으로 기록한다. 녹음·전사 중 확정 금지는 서비스에 유지됐다(`core/notes/services.py:135`).
- 방향: 확정 전에 본문과 메타 전체 큐를 성공적으로 flush하고 새 version으로 확정한다. 실패/409이면 확정을 중단한다. 확정 후 공개되는 내용이 사용자가 화면에서 검토한 최신 값인지 서버 통합 시험을 추가한다.

### L1 — 하: 슬래시 블록 메뉴 삭제

- 위치: 삭제 `37be542:core/web/static/notes.js:89`, `:306`; 대체 툴바 `core/web/static/md-field.js:16`, `:190`.
- 재현: 빈 문단에서 `/` 또는 `/표`를 입력한다. 이전 목록 메뉴를 만드는 코드/확장이 없으며 새 툴바는 Ctrl+K·Alt+F10만 별도 처리한다.
- 방향: 메뉴를 복구하거나 키보드 툴바가 공식 대체 동작임을 안내한다. 표·제목 등은 툴바로 넣을 수 있어 본문 데이터 손실과는 구분한다.

### L2 — 하: 문서 편집기에는 HTMX destroy 경로가 없다

- 위치: `core/web/static/doc-tiptap.js:17`, `:175`, `:176`, `:257`; 공용 cleanup 소비자 `core/web/static/md-field.js:350`–`:353`.
- 재현: `.md-editor` 조각을 HTMX로 제거한다. 문서 init은 htmx:load를 지원하지만 root에 `_mdDestroy`를 등록하지 않으므로 공용 cleanup이 Tiptap·메타 타이머·전역 visibilitychange/beforeunload 리스너를 정리하지 않는다.
- 방향: 문서 편집기도 명시적인 수명주기 함수를 갖게 하고 저장 상태를 보전한 뒤 리스너/타이머/ResizeObserver를 해제한다. 현재 문서·회의록 이동이 주로 전체 페이지 탐색이므로 운영에서 반복 누수가 발생하는 경로는 확인하지 못했다. 일반 data-md 칸과 md-view에는 destroy가 있다.

### L3 — 하: 좁은 화면의 키보드 편집 진입 버튼이 숨겨진다

- 위치: `core/web/static/app.css:1368`; `core/web/static/doc-tiptap.js:212`, `:219`, `:241`; `core/web/templates/docs/_editor.html:6`.
- 재현: 좁은 화면에서 포인터 없이 Tab/Enter로 문서 본문 편집을 시작하려 한다. `.md-edit-row`가 display:none이라 편집 시작 버튼은 접근성 트리/탭 순서에서 빠진다. readonly 본문의 Enter 진입 처리는 없고, 본문 클릭으로만 editable이 된다.
- 방향: 시각적으로 숨기더라도 키보드 진입 수단을 유지하거나 readonly 영역의 Enter/Space로 편집을 시작한다. label.field→div.md-field 변경은 명시적 label for와 textarea id·초점 위임이 있어 연결 단절을 확인하지 못했다. 화면 낭독기 실제 발화는 시험하지 않았다.

## 라이선스

- `tools/tiptap-bundle/package.json:10`의 의존성과 lockfile 73개 설치 패키지 license 값이 모두 MIT이며 `@tiptap-pro/*`는 발견되지 않았다.
- 번들 헤더(`core/web/static/vendor/tiptap.bundle.js:1`)의 38개 런타임 패키지가 `tools/tiptap-bundle/THIRD_PARTY_LICENSES.txt:1`부터 고지돼 있다. build는 실제 metafile 입력 패키지만 모으고 MIT 외 패키지가 있으면 실패한다(`tools/tiptap-bundle/build.mjs:42`, `:54`). 고지된 라이선스는 모두 MIT였다.
- 이번 검토에서 non-MIT/Pro 혼입 근거는 없다. 의존성 설치·재빌드는 수정 금지 범위를 지키기 위해 실행하지 않았다. 따라서 minified 번들의 모든 바이트를 upstream 배포물과 대조한 공급망 검증은 하지 않았다.

## 확인 불가·한계

- 실제 로그인한 Django 화면에서 XSS 페이로드를 DB에 저장한 뒤 다른 사용자 세션으로 열어보는 종단 시험: 미실행. 실제 템플릿의 escaped textarea 저장소와 동일한 md-view DOM 구조 및 실제 모듈은 시험했다(`core/web/templates/github/issues.html:46`, `core/web/static/md-field.js:331`).
- 실제 Windows/모바일 한글 IME, iOS 키보드/viewport, 화면 낭독기: 미실행. 조합 상태 모의만으로 실제 IME 안전성을 확정하지 않는다.
- 실제 서버와 탭 두 개의 동시 저장·확정 순서, 느린 네트워크에서 HTMX 교체와 저장 실패 후 복구: 전체 종단 시험 미실행. 정상 큐와 409 클라이언트 경로는 모의했다.
- 실제 거버넌스/요청/결정/GitHub 개별 인증 화면마다 실행하지는 않았다. 이 화면들은 공용 md-view/field 경로를 공유하며 템플릿 및 전체 pytest를 확인했다.

요구사항 확인을 위한 추가 참고: 브라우저 제약 검증은 submit 이벤트보다 먼저 수행된다([MDN 제약 검증](https://developer.mozilla.org/en-US/docs/Web/HTML/Guides/Constraint_validation)). 이번 버튼/Ctrl+Enter 시험에서는 입력 update가 textarea를 먼저 동기화하여 필수 검증 실패를 재현하지 못했다.
