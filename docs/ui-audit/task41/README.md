# TASK-41 디자인 개선 검증

2026-10-04 · 브랜치 `codex/design-system-TASK-41`

## 결과

실제 Docker 앱의 디자인 판단은 GPT-6 Astra가 담당했다. 공통 토큰·카드·목록·상태 색을
정리하고 KPI, 오늘 집중 영역, 설정 폭, 목표일 액션, 문서 빈 상태와 편집 영역을 개선했다.
규칙과 이유는 루트 `DESIGN.md`에 있다.

## 검증 환경

- 미리보기: http://127.0.0.1:8017
- 독립 컨테이너 `pm-design-task41`, 이미지 `pm-design-audit:20261003`.
- 독립 볼륨 `pm-design-task41`, SQLite `/data/design.sqlite3`.
- 템플릿과 static은 현재 작업 폴더에서 읽기 전용으로 마운트했다.
- 가상 계정 `design_demo` / `DemoReview41!` (이 로컬 샘플 전용).
- 운영 DB·기존 로컬 서비스·Discord·외부 배포는 이 미리보기와 연결하지 않았다.
- 샘플 생성기는 `seed_preview.py`이며 정확한 독립 DB URL을 확인하고 실행한다.

## 시각 검증

Astra가 1280px 데스크톱에서 오늘, 내 태스크, 프로젝트 상세, 보드, 태스크 상세, 조직,
부하, 로드맵, 빈 문서, 회의록, 프로필, 포트폴리오 12개 화면을 수정 전후로 평가했다.
390×844에서는 오늘·프로젝트·태스크·회의록·조직 5개를 평가했다.
프로젝트 진입점 `/projects`는 이 앱에서 첫 프로젝트 상세로 이동한다.

모바일 KPI 3열 우선순위, 오늘 집중 영역 여백, 보드 상단을 추가 수정했다.
Astra의 마지막 판정은 필수 디자인 지적 해소·합격이다.

캡처는 다음 로컬 폴더에 보관했다:
`C:/Users/tjrdu/.codex/visualizations/2026/10/03/01a10243-206a-7071-a490-d1c734ef206d/task41/`

- `before-*.jpg`: 원본.
- `after-*.jpg`: 첫 수정본.
- `final-board.jpg`, `final-mobile-project.jpg`, `final2-mobile-today.jpg`: 필수 보정본.

## 실행 확인

- `core/.venv/Scripts/python.exe -m pytest web -q`: 웹 테스트 145개 통과.
- Docker `python manage.py check`: 문제 없음.
- 1280px 12개·390px 5개 화면에서 문서 전체 폭이 viewport를 넘지 않음을 DOM으로 확인.
- 360×800의 오늘·프로젝트·태스크·회의록 화면에서도 가로 넘침 없음, 주요 터치 액션 44px 확인.
- 브라우저에서 샘플 로그인, 목록의 상세 패널 열기, 실제 키 입력 후 자동 저장과
  새로고침 후 값 유지, 빈 문서의 첫 문서 생성 및 본문 저장·새로고침 후 유지 확인.
- 내 태스크의 검토 대기 필터 적용 후 URL 상태와 결과 4건 표시 확인.
- 브라우저 확인 시 수집된 console error 없음.

실제 사용자의 운영 데이터나 외부 연동은 이 검증에 포함되지 않는다.
어두운 색 토큰은 구현했지만 Astra의 시각 평가는 밝은 화면을 대상으로 한다.

## 미리보기 다시 열기

기존 미리보기는 `docker start pm-design-task41` 후 위 주소로 연다.
스타일 변경 후에는 `docker exec pm-design-task41 python manage.py collectstatic --noinput`과
`docker restart pm-design-task41`로 정적 파일과 템플릿을 갱신한다.
별도 운영 반영은 이 작업에 포함하지 않았다.
