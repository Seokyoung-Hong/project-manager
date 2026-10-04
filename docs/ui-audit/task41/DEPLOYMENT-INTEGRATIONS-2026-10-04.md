# 연동·요청·Discord 통합 운영 배포

2026-10-04 22:45 KST. 사용자의 명시적인 병합 및 운영 배포 지시에 따라 실행했다. 이전 통합 문서의 운영 미승인 상태는 이 요청으로 변경되었다.

## 반영 결과

- PR [#9](https://github.com/Seokyoung-Hong/project-manager/pull/9)를 main `2c96b8546251c70ebc764a651d7fcf96b03dc1da`로 병합했다. Core/Discord/MCP GitHub CI 3개 모두 성공한 `5d34e39`를 병합 대상으로 확인했다.
- 운영 서버 `root@172.30.1.30`, `/opt/project-manager`, 공개 주소 `https://project.sio2.kr`.
- 서버는 오래된 Git HEAD에 후속 변경을 직접 적용한 상태였다. 강제 pull/reset 대신 병합 소스와 경로별 내용을 비교해 기존 파일 117개·새 파일 30개를 반영했다. 환경 파일·운영 전용 파일·데이터 볼륨은 보존했다. 서버 Git HEAD 자체는 배포 버전 표식이 아니다.
- `web`, `discord-bot`, `mcp` 이미지 빌드 후 web의 health와 마이그레이션을 확인하고 봇·MCP를 순서대로 갱신했다. 전체 Compose down이나 DB 재생성은 수행하지 않았다. 발송 `discord` 서비스는 원래 실행 중이지 않아 이번에도 시작하지 않았다.
- 새 `discord_bot_data` 볼륨이 `/data/bot.sqlite`를 영속 저장한다. 봇 제어 포트 8081은 컨테이너 내부에만 노출된다.
- 운영 Postgres에서 github 0005, orgs 0006–0008, projects 0009, tasks 0004 적용 성공. `migrate --check`, Django check 정상.

## 검증

- 내부 및 공개 `/healthz`: HTTP 200, `{"ok": true}`.
- 공개 `/mcp`: 인증 없는 요청에 HTTP 401; OAuth protected-resource metadata는 HTTP 200.
- web healthy, DB healthy, 봇·MCP running. Discord gateway 연결과 봇 접속 성공, 봇 전용 orgs/channels API HTTP 200, MCP Uvicorn 기동 정상.
- 실행 컨테이너 파일과 병합 소스를 해시로 비교: web 287파일, discord-bot 21파일, mcp 12파일 모두 일치.
- 배포 전후 DB 컨테이너 ID는 동일하다(`025ec5084907…`).
- 운영 DB를 읽기만 하는 RequestFactory GET 10경로 모두 HTTP 200: today, requests, requests/new, help/integrations, settings/profile, settings/tokens, orgs/1/discord, orgs/1/teams, projects/6, projects/6/repo. 인증 세션 저장이나 POST 없이 렌더만 확인했다.
- Astra 실제 공개 브라우저: 로그인 1280/390px에서 GitHub 로그인 버튼·가입 안내 정상, 가로 넘침/pageerror/console error 0. app.css/app.js/notes.js/webmcp.js 모두 HTTP 200이며 줄바꿈 정규화 후 병합 소스와 일치.
- [Astra 증거](production-integration-20261004/evidence.json), [모바일](production-integration-20261004/login-390.png), [데스크톱](production-integration-20261004/login-1280.png).

## Discord 활성화 상태

실제 봇 애플리케이션의 Server Members Intent 승인 플래그는 false, 현재 환경 플래그는 0이다. 승인되지 않은 특권 인텐트를 요청해 봇을 중단시키지 않도록 이 상태를 유지했다. 운영 조직의 Discord 서버 연결 수도 0이다.

따라서 봇 접속과 기존 DM 명령은 기동되었지만 **채널 감시·자동 권한 관리는 아직 활성화되지 않았다**. 운영에서 사용하려면 Developer Portal의 Server Members Intent 승인 → `DISCORD_MEMBERS_INTENT=1` → 봇 재기동, 조직 Discord 서버 연결, 서버 관리자의 봇 권한 `268504080` 재승인이 필요하다. 이번 배포에서 조직/채널 정책이나 외부 인원 허용을 임의로 변경하지 않았다.

운영 계정 브라우저 로그인·OAuth 왕복·실채널 변경·실제 DM 전달은 수행하지 않았다. 통합 기능의 실제 POST 동작은 별도 로컬 Docker에서 Astra가 검증한 결과를 따른다.

## 백업 및 롤백

보호된 서버 디렉터리(권한 700): `/opt/project-manager/.deploy-backups/integration-merge9-20261004`.

- `source-before.tar`, `changed-files.json`, `new-files.json`: 교체 전 경로와 신규 경로.
- `database-before.dump`: 운영 Postgres custom-format 백업. 파일이 존재하고 `pg_restore -l`로 목록을 읽을 수 있음을 확인했다.
- `.env.before`, `.env.discord.before`: 환경 백업. 저장소 산출물에는 포함하지 않는다.
- `containers-before.json`, `images-before.txt`: 기존 실행 서비스/이미지.
- 기존 이미지 태그: `project-manager-web:rollback-merge9-20261004`, `project-manager-discord-bot:rollback-merge9-20261004`, `project-manager-mcp:rollback-merge9-20261004`.

롤백 시 해당 경로의 기존 소스를 복구하고 이번 신규 경로만 목록에 따라 처리한다. schema 변경이 있어 이전 이미지 재시작만으로 롤백이 완성되지는 않는다. 마이그레이션 역방향 또는 DB 복원이 필요한지 운영 데이터 변경을 확인한 후 결정한다. DB 백업을 자동 복원하지 않는다.
