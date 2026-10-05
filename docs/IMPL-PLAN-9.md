# N2 — 라운드 9 설계 개정 v2: 봇 하나로 음성 회의 녹음 → 전사 → 회의록 (Fable, 2026-10-06)

기준: main `7d721c5`(= `docs/IMPL-PLAN-9.md` v1). 이 문서는 사용자 결정(2026-10-06) 5건을 반영한 **개정 전문**이며 v1의 §1.4 이후 전사 정렬·§3 모델·§4 고지·§6 복구는 바뀐 부분만 적고 나머지는 v1을 따른다. 코드·git은 건드리지 않았다. 법률 부분은 법률 자문이 아니다.

## 0. 사용자 결정과 반영 요지

| # | 결정 | 반영 |
|---|---|---|
| 1 | **봇은 하나만.** 새 Discord 앱을 만들지 않고 녹음 가능한 플랫폼으로 옮긴다 | §1: (a) 전체 재작성 vs **(b) 게이트웨이 부분만 Node로 이전** 비교 → **(b) 추천** |
| 2 | 전사 기본 `gpt-transcribe`, **로컬 OpenAI 호환 전사 서버가 있으면 우선**, 실패 시 OpenAI 대체 | §3 |
| 3 | **요약은 서버가 하지 않는다.** 전사문까지만 초안에 넣고 사용자가 MCP·스킬로 정리 | §4. 서버의 LLM 키·비용 0 |
| 4 | 오디오 **7일 보관**, 백업 제외 | `meeting.audio_keep_days` 기본 7 |
| 5 | 초안은 시작자+관리자만, 확정 시 프로젝트 | v1 §3.3 그대로(§4.4에 참여자 열람 제안 1건) |

---

## 1. 플랫폼 이전: (a) 전체 재작성 vs (b) 게이트웨이만 이전

### 1.1 현재 discord_service의 두 프로세스가 무엇에 의존하는가 (코드로 확인)
| 프로세스 | 모듈(행) | Discord 연결 | 테스트 |
|---|---|---|---|
| `bot`(게이트웨이, discord.py) | listener 143, slash 612, commands 243(DM 파싱·답장 문구, 슬래시도 공유), channels 296, watch 229, control 375(aiohttp 8081), store의 `grants` 표, core_client 봇 경로 일부, messages 일부(HELP·STATUS·today_message·SLASH_HELP) | **게이트웨이 세션**(인텐트 guilds·dm_messages·members 선택) | test_slash 23, test_requests 11, test_channels 12, test_watch 29, test_listener 3 = **78** |
| `run`(발송, 60초 tick) | scheduler 266, notify 185, weekly 53, summarize 87, escalate 123, github_hooks 68, channels_post 101, discord.py 208(httpx REST `Bot`), store(sent·daily·dm·weekly·runs·seen_status), core_client 나머지 | **REST만**(`discord.py:8 API=https://discord.com/api/v10`, `discord.py:58` "게이트웨이는 listener가 맡는다") | test_notify 28, test_weekly 12, test_escalate 10, test_commands 16, test_channels_post 12, test_github_hooks 6, test_store 8, test_discord 9 = **101** |

`import discord`(discord.py)는 channels·control·listener·slash·watch 5개 파일에만 있다(grep). 즉 **게이트웨이 경계가 이미 파일 단위로 깨끗이 나뉘어 있다.** Discord REST는 게이트웨이 세션과 무관하게 같은 봇 토큰으로 쓸 수 있으므로(일반 지식), 게이트웨이 연결이 Node 하나뿐이면 토큰 공유 충돌(v1이 걱정한 인터랙션 분배·`tree.sync` 덮어쓰기)은 생기지 않는다.

