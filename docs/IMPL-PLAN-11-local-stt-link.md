> 번호 주의: 기존 `docs/IMPL-PLAN-11.md`(라운드 11: Notion 가져오기 등)와 다른 주제의 문서다.

# IMPL-PLAN-11 · 내 PC를 전사 서버로 연결하기 (2026-10-13, 개정 1 — Fable 승인 조건·권고·사용자 결정 반영)

사용자 요구: 누구나 포트포워딩 없이 자기 PC를 유달리 전사 서버로 쓴다. PC에서 명령 하나 → 기기 인증으로 계정에 묶는다 → 켜져 있는 동안만 쓴다.
기준: discord_test `99c0e84`, udally-stt `1e2825b`. 근거 표기는 `파일:줄`. 이 문서는 계획만이며 코드는 바꾸지 않았다.
사용자에게 보일 문구는 전부 `{{COPY:키}}` 자리표시다(문구는 Sol이 쓴다). 키 목록은 §9.3.

**사용자 결정(2026-10-13, 바꾸지 않는다)**
1. PC에서 명령 하나(Docker 또는 uv) → 기기 인증(주소+코드, RFC 8628 유사)으로 유달리 계정에 묶는다. 켜져 있는 동안만 쓴다.
2. 들어오는 연결 없음. PC → 유달리로 나가는 연결만 쓴다. 유달리가 지시 주체이고, 전사 지시는 서버 주인만 한다.
3. 범위: 서버 주인이 볼 수 있는 회의록의 녹음. 조직 관리자는 "멤버 PC로 전사"를 끌 수 있다(기본 켜짐).
4. Discord 자동 전사: 진행자의 PC가 켜져 있으면 그 PC로, 꺼져 있으면 조직 설정(서버 주소·OpenAI 키)으로.
5. 조직 "전사 권한" 설정(조직 자원으로 지시할 수 있는 사람) + 녹음당 시도 횟수 한도. 자기 PC 전사는 권한·한도 없음. 멤버도 범위 안 녹음에 전사 메뉴를 쓴다(서버 설정·조직 키는 관리자만).
6. 기존 "서버 주소 직접 입력"은 고급 설정으로 남긴다.
7. 모델 선택지는 "내 PC · OpenAI Whisper large-v3-turbo"처럼 계열까지. 꺼져 있으면 "꺼져 있음"으로 고를 수 없다. 전사문 ≠ 회의록(다시 전사해도 회의록 본문은 그대로).
8. (개정 1 추가) 전사 권한 기본값 = 멤버 누구나(관리자가 바꿀 수 있음).
9. (개정 1 추가) 조직 수단으로 하는 사람 지시 전사는 **녹음당 1회**. 누가 이미 조직 수단으로 전사했으면 멤버는 그 녹음을 조직 수단으로 다시 전사할 수 없다. 관리자는 예외. 자동 전사·넘겨받은 작업·시작 전 취소는 세지 않는다. 자기 PC 전사는 무제한.
10. (개정 1 추가) 이미지는 GitHub 공개 저장소 + GHCR 공개 이미지로 배포한다(라이선스 검토를 통과한 뒤, 계정·저장소 이름은 따로 정함). 공개는 플래그 없이 바로 전체 공개.
11. (개정 1 추가) 자동 전사에 쓰는 PC 모델 = 마지막으로 [모델 적용]한 모델. 넘기기까지 기다리는 시간 2분. 시안은 따로 만들지 않고 기존 시안 B 안에 넣는다.

## 0. 요지

- **연결 = 짧은 폴링**(§2). PC가 5초마다 `POST /api/integrations/stt/heartbeat`를 보내고, 응답으로 명령(모델 받기)과 작업을 받는다. 진행 보고·취소는 Node와 **같은 진행 PATCH 응답의 `cancel`** 패턴을 그대로 쓴다. ASGI·WebSocket·NPM 설정·새 서비스는 필요 없다.
- **PC = 또 하나의 작업자**(§4). PC가 직접 대기열에서 **자기에게 배정된 작업만** 가져가고(core `claim()`에 `server` 조건 추가), 트랙·녹음을 core에서 내려받아 PC 안에서 잘라 전사한 뒤, 구간별 결과 행을 올린다. 전사문 조립(`[HH:MM:SS] 이름: …`)은 core가 한다 → PC에는 이름 목록을 주지 않는다.
- 요청마다 core가 PC로 HTTP를 중계하는 방식은 버린다(Node가 결과를 기다리며 막히고, core가 구간 오디오를 임시 보관해야 한다).
- **Node 변경 없음**(§7.3). Discord 자동 전사를 PC로 보낼 때는 core가 `names` 응답의 `stt`를 비워 Node가 "녹음만" 경로로 초안을 올리게 하고, 그 뒤 PC가 대기열에서 가져간다. PC가 꺼지면 core가 작업을 조직 수단으로 넘겨 Node가 기존 `claim`으로 가져간다.
- 토큰 = 기존 `ApiToken`에 새 범위 `stt`(해시 저장·폐기 그대로). 서버당 토큰 1개.
- 설치 = OS별 한 줄(`irm https://udally.sio2.kr/stt/install.ps1 | iex` / `curl -fsSL https://udally.sio2.kr/stt/install.sh | sh`). Docker가 있으면 GHCR 이미지(digest 고정), 없으면 uv. 끝나면 기기 인증까지 이어진다(§10.1).
- 기존 frps 중계(`99c0e84`)는 이 기능이 운영에서 확인된 뒤 지운다(§13, 사용자 승인 뒤).

## 1. 근거(현재 코드)

| 사실 | 출처 |
|---|---|
| 운영 gunicorn은 `gthread` 2 워커 × 32 스레드, `--timeout 90`. SSE가 이미 연결을 50초 붙잡는다(워커당 24개 상한) | `core/entrypoint.sh:4-13` |
| Node는 후처리 큐가 빌 때만 `POST /transcriptions/claim`, 진행은 5초 간격 PATCH, 응답 `cancel`이면 abort | `discord_gateway/src/meetings.mjs:247-262, 363-374` |
| `claim()`은 `select_for_update(skip_locked)`로 가장 오래된 queued 하나, 같은 녹음에 도는 작업이 있으면 건너뜀 | `core/notes/transcription.py:259-277` |
| `requeue()`는 `kind="retry"`만 되돌린다 — `kind="upload"` 작업은 Node 재시작 때 되돌려지지 않는다(기존 빈틈, §7.5에서 같이 고침) | `core/notes/transcription.py:280-293` |
| 진행 보고는 `report()` 하나. `engine`·`model`을 보고로 바꿀 수 있다(PC 경로에서는 막아야 함) | `core/notes/transcription.py:219-243`, `core/api/schemas.py:540-553` |
| 자동 작업은 종료 PATCH 때 `running`으로 생기고 Node가 바로 전사, draft PATCH로 끝난다 | `core/notes/services.py:441-455, 505-510`, `transcription.py:158-211` |
| Node 자동 전사는 `GET /meetings/{id}/names`의 `stt`로 수단을 정한다. url·키가 비면 즉시 빈 초안(`engine: none`) | `meetings.mjs:335-356`, `transcribe.mjs:104-132`, `core/api/routers/discord.py:888-896` |
| Node는 올리기(혼합·트랙) → 전사 → draft PATCH 순서. 올리기 실패해도 PATCH는 진행 | `meetings.mjs:265-296, 308-333` |
| draft 알림은 `stats.engine == "none"`이면 "녹음만" 문구 | `core/notes/services.py:459-471` |
| 보관 0일이면 `audio_expires_at = ended_at` → 바로 만료(다시 전사 불가) | `core/notes/services.py:452-454, 519-520` |
| 회의록 가시성 관문 `visible_notes(user)`. 초안은 진행자·조직 관리자만 | `core/notes/services.py:25-41` |
| 전사 메뉴·다시 전사·취소·지정은 전부 조직 관리자 전용(`not_admin`, `require_admin`) | `core/web/views/transcribe.py:30-32`, `transcription.py:318, 389, 401`, `orgs/_tabs.html:11` |
| 올린 녹음 [전사 시작]은 회의록 편집 권한(`_check_edit`) + 조직 기본 수단 | `transcription.py:323-337`, `core/web/views/notes.py:194-207` |
| 토큰: `ApiToken`(sha256 해시, prefix, scope read/write/bot, revoke). 범위 검사는 `TokenAuth` 한 곳, 봇 경로는 `BotTokenAuth`로 구조적으로 막음 | `core/accounts/models.py:43-110`, `core/api/auth.py:24-60` |
| `TokenAuth`는 write 아닌 범위의 **쓰기만** 막는다 → 새 범위는 GET까지 막는 가드가 따로 필요 | `core/api/auth.py:28-35` |
| 시도 잠금 표 `LoginLock`(워커 공통) | `core/accounts/models.py:201-213` |
| 전사 설정 키 `STT_KEYS`는 전사 메뉴에서만 편집 | `core/orgs/settings.py:812-870, 956-962`, `views/transcribe.py:73-115` |
| 모델 목록 조립 `stt_models`(필드 표 §10 계약), [모델 적용] = `POST /v1/models/{id}` | `core/web/views/orgs.py:605-701`, `docs/IMPL-PLAN-10-transcribe-menu.md:157-176` |
| udally-stt: FastAPI, `/v1/models`(display_name·family·owned_by·fits·device·compute_type·rtf), 받기 스레드, `run()`이 전사 본체, `STT_CONCURRENCY` 3 | `udally-stt/server.py:54, 188-238, 342-366, 386-404` |
| udally-stt 이미지에는 ffmpeg 바이너리가 없다(python:3.12-slim). 디코딩은 PyAV(faster-whisper `decode_audio`) | `udally-stt/Dockerfile:1-22`, `server.py:313` |
| frps 중계(compose `relay` 프로필, `.env` FRP_TOKEN) | `compose.yml:148-155`, 커밋 `99c0e84` |

