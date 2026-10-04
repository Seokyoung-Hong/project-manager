# 승인 후 통합 완료 및 검증 기록

2026-10-04. 기존 인계·계획 문서는 당시 상태를 보존한다. 이 문서가 후속 통합 결과다.

## 검토 수신과 통합

상대 Orca 세션 `6f31d3ec-9fa9-4d68-96e8-8f12cb9b460c`의 최종 검토 승인 메시지 `msg_c8f524a5dda2`를 수신했다. 승인된 최종 변경은 `7da3dde`이며, 상대 세션을 다시 실행하거나 상대 워크트리를 수정하지 않았다. 승인 메시지에 회신하고 통합·검증 진행 상태를 같은 Orca 스레드에 전달했다.

통합 워크트리: `C:/Users/tjrdu/orca/workspaces/project-manager/integrations-discord-review`.
브랜치: `Seokyoung-Hong/integrations-discord-review`.

- UI-UX 구현 `2d0c2c2`: 이슈 Markdown, 연동 문제 설명·질문 복사, 실패한 GitHub 작업 재시도.
- 승인된 요청/Discord 구현 `7da3dde`: 요청·할당·팀장, 비공개 채널·접근 감시·자동 권한 관리, 실행자 Discord 권한 검사.
- 최신 `origin/main` `b8981c8`: GitHub 로그인·가입, 권한·AI 정책, CI와 Ruff 설정.
- 통합 커밋 `194d694`, 최신 main 결합 및 보완 커밋 `1168583`.

GitHub 로그인/기존 계정 연결 검증과 안전한 오류 안내를 함께 보존했다. 채널 관리 옵션, 비공개 권한 기록, 길드별 조직 경계와 기존 채널 연결 전 검사를 유지했다. 최신 main에 맞춰 설정 레지스트리와 테스트 데이터를 조정했다.

독립 검토에서 MCP 사용자 토큰을 봇 토큰으로 바꾸는 채널 연결 경로의 AI 출처 소실을 발견했다. `POST /api/orgs/{org_id}/discord-control-check`에서 실제 사용자 토큰과 MCP 출처로 조직 관리자/AI 정책을 확인하고, 연결·해제·생성 전에 호출하도록 보완했다. 정책 거절·통신 실패·잘못된 성공 응답에서는 Discord 변경 없이 중단한다. 일반 조직 조회는 그대로 허용한다.

## 실행 검증

| 검사 | 결과 |
|---|---|
| Core 전체 pytest | 708 passed |
| Discord 전체 pytest | 164 passed |
| MCP 전체 pytest | 46 passed |
| 전 파일 pre-commit Ruff check / format | Passed |
| Django check | 오류 없음 |
| makemigrations --check --dry-run | 변경 없음 |
| 새 SQLite DB 전체 migrate | 성공 |
| 승인된 Discord 브랜치 DB → 통합 DB migrate | 성공; GitHub 0005 적용 |
| Compose 전체 profile config | 성공; 검증 사본에서 env_file을 제거했으며 비밀값 사용 없음 |

AI 토큰의 사람 출처 위장, 사람 토큰의 MCP 출처, 조직 AI 차단, 일반 멤버·읽기 전용 토큰 거절을 검증했다. 정책 조회의 거절·타임아웃·유효하지 않은 JSON 때 채널 생성/연결/해제가 실행되지 않는 테스트도 통과했다.

## Astra 실제 웹 검증

Docker `pm-integration-live-20261004`, `http://127.0.0.1:8019`에서 실제 로그인 후 확인했다. 통합 워크트리의 core를 읽기 전용으로 마운트하고 별도 테스트 DB와 합성 사용자/조직/Discord 권한 정보를 사용했다. GitHub 응답은 로컬 fixture로 처리했다.

8경로(`/projects/1/issues`, `/orgs/1/issues`, `/projects/1/repo`, `/help/integrations`, `/orgs/1/discord`, `/teams/1`, `/requests/1`, `/requests/new`)를 390px/1280px에서 열었으며 HTTP 200, 가로 넘침 0, pageerror 0이었다.

실제 로컬 POST로 Discord 외부 인원 허용→철회, 자동 관리 켜기→끄기, 팀장 지정→해제, 일반 요청 수락→완료를 확인했다. 외부 Discord 서버에서 실행한 결과가 아니라 웹 동작과 로컬 DB 상태 검증이다.

공유용 화면: [Markdown](evidence/integration-live-20261004/390-projects-1-issues.png), [접근 팀 안내](evidence/integration-live-20261004/390-projects-1-repo.png), [Discord 관리](evidence/integration-live-20261004/390-orgs-1-discord.png), [요청](evidence/integration-live-20261004/1280-requests-1.png).

상세 로컬 증거: `%TEMP%/integration-live-astra-20261004`. 인증 세션과 인증 정보가 포함된 스크립트는 저장소 산출물에서 제외했다.

## 검증 한계 및 운영 적용 조건

실제 GitHub OAuth/조직 권한 승인, Discord gateway·실채널 변경, 실제 DM 전달, 운영 DB와 운영 배포는 수행하지 않았다. 운영/Discord Developer Portal 변경에 대한 승인은 이번 통합 승인에 포함되어 있지 않다.

운영에서 감시·자동 관리를 켜려면 Discord Developer Portal의 Server Members Intent를 먼저 승인하고 `DISCORD_MEMBERS_INTENT=1`을 설정한다. 봇 권한 `268504080`으로 서버별 재설치 승인과 `discord_bot_data` 영속 볼륨이 필요하다. 인텐트·실행자 권한이 없거나 확인 정보가 오래됐을 때는 차단/안내 상태를 유지한다.

새 번호의 마이그레이션은 orgs 0006–0008, projects 0009, tasks 0004, github 0005이다. 검증 DB 마이그레이션 성공은 운영 데이터 백업과 실제 배포 검증을 대신하지 않는다.

Astra 최종 확인: Markdown 제목·굵게·코드블록·disabled 체크박스와 원문 초기 접힘/펼침이 정상이며 script 실행과 javascript 링크가 없었다. 접근 팀 HTTP 403 도움말의 실제 클립보드 복사값이 질문 전체와 일치했고 readonly 입력칸 높이는 160px이었다. 최종 DB 확인 결과 허용 철회한 경고 레코드는 없고, 팀 자동 관리/팀원2 팀장 상태는 false, 요청1 상태는 done이었다. 상세 증거 색인은 `%TEMP%/integration-live-astra-20261004/SUMMARY.md`, 최종 상태는 `db-final.json`이다.
