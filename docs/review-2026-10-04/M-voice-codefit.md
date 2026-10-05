# Discord 음성 회의록 — 현재 코드·배포 구조 적합성 조사 (main abfdced, 읽기 전용)

경로는 저장소 루트 기준. 줄번호는 조사 시점 기준.

## 1. discord_service 구조

- 라이브러리: `discord.py>=2.4,<3` (discord_service/pyproject.toml:10), lock은 **2.7.1** (discord_service/uv.lock:228-229). 의존성은 aiohttp, (3.13+에서) audioop-lts뿐(uv.lock:231-234).
- **음성 관련 의존성·코드 없음**: lock에 PyNaCl·davey·discord-ext-voice-recv 없음(uv.lock grep 0건). discord_service 소스에 voice/opus/ffmpeg 문자열 0건. Dockerfile은 python:3.12-slim + uv sync만, ffmpeg/libopus 설치 없음(discord_service/Dockerfile:1-8).
- 상주 프로세스 2종(같은 이미지):
  - `discord` = `run`, 60초 tick 발송, REST(httpx)만 — compose.yml:46-58, __main__.py:52-54, 자체 `Bot` 클래스(httpx 동기) discord_service/discord.py:55-65.
  - `discord-bot` = `bot`, 게이트웨이 리스너 — compose.yml:60-76, __main__.py:49-51. 내부 control 서버 8081(MCP 브리지) compose.yml:66,74-75, listener.py:91-100.
  - 둘 다 `profiles: ["discord"]`, `env_file: .env.discord` (compose.yml:47-49, 61-63).
- 인텐트: `Intents.none()` + dm_messages + guilds (+ 선택 members) (listener.py:52-55). **voice_states 인텐트 없음** → 음성 채널 입·퇴장(시작자 퇴장 30초 규칙) 감지 불가. voice_states는 비특권이라 포털 작업 불필요(일반 지식, 저장소 근거 없음).
- 4014(특권 인텐트 거부) 시 인텐트 줄여 재접속 폴백(listener.py:33-48).
- 슬래시 명령: `app_commands.CommandTree`, 바인딩된 길드마다 `register(tree, guild, ...)` (listener.py:62-77), setup_hook에서 길드별 `tree.sync`(listener.py:79-90). 등록 함수 slash.py:185, 응답은 defer(ephemeral) + to_thread로 동기 core 호출(slash.py:193-200). 길드 목록은 기동 시 1회만 읽음(listener.py:63-68).
- core 호출: `CoreClient`(동기 httpx, Bearer, X-Source: api) core_client.py:4-11. 봇 경로는 `/api/integrations/discord/*`에 `discord_user_id`를 실어 보냄(core_client.py:109-112). core 라우터는 `BotTokenAuth`로 scope=="bot" 토큰만 통과(core/api/auth.py:40-55, core/api/routers/discord.py:61). 실행자는 `user_by_discord_id`로 사람으로 바뀌고 source="dc"(routers/discord.py:66-75).
- 상태 저장: SQLite `Store` — 테이블 sent/daily/dm/weekly/runs/seen_status/grants(store.py:6-38). 봇은 `/data/bot.sqlite`, 발송은 `/data/discord.sqlite`로 파일 분리(compose.yml:52,67; listener.py:57-58).
  - 불일치: __main__.py:47 주석은 "리스너는 SQLite를 아예 열지 않고"인데 listener.py:58은 Store를 연다.
- 실행자 권한 확인: PM 쪽 인가는 core가(slash.py:202 주석 "인가는 core가 한다"), Discord 쪽은 `can_manage_channels(user)` = `user.guild_permissions.manage_channels`, 실패 시 False(fail closed) (channels.py:163-171). 길드↔조직 매칭 `guild_org_ids`(channels.py:174-177). `/알림채널`에서 사용(slash.py 약 590행).

## 2. 녹음기 배치

### A. 기존 discord-bot 프로세스에 넣기
- 장점: 게이트웨이 연결·명령 트리·길드 등록·core 클라이언트·권한 헬퍼 재사용(listener.py:62-103, slash.py:185). 같은 토큰 연결 1개 유지. 음성 연결은 게이트웨이 세션에 묶이므로 명령 수신자 = 음성 소유자, 라우팅 문제 없음.
- 단점: discord.py 본체는 음성 **수신**을 공식 지원하지 않음(확장 `discord-ext-voice-recv` 등 필요 — 일반 지식, 저장소 근거 없음). 오디오 디코딩·버퍼링이 같은 이벤트 루프면 하트비트 굶음 위험 — 리스너가 이미 이 위험을 경고(listener.py:136-138). 녹음 중 재배포 = 녹음 중단 + 알림·명령 동시 정지. 메모리 증가가 알림 봇까지 OOM에 끌어들임.
- Dockerfile에 ffmpeg/libopus, pyproject에 voice extra(PyNaCl/davey) 추가 → `discord`·`discord-bot` 두 서비스 이미지 모두 커짐(같은 build 컨텍스트 compose.yml:48,62).

