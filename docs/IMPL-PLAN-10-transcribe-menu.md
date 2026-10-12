# IMPL-PLAN-10 · 전사 메뉴 (2026-10-12, 시안 B로 구현 — 커밋 전)

사용자 요구: 전사는 메뉴를 따로 둔다 / 전사 중 예상 소요시간을 보여 주고, 취소하고 다른 모델로 다시 전사할 수 있게 /
장치·정밀도·속도 같은 세부 정보는 밖에 꺼내지 않고 세부 보기에 넣는다.
시안: `docs/drafts/transcribe-menu/` A·B·C(아래 §2).

**사용자 결정(2026-10-12)**
- 시안 **B**(작업 목록 + 패널, "전사 작업 / 전사 서버" 두 보기).
- 메뉴는 **조직 관리자만**.
- 모델은 제작자·계열이 보여야 한다. 서버가 `display_name`·`family`·`owned_by`를 주면 그것만 쓰고, 없으면 id로 추정하지 않고 id 그대로 + 수단 표시
  (로컬 "… · 로컬 서버", 조직 키 "OpenAI Whisper(whisper-1) · OpenAI API").
- **전사문 ≠ 회의록**(정정, 최우선): 전사문은 녹음을 글로 옮긴 원문으로 전사 작업마다 남고 녹음 쪽(`VoiceRecording.transcript_md` = 현재 전사문,
  `TranscriptionJob.transcript_md` = 시도별)에 저장한다. 회의록(MeetingNote 본문)은 사람·AI가 정리하는 문서이고 전사문을 참고 자료로 볼 뿐이다.
  다시 전사는 회의록 본문을 바꾸지 않는다. 앞서 적은 "[이 전사문으로 바꾸기]로 확정 회의록 교체"는 폐기하고 **[현재 전사문으로 지정]**만 둔다.
  기존 회의록은 데이터 이전 없이 그대로 둔다(마이그레이션은 AddField·CreateModel만).
  확인 결과 지금 코드도 전사문을 회의록 본문에 넣지 않는다 — draft 전이 때 본문이 비었으면 정리용 틀(`DRAFT_BODY`: 요약·결정 사항·할 일·미결)만 넣고,
  전사문은 `rec.transcript_md`에 둔다(`core/notes/services.py` update_recording). 바꾼 것은 알림 문구("전사문이 포함된 회의록 초안" → "회의록 초안과 전사문이 준비된 상태")와
  회의록 화면의 전사문 칸 설명뿐이다.

## 0. 요지

- 위치: **조직 탭 `전사`**(회의록 탭 바로 뒤, 조직 관리자 전용 — 지금 전사 설정과 같은 권한). URL `/orgs/<id>/transcribe`.
- 지금 조직 설정 안의 전사 칸(`meeting.stt_url`·`stt_model`·`stt_timeout_s`·`stt_api_key`·`openai_api_key`)과
  [연결 시험]·[모델 적용]·받는 중 폴링(`org_stt_test`·`org_stt_apply`)을 **새 메뉴로 옮긴다**. 설정 키·저장 형식은 그대로 둔다(마이그레이션 없음).
  설정 화면의 meeting 묶음에는 "전사 설정은 전사 메뉴에서 바꿉니다" 한 줄 링크만 남긴다.
- 전사 작업을 core에 `TranscriptionJob`으로 기록한다. **실행은 계속 Node 음성 서비스**가 한다(자동 전사·다시 전사 모두).
  core는 상태·진행·취소 신호·예상 시간 계산만 맡는다.
- 다시 전사 입력 = **참여자별 트랙(`VoiceTrack`) + core에 새로 저장하는 구간 목록**. 혼합 파일은 쓰지 않는다(화자가 섞인다).

## 1. 근거(현재 코드)

