# 구현 지시서 02: discord_service (별도 프로세스)


> **이 문서는 2026-09-10에 끝난 최초 구축의 기록이다.** 지금 할 일은 [GUIDE-V2-00-overview.md](GUIDE-V2-00-overview.md)부터 시작하는 묶음이다. 이 문서에 나오는 `Team`·`teams`·"팀"은 2026-09-11 개명 전 용어로 **조직**을 뜻한다. 대조표는 [GUIDE-V2-01](GUIDE-V2-01-org-teams.md) §1에 있다.

GUIDE-00을 먼저 읽는다. 이 파트는 **core 코드를 한 줄도 import하지 않는다.** core와는 HTTP API(GUIDE-01-3)로만 통신한다. 상태는 SQLite 파일 하나. Django 없음.

역할이 둘이다.

1. **발송(틱)** — 마감 알림(D-3 · D-1 · 당일 · 기한 초과)을 **담당자 개인 DM**으로, 주간 보고를 **팀 채널**로 보낸다. 결과를 core `/ops`에 보고한다.
2. **수신(리스너)** — 봇에게 온 **평문 DM**을 읽어 `오늘` · `완료` · `연장` · `연결` 명령을 core API로 넘긴다.

둘은 같은 이미지의 다른 서브커맨드다(`run` / `bot`). 프로세스를 나누는 이유는 Step 5에 적었다.

개정 2026-09-10 (2차): **Discord Webhook을 버리고 봇 토큰으로 바꿨다.** 팀 채널 전체 공지 → 담당자 개인 DM + DM 명령. `DiscordWebhook` 모델·`팀 → 알림 채널` 관리 화면·`Fanout`·`DISCORD_WEBHOOK_URL`이 전부 사라졌고, **core는 Discord로 나가는 요청이 한 곳도 없다**(발송은 이 서비스 전담).

개정 2026-09-10 (1차): 태스크 상태 7개(`paused`·`blocked`가 상태), `is_blocked` 대신 `status`·`stop_reason`, 주간 집계에서 `commented` 삭제.

---

## Step 0. 환경

`discord_service/` 디렉터리에서:

```bash
uv init --no-workspace --name udally-discord --python 3.12
uv add "httpx>=0.27" "discord.py>=2.4,<3"
uv add --dev "pytest>=8" "ruff>=0.6"
uv lock
```

자동 생성된 `main.py`/`hello.py`는 지운다. 완성된 `pyproject.toml`:

```toml
[project]
name = "udally-discord"
version = "0.1.0"
description = "유달리 — Discord 알림 서비스"
requires-python = ">=3.12"
dependencies = [
    "httpx>=0.27",
    # 게이트웨이(WebSocket) 프로토콜: 하트비트·RESUME·close code 처리를 직접 쓰지 않는다.
    "discord.py>=2.4,<3",
]

[tool.pytest.ini_options]
testpaths = ["tests"]
pythonpath = ["."]

[tool.ruff]
line-length = 100
target-version = "py312"

[tool.ruff.lint]
select = ["E", "F", "I", "UP", "B"]
ignore = ["E501"]

[dependency-groups]
dev = [
    "pytest>=8",
    "ruff>=0.6",
]
```

### 왜 `discord.py`를 쓰는가 (의존성을 하나 더 받는 이유)

수신은 **게이트웨이(WebSocket)** 다. REST로 폴링할 수 있는 경로가 없다. 직접 쓰면 우리가 소유해야 하는 것:

| 직접 쓰면 | `discord.py`를 쓰면 |
|---|---|
| `GET /gateway/bot` → WSS 접속 → `HELLO`의 `heartbeat_interval`마다 하트비트, **ACK가 안 오면** 연결을 버리고 재접속 | 라이브러리 |
| 끊기면 `resume_gateway_url`로 RESUME(`session_id` + 마지막 `s`), 세션이 죽었으면 IDENTIFY부터 다시 | 라이브러리 |
| close code 표 — `4004`·`4010`·`4011`·`4012`·`4013`·`4014`는 재접속해도 소용없고(설정을 고쳐야 한다) 나머지는 재접속해야 한다 | 라이브러리 |
| DM 판정 — `channel.type`으로 가르면 시스템 메시지 `RECIPIENT_ADD`(type 1)와 헷갈린다 | `message.guild is None` |
| IDENTIFY 예산(하루 1000회) 백오프 | 라이브러리 |

우리가 쓰는 코드는 `listener.py` **59줄**(주석·독스트링 포함, 실코드 40줄)이 되고 그 안에 게이트웨이 프로토콜은 한 줄도 없다. 대가는 이미지 안의 `aiohttp`와 전이 의존성 몇 개다 — 컨테이너지 브라우저 번들이 아니다.

**발송은 라이브러리를 쓰지 않는다.** 봇 REST 두 엔드포인트만 필요하고 동기 호출이 맞아서 `httpx`로 직접 부른다(`discord.py`의 `Bot`).

파일 구성:

```
discord_service/
  pyproject.toml
  Dockerfile
  README.md
  discord_service/
    __init__.py
    __main__.py     CLI: run | bot | once | test | weekly | deadlines | status
    config.py       환경 변수 → Config
    store.py        SQLite (발송 기록 · DM 채널 캐시)
    core_client.py  core API 호출 (읽기 + 봇 명령 5개)
    discord.py      봇 REST 전송 (개인 DM · 팀 채널, 재시도, 2000자 분할)
    messages.py     메시지 문자열 만들기
    notify.py       마감 알림 작업 (담당자별 묶기)
    weekly.py       주간 보고 작업
    summarize.py    요약 (LLM 자리, 기본 고정 형식)
    scheduler.py    60초 루프
    listener.py     게이트웨이 수신 (discord.py)
    commands.py     DM 평문 명령 해석
  tests/
    conftest.py  test_notify.py  test_weekly.py  test_discord.py
    test_store.py  test_commands.py  test_listener.py
```

> **이름 충돌 주의.** `discord_service/discord_service/discord.py`가 있어도 `listener.py`의 `import discord`는 site-packages의 `discord.py`를 가리킨다 — 절대 임포트이고 패키지 디렉터리는 `sys.path`에 없다. 파일 이름을 바꾸지 않는다(import 5곳 + 문서 churn을 살 이유가 없다). `listener.py` 맨 위 주석이 그 사실을 적어 둔다.

---

## Step 1. 설정과 저장소

### `discord_service/config.py`

```python
import os
from dataclasses import dataclass
from zoneinfo import ZoneInfo


@dataclass(frozen=True)
class Config:
    core_url: str
    core_token: str
    team_id: int
    bot_token: str
    channel_id: str
    tz: ZoneInfo
    send_hour: int
    weekly_weekday: int
    weekly_hour: int
    llm_provider: str
    db_path: str
    site_name: str

    @classmethod
    def from_env(cls) -> "Config":
        def need(k):
            v = os.environ.get(k, "").strip()
            if not v:
                raise SystemExit(f"환경 변수 {k} 가 필요합니다.")
            return v

        return cls(
            core_url=need("CORE_URL").rstrip("/"),
            core_token=need("CORE_TOKEN"),
            team_id=int(need("TEAM_ID")),
            bot_token=need("DISCORD_BOT_TOKEN"),
            channel_id=need("DISCORD_CHANNEL_ID"),
            tz=ZoneInfo(os.environ.get("TZ", "Asia/Seoul")),
            send_hour=int(os.environ.get("SEND_HOUR", "9")),
            weekly_weekday=int(os.environ.get("WEEKLY_WEEKDAY", "0")),
            weekly_hour=int(os.environ.get("WEEKLY_HOUR", "9")),
            llm_provider=os.environ.get("LLM_PROVIDER", "").strip().lower(),
            db_path=os.environ.get("DB_PATH", "/data/discord.sqlite"),
            site_name=os.environ.get("SITE_NAME", "유달리"),
        )
```

`bot_token`과 `channel_id`는 **둘 다 `need`** 다. 예비값이 없다 — 봇 토큰이 없으면 아무것도 못 보내고, 채널 id가 없으면 주간 보고와 'DM을 못 보냈다' 통보가 갈 곳이 없다. 실행 즉시 `SystemExit`로 죽는 게 조용히 반쯤 도는 것보다 낫다.

팀 채널 id를 **core DB에 두지 않는다**: 비밀도 아니고 배포당 값 하나다. 팀이 둘 이상이 되면 `Team.discord_channel_id` 컬럼 하나를 붙인다(방금 지운 관리 화면을 되살리지 않는다).

### `discord_service/store.py`

