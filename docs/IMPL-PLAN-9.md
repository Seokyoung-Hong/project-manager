# N — 라운드 9 설계: Discord 음성 회의 녹음 → 전사 → 회의록 (IMPL-PLAN-9 초안, Fable, 2026-10-05)

기준 커밋 main `abfdced`. 입력: 외부 조사 `L-voice-research.md`(L), 코드 적합성 조사 `M-voice-codefit.md`(M). 법률 부분은 법률 자문이 아니다.
GUIDE-00 규칙(업무 규칙은 core `services`에만, 함수형 뷰, core에 새 의존성 없음)과 라운드 7·8 규칙(가시성 관문, 비밀값은 서비스별 env, Discord 관리 동작은 PM 권한 + 실행자 Discord 권한, 격식체, `DESIGN.md`)이 그대로 적용된다.
코드·git은 아직 건드리지 않았다. §9의 사용자 결정 뒤에 `docs/IMPL-PLAN-9.md`로 옮긴다.

## 0. 결론

**추천안: 별도 Node 녹음 서비스 `recorder`(새 Discord 앱·별도 토큰) + 기존 discord-bot이 명령을 받아 내부 HTTP로 지시 + core에는 회의록 모델·봇 API·확정 화면만.**

| 결정 | 선택 | 이유 |
|---|---|---|
| 런타임 | Node 22 + `@discordjs/voice` **0.19.2 고정** + `@snazzah/davey` + `@discordjs/opus` | DAVE 수신 복호화가 **안정 릴리스**에 있는 유일한 범용 조합(L §1.2~1.3). main의 다음 릴리스는 breaking(AudioPacket, Node 24)이라 버전을 고정한다 |
| 탈락: Python(discord.py + voice-recv/Pycord) | — | 수신 DAVE가 미병합 PR·개인 포크뿐(L §1.2). 운영 봇을 그 위에 올릴 수 없다 |
| 탈락: Rust Songbird | — | 수신 DAVE 실동작 미확인, 저장소에 Rust 선례 없음(L §1.2, 확인 불가) |
| 탈락: Dysnomia + davey | — | Craig 실전 사례는 강하나 범용 문서가 적다. `@discordjs/voice`가 막히면 2순위 대체재 |
| 봇 토큰 | **새 Discord 앱(별도 토큰)** | 같은 토큰으로 두 게이트웨이 세션을 열면 인터랙션 분배가 모호하고 길드 범위 `tree.sync`가 서로 덮어쓴다(M §2-B). 길드에 봇 하나 더 초대하면 끝 |
| 명령 수신 | 기존 **discord-bot**이 `/회의록`류를 받는다 | core 인가·`ac_project` 자동완성·격식체 응답·`too_fast`가 이미 있다(slash.py:185~). recorder는 명령을 등록하지 않고 내부 HTTP만 듣는다(control.py 패턴의 역방향) |
| 배치 | 운영 LXC(512MB)에 compose 서비스로, `profiles: ["recorder"]` | §7 메모리 추정으로 감당 가능하다고 본다. 핵심은 **Opus 패킷을 디코딩하지 않고 Ogg로 그대로 쓰는 것**(Craig 방식, L §6). PoC(§8 P0)에서 `docker stats`로 확정한다 |
| 전사 | **`gpt-transcribe`** $0.0045/분, 발화 구간 파일 단위 | 트랙이 화자별이라 diarize 불필요. 타임라인은 녹음기가 기록한 구간 시작 시각으로 맞추므로 타임스탬프 없는 모델로 충분(L §3). `whisper-1`은 대안 |
| 요약 | Claude Sonnet(권장) 또는 gpt-5-mini — §9 질문 3 | 회의당 $0.01~0.07, 품질 차이가 비용보다 크다 |
| 전사·요약 수행 위치 | **recorder(Node)** | OpenAI/Anthropic 키가 recorder env에만 있다(비밀값 분리 원칙, M §4). core는 결과만 받는다 |
| 오디오 저장 | recorder 전용 볼륨 `recorder_data`, core에 올리지 않음 | 첨부 모델 재사용 불가(M §2 공통). 백업 tar에서 제외해 급증을 막는다 |

