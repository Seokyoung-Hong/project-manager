# 분산 배치 검토 — 열린 망 최소 서버 + 닫힌 망 본 서버

작성 2026-10-13. 코드 변경 없음(검토만). 기준 커밋 `fec18a3`.

## 0. 결론

- **가능. 코드 변경 없이 된다.** 서비스를 쪼개지 않고 compose 묶음 전체를 닫힌 망(아웃바운드만) 서버로 옮기고,
  열린 망에는 TLS 종단 + 리버스 프록시 + 사설망 끝점만 둔다.
- 권장 연결: **(b) WireGuard/Tailscale 사설망 + 열린 망 리버스 프록시가 사설 IP로 프록시.** 닫힌 망이 먼저 나가서
  터널을 맺으므로(keepalive) 닫힌 망에 인바운드 포트가 필요 없다.
- 서비스를 여러 망으로 **쪼개는 것**(web·DB·워커를 서로 다른 곳)은 조건부다. 아래 §5의 제약(단일 인스턴스·로컬 미디어·
  DB 지연)을 먼저 풀어야 하고, 지금 규모에선 이득이 없다.

## 1. 지금의 서비스 간 통신 지도

| 호출자 → 대상 | 주소(기본값) | 설정 위치 | 인증 |
|---|---|---|---|
| web·purge·realtime → db | `postgres://…@db:5432/pm` | compose.yml:37,65,80 (`DATABASE_URL`) | DB 비밀번호, TLS 없음 |
| realtime → db (LISTEN 장기 연결) | 위 설정 재사용 | core/web/realtime/hub.py:96-109, 291 | keepalive 30s/10s×3, 끊기면 재접속+resync |
| discord·discord-bot·discord-voice → web | `http://web:8000` | compose.yml:100,115,135 / .env.discord.example:4 / discord_gateway/gateway.mjs:63 | `CORE_TOKEN` Bearer |
| discord-bot → discord-voice | `http://discord-voice:8082` | compose.yml:118, discord_service/config.py:24,48 | `VOICE_CONTROL_SECRET` |
| mcp → web / → discord-bot | `http://web:8000`, `http://discord-bot:8081` | compose.yml:157-158, mcp_server/core_client.py:6, server.py:87 | 사용자 토큰 Bearer |
| purge(AI 워커) → copilot | `COPILOT_RUNTIME_URL`(예 `copilot:4321`) | settings.py:200-201, .env.example:72 | `COPILOT_CONNECTION_TOKEN` |
| 브라우저 → web / realtime | NPM → `WEB_PORT`, `^~ /rt/` → `RT_PORT` | compose.yml:50, 93 | 세션 쿠키 |
| GitHub → web (웹훅) | `POST /api/github/webhook` | core/api/routers/github.py:38 | `GITHUB_WEBHOOK_SECRET` 서명 |
| 내 PC(udally-link) → web | `SITE_URL` heartbeat 5초 | core/notes/stt_link.py:1-3 | 기기 토큰. **들어오는 연결 없음** |
| Discord | 봇이 게이트웨이로 **나가서** 붙음 | discord_service listener, discord_gateway | 인바운드 엔드포인트 없음(verify_key·interactions 엔드포인트 코드 없음) |
| web → GitHub·Discord·OpenAI·HF | 외부 HTTPS(아웃바운드) | — | — |

- 하드코딩된 내부 이름은 전부 환경변수 기본값이다(`CORE_URL`, `VOICE_URL`, `DISCORD_CONTROL_URL`, `DATABASE_URL`). 코드에 박힌 것 없음.
- **인바운드가 필요한 것은 브라우저 요청·GitHub 웹훅·udally-link heartbeat·OAuth 콜백(브라우저 리다이렉트) 뿐이고 모두 같은 도메인의 HTTPS다.**
  Discord는 아웃바운드만 쓴다. → 열린 망은 "도메인 하나의 HTTPS 프록시"면 충분하다.

## 2. 열린 망에 꼭 있어야 하는 것(최소 집합)

