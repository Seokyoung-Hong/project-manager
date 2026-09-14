# discord_service

산돌이 태스크의 Discord **봇**이다. 두 가지를 한다.

1. **발송** — 마감 알림(D-3 · D-1 · 당일 · 기한 초과)을 **담당자 개인 DM**으로, 주간 보고를 팀 채널로 보낸다.
2. **수신** — 봇에게 온 **평문 DM**을 읽어 `오늘` · `완료` · `연장` · `연결` 명령을 처리한다.

core 코드를 import하지 않는다. core의 HTTP API로만 통신하며, 상태는 SQLite 파일 하나에 둔다.
Webhook은 쓰지 않는다 — 발송은 봇 토큰으로 `discord.com/api/v10`에 직접 하고, core는 Discord로
나가는 요청을 한 곳도 하지 않는다.

발송 대상은 **연결된 사람 본인**이다. 관리 화면에 채널을 등록하는 절차는 없어졌고, 각자
웹 `설정 → 프로필`에서 받은 1회용 코드를 봇에게 DM으로 보내면 연결된다.

## 환경 변수

| 이름 | 필수 | 기본값 | 설명 |
|---|---|---|---|
| `CORE_URL` | ✅ | — | core 주소. 예: `http://web:8000` |
| `CORE_TOKEN` | ✅ | — | core에서 발급한 **`bot` 범위** API 토큰 (`pm_…`) |
| `ORG_ID` | ✅ | — | 마감 스캔·주간 보고 대상 조직 id |
| `DISCORD_BOT_TOKEN` | ✅ | — | Developer Portal → Bot → `[Reset Token]`. **이 파일 밖으로 내보내지 않는다** |
| `DISCORD_CHANNEL_ID` | ✅ | — | 주간 보고와 'DM을 못 보냈다' 통보를 받을 채널 id |
| `DISCORD_GUILD_ID` | | (빈 값) | 슬래시 명령을 등록하고 채널을 만들 서버 id. 비우면 슬래시 명령 없이 DM 명령만 동작 |
| `TZ` | | `Asia/Seoul` | 판정·표시 기준 시간대 |
| `SEND_HOUR` | | `9` | 마감 알림을 보낼 시각(시). 이 시각 **이후** 첫 tick에 하루 1회 |
| `WEEKLY_WEEKDAY` | | `0` | 주간 보고 요일 (0=월) |
| `WEEKLY_HOUR` | | `9` | 주간 보고 시각(시) |
| `LLM_PROVIDER` | | (빈 값) | 비우면 고정 형식 보고서. 값이 있고 실패하면 고정 형식으로 되돌아간다 |
| `DB_PATH` | | `/data/discord.sqlite` | 발송 기록·DM 채널 캐시 SQLite 경로 |
| `SITE_NAME` | | `산돌이 업무` | 테스트 메시지에 쓰는 이름 |

`SEND_HOUR`·`WEEKLY_WEEKDAY`·`WEEKLY_HOUR`는 조직이 웹 `/orgs/<id>/settings`에서 해당 값(`notify.send_hour`
등)을 정하면 그 값이 이 env보다 우선한다(`core_client.org_settings`가 매 틱 조직 설정을 읽고, 값이 없을 때만
이 env로 대체한다). 재배포 없이 시각을 바꾸고 싶으면 조직 설정을, 조직이 하나도 안 건드렸으면 이 env가
지금처럼 그대로 적용된다.

`DISCORD_BOT_TOKEN`과 `CORE_TOKEN`은 **`.env.discord`에만** 둔다(core(web) 프로세스에는 넣지 않는다).
채널 id는 비밀이 아니다. 개발자 모드를 켜고 채널 우클릭 → ID 복사로 얻는다.

## CLI

```bash
python -m discord_service run                     # 60초 루프로 상주 · 발송 (컨테이너 기본 명령)
python -m discord_service bot                     # 게이트웨이로 상주 · DM 명령 수신
python -m discord_service once                    # 지금 시각 기준 tick 1회
python -m discord_service test                    # 팀 채널에 테스트 메시지 1건
python -m discord_service deadlines --date 2026-09-09   # 마감 알림 즉시 실행 (기본: 오늘)
python -m discord_service weekly --now --week-start 2026-08-31   # 주간 보고 (--now는 재발송)
python -m discord_service status                  # 최근 발송·실행 기록 JSON
```