| 사실 | 출처 |
|---|---|
| 전사 설정은 조직 설정 화면의 설정 행 안에 select + [모델 적용] + [연결 시험] | `core/web/templates/settings/_setting_control.html:28-34`, `core/web/views/orgs.py:561-663` |
| 조직 탭 목록(회의록 다음에 이슈·GitHub·Discord·설정) | `core/web/templates/orgs/_tabs.html:3-14` |
| Node가 회의 종료 뒤 구간마다 전사(동시 3, 1.5초 미만 구간 제외), 로컬 → 조직 OpenAI 키 순 | `discord_gateway/src/transcribe.mjs:6-7, 70-72` |
| 후처리 큐는 한 번에 회의 하나. 올리기 → 전사 → draft PATCH → `seg/`·`meeting.ogg`·`track-*` 삭제 | `discord_gateway/src/meetings.mjs:232-271` |
| 트랙은 그 사람 구간만 회의 시작 기준 지연(`delay_ms`)으로 섞은 파일 = 회의 길이 전체에 침묵이 낀 파일 | `meetings.mjs:279-296` |
| 구간 경계(`segments.jsonl`)는 Node 로컬에만 있고 core에는 없다. `stats`에는 개수만 | `core/notes/models.py:80-81`, `meetings.mjs:284` |
| 전사문은 회의록 본문이 아니라 `VoiceRecording.transcript_md` 별도 칸 → 바꿔 써도 사용자가 고친 본문은 안전 | `core/notes/services.py:486-494` |
| Node → core 호출은 PATCH/PUT/GET names뿐, core → Node 통로 없음(Node가 core를 폴링하지 않음) | `discord_gateway/src/core.mjs:43-60` |
| core에 백그라운드 작업 실행기 없음(관리 명령만: purge_expired 등) | `core/ops/management/commands/` |
| 로컬 서버 `/v1/models` 지금 필드: id·status(ready/downloading/not_downloaded)·progress·error. fits·device·compute_type·rtf는 아직 없음 | `udally-stt/server.py:69-82` |

## 2. 화면

공통: 조직 탭 `전사` · `.page-head` 제목 "전사" · 사용자에게는 모델 이름·상태·"약 N분 남음"·"30분 회의 약 N분"만 보인다.
장치·정밀도·실측 배수(rtf)·동시 처리·구간 수·실패 구간·응답 시간은 **세부 정보**(`details.fold` 또는 대화상자)에만 둔다.
`fits=false` 모델은 고를 수 없게(disabled) 하고 이유는 "이 서버에서 쓸 수 없음" 한 마디로.

| 시안 | 구조 | 다시 전사 위치 | 세부 정보 위치 |
|---|---|---|---|
| A `A-two-cards.html` | 한 화면 두 카드: 위 "전사 서버"(연결 상태·모델 select·[모델 적용]·속도 상자), 아래 "전사 작업" 표(회의록/상태/진행/남은 시간/행동). 850px 이하 표 → 쌓인 행 | 행의 [다른 모델로 다시 전사] → 대화상자(모델 선택 카드마다 예상 시간) | 행 안 접힘 "세부 정보", 서버 상자 안 "서버 세부 정보" |
| B `B-list-panel.html` | `.view-switch`로 "전사 작업 / 전사 서버" 두 보기. 작업은 진행 중·대기·끝남 묶음 목록, 행을 누르면 오른쪽 패널(DESIGN 2.6, 모바일 전체 시트) | 패널 안: 큰 "약 N분 남음" + [전사 취소] + 모델 선택 카드 + [취소하고 다시 전사] | 패널 접힘 "세부 정보"·"전사 기록 N" |
| C `C-model-meeting.html` | 맨 위 세이지 띠 "지금 전사 중"(화면당 초점 장식 하나) · 모델 선택 카드 묶음(준비됨/받는 중 막대/받기/OpenAI) · 회의별 전사 기록(시도 칩, 지금 전사문 표시, 되돌리기) | 회의 줄 안 select(모델·예상 시간) + [다시 전사] | 모델 카드 [세부 정보] 대화상자, 서버 주소·키는 [전사 서버 설정] 대화상자 |

상태 표기(`.conn-state`): 전사 중 `on` · 대기 기본 · 끝남 기본 · 끝남·구간 N개 실패 `warn` · 취소됨 `off` · 실패 `bad`.
버튼 문구: [전사 취소] [대기 취소] [다른 모델로 다시 전사] [다시 전사 시작] [취소하고 다시 전사] [현재 전사문으로 지정] [전사 서버 설정 저장] [모델 적용] [연결 시험] [닫기].
보관 기간이 지난 회의: 버튼 대신 "보관 기간이 지나 다시 전사할 수 없습니다". 구간 목록이 없는 이전 회의(§5): "이 회의는 다시 전사를 지원하기 전에 녹음되었습니다".
빈 상태: `.empty`("전사한 회의가 없습니다" + "Discord에서 /회의시작 으로 회의를 녹음하면 끝난 뒤 자동으로 전사합니다").
회의록 화면(전사문 칸 옆)에도 "전사 중 · 약 N분 남음" 한 줄과 전사 메뉴 링크를 둔다(진행자는 전사 메뉴를 못 볼 수 있으므로 읽기만).

