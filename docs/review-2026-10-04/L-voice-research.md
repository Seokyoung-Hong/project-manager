# L. Discord 음성 멀티트랙 녹음 → 전사 → 회의록: 외부 사실 조사

- 확인일: **2026-10-05** (별도 표기가 없으면 모든 URL은 이 날짜에 확인)
- GitHub 정보는 `gh api`(릴리스·커밋·이슈 메타데이터)로 확인
- 현재 저장소의 봇: `discord_service/pyproject.toml:10` → `discord.py>=2.4,<3`
- 법률 부분은 공개 자료를 정리한 것이며 **법률 자문이 아님**

---

## 0. 결론 요약

| 항목 | 결론 |
|---|---|
| DAVE | 2026-03-01부터 Discord는 DM·그룹 DM·음성 채널·Go Live에서 E2EE 통화만 지원합니다. 봇도 DAVE가 없으면 close code **4017**로 접속이 끊깁니다. 예외는 Stage 채널뿐입니다. |
| 수신+DAVE 복호화가 **안정 릴리스로** 되는 조합 | **Node: `@discordjs/voice` 0.19.2(2026-03-13) + `@snazzah/davey`**, **Dysnomia(Eris 포크) + davey**(Craig 운영 사례), **Rust: Songbird 0.6.0(2026-04-05) `receive` feature** |
| Python 상황 | discord.py 2.7.0(2026-02-27)은 DAVE를 지원하지만 **수신 API는 없습니다**. `discord-ext-voice-recv` 원본은 DAVE 수신 복호화가 없고(마지막 push 2025-06-18), DAVE PR 5건이 열린 채로 남아 있습니다. Pycord 2.8.x 안정판은 DAVE를 **송신에만** 지원합니다. 수신 DAVE는 미병합 PR #3159(`fix/voice-rec-2`)에 있습니다. |
| 추천 | 기존 Python 봇은 그대로 두고, **녹음 전용 Node 사이드카(`@discordjs/voice` + davey + prism-media/opus)**를 따로 둡니다. 음성 연결만 그 사이드카가 맡습니다. |
| 전사 | 기본은 **`gpt-transcribe`**($0.0045/분, 프롬프트 지원, 타임스탬프 없음)입니다. 참여자별 트랙을 **발화 구간 단위로 잘라** 보내고, 타임라인은 녹음기가 기록한 구간 시작 시각으로 맞춥니다. 세그먼트·단어 타임스탬프가 꼭 필요하면 `whisper-1`(verbose_json)을 씁니다. 트랙이 이미 화자별로 나뉘어 있으므로 diarize 모델은 필요 없습니다. |
| 요약 | 1시간 회의 전사문(약 1만~2만 토큰) 기준으로 Claude Sonnet 5.5는 1회 약 $0.05~0.1, gpt-5-mini는 1센트 안팎입니다. |

---

## 1. Discord DAVE와 라이브러리별 음성 수신

### 1.1 DAVE 일정·강제
- 공식 개발자 문서: "we will **only support E2EE calls starting on March 1st, 2026** for all audio and video conversations in DMs, GDMs, voice channels, and Go Live" — https://docs.discord.com/developers/topics/voice-connections (원문 저장소: https://github.com/discord/discord-api-docs/blob/main/developers/topics/voice-connections.mdx , "End-to-End Encryption (DAVE Protocol)" 절)
- Identify(op 0)에 `max_dave_protocol_version`을 보내야 합니다. 0이거나 생략하면 "no DAVE protocol support"로 봅니다(같은 문서).
- Close code **4017 "E2EE/DAVE protocol required"**: https://github.com/discord/discord-api-docs/blob/main/developers/topics/opcodes-and-status-codes.mdx
- 공식 블로그(2026-05-18): "As of early March 2026, every voice and video call … is end-to-end encrypted by default". DAVE는 2025년에 봇·앱으로 확대됐고, Stage 채널은 예외입니다. — https://discord.com/blog/every-voice-and-video-call-on-discord-is-now-end-to-end-encrypted
- 실제 4017 접속 거부 사례(2026-03-03): https://github.com/Pycord-Development/pycord/issues/3135
- 구조상 의미: 미디어 키는 MLS 그룹 참가자만 압니다. 봇은 MLS 그룹의 **참가자**로 들어가야 복호화할 수 있습니다. 봇이 들어오면 클라이언트 쪽 그룹 구성원도 바뀝니다(같은 voice-connections 문서, op 29/30 설명).
- 음성 **수신**은 Discord가 공식 문서로 보장하지 않습니다. `@discordjs/voice` README: "Audio receive is not documented by Discord so stable support is not guaranteed" — https://github.com/discordjs/discord.js/tree/main/packages/voice