---

## 1. 전체 흐름

### 1.1 시작 `/회의록 [프로젝트] [제목]`
1. discord-bot(slash.py)이 받는다. `defer(ephemeral)` → core `/api/integrations/discord/meetings/check`(봇 API)로 인가:
   - 실행자가 PM 멤버이고(`_actor`), 프로젝트를 지정했으면 `visible_projects`에 있고, 조직 설정 `meeting.recording_enabled`가 켜져 있어야 한다.
   - Discord 쪽: `interaction.user.voice.channel`이 있어야 한다(**음성 채널에 있는 당사자만** 시작 — 통비법 당사자 녹음 구조, L §5.1). 관리자 권한은 요구하지 않는다(녹음은 채널 관리가 아니다).
2. core가 `VoiceRecording(status=recording)` + 초안 `MeetingNote(status=draft)`를 만들고 id를 돌려준다.
3. discord-bot이 recorder에 `POST http://recorder:8082/sessions {guild_id, channel_id, recording_id, starter_user_id, max_minutes, keep_days}`.
4. recorder가 음성 채널에 접속(DAVE 협상), 자기 닉네임을 `[녹음중] 산돌이`로 바꾸고, 음성 채널의 텍스트 채팅에 **공개 고지**를 보낸다:
   > 회의 녹음을 시작했습니다(시작: @시작자). 이 채널에 머무르면 녹음·전사에 동의한 것으로 봅니다. 참여를 원하지 않으면 채널에서 나가 주세요. 처리방침: <SITE_URL>/privacy
5. discord-bot이 실행자에게 ephemeral로 "녹음을 시작했습니다. 종료는 `/회의_종료`, 최대 N분입니다." 응답.

실패(recorder 접속 실패·4017·채널 정원 초과): recorder가 4xx/5xx를 돌려주고 discord-bot이 core에 `status=failed`로 되돌린 뒤 "녹음을 시작하지 못했습니다: <이유>".

### 1.2 녹음 중
- recorder는 `GuildVoiceStates` 인텐트로 `voiceStateUpdate`를 받는다(비특권).
  - **입장**: 참여자 목록에 추가, 텍스트 채팅에 "@입장자 님, 이 채널은 녹음 중입니다." 고지(스팸 방지: 같은 사람은 세션당 1회).
  - **퇴장**: 참여자 목록 갱신.
  - **시작자 퇴장**: 30초 타이머 시작. 텍스트 채팅에 "시작자가 나갔습니다. 30초 안에 `/회의_이어가기`를 하지 않으면 녹음을 종료합니다." 시작자가 30초 안에 다시 들어오면 타이머 취소.
- `/회의_이어가기`: discord-bot이 받아 core 인가(멤버, 프로젝트 가시성) → recorder `POST /sessions/{id}/takeover {user_id}`. recorder는 **그 사용자가 지금 그 음성 채널에 있을 때만** 시작자를 바꾼다(없으면 409 "음성 채널에 있는 참여자만 이어갈 수 있습니다").
- 오디오: `receiver.subscribe(userId, {end: {behavior: AfterSilence, duration: 2000}})`를 `speaking` 시작마다 열어 **발화 구간마다 파일 하나** `seg/{seq:05}-{userId}-{startMs}.ogg`. 구간 시작 시각은 첫 패킷 도착 벽시계(`Date.now()` − 세션 시작)로 기록하고 `segments.jsonl`에 append. Opus 패킷은 디코딩하지 않고 Ogg 페이지로 그대로 쓴다(디코더·ffmpeg 없이, 메모리 거의 0).
- 복호화 실패 프레임(MLS epoch 전환 중)은 세어서 세션 메타에 남긴다. 전사엔 영향이 작다(L §2).
- 세션 상태는 메모리 + `/data/sessions/{id}/session.json`(재시작 복구용).

