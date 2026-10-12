# 내 PC 전사 연결 · 임시 문구 모음 (IMPL-PLAN-11-local-stt-link)

2026-10-13 core 구현에서 넣은 **임시 문구**다. 최종 문구는 Sol이 이 표를 보고 정해 해당 위치를 바꾼다.
위치의 코드·템플릿에는 같은 키가 `# COPY:키` / `{# COPY:키 #}` 주석으로 붙어 있다(`grep -rn "COPY:" core`).
말투: 격식체("…입니다", 요청만 "…해 주세요"). 모델 표시는 계열 포함("내 PC · OpenAI Whisper large-v3-turbo").
전사문 ≠ 회의록 — 다시 전사가 회의록 본문을 바꾼다는 뜻의 문구 금지. 금지어: "large-turbo", "회의록을 다시 전사".
줄 번호는 커밋 시점 기준(바뀌면 키로 찾는다).

## 기기 인증·연결 화면

| 키 | 위치 | 임시 문구 | 맥락 |
|---|---|---|---|
| link_title | core/web/templates/settings/stt_link.html:5 | 내 PC를 전사 서버로 연결 | /link 제목 |
| link_code_help | core/web/templates/settings/stt_link.html:8 | PC에서 실행한 연결 명령이 보여 준 코드 8자리를 입력해 주세요. | 빈 코드 입력칸 위(주소로 채우지 않음) |
| link_consent | core/web/templates/settings/stt_link.html:17 | ⚠ 직접 PC에서 연결 명령을 실행한 경우에만 허용해 주세요. 다른 사람이 보내 준 코드를 허용하면 그 사람의 PC가 내 계정으로 내가 볼 수 있는 녹음을 전사합니다. | 확인 화면 경고(피싱 대비) |
| link_done | core/web/templates/settings/stt_link.html:34 | '{name}'을(를) 연결했습니다. PC 화면으로 돌아가 주세요. | 허용 결과 |
| link_denied | core/web/templates/settings/stt_link.html:35 | 연결을 거절했습니다. 이 PC는 내 계정에 연결되지 않습니다. | 거절 결과 |
| link_expired | core/web/templates/settings/stt_link.html:36 · core/web/views/stt_link.py:28 | 코드가 만료되었습니다. PC에서 연결 명령을 다시 실행해 주세요. | 확인 중 만료 |
| link_not_found | core/web/views/stt_link.py:23 | 코드를 찾을 수 없습니다. PC 화면에 보이는 코드를 다시 확인해 주세요. | 코드 오입력 |
| link_too_many | core/web/views/stt_link.py:26 | 코드를 여러 번 잘못 입력했습니다. {minutes}분 뒤 다시 시도해 주세요. | 10분 5회 잠금 |
| too_many_servers | core/notes/stt_link.py:36 | 전사 서버는 한 사람당 5대까지 연결할 수 있습니다. 쓰지 않는 서버를 끊은 뒤 다시 허용해 주세요. | 허용 시 상한 |
| link_approved_notice | core/notes/stt_link.py:40 | 내 PC 전사 서버 '{name}'을(를) 연결했습니다. 직접 연결한 PC가 아니라면 내 PC 연결 화면에서 바로 끊어 주세요. <링크> | 허용 직후 Discord DM |

## 내 PC 연결 화면(/settings/stt)

