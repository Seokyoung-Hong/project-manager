# AI 자동완성 최종 문구

작성 기준: IMPL-PLAN-12 §2·§12·§15 및 이번 작업의 확정 결정. 코드와 기존 정책 문서는 수정하지 않았습니다. 위치는 작성 시점의 코드 기준이며 병렬 수정으로 줄번호가 바뀔 수 있습니다.

## 확정 용어표

| 용어 | 뜻·사용 기준 | 사용하지 않는 말 |
|---|---|---|
| AI 자동완성 | 기능 전체 이름. 조직 설정은 ‘AI 자동완성 사용’ | AI 어시스트, 코파일럿, 매직, AI 쓰기 허용 |
| AI로 쓰기 | 입력 칸의 초안 요청 버튼 | 자동 생성, 아이콘 단독 버튼 |
| 조직 AI | 작업 중인 조직 관리자가 등록한 AI | 조직 LLM, 공용 키 |
| 개인 AI | 이용자가 등록한 OpenAI 호환 AI | 내 LLM, 프로바이더, 공급자 |
| AI 사용 순서 | 사용 가능한 개인 AI·조직 AI에 요청하는 순서 | 폴백, 우선순위 큐 |
| AI 서버 주소 / 모델 / 키 | 연결 설정의 세 항목 | 엔드포인트 |
| 내 PC / 내 PC 연결 | 이용자가 연결한 자신의 PC / 연결 설정 이름 | 멤버 PC, 로컬 중계 서버 |
| 내 PC 거쳐 보내기 | PC 내부·사설망의 개인 AI에 요청하는 경로 | 터널, 프록시, 중계 서버 |
| 미리보기 / 적용 / 다시 쓰기 / 닫기 | 확인·반영·재요청·대화상자 종료 | 수락, 승인, 재생성 |
| 태스크 후보 / 태스크 후보 뽑기 | 태스크 생성 전 제안 목록 / 요청 버튼 | 추출, 액션 아이템, AI로 나눠 가져오기 |
| 고른 후보로 태스크 만들기 | 확인·수정한 후보의 생성 버튼 | 자동 태스크 생성 |
| 비슷한 태스크 | 중복일 가능성이 있는 기존 태스크 | 중복 태스크(단정) |
| 허용 호스트 | 조직 AI 사설 주소 허용 목록의 호스트 이름·IP | 화이트리스트 |
| 구성원 / 관리자 | 조직의 이용자 / 관리 권한을 가진 이용자 | 멤버(이 기능 문구에서) |
| 오늘 조직 AI n/한도 | 사용량과 현재 조직의 하루 한도 | 쿼터, 크레딧 |

금지어는 기능 UI에 적용합니다. 정책 문서의 법률상 ‘제공자·수탁자’와 기술 규격 ‘OpenAI 호환’은 사용할 수 있습니다. 기존 ‘AI 연결·AI 도구·AI용 토큰’은 MCP 의미이므로 이 기능 이름으로 쓰지 않습니다. 격식체를 유지하며 요청은 ‘…해 주세요’로 씁니다.

## 키별 최종 문구

실제 COPY 키 **117개**, 와일드카드·주석 묶음을 구체화하고 표시 없는 UI를 보완한 키 **51개**, 총 **168개**입니다. COPY:키는 설명용 표기로 제외했습니다. ai_job_*·ai_candidates_*·ai_doc_*는 아래 개별 키로 확정했습니다. ai_minutes·ai_extract 묶음은 두 키로 셉니다. 같은 키가 여러 위치에서 쓰이면 한 행에 모두 기재했습니다.

동적 값 표기 {name}·{max}·{n}·{limit}·{host}·{code}는 각 위치의 기존 변수로 치환합니다. HTML·아이콘은 문구에 포함하지 않습니다. 조건부 분기는 코드 조건을 유지합니다. 연결 확인 결과의 모델 선택 안내는 기존 fill/list_id 조건이 참일 때만 표시합니다.

