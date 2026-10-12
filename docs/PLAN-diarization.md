# 회의록 전사 화자 분리(diarization) 계획 (2026-10-12)

구현 전 계획이다. 사용자가 §7 질문에 답하면 방식·범위를 확정한다. 전사 흐름·용어는 `IMPL-PLAN-9.md`, 프로세스 구성은 `IMPL-PLAN-9-parallel.md`를 따른다.

## 0. 요지

- **Discord 회의는 이미 화자가 분리돼 있다.** 녹음이 사람별 구간(`discord_gateway/src/recorder.mjs`, 구간마다 `user_id`)이고, 전사도 구간 단위로 `[HH:MM:SS] 이름: 텍스트`를 만든다(`discord_gateway/src/transcribe.mjs:24-30`). 참여자별 트랙도 저장된다(`core/notes/models.py:95` VoiceTrack).
- **지금 화자 분리가 필요한 입력은 없다.** 웹 업로드 `note_upload`는 Markdown(.md/.markdown)만 받는다(`core/web/views/notes.py:138-155`, `core/notes/services.py:104`). 녹음 파일을 올리는 경로 자체가 없다.
- 따라서 화자 분리는 **"녹음 파일 올리기" 기능을 새로 만들 때만** 의미가 있다. 그 기능을 만들지부터 사용자가 정한다(§7 질문 1).
- 추천(만든다면): **로컬 전사 서버(udally-stt)에 pyannote `speaker-diarization-community-1` 컨테이너를 더하고, 응답은 OpenAI `diarized_json` 형식을 그대로 따른다. 대체 경로는 조직 OpenAI 키의 `gpt-4o-transcribe-diarize`.** 같은 요청·응답 형식이라 유달리 쪽 코드는 한 갈래다.

## 1. 화자 분리가 필요한 경우

| 경우 | 지금 상태 | 화자 분리 필요 | 비고 |
|---|---|---|---|
| A. Discord 음성 회의(1인 1계정) | 사람별 구간으로 이미 분리 | 불필요 | 이름 = Discord 참여자 |
| B. Discord 한 계정 마이크로 여러 명(회의실 노트북 1대) | 그 계정 이름 하나로 묶임 | 필요(그 사람 구간 안에서만) | 그 트랙만 화자 분리. 라벨 "홍길동 마이크 · 화자 2" |
| C. 대면·오프라인 회의를 휴대폰 등으로 녹음 | 올릴 경로 없음 | 필요 | 새 기능 "녹음 파일 올리기" 전제 |
| D. 다른 도구(Zoom·Meet) 녹음 파일 | 올릴 경로 없음 | 필요 | C와 같은 경로 |

- B는 드물고, C를 만들면 "회의실 녹음을 따로 올리기"로 대신할 수 있다. **B는 1단계 범위에서 뺀다**(필요해지면 트랙 파일을 C 경로에 넣으면 된다 — VoiceTrack 파일이 이미 있음).
- 결론: 범위 = **C·D(녹음 파일 올리기 + 화자 분리 + 화자 이름 정하기)**.

## 2. 방식 비교

