# 서버·JavaScript 사용자 메시지 검토

## 조사 범위

- `core/web/views/`의 Python 파일 21개 전부(`__init__.py`, `auth.py`, `common.py`, `decisions.py`, `discord.py`, `docs.py`, `events.py`, `github.py`, `me.py`, `notes.py`, `oauth.py`, `ops.py`, `orgs.py`, `portfolio.py`, `projects.py`, `roadmap.py`, `search.py`, `settings.py`, `tasks.py`, `teams.py`, `today.py`), `core/web/forms.py`, `core/web/static/app.js`, `core/web/static/notes.js`: 총 24파일·4,754줄. `messages.*`, `alert`, `prompt`, `flash`, `error=`, `raise ServiceError` 등을 기준으로 144개 후보 줄을 확인했다.
- 앱별 서비스 오류: `core/accounts/services.py`, `core/github/{pr_context,services,writes}.py`, `core/notes/services.py`, `core/orgs/{discord,requests,services}.py`, `core/portfolio/drafts.py`, `core/projects/{docs,services}.py`, `core/tasks/{decision_services,services}.py` 총 13파일과 `core/orgs/settings.py` 1파일에서 `raise ServiceError` 203곳을 색인했다. `core/orgs/settings.py`의 설정 라벨·도움말 자체는 부모 담당 범위로 두었다. 공통 처리 경로는 `core/common/errors.py`, `core/accounts/views.py`, `core/api/{api,auth}.py`도 확인했다.
- 확인 방법: 소스의 분기·응답·서비스 동작 대조. 브라우저 재현과 실서버 호출은 수행하지 않았다.

## 결론·근거·불일치·누락

1. **P1 — 문서·회의록 생성/업로드/삭제 실패가 화면에서 침묵함.** 현재는 오류 없이 목록으로 되돌아간다 → 권장: 원인을 메시지로 표시하고 업로드에서는 파일 형식·크기·인코딩처럼 고칠 수 있는 조건을 그대로 전달한다. `core/web/views/docs.py:54-74,102-109`, `core/web/views/notes.py:87-113,147-156`이 `ServiceError`를 버리고 리다이렉트한다. 서비스는 `.md`/`.markdown`, 256KB, UTF-8 등 구체적인 오류를 준비한다(`core/projects/docs.py:91-97`, `core/notes/services.py:96-102`). 사용자는 실패인지도 알기 어렵다.
2. **P1 — 잘못된 초대 만료 기간이 성공으로 표시됨.** 현재 `InviteForm` 검증 실패 시 `days=7`로 바꾸고 초대 링크를 발급한다 → 권장: `만료 기간은 1~90일로 입력하세요. 초대 링크는 만들지 않았습니다.` `core/web/views/orgs.py:166-172`, `core/web/forms.py:29-33`, `core/orgs/services.py:136-148`. 사용자가 입력한 기간과 실제 만료일이 달라진다.
3. **P2 — 모든 HTMX 오류가 저장 실패로 표시됨.** 현재 `저장하지 못했습니다. 페이지를 새로고침한 뒤 다시 시도하세요. (상태코드)` → 권장: 요청 동작별 오류를 표시하고 공통 실패에서는 `요청을 처리하지 못했습니다. 다시 시도하세요.` `core/web/static/app.js:102-110`의 리스너는 `body` 전체에 붙으며 저장 여부를 검사하지 않는다. 태스크 패널 열기도 HTMX 경로다(`core/web/static/app.js:113-118`).
4. **P2 — 자동 저장 유효성 오류의 원인을 숨김.** 현재 `저장 실패 · 새로고침하세요` → 권장: 400 응답의 유효성 오류를 표시하고, 네트워크 실패에만 연결·재시도를 안내한다. `core/web/static/notes.js:565-586`은 409만 별도 처리하고 다른 실패의 응답 본문을 버린다. 서버는 구체 오류를 400 본문으로 보낸다(`core/web/views/docs.py:91-94`, `core/web/views/notes.py:138-141`). 새로고침만으로 길이 초과·권한 오류가 해결되지는 않는다.
5. **P2 — 수동 복사 실패도 복사 완료로 표시됨.** 현재 클립보드 쓰기가 실패하면 `prompt`를 열고 곧바로 `복사됨` 또는 `TASK-… 링크 복사됨`을 표시한다 → 권장: `아래 내용을 선택해 직접 복사하세요`를 표시하고 성공 상태는 실제 복사 완료 후에만 쓴다. `core/web/static/app.js:135-145`의 `prompt` 반환값과 복사 여부를 확인하지 않는다.
6. **P2 — 일부 저장소 이슈 동기화 실패에도 전체 성공처럼 읽힘.** 현재 실패 저장소 수 오류와 함께 `열린 이슈 N건을 확인했습니다.` 성공 메시지를 항상 표시한다 → 권장: `일부 저장소만 확인했습니다. 확인한 저장소의 열린 이슈 N건, 실패 F곳.` `core/web/views/github.py:323-330`과 `core/github/services.py:833-845`. `N=0`일 때 특히 전부 실패와 실제 열린 이슈 0건이 섞여 읽힌다.
7. **P3 — 링크 입력 오류가 어느 필드인지 감춤.** 현재 `링크 입력이 올바르지 않습니다.` → 권장: 폼 오류를 필드별로 표시한다(예: `URL 형식을 확인하세요`, `제목을 입력하세요`). `core/web/views/projects.py:302-319`, `core/web/views/tasks.py:385-397`은 `LinkForm`의 유효성 결과를 버린다. 필드의 제약은 `core/web/forms.py:111-117`에 있다.

## 확인 불가

- 템플릿이 메시지를 실제로 어디에 배치하는지, 화면별 체감, 배포본 반영 여부는 이 갈래에서 확인하지 않았다. 화면·템플릿은 별도 담당 범위다.