### B. 별도 recorder 서비스
- 같은 봇 토큰으로 두 번째 게이트웨이 세션: 인터랙션 전달 대상이 모호해지고, 명령 등록(길드 범위 sync는 전체 교체 — listener.py:86)도 서로 덮어씀. → 같은 토큰을 쓴다면 명령은 discord-bot에만, recorder는 명령 등록 금지. (Discord 동작 자체는 일반 지식)
- 권장 변형: **recorder = 별도 봇 애플리케이션(별도 토큰)**. discord-bot이 `/회의록`을 받아 내부 HTTP(control 서버 패턴 control.py, compose.yml:74-75)로 "채널 X 녹음 시작/이어가기/종료"를 지시. 음성 연결은 recorder 단독 소유. 길드에 봇 하나 더 초대 필요.
- 다른 런타임(예: Node discord.js + @discordjs/voice) 가능하나 저장소에 Node 서비스 선례 없음(compose.yml 서비스 전부 Python/외부 이미지).
- 자원 격리: 녹음 OOM이 알림 봇을 죽이지 않음. profiles로 켜고 끄기 쉬움(mcp 선례 compose.yml:78-79).

### 공통 배포 영향
- 서버 자원: 512MB/8GB/5GB 수치는 docs/OPERATIONS-DEPLOYMENT.md(전체 71행)에 **없음**(grep 0건). IMPL-PLAN-7.md:490은 "운영 LXC 디스크 여유 — 범위 밖" → 확인 불가. 참여자별 PCM 48kHz·16bit·스테레오 ≈ 11.5MB/분/인(계산값) → 디스크에는 Opus/OGG로 바로 써야 함(대략 0.5MB/분/인, 일반 지식).
- 오디오 저장: `media_data`는 web 전용 마운트(compose.yml:24-26). discord 계열은 `discord_data`/`discord_bot_data`만(compose.yml:53-54,69-70). recorder가 media에 쓰려면 볼륨 공유 또는 core 업로드 API 필요.
- 첨부 재사용: `Attachment`는 task 또는 project에만 붙음(core/tasks/models.py:520-535), 회의록 FK 없음. 허용 확장자에 오디오(.ogg/.opus/.m4a/.wav) 없음(core/tasks/attachments.py:26-45). 파일당 25MB(:24), 대상당 50개(:25), 조직 합계 `org.attachment_quota_mb` 기본 2048(core/orgs/settings.py:347-357, attachments.py:69). → 그대로 재사용 불가, 쿼터 계산 규칙만 차용 가능.
- 백업: backup.sh는 `media_data discord_data discord_bot_data`를 통째 tar(scripts/backup.sh:22-30), 보관 30일(:8). 새 볼륨은 목록 추가 필요. 오디오를 media_data에 두면 매일 전체 tar에 포함돼 백업 급증 → 보관 기간 설정·전사 후 삭제 필요.
- 업로드 한도: 프록시 26m 권고(docs/OPERATIONS-DEPLOYMENT.md:63) — 오디오를 HTTP로 core에 올리면 영향.

## 3. 회의록 연결

