# 구현 지시서 04: 배포 (Proxmox + Docker Compose + Cloudflare Tunnel)


> **이 문서는 2026-09-10에 끝난 최초 구축의 기록이다.** 지금 할 일은 [GUIDE-V2-00-overview.md](GUIDE-V2-00-overview.md)부터 시작하는 묶음이다. 이 문서에 나오는 `Team`·`teams`·"팀"은 2026-09-11 개명 전 용어로 **조직**을 뜻한다. 대조표는 [GUIDE-V2-01](GUIDE-V2-01-org-teams.md) §1에 있다.

GUIDE-00을 먼저 읽는다. 이 문서는 저장소 루트의 `compose.yml`, `.env.example`, `.env.discord.example`, `README.md`, core의 Dockerfile을 만들고 Proxmox에 올리는 절차다. Discord·MCP의 Dockerfile은 각 GUIDE에서 이미 만들었다.

서버는 어떤 포트도 외부에 열지 않는다. Cloudflare Tunnel(`cloudflared` 컨테이너)이 바깥에서 들어오는 HTTPS를 내부 컨테이너로 넘긴다. TLS는 Cloudflare가 끝낸다.

---

## Step 1. core Dockerfile과 entrypoint

`core/Dockerfile`:

```dockerfile
FROM python:3.12-slim
COPY --from=ghcr.io/astral-sh/uv:latest /uv /usr/local/bin/uv
WORKDIR /app
COPY pyproject.toml uv.lock ./
RUN uv sync --frozen --no-dev
COPY . .
ENV PATH="/app/.venv/bin:$PATH" PYTHONUNBUFFERED=1 DJANGO_SETTINGS_MODULE=config.settings
RUN chmod +x entrypoint.sh
EXPOSE 8000
ENTRYPOINT ["./entrypoint.sh"]
```

`core/entrypoint.sh`:

```sh
#!/bin/sh
set -e
python manage.py migrate --noinput
python manage.py collectstatic --noinput
# SSE(/events)가 연결을 열어 두므로 스레드 워커를 쓴다. sync 워커는 연결 하나가 워커를 통째로 막는다.
# --timeout은 스트림 수명(web/views/events.py의 STREAM_SECONDS=50초)보다 길어야 한다.
exec gunicorn config.wsgi:application \
  --bind 0.0.0.0:8000 --worker-class gthread --workers 2 --threads 16 --timeout 90 \
  --forwarded-allow-ips="*" --access-logfile - --error-logfile -
```

`core/.dockerignore`:

```
.venv/
db.sqlite3
staticfiles/
__pycache__/
.pytest_cache/
.ruff_cache/
```

---

## Step 2. `compose.yml` (저장소 루트)

