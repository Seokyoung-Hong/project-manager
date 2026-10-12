# 화자 분리 성능 검증 자료 조사 (2026-10-12)

용도 기준: 한국어 회의, 2~10명, 로컬 CPU 또는 GPU. 수치는 모두 출처 표기. 블로그·업체 문서 수치는 **[업체 주장]**.

## 1. 요약 결론

- **한국어 회의 공개 평가는 없다.** 찾은 한국어 평가는 유아–보호자 가정 녹음(2인) 1건뿐이며 회의와 조건이 다르다 [K1]. 아시아권 회의 근거는 중국어 AliMeeting·AISHELL-4뿐.
- **오픈·상업 사용 가능 + CPU 가능 = pyannote community-1이 사실상 유일한 후보.** AliMeeting 20.3%, AISHELL-4 11.7% (collar 0, 겹침 포함) [P2]. CPU 속도는 실시간의 1.5~2배 정도 [업체 주장, F1] → 1시간 회의 30~40분.
- 정확도만 보면 DiariZen(AliMeeting far 10.8%)이 더 좋지만 **모델 가중치가 CC BY-NC 4.0(비상업)** [D1]. pyannote precision-2(AliMeeting 15.2%)는 유료 [P2].
- NeMo 계열은 GPU 전제. Sortformer v1/v2는 **4명 상한**, 5명 이상에서 급격히 나빠짐(DIHARD III 5~9명 42.56%) [N2]. Nemotron-3-Diarization(2026-09-23)은 8명·상업 사용 가능 라이선스지만 학습 언어에 한국어 없음, CPU 지원 명시 없음 [N3].
- OpenAI `gpt-4o-transcribe-diarize`는 **공개 DER 없음**(확인 불가).
- 결론: 2~10명 한국어 회의라면 **community-1로 시작하고, 우리 녹음 20개 안팎으로 직접 DER을 재서** 25%를 넘으면 GPU + Nemotron-3 또는 OpenAI 대체를 검토한다.

## 2. 모델 × 데이터셋 DER (%)

조건 표기: c0 = collar 없음, c.25 = 0.25초, OV = 겹친 발화 포함 평가.

| 모델 | AMI | AISHELL-4 | AliMeeting | DIHARD III | VoxConverse | MSDWild | 조건·출처 |
|---|---|---|---|---|---|---|---|
| pyannote 3.1 | 18.8 (IHM mix) / 22.4 (SDM ch1) | 12.2 | 24.4 (ch1) | 21.7 (full) | 11.3 | 25.3 | c0, OV [P1] |
| pyannote community-1 | 17.0 (IHM) | 11.7 | 20.3 | 20.2 | 11.2 | — | c0, OV(README 표; 조건은 3.1과 같은 벤치마크로 추정 — 명시 확인 불가) [P2][P3] |
| pyannote precision-2 (유료) | 12.9 (IHM) | 11.4 | 15.2 | 14.7 | 8.5 | — | [업체 주장, P2] |
| DiariZen-Large-s80-v2 | 13.9 (SDM) | 10.1 | 10.8 (far) | 14.5 (full) | 9.1 | 15.8 | c0, 도메인 적응 없음 [D1]. 가중치 비상업 |
| Sortformer 4spk-v1 | — | — | — | 16.28 (후처리 14.76) | — | — | DIHARD3-Eval c0, OV [N1]. 비상업 |
| Streaming Sortformer 4spk-v2 | — | — | — | 18.91 (1–4명 13.24, 5–9명 42.56) | — | — | c0, OV, 후처리 포함 [N2] |
| Nemotron-3-Diarization | — | — | — | 12.73 (full, 30.4s 지연) | — | — | [N3], 1–4명 9.13 / 5–9명 27.58 [업체·언론, N4] |
| NeMo MSDD | 1.05 (MixHeadset) | — | — | — | — | — | CALLHOME 3.92 [M1]. **조건(oracle VAD·겹침 제외 여부) 확인 불가** — 위 표와 직접 비교 금지 |
| whisperX | 별도 수치 없음 | | | | | | 화자 분리는 pyannote community-1을 그대로 씀 [W1] → community-1 수치를 따름 |
| OpenAI gpt-4o-transcribe-diarize | 확인 불가 | | | | | | 공식 DER 미공개 [O1] |

