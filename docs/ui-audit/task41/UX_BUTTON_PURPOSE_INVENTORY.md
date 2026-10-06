# UI-UX 전체 버튼·링크 목적성 인벤토리

2026-10-04 · 현재 UI-UX 소스 기준. 앱 수정 없음.

템플릿 62개 전체에서 컨트롤 위치 304곳, URL 이름 118개를 대조했다.

한 행은 템플릿의 컨트롤 위치다. 반복 데이터 개수와 조건 분기를 펼친 실제 DOM 개수가 아니다. 조건부 문구는 병기한다.
입력 컨트롤의 현재 값·선택지, 아이콘과 접근성 이름도 함께 기록한다. JS가 숨기는 fallback 저장 버튼은 별도 판정한다.
GET/POST는 클릭·폼 제출을 구분한다. 펼치기·취소·복사 등 JS 동작은 상위 폼의 POST보다 우선하여 대조했다.
소스 대응 판정은 실제 동작 성공·모든 권한 분기의 브라우저 통과를 의미하지 않는다. 외부 URL 값과 데이터별 제목은 미확정이다.

[최종 검토·범위·Astra 화면 검증](UX_BUTTON_PURPOSE_REVIEW.md) · [원시 속성·라우트 JSON](button-purpose-inventory.json)

## auth/join.html

| ID·근거 | 현재 문구 / 접근성 이름 | 사용자 목적 | 예상·실제 결과 | 권장 문구·보조 안내 | 동작 근거·판정 |
| --- | --- | --- | --- | --- | --- |
| B001 · `core/web/templates/auth/join.html:9` | 가입하고 참여하기 | 계정을 만들고 초대 조직 참여 준비 | GET signup?next=join → 가입 후 참여 확인 페이지; 즉시 조직 참여 아님 | 가입 후 참여하기 / 계정 만들기 + 후속 참여 안내 | core/web/views/auth.py:15 · 개별 검토 |
| B002 · `core/web/templates/auth/join.html:10` | 이미 계정이 있습니다 · 로그인 | 로그인 | GET · 로그인 화면; POST 세션 로그인 | 유지 | core/web/urls.py:39 · 소스 동작 대조 |
| B003 · `core/web/templates/auth/join.html:24` | 조직에 참여하기 | 초대받은 조직에 참여 | POST join_by_token으로 실제 참여 후 오늘 이동 | 조직에 참여하기 | core/web/views/auth.py:29 · 소스 동작 대조 |

## auth/login.html

| ID·근거 | 현재 문구 / 접근성 이름 | 사용자 목적 | 예상·실제 결과 | 권장 문구·보조 안내 | 동작 근거·판정 |
| --- | --- | --- | --- | --- | --- |
| B004 · `core/web/templates/auth/login.html:8` | 로그인 | 계정 로그인 | POST Django LoginView 세션 로그인 | 로그인 | core/web/urls.py:39 · 소스 동작 대조 |
| B005 · `core/web/templates/auth/login.html:10` | 가입 | 새 계정 만들기 | GET · 가입 화면; 유효 POST 계정 생성·로그인·next/조직 목록 이동 | 유지 | core/web/views/auth.py:15 · 소스 동작 대조 |

## auth/signup.html

| ID·근거 | 현재 문구 / 접근성 이름 | 사용자 목적 | 예상·실제 결과 | 권장 문구·보조 안내 | 동작 근거·판정 |
| --- | --- | --- | --- | --- | --- |
| B006 · `core/web/templates/auth/signup.html:7` | 가입 | 새 계정 가입 | POST 계정 생성·로그인 후 next/조직 목록 이동 | 가입 | core/web/views/auth.py:15 · 소스 동작 대조 |
| B007 · `core/web/templates/auth/signup.html:9` | 로그인 | 로그인 | GET · 로그인 화면; POST 세션 로그인 | 유지 | core/web/urls.py:39 · 소스 동작 대조 |

## base.html

| ID·근거 | 현재 문구 / 접근성 이름 | 사용자 목적 | 예상·실제 결과 | 권장 문구·보조 안내 | 동작 근거·판정 |
| --- | --- | --- | --- | --- | --- |
| B008 · `core/web/templates/base.html:17` | {{ current_org.name\|default:"유달리" }} / 접근성: 조직 전환 | 해당 묶음·상세 내용 확인 | HTML details 접힘/펼침; 데이터 변경 없음 | 문맥이 드러나는 현재 제목 유지 | core/web/templates/base.html:17 · 소스 대응 |
| B009 · `core/web/templates/base.html:26` | {{ o.name }} | 조직 업무 확인 | GET · 선택 조직의 개요 표시 | 유지 | core/web/views/orgs.py:65 · 소스 동작 대조 |
| B010 · `core/web/templates/base.html:28` | ＋ 새 조직 만들기 | 새 조직 생성 | GET · GET 생성 폼; 유효 POST 조직 생성 | 조직 만들기 | core/web/views/orgs.py:51 · 소스 동작 대조 |
| B011 · `core/web/templates/base.html:32` | 유달리 | 오늘 할 일 확인 | GET · 오늘 목록; cal/day/quick 파라미터에 따라 달력·빠른 추가 표시 | 유지 | core/web/views/today.py:139 · 소스 동작 대조 |
| B012 · `core/web/templates/base.html:36` | 오늘 | 오늘 할 일 확인 | GET · 오늘 목록; cal/day/quick 파라미터에 따라 달력·빠른 추가 표시 | 유지 | core/web/views/today.py:139 · 소스 동작 대조 |
| B013 · `core/web/templates/base.html:37` | 내 태스크 | 담당 태스크 확인 | GET · 담당자·묶음·정렬·필터 조건에 맞는 태스크 목록 표시 | 유지 | core/web/views/me.py:15 · 소스 동작 대조 |
| B014 · `core/web/templates/base.html:38` | 프로젝트 | 현재 프로젝트 작업 열기 | GET project_index는 최근/첫 프로젝트로 이동; 프로젝트 전체 목록 아님 | 프로젝트 유지 + 현재 프로젝트 전환 손잡이; 목록이라고 안내 금지 | core/web/views/projects.py:67 · 개별 검토 |
| B015 · `core/web/templates/base.html:39` | 조직 | 현재 조직 업무 확인 | GET · 현재 조직 상세로 이동; 없으면 조직 목록 | 유지 | core/web/views/orgs.py:25 · 소스 동작 대조 |
| B016 · `core/web/templates/base.html:40` | 검색 | 태스크 찾기 | GET · 태스크 번호·제목·프로젝트 이름 검색 화면 | 유지 | core/web/views/search.py:10 · 소스 동작 대조 |
| B017 · `core/web/templates/base.html:44` | 빠른 추가 | 새 태스크 입력 시작 | JS 빠른 추가 폼 펼침; 아직 생성 안함 | 태스크 빠른 추가 / 입력 닫기 | core/web/static/app.js:213 · 개별 검토 |
| B018 · `core/web/templates/base.html:46` | 빠른 추가 | 새 태스크 입력 시작 | GET today?quick=1 빠른 추가 폼 표시 | 태스크 빠른 추가 | core/web/views/today.py:139 · 개별 검토 |
| B019 · `core/web/templates/base.html:49` | {{ user.display_name\|initial }} / 접근성: 내 메뉴 | 해당 묶음·상세 내용 확인 | HTML details 접힘/펼침; 데이터 변경 없음 | 문맥이 드러나는 현재 제목 유지 | core/web/templates/base.html:49 · 소스 대응 |
| B020 · `core/web/templates/base.html:52` | 프로필 | 개인 정보·연동 관리 | GET · 프로필·개인 GitHub/Discord 연결 화면 | 유지 | core/web/views/settings.py:16 · 소스 동작 대조 |
| B021 · `core/web/templates/base.html:53` | 내 포트폴리오 | 내 기록으로 초안 준비·확인 | GET · 출처 선택 또는 draft 파라미터의 저장된 초안 표시 | 유지 | core/web/views/portfolio.py:157 · 소스 동작 대조 |
| B022 · `core/web/templates/base.html:54` | API 토큰 | AI·자동화 연결 설정 찾기 | GET 토큰 관리 + 연결 안내 | API 토큰 유지; AI 연결 안내 진입을 보조 링크로 | core/web/views/settings.py:49 · 개별 검토 |
| B023 · `core/web/templates/base.html:55` | 운영 상태 | 운영 상태 확인 | GET · staff 전용 실행 상태 화면 | 유지 | core/web/views/ops.py:21 · 소스 동작 대조 |
| B024 · `core/web/templates/base.html:56` | 로그아웃 | 로그인 종료 | POST · POST 세션 로그아웃 | 유지 | core/web/urls.py:47 · 소스 동작 대조 |
| B025 · `core/web/templates/base.html:65` | 현재 프로젝트 {{ project.name\|default:"프로젝트 선택" }} {{ nav_projects\|length }} / 접근성: 프로젝트 전환, 현재 {{ project.name\|default:'프로젝트 선택' }} | 해당 묶음·상세 내용 확인 | HTML details 접힘/펼침; 데이터 변경 없음 | 문맥이 드러나는 현재 제목 유지 | core/web/templates/base.html:65 · 소스 대응 |
| B026 · `core/web/templates/base.html:78` | {{ p.name\|initial }} {{ p.name }} 미완료 {{ p.open_count }} | 프로젝트 태스크 확인 | GET · 선택 프로젝트 목록 또는 보드 | 유지 | core/web/views/projects.py:182 · 소스 동작 대조 |
| B027 · `core/web/templates/base.html:84` | ＋ 새 프로젝트 | 새 프로젝트 생성 | GET · GET 생성 다이얼로그; 유효 POST 프로젝트 생성 | 새 프로젝트 / 프로젝트 만들기 | core/web/views/projects.py:121 · 소스 동작 대조 |
| B028 · `core/web/templates/base.html:92` | « / 접근성: 프로젝트 목록 접기 | 프로젝트 목록의 공간 조절 | JS 레일 접힘/펼침과 localStorage 저장 | 프로젝트 목록 접기/펼치기 | core/web/static/app.js:29 · JS 동작 대조 |
| B029 · `core/web/templates/base.html:97` | {{ p.name\|initial }} {{ p.name }} {{ p.open_count }} / 접근성: {{ p.name }} | 프로젝트 태스크 확인 | GET · 선택 프로젝트 목록 또는 보드 | 유지 | core/web/views/projects.py:182 · 소스 동작 대조 |
| B030 · `core/web/templates/base.html:105` | ＋ 새 프로젝트 | 새 프로젝트 생성 | GET · GET 생성 다이얼로그; 유효 POST 프로젝트 생성 | 새 프로젝트 / 프로젝트 만들기 | core/web/views/projects.py:121 · 소스 동작 대조 |
| B031 · `core/web/templates/base.html:114` | ✕ / 접근성: 닫기 | 안내 메시지 숨기기 | JS notice DOM 제거; 작업 취소 아님 | 안내 닫기 | core/web/static/app.js:125 · JS 동작 대조 |

## github/issues.html

| ID·근거 | 현재 문구 / 접근성 이름 | 사용자 목적 | 예상·실제 결과 | 권장 문구·보조 안내 | 동작 근거·판정 |
| --- | --- | --- | --- | --- | --- |
| B032 · `core/web/templates/github/issues.html:8` | 저장소 전체 {{ r.full_name }} | 원하는 GitHub 이슈 좁히기 | GET repo/state/q 조건으로 목록 조회 | 저장소·가져온 상태 라벨, 검색 | core/web/views/github.py:291 · 소스 동작 대조 |
| B033 · `core/web/templates/github/issues.html:15` | 안 가져온 것 가져온 것 전부 | 원하는 GitHub 이슈 좁히기 | GET repo/state/q 조건으로 목록 조회 | 저장소·가져온 상태 라벨, 검색 | core/web/views/github.py:291 · 소스 동작 대조 |
| B034 · `core/web/templates/github/issues.html:21` | 찾기 | 원하는 GitHub 이슈 좁히기 | GET repo/state/q 조건으로 목록 조회 | 저장소·가져온 상태 라벨, 검색 | core/web/views/github.py:291 · 소스 동작 대조 |
| B035 · `core/web/templates/github/issues.html:26` | GitHub에서 새로 고침 | GitHub 이슈 갱신 / GitHub 이슈 갱신 | POST · POST 해당 프로젝트/조직 이슈 캐시 갱신; 일부 실패 가능 / POST 해당 프로젝트/조직 이슈 캐시 갱신; 일부 실패 가능 | GitHub에서 새로 고침 / GitHub에서 새로 고침 | core/web/views/github.py:405; core/web/views/github.py:324 · 소스 동작 대조 |
| B036 · `core/web/templates/github/issues.html:33` | #{{ issue.number }} {{ issue.title }} | 관련 자료·설정 열기 | GET https://github.com/{{ issue.connection.full_name }}/issues/{{ issue.number }} 새 탭 | 대상 제목 유지; 변수 URL의 실제 값은 데이터별 확인 필요 | core/web/templates/github/issues.html:33 · 동적 URL/외부 화면 미검증 |
| B037 · `core/web/templates/github/issues.html:44` | 본문 보기 | 이슈 내용 확인 | HTML details 본문 펼침; 외부 이슈 이동 아님 | 본문 보기 유지 | core/web/templates/github/issues.html:44 · 개별 검토 |
| B038 · `core/web/templates/github/issues.html:49` | {{ issue.task.number }} | 태스크 내용 확인 | GET · 태스크 상세 페이지 | 유지 | core/web/views/tasks.py:136 · 소스 동작 대조 |
| B039 · `core/web/templates/github/issues.html:55` | 내 태스크로 가져오기 | 이슈를 내가 맡을 태스크로 등록 / 이슈를 내가 맡을 태스크로 등록 | POST · POST actor 담당 태스크 생성·이슈 연결; 이미 가져왔으면 기존 태스크 반환 / POST actor 담당 태스크 생성·이슈 연결; 이미 가져왔으면 기존 태스크 반환 | 내 태스크로 가져오기 / 내 태스크로 가져오기 | core/web/views/github.py:422; core/web/views/github.py:336 · 소스 동작 대조 |