`run`과 `bot`은 **별개 프로세스**다(compose의 `discord` / `discord-bot`). `bot`은 SQLite를
열지 않는다 — 발송 프로세스를 단일 writer로 남기기 위해서다. 그래서 `discord-bot` 컨테이너에는
볼륨을 붙이지 않는다.

## DM 명령

| 보내는 말 | 하는 일 |
|---|---|
| `오늘` | 오늘 화면과 같은 목록 (최대 15줄) |
| `완료 12` · `완료 TASK-12` | 그 태스크를 완료로 |
| `연장 12 2026-09-20 QA 지연` | 목표일을 미루고 사유를 이력에 남긴다 |
| `연결 A3F19C2D` | 웹 `설정 → 프로필`에서 받은 코드로 계정 연결 (10분·1회용) |
| `연결해제` | 연결을 끊는다. **DM 알림도 즉시 멈춘다**(수신 거부 수단) |
| 그 밖의 아무 말 | 명령 목록 답장 |

영어 별칭(`today` · `done` · `extend` · `link` · `unlink`)도 받는다. 변경은 웹에서 한 것과 같은
검사·같은 이력을 남긴다(행위자는 연결된 **사람**, 경로는 `Discord`).

## 슬래시 명령 (`DISCORD_GUILD_ID`가 있을 때)

같은 core 경로·같은 문구다. 파싱만 Discord가 대신한다. **답장은 전부 나에게만 보인다(ephemeral)** —
서버 채널은 공유 공간이고 `/오늘`은 그 사람의 업무 목록이기 때문이다.

| 명령 | 인자 |
|---|---|
| `/오늘` `/연결해제` `/도움` | — |
| `/완료` | `번호` |
| `/연장` | `번호` `기한` `사유` |
| `/연결` | `코드` |
| `/태스크만들기` | `프로젝트` `제목` (`기한` `기한미정사유` `중요도` `담당자`) |
| `/태스크수정` | `번호` (`제목` `기한` `중요도` `담당자` `다음행동`) |
| `/메모` | `번호` `내용` |
| `/상태` | `번호` `상태`(목록에서 선택) (`사유`) |
| `/팀채널` `/프로젝트채널` | `팀`/`프로젝트` (`카테고리`) — 채널을 만들고 core에 연결한다. **부르는 사람이 Discord 서버에서 Manage Channels를 갖고 있고 PM 조직 관리자여야 한다**(둘 다). 봇은 그 사람이 이미 가진 Discord 권한보다 더 주지 않는다 |

`번호`·`프로젝트`·`팀`·`담당자`는 입력하면 목록이 뜬다(내 미완료 태스크·내 조직의 프로젝트·팀·멤버).
목록도 core가 그 사람 기준으로 준다 — 연결되지 않은 사람에게는 빈 목록이다. 봇 프로세스가 30초 캐시를
들고 있어 타자마다 core를 부르지 않는다. 명령 동기화는 기동 시 서버 범위로 한 번 한다(즉시 반영).

## Discord 쪽 준비

1. Developer Portal에서 앱을 만들고 **Bot** 페이지 `[Reset Token]` → `DISCORD_BOT_TOKEN`.
   토큰은 그때 한 번만 보인다. APPLICATION ID·PUBLIC KEY는 필요 없다(인터랙션 엔드포인트를 쓰지 않는다).
2. **특권 인텐트는 하나도 켜지 않는다.** 봇에게 온 DM의 본문은 MESSAGE CONTENT 없이도 전달된다.
3. Installation → **Guild Install**, scope `bot` + `applications.commands`, permissions
   `VIEW_CHANNEL | SEND_MESSAGES | MANAGE_CHANNELS`(=3088). 그 링크로 팀 서버에 추가한다.
   Manage Channels는 `/팀채널`·`/프로젝트채널`용이다. **그 밖의 권한(Manage Roles·Manage Server·
   Administrator)은 주지 않는다.** 서버 id(개발자 모드 → 서버 우클릭 → ID 복사)를 `DISCORD_GUILD_ID`에 넣는다.
