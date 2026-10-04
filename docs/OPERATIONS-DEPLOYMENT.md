# 서비스 범위별 운영 및 배포

운영 서버는 `root@172.30.1.30`이다. 이 저장소의 코드 변경은 영향을 받는 Compose 서비스 단위로 나누어 배포한다. 서버의 실제 경로와 상태를 확인하기 전에 경로나 서비스 상태를 가정하지 않는다.

## SSH 접속과 신뢰 확인

- 운영자 계정의 기본 OpenSSH 설정과 기본 `known_hosts`를 사용해 `ssh root@172.30.1.30`으로 접속한다.
- `StrictHostKeyChecking=no`, `UserKnownHostsFile=/dev/null` 등 호스트 검증을 끄는 옵션은 사용하지 않는다. Codex 실행 환경이 운영자와 다른 계정이면 운영자의 설정을 임의로 덮어쓰지 않는다.
- 자동 배포가 기본 `known_hosts`에서 호스트 키를 확인하지 못하면 배포를 멈춘다. 서버 콘솔 등 신뢰할 수 있는 경로로 지문을 확인해 등록한 뒤 다시 접속한다. `ssh-keyscan` 결과만으로 키를 신뢰하지 않는다.
- 접속 후 `hostname`, `pwd`, Compose 프로젝트의 서비스 상태와 저장소 상태를 읽어 대상이 맞는지 확인한다. `.env`, `.env.discord`, 데이터 볼륨, 서버 전용 파일은 유지한다.

## 배포 단위

| 변경 경로 | Compose 서비스 | 작업 |
|---|---|---|
| `core/` | `web` | 이미지 빌드 후 `web`만 재생성. 새 migration이 있을 때만 적용 결과 확인 |
| `discord_service/` | `discord-bot` 또는 `discord` | 게이트웨이·슬래시 명령·채널 제어 변경은 `discord-bot`; 발송/스케줄 변경은 `discord`. 공유 모듈이면 두 서비스 모두 갱신 |
| `mcp_server/` | `mcp` | 이미지 빌드 후 `mcp`만 재생성 |
| `compose.yml` | 바뀐 서비스 | 설정 차이를 읽고 해당 서비스만 재생성. DB·볼륨은 건드리지 않는다 |

`web`, `discord-bot`, `mcp`가 모두 바뀐 경우 순서대로 각 이미지와 서비스만 갱신한다. 전체 `docker compose down`, 볼륨 삭제, 저장소 전체 덮어쓰기는 사용하지 않는다. 실제 작업 경로를 확인한 뒤 `docker compose build <서비스>`와 `docker compose up -d <서비스>`를 해당 서비스에 각각 실행한다. 배포 직후 `docker compose ps`와 해당 서비스의 최근 로그, `/healthz` 및 영향을 받은 API 응답을 읽어 확인한다. 비밀값을 출력하는 `docker compose config` 전체 출력과 환경 파일 덤프는 하지 않는다.

## MCP의 Discord 프로젝트 채널 관리

MCP 컨테이너에는 Discord 토큰을 넣지 않는다. `discord-bot`이 내부 Compose 네트워크에서만 포트 `8081`을 열어 Discord gateway cache를 조회·관리한다. 이 포트는 호스트에 공개하지 않는다. MCP는 호출자의 ProjectManager bearer token을 전달하며, Discord 제어 브리지는 각 요청에서 조직 관리자 권한과 조직-길드 연결을 확인한다. Core가 최종 채널 연결을 저장할 때에도 같은 사용자 토큰과 조직 관리자 검사를 적용한다.

관리 흐름:

1. `list_discord_channels(org_id)`로 텍스트 채널명·ID와 카테고리를 조회한다. `channels_by_name`은 이름→ID dict이며, 동명 채널은 카테고리명을 덧붙인다. `channels_by_name_all`은 원래 이름별 전체 ID 목록이다.
2. `plan_project_channel_assignments(org_id)`로 기존 연결과 이름이 일치하는 후보를 확인한다. 이름이 모호한 채널은 자동으로 고르지 않는다.
3. 관리자에게 연결 계획을 보여 주고 승인받은 뒤 `assign_project_channel`로 기존 채널을 연결한다.
4. 맞는 채널이 없으면 적합한 기존 카테고리를 먼저 제안한다. 없거나 맞지 않을 때 새 카테고리를 제안하고 승인받은 뒤 `create_project_channel`을 호출한다. 채널·카테고리 생성이나 연결 저장이 실패하면 새로 만든 Discord 리소스를 되돌린다.