## 2. 연결 방식 — 결정: 짧은 폴링

| | 짧은 폴링(채택) | 롱폴 | WebSocket |
|---|---|---|---|
| 방법 | PC가 5초마다 heartbeat. 응답에 명령·작업 | heartbeat가 일이 생길 때까지 최대 25초 대기 | PC↔core 상시 연결 |
| core 새 코드 | 엔드포인트 5개(§6), 기존 `claim`·`report` 재사용 | 같음 + 대기 루프(DB 변화 알림이 없어 결국 1초 간격 조회) | ASGI 서버·channels·채널 레이어(redis) |
| 운영 변경 | 없음 | 스레드 점유(서버 1대 = 스레드 1개 상시, SSE 몫과 경쟁), NPM 읽기 시간 확인 | uvicorn/daphne 전환, redis 추가, NPM websocket 허용 |
| 지연 | 명령 ≤5초, 취소 ≤ 구간 하나 + 5초(Node와 같음) | 명령 ~1초 | 즉시 |
| 부하 | 서버 N대 → N/5 요청/초, 행 쓰기는 상태가 바뀌었거나 10초 지났을 때만 | 같거나 큼 | 작음 |

- 결정 근거: 지연 5초는 전사(분 단위)에 비해 무시할 만하고, 운영 변경이 0이다. 취소는 이미 진행 PATCH 응답으로 받으므로 heartbeat 지연과 무관하다.
- ponytail: 명령 지연이 문제가 되면 heartbeat 응답에 `poll_s`를 1로 내려 보낸다(서버가 간격을 정한다). 그 이상은 그때 롱폴.

**모델 목록·[모델 적용]·연결 시험을 이 방식으로**
- 모델 목록: PC가 heartbeat 본문에 자기 `/v1/models` 항목 배열을 그대로 싣는다 → core는 `SttServer.models`에 저장(바뀌었을 때만). 화면은 저장본을 읽는다(PC로 요청하지 않는다). 기존 `stt_models`의 항목 해석부를 함수로 떼어 같이 쓴다(`parse_models(items)`).
- [모델 적용]: 화면이 `SttServer.pull_model`을 저장 → 다음 heartbeat 응답 `pull`로 전달 → PC가 내부에서 `start_download` 로직 실행 → 진행률·오류는 다음 heartbeat의 models(`downloading`·`progress`·`error`, `server.py:200-219`)로만 보인다(따로 결과 칸을 두지 않는다). 화면은 받는 중이면 기존처럼 3초마다 다시 그린다(`_stt_test.html` polling 패턴). `fits=false` 모델은 화면에서 고를 수 없으므로 409는 화면 앞에서 막힌다. 받은 모델이 `ready`가 되면 core가 `default_model`로 두고 `pull_model`을 비운다.
- 연결 시험: 네트워크 호출 없이 "마지막 응답 N초 전·준비된 모델 N개"를 보여 준다. 판정: `last_seen_at`이 15초(heartbeat 3번) 안이면 켜짐.

## 3. 기기 인증(RFC 8628 유사)

```
PC: uv run server.py connect           ─▶ POST /api/integrations/stt/device {name, machine_id, version}
                                       ◀─ {device_code, user_code "BCDF-GHJK", verification_uri, expires_in 600, interval 5}
PC 화면: {{COPY:connect_prompt}}  (주소 + 코드. 코드가 들어간 주소는 만들지 않는다)
사람: https://udally.sio2.kr/link 를 직접 연다(로그인 필요 → 로그인 뒤 돌아옴)
      → PC 화면에 뜬 코드를 손으로 입력 → 확인 화면: 기기 이름(고칠 수 있음)·장치·버전·요청 시각 + [허용] [거절]
PC: 5초마다 POST /api/integrations/stt/device/token {device_code}
      → 400 {error: authorization_pending | access_denied | expired_token}
      → 200 {access_token, server_id, name}   (승인 뒤 첫 조회 때 한 번 발급, 이후 같은 device_code는 expired_token)
PC: 토큰 파일 저장 → heartbeat 시작
core: 허용하면 소유자에게 알림 {{COPY:link_approved_notice|server_name}} (기존 알림 경로 `_notify_owner`(`core/notes/services.py:260`)와 같은 DM 함수를 재사용)
```

- **피싱 대비**(개정 1): `verification_uri_complete`와 `/link?code=` 자동 채움을 두지 않는다. 남이 만든 코드를 링크로 보내 "허용"만 누르게 하는 공격을 막으려고, 사람이 **자기 PC 화면에서 본 코드**를 직접 입력하게 한다. 확인 화면에는 `{{COPY:link_consent}}`(자기 PC에서 실행한 명령이 맞는지 확인하라는 경고)를 둔다. 허용 직후 알림으로 모르는 연결을 알아챌 수 있다.
- `user_code`: 8자, 모음·헷갈리는 글자 뺀 20자 알파벳(RFC 8628 §6.1 권고), 4-4 하이픈. 대소문자·하이픈 무시. 대기 중인 코드끼리 유일.
- `device_code`: `secrets.token_urlsafe(32)`, **sha256만 저장**. 10분 만료, 1회 사용. 조회 간격은 PC가 `interval`을 지킨다(`slow_down`은 두지 않는다 — ponytail: 조회가 문제가 되면 그때 넣는다).
- 토큰 발급은 승인 시점이 아니라 **PC가 승인 뒤 처음 물을 때** 만든다 → 원문을 core에 잠시라도 보관할 일이 없다. `ApiToken.issue(user, name=…, scope="stt", for_ai=False)` 재사용(`core/accounts/models.py:69-85`).
- **서버별 1개**: `SttServer`는 `(owner, machine_id)` 유일. 같은 기기를 다시 연결하면 행을 재사용하고 이전 토큰을 `revoke()`한 뒤 새 토큰을 단다. 사람당 서버 상한 5대(`MAX_SERVERS`).
- `machine_id`: PC가 처음 connect 때 만든 uuid4(토큰 파일에 같이 저장). 다른 사람 machine_id를 넣어도 `owner`가 달라 남의 행을 건드리지 못한다.
- 폐기: [끊기](웹) → 토큰 revoke + 행 삭제 + 그 서버의 활성 작업 정리(§7.4). PC는 다음 heartbeat에서 401 → 토큰 파일 삭제, `{{COPY:pc_unlinked}}` 출력, 종료 코드 3.
- 남용 한도: 코드 확인 실패는 `LoginLock(kind="stt_link", key=user.pk)`로 10분 5회. 코드 발급은 거절하지 않는다 — 미승인 대기 코드가 200개를 넘으면 **가장 오래된 대기 코드부터 지운다**(발급 폭주가 정상 사용자를 막지 못하게, 표 크기도 고정). IP를 남기지 않는 방침(`entrypoint.sh:9`)이라 IP 기준 제한은 두지 않는다. 같은 machine_id의 대기 코드는 새 발급 때 지운다.
- 탈퇴: 토큰은 `accounts/services.py:265`가 이미 지우고, `SttServer.owner`는 CASCADE.