### 1.3 종료
- 경로: `/회의_종료`(시작자 또는 조직 관리자), 30초 자동 종료(`end_reason=starter_left`), 최대 길이(`max_minutes`, 기본 180, 종료 5분 전 텍스트 고지), 봇 혼자 남음(모두 퇴장 → 즉시 종료), recorder 재시작(§6).
- recorder가 음성 채널을 나가고 닉네임을 되돌린 뒤 텍스트 채팅에 "녹음을 마쳤습니다(N분, 참여 M명). 회의록 초안이 준비되면 @시작자 님께 알립니다."
- core에 `PATCH /api/integrations/discord/meetings/{id} {status: transcribing, ended_at, end_reason, participants}`.

### 1.4 전사 (recorder, 백그라운드 큐)
1. 1.5초 미만 구간은 건너뛴다(비용·환각).
2. 구간 ogg → `ffmpeg -i in.ogg -c:a copy out.webm`(재인코딩 없음, OpenAI가 ogg는 안 받고 webm은 받는다 — L §3). 25MB는 구간 단위라 걸릴 일이 없다(64kbps 기준 50분 분량).
3. OpenAI `audio/transcriptions` `model=gpt-transcribe`, `language=ko`, `prompt`에 프로젝트명·참여자 표시명(고유명사 보정). **동시 3개**로 제한.
4. 결과를 `segments.jsonl`의 `start_ms` 순으로 정렬 → 전사 원문:
   ```
   [00:00:12] 홍길동: ...
   [00:00:40] 김철수: ...
   ```
   화자 = 트랙 주인(Discord 사용자 → core가 준 `discord_user_id → 표시명` 매핑, 미연결 사용자는 Discord 표시명).
5. 실패 구간은 3회 재시도 후 `[전사 실패]`로 표기하고 계속한다.

### 1.5 회의록 초안 (recorder → LLM)
- 입력: 전사 원문 + 프로젝트명·참여자·회의 일시. 출력(JSON): `title`, `summary_md`(요약), `decisions[]`(`{summary, reason}`), `action_items[]`(`{title, assignee_name|null, due_hint|null}`), `open_questions[]`.
- recorder가 core `PATCH /meetings/{id}`에 `{status: draft, transcript_md, draft: {...}, cost_usd}`. core `services.notes.apply_voice_draft`가 `MeetingNote.body_md`를 아래 형식으로 채운다(격식체):
  ```
  ## 요약
  ## 결정 사항
  - [ ] ...
  ## 할 일
  - [ ] ...(담당: ...)
  ## 미결
  ## 전사 원문
  <details>…</details>
  ```
- 시작자에게 Notice(`tasks.work_requests.notify`)로 "회의록 초안이 준비되었습니다 → <링크>". core는 Discord로 직접 나가지 않는다(라운드 8 원칙).

### 1.6 확정 (웹)
- `/notes/{id}` 기존 편집 화면에 **초안 띠**(status=draft): "음성 회의 초안입니다. 내용을 확인하고 확정해 주세요." + 공개 범위 선택(프로젝트/팀/조직 공통) + [확정] 버튼.
- 확정 전: 시작자(created_by)와 조직 관리자만 본다(§3.3). 확정 시 `status=final`, 선택한 범위로 가시성 관문이 적용된다.
- 결정·할 일 연결은 확정 화면의 항목별 버튼으로 **사람이** 한다:
  - 결정 항목 → [태스크에 기록]: 태스크 선택 → `TaskDecisionRecord(kind=user_input, input_type=major_choice, status=proposed, source="web", evidence_basis=inferred, summary=…)`. 기존 모델에 `task` 필수라 태스크 없는 결정은 회의록 본문에만 남는다(새 모델 안 만든다).
  - 할 일 항목 → [태스크 만들기]: 기존 태스크 생성 폼에 제목·담당 prefill → `MeetingNote.tasks`에 링크(`link_task`).