```python
import sqlite3
from contextlib import contextmanager
from datetime import UTC, datetime

DDL = """
CREATE TABLE IF NOT EXISTS sent(
  task_id INTEGER NOT NULL, kind TEXT NOT NULL, due_date TEXT NOT NULL,
  status TEXT NOT NULL, attempts INTEGER NOT NULL DEFAULT 0, last_error TEXT,
  created_at TEXT NOT NULL, sent_at TEXT,
  PRIMARY KEY(task_id, kind, due_date)
);
CREATE TABLE IF NOT EXISTS daily(kind TEXT NOT NULL, date TEXT NOT NULL, PRIMARY KEY(kind, date));
-- (봇, Discord 사용자) 쌍의 DM 채널. 매번 열면 40003(DM 여는 속도 초과)이 난다.
CREATE TABLE IF NOT EXISTS dm(discord_user_id TEXT PRIMARY KEY, channel_id TEXT NOT NULL);
CREATE TABLE IF NOT EXISTS weekly(
  period_start TEXT PRIMARY KEY, data_json TEXT NOT NULL, summary TEXT NOT NULL,
  source TEXT NOT NULL, sent_status TEXT NOT NULL, sent_at TEXT
);
CREATE TABLE IF NOT EXISTS runs(
  id INTEGER PRIMARY KEY AUTOINCREMENT, name TEXT NOT NULL, ran_at TEXT NOT NULL,
  ok INTEGER NOT NULL, note TEXT
);
"""


def _now() -> str:
    return datetime.now(UTC).isoformat()


class Store:
    def __init__(self, path: str):
        self.path = path
        with self._conn() as c:
            c.executescript(DDL)

    @contextmanager
    def _conn(self):
        conn = sqlite3.connect(self.path, timeout=30)
        conn.row_factory = sqlite3.Row
        try:
            yield conn
            conn.commit()
        finally:
            conn.close()

    # --- 마감 알림 ---
    def claim(self, task_id: int, kind: str, due_date: str) -> bool:
        """발송 전에 자리를 잡는다. 이미 있으면 False (중복 방지)."""
        with self._conn() as c:
            cur = c.execute(
                "INSERT OR IGNORE INTO sent(task_id, kind, due_date, status, created_at) VALUES(?,?,?,?,?)",
                (task_id, kind, due_date, "sending", _now()),
            )
            return cur.rowcount == 1

    def mark(self, task_id: int, kind: str, due_date: str, status: str, error: str | None = None):
        with self._conn() as c:
            c.execute(
                "UPDATE sent SET status=?, attempts=attempts+1, last_error=?, sent_at=? "
                "WHERE task_id=? AND kind=? AND due_date=?",
                (status, error, _now() if status == "sent" else None, task_id, kind, due_date),
            )

    def release(self, task_id: int, kind: str, due_date: str):
        """발송하지 않기로 했을 때(완료·기한 변경) 자리를 지운다."""
        with self._conn() as c:
            c.execute(
                "DELETE FROM sent WHERE task_id=? AND kind=? AND due_date=? AND status='sending'",
                (task_id, kind, due_date),
            )

    # --- DM 채널 캐시 ---
    def dm_channel(self, discord_user_id: str) -> str | None:
        with self._conn() as c:
            row = c.execute(
                "SELECT channel_id FROM dm WHERE discord_user_id=?", (str(discord_user_id),)
            ).fetchone()
            return row["channel_id"] if row else None

    def save_dm_channel(self, discord_user_id: str, channel_id: str):
        with self._conn() as c:
            c.execute(
                "INSERT OR REPLACE INTO dm(discord_user_id, channel_id) VALUES(?,?)",
                (str(discord_user_id), str(channel_id)),
            )

    def forget_dm_channel(self, discord_user_id: str):
        with self._conn() as c:
            c.execute("DELETE FROM dm WHERE discord_user_id=?", (str(discord_user_id),))

    # --- 하루 1회 작업 ---
    def claim_daily(self, kind: str, date: str) -> bool:
        with self._conn() as c:
            cur = c.execute("INSERT OR IGNORE INTO daily(kind, date) VALUES(?,?)", (kind, date))
            return cur.rowcount == 1

    def release_daily(self, kind: str, date: str):
        with self._conn() as c:
            c.execute("DELETE FROM daily WHERE kind=? AND date=?", (kind, date))

    # --- 주간 ---
    def weekly_sent(self, period_start: str) -> bool:
        with self._conn() as c:
            row = c.execute(
                "SELECT sent_status FROM weekly WHERE period_start=?", (period_start,)
            ).fetchone()
            return row is not None and row["sent_status"] == "sent"

    def save_weekly(
        self, period_start: str, data_json: str, summary: str, source: str, sent_status: str
    ):
        with self._conn() as c:
            c.execute(
                "INSERT OR REPLACE INTO weekly(period_start, data_json, summary, source, sent_status, sent_at) "
                "VALUES(?,?,?,?,?,?)",
                (
                    period_start,
                    data_json,
                    summary,
                    source,
                    sent_status,
                    _now() if sent_status == "sent" else None,
                ),
            )

    # --- 실행 기록 ---
    def record_run(self, name: str, ok: bool, note: str = ""):
        with self._conn() as c:
            c.execute(
                "INSERT INTO runs(name, ran_at, ok, note) VALUES(?,?,?,?)",
                (name, _now(), int(ok), note[:500]),
            )

    def recent(self, limit: int = 20) -> dict:
        with self._conn() as c:
            runs = [
                dict(r) for r in c.execute("SELECT * FROM runs ORDER BY id DESC LIMIT ?", (limit,))
            ]
            sent = [
                dict(r)
                for r in c.execute("SELECT * FROM sent ORDER BY created_at DESC LIMIT ?", (limit,))
            ]
            weekly = [
                dict(r)
                for r in c.execute(
                    "SELECT period_start, source, sent_status, sent_at FROM weekly "
                    "ORDER BY period_start DESC LIMIT 5"
                )
            ]
        return {"runs": runs, "sent": sent, "weekly": weekly}
```

`dm` 표가 이 개정에서 새로 생겼다. `CREATE TABLE IF NOT EXISTS`라 마이그레이션 장치 없이 기존 `discord.sqlite`에 붙는다. 나머지 네 표(`sent`·`daily`·`weekly`·`runs`)는 무변경이다.

`sent`의 `kind`는 길이 제약이 없는 `TEXT`다. 이 개정에서 `kind`에 `d1:2`(종류:담당자 id) 같은 값이 들어가는데 **스키마 변경이 0줄**인 이유다.

---

## Step 2. core 클라이언트와 봇 전송

### `discord_service/core_client.py`

```python
import httpx


class CoreClient:
    def __init__(self, base_url: str, token: str, transport=None):
        self.http = httpx.Client(
            base_url=base_url,
            timeout=20,
            headers={"Authorization": f"Bearer {token}", "X-Source": "api"},
            transport=transport,
        )

    def open_tasks(self, team_id: int, due_to: str | None = None) -> list[dict]:
        """미완료 태스크 전부 (페이지 순회). due_to는 'YYYY-MM-DD'."""
        items, offset = [], 0
        while True:
            params = {
                "team": team_id,
                "status": "todo,doing,paused,blocked,review",
                "limit": 200,
                "offset": offset,
            }
            if due_to:
                params["due_to"] = due_to
            r = self.http.get("/api/tasks", params=params)
            r.raise_for_status()
            data = r.json()
            items.extend(data["items"])
            offset += data["limit"]
            if offset >= data["total"]:
                return items

    def task(self, task_id: int) -> dict | None:
        r = self.http.get(f"/api/tasks/{task_id}")
        if r.status_code == 404:
            return None
        r.raise_for_status()
        return r.json()

    def weekly(self, team_id: int, week_start: str) -> dict:
        r = self.http.get("/api/reports/weekly", params={"team": team_id, "week_start": week_start})
        r.raise_for_status()
        return r.json()

    # --- 봇 명령 (행위자는 연결된 사람. core가 discord_user_id로 찾는다) ---

    def _bot(self, path: str, body: dict) -> dict:
        r = self.http.post(f"/api/integrations/discord{path}", json=body)
        r.raise_for_status()
        return r.json()

    def link(self, code: str, did: str) -> dict:
        return self._bot("/link", {"code": code, "discord_user_id": did})

    def unlink(self, did: str) -> dict:
        return self._bot("/unlink", {"discord_user_id": did})

    def today(self, did: str) -> dict:
        return self._bot("/today", {"discord_user_id": did})

    def done(self, did: str, task_id: int) -> dict:
        return self._bot(f"/tasks/{task_id}/done", {"discord_user_id": did})

    def extend(self, did: str, task_id: int, due_date: str, reason: str) -> dict:
        return self._bot(
            f"/tasks/{task_id}/extend",
            {"discord_user_id": did, "due_date": due_date, "reason": reason},
        )

    def report_status(self, ok: bool, detail: dict):
        try:
            self.http.post("/api/integrations/discord/status", json={"ok": ok, "detail": detail})
        except httpx.HTTPError:
            pass  # 상태 보고 실패는 본 작업을 막지 않는다
```

아래쪽 5개(`link`·`unlink`·`today`·`done`·`extend`)는 리스너가 쓴다. 전부 POST다 — `오늘`이 GET이 아닌 이유는 식별자(snowflake)를 쿼리 문자열에 싣지 않기 위해서다. 경로와 요청·응답 모양은 GUIDE-01-3 §5.6의 `api/routers/discord.py`가 정의한다.

`raise_for_status()`를 그대로 올린다. 상태 코드를 한국어 문구로 바꾸는 곳은 `commands.py` 한 곳뿐이다(Step 6).

`CORE_TOKEN`은 이제 **`bot` 범위**여야 한다. 그 라우터는 `Router(auth=BotTokenAuth())`라서 세션 쿠키·`read`·`write` 토큰이 아예 못 들어온다.

### `discord_service/discord.py`

```python
import logging
import time

import httpx

log = logging.getLogger(__name__)

API = "https://discord.com/api/v10"
MAX_LEN = 1900  # Discord content 한도 2000자, 여유
# Discord는 봇 요청에 User-Agent를 요구한다. 없으면 Cloudflare가 40333으로 막는다.
UA = "DiscordBot (https://project.sio2.kr, 0.1)"
STALE_CHANNEL = 10003  # 캐시해 둔 DM 채널이 사라졌다. 한 번 다시 열면 된다.
# 3회 루프에 넣지 않고 즉시 포기할 코드들. 50007·50278·10013은 그 사용자에 대해 영구적이고,
# 재시도하면 10분당 1만 invalid-request 예산만 태운다(LXC는 egress IP가 하나다).
NO_RETRY_CODES = {50007, 50278, 10013, STALE_CHANNEL}


def chunk(text: str) -> list[str]:
    """줄 단위로 1900자 이하 조각으로 나눈다."""
    parts, buf = [], ""
    for line in text.splitlines(keepends=True):
        if len(buf) + len(line) > MAX_LEN and buf:
            parts.append(buf)
            buf = ""
        buf += line
    if buf:
        parts.append(buf)
    return parts or [""]


class UnknownResult(Exception):
    """응답을 못 받아 성공 여부를 모른다."""


class DmBlocked(Exception):
    """그 사람에게는 DM을 보낼 수 없다. 재시도해도 달라지지 않는다."""

    def __init__(self, code: int):
        super().__init__(f"discord {code}")
        self.code = code


class Bot:
    """Discord 봇 REST. 개인 DM과 채널 게시 두 가지만 한다.

    게이트웨이(수신)는 listener.py가 discord.py로 맡는다. 여기는 발송 전용이라
    httpx 동기 호출로 충분하다.
    """

    def __init__(
        self, token: str, channel_id: str = "", store=None, transport=None, sleep=time.sleep
    ):
        self.http = httpx.Client(
            base_url=API,
            timeout=15,
            headers={"Authorization": f"Bot {token}", "User-Agent": UA},
            transport=transport,
        )
        # 팀 채널: 주간 보고와 'DM을 못 보냈다' 통보가 가는 곳. 배포당 하나다.
        self.channel_id = str(channel_id)
        self.store = store
        self.sleep = sleep

    # ---------- 개인 DM ----------

    def dm_channel(self, discord_user_id: str) -> str:
        """(봇, 사용자) 쌍의 DM 채널 id. 봇 전체가 한 버킷을 쓰므로 캐시한다.

        매번 열면 `40003 You are opening direct messages too fast`가 나고, 문서도
        새 DM을 여는 것 자체가 제한된다고 경고한다.
        """
        if self.store is not None:
            cached = self.store.dm_channel(discord_user_id)
            if cached:
                return cached
        data = self._request(
            "POST", "/users/@me/channels", {"recipient_id": str(discord_user_id)}
        )
        channel_id = str(data["id"])
        if self.store is not None:
            self.store.save_dm_channel(discord_user_id, channel_id)
        return channel_id

    def send_dm(self, discord_user_id: str, text: str) -> str:
        """받는 사람 본인에게만 가므로 멘션을 만들지 않는다."""
        channel_id = self.dm_channel(discord_user_id)
        try:
            self._send(channel_id, text, parse=[])
        except DmBlocked as e:
            if e.code != STALE_CHANNEL:
                raise
            # 캐시한 채널이 사라졌다. 한 번만 다시 열고 재전송한다.
            if self.store is not None:
                self.store.forget_dm_channel(discord_user_id)
            self._send(self.dm_channel(discord_user_id), text, parse=[])
        return "sent"

    # ---------- 채널 ----------

    def send_channel(self, text: str) -> str:
        """팀 채널 게시(주간 보고 등). 멘션이 목적이라 사용자 멘션만 허용한다."""
        if not self.channel_id:
            raise RuntimeError("DISCORD_CHANNEL_ID가 없습니다.")
        self._send(self.channel_id, text, parse=["users"])
        return "sent"

    # ---------- 내부 ----------

    def _send(self, channel_id: str, text: str, *, parse: list[str]) -> None:
        for part in chunk(text):
            self._request(
                "POST",
                f"/channels/{channel_id}/messages",
                {"content": part, "allowed_mentions": {"parse": parse}},
            )

    def _request(self, method: str, path: str, json_body: dict) -> dict:
        """3회까지. 429·5xx는 백오프, DM 불가 코드는 즉시 포기."""
        delay = 2.0
        last = None
        for _ in range(3):
            try:
                r = self.http.request(method, path, json=json_body)
            except httpx.TimeoutException as e:
                raise UnknownResult(str(e)) from e
            except httpx.HTTPError as e:
                last = e
                self.sleep(delay)
                delay *= 2
                continue
            if r.status_code in (200, 201, 204):
                return r.json() if r.content else {}
            code = _error_code(r)
            if code in NO_RETRY_CODES:
                raise DmBlocked(code)
            if r.status_code == 429 or r.status_code >= 500:
                # retry_after는 초 단위(v8+). 숫자를 하드코딩하지 않고 헤더/본문을 따른다.
                retry_after = _retry_after(r, delay)
                last = RuntimeError(f"HTTP {r.status_code}")
                self.sleep(max(retry_after, delay))
                delay *= 2
                continue
            raise RuntimeError(f"HTTP {r.status_code}: {r.text[:200]}")
        raise RuntimeError(f"3회 실패: {last}")


def _error_code(r: httpx.Response) -> int | None:
    try:
        return r.json().get("code")
    except Exception:  # noqa: BLE001  본문이 JSON이 아닐 수 있다
        return None


def _retry_after(r: httpx.Response, default: float) -> float:
    for value in (r.headers.get("Retry-After"), _body_retry_after(r)):
        try:
            return float(value)
        except (TypeError, ValueError):
            continue
    return default


def _body_retry_after(r: httpx.Response):
    try:
        return r.json().get("retry_after")
    except Exception:  # noqa: BLE001
        return None
```