## 4. 실행 모델: PC = 작업자

- 대기열·상태 모델은 IMPL-PLAN-10 §4 그대로. 차이는 `TranscriptionJob.server`(FK)가 있으면 **그 서버만** 가져갈 수 있다는 것.
  - Node `claim()`: `.filter(server__isnull=True)` 추가.
  - PC `claim_for(server)`: `.filter(server=server)` + 녹음 상태 `draft|done` + 입력이 **다** 올라왔을 때만:
    디스코드는 `{g.user_id for g in rec.segments} ⊆ {올라온 트랙(audio 있음)의 discord_user_id}`, 올린 녹음은 `rec.audio` 있음. 조건이 안 맞으면 건너뛰고 다음 heartbeat에서 다시 본다.
    (`retry_block`(`transcription.py:309`)은 트랙이 **하나라도** 있으면 통과라서 쓰지 않는다. Node는 트랙을 한 사람씩 올리고 실패해도 draft PATCH를 보내므로(`meetings.mjs:279-290, 308-333`) 일부 트랙만 있는 draft가 생길 수 있다 — 그때 가져가면 일부 화자만 전사된다.)
  - 둘 다 `select_for_update(skip_locked)` — 다른 서버·Node가 가로챌 수 없다(같은 행을 못 잡고, 조건에서 이미 빠진다).
- PC는 받은 작업을 이렇게 돈다(udally-stt `link.py`):
  1. `GET …/jobs/{id}/tracks/{uid}`(디스코드) 또는 `…/jobs/{id}/audio`(올린 녹음)를 임시 폴더에 스트리밍으로 받는다.
  2. 디스코드: PyAV로 트랙을 16kHz mono로 **흘려 디코드하면서 구간(`start_ms`·`duration_ms`)에 걸린 샘플만** 남긴다(3시간 트랙을 통째로 메모리에 올리지 않는다). 1.5초 미만 구간은 뺀다(`MIN_SEGMENT_MS` 일치).
     올린 녹음: 10분 창으로 디코드 → faster-whisper 내장 VAD(`faster_whisper.vad.get_speech_timestamps`)로 말한 구간을 찾고 30초 넘으면 자른다(Node `splitBySilence`와 같은 역할, 기준값은 달라도 된다 — 화자 하나).
  3. 구간마다 기존 `run(model, audio, "ko", glossary, cancel)`을 `STT_CONCURRENCY` 스레드로 부른다(HTTP를 거치지 않는다).
     `run()`은 메모리 부족 때 `HTTPException(503)`을 던진다(`server.py:396-402`) → `link.py`가 이것(과 그 밖의 예외)을 잡아 그 구간을 `failed` 행으로 남기고 다음 구간으로 간다. 다음 구간은 `run()`이 이미 낮춘 정밀도로 돈다.
  4. 5초마다 `PATCH …/jobs/{id}` 진행 보고, 응답 `cancel: true`면 `cancel` 이벤트를 걸고(기존 `decode`가 구간마다 확인, `server.py:369-384`) `status=cancelled`.
  5. 끝나면 `rows: [{seq, user_id, start_ms, text} | {seq, user_id, start_ms, failed: true}]` + stats로 `status=done`. 임시 폴더 삭제.
- core가 `rows` → 전사문: `transcription.format_transcript(rows, names)` = Node `formatTranscript`(`transcribe.mjs:54-60`)의 Python 판(이름은 `speaker_names(rec)`, 올린 녹음은 `UPLOAD_SPEAKER`, 실패 행은 Node `texts.TRANSCRIBE_FAILED`와 같은 문구 상수). 시험 하나로 Node와 같은 출력인지 대조한다.
- PC 하나는 작업을 한 번에 하나만 한다(heartbeat `job_id`가 있으면 새 작업을 주지 않는다).

## 5. 데이터 모델 · 마이그레이션

**accounts** (`0009_alter_apitoken_scope`, AlterField choices만)
- `ApiToken.SCOPES`에 `("stt", "전사 서버")`. `max_length=5`에 들어간다.

**notes** (`0011_stt_server`, CreateModel·AddField만 — RunPython 없음)
- `SttServer`: `owner` FK User CASCADE · `name` 50 · `machine_id` 36 · `token` OneToOne ApiToken null SET_NULL · `created_at` · `last_seen_at` null ·
  `version` 20 · `device` JSON(장치·GPU 이름·RAM — 세부 정보만) · `concurrency` int 1 · `models` JSON list(heartbeat 원본) ·
  `default_model` 200 · `pull_model` 200. 제약 `unique(owner, machine_id)`. `models`·`device`는 각각 직렬화 32KB 상한(넘으면 422, 저장 안 함).
- `SttDeviceCode`: `code_hash` 64 unique · `user_code` 9 · `name` · `machine_id` · `version` · `device` JSON(32KB 상한) · `created_at` · `expires_at` ·
  `approved_by` FK User null · `denied` bool · `used_at` null. 제약 `unique(user_code) where used_at is null and denied=false`. 만료 행은 `purge_expired`(관리 명령)에 한 줄 추가로 지운다.
- `TranscriptionJob`: `server` FK SttServer null SET_NULL · `claimed_at` null(작업자가 가져간 시각 — Node·PC 공통, §7.5 requeue 기준).
  `engine` 값에 `"pc"` 추가(choices 없음, 주석만). 표시 이름은 지금처럼 `stats.label`에 생성 시점 값으로 남겨 서버를 지워도 기록이 읽힌다.

**orgs/settings.py** SPECS(마이그레이션 없음, `STT_KEYS`에 추가해 전사 메뉴에서 편집)
| 키 | 종류 | 기본 | 뜻 |
|---|---|---|---|
| `meeting.member_pc` | bool | `True` | 멤버 PC로 전사 허용. 끄면 이 조직 녹음은 PC 작업을 만들지 않고, 대기 중인 PC 작업은 다음 배정 때 취소(`pc_disabled`) |
| `meeting.transcribe_level` | choice `member`/`admin` | `member`(사용자 결정 8) | 조직 자원(조직 서버 주소·OpenAI 키)으로 전사를 지시할 수 있는 사람 |

시도 한도는 설정 칸이 아니라 고정 규칙(녹음당 1회, §8)이다. ponytail: 조직마다 다르게 하자는 요구가 생기면 그때 int 설정으로 뺀다.

## 6. API 계약

### 6.1 PC용 `core/api/routers/stt.py` → `api.add_router("/integrations/stt", stt.router)`

- 인증: device 두 개는 `auth=None`. 나머지는 `SttTokenAuth`(BotTokenAuth와 같은 꼴, scope `stt`만 통과) — 라우터 auth를 이것 하나로 둔다.
- **`TokenAuth`에 가드 추가**: `t.scope == "stt"`이고 경로가 `/api/integrations/stt/`로 시작하지 않으면 403. 이게 없으면 stt 토큰으로 다른 API를 GET할 수 있다(§1 `auth.py:28-35`).
- 오류 본문은 기존 형식(`{"detail": …}`), 사용자 문구는 `{{COPY:…}}`.