```yaml
services:
  db:
    image: postgres:16-alpine
    environment:
      POSTGRES_DB: pm
      POSTGRES_USER: pm
      POSTGRES_PASSWORD: ${POSTGRES_PASSWORD:-pm}
    volumes:
      - pgdata:/var/lib/postgresql/data
    healthcheck:
      test: ["CMD-SHELL", "pg_isready -U pm -d pm"]
      interval: 5s
      timeout: 3s
      retries: 20
    restart: unless-stopped     # 없으면 호스트 재부팅 뒤 db만 내려가 web이 migrate에서 크래시 루프한다.
    ports:
      - "127.0.0.1:5432:5432"   # 로컬 개발·테스트용. 서버에서는 이 두 줄을 지운다.

  web:
    build: ./core
    env_file: .env               # 봇 토큰·CORE_TOKEN은 여기 없다(.env.discord에만 있다)
    environment:
      DATABASE_URL: postgres://pm:${POSTGRES_PASSWORD:-pm}@db:5432/pm
    depends_on:
      db:
        condition: service_healthy
    restart: unless-stopped

  discord:                       # 발송(60초 틱): 마감 DM·주간 보고
    build: ./discord_service
    env_file: .env.discord
    environment:
      CORE_URL: http://web:8000
      DB_PATH: /data/discord.sqlite
    volumes:
      - discord_data:/data
    depends_on:
      - web
    restart: unless-stopped

  discord-bot:                   # 수신(게이트웨이): DM 평문 명령. 같은 이미지, 리스너만 돈다
    build: ./discord_service
    env_file: .env.discord
    environment:
      CORE_URL: http://web:8000
    command: ["python", "-m", "discord_service", "bot"]
    depends_on:
      - web
    # 볼륨 없음: 리스너는 SQLite를 열지 않는다(발송 프로세스가 단일 writer로 남는다).
    restart: unless-stopped

  mcp:
    build: ./mcp_server
    environment:
      CORE_URL: http://web:8000
      PORT: "8080"
    depends_on:
      - web
    restart: unless-stopped

  cloudflared:
    image: cloudflare/cloudflared:latest
    command: tunnel --no-autoupdate run
    environment:
      TUNNEL_TOKEN: ${CLOUDFLARE_TUNNEL_TOKEN}
    depends_on:
      - web
      - mcp
    restart: unless-stopped

volumes:
  pgdata:
  discord_data:
```

`discord`·`discord-bot`은 `CORE_TOKEN`·`DISCORD_BOT_TOKEN`·`DISCORD_CHANNEL_ID`가 준비되기 전에는 시작 직후 종료된다(`Config.from_env`의 환경 변수 검사). 그동안은 `docker compose up -d db web mcp cloudflared`처럼 골라서 띄운다.

**단, 두 환경 파일은 골라서 띄울 때도 다 있어야 한다.** compose는 명령 대상이 아닌 서비스의 `env_file`까지 모델을 읽을 때 확인하고, 없으면 `env file … not found`로 전체가 멈춘다. 그래서 첫 준비는 항상 두 줄이다: `cp .env.example .env && cp .env.discord.example .env.discord`(내용은 나중에 채워도 된다).

환경 파일이 둘인 이유는 **비밀의 반경**이다. `web`이 `.env.discord`를 읽으면 Discord 봇 토큰과 `CORE_TOKEN`이 gunicorn 프로세스 환경에 들어가고, 그 프로세스는 사용자 요청을 처리한다. 나눠 두면 core는 그 두 값을 볼 일이 없다(GUIDE-00 §3). compose의 `${}` 보간에 쓰이는 `POSTGRES_PASSWORD`·`CLOUDFLARE_TUNNEL_TOKEN`은 `.env`에 남는다 — 보간은 compose 자신이 루트 `.env`만 읽는다.

컨테이너가 둘인 이유는 **SQLite writer가 하나여야** 하기 때문이다. 같은 이미지에서 `discord`는 틱(발송)을, `discord-bot`은 게이트웨이 리스너(수신)를 돈다. 리스너는 `Store`를 만들지 않으므로 볼륨이 없다. `discord`를 replicas 2로 올리면 중복 방지가 깨진다.

---

## Step 3. `.env.example`과 `.env.discord.example` (저장소 루트)

`.env.example`:

```
# --- core (web) ---
SECRET_KEY=change-me-to-a-long-random-string
DEBUG=0
# `web`는 compose 내부 호출용(mcp·discord가 http://web:8000 으로 부른다). 빼면 그 요청이 400이 된다.
ALLOWED_HOSTS=pm.example.com,web
CSRF_TRUSTED_ORIGINS=https://pm.example.com
SITE_URL=https://pm.example.com
POSTGRES_PASSWORD=change-me

# --- cloudflared ---
CLOUDFLARE_TUNNEL_TOKEN=eyJ...

# discord_service의 설정은 이 파일에 없다. `.env.discord.example` → `.env.discord`를 쓴다.
# Discord 봇 토큰과 CORE_TOKEN이 web 프로세스의 환경에까지 들어가지 않게 나눠 둔 것이다.
```