Discord 슬래시 명령 `/프로젝트채널`도 `기존채널` 옵션으로 기존 텍스트 채널을 연결하고, `새카테고리만들기` 옵션으로 없는 카테고리를 생성할 수 있다. 기존 명령의 Discord 사용자 `Manage Channels` 검사는 계속 적용된다. MCP 사용자는 ProjectManager 조직 관리자여야 하며 Discord 봇에도 채널 관리 권한이 필요하다.

운영 준비 조건:

- `.env.discord`의 `CORE_TOKEN`은 전용 `discord-bot` 계정의 `bot` 범위 API 토큰이어야 한다. 봇 시작 로그에서 `/api/integrations/discord/orgs`가 `401`이면 사용자·토큰 연결을 확인하고, 교체 후 `discord-bot`을 재기동한다. 토큰 값이나 `.env.discord` 전체를 로그·응답에 출력하지 않는다.
- 조직 관리자가 웹의 조직 Discord 설정에서 길드를 연결해야 MCP가 해당 조직의 채널을 조회한다. 길드 연결 전에는 슬래시 명령을 동기화할 대상도 없으며 MCP 제어 API는 `409`를 반환한다.
- `discord-bot`은 `8081`을 컨테이너 내부에만 노출한다. `docker compose ps discord-bot`에서 호스트 포트 매핑이 없어야 한다.

## Discord 채널 감시·자동 관리 (IMPL-PLAN-5 B)

팀·프로젝트 채널은 비공개로 만들고, 연결 뒤에도 권한 밖 인원이 보이는지 감시한다. 이를 위해 **Server Members 특권 인텐트**와 봇 권한 `268504080`(View Channels·Send Messages·Read Message History·Manage Channels·Manage Roles)가 필요하다. 아래 순서를 지킨다. 순서가 바뀌면 봇 기동이 실패한다.

1. **포털에서 인텐트를 먼저 켠다.** Discord Developer Portal → 앱 → Bot → Privileged Gateway Intents → **Server Members Intent**를 켠다. 켜지 않은 채 코드가 이 인텐트를 요청하면 게이트웨이가 접속을 거부(close code 4014)해 슬래시 명령·DM이 모두 멈춘다.
2. **`.env.discord`에 `DISCORD_MEMBERS_INTENT=1`을 추가**하고 새 이미지로 `discord-bot`만 갱신한다. 이 값이 없거나 `0`이면 감시·조정은 건너뛰고, 기존 채널 연결은 "확인 불가"로 다뤄져 `권한밖허용:True` 없이는 연결되지 않는다(fail closed).
3. **봇을 다시 승인한다.** 웹 `조직 → Discord`의 "권한 갱신 필요" 링크(또는 `봇 다시 설치`)로 서버 관리자가 재승인한다. 새 권한이 켜지면 이 안내가 사라진다. 이미 설치된 서버는 재승인 전까지 자동 관리의 덮어쓰기 추가가 거절될 수 있다(감시와 경고는 동작한다).
4. `discord-bot`은 자동 관리가 넣은 덮어쓰기를 기록하려고 SQLite(`/data/bot.sqlite`, 볼륨 `discord_bot_data`)를 쓴다. 발송 프로세스(`discord`)의 파일과 별개다. 볼륨을 지우면 봇이 넣은 덮어쓰기를 다시 추적하지 못한다(자동으로 지워지지 않고 남는다).
5. 배포 뒤 확인: `discord-bot` 로그에 접속 로그가 나오는지, 웹 `조직 → Discord`의 상태가 "감시 꺼짐"에서 "정상"으로 바뀌는지(최대 5분), 새 권한 보고가 반영됐는지 본다.

동작 요약: 5분마다, 그리고 채널·역할·멤버 변경 이벤트가 오면 해당 서버를 다시 검사한다. 새로 보인 권한 밖 인원은 조직 관리자에게 DM으로 알리고(채널에는 올리지 않는다) 웹에서 `허용`·`철회`한다. 권한 밖 인원을 자동으로 쫓아내거나 서버 역할을 만들고 바꾸지는 않는다. 자동 관리가 켜진 채널에서 봇은 허용 집합의 연결 계정에게 멤버 단위 덮어쓰기(보기·쓰기·기록 읽기)만 넣고 뺀다.