| 메서드·경로 | 요청 | 응답 | 상태 코드 |
|---|---|---|---|
| `POST /device` | `{name ≤50, machine_id uuid, version, device{} ≤32KB}` | `{device_code, user_code, verification_uri, expires_in, interval}` | 200 · 422 형식·크기 초과 |
| `POST /device/token` | `{device_code}` | `{access_token, server_id, name}` | 200 · 400 `{error: authorization_pending\|access_denied\|expired_token}` |
| `POST /heartbeat` | `{version, job_id\|null, concurrency, device{} ≤32KB, models[/v1/models 항목] ≤32KB}` | `{poll_s: 5, pull: id\|null, job: 작업\|null}` | 200 · 401 토큰 폐기(PC는 연결 끊김 처리) · 422 크기 초과 · 426 `version`이 최소 버전 미만(`{{COPY:pc_update_needed}}`) |
| `GET /jobs/{id}/tracks/{discord_user_id}` | — | `audio/ogg` 스트림 | 200 · 404 내 작업 아님·트랙 없음 · 409 작업이 running 아님 · 410 만료 |
| `GET /jobs/{id}/audio` | — | 원본 스트림 + `X-Audio-Ext` | 같음 |
| `DELETE /self` | — | `{ok: true}` | 200 · 401(스스로 끊기 = [끊기]와 같은 정리, §7.4) |
| `PATCH /jobs/{id}` | `{audio_ms, done_ms, segments_total, segments_done, segments_failed, status?: done\|failed\|cancelled, rows?, stats?, error?}` | `{status, cancel}` | 200 · 404 내 작업 아님 · 409 이미 끝남 · 413 전사문 256KB 초과 · 422 rows 형식 |

heartbeat의 `job`(PC가 가져간 작업):
```json
{"id": 41, "recording_id": 7, "model": "Systran/faster-whisper-large-v3-turbo", "source": "discord",
 "segments": [{"seq": 1, "user_id": "123", "start_ms": 0, "duration_ms": 4200}], "tracks": ["123", "456"],
 "glossary": "…", "language": "ko"}
```
- 이름(`speaker_names`)·참여자 목록은 주지 않는다(core가 조립). 조직 키·서버 주소도 당연히 없다.
- heartbeat 처리 순서: ① 토큰→서버 ② `last_seen_at`·models 저장(바뀌었거나 10초 지났을 때만), `pull_model`이 models에서 `ready`면 `default_model`로 옮김 ③ 내 running 작업이 있는데 `job_id`가 다르면 되돌림(§7.5) ④ `job_id`가 없으면 `claim_for(server)`.
- PATCH: `report()` 재사용. 단 `engine`·`model`은 받지 않는다(PC가 수단을 바꿀 수 없다). `rows`가 오면 `format_transcript` 결과를 `transcript_md`로 넘긴다. rows 상한 = `MAX_SEGMENTS`(20000), 행 text 2,000자.
- 내려받기 검사(둘 다): `job.server == 토큰의 서버` · `job.status in RUNNING` · `job.claimed_at` 있음 · `get_visible_note(server.owner, note_id)`가 지금도 있음 · `audio_expired(rec)` 아님 · 트랙 uid가 그 녹음 트랙. 하나라도 아니면 404(존재를 숨긴다).

### 6.2 웹

| URL | 권한 | 내용 |
|---|---|---|
| `GET/POST /link` | 로그인 | 코드 입력(빈 칸, 주소로 채우지 않음)·확인 화면, [허용] [거절]. 허용 시 서버 이름 확정 + 소유자 알림 |
| `GET /stt/<install\|uninstall>.<ps1\|sh>` | 없음(공개) | GitHub raw(커밋 sha 고정)로 302 — §10.1 |
| `GET /settings/stt` | 본인 | 내 전사 서버: 연결 명령 안내(Docker·uv 탭), 서버 목록(이름·켜짐/꺼짐·마지막 응답·준비된 모델), 모델 select + [모델 적용], [끊기] |
| `POST /settings/stt/<id>/pull` | 서버 주인 | `pull_model` 저장, HTMX 조각 반환(받는 중 3초 폴링) |
| `POST /settings/stt/<id>/unlink` | 서버 주인 | §3 폐기 |
| `/orgs/<id>/transcribe` | **구성원**으로 넓힘 | "전사 작업" 보기 = `visible_notes(user)` 안의 녹음만. "전사 서버" 보기(조직 서버 주소·키·정책)는 관리자만, 멤버에게는 보기 전환을 숨김 |
| 패널·진행·다시 전사·취소·지정 | §8 표 | 관리자 검사를 §8 함수로 바꾼다 |

`/settings/tokens` 목록에서는 `scope="stt"`를 뺀다(전사 서버 화면에서 관리).

## 7. 배정 · 오프라인 · 취소 · Discord 자동 전사

### 7.1 켜짐 판정
- `online(server) = last_seen_at > now − 15초`. 화면 "꺼져 있음"은 이 값.
- `gone(server) = last_seen_at < now − 2분`(재부팅·잠깐 끊김을 견디는 여유) — 자동 작업을 넘기는 기준.

### 7.2 다시 전사·올린 녹음 전사(사람이 고름)
- 선택지 값 `pc|<server_id>|<model>`. `request_retry`/`request_upload`가 `engine="pc"`, `server`, `model`로 queued 작업을 만든다(`_enqueue` 재사용, 조직 수단 검사 대신 §8 PC 검사).
- PC가 꺼져 있으면 선택 불가(화면). 고른 뒤 꺼지면 작업은 **그 PC를 기다린다**(사람이 그 PC를 골랐으므로). 화면 `{{COPY:job_waiting_pc}}`, [대기 취소] 가능. 24시간 지나면 다음 배정 점검 때 `cancelled`(`error="pc_offline"`).

### 7.3 Discord 자동 전사(Node 변경 없음)
1. 종료 PATCH(`transcribing`) → `start_auto_job(rec)`: 진행자(`rec.host`)의 서버 중 `online`이고 `default_model`이 `ready`인 것이 있고, `meeting.member_pc`가 켜져 있고, `audio_keep_days > 0`(0이면 Node가 지운 뒤 PC가 받을 수 없다)이면 →
   `kind=auto, engine="pc", server=S, model=S.default_model, status="queued", requested_by=host`. 아니면 지금처럼 `running`(Node 즉시 전사).
   서버가 여러 대면 마지막 응답이 가장 최근인 것.
2. `_recording_out.job_id`는 running 자동 작업만 보므로 null → Node는 진행 보고를 하지 않는다.
3. Node `transcribe()`가 `GET /meetings/{id}/names`를 부를 때, 활성 PC 자동 작업이 있으면 core가 `stt`를 **빈 값**으로 주고 그 작업 `stats.stt_withheld = true`를 남긴다 → Node는 즉시 빈 전사문의 draft PATCH(segments 포함, `stats.engine="none"`).
4. draft PATCH → `finish_auto_job`이 **자동 작업을 닫는 유일한 자리**다(개정 1). 경우:
   - running 자동 작업(Node가 즉시 전사) → 지금처럼 닫는다.
   - queued PC 자동 작업이 살아 있음 → `audio_ms`·`segments_total`을 `rec.segments`로 채우고 PC를 기다린다. 알림은 "녹음만" 대신 `{{COPY:draft_pc_transcribing}}`. 말한 구간이 없으면 바로 `done`(빈 전사문).
   - PC 자동 작업이 transcribing 중에 취소됐고(아래 6-가) `stt_withheld`였다(= Node가 빈 stt로 전사를 건너뜀) → 조직 수단 queued 작업을 새로 만들어 Node `claim`에 맡긴다(조직 수단이 없으면 `failed(no_engine)`). 취소 전에 Node가 이미 조직 stt를 받았다면(`stt_withheld` 아님) Node 결과가 곧 전사이므로 그 결과로 `done` 자동 작업 한 건을 기록만 한다.
   - 어느 경우든 같은 녹음에 자동 작업이 두 번 돌지 않는다(이중 전사 없음).
5. PC가 heartbeat로 가져가 §4대로 전사 → `done`이면 `_finish`가 현재 전사문으로 지정(회의록 본문은 그대로).
6. **PC가 꺼지면**(`gone`). 점검은 **Node `claim()`과 PC heartbeat 시작부**에서 게으르게 한다(core에 백그라운드 실행기가 없다 — `IMPL-PLAN-10 §1`).
   - 가. `rec.status == "transcribing"`(draft 전): **넘기지 않는다.** PC 작업을 `cancelled(pc_offline)`로 끝내고 Node 기본 경로에 맡긴다 — names를 아직 안 불렀으면 Node가 조직 stt로 바로 전사하고, 이미 빈 stt를 받았으면 4의 세 번째 경우가 받는다. (draft 전에 queued로 넘기면 Node 즉시 전사와 claim 전사가 겹친다.)
   - 나. `rec.status in (draft, done)`: queued이거나 running인 PC 자동 작업을 `server=None`, `engine/model = _org_engine(org)`, 진행 0으로 **§7.6 `requeue_or_cancel`**에 넘긴다 → Node가 다음 `claim`(20초 주기)에서 기존 `runRetry` 경로로 트랙을 받아 전사. 조직 수단도 없으면 `failed(no_engine)`.
   - 넘긴 작업은 조직 자원 시도 한도에 세지 않는다(§8).

