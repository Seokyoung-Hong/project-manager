# IMPL-PLAN-9 병행 구성: Python 봇 + Node 음성 서비스 (2026-10-12)

`IMPL-PLAN-9.md` §1의 "(b) 게이트웨이 전체를 Node로 이전"을 **보류**하고, 같은 봇 토큰으로 게이트웨이 세션 두 개를 띄운다(Discord는 같은 토큰의 복수 세션을 허용 — `discord-api-docs/developers/events/gateway.mdx`). 사용자 지시(10-12): "같은 토큰으로 세션 여러 개 쓸 수 있을 텐데", "병행 구성 개발 즉시 진행".
이 문서가 IMPL-PLAN-9 §1·§2의 프로세스 구성보다 우선한다. 전사·회의록·용어표·사용자 결정 1~3은 IMPL-PLAN-9 그대로다.

## 1. 역할 분담

| 서비스 | 언어 | 게이트웨이 | 맡는 일 | 하지 않는 일 |
|---|---|---|---|---|
| `discord-bot` (기존) | Python discord.py | 세션 A, 인텐트 그대로(guilds·dm_messages·members) | **모든 슬래시 명령·버튼**(새 `/회의시작`·`/회의종료`·`/회의진행자`·`/회의받기` 포함), `tree.sync`, DM, 채널 관리, control 8081 | 음성 연결. 음성 상태를 모른다(voice_states 인텐트 없음) |
| `discord-voice` (신규) | Node 22 discord.js + @discordjs/voice + davey (`discord_gateway/`) | 세션 B, 인텐트 `Guilds`·`GuildVoiceStates`만 | 음성 상태 추적, 음성 접속·녹음(구간 Ogg), 회의 자동 종료(진행자 퇴장 유예·모두 퇴장·최대 길이), 음성 채널 텍스트 채팅 고지, 닉네임 `[녹음중] 유달리`, 전사(로컬→OpenAI), core에 결과 PATCH, 7일 정리, 재시작 복구, 내부 HTTP 8082 | **명령 등록·인터랙션 응답 금지**(`interactionCreate`를 듣지 않는다, `application.commands`를 건드리지 않는다). DM 처리 금지 |

- 인터랙션은 두 세션 모두에 올 수 있으나 Node는 무시하므로 응답 충돌이 없다.
- `discord`(발송, REST)는 변화 없음.

## 2. compose
```yaml
  discord-voice:
    profiles: ["discord"]
    build: ./discord_gateway
    env_file: .env.discord          # DISCORD_BOT_TOKEN, CORE_TOKEN, (선택) OPENAI_API_KEY, OPENAI_TRANSCRIBE_MODEL
    environment:
      CORE_URL: http://web:8000
      VOICE_CONTROL_PORT: "8082"
      VOICE_DATA: /data
    volumes: [discord_voice_data:/data]   # /data/meetings/<recording_id>/ — 백업 제외(7일 임시 자료)
    expose: ["8082"]                      # discord-bot만 부른다. 호스트 포트 공개 금지
    mem_limit: 256m
    depends_on: { web: { condition: service_healthy } }
    restart: unless-stopped
```
`discord-bot`에 `VOICE_URL: http://discord-voice:8082` 추가. 둘 다 `.env.discord`의 `VOICE_CONTROL_SECRET`(없으면 기동 시 경고, 요청 거절)을 `Authorization: Bearer`로 주고받는다.

## 3. 내부 HTTP (Node, 8082, JSON, Bearer VOICE_CONTROL_SECRET)
| 메서드·경로 | 요청 | 응답 | 비고 |
|---|---|---|---|
| `GET /healthz` | — | `{ok, ready, meetings}` | 인증 없음 |
| `GET /guilds/{guild_id}/meeting` | — | `{meeting: null}` 또는 `{meeting: {recording_id, note_id, voice_channel_id, host_discord_user_id, started_at, participants: [{discord_user_id, discord_name, joined_at, left_at}]}}` | Python의 `/회의종료`·`/회의진행자`·`/회의받기`가 먼저 부른다 |
| `GET /guilds/{guild_id}/members/{user_id}/voice` | — | `{channel_id: str\|null}` | `/회의시작` 전 실행자 위치 확인 |
| `POST /meetings` | `{guild_id, discord_user_id, project_id, team_id, title}` | 201 `{meeting, recording}`(core `POST /meetings` 응답) / 409 `{detail}` 실행자가 음성 채널에 없음·이미 회의 중 / 4xx core 거절을 그대로 `{detail}` / 502 음성 접속 실패(core에 `failed` PATCH 후) | Node가 core `POST /api/integrations/discord/meetings`를 부르고 음성 접속까지 마친 뒤 응답한다(30초 상한) |
| `POST /meetings/{recording_id}/stop` | `{discord_user_id}` | 200 `{recording}` / core 거절 403·400은 `{detail}` 그대로 | Node가 core PATCH `status=transcribing, end_reason=command, discord_user_id` → 성공 시 음성 퇴장·전사 시작 |
| `POST /meetings/{recording_id}/host` | `{discord_user_id}` (새 진행자) | `{ok}` | Python이 core `/host`·버튼 승인 성공 뒤 알린다 → Node의 진행자 퇴장 감시 대상을 바꾼다 |