### 봇 REST 규칙 (틀리기 쉬운 것만)

| 규칙 | 근거 |
|---|---|
| `Authorization: Bot <token>` | 봇 토큰은 `Bearer`가 아니다. 접두사가 틀리면 401 |
| `User-Agent`가 **필수** | 없으면 Cloudflare가 앞단에서 막고 `40333`이 온다. 배포마다 바뀔 값이 아니라 상수다(`UA`) |
| DM은 **호출 2회** | `POST /users/@me/channels {"recipient_id": …}` → 채널 id → `POST /channels/{id}/messages`. 채널 id는 SQLite에 캐시한다 — 새 DM을 여는 것 자체가 제한되고 `40003 You are opening direct messages too fast` 전용 코드까지 있다. 버킷은 봇 전체가 공유한다 |
| `allowed_mentions.parse` | 개인 DM은 `[]` (받는 사람 본인이라 멘션할 이유가 없다), 팀 채널은 `["users"]` (주간 보고는 멘션이 목적이고 `@everyone`·역할은 막는다) |
| `50007` · `50278` · `10013` (`NO_RETRY_CODES`) | 각각 DM 차단·닫힘 / 봇과 공통 서버 없음 / 없는 사용자. **그 사람에게는 영구적이다.** `DmBlocked`로 즉시 포기한다 — 재시도는 10분당 1만 invalid-request 예산만 태우고 LXC는 egress IP가 하나다 |
| `10003 Unknown channel` (`STALE_CHANNEL`) | 재시도 금지 코드에 함께 넣되(같은 채널로 다시 보내도 소용없다) 유일하게 복구 경로가 있다. 캐시 행을 지우고 **한 번만** 다시 연 뒤 재전송한다(`send_dm`의 `except DmBlocked`) |
| `429` · `5xx` | `Retry-After`(초 단위, v8+) → 없으면 본문 `retry_after` → 없으면 지수 백오프. 3회까지. 숫자를 하드코딩하지 않는다 |
| 타임아웃 | `UnknownResult`. 보냈는지 모르므로 **중복 발송하지 않는다**(`sent` 행이 `unknown`으로 남는다) |
| 성공 코드 | 메시지 생성은 `200` + JSON 본문이다(웹훅의 `204`가 아니다). `_request`는 `(200, 201, 204)`를 성공으로 보고 본문이 있으면 파싱한다 |

`chunk()`·`MAX_LEN`·`UnknownResult`와 3회 재시도 블록은 Webhook 시절 그대로 이관했다. `Webhook`·`Fanout`·`Sender` 별칭은 삭제됐다.

---

## Step 3. 메시지와 마감 알림

### `discord_service/messages.py`

```python
STATUS = {
    "todo": "시작 전",
    "doing": "진행 중",
    "paused": "일시정지",
    "blocked": "막힘",
    "review": "검토 대기",
    "done": "완료",
    "cancelled": "취소",
}
KIND_TITLE = {"d3": "D-3", "d1": "D-1", "d0": "오늘 마감", "overdue": "기한 초과"}

HELP = """이렇게 보내면 됩니다.
• `오늘` — 오늘 할 일
• `완료 12` — 12번(TASK-12) 태스크를 완료로
• `연장 12 2026-09-20 QA 지연` — 목표일을 미루고 사유 남기기
• `연결 <코드>` — 웹 설정 → 프로필에서 받은 코드로 계정 연결
• `연결해제` — 연결 끊기(DM 알림도 멈춥니다)"""


def mention(assignee: dict) -> str:
    """팀 채널 게시용. 개인 DM에는 쓰지 않는다(받는 사람 본인이다)."""
    did = assignee.get("discord_user_id")
    return f"<@{did}>" if did else assignee.get("display_name", "?")


def task_line(t: dict) -> str:
    """개인 DM용 한 줄. 담당자는 받는 사람 본인이라 넣지 않는다."""
    reason = f" ({t['stop_reason']})" if t.get("stop_reason") else ""
    return (
        f"• **{t['number']}** {t['title']} — {t['project']['name']}"
        f" — {STATUS.get(t['status'], t['status'])}{reason}\n  {t['url']}"
    )


def team_task_line(t: dict) -> str:
    """팀 채널용 한 줄. 누구 일인지 보여야 한다."""
    reason = f" ({t['stop_reason']})" if t.get("stop_reason") else ""
    return (
        f"• **{t['number']}** {t['title']} — {t['project']['name']} — {mention(t['assignee'])}"
        f" — {STATUS.get(t['status'], t['status'])}{reason}\n  {t['url']}"
    )


def deadline_message(kind: str, tasks: list[dict], today: str) -> str:
    head = f"📌 마감 알림 · {KIND_TITLE[kind]} · {today}"
    lines = [
        task_line(t) + (f"  (기한 {t['due_date']})" if kind == "overdue" else "") for t in tasks
    ]
    tail = '\n답장으로 처리할 수 있어요: `완료 12` · `연장 12 2026-09-20 사유` · `도움`'
    return head + "\n" + "\n".join(lines) + tail


def dm_blocked_message(assignee: dict) -> str:
    """DM이 막힌 사람에게 팀 채널로 알리는 문구. 태스크 내용은 넣지 않는다."""
    return (
        f"{mention(assignee)} 마감 알림 DM을 보낼 수 없어요. 서버 우클릭 → 개인정보 보호 설정 →"
        " '서버 멤버의 DM 허용'을 켜 주세요."
    )


def today_message(view: dict) -> str:
    """`오늘` 답장. 오늘 화면과 같은 내용."""
    c = view["counts"]
    head = f"🗓 오늘 · {view['date']} · 미완료 {c['my_open']}건 · 오늘 완료 {c['done_today']}건"
    items = view["items"][:15]
    if not items:
        return head + "\n담은 일이 없습니다. 웹 `/today`에서 담아 보세요."
    more = len(view["items"]) - len(items)
    body = "\n".join(task_line(t) for t in items)
    return head + "\n" + body + (f"\n… 그리고 {more}건 더" if more > 0 else "")


def test_message(site_name: str) -> str:
    return f"✅ {site_name} Discord 봇 연결 테스트"
```

- `task_line()`에서 **담당자를 뺐다.** 개인 DM이라 받는 사람이 본인이다. 팀 채널용은 멘션이 남은 `team_task_line()`이다(`mention()`이 살아 있는 이유는 주간 보고).
- `deadline_message()` 마지막 줄이 답장 문법을 가르친다. 평문 명령에는 슬래시 명령의 자동완성이 없으니 마감 DM이 그 역할을 한다.
- `dm_blocked_message()`에는 **태스크 제목도 URL도 넣지 않는다.** 그 통보는 공개 채널로 간다.

### `discord_service/notify.py`