- 자동 생성은 하지 않는다(AI 판단을 사람 확인 없이 기록하지 않는 기존 원칙).

---

## 2. 서비스 구성

```
discord-bot (Python, 기존)  ──슬래시 수신·core 인가──▶ core (Django)
      │ POST /sessions, /takeover, /stop                     ▲ PATCH /api/integrations/discord/meetings/{id}
      ▼                                                      │ (봇 토큰 CORE_TOKEN, 같은 BotTokenAuth)
recorder (Node 22, 새 앱 토큰) ── 음성 채널(DAVE) ── OpenAI(전사) / Anthropic 또는 OpenAI(요약)
      └ /data/sessions/{id}/seg/*.ogg (recorder_data 볼륨)
```

### 2.1 recorder 디렉터리 `recorder/`
- `package.json`: `@discordjs/voice@0.19.2`(정확히 고정), `discord.js@^14`, `@snazzah/davey@^0.1.12`, `@discordjs/opus`, `prism-media`(Ogg 쓰기 — `OggLogicalBitstream`이 있는 2.0 alpha, discord.js 공식 recorder 예제와 같은 것; 안 되면 자체 Ogg 라이터 ~100줄, P0에서 결정), `openai`, `@anthropic-ai/sdk`(질문 3이 Claude일 때만).
- `Dockerfile`: `node:22-slim` + `ffmpeg`(apt, 리먹스에만 씀). 이미지 ~250MB.
- 파일: `index.js`(HTTP 서버 8082 + Discord 클라이언트), `session.js`(상태기·타이머·구간 쓰기), `transcribe.js`, `summarize.js`, `core.js`(core 호출), `janitor.js`(보관 기간 삭제, 1시간마다).
- HTTP 인증: 내부 compose 네트워크 전용 + `RECORDER_SHARED_SECRET` 헤더(discord-bot ↔ recorder). 호스트 포트로 공개하지 않는다(`expose`만, control 8081과 같다).
- 로그는 격식체가 아니어도 되지만 **채널에 보내는 문장은 전부 격식체**(상수로 한 파일에 모은다).

### 2.2 compose.yml 추가
```yaml
  recorder:                      # 음성 회의 녹음·전사. 별도 Discord 앱 토큰. 명령은 discord-bot이 받아 내부 HTTP로 지시한다
    profiles: ["recorder"]
    build: ./recorder
    env_file: .env.recorder      # RECORDER_BOT_TOKEN, OPENAI_API_KEY, (ANTHROPIC_API_KEY), CORE_TOKEN, RECORDER_SHARED_SECRET
    environment:
      CORE_URL: http://web:8000
      DATA_DIR: /data
      PORT: "8082"
    volumes:
      - recorder_data:/data
    expose: ["8082"]
    mem_limit: 256m              # 녹음이 폭주해도 web·db를 끌어내리지 않게
    depends_on: { web: { condition: service_healthy } }
    restart: unless-stopped
```
discord-bot에 `RECORDER_URL: http://recorder:8082`와 `RECORDER_SHARED_SECRET`(.env.discord) 추가. `.env.recorder.example` 신설. recorder_data는 **backup.sh 목록에 넣지 않는다**(주석으로 이유를 적는다 — 오디오는 보관 기간 뒤 지워지는 임시 자료).

### 2.3 Discord 앱(사용자가 할 일)
- 새 앱 "산돌이 녹음" 생성 → 봇 토큰 → `.env.recorder`. 특권 인텐트 불필요.
- 초대 권한: `View Channels`, `Connect`, `Send Messages`(음성 채널 텍스트 고지), `Change Nickname`. 길드 정원·채널 정원을 따른다(`MOVE_MEMBERS` 없음).

---

## 3. 데이터 모델·API (core)