## me.html

| ID·근거 | 현재 문구 / 접근성 이름 | 사용자 목적 | 예상·실제 결과 | 권장 문구·보조 안내 | 동작 근거·판정 |
| --- | --- | --- | --- | --- | --- |
| B040 · `core/web/templates/me.html:6` | 조직 전체 나 {{ m.display_name }} / 접근성: 팀원 | 담당자·묶음·정렬·필터 조정 | GET me 조회; member=0은 조직 전체, group/sort는 목록 표현 | 조건명 유지; 담당 범위 aria-label을 담당자로 | core/web/views/me.py:15 · 소스 동작 대조 |
| B041 · `core/web/templates/me.html:17` | {{ label }} | 담당자·묶음·정렬·필터 조정 | GET me 조회; member=0은 조직 전체, group/sort는 목록 표현 | 조건명 유지; 담당 범위 aria-label을 담당자로 | core/web/views/me.py:15 · 소스 동작 대조 |
| B042 · `core/web/templates/me.html:21` | {{ label }} | 담당자·묶음·정렬·필터 조정 | GET me 조회; member=0은 조직 전체, group/sort는 목록 표현 | 조건명 유지; 담당 범위 aria-label을 담당자로 | core/web/views/me.py:15 · 소스 동작 대조 |
| B043 · `core/web/templates/me.html:25` | 필터 조건 적용됨 기한 · 프로젝트 · 상태 · 중요도 ⌄ | 해당 묶음·상세 내용 확인 | HTML details 접힘/펼침; 데이터 변경 없음 | 문맥이 드러나는 현재 제목 유지 | core/web/templates/me.html:25 · 소스 대응 |
| B044 · `core/web/templates/me.html:31` | {{ label }} / 접근성: 기한 | 담당자·묶음·정렬·필터 조정 | GET me 조회; member=0은 조직 전체, group/sort는 목록 표현 | 조건명 유지; 담당 범위 aria-label을 담당자로 | core/web/views/me.py:15 · 소스 동작 대조 |
| B045 · `core/web/templates/me.html:32` | 모든 프로젝트 {{ p.name }} / 접근성: 프로젝트 | 담당자·묶음·정렬·필터 조정 | GET me 조회; member=0은 조직 전체, group/sort는 목록 표현 | 조건명 유지; 담당 범위 aria-label을 담당자로 | core/web/views/me.py:15 · 소스 동작 대조 |
| B046 · `core/web/templates/me.html:33` | {{ label }} / 접근성: 상태 | 담당자·묶음·정렬·필터 조정 | GET me 조회; member=0은 조직 전체, group/sort는 목록 표현 | 조건명 유지; 담당 범위 aria-label을 담당자로 | core/web/views/me.py:15 · 소스 동작 대조 |
| B047 · `core/web/templates/me.html:34` | {{ label }} / 접근성: 중요도 | 담당자·묶음·정렬·필터 조정 | GET me 조회; member=0은 조직 전체, group/sort는 목록 표현 | 조건명 유지; 담당 범위 aria-label을 담당자로 | core/web/views/me.py:15 · 소스 동작 대조 |
| B048 · `core/web/templates/me.html:35` | 필터 지우기 | 추가 필터 해제 | GET member/group/sort 유지하고 due/project/status/priority 제거 | 추가 필터 지우기; 담당자·묶음·정렬 유지 설명 | core/web/templates/me.html:35 · 개별 검토 |
| B049 · `core/web/templates/me.html:49` | {{ p.project.name }} | 프로젝트 태스크 확인 | GET · 선택 프로젝트 목록 또는 보드 | 유지 | core/web/views/projects.py:182 · 소스 동작 대조 |

## notes/list.html

| ID·근거 | 현재 문구 / 접근성 이름 | 사용자 목적 | 예상·실제 결과 | 권장 문구·보조 안내 | 동작 근거·판정 |
| --- | --- | --- | --- | --- | --- |
| B050 · `core/web/templates/notes/list.html:11` | file | Markdown을 회의록으로 등록 | POST · 파일 선택 후 POST 업로드·생성 | Markdown 회의록 올리기; 선택 즉시 제출 안내 | core/web/views/notes.py:98 · 소스 동작 대조 |
| B051 · `core/web/templates/notes/list.html:12` | .md 올리기 | Markdown을 회의록으로 등록 | POST · 파일 선택 후 POST 업로드·생성 | Markdown 회의록 올리기; 선택 즉시 제출 안내 | core/web/views/notes.py:98 · 소스 동작 대조 |
| B052 · `core/web/templates/notes/list.html:14` | 새 회의록 | 새 회의록 바로 작성 | POST · POST 빈 회의록 생성 후 해당 회의록 이동 | 새 회의록 만들기 | core/web/views/notes.py:87 · 소스 동작 대조 |
| B053 · `core/web/templates/notes/list.html:20` | 전체 팀 공통 {{ p.name }} / 접근성: 범위 | 회의록 프로젝트 범위 좁히기 | GET scope로 프로젝트 또는 조직 공통 회의록 필터 | 조직 공통(프로젝트 미지정) | core/web/views/notes.py:33 · 소스 동작 대조 |
| B054 · `core/web/templates/notes/list.html:29` | 적용 | 회의록 검색 조건 적용 | GET scope/q 조건 조회 | 적용 유지 | core/web/views/notes.py:33 · 소스 동작 대조 |
| B055 · `core/web/templates/notes/list.html:33` | 태그 전체 | 회의록 선택 또는 태그로 찾기 | GET scope/tag/note로 목록·선택 문서 갱신 | 태그·회의록 제목 유지 | core/web/views/notes.py:33 · 소스 동작 대조 |
| B056 · `core/web/templates/notes/list.html:35` | {{ t }} | 회의록 선택 또는 태그로 찾기 | GET scope/tag/note로 목록·선택 문서 갱신 | 태그·회의록 제목 유지 | core/web/views/notes.py:33 · 소스 동작 대조 |
| B057 · `core/web/templates/notes/list.html:43` | {{ n.title }} {{ n.created_by.display_name }} · v{{ n.version }} · {{ n.updated_at\|date:"n/j" }} {{ t }} | 회의록 선택 또는 태그로 찾기 | GET scope/tag/note로 목록·선택 문서 갱신 | 태그·회의록 제목 유지 | core/web/views/notes.py:33 · 소스 동작 대조 |
| B058 · `core/web/templates/notes/list.html:57` | ← 회의록 목록 | 회의록 목록으로 돌아가기 | GET 선택 해제; JS는 미저장 상태 flush 성공 후 이동 | 회의록 목록 유지 | core/web/static/notes.js:686 · 소스 동작 대조 |
| B059 · `core/web/templates/notes/list.html:88` | 본문 편집 | 회의록 본문 작성 시작 | JS beginEditing; POST 저장 버튼 아님 | 본문 편집 유지; 자동 저장 상태 안내 | core/web/static/notes.js:436 · 개별 검토 |
| B060 · `core/web/templates/notes/list.html:95` | 저장 | 회의록 수동 저장(JS 미실행) | JS 초기화 후 숨김; fallback 폼 POST로 저장 | fallback 회의록 저장; 실제 화면 주 버튼으로 집계 안함 | core/web/static/notes.js:149 · 개별 검토 |
| B061 · `core/web/templates/notes/list.html:101` | 쓰는 법 | 해당 묶음·상세 내용 확인 | HTML details 접힘/펼침; 데이터 변경 없음 | 문맥이 드러나는 현재 제목 유지 | core/web/templates/notes/list.html:101 · 소스 대응 |
| B062 · `core/web/templates/notes/list.html:106` | 삭제 | 회의록 본문까지 제거 | POST · POST 회의록 삭제 | 회의록 삭제 | core/web/views/notes.py:149 · 소스 동작 대조 |

## oauth/authorize.html

| ID·근거 | 현재 문구 / 접근성 이름 | 사용자 목적 | 예상·실제 결과 | 권장 문구·보조 안내 | 동작 근거·판정 |
| --- | --- | --- | --- | --- | --- |
| B063 · `core/web/templates/oauth/authorize.html:15` | 허용 | AI 클라이언트 접근 허용 | POST 선택 scope로 OAuth 코드 발급 후 등록 redirect_uri 이동 | 접근 허용 | core/web/views/oauth.py:131 · 소스 동작 대조 |
| B064 · `core/web/templates/oauth/authorize.html:16` | 취소 | AI 연결 요청 거절 | POST access_denied로 클라이언트 복귀 | 연결 취소 | core/web/views/oauth.py:132 · 소스 동작 대조 |
| B065 · `core/web/templates/oauth/authorize.html:20` | 설정 → API 토큰 | API·AI 연결 자격 관리 | GET · 토큰 관리·연결 안내 화면 | 유지 | core/web/views/settings.py:49 · 소스 동작 대조 |

## ops.html

| ID·근거 | 현재 문구 / 접근성 이름 | 사용자 목적 | 예상·실제 결과 | 권장 문구·보조 안내 | 동작 근거·판정 |
| --- | --- | --- | --- | --- | --- |
| B066 · `core/web/templates/ops.html:5` | JSON 내보내기 | 운영 데이터 파일 확보 | GET · GET 지정 모델 전체 레코드 JSON; 문서·회의록 등 제외되어 완전 백업 아님 | 운영 데이터 JSON 내보내기 | core/web/views/ops.py:26 · 소스 동작 대조 |

## orgs/_milestone_dialog.html

| ID·근거 | 현재 문구 / 접근성 이름 | 사용자 목적 | 예상·실제 결과 | 권장 문구·보조 안내 | 동작 근거·판정 |
| --- | --- | --- | --- | --- | --- |
| B067 · `core/web/templates/orgs/_milestone_dialog.html:18` | 변경 내용 저장 마일스톤 만들기 | 마일스톤 수정 / 마일스톤 생성 | POST · GET 폼; POST 저장 / GET 폼; POST 생성 | 마일스톤 수정 / 변경 내용 저장 / 새 마일스톤 / 마일스톤 만들기 | core/web/views/roadmap.py:155; core/web/views/roadmap.py:135 · 소스 동작 대조 |
| B068 · `core/web/templates/orgs/_milestone_dialog.html:19` | 취소 | 마일스톤 편집 중단 | JS dialog 닫기; 폼 POST 안함 | 취소 유지 | core/web/static/app.js:193 · 개별 검토 |

## orgs/_pending_requests.html

| ID·근거 | 현재 문구 / 접근성 이름 | 사용자 목적 | 예상·실제 결과 | 권장 문구·보조 안내 | 동작 근거·판정 |
| --- | --- | --- | --- | --- | --- |
| B069 · `core/web/templates/orgs/_pending_requests.html:6` | {{ r.get_kind_display }} #{{ r.pk }} | AI 변경 요청 상세 확인 | ChangeRequest.path로 GET 상세 이동 | 변경 종류와 요청 번호 유지 | core/web/templates/orgs/_pending_requests.html:6 · 소스 동작 대조 |

## orgs/_tabs.html

| ID·근거 | 현재 문구 / 접근성 이름 | 사용자 목적 | 예상·실제 결과 | 권장 문구·보조 안내 | 동작 근거·판정 |
| --- | --- | --- | --- | --- | --- |
| B070 · `core/web/templates/orgs/_tabs.html:3` | 개요 | 조직 업무 확인 | GET · 선택 조직의 개요 표시 | 유지 | core/web/views/orgs.py:65 · 소스 동작 대조 |
| B071 · `core/web/templates/orgs/_tabs.html:4` | 팀 | 멤버·팀·초대 관리 | GET · 조직 멤버·초대·팀 관리 화면 | 유지 | core/web/views/orgs.py:101 · 소스 동작 대조 |
| B072 · `core/web/templates/orgs/_tabs.html:5` | 부하 현황 | 조직 업무 부하 확인 | GET · 부하 지표와 팀·기술 태그 필터 화면 | 유지 | core/web/views/roadmap.py:27 · 소스 동작 대조 |
| B073 · `core/web/templates/orgs/_tabs.html:6` | 로드맵 | 프로젝트 일정·의존성 확인 | GET · 마일스톤·프로젝트 의존성 화면 | 유지 | core/web/views/roadmap.py:68 · 소스 동작 대조 |
| B074 · `core/web/templates/orgs/_tabs.html:8` | 거버넌스 | 조직 합의 확인·편집 | GET · 거버넌스 본문·편집 화면 | 유지 | core/web/views/orgs.py:235 · 소스 동작 대조 |
| B075 · `core/web/templates/orgs/_tabs.html:9` | 회의록 | 회의 기록 확인 | GET · 조직 회의록 목록 또는 지정 회의록 표시 | 유지 | core/web/views/notes.py:33 · 소스 동작 대조 |
| B076 · `core/web/templates/orgs/_tabs.html:10` | 이슈 | 조직 저장소 이슈 확인 | GET · 조직 GitHub 이슈 목록 | 유지 | core/web/views/github.py:291 · 소스 동작 대조 |
| B077 · `core/web/templates/orgs/_tabs.html:11` | GitHub | 조직 GitHub 연동 관리 | GET · GitHub App 설치·조직 저장소 연결 상태 | 유지 | core/web/views/github.py:35 · 소스 동작 대조 |
| B078 · `core/web/templates/orgs/_tabs.html:12` | Discord | 조직 Discord 연동 관리 | GET · Discord 서버 연결 화면 | 유지 | core/web/views/discord.py:38 · 소스 동작 대조 |
| B079 · `core/web/templates/orgs/_tabs.html:13` | 설정 | 조직 규칙 관리 | GET · 조직 설정·잠금 화면 | 유지 | core/web/views/orgs.py:350 · 소스 동작 대조 |

