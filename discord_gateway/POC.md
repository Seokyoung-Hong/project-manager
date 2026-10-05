# M0 음성 수신 PoC 실행 절차

IMPL-PLAN-9 §7 M0, 사용자 결정 3(운영 봇 토큰 사용). 운영 서버 `root@172.30.1.30:/opt/project-manager`(VPN 필요)에서 **운영 `discord-bot`(Python 게이트웨이)을 잠시 내리고** 같은 토큰으로 이 컨테이너를 올린다. 실행 직전에 무엇을 내리고 올리는지 사용자에게 알린다.

## 0. 무엇이 멈추나
- 멈춤: 슬래시 명령·DM 명령·채널 자동 관리(watch)·MCP 채널 브리지(8081). 그동안 슬래시 명령은 "응답하지 않았습니다"로 실패한다. 명령 트리는 지워지지 않는다(PoC는 명령을 등록하지 않는다).
- 그대로: `discord`(발송, REST만) — 마감 DM·주간 보고·에스컬레이션은 계속 나간다.

## 1. 준비 (다운타임 없음)
1. 참여자 3명과 시간 약속(35분). 참여자에게 "녹음 PoC, 끝나면 파일 삭제"를 미리 알린다.
2. 음성 채널 id(개발자 모드 → 채널 우클릭 → ID 복사). 길드는 `.env.discord`의 `DISCORD_GUILD_ID`(다르면 `POC_GUILD_ID`). 봇에 그 채널의 보기·연결 권한이 있는지 확인.
3. 이 디렉터리를 서버로 복사(`node_modules`·`poc-out` 제외)하고 출력 폴더 권한을 컨테이너 사용자(uid 1000)에 맞춘다.
   ```sh
   # PC에서
   tar --exclude=node_modules --exclude=poc-out -czf - discord_gateway | ssh root@172.30.1.30 'cd /opt/project-manager && tar xzf -'
   # 서버에서
   cd /opt/project-manager && mkdir -p discord_gateway/poc-out && chown 1000:1000 discord_gateway/poc-out
   ```
4. 이미지를 미리 빌드한다(내린 뒤 기다리지 않게).
   ```sh
   docker compose -p voice-poc -f discord_gateway/compose.poc.yml build
   ```

## 2. 내리기 → 올리기
```sh
cd /opt/project-manager
docker compose stop discord-bot                 # 운영 게이트웨이만 정지(발송 discord는 그대로)
docker compose ps discord-bot discord           # discord-bot: exited, discord: running 확인
POC_CHANNEL_ID=<음성채널id> POC_MINUTES=35 \
  docker compose -p voice-poc -f discord_gateway/compose.poc.yml up -d
docker logs -f voice-poc-voice-poc-1            # ready → voice ready → dave 줄 확인
```
`voice ready`가 30초 안에 안 나오거나 `4017`이 보이면 바로 **4. 원복**.

## 3. 진행 중 확인
- 메모리: `docker stats --no-stream voice-poc-voice-poc-1` (5분마다, MEM USAGE / LIMIT 256MiB). 로그의 `metrics` 줄(60초마다)에 `rss_mb`·`max_rss_mb`·`segments`·`rtp_lost`·`dave_transitions`·`decrypt_failures`가 있다.
  ```sh
  grep '"metrics"' discord_gateway/poc-out/*/poc.log | tail -3
  ```
- 시나리오(30분 안에): 3명 동시 발화, 입장·퇴장 합계 10회 이상, 사람 1명이 다른 음성 채널로 이동했다가 복귀 1회. 가능하면 관리자가 봇을 다른 채널로 끌어 옮기기 1회(봇 이동 재접속 확인, 실패해도 기록만).
- 끝: `POC_MINUTES`가 지나면 스스로 종료하고 `report.json`을 쓴다. 일찍 끝낼 때는 `docker compose -p voice-poc -f discord_gateway/compose.poc.yml stop`(SIGTERM → 리포트 작성).

## 4. 원복 (성공·실패·중단 모두 즉시)
```sh
cd /opt/project-manager
docker compose -p voice-poc -f discord_gateway/compose.poc.yml down
docker compose start discord-bot
docker compose logs --tail 30 discord-bot       # 로그인·명령 sync 확인
```
Discord에서 `/도움`과 DM `오늘` 각 1회 응답 확인. 안 되면 `docker compose up -d discord-bot`.

## 5. 결과 확인
출력: `discord_gateway/poc-out/<시작시각>/` — `report.json`, `poc.log`, `events.jsonl`(입퇴장·이동), `segments.jsonl`(구간 메타), `seg/*.ogg`.
```sh
cat discord_gateway/poc-out/*/report.json
# 모든 구간 파일 디코딩 확인(실패 개수 출력)
docker run --rm --entrypoint sh -v /opt/project-manager/discord_gateway/poc-out:/d voice-poc-voice-poc \
  -c 'n=0; t=0; for f in /d/*/seg/*.ogg; do t=$((t+1)); ffmpeg -v error -xerror -i "$f" -f null - || n=$((n+1)); done; echo "구간 $t개 중 실패 $n개"'
```
몇 개는 PC로 받아 직접 들어 본다(VLC 등). 확인이 끝나면 `rm -rf discord_gateway/poc-out/*`(녹음은 개인정보 — 7일 넘겨 두지 않는다).

## 성공 기준
| 항목 | 기준 | 볼 곳 |
|---|---|---|
| DAVE 접속 | `voice ready`, 4017 없음, `[DAVE] Session initialized for protocol version 1` 이상 | poc.log |
| 참여자 | 3명 이상 각자 구간이 생김 | report.users |
| 길이 | 30분 이상 유지, `end_reason: "time"` | report.minutes |
| 입퇴장 | join+leave 10회 이상, move 1회 이상 기록 | report.voice_events, events.jsonl |
| 메모리 | `max_rss_mb` < 256, `docker stats`에서 한도 근처 없음·OOM 재시작 없음 | report, docker stats |
| 재생 | 디코딩 실패 0개, 표본 청취 정상 | §5 명령 |
| 손실 | 사용자별 `loss_pct` 기록(기준 없음, 5% 넘으면 보고) · `decrypt_failures`·`dave.transitions` 기록 | report |
| 장시간 | 25~30분 구간에도 새 구간이 계속 생김(keepalive 끊김 없음, Pycord #3388 선례) | segments.jsonl의 start_ms |

실패 시 설계서대로 Dysnomia + davey를 검토한다.