- TLS 종단 + 리버스 프록시(NPM 또는 Caddy/nginx): `/` → web 8000, `^~ /rt/` → realtime 8082(WS 업그레이드), (mcp 켤 때) → 8080.
- 사설망 끝점: WireGuard면 UDP 포트 1개 공개, Tailscale이면 공개 포트 불필요(DERP 중계 폴백).
- 웹훅·OAuth 콜백·SSE/WS **종단은 닫힌 망의 앱**이다. 열린 망은 바이트만 넘긴다(애플리케이션 상태 없음).
- 메모리: nginx/Caddy 단독 수십 MB, NPM(Node+자체 DB)은 수백 MB 수준 → **512MB~1GB VPS 1대**면 충분. 비용은 저가 VPS 등급(월 수 달러대). 정확한 가격 확인 불가.
- 대역폭: 모든 응답이 열린 망을 두 번 지난다(닫힌→열린→사용자). 첨부 25MB 다운로드가 잦으면 VPS 송신량 요금 확인 필요.
- 이미 집(house)의 NPM(nginx.house.sio2.kr)이 열린 망 역할을 하고 있다면 **새 VPS 없이 그 NPM이 사설 IP로 프록시만 바꾸면 된다.**

## 3. 닫힌 망으로 옮길 것

- **전부 한 묶음으로**: db·web·realtime·purge(AI 워커 포함)·discord×3·mcp·copilot. compose.yml 그대로.
- **DB도 닫힌 망, web과 같은 호스트에 둔다.** Django 화면은 요청당 쿼리가 여러 번이라 web↔DB 사이 RTT가 곱으로 쌓인다.
  realtime의 LISTEN 연결(hub.py:291)도 같은 호스트면 끊길 일이 거의 없다.
- 백업: scripts/backup.sh:21(pg_dump)·:26(media·discord 볼륨)은 닫힌 망에서 그대로 돈다. 외부 보관은 **아웃바운드 push**(rclone·restic 등)로. 닫힌 망 장애 대비 열린 망 VPS를 백업 보관처로 겸할 수 있다.

## 4. 연결 방식 비교

| | (a) 역방향 터널(frp·rathole·cloudflared·Tailscale Funnel) | (b) WireGuard/Tailscale 사설망 + 열린 망 프록시 | (c) 앱 수준 폴링(udally-link식) |
|---|---|---|---|
| 코드 변경 | 없음(cloudflared는 compose.yml:187 `tunnel` 프로필로 이미 있음) | 없음(.env 바인드 주소만) | 웹 전체를 다시 짜야 함 |
| 실시간 WS/SSE | 지원(frp·cloudflared 모두 WS 통과) | L3라 그대로 | 불가(요청마다 폴링 왕복) |
| 큰 업로드 | 첨부 25MB 통과. 녹음 300MB(notes/services.py:666)는 discord-voice→web **내부 호출**이라 터널을 안 지남 | 같음 | 부적합 |
| 웹훅 지연 | 터널 RTT만 추가 | 같은 수준 | 폴링 주기만큼 지연 |
| 장애 | 터널 클라이언트 1개가 전 트래픽을 다중화 → 그 연결이 끊기면 전체 중단(재접속까지) | WG는 상태 없는 UDP, keepalive로 즉시 복구. 끊겨도 프록시가 502 후 복구 | — |
| 보안 | frps 제어 포트·토큰 관리 필요. cloudflared는 TLS가 Cloudflare에서 풀림(평문이 제3자 경유 → 처리방침·국외이전 문구 영향) | 프록시만 공개. 앱 포트는 사설 IP에만 바인드 | — |
| 판단 | 차선. 프록시를 따로 둘 수 없을 때(cloudflared) | **권장** | 웹엔 부적합. 지금처럼 PC 전사 연결에만 |