## orgs/_team_dialog.html

| ID·근거 | 현재 문구 / 접근성 이름 | 사용자 목적 | 예상·실제 결과 | 권장 문구·보조 안내 | 동작 근거·판정 |
| --- | --- | --- | --- | --- | --- |
| B080 · `core/web/templates/orgs/_team_dialog.html:10` | 변경 내용 저장 팀 만들기 | PM 팀 정보 수정 / 새 PM 팀 생성 | POST · GET 폼; POST 변경 저장·조건부 GitHub 반영 / GET 다이얼로그; POST 팀 생성 | 팀 수정 / 변경 내용 저장 / 새 팀 / 팀 만들기 | core/web/views/teams.py:59; core/web/views/teams.py:43 · 소스 동작 대조 |
| B081 · `core/web/templates/orgs/_team_dialog.html:11` | 취소 | 팀 편집 중단 | JS dialog 닫기; 폼 POST 안함 | 취소 유지 | core/web/static/app.js:193 · 개별 검토 |

## orgs/capacity.html

| ID·근거 | 현재 문구 / 접근성 이름 | 사용자 목적 | 예상·실제 결과 | 권장 문구·보조 안내 | 동작 근거·판정 |
| --- | --- | --- | --- | --- | --- |
| B082 · `core/web/templates/orgs/capacity.html:8` | 전체 팀 {{ t.name }} | 원하는 팀 부하 확인 | GET team 필터; KPI는 조직 전체 | 팀 필터 유지 + 조직 전체 KPI 범위 안내 | core/web/views/roadmap.py:27 · 소스 동작 대조 |
| B083 · `core/web/templates/orgs/capacity.html:23` | {{ r.user.display_name }} | 멤버 담당 태스크 열기 | GET me?member=id | 멤버 이름 유지 | core/web/views/roadmap.py:27 · 소스 동작 대조 |
| B084 · `core/web/templates/orgs/capacity.html:48` | {{ tag }} | 기술 태그로 부하 좁히기 | GET tags 추가/제외 필터, 데이터 변경 없음 | 기술 태그 유지 | core/web/views/roadmap.py:27 · 소스 동작 대조 |
| B085 · `core/web/templates/orgs/capacity.html:50` | {{ tag }} | 기술 태그로 부하 좁히기 | GET tags 추가/제외 필터, 데이터 변경 없음 | 기술 태그 유지 | core/web/views/roadmap.py:27 · 소스 동작 대조 |

## orgs/change_request.html

| ID·근거 | 현재 문구 / 접근성 이름 | 사용자 목적 | 예상·실제 결과 | 권장 문구·보조 안내 | 동작 근거·판정 |
| --- | --- | --- | --- | --- | --- |
| B086 · `core/web/templates/orgs/change_request.html:40` | 허용하면 적용될 전체 글 보기 | 해당 묶음·상세 내용 확인 | HTML details 접힘/펼침; 데이터 변경 없음 | 문맥이 드러나는 현재 제목 유지 | core/web/templates/orgs/change_request.html:40 · 소스 대응 |
| B087 · `core/web/templates/orgs/change_request.html:47` | 허용하고 반영 | AI 요청한 변경 적용 | POST action=approve 변경 허용 및 즉시 반영 | 변경 허용하고 반영 | core/web/views/orgs.py:283 · 소스 동작 대조 |
| B088 · `core/web/templates/orgs/change_request.html:49` | 거절 | AI 변경 요청 거절 | POST action=reject 요청 거절·사유 기록 | 요청 거절 | core/web/views/orgs.py:286 · 소스 동작 대조 |

## orgs/detail.html

| ID·근거 | 현재 문구 / 접근성 이름 | 사용자 목적 | 예상·실제 결과 | 권장 문구·보조 안내 | 동작 근거·판정 |
| --- | --- | --- | --- | --- | --- |
| B089 · `core/web/templates/orgs/detail.html:6` | {{ value }} {{ label }} | KPI 해당 태스크 확인 | 뷰가 만든 url의 조건으로 GET 태스크 조회 | 숫자+범위 라벨 유지 | core/web/views/orgs.py:65 · 소스 동작 대조 |
| B090 · `core/web/templates/orgs/detail.html:13` | 1 | 보관한 프로젝트도 조회 | GET include_archived=1 포함 조회 | 보관 포함 유지 | core/web/views/orgs.py:65 · 소스 동작 대조 |
| B091 · `core/web/templates/orgs/detail.html:14` | 새 프로젝트 | 새 프로젝트 생성 | GET · GET 생성 다이얼로그; 유효 POST 프로젝트 생성 | 새 프로젝트 / 프로젝트 만들기 | core/web/views/projects.py:121 · 소스 동작 대조 |
| B092 · `core/web/templates/orgs/detail.html:24` | {{ p.name }} | 프로젝트 태스크 확인 | GET · 선택 프로젝트 목록 또는 보드 | 유지 | core/web/views/projects.py:182 · 소스 동작 대조 |
| B093 · `core/web/templates/orgs/detail.html:44` | {{ a.assignee__display_name }} | 담당자 업무 확인 | GET me?member=id | 담당자 이름 유지 | core/web/views/orgs.py:65 · 소스 동작 대조 |

## orgs/discord.html

| ID·근거 | 현재 문구 / 접근성 이름 | 사용자 목적 | 예상·실제 결과 | 권장 문구·보조 안내 | 동작 근거·판정 |
| --- | --- | --- | --- | --- | --- |
| B094 · `core/web/templates/orgs/discord.html:13` | 연결 해제 | 조직 Discord 서버 연결 중단 | POST 조직 Discord 연결 해제 | Discord 서버 연결 해제 | core/web/views/discord.py:94 · 개별 검토 |
| B095 · `core/web/templates/orgs/discord.html:17` | Discord 서버 연결 | 조직 Discord 서버 연결 시작 | GET · GET Discord 설치·권한 선택 단계 | Discord 서버 연결 | core/web/views/discord.py:51 · 소스 동작 대조 |

## orgs/github.html

| ID·근거 | 현재 문구 / 접근성 이름 | 사용자 목적 | 예상·실제 결과 | 권장 문구·보조 안내 | 동작 근거·판정 |
| --- | --- | --- | --- | --- | --- |
| B096 · `core/web/templates/orgs/github.html:11` | GitHub에서 설정 | 관련 자료·설정 열기 | GET https://github.com/organizations/{{ install.account_login }}/settings/installations/{{ install.installation_id }} 새 탭 | 대상 제목 유지; 변수 URL의 실제 값은 데이터별 확인 필요 | core/web/templates/orgs/github.html:11 · 동적 URL/외부 화면 미검증 |
| B097 · `core/web/templates/orgs/github.html:15` | GitHub 앱 설치 | 조직 GitHub App 설치 시작 | GET · GET 외부 앱 설치·권한 선택 화면 | GitHub 앱 설치 | core/web/views/github.py:56 · 소스 동작 대조 |
| B098 · `core/web/templates/orgs/github.html:25` | 다시 확인 | 조직에서 접근 가능한 저장소 확인 | POST 개인 저장소 갱신 후 프로필 이동; 조직 설치 갱신 아님 | 내 접근 저장소 다시 확인; 화면 복귀 동작 개선 검토 | core/web/views/github.py:139 · 개별 검토 |
| B099 · `core/web/templates/orgs/github.html:28` | 프로필에서 연결 | 개인 정보·연동 관리 | GET · 프로필·개인 GitHub/Discord 연결 화면 | 유지 | core/web/views/settings.py:16 · 소스 동작 대조 |
| B100 · `core/web/templates/orgs/github.html:40` | 저장소 설정 | 프로젝트 저장소 연동 관리 | GET · 저장소 연결·규칙·이슈·이벤트 화면; 조건부 이슈 동기화 가능 | 유지 | core/web/views/github.py:177 · 소스 동작 대조 |

## orgs/governance.html

| ID·근거 | 현재 문구 / 접근성 이름 | 사용자 목적 | 예상·실제 결과 | 권장 문구·보조 안내 | 동작 근거·판정 |
| --- | --- | --- | --- | --- | --- |
| B101 · `core/web/templates/orgs/governance.html:14` | 설정에서 바꾸기 | 조직 규칙 관리 | GET · 조직 설정·잠금 화면 | 유지 | core/web/views/orgs.py:350 · 소스 동작 대조 |
| B102 · `core/web/templates/orgs/governance.html:31` | 저장 | 조직 합의 편집 내용 저장 | POST 거버넌스 본문 저장 | 거버넌스 저장 | core/web/views/orgs.py:235 · 소스 동작 대조 |
| B103 · `core/web/templates/orgs/governance.html:33` | 기본안으로 되돌리기 | 조직 합의를 기본안으로 교체 | 확인 후 POST reset=1 기존 본문을 기본안으로 교체 | 기본안으로 되돌리기 유지; 현재 본문 교체 안내 | core/web/views/orgs.py:235 · 소스 동작 대조 |
| B104 · `core/web/templates/orgs/governance.html:39` | 미리보기 | 해당 묶음·상세 내용 확인 | HTML details 접힘/펼침; 데이터 변경 없음 | 문맥이 드러나는 현재 제목 유지 | core/web/templates/orgs/governance.html:39 · 소스 대응 |

## orgs/list.html

| ID·근거 | 현재 문구 / 접근성 이름 | 사용자 목적 | 예상·실제 결과 | 권장 문구·보조 안내 | 동작 근거·판정 |
| --- | --- | --- | --- | --- | --- |
| B105 · `core/web/templates/orgs/list.html:10` | {{ o.name }} | 조직 업무 확인 | GET · 선택 조직의 개요 표시 | 유지 | core/web/views/orgs.py:65 · 소스 동작 대조 |
| B106 · `core/web/templates/orgs/list.html:18` | 조직 만들기 | 새 조직 생성 | GET · GET 생성 폼; 유효 POST 조직 생성 | 조직 만들기 | core/web/views/orgs.py:51 · 소스 동작 대조 |

## orgs/new.html

| ID·근거 | 현재 문구 / 접근성 이름 | 사용자 목적 | 예상·실제 결과 | 권장 문구·보조 안내 | 동작 근거·판정 |
| --- | --- | --- | --- | --- | --- |
| B107 · `core/web/templates/orgs/new.html:8` | 만들기 | 새 조직 만들기 | POST 조직 생성 | 조직 만들기 | core/web/views/orgs.py:51 · 소스 동작 대조 |

## orgs/roadmap.html

| ID·근거 | 현재 문구 / 접근성 이름 | 사용자 목적 | 예상·실제 결과 | 권장 문구·보조 안내 | 동작 근거·판정 |
| --- | --- | --- | --- | --- | --- |
| B108 · `core/web/templates/orgs/roadmap.html:7` | 새 마일스톤 | 마일스톤 생성 | GET · GET 폼; POST 생성 | 새 마일스톤 / 마일스톤 만들기 | core/web/views/roadmap.py:135 · 소스 동작 대조 |
| B109 · `core/web/templates/orgs/roadmap.html:26` | 수정 | 마일스톤 수정 | GET · GET 폼; POST 저장 | 마일스톤 수정 / 변경 내용 저장 | core/web/views/roadmap.py:155 · 소스 동작 대조 |
| B110 · `core/web/templates/orgs/roadmap.html:46` | 삭제 / 접근성: {{ d.from_project.name }}에서 {{ d.to_project.name }} 의존성 삭제 | 의존 관계만 제거 | POST · POST 관계 레코드 삭제; 프로젝트 유지 | 의존 관계 삭제 | core/web/views/roadmap.py:207 · 소스 동작 대조 |
| B111 · `core/web/templates/orgs/roadmap.html:70` | 추가 | 프로젝트 의존 관계 등록 | POST · POST from_project→to_project 데이터 생성; 착수 자동 차단 보장 아님 | 프로젝트 의존 관계 추가 | core/web/views/roadmap.py:188 · 소스 동작 대조 |

## orgs/settings.html