`.env.discord.example`:

```
# discord·discord-bot 컨테이너 전용. `.env.discord`로 복사해 채운다(git에 올리지 않는다).
# 이 파일의 두 비밀(DISCORD_BOT_TOKEN, CORE_TOKEN)은 core DB·화면·로그·/ops 어디에도 없다.

CORE_URL=http://web:8000
# discord-bot 계정의 `bot` 범위 토큰. 그 계정은 팀 **멤버**면 된다(관리자 승격 불필요).
# 발급은 서버 셸 한 줄로만 한다 — 웹 화면에서는 bot 범위를 만들 수 없다(Step 7).
CORE_TOKEN=pm_xxx
TEAM_ID=1

# Developer Portal → Bot → [Reset Token]. 이때 한 번만 보인다. 이 파일 밖으로 내보내지 않는다.
DISCORD_BOT_TOKEN=
# 주간 보고와 'DM을 보낼 수 없다' 통보가 갈 채널 id(개발자 모드 → 채널 우클릭 → ID 복사).
# 비밀이 아니지만 없으면 컨테이너가 기동하지 않는다(Config.need).
DISCORD_CHANNEL_ID=

TZ=Asia/Seoul
SEND_HOUR=9
WEEKLY_WEEKDAY=0
WEEKLY_HOUR=9
LLM_PROVIDER=
SITE_NAME=유달리
```

`.env`도 `.env.discord`도 git에 넣지 않는다(`.gitignore`에 둘 다 있음).

---

## Step 4. 로컬 실행 확인

저장소 루트에서:

```bash
cp .env.example .env
cp .env.discord.example .env.discord   # 비어 있어도 된다. 없으면 compose가 파일 전체를 못 읽는다.
# .env에서 DEBUG=1  ALLOWED_HOSTS=localhost,127.0.0.1,web
#          CSRF_TRUSTED_ORIGINS=http://localhost:8000,http://127.0.0.1:8000
#          SITE_URL=http://localhost:8000  으로 바꾼다.
docker compose up -d --build           # db·web·mcp. discord·cloudflared는 프로필이라 안 뜬다
docker compose exec web python manage.py createsuperuser
docker compose logs -f web
```

`db`·`web`·`mcp`는 `127.0.0.1`에만 포트를 연다(`5432`·`8000`·`8080`). 루프백이라 밖에서는 못 들어오고,
공개는 `cloudflared`가 한다 — 그래서 서버에서도 이 줄들을 지울 필요가 없다.

시크릿이 필요한 세 서비스는 프로필로 빼 두었다. 없는 상태로 `up` 하면 `Config.need`가
`SystemExit`을 내고 `restart: unless-stopped`가 크래시 루프를 만들기 때문이다:

| 프로필 | 서비스 | 켜기 전에 채울 것 |
|---|---|---|
| `discord` | `discord`, `discord-bot` | `.env.discord`의 `CORE_TOKEN`·`DISCORD_BOT_TOKEN`·`DISCORD_CHANNEL_ID` |
| `tunnel` | `cloudflared` | `.env`의 `CLOUDFLARE_TUNNEL_TOKEN` |

`docker compose --profile discord up -d` 또는 이름을 직접 대서(`docker compose up -d discord`) 켠다.
이름을 대면 프로필이 자동으로 켜지므로 Step 7의 배포 명령은 그대로 쓸 수 있다.

확인:

- `docker compose exec web python manage.py check` 오류 없음.
- 호스트에서 `curl -s http://127.0.0.1:8000/healthz` → `{"ok": true}`. 브라우저로 `http://localhost:8000/login`.
- core 테스트를 Postgres로: `cd core && DATABASE_URL=postgres://pm:pm@127.0.0.1:5432/pm uv run pytest -q` 통과.
- SQLite로 개발하던 데이터를 옮기려면 `dumpdata`(`--exclude contenttypes --exclude auth.permission --exclude sessions`) 후
  `docker compose exec -T web python manage.py loaddata --format=json - < devdata.json`. 비밀번호 해시가 함께 넘어와 기존 계정으로 로그인된다.