| 키 | 위치 | 임시 문구 | 맥락 |
|---|---|---|---|
| (탭) | core/web/templates/settings/_tabs.html | 내 PC 연결 | 설정 탭 이름 |
| settings_stt_title | core/web/templates/settings/stt.html:6 | 내 PC 전사 서버 | 카드 제목 |
| settings_stt_intro | core/web/templates/settings/stt.html:7 | PC에서 명령 한 줄을 실행하고 화면에 뜬 코드를 {링크}에 입력하면 연결됩니다. PC가 켜져 있는 동안 내가 볼 수 있는 회의록의 녹음을 그 PC로 전사합니다. 포트를 열 필요가 없습니다. | 안내 |
| install_windows_help | core/web/templates/settings/stt.html:11 | PowerShell에 붙여 넣어 실행해 주세요. Docker가 있으면 Docker로, 없으면 uv로 설치합니다. 관리자 권한은 필요하지 않습니다. | Windows 접힘 |
| install_unix_help | core/web/templates/settings/stt.html:16 | 터미널에 붙여 넣어 실행해 주세요. 다시 실행하면 최신 판으로 업데이트합니다. | macOS·Linux 접힘 |
| install_advanced_help | core/web/templates/settings/stt.html:20 | 설치 스크립트는 실행 전에 열어 볼 수 있습니다: install.ps1 · install.sh. 이미 udally-stt를 설치했다면 `udally-stt connect`로 연결합니다. | 고급 접힘 |
| install_uninstall_help | core/web/templates/settings/stt.html:23 | 제거하면 이 화면의 연결도 함께 끊깁니다. 받은 모델 파일은 남으며, 지우는 방법은 제거 명령이 알려 줍니다. | 제거 안내 |
| settings_stt_empty | core/web/templates/settings/stt.html:28 | 연결한 PC가 없습니다 / 위 명령을 PC에서 실행하면 그 PC로 회의 녹음을 전사할 수 있습니다. | 빈 상태 |
| pull_failed | core/web/templates/settings/_stt_server.html:8 | 모델을 받지 못했습니다. {오류} | 받기 오류(PC가 heartbeat models의 error로 보냄) |
| pull_started | core/web/templates/settings/_stt_server.html:17 | 모델을 받는 중입니다. 다 받으면 회의 자동 전사에 이 모델을 씁니다. / 모델을 적용했습니다. / 회의 자동 전사 모델: {이름} / 모델을 적용하면 내가 진행한 회의를 이 PC로 자동 전사합니다. | 모델 칸 도움말 |
| pull_not_fits | core/notes/stt_link.py:266 | 이 PC에서 쓸 수 있는 모델을 골라 주세요. | fits=false·없는 모델 |
| unlink_confirm | core/web/templates/settings/_stt_server.html:27 | '{name}' 연결을 끊습니다. 이 PC는 더 이상 전사하지 않고, 진행 중인 전사는 조직 수단으로 넘기거나 취소합니다. 다시 쓰려면 PC에서 연결 명령을 다시 실행해야 합니다. [연결 끊기] | 확인 창 |
| unlink_done | core/web/views/stt_link.py:153 | '{name}' 연결을 끊었습니다. | 끊은 뒤 알림 |

## 전사 선택지·권한·작업 표시

| 키 | 위치 | 임시 문구 | 맥락 |
|---|---|---|---|
| pc_model_label | core/notes/transcription.py:92, :100 | 내 PC · {모델 표시 이름} / 내 PC({서버 이름}) · {모델 표시 이름} | 선택지·작업 라벨(서버 여러 대면 이름) |
| pc_offline_option | core/web/views/transcribe.py:181 | 내 PC · 꺼져 있음 / 내 PC({서버 이름}) · 꺼져 있음 | 고를 수 없는 한 줄 |
| pc_disabled_by_org | core/notes/transcription.py:43 | 이 조직은 멤버 PC로 전사하지 않도록 설정되어 있습니다. | 선택지 한 줄·오류 |
| pc_offline | core/notes/transcription.py:46 | 고른 PC가 꺼져 있습니다. PC에서 전사 서버를 켠 뒤 다시 시도해 주세요. | 지시 시점 오류 |
| pc_not_mine | core/notes/transcription.py:48 | 내 PC 전사 서버만 고를 수 있습니다. | 남의 서버 지정 |
| pc_no_model | core/notes/transcription.py:49 | 내 PC에 준비된 모델을 골라 주세요. | 준비 안 된 모델 |
| org_stt_no_permission | core/notes/transcription.py:50 | 조직 전사 수단은 조직 관리자만 쓸 수 있습니다. 내 PC를 연결해 전사해 주세요. | transcribe_level=admin |
| org_stt_already_used | core/notes/transcription.py:53 | 이 녹음은 이미 조직 전사 수단으로 전사했습니다. 내 PC로 전사하거나 조직 관리자에게 요청해 주세요. | 녹음당 1회 한도(멤버) |
| no_access | core/notes/transcription.py:55 | 이 녹음을 볼 수 있는 사람만 전사할 수 있습니다. | 가시성 |
| no_options | core/web/templates/orgs/_transcribe_panel.html:20 | 다시 전사에 쓸 수 있는 모델이 없습니다. 전사 서버 보기에서 서버 주소나 OpenAI 키를 저장하거나, 설정의 내 PC 연결에서 PC를 연결해 주세요. | 선택지 없음 |
| job_waiting_pc | core/web/templates/orgs/_transcribe_progress.html:5 | PC를 기다리는 중 / 고른 PC가 꺼져 있습니다. PC에서 전사 서버가 켜지면 시작하며, 하루가 지나면 취소됩니다. | 대기 중 PC 꺼짐 |
| job_runner_pc | core/web/views/transcribe.py:46 | {주인}님의 PC({서버 이름}) | 작업 행·세부 정보 |
| job_runner_pc_gone | core/web/views/transcribe.py:48 | 연결이 끊긴 PC | 서버 삭제 뒤 기록 |
| draft_pc_transcribing | core/notes/services.py:468 | 회의록 초안이 준비된 상태입니다. 전사문은 진행자 PC에서 만드는 중입니다. | draft DM(PC 자동 전사) |
| pc_update_needed | core/api/routers/stt.py:25 | 전사 서버 프로그램이 오래되었습니다. 설치 명령을 다시 실행해 업데이트해 주세요. | heartbeat 426 본문(PC가 출력) |

