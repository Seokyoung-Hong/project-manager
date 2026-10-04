# IMPL-PLAN-5: 요청 REST API · Discord 채널 관리 (2026-10-04, Fable 검토 반영본)

브랜치 `Seokyoung-Hong/팀-인원에게-태스크-요청`. 이미 들어간 것: `WorkRequest`·`Notice` 모델과
`tasks/work_requests.py` 서비스, 웹 요청함, Discord `/요청*` 명령, 팀장(`TeamMembership.is_lead`).
이 문서는 그 위에 얹을 두 묶음의 계획이다.

- **A. 요청 REST API** — 스킬(`/pm-*`)·MCP·WebMCP에서도 요청을 다룬다.
- **B. Discord 채널 관리** — 팀·프로젝트 전용 채널을 연결하거나 만들고, 권한 밖 인원을 감시한다.

공통 원칙(GUIDE-00 §3)은 그대로다: 업무 규칙은 `services`에만, core는 Discord로 직접 요청하지 않는다,
새 의존성 없음, 함수형 뷰.

---

## A. 요청 REST API

### A1. 엔드포인트 (`core/api/routers/requests.py`, prefix `/api/requests`)

인증·처리량은 다른 라우터와 같다(세션 또는 토큰, 60/m). `ctx(request)`로 actor·source를 얻는다
(AI 토큰이면 `source="mcp"`).

| 메서드·경로 | 본문/쿼리 | 서비스 | 응답 |
|---|---|---|---|
| `GET /api/requests` | `box=received\|sent\|all`(기본 received), `status`, `org`, `limit`·`offset` | `received`·`visible_requests` | `{items:[RequestOut], total, limit, offset}` |
| `GET /api/requests/{id}` | | `get_visible_request` (없으면 404) | `RequestOut` + `can_answer`·`can_cancel`·`can_complete` |
| `POST /api/requests` | `org_id, kind(work\|general), title, body, team_id\|to_user_id` · `Idempotency-Key` | `create_request` | 201 `RequestOut` |
| `POST /api/requests/{id}/accept` | `project_id?, assignee_id?, due_date?, note` | `accept` | `RequestOut` (+ `task: TaskOut`) |
| `POST /api/requests/{id}/decline` | `note` | `decline` | `RequestOut` |
| `POST /api/requests/{id}/cancel` | | `cancel` | `RequestOut` |
| `POST /api/requests/{id}/done` | `note` | `complete` | `RequestOut` |

- `RequestOut`은 이미 있는 `api/serialize.request_out`을 스키마로 옮긴다(Discord 봇 응답과 같은 모양).
- 다른 조직의 `team_id`·`to_user_id`·`project_id`·`assignee_id`는 서비스가 막지만, 라우터는 존재 여부를
  드러내지 않게 "찾을 수 없습니다"(400)로 통일한다.
- `Idempotency-Key`: 태스크 생성과 같은 `IdempotencyKey`(target_type=`request`)로 중복 생성을 막는다.
  AI가 재시도해도 요청이 두 번 가지 않게 하는 것이 목적이다.

### A2. AI 정책 (조직 설정 `ai.*`, 기존 `_ai_check` 방식)

| 키 | 기본 | 막는 것 |
|---|---|---|
| `ai.create_request` | allow | AI가 요청을 만들기·취소하기 |
| `ai.answer_request` | **deny** | AI가 수락·거절·완료하기 |

- 수락은 "내가 이 일을 맡겠다"는 사람의 약속이고 태스크·담당이 바뀐다. 그래서 기본은 사람만 하게 둔다.
  조직이 켜면 AI도 할 수 있다.
- `ai.enabled`가 꺼져 있으면 둘 다 막힌다(기존 규칙).
- 담당 요청(assign)은 이미 `ai.change_assignee`의 적용을 받는다. 바뀌는 것 없음.

### A3. 클라이언트

- **MCP(`mcp_server`)**: `list_requests`, `get_request`, `create_request`, `answer_request(id, action, …)`
  4개 도구를 추가한다. action은 accept·decline·cancel·done 중 하나다. 도구 설명에 "수락은 사용자 확인 후"를 적는다.