---

## Step 5. Proxmox 서버 준비

1. Proxmox에서 Debian 12 LXC 컨테이너 생성: CPU 2, 메모리 2 GB, 디스크 20 GB, **Options → Features에서 `nesting=1`, `keyctl=1`** 켜기(Docker 실행에 필요). 비특권 컨테이너 권장.
2. 컨테이너 안에서 Docker 설치:

```bash
apt-get update && apt-get install -y ca-certificates curl git
install -m 0755 -d /etc/apt/keyrings
curl -fsSL https://download.docker.com/linux/debian/gpg -o /etc/apt/keyrings/docker.asc
echo "deb [arch=$(dpkg --print-architecture) signed-by=/etc/apt/keyrings/docker.asc] https://download.docker.com/linux/debian $(. /etc/os-release && echo $VERSION_CODENAME) stable" > /etc/apt/sources.list.d/docker.list
apt-get update && apt-get install -y docker-ce docker-ce-cli containerd.io docker-compose-plugin
docker run --rm hello-world
```

3. 저장소를 `/opt/project-manager`에 복사(git 원격이 없으므로 `scp` 또는 `rsync`). `.venv/`, `db.sqlite3`는 복사하지 않는다.

---

## Step 6. Cloudflare Tunnel

공개하는 방법은 둘 중 하나다. 어느 쪽이든 Django 설정은 같다(`SECURE_PROXY_SSL_HEADER`가 `X-Forwarded-Proto`를 읽는다).

| 방법 | `web` 포트 바인딩 | 쓰는 때 |
|---|---|---|
| **Cloudflare Tunnel** (`cloudflared` 컨테이너) | `127.0.0.1:8000:8000` | 서버에서 어떤 포트도 열고 싶지 않을 때. 아래 절차 |
| **외부 리버스 프록시** (NginxProxyManager 등, 다른 장비) | `8000:8000` | 이미 프록시 장비가 있을 때. 방화벽에서 **프록시 IP만** 8000번을 연다 |

현재 `compose.yml`은 두 번째(`8000:8000`)로 되어 있다. 첫 번째로 가려면 `web`의 `ports`를 `"127.0.0.1:8000:8000"`으로 되돌리고 `CLOUDFLARE_TUNNEL_TOKEN`을 채운 뒤 `--profile tunnel`로 띄운다.

외부 리버스 프록시 쪽 설정(NginxProxyManager 입력값, `.env` 도메인 셋, 방화벽)은 [GITHUB-APP-SETUP.md](GITHUB-APP-SETUP.md) §4에 정리되어 있다. `mcp`를 외부에 공개해야 하면 같은 방식으로 `mcp` 서비스의 포트도 열고 별도 도메인을 붙인다.

아래는 Cloudflare Tunnel 절차다.


Cloudflare 대시보드 → Zero Trust → Networks → Tunnels:

1. **Create a tunnel** → Cloudflared → 이름 `udally` → 나오는 토큰(`eyJ...`)을 `.env`의 `CLOUDFLARE_TUNNEL_TOKEN`에 넣는다.
2. **Public Hostname** 두 개 추가:

| Subdomain | Domain | Service |
|---|---|---|
| `pm` | `<도메인>` | `HTTP` `web:8000` |
| `mcp` | `<도메인>` | `HTTP` `mcp:8080` |

`web`, `mcp`는 compose 네트워크의 서비스 이름이다. cloudflared 컨테이너가 같은 네트워크에 있으므로 그대로 닿는다.