- `MeetingNote`: org(필수), project(nullable = "팀 공통"), title, body_md, created_on, tags, version, tasks M2M(related_name="meeting_notes"), created_by(PROTECT, 필수) (core/notes/models.py:5-27). **team FK·오디오·전사 필드 없음**.
- 서비스: `create_note`(멤버·프로젝트 가시성 확인) core/notes/services.py:52-67, 본문 256KB 상한 :15, `link_task` :121-126, `visible_notes` = 프로젝트 없음 or visible_projects :29-33.
- **API·MCP 없음 확인**: core/api/routers/ (attachments, decisions, discord, docs, github, integrations, me, orgs, pr_context, projects, reports, requests, settings, tasks, today)에 notes 없음. mcp_server·skills에 MeetingNote/meeting 0건. 웹 경로만(core/web/urls.py:220-228). → 봇용 회의록 생성 엔드포인트 신설 필요(routers/discord.py 패턴 `_actor` → 서비스, :66-75, :303-315).
- created_by가 사람 필수 → `/회의록` 실행자(discord_user_id → User)를 작성자로 쓰는 기존 규칙과 맞음(routers/discord.py:1-5).
- 가시성: 프로젝트 공개 범위 "teams"면 관리자·프로젝트 관리자·담당 팀 멤버만(core/projects/services.py:73-89). 팀 `is_private`은 팀 세부 화면만 숨김(core/orgs/models.py:84-97) — 회의록 가시성과 무관. 프로젝트 없는 회의록은 조직 전원 공개 → 비공개 팀 음성 회의를 project 없이 저장하면 노출(설계 결정 필요).
- 결정 기록: `TaskDecisionRecord`는 task 필수, source 선택지 web/api/mcp(max_length=3, "dc" 없음) (core/tasks/models.py:153-215). 상태 `proposed`(확인 대기) 있음 → 회의 결정 후보를 proposed로 넣는 자리. 회의록 FK 없음.
- 태스크 후보: Discord 경로 태스크 생성 엔드포인트 존재(routers/discord.py:303-315). 후보 전용 모델은 찾지 못함.
- 채널 매핑: Organization.discord_guild_id/discord_channel_id(core/orgs/models.py:33-36), Team.discord_channel_id(:92), Project.discord_channel_id(core/projects/models.py:39). 모두 **텍스트 채널 하나**용, 봇 채널 명령도 TextChannel만(slash.py channel_cmd `selected: discord.TextChannel`, 약 459행). **음성 채널 → 프로젝트/팀 매핑 없음** → `/회의록`에 프로젝트 옵션(ac_project 자동완성 재사용 slash.py:208)이 최소 비용.

## 4. LLM·외부 API 설정
- `LLM_PROVIDER`는 config.py:40에서 읽지만 미구현(summarize.py:85, README.md:184, .env.discord.example:22-23).
- AI 정책 `ai.*`는 source=="mcp"에만(core/orgs/settings.py:31,358; core/orgs/services.py:39-46). 봇 경로 source="dc"는 대상 아님 → 전사·요약 결과 쓰기를 AI 정책에 묶으려면 별도 규칙 필요.
- 비밀값 분리: 봇 토큰·CORE_TOKEN을 web 환경에 넣지 않으려고 .env.discord로 분리(.env.example:54-56, .env.discord.example:1-2). → OpenAI 키는 전사·요약 수행 컨테이너 전용 env(.env.discord 또는 새 .env.recorder)에 두는 것이 원칙과 일치. core .env에 두면 web까지 퍼짐.

## 5. 설정 항목 자리
- `Spec(key, kind, default, scope, overridable, group, label, help, choices, lo, hi, ai_only, hidden)` core/orgs/settings.py:19-33, `GROUPS` :794-801(task/project/org/ai/notify/user). `hidden=True`로 미동작 설정 숨김(:32-34). 조회 `effective(key, org=, project=)` :900.
- 후보(새 그룹 "meeting"): `meeting.recording_enabled`(bool, 기본 False), `meeting.audio_keep_days`(int, 0=전사 후 즉시 삭제), `meeting.transcribe_model`(choice), `meeting.auto_summary`(bool), `meeting.max_minutes`(int). 프로젝트별 끄기는 overridable=True.
- 봇이 설정을 읽는 경로: `core.orgs()` 응답 settings를 scheduler가 매 틱 읽음(config.py:113-114 주석) → 재사용 가능.

## 6. 단계안 · 충돌 지점
1. core: 회의록 출처·오디오 메타(또는 별도 Recording 모델) + 봇 엔드포인트 + 설정 Spec. 파일: core/notes/models.py, core/api/routers/discord.py, core/api/schemas.py, core/orgs/settings.py.
2. 녹음기: 의존성·Dockerfile·compose 서비스, voice_states 인텐트, `/회의록`·`/회의_이어가기`(slash.py), 30초 타이머(on_voice_state_update, listener.py).
3. 전사(OpenAI) → 원문 회의록 저장.
4. 요약·결정 후보(proposed)·태스크 후보.
5. 보관 기간 정리 작업 + backup.sh 볼륨 목록.
- 충돌 지점: slash.py(612행, 모든 명령이 `register` 한 함수), listener.py(인텐트·이벤트), core/api/routers/discord.py(봇 엔드포인트 전부), core/api/schemas.py, core/orgs/settings.py(SPECS 단일 dict), compose.yml, discord_service/pyproject.toml+uv.lock, scripts/backup.sh.

## 확인 불가
- LXC 512MB/8GB/5GB 수치(저장소 문서에 없음).
- discord.py 2.7.1 + 확장의 음성 수신이 Discord DAVE(음성 E2EE) 환경에서 동작하는지.
- 같은 토큰 다중 게이트웨이 세션 시 인터랙션 분배 방식.
- 태스크 "후보" 전용 모델 유무.