| ID·근거 | 현재 문구 / 접근성 이름 | 사용자 목적 | 예상·실제 결과 | 권장 문구·보조 안내 | 동작 근거·판정 |
| --- | --- | --- | --- | --- | --- |
| B112 · `core/web/templates/orgs/settings.html:12` | {{ label }} {{ group_rows\|length }} | 원하는 설정 묶음 찾기 | JS 해당 섹션 열고 다른 섹션 닫기·스크롤; 저장 안함 | 섹션 제목 유지 | core/web/static/app.js:195 · JS 동작 대조 |
| B113 · `core/web/templates/orgs/settings.html:14` | 조직 설정 저장 | 조직 설정·잠금 저장 | POST 조직 값과 잠금 함께 저장 | 조직 설정 저장 | core/web/views/orgs.py:350 · 소스 동작 대조 |
| B114 · `core/web/templates/orgs/settings.html:17` | {{ label }} {{ group_rows\|length }}개 항목 | 해당 묶음·상세 내용 확인 | HTML details 접힘/펼침; 데이터 변경 없음 | 문맥이 드러나는 현재 제목 유지 | core/web/templates/orgs/settings.html:17 · 소스 대응 |

## orgs/team_detail.html

| ID·근거 | 현재 문구 / 접근성 이름 | 사용자 목적 | 예상·실제 결과 | 권장 문구·보조 안내 | 동작 근거·판정 |
| --- | --- | --- | --- | --- | --- |
| B115 · `core/web/templates/orgs/team_detail.html:7` | {{ org.name }} | 멤버·팀·초대 관리 | GET · 조직 멤버·초대·팀 관리 화면 | 유지 | core/web/views/orgs.py:101 · 소스 동작 대조 |
| B116 · `core/web/templates/orgs/team_detail.html:13` | 수정 | PM 팀 정보 수정 | GET · GET 폼; POST 변경 저장·조건부 GitHub 반영 | 팀 수정 / 변경 내용 저장 | core/web/views/teams.py:59 · 소스 동작 대조 |
| B117 · `core/web/templates/orgs/team_detail.html:14` | 삭제 | PM 팀 제거 | POST · POST 팀 삭제; 멤버·프로젝트·GitHub 팀 유지 | 팀 삭제 | core/web/views/teams.py:82 · 소스 동작 대조 |
| B118 · `core/web/templates/orgs/team_detail.html:24` | GitHub에 반영 | PM 멤버를 GitHub에도 등록 | POST · POST 활성 PM 멤버 추가 요청; 외부에만 있는 멤버 제거 안함 | GitHub에 멤버 추가 | core/web/views/teams.py:231 · 소스 동작 대조 |
| B119 · `core/web/templates/orgs/team_detail.html:25` | 연결 해제 | 팀 연결만 해제 | POST · POST PM 연결 삭제; 외부 팀 유지 | GitHub 팀 연결 해제 | core/web/views/teams.py:221 · 소스 동작 대조 |
| B120 · `core/web/templates/orgs/team_detail.html:33` | 연결 | 기존 GitHub 팀 연결 | POST · POST PM 연결 생성; 멤버 반영은 별도 | 선택한 GitHub 팀 연결 | core/web/views/teams.py:181 · 소스 동작 대조 |
| B121 · `core/web/templates/orgs/team_detail.html:35` | GitHub에 새 팀 만들기 | 외부 팀 생성 및 연결 | POST · POST GitHub 새 팀 생성 후 PM 연결 | GitHub 팀 만들고 연결 | core/web/views/teams.py:198 · 소스 동작 대조 |
| B122 · `core/web/templates/orgs/team_detail.html:48` | 제거 | PM 팀 구성원 제외 | POST 팀 제거와 조건부 GitHub 팀 제거 요청; 외부 성공 보장 안함 | 팀에서 제거; GitHub 반영 요청 조건 안내 | core/web/views/teams.py:149 · 개별 검토 |
| B123 · `core/web/templates/orgs/team_detail.html:58` | 추가 | PM 팀에 구성원 추가 | POST 팀 추가와 조건부 GitHub 팀 추가 요청 | 팀 멤버 추가; 외부 반영 결과 확인 안내 | core/web/views/teams.py:131 · 개별 검토 |
| B124 · `core/web/templates/orgs/team_detail.html:64` | {{ p.name }} | 프로젝트 태스크 확인 | GET · 선택 프로젝트 목록 또는 보드 | 유지 | core/web/views/projects.py:182 · 소스 동작 대조 |

## orgs/teams.html

| ID·근거 | 현재 문구 / 접근성 이름 | 사용자 목적 | 예상·실제 결과 | 권장 문구·보조 안내 | 동작 근거·판정 |
| --- | --- | --- | --- | --- | --- |
| B125 · `core/web/templates/orgs/teams.html:19` | 관리자 멤버 / 접근성: {{ r.m.user.display_name }} 역할 | 조직 멤버 역할 변경 | POST · select change POST 조직 역할 저장 | 조직 역할 라벨 유지 | core/web/views/orgs.py:201 · 소스 동작 대조 |
| B126 · `core/web/templates/orgs/teams.html:30` | 저장 | 멤버 기술 등록 | POST · POST 기술 태그 저장 | 기술 태그 저장 | core/web/views/orgs.py:146 · 소스 동작 대조 |
| B127 · `core/web/templates/orgs/teams.html:35` | 제거 | 조직에서 멤버 제외 | POST · POST 조직 제거·조건부 GitHub 조직 제거 요청; 태스크 담당 유지 | 조직에서 제거 | core/web/views/orgs.py:213 · 소스 동작 대조 |
| B128 · `core/web/templates/orgs/teams.html:36` | 제거 / 접근성: 마지막 관리자는 제거할 수 없습니다 | 조직 멤버 제거 | disabled로 요청 안함; 마지막 관리자 제한 | 조직에서 제거; 비활성 사유 유지 | core/web/templates/orgs/teams.html:36 · 소스 동작 대조 |
| B129 · `core/web/templates/orgs/teams.html:54` | 복사 | 초대 주소 전달 | JS 초대 URL 클립보드 복사; 실패 fallback 후에도 성공 안내 문제 | 초대 링크 복사 + 성공 분기 수정 필요 | core/web/static/app.js:131 · 개별 검토 |
| B130 · `core/web/templates/orgs/teams.html:59` | 폐기 | 초대 사용 중단 | POST · POST 초대 폐기 | 초대 링크 폐기 | core/web/views/orgs.py:189 · 소스 동작 대조 |
| B131 · `core/web/templates/orgs/teams.html:67` | gh_invite | 조직 초대에 GitHub 초대도 포함 | 체크박스는 입력칸 표시만 바꿈; 초대 발급 시 처리 | GitHub 조직에도 초대 유지; 체크만으로 발급 아님 | core/web/templates/orgs/teams.html:67 · 소스 동작 대조 |
| B132 · `core/web/templates/orgs/teams.html:70` | 초대 링크 만들기 | 참여 초대 발급 | POST · POST 초대 링크 생성; gh_invite면 조건부 외부 초대 요청; 기간 검증 fallback 별도 문제 | 초대 링크 만들기 | core/web/views/orgs.py:166 · 소스 동작 대조 |
| B133 · `core/web/templates/orgs/teams.html:76` | 새 팀 | 새 PM 팀 생성 | GET · GET 다이얼로그; POST 팀 생성 | 새 팀 / 팀 만들기 | core/web/views/teams.py:43 · 소스 동작 대조 |
| B134 · `core/web/templates/orgs/teams.html:83` | {{ row.team.name }} | 팀 구성·프로젝트 확인 | GET · 선택 팀 상세·GitHub 팀 연결 화면 | 유지 | core/web/views/teams.py:93 · 소스 동작 대조 |
| B135 · `core/web/templates/orgs/teams.html:88` | 수정 | PM 팀 정보 수정 | GET · GET 폼; POST 변경 저장·조건부 GitHub 반영 | 팀 수정 / 변경 내용 저장 | core/web/views/teams.py:59 · 소스 동작 대조 |
| B136 · `core/web/templates/orgs/teams.html:89` | 삭제 | PM 팀 제거 | POST · POST 팀 삭제; 멤버·프로젝트·GitHub 팀 유지 | 팀 삭제 | core/web/views/teams.py:82 · 소스 동작 대조 |

## portfolio/index.html

| ID·근거 | 현재 문구 / 접근성 이름 | 사용자 목적 | 예상·실제 결과 | 권장 문구·보조 안내 | 동작 근거·판정 |
| --- | --- | --- | --- | --- | --- |
| B137 · `core/web/templates/portfolio/index.html:11` | 새 초안 만들기 | 다음 포트폴리오 작성 준비 | GET 출처 선택 화면; 비공개 초안 생성 안함 | 새 초안 준비하기 | core/web/views/portfolio.py:157 · 개별 검토 |
| B138 · `core/web/templates/portfolio/index.html:19` | {{ saved.title }} | 저장한 초안 다시 열기 | GET portfolio?draft=id 기존 초안 표시 | 초안 제목 유지 | core/web/views/portfolio.py:159 · 개별 검토 |
| B139 · `core/web/templates/portfolio/index.html:35` | 저장 | 편집한 초안 저장 | POST · POST 제목·Markdown 저장; 버전 충돌 검사 | 초안 저장 | core/web/views/portfolio.py:253 · 소스 동작 대조 |
| B140 · `core/web/templates/portfolio/index.html:36` | Markdown 다운로드 | 저장된 초안 파일 확보 | GET · GET 서버 저장 Markdown 다운로드; 미저장 본문 제출 안함 | Markdown 다운로드 유지 + 저장된 내용만 내보낸다는 안내 후보 | core/web/views/portfolio.py:287 · 소스 동작 대조 |
| B141 · `core/web/templates/portfolio/index.html:56` | {{ org.name }} / 접근성: 조직 | 포트폴리오 출처 조직 선택 | GET 조직 필터 새 조회; 초안 생성 아님 | 조직 라벨 유지 | core/web/views/portfolio.py:157 · 개별 검토 |
| B142 · `core/web/templates/portfolio/index.html:68` | 출처 보기 | 조건에 맞는 출처 찾기 | GET 프로젝트·기간·기록 종류로 출처 조회 | 출처 보기 유지 | core/web/views/portfolio.py:175 · 개별 검토 |
| B143 · `core/web/templates/portfolio/index.html:98` | 선택한 출처로 AI 프롬프트 만들기 | 외부 AI에 작성 요청 준비 | POST · POST 선택 출처로 프롬프트 생성; 앱 내 초안 자동 생성 아님 | 선택한 출처로 AI 프롬프트 만들기 유지(Astra) | core/web/views/portfolio.py:189 · 소스 동작 대조 |
| B144 · `core/web/templates/portfolio/index.html:103` | 프롬프트 복사 | 외부 AI에 작성 요청 전달 | JS clipboard.writeText; 성공·실패 피드백 없음 | AI 작성 요청 복사 + 피드백·fallback | core/web/templates/portfolio/index.html:103 · 개별 검토 |
| B145 · `core/web/templates/portfolio/index.html:111` | 비공개 초안 저장 | AI 결과를 개인 초안으로 보관 | POST · POST 붙여 넣은 Markdown·출처로 비공개 초안 생성 | 비공개 초안 저장 | core/web/views/portfolio.py:218 · 소스 동작 대조 |

## projects/_board.html

| ID·근거 | 현재 문구 / 접근성 이름 | 사용자 목적 | 예상·실제 결과 | 권장 문구·보조 안내 | 동작 근거·판정 |
| --- | --- | --- | --- | --- | --- |
| B146 · `core/web/templates/projects/_board.html:6` | ‹ / 접근성: 이전 상태 열 | 다른 상태 열 확인 | JS 칸반을 이전/다음 열 방향으로 가로 스크롤 | 이전 상태 열 / 다음 상태 열; 기존 aria-label 대조 | core/web/static/app.js:222 · JS 동작 대조 |
| B147 · `core/web/templates/projects/_board.html:8` | › / 접근성: 다음 상태 열 | 다른 상태 열 확인 | JS 칸반을 이전/다음 열 방향으로 가로 스크롤 | 이전 상태 열 / 다음 상태 열; 기존 aria-label 대조 | core/web/static/app.js:222 · JS 동작 대조 |

## projects/_dialog.html

| ID·근거 | 현재 문구 / 접근성 이름 | 사용자 목적 | 예상·실제 결과 | 권장 문구·보조 안내 | 동작 근거·판정 |
| --- | --- | --- | --- | --- | --- |
| B148 · `core/web/templates/projects/_dialog.html:22` | 변경 내용 저장 프로젝트 만들기 | 프로젝트 정보 수정 / 새 프로젝트 생성 | POST · GET 편집 다이얼로그; 유효 POST 변경 저장 / GET 생성 다이얼로그; 유효 POST 프로젝트 생성 | 프로젝트 수정 / 변경 내용 저장 / 새 프로젝트 / 프로젝트 만들기 | core/web/views/projects.py:145; core/web/views/projects.py:121 · 소스 동작 대조 |
| B149 · `core/web/templates/projects/_dialog.html:23` | 취소 | 프로젝트 편집 중단 | JS dialog 닫기; 폼 POST 없음 | 취소 유지 | core/web/static/app.js:193 · 개별 검토 |

## projects/_endpoints.html

| ID·근거 | 현재 문구 / 접근성 이름 | 사용자 목적 | 예상·실제 결과 | 권장 문구·보조 안내 | 동작 근거·판정 |
| --- | --- | --- | --- | --- | --- |
| B150 · `core/web/templates/projects/_endpoints.html:10` | {{ op.method }} {{ op.path }} {{ op.summary }} 인증 | 해당 묶음·상세 내용 확인 | HTML details 접힘/펼침; 데이터 변경 없음 | 문맥이 드러나는 현재 제목 유지 | core/web/templates/projects/_endpoints.html:10 · 소스 대응 |