### 1.2 비교
| 항목 | (a) discord_service 전체를 Node로 | **(b) 게이트웨이 부분만 Node로, 발송은 Python 유지** |
|---|---|---|
| 옮기는 코드 | 약 3,000행 + 테스트 179개 전부. 발송 쪽은 REST·SQLite 상태(sent/daily/weekly/runs/seen_status)·주간 보고 집계·에스컬레이션 규칙·GitHub 웹훅 작업·채널 사건 폴링까지 재구현 | 약 1,900행(listener·slash·commands·channels·watch·control + store grants + core 봇 경로) → Node 약 1,800~2,200행. 테스트 78개를 vitest로 |
| 규모 | **XL**(4~6단계, 2개 프로세스 동시 컷오버) | **L**(1단계 L + 녹음 M) |
| 얻는 것 | 언어 하나, 프로세스 하나(-50MB) | 음성 녹음 가능, 명령·DM·채널 관리가 한 프로세스에 |
| 위험 | 발송 쪽은 옮길 **기능적 이유가 없다**(REST·tick은 언어 무관). 179개 테스트 전부 재작성, 발송 누락·중복(sent 표 호환) 사고 가능 | 명령 20개·DM 명령·control 3 엔드포인트·watch 동작 동등성. 발송은 손대지 않아 알림 사고 위험 0 |
| 512MB 영향 | Python 2 프로세스(≈100MB) → Node 1(대기 ≈100MB, 녹음 중 ≈150MB): **±0~+50MB** | Python bot(≈50MB) → Node gateway(대기 ≈80~90MB, 녹음 중 ≈130MB): **+30~80MB**. v1(별도 recorder 추가 +100~120MB)보다 작다 |
| 배포 중단 | 두 서비스 재배포, 발송 틱 공백 수 분(sent 표로 중복 발송은 막힘) | `discord-bot` 서비스만 이미지 교체 1~3분. 명령·DM·채널 감시만 멈추고 **발송은 무중단** |
| 롤백 | 두 서비스 되돌리기 + SQLite 스키마 호환 확인 | compose의 `discord-bot` build 경로를 `./discord_service`로 되돌리고 `up -d --build discord-bot`. 같은 앱이라 Python이 `tree.sync`로 명령 트리를 다시 덮어쓴다. `discord_bot_data` 볼륨(grants SQLite)은 **같은 스키마를 Node `node:sqlite`로 그대로 읽고 쓰므로** 데이터 손실 없음 |
| 테스트 자산 | 101개(발송) 폐기 | 101개 그대로, 78개 포팅 |

**추천: (b).** 발송은 REST라 옮길 이유가 없고, 게이트웨이 경계가 파일 단위로 이미 갈라져 있다. (a)는 "언어 하나"라는 취향 이익에 XL 비용과 알림 사고 위험을 치른다. (a)가 필요해지는 때(발송도 게이트웨이 캐시가 필요해질 때)가 오면 그때 한 라운드로 옮기면 된다 — (b)의 Node 코드는 그대로 재사용된다.

### 1.3 플랫폼 선택(녹음 가능한 것 중)
| 후보 | 판단 |
|---|---|
| **Node 22 + discord.js 14 + `@discordjs/voice` 0.19.2 고정 + `@snazzah/davey`** | **채택.** DAVE 수신이 안정 릴리스에 있는 유일한 범용 조합(L §1.3). 슬래시·DM·채널 관리 API가 discord.py와 1:1 대응(`SlashCommandBuilder`, autocomplete, `PermissionOverwrites`, `GuildMember.permissions`) |
| Dysnomia(Eris 포크) + davey | Craig 실전 사례. 문서 적음. `@discordjs/voice`가 PoC에서 막히면 2순위 |
| Python 유지 + DAVE 수신 포크 | 미병합 PR·개인 포크(L §1.2). 운영 봇의 토대로 비추천 — 이전 비용 0이지만 깨질 때 고칠 사람이 우리뿐 |
| Rust Songbird / Java JDA | 수신 DAVE 미확인, 저장소 선례 없음 |

### 1.4 (b)의 구조
```
discord-gateway (Node, 봇 토큰 A)         discord (Python `run`, 봇 토큰 A, REST만 — 그대로)
 ├ 슬래시 20개 · DM 명령 · 채널 생성/연결 · watch · control 8081   ├ 마감 DM · 주간 보고 · 에스컬레이션 · GitHub 웹훅 작업 · 채널 사건
 ├ 음성 세션(녹음 · 구간 Ogg) · 전사 큐(로컬 → OpenAI) · janitor     └ sent/daily/… SQLite (discord_data)
 └ grants SQLite(discord_bot_data, 같은 스키마) · /data/sessions/*      
                 └────────── core /api/integrations/discord/* (BotTokenAuth, CORE_TOKEN) ──────────┘
```
- 디렉터리 `discord_gateway/`(Node). compose의 `discord-bot` 서비스가 `build: ./discord_gateway`로 바뀌고 이름·env_file(`.env.discord`)·볼륨·8081 expose는 그대로다. mcp의 `DISCORD_CONTROL_URL`도 그대로.
- `.env.discord`에 추가: `OPENAI_API_KEY`(전사), `STT_LOCAL_API_KEY`(§3, 선택). 발송 Python은 이 키를 읽지 않는다(Config.need에 없음) — 같은 env_file을 쓰되 모르는 키는 무시.
- 업무 로직 위치: 지금도 봇에는 업무 규칙이 없다(commands.py 머리말 "판단은 전부 core의 services가 한다"). **core로 더 옮기지 않고 그대로 포팅**한다. 옮길 후보였던 "권한 밖 인원 확인"은 이미 `/channel-check`가 core에 있고, 봇이 하는 일은 파싱·문구·Discord 권한 확인(`manage_channels`)·캐시 계산뿐이다. 문구(messages.py의 DM·슬래시 쪽)는 Node 상수 파일로 옮기되 **문자열을 바꾸지 않는다**(테스트가 문구를 본다).
- 테스트: vitest(새 dev 의존성 1개). conftest.py의 `FakeCore`(가짜 core transport)·`FakeInteraction`을 같은 설계로 옮긴다. core의 1268개 테스트는 영향 없음.
- 메모리 절약: discord.js `makeCache`로 메시지·프레즌스 캐시 0, `NODE_OPTIONS=--max-old-space-size=160`, `mem_limit: 256m`.
- 프로세스 하나에 음성이 들어오므로 녹음 OOM이 명령·DM도 죽인다. 완화는 mem_limit + Opus 무디코딩 + 재시작 복구(v1 §6). 알림 발송은 다른 프로세스라 무관.