- frp를 '내 PC 연결'에서 폐기한 이유는 **불특정 다수 사용자 PC마다 공개 주소를 내주는 구조**였기 때문이다(10-13 결정). 이번은
  **우리 서버 2대 사이 고정 링크**라 그 이유는 해당하지 않는다. 다만 (b)가 같은 일을 더 단순하게(포트 여러 개를 L3로) 해서 (a)를 고를 이유가 적다.

## 5. 외부망으로 나눌 때 막히는 것(쪼개는 경우에만 해당)

권장안(전부 닫힌 망 한 곳)에서는 아래가 문제 되지 않는다. 서비스를 여러 망으로 쪼갤 때만 풀어야 한다.

1. **앱 포트의 신뢰 경계.** `SECURE_PROXY_SSL_HEADER`(settings.py:140), gunicorn `--forwarded-allow-ips="*"`(core/entrypoint.sh:12),
   uvicorn `--forwarded-allow-ips "*"`(compose.yml:84-85), 로그인 잠금이 XFF 맨 오른쪽 값을 IP로 셈(core/accounts/auth.py:50-53).
   → 8000·8082에 프록시 말고 누가 닿으면 https 위장·IP 잠금 우회가 된다. **사설 IP에만 바인드**가 필수(OPERATIONS-DEPLOYMENT.md:59).
   `SECURE_SSL_REDIRECT`를 끈 이유(settings.py:146-148)도 내부 평문 호출 전제다.
2. **DB를 망 밖에 열기.** compose DB는 TLS 없음(compose.yml:15-31). 열려면 `sslmode=require`·pg_hba 제한·사설망 필수.
   realtime LISTEN은 장기 연결이라 NAT 유휴 타임아웃에 취약(keepalive는 있음, hub.py:105-108). 쿼리 RTT 누적.
3. **미디어 로컬 디스크.** `MEDIA_ROOT`가 FileSystemStorage(settings.py:115-120, compose.yml:38-40). web 인스턴스가 둘 이상이면 공유 저장소(S3 호환 등) 필요.
4. **단일 인스턴스 전제.**
   - purge: `github_reconcile`·`purge_expired`에 잠금 없음(run_periodic.py:11-26) → 두 곳에서 돌면 중복 실행. AI 워커 `claim`은 SKIP LOCKED라 안전(assist/worker.py:96).
   - AI 워커 `sweep`이 `claimed_at`과 각 호스트 `timezone.now()`를 비교(worker.py:381-410) → 호스트 간 **시계 동기(NTP)** 필요.
   - realtime: 연결 상태가 프로세스 메모리(hub.py, `--workers 1`, compose.yml:82-84). 여러 대면 SSE/폴링에 스티키 세션 필요.
   - Discord: 봇 토큰당 게이트웨이 세션 고정(discord-bot 1 + discord-voice 1) → 각각 한 곳에서만.
5. **내부 평문 HTTP.** CORE_TOKEN·VOICE_CONTROL_SECRET·COPILOT_CONNECTION_TOKEN이 `http://`로 오간다. 망을 건너면 사설망 안이거나 HTTPS여야 한다.
   copilot 런타임은 토큰이 비면 "같은 망의 누구나" 붙는다(compose.yml:176).

세션은 DB 세션(settings.py:132)이고 캐시 백엔드 미설정(기본 로컬 메모리)이라 세션 공유 문제는 없다. 캐시를 공유 상태로 쓰는 곳이 있는지는 확인 불가.

## 6. 권장안과 이행 계획

**권장안**: 열린 망 = NPM(또는 Caddy) + WireGuard/Tailscale. 닫힌 망 = 현재 compose 전체.

단계:
1. 열린 망 준비: 기존 house NPM을 쓰거나 VPS 1대(512MB~1GB). 사설망(Tailscale 또는 WG, 닫힌 쪽 `PersistentKeepalive=25`)으로 두 서버 연결, 사설 IP 핑 확인.
2. 닫힌 망 서버에 Docker 설치, 코드는 지금처럼 git archive로 풀기, `.env`·`.env.discord` 복사.
   `.env`: `WEB_PORT=<사설IP>:8000`, `RT_PORT=<사설IP>:8082`, (mcp) `MCP_PORT=<사설IP>:8080`. compose.yml:30-31의 db 포트 두 줄 삭제(기존 지침).