- **WebMCP(`core/web/static/webmcp.js`)**: 같은 이름·같은 규칙으로 4개를 추가한다(README의 "같은 도구" 원칙).
- **스킬**:
  - `skills/pm/SKILL.md`에 요청 엔드포인트를 적는다(`pm.py call`로 그대로 부른다. 스크립트 변경은 없음).
  - `/pm-today`는 "답할 요청 N건"을 함께 보인다(읽기 전용).

### A4. 테스트

라우터 테스트로 권한(남의 요청 404, 받는 사람이 아닌데 수락하면 400), AI 정책(기본 deny), 멱등성,
목록 필터를 본다. MCP·WebMCP는 기존 도구 테스트 방식을 따른다.

---

## B. Discord 채널 관리

### B0. 문제와 목표

팀 요청 제목·요청자가 팀 채널에 공개로 올라간다. 팀 채널을 서버 전체가 볼 수 있으면 비공개 절차가 아니다.
목표는 세 가지다.

1. 팀·프로젝트마다 전용 채널을 **기존 채널 연결** 또는 **새로 만들기(비공개)**로 정한다.
2. 연결하려는 채널에 권한 밖의 인원이 있으면 **경고하고, 명시적 허용을 받아야** 연결한다.
3. 연결 뒤에도 감시한다. **허용받지 않은 인원이 새로 보이면 다시 경고**한다.

### B1. "권한 안"의 정의

| 채널 | 허용 집합 |
|---|---|
| 팀 채널 | 그 팀의 팀원 |
| 프로젝트 채널 | 프로젝트 관리자(`owners`) ∪ 프로젝트 담당 팀의 팀원 |
| 공통 | 그 채널에서 명시적으로 허용한 인원 |

- 허용 집합은 매번 PM 데이터에서 계산한다. 팀원이 늘면 그 사람은 자동으로 "권한 안"이 된다.
- PM 사용자는 연결한 Discord 계정으로 대응한다. 계정을 연결하지 않은 사람은 권한 밖이다.
- **봇 계정(`member.bot`)은 모두 제외한다.** 서버 관리자(Administrator)는 모든 채널을 보므로 처음 한 번은
  경고된다. 허용하면 그 뒤로는 조용하다.

### B2. 구조 (core는 Discord를 부르지 않는다)

- 연결·생성은 **Discord 안에서** 한다. 대상은 `/팀채널`·`/프로젝트채널` 명령과 MCP 제어 서버(`control.py`)다.
  웹에서는 채널을 고르지 않는다(`core/web/views/discord.py` 상단 원칙 유지). 웹은 상태와 허용·철회만 한다.
- 봇이 채널을 볼 수 있는 사람을 계산한다: `channel.permissions_for(member).view_channel`, 봇 제외.
  - 연결할 때: 그 목록을 core에 보내면 core가 권한 밖 인원을 돌려준다.
  - 감시할 때: 봇이 `GET /discord/channels`로 연결된 채널과 각 채널의 허용 Discord id 집합을 받는다.
    차집합만 `POST /discord/channel-alerts`(채널별 **현재** 권한 밖 인원 전체)로 올린다.
- 감시 주기는 5분이다. 다음 게이트웨이 이벤트가 오면 해당 길드를 바로 다시 본다.
  - `CHANNEL_UPDATE`, `GUILD_ROLE_UPDATE`(guilds 인텐트)
  - `GUILD_MEMBER_UPDATE`, `GUILD_MEMBER_ADD`(members 인텐트)

### B3. Discord 쪽 변경

| 항목 | 지금 | 바뀌는 것 |
|---|---|---|
| 봇 권한(설치 URL) | 3088 (View·Send·Manage Channels) | **그대로.** 채널을 만들 때 넣는 권한 덮어쓰기는 Manage Channels로 충분하다. 재승인이 필요 없다 |
| 게이트웨이 인텐트 | `guilds`, `dm_messages` | **+ `members`(특권)**. 사람 단위로 누가 보는지 알려면 필요하다 |

- **켜는 순서**: Developer Portal에서 Server Members Intent를 먼저 켠다. 그다음 환경변수 `DISCORD_MEMBERS_INTENT=1`로
  배포한다. 포털이 꺼진 채 인텐트를 요청하면 봇이 기동에 실패해 알림·명령이 모두 멈춘다.