### 1.5 컷오버·롤백 절차(운영 변경은 사용자 몫, 여기엔 목록만)
1. 서버 `.env.discord`에 `OPENAI_API_KEY` 추가. 2. `docker compose up -d --build discord-bot`(이미지 교체, 1~3분). 3. 슬래시 명령이 같은 앱으로 다시 sync — 사용자 측 변화 없음. 4. `/도움`·DM `오늘`·`/프로젝트채널` 각 1회 확인. 5. 문제면 compose build 경로를 되돌려 같은 명령으로 롤백.
Python 게이트웨이 코드(listener·slash·commands·channels·watch·control + 테스트 78)는 **한 라운드 뒤** 삭제한다. 그동안 `discord_service/pyproject.toml`에서 discord.py 의존성은 남겨 둔다(롤백 보장).

---

## 2. 개정된 흐름 (v1 §1에서 바뀐 것만)
- `/회의록`·`/회의_이어가기`·`/회의_종료`를 **같은 Node 프로세스**가 받고 음성 세션도 같은 프로세스가 연다. discord-bot ↔ recorder 내부 HTTP(v1 §1.1-3, §2.1)는 **없어진다**. `RECORDER_SHARED_SECRET`도 없다.
- 녹음 중 닉네임 `[녹음중] 산돌이`는 **그 봇 하나**의 길드 닉네임이 바뀐다(알림 발송은 REST라 닉네임과 무관하지만 DM·채널 메시지 발신자 이름도 녹음 중에는 `[녹음중] 산돌이`로 보인다 — 수용).
- 시작 고지·입장 고지·30초 규칙·종료 경로 5종·구간 Ogg·시작 시각 정렬은 v1 그대로.
- 종료 후: 전사(§3) → core `PATCH /meetings/{id} {status: draft, transcript_md, stats}` → `MeetingNote.body_md`를 **전사 원문만으로** 채운다:
  ```
  ## 요약
  (아직 없음 — `/pm-meeting 12` 또는 웹에서 작성해 주세요.)
  ## 결정 사항
  ## 할 일
  ## 미결
  ## 전사 원문
  <details><summary>전사: 로컬 서버 Systran/faster-whisper-small (구간 212개) · OpenAI gpt-transcribe (구간 3개)</summary>
  [00:00:12] 홍길동: ...
  </details>
  ```
- 시작자 Notice: "회의록 초안(전사)이 준비되었습니다. `/pm-meeting 12`로 정리하거나 웹에서 작성해 주세요. <링크>".
- 확정은 웹에서만(v1 §1.6). 결정·할 일 연결 버튼도 그대로.

---

## 3. 전사: 로컬 서버 우선 → OpenAI 대체

### 3.1 설정
| 위치 | 키 | 값 |
|---|---|---|
| 조직 설정(`core/orgs/settings.py`, 그룹 `meeting`) | `meeting.stt_url` | kind **text**(신설 kind, 최대 200자, `http(s)://` 스킴만). 비면 로컬 없음. 예 `http://172.30.1.50:8000` |
| | `meeting.stt_model` | text. 로컬 서버에 보낼 `model`(speaches는 `Systran/faster-whisper-small` 같은 이름이 필수). 비면 `whisper-1`로 보낸다(whisper.cpp server는 무시한다) |
| | `meeting.stt_timeout_s` | int 10~600, 기본 120. 구간 하나의 응답 대기 상한 |
| `.env.discord`(gateway만 읽음) | `STT_LOCAL_API_KEY` | 로컬 서버 Bearer(선택). **키는 DB에 두지 않는다**(비밀값은 서비스별 env 원칙; core에 암호화 저장 선례 없음 — §6 질문 1) |
| | `OPENAI_API_KEY`, `OPENAI_TRANSCRIBE_MODEL`(기본 `gpt-transcribe`) | 대체 경로 |
설정 변경은 조직 관리자만(기존 설정 화면 권한), 기존 설정 변경 기록(`ChangeLog`, orgs/services.py:85~)이 그대로 남는다. 설정 화면의 `meeting.stt_url` 옆에 [연결 확인] 버튼(core가 gateway control `GET /stt-health?org=`를 호출해 결과 표시 — mcp가 control을 부르는 기존 패턴과 같다).