3. 시험 기동: `discord` 프로필 **빼고** 올려(게이트웨이 중복 방지) 임시 호스트명으로 프록시해 로그인·/rt/ws·첨부 25MB 확인.
4. 전환(점검 창): 기존 LXC에서 web·purge·discord 정지 → backup.sh로 마지막 덤프·볼륨 → 닫힌 망에 복원(pg_restore, media 볼륨) → 전체 기동 →
   NPM 프록시 대상(호스트 76의 `/` 및 `^~ /rt/`)을 사설 IP로 변경. 새 VPS라면 DNS A 레코드·인증서도.
5. 검증: 로그인, 실시간 반영, GitHub 웹훅 재전송(Recent Deliveries → Redeliver), Discord DM·회의 녹음 업로드, udally-link heartbeat, MCP.
6. 기존 LXC는 1~2주 정지 상태로 보존.

롤백: NPM 대상을 기존 LXC로 되돌리고 기존 compose 기동. **전환 후 닫힌 망에 쌓인 데이터는 덤프해 되돌려야** 잃지 않는다 → 전환 창을 짧게, 롤백 시 역방향 덤프·복원 절차를 같이 적어 둔다.
GitHub 웹훅이 전환 중 실패해도 `github_reconcile`(5분)이 보정한다(run_periodic.py:11).

## 7. 최소 변경 목록

| 대상 | 내용 | 작업량 |
|---|---|---|
| 운영 `.env` | `WEB_PORT`·`RT_PORT`·`MCP_PORT`를 사설 IP 바인드로(compose.yml:50,93,170이 `IP:포트` 형식을 이미 받음) | 수 분 |
| compose.yml:30-31 | 서버에서 db 포트 줄 삭제(기존 지침 그대로) | 수 분 |
| NPM | 프록시 대상 IP 변경, `client_max_body_size 26m`(OPERATIONS-DEPLOYMENT.md:64), `/rt/` WS·긴 read timeout 유지 | 30분 |
| docs/OPERATIONS-DEPLOYMENT.md:59,62 | "프록시 IP만 허용" → "사설 IP에만 바인드" 문구 보강, 사설망 절 추가 | 30분 |
| scripts/backup.sh | 외부 보관 push 한 줄(선택) | 30분 |
| 코드 | **없음** | — |

쪼개기까지 갈 때만(지금은 비권장): purge 단일 실행 잠금(Postgres advisory lock, run_periodic.py), 미디어 S3 저장소(settings.py:115-120), DB TLS(`DATABASE_URL`에 `sslmode=require`), realtime 스티키 세션 — 각 반나절~수일.

위험:
- 닫힌 망 서버의 아웃바운드가 끊기면 서비스 전체 중단(지금 LXC 단일 장애점과 같은 수준). 열린 망 VPS가 단일 장애점으로 하나 더 늘어난다.
- 사설망 RTT만큼 모든 요청 지연 증가(국내 수~수십 ms 예상, 실측 필요).
- 8000·8082가 사설 IP 외에 노출되면 §5-1의 헤더 위장이 열린다 — 바인드 확인을 검증 항목에 넣는다.
- 전환 중 Discord 봇이 두 곳에서 동시에 뜨면 게이트웨이 세션 충돌·중복 발송.

## 8. 확인 불가

- 닫힌 망 서버의 실제 아웃바운드 정책(UDP 허용 여부 → WG 직결 vs Tailscale DERP 중계·지연).
- 두 서버 간 실제 RTT와 VPS 송신량 요금.
- cloudflared 경유 시 X-Forwarded-For 맨 오른쪽 값이 실제 클라이언트 IP인지(로그인 잠금 정확도).
- 장고 캐시를 공유 상태로 쓰는 코드가 있는지(전수 검색 안 함).