```python
import logging
from collections import defaultdict
from datetime import date, timedelta

from .core_client import CoreClient
from .discord import Bot, ChannelOpenFailed, DmBlocked, UnknownResult
from .messages import deadline_message, dm_blocked_message
from .store import Store

log = logging.getLogger(__name__)
OPEN = ("todo", "doing", "paused", "blocked", "review")
KINDS = ("d3", "d1", "d0", "overdue")


def classify(task: dict, today: date) -> str | None:
    """오늘 기준 이 태스크에 보낼 알림 종류. 없으면 None."""
    if not task.get("due_date") or task["status"] not in OPEN:
        return None
    due = date.fromisoformat(task["due_date"])
    delta = (due - today).days
    if delta == 3:
        return "d3"
    if delta == 1:
        return "d1"
    if delta == 0:
        return "d0"
    if delta < 0:
        return "overdue"
    return None


def run_deadlines(core: CoreClient, bot: Bot, store: Store, team_id: int, today: date) -> dict:
    """하루 1회. 담당자별 개인 DM으로 보낸다.

    한 사람이 하루에 받는 DM은 종류당 1건, 최대 4건이다(D-3·D-1·당일·기한 초과).
    태스크마다 한 통씩 보내면 아침에 DM 폭탄이 되고 Discord Developer Policy의
    '원치 않는 반복 DM'에 걸린다.
    """
    today_s = today.isoformat()
    result = {
        "sent": 0,
        "skipped": 0,
        "failed": 0,
        "unknown": 0,
        "unlinked": 0,
        # 자리를 놓아준 것들. 하루 1회 문턱(claim_daily)을 다시 열어야 실제로 재시도된다.
        "open_failed": 0,
        "recheck_failed": 0,
    }
    unlinked_names: list[str] = []
    candidates = core.open_tasks(team_id, due_to=(today + timedelta(days=3)).isoformat())

    # (종류, 담당자) 로 묶는다. 담당자는 태스크당 한 명이다.
    grouped: dict[tuple[str, int], list[dict]] = defaultdict(list)
    for t in candidates:
        kind = classify(t, today)
        assignee = t.get("assignee") or {}
        if kind and assignee.get("id"):
            grouped[(kind, assignee["id"])].append(t)

    for kind in KINDS:
        for uid in sorted(u for (k, u) in grouped if k == kind):
            tasks = grouped[(kind, uid)]
            assignee = tasks[0]["assignee"]
            did = assignee.get("discord_user_id")
            if not did:
                # 자리를 잡지 않는다. 나중에 연결하면 그 다음 알림부터 정상으로 받는다.
                result["unlinked"] += 1
                name = assignee.get("display_name") or str(uid)
                if name not in unlinked_names:
                    unlinked_names.append(name)
                log.warning("Discord 미연결이라 DM을 못 보낸다: %s", assignee.get("display_name"))
                continue
            key = f"{kind}:{uid}"
            if not store.claim(0, key, today_s):
                result["skipped"] += 1
                continue
            try:
                fresh = [core.task(t["id"]) for t in tasks]  # 발송 직전 재확인 (A09, A10)
            except Exception as e:  # noqa: BLE001
                # 자리를 잡아 둔 채 나가면 그 알림은 영구히 안 나간다. 놓아준다.
                # skipped(이미 보냄·더 이상 해당 없음)와 섞으면 손실이 안 보이므로 따로 센다 —
                # 이 숫자가 0이 아니면 scheduler가 그날 문턱을 다시 열고 /ops를 빨강으로 만든다.
                store.release(0, key, today_s)
                result["recheck_failed"] += 1
                log.warning("재확인 실패, 이 틱 뒤에 다시 훑는다: %s: %s", key, e)
                continue
            live = [f for f in fresh if f and classify(f, today) == kind]
            if not live:
                store.release(0, key, today_s)
                result["skipped"] += 1
                continue
            live.sort(key=lambda x: (x["due_date"], x["id"]))
            _send_dm(bot, store, did, deadline_message(kind, live, today_s), key, today_s, result)

    result["unlinked_names"] = unlinked_names
    return result


def _send_dm(bot, store, did, text, key, day, result):
    try:
        bot.send_dm(did, text)
        store.mark(0, key, day, "sent")
        result["sent"] += 1
    except ChannelOpenFailed as e:
        # 아직 아무것도 보내지 않았다. 자리를 놓아준다(scheduler가 그날 문턱을 다시 연다).
        store.release(0, key, day)
        result["open_failed"] += 1
        log.warning("DM 채널을 열지 못했다, 다음 실행에서 재시도: %s: %s", key, e)
    except DmBlocked as e:
        # 영구 실패다. 자리를 남겨 다음 틱에 다시 시도하지 않는다(403은 invalid-request 예산을 태운다).
        store.mark(0, key, day, "failed", str(e))
        result["failed"] += 1
        log.error("DM 거부: %s %s", key, e)
        _notify_channel_once(bot, store, did, day)
    except UnknownResult as e:
        store.mark(0, key, day, "unknown", str(e))
        result["unknown"] += 1
        log.warning("발송 결과 불명확: %s", key)
    except Exception as e:  # noqa: BLE001
        store.mark(0, key, day, "failed", str(e))
        result["failed"] += 1
        log.error("발송 실패: %s: %s", key, e)


def _notify_channel_once(bot, store, did, day):
    """DM이 막힌 사람에게는 팀 채널로 하루 한 번만 알린다. 태스크 내용은 넣지 않는다."""
    if not store.claim(0, f"dmblocked:{did}", day):
        return
    try:
        bot.send_channel(dm_blocked_message({"discord_user_id": did}))
        store.mark(0, f"dmblocked:{did}", day, "sent")
    except Exception as e:  # noqa: BLE001
        store.mark(0, f"dmblocked:{did}", day, "failed", str(e))
        log.error("DM 거부 통보 실패: %s", e)
```

### 중복 방지 키 — 담당자별

```
store.claim(0, f"{kind}:{uid}", today)      # 예: (0, "d1:2", "2026-09-09")
```

- `task_id`는 **0**, `kind`는 `종류:PM 사용자 id`, `due_date` 칼럼에는 **날짜**가 들어간다. 한 사람이 하루에 받는 DM은 최대 4건(D-3 · D-1 · 당일 · 기한 초과)이다.
- 태스크마다 한 통씩 보내면 09:00에 DM 폭탄이 되고 Discord Developer Policy의 '빈번한 원치 않는 DM'에 걸린다. 방어 논거는 "사용자가 직접 `연결`한 계정에만 · 자기 담당 태스크만 · 사람당 하루 최대 4건 · `연결해제`가 즉시 opt-out"이다. **claim → 발송 → mark 순서와 '실패는 재시도 없음' 규칙을 느슨하게 하지 않는다**(반복 발송 버그는 봇과 소유자 계정 정지 사유다).
- 키를 **PM 사용자 id**로 잡는 이유: Discord를 재연결해도 그 날의 자리가 바뀌지 않는다. 반대로 DM 채널 캐시(`dm` 표)는 (봇, Discord 사용자) 쌍의 속성이라 **discord id**를 키로 쓴다.
- 이전 개정의 기한 초과 특례 루프와 `claim_daily("overdue")`는 **삭제**됐다. 네 종류가 한 루프로 합쳐져 `notify.py`가 짧아졌다.
- **배포 시각 제약이 없다.** `scheduler.py`의 `store.claim_daily("deadline", today)`가 마감 잡을 이미 하루 1회로 막고 그 행은 볼륨에 남는다. 그날 이미 돌았으면 새 코드도 건너뛰고, 안 돌았으면 새 키로 한 번 돈다. 옛 키(`(12,"d1",…)`, `(0,"overdue",…)`)는 아무도 읽지 않는 죽은 행이 된다 — 중복 발송 경로가 없으니 시드 마이그레이션도 필요 없다.

### 실패 분기 전부

| 상황 | 처리 | 결과 |
|---|---|---|
| 담당자에게 `discord_user_id`가 없다 | DM을 시도하지 않고 **`claim`도 하지 않는다** → 나중에 연결하면 그 다음 알림부터 정상 | `unlinked += 1`, `unlinked_names`에 표시 이름, WARNING 로그 1줄. **`failed`가 아니다** |
| `50007` · `50278` · `10013` (`DmBlocked`) | `mark(…, "failed")`로 자리를 **남긴다** → 다음 60초 틱에 재시도되지 않는다 | `failed += 1` → `/ops` 빨강 + detail에 코드. 팀 채널에 대체 통보 1건(`claim(0, f"dmblocked:{did}", day)`로 사람당 하루 1회, 본문에 태스크 정보 없음) |
| `40003` · `429` · `5xx` | 3회 / `Retry-After` 백오프 | 끝까지 실패하면 `failed` |
| `httpx.TimeoutException` | `UnknownResult` | `status="unknown"`, 중복 발송하지 않는다 |
| 재확인(`core.task`) 실패 | `store.release` + **그날 문턱 다시 열기**(scheduler) → 다음 틱에 다시 훑는다 | `recheck_failed += 1` |
| 재확인 결과 `classify != kind` (완료·취소·기한 변경) | `release` | `skipped += 1` |
| `10003`으로 캐시한 DM 채널이 죽음 | 캐시 삭제 → 1회 재개설 → 재전송 | 성공 |

규칙 정리:

- D-3 · D-1 · 당일은 **그 날에만** 보낸다. `classify`가 정확히 3, 1, 0일 차이만 잡으므로 하루 지나면 자동으로 안 보낸다(소급 금지).
- 발송 직전에 묶인 태스크를 각각 `core.task(id)`로 다시 읽고 `classify(f, today) == kind`만 남긴다. 완료·취소·기한 변경이 여기서 걸러진다(옛 `fresh["due_date"] != t["due_date"]` 검사는 `classify`가 이미 포함해서 지웠다).
- 막힘·일시정지 태스크도 미완료이므로 포함한다. 메시지에는 상태 뒤에 사유가 괄호로 붙는다.
- `failed`로 남은 건은 재시도하지 않는다. `# ponytail: 실패 건 자동 재시도 없음, 필요하면 status='failed' 행을 다음날 재시도`

---

## Step 4. 주간 보고

### `discord_service/summarize.py`

```python
from .messages import mention


def fixed_summary(data: dict) -> str:
    """LLM 없이 만드는 고정 형식 보고서."""
    c = data["counts"]
    head = (
        f"📊 주간 업데이트 · {data['team']['name']} · "
        f"{data['period_start']} ~ {data['period_end']} (직전 주)"
    )
    quiet = (
        c["completed"] == 0
        and c["reopened"] == 0
        and c["overdue"] == 0
        and c["blocked"] == 0
        and c["due_this_week"] == 0
    )
    if quiet:
        return head + "\n특이 사항 없음. 미완료 " + str(c["open"]) + "건."

    def section(title, items, extra=None):
        if not items:
            return ""
        lines = [f"**{title}** ({len(items)})"]
        for t in items:
            s = f"• {t['number']} {t['title']} — {t['project']['name']} — {mention(t['assignee'])}"
            if extra:
                s += extra(t)
            lines.append(s)
        return "\n".join(lines) + "\n"

    body = [
        head,
        "",
        section("지난주 완료", data["completed"]),
        section("지난주 재개", data["reopened"]),
        section("이번 주 마감", data["due_this_week"], lambda t: f" — {t['due_date']}"),
        section("기한 초과", data["overdue"], lambda t: f" — 기한 {t['due_date']}"),
        section("막힘", data["blocked"]),
    ]
    proj = [
        f"• {p['project']['name']}: 완료 {p['completed']} · 미완료 {p['open']} · "
        f"초과 {p['overdue']} · 막힘 {p['blocked']}"
        for p in data["by_project"]
    ]
    if proj:
        body.append("**프로젝트별**\n" + "\n".join(proj))
    body.append(f"검토 대기 {c['review']}건 · 기한 미정 {c['no_due']}건")
    # /ops는 staff만 보지만 이 보고는 당사자가 본다. 연결을 안 한 사람이 스스로 알게 한다.
    unlinked = [m["display_name"] for m in data.get("members", []) if not m.get("discord_user_id")]
    if unlinked:
        body.append(
            "⚠️ Discord 미연결: " + ", ".join(unlinked) + " — 개인 DM 마감 알림을 못 받습니다."
        )
    return "\n".join(b for b in body if b is not None)


def summarize(data: dict, provider: str) -> tuple[str, str]:
    """(요약문, source). provider가 비어 있거나 실패하면 고정 형식."""
    if not provider:
        return fixed_summary(data), "fixed"
    try:
        text = _llm(data, provider)
        if not text or not text.strip():
            raise RuntimeError("empty")
        return text.strip(), "llm"
    except Exception:  # noqa: BLE001
        return fixed_summary(data), "fixed"


def _llm(data: dict, provider: str) -> str:
    # ponytail: 제공업체 미정. 정해지면 여기 분기 하나만 추가한다. 다른 파일은 손대지 않는다.
    raise NotImplementedError(f"LLM provider not configured: {provider}")
```

마지막 `unlinked` 블록이 이 개정에서 추가됐다. `/ops`는 staff만 보지만 주간 채널 보고는 당사자가 본다 — 연결을 안 한 사람이 스스로 알게 한다. `data["members"]`는 core의 주간 API가 이미 `user_brief`로 실어 준다(GUIDE-01-2 §4.1).

### `discord_service/weekly.py`