| | 1안 pyannote community-1 (udally-stt 옆 컨테이너) | 2안 OpenAI `gpt-4o-transcribe-diarize` (조직 키) | 3안 NeMo Sortformer |
|---|---|---|---|
| 정확도 | DER AMI 17.0%, AliMeeting(중국어 회의) 20.3%, AISHELL-4 11.7% [1]. 한국어 수치 확인 불가 | 공개 DER 확인 불가. 한국어 성능 확인 불가 | 4명까지, 5명 이상 성능 저하, 주로 영어 학습 [3][4] |
| 비용 | 무료(전사 서버 PC 전력) | 토큰 과금 입력 $2.50/1M·출력 $10/1M [2]. 분당 약 $0.006은 제3자 추정 [6] | 무료 |
| 메모리·하드웨어 | CPU 기본 동작, GPU 선택 [1]. 실측 속도·RAM 확인 불가 → 1단계에서 실측 | 0 (운영 LXC 부담 없음) | GPU 필수, CPU 부적합 [3][4] |
| 라이선스·요건 | CC-BY-4.0, HF 게이트 모델(연락처 공유 동의 + HF 토큰) [1]. pyannote.audio 4.x | OpenAI 약관. 녹음이 외부로 나감 | v1 CC-BY-NC-4.0(비상업) [3], 스트리밍 v2 CC-BY-4.0 [4] |
| 구현량 | 중: 작은 FastAPI 서비스 1개(speaches 전사 + pyannote + 구간 겹침 매칭) | 소: 요청 인자만 다름 | 대: NeMo 런타임·GPU 전제 |
| 제약 | 화자 수 힌트 `num_speakers`/`min/max_speakers` [1] | prompt(용어표) 미지원, 30초 넘으면 `chunking_strategy` 필요, 알려진 화자 4명까지 [5]. 최대 출력 2,000토큰 [2] → 긴 녹음은 나눠 보내야 하는지 확인 불가 | 4명 상한 |

참고:
- **speaches는 화자 분리를 지원하지 않는다**(기능 목록·문서에 없음) [7]. 그래서 1안은 speaches를 바꾸지 않고 옆에 서비스를 둔다.
- **whisperX**(BSD-2)도 화자 분리는 pyannote community-1을 그대로 쓰고 HF 토큰이 필요하다 [8]. 한국어 정렬 모델(`kresnik/wav2vec2-large-xlsr-korean`)이 있다 [9]. 단어 단위 정렬이 필요할 때만 의미 있으며, 이미 speaches(faster-whisper)를 쓰므로 **1단계는 구간(segment) 단위 매칭으로 충분**하다. whisperX는 정확도가 모자랄 때의 대안으로 남긴다.
- 한국어 화자 분리 공개 벤치마크(회의 데이터)는 찾지 못했다. 한국어 전화(8kHz)용 pyannote 미세조정 모델은 있다 [10]. → **샘플 회의 녹음으로 직접 재는 단계를 넣는다(§6 S1).**

## 3. 추천안

**1안 + 2안 대체.** 순서는 지금 전사와 같다: 로컬 서버 우선 → 실패 시 조직 OpenAI 키(`IMPL-PLAN-9.md` §3).

- 이유: 무료·녹음이 밖으로 안 나감(1안), 운영 LXC(RAM 2GB·1 vCPU·GPU 없음)에는 추론을 올리지 않음, 응답 형식을 OpenAI에 맞춰 대체 경로를 같은 코드로 처리.
- 3안은 GPU 필수·영어 위주·4명 상한이라 제외.
- 2안 단독도 가능하다(구현량 최소). 다만 용어표 prompt를 못 쓴다 [5] — 고유명사 전사 품질이 떨어질 수 있다.

## 4. API 확장 (OpenAI 호환 유지)

OpenAI가 이미 정한 형식을 그대로 쓴다. 새 필드를 발명하지 않는다.

요청 (`POST /v1/audio/transcriptions`, multipart):
- `model`: 로컬은 `udally-diarize`(가칭, `/v1/models`에 노출), OpenAI는 `gpt-4o-transcribe-diarize`
- `response_format=diarized_json`, `language=ko`, `chunking_strategy=auto`
- (선택) `known_speaker_names[]` / `known_speaker_references[]` — OpenAI 형식 [5]. 1단계는 보내지 않는다.
- 로컬 전용 확장: `num_speakers`, `min_speakers`, `max_speakers`(pyannote 인자 [1]). OpenAI는 모르는 필드라 대체 경로에서는 빼고 보낸다.

응답 (`diarized_json`, OpenAI 형식 [5]):
```json
{ "text": "...", "segments": [ { "speaker": "A", "start": 0.0, "end": 4.2, "text": "..." } ] }
```

