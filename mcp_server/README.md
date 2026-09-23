# mcp_server

산돌이 태스크를 AI 클라이언트(Claude Code, Codex CLI, Claude 앱, ChatGPT)에 연결하는 MCP 서버.
core 코드를 import하지 않는다. core의 HTTP API만 호출하는 얇은 껍데기이고 상태를 두지 않는다.

## 환경 변수

| 이름 | 기본값 | 설명 |
|---|---|---|
| `CORE_URL` | `http://web:8000` | core 주소(컨테이너 안) |
| `DISCORD_CONTROL_URL` | `http://discord-bot:8081` | Discord 봇 내부 채널 관리 API. `discord` Compose 프로필이 꺼져 있으면 Discord 도구는 사용 불가 |
| `AUTH_SERVER_URL` | 없음 | core의 **공개** 주소. OAuth 인가 서버다. 비면 OAuth를 광고하지 않는다 |
| `PORT` | `8080` | 수신 포트 |

## 인증

토큰은 요청마다 온다. 세 가지가 다 통한다.

1. **OAuth 2.1** — 클라이언트가 401의 `WWW-Authenticate: ... resource_metadata=`를 보고
   `/.well-known/oauth-protected-resource`를 읽어 core로 간다. 사람은 로그인하고 '허용'만 누른다.
   나오는 것은 평범한 API 토큰이라 `/settings/tokens`에서 폐기한다. `AUTH_SERVER_URL`이 있어야 켜진다.
2. **`Authorization: Bearer <TOKEN>` 헤더** — 헤더를 넣을 수 있는 클라이언트(Claude Code, Codex CLI).
3. **경로 `/u/<TOKEN>/mcp`** — 둘 다 못 넣는 곳의 마지막 수단. 주소가 곧 비밀번호다.

셋 다 없으면 연결 자체가 401로 끊긴다 — 커넥터가 "연결됨"으로 보이는데 도구 호출만 전부
거부되는 일이 없게. 이 서버는 토큰을 검사하지 않는다. 진짜 판정은 core가 한다.

## 실행

```bash
CORE_URL=http://localhost:8000 uv run python -m mcp_server
```

## 한 도메인, 경로로 나누기 (운영 구성)

MCP는 core와 **같은 도메인**에 있다. 앞단 게이트웨이가 경로만 보고 나눈다. 도메인도 인증서도
하나고, OAuth의 인가 서버와 자원 서버가 같은 출처가 된다. 서버 코드는 어느 쪽이든 그대로다 —
공개 주소를 Host 헤더에서 끌어내기 때문이다.

NginxProxyManager의 `project.sio2.kr` 호스트에 Custom location 세 개를 둔다.

| location | 보낼 곳 |
|---|---|
| `^~ /mcp` | `172.30.1.30:8081` |
| `^~ /u/` | `172.30.1.30:8081` (개인 비밀 URL) |
| `^~ /.well-known/oauth-protected-resource` | `172.30.1.30:8081` |

나머지(`/`, `/oauth/…`, `/.well-known/oauth-authorization-server`)는 core로 간다.
core에는 `/mcp`도 `/u/`도 없으니 부딪히지 않는다. `location /mcp`는 `/mcpxxx`까지 걸리므로
`^~`로 못 박는다. Host는 원래 도메인 그대로 넘겨야 한다(NPM 기본값이 그렇다).

`.env`는 두 줄이면 된다. `MCP_URL`은 비워 두면 `SITE_URL`을 그대로 쓴다.

```
SITE_URL=https://project.sio2.kr
MCP_ALLOWED_HOSTS=project.sio2.kr
```

## 클라이언트 연결

운영 서버의 MCP 주소는 `https://project.sio2.kr/mcp`이다(다른 곳에 올렸다면 그 주소로 바꿔 읽는다). `<TOKEN>`은 core의 `/settings/tokens`에서 발급한 값.