```python
import json
import logging
from datetime import date, timedelta

from .core_client import CoreClient
from .discord import Bot, UnknownResult
from .store import Store
from .summarize import summarize

log = logging.getLogger(__name__)


def last_monday(today: date) -> date:
    this_monday = today - timedelta(days=today.weekday())
    return this_monday - timedelta(days=7)


def run_weekly(
    core: CoreClient,
    bot: Bot,
    store: Store,
    team_id: int,
    week_start: date,
    provider: str,
    force: bool = False,
) -> dict:
    ws = week_start.isoformat()
    if not force and store.weekly_sent(ws):
        return {"status": "skipped", "period_start": ws}
    data = core.weekly(team_id, ws)
    summary, source = summarize(data, provider)
    try:
        bot.send_channel(summary)
        status = "sent"
    except UnknownResult:
        status = "unknown"
    except Exception as e:  # noqa: BLE001
        log.error("주간 보고 발송 실패: %s", e)
        status = "failed"
    store.save_weekly(ws, json.dumps(data, ensure_ascii=False), summary, source, status)
    return {"status": status, "period_start": ws, "source": source}
```

주간 보고는 **팀 채널 1건**이다. 개인 DM으로 쪼개지 않는다 — `weekly` 표의 PK가 `period_start` 하나이고 SQLite는 PK를 ALTER할 수 없다. 팀 보고는 공유물이기도 하다.

---

## Step 5. 스케줄러와 CLI

### `discord_service/scheduler.py`

```python
import logging
import time
from datetime import datetime

from .config import Config
from .core_client import CoreClient
from .discord import Bot
from .notify import run_deadlines
from .store import Store
from .weekly import last_monday, run_weekly

log = logging.getLogger(__name__)

# 놓아준 자리를 다시 훑을 기회. 하루 1회 문턱을 무한히 열어 주면 core가 아픈 동안 매 분
# 전체 스캔을 반복해 처리량 제한(60/m)을 스스로 태운다.
RETRY_SWEEPS = 3


def _reopen_today(store: Store, day: str) -> bool:
    """놓아준 알림이 있을 때 그날 문턱을 다시 연다. 하루 RETRY_SWEEPS번까지.

    중복 발송 걱정은 없다 — 이미 보낸 묶음은 `sent` 행이 막는다. 다시 여는 것은
    '아직 안 보낸 묶음만' 다시 훑겠다는 뜻이다.
    """
    for n in range(1, RETRY_SWEEPS + 1):
        if store.claim_daily(f"deadline-retry-{n}", day):
            store.release_daily("deadline", day)
            return True
    return False


def tick(cfg: Config, core: CoreClient, bot: Bot, store: Store, now: datetime) -> list[dict]:
    """1분마다 호출. 실행한 작업 결과 목록."""
    results = []
    today = now.date()
    day = today.isoformat()
    if now.hour >= cfg.send_hour and store.claim_daily("deadline", day):
        try:
            r = run_deadlines(core, bot, store, cfg.team_id, today)
            # 발송 실패는 예외로 올라오지 않고 결과에 세어진다(DM 거부·채널 열기 실패·재확인 실패).
            # /ops에 ok로 보이면 아무도 모른다. 미연결(unlinked)은 실패가 아니다 —
            # 한 명이 연결을 안 했다고 /ops가 영구 빨강이 되면 그 신호를 아무도 안 본다.
            retry_later = r["open_failed"] + r["recheck_failed"]
            ok = r["failed"] == 0 and retry_later == 0
            # 놓아준 자리는 그날 문턱을 다시 열어야 실제로 재시도된다. release()만으로는
            # claim_daily가 이미 소비돼 그날 다시 안 돈다(= 그 사람은 알림을 못 받는다).
            if retry_later:
                r["reopened"] = _reopen_today(store, day)
            store.record_run("deadline", ok, str(r))
            core.report_status(ok, {"job": "deadline", **r})
            results.append({"job": "deadline", **r})
        except Exception as e:  # noqa: BLE001
            store.release_daily("deadline", day)  # 다음 tick에 다시 시도
            store.record_run("deadline", False, str(e))
            core.report_status(False, {"job": "deadline", "error": str(e)})
            log.exception("deadline job failed")
    if now.weekday() == cfg.weekly_weekday and now.hour >= cfg.weekly_hour:
        ws = last_monday(today)
        if not store.weekly_sent(ws.isoformat()):
            try:
                r = run_weekly(core, bot, store, cfg.team_id, ws, cfg.llm_provider)
                store.record_run("weekly", r["status"] == "sent", str(r))
                core.report_status(r["status"] == "sent", {"job": "weekly", **r})
                results.append({"job": "weekly", **r})
            except Exception as e:  # noqa: BLE001
                store.record_run("weekly", False, str(e))
                core.report_status(False, {"job": "weekly", "error": str(e)})
                log.exception("weekly job failed")
    return results


def loop(cfg: Config):
    # ponytail: 단일 프로세스 전제. 복제 수를 늘리면 SQLite 파일을 공유하지 못하므로 1개만 띄운다.
    core = CoreClient(cfg.core_url, cfg.core_token)
    store = Store(cfg.db_path)
    bot = Bot(cfg.bot_token, cfg.channel_id, store)
    log.info("discord_service 시작 (team=%s, send_hour=%s)", cfg.team_id, cfg.send_hour)
    while True:
        try:
            tick(cfg, core, bot, store, datetime.now(cfg.tz))
        except Exception:  # noqa: BLE001
            log.exception("tick failed")
        time.sleep(60)
```

`send_hour` **이후** 첫 tick에 보내는 방식이다(`>=`). 서비스가 9시 이후에 켜져도 그날 알림을 한 번은 보낸다. 다만 하루 넘긴 D-3·D-1은 `classify`가 걸러 소급 발송하지 않는다.

`ok = r["failed"] == 0 and (r["open_failed"] + r["recheck_failed"]) == 0`이다 — **미연결(`unlinked`)은 실패가 아니다.** 한 명이 연결을 안 했다고 `/ops`가 영구 빨강이 되면 그 신호를 아무도 안 본다. 대신 `unlinked`·`unlinked_names`가 `report_status`의 detail과 주간 보고 본문에 실린다.

### `discord_service/__main__.py`

```python
import argparse
import json
import logging
from datetime import date, datetime

from . import listener
from .config import Config
from .core_client import CoreClient
from .discord import Bot
from .messages import test_message
from .notify import run_deadlines
from .scheduler import loop, tick
from .store import Store
from .weekly import last_monday, run_weekly


def main():
    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(name)s %(message)s")
    p = argparse.ArgumentParser(prog="discord_service")
    sub = p.add_subparsers(dest="cmd", required=True)
    sub.add_parser("run", help="60초 루프로 상주 (발송)")
    sub.add_parser("bot", help="DM 명령 수신으로 상주 (게이트웨이)")
    sub.add_parser("once", help="지금 시각 기준 tick 1회")
    sub.add_parser("test", help="팀 채널에 테스트 메시지 1건")
    w = sub.add_parser("weekly", help="주간 보고")
    w.add_argument("--now", action="store_true", help="이미 보냈어도 다시 보낸다")
    w.add_argument("--week-start", help="YYYY-MM-DD (월요일)")
    d = sub.add_parser("deadlines", help="마감 알림 즉시 실행")
    d.add_argument("--date", help="YYYY-MM-DD 기준일 (기본 오늘)")
    sub.add_parser("status", help="최근 발송 기록")
    a = p.parse_args()

    cfg = Config.from_env()
    core = CoreClient(cfg.core_url, cfg.core_token)

    # 리스너는 SQLite를 열지 않는다(발송 프로세스가 단일 writer로 남는다).
    if a.cmd == "bot":
        listener.run(cfg, core)
        return

    store = Store(cfg.db_path)
    bot = Bot(cfg.bot_token, cfg.channel_id, store)

    if a.cmd == "run":
        loop(cfg)
    elif a.cmd == "once":
        print(tick(cfg, core, bot, store, datetime.now(cfg.tz)))
    elif a.cmd == "test":
        bot.send_channel(test_message(cfg.site_name))
        print("sent")
    elif a.cmd == "weekly":
        ws = (
            date.fromisoformat(a.week_start)
            if a.week_start
            else last_monday(datetime.now(cfg.tz).date())
        )
        print(run_weekly(core, bot, store, cfg.team_id, ws, cfg.llm_provider, force=a.now))
    elif a.cmd == "deadlines":
        today = date.fromisoformat(a.date) if a.date else datetime.now(cfg.tz).date()
        print(run_deadlines(core, bot, store, cfg.team_id, today))
    elif a.cmd == "status":
        print(json.dumps(store.recent(), ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
```

`bot` 서브커맨드는 **`Store(...)` 생성 앞에서** 갈라진다. 이유:

- SQLite는 writer가 하나여야 한다. 발송 컨테이너(`discord`)가 그 하나다.
- 리스너는 발송 기록도 DM 채널 캐시도 쓸 일이 없다(답장은 `message.channel.send()`).
- 그래서 `discord-bot` 컨테이너에는 볼륨을 붙이지 않고, `Dockerfile`의 `VOLUME ["/data"]`도 삭제했다(익명 볼륨 누적 제거).

`discord_service/__init__.py`는 빈 파일.

---

## Step 6. DM 명령 수신 (리스너와 명령 해석)

### 명령 집합

리스너는 **평문 DM**을 읽는다. 슬래시 명령이 아니다 → 등록 스크립트·하루 200회 create 한도·3초 응답 시한과 defer·`40060` 중복 ACK가 전부 없다.

| 명령 | 동작 | core 엔드포인트 |
|---|---|---|
| `연결 <8자코드>` / `link` | 이 Discord 계정을 PM 계정에 연결 | `POST /api/integrations/discord/link` |
| `연결해제` / `unlink` | 연결을 끊는다. 즉시 DM 알림이 멈추므로 **수신 거부 수단**을 겸한다 | `POST …/unlink` |
| `오늘` / `today` | 오늘 화면과 같은 내용. 최대 15줄 | `POST …/today` |
| `완료 <번호>` / `done` | 태스크를 완료로. 마감 DM에 그대로 답장하는 핵심 동작 | `POST …/tasks/{id}/done` |
| `연장 <번호> <YYYY-MM-DD> <사유…>` / `extend` | 목표일을 미루고 사유를 이력에 남긴다 | `POST …/tasks/{id}/extend` |
| 그 밖의 텍스트 (`도움` 포함) | `HELP` 답장. 오타·잡담이 조용히 무시되지 않게 | 호출 없음 |

- `번호`는 `12`와 `TASK-12`를 모두 받는다(`upper().replace("TASK-", "")` + `isdecimal()` — 검색 화면과 같은 방식).
- `expected_version`은 **core 라우터가** 같은 요청 안에서 태스크를 읽어 그 값으로 CAS를 건다. 사용자는 버전을 본 적이 없고 의도는 "지금 완료로 바꿔라"다. 읽기와 쓰기 사이(수 ms)에 웹 편집이 끼면 409 → `방금 다른 곳에서 바뀌었어요.` **재시도 루프를 만들지 않는다.**
- 같은 `완료`를 두 번 보내도 무해하다(core가 같은 상태면 조기 반환한다 — 이력도 한 줄). `연장`은 멱등이 아니지만 현재 목표일보다 앞 날짜를 거부하므로 이중 연장이 구조적으로 불가능하다.

### `discord_service/listener.py`