로컬 서비스(udally-stt에 `diarize` 컨테이너 추가, 담당 레포는 udally-stt):
1. speaches에 `response_format=verbose_json`으로 전사 요청 → 구간 `start/end/text` (prompt=용어표 사용 가능)
2. pyannote community-1 exclusive 출력으로 화자 구간 [1]
3. 전사 구간마다 겹침이 가장 긴 화자를 붙인다. ponytail: 구간 안에서 화자가 바뀌면 한 화자로 묶인다 — 정확도가 모자라면 whisperX 단어 정렬로 올린다
4. 다른 `model` 요청은 speaches로 그대로 넘긴다(기존 전사 무변경). 포트·API 키는 지금 compose 규칙 그대로
- HF 토큰은 udally-stt `.env`에만 둔다. 모델은 첫 기동 때 받아 볼륨에 캐시(지금 `hf-hub-cache`와 같은 방식).

## 5. 유달리 쪽 변경

**데이터 모델** (`core/notes/models.py`, 마이그레이션 1개):
- 녹음 파일 올리기는 `VoiceRecording`을 재사용한다(회의록 문서와 1:1, `audio`·보관 만료·내려받기·`purge_expired`가 이미 있음). 추가 필드:
  - `source`: `discord` | `upload` (기본 `discord`)
  - `segments` JSON: `[{start_ms, end_ms, speaker, text}]` — 화자 이름을 바꾸면 `transcript_md`를 다시 만들기 위한 원본
  - `speakers` JSON: `{"A": {"name": "홍길동", "user_id": 12|null}}`
- `guild_id`·`voice_channel_id`는 업로드일 때 빈 값. `started_by`=`host`=올린 사람.
- Discord 회의는 바뀌지 않는다(`segments`·`speakers` 비움, 기존 `transcript_md` 그대로).

**전사 결과 형식**: 기존과 같은 `[HH:MM:SS] 이름: 텍스트`. 이름을 아직 안 정한 화자는 `화자 A`. 이름을 정하면 `segments`+`speakers`로 다시 만든다(초안 상태일 때만, 확정 후에는 문서 편집으로).

**누가 전사를 돌리나**: 전사 코드는 Node `discord-voice`에만 있다(`transcribe.mjs`). 운영 LXC 메모리를 생각해 **core가 직접 오래 기다리지 않는다.** 후보:
- (가) `discord-voice`에 "올린 파일 전사" 작업 추가 — 재시도·로컬→OpenAI 대체·stats가 이미 있음. 단 `discord` 프로필이 꺼진 조직 서버에선 못 돈다.
- (나) core에 짧은 관리 명령/백그라운드 루프(`purge_expired`처럼 compose 루프) — Discord와 무관.
- 추천: (나). 업로드 기능은 Discord 없이도 써야 하므로. HTTP 호출만 하고 추론은 전사 서버가 하므로 메모리 부담은 작다.

**업로드 화면** (`core/web/views/notes.py`, 회의록 목록의 "올리기"):
- 지금 Markdown 올리기 옆에 "녹음 파일 올리기"를 둔다. 크기 상한·형식 확인(지금 `_is_ogg_opus`는 Ogg Opus만 — 휴대폰 녹음은 m4a가 많아 형식 범위를 정해야 함, §7 질문 2)
- 상태 표시는 기존 `transcribing → draft` 그대로.

**화자 이름 정하기 UI** (초안 회의록 화면, `DESIGN.md` 따름):
- 화자 목록(A, B, …)마다 첫 발언 한 줄 미리보기 + 그 구간 재생(이미 있는 녹음 내려받기 뷰에 범위 재생) + 이름 칸(조직 멤버 고르기 또는 직접 입력).
- 저장하면 `transcript_md` 재생성. 화자 합치기(A와 C가 같은 사람)는 같은 이름을 고르면 되도록 한다 — 별도 기능 안 만듦.
- 권한: 지금 초안 규칙 그대로(진행자·조직 관리자).

**조직 설정** (`core/orgs/settings.py` `meeting.stt_*` 옆): 새 설정 없음을 기본으로 한다. 로컬 서버 `/v1/models`에 `udally-diarize`가 보이면 쓰고, 없으면 OpenAI 키로, 둘 다 없으면 화자 분리 없이 전사(`화자` 라벨 없음).