제3자 통합 비교 [B1] (CALLHOME·VoxConverse·AMI·AliMeeting 196.6시간, **collar 0.25, 겹침 포함**, pyannote는 3.1):
- 전체 DER: pyannoteAI(유료 API) 11.2, DiariZen 13.3, 나머지(Sortformer·SF v2·pyannote 3.1)는 그림으로만 제시 — 표 수치 확인 불가.
- 주된 오류: 놓친 발화(경계 타이밍, 평균 약 350ms), 화자 많을수록 화자 혼동 증가. Sortformer 계열은 4명 초과에서 크게 나빠짐.

화자 수 오류:
- 한국어 유아 녹음: 화자 수 정답률 Sortformer 88.68%, pyannote 62.26%, SpeechBrain 43.40% [K1].
- 그 밖의 공개 화자 수 오류율은 확인 불가. community-1은 "화자 수 세기·배정 개선"이라고만 함 [P2].

JER: 위 출처 어디에도 표로 없음 — 확인 불가.

## 3. 속도·자원

| 모델 | 속도 | 하드웨어 | 메모리 | 출처 |
|---|---|---|---|---|
| pyannote community-1 | 오디오 1시간당 31–37초 | H100 | 확인 불가 | [P2] |
| pyannote community-1 | RTFx 1.5–2 (CPU), 20–25 (Apple MPS) | 기종 미상 | 확인 불가 | [업체 주장, F1] |
| pyannote precision-2 | 1시간당 14초 | H100 | — | [업체 주장, P2] |
| pyannote 3.1 | RTF 45.0x (실시간 대비) | RTX A6000 | — | [B1] |
| DiariZen | 20.2x | RTX A6000 | — | [B1] |
| Sortformer v2 / v2-stream | 214.3x / 209.5x | RTX A6000 | — | [B1] |
| Sortformer v1 | RTFx 437 (DIHARD3) | RTX A6000 48GB, 배치 1 | 길이는 GPU 메모리에 달림(A6000에서 약 12분) | [N1] |
| Nemotron-3-Diarization | RTFx 1340–4385 | RTX PRO 5000 Blackwell | CPU 지원 명시 없음 | [N3] |

## 4. 한국어 근거

- **한국어 회의 공개 DER: 없음.**
- 유일한 한국어 평가 [K1]: 유아(2–5세)–보호자 가정 녹음 53개, 스마트폰 등 개인 기기. DER(2인 녹음 34개, collar 0.16초): Sortformer 33.04%, pyannote 154.36%, SpeechBrain 136.21%. 유아 음성·고음 겹침이 원인이라 회의와 조건이 다르다 — 참고만.
- 한국어 전화(8kHz) 미세조정 pyannote 모델은 있으나 공개 DER 확인 불가 [K2].
- 다국어 벤치마크(soniqo)는 8개 언어에 한국어 없음 [S1]. DISPLACE 2024도 인도 언어만 [S2].
- AI Hub "주요 영역별 회의 음성"(파생 데이터 680GB로 존재 확인 [K3])은 있으나 화자 분리용 정답(시간 구간별 화자) 제공 여부 확인 불가.
- 가장 가까운 대리 지표: 중국어 회의 AliMeeting(원거리 마이크, 4인 내외) — community-1 20.3% [P2].

## 5. 수치 비교 시 주의점

- **collar**: 0.25초 collar는 경계 오차를 빼 줘 DER이 크게 낮아진다. pyannote·DiariZen 카드는 c0, [B1]·CALLHOME은 c.25 → 같은 표에 섞지 말 것.
- **겹친 발화**: 제외(skip_overlap)하면 낮아진다. 회의는 겹침이 많아 반드시 포함으로 잰다.
- **oracle VAD**: 정답 발화 구간을 주면 놓침·오경보가 0에 가까워져 DER이 비현실적으로 낮다(MSDD 1.05%처럼 조건이 불명확한 수치는 쓰지 말 것).
- **마이크 조건**: AMI IHM(헤드셋 합본) < SDM(원거리 1채널). 회의실 노트북 녹음은 SDM·AliMeeting far에 가깝다.
- **후처리·하이퍼파라미터 튜닝**: Sortformer 카드 수치는 데이터셋별 후처리 최적화값 포함 [N1].
- **화자 수 힌트**: `num_speakers`를 주면(oracle 화자 수) 낮아진다. 실제 운영 조건(힌트 없음 또는 참석자 수만)으로 잰다.
- **업체 표**(pyannote.ai, FluidInference, Voice Arena)는 재현 조건이 공개되지 않은 경우가 많다.

## 6. 자체 검증 방법 제안