4. 팀원 전원: 서버 우클릭 → 개인정보 보호 설정 → **'서버 멤버의 DM 허용' 켜기.** 꺼져 있으면
   Discord가 `50007`로 영구 거부한다(봇은 친구 추가가 안 되므로 '친구만' 설정은 하드 블록이다).
5. 토큰이 유출되면 포털에서 `[Reset Token]` → `.env.discord` 수정 → `docker compose up -d discord discord-bot`.
   겹치는 유효 창이 없어 그 사이 알림이 끊긴다.

## core 연동 계정 만들기

1. core에서 `/signup`으로 연동 전용 계정(예: `discord-bot`)을 만든다.
2. 초대 링크로 그 계정을 팀에 넣는다. **팀원이면 된다** — 관리자 승격은 필요 없다.
   (마감 스캔이 그 계정의 팀 범위 GET을 쓰므로 멤버십 자체는 필요하다.)
3. `bot` 범위 토큰을 발급한다. 웹 화면에서는 만들 수 없다(자기 발급은 권한 상승이다) — 서버 셸에서:
   ```bash
   docker compose exec web python manage.py shell -c "from accounts.models import ApiToken,User; print(ApiToken.issue(User.objects.get(username='discord-bot'),'Discord 봇','bot')[1])"
   ```
   출력된 `pm_…`을 `CORE_TOKEN`에 넣는다. 그 토큰은 `/api/integrations/discord/…` 밖에서는
   쓰기가 403이고, 그 안에서는 **연결된 사용자의 권한으로** 오늘 읽기·완료·연장 세 가지만 한다.
4. `ORG_ID`는 `/orgs/<id>` 주소의 숫자다.

## 로컬 실행

```bash
CORE_URL=http://localhost:8000 CORE_TOKEN=pm_xxx ORG_ID=1 \
DISCORD_BOT_TOKEN=xxx DISCORD_CHANNEL_ID=123456789 \
DB_PATH=./discord.sqlite \
uv run python -m discord_service test
```

Windows에서 직접 실행하려면 시스템에 IANA 시간대 DB가 없어 `TZ` 해석이 실패할 수 있다.
그때는 Docker로 실행한다(이미지에 tzdata가 들어 있다).

## 규칙

- 마감 알림은 **담당자 개인 DM**으로 간다. 팀 채널에 전체 공지하지 않는다.
- 한 사람이 하루에 받는 DM은 **종류당 1건, 최대 4건**이다(D-3 · D-1 · 당일 · 기한 초과).
  같은 종류의 태스크 여러 건은 한 통에 묶인다. 중복 방지 키는 `(종류, 담당자, 날짜)`다.
- D-3 · D-1 · 당일은 **그날에만** 보낸다. 놓친 날을 소급 발송하지 않는다.
- 발송 직전에 태스크를 다시 읽어 완료·취소·기한 변경을 걸러낸다.
- Discord를 **연결하지 않은 사람**에게는 아무것도 보내지 않고 자리도 잡지 않는다(연결하면 그
  다음 알림부터 정상). 그 사람 이름은 주간 보고 마지막 줄과 `/ops` detail에 뜬다 — 실패로 세지 않는다.
- **DM이 막힌 사람**(`50007` · `50278` · `10013`)은 재시도하지 않는다. 그 건은 실패로 기록하고,
  팀 채널에 하루 한 번 "DM을 켜 주세요" 통보만 보낸다. 그 통보에는 태스크 제목도 URL도 넣지 않는다.
- 개인 DM은 멘션을 만들지 않는다(`allowed_mentions.parse=[]`). 팀 채널 게시만 사용자 멘션을
  허용한다(`parse=["users"]`) — `@everyone`·역할 멘션은 어느 쪽도 못 만든다.
- 실패한 건은 자동 재시도하지 않는다.
- DM 채널 id는 SQLite에 캐시한다. 매번 새로 열면 `40003`(DM 여는 속도 초과)이 난다.

## 테스트

```bash
uv run pytest -q
uv run ruff check .
```