### 7.4 취소
- 화면 취소 = 기존 `cancel()`: queued면 바로 `cancelled`, running이면 `cancelling` → PC 진행 PATCH 응답 `cancel: true` → PC가 끊고 `cancelled` 보고. 지연은 구간 하나 + 5초.
- PC가 응답이 없으면(`gone`) 취소는 기다리지 않고 바로 끝낸다(기존 `is_stale` 분기에 `engine=="pc" and gone(server)` 추가).
- [끊기]: 그 서버의 queued 작업 `cancelled(pc_unlinked)`, running 자동 작업은 §7.3-6과 같은 규칙(transcribing이면 취소, 아니면 `requeue_or_cancel`로 조직 수단에 넘김), running 다시 전사는 `cancelled`.

### 7.5 재시작·되돌리기
- `claim()`·`claim_for()`가 `claimed_at`을 찍는다.
- Node `requeue()`: `server is null and claimed_at not null and status in RUNNING`(kind 무관)로 바꾼다 → 넘겨받은 자동 작업·올린 녹음 작업도 되돌려진다(§1의 기존 빈틈 해소). 되돌리기는 §7.6 함수로.
- PC: heartbeat `job_id`가 비었는데 core에 그 서버의 running 작업이 있으면(= PC 재시작) §7.6 함수로 되돌림 → 같은 heartbeat에서 다시 배정. 중간 결과 재개는 하지 않는다(ponytail: 긴 회의에서 아까우면 rows를 부분 보고로 쌓는다).

### 7.6 queued 되돌리기 규칙(개정 1, `uniq_transcription_queued` 보호)
- 녹음당 queued는 하나뿐이다(`core/notes/models.py:167-171`). 그런데 running 작업에 사람이 다시 전사를 걸면 running은 `cancelling`, 새 작업은 `queued`가 된다(`transcription.py:357-359`). 이 상태에서 넘기기·재시작 되돌리기가 running/cancelling을 queued로 바꾸면 IntegrityError다.
- 그래서 running → queued로 바꾸는 **모든 경로**(§7.3-6-나 gone 넘기기, §7.4 [끊기], §7.5 Node `requeue()`·PC 재시작 되돌리기)는 함수 하나 `requeue_or_cancel(job, **바꿀 칸)`만 쓴다:
  `job.status == "cancelling"` **또는** 같은 녹음에 다른 `queued` 작업이 있으면 → `_finish(job, "cancelled")`; 아니면 → 칸을 바꾸고 진행 0, `queued`.
  지금 `requeue()`의 분기(`transcription.py:287`)를 이 함수로 옮긴 것이다. `select_for_update`로 녹음 행을 먼저 잠근다(`request_retry`와 같은 순서 — `transcription.py:317`).

## 8. 권한 · 한도

| 행동 | 조직 자원(local·openai) | 내 PC(pc) |
|---|---|---|
| 작업 목록·패널 보기 | 구성원, `visible_notes(user)` 안의 녹음만 | 같음 |
| 다시 전사·올린 녹음 전사 지시 | `can_use_org_stt(user, org)` = 관리자 또는 `transcribe_level == "member"` · 한도 안 | 서버 주인 = 지시자 · `member_pc` 켜짐 · 그 녹음이 `visible_notes(owner)` 안 |
| 시도 한도 | **녹음당 1회, 관리자 예외**(사용자 결정 9). 셈 = 그 녹음의 `engine in (local, openai)` 작업 중 `kind != auto`, `stats.handoff` 아님(PC에서 넘겨받은 작업), "시작 전 취소"(`cancelled` + `claimed_at` null) 아님인 것. 1건이라도 있으면 **누가 지시했든** 멤버는 그 녹음을 조직 수단으로 다시 전사할 수 없다. 자동 전사는 "다른 사람이 전사한 것"으로 치지 않는다 → 자동 전사만 있었던 녹음은 멤버가 조직 수단으로 한 번 다시 전사할 수 있다 | 없음(무제한) |
| 취소 | 관리자 · 요청자 | 관리자 · 서버 주인 |
| [현재 전사문으로 지정] | 관리자 · 회의록 편집 권한(`_check_edit`) | 같음 |
| 전사 서버 보기(조직 주소·키·정책) | 관리자만(지금 그대로) | — |
| 내 서버 연결·모델 적용·끊기 | — | 본인만 |

- 서비스 함수 하나 `transcription.check_request(rec, actor, engine, server)`에 모은다(웹·노트 화면이 같이 부른다). 지금의 `require_admin`(`transcription.py:318`)과 `_check_edit`(`:329`) 자리를 이것으로 바꾼다.
- 넘기기(§7.3-6-나)가 만든 작업에는 `stats.handoff = true`를 남겨 위 셈에서 뺀다.
- `meeting.member_pc`를 끄면: 선택지에서 PC가 사라지고(`{{COPY:pc_disabled_by_org}}`), 대기 PC 작업은 다음 배정 때 `cancelled(pc_disabled)`, 진행 중인 것은 끝까지 둔다.

## 9. 화면

DESIGN.md 부품만 쓴다(`.conn-state`, `details.fold`, `.empty`, 패널). 별도 시안은 만들지 않고 기존 시안 B(작업 목록 + 패널, IMPL-PLAN-10 §2) 안에 넣는다(사용자 결정 11).

### 9.1 선택지 표시(전사 패널·회의록 [전사 시작])
- 내 PC의 ready·fits 모델: `{{COPY:pc_model_label|server_name, model_name}}` — 예시 형태 "내 PC · OpenAI Whisper large-v3-turbo". `model_name`은 기존 `model_name(id, info)`(display_name 우선, `transcription.py:37-47`) — id로 추정하지 않는다. udally-stt `meta()`가 `"OpenAI Whisper large-v3-turbo"`를 이미 준다(`server.py:188-198`). 서버 여러 대면 서버 이름을 넣는다.
- 꺼진 서버: 한 줄 disabled `{{COPY:pc_offline_option|server_name}}`("꺼져 있음").
- 조직 수단: 지금 그대로(`… · 로컬 서버`, `OpenAI Whisper(whisper-1) · OpenAI API`). 권한이 없으면 disabled + `{{COPY:org_stt_no_permission}}`, 이미 조직 수단으로 전사된 녹음이면(멤버) disabled + `{{COPY:org_stt_already_used}}`.
- 전사문 ≠ 회의록: 패널의 [다시 전사] 근처 설명은 기존 문구 유지(바꾸지 않는다).

### 9.2 새 화면
- `/link`: 빈 코드 입력칸(주소로 채우지 않음, §3 피싱 대비) → 확인 카드(기기 이름 입력·장치 요약·`{{COPY:link_consent}}`) → [허용] [거절] → 결과 `{{COPY:link_done}}`/`{{COPY:link_denied}}`/`{{COPY:link_expired}}`.
- `/settings/stt`("내 PC 연결"): 빈 상태 `.empty` + **OS별 한 줄 설치 명령**(§10.1, Windows·macOS/Linux 탭, 복사 버튼, `{{COPY:install_windows_help}}`·`{{COPY:install_unix_help}}`·`{{COPY:install_uninstall_help}}`) + 고급(Docker·uv 직접 명령) 접힘 / 서버 행: 이름 · `.conn-state on|off` · 마지막 응답 · 모델 select + [모델 적용] · 세부 정보 접힘(장치·정밀도·버전) · [끊기](확인 대화상자 `{{COPY:unlink_confirm}}`).
- 전사 메뉴 "전사 서버" 보기(관리자): 고급 설정 접힘 안에 기존 주소·모델·키 칸(결정 6) + 정책 2칸(§5) + "멤버 PC 연결 N대 켜짐" 한 줄.
- 작업 행 수단 표시: PC 작업은 `{{COPY:job_runner_pc|owner_name, server_name}}`(관리자에게 누구 PC인지 보이게).