```python
"""봇에게 온 DM을 받는 상주 프로세스.

`import discord`는 절대 임포트라 site-packages의 discord.py를 가리킨다
(같은 패키지의 `discord_service/discord.py`가 아니다 — 패키지 디렉터리는 sys.path에 없다).

인텐트는 `DIRECT_MESSAGES`(1<<12) 하나, 비특권이다. 봇에게 온 DM의 본문은
MESSAGE_CONTENT 특권 인텐트 없이도 전달된다(문서 명시 예외). 특권 인텐트는 켜지 않는다.
"""

import asyncio
import logging
import time

import discord

from .commands import handle
from .core_client import CoreClient
from .discord import chunk

log = logging.getLogger(__name__)

# 발신자별 분당 한도. core의 처리량 제한(60/m)은 봇 계정 하나로 세므로 한 사람이
# 다 쓰면 다른 사람 명령까지 429가 된다.
RATE = 20


def too_fast(seen: dict[str, list[float]], uid: str, now: float) -> bool:
    recent = [t for t in seen.get(uid, []) if now - t < 60]
    recent.append(now)
    seen[uid] = recent
    return len(recent) > RATE


def run(cfg, core: CoreClient):
    intents = discord.Intents.none()
    intents.dm_messages = True
    client = discord.Client(intents=intents)
    seen: dict[str, list[float]] = {}

    @client.event
    async def on_ready():
        log.info("discord 봇 접속: %s", client.user)

    @client.event
    async def on_message(message):
        if message.author.bot or message.guild is not None:
            return  # 자기 메시지 루프 방지 + DM만 받는다
        uid = str(message.author.id)
        if too_fast(seen, uid, time.monotonic()):
            log.warning("발신자 한도 초과로 무시: %s", uid)
            return
        # CoreClient는 동기 httpx다. 이벤트 루프에서 그대로 부르면 하트비트가 굶어
        # 게이트웨이가 연결을 끊는다.
        reply = await asyncio.to_thread(handle, core, uid, message.content)
        for part in chunk(reply):
            await message.channel.send(part, allowed_mentions=discord.AllowedMentions.none())

    # 재접속·하트비트·RESUME·close code 처리는 라이브러리가 맡는다.
    client.run(cfg.bot_token, log_handler=None)
```

**인텐트는 `DIRECT_MESSAGES`(1<<12) 하나, 비특권이다.** 특권 인텐트(MESSAGE CONTENT, GUILD MEMBERS, PRESENCE)는 하나도 켜지 않는다 — 봇에게 온 DM의 본문은 MESSAGE CONTENT 없이도 전달되는 **문서에 명시된 예외**다. 포털에서 켤 토글이 없다는 뜻이고, 심사도 없다.

지키는 것 세 가지:

1. `message.author.bot`이면 무시 — 자기 답장에 자기가 반응하는 루프를 막는다.
2. `message.guild is not None`이면 무시 — 서버 채널 대화를 명령으로 읽지 않는다. `channel.type` 비교보다 안전하다.
3. `asyncio.to_thread(handle, …)` — `CoreClient`는 **동기** `httpx`다. 이벤트 루프에서 그대로 부르면 하트비트가 굶어 게이트웨이가 연결을 끊는다.

`too_fast()`는 발신자별 분당 20회다. core의 처리량 제한은 토큰 소유자(`request.auth.pk`) 기준이고 봇 계정은 하나라서, 한 사람이 다 쓰면 다른 사람 명령까지 429가 된다. 순수 함수라 테스트가 한 줄이다.

리스너는 `/ops`에 상태를 보고하지 **않는다.** `IntegrationStatus`는 `name` 단일 키라 보고하면 틱의 `discord` 행을 덮어쓰고, 재접속은 라이브러리가 맡으니 보고할 close code도 없다. 상태는 `docker compose logs discord-bot` + `restart: unless-stopped`로 본다.

### `discord_service/commands.py`

```python
"""DM 평문 명령 해석. core를 부르고 한국어 답장 문자열을 돌려준다.

여기에는 업무 규칙이 없다. 파싱과 문구뿐이고, 판단은 전부 core의 services가 한다.
"""

import logging
from datetime import date

import httpx

from .core_client import CoreClient
from .messages import HELP, today_message

log = logging.getLogger(__name__)

NEED_NUMBER = '태스크 번호가 필요해요. 예: `완료 12` (마감 알림의 "TASK-12"에서 숫자만)'
NEED_CODE = "연결 코드가 필요해요. 웹 설정 → 프로필에서 [Discord 연결]을 누르면 나옵니다."
NEED_EXTEND = "예: `연장 12 2026-09-20 QA 지연` (번호, 새 목표일, 사유)"


def task_number(token: str) -> int | None:
    """`12`와 `TASK-12`를 모두 받는다(검색 화면과 같은 방식)."""
    t = (token or "").upper().replace("TASK-", "").strip()
    return int(t) if t.isdecimal() else None


def handle(core: CoreClient, author_id: str, text: str) -> str:
    parts = (text or "").strip().split()
    if not parts:
        return HELP
    cmd, args = parts[0], parts[1:]
    try:
        return _dispatch(core, author_id, cmd, args)
    except httpx.HTTPStatusError as e:
        return _error_reply(e.response)
    except httpx.HTTPError as e:
        log.warning("core 호출 실패: %s", e)
        return "지금은 처리하지 못했어요. 잠시 뒤 다시 보내 주세요."


def _dispatch(core: CoreClient, author_id: str, cmd: str, args: list[str]) -> str:
    if cmd in ("연결", "link"):
        if not args:
            return NEED_CODE
        name = core.link(args[0], author_id).get("display_name", "")
        return f"{name} 계정과 연결했습니다. `오늘` 을 보내 보세요."
    if cmd in ("연결해제", "unlink"):
        core.unlink(author_id)
        return "연결을 끊었습니다. 마감 알림 DM도 멈춥니다."
    if cmd in ("오늘", "today"):
        return today_message(core.today(author_id))
    if cmd in ("완료", "done"):
        num = task_number(args[0]) if args else None
        if num is None:
            return NEED_NUMBER
        r = core.done(author_id, num)
        t = r["task"]
        return f"**{t['number']}** {t['title']} — {r['was']} → 완료로 바꿨습니다."
    if cmd in ("연장", "extend"):
        num = task_number(args[0]) if args else None
        if num is None or len(args) < 2:
            return NEED_EXTEND
        try:
            due = date.fromisoformat(args[1])
        except ValueError:
            return "날짜 형식은 `2026-09-20` 처럼 보내 주세요."
        reason = " ".join(args[2:])
        t = core.extend(author_id, num, due.isoformat(), reason)["task"]
        return f"**{t['number']}** {t['title']} — 목표일을 {t['due_date']}로 미뤘습니다."
    return HELP


def _error_reply(r: httpx.Response) -> str:
    detail = _detail(r)
    if r.status_code == 404:
        return detail or '찾을 수 없습니다. `연결` 이 필요할 수 있어요.'
    if r.status_code == 403:
        return "권한이 없습니다."
    if r.status_code == 409:
        return "방금 다른 곳에서 바뀌었어요. 다시 보내 주세요."
    if r.status_code == 429:
        return "요청이 몰렸어요. 1분 뒤 다시 보내 주세요."
    if r.status_code == 400:
        return detail or "입력을 다시 확인해 주세요."
    log.warning("core %s: %s", r.status_code, detail)
    return "지금은 처리하지 못했어요. 잠시 뒤 다시 보내 주세요."


def _detail(r: httpx.Response) -> str:
    """`{"detail": "문구"}`(HttpError)와 `{"detail": {필드: 문구}}`(ServiceError) 둘 다."""
    try:
        d = r.json().get("detail")
    except Exception:  # noqa: BLE001
        return ""
    if isinstance(d, str):
        return d
    if isinstance(d, dict):
        return " ".join(str(v) for v in d.values())
    return ""
```

업무 규칙이 여기 없다. 파싱과 문구뿐이고 판단은 전부 core의 services가 한다.

| 상태 | 답장 |
|---|---|
| 404 | 응답 본문의 한국어 문구(없으면 `찾을 수 없습니다. 연결 이 필요할 수 있어요.`). 미연결 계정이 `완료 12`를 보내면 여기로 온다 — **쓰기 호출은 0회** |
| 403 | `권한이 없습니다.` |
| 409 | `방금 다른 곳에서 바뀌었어요. 다시 보내 주세요.` |
| 429 | `요청이 몰렸어요. 1분 뒤 다시 보내 주세요.` |
| 400 | 응답 본문의 한국어 문구 그대로 |
| 그 밖 · `httpx.HTTPError` | `지금은 처리하지 못했어요. 잠시 뒤 다시 보내 주세요.` |

`_detail()`이 두 모양을 모두 받는다: `HttpError`는 `{"detail": "문구"}`, `ServiceError`는 `{"detail": {필드: 문구}}`다. 그래서 `연장`을 현재 목표일보다 앞 날짜로 보내면 core의 `현재 목표일보다 뒤의 날짜를 선택하세요.`가 그대로 사용자에게 간다("오류"가 아니라 "이미 연장됨"으로 읽힌다).

일부러 넣지 않은 명령: `메모`(core의 `update_text`가 ChangeLog를 남기지 않아 내용 변경이 감사 기록에서 사라진다), `시작`/`막힘`(`완료`와 같은 호출 지점에 상태 리터럴만 다르다 — 5명에게 6개 명령은 과하다).

---

## Step 7. 테스트

Webhook 시절의 `tests/test_fanout.py`(9개)와 `FakeHook`은 **삭제한다** — `Fanout`이 없다. 그 파일에서 살릴 값이 있던 "전부 실패한 틱은 `/ops`에 ok로 보이지 않는다"만 `test_notify.py`로 옮겼다.

`FakeBot`은 `Bot`을 흉내 내지 않고 **실제 `Bot`을 `httpx.MockTransport`로 감싼다.** 그래서 `Authorization: Bot …`·`User-Agent`·`allowed_mentions`·"DM은 호출 2회"·429 백오프가 전부 진짜 코드 경로로 검증된다.

### `tests/conftest.py`