- 환경변수가 꺼져 있으면 감시는 건너뛴다. 기존 채널 연결은 **확인 불가**를 권한 밖 인원이 있는 것과 같이
  다룬다(fail closed). 즉 명시적 허용 옵션이 있어야 연결된다.

### B4. 모델 (`orgs` 앱, 1개)

```python
class DiscordChannelAlert(models.Model):
    """채널을 볼 수 있는 권한 밖 인원. 허용하면 allowed로 남아 허용 목록 역할도 한다."""
    org, channel_id, discord_user_id, display_name
    status  # open(경고 중) | allowed(명시적 허용) | gone(경고 중에 사라짐)
    first_seen, resolved_by, resolved_at
    unique(channel_id, discord_user_id)
```

- 허용 목록은 `status=allowed`인 행이다. 철회하면 행을 지운다. 다음 감시에서 아직 보이면 다시 `open` 경고가 된다.
- 채널 연결을 끊거나 바꾸면 그 채널의 행을 지운다.

### B5. 흐름

1. **기존 채널 연결**
   - 대상: `/팀채널 기존채널:#x`(신규 옵션), `/프로젝트채널 기존채널:#x`, MCP `assign_channel`.
   - 봇이 보는 사람 목록을 core에 보내면, core가 권한 밖 인원을 계산한다.
   - 권한 밖 인원이 없으면 바로 연결한다.
   - 있으면 **연결하지 않고** 명단을 비공개로 답한다: "권한 밖 N명: … 이 인원을 허용하고 연결하려면
     `권한밖허용:True`로 다시 실행해 주세요."
   - 옵션을 켜고 다시 실행하면 연결하고, 그 명단을 `allowed`로 기록한다. 명단은 다시 계산하므로, 그사이 늘어난 사람이 있으면 다시 거절한다.
   - MCP는 같은 의미의 `allow_outsiders=true` 인자를 쓰고, 도구 설명에 "사용자 확인 후"를 적는다.
2. **새로 만들기**
   - `/팀채널`·`/프로젝트채널`(기존채널 미지정)과 MCP `create_project_channel`.
   - 채널을 **비공개로** 만든다: @everyone VIEW 거부, 허용 집합 중 Discord를 연결한 계정과 봇은 VIEW 허용.
   - 지금의 공개 채널 생성 코드를 이것으로 바꾼다.
3. **감시**
   - 봇이 올린 "현재 권한 밖 인원"을 기존 행과 비교한다.
   - 새로 보이거나 `gone`이었다가 다시 보이면 `open`으로 두고 **조직 관리자에게 DM 알림**(`Notice`)을 보낸다.
     웹 배지도 띄운다. DM에는 채널과 인원 수, 이름을 넣되 길면 자른다(1900자).
   - `open`인데 사라지면 `gone`. `allowed`는 그대로다.
   - 채널 자체에는 경고를 올리지 않는다.
4. **허용·철회**: 웹 `조직 → Discord`(관리자)의 채널별 경고 목록에서 [허용], 허용 목록에서 [철회]를 누른다.
5. **실행자 권한(권한 상승 방지)**
   - 슬래시 명령은 지금처럼 실행한 사람의 `manage_channels`를 본다.
   - **MCP 제어 서버에는 이 검사가 없다**(`control.py` `_org`는 PM 관리자만 확인한다).
   - 토큰 주인의 연결된 Discord 계정을 `guild.fetch_member`로 조회해 Manage Channels를 확인하고, 없거나 조회할 수 없으면 거절한다.
     캐시(`get_member`)는 쓰지 않는다.

### B6. 화면 (웹 `조직 → Discord`, 관리자)

- 팀·프로젝트 표에 연결 채널, 상태(정상 / 권한 밖 N명 / 미연결 / 감시 꺼짐)를 보인다.
- 연결과 생성은 "Discord에서 `/팀채널`·`/프로젝트채널`로 합니다"라고 안내한다.
- 채널별 경고 목록에는 [허용]을, 허용 목록에는 [철회]를 둔다.

### B7. 단계

1. 모델과 비교 서비스(순수 함수: 보는 사람 목록·허용 집합 → 권한 밖 명단). 봇 API `GET /discord/channels`,
   `POST /discord/channel-alerts`, `POST /discord/channel-check`(연결 전 확인). 테스트 포함.