## 3. 예상 시간

**입력**
- `A` = 전사할 음성 길이(ms) = 구간 목록 중 1.5초 이상 구간 `duration_ms`의 합(말한 시간. 회의 길이가 아니다).
- `rtf0` = 처리 배수(처리 시간 ÷ 음성 길이) 사전값, 아래 순서로 첫 번째 있는 값:
  1. 같은 조직·같은 수단·같은 모델의 최근 끝난 작업 5건 `measured_rtf` 중앙값(core가 계산, 가장 믿을 만함)
  2. 로컬 서버 `/v1/models` 항목의 `rtf`(udally-stt가 내기로 한 실측값)
  3. 기본값 표: OpenAI `0.08`, 로컬은 **없음**
- `p` = 동시 처리 수 = min(Node `CONCURRENCY` 3, 서버가 알려 준 동시 처리 수, 없으면 1). OpenAI는 3.

**시작 전·대기 중**: `ETA = A × rtf0 ÷ p + 구간 수 × 0.4초 ÷ p`(ffmpeg 변환·HTTP 고정비). `rtf0`가 없으면 "예상 시간 계산 중"으로 두고 첫 구간 결과 뒤 표시.
대기 작업은 "약 N분 뒤 시작" = 앞 작업들의 남은 시간 합.

**진행 중 갱신**(Node가 진행을 보낼 때마다 core가 다시 계산)
- `d` = 끝난 구간 음성 합, `t` = 시작 뒤 경과. `r_obs = t ÷ d`(관측 배수, p 효과 포함).
- 가중 `w = min(1, d ÷ max(A × 0.3, 60초))` — 30% 또는 1분 분량을 처리하면 관측값만 믿는다.
- `r = w × r_obs + (1 − w) × (rtf0 ÷ p)`, `남은 시간 = (A − d) × r`.
- 표시: 1분 미만 "1분 안에 끝남", 그 외 "약 N분"(올림). 바뀐 값이 15% 넘게 다르거나 30초가 지났을 때만 숫자를 바꾼다(튀지 않게).
- 끝나면 `measured_rtf = (끝난 시각 − 시작 시각) ÷ A`를 저장 → 다음 계산의 1번 사전값.
- 모델 고르기 화면의 "30분 회의 약 N분"은 `A = 30분 × 조직 평균 말한 비율`(최근 회의 `A ÷ 회의 길이`, 없으면 0.6)로 같은 식.

## 4. 작업 상태 모델

```
queued ──(Node가 가져감)──▶ running ──▶ done
  │                           │  └────▶ failed   (전부 실패·수단 없음·입력 없음)
  └─(대기 취소, core가 바로)─▶ cancelled ◀─(Node 확인)─ cancelling ◀─(전사 취소)─ running
```