## projects/_tabs.html

| ID·근거 | 현재 문구 / 접근성 이름 | 사용자 목적 | 예상·실제 결과 | 권장 문구·보조 안내 | 동작 근거·판정 |
| --- | --- | --- | --- | --- | --- |
| B151 · `core/web/templates/projects/_tabs.html:2` | {{ project.org.name }} | 조직 업무 확인 | GET · 선택 조직의 개요 표시 | 유지 | core/web/views/orgs.py:65 · 소스 동작 대조 |
| B152 · `core/web/templates/projects/_tabs.html:6` | 태스크 | 프로젝트 태스크 확인 | GET · 선택 프로젝트 목록 또는 보드 | 유지 | core/web/views/projects.py:182 · 소스 동작 대조 |
| B153 · `core/web/templates/projects/_tabs.html:7` | 문서 | 프로젝트 문서 읽기·편집 | GET · 문서 목록 또는 doc 파라미터의 문서 표시 | 유지 | core/web/views/docs.py:24 · 소스 동작 대조 |
| B154 · `core/web/templates/projects/_tabs.html:8` | API 문서 | API 정의 확인 | GET · OpenAPI 문서·엔드포인트 화면 | 유지 | core/web/views/projects.py:323 · 소스 동작 대조 |
| B155 · `core/web/templates/projects/_tabs.html:9` | 이슈 | 프로젝트 이슈 확인 | GET · 프로젝트 GitHub 이슈 목록 | 유지 | core/web/views/github.py:371 · 소스 동작 대조 |
| B156 · `core/web/templates/projects/_tabs.html:10` | GitHub | 프로젝트 저장소 연동 관리 | GET · 저장소 연결·규칙·이슈·이벤트 화면; 조건부 이슈 동기화 가능 | 유지 | core/web/views/github.py:177 · 소스 동작 대조 |
| B157 · `core/web/templates/projects/_tabs.html:11` | 설정 | 프로젝트 규칙·수명주기 관리 | GET · 설정·보관·삭제·거버넌스 화면 | 유지 | core/web/views/projects.py:369 · 소스 동작 대조 |

## projects/_task_form.html

| ID·근거 | 현재 문구 / 접근성 이름 | 사용자 목적 | 예상·실제 결과 | 권장 문구·보조 안내 | 동작 근거·판정 |
| --- | --- | --- | --- | --- | --- |
| B158 · `core/web/templates/projects/_task_form.html:14` | 태스크 만들기 | 프로젝트 태스크 등록 | POST · POST 새 태스크 생성 | 태스크 만들기 | core/web/views/projects.py:220 · 소스 동작 대조 |
| B159 · `core/web/templates/projects/_task_form.html:15` | 취소 | 새 태스크 입력 닫기 | JS 폼 숨김; 필드 내용 초기화·생성 취소 요청 아님 | 입력 닫기; 기존 값 유지 안내 | core/web/static/app.js:213 · 개별 검토 |

## projects/api.html

| ID·근거 | 현재 문구 / 접근성 이름 | 사용자 목적 | 예상·실제 결과 | 권장 문구·보조 안내 | 동작 근거·판정 |
| --- | --- | --- | --- | --- | --- |
| B160 · `core/web/templates/projects/api.html:22` | 주소에서 불러오기 | 주소의 OpenAPI 정의를 프로젝트에 저장 | POST url의 JSON 조회·검증 후 set_api_spec 저장 | 주소에서 API 문서 불러오기 | core/web/views/projects.py:323 · 소스 동작 대조 |
| B161 · `core/web/templates/projects/api.html:23` | file | JSON 파일을 API 정의로 저장 | 파일 선택 change 즉시 POST 업로드·검증·저장 | OpenAPI JSON 파일 올리기; 선택 즉시 저장 안내 | core/web/views/projects.py:328 · 소스 동작 대조 |
| B162 · `core/web/templates/projects/api.html:24` | 파일 | 파일로 API 정의 가져오기 | 연결된 file input 선택창; 선택하면 즉시 POST 저장 | OpenAPI JSON 파일 올리기 | core/web/templates/projects/api.html:23 · 소스 동작 대조 |
| B163 · `core/web/templates/projects/api.html:37` | {{ q }} / 접근성: 엔드포인트 검색 | API 정의 확인 | GET · OpenAPI 문서·엔드포인트 화면 | 유지 | core/web/views/projects.py:323 · 소스 동작 대조 |

## projects/detail.html

| ID·근거 | 현재 문구 / 접근성 이름 | 사용자 목적 | 예상·실제 결과 | 권장 문구·보조 안내 | 동작 근거·판정 |
| --- | --- | --- | --- | --- | --- |
| B164 · `core/web/templates/projects/detail.html:11` | {{ l.get_kind_display }}: {{ l.title }} | 관련 자료·설정 열기 | GET {{ l.url }} 새 탭 | 대상 제목 유지; 변수 URL의 실제 값은 데이터별 확인 필요 | core/web/templates/projects/detail.html:11 · 동적 URL/외부 화면 미검증 |
| B165 · `core/web/templates/projects/detail.html:18` | 프로젝트 수정 | 프로젝트 정보 수정 | GET · GET 편집 다이얼로그; 유효 POST 변경 저장 | 프로젝트 수정 / 변경 내용 저장 | core/web/views/projects.py:145 · 소스 동작 대조 |
| B166 · `core/web/templates/projects/detail.html:19` | 닫기 태스크 만들기 | 프로젝트 태스크 입력 시작·닫기 | JS #task-form hidden 토글; 생성은 하단 제출 | 새 태스크 입력 / 입력 닫기 | core/web/static/app.js:213 · 개별 검토 |
| B167 · `core/web/templates/projects/detail.html:34` | 목록 | 태스크 표시 방식 선택 | GET view=list/board; 태스크 데이터 변경 없음 | 목록 / 보드 유지 | core/web/views/projects.py:182 · 소스 동작 대조 |
| B168 · `core/web/templates/projects/detail.html:35` | 보드 | 태스크 표시 방식 선택 | GET view=list/board; 태스크 데이터 변경 없음 | 목록 / 보드 유지 | core/web/views/projects.py:182 · 소스 동작 대조 |
| B169 · `core/web/templates/projects/detail.html:39` | 1 | 종료 태스크도 조회 | GET include_closed=1 포함 조회 | 완료·취소 포함 유지 | core/web/views/projects.py:182 · 소스 동작 대조 |
| B170 · `core/web/templates/projects/detail.html:51` | {{ l.title }} | 관련 자료·설정 열기 | GET {{ l.url }} 새 탭 | 대상 제목 유지; 변수 URL의 실제 값은 데이터별 확인 필요 | core/web/templates/projects/detail.html:51 · 동적 URL/외부 화면 미검증 |
| B171 · `core/web/templates/projects/detail.html:51` | 삭제 | 참고 링크만 제거 | POST · POST Link 레코드 삭제; 외부 사이트 유지 | 링크 삭제 | core/web/views/tasks.py:402 · 소스 동작 대조 |
| B172 · `core/web/templates/projects/detail.html:52` | ＋ 링크 추가 | 입력 폼 열기·닫기 | JS data-target hidden 토글; 데이터 생성·취소·초기화 안함 | 대상+열기/닫기, 제출 결과와 구분 | core/web/static/app.js:213 · JS 동작 대조 |
| B173 · `core/web/templates/projects/detail.html:56` | 추가 | 프로젝트 참고 주소 등록 | POST · POST Link 등록 | 프로젝트 링크 추가 | core/web/views/projects.py:302 · 소스 동작 대조 |

## projects/docs.html

| ID·근거 | 현재 문구 / 접근성 이름 | 사용자 목적 | 예상·실제 결과 | 권장 문구·보조 안내 | 동작 근거·판정 |
| --- | --- | --- | --- | --- | --- |
| B174 · `core/web/templates/projects/docs.html:11` | file | Markdown을 문서로 등록 | POST · 파일 선택 후 POST 업로드·생성 | Markdown 문서 올리기; 선택 즉시 제출 안내 | core/web/views/docs.py:65 · 소스 동작 대조 |
| B175 · `core/web/templates/projects/docs.html:12` | .md 올리기 | Markdown을 문서로 등록 | POST · 파일 선택 후 POST 업로드·생성 | Markdown 문서 올리기; 선택 즉시 제출 안내 | core/web/views/docs.py:65 · 소스 동작 대조 |
| B176 · `core/web/templates/projects/docs.html:14` | 새 문서 | 새 문서 바로 작성 | POST · POST 빈 문서 생성 후 해당 문서 이동 | 문서가 있을 때 새 문서 유지; 빈 상태는 첫 문서 만들기 하나만(F27) | core/web/views/docs.py:54 · 소스 동작 대조 |
| B177 · `core/web/templates/projects/docs.html:18` | {{ d.title }} {{ d.updated_by.display_name }} {{ d.created_by.display_name }} · {{ d.get_updated_source_display }} · v{{ d.version }} · {{ d.updated_at\|date:"n/j" }} | 기존 문서 열기 | GET ?doc=id로 선택 문서 표시 | 문서 제목 유지 | core/web/views/docs.py:24 · 소스 동작 대조 |
| B178 · `core/web/templates/projects/docs.html:44` | 본문 편집 | 문서 본문 작성 시작 | JS beginEditing; POST 저장 아님 | 본문 편집 유지; 자동 저장 상태 안내 | core/web/static/notes.js:436 · 개별 검토 |
| B179 · `core/web/templates/projects/docs.html:51` | 저장 | 문서 수동 저장(JS 미실행) | JS 초기화 후 숨김; fallback 폼 POST 저장 | fallback 문서 저장; 실제 화면 주 버튼 집계 안함 | core/web/static/notes.js:149 · 개별 검토 |
| B180 · `core/web/templates/projects/docs.html:56` | 쓰는 법 | 해당 묶음·상세 내용 확인 | HTML details 접힘/펼침; 데이터 변경 없음 | 문맥이 드러나는 현재 제목 유지 | core/web/templates/projects/docs.html:56 · 소스 대응 |
| B181 · `core/web/templates/projects/docs.html:61` | 삭제 | 문서 본문까지 제거 | POST · POST 문서 삭제 | 문서 삭제 | core/web/views/docs.py:102 · 소스 동작 대조 |
| B182 · `core/web/templates/projects/docs.html:68` | 첫 문서 만들기 | 새 문서 바로 작성 | POST · POST 빈 문서 생성 후 해당 문서 이동 | 첫 문서 만들기 유지; 빈 상태의 상단 중복 생성 버튼 제거 후보(F27) | core/web/views/docs.py:54 · 소스 동작 대조 |

## projects/empty.html

| ID·근거 | 현재 문구 / 접근성 이름 | 사용자 목적 | 예상·실제 결과 | 권장 문구·보조 안내 | 동작 근거·판정 |
| --- | --- | --- | --- | --- | --- |
| B183 · `core/web/templates/projects/empty.html:7` | 새 프로젝트 | 새 프로젝트 생성 | GET · GET 생성 다이얼로그; 유효 POST 프로젝트 생성 | 새 프로젝트 / 프로젝트 만들기 | core/web/views/projects.py:121 · 소스 동작 대조 |

## projects/repo.html

| ID·근거 | 현재 문구 / 접근성 이름 | 사용자 목적 | 예상·실제 결과 | 권장 문구·보조 안내 | 동작 근거·판정 |
| --- | --- | --- | --- | --- | --- |
| B184 · `core/web/templates/projects/repo.html:17` | 저장소 연결 | 프로젝트를 기존 저장소에 연결 | POST connect_repo; 성공 시 저장소 화면 복귀 | 저장소 연결 | core/web/views/github.py:177 · 소스 동작 대조 |
| B185 · `core/web/templates/projects/repo.html:21` | GitHub 연결 | 개인 GitHub 연결 단계 찾기 | GET 프로필; OAuth 바로 시작 아님 | 프로필에서 GitHub 연결 | core/web/templates/projects/repo.html:21 · 개별 검토 |
| B186 · `core/web/templates/projects/repo.html:25` | {{ state.conn.full_name }} | 관련 자료·설정 열기 | GET https://github.com/{{ state.conn.full_name }} 새 탭 | 대상 제목 유지; 변수 URL의 실제 값은 데이터별 확인 필요 | core/web/templates/projects/repo.html:25 · 동적 URL/외부 화면 미검증 |
| B187 · `core/web/templates/projects/repo.html:29` | 연결 해제 | 프로젝트와 저장소 연결 해제 | POST · POST RepoConnection 해제; 외부 저장소 유지 | 저장소 연결 해제 | core/web/views/github.py:229 · 소스 동작 대조 |
| B188 · `core/web/templates/projects/repo.html:43` | GitHub에서 변경 | 관련 자료·설정 열기 | GET https://github.com/{{ state.conn.full_name }}/settings/access 새 탭 | 대상 제목 유지; 변수 URL의 실제 값은 데이터별 확인 필요 | core/web/templates/projects/repo.html:43 · 동적 URL/외부 화면 미검증 |
| B189 · `core/web/templates/projects/repo.html:59` | 규칙 저장 | 저장소 연동 규칙 저장 | POST · POST 기본 담당·자동 가져오기 등 규칙 저장 | 저장소 규칙 저장 | core/web/views/github.py:242 · 소스 동작 대조 |
| B190 · `core/web/templates/projects/repo.html:62` | 지금 확인 | 최신 저장소 이슈 확인 | POST · POST GitHub 열린 이슈 갱신; 자동 가져오기 규칙 영향 별도 | GitHub 이슈 새로 확인 | core/web/views/github.py:259 · 소스 동작 대조 |
| B191 · `core/web/templates/projects/repo.html:73` | 태스크로 가져오기 | 이슈를 내가 맡을 태스크로 등록 | POST · POST actor 담당 태스크 생성·이슈 연결; 이미 가져왔으면 기존 태스크 반환 | 내 태스크로 가져오기 | core/web/views/github.py:275 · 소스 동작 대조 |
| B192 · `core/web/templates/projects/repo.html:88` | {{ e.task.number }} | 태스크 내용 확인 | GET · 태스크 상세 페이지 | 유지 | core/web/views/tasks.py:136 · 소스 동작 대조 |
| B193 · `core/web/templates/projects/repo.html:90` | 연결 | 이벤트를 연결할 태스크 선택 | HTML details 선택 폼 열기; 아직 연결 저장 아님 | 연결할 태스크 선택 | core/web/templates/projects/repo.html:89 · 개별 검토 |
| B194 · `core/web/templates/projects/repo.html:96` | 연결 | GitHub 이벤트를 태스크 증거로 연결 | POST · POST 이벤트의 task 참조 저장; 태스크 생성·상태 변경 아님 | 태스크에 이벤트 연결 | core/web/views/github.py:353 · 소스 동작 대조 |