**용어**(사용자 노출 통일, 금지어 grep 대상): "화자 분리"는 화면에 쓰지 않고 **"말한 사람 나누기"**, 라벨은 **"화자 A"**, 동작은 **"화자 이름 정하기"** — 문구는 관례대로 Sol이 확정.

## 6. 단계·담당

| 단계 | 내용 | 담당 | 레포 | 선행 |
|---|---|---|---|---|
| S0 | §7 질문 답 받기 | 메인 | — | — |
| S1 | 한국어 샘플(대면 회의 3~5명, 10~30분)로 1안·2안 정확도·속도·RAM 실측. 결과로 1안 유지 여부 결정 | Opus | udally-stt(실험만) | S0 |
| S2 | udally-stt `diarize` 서비스(§4) + compose + 시험 | Opus 구현, Sol 교차 검토 | udally-stt | S1 |
| S3 | core: 모델 필드·마이그레이션(Postgres 리허설), 업로드 뷰·전사 작업(나), `segments`→`transcript_md` 생성, 시험 | Opus | discord_test | S0 (S2와 병렬, 응답 형식만 고정) |
| S4 | 화자 이름 정하기 UI | Opus 구현, Astra 화면 검토(Sol이 찍기, 모바일 포함) | discord_test | S3 |
| S5 | 승인(배포 전) | Fable | — | S2~S4 |

- 충돌 파일: `core/notes/models.py`, `core/notes/services.py`, `core/web/views/notes.py`, 회의록 템플릿. 지금 core/web·orgs 작업과 겹치므로 그 작업 병합 뒤 시작.
- S3은 2안(OpenAI)만으로도 끝까지 시험 가능 — S2가 늦어도 막히지 않는다.

## 7. 사용자에게 물을 것 (최대 3개)

1. **녹음 파일 올리기 기능을 만들까요?** 만들지 않으면 화자 분리는 필요 없습니다(Discord 회의는 이미 사람별입니다). 한 Discord 계정을 여럿이 쓰는 경우(§1 B)도 이번 범위에 넣을지 함께 정해 주세요.
2. **엔진**: 로컬 pyannote 우선 + OpenAI 대체(추천) / OpenAI만(구현 최소, 녹음이 외부로 나가고 용어표 미적용) 중 골라 주세요. 로컬이면 HF 계정으로 community-1 모델 동의·토큰 발급이 필요합니다.
3. **올릴 수 있는 형식·길이**: 휴대폰 녹음(m4a/mp3/wav)까지 받을지, 최대 길이(예: 2시간)·크기를 정해 주세요.

## 8. 확인 불가·위험

- 한국어 회의 화자 분리 정확도(pyannote·OpenAI 모두) — 공개 수치 없음. S1 실측으로 대신.
- pyannote community-1의 CPU 처리 속도·RAM — 공식 수치 없음.
- `gpt-4o-transcribe-diarize`의 공식 분당 가격(토큰 단가만 공식, 분당 $0.006은 제3자 추정 [6]), 최대 출력 2,000토큰과 긴 녹음의 관계, 한국어 지원 여부 명시.
- 전사 서버 PC가 꺼져 있으면 로컬 경로 불가 → OpenAI 대체 또는 대기(지금 규칙과 같음).

## 출처

1. https://huggingface.co/pyannote/speaker-diarization-community-1
2. https://developers.openai.com/api/docs/models/gpt-4o-transcribe-diarize
3. https://huggingface.co/nvidia/diar_sortformer_4spk-v1
4. https://huggingface.co/nvidia/diar_streaming_sortformer_4spk-v2
5. https://developers.openai.com/api/docs/guides/speech-to-text
6. https://costgoat.com/pricing/openai-transcription (제3자)
7. https://github.com/speaches-ai/speaches
8. https://github.com/m-bain/whisperX
9. https://raw.githubusercontent.com/m-bain/whisperX/main/whisperx/alignment.py (58행 `"ko"`)
10. https://huggingface.co/batiai/batispeak-diarize
