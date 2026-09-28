# 산돌이 PM 스킬

Claude Code에서 산돌이 PM을 쓰는 스킬과 `/` 명령이다. core API(`/api`)를 직접 부르며 MCP 서버에 의존하지 않는다.
MCP 커넥터(`mcp_server/`)는 claude.ai 웹·모바일처럼 셸이 없는 클라이언트를 위한 선택 확장이다.

| 명령 | 하는 일 | 쓰기 |
|---|---|---|
| `/pm [할 일]` | 기본 스킬. 자유 요청과 공통 규칙(다른 명령이 읽는다) | 요청에 따라 |
| `/pm-today` | 오늘 할 일·밀린 것·막힌 것 요약 | 읽기 |
| `/pm-start [TASK-N \| #이슈]` | 착수. 인자가 없으면 대화로 태스크를 찾거나 만든다 | 쓰기 |
| `/pm-new [설명]` | 태스크 하나 만들기. 필요하면 분할 제안 | 쓰기 |
| `/pm-split [TASK-N \| 설명]` | 여러 태스크로 나누기 | 쓰기 |
| `/pm-from-issue [#N]` | GitHub 이슈를 태스크로 가져오기 | 쓰기 |
| `/pm-followup [할 일]` | 작업 중 발견한 범위 밖 일을 후속 태스크로 | 쓰기 |
| `/pm-decide [TASK-N]` | 사용자 결정·AI 판단을 요지로 기록 | 쓰기 |
| `/pm-pr [TASK-N]` | PR 설명 초안 | 읽기 |
| `/pm-done [TASK-N]` | 마무리 점검 후 review로 | 쓰기 |
| `/pm-triage` | 기한 넘김·막힘 정리 | 쓰기 |
| `/pm-weekly` | 주간 보고 초안 | 읽기 |
| `/pm-portfolio` | 개인 포트폴리오 초안(비공개) | 쓰기 |

쓰기 명령은 사용자가 직접 입력할 때만 돈다(`disable-model-invocation`). "태스크 만들어" 같은 자연어 요청은 `/pm`이 받는다.

## 설치

1. `pm`과 `pm-*` 폴더를 모두 같은 스킬 폴더에 복사한다. 다른 명령이 `../pm/`의 규칙과 스크립트를 쓰므로 함께 둬야 한다.
   - 모든 프로젝트에서: `~/.claude/skills/`
   - 이 저장소에서만: `.claude/skills/`

   ```powershell
   Copy-Item -Recurse -Force skills\pm, skills\pm-* $HOME\.claude\skills\
   ```

2. 로그인한다. 브라우저가 열리면 PM에 로그인하고 읽기/쓰기 중 골라 허용한다(쓰기 명령을 쓰려면 쓰기).
   처음 명령을 쓸 때 Claude가 대신 실행해 주기도 한다.

   ```powershell
   python $HOME\.claude\skills\pm\scripts\pm.py login
   ```

   토큰은 `~/.config/sandol-pm/token.json`에 저장되고 로그인한 서버 주소로만 쓰인다. `pm.py logout`은 이 파일을 지운다.
   서버 쪽 토큰은 `/settings/tokens`에 "산돌이 PM 스킬 (기기 이름)"으로 보이며, 기기를 잃어버리면 거기서 폐기한다.
   환경 변수 `SANDOL_PM_TOKEN`을 넣으면 그것이 우선한다. 다른 서버는 `SANDOL_PM_URL`(기본 `https://project.sio2.kr`).

3. Python 3.9 이상이 필요하다. 추가 패키지는 없다.

## 개발

- 스크립트 점검: `python skills/test_pm.py`
- `pm.py login`(OAuth)으로 받은 토큰은 AI용이라 조직의 AI 정책(`ai.*`)이 적용된다. 요청에 붙는 `X-Source: ai`는 표시일 뿐,
  서버는 토큰의 용도로 판단한다.
- 엔드포인트는 스킬에 복사하지 않는다. 자주 쓰는 것만 `pm/SKILL.md`에 두고, 나머지는 `pm.py spec`으로 명세를 읽는다.