## projects/settings.html

| ID·근거 | 현재 문구 / 접근성 이름 | 사용자 목적 | 예상·실제 결과 | 권장 문구·보조 안내 | 동작 근거·판정 |
| --- | --- | --- | --- | --- | --- |
| B195 · `core/web/templates/projects/settings.html:16` | {{ label }} {{ group_rows\|length }} | 원하는 설정 묶음 찾기 | JS 해당 섹션 열고 다른 섹션 닫기·스크롤; 저장 안함 | 섹션 제목 유지 | core/web/static/app.js:195 · JS 동작 대조 |
| B196 · `core/web/templates/projects/settings.html:18` | 프로젝트 설정 저장 | 프로젝트 규칙 변경 저장 | POST 잠금 제외 프로젝트 설정 저장 | 프로젝트 설정 저장 | core/web/views/projects.py:369 · 소스 동작 대조 |
| B197 · `core/web/templates/projects/settings.html:21` | {{ label }} {{ group_rows\|length }}개 항목 | 해당 묶음·상세 내용 확인 | HTML details 접힘/펼침; 데이터 변경 없음 | 문맥이 드러나는 현재 제목 유지 | core/web/templates/projects/settings.html:21 · 소스 대응 |
| B198 · `core/web/templates/projects/settings.html:48` | 저장소 규칙 저장 | 저장소 연동 규칙 저장 | POST · POST 기본 담당·자동 가져오기 등 규칙 저장 | 저장소 규칙 저장 | core/web/views/github.py:242 · 소스 동작 대조 |
| B199 · `core/web/templates/projects/settings.html:50` | GitHub 탭 | 프로젝트 저장소 연동 관리 | GET · 저장소 연결·규칙·이슈·이벤트 화면; 조건부 이슈 동기화 가능 | 유지 | core/web/views/github.py:177 · 소스 동작 대조 |
| B200 · `core/web/templates/projects/settings.html:66` | 보관 해제 | 보관 프로젝트 다시 사용 | POST · POST 보관 해제 | 프로젝트 보관 해제 | core/web/views/projects.py:277 · 소스 동작 대조 |
| B201 · `core/web/templates/projects/settings.html:72` | 프로젝트 삭제 | 보관 프로젝트 영구 제거 | POST · POST 관리자·보관 조건 검사 후 삭제 | 프로젝트 삭제 | core/web/views/projects.py:288 · 소스 동작 대조 |
| B202 · `core/web/templates/projects/settings.html:82` | 프로젝트 보관 | 프로젝트를 활성 업무에서 보관 | POST · POST 보관; cancel_open=1이면 미완료 태스크 취소도 수행 | 프로젝트 보관 / 미완료 태스크를 취소하고 프로젝트 보관 | core/web/views/projects.py:252 · 소스 동작 대조 |
| B203 · `core/web/templates/projects/settings.html:87` | 미완료까지 취소하고 보관 | 프로젝트 종료와 미완료 태스크 처리 | POST cancel_open=1 미완료 태스크 취소 후 보관 | 미완료 태스크를 취소하고 프로젝트 보관; 확인에 대상 범위 안내 | core/web/views/projects.py:252 · 개별 검토 |
| B204 · `core/web/templates/projects/settings.html:102` | 거버넌스 저장 | 프로젝트 추가 합의 저장 | POST action=governance_extra 본문 저장 | 프로젝트 거버넌스 저장 | core/web/views/projects.py:379 · 소스 동작 대조 |

## search.html

| ID·근거 | 현재 문구 / 접근성 이름 | 사용자 목적 | 예상·실제 결과 | 권장 문구·보조 안내 | 동작 근거·판정 |
| --- | --- | --- | --- | --- | --- |
| B205 · `core/web/templates/search.html:10` | 검색 | 태스크 찾기 | GET q 검색; 번호·제목·프로젝트명 대상 | 검색 유지; 검색 범위 안내 | core/web/views/search.py:10 · 소스 동작 대조 |

## settings/_setting_row.html

| ID·근거 | 현재 문구 / 접근성 이름 | 사용자 목적 | 예상·실제 결과 | 권장 문구·보조 안내 | 동작 근거·판정 |
| --- | --- | --- | --- | --- | --- |
| B206 · `core/web/templates/settings/_setting_row.html:10` | 조직에서 잠금 · 조직 설정에서 해제 | 조직 규칙 관리 | GET · 조직 설정·잠금 화면 | 유지 | core/web/views/orgs.py:350 · 소스 동작 대조 |

## settings/_tabs.html

| ID·근거 | 현재 문구 / 접근성 이름 | 사용자 목적 | 예상·실제 결과 | 권장 문구·보조 안내 | 동작 근거·판정 |
| --- | --- | --- | --- | --- | --- |
| B207 · `core/web/templates/settings/_tabs.html:4` | 프로필 | 개인 정보·연동 관리 | GET · 프로필·개인 GitHub/Discord 연결 화면 | 유지 | core/web/views/settings.py:16 · 소스 동작 대조 |
| B208 · `core/web/templates/settings/_tabs.html:5` | 환경설정 | 개인 환경설정 관리 | GET · 개인 설정 화면 | 유지 | core/web/views/settings.py:82 · 소스 동작 대조 |
| B209 · `core/web/templates/settings/_tabs.html:6` | API 토큰 | API·AI 연결 자격 관리 | GET · 토큰 관리·연결 안내 화면 | 유지 | core/web/views/settings.py:49 · 소스 동작 대조 |
| B210 · `core/web/templates/settings/_tabs.html:7` | 운영 상태 | 운영 상태 확인 | GET · staff 전용 실행 상태 화면 | 유지 | core/web/views/ops.py:21 · 소스 동작 대조 |

## settings/preferences.html

| ID·근거 | 현재 문구 / 접근성 이름 | 사용자 목적 | 예상·실제 결과 | 권장 문구·보조 안내 | 동작 근거·판정 |
| --- | --- | --- | --- | --- | --- |
| B211 · `core/web/templates/settings/preferences.html:14` | 환경설정 저장 | 개인 설정 저장 | POST 개인 환경설정 값 저장 | 환경설정 저장 | core/web/views/settings.py:82 · 소스 동작 대조 |

## settings/profile.html

| ID·근거 | 현재 문구 / 접근성 이름 | 사용자 목적 | 예상·실제 결과 | 권장 문구·보조 안내 | 동작 근거·판정 |
| --- | --- | --- | --- | --- | --- |
| B212 · `core/web/templates/settings/profile.html:8` | 저장 | 표시 이름 변경 | POST display_name만 저장 | 표시 이름 저장 | core/web/views/settings.py:16 · 소스 동작 대조 |
| B213 · `core/web/templates/settings/profile.html:21` | 연결 해제 | 개인 Discord 연결·알림 중단 | POST 개인 Discord 계정 해제, 마감 알림 DM 중단 | Discord 계정 연결 해제 | core/web/views/settings.py:42 · 개별 검토 |
| B214 · `core/web/templates/settings/profile.html:25` | Discord 연결 | 개인 Discord 계정 연결 준비 | POST · POST 연결 코드 발급; 연결 완료는 봇 DM 후속 단계 | Discord 연결 코드 받기 | core/web/views/settings.py:34 · 소스 동작 대조 |
| B215 · `core/web/templates/settings/profile.html:34` | 연결 해제 | 개인 GitHub 인증 연결 중단 | POST · POST GitHubIdentity 삭제; 외부 계정 유지 | GitHub 계정 연결 해제 | core/web/views/github.py:154 · 소스 동작 대조 |
| B216 · `core/web/templates/settings/profile.html:38` | 다시 확인 | 접근 가능한 저장소 갱신 | POST · POST 개인 저장소 캐시 갱신 후 프로필 이동 | 접근 가능한 저장소 다시 확인 | core/web/views/github.py:139 · 소스 동작 대조 |
| B217 · `core/web/templates/settings/profile.html:40` | GitHub 연결 | 개인 GitHub 연동 시작 | GET · GET 외부 OAuth 권한 확인 단계 | GitHub 계정 연결 | core/web/views/github.py:95 · 소스 동작 대조 |

## settings/tokens.html

| ID·근거 | 현재 문구 / 접근성 이름 | 사용자 목적 | 예상·실제 결과 | 권장 문구·보조 안내 | 동작 근거·판정 |
| --- | --- | --- | --- | --- | --- |
| B218 · `core/web/templates/settings/tokens.html:23` | 폐기 | API 인증 수단 사용 중단 | POST · POST 본인 토큰 revoke | 토큰 폐기 | core/web/views/settings.py:75 · 소스 동작 대조 |
| B219 · `core/web/templates/settings/tokens.html:30` | 폐기된 토큰 {{ revoked_tokens\|length }}개 | 해당 묶음·상세 내용 확인 | HTML details 접힘/펼침; 데이터 변경 없음 | 문맥이 드러나는 현재 제목 유지 | core/web/templates/settings/tokens.html:30 · 소스 대응 |
| B220 · `core/web/templates/settings/tokens.html:44` | 토큰 발급 | 연결 자격 발급 | POST scope와 purpose로 토큰 발급; 원문 한 번 표시 | 토큰 발급 유지 + AI용 정책·권한 안내 | core/web/views/settings.py:49 · 소스 동작 대조 |
| B221 · `core/web/templates/settings/tokens.html:61` | 복사 | AI 클라이언트 서버 주소 전달 | JS mcp_url/mcp 복사 | 서버 주소 복사 | core/web/templates/settings/tokens.html:61 · 개별 검토 |
| B222 · `core/web/templates/settings/tokens.html:67` | 복사 | 클라이언트 설정 명령 준비 | JS TOKEN placeholder를 포함한 명령 복사; 토큰 자동 삽입 안함 | 설정 명령 복사; 토큰 교체 안내 유지 | core/web/templates/settings/tokens.html:67 · 개별 검토 |

## tasks/_checklist.html

| ID·근거 | 현재 문구 / 접근성 이름 | 사용자 목적 | 예상·실제 결과 | 권장 문구·보조 안내 | 동작 근거·판정 |
| --- | --- | --- | --- | --- | --- |
| B223 · `core/web/templates/tasks/_checklist.html:9` | {{ item.text }} | 체크 항목 완료·순서·삭제 관리 | POST · POST action=toggle/up/down/delete | 항목 완료/위로/아래로/삭제; 대상 접근성 이름 | core/web/views/tasks.py:352 · 소스 동작 대조 |
| B224 · `core/web/templates/tasks/_checklist.html:11` | ↑ / 접근성: 위로 | 체크 항목 순서 올리기 | POST checklist_action up | 체크 항목 위로 이동 aria-label | core/web/templates/tasks/_checklist.html:11 · 개별 검토 |
| B225 · `core/web/templates/tasks/_checklist.html:12` | ↓ / 접근성: 아래로 | 체크 항목 순서 내리기 | POST checklist_action down | 체크 항목 아래로 이동 aria-label | core/web/templates/tasks/_checklist.html:12 · 개별 검토 |
| B226 · `core/web/templates/tasks/_checklist.html:13` | ✕ / 접근성: 삭제 | 체크 항목 제거 | POST checklist_action delete | 체크 항목 삭제 aria-label | core/web/templates/tasks/_checklist.html:13 · 개별 검토 |
| B227 · `core/web/templates/tasks/_checklist.html:19` | 추가 | 체크 항목 등록 | POST · POST 체크리스트 생성 | 체크 항목 추가 | core/web/views/tasks.py:341 · 소스 동작 대조 |

## tasks/_decisions.html