```python
import json

import httpx
import pytest

from discord_service.core_client import CoreClient
from discord_service.discord import Bot
from discord_service.messages import STATUS
from discord_service.store import Store

OPEN = ("todo", "doing", "paused", "blocked", "review")
BOT_PREFIX = "/api/integrations/discord/"
CHANNEL = "999"  # 팀 채널 id (DISCORD_CHANNEL_ID)


def member(i=2, did="111", name="팀원"):
    return {"id": i, "display_name": name, "discord_user_id": did}


def task(i, due, status="todo", stop_reason="", assignee=None):
    return {
        "id": i,
        "number": f"TASK-{i}",
        "title": f"할 일 {i}",
        "project": {"id": 1, "name": "학식 API", "team_id": 1},
        "assignee": member() if assignee is None else assignee,
        "status": status,
        "priority": 5,
        "due_date": due,
        "stop_reason": stop_reason,
        "next_action": "",
        "url": f"http://pm/tasks/{i}",
    }


def weekly_data(
    completed=(),
    reopened=(),
    due_this_week=(),
    overdue=(),
    blocked=(),
    by_project=None,
    members=None,
):
    completed, reopened = list(completed), list(reopened)
    due_this_week, overdue, blocked = list(due_this_week), list(overdue), list(blocked)
    return {
        "team": {"id": 1, "name": "산돌이"},
        "period_start": "2026-08-31",
        "period_end": "2026-09-07",
        "completed": completed,
        "reopened": reopened,
        "due_this_week": due_this_week,
        "overdue": overdue,
        "blocked": blocked,
        "by_project": by_project
        if by_project is not None
        else [
            {
                "project": {"id": 1, "name": "학식 API", "status": "active"},
                "completed": len(completed),
                "reopened": len(reopened),
                "open": 2,
                "overdue": len(overdue),
                "blocked": len(blocked),
            }
        ],
        "counts": {
            "completed": len(completed),
            "reopened": len(reopened),
            "due_this_week": len(due_this_week),
            "overdue": len(overdue),
            "blocked": len(blocked),
            "open": 2,
            "review": 0,
            "no_due": 0,
        },
        "members": [member()] if members is None else list(members),
    }


class FakeCore:
    """core API 흉내. tasks dict를 바꾸면 응답이 바뀐다.

    봇 명령 5개(`/api/integrations/discord/…`)를 함께 흉내 낸다. `bot_status`를
    404·403·409·429·400 중 하나로 바꾸면 그 상태와 `bot_detail`(한국어 문구)로 답한다.
    """

    def __init__(self, tasks: list[dict], weekly: dict | None = None):
        self.tasks = {t["id"]: t for t in tasks}
        self.weekly_data = weekly
        self.status_reports = []
        self.calls: list[tuple[str, dict]] = []  # 봇 명령 호출 (경로, 본문)
        self.writes: list[tuple[str, dict]] = []  # 실제로 태스크를 바꾼 호출만
        self.bot_status = 200
        self.bot_detail = "x"

    # --- 조회 도움말 ---
    def paths(self) -> list[str]:
        return [p for p, _ in self.calls]

    def handler(self, request: httpx.Request) -> httpx.Response:
        path = request.url.path
        if path == "/api/tasks":
            items = [t for t in self.tasks.values() if t["status"] in OPEN]
            due_to = request.url.params.get("due_to")
            if due_to:
                items = [t for t in items if t["due_date"] and t["due_date"] <= due_to]
            return httpx.Response(
                200, json={"items": items, "total": len(items), "limit": 200, "offset": 0}
            )
        if path.startswith("/api/tasks/"):
            t = self.tasks.get(int(path.rsplit("/", 1)[1]))
            return httpx.Response(200, json=t) if t else httpx.Response(404, json={"detail": "x"})
        if path == "/api/reports/weekly":
            return httpx.Response(200, json=self.weekly_data)
        if path == BOT_PREFIX + "status":
            self.status_reports.append(json.loads(request.content))
            return httpx.Response(204)
        if path.startswith(BOT_PREFIX):
            return self._bot(path.removeprefix(BOT_PREFIX), json.loads(request.content))
        return httpx.Response(404)

    def _bot(self, cmd: str, body: dict) -> httpx.Response:
        self.calls.append((cmd, body))
        if self.bot_status != 200:
            return httpx.Response(self.bot_status, json={"detail": self.bot_detail})
        if cmd == "link":
            return httpx.Response(200, json={"display_name": "홍길동"})
        if cmd == "unlink":
            return httpx.Response(200, json={"unlinked": True})
        if cmd == "today":
            items = [t for t in self.tasks.values() if t["status"] in OPEN]
            return httpx.Response(
                200,
                json={
                    "display_name": "홍길동",
                    "date": "2026-09-09",
                    "items": items,
                    "counts": {"my_open": len(items), "done_today": 1},
                },
            )
        parts = cmd.split("/")  # tasks/<id>/<action>
        if len(parts) == 3 and parts[0] == "tasks":
            t = self.tasks.get(int(parts[1]))
            if t is None:
                return httpx.Response(404, json={"detail": "태스크를 찾을 수 없습니다."})
            self.writes.append((cmd, body))
            if parts[2] == "done":
                was = STATUS[t["status"]]
                t["status"] = "done"
                return httpx.Response(200, json={"was": was, "task": t})
            if parts[2] == "extend":
                t["due_date"] = body["due_date"]
                return httpx.Response(200, json={"task": t})
        return httpx.Response(404, json={"detail": "x"})


class FakeBot:
    """Discord 봇 REST 흉내. 실제 `Bot`을 MockTransport로 감싼다.

    `errors[채널id]`(또는 모든 채널을 뜻하는 `"*"`)에 `(상태, 본문)`을 넣으면 그 순서로
    답한다. 예: `{"dm-111": [(403, {"code": 50007})]}`, `{"*": [429]}`.
    """

    def __init__(self, errors: dict | None = None):
        self.calls: list[dict] = []  # 모든 요청 (경로·본문·헤더)
        self.opened: list[str] = []  # /users/@me/channels 를 부른 recipient_id
        self.messages: list[dict] = []  # 성공한 발송 (채널·본문·allowed_mentions)
        self.errors = {k: list(v) for k, v in (errors or {}).items()}

    # --- 조회 도움말 ---
    @property
    def sent(self) -> list[str]:
        return [m["content"] for m in self.messages]

    def to(self, channel: str) -> list[str]:
        return [m["content"] for m in self.messages if m["channel"] == channel]

    def dm(self, discord_user_id: str) -> list[str]:
        return self.to(f"dm-{discord_user_id}")

    def attempts(self, channel: str) -> int:
        return sum(1 for c in self.calls if c["path"] == f"/channels/{channel}/messages")

    def handler(self, request: httpx.Request) -> httpx.Response:
        path = request.url.path.removeprefix("/api/v10")
        body = json.loads(request.content)
        self.calls.append(
            {
                "path": path,
                "body": body,
                "auth": request.headers.get("Authorization"),
                "ua": request.headers.get("User-Agent"),
            }
        )
        if path == "/users/@me/channels":
            recipient = str(body["recipient_id"])
            self.opened.append(recipient)
            return httpx.Response(200, json={"id": f"dm-{recipient}"})
        channel = path.split("/")[2]
        status, payload = self._next(channel)
        if status != 200:
            headers = {"Retry-After": "0"} if status == 429 else {}
            return httpx.Response(status, json=payload, headers=headers)
        self.messages.append(
            {
                "channel": channel,
                "content": body["content"],
                "allowed_mentions": body["allowed_mentions"],
            }
        )
        return httpx.Response(200, json={"id": "m1"})

    def _next(self, channel: str) -> tuple[int, dict]:
        for key in (channel, "*"):
            queue = self.errors.get(key)
            if queue:
                e = queue.pop(0)
                return (e, {}) if isinstance(e, int) else e
        return 200, {}


def make_bot(fake: FakeBot, store=None, channel_id: str = CHANNEL) -> Bot:
    return Bot(
        "botsecret",
        channel_id,
        store,
        transport=httpx.MockTransport(fake.handler),
        sleep=lambda s: None,
    )


def make_core(fake: FakeCore) -> CoreClient:
    return CoreClient("http://core", "pm_test", transport=httpx.MockTransport(fake.handler))


@pytest.fixture
def store(tmp_path):
    return Store(str(tmp_path / "t.sqlite"))


@pytest.fixture
def fake_bot():
    return FakeBot()


@pytest.fixture
def bot(fake_bot, store):
    return make_bot(fake_bot, store)
```

읽는 방법 세 가지:

- `fake_bot.dm("111")` — 그 사람에게 실제로 도착한 본문 목록. `fake_bot.to(CHANNEL)`은 팀 채널.
- `fake_bot.attempts("dm-111")` — 그 채널로 나간 **HTTP 시도 횟수**. "재시도하지 않는다"를 이것으로 본다.
- `fake_core.paths()` / `fake_core.writes` — 봇 명령이 부른 경로와, 그중 **실제로 태스크를 바꾼** 호출. "쓰기 0회"를 `writes == []`로 본다.

### 테스트 목록 (58개)

`tests/test_discord.py` — 봇 REST 발송

| 테스트 | 검증 |
|---|---|
| `test_chunk_splits_long_text` | 3000자 초과 → 조각 2개 이상, 각 ≤1900, 이어 붙이면 원문 |
| `test_dm_opens_channel_then_sends_with_bot_headers` | 호출 순서가 `/users/@me/channels` → `/channels/dm-111/messages`. `allowed_mentions == {"parse": []}`, 본문에 `<@` 없음, 모든 요청에 `Authorization: Bot botsecret`과 `DiscordBot (` UA |
| `test_channel_post_allows_user_mentions` | 팀 채널 게시는 `{"parse": ["users"]}`이고 채널 id가 `cfg.channel_id` |
| `test_dm_channel_is_cached` | 같은 사람에게 2건 → `opened == ["111"]` (채널 개설 1회) |
| `test_unknown_channel_reopens_once` | 캐시가 있는데 첫 게시가 `(404, {"code": 10003})` → 캐시 삭제 후 **1회** 재개설, 게시 시도 2회, 결과는 성공 |
| `test_blocked_dm_raises_without_retry` | `(403, {"code": 50007})` → `DmBlocked(50007)`, 게시 시도 **1회**, 성공 발송 0건 |
| `test_retries_429_with_retry_after` | `429` 뒤 성공 → 시도 2회, 본문 1건 |
| `test_reopen_resends_only_the_failing_chunk` | 조각 2개 이상인 본문에서 두 번째가 `10003` → 재개설 후 **그 조각부터** 이어 보내고, 받은 조각 목록이 `chunk(text)`와 정확히 일치(앞 조각 중복 없음) |
| `test_channel_open_failure_is_retryable_not_unknown` | 채널 열기가 타임아웃 → `ChannelOpenFailed`(= `UnknownResult` 아님), 캐시에 아무것도 남지 않는다 |

`tests/test_notify.py` — 마감 알림