### 1.2 라이브러리 현황(2026-10-05 기준)

| 라이브러리 | 수신 | DAVE | 근거 |
|---|---|---|---|
| **discord.py** | 공식 수신 없음 | v2.7.0(태그 커밋 2026-02-27) "Add DAVE protocol support for voice connections". v2.7.1에서 davey 미설치 경고 추가 | https://github.com/Rapptz/discord.py/blob/master/docs/whats_new.rst |
| **discord-ext-voice-recv**(imayhaveborkedit) | 있음(실험적, "not yet feature complete") | **수신 복호화 없음**. 마지막 push 2025-06-18. DAVE 관련 열린 PR·이슈: #54(03-07), #56(03-12), #58(07-03), #62(08-12), #64(08-18). #61 "OpusError: corrupted stream with davey installed (DAVE not decrypted on receive path)" | https://github.com/imayhaveborkedit/discord-ext-voice-recv/issues |
| zacker150 포크 | DAVE 복호화 주장 | 스타 0, 마지막 push 2026-09-07. 검증되지 않은 개인 포크 | https://github.com/zacker150/discord-ext-voice-recv |
| **Pycord** | `start_recording`·Sink | v2.8.0(2026-05-18): "Support for Discord DAVE … for **voice-sending** related features". 수신 DAVE는 PR #3159(2026-03-19 생성, 미병합, 마지막 갱신 2026-09-05)에 있고, 추적 이슈는 #3139. 메인테이너(2026-04-27): "We cannot give an ETA". 개발 브랜치 사용자 보고 #3388(2026-09-13): UDP keepalive가 5000초로 잡혀 있어 녹음 5~9분 뒤 소리가 끊김 | https://github.com/Pycord-Development/pycord/releases/tag/v2.8.0 , https://github.com/Pycord-Development/pycord/issues/3139 , https://github.com/Pycord-Development/pycord/pull/3159 , https://github.com/Pycord-Development/pycord/issues/3388 |
| nextcord | 공식 수신 없음 | v3.2.0(2026-05-21) "adds support for … DAVE E2EE connections" | https://github.com/nextcord/nextcord/releases/tag/v3.2.0 |
| disnake | 공식 수신 없음 | v2.12.1(2026-07-22) 릴리스 노트에 DAVE 언급 없음 → 확인 불가 | https://github.com/DisnakeDev/disnake/releases |
| **@discordjs/voice** | `VoiceReceiver.subscribe(userId)`, `speaking` 이벤트, `EndBehaviorType`(Manual/AfterSilence/AfterInactivity), `SSRCMap`/`SpeakingMap` | 0.19.0(2025-08-17)의 DAVE 수신은 재접속 루프와 소리 0 문제가 있었습니다(#11419, 2026-02-13). 0.19.1(03-09) "Always install Davey". **0.19.2(03-13)** "Strip padding from packets and add guards"(#11449, #11419 해결). main에는 이후 "receivers return AudioPacket classes"(06-27, breaking), Node 24 요구(07-17), 서버 업데이트 경쟁 상태 수정(09-28)이 들어갔으나 아직 릴리스되지 않았습니다 | https://github.com/discordjs/discord.js/issues/11419 , https://github.com/discordjs/discord.js/pull/11449 , https://github.com/discordjs/discord.js/tree/main/packages/voice/src/receive |
| `@snazzah/davey` | DAVE 구현(Rust, JS·Python·Rust 바인딩) | js-0.1.12 / py-0.1.6 / rs-0.1.4(2026-06-22). discord.py·Pycord·discord.js·Craig가 모두 사용 | https://github.com/Snazzah/davey/releases |
| **Dysnomia**(Eris 포크) | 있음 | DAVE(2025-09-12, #196), 복호화 실패 허용(2025-11-08, #228), 4017 처리(2026-03-02, #236) | https://github.com/projectdysnomia/dysnomia |
| **Songbird**(Rust) | `receive` feature | v0.6.0(2026-04-05) "support for … DAVE protocol, which is since 2026 mandatory for all voice connections". `decrypt_*_in_place` 수정도 포함. **수신 경로에서 DAVE 복호화가 되는지는 릴리스 노트만으로 단정할 수 없습니다** | https://github.com/serenity-rs/songbird/releases/tag/v0.6.0 |
| JDA | 오디오 수신 API 있음 | v6.4.0~6.7.0(2026-03-28~09-20) 릴리스 노트에 DAVE 언급 없음 → **확인 불가** | https://github.com/discord-jda/JDA/releases |

### 1.3 결론: 2026-10 현재 실사용 가능한 조합
1. **Node + `@discordjs/voice` ≥0.19.2 + `@snazzah/davey` + `@discordjs/opus`(또는 opusscript) + prism-media**: 공식 릴리스이고, DAVE 수신 버그 수정이 릴리스에 들어가 있습니다.
2. **Dysnomia + davey**: Craig(대형 녹음 봇)가 운영 중이라 실전 근거가 가장 강합니다. 다만 범용 문서가 적습니다.
3. Songbird 0.6.0: Rust 스택이라 이 프로젝트와 맞지 않습니다.
- Python만으로 하려면 미병합 PR이나 개인 포크에 의존해야 해서 **비추천**입니다.
- 참고: openclaw(@discordjs/voice 사용)는 2026-02에 DAVE 수신 실패를 겪고 davey 의존성을 복구해 고쳤다고 했습니다. 그 뒤에도 재현된다는 댓글이 있었습니다(0.19.2 이전 시점). https://github.com/openclaw/openclaw/issues/24825

---

## 2. 참여자별 트랙의 실제 동작

- **SSRC↔사용자 매핑**: 클라이언트마다 SSRC가 있습니다(op 2 Ready의 `ssrc`, op 5 Speaking 페이로드). @discordjs/voice는 `SSRCMap`(ssrc→userId)과 `SpeakingMap`(발화 시작·종료 이벤트)으로 이를 관리합니다. https://github.com/discord/discord-api-docs/blob/main/developers/topics/voice-connections.mdx ("Speaking" 절), https://github.com/discordjs/discord.js/tree/main/packages/voice/src/receive
- **말할 때만 패킷이 옵니다**: 침묵 구간에는 RTP가 오지 않습니다. `EndBehaviorType.AfterSilence`는 침묵 후 스트림을 닫는 방식입니다(AudioReceiveStream.ts). 타임라인을 맞추는 방법은 둘 중 하나입니다. (a) 패킷(또는 발화 구간)이 도착한 **벽시계 시각**을 기록하고 나중에 그 오프셋만큼 무음을 채우거나, (b) RTP timestamp(48kHz) 차이로 무음 프레임을 채웁니다. Craig가 "Every audio file … in perfect sync"를 내세우는 것도 이런 시각 기록을 바탕으로 합니다(https://craig.chat/). 전사가 목적이라면 **트랙 전체를 맞출 필요 없이 "발화 구간 파일 + 시작 시각"**만 있으면 충분합니다.
- **패킷 손실**: UDP라 손실이 납니다. Opus 디코더의 PLC/FEC로 보정하거나 그대로 건너뜁니다. 전사에는 영향이 작습니다(일반 지식, 출처 없음).
- **DAVE 특유의 위험**: 참가자가 드나들 때 MLS epoch이 바뀌고, 그 사이 복호화 실패 프레임이 생깁니다. Dysnomia는 "DAVE decryption failure tolerance"를 따로 넣었습니다(#228). 모든 프레임이 들어온다는 보장은 없습니다.
- **연결 제약**: 봇 계정은 길드당 음성 상태가 하나라서, 한 길드에서 동시에 한 채널만 녹음할 수 있습니다(Gateway Update Voice State가 guild 단위). 채널 사용자 수 제한도 지킵니다. "Bot users respect the voice channel's user limit … `MOVE_MEMBERS` bypasses" — voice-connections.mdx
- **keepalive**: Pycord #3388처럼 UDP keepalive가 빠지면 몇 분 뒤 Discord가 음성 전송을 멈춥니다. 장시간 녹음을 테스트할 때 반드시 확인해야 합니다.
- **재접속**: 음성 서버 이동(VOICE_SERVER_UPDATE) 때 세션을 다시 만들어야 하고 SSRC 매핑도 새로 받습니다. @discordjs/voice main에 2026-09-28 "handle server update race condition"(#11581)이 들어갔으나 아직 릴리스되지 않았습니다.
- **Opus**: 수신 데이터는 Opus 프레임(48kHz, 20ms)입니다. 방법은 둘입니다. (a) Ogg/Opus 컨테이너에 그대로 담기(재인코딩 없음, Craig 방식). (b) prism-media/@discordjs/opus로 PCM 디코딩한 뒤 ffmpeg로 압축. OpenAI 지원 형식에는 **ogg가 없으므로** 업로드 전에 webm(Opus)이나 mp3/m4a로 바꿔야 합니다(§3).

---

## 3. 전사 API(OpenAI)

출처: https://developers.openai.com/api/docs/guides/speech-to-text , https://developers.openai.com/api/docs/pricing

| 모델 | 가격/분 | 형식·타임스탬프 | prompt | 비고 |
|---|---|---|---|---|
| `gpt-transcribe`(2026-07-28 출시, 2차 출처 https://costgoat.com/pricing/openai-transcription) | **$0.0045** | json만, **타임스탬프 없음** | 지원 | 원어 전사에 공식 권장 모델 |
| `gpt-4o-transcribe` | $0.006 | json, 타임스탬프 없음 | 지원 | 신규 도입에는 비권장(2차 출처) |
| `gpt-4o-mini-transcribe` | $0.003 | json, 타임스탬프 없음 | 지원 | 가장 저렴 |
| `gpt-4o-transcribe-diarize` | $0.006 | `diarized_json`(구간 타임스탬프 포함) | **미지원** | 30초 초과 시 `chunking_strategy` 필요. 알려진 화자 참조는 최대 4명 |
| `whisper-1` | $0.006 | json, text, srt, verbose_json, **word·segment 타임스탬프** | 지원(224토큰) | 단어 타임스탬프·자막이 필요할 때만 |

- 공통: 파일 **25MB** 한도. 형식은 mp3, mp4, mpeg, mpga, m4a, wav, webm(**ogg는 목록에 없음**).
- 25MB 계산: Opus 32kbps webm이면 약 100분 분량입니다. 발화 구간 단위로 자르면 한도 걱정이 없습니다.
- 한국어 품질: 모델별 한국어 WER 공식 수치는 **확인 불가**입니다.
- 참여자별 트랙이므로 diarize는 필요 없고, 화자는 트랙 주인으로 정해집니다. 타임라인은 녹음기가 기록한 발화 시작 시각으로 맞춥니다. 그러면 타임스탬프가 없는 `gpt-transcribe`로도 충분합니다.
- 예상 비용: 1시간 회의에 실제 발화 합계가 60분이면 gpt-transcribe 약 $0.27입니다. 참여자 트랙 합이 회의 시간보다 길어질 수는 있지만, 말할 때만 패킷이 오므로 대체로 회의 시간과 비슷합니다(추정).
- 실시간 전사 모델(gpt-live-transcribe, gpt-realtime-whisper)은 $0.017/분입니다(가격 페이지). 실시간이 필요 없으니 쓸 이유가 없습니다.
- **로컬 faster-whisper**: README 기준 small 모델을 CPU int8로 13분 음성을 처리할 때 **RAM 1477MB**입니다(https://github.com/SYSTRAN/faster-whisper). 512MB 서버에서는 사실상 불가능합니다.
- 다른 클라우드 STT(Google, Azure, Deepgram 등): 이번 조사에서 최신 가격을 확인하지 못했습니다 → **확인 불가**.

---

## 4. 요약 LLM

| 모델 | 입력/출력 ($/1M 토큰) | 출처 |
|---|---|---|
| Claude Haiku 4.5 | 1 / 5 | https://platform.claude.com/docs/en/about-claude/pricing |
| Claude Sonnet 5.5 | 2 / 10 (Batch 1 / 5) | 같음 |
| Claude Opus 5.5 | 4 / 20 | 같음 |
| gpt-5-mini | 0.25 / 2.00 | https://developers.openai.com/api/docs/pricing |
| gpt-5-nano | 0.05 / 0.40 | 같음 |

- 1시간 회의 한국어 전사문을 약 1.5만~2.5만 토큰으로 잡고(추정, Claude 4.7 이후 토크나이저는 약 30% 더 많이 셉니다), 출력을 약 2천 토큰으로 잡으면:
  - Sonnet 5.5: 약 $0.05~0.07
  - Haiku 4.5: 약 $0.03
  - gpt-5-mini: 약 $0.01
- 회의록은 결정·할 일 추출 품질이 중요해서 Sonnet급이 무난합니다. 비용 차이는 회의당 몇 센트입니다.

---

## 5. 법·정책(법률 자문 아님)

### 5.1 통신비밀보호법
- 제3조 제1항과 제14조는 "공개되지 아니한 **타인간의 대화**"를 녹음·청취하는 것을 금지합니다. 위반 시 처벌은 제16조이며 1년 이상 10년 이하 징역입니다(조문 번호는 2차 출처 기준, law.go.kr 원문은 가져오지 못함).
- 대법원 2006.10.12. 2006도4981: **대화 당사자의 녹음은 위반이 아닙니다.** 이 조항의 취지는 대화에 원래 참여하지 않은 **제3자**의 녹음을 막는 데 있습니다. 출처:
  - https://www.classhklaw.com/newsletter_view.php?seq=2753
  - https://casenote.kr/%EB%8C%80%EB%B2%95%EC%9B%90/2013%EB%8F%8415616 (2013도15616, 제3자 녹음 사례)
  - 대법원 2024.2.29. 판결(종료된 대화 녹음물 재생이 '청취'인지): https://www.scourt.go.kr/portal/news/NewsViewAction.work?seqnum=9749&gubun=4&type=5
- 당사자도 상대 동의 없이 녹음하지 못하게 하려던 개정안(윤상현 의원, 2022)은 **2022-09-29 철회**됐습니다. https://www.lawtimes.co.kr/news/articleView.html?idxno=181601 , https://v.daum.net/v/20220822092121360
- **봇 녹음의 해석**: 대화 참여자(명령자)가 자기 도구로 녹음을 시작하는 구조라면 "당사자 녹음"에 가깝다는 해석이 가능합니다. 그러나 다음 경우에는 제3자 녹음 시비가 생길 수 있습니다. 이를 직접 다룬 판례는 **확인 불가**입니다.
  - 봇 운영자(서비스)가 녹음물을 보관·처리하는 경우
  - 명령자가 나간 뒤에도 녹음이 계속되는 경우(**30초 자동 종료가 바로 이 위험을 줄입니다**)
  - 명령자가 처음부터 없던 대화를 녹음하는 경우
- 실무적 완화책: 녹음 중 표시, 입장 시 고지, 이어가기는 현재 참여자만 할 수 있게, 명령자 부재 시 종료.

### 5.2 개인정보보호법
- 개인정보보호위원회 입장으로 전해지는 내용: 녹취의 목소리는 개인을 알아볼 수 있는 정보라서 개인정보입니다(언론 보도 경유, 원문 미확인). https://www.publictoday.co.kr/news/articleView.html?idxno=65708 , https://www.thescoop.co.kr/news/articleView.html?idxno=300101
- 따라서 다음이 필요합니다.
  - 수집 근거: 동의 또는 정당한 이익 등
  - 처리방침에 녹음·전사·국외이전(OpenAI·Anthropic 등 해외 API) 명시
  - 보관 기간을 정하고 파기
- 공공기관 예시: 녹음파일 보관은 "1개월 원칙, 1년 이내"(충남대 운영지침). https://plus.cnu.ac.kr/html/kr/guide/guide_080504.html — 민간에 적용되는 기준은 아니고 참고용입니다.
- 국외이전(제28조의8) 고지 요건 원문은 이번에 직접 확인하지 못했습니다 → **확인 불가**(law.go.kr 본문을 가져오지 못함).

### 5.3 Discord 정책
- Developer Policy 본문(support-dev.discord.com)은 403으로 막혀 원문을 확인하지 못했습니다 → **확인 불가**. discord-api-docs 저장소의 `developers/policies/developer-policy.mdx`는 외부 링크 스텁(126바이트)입니다.
- 2차 출처들은 "동의 없는 녹음 금지, 녹음 사실 고지"를 공통으로 말합니다. https://support.discord.com/hc/en-us/community/posts/360071369492-Record-Calls (커뮤니티 글이라 공식 정책 아님)
- Discord 자체는 음성을 저장하지 않는다고 밝힙니다. https://www.pcgamer.com/discord-says-its-still-not-recording-your-voice-chats-or-livestreams/
- 권장: 녹음 상태 표시(Craig처럼 닉네임 "[RECORDING]"), 시작 시 채널 공지, 처리방침 링크.

---

## 6. 오픈소스 사례: Craig
- 저장소: https://github.com/CraigChat/craig (마지막 push 2026-09-29). 봇 의존성은 `@projectdysnomia/dysnomia`(git 커밋 고정), `@snazzah/davey ^0.1.12`, `@discordjs/opus`, `sodium-native`(apps/bot/package.json).
- 사이트(https://craig.chat/):
  - "a separate audio track for each speaking user"
  - FLAC/AAC, Audacity·Audition 프로젝트로 받기
  - 최대 6시간, **7일 보관**
  - 녹음 중에는 이름 옆에 "[RECORDING]" 표시
  - 모든 트랙 "perfect sync"
- 참고할 점:
  - 원본 Opus 패킷을 시각과 함께 그대로 저장하고, 디코딩·믹싱은 나중에 합니다. 녹음기의 CPU·메모리 부담이 작아 512MB 서버에 유리합니다.
  - 보관 기간이 짧습니다.
  - 녹음 중임을 눈에 띄게 표시합니다.

---

## 7. 위험·불확실
- 음성 수신은 Discord 비공식 기능입니다. DAVE 이후 라이브러리 버그가 잦았습니다(djs #11419, Pycord #3388, voice-recv #61).
- @discordjs/voice 0.19.2 이후 main의 breaking change(AudioPacket, Node 24)가 다음 릴리스에 들어갑니다. 버전을 고정해야 합니다.
- MLS epoch 전환 중 프레임 유실 가능성이 있습니다.
- 봇 녹음이 통비법상 당사자 녹음인지에 대한 판례는 확인하지 못했습니다.
- gpt-transcribe의 한국어 성능 수치가 없습니다. 실제 회의 샘플로 비교(gpt-transcribe vs whisper-1)하는 것이 좋습니다.

## 8. 확인 불가 목록
- JDA·disnake의 DAVE 지원 여부
- Songbird 수신 경로의 DAVE 복호화 실동작
- Discord Developer Policy 원문 중 녹음·동의 조항
- 개인정보보호법 국외이전 조항 원문
- 봇 녹음에 관한 통비법 판례
- 다른 클라우드 STT 최신 가격
- OpenAI 모델별 한국어 WER