| 클라이언트 | 방식 | 설정 |
|---|---|---|
| Claude 앱 / claude.ai | OAuth | 설정 → 커넥터 → 커스텀 커넥터 추가 → URL `https://project.sio2.kr/mcp`. '연결'을 누르면 로그인·허용 화면이 뜬다 |
| Claude Code | 헤더 | `claude mcp add --transport http sandol https://project.sio2.kr/mcp --header "Authorization: Bearer <TOKEN>"` |
| Codex CLI | 헤더 | `~/.codex/config.toml`에 `[mcp_servers.sandol]` `url = "https://project.sio2.kr/mcp"` `bearer_token_env_var = "SANDOL_TOKEN"` 추가, 환경 변수 `SANDOL_TOKEN=<TOKEN>` |
| 그 밖 | 개인 비밀 URL | URL `https://project.sio2.kr/u/<TOKEN>/mcp`, 인증 없음 |

개인 비밀 URL은 비밀번호와 같다. 공유하지 말고, 유출되면 `/settings/tokens`에서 폐기한다.

## 에이전트에게 사용법을 알려 주는 법

붙이기만 하면 에이전트는 도구 이름만 알 뿐 언제 무엇을 부를지 모른다. 그래서 세 겹으로 준다.

| 겹 | 무엇 | 언제 쓰이나 |
|---|---|---|
| `instructions` | `server.py`의 `INSTRUCTIONS`. 꼭 지켜야 할 것만 | 연결 즉시 모델의 문맥에 들어간다. 짧게 유지한다 |
| `get_guide` 도구 | `skill/SKILL.md` 본문 | 에이전트가 필요할 때 스스로 부른다. 모든 클라이언트에서 통한다 |
| `guide://sandol-pm` 자원 | 같은 글 | 자원을 보여 주는 클라이언트에서 사람이 대화에 붙인다 |

글은 `skill/SKILL.md` **한 곳**에만 있다. 도구와 자원은 그 파일을 읽어 낸다 — 사본을 두면
한쪽만 고쳐진다. 조직마다 다른 규칙(거버넌스)은 여기가 아니라 `get_governance`가 낸다.
같은 파일을 `.claude/skills/sandol-pm/SKILL.md`로 복사하면 스킬로도 쓸 수 있다.

## MCP 도구

- 사용법: `get_guide` — 이 서버를 처음 쓸 때 읽는다.
- 조직·프로젝트: `list_orgs` `get_org` `list_projects` `get_project` `create_project` `update_project`
- 태스크: `list_tasks` `get_task` `get_task_github` `get_task_history` `create_task` `update_task`
  `transition_task` `extend_task` `append_note` `delete_task`
- GitHub 저장소: `list_org_repos` `get_project_repo` `connect_repo`; 조회는 저장소 접근 권한을 확인한다.
- 문서: `list_docs` `get_doc` `create_doc` `update_doc`
- 조직·팀: `list_members` `list_teams` `create_team` `add_team_member` `remove_team_member` `delete_team`
  `set_project_teams` `create_invite` `revoke_invite`
- 설정·개인화: `get_governance` `update_governance` `get_settings` `update_org_settings`
  `get_project_settings` `update_project_settings` `get_my_settings` `update_my_settings`
- 오늘 목록·현황: `get_today` `add_today` `exclude_today` `restore_excluded_today` `reorder_today`
  `set_today_auto_pull` `get_org_status` `get_weekly_report_data`
- ChatGPT 커넥터 호환 별칭: `search` `fetch`

수정 도구는 `get_task`로 읽은 최신 `version`을 함께 보낸다. 충돌하면 다시 읽고 재시도한다.
거버넌스는 조직이 화면에서 고치는 글이고 서버는 검증하지 않는다 — 자세한 건 `docs/GOVERNANCE.md`.

## 테스트

```bash
uv run pytest -q
uv run ruff check .
```