- **자동 작업**: Node의 종료 PATCH(`status=transcribing`)를 core가 받을 때 `kind=auto` 작업을 만들고 응답에 `job_id`를 준다. Node는 지금처럼 바로 전사한다(대기열 거치지 않음).
- **다시 전사**: 화면에서 [다시 전사 시작] → core가 `kind=retry, status=queued` 작업 생성(회의당 대기·진행 작업 하나. 진행 중에 고르면 진행 작업을 `cancelling`으로 바꾸고 새 작업을 대기열에 넣는다 = "취소하고 다시 전사").
- **실행 주체 = Node**. 이유: ffmpeg·구간 전사·엔진 대체·prompt 거부 재시도·용어집이 이미 `transcribe.mjs`에 있다. core는 gunicorn 웹뿐이라 실행기가 없고, RAM 2GB·1 vCPU에서 web 프로세스 안 스레드 전사는 요청 처리를 막는다. Node는 후처리 큐(한 번에 하나)를 그대로 써서 메모리 상한(384MB)을 지킨다.
- **Node가 일을 받는 방법**: 후처리 큐가 비어 있을 때만 20초마다 `POST /transcriptions/claim`(core가 `select_for_update(skip_locked)`로 가장 오래된 queued 하나를 running으로 바꿔 돌려줌). 회의 종료 후처리가 항상 먼저다.
- **취소 신호**: Node는 구간 결과마다(최소 5초 간격) `PATCH /transcriptions/{id}`로 진행을 보내고, 응답의 `cancel: true`를 본다. 받으면 새 구간을 꺼내지 않고 진행 중 요청은 `AbortController`로 끊은 뒤 `status=cancelled`를 보낸다. 지연은 최대 "구간 하나 + 5초".
- **결과 반영**: 끝난 작업의 전사문은 `job.transcript_md`에 둔다. 끝난 작업이 현재 전사문(`rec.transcript_md`·`rec.transcript_job`)이 되고, 이전 시도는 전사 기록에 남아 [현재 전사문으로 지정]으로 되돌린다. 회의록 상태(초안·확정)와 본문은 건드리지 않는다.
- 자동 작업을 취소하면 지금처럼 빈 전사문의 초안이 된다(회의록은 그대로 생긴다).
- Node 재시작: running 작업은 core에 남는다. Node 기동 시 자기 것이던 running 작업을 `queued`로 되돌리는 `POST /transcriptions/requeue` 한 번(자동 작업은 기존 `results.jsonl` 재개 그대로).
- 오래 멈춘 작업: 마지막 진행 보고 뒤 10분 넘으면 core가 화면에 "응답 없음"(`warn`)으로 보이고 [대기열에 다시 넣기]만 허락.

## 5. 다시 전사 입력

- 혼합 파일(`VoiceRecording.audio`)은 화자가 섞여 `[시각] 이름:` 형식을 못 만든다 → 쓰지 않는다.
- 트랙 통째 전사는 회의 길이 × 참여자 수만큼 침묵을 처리해 느리고(1 vCPU), whisper가 침묵에서 문장을 지어낸다 → 쓰지 않는다.
- **채택**: Node가 올리기 단계에서 구간 목록 `[{seq, user_id, start_ms, duration_ms}]`을 core에 함께 보낸다(`VoiceRecording.segments` JSON, 회의당 수백 행·수십 KB).
  다시 전사 때 Node는 트랙을 임시 폴더로 받아(스트리밍, 파일 기반) `ffmpeg -ss start -t dur -i track.ogg -c:a copy -f webm`로 구간을 잘라 기존 `transcribeMeeting`에 넘긴다(`convert`만 바꿈). 끝나면 임시 폴더를 지운다.
- 구간 목록이 없는 이전 회의는 다시 전사를 막는다. ponytail: 필요하면 트랙에 ffmpeg `silencedetect`로 구간을 다시 찾는 대체 경로를 더한다.
- 보관 기간이 지나 트랙이 지워졌으면 막는다(`audio_expired`).

## 6. 데이터 모델 · API

**core/notes/models.py**
- `VoiceRecording.segments = JSONField(default=list)` (새 칸).
- `TranscriptionJob`: `recording` FK · `kind`(auto/retry) · `status`(queued/running/cancelling/cancelled/done/failed) · `engine`(local/openai) · `model` ·
  `requested_by` FK null · `audio_ms`(A) · `done_ms` · `segments_total` · `segments_done` · `segments_failed` · `measured_rtf` float null ·
  `transcript_md` · `stats` JSON(장치·정밀도·rtf 등 세부 정보 원본) · `error`(사용자 문구 코드) · `created_at` · `started_at` · `progress_at` · `finished_at`.
  제약: 회의당 `status in (queued, running, cancelling)` 하나(부분 유니크).
- 데이터 이전(RunPython) 없음. 기존 회의는 작업 이력 없이 시작한다.