2. 운영: 포털에서 인텐트 켜기, 그 뒤 봇에 `DISCORD_MEMBERS_INTENT` 플래그와 감시 루프·이벤트 트리거를 배포한다.
3. 비공개 생성과 연결 경고로 세 경로를 모두 바꾼다: `/팀채널`(기존채널 옵션 신설), `/프로젝트채널`, MCP `control.py`.
   MCP에는 Manage Channels 검사도 추가한다.
4. 웹 상태·허용·철회 화면. `OPERATIONS-DEPLOYMENT.md`에 인텐트 켜는 순서를 적는다.

### B8. 테스트에서 꼭 볼 것

공개 채널을 감지해도 채널에는 경고를 올리지 않는다. 허용을 철회하면 다시 경고한다. `gone`이었던 사람이 다시 나타나면 다시 경고한다.
MCP 제어 서버는 Manage Channels가 없으면 거절한다. 인텐트가 꺼져 있으면 `권한밖허용` 없이는 연결을 거절한다.
봇 계정은 제외한다.

### B9. 하지 않는 것

- 권한 밖 인원을 자동으로 쫓아내지 않는다. Manage Roles가 없어서 연결 뒤에는 채널 권한을 고치지 못한다.
  **PM에 팀원을 새로 넣으면 그 사람의 Discord 접근은 사람이 직접 열어 준다.** 웹 상태 화면에 "Discord 미접근 팀원"으로 표시한다.
- 서버 역할을 만들거나 바꾸지 않는다. 조직 알림 채널은 감시하지 않는다.

---

## 결정 사항 (검토 반영 후)

1. **members 특권 인텐트**를 켜야 한다(포털에서 한 번). 봇 권한 추가와 재승인은 필요 없다.
2. `ai.answer_request` 기본은 **deny**다. `/pm-*` 스킬도 AI 경로로 판정되므로 스킬에서 "수락해 줘"는 막힌다.
   SKILL.md에 이를 적는다.
3. 팀원 변동을 채널 권한에 자동 반영하지 **않는다**. 하려면 Manage Roles 권한을 추가하고 봇을 다시 승인받아야 한다.

---

## 사용자 결정 (2026-10-04) — 위 B3·B9·결정 3을 덮어쓴다

1. members 인텐트: 진행한다(포털에서 켠다).
2. `ai.answer_request` 기본 deny 유지. 추가로 웹 토큰 발급 화면에 AI용·사람용 차이와
   "사람용을 AI에 주면 생기는 문제"를 강하게 경고하고, 사람용은 확인 체크를 받아야 발급한다(구현 완료).
3. **자동 관리를 한다.**
   - 봇 권한: 3088 → **268438544**(+ Manage Roles). 이미 설치된 서버는 재승인이 필요하다.
     웹 Discord 화면에 "권한 갱신 필요"와 재설치 링크를 띄운다. 봇이 길드 권한을 core에 보고한다.
   - `Team.discord_channel_managed`·`Project.discord_channel_managed`(bool)을 둔다.
     봇이 만든 채널은 켜진 채로, 사람이 만든 채널은 꺼진 채로 시작한다. 켜는 방법은 두 가지다.
     - 웹 `조직 → Discord`의 토글(조직 관리자)
     - 연결 명령 옵션 `자동관리:True`
   - **조정(reconcile)**: 매 틱마다 자동 관리 채널에서 허용 집합(B1)의 Discord 연결 계정에게 멤버 단위 덮어쓰기
     (VIEW·SEND 허용)를 보장한다.
     - 봇이 넣은 멤버 덮어쓰기는 봇 저장소(SQLite)에 기록한다. 허용 집합에서 빠진 사람은 **봇이 넣은 것만** 지운다.
     - 역할 덮어쓰기, @everyone, 사람이 넣은 멤버 덮어쓰기는 건드리지 않는다.
     - 봇은 VIEW·SEND·READ_HISTORY 외의 권한을 주지 않는다.
   - 사람이 만든 채널에서 자동 관리를 켜도 @everyone을 바꾸지 않는다. 공개 채널은 여전히 권한 밖 인원 경고로 드러난다.
   - B9의 "Discord 미접근 팀원" 표시는 자동 관리가 꺼진 채널에만 남는다.