### 3.2 엔진 선택·헬스체크
- **세션 시작 시**(`/회의록`): `stt_url`이 있으면 `GET {url}/v1/models`(OpenAI 호환 공통, 3초). 200이고 JSON이면 `local_ok=true`, 모델 목록에 `stt_model`이 없으면 경고만 로그. 결과를 세션 메타·시작 고지에 적는다: "전사: 로컬 서버(모델 x)" 또는 "전사: OpenAI gpt-transcribe" 또는 "로컬 서버 연결 실패 → OpenAI".
- **전사 시작 시** 한 번 더 확인한다(녹음 1~3시간 사이에 PC가 꺼질 수 있다).
- 둘 다 없으면(`stt_url` 비고 `OPENAI_API_KEY` 없음) `/회의록`은 "전사 수단이 설정되지 않았습니다"로 거절한다 — 녹음만 하고 버리지 않는다.

### 3.3 요청과 대체 규칙(구간 단위)
```
engine = local_ok ? local : openai
for seg in segments(start_ms 순, 동시 3):
    if engine == local:
        r = POST {stt_url}/v1/audio/transcriptions  (multipart: file=seg.webm, model=stt_model|whisper-1, language=ko, response_format=json, prompt=참여자·프로젝트명)
        timeout = min(stt_timeout_s, 30 + 3 × seg_seconds)
        실패 분류:
          - 400/415 and 형식 의심 → 같은 구간을 16kHz mono wav로 1회 재시도(whisper.cpp server는 wav만 받는다고 알려져 있음 — 확인 불가). 성공하면 세션 동안 wav 고정
          - 400 and prompt 거부 의심 → prompt 없이 1회 재시도. 성공하면 세션 동안 prompt 생략
          - 연결 실패·타임아웃·5xx → 10초 뒤 1회 재시도 → 또 실패하면 local_down=true, 이 구간부터 openai
    if engine == openai: v1 §1.4 그대로(3회 재시도)
    local_down이면 5분마다 /v1/models로 복귀 시도(남은 구간이 많을 때 PC가 돌아오면 다시 로컬)
```
- 성공 응답은 `text` 필드만 쓴다(verbose_json 아님). 빈 문자열은 `[무음]`으로 두지 않고 그 줄을 뺀다.
- 기록: `VoiceRecording.stats.engines = [{engine:"local", host:"172.30.1.50", model, segments, failed}, {engine:"openai", model, segments, failed}]`, 전사 원문 머리 한 줄(§2 예시). 회의록 화면 메타에 "전사 엔진"으로 보인다.
- OpenAI 키가 없고 로컬이 죽으면 남은 구간은 `[전사 실패]`, `status=failed`가 아니라 `draft`에 **부분 전사**로 저장하고 Notice에 "구간 N개 전사 실패"를 적는다. 오디오는 7일 보관되므로 `/ops`의 [재전사] 버튼(M4, 선택)으로 다시 돌릴 수 있다.

### 3.4 네트워크·보안(로컬 서버가 LXC 밖에 있을 때)
- 경로: 운영 LXC(172.30.1.30) → 사용자 PC(같은 사설망·VPN). gateway 컨테이너는 outbound가 열려 있으므로 compose 변경은 없다. 공인 주소로 노출된 서버(터널·NPM)면 https와 키를 쓴다.
- URL 검증(core Spec 저장 시): 스킴 http/https만, `localhost`·`127.0.0.0/8`·`169.254.0.0/16`·compose 서비스 이름(`web`, `db`) 거부(SSRF — gateway가 core 내부 주소로 오디오를 쏘지 못하게). **http는 사설 대역(10/8, 172.16/12, 192.168/16)일 때만 허용**, 그 밖은 https 필수.
- 나가는 데이터: 참여자 음성(webm/wav)과 prompt(참여자 표시명·프로젝트명). 처리방침 문구에 "조직 관리자가 지정한 자체 전사 서버로 전송될 수 있습니다. 그 서버의 관리 책임은 조직에 있습니다"를 넣는다(v1 §4 문단에 한 문장 추가). 국외이전 표에는 OpenAI만 남고, 로컬 서버는 국내 처리로 분류한다.
- 로컬 서버의 TLS 인증서가 사설 CA면 `STT_LOCAL_CA_FILE`(선택 env)로 신뢰 추가. 인증서 검증 끄기 옵션은 두지 않는다.
- 로컬 서버는 오디오를 저장할 수 있다(speaches 등은 기본 저장 안 함 — 확인 불가). 운영 안내 문서(`DISCORD-VOICE-SETUP.md`)에 "서버 쪽 저장 끄기"를 체크리스트로 적는다.

### 3.5 비용(1시간·5명)
- 로컬이 받아 주면 **$0**. OpenAI 대체 전부면 $0.27~0.32. 요약은 서버 비용 0(사용자 AI).
- 로컬 서버 사양 참고: faster-whisper small CPU int8 RAM ≈1.5GB(L §3) — 사용자 PC에서는 가볍고, LXC(512MB)에서는 불가(그래서 외부에 둔다).