**봇 API** `core/api/routers/discord.py`(봇 범위 토큰)
- `PATCH /meetings/{id}` 응답에 `job_id`(transcribing으로 바뀔 때). 본문에 `segments` 받기.
- `POST /transcriptions/claim` → `{job, recording_id, engine, model, stt, glossary, names, segments, tracks: [discord_user_id]}` 또는 204.
- `PATCH /transcriptions/{job_id}` 진행·결과(`done_ms, segments_done, segments_failed` / `status, transcript_md, stats`) → `{cancel}`.
- `GET /meetings/{id}/tracks/{discord_user_id}` 봇용 트랙 내려받기(지금은 PUT만).
- `POST /transcriptions/requeue`.

**웹** `core/web/views/orgs.py` → 새 `core/web/views/transcribe.py`로 분리
- `GET /orgs/<id>/transcribe`(화면) · `GET …/transcribe/jobs`(HTMX 조각, running·queued가 있으면 `hx-trigger="every 5s"`) ·
  `POST …/transcribe/jobs/<job>/cancel` · `POST …/transcribe/recordings/<rec>/retry`(model, engine) · `POST …/transcribe/jobs/<job>/use`(되돌리기).
- `org_stt_test`·`org_stt_apply`는 URL 이름을 유지한 채 새 화면에서 쓴다(설정 화면 분기 제거).

**udally-stt**(다른 에이전트) `/v1/models` 항목에 `fits`·`device`·`compute_type`·`rtf`·(가능하면 `concurrency`) — 없으면 §3 순서대로 대체.

## 7. 단계 · 충돌 파일

| 단계 | 내용 | 파일 | 충돌 주의 |
|---|---|---|---|
| 1 core 모델·봇 API | §6 모델·마이그레이션·봇 엔드포인트·예상 시간 함수(`notes/transcribe_eta.py` + 테스트 1개) | `core/notes/models.py`, `core/notes/migrations/`, `core/notes/services.py`, `core/api/routers/discord.py`, `core/api/schemas.py` | 화자 분리 계획(`docs/PLAN-diarization.md` §5)이 같은 모델·라우터를 건드림 — 순서를 정해 한쪽 뒤에 |
| 2 Node | segments 올리기, job_id 진행 보고·취소, claim 폴링, 트랙 내려받아 구간 자르기 | `discord_gateway/src/core.mjs`, `meetings.mjs`, `transcribe.mjs`(`signal`·`onProgress` 인자) + 테스트 | `meetings.mjs`는 6660a15(트랙 저장) 직후, 화자 분리와도 겹침 |
| 3 웹 화면 | 고른 시안, 탭 추가, 설정 화면에서 전사 칸 제거·링크, 회의록 화면 한 줄 | `orgs/_tabs.html`, 새 `orgs/transcribe*.html`, `views/transcribe.py`, `views/orgs.py`, `settings/_setting_control.html`, `web/urls.py`, `static/app.css`, `DESIGN.md`(표 한 줄), `/ops/design` 견본 | `_setting_control.html`·`orgs.py`는 2a298ef에서 막 바뀜 |
| 4 검증 | pytest·ruff·node test, Postgres 임시 DB에 migrate, 390·1440 라이트·다크 화면 | — | — |

1 → 2 → 3 순서(2·3은 1의 API 확정 뒤 병렬 가능).

## 8. 사용자 결정 (답변 완료, 2026-10-12)

1. 시안 B. 2. 확정 회의록 교체는 폐기 — 전사문은 회의록과 별개, [현재 전사문으로 지정]만(§0 정정). 3. 메뉴는 조직 관리자만.

## 9. 확인 불가 · 위험

- udally-stt `rtf`의 정의(단일 요청 기준인지 동시 처리 포함 처리량인지)와 `concurrency` 제공 여부 — 정의에 따라 §3의 `p`로 나눌지가 바뀐다. 현재 `server.py`에는 아직 없다.
- 운영 서버 녹음 보관 기간 설정값·실제 보관 중인 회의 수.
- `ffmpeg -c:a copy`로 Ogg Opus 트랙을 구간 자르기할 때 앞부분 20~80ms 손실 정도(실측 필요, 문제면 구간 앞뒤 0.2초 여유).
- 다시 전사가 대기열을 오래 차지하면 그동안 끝난 회의의 자동 전사가 늦어진다 — claim은 후처리 큐가 빌 때만 하므로 막히지는 않지만, 다시 전사 도중 회의가 끝나면 그 회의는 다시 전사가 끝난 뒤 시작한다(필요하면 다시 전사를 끊고 양보하는 규칙 추가).