### 3.1 모델
`core/notes/models.py`
- `MeetingNote`에 열 추가: `team = FK("orgs.Team", null=True, SET_NULL, related_name="notes")`, `status = Char(choices=draft|final, default="final")`, `source = Char(choices=web|voice, default="web")`. 기존 행은 기본값으로 영향 없음.
- 새 모델 `VoiceRecording`:
  ```
  note            OneToOne(MeetingNote, CASCADE, related_name="recording")
  guild_id        Char(32)   voice_channel_id Char(32)
  started_by      FK(User, PROTECT)   # /회의록 실행자. 이어가기로 바뀌면 current_owner에 반영
  current_owner   FK(User, PROTECT)
  started_at / ended_at   DateTime
  end_reason      Char(choices=command|starter_left|max_length|empty|restart|failed, blank)
  status          Char(choices=recording|transcribing|draft|done|failed)
  participants    JSON  # [{discord_user_id, display_name, user_id|null, joined_at, left_at}]
  transcript_md   Text  # 256KB 상한(notes.services.MAX_BODY와 같은 규칙)
  stats           JSON  # {segments, skipped, decrypt_failures, transcribe_failed, cost_usd, model, summary_model}
  audio_expires_at DateTime(null)  # recorder가 지우는 예정 시각(화면 표시용)
  ```
  오디오 경로는 core에 두지 않는다(recorder가 `recording.id`로 디렉터리를 찾는다).
- 결정·할 일 후보는 **별도 모델 없이** `MeetingNote.body_md` 체크리스트로 둔다(§1.6). 구조화된 초안 JSON은 `VoiceRecording.stats`가 아닌 `draft_json = JSON(blank)`에 보관해 확정 화면이 항목별 버튼을 그릴 때 쓴다.

### 3.2 봇 API (`core/api/routers/discord.py`, `BotTokenAuth`)
| 경로 | 역할 |
|---|---|
| `POST /meetings/check` | 인가·설정 조회: 멤버·프로젝트 가시성·`meeting.recording_enabled`. 응답 `{ok, max_minutes, keep_days, participants_hint}` |
| `POST /meetings` | `VoiceRecording(recording)` + 초안 `MeetingNote(draft, source=voice, created_by=실행자, project, team)` 생성 → `{id, note_id}` |
| `PATCH /meetings/{id}` | recorder·discord-bot이 상태 전이·결과를 올린다(`takeover`, `stop`, `transcript`, `draft`, `failed`). 서비스 `notes.services.update_recording`이 상태기 검증(역행 금지) |
| `GET /meetings/{id}/names` | `discord_user_id → 표시명·user_id` 매핑(전사 화자 표기용) |
업로드 본문은 전사 원문(≤256KB)뿐이라 프록시 26m 한도와 무관.

### 3.3 가시성
`visible_notes(user)` 수정:
```
Q(status="final") & (Q(project__isnull=True, team__isnull=True) | Q(project__in=visible_projects) | Q(team__in=visible_teams))
| Q(status="draft") & (Q(created_by=user) | Q(org admin))
```
- 비공개 팀 회의: `/회의록 팀:<팀>`으로 시작하면 `team` FK가 붙고 확정 뒤에도 `visible_teams` 안에서만 보인다. 프로젝트와 팀을 둘 다 비우면 확정 때 "조직 전원에게 공개됩니다" 확인 문구를 띄운다.
- 결정 기록·태스크 연결은 기존 관문(`get_visible_task`)을 그대로 탄다.

### 3.4 설정 (`core/orgs/settings.py`, 새 그룹 `("meeting", "회의 녹음")`)
| 키 | kind | 기본 | overridable | 설명 |
|---|---|---|---|---|
| `meeting.recording_enabled` | bool | False | True(프로젝트별 끄기) | 꺼져 있으면 `/회의록`이 "이 조직은 회의 녹음을 켜지 않았습니다" |
| `meeting.audio_keep_days` | int 0~30 | **0**(전사 끝나면 즉시 삭제) | False | 0이면 전사 직후 삭제, N이면 N일 뒤 janitor가 삭제 |
| `meeting.max_minutes` | int 10~360 | 180 | True | 자동 종료 |
| `meeting.default_visibility` | choice project/team/org | project | False | 확정 화면의 기본 선택값 |
전사·요약 모델은 조직 설정이 아니라 recorder env(`TRANSCRIBE_MODEL`, `SUMMARY_MODEL`)로 둔다 — 키와 함께 바뀌는 운영 값이다.
봇은 `check` 응답으로 값을 받으므로 recorder가 core 설정을 직접 읽지 않는다.