---

## 4. 요약·정리는 사용자의 AI가 (MCP·스킬)

### 4.1 core: 회의록 사용자 API 신설(지금은 웹 경로만 있다 — M §3)
`core/api/routers/notes.py`(새 파일), `api.add_router("/notes", notes.router)`. 사용자 토큰·세션 인증(다른 사용자 라우터와 같은 `AuthBearer`), 가시성은 `get_visible_note` + 초안 규칙.
| 경로 | 역할 | source=mcp일 때 AI 정책 |
|---|---|---|
| `GET /api/orgs/{org}/notes?status=draft\|final&project=` | 목록(제목·일시·프로젝트·status·source·recording 요약) | 읽기: `ai.enabled`만 |
| `GET /api/notes/{id}?transcript=1` | 본문. `transcript=1`이면 `recording.transcript_md`·`stats`·참여자 포함 | 같음 |
| `PATCH /api/notes/{id}` | `title`, `body_md`, `tags`, `version`(낙관적 잠금, 기존 `note_save`와 같은 규칙) | `require_ai_enabled` + **`ai.edit_text`**(기존 키, 텍스트 편집 허용) deny면 403. 새 키 안 만든다 |
| `POST /api/notes/{id}/finalize {project_id|team_id|null}` | 확정(status=final, 공개 범위) | **source=mcp는 항상 403** — 확정은 사람이 웹에서 |
초안 편집 권한: created_by(시작자) 또는 조직 관리자. 확정 뒤 편집은 기존 회의록 규칙(멤버면 가능)을 따른다.
전사 원문은 `transcript_md`에 따로 있고 `body_md`의 `<details>` 블록은 **core가 만든 사본**이다. 사용자 AI가 `body_md`를 덮어쓰면서 `<details>`를 지워도 원문은 남는다(화면은 `transcript_md`를 접힌 영역으로 항상 보여 준다). 따라서 `body_md`에서 전사 사본은 **넣지 않고**, 화면·API가 `transcript_md`를 따로 내는 쪽이 단순하다 → §2의 `<details>`는 빼고 `body_md`는 빈 틀(요약/결정/할 일/미결)만 둔다. (v1 §1.5 형식 수정)

### 4.2 MCP 도구(`mcp_server/mcp_server/server.py`, 기존 `_core()` 패턴)
- `list_meeting_notes(org_id, status="draft", project_id=None)`
- `get_meeting_note(note_id, include_transcript=True)` — 전사·참여자·엔진 메타 포함
- `update_meeting_note(note_id, version, body_md=None, title=None, tags=None)`
- 확정 도구 없음(안내 문구: "확정은 웹 회의록 화면에서 합니다").
- 결정·할 일은 **기존 도구** 그대로: `record_task_decision(status=proposed)`, `create_task`, 그리고 태스크 연결은 `PATCH /api/notes/{id}`의 `task_ids`(추가 필드, `link_task` 호출). 전부 기존 `ai.*` 정책을 탄다(`ai.create_task` 등).
- `get_guide()` 문단에 회의록 절 추가.

### 4.3 스킬 `skills/pm-meeting/SKILL.md` (Claude Code용, core API 직접)
```
---
name: pm-meeting
description: 음성 회의 전사(초안 회의록)를 읽어 요약·결정·할 일·미결을 정리해 회의록 본문을 채운다. "회의록 12 정리해", "최근 회의 요약" 같은 요청에 쓴다. 확정은 하지 않는다.
argument-hint: "[회의록 번호 | 최근]"
---
1. ../pm/SKILL.md 규칙. 인자가 없거나 "최근"이면 GET /api/orgs/{org}/notes?status=draft 중 내가 시작한 최신 1건.
2. GET /api/notes/{id}?transcript=1 — 전사·참여자·프로젝트·엔진 메타를 읽는다. 전사 실패 구간 수가 있으면 먼저 알린다.
3. 작성(격식체, 서버가 준 사실만):
   ## 요약(5줄 이내) / ## 결정 사항(- 결정 — 근거 — 발언자) / ## 할 일(- 할 일 — 담당(표시명) — 기한 단서) / ## 미결
   발언자는 전사의 화자 표기를 그대로 쓰고, 전사에 없는 사실을 지어내지 않는다. 불확실하면 "(확인 필요)".
4. 사용자에게 본문을 보여 주고 확인받은 뒤 PATCH /api/notes/{id} {body_md, title?, version}.
5. 결정 항목은 사용자가 고른 것만 record_task_decision(status=proposed), 할 일은 사용자가 고른 것만 create_task → task_ids로 연결. 묻지 않고 만들지 않는다.
6. 마지막 줄: "확정은 웹 회의록 화면에서 해 주세요: <링크>".
```
claude.ai(MCP)에서는 같은 순서를 `get_guide()`의 회의록 절이 안내한다.