**공개 호스트네임은 Discord 봇을 붙여도 두 개 그대로다.** 게이트웨이 봇은 Discord로 **나가는** 연결(WebSocket + REST)만 쓰고, Cloudflare Tunnel은 들어오는 트래픽만 다룬다 — 터널이 해 줄 일이 없다. 그래서 이 배포에는 다음이 **존재하지 않는다**: 세 번째 공개 경로(`dc.<도메인>`), 그 경로의 TLS, Ed25519 서명 검증(`DISCORD_PUBLIC_KEY`·pynacl), CSRF 면제 raw-body 뷰, 그리고 "Discord가 인터랙션 URL을 조용히 지웠다"는 실패 모드. HTTP 인터랙션 엔드포인트를 쓰면 그 넷이 전부 딸려 오는데, 마감 DM에는 **여전히 봇 토큰이 필요하다**(인터랙션 토큰은 그 대화 15분용) — 부품만 늘어난다.

3. (선택) Security → WAF → Rate limiting rules: `(http.request.uri.path in {"/login" "/signup"})` 를 IP당 1분 20회로 제한.
4. (선택) Zero Trust → Access → Applications 로 `pm.<도메인>/admin/*` 에 이메일 인증을 걸 수 있다. 지금은 하지 않는다.

---

## Step 7. 서버에서 기동

```bash
cd /opt/project-manager
cp .env.example .env && nano .env      # 실제 값 입력. SECRET_KEY는 `python3 -c "import secrets;print(secrets.token_urlsafe(50))"`
cp .env.discord.example .env.discord   # 봇 토큰·CORE_TOKEN은 아래 3~4번에서 채운다
# 포트는 셋 다 127.0.0.1에만 붙는다 — 지울 필요 없다(밖에서는 못 들어온다)
docker compose up -d --build db web mcp cloudflared
docker compose exec web python manage.py createsuperuser
docker compose logs --tail=50 web cloudflared
```

브라우저에서 `https://pm.<도메인>/healthz` → `{"ok": true}`. `https://pm.<도메인>/login` 열림.

초기 데이터:

1. superuser로 `/signup`이 아닌 `/login`으로 들어가 `/teams/new`에서 팀 생성(예: 산돌이 서비스). 만든 사람이 관리자가 된다.
2. `/teams/<id>/members`(팀원 관리)에서 초대 링크 발급 → 팀원에게 전달. 팀원은 `/signup` 후 링크로 참여.
3. Discord 앱 준비(운영자 1회, 브라우저): Developer Portal → 앱 생성 → **Bot** 페이지 → `[Reset Token]` → 토큰을 `.env.discord`의 `DISCORD_BOT_TOKEN`에. **이때 한 번만 보인다.** 켤 특권 인텐트는 **없다**(`DIRECT_MESSAGES`는 비특권이고, 봇에게 온 DM의 본문은 MESSAGE_CONTENT 없이 전달된다). APPLICATION ID·PUBLIC KEY는 필요 없다(인터랙션 엔드포인트를 쓰지 않는다). Installation → **Guild Install만**, scope `bot` + `applications.commands`, permissions `VIEW_CHANNEL | SEND_MESSAGES = 3072` → 설치 링크로 팀 서버에 추가. 팀원 전원이 그 서버에 참여하고 **서버 우클릭 → 개인정보 보호 설정 → '서버 멤버의 DM 허용'을 켠다**(꺼져 있으면 `50007`로 영구 거부다 — 봇은 친구 추가가 안 되므로 '친구만'은 하드 블록). 개발자 모드를 켜고 주간 보고 채널의 ID를 복사해 `DISCORD_CHANNEL_ID`에.
4. Discord 연동 계정: `/signup`으로 `discord-bot` 계정 생성 → 초대 링크로 팀 참여. **팀원(member)이면 된다** — 관리자로 올리지 않는다. 마감 스캔이 그 계정의 팀 범위 GET을 쓰므로 멤버십 자체는 필요하다. 토큰은 웹에서 만들 수 없다(`bot` 범위 자기 발급 = 권한 상승). 서버 셸 한 줄로 발급한다:

   ```bash
   docker compose exec web python manage.py shell -c "from accounts.models import ApiToken,User; print(ApiToken.issue(User.objects.get(username='discord-bot'),'Discord 봇','bot')[1])"
   ```

   출력값을 `.env.discord`의 `CORE_TOKEN`에 넣고 `TEAM_ID`를 확인한 뒤 `docker compose up -d discord discord-bot`.