---

## 4. 동의·고지·개인정보 (법률 자문 아님, L §5)
- 구조: **음성 채널에 있는 당사자만 시작·이어가기**, 시작자 부재 30초 종료, 녹음 중 닉네임 표시, 입장자 개별 고지 → 제3자 녹음 시비를 줄이는 장치를 전부 갖춘다.
- `/privacy` 처리방침에 추가할 문단(웹 정적 페이지, 확정 문구는 사용자 검토):
  > 음성 회의록: 참여자가 `/회의록`으로 시작한 Discord 음성 회의의 음성을 참여자별로 녹음하고, 텍스트로 변환해 회의록 초안을 만듭니다. 음성 파일은 변환 후 즉시(또는 조직 설정에 따라 최대 30일 안에) 삭제하며 백업에 포함하지 않습니다. 변환·요약을 위해 음성과 텍스트가 미국의 OpenAI(및 Anthropic)에 전송·처리됩니다. 전사 원문과 회의록은 조직이 삭제할 때까지 보관합니다.
- 국외이전 고지 항목(이전받는 자·국가·목적·항목·기간)은 처리방침에 표로 적는다. 조문 원문은 L에서 확인 불가였으므로 사용자가 최종 확인한다.
- 전사 원문 삭제: 회의록 삭제 시 `VoiceRecording`이 CASCADE로 같이 지워진다. 별도 보존 정책은 두지 않는다.

---

## 5. 비용 (1시간·5명 회의, 추정)
| 항목 | 계산 | 금액 |
|---|---|---|
| 전사 gpt-transcribe | 발화 합계 ≈ 60~70분 × $0.0045 | $0.27~0.32 |
| 요약 Claude Sonnet 5.5 | 입력 2만 토큰 × $2/M + 출력 2천 × $10/M | ≈ $0.06 |
| (대안) gpt-5-mini | | ≈ $0.01 |
| 합계 | | **≈ $0.35/회의**, 월 20회 ≈ $7 |
디스크: 64kbps Opus, 발화 60분 ≈ 30MB/회의. keep_days=7, 하루 2회여도 < 0.5GB. 전사 원문 ≈ 50KB/회의(DB).

---