### 4.4 가시성·초안 규칙과의 맞물림
- 초안은 **시작자+조직 관리자**만 읽고 편집한다(결정 5). 참여자는 확정 뒤에 본다.
- 제안(§6 질문 2): 참여자(`participants[].user_id`, 연결 계정)도 **초안 열람**을 허용하면 참여자 각자가 자기 AI로 정리해 시작자에게 보낼 수 있다. 편집은 여전히 시작자·관리자. 기본은 결정 5대로 두고 사용자에게 묻는다.
- AI가 초안을 편집해도 `status`는 바뀌지 않는다. 확정 전에는 프로젝트 멤버에게 보이지 않으므로 AI가 만든 요약이 사람 확인 없이 퍼지지 않는다(기존 "AI 판단은 사람 확인 뒤 기록" 원칙과 일치).
- 전사 원문은 개인정보(음성 → 텍스트)다. 확정 뒤에도 `transcript=1`은 **회의록을 볼 수 있는 사람**만, 화면은 접힌 영역. 회의록 삭제 시 CASCADE.

---

## 5. 데이터 모델·설정 변경(v1 §3 대비 차이)
- `VoiceRecording.stats.engines`(§3.3). `draft_json` 열은 **없앤다**(서버가 요약 JSON을 만들지 않는다). 확정 화면의 "항목별 버튼"은 `body_md`의 체크리스트 줄을 파싱해 그린다(간단한 `- [ ] ` 줄 추출, 템플릿 밖 형식이면 버튼 없이 본문만).
- `meeting.*` Spec: `recording_enabled`(False) · `audio_keep_days`(**7**, 0~30) · `max_minutes`(180) · `default_visibility`(project) · **`stt_url`·`stt_model`·`stt_timeout_s`**(§3.1). Spec에 kind `text` 처리(검증 함수 `validate_text`에 URL 규칙 §3.4)가 추가된다.
- `MeetingNote.team/status/source`, `visible_notes` 규칙, `TaskDecisionRecord` 재사용은 v1 그대로.

---

## 6. 남은 사용자 질문(최대 3개)
1. **로컬 전사 서버의 API 키 보관 위치**
   - (a) **`.env.discord`의 `STT_LOCAL_API_KEY` 하나 — 추천.** 비밀값은 서비스별 env라는 기존 원칙, core DB에 비밀 저장 선례 없음. URL·모델은 조직 설정에 둔다.
   - (b) 조직 설정에 키까지(DB 평문, 화면에서는 마스킹). 조직마다 다른 서버를 쓸 때만 필요하며 지금은 단일 조직 운영이다.
2. **초안 열람 범위에 녹음 참여자를 넣을까요?**
   - (a) 시작자+관리자만(결정 5 그대로).
   - (b) **+참여자(연결 계정) 열람만 — 추천.** 참여자가 자기 AI로 정리해 시작자에게 보낼 수 있다. 편집·확정은 시작자·관리자.
3. **PoC(M0)용 개발 Discord 앱·서버 사용**
   - (a) **개발용 Discord 서버 + 테스트 앱 토큰(운영 토큰·운영 서버와 무관, PoC 뒤 삭제) — 추천.** 운영 봇 토큰으로 PoC를 하면 Python 리스너와 게이트웨이가 둘이 된다.
   - (b) 운영 서버에서 Python `discord-bot`을 잠시 내리고 운영 토큰으로. 그동안 명령·DM이 멈춘다.
(추천대로 확정하는 것: 전사 구간 침묵 2초·1.5초 미만 생략·동시 3, `ai.edit_text`로 AI 편집 정책, 확정은 웹만, Node 22 + `node:sqlite`.)

---

## 7. 구현 단계·담당·규모·충돌 파일