### 9.3 문구 자리표시 목록(Sol)
`connect_prompt` · `connect_waiting` · `connect_ok` · `pc_unlinked` · `pc_update_needed` · `pc_model_label` · `pc_offline_option` · `pc_disabled_by_org` ·
`org_stt_no_permission` · `org_stt_already_used` · `link_approved_notice` · `install_windows_help` · `install_unix_help` · `install_uninstall_help` · `install_*`(스크립트 출력 문구) · `job_waiting_pc` · `job_runner_pc` · `draft_pc_transcribing` · `link_title` · `link_code_help` · `link_consent` ·
`link_done` · `link_denied` · `link_expired` · `link_too_many`(코드 확인 실패 잠금) · `settings_stt_title` · `settings_stt_empty` · `unlink_confirm` · `pull_started` · `pull_not_fits` ·
`setting_member_pc_label/help` · `setting_transcribe_level_label/help` · 오류 코드 표시 `pc_offline` · `pc_disabled` · `pc_unlinked` · `no_access`.
금지어 grep 대상: "large-turbo"(계열 없는 모델명), "회의록을 다시 전사"(전사문≠회의록).

## 10. udally-stt

- **새 파일 `link.py`**(server.py 옆, 같은 PEP 723 의존성 + `httpx` 대신 표준 `urllib.request` — 의존성 추가 없음). `server.py`에 하위 명령 한 줄: `python server.py connect` → `link.main()`. 기존 `uv run server.py`(HTTP 서버)는 그대로 = 고급 설정의 "서버 주소 직접 입력" 경로.
- `connect` 모드는 **HTTP 포트를 열지 않는다**(들어오는 연결 없음). `server.py`의 `status_of`·`start_download` 로직·`run()`·`load()`를 함수로 불러 쓴다(`start_download`의 본문을 `pull(model_id) -> (status, item)` 함수로 떼고 HTTP 핸들러는 그것을 부르게 한다).
- 배포 전제(사용자 결정 10): udally-stt를 **GitHub 공개 저장소** + **GHCR 공개 이미지**(`ghcr.io/<계정>/udally-stt:<버전>-cpu|-cuda`, 계정·저장소 이름은 미정 → §14)로 낸다. 라이선스 검토(프리셋 모델 라이선스 표, `README.md`) 통과가 먼저다. 저장소에 태그(`v0.x.y`)를 달면 GitHub Actions가 이미지 두 개를 빌드·푸시하고 digest를 릴리스 노트에 적는다(새 파일 `.github/workflows/release.yml`).
- 패키지화: `uv tool install`이 되도록 `pyproject.toml`을 더한다(`[project.scripts] udally-stt = "server:cli"`, 의존성은 PEP 723 머리와 같은 목록 — 한 곳만 고치도록 `test_plan.py`에서 두 목록 일치를 assert). `cli()`: 인자 없으면 기존 HTTP 서버, `connect`면 link 모드.
- 사람이 치는 명령은 §10.1 한 줄 설치가 기본이다. 직접 명령(고급, README·화면 접힘):
  - uv: `uv tool install --force git+https://github.com/<계정>/udally-stt@v0.x.y` → `udally-stt connect`. 주소는 `UDALLY_URL`(기본 `https://udally.sio2.kr`).
  - Docker(CPU): `docker run -it --restart unless-stopped --name udally-stt -v udally-stt:/cache ghcr.io/<계정>/udally-stt:v0.x.y-cpu connect`
  - Docker(GPU): 위에 `--gpus all`, 태그 `-cuda`. 코드가 터미널에 뜨고, 승인 뒤 그대로 돈다. compose 사용자는 `compose.link.yaml`(`command: ["python", "server.py", "connect"]`).
- 토큰 보관: `STT_LINK_FILE`, 기본 Docker `/cache/udally-link.json`(모델 볼륨에 같이 — 컨테이너를 지워도 남는다), uv는 Windows `%APPDATA%\udally-stt\link.json`, 그 외 `~/.config/udally-stt/link.json`. 내용 `{url, server_id, machine_id, token}`. POSIX는 0600으로 만든다. 로그에 토큰을 찍지 않는다(앞 12자 prefix만).
- 재연결: 네트워크 오류·5xx는 2·4·8…60초 백오프 + 지터, 성공하면 5초(서버 `poll_s`)로 복귀. 401이면 토큰 파일 삭제 후 종료 코드 3(Docker `unless-stopped`가 다시 띄우면 새 코드를 보여 준다 = 다시 연결 흐름). 426이면 업데이트 안내 후 종료.
- 작업 중 끊김: 진행 PATCH가 실패해도 전사는 계속하고 마지막 결과 보고만 백오프로 재시도(최대 10분). 그 사이 core가 `gone`으로 넘겼으면 결과 PATCH가 404/409 → 버린다.
- heartbeat `models`는 `list_models()`의 `data` 그대로(IMPL-PLAN-10 §10 계약 유지 — 새 필드 없음). `concurrency = STT_CONCURRENCY`, `device = {gpus, ram_free_mb}` 요약.
- 모델 미준비(`status != ready`)인 작업이 오면 바로 `failed(error="model_not_ready")` — 받기는 [모델 적용]만 시작한다(지금 409 규칙과 같음).
- 메모리 부족: `run()`의 `HTTPException(503)`을 구간 `failed`로 바꿔 보고한다(§4-3). 작업 전체를 실패시키지 않는다.
- 시험(`test_link.py`, assert 기반 하나): 503을 던지는 가짜 `run`으로 해당 구간만 failed인지, 구간 슬라이스(흘려 디코드한 결과 길이 = 구간 길이 ±20ms, `samples/` 파일 사용), heartbeat 응답 해석(pull·job·401), 토큰 파일 저장·삭제.

### 10.1 한 줄 설치(개정 1 추가)

사람이 치는 명령은 OS별 한 줄이다.
- Windows(PowerShell 5.1·7): `irm https://udally.sio2.kr/stt/install.ps1 | iex`
- macOS·Linux: `curl -fsSL https://udally.sio2.kr/stt/install.sh | sh`
- 제거: `irm https://udally.sio2.kr/stt/uninstall.ps1 | iex` / `curl -fsSL https://udally.sio2.kr/stt/uninstall.sh | sh`

**주소 결정: 유달리 주소 + core는 302만 한다**
| 안 | 장점 | 단점 |
|---|---|---|
| core 정적 파일(`static/`에 사본) | 유달리 주소 | 스크립트가 두 저장소에 생긴다(사본 동기화), 바꿀 때마다 core 배포 |
| GitHub raw 직접 | 원본 하나 | 주소가 길고 계정·저장소 이름이 화면·문서에 박힌다(이름이 미정 — §14) |
| **core가 GitHub raw로 302(채택)** | 안내는 유달리 주소 하나, 원본은 udally-stt 저장소 하나(버전 관리), 계정 이름을 바꿔도 화면·문서는 그대로 | core 뷰 1개 |
- core: `GET /stt/<install|uninstall>.<ps1|sh>` → 302 `https://raw.githubusercontent.com/<계정>/udally-stt/<커밋 sha>/scripts/<파일>`. 로그인 불필요. 커밋 sha는 core 설정 상수 `STT_RELEASE = {"version", "commit"}`(환경변수로 덮을 수 있음) — 태그는 옮길 수 있어 **커밋 sha로 고정**한다. `irm`·`curl -L`(`-fsSL`에 포함) 모두 리다이렉트를 따른다. 두 단계 모두 HTTPS.
- 업데이트는 udally-stt 릴리스 → core `STT_RELEASE` 한 줄 변경 → 배포 순서로 한다(지금 안내되는 스크립트가 무엇인지 core가 정한다).