5. 채널 확인: `docker compose exec discord python -m discord_service test` → 지정 채널에 확인 메시지. 실패하면 permissions(3072)나 채널 id를 본다. 리스너 확인: `docker compose logs -f discord-bot`에 `discord 봇 접속`이 찍힌 뒤 봇에게 DM으로 `도움`을 보내면 명령 목록이 답장으로 온다.
6. 각자 Discord 연결: 웹 `/settings/profile` → **[Discord 연결]** → 8자 코드 → Discord에서 봇에게 DM으로 `연결 A3F19C2D`(10분 안에). `/teams/<id>/members`에서 전원이 '연결'로 바뀌는지 확인한다. **마이그레이션이 기존 `discord_user_id`를 전부 비우므로(증명되지 않은 손입력 값), 전원이 연결을 마치기 전까지 개인 DM 알림은 0건이다 — 배포 전에 팀에 공지한다.**
7. 리허설: `docker compose exec discord python -m discord_service deadlines --date <오늘>` → 담당자 DM 도착 + `python -m discord_service status`의 `sent` 행 확인.
8. 각자 `/settings/tokens`에서 개인 토큰 발급 후 GUIDE-03 Step 5 표대로 AI 클라이언트 연결. MCP URL은 `https://mcp.<도메인>`.

배포 시각 제약은 **없다**. 마감 잡은 `store.claim_daily("deadline", 오늘)`이 하루 1회로 막고 그 행은 `discord_data` 볼륨에 남는다 — 그날 이미 돌았으면 새 코드가 건너뛰고, 안 돌았으면 새 키로 한 번 돈다. 옛 중복 방지 키는 아무도 읽지 않는 죽은 행이 된다.

`teams 0003`(웹훅 모델 삭제)은 **되돌릴 수 없다.** 등록해 둔 주소가 필요하면 배포 전에 `/ops` 내보내기로 백업한다.

봇 토큰이 유출되면: 포털 `[Reset Token]` → `.env.discord` 수정 → `docker compose up -d discord discord-bot`. 겹치는 유효 창이 없어 그사이 알림이 끊긴다.

---

## Step 8. 상태 확인과 갱신

- UptimeRobot(무료)에 `https://pm.<도메인>/healthz` HTTP 모니터를 5분 간격으로 등록. 알림은 이메일로 받는다.
- `/ops`(superuser)에서 `discord` 통합의 마지막 실행과 결과를 본다. `detail`에 `sent`·`skipped`·`failed`·`unknown`·`unlinked`가 들어 있다. **`unlinked`는 실패가 아니다**(`ok`는 `failed == 0`로 판정한다) — 한 명이 연결을 안 했다고 `/ops`가 영구 빨강이 되면 그 신호를 아무도 안 보게 된다. `failed`가 있으면 `detail`의 Discord 오류 코드를 본다(`50007`·`50278`·`10013`이면 그 사람의 DM 설정이다. 팀 채널에도 하루 한 번 안내가 간다).
- 리스너는 `/ops`에 보고하지 않는다(`IntegrationStatus.name`이 단일 키라 틱의 `discord` 행을 덮어쓴다). 상태는 `docker compose logs discord-bot`으로 보고, 재접속은 discord.py + `restart: unless-stopped`가 맡는다.
- 발송 기록 상세: `docker compose exec discord python -m discord_service status`(최근 `runs`·`sent`·`weekly`).
- 코드 갱신: 파일 복사 후 `docker compose up -d --build`. 마이그레이션은 entrypoint가 자동 실행.
- 백업은 후속 과제다. 그때까지 Proxmox의 Datacenter → Backup에서 이 컨테이너를 매일 다른 스토리지로 vzdump 하도록 예약해 둔다.
- 월 1회: 각 파트에서 `uv lock --upgrade` 후 테스트 → 재빌드.

