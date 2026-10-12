# 한국어 화자 분리 실사용 성능 — 비공식 자료 조사 (2026-10-12)

공식 자료(논문·모델 카드) 조사는 `diarization-benchmarks.md`. 이 문서는 블로그·GitHub·커뮤니티·기업 자료만 다룬다.
신뢰도: **측정 있음**(수치·절차 공개) / **개인 체감**(수치 없음) / **기업 주장**(재현 불가) / **미검증**(구현만, 실측 없음).

## 1. 핵심 발견

- **한국어 회의를 실제로 돌려 본 기록은 1건뿐**: 98분·6명 참석(5명 발화) 한국어 회의, sherpa-onnx + CAM++ 임베딩. 화자 수를 5로 고정하면 5명 모두 구분, **자동 화자 수는 485명으로 과분할돼 못 씀** [U1]. pyannote는 같은 프로젝트에서 HF 토큰 문제로 **시험하지 않음**.
- **한국어 실측 DER은 전화(2인) 1건뿐**: pyannote 기본 25.9% → 한국어 미세조정 13.2% (통화 3건, collar 0.5초, num_speakers=2) [U2]. 미세조정 데이터는 한국어 회의 음성(KconfSpeech)으로 합성.
- **"화자 수를 알려 줘야 쓸 만하다"는 공통 체감**: 참석자 수 상한/고정 입력을 둔 구현이 여럿 [U1][U5][U7]. 단일 마이크 회의에서 정확도가 떨어진다는 언급 [U7].
- **한국어 회의용으로 pyannote community-1을 쓰는 앱은 있으나 정확도는 안 쟀다** [U6]. 미세조정 공개 모델은 카드에 데이터·조건이 없어 수치를 믿을 수 없음 [U3].
- **국내 기업 수치 없음**: 클로바노트(WISE 엔진)·리턴제로(VITO) 모두 화자 분리를 기능으로 내세우나 DER 등 수치는 찾지 못함 [C1][C2].
- **AI Hub "주요 영역별 회의 음성인식 데이터"(7,000시간, 회의당 2~45명)는 화자·말바뀜 정보를 포함**한다고 소개됨 [D1] → 한국어 회의 평가셋으로 쓸 수 있는 유일한 공개 후보(라벨 형식 직접 확인 필요).
- OpenAI `gpt-4o-transcribe-diarize`로 한국어 통화·메모 전사를 옮긴 개인 프로젝트가 있으나 품질 기록은 없음 [U4].

## 2. 자료별 정리

| # | 자료 | 방식 | 조건 | 결과 | 신뢰도 |
|---|---|---|---|---|---|
| U1 | GitHub 이슈 idean3885/claude-ops-agent#540 | sherpa-onnx + CAM++ zh_en / WeSpeaker ResNet34 | 한국어 회의 98분, 참석 6·발화 5명, Apple M2 Pro 2스레드 | CAM++ 화자 수 5 고정: 744초, 5명 모두 구분(사람 확인), 짧은 맞장구는 섞임. 자동(임계 0.5): 485명 과분할. ResNet34: 1,850초, 3명을 못 나눔(한 사람 72분) | 측정 있음(DER 없음, 체감 평가) |
| U2 | HF batiai/batispeak-diarize | pyannote 분할 단계만 한국어 미세조정 | 실제 한국어 통화 3건(2.3~7.8분), 8kHz, 2인, collar 0.5초, 정답 1초 단위 | 기본 25.9% → 13.2% DER(평균) | 측정 있음(표본 3건·거친 정답 — 절대값은 참고만) |
| U3 | HF ppxyn1/speaker-segmentation-fine-tuned-korean2 | pyannote 3.0 분할 미세조정 | 데이터 `test_data`, 설명 없음 | DER 0.0050 (0.5%) | 믿기 어려움(조건 미공개, 과적합 의심) |
| U4 | GitHub baekenough/second-brain#111, PR#174 | pyannote 마이크로서비스 구현 → OpenAI gpt-4o-transcribe-diarize로 전환 | 한국어 통화·음성 메모, 모노 AAC 44.1kHz, 2인 위주 | 로컬 pyannote는 기본 꺼둔 채 실측 없이 폐기, OpenAI 품질 기록 없음 | 미검증 |
| U5 | GitHub ByeongJooSung/MeetNote PR#1 | 브라우저 내 화자 구분, 10초 창·5초 이동, 창당 최대 3명 | 한국어 회의, 4명 이상에서 개선 목적 | `eval_stt.py`로 화자 정확도 측정 도구는 있으나 수치 미공개 | 개인 체감 |
| U6 | GitHub dev-universe/meeting-archive | faster-whisper + pyannote.audio 4.0.7(community-1) | Windows, RTX 3050 6GB, 참석자 1~30 입력 | "실제 다중 화자 회의의 정확도·VRAM 사용량은 별도 측정하지 않았습니다" | 미검증 |
| U7 | GitHub gggg8657/meeting-local | sherpa-onnx(pyannote-segmentation-3.0 ONNX + CAM++) | 폐쇄망, HF 토큰 불필요가 선택 이유 | "마이크 하나로 녹음한 회의에서 떨어진다", 화자 수 직접 지정 권장 | 개인 체감 |
| U8 | PyTorchKR: Senko 소개 | Senko 파이프라인 | 영어·중국어 벤치마크만 | VoxConverse 10.5%, AISHELL-4 9.3%, 1시간 5초(RTX 4090). 한국어는 "충분히 쓸 수 있다"는 말뿐 | 업체(개발자) 주장, 한국어 근거 없음 |
| U9 | DBpia: Pyannote·Resemblyzer 부모–아동 대화 (2025 한국컴퓨터정보학회 하계) | pyannote 기반 TS-VAD 등 | 놀이실, 개인 마이크, 아동 발화·겹침 많음 | 정확도 71.06%(검색 요약 기준, 지표 정의 확인 불가) | 측정 있음(학회 발표, 회의 아님) |
| U10 | GitHub whisperX#11 | whisperX 한국어 | — | 언어 코드를 `kr`로 주면 정렬 타임스탬프가 0.5초대로 뭉개짐 → 언어 코드 문제로 해결. 화자 분리 품질 언급 없음 | 개인 체감 |
| C1 | 네이버 클로바노트(보도) | NEST 전사 + WISE 화자 엔진 | — | 화자 분리 기능 설명만, 수치 없음 | 기업 주장 |
| C2 | 리턴제로 VITO(보도) | 자체 엔진 | 통화 | "통화 참여 화자를 정밀하게 구분" 홍보, 수치 없음 | 기업 주장 |
| C3 | 티로 블로그(클로바노트·다글로·티로 비교) | — | 1인 인터뷰 | 화자 분리는 비교하지 않음 | 해당 없음 |
| D1 | AI Hub 464 주요 영역별 회의 음성인식 | — | 7,000시간, 회의당 2~45명(2명 32.3%, 3명 17.4%), 방송·국회·UCC·주제 녹음 | 화자 정보·말바뀜 라벨 포함으로 소개(JSON+WAV) | 공공 데이터 소개(라벨 세부는 직접 확인 필요) |