**스크립트 동작**(`scripts/install.ps1`·`scripts/install.sh`, udally-stt 저장소. 둘 다 사람 입력을 받지 않는다 — `| sh`는 표준 입력이 스크립트라 물을 수 없다)
1. 스크립트 머리에 릴리스 값이 박혀 있다: 버전, 커밋 sha, 이미지 digest 두 개(cpu·cuda). 릴리스 워크플로가 채운다.
2. **Docker 경로**(`docker info`가 성공하면):
   - GPU 판별: `nvidia-smi`가 있고 `docker run --rm --gpus all busybox true`가 성공하면 cuda, 아니면 cpu(작은 이미지로 `--gpus` 가능 여부만 본다).
   - `docker pull ghcr.io/<계정>/udally-stt@sha256:<digest>`(**digest 고정** = 무결성) → 기존 `udally-stt` 컨테이너가 있으면 지우고 같은 볼륨으로 다시 만든다:
     `docker run -d --name udally-stt --restart unless-stopped -v udally-stt:/cache [--gpus all] <이미지@digest> connect`
   - 토큰은 볼륨(`/cache/udally-link.json`)에 있으므로 **다시 실행 = 업데이트**이고 다시 연결하지 않는다.
   - 아직 연결 전이면 `docker logs -f`를 보며 기기 인증 주소·코드를 그대로 보여 주고, 연결 완료 줄이 나오면 끝낸다(`{{COPY:install_done}}`).
   - Linux에서 docker 권한이 없으면(docker 그룹 아님) sudo를 쓰지 않고 uv 경로로 간다.
3. **uv 경로**(Docker가 없을 때):
   - uv가 없으면 버전 고정 공식 설치 스크립트로 사용자 영역에 설치(`https://astral.sh/uv/<버전>/install.ps1|.sh` — 관리자 권한 불필요).
   - `uv tool install --force --python 3.12 "udally-stt[cuda] @ git+https://github.com/<계정>/udally-stt@<커밋 sha>"`(`nvidia-smi`가 있으면 `[cuda]` = cuBLAS·cuDNN 휠, Dockerfile GPU 단계와 같은 목록). 커밋 sha 고정. 다시 실행하면 `--force`로 덮어쓴다 = 업데이트.
   - `udally-stt connect --until-linked`(연결 전이면 주소·코드 표시 → 승인 뒤 토큰 저장하고 끝남, 이미 연결됐으면 바로 끝남).
   - 자동 시작(사용자 영역, 관리자 불필요): Windows는 시작프로그램 폴더 바로가기(`udally-stt connect`, 최소화 창), Linux는 `systemd --user` 단위, macOS는 `~/Library/LaunchAgents` plist. 등록 뒤 지금 바로 한 번 띄운다.
4. 제거(`uninstall`): ① 연결돼 있으면 PC 토큰으로 `DELETE /api/integrations/stt/self`(스스로 끊기 — §6.1 추가) ② Docker면 컨테이너 삭제(모델 볼륨은 남기고 지우는 명령을 안내 `{{COPY:install_volume_hint}}`), uv면 `uv tool uninstall udally-stt` + 자동 시작 항목 삭제 + 토큰 파일 삭제.

**보안**
- HTTPS 고정: 스크립트 안 모든 주소는 `https://` 상수, http로 내려가는 리다이렉트를 따르지 않는다(PowerShell은 `-MaximumRedirection` 기본, curl은 `--proto '=https'`).
- 원본은 udally-stt 저장소에서 리뷰·태그로 관리, core는 커밋 sha만 가리킨다. 이미지는 digest, uv 설치는 커밋 sha, uv 자체는 버전 고정 → 같은 한 줄이 언제나 같은 내용을 설치한다.
- 관리자 권한 요구 없음(Docker 경로는 Docker가 이미 있을 때만, uv 경로는 사용자 영역). 스크립트는 sudo·UAC 승격을 하지 않는다.
- 스크립트는 토큰을 출력하지 않는다. 받은 파일·실행 내용은 README에 "실행 전 읽어 보기" 주소(`/stt/install.ps1`을 브라우저로 열면 원본이 보임)로 안내.
- ponytail: 스크립트 서명(Authenticode·minisign)은 하지 않는다 — 배포가 넓어지면 그때.

## 11. 보안

- **다른 사람 녹음 차단**: 작업은 `server.owner`가 볼 수 있는 녹음에서만 만들고(지시 때), 가져갈 때(`claim_for`)와 내려받을 때마다 `get_visible_note(owner, …)`를 다시 본다(그 사이 조직에서 빠졌거나 공개 범위가 바뀌면 `failed(no_access)`/404). 내려받기 URL은 작업 id 기준이고 `job.server == 토큰 서버`일 때만 열린다 — 녹음 id를 바꿔 넣어도 소용없다.
- **기기 인증 피싱**: 코드 자동 채움 주소가 없고 사람이 PC 화면의 코드를 직접 입력, 허용 직후 소유자 알림(§3).
- **토큰 범위**: scope `stt`는 `/api/integrations/stt/*` 밖에서 401/403(TokenAuth 가드 + 라우터 auth 고정, 두 겹). `for_ai=False`. 만료 없음, 폐기는 [끊기]·재연결·탈퇴. 다른 서버 작업 PATCH는 404.
- **PC가 줄 수 있는 것만 받는다**: 진행 숫자·rows·stats(세부 정보, 32KB 상한)·error 코드(목록 밖이면 `pc_error`). engine·model·전사문 원문 직접 지정은 받지 않는다. rows의 `user_id`가 작업 segments에 없는 값이면 버린다.
- **PC에 주는 것 최소화**: 오디오·구간·용어집만. 이름·참여자·조직 키·서버 주소는 주지 않는다. 받은 오디오는 작업이 끝나면 지운다(udally-stt).
- **남용 한도**: 기기 코드(§3, 확인 실패 잠금 + 대기 코드 200개 넘으면 가장 오래된 것부터 밀어내기), heartbeat `models`·`device` 각 32KB 상한, 사람당 서버 5대, PC당 동시 작업 1, heartbeat는 1초보다 잦으면 응답만 하고 저장 안 함(쓰기 폭주 방지). 조직 자원은 §8 한도. PC 작업 자체는 한도 없음(사용자 결정) — 대신 녹음당 활성 작업 1개 제약(기존 부분 유니크)이 그대로 걸린다.
- SSRF 걱정이 줄어든다: core가 PC로 나가는 연결이 없다.
- 감사: 연결·끊기·[모델 적용]은 기존 조직 활동 기록 대상 아님(개인 자원). 전사 작업 기록에 `requested_by`·`server`·`stats.label`이 남는다.

## 12. 구현 갈래 · 파일 · 시험 · 배포 순서

계약(§6.1 표 + §4 rows 형식 + heartbeat `job`)을 먼저 확정하면 core와 udally-stt는 **병렬**로 간다. Node는 **갈래 없음**(§7.3 — core만으로 경로를 바꾼다).

| 갈래 | 파일 | 하는 일 |
|---|---|---|
| C1 core 모델·API | `core/accounts/models.py`(SCOPES), `accounts/migrations/0009_*`, `core/notes/models.py`(SttServer·SttDeviceCode·Job 칸), `notes/migrations/0011_*`, 새 `core/notes/stt_link.py`(기기 인증·heartbeat·배정·넘기기), `core/notes/transcription.py`(claim 필터·claim_for·requeue·start/finish_auto_job·format_transcript·check_request·is_stale), `core/notes/services.py`(draft 알림 분기), `core/api/auth.py`(stt 가드·SttTokenAuth), 새 `core/api/routers/stt.py`, `core/api/api.py`(add_router), `core/api/schemas.py`, `core/api/routers/discord.py`(names의 stt 비우기), `core/orgs/settings.py`(SPECS 2개·STT_KEYS), `core/ops/management/commands/purge_expired.py`(만료 코드) |
| C2 core 웹 | `core/web/urls.py`, 새 `core/web/views/stt_link.py`(/link, /settings/stt), `core/web/views/transcribe.py`(권한·PC 선택지·멤버 보기), `core/web/views/orgs.py`(`parse_models` 분리), `core/web/views/notes.py`([전사 시작] 선택지), `core/web/views/settings.py`(토큰 목록에서 stt 제외), 새 `core/web/views/stt_install.py`(`/stt/*.ps1|sh` → GitHub raw 302, `STT_RELEASE` 상수는 `core/config/settings.py`), 템플릿 `orgs/_tabs.html`·`orgs/transcribe.html`·`orgs/_transcribe_panel.html`·`notes/…`(전사 시작)·새 `accounts/link.html`·`settings/stt.html`·`settings/_stt_server.html`, `static/app.css`(필요 시), `DESIGN.md`(표 한 줄) |
| U udally-stt | `server.py`(connect 하위 명령·`cli()`, `pull()` 분리), 새 `link.py`, 새 `test_link.py`, 새 `pyproject.toml`(uv tool·`[cuda]` 추가 의존성), `test_plan.py`(의존성 목록 일치 assert), 새 `compose.link.yaml`, 새 `scripts/install.ps1`·`install.sh`·`uninstall.ps1`·`uninstall.sh`, 새 `.github/workflows/release.yml`(이미지 빌드·푸시, digest·커밋 sha를 스크립트 머리에 채움), `LICENSE`, `README.md`(한 줄 설치·고급 명령·라이선스 표) |