`{detail}`은 사용자에게 그대로 보여 줄 한국어 문장(core의 `detail` 문자열·dict 값을 펼친 것).

## 4. 흐름
- **`/회의시작 [프로젝트] [팀] [제목]`** (Python): `defer(ephemeral)` → Node `POST /meetings` → 성공: 실행자에게 "회의를 시작했습니다…" / 실패: `detail`. 프로젝트·팀 자동완성은 기존 슬래시와 같은 방식.
- **Node 시작 처리**: 실행자 음성 채널 확인 → core `POST /meetings`(voice_channel_id) → `joinVoiceChannel(selfDeaf:false, selfMute:true)` → Ready 30초 → 닉네임 변경(실패 무시) → 음성 채널 텍스트 채팅에 시작 고지 → 참여자 목록 초기화(채널에 이미 있는 사람) → core PATCH participants.
- **녹음 중** (Node): 입장 → 참여자 추가·입장 고지(회의당 1인 1회)·participants PATCH(디바운스 5초). 퇴장 → left_at. **진행자 퇴장** → `leave_grace_s` 유예, 안에 돌아오면 취소, 지나면 core PATCH `end_reason=host_left, discord_user_id=나간 사람` → 200이면 종료하고 응답 `channel_notice`를 채널에 / 400이면(진행자가 아님) 계속. **사람 0명**(봇만) → `end_reason=empty`(discord_user_id 비움). **최대 길이** `max_minutes` → 5분 전 고지, 도달 시 `max_length`. 봇이 강제로 끌려 나가 5초 안에 재접속 못 하면 `failed`.
- **`/회의종료`** (Python): Node `GET meeting` → 없으면 "진행 중인 회의가 없습니다" → Node `POST stop`.
- **`/회의진행자 @참여자`** (Python): Node `GET meeting`의 participants로 core `POST /meetings/{id}/host` → 성공 시 `channel_notice`를 음성 채널 텍스트 채팅에, Node `POST /host`.
- **`/회의받기`** (Python): core `POST /host-requests`(participants 동봉) → `texts.mention` + [승인]·[거절] 버튼(custom_id `meeting-host:{recording_id}:{request_id}:{1|0}`)을 음성 채널 텍스트 채팅에. 버튼(Python, 재시작에도 살아야 하므로 `on_interaction`에서 custom_id 접두로 처리) → core 응답 → 승인: `texts.channel_notice` 채널에 + Node `POST /host` / 거절: `texts.requester_notice`를 요청자에게 DM(실패 시 채널) / 403: `detail.meeting`을 누른 사람에게만(ephemeral).
- **종료 공통** (Node): 활성 구간 마감 → 음성 퇴장 → 닉네임 복구 → 종료 고지 → 전사 큐.
- **전사** (Node, IMPL-PLAN-9 §3): core `GET /meetings/{id}/names`(화자 이름·stt·용어집) → 1.5초 미만 구간 생략 → 엔진 = stt.url 헬스(`GET {url}/v1/models` 3초) 통과 시 로컬, 아니면 `OPENAI_API_KEY` 있으면 OpenAI(`OPENAI_TRANSCRIBE_MODEL`, 기본 `gpt-transcribe` — 사용자 결정 2), 둘 다 없으면 즉시 `failed`(stats에 사유). 구간 동시 3, `language=ko`, `prompt=용어집`, 로컬 400/415는 wav 재시도·prompt 거부 의심은 prompt 없이 재시도, 연결 실패 2회면 이후 OpenAI. 결과 `[HH:MM:SS] 이름: 텍스트`(회의 시작 기준, start_ms 순, 빈 결과 줄 생략). core PATCH `status=draft, transcript_md, participants, stats{engines:[…], segments, skipped, failed, minutes}`. 전사 일부 실패는 `[전사 실패]` 줄로 두고 draft.
- **재시작 복구** (Node 기동 시): `/data/meetings/*/state.json` 중 `phase=recording` → core PATCH `transcribing, end_reason=restart` → 있는 구간으로 전사. `phase=transcribing` → 전사 재개.
- **정리**: 1시간마다 `audio_expires_at`(core 응답에서 state.json에 저장) 지난 폴더 삭제.