GitHub 저장소 이슈 검색("Korean"): pyannote-audio·DiariZen 0건, whisperX는 언어 코드·정렬 이슈뿐(#11, #61, #929), NeMo는 검색 실패 — 한국어 화자 분리 정확도 이슈는 없음.

## 3. 기존 결론(community-1 추천)에 주는 영향

- **바뀌지 않는다.** community-1을 깎는 한국어 근거도, 더 나은 대안의 한국어 근거도 없다.
- **보강할 점 3가지**
  1. **화자 수 입력을 기본으로**: 자동 화자 수는 한국어 회의에서 크게 틀린 사례가 있다 [U1]. 유달리 업로드 화면에 "참석 인원"(선택) 칸을 두고 `num_speakers`/`max_speakers`로 넘긴다.
  2. **비교군에 sherpa-onnx + CAM++(3D-Speaker)를 추가**: HF 토큰 불필요, CPU·ONNX로 가볍고, 한국어 회의 실사용 1건이 있다 [U1][U7]. 같은 pyannote 분할 모델을 쓰므로 차이는 임베딩·군집화.
  3. **한국어 미세조정은 효과가 크다는 신호**(통화 −12.8%p [U2]) — 1단계 실측이 나쁘면 분할 단계 미세조정을 2단계 후보로.
- 자체 검증셋: Discord 참여자별 트랙(자동 정답) + **AI Hub 464 회의 음성**(라벨 확인 후) 일부를 쓰면 사람 표기 부담을 줄일 수 있다.

## 4. 확인 불가

- pyannote community-1·3.1을 한국어 회의(3명 이상)에 돌린 실측 DER·체감 기록.
- OpenAI gpt-4o-transcribe-diarize의 한국어 화자 분리 품질(사용 사례는 있으나 기록 없음).
- NeMo Sortformer·DiariZen·whisperX의 한국어 회의 사용 후기.
- 클로바노트·VITO·카카오·당근의 화자 분리 수치 또는 기술 블로그 글(검색에서 찾지 못함).
- Reddit 관련 글(검색 결과 없음, API 접근 실패), 유튜브 데모(측정 있는 영상 찾지 못함).
- AI Hub 464의 라벨이 시간 구간별 화자(RTTM로 바꿀 수 있는 형식)인지 — 데이터 소개 페이지 요약 기준이며 실제 JSON은 미확인.
- U9 논문의 "정확도 71.06%" 지표 정의.

## 출처

- [U1] https://github.com/idean3885/claude-ops-agent/issues/540
- [U2] https://huggingface.co/batiai/batispeak-diarize
- [U3] https://huggingface.co/ppxyn1/speaker-segmentation-fine-tuned-korean2
- [U4] https://github.com/baekenough/second-brain/issues/111 , https://github.com/baekenough/second-brain/pull/174
- [U5] https://github.com/ByeongJooSung/MeetNote/pull/1
- [U6] https://github.com/dev-universe/meeting-archive
- [U7] https://github.com/gggg8657/meeting-local
- [U8] https://discuss.pytorch.kr/t/senko-speaker-diarization/7695
- [U9] https://www.dbpia.co.kr/journal/articleDetail?nodeId=NODE12337705
- [U10] https://github.com/m-bain/whisperX/issues/11
- [C1] https://navercorp.com/en/media/pressReleasesDetail?seq=30622 , https://designcompass.org/en/2023/11/20/clovanote-release/
- [C2] https://www.fnnews.com/news/202207241729546607
- [C3] https://tiro.ooo/ko/blog/-%EC%9D%8C%EC%84%B1-%EC%9D%B8%EC%8B%9D-ai-%EC%A0%95%ED%99%95%EB%8F%84-%EB%B9%84%EA%B5%90-%ED%81%B4%EB%A1%9C%EB%B0%94%EB%85%B8%ED%8A%B8-vs-%EB%8B%A4%EA%B8%80%EB%A1%9C-vs-%ED%8B%B0%EB%A1%9C-31174
- [D1] https://www.aihub.or.kr/aihubdata/data/view.do?dataSetSn=464