## 전사 메뉴 "전사 서버" 보기(관리자)

| 키 | 위치 | 임시 문구 | 맥락 |
|---|---|---|---|
| server_view_intro | core/web/templates/orgs/transcribe.html:11 | 회의가 끝나면 진행자의 PC가 켜져 있으면 그 PC로, 아니면 이 서버와 모델로 전사문을 만듭니다. 로컬 전사 서버가 없으면 조직 OpenAI 키로 전사합니다. | 카드 안내 |
| pc_online_count | core/web/templates/orgs/transcribe.html:12 | 멤버 PC 연결 {N}대 켜짐 | 한 줄 |
| server_advanced | core/web/templates/orgs/transcribe.html:16 | 고급 설정 · 조직 전사 서버 주소 직접 입력 | 접힘 제목(기존 칸) |
| setting_member_pc_label/help | core/orgs/settings.py:872 | 멤버 PC로 전사 / 켜면 구성원이 자기 PC에 연결한 전사 서버로 이 조직 녹음을 전사할 수 있습니다. 끄면 대기 중인 PC 전사는 취소됩니다. | 정책 칸 |
| setting_transcribe_level_label/help | core/orgs/settings.py:882 | 조직 전사 수단을 쓸 수 있는 사람 / 조직 전사 서버와 조직 OpenAI 키로 전사를 시작할 수 있는 사람입니다. 멤버는 녹음마다 한 번만 쓸 수 있습니다. | 정책 칸(선택지 "멤버 누구나"/"조직 관리자만") |

## 참여자별 녹음 zip(후속 요청)

| 키 | 위치 | 임시 문구 | 맥락 |
|---|---|---|---|
| tracks_zip | core/web/templates/notes/_tracks_download.html:3 | 참여자별 녹음 한 번에 내려받기(zip) · {N}명 · {총 크기} | 회의록 화면·전사 패널 녹음 칸 |
| tracks_each | core/web/templates/notes/_tracks_download.html:4 | 참여자별로 하나씩 내려받기 | 개별 링크 접힘 제목 |

## 오류 코드 표시(작업 상태 칸)

위치: core/notes/transcription.py:65 `ERROR_LABELS`(키 `job_error_<코드>`), 표시는 core/web/templates/orgs/_transcribe_state.html — 실패는 "⚠ 문구", 취소는 "취소됨 · 문구". 목록에 없는 코드는 "실패".

| 코드 | 임시 문구 | 맥락 |
|---|---|---|
| no_engine | 전사 수단 없음 | 기존 문구 그대로 |
| pc_offline | PC가 꺼져 있음 | 자동 작업 취소·사람이 고른 PC 24시간 대기 끝 |
| pc_unlinked | PC 연결 끊김 | [끊기]·DELETE /self |
| pc_disabled | 멤버 PC 전사 꺼짐 | 조직이 member_pc를 끔 |
| no_access | 볼 수 없는 녹음 | PC 주인이 더는 못 봄 |
| expired | 보관 기간 지남 | 가져갈 때 만료 |
| model_not_ready | PC에 모델 없음 | PC 보고 |
| download_failed | 모델 받기 실패 | PC 보고(계획서 목록) |
| decode_failed | 녹음 읽기 실패 | PC 보고 |
| audio_unavailable | 녹음을 받지 못함 | PC 보고(no_audio도 이것으로 바꿔 저장) |
| out_of_memory | PC 메모리 부족 | 보통 구간 실패로 오지만 작업 코드로 와도 받는다 |
| transcript_too_large | 전사문이 너무 큼 | PC가 413을 받은 뒤 보고 |
| pc_error | PC 오류 | PC 보고·목록 밖 코드 |