| 단계 | 내용 | 규모 | 담당 | 파일 | 게이트 |
|---|---|---|---|---|---|
| **M0 PoC** | `discord_gateway/` 뼈대: 접속·DAVE·구간 Ogg·`voiceStateUpdate`. 개발용 서버에서 3명·30분·입퇴장 10회·채널 이동 1회·`docker stats` | S | Opus | `discord_gateway/*`, `compose.yml`(서비스 교체는 M1에서) | 사용자 승인. 실패 시 Dysnomia |
| **M1 게이트웨이 이전** | listener·slash(20개)·DM commands·channels·watch·control(8081, 3 엔드포인트)·grants(`node:sqlite`, 같은 스키마)·core 봇 클라이언트 → Node. vitest 78개 포팅. 기능 동등성 체크리스트(명령마다 Python 테스트의 입력·기대 문구 그대로) | **L** | Opus(검토 Sol 1회) | `discord_gateway/*`, `compose.yml`(discord-bot build 경로), `.env.discord.example`, `docs/OPERATIONS-DEPLOYMENT.md` | 체크리스트 전부 통과, 컷오버 리허설(로컬 compose) |
| **M2 core** | `MeetingNote` 열·`VoiceRecording`·봇 API 4개·**회의록 사용자 API 4개**·`meeting.*` Spec(kind text·URL 검증)·`visible_notes`·테스트 | M | Opus | `core/notes/models.py`·`services.py`, `core/api/routers/discord.py`·**`notes.py`(신설)**·`api.py`·`schemas.py`, `core/orgs/settings.py` | pytest·ruff |
| **M3 음성·전사** | 세션 상태기·30초·종료 5종·구간 전사 큐(**로컬→OpenAI 대체**, 헬스체크, 형식·prompt 재시도)·`stats.engines`·janitor(7일)·재시작 복구·`/stt-health` control | M | Opus | `discord_gateway/voice/*`, `control` | 개발 서버 1시간 실녹음 → 전사 초안. 로컬 서버(speaches) 켜고/끄고 대체 전환 확인 |
| **M4 MCP·스킬·웹·문서** | MCP 도구 3개·`get_guide`·`skills/pm-meeting`·확정 화면(초안 띠·공개 범위·체크리스트 버튼, `DESIGN.md`)·설정 화면 [연결 확인]·`/privacy` 문단·`DISCORD-VOICE-SETUP.md`·`backup.sh` 주석(recorder 볼륨 없음 — 오디오는 `discord_bot_data` 아래 `sessions/`; **백업 tar에서 `sessions/`를 `--exclude`**) | M | Sonnet | `mcp_server/mcp_server/server.py`, `skills/pm-meeting/`, `core/web/views/notes.py`·템플릿, `docs/*`, `scripts/backup.sh` | 디자인 검토, 스킬 `test_pm.py` 통과 |
| 정리(다음 라운드) | Python 게이트웨이 5파일·테스트 78·discord.py 의존성 삭제 | S | Sonnet | `discord_service/*` | 컷오버 2주 안정 뒤 |

순서: M0 → **M1 ∥ M2** → M3 → M4. 전체 규모 **L**(v1의 별도 recorder안은 M+였고, 이전 비용 L이 더해진 대신 봇·토큰·내부 HTTP가 하나씩 준다).
충돌: `compose.yml`(M1 단독), `routers/discord.py`·`schemas.py`·`settings.py`·`api.py`(M2 단독), `server.py`(M4 단독), `scripts/backup.sh`(M4). M1과 M2는 API 계약(v1 §3.2 + §4.1)만 맞추면 겹치는 파일이 없다.
오디오 저장 위치는 기존 `discord_bot_data` 볼륨의 `sessions/` 하위(새 볼륨 없음). backup.sh의 tar에 `--exclude=./sessions`를 넣는다(7일짜리 임시 자료를 30일 백업에 넣지 않는다).

---

## 8. 메모리 재추정(512MB)
| 프로세스 | v1(별도 recorder) | **v2(b)** |
|---|---|---|
| postgres + web | 170~240 | 170~240 |
| discord(발송, Python) | 50 | 50 |
| discord-bot(Python) | 50 | — |
| recorder(Node) 대기/녹음 | 70/110 | — |
| **discord-gateway(Node)** 대기/녹음 | — | 85/130 |
| 합계 대기/녹음 | 390~460 / 430~500 | **305~375 / 350~420** |
v2가 v1보다 60~80MB 가볍다. M0에서 측정해 확정한다. `mem_limit 256m`은 유지.

---

## 9. 확인 불가·위험
- `@discordjs/voice` 0.19.2 장시간 안정성(M0가 답한다). 음성 수신은 Discord 비공식.
- whisper.cpp server의 입력 형식(wav만?)·speaches의 `prompt`·`language` 지원 범위·오디오 저장 기본값 — M3에서 실제 서버로 확인. 설계는 400/415 재시도로 흡수한다.
- Python 테스트 78개의 Node 포팅 중 가짜 Discord 객체(`FakeInteraction`, conftest 458행)의 동등성 — M1 체크리스트로 보완.
- `node:sqlite`는 Node 22.13+에서 플래그 없이 쓸 수 있다고 알고 있다(확인 불가 시 `better-sqlite3` 1개 추가).
- 운영 LXC 현재 메모리 사용량(저장소에 없음).
- 봇 녹음의 통비법 판례, gpt-transcribe·로컬 모델의 한국어 WER.

## 사용자 결정 결과 (2026-10-06) — 위 설계보다 우선
1. 로컬 STT API 키는 **조직 설정(DB)**에 둔다. 단 평문이 아니라 기존 GitHub 토큰 저장과 같은 Fernet 암호화로 저장하고, 화면·API·로그에는 마스킹(설정됨/미설정만). 설정 화면에서 바꿀 수 있다.
2. 회의록 초안 열람은 **시작자+관리자만**. 참여자에게는 확정 후 공개 범위대로.
3. M0 PoC는 **운영 봇 토큰**으로 한다(개발용 앱 없음). PoC 동안 운영 `discord-bot`을 잠시 내리고, 끝나면 즉시 원복한다. 시점은 사용자와 맞춘다(3명·30분 음성 참여 필요). 운영 서버에서 무엇을 내리고 올리는지는 실행 직전에 사용자에게 알린다.