| ID·근거 | 현재 문구 / 접근성 이름 | 사용자 목적 | 예상·실제 결과 | 권장 문구·보조 안내 | 동작 근거·판정 |
| --- | --- | --- | --- | --- | --- |
| B228 · `core/web/templates/tasks/_decisions.html:47` | 확인 웹에서 확인 | 수집된 내 의사결정이 맞다고 확인 | POST · POST 본인 user_input confirmed 전환; AI 판단 승인 아님 | 내 의사결정으로 확인 | core/web/views/decisions.py:56 · 소스 동작 대조 |
| B229 · `core/web/templates/tasks/_decisions.html:52` | 기록 제외 | 내 입력 기록 제외 | POST · POST rejected 전환; 원본 감사 기록 보존 | 기록 제외 | core/web/views/decisions.py:67 · 소스 동작 대조 |
| B230 · `core/web/templates/tasks/_decisions.html:57` | 정정 기록 추가 | 해당 묶음·상세 내용 확인 | HTML details 접힘/펼침; 데이터 변경 없음 | 문맥이 드러나는 현재 제목 유지 | core/web/templates/tasks/_decisions.html:57 · 소스 대응 |
| B231 · `core/web/templates/tasks/_decisions.html:75` | 정정 기록 저장 | 의사결정 기록을 이력으로 정정 | POST · POST 원본과 연결된 새 정정 기록 생성 | 정정 기록 저장 | core/web/views/decisions.py:84 · 소스 동작 대조 |

## tasks/_extend.html

| ID·근거 | 현재 문구 / 접근성 이름 | 사용자 목적 | 예상·실제 결과 | 권장 문구·보조 안내 | 동작 근거·판정 |
| --- | --- | --- | --- | --- | --- |
| B232 · `core/web/templates/tasks/_extend.html:6` | 저장 | 목표일 최초 지정 또는 연장 | POST · POST 날짜·사유 저장; 같은 연장 폼 사용 | 목표일 저장 / 목표일 연장 | core/web/views/tasks.py:264 · 소스 동작 대조 |

## tasks/_git.html

| ID·근거 | 현재 문구 / 접근성 이름 | 사용자 목적 | 예상·실제 결과 | 권장 문구·보조 안내 | 동작 근거·판정 |
| --- | --- | --- | --- | --- | --- |
| B233 · `core/web/templates/tasks/_git.html:5` | 저장소 연결 | 프로젝트 저장소 연동 관리 | GET · 저장소 연결·규칙·이슈·이벤트 화면; 조건부 이슈 동기화 가능 | 유지 | core/web/views/github.py:177 · 소스 동작 대조 |
| B234 · `core/web/templates/tasks/_git.html:7` | GitHub 연결 | 개인 GitHub 연결 준비 | GET 프로필; 직접 OAuth 시작 아님 | 프로필에서 GitHub 연결 | core/web/templates/tasks/_git.html:7 · 개별 검토 |
| B235 · `core/web/templates/tasks/_git.html:22` | 이슈 연결 | 기존 이슈 연결 | POST · POST GitHub 이슈 번호 연결 | 이슈 연결 | core/web/views/github.py:446 · 소스 동작 대조 |
| B236 · `core/web/templates/tasks/_git.html:24` | 이슈 만들기 | 외부 이슈 생성 | POST · POST GitHub 이슈 생성 후 태스크 연결 | GitHub 이슈 만들기 | core/web/views/github.py:500 · 소스 동작 대조 |
| B237 · `core/web/templates/tasks/_git.html:27` | 이슈 #{{ gh.link.issue_number }} 닫기 | 완료 태스크의 외부 이슈 닫기 | POST · POST 완료·열린 이슈 조건 확인 후 외부 닫기 요청 | 이슈 #N 닫기 | core/web/views/github.py:529 · 소스 동작 대조 |
| B238 · `core/web/templates/tasks/_git.html:29` | 이슈 연결 해제 | 태스크 외부 참조만 해제 | POST · POST what=issue/branch/pr/all 참조 해제; 외부 객체 삭제 아님 | 대상 연결 해제 / 이 태스크의 GitHub 연결 모두 해제 | core/web/views/github.py:485 · 소스 동작 대조 |
| B239 · `core/web/templates/tasks/_git.html:38` | 브랜치 연결 | 기존 브랜치 연결 | POST · POST 브랜치 참조 연결 | 브랜치 연결 | core/web/views/github.py:468 · 소스 동작 대조 |
| B240 · `core/web/templates/tasks/_git.html:42` | 브랜치 만들기 | 외부 브랜치 생성 | POST · POST GitHub 브랜치 생성 후 연결 | GitHub 브랜치 만들기 | core/web/views/github.py:514 · 소스 동작 대조 |
| B241 · `core/web/templates/tasks/_git.html:45` | 브랜치 연결 해제 | 태스크 외부 참조만 해제 | POST · POST what=issue/branch/pr/all 참조 해제; 외부 객체 삭제 아님 | 대상 연결 해제 / 이 태스크의 GitHub 연결 모두 해제 | core/web/views/github.py:485 · 소스 동작 대조 |
| B242 · `core/web/templates/tasks/_git.html:59` | PR 열기 | 연결된 PR 읽기 | GET 기존 gh.pr_url 외부 웹페이지; PR 생성·재개 아님 | GitHub에서 PR 보기 | core/web/templates/tasks/_git.html:59 · 개별 검토 |
| B243 · `core/web/templates/tasks/_git.html:61` | PR 연결 해제 | 태스크 외부 참조만 해제 | POST · POST what=issue/branch/pr/all 참조 해제; 외부 객체 삭제 아님 | 대상 연결 해제 / 이 태스크의 GitHub 연결 모두 해제 | core/web/views/github.py:485 · 소스 동작 대조 |
| B244 · `core/web/templates/tasks/_git.html:78` | GitHub 연결 전체 해제 | 이 태스크의 외부 참조 전부 해제 | POST what=all 태스크 Git 연결 제거; 개인 계정·프로젝트 저장소 해제 아님 | 이 태스크의 GitHub 연결 모두 해제 | core/web/views/github.py:485 · 개별 검토 |

## tasks/_panel.html

| ID·근거 | 현재 문구 / 접근성 이름 | 사용자 목적 | 예상·실제 결과 | 권장 문구·보조 안내 | 동작 근거·판정 |
| --- | --- | --- | --- | --- | --- |
| B245 · `core/web/templates/tasks/_panel.html:3` | ← {{ task.project.name }} | 프로젝트 태스크 확인 | GET · 선택 프로젝트 목록 또는 보드 | 유지 | core/web/views/projects.py:182 · 소스 동작 대조 |
| B246 · `core/web/templates/tasks/_panel.html:9` | 링크 복사 | 해당 주소·텍스트 전달 | JS clipboard 복사; 실패 수동 prompt 취소에도 성공 안내 가능 | 대상을 포함한 복사 문구; 성공 분기 수정 | core/web/static/app.js:131 · 동작 수정 필요 |
| B247 · `core/web/templates/tasks/_panel.html:11` | 크게 보기 | 태스크 상세를 넓게 읽기 | JS 패널 폭 변경·선호 저장; 글자 크기 변경 아님 | 패널 넓히기 / 패널 줄이기 | core/web/static/app.js:188 · JS 동작 대조 |
| B248 · `core/web/templates/tasks/_panel.html:12` | 닫기 / 접근성: 태스크 상세 닫기 | 태스크 패널 닫기 | JS 패널 비우기·이전 URL/스크롤 복원; 저장·취소 요청 없음 | 태스크 상세 닫기; 자동 저장 상태 안내 | core/web/static/app.js:181 · JS 동작 대조 |
| B249 · `core/web/templates/tasks/_panel.html:20` | {{ task.title }} / 접근성: 제목 | 태스크 내용 편집 | POST · POST 지정 field 저장; change, 메모는 keyup 600ms도 적용 | 필드 이름 유지 + 자동 저장 시점 안내 | core/web/views/tasks.py:229 · 소스 동작 대조 |
| B250 · `core/web/templates/tasks/_panel.html:26` | {{ p.name }} / 접근성: 프로젝트 | 담당자·프로젝트·기한 미정 사유 변경 | POST · change POST 메타 정보 저장 | 필드 이름 유지 + 저장 시점 안내 | core/web/views/tasks.py:167 · 소스 동작 대조 |
| B251 · `core/web/templates/tasks/_panel.html:33` | {{ u.display_name }} / 접근성: 담당자 | 담당자·프로젝트·기한 미정 사유 변경 | POST · change POST 메타 정보 저장 | 필드 이름 유지 + 저장 시점 안내 | core/web/views/tasks.py:167 · 소스 동작 대조 |
| B252 · `core/web/templates/tasks/_panel.html:41` | {{ label }} / 접근성: 상태 | 태스크 상태 전환 | POST · POST 상태 변경; 막힘은 사유 입력 먼저; 서버 규칙 적용 | 태스크 전체 상태임을 명시; 상태 선택은 유지 | core/web/views/tasks.py:207 · 소스 동작 대조 |
| B253 · `core/web/templates/tasks/_panel.html:52` | {{ n }} / 접근성: 중요도 | 태스크 중요도 조정 | POST · change POST 중요도 저장 | 중요도 라벨 유지 | core/web/views/tasks.py:241 · 소스 동작 대조 |
| B254 · `core/web/templates/tasks/_panel.html:62` | {{ task.description }} / 접근성: 설명 | 태스크 내용 편집 | POST · POST 지정 field 저장; change, 메모는 keyup 600ms도 적용 | 필드 이름 유지 + 자동 저장 시점 안내 | core/web/views/tasks.py:229 · 소스 동작 대조 |
| B255 · `core/web/templates/tasks/_panel.html:68` | 취소 목표일 연장하기 목표일 정하기 | 목표일 지정·연장 입력 시작 | JS 연장 폼 펼침; POST 날짜 저장 아님 | 목표일 정하기 / 목표일 연장하기 / 입력 닫기 | core/web/templates/tasks/_panel.html:68 · 개별 검토 |
| B256 · `core/web/templates/tasks/_panel.html:75` | {{ task.no_due_reason }} / 접근성: 기한 미정 사유 | 담당자·프로젝트·기한 미정 사유 변경 | POST · change POST 메타 정보 저장 | 필드 이름 유지 + 저장 시점 안내 | core/web/views/tasks.py:167 · 소스 동작 대조 |
| B257 · `core/web/templates/tasks/_panel.html:85` | {{ task.done_when }} / 접근성: 완료 조건 | 태스크 내용 편집 | POST · POST 지정 field 저장; change, 메모는 keyup 600ms도 적용 | 필드 이름 유지 + 자동 저장 시점 안내 | core/web/views/tasks.py:229 · 소스 동작 대조 |
| B258 · `core/web/templates/tasks/_panel.html:88` | {{ task.next_action }} / 접근성: 다음 행동 | 태스크 내용 편집 | POST · POST 지정 field 저장; change, 메모는 keyup 600ms도 적용 | 필드 이름 유지 + 자동 저장 시점 안내 | core/web/views/tasks.py:229 · 소스 동작 대조 |
| B259 · `core/web/templates/tasks/_panel.html:92` | {{ task.notes }} / 접근성: 진행 메모 | 태스크 내용 편집 | POST · POST 지정 field 저장; change, 메모는 keyup 600ms도 적용 | 필드 이름 유지 + 자동 저장 시점 안내 | core/web/views/tasks.py:229 · 소스 동작 대조 |
| B260 · `core/web/templates/tasks/_panel.html:96` | GitHub · {{ gh_summary }} | 해당 묶음·상세 내용 확인 | HTML details 접힘/펼침; 데이터 변경 없음 | 문맥이 드러나는 현재 제목 유지 | core/web/templates/tasks/_panel.html:96 · 소스 대응 |
| B261 · `core/web/templates/tasks/_panel.html:98` | 변경 이력 {{ history\|length }} | 해당 묶음·상세 내용 확인 | HTML details 접힘/펼침; 데이터 변경 없음 | 문맥이 드러나는 현재 제목 유지 | core/web/templates/tasks/_panel.html:98 · 소스 대응 |
| B262 · `core/web/templates/tasks/_panel.html:99` | 더보기 | 해당 묶음·상세 내용 확인 | HTML details 접힘/펼침; 데이터 변경 없음 | 문맥이 드러나는 현재 제목 유지 | core/web/templates/tasks/_panel.html:99 · 소스 대응 |
| B263 · `core/web/templates/tasks/_panel.html:102` | 태스크 삭제 | 태스크 영구 제거 | POST · POST 태스크 삭제 | 태스크 삭제 | core/web/views/tasks.py:148 · 소스 동작 대조 |

## tasks/_refs.html