---

## Step 9. 루트 `README.md`

루트 `README.md`는 이미 목업 핸드오프 문서다. **지우지 말고 맨 앞에 "실행 안내" 절을 덧붙인다.** 기존 내용은 그 아래 "디자인 핸드오프" 제목으로 그대로 둔다. 덧붙일 내용:

1. 한 줄 소개와 세 파트(`core`, `discord_service`, `mcp_server`) 역할.
2. 문서 링크: `PLAN.md`, `docs/IMPL-PLAN.md`, `docs/SPEC.md`, `docs/GUIDE-*.md`.
3. 로컬 개발 빠른 시작: `cd core && uv sync && uv run python manage.py migrate && uv run python manage.py runserver`, 테스트 명령.
4. Docker 로컬 실행(Step 4)과 서버 배포(Step 5~7) 요약, 자세한 건 이 문서로 링크.
5. 환경 변수 표(`.env.example`과 `.env.discord.example` 항목 설명. 두 파일로 나눈 이유 한 줄 포함).
6. 목업 보는 법: 루트에서 `python -m http.server 8765` 후 `유달리 업무 목업 v2.dc.html` 열기.

---

## 완료 체크

- [x] `docker compose build` 세 이미지 모두 성공 (web 376MB · mcp 308MB · discord 269MB. `discord`와 `discord-bot`은 같은 이미지다)
- [x] 로컬에서 `db web mcp` 기동 후 `/healthz` OK, Postgres 16으로 core 테스트 통과
- [ ] Proxmox LXC 기동·`https://pm.<도메인>/healthz`  ← 사용자 인프라 필요
- [x] 팀 생성 → 초대 링크 발급 → 새 계정 가입 → 참여까지 실행 중 서버에서 확인 (참여 후 프로젝트 레일에 팀 프로젝트가 보이고 '초대 링크가 필요합니다' 안내가 사라진다)
- [x] 팀원 관리 화면에서 역할 변경·제거·초대까지 브라우저에서 확인
- [x] 프로필의 **[Discord 연결]**로 코드가 한 번만 노출되고, `/teams/<id>/webhooks`가 404이며, 웹에서 `bot` 범위 토큰을 만들 수 없다
- [x] `.env`와 `.env.discord`가 나뉘어 있고 `web` 컨테이너 환경에 `DISCORD_BOT_TOKEN`이 없다 (`docker compose exec web env | grep -c DISCORD_BOT_TOKEN` → 0)
- [ ] 실제 봇 토큰으로 담당자 개인 DM 수신 + DM `오늘`·`완료 12` 왕복  ← 사용자 인프라 필요 — 컨테이너 기동·설정 파싱·발송/수신 경로는 가짜 전송으로 확인. 포털에서 봇을 만들어 `.env.discord`를 채우면 된다
- [ ] `bot` 범위 `CORE_TOKEN` 발급(Step 7의 셸 한 줄)  ← 사용자 인프라 필요
- [ ] 공개 URL로 커넥터 등록  ← 사용자 인프라 필요 — mcp 컨테이너에서 `list_tasks` 동작 확인
- [ ] UptimeRobot 모니터 등록  ← 사용자 인프라 필요
- [ ] Proxmox vzdump 예약 등록  ← 사용자 인프라 필요
- [x] `README.md` 작성 (실행 안내 절을 앞에 덧붙이고 기존 핸드오프는 그대로 뒀다)
- [x] 완료 보고서 작성 ([IMPL-REPORT.md](IMPL-REPORT.md))

커밋: `deploy: compose, cloudflared, readme`