## 10. udally-stt 계약 가정 (대조용 — 필드가 없어도 동작한다)

`GET /v1/models` → `{"data": [항목…]}`. 항목에서 읽는 필드와, 없을 때의 동작(`core/web/views/orgs.py` `stt_models`, `core/notes/transcription.py`):

| 필드 | 가정한 뜻·형 | 없을 때 |
|---|---|---|
| `id` | 문자열, 전사 요청 `model` 값 | 항목을 버린다 |
| `status` | `ready` / `downloading` / `not_downloaded` | `ready`로 본다(일반 OpenAI 호환 서버) |
| `progress` | 0~1 실수, `downloading`일 때 | 퍼센트 생략 |
| `display_name` | 사용자에게 보일 전체 이름(예 "OpenAI Whisper large-v3-turbo") | 아래 조합 |
| `family` | 계열(예 "Whisper") | 생략 |
| `owned_by` | 제작자(예 "OpenAI"). id·family에 이미 들어 있으면 붙이지 않는다 | 생략 → 이름 = `owned_by family id` 중 있는 것, 모두 없으면 id 그대로(추정 안 함) |
| `fits` | bool, 이 서버 메모리·장치에서 돌릴 수 있는지. `false`면 고를 수 없고 "이 서버에서 쓸 수 없음" | 쓸 수 있다고 본다 |
| `device` · `compute_type` | 문자열(예 "cpu"·"int8") | 세부 정보에서 줄 생략 |
| `rtf` | 실수, **요청 하나 기준** 처리 시간 ÷ 음성 길이 | 실측(같은 조직·수단·모델 최근 5건 중앙값)이 우선. 둘 다 없으면 로컬은 "예상 시간 계산 중" |
| `concurrency` | 정수, 서버가 동시에 처리하는 요청 수 | 1로 본다. 예상 시간의 병렬 수 = min(3, concurrency) |

- 받기: `POST /v1/models/{id}` 202/200(기존 [모델 적용]), 404·405면 받기 미지원으로 보고 저장만.
- 전사: `POST /v1/audio/transcriptions`(OpenAI 호환, `model`·`language=ko`·`prompt`·`response_format=json`) — 바꾸지 않았다. 409(모델 미준비)는 구간 실패로 기록된다.
- 서버 `rtf`가 처리량 기준(동시 처리 포함)이면 `prior_rtf`에서 `p`로 나누지 말아야 한다 — 확정되면 `transcription.prior_rtf` 한 줄을 고친다.

## 11. 구현 메모 (계획과 달라진 점)

- 다시 전사 실행: Node `Meetings.pollJobs()`(20초마다, 후처리 큐가 비었을 때만) → `POST /transcriptions/claim` → 트랙 `GET /meetings/{id}/tracks/{uid}`를 `data/retry/<job>/`에 받아 `ffmpeg -ss -t`로 구간을 잘라 전사 → `PATCH /transcriptions/{id}` done/failed/cancelled → 임시 폴더 삭제.
  고른 수단만 쓴다(로컬이면 OpenAI 대체 끔, OpenAI면 로컬 주소 비움).
- 자동 작업: 종료 PATCH 응답의 `job_id`로 진행을 보고(5초 간격)하고 응답 `cancel`이면 멈춘다. 끝은 기존 draft PATCH가 맡는다(취소면 `stats.cancelled`, 녹음만이면 실패 `no_engine`).
- 응답 없는 작업(10분): [전사 취소]가 Node를 기다리지 않고 바로 취소로 끝낸다. 계획의 [대기열에 다시 넣기]는 두지 않았다.
- 예상 시간 표시의 "15% 넘게 바뀔 때만 갱신"은 생략(5초 폴링마다 다시 계산). ponytail: 숫자가 튀면 그때 넣는다.
- 회의록 화면에는 "전사 중 · 약 N분"(관리자에게는 전사 메뉴 링크)과 접힌 전사문 칸만 둔다.
- 조직 설정 화면에서 전사 칸(`orgs.settings.STT_KEYS`)을 빼고 링크 한 줄만 남겼다. 두 화면 모두 서로의 값을 보존해 저장한다.
- `/ops/design` 견본은 추가하지 않았다(DESIGN.md 4장에 부품 한 줄만).