| 키 | 위치(파일:줄) | 현재 임시 문구 | 최종 문구 |
|---|---|---|---|
| extract_assignee_check | core/assist/extract.py:18 | 이름 확인 필요 | 담당자 확인 필요 |
| extract_no_due_meeting | core/assist/extract.py:19 | 회의록 태스크 후보로 만들었습니다 | 회의록의 태스크 후보에서 생성되어 기한이 정해지지 않았습니다. |
| extract_no_due_issue | core/assist/extract.py:20 | GitHub 이슈 태스크 후보로 만들었습니다 | GitHub 이슈의 태스크 후보에서 생성되어 기한이 정해지지 않았습니다. |
| extract_title_required | core/assist/extract.py:139 | 제목을 입력해 주세요. | 후보 제목이 없습니다. 태스크 제목을 입력해 주세요. |
| extract_due_invalid | core/assist/extract.py:150 | 기한 형식이 올바르지 않습니다. | 기한 형식이 올바르지 않습니다. 날짜 입력 칸에서 유효한 날짜를 선택해 주세요. |
| extract_row_failed | core/assist/extract.py:168 | 만들 수 없습니다. | 이 후보로 태스크를 만들지 못했습니다. 입력 내용과 프로젝트 권한을 확인한 뒤 다시 시도해 주세요. |
| extract_not_ready | core/assist/extract.py:185 | 태스크 후보가 아직 없습니다. | 태스크 후보가 아직 준비되지 않았습니다. 후보 뽑기가 끝난 뒤 다시 시도해 주세요. |
| extract_row_missing | core/assist/extract.py:200<br>core/assist/extract.py:232 | 후보를 찾을 수 없습니다. | 해당 태스크 후보를 찾을 수 없습니다. 후보를 다시 뽑은 뒤 선택해 주세요. |
| extract_project_required | core/assist/extract.py:236 | 프로젝트를 골라 주세요. | 프로젝트가 선택되지 않았습니다. 태스크를 만들 프로젝트를 선택해 주세요. |
| assist_url_invalid | core/assist/net.py:152<br>core/assist/net.py:191 | http:// 또는 https://로 시작하고 사용자 정보·쿼리가 없는 주소여야 합니다. / 주소 형식이 올바르지 않습니다. | AI 서버 주소 형식이 올바르지 않습니다. http:// 또는 https://로 시작하고 사용자 정보·쿼리를 포함하지 않는 주소를 입력해 주세요. |
| assist_url_unresolved | core/assist/net.py:167 | 주소를 찾을 수 없습니다. 주소를 확인해 주세요. | AI 서버 주소를 찾을 수 없습니다. 호스트 이름과 네트워크 연결을 확인해 주세요. |
| assist_url_https | core/assist/net.py:173<br>core/assist/net.py:203 | 공개 주소는 https://만 쓸 수 있습니다. / https:// 주소여야 합니다. | 공개 AI 서버 주소에는 HTTPS가 필요합니다. https://로 시작하는 주소를 입력해 주세요. |
| assist_url_scheme | core/assist/net.py:193 | http:// 또는 https://로 시작하는 주소여야 합니다. | AI 서버 주소에 통신 방식 또는 호스트가 없습니다. http:// 또는 https://로 시작하는 전체 주소를 입력해 주세요. |
| assist_url_extra | core/assist/net.py:194 | 사용자 정보·쿼리가 없는 주소여야 합니다. | AI 서버 주소에 사용자 정보 또는 쿼리가 포함되어 있습니다. 해당 정보를 제외한 주소를 입력해 주세요. |
| assist_url_blocked | core/assist/net.py:195 | 쓸 수 없는 주소입니다. 운영자에게 허용 호스트 등록을 요청해 주세요. | 보안 제한으로 사용할 수 없는 주소입니다. 공개 HTTPS 주소를 사용하거나, 사설망 주소이면 서비스 운영자에게 허용 호스트 등록 가능 여부를 문의해 주세요. |
| assist_bad_field | core/assist/services.py:53<br>core/assist/services.py:56 | 이 칸은 AI로 쓸 수 없습니다. | 이 칸은 AI 자동완성을 지원하지 않습니다. AI로 쓰기 버튼이 있는 칸에서 요청해 주세요. |
| assist_no_transcript | core/assist/services.py:66 | 전사문이 없어 회의록을 쓸 수 없습니다. | 전사문이 없어 회의록을 작성할 수 없습니다. 전사를 완료한 뒤 다시 요청해 주세요. |
| assist_pick_template | core/assist/services.py:75 | 템플릿을 골라 주세요. | 사용 가능한 템플릿이 선택되지 않았습니다. 이 조직에서 접근할 수 있는 템플릿을 선택해 주세요. |
| assist_busy | core/assist/services.py:82 | 진행 중인 AI 작업이 끝난 뒤 다시 요청해 주세요. | 동시에 처리할 수 있는 AI 작업 수를 넘었습니다. 진행 중인 작업이 끝난 뒤 다시 요청해 주세요. |
| assist_rate | core/assist/services.py:86 | 진행 중인 AI 작업이 끝난 뒤 다시 요청해 주세요. / AI 요청이 너무 많습니다. 잠시 뒤 다시 요청해 주세요. | 최근 1시간의 AI 요청 한도를 넘었습니다. 잠시 후 다시 요청해 주세요. |
| assist_apply_mode | core/assist/services.py:162 | 적용 방식을 골라 주세요. | 적용 방식이 선택되지 않았습니다. 내용을 바꾸거나 뒤에 추가하는 방식을 선택해 주세요. |
| assist_nothing_to_apply | core/assist/services.py:165 | 적용할 결과가 없습니다. | 적용할 AI 결과가 없습니다. AI로 쓰기를 다시 요청해 주세요. |
| assist_enabled_label | core/orgs/settings.py:924 | AI 자동완성 사용 | AI 자동완성 사용 |
| assist_enabled_help | core/orgs/settings.py:925 | 끄면 이 조직 내용으로는 조직 AI·개인 AI 모두 자동완성과 태스크 후보 뽑기를 쓸 수 없습니다. | 끄면 이 조직의 내용으로 조직 AI와 개인 AI를 모두 사용할 수 없으며, AI 자동완성과 태스크 후보 뽑기 버튼이 표시되지 않습니다. |
| assist_org_url_label | core/orgs/settings.py:934 | 조직 AI 주소 | 조직 AI 주소 |
| assist_org_url_help | core/orgs/settings.py:935 | OpenAI 호환 서버 주소입니다(예: https://api.example.com/v1). | OpenAI 호환 AI 서버 주소입니다. 예: https://api.example.com/v1. 사설망 주소는 서비스 운영자의 허용 호스트 등록이 필요합니다. |
| assist_org_model_label | core/orgs/settings.py:946 | 조직 AI 모델 | 조직 AI 모델 |
| assist_org_model_help | core/orgs/settings.py:947 | 조직 AI 서버에 보낼 모델 이름입니다. | 조직 AI 서버에서 사용할 모델 이름입니다. |
| assist_org_api_key_label | core/orgs/settings.py:957 | 조직 AI 키 | 조직 AI 키 |
| assist_org_api_key_help | core/orgs/settings.py:958 | 암호화해 저장하며 화면에는 설정 여부만 보입니다. | 키는 암호화하여 저장하며 화면에는 설정 여부만 표시됩니다. |
| assist_org_level_label | core/orgs/settings.py:967 | 조직 AI를 쓸 수 있는 사람 | 조직 AI 사용 권한 |
| assist_org_daily_limit_label | core/orgs/settings.py:978 | 조직 AI 하루 한도(멤버 한 사람) | 조직 AI 하루 한도(구성원 1명) |
| assist_org_daily_limit_help | core/orgs/settings.py:979 | 멤버 한 사람이 하루에 조직 AI로 실행할 수 있는 작업 수입니다. 관리자는 세지 않습니다. 0이면 제한하지 않습니다. | 구성원 1명이 하루에 조직 AI로 실행할 수 있는 작업 수입니다. 기본값은 30이며, 관리자는 한도에서 제외됩니다. 0이면 제한하지 않습니다. |
| assist_group | core/orgs/settings.py:1088 | AI 자동완성 | AI 자동완성 |
| ai_write | core/web/static/ai-fill.js:37 | b.textContent = "AI로 쓰기"; | AI로 쓰기 |
| ai_sending | core/web/static/ai-fill.js:51 | body.innerHTML = 'AI에게 요청을 보내는 중입니다.'; | AI에 요청을 보내는 중입니다. |
| ai_apply_unsaved | core/web/static/ai-fill.js:80 | body.insertAdjacentHTML("afterbegin", '⚠ 본문을 아직 저장하지 못해 적용하지 않았습니다. 저장 상태를 확인한 뒤 다시 눌러 주세요.'); | 본문을 저장하지 못해 AI 결과를 적용하지 않았습니다. 저장 상태를 확인한 뒤 다시 적용해 주세요. |
| ai_err_unknown | core/web/static/ai-fill.js:119 | if (![400, 403, 409, 429].includes(s)) e.detail.serverResponse = '⚠ 요청을 처리하지 못했습니다. 대화상자를 닫고 다시 시도해 주세요.'; | 요청을 처리하지 못했습니다. 대화상자를 닫고 다시 시도해 주세요. |
| ai_extract_issue | core/web/templates/github/issues.html:62 | AI로 나눠 가져오기 / #{{ issue.number }} 이슈를 AI로 나눠 가져오기 | 태스크 후보 뽑기 / #{{ issue.number }} 이슈에서 태스크 후보 뽑기 |
| ai_minutes | core/web/templates/notes/list.html:63 | AI로 회의록 쓰기 | AI로 회의록 쓰기 |
| ai_extract | core/web/templates/notes/list.html:65 | 태스크 후보 뽑기 | 태스크 후보 뽑기 |
| ops_assist_intro | core/web/templates/ops/assist.html:6 | 조직 AI 주소가 사설망(10/8·172.16/12·192.168/16 등)을 가리킬 때 이 목록에 있는 호스트만 허용합니다. 호스트 문자열이 정확히 같아야 하며 와일드카드는 없습니다. 루프백·링크로컬·내부 서비스 이름은 목록에 넣어도 막힙니다. 개인 AI에는 적용하지 않습니다. | 조직 AI가 사설망 주소를 사용할 때는 이 목록에 등록된 호스트만 허용합니다. 호스트 이름 또는 IP 주소가 정확히 일치해야 합니다. 와일드카드는 지원하지 않으며, 루프백·링크로컬·내부 서비스 이름 등 차단 대상은 등록해도 사용할 수 없습니다. 개인 AI에는 적용되지 않습니다. |
| ops_assist_empty | core/web/templates/ops/assist.html:14 | {% empty %}허용 호스트가 없습니다. 조직 AI는 공개 https 주소만 쓸 수 있습니다. | 허용 호스트가 없습니다. 조직 AI에는 공개 HTTPS 주소를 사용할 수 있습니다. |
| ops_assist_host_help | core/web/templates/ops/assist.html:24 | 예: llm.lab.internal, 10.0.0.5. http://·포트·경로 없이 입력해 주세요. | 예: llm.lab.internal, 10.0.0.5. http://·https://·포트·경로를 제외하고 입력해 주세요. |
| ops_assist_nav | core/web/templates/ops/base.html:10 | AI 허용 호스트 | AI 허용 호스트 |
| assist_org_test_ok | core/web/templates/orgs/_assist_result.html:3 | {% else %}연결되었습니다. 모델 {{ count }}개를 확인했습니다.{% if fill %} 조직 AI 모델 칸에서 고른 뒤 조직 설정을 저장해 주세요.{% endif %}{% endif %} | 연결되었습니다. 모델 {{ count }}개를 확인했습니다. 조직 AI 모델을 선택한 뒤 조직 설정을 저장해 주세요. |
| assist_enabled_notice | core/web/templates/orgs/_assist_test.html:2 | 켜져 있으면 구성원이 업무 내용을 개인 AI·조직 AI로 보낼 수 있습니다. 끌 수 있습니다. | AI 자동완성은 기본으로 켜져 있습니다. AI가 등록되어 있으면 구성원의 요청에 따라 업무 내용과 필요한 맥락을 조직 AI 또는 개인 AI로 전송합니다. 다른 구성원의 표시 이름이 포함될 수 있으며, 전송·보관 조건은 해당 AI 운영자에 따릅니다. 원하지 않으면 이 설정을 꺼 주세요. |
| assist_org_test | core/web/templates/orgs/_assist_test.html:4 | 조직 AI 연결 시험 | 조직 AI 연결 확인 |
| assist_org_models | core/web/templates/orgs/_assist_test.html:5 | 조직 AI 모델 불러오기 | 조직 AI 모델 불러오기 |
| settings_ai_title | core/web/templates/settings/ai.html:6 | AI 사용 순서 | AI 사용 순서 |
| settings_ai_intro | core/web/templates/settings/ai.html:7 | AI 자동완성은 위에서부터 차례로 시도합니다. 앞의 AI가 응답하지 않으면 다음 AI로 넘어갑니다. 조직 AI는 작업하는 조직의 관리자가 등록한 AI이며, 조직이 AI 자동완성을 끄면 어느 AI로도 보내지 않습니다. | AI 자동완성과 태스크 후보 뽑기는 위에서부터 사용 가능한 AI에 요청합니다. 요청에 실패하면 다음 AI에 같은 업무 내용이 전송될 수 있습니다. 조직 AI는 작업 중인 조직의 관리자가 등록한 AI입니다. 조직의 AI 자동완성이 꺼져 있으면 조직 AI와 개인 AI에 이 조직의 내용을 전송하지 않습니다. |
| settings_ai_add_title | core/web/templates/settings/ai.html:13 | 개인 AI 추가 | 개인 AI 추가 |
| assist_src_limit_help | core/web/templates/settings/ai.html:15 | 개인 AI는 {{ personal_max }}개까지 등록할 수 있습니다. 새로 추가하려면 쓰지 않는 개인 AI를 삭제해 주세요. | 개인 AI는 {{ personal_max }}개까지 등록할 수 있습니다. 새로 등록하려면 사용하지 않는 개인 AI를 삭제해 주세요. |
| settings_ai_add_help | core/web/templates/settings/ai.html:17 | OpenAI 호환 서버의 주소·모델·키를 등록합니다. 공개 주소는 https여야 하고, PC 안(localhost)이나 사설망 주소는 내 PC를 거쳐 보냅니다. | OpenAI 호환 AI 서버의 주소·모델·키를 등록합니다. 공개 HTTPS 주소는 유달리 서버가 직접 요청하며, PC 내부 또는 사설망 주소는 내 PC 연결을 거쳐 요청합니다. 업무 내용은 등록한 AI로 전송되며, 처리 국가와 보관 조건은 해당 AI 운영자에 따릅니다. |
| settings_ai_add_open | core/web/templates/settings/ai.html:19 | 개인 AI 입력 칸 열기 | 개인 AI 입력 칸 열기 |
| settings_ai_add_submit | core/web/templates/settings/ai.html:22 | 개인 AI 등록 | 개인 AI 등록 |
| assist_src_name | core/web/templates/settings/_ai_fields.html:3 | 이름 | 이름 |
| assist_src_url_help | core/web/templates/settings/_ai_fields.html:5 | …/v1까지 입력해 주세요. 예: https://api.example.com/v1, http://localhost:11434/v1 | /v1까지 입력해 주세요. 예: https://api.example.com/v1, http://localhost:11434/v1 |
| assist_src_model | core/web/templates/settings/_ai_fields.html:6 | 모델 | 모델 |
| assist_src_key | core/web/templates/settings/_ai_fields.html:8 | 키 | 키 / 설정됨 / 미설정 / 변경할 때만 입력 |
| assist_src_key_clear | core/web/templates/settings/_ai_fields.html:9 | {% if key_set %} 저장한 키 지우기{% endif %} | 저장한 키 삭제 |
| assist_src_pc_help | core/web/templates/settings/_ai_fields.html:15 | 주소가 PC 안(localhost)이나 사설망이면 이 PC가 대신 부릅니다. 공개 주소면 고르지 않아도 됩니다. | PC 내부(localhost) 또는 사설망 주소는 선택한 내 PC를 거쳐 요청합니다. 공개 HTTPS 주소에는 PC 선택이 필요하지 않습니다. |
| assist_src_pc_none | core/web/templates/settings/_ai_fields.html:17 | PC 안이나 사설망의 AI를 쓰려면 먼저 내 PC를 연결해 주세요. | PC 내부 또는 사설망의 AI를 사용하려면 먼저 [내 PC 연결]에서 PC를 연결해 주세요. |
| assist_test_ok | core/web/templates/settings/_ai_result.html:3 | {% else %}연결되었습니다. 모델 {{ count }}개를 확인했습니다.{% if list_id %} 모델 칸에서 고를 수 있습니다.{% endif %}{% endif %} | 연결되었습니다. 모델 {{ count }}개를 확인했습니다. 모델 입력 칸에서 선택할 수 있습니다. |
| assist_src_state | core/web/templates/settings/_ai_source.html:7 | {% if s.enabled %}사용{% else %}꺼짐{% endif %} | 켜짐 / 꺼짐 |
| assist_src_org_help | core/web/templates/settings/_ai_source.html:11 | {% if s.kind == "org" %}작업하는 조직의 관리자가 등록한 AI입니다. 주소·모델은 조직마다 다르고, 조직 설정에 따라 쓸 수 없거나 하루 한도가 있을 수 있습니다. | 작업 중인 조직의 관리자가 등록한 AI입니다. 기본 사용 권한은 구성원 누구나이며, 구성원 1명당 하루 30회까지 사용할 수 있습니다. 관리자는 하루 한도에서 제외됩니다. 관리자는 사용 권한을 관리자만으로 제한하거나 하루 한도를 변경할 수 있습니다. |
| assist_src_pc_unlinked | core/web/templates/settings/_ai_source.html:12 | {% elif s.route == "pc" and not s.server %}⚠ 연결된 PC가 없습니다. 아래 [PC 다시 고르기]에서 거쳐 갈 내 PC를 골라 주세요. | 개인 AI에 연결된 내 PC가 없습니다. [PC 다시 고르기]에서 연결할 내 PC를 선택해 주세요. |
| assist_src_pc_via | core/web/templates/settings/_ai_source.html:13 | {% elif s.route == "pc" %}{{ s.base_url }} · {{ s.server.name }}을 거쳐 보냅니다. | {{ s.base_url }} · 내 PC {{ s.server.name }}을 거쳐 요청합니다. |
| assist_src_last_error | core/web/templates/settings/_ai_source.html:15 | {% if s.last_error %}⚠ 최근 오류: {{ s.error_label }}{% endif %} | 최근 오류: {{ s.error_label }} |
| assist_src_toggle | core/web/templates/settings/_ai_source.html:19 | {% csrf_token %}{% if s.enabled %}이 AI 끄기{% else %}이 AI 켜기{% endif %} | 이 AI 끄기 / 이 AI 켜기 |
| assist_src_delete_confirm | core/web/templates/settings/_ai_source.html:25 | {% csrf_token %}개인 AI 삭제 | 개인 AI ‘{{ s.name }}’ 설정과 저장한 키를 삭제합니다. 다시 사용하려면 새로 등록해야 합니다. |
| assist_src_edit | core/web/templates/settings/_ai_source.html:31 | {% if s.route == "pc" and not s.server %}PC 다시 고르기{% else %}{{ s.name }} 고치기{% endif %} | PC 다시 고르기 / {{ s.name }} 수정 |
| assist_src_save | core/web/templates/settings/_ai_source.html:34 | 개인 AI 저장 | 개인 AI 저장 |
| settings_ai_tab | core/web/templates/settings/_tabs.html:8 | 프로필   환경설정   API 토큰   내 PC 연결   AI{# | AI |
| ai_err_generic | core/web/views/assist.py:25 | AI가 글을 쓰지 못했습니다(오류 코드 {code}). 잠시 후 다시 요청해 주세요. | AI 요청을 완료하지 못했습니다(오류 코드 {code}). 잠시 후 다시 요청해 주세요. |
| ai_err_field | core/web/views/assist.py:26 | 이 칸은 AI로 쓸 수 없습니다. | 이 칸은 AI 자동완성을 지원하지 않습니다. AI로 쓰기 버튼이 있는 칸에서 요청해 주세요. |
| ai_err_target | core/web/views/assist.py:27 | 대상을 먼저 골라 주세요. | 요청할 대상이 선택되지 않았습니다. 대상 태스크·문서·프로젝트를 선택해 주세요. |
| ai_err_rate | core/web/views/assist.py:28 | AI 요청이 너무 많습니다. 진행 중인 작업이 끝난 뒤 다시 요청해 주세요. | 동시에 처리할 수 있는 AI 요청 수를 넘었습니다. 진행 중인 작업이 끝난 뒤 다시 요청해 주세요. |
| ai_err_conflict | core/web/views/assist.py:29 | 다른 사람이 먼저 본문을 고쳐 적용하지 못했습니다. 새로고침한 뒤 다시 요청해 주세요. | 요청 후 본문이 변경되어 적용하지 못했습니다. 새로고침하여 본문을 확인한 뒤 다시 요청해 주세요. |
| ai_org_count | core/web/views/assist.py:69 | 오늘 조직 AI {services.today_org_count(user, org)}/{limit} | 오늘 조직 AI {n}/{limit} |
| ai_by_org | core/web/views/assist.py:75 | 조직 AI | 조직 AI |
| ai_by_pc | core/web/views/assist.py:77 | 내 PC 거쳐 보내기 · {name} | 개인 AI · {name} · 내 PC 거쳐 보내기 |
| ai_by_personal | core/web/views/assist.py:79 | 개인 AI · {name} | 개인 AI · {name} |
| ai_pick_none | core/web/views/assist.py:241 | 만들 후보를 하나 이상 골라 주세요. | 선택한 태스크 후보가 없습니다. 만들 후보를 하나 이상 선택해 주세요. |
| assist_err_connect_failed | core/web/views/assist_settings.py:35 | AI 서버에 접속할 수 없습니다. 주소를 확인해 주세요. | AI 서버에 연결하지 못했습니다. 서버 주소와 연결 상태를 확인해 주세요. |
| assist_err_timeout | core/web/views/assist_settings.py:36 | AI 서버가 제때 응답하지 않았습니다. 잠시 뒤 다시 시도해 주세요. | AI 서버가 제한 시간 안에 응답하지 않았습니다. 잠시 후 다시 시도해 주세요. |
| assist_err_http_4xx | core/web/views/assist_settings.py:37 | AI 서버가 요청을 거절했습니다. 주소를 확인해 주세요. | AI 서버가 요청을 거부했습니다. 서버 주소·모델·키와 서버의 이용 조건을 확인해 주세요. |
| assist_err_http_5xx | core/web/views/assist_settings.py:38 | AI 서버에 오류가 났습니다. 잠시 뒤 다시 시도해 주세요. | AI 서버에 오류가 발생했습니다. 잠시 후 다시 시도해 주세요. |
| assist_err_auth_failed | core/web/views/assist_settings.py:39 | 키가 맞지 않습니다. 키를 확인해 주세요. | AI 서버에서 키를 인증하지 못했습니다. 키의 유효 기간과 사용 권한을 확인해 주세요. |
| assist_err_model_not_found | core/web/views/assist_settings.py:40 | 모델을 찾을 수 없습니다. 모델 이름을 확인해 주세요. | AI 서버에서 지정한 모델을 찾지 못했습니다. 모델 이름을 확인해 주세요. |
| assist_err_bad_output | core/web/views/assist_settings.py:41 | AI 응답을 읽지 못했습니다. 다시 시도하고, 계속되면 OpenAI 호환 주소·모델인지 확인해 주세요. | AI 응답이 필요한 형식과 맞지 않습니다. 다시 시도하고, 계속되면 서버와 모델의 OpenAI 호환 여부를 확인해 주세요. |
| assist_err_too_large | core/web/views/assist_settings.py:42 | AI 서버의 응답이 너무 큽니다. | AI 응답이 허용 크기를 넘었습니다. 요청 범위를 줄이거나 다른 모델로 다시 시도해 주세요. |
| assist_err_blocked_address | core/web/views/assist_settings.py:43 | 이 주소로는 보낼 수 없습니다. 공개 https 주소이거나 운영자가 허용한 주소여야 합니다. | 보안 제한으로 AI 서버에 연결하지 못했습니다. 개인 AI는 주소와 내 PC 연결을 확인하고, 조직 AI는 관리자에게 공개 HTTPS 주소 또는 허용 호스트 설정 확인을 요청해 주세요. |
| assist_err_pc_offline | core/web/views/assist_settings.py:44 | 거쳐 갈 PC가 꺼져 있습니다. | 요청을 보낼 내 PC에 연결할 수 없습니다. PC에서 내 PC 연결을 실행한 뒤 다시 시도해 주세요. |
| assist_err_pc_unlinked | core/web/views/assist_settings.py:45 | 연결된 PC가 없습니다. | 개인 AI에 연결된 내 PC가 없습니다. 설정 > AI에서 [PC 다시 고르기]를 눌러 연결할 PC를 선택해 주세요. |
| assist_err_pc_error | core/web/views/assist_settings.py:46 | PC에서 AI 서버를 부르지 못했습니다. | 내 PC에서 AI 서버에 요청하지 못했습니다. PC의 연결 상태와 AI 서버 주소·모델·키를 확인해 주세요. |
| assist_err_no_source | core/web/views/assist_settings.py:48 | 쓸 수 있는 AI가 없거나 대상을 더 볼 수 없습니다. 설정의 AI 탭에서 개인 AI를 등록하거나 조직 관리자에게 조직 AI 등록을 요청해 주세요. | 사용 가능한 AI가 없거나 대상에 접근할 수 없습니다. 대상 접근 권한과 설정 > AI의 사용 여부·사용 순서를 확인하고, 조직 AI는 관리자에게 등록·권한·하루 한도 확인을 요청해 주세요. |
| assist_err_no_worker | core/web/views/assist_settings.py:49 | AI 작업을 처리할 곳이 없어 멈췄습니다. 잠시 뒤 다시 요청해 주세요. | AI 작업을 처리할 수 없어 요청이 중단되었습니다. 잠시 후 다시 요청하고, 계속되면 서비스 운영자에게 문의해 주세요. |
| assist_err_org_disabled | core/web/views/assist_settings.py:50 | 이 조직은 AI 자동완성을 쓰지 않도록 설정되어 있습니다. | 이 조직의 AI 자동완성이 꺼져 있습니다. 사용이 필요하면 조직 관리자에게 문의해 주세요. |
| assist_cancelled | core/web/views/assist_settings.py:51 | 작업을 취소했습니다. | AI 작업을 취소했습니다. |
| assist_err_unknown | core/web/views/assist_settings.py:53 | AI 서버를 부르지 못했습니다. | AI 서버에 요청하지 못했습니다. 연결 상태와 AI 설정을 확인한 뒤 다시 시도해 주세요. |
| assist_src_name_invalid | core/web/views/assist_settings.py:102 | 이름을 50자 이내로 입력해 주세요. | 이름이 없거나 50자를 넘었습니다. 이름을 50자 이내로 입력해 주세요. |
| assist_src_url_required | core/web/views/assist_settings.py:105 | AI 서버 주소를 300자 이내로 입력해 주세요. | AI 서버 주소가 없거나 300자를 넘었습니다. 주소를 300자 이내로 입력해 주세요. |
| assist_src_model_long | core/web/views/assist_settings.py:108 | 모델 이름은 200자 이내여야 합니다. | 모델 이름이 200자를 넘었습니다. 모델 이름을 200자 이내로 입력해 주세요. |
| assist_src_pc_required | core/web/views/assist_settings.py:122 | PC 안이나 사설망 주소는 내 PC를 거쳐 보냅니다. 거쳐 갈 내 PC를 골라 주세요. | PC 내부 또는 사설망 주소는 내 PC를 거쳐 요청해야 합니다. 연결할 내 PC를 선택해 주세요. |
| assist_src_key_no_crypto | core/web/views/assist_settings.py:132 | 서버의 암호화 설정이 없어 키를 저장할 수 없습니다. 서비스 운영자에게 문의해 주세요. | 서버의 암호화 설정이 없어 키를 저장할 수 없습니다. 서비스 운영자에게 문의해 주세요. |
| assist_src_limit | core/web/views/assist_settings.py:162 | 개인 AI는 {AiSource.MAX_PERSONAL}개까지 등록할 수 있습니다. | 개인 AI 등록 한도인 {max}개에 도달했습니다. 새로 등록하려면 사용하지 않는 개인 AI를 삭제해 주세요. |
| assist_src_added | core/web/views/assist_settings.py:171 | 개인 AI '{src.name}'을 등록했습니다. | 개인 AI ‘{name}’을 등록했습니다. |
| assist_src_saved | core/web/views/assist_settings.py:192 | '{src.name}' 설정을 저장했습니다. | 개인 AI ‘{name}’ 설정을 저장했습니다. |
| assist_src_deleted | core/web/views/assist_settings.py:223 | 개인 AI '{src.name}'을 삭제했습니다. | 개인 AI ‘{name}’을 삭제했습니다. |
| assist_org_url_required | core/web/views/assist_settings.py:275 | 조직 AI 주소를 입력해 주세요. | 조직 AI 주소가 없습니다. 조직 AI 서버 주소를 입력해 주세요. |
| ops_assist_host_invalid | core/web/views/assist_settings.py:318 | 호스트 이름이나 IP 주소만 입력해 주세요. 주소 앞의 http://, 포트, 경로, *는 넣지 않습니다. | 허용 호스트 형식이 올바르지 않습니다. 호스트 이름 또는 IP 주소만 입력하고, http://·https://·포트·경로·*는 제외해 주세요. |
| ops_assist_host_dup | core/web/views/assist_settings.py:334 | 이미 목록에 있는 호스트입니다. | 이미 등록된 허용 호스트입니다. 목록에서 해당 호스트를 확인해 주세요. |
| ops_assist_host_added | core/web/views/assist_settings.py:343 | 허용 호스트 {host}를 추가했습니다. | 허용 호스트 {host}를 추가했습니다. |
| ops_assist_delete_title | core/web/views/assist_settings.py:362 | 허용 호스트 삭제 — {row.host} | 허용 호스트 삭제 · {host} |
| ops_assist_delete_summary | core/web/views/assist_settings.py:363 | 이 주소를 쓰는 조직 AI는 다음 요청부터 막힙니다. | 이 호스트를 사용하는 조직 AI는 다음 요청부터 차단됩니다. |
| ops_assist_host_removed | core/web/views/assist_settings.py:377 | 허용 호스트 {host}를 삭제했습니다. | 허용 호스트 {host}를 삭제했습니다. |

## 묶음 키·표시 없는 자리의 확정 키

아래 키는 문구 적용 작업자가 코드에 추가할 식별자입니다. 기존 data-ai 입력 칸에는 ai_write 공통 버튼을 사용하며, 입력 칸 자체의 기존 라벨은 바꾸지 않습니다. 버튼의 접근성 이름에도 같은 최종 용어를 적용합니다.

| 키 | 위치(파일:줄) | 현재 임시 문구 | 최종 문구 |
|---|---|---|
| ai_job_queued | core/web/templates/assist/_job.html:4 | AI 작업이 차례를 기다리고 있습니다. | AI 작업이 차례를 기다리고 있습니다. |
| ai_job_running | core/web/templates/assist/_job.html:4 | AI가 쓰는 중입니다. 대화상자를 닫으면 작업을 취소합니다. | AI가 작성 중입니다. 대화상자를 닫으면 작업이 취소됩니다. |
| ai_job_cancelling | core/web/templates/assist/_job.html:4 | AI 작업을 취소하는 중입니다. | AI 작업을 취소하는 중입니다. |
| ai_job_cancel | core/web/templates/assist/_job.html:5 | AI 작업 취소 | AI 작업 취소 |
| ai_job_retry | core/web/templates/assist/_job.html:8 | 다시 쓰기 | 다시 쓰기 |
| ai_job_line_help | core/web/templates/assist/_job.html:10 | 하나를 고르면 칸에 넣습니다. 칸의 저장 방식대로 저장됩니다. | 결과를 확인한 뒤 하나를 선택해 주세요. 선택한 결과를 칸에 적용하며, 해당 칸의 저장 방식에 따라 저장됩니다. |
| ai_job_line_empty | core/web/templates/assist/_job.html:13 | AI가 고를 만한 글을 내지 못했습니다. [다시 쓰기]를 눌러 주세요. | AI가 선택할 결과를 만들지 못했습니다. [다시 쓰기]를 눌러 주세요. |
| ai_job_list_legend | core/web/templates/assist/_job.html:19 | 추가할 체크 항목 | 추가할 체크 항목 |
| ai_job_list_empty | core/web/templates/assist/_job.html:21 | AI가 체크 항목을 내지 못했습니다. [다시 쓰기]를 눌러 주세요. | AI가 체크 항목을 만들지 못했습니다. [다시 쓰기]를 눌러 주세요. |
| ai_job_list_apply | core/web/templates/assist/_job.html:24 | 고른 항목 추가 | 고른 항목 적용 |
| ai_job_preview | core/web/templates/assist/_job.html:29 | AI가 쓴 글 미리보기 | AI 결과 미리보기 |
| ai_job_replace_field | core/web/templates/assist/_job.html:32 | 칸 내용 바꾸기 | 적용 · 칸 내용 바꾸기 |
| ai_job_append_field | core/web/templates/assist/_job.html:33 | 칸 뒤에 붙이기 | 적용 · 칸 뒤에 추가 |
| ai_job_append_body | core/web/templates/assist/_job.html:36 | 본문 뒤에 붙이기 | 적용 · 본문 뒤에 추가 |
| ai_job_replace_body | core/web/templates/assist/_job.html:38 | 본문 바꾸기 | 적용 · 본문 바꾸기 |
| ai_job_version_help | core/web/templates/assist/_job.html:44 | 적용하면 지금 본문이 이전 버전에 남습니다. | 미리보기를 확인한 뒤 적용해 주세요. 적용 전 본문은 이전 버전에 남습니다. |
| ai_job_source | core/web/templates/assist/_job.html:46 | 쓴 AI: {{ source_line }} | 사용한 AI: {{ source_line }} |
| ai_candidates_intro | core/web/templates/assist/_candidates.html:4 | 만들 후보를 고르고 고친 뒤 아래 버튼을 눌러 주세요. 담당자·기한은 AI가 추정한 값입니다. | 태스크로 만들 후보를 선택하고 내용을 확인·수정해 주세요. 담당자와 기한은 AI가 추정한 값입니다. |
| ai_candidates_scroll | core/web/templates/assist/_candidates.html:5 | 표를 좌우로 밀어 전체 항목을 확인해 주세요. | 표를 좌우로 이동하여 전체 항목을 확인해 주세요. |
| ai_candidates_table | core/web/templates/assist/_candidates.html:6 | 태스크 후보 표, 좌우로 스크롤 가능 | 태스크 후보 표 · 좌우로 이동 가능 |
| ai_candidates_headers | core/web/templates/assist/_candidates.html:8 | 고르기 / 제목·설명 / 담당자 / 기한 / 프로젝트 | 선택 / 제목·설명 / 담당자 / 기한 / 프로젝트 |
| ai_candidates_created | core/web/templates/assist/_candidates.html:13 | 만듦 | 생성됨 |
| ai_candidates_pick | core/web/templates/assist/_candidates.html:16 | 후보 {{ forloop.counter }} 고르기 | 태스크 후보 {{ forloop.counter }} 선택 |
| ai_candidates_title | core/web/templates/assist/_candidates.html:18 | 후보 {{ forloop.counter }} 제목 | 태스크 후보 {{ forloop.counter }} 제목 |
| ai_candidates_description | core/web/templates/assist/_candidates.html:19 | 설명 / 후보 {{ forloop.counter }} 설명 | 설명 / 태스크 후보 {{ forloop.counter }} 설명 |
| ai_candidates_evidence | core/web/templates/assist/_candidates.html:22 | 근거: {{ r.c.evidence }} | 근거: {{ r.c.evidence }} |
| ai_candidates_similar | core/web/templates/assist/_candidates.html:23 | 비슷한 태스크 / 그 태스크 열기 | 비슷한 태스크 / 태스크 열기 |
| ai_candidates_assignee | core/web/templates/assist/_candidates.html:27 | 후보 {{ forloop.counter }} 담당자 | 태스크 후보 {{ forloop.counter }} 담당자 |
| ai_candidates_self | core/web/templates/assist/_candidates.html:28 | 나 | 나 |
| ai_candidates_assignee_check | core/web/templates/assist/_candidates.html:31 | 이름 확인 필요 | 담당자 확인 필요 |
| ai_candidates_due | core/web/templates/assist/_candidates.html:33 | 후보 {{ forloop.counter }} 기한 | 태스크 후보 {{ forloop.counter }} 기한 |
| ai_candidates_project | core/web/templates/assist/_candidates.html:35 | 후보 {{ forloop.counter }} 프로젝트 | 태스크 후보 {{ forloop.counter }} 프로젝트 |
| ai_candidates_create | core/web/templates/assist/_candidates.html:46 | 고른 후보로 태스크 만들기 | 고른 후보로 태스크 만들기 |
| ai_candidates_retry | core/web/templates/assist/_candidates.html:47 | 후보 다시 뽑기 | 후보 다시 뽑기 |
| ai_candidates_empty | core/web/templates/assist/_candidates.html:50 | AI가 태스크 후보를 찾지 못했습니다. 내용이 짧으면 후보가 없을 수 있습니다. | AI가 태스크 후보를 찾지 못했습니다. 원문 내용을 확인한 뒤 [후보 다시 뽑기]를 눌러 주세요. |
| ai_doc_menu | core/web/templates/docs/index.html:56 | AI로 쓰기 | AI로 쓰기 |
| ai_doc_fill | core/web/templates/docs/index.html:58 | AI로 본문 채우기 | AI로 본문 쓰기 |
| ai_doc_continue | core/web/templates/docs/index.html:59 | AI로 이어 쓰기 | AI로 이어 쓰기 |
| ai_doc_template_select | core/web/templates/docs/index.html:61 | AI가 따를 템플릿 / 템플릿 고르기 | 사용할 템플릿 / 템플릿 선택 |
| ai_doc_template | core/web/templates/docs/index.html:65 | AI로 템플릿 틀에 맞춰 다시 쓰기 | AI로 템플릿에 맞춰 쓰기 |
| ai_close | core/web/templates/base.html:157 | 닫기 | 닫기 |
| ai_minutes_no_transcript | core/web/templates/notes/list.html:64 | 전사문이 있어야 쓸 수 있습니다. | 전사문이 있어야 회의록을 작성할 수 있습니다. |
| assist_src_url_label | core/web/templates/settings/_ai_fields.html:4 | AI 서버 주소 | AI 서버 주소 |
| assist_src_pc_label | core/web/templates/settings/_ai_fields.html:11 | 거쳐 갈 내 PC / PC 고르기 | 연결할 내 PC / 내 PC 선택 |
| assist_src_move | core/web/templates/settings/_ai_source.html:17 | 순서 올리기 / 순서 내리기 | 순서 올리기 / 순서 내리기 |
| assist_src_test | core/web/templates/settings/_ai_source.html:21 | 연결 시험 | 연결 확인 |
| assist_src_models | core/web/templates/settings/_ai_source.html:22 | 모델 불러오기 | 모델 불러오기 |
| assist_src_delete | core/web/templates/settings/_ai_source.html:25 | 개인 AI 삭제 | 개인 AI 삭제 |
| assist_org_level_choices | core/orgs/settings.py:271 | 멤버 누구나 / 조직 관리자만 | 구성원 누구나 / 관리자만 |
| assist_route_direct | core/assist/models.py:26 | 서버가 직접 / 내 PC 거쳐 보내기 / 조직 AI | 유달리 서버에서 요청 |
| assist_route_pc | core/assist/models.py:26 | 서버가 직접 / 내 PC 거쳐 보내기 / 조직 AI | 내 PC 거쳐 보내기 |

## 구현·법률 확인 사항

- 기본 켬은 전송 시작을 뜻하지 않습니다. AI 등록과 이용자의 요청이 있어야 전송합니다. 조직 설정을 끄면 해당 조직의 내용은 개인 AI에도 보내지 않습니다.
- 적용 버튼은 동작을 구분하면서 ‘적용’을 표시합니다. 짧은 칸의 선택형 결과는 선택 자체가 적용이며, 문서·회의록 본문 적용 전 내용만 이전 버전으로 안내합니다.
- ai_org_count는 현재 조직 설정 한도를 표시합니다(기본 30). 관리자와 무제한 조직에는 유한 한도 문구를 표시하지 않습니다. 요청 수와 태스크 후보에서 만든 태스크 수를 혼동하지 않습니다.
- assist_url_blocked는 루프백 등 등록해도 차단되는 주소를 허용할 수 있다고 보장하지 않습니다.
- 개인 AI 경로의 최근 오류에는 조직 전용 허용 호스트 안내만 표시하지 않습니다.
- 국외 이전 동의의 법적 근거와 조직별 수신자 고지의 구체화는 privacy-v3.md·terms-v2.md 끝의 ‘검토 필요’에 정리했습니다. L10의 DOC_VERSIONS 변경과 로그인 재동의는 구현 담당 작업이며 이 산출물은 코드를 바꾸지 않습니다.

## 추가 키

칸 안 AI 버튼과 칸 아래 패널, Codex 종류 선택 도입 뒤 추가된 문구입니다. **AI 문구 26행: 신규 키 제안 24개(표시 없는 자리 7개와 Codex 구분 오류 키 1개 포함), 기존 키 재확정 2개**입니다. 기존 표의 같은 키는 이 절의 문구를 우선합니다. 약관 시행일 문장은 별도 제안이며 AI 키 수에는 포함하지 않습니다.

| 키 | 위치(파일:줄) | 현재 임시 문구 | 최종 문구 |
|---|---|---|---|
| ai_autocomplete_cancel | core/web/static/ai-fill.js:17 | AI 자동완성 취소 | AI 자동완성 취소 |
| ai_cancelled | core/web/static/ai-fill.js:111 | AI 자동완성을 취소했습니다. | AI 자동완성을 취소했습니다. |
| ai_filled | core/web/static/ai-fill.js:146 | AI가 칸을 채웠습니다. | AI가 칸을 채웠습니다. 내용을 확인한 뒤 저장해 주세요. |
| ai_undo | core/web/static/ai-fill.js:148 | 되돌리기 | 되돌리기 |
| ai_preview | core/web/static/ai-fill.js:158 | AI 미리보기입니다. 적용해야 저장됩니다. | AI 결과 미리보기입니다. [적용] 또는 [뒤에 붙이기]를 눌러야 저장됩니다. |
| ai_apply | core/web/static/ai-fill.js:160 | 적용 | 적용 |
| ai_append | core/web/static/ai-fill.js:161 | 뒤에 붙이기 | 뒤에 붙이기 |
| ai_discard | core/web/static/ai-fill.js:129,162 | 버리기 | 버리기 |
| assist_err_codex_missing | core/web/views/assist_settings.py:47 | PC에 Codex CLI가 없습니다. Codex를 설치한 뒤 다시 시도해 주세요. | 선택한 내 PC에 Codex가 설치되어 있지 않습니다. 해당 PC에 Codex를 설치하고 로그인한 뒤 다시 시도해 주세요. |
| assist_err_codex_link_update（신규 원인 구분 키 제안） | core/web/views/assist_settings.py:47（현재 codex_missing 공용, 분기 추가 필요） | 옛 udally-link의 Codex 미지원과 Codex 미설치를 같은 오류로 표시 | 선택한 내 PC의 udally-link가 Codex를 지원하지 않는 버전입니다. 해당 PC의 udally-link를 최신 버전으로 업데이트한 뒤 다시 시도해 주세요. |
| assist_err_codex_auth | core/web/views/assist_settings.py:48 | PC의 Codex가 로그인되어 있지 않습니다. PC에서 codex login을 실행해 주세요. | 선택한 내 PC의 Codex에 로그인되어 있지 않습니다. 해당 PC에서 `codex login`으로 로그인한 뒤 다시 시도해 주세요. |
| assist_err_rate | core/web/views/assist_settings.py:49 | 오늘 쓸 수 있는 조직 AI 횟수를 다 썼습니다. 내일 다시 쓰거나 개인 AI를 등록해 주세요. | 오늘의 조직 AI 사용 한도에 도달했습니다. 내일 다시 시도하거나 설정 > AI에서 개인 AI를 등록해 주세요. |
| assist_src_backend | core/web/templates/settings/_ai_fields.html:5-8 | 종류 / OpenAI 호환 AI 서버 / Codex(내 구독, 내 PC) | 종류 / OpenAI 호환 AI 서버 / Codex(내 구독, 내 PC) |
| assist_src_codex_help | core/web/templates/settings/_ai_fields.html:9 | Codex는 고른 내 PC에 설치·로그인된 Codex CLI로 씁니다. 주소·키는 필요 없고, 구독 정보는 PC 밖으로 나가지 않습니다. | Codex는 선택한 내 PC에 설치·로그인된 Codex CLI로 사용합니다. AI 서버 주소와 키는 입력하지 않습니다. 구독 인증 정보는 내 PC에 보관됩니다. |
| assist_src_codex_pc_required | core/web/views/assist_settings.py:129 | Codex는 내 PC에서 실행합니다. Codex가 설치·로그인된 내 PC를 골라 주세요. | Codex를 사용할 내 PC를 선택해 주세요. 해당 PC에 Codex가 설치되어 있고 로그인되어 있어야 합니다. |
| assist_src_codex_via | core/web/templates/settings/_ai_source.html:13 | {name}의 Codex CLI로 씁니다. | {name}에 설치된 Codex로 요청합니다. |
| assist_src_model_codex_help | core/web/templates/settings/_ai_fields.html:13 | Codex는 비우면 Codex 기본 모델을 씁니다. | 모델을 비워 두면 선택한 내 PC의 Codex 기본 모델을 사용합니다. |
| assist_src_codex_badge（표시 없는 자리） | core/web/templates/settings/_ai_source.html:8 | Codex(내 구독) | Codex(내 구독) |
| assist_src_codex_default_model（표시 없는 자리） | core/web/templates/settings/_ai_source.html:9 | Codex 기본 모델 | Codex 기본 모델 |
| assist_src_model_empty（표시 없는 자리） | core/web/templates/settings/_ai_source.html:9 | 모델 미입력 | 모델 미입력 |
| assist_src_kind_label（표시 없는 자리） | core/web/templates/settings/_ai_fields.html:5 | 종류 | 종류 |
| assist_src_openai_url_label（표시 없는 자리） | core/web/templates/settings/_ai_fields.html:10 | AI 서버 주소(OpenAI 호환일 때) | AI 서버 주소(OpenAI 호환 AI 서버용) |
| ai_previous_candidate（표시 없는 자리） | core/web/static/ai-fill.js:147,159 | 이전 후보 | 이전 후보 |
| ai_next_candidate（표시 없는 자리） | core/web/static/ai-fill.js:147,159 | 다음 후보 | 다음 후보 |
| ai_job_running（재확정） | core/web/templates/assist/_job.html:4 | AI가 쓰는 중입니다. / 기존 초안: 대화상자를 닫으면 작업이 취소됩니다. | AI가 작성 중입니다. 취소하려면 [AI 작업 취소]를 눌러 주세요. |
| ai_err_unknown（재확정） | core/web/static/ai-fill.js:265 | 요청을 처리하지 못했습니다. 잠시 뒤 다시 시도해 주세요. / 기존 초안: 대화상자를 닫고 다시 시도해 주세요. | 요청을 처리하지 못했습니다. 잠시 후 다시 시도해 주세요. |

- `assist_src_backend`의 선택지 묶음과 `assist_src_kind_label`의 라벨은 같은 ‘종류’를 사용합니다. 라벨을 별도 키로 분리할 때도 화면에 중복 출력하지 않습니다.
- `ai_job_running`은 대화상자와 칸 아래 패널 모두 실제로 제공하는 [AI 작업 취소]를 안내합니다. 대화상자 닫기·칸 안 스피너 재클릭의 취소 동작은 각 버튼의 접근성 이름으로 알립니다.
- `ai_preview`의 [뒤에 붙이기]는 긴 글 미리보기에만 있습니다. 한 줄 후보에는 “AI 결과 미리보기입니다. [적용]을 눌러야 저장됩니다.”로 분기합니다.
- `codex_missing`만으로는 구버전 udally-link의 기능 미지원과 Codex 미설치를 확정할 수 없습니다. 구현 담당자는 PC 기능 지원 정보로 구버전을 먼저 구분하여 `assist_err_codex_link_update`를 표시하고, Codex 실행 파일 부재가 확인된 경우만 `assist_err_codex_missing`을 표시해 주세요. 원인 확인이 안 된 상태에는 “선택한 내 PC에서 Codex를 사용할 수 없습니다. udally-link 버전과 Codex 설치·로그인 상태를 확인해 주세요.”를 사용합니다. 이 문서는 원인 분기를 구현하지 않았습니다.
- 구독 인증 정보 보관 안내는 업무 내용이 PC에만 머문다는 뜻이 아닙니다. 입력과 필요한 맥락은 Codex의 AI 서비스로 전송될 수 있으므로 기존 전송 고지를 유지합니다.

### 약관 부칙 시행일

| 키 | 위치(파일:줄) | 현재 임시 문구 | 최종 문구 |
|---|---|---|---|
| terms_effective_date（문장 제안, AI 키 수 제외） | core/web/content/terms.md:151（부칙） | 이 약관은 배포 시 확정한 시행일부터 적용합니다. | 이 약관은 2026년 10월 13일부터 시행합니다. |

약관 원본 및 HTML은 수정하지 않았습니다. 문구 적용 담당자가 두 산출물의 시행일을 함께 반영해 주세요.