## 6. 실패·복구
| 상황 | 처리 |
|---|---|
| recorder 재시작(배포·OOM) | 기동 시 `/data/sessions/*/session.json` 중 `recording` 상태를 찾아 **재접속하지 않고** 종료 처리(`end_reason=restart`) → 지금까지의 구간으로 전사·초안 진행 → 채널에 "녹음이 중단되어 지금까지의 내용으로 회의록을 만듭니다" + 시작자 Notice. 자동 재개는 하지 않는다(동의 상태 불명) |
| 음성 서버 이동(VOICE_SERVER_UPDATE) | `@discordjs/voice`가 재협상. 구간 파일은 영향 없음. 0.19.2의 경쟁 상태 수정은 미릴리스(L §2) → PoC에서 채널 이동·재접속 검증 |
| DAVE epoch 전환 손실 | 수용. `decrypt_failures` 집계만. 비율이 10% 넘으면 초안 상단에 경고 |
| 4017·DAVE 협상 실패 | 시작 실패로 즉시 보고. 라이브러리 업데이트 외 대응 없음 |
| 긴 녹음 keepalive | 라이브러리 내장 UDP keepalive. **PoC 필수 확인 항목**(Pycord #3388 선례) |
| 전사 API 실패 | 구간별 3회 재시도, 실패 표기. 전체 실패면 `status=failed` + Notice. 오디오를 지우지 않고 keep_days만큼 보관해 `/ops`에서 재시도 버튼(P4, 선택) |
| discord-bot ↔ recorder 단절 | 명령은 "녹음 서비스에 연결할 수 없습니다"로 즉시 답한다. 녹음 자체는 recorder 단독으로 계속된다(30초 규칙·최대 길이는 recorder가 집행) |
| 중복 시작 | 길드당 세션 1개(봇은 길드당 음성 상태 하나). 이미 있으면 "이 서버에서는 이미 녹음 중입니다(채널 #x)" |

---

## 7. 메모리 추정 (512MB LXC)
| 프로세스 | 추정 RSS |
|---|---|
| postgres | 40~60MB |
| web(gunicorn) | 120~180MB |
| discord + discord-bot | 50MB × 2 |
| **recorder 대기** | 60~80MB(Node + discord.js 캐시 최소화 `makeCache` 비활성) |
| **recorder 녹음 중(5트랙)** | +20~40MB(디코딩 안 함, 패킷을 바로 파일에 씀) |
| ffmpeg 리먹스(`-c copy`, 순차 1개) | +20MB, 수 초 |
| 요약·전사 HTTP | 미미 |
합계 ≈ 420~500MB로 **빠듯하다**. 완화: recorder `mem_limit 256m`, `NODE_OPTIONS=--max-old-space-size=128`, mcp 프로필과 동시에 켜지 않거나 swap 512MB 추가를 운영 메모에 권고(운영 변경은 사용자 몫). **P0에서 `docker stats`로 측정하고 넘치면 LXC 메모리 증설이 선행 조건**이다.

---

## 8. 구현 단계 · 담당 · 충돌 파일

| 단계 | 내용 | 담당 | 파일 | 게이트 |
|---|---|---|---|---|
| **P0 PoC** | `recorder/` 뼈대: 접속·DAVE·`subscribe`·구간 Ogg 쓰기·`voiceStateUpdate`. 운영과 같은 이미지로 **실제 Discord 서버에서 3명 이상, 30분 이상** 녹음, 입퇴장 10회, 채널 이동 1회, 파일 재생 확인, `docker stats` 최대 RSS 기록 | Opus | `recorder/*`, `compose.yml`(서비스 추가만) | 사용자 승인. 실패하면 Dysnomia로 교체 검토 |
| P1 core | 모델·마이그레이션·`notes/services`(상태기·`apply_voice_draft`·가시성)·봇 API 4개·설정 Spec·테스트 | Opus | `core/notes/models.py`, `core/notes/services.py`, `core/api/routers/discord.py`, `core/api/schemas.py`, `core/orgs/settings.py` | pytest 전부 통과, ruff 0 |
| P2 discord-bot | `/회의록 [프로젝트] [팀] [제목]`, `/회의_이어가기`, `/회의_종료` + recorder HTTP 클라이언트 + 격식체 메시지 | Sonnet | `discord_service/.../slash.py`(612행 단일 `register` — P2 혼자 만진다), `config.py`, `.env.discord.example` | 단위 테스트(httpx mock) |
| P3 recorder 파이프라인 | 세션 상태기·30초 타이머·종료 경로 5종·전사 큐·요약·core PATCH·janitor·재시작 복구 | Opus | `recorder/*` | 1시간 실녹음 → 초안까지 end-to-end |
| P4 웹·운영 | 확정 화면(초안 띠·공개 범위·항목별 버튼, `DESIGN.md`), `/privacy` 문단, `OPERATIONS-DEPLOYMENT.md`(새 앱·env·메모리), `backup.sh` 주석, `GITHUB-APP-SETUP`류로 `DISCORD-RECORDER-SETUP.md` | Sonnet(화면은 디자인 규칙 검토 후) | `core/web/*notes*`, `core/templates/notes/*`, `docs/*`, `scripts/backup.sh` | 디자인 검토 |
| 검토 | P1·P3는 다른 제조사 검토(Sol) 1회 → Fable 승인 | | | |

P1과 P2·P3는 API 계약(§3.2)만 맞추면 병렬 가능. P2와 P4는 파일이 겹치지 않는다. 충돌 지점은 `slash.py`(P2 단독), `routers/discord.py`·`schemas.py`·`settings.py`(P1 단독), `compose.yml`(P0에서 한 번, 이후 변경 금지).

---

## 9. 사용자 결정 질문 (최대 5개)

1. **녹음 봇을 새 Discord 앱으로 만들까요?** (새 봇 토큰 1개, 길드에 봇 하나 더 초대)
   - (a) **새 앱 — 추천.** 인터랙션·명령 동기화 충돌이 없고 녹음 장애가 알림 봇과 분리된다.
   - (b) 기존 봇 토큰 공유. 같은 토큰 두 세션의 인터랙션 분배가 확인 불가라 비추천.
2. **전사 모델**
   - (a) **`gpt-transcribe` $0.0045/분 — 추천.** 구간 단위라 타임스탬프가 필요 없다.
   - (b) `whisper-1` $0.006/분. 단어 타임스탬프·자막(srt)이 필요할 때만.
   - 둘 다 OpenAI 키가 필요하다. 한국어 품질은 공식 수치가 없어 P3에서 실제 회의 1건으로 비교해 바꿀 수 있게 env로 둔다.
3. **요약 LLM과 키**
   - (a) **Claude Sonnet(Anthropic 키 추가) — 추천.** 결정·할 일 추출 품질. 회의당 ≈ $0.06.
   - (b) OpenAI `gpt-5-mini`. 키 하나로 운영이 단순하고 ≈ $0.01. 품질이 모자라면 (a)로 전환(env 한 줄).
4. **오디오 보관·백업**
   - (a) **전사 끝나면 즉시 삭제(`audio_keep_days=0`), 백업 미포함 — 추천.** 개인정보 최소화·디스크 걱정 없음. 전사 실패 시에만 7일 보관 후 삭제.
   - (b) 7일 보관(재전사·청취 가능), 백업 미포함.
   - (c) 30일 보관. 비추천(개인정보·디스크).
5. **회의록 공개 범위 기본값**
   - (a) **초안은 시작자+관리자만, 확정 때 프로젝트 선택이 기본 — 추천.** `/회의록`에서 프로젝트를 고르면 그대로 기본값.
   - (b) 팀 기본(비공개 팀 회의가 많다면).
   - (c) 조직 전원 공개 기본. 비추천.

추천대로 확정하는 나머지: 최대 녹음 180분(조직 설정으로 변경 가능), 침묵 2초 구간 분할, 1.5초 미만 구간 전사 생략, 시작자 부재 30초, recorder `mem_limit 256m`, 결정·태스크 연결은 사람이 확정 화면에서.

---

## 10. 확인 불가 · 위험
- 운영 LXC의 **현재** 메모리 사용량(저장소에 없음). P0 측정 전까지 §7은 추정이다.
- `@discordjs/voice` 0.19.2가 운영 환경에서 30분 이상 안정적인지(P0가 답한다). 라이브러리가 Discord 비공식 기능 위에 있어 Discord 쪽 변경으로 언제든 깨질 수 있다.
- prism-media 2.0 alpha의 Ogg 라이터 안정성(P0에서 자체 라이터로 대체 여부 결정).
- 봇 녹음이 통비법상 당사자 녹음으로 인정되는지에 대한 판례(없음). 처리방침·고지 문구는 사용자가 최종 확인.
- gpt-transcribe의 한국어 WER.
- 같은 길드에서 두 채널 동시 녹음은 **불가**(봇 하나 = 길드당 음성 상태 하나). 필요해지면 recorder 앱을 하나 더 두는 방식인데, 지금은 범위 밖.