## 5. 문구
사용자에게 보이는 새 문구는 Python `discord_service/discord_service/messages.py`의 `MEETING_*` 상수, Node `discord_gateway/src/texts.mjs` 한 파일에만 둔다. 격식체·IMPL-PLAN-9 용어표(회의·회의록·녹음·전사문·진행자·참여자) 준수. 구현 뒤 Sol이 문구만 다시 쓴다.

## 6. 운영 영향
- 기존 `discord-bot`은 재시작 1회(새 명령 sync). 음성 서비스 장애는 명령·DM에 영향 없음.
- 메모리: Node 대기 ≈85MB·녹음 ≈130MB(IMPL-PLAN-9 §8). 운영 LXC 가용 ≈190MB(10-12 측정) — `mem_limit 256m`, 녹음 중 `docker stats` 관찰.
- 전사 수단: 운영 `.env.discord`에 `OPENAI_API_KEY` 없음, 조직 `meeting.stt_url` 확인 필요. 없으면 녹음은 되지만 회의록은 `failed`.

## 7. 변경(10-12 사용자 결정 4) — 기본은 녹음만, 내려받아 직접 전사. OpenAI 키는 조직 선택
> "기본적으로는 녹음만 시행하고 그걸 다운로드 받아서 직접 전사할 수 있는 환경을 마련하고, 또 OpenAI 키를 넣어서 로컬 서버 대신 이 키로 whisper를 호출할 수도 있는 옵션을 제공하자." 조직·사용자별 로컬 전사 서버 이미지는 **나중에 별도**로 만든다.

§4 전사·§2 env를 이렇게 바꾼다.
- **녹음 파일**: 회의가 끝나면 Node가 구간들을 회의 시작 기준 시각에 맞춰 **하나의 혼합 음성 파일**(`meeting.ogg`, Opus 모노 32kbps 안팎)로 만든다(ffmpeg, 메모리 256MB 안에서 — 입력이 많으면 묶음 단위로 나눠 섞는다). core 봇 API `PUT /api/integrations/discord/meetings/{id}/audio`(multipart `file`)로 올린다. 올리기에 성공하면 Node 로컬 구간은 지운다(실패하면 재시도, 7일 정리는 그대로 안전망).
- **참여자별 트랙(10-12)**: 혼합 파일에 더해 사람마다 자기 구간만 같은 회의 시작 기준(adelay)으로 섞은 `track-<discord_user_id>.ogg`를 순차로 만들어 `PUT …/meetings/{id}/tracks/{discord_user_id}`(덮어쓰기, 상한·형식·410은 `/audio`와 같음)로 올린다. 혼합+모든 트랙이 올라가야 `uploaded`. core는 `VoiceTrack`(recording·discord_user_id 유일)에 두고, 회의록 화면에 참여자 이름별 내려받기(`회의록-<note>-<이름>.ogg`, 권한·만료 정리는 혼합 파일과 같음).
- **엔진 선택**: ① 조직 설정 `meeting.stt_url`(기존, 로컬 서버) ② 조직 설정 **`meeting.openai_api_key`**(신설, `meeting.stt_api_key`와 같은 Fernet 암호화·마스킹) → OpenAI `whisper-1`(env `OPENAI_TRANSCRIBE_MODEL`로만 바꿈) ③ 둘 다 없으면 **녹음만**. `.env.discord`의 `OPENAI_API_KEY`는 쓰지 않는다.
- **녹음만일 때**: core PATCH `status=draft, transcript_md="", stats{engine:"none", …}`. 실패가 아니다. 진행자 알림 문구는 "녹음 파일이 준비되었습니다. 회의록 화면에서 내려받아 전사할 수 있습니다." 계열(core가 `stats.engine`으로 고른다).
- **core**: 오디오는 `MEDIA_ROOT` 아래 공개 URL이 없는 경로에 저장하고, 회의록 화면에 **[녹음 내려받기]**(회의록을 볼 수 있는 사람 — 초안이면 진행자·조직 관리자). `audio_expires_at`이 지나면 파일을 지우고 버튼 대신 "보관 기간(N일)이 지나 삭제되었습니다". 업로드 상한 300MB.
- `/회의시작`은 전사 수단이 없어도 거절하지 않는다(IMPL-PLAN-9 §3.2 마지막 줄 폐기).