- C1 → C2 순서(C2는 C1의 서비스 함수에 기댄다). U는 계약 확정 뒤 C1과 동시에. C1과 U가 같은 파일을 쓰지 않는다.
- 충돌 주의: `transcription.py`·`discord.py`는 화자 분리 계획(`docs/PLAN-diarization.md`)과 겹친다 — 그쪽 진행 여부를 확인하고 한쪽 뒤에.

**시험**
- core(pytest, `core/notes/test_stt_link.py` 하나 + 기존 `test_transcription.py` 보강):
  기기 인증 전 상태(pending/denied/expired/1회 발급/재연결 시 이전 토큰 폐기/서버 5대 상한/코드 실패 잠금/대기 코드 200개 밀어내기/`/link?code=`가 칸을 채우지 않음/허용 시 소유자 알림) · heartbeat 32KB 초과 → 422 · `DELETE /self` ·
  stt 토큰으로 `/api/tasks` GET·`/api/integrations/discord/*` → 403 · 다른 서버 작업 내려받기·PATCH → 404 · 볼 수 없는 녹음 → 404/`no_access` ·
  Node `claim()`이 PC 작업을 안 가져감 · `claim_for` 동시 두 번 → 하나만 · 녹음 draft 전엔 PC가 못 가져감 · segments 화자 중 트랙이 하나라도 없으면 못 가져감 ·
  `uniq_transcription_queued`: running PC 작업에 다시 전사(→ cancelling + queued) 뒤 gone 넘기기·PC 재시작·Node requeue·[끊기] 각각에서 IntegrityError 없이 cancelled ·
  transcribing 중 gone → PC 작업 cancelled, names 전이면 Node 즉시 전사 1회 / names 뒤면 draft 때 조직 수단 queued 1건(어느 쪽이든 전사 1회) ·
  자동 전사: 진행자 PC 켜짐 → names `stt` 빔 → draft 뒤 PC 배정 / PC 꺼짐 → 기존 즉시 전사 / 배정 뒤 2분 끊김 → 조직 수단으로 넘어가 Node claim / 조직 수단도 없음 → `no_engine` · 보관 0일 → PC로 안 보냄 ·
  취소(queued·running·gone) · requeue가 upload·넘겨받은 작업까지 되돌림 · PC 재시작 되돌림 ·
  권한 표(§8) 행마다 1건 · 한도 셈(녹음당 1회, 다른 사람이 조직 수단으로 한 뒤 멤버 거절, 관리자 통과, auto·넘겨받은 작업·시작 전 취소 제외, 자동 전사만 있던 녹음은 멤버 1회 허용) · `/stt/install.ps1` 302 위치가 `STT_RELEASE` 커밋 sha · `member_pc` 끄기 · `format_transcript`가 Node `formatTranscript` 고정 예시와 같은 출력.
- Node: 변경 없음 → 기존 `node --test` 그대로 통과만 확인.
- 한 줄 설치: Windows PowerShell 5.1과 7 각각 × (Docker 있음 / 없음) — 첫 설치·다시 실행(업데이트, 다시 연결 안 함)·제거. Linux `sh`(dash)는 Docker 없는 ubuntu 컨테이너에서 uv 경로·`systemd --user` 등록 확인(컨테이너에 systemd가 없으면 등록 건너뜀 메시지), Docker 있는 Linux PC에서 cpu·cuda 판별. 정적 검사 PSScriptAnalyzer·shellcheck. macOS는 실기 없음 → §15.
- udally-stt: `test_link.py` + 실제 PC로 운영 대상 끝까지 1회(연결 → 모델 적용 → 올린 녹음 전사 → Discord 회의 자동 전사 → PC 끄기 → 넘기기).
- Postgres 임시 DB에 migrate(데이터 있는 상태, 메모: RunPython은 없지만 부분 유니크 제약 생성 확인). ruff. 화면 390·1440 라이트·다크(/link, /settings/stt, 패널 선택지).

**배포 순서**
1. core(C1+C2) 배포 — PC가 하나도 없으면 동작이 지금과 같다(`start_auto_job`이 PC를 못 찾음, 선택지에 PC 없음). 새 설정 기본값 `member_pc=True`라도 연결된 PC가 없으면 영향 없음.
0. (선행) udally-stt 라이선스 검토 → GitHub 공개 저장소 생성 → 첫 태그 릴리스로 GHCR 이미지·digest 확보.
2. core `STT_RELEASE`를 첫 릴리스 커밋으로 맞춰 배포 → 사용자 PC에서 한 줄 설치로 연결·끝까지 시험(운영 = 최종 시험 서버).
3. 플래그 없이 바로 전체 공개(사용자 결정 10).
4. 확인 뒤 §13 정리.

## 13. 정리 대상(사용자 승인 뒤)

- `compose.yml:148-155` frps 서비스(커밋 `99c0e84`) 삭제 — 되돌리기 커밋 하나.
- 서버 `.env`의 `FRP_TOKEN` 줄, NPM의 `stt.sio2.kr` 프록시 호스트·`/~!frp` 위치 설정.
- 임시 ssh 터널, 서버 `/root/stt-fwd.py`.
- 조직 설정 `meeting.stt_url`이 frps 주소(`stt.sio2.kr`)를 가리키고 있으면 비우거나 내 PC 연결로 바꾸기(사용자 판단).

## 14. 열린 질문(사용자가 정할 것)

개정 1에서 닫힌 것: 전사 권한 기본값(멤버 누구나) · 시도 한도(녹음당 1회, 관리자 예외) · 관리자 예외 · 이미지 배포처(GitHub 공개 + GHCR 공개) · 공개 방식(플래그 없이 전체 공개) · 화면 시안(시안 B 안에 추가) · 자동 전사 PC 모델(마지막 [모델 적용]) · 넘김 대기 2분.

남은 것:
1. **GitHub 계정·저장소 이름**(GHCR 이미지 이름이 같이 정해진다). 예: `<계정>/udally-stt`.
2. **라이선스 검토 결과**와 udally-stt 저장소 라이선스(공개의 선행 조건, 프리셋 모델 라이선스 표 포함).

## 15. 확인 불가 · 위험

- udally-stt의 `RESUME.md`는 이 저장소에 없다(지시문에 언급) — 내용 확인 불가.
- PyAV 흘려 디코드로 구간 경계 정확도(±20ms 가정)와 Nemotron 경로(`server.py:300-323`, 별도 디코더)에서의 동작 — 실측 필요.
- 운영 NPM이 `/api/integrations/stt/*`의 긴 내려받기(수백 MB 올린 녹음)를 끊는 시간 제한 — 기존 Node 내려받기와 같은 경로라 같을 것으로 보지만 확인 불가.
- heartbeat 쓰기 부하는 서버 수십 대까지 문제없다고 추정(5초 주기, 10초 쓰기 생략). 실측 없음.
- 화자 분리 계획과 `transcription.py`·자동 전사 흐름이 겹친다 — 그쪽 진행 상태 확인 불가.
- 한 줄 설치: macOS 실기 시험 불가(LaunchAgent 동작 미확인). 오래된 Windows의 PowerShell 5.1이 TLS 1.2를 기본으로 쓰지 않으면 `irm`이 실패할 수 있다 — Windows 10 최신·11은 시스템 기본이 TLS 1.2라 문제없다고 추정, 실패 시 README에 한 줄 대체 명령. Windows의 uv 경로 `[cuda]`(cuBLAS·cuDNN 휠)로 faster-whisper GPU가 도는지 실측 필요. Docker Desktop(Windows)에서 `--gpus all busybox` 판별이 NVIDIA WSL 드라이버에서 맞게 동작하는지 실측 필요.
- `docs/IMPL-PLAN-11.md`(라운드 11, 다른 주제)가 이미 있다. 이 문서는 지시대로 `IMPL-PLAN-11-local-stt-link.md`로 두었다(IMPL-PLAN-10 두 벌과 같은 관례).