| ID·근거 | 현재 문구 / 접근성 이름 | 사용자 목적 | 예상·실제 결과 | 권장 문구·보조 안내 | 동작 근거·판정 |
| --- | --- | --- | --- | --- | --- |
| B264 · `core/web/templates/tasks/_refs.html:6` | {{ d.title }} | 프로젝트 문서 읽기·편집 | GET · 문서 목록 또는 doc 파라미터의 문서 표시 | 유지 | core/web/views/docs.py:24 · 소스 동작 대조 |
| B265 · `core/web/templates/tasks/_refs.html:7` | ✕ | 태스크 문서 참조 제거 | POST 연결 해제; 문서 본문 유지 | aria-label: 문서 이름 + 연결 해제 | core/web/views/docs.py:134 · 개별 검토 |
| B266 · `core/web/templates/tasks/_refs.html:11` | {{ n.title }} | 회의 기록 확인 | GET · 조직 회의록 목록 또는 지정 회의록 표시 | 유지 | core/web/views/notes.py:33 · 소스 동작 대조 |
| B267 · `core/web/templates/tasks/_refs.html:12` | ✕ | 태스크 회의록 참조 제거 | POST 연결 해제; 회의록 유지 | aria-label: 회의록 이름 + 연결 해제 | core/web/views/notes.py:176 · 개별 검토 |
| B268 · `core/web/templates/tasks/_refs.html:15` | {{ l.title }} | 관련 자료·설정 열기 | GET {{ l.url }} 새 탭 | 대상 제목 유지; 변수 URL의 실제 값은 데이터별 확인 필요 | core/web/templates/tasks/_refs.html:15 · 동적 URL/외부 화면 미검증 |
| B269 · `core/web/templates/tasks/_refs.html:16` | 삭제 | 참고 링크만 제거 | POST · POST Link 레코드 삭제; 외부 사이트 유지 | 링크 삭제 | core/web/views/tasks.py:402 · 소스 동작 대조 |
| B270 · `core/web/templates/tasks/_refs.html:25` | 연결 | 기존 문서를 참고로 연결 | POST · POST 태스크·문서 참조 추가 | 문서 연결 | core/web/views/docs.py:117 · 소스 동작 대조 |
| B271 · `core/web/templates/tasks/_refs.html:33` | 연결 | 기존 회의록을 참고로 연결 | POST · POST 태스크·회의록 참조 추가 | 회의록 연결 | core/web/views/notes.py:161 · 소스 동작 대조 |
| B272 · `core/web/templates/tasks/_refs.html:35` | ＋ 외부 주소 추가 | 입력 폼 열기·닫기 | JS data-target hidden 토글; 데이터 생성·취소·초기화 안함 | 대상+열기/닫기, 제출 결과와 구분 | core/web/static/app.js:213 · JS 동작 대조 |
| B273 · `core/web/templates/tasks/_refs.html:40` | 추가 | 태스크 참고 주소 등록 | POST · POST Link 등록 | 외부 링크 추가 | core/web/views/tasks.py:387 · 소스 동작 대조 |

## tasks/_row.html

| ID·근거 | 현재 문구 / 접근성 이름 | 사용자 목적 | 예상·실제 결과 | 권장 문구·보조 안내 | 동작 근거·판정 |
| --- | --- | --- | --- | --- | --- |
| B274 · `core/web/templates/tasks/_row.html:28` | {{ code\|status_mark }} {{ label }} / 접근성: 상태 | 태스크 상태 전환 | POST · POST 상태 변경; 막힘은 사유 입력 먼저; 서버 규칙 적용 | 태스크 전체 상태임을 명시; 상태 선택은 유지 | core/web/views/tasks.py:207 · 소스 동작 대조 |
| B275 · `core/web/templates/tasks/_row.html:39` | 오늘 제외 / 접근성: 오늘 할 일 목록에서 빼기 | 오늘 계획에서만 제외 | POST · POST 오늘 목록 제외; 태스크 삭제·취소 아님 | 오늘 목록에서 빼기 | core/web/views/today.py:208 · 소스 동작 대조 |
| B276 · `core/web/templates/tasks/_row.html:41` | 오늘 제외 / 접근성: 오늘 할 일 목록에서 빼기 | 오늘 계획에서만 제외 | POST · POST 오늘 목록 제외; 태스크 삭제·취소 아님 | 오늘 목록에서 빼기 | core/web/views/today.py:208 · 소스 동작 대조 |
| B277 · `core/web/templates/tasks/_row.html:43` | 오늘 추가 / 접근성: 오늘 할 일 목록에 담기 | 기존 태스크를 오늘 계획에 등록 | POST · POST 본인 오늘 목록 추가 | 오늘 목록에 추가 | core/web/views/today.py:200 · 소스 동작 대조 |
| B278 · `core/web/templates/tasks/_row.html:46` | 바로가기 링크 복사 | 태스크 바로가기 전달 | JS /tasks/id 주소 클립보드 복사 | 태스크 링크 복사; 실패 fallback 성공 안내 수정 | core/web/static/app.js:142 · 개별 검토 |
| B279 · `core/web/templates/tasks/_row.html:48` | ↑ / 접근성: 위로 | 오늘 순서 조정 | POST · POST 해당 태스크를 up/down 이동 | 오늘 목록에서 위로 / 아래로 | core/web/views/today.py:223 · 소스 동작 대조 |
| B280 · `core/web/templates/tasks/_row.html:49` | ↓ / 접근성: 아래로 | 오늘 순서 조정 | POST · POST 해당 태스크를 up/down 이동 | 오늘 목록에서 위로 / 아래로 | core/web/views/today.py:223 · 소스 동작 대조 |

## tasks/_stop.html

| ID·근거 | 현재 문구 / 접근성 이름 | 사용자 목적 | 예상·실제 결과 | 권장 문구·보조 안내 | 동작 근거·판정 |
| --- | --- | --- | --- | --- | --- |
| B281 · `core/web/templates/tasks/_stop.html:9` | 막힘으로 변경 사유 저장 | 일시정지·막힘 사유 기록 | POST · POST 사유 저장; block_pending이면 막힘으로 전환 | 막힘으로 변경 / 사유 저장 | core/web/views/tasks.py:289 · 소스 동작 대조 |
| B282 · `core/web/templates/tasks/_stop.html:10` | 취소 | 막힘 상태로 바꾸기 취소 | GET task_panel 재조회; 상태 변경 POST 안함 | 취소 유지 | core/web/views/tasks.py:142 · 개별 검토 |

## today/_head.html

| ID·근거 | 현재 문구 / 접근성 이름 | 사용자 목적 | 예상·실제 결과 | 권장 문구·보조 안내 | 동작 근거·판정 |
| --- | --- | --- | --- | --- | --- |
| B283 · `core/web/templates/today/_head.html:7` | {{ counts.done_today }} 오늘 완료 | 담당 태스크 확인 | GET · 담당자·묶음·정렬·필터 조건에 맞는 태스크 목록 표시 | 유지 | core/web/views/me.py:15 · 소스 동작 대조 |
| B284 · `core/web/templates/today/_head.html:8` | {{ counts.done_7d }} 7일 완료 | 최근 완료 태스크 확인 | GET me?status=done_7d | 최근 7일 완료 | core/web/templates/today/_head.html:8 · 개별 검토 |
| B285 · `core/web/templates/today/_head.html:9` | {{ counts.my_open }} 미완료 | 담당 태스크 확인 | GET · 담당자·묶음·정렬·필터 조건에 맞는 태스크 목록 표시 | 유지 | core/web/views/me.py:15 · 소스 동작 대조 |
| B286 · `core/web/templates/today/_head.html:29` | 완료로 표시 진행 중으로 시작 | 집중 태스크 시작 또는 완료 | POST task_status가 focus 태스크 전체 상태 전환; 다음 행동만 완료 아님 | 태스크 완료로 표시 / 태스크 진행 시작 | core/web/views/tasks.py:207 · 개별 검토 |
| B287 · `core/web/templates/today/_head.html:31` | 진행 메모 열기 | 진행 메모 이어 쓰기 | GET task_panel?focus=notes 편집 가능한 태스크 패널·메모 포커스 | 진행 메모 열기 유지 | core/web/views/tasks.py:142 · 개별 검토 |
| B288 · `core/web/templates/today/_head.html:32` | 자세히 보기 | 집중 태스크 상세 확인 | GET task_panel 패널 표시; 상세 페이지 전체 이동 아님 | 자세히 보기 유지(집중 태스크 문맥); 필요 시 태스크 상세 열기 후보 | core/web/views/tasks.py:142 · 개별 검토 |

## today/_list.html

| ID·근거 | 현재 문구 / 접근성 이름 | 사용자 목적 | 예상·실제 결과 | 권장 문구·보조 안내 | 동작 근거·판정 |
| --- | --- | --- | --- | --- | --- |
| B289 · `core/web/templates/today/_list.html:10` | 일정 닫기 보기 | 월별 목표일 일정 확인·숨김 | GET cal 파라미터로 달력 표시/해제 | 일정 보기 / 일정 닫기 유지 | core/web/views/today.py:69 · 개별 검토 |
| B290 · `core/web/templates/today/_list.html:18` | {{ label }} / 접근성: 마감 기준 자동 담기 | 목표일 기준 자동 추가 조정 | POST · change POST auto_pull_days 저장 | 목표일 기준 자동 추가 · N일 이내 | core/web/views/today.py:230 · 소스 동작 대조 |
| B291 · `core/web/templates/today/_list.html:24` | {{ counts.due_today }} 오늘 마감 | 담당 태스크 확인 | GET · 담당자·묶음·정렬·필터 조건에 맞는 태스크 목록 표시 | 유지 | core/web/views/me.py:15 · 소스 동작 대조 |
| B292 · `core/web/templates/today/_list.html:25` | {{ counts.overdue }} 기한 초과 | 담당 태스크 확인 | GET · 담당자·묶음·정렬·필터 조건에 맞는 태스크 목록 표시 | 유지 | core/web/views/me.py:15 · 소스 동작 대조 |
| B293 · `core/web/templates/today/_list.html:26` | {{ counts.review }} 검토 대기 | 담당 태스크 확인 | GET · 담당자·묶음·정렬·필터 조건에 맞는 태스크 목록 표시 | 유지 | core/web/views/me.py:15 · 소스 동작 대조 |
| B294 · `core/web/templates/today/_list.html:27` | {{ counts.blocked }} 막힘 | 담당 태스크 확인 | GET · 담당자·묶음·정렬·필터 조건에 맞는 태스크 목록 표시 | 유지 | core/web/views/me.py:15 · 소스 동작 대조 |
| B295 · `core/web/templates/today/_list.html:30` | 제외한 태스크 복원 | 제외한 태스크를 다시 오늘 계획에 넣기 | POST 본인 오늘 제외 항목 복원; 삭제 태스크 복구 아님 | 오늘 목록에 복원 | core/web/views/today.py:216 · 개별 검토 |
| B296 · `core/web/templates/today/_list.html:34` | 오늘 완료 ({{ done_rows\|length }}) | 해당 묶음·상세 내용 확인 | HTML details 접힘/펼침; 데이터 변경 없음 | 문맥이 드러나는 현재 제목 유지 | core/web/templates/today/_list.html:34 · 소스 대응 |

## today/_quick.html

| ID·근거 | 현재 문구 / 접근성 이름 | 사용자 목적 | 예상·실제 결과 | 권장 문구·보조 안내 | 동작 근거·판정 |
| --- | --- | --- | --- | --- | --- |
| B297 · `core/web/templates/today/_quick.html:13` | 추가 | 태스크 생성 후 오늘 계획에 등록 | POST · POST 태스크 생성·today_add | 태스크 만들고 오늘에 추가 | core/web/views/today.py:176 · 소스 동작 대조 |
| B298 · `core/web/templates/today/_quick.html:13` | 취소 | 빠른 추가 입력 닫기 | JS 폼 숨김; 입력 내용 초기화 안함 | 입력 닫기 | core/web/static/app.js:213 · 개별 검토 |

## today/_schedule.html

| ID·근거 | 현재 문구 / 접근성 이름 | 사용자 목적 | 예상·실제 결과 | 권장 문구·보조 안내 | 동작 근거·판정 |
| --- | --- | --- | --- | --- | --- |
| B299 · `core/web/templates/today/_schedule.html:8` | ‹ / 접근성: 이전 달 | 달력 월·날짜 이동 | GET 오늘 페이지의 cal/day 조건 변경 | 이전 달 / 다음 달 / 이번 달 / 날짜 접근성 이름 유지 | core/web/views/today.py:69 · 소스 동작 대조 |
| B300 · `core/web/templates/today/_schedule.html:10` | › / 접근성: 다음 달 | 달력 월·날짜 이동 | GET 오늘 페이지의 cal/day 조건 변경 | 이전 달 / 다음 달 / 이번 달 / 날짜 접근성 이름 유지 | core/web/views/today.py:69 · 소스 동작 대조 |
| B301 · `core/web/templates/today/_schedule.html:11` | 이번 달 | 달력 월·날짜 이동 | GET 오늘 페이지의 cal/day 조건 변경 | 이전 달 / 다음 달 / 이번 달 / 날짜 접근성 이름 유지 | core/web/views/today.py:69 · 소스 동작 대조 |
| B302 · `core/web/templates/today/_schedule.html:12` | 닫기 | 월별 일정 화면 닫기 | GET today#today-list 캘린더 파라미터 제거 | 일정 닫기 | core/web/templates/today/_schedule.html:12 · 개별 검토 |
| B303 · `core/web/templates/today/_schedule.html:18` | {{ c.day }} ●{{ c.n }} / 접근성: {{ c.aria }} | 달력 월·날짜 이동 | GET 오늘 페이지의 cal/day 조건 변경 | 이전 달 / 다음 달 / 이번 달 / 날짜 접근성 이름 유지 | core/web/views/today.py:69 · 소스 동작 대조 |
| B304 · `core/web/templates/today/_schedule.html:25` | {{ t.title }} | 태스크 내용 읽기·편집 | GET · HTMX 패널 표시; focus=notes 메모 포커스, block=1 막힘 사유 | 유지 | core/web/views/tasks.py:142 · 소스 동작 대조 |

## 컨트롤이 없는 템플릿도 조사 범위에 포함

- `core/web/templates/_fields.html`
- `core/web/templates/dialog_page.html`
- `core/web/templates/oauth/error.html`
- `core/web/templates/settings/_setting_control.html`
- `core/web/templates/tasks/_history.html`
- `core/web/templates/tasks/detail.html`
- `core/web/templates/today.html`