- **샘플**: 실제 회의 녹음 15~20개(각 10~30분, 합계 약 5시간). 인원 2–3 / 4–6 / 7–10명을 고르게, 녹음 기기 2종 이상(노트북·휴대폰), 대면 회의 위주. 녹음 동의 필수.
- **정답 만들기**: 사람이 RTTM으로 화자 구간 표기(1시간당 3~5시간 작업 예상 — 추정). 도구 예: ELAN 또는 Audacity 라벨 → RTTM 변환. 일부는 Discord 회의 녹음으로 대체 가능 — 사람별 트랙(VoiceTrack)이 있어 **정답 RTTM을 자동으로 만들 수 있다**(혼합 녹음을 입력, 트랙 구간을 정답으로). 단 온라인 음질이라 대면 회의 대표성은 떨어진다.
- **지표**(`pyannote.metrics`): DER(collar 0, 겹침 포함)을 주지표로, FA·Miss·Confusion 분해, JER, 화자 수 정답률(예측 화자 수 = 실제), 인원 구간별 DER. 보조로 collar 0.25 수치도 같이 남겨 공개 수치와 대조.
- **실용 지표**: 전사 결과 기준 "화자가 틀린 발화 비율"(구간 단위, 사람이 확인) — 사용자가 체감하는 품질.
- **속도·자원**: 전사 서버 PC에서 RTF와 최대 RSS(`/usr/bin/time -v` 또는 `docker stats`) 측정, CPU/GPU 각각.
- **비교군**: community-1(힌트 없음 / 참석자 수 힌트), OpenAI gpt-4o-transcribe-diarize(같은 파일), (GPU 있으면) Nemotron-3-Diarization.
- **합격선 예시**: DER(c0, 겹침 포함) 25% 이하 + 화자 수 정답률 70% 이상 — 사용자와 합의 필요.

## 7. 확인 불가

- 한국어 회의 데이터에서의 DER(모든 모델).
- OpenAI gpt-4o-transcribe-diarize의 DER·화자 수 정확도·한국어 성능.
- community-1의 CPU 속도(업체 문서 외)와 메모리 사용량, community-1 README 표의 collar·겹침 조건 명시.
- [B1]의 모델별·데이터셋별 표 수치(그림으로만 제시).
- NeMo MSDD 수치의 평가 조건.
- JER 공개 수치, Ego4D 수치(pyannote 3.1 카드에도 없음).
- AI Hub 회의 음성의 화자 구간 정답 제공 여부.

## 출처

- [P1] pyannote 3.1 모델 카드 — https://huggingface.co/pyannote/speaker-diarization-3.1
- [P2] pyannote-audio README (3.1/community-1/precision-2 표, H100 속도) — https://github.com/pyannote/pyannote-audio
- [P3] community-1 모델 카드 — https://huggingface.co/pyannote/speaker-diarization-community-1
- [D1] DiariZen — https://github.com/BUTSpeechFIT/DiariZen
- [N1] Sortformer 4spk-v1 — https://huggingface.co/nvidia/diar_sortformer_4spk-v1
- [N2] Streaming Sortformer 4spk-v2 — https://huggingface.co/nvidia/diar_streaming_sortformer_4spk-v2
- [N3] Nemotron-3-Diarization — https://huggingface.co/nvidia/Nemotron-3-Diarization
- [N4] 언론 보도(1–4명/5–9명 수치) — https://www.unite.ai/nvidia-releases-nemotron-3-diarization-open-weight-speaker-model/
- [M1] MSDD (Interspeech 2022) — https://arxiv.org/abs/2203.15974
- [W1] whisperX — https://github.com/m-bain/whisperX
- [O1] OpenAI 전사 가이드 — https://developers.openai.com/api/docs/guides/speech-to-text
- [B1] Benchmarking Diarization Models (arXiv 2509.26177) — https://arxiv.org/html/2509.26177
- [F1] FluidInference 벤치마크 문서 — https://docs.fluidinference.com/reference/benchmarks.md
- [K1] Korean Toddler Speech diarization (arXiv 2606.10213) — https://arxiv.org/html/2606.10213v1
- [K2] batispeak-diarize — https://huggingface.co/batiai/batispeak-diarize
- [K3] AI Hub 회의 음성 파생 데이터 — https://huggingface.co/datasets/maxseats/aihub-464-preprocessed-680GB-set-43
- [S1] soniqo 다국어 벤치마크 — https://soniqo.audio/ko/benchmarks/diarization
- [S2] DISPLACE 2024 — https://arxiv.org/html/2406.09494v1
