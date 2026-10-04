# TASK-41 운영 배포 완료

2026-10-04 19:56 KST · 사용자 운영 배포 요청에 따라 실행.

## 반영

- 운영: `root@172.30.1.30`, `/opt/project-manager`, 공개 주소 `https://project.sio2.kr`.
- 반영 소스: `e8a8435`의 core 변경 54파일(앱 구현 커밋 `c5c5e1c`).
- 서버는 오래된 Git HEAD에 후속 파일 변경을 직접 적용한 상태다. 강제 reset/pull 대신,
  이번 54경로가 구현 전 `134ae90` 내용과 일치하는지 해시로 확인한 뒤 그 경로만 교체했다.
  새 파일은 서버에 없음을 확인했다. 운영자의 다른 변경·설정·볼륨은 보존했다.
- `docker compose build web` 후 `docker compose up -d --no-deps web`만 실행했다.
  DB·MCP·Discord 봇 컨테이너 ID는 배포 전후 그대로다.
- 이전/새 이미지의 migrate plan 모두 적용할 작업 없음. 새 이미지 시스템 검사 정상.
- 새 web 이미지: `sha256:454a3c9629f2c7c57d00d135f7e89b028c8d2633b7c8e7a2eb2c81fe22cc9c3b`.
- 실행 컨테이너 안의 54파일을 main 소스 해시와 대조: 불일치 0.

## 확인

- 내부 `http://127.0.0.1:8080/healthz`: 200, `{"ok": true}`.
- 공개 `/healthz`: 200, `{"ok": true}`; `/login`: 200.
- 새 컨테이너 `manage.py check`: 오류 0, Gunicorn 정상 시작.
- 운영 DB 읽기만 수행하는 RequestFactory GET 렌더 검사 10경로 모두 200:
  `/today`, `/me`, `/projects/16`, `/projects/16/docs`, `/orgs/1`, `/orgs/1/notes`,
  `/orgs/1/settings`, `/settings/profile`, `/settings/preferences`, `/portfolio`.
  인증 세션 생성이나 저장 POST는 하지 않았다. 이 검사는 실제 브라우저 로그인 검증과 구별한다.
- Astra 공개 브라우저: 로그인 1280/390px 정상, console/pageerror 0, 가로 넘침 0.
  공개 CSS/app.js/notes.js는 줄바꿈 정규화 후 로컬 소스와 일치한다.
  [운영 브라우저 증거](production-browser/evidence.json), [정적 파일 비교](production-browser/asset-comparison.json).
- collectstatic의 중복 경로 경고는 있으나, 실제 제공된 3개 변경 정적 파일은 최신 소스와 일치했다.
- 운영 계정 로그인 후 저장/외부 연동 POST는 실행하지 않았다. 구현 동작 검증은
  [독립 미리보기 검증](IMPLEMENTATION-2026-10-04.md)에 기록한 587테스트·Astra 결과를 따른다.

## 백업과 롤백

- 보호된 서버 디렉터리: `/opt/project-manager/.deploy-backups/task41-20261004-105558` (권한 700).
- `source-before.tar`: 교체한 기존 파일. `new-files.json`: 이번에 추가한 파일 경로.
- `database-before.dump`: 배포 직전 Postgres custom-format dump. DB 복원은 이번에 수행하지 않았다.
- `previous-image.txt`, `containers-before.txt`: 기존 이미지·컨테이너 기록.
- 이전 이미지 태그: `project-manager-web:rollback-task41-20261004`.
  이전 이미지 ID `sha256:b5305913eaff613d92dc99a02b98fe7adfde9dff374f287c91445be54411d724`.
- 롤백이 필요하면 백업 소스를 해당 경로에 복구하고, 새 파일 목록의 해당 파일만 제거한 뒤
  이전 이미지 태그를 `project-manager-web:latest`로 지정하고 web만 재생성한다.
  이번 배포에는 schema 변경이 없으므로 DB dump를 자동 복원하지 않는다.

이 기록과 증거에는 운영 토큰·환경 파일·DB 내용·인증 세션을 포함하지 않는다.