| 테스트 | 검증 |
|---|---|
| `test_classify` | 오늘 2026-09-09 기준 due 09-12→`d3`, 09-10→`d1`, 09-09→`d0`, 09-01→`overdue`, 09-11→None, None→None, status done→None |
| `test_dm_goes_to_the_assignee_only` | DM 1건 = 채널 개설 1회 + 발송 1회. 멘션 없음, 담당자 칼럼 없음, 봇 헤더 존재 |
| `test_same_kind_same_assignee_is_one_dm` | 같은 담당자·같은 종류 2건 → DM **1건**, `sent` 표의 kind가 `["d1:2"]` |
| `test_each_assignee_gets_their_own_dm` | 기한 초과 담당자 2명 → DM 2건, kind `["overdue:2", "overdue:3"]`. 같은 날 두 번째 실행은 `sent 0` / `skipped 2` |
| `test_sends_each_kind_once` | d3·d1·d0 각 1개 + overdue 2개(전부 담당자 id 2) → `sent == 4`(사람당 하루 최대 4건), 채널 개설 1회, 기한 초과 본문에 TASK-4·TASK-5 둘 다. 재실행 → `sent 0`, `skipped >= 4` |
| `test_unlinked_assignee_is_counted_not_claimed` | 미연결 담당자 → HTTP 호출 0회, **`sent` 행 0개**, `unlinked == 1`, `unlinked_names == ["미연결"]`, `failed == 0` |
| `test_blocked_dm_fails_once_and_notifies_channel` | `50007` → 그 행만 `failed`·`last_error`에 `50007`, 시도 1회, 다른 담당자는 정상. 팀 채널 통보 **1건**이고 본문에 태스크 제목(`할 일`)도 `http`도 없다. 같은 날 재실행하면 재발송 0·재통보 0 |
| `test_due_changed_before_send_not_sent` | `CoreClient.task`를 monkeypatch해 다른 `due_date` → `sent 0`, `skipped 1`, `sent` 표 비어 있음(자리를 놓아준다) |
| `test_completed_before_send_not_sent` | monkeypatch로 `status="done"` → `sent 0`, 발송 0건 |
| `test_recheck_failure_releases_the_claim` | `core.task`가 예외 → `recheck_failed 1`·`skipped 0`, `sent` 표 비어 있음 |
| `test_channel_open_failure_releases_the_claim` | `dm_channel`이 `ChannelOpenFailed` → `open_failed 1`·`failed 0`, `sent` 표 비어 있음. 아직 아무것도 보내지 않았으므로 그날 알림을 잃지 않는다 |
| `test_released_alerts_reopen_the_day_and_are_retried` | 재확인이 한 번 실패 → `recheck_failed 1`·`reopened True`·`/ops` 빨강, **같은 날 다시 훑어** 두 번째 틱에서 발송된다 |
| `test_reopening_the_day_is_bounded` | 계속 실패하면 `reopened`가 `[True, True, True, False]` — 첫 훑기 + 재훑기 3회로 끝난다(매 분 전체 스캔을 반복하지 않는다) |
| `test_blocked_task_included` | `blocked`+`stop_reason="서류 대기"` d0, `paused` d1 → 본문에 "막힘"·"서류 대기"·"일시정지" |
| `test_no_backfill_for_missed_days` | due가 오늘+2 → 아무것도 안 보냄 |
| `test_failed_send_recorded` | 500 3회 → `failed 1`, `sent` 행 `status='failed'` |
| `test_retry_on_429_then_success` | 429 뒤 성공 → `sent 1`, 시도 2회 |
| `test_failure_is_reported_to_core_as_not_ok` | DM 거부가 하나라도 있으면 `tick`이 `/ops`에 `ok: false` |
| `test_unlinked_alone_is_still_ok` | 미연결만 있으면 `unlinked 1`·`failed 0`이고 `/ops`는 **`ok: true`** — 한 명이 연결을 안 했다고 영구 빨강이 되면 그 신호를 아무도 안 본다 |
| `test_status_reported_to_core` | 정상 틱은 `ok: true` |

`tests/test_weekly.py` — 주간 보고

| 테스트 | 검증 |
|---|---|
| `test_fixed_summary_quiet` | counts 전부 0 → "특이 사항 없음" |
| `test_fixed_summary_sections` | completed 1 · overdue 1 → 절 제목, 태스크 번호, `<@111>` |
| `test_summarize_falls_back_when_provider_fails` | `provider="bogus"` → source `"fixed"` |
| `test_run_weekly_goes_to_the_team_channel` | 게시 채널이 `CHANNEL` 하나, `{"parse": ["users"]}`, 본문에 `⚠️ Discord 미연결: 미연결` 줄 |
| `test_run_weekly_once_per_period` | 첫 실행 `sent`, 두 번째 `skipped`, `force=True`면 다시 `sent` — 게시는 총 2건 |
| `test_run_weekly_marks_failed_but_saves` | 500 3회 → `status=="failed"`, `weekly` 행 `sent_status=="failed"`(본문은 저장된다) |
| `test_last_monday` | 2026-09-09(수) → 2026-08-31 |

`tests/test_commands.py` — DM 평문 명령

| 테스트 | 검증 |
|---|---|
| `test_task_number_accepts_both_forms` | `12`·`TASK-12`·`task-12` → 12, `열두`·빈 문자열 → None |
| `test_done_hits_the_same_call_either_way` | `완료 12`와 `완료 TASK-12`가 같은 경로(`tasks/12/done`)와 같은 답장 |
| `test_extend_splits_date_and_reason` | `연장 12 2026-09-20 QA 지연` → 본문 `due_date`·`reason` 분리 |
| `test_extend_rejects_bad_date` | `연장 12 9월20일 사유` → 형식 안내(예시 날짜 포함), core 호출 0회 |
| `test_today_renders_the_view` | `오늘` → 날짜·태스크 번호·`오늘 완료 1건` |
| `test_link_sends_the_code` | `연결 A3F19C2D` → 본문 `{"code": …, "discord_user_id": …}`, `홍길동 계정과 연결했습니다.` |
| `test_unlink_is_the_opt_out` | `연결해제` → `DM도 멈춥니다` |
| `test_unknown_text_gets_help` | 잡담·`도움`·빈 문자열 → `HELP`, core 호출 0회 |
| `test_missing_number_is_guided` | `완료`·`완료 열두개` → `NEED_NUMBER`, 호출 0회 |
| `test_unlinked_account_is_told_to_link` | 404 + 한국어 detail → 그 문구 그대로, **`writes == []`**, 태스크 상태 그대로 |
| `test_missing_detail_falls_back_to_link_hint` | 404에 본문이 없으면 `` `연결` `` 안내 |
| `test_conflict_is_not_retried` | 409 → `방금 다른 곳에서 바뀌었어요. 다시 보내 주세요.`, 호출 1회(재시도 루프 없음) |
| `test_service_error_detail_is_passed_through` | 400 `{"detail": {"due_date": "현재 목표일보다 뒤의 날짜를 선택하세요."}}` → 그 문구 그대로 |
| `test_rate_limited_reply` | 429 → `요청이 몰렸어요. 1분 뒤 다시 보내 주세요.` |
| `test_forbidden_reply` | 403 → `권한이 없습니다.` |
| `test_server_error_is_generic` | 500 → `지금은 처리하지 못했어요…` |

`tests/test_listener.py` — 발신자별 쿨다운

| 테스트 | 검증 |
|---|---|
| `test_rate_limit_per_sender` | `RATE`회까지 False, 그 다음 True, 다른 발신자는 영향 없음 |
| `test_window_resets_after_60s` | 61초 뒤 False이고 지난 창 기록은 버려진다(`len(seen["111"]) == 1`) |

`tests/test_store.py` — SQLite

| 테스트 | 검증 |
|---|---|
| `test_claim_is_exclusive` | 같은 키 `claim` 두 번 → True, False |
| `test_release_only_sending` | mark sent 후 release → 행 유지 |
| `test_claim_daily` | 같은 날 두 번 → True, False. release 후 다시 True |
| `test_dm_channel_cache_roundtrip` | `dm_channel`은 없으면 `None`, 저장·덮어쓰기·삭제가 그대로 반영된다 |

리스너의 `on_message`와 `client.run`은 테스트하지 않는다. 게이트웨이는 라이브러리 몫이고, 우리 몫인 파싱·문구·한도는 `handle()`과 `too_fast()`가 순수 함수라 그것만 직접 부른다.

---

## Step 8. Dockerfile과 README

`discord_service/Dockerfile`:

```dockerfile
FROM python:3.12-slim
COPY --from=ghcr.io/astral-sh/uv:latest /uv /usr/local/bin/uv
WORKDIR /app
COPY pyproject.toml uv.lock ./
RUN uv sync --frozen --no-dev
COPY discord_service ./discord_service
ENV PATH="/app/.venv/bin:$PATH" TZ=Asia/Seoul PYTHONUNBUFFERED=1
CMD ["python", "-m", "discord_service", "run"]
```

`VOLUME ["/data"]`가 없다. 발송 컨테이너의 볼륨은 `compose.yml`이 이름 있는 볼륨으로 붙이고(`discord_data:/data`), 리스너 컨테이너(`discord-bot`)는 SQLite를 아예 열지 않는다. `VOLUME`을 남겨 두면 리스너가 뜰 때마다 익명 볼륨이 쌓인다.

`discord_service/README.md`에는 환경 변수 표(Step 1의 `Config` 필드 전부 + 기본값), CLI 7개 사용법, `bot` 범위 토큰으로 연동 계정을 만드는 절차(팀 **멤버십**만 필요하고 관리자 승격은 필요 없다), 로컬 실행 예, 알림 규칙을 적는다.

컨테이너 두 개와 `.env.discord` 분리는 GUIDE-04 §Step 2·3에 있다. 요점만: 봇 토큰과 `CORE_TOKEN`은 `.env.discord`에만 두고 core(web) 프로세스에는 넣지 않는다.

---

## 검증과 완료 체크

```bash
uv run pytest -q
uv run ruff check .
```

- [ ] 위 두 명령 통과 (Step 7 기준 58개)
- [x] core 코드를 import한 곳이 없다 (`grep` 결과 없음)
- [x] `listener.py`가 59줄이고 하트비트·RESUME·close code 처리가 우리 코드에 없다
- [ ] 실제 Discord 발송·수신  ← **사용자 인프라 필요**. Developer Portal에서 앱 생성 → Bot 페이지 `[Reset Token]` → `.env.discord`의 `DISCORD_BOT_TOKEN`. 특권 인텐트는 켜지 않는다
- [ ] 봇을 팀 서버에 설치  ← **사용자 인프라 필요**. Guild Install만, scope `bot`, permissions `VIEW_CHANNEL | SEND_MESSAGES = 3072`
- [ ] 팀원 전원이 서버 우클릭 → 개인정보 보호 설정 → '서버 멤버의 DM 허용' 켜기  ← **사용자 인프라 필요**. 꺼져 있으면 `50007`로 영구 거부다(봇은 친구 추가가 안 되므로 '친구만' 설정은 하드 블록)
- [ ] `python -m discord_service test` → 지정 채널에 확인 메시지  ← **사용자 인프라 필요**. 실패하면 권한(3072)과 `DISCORD_CHANNEL_ID`를 본다
- [ ] `docker compose logs -f discord-bot`에 `discord 봇 접속` → 봇에게 DM으로 `도움` → `HELP` 답장  ← **사용자 인프라 필요**
- [ ] 각자 웹 `/settings/profile` → `[Discord 연결]` → DM `연결 <코드>` → `오늘`·`완료`  ← **사용자 인프라 필요**
- [ ] `deadlines --date <오늘>` 1회 발송 후 재실행 시 `skipped`  ← **사용자 인프라 필요**(DM 도달이 전제)
- [ ] `weekly --now`로 고정 형식 주간 보고 1건  ← **사용자 인프라 필요**
- [ ] core `/ops`에 `discord` 행 + detail의 `unlinked`  ← **사용자 인프라 필요**
- [ ] `docker build` 성공
- [ ] 완료 보고서 갱신 ([IMPL-REPORT.md](IMPL-REPORT.md))

배포 전 공지: 마이그레이션이 기존 `discord_user_id`를 전부 비운다(손으로 입력한 값에는 소유 증명이 없다). **전원이 `연결`을 하기 전까지 개인 DM 알림은 0건이다.**

커밋: `feat: Discord 챗봇 — 담당자 개인 DM 알림과 DM 명령 (웹훅 삭제)`

다음: [GUIDE-03-mcp.md](GUIDE-03-mcp.md)