## 사용자 결정 결과 2 (2026-10-06) — 위 모든 설계보다 우선
1. **`/회의_이어가기` 제거.** 시작 명령은 **`/회의시작`**(기존 `/회의록` 이름 대체). 시작자가 음성 채널을 떠나면 회의를 종료하고 그 텍스트 채널에 알린다: "회의 시작자가 나가서 회의를 종료하였습니다. 새 회의록을 작성하려면 /회의시작 을 눌러주세요." 순간 끊김(재접속) 대비 짧은 유예(기본 10초, 설정 `meeting.leave_grace_s`)만 둔다. `current_owner`·이어가기 API·권한 이전은 없앤다.
2. **참가자 = PM 계정 연동.** 참가자는 Discord↔PM 계정 연결(`accounts.identity.resolve("discord", …)`)로 PM 사용자에 매핑하고, 회의록에 **참석자(PM 계정)**를 남긴다. 전사 화자 표기는 PM 이름, 미연결자는 Discord 닉네임(계정 없음 표시).
3. **전사 정확도용 단어 목록(prompt)**: 조직 문서(ProjectDoc)·회의록·프로젝트·마일스톤·태스크 제목에서 자주 나오는 용어와 **참가자 이름**으로 용어집을 만들어 전사 요청의 prompt로 넘긴다. **녹음 시작자가 볼 수 있는 자료(`visible_projects`, 비공개 팀 규칙)에서만** 뽑는다. 길이는 전사 API의 prompt 한도에 맞춰 상위 N개로 자른다. 로컬 엔진이 prompt를 거부하면 prompt 없이 재시도(§3 규칙 유지).
4. **동시 녹음은 Discord 서버(길드)당 하나**(Discord 제약: 봇 하나는 길드당 음성 채널 하나). 이미 녹음 중이면 안내. 다른 길드끼리는 동시 가능.
5. **(추가) `/회의진행자넘기기 @참가자`**: 현재 진행자만 쓸 수 있고, 대상은 같은 음성 채널에 있는 PM 계정 연결 참가자. 녹음은 하나로 계속 이어진다(새 녹음·새 회의록을 만들지 않음). 새 진행자가 회의 전체의 회의록(초안 열람·편집·확정)을 관리하고, 이전 진행자는 권한을 잃는다(현재 진행자+조직 관리자만). 진행자가 넘기지 않고 나가면 1번 규칙대로 종료·안내("…새 회의록을 작성하려면 /회의시작 …"). 넘김은 채널에 공지하고 녹음 세션에 이력(누가 언제 누구에게)을 남긴다.

## 용어 통일 (2026-10-06, 사용자 지시 — 명령·알림·화면·API 설명·문서·스킬 모두 이 표만 쓴다)
| 표준 용어 | 뜻 | 쓰지 않는 말 |
|---|---|---|
| **회의** | 음성 채널에서 `/회의시작`부터 종료까지의 한 번 | 세션, 녹음 세션, 미팅 |
| **회의록** | 회의 결과로 남는 PM 문서(초안 → 확정) | 미팅 노트, 노트, 회의 기록 |
| **녹음** | 회의 중 참여자별 음성을 저장하는 일 | 레코딩, 수음 |
| **전사문** | 녹음을 글로 옮긴 원문(화자·시각 순) | 트랜스크립트, 받아쓰기, 자막 |
| **진행자** | 회의를 이끌고 회의록을 관리하는 사람(처음엔 `/회의시작` 한 사람) | 시작자, 주최자, 호스트, 오너 |
| **참여자** | 회의 중 음성 채널에 있던 사람 | 참가자, 참석자, 멤버 |
| **초안 / 확정** | 회의록 상태. 초안은 진행자·관리자만, 확정 뒤 공개 범위대로 | 임시, 드래프트, 완료, 게시 |
| **용어집** | 전사 정확도를 위해 넘기는 단어 목록 | 프롬프트, 사전, 단어장 |

명령 이름(모두 `회의` 접두):
- `/회의시작` — 회의 시작(녹음 시작, 실행자가 진행자)
- `/회의종료` — 진행자가 회의 종료
- `/회의진행자 @참여자` — 진행자 넘기기(앞 5번의 `/회의진행자넘기기`를 이 이름으로 통일)

안내 문구 기준: "회의 진행자가 나가서 회의를 종료하였습니다. 새 회의를 시작하려면 /회의시작 을 눌러 주세요." (격식체·용어표 준수)
코드 식별자는 영문 그대로 둔다(`MeetingNote`, `VoiceRecording`, `host`). 사용자에게 보이는 글에만 이 표를 적용한다.
