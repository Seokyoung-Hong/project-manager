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
-- 다중 조직(§8.4): 자리를 조직마다 따로 잡는다. task_id는 전역 유일이라 sent는 그대로 두되,
-- 태스크에 매이지 않는 kind(예 "d1:2", "dmblocked:111")는 호출 쪽에서 org_id를 앞에 붙여 넣는다.
CREATE TABLE IF NOT EXISTS daily(
  org_id INTEGER NOT NULL DEFAULT 0, kind TEXT NOT NULL, date TEXT NOT NULL,
  PRIMARY KEY(org_id, kind, date)
);
-- (봇, Discord 사용자) 쌍의 DM 채널. 매번 열면 40003(DM 여는 속도 초과)이 난다.
-- Discord 사용자는 조직을 몰라도 되므로(같은 사람이 여러 조직일 수 있다) org 없이 그대로 둔다.
CREATE TABLE IF NOT EXISTS dm(discord_user_id TEXT PRIMARY KEY, channel_id TEXT NOT NULL);
CREATE TABLE IF NOT EXISTS weekly(
  org_id INTEGER NOT NULL DEFAULT 0, period_start TEXT NOT NULL, data_json TEXT NOT NULL,
  summary TEXT NOT NULL, source TEXT NOT NULL, sent_status TEXT NOT NULL, sent_at TEXT,
  PRIMARY KEY(org_id, period_start)
);
CREATE TABLE IF NOT EXISTS runs(
  id INTEGER PRIMARY KEY AUTOINCREMENT, name TEXT NOT NULL, ran_at TEXT NOT NULL,
  ok INTEGER NOT NULL, note TEXT
);
-- channels_post.py가 "무엇이 바뀌었는지"를 알아보는 데만 쓴다(사건 자체의 중복 방지는
-- notify.py처럼 sent 표를 쓴다 — 새 표를 늘리지 않는다는 원칙은 그쪽을 가리킨다. 이 표는
-- 중복 방지가 아니라 '지난번 상태가 뭐였나'를 남기는 별개의 필요다).
CREATE TABLE IF NOT EXISTS seen_status(
  org_id INTEGER NOT NULL, task_id INTEGER NOT NULL, status TEXT NOT NULL, seen_at TEXT NOT NULL,
  PRIMARY KEY(org_id, task_id)
);
-- 자동 관리가 채널에 넣은 멤버 덮어쓰기. 여기 있는 것만 봇이 지운다(사람이 넣은 것은 건드리지 않는다).
CREATE TABLE IF NOT EXISTS grants(
  channel_id TEXT NOT NULL, discord_user_id TEXT NOT NULL,
  PRIMARY KEY(channel_id, discord_user_id)
);
"""


def _now() -> str:
    return datetime.now(UTC).isoformat()


_NEW_SCHEMA = {
    "daily": (
        "CREATE TABLE daily(org_id INTEGER NOT NULL DEFAULT 0, kind TEXT NOT NULL, "
        "date TEXT NOT NULL, PRIMARY KEY(org_id, kind, date))",
        "org_id, kind, date",
        "kind, date",
    ),
    "weekly": (
        "CREATE TABLE weekly(org_id INTEGER NOT NULL DEFAULT 0, period_start TEXT NOT NULL, "
        "data_json TEXT NOT NULL, summary TEXT NOT NULL, source TEXT NOT NULL, "
        "sent_status TEXT NOT NULL, sent_at TEXT, PRIMARY KEY(org_id, period_start))",
        "org_id, period_start, data_json, summary, source, sent_status, sent_at",
        "period_start, data_json, summary, source, sent_status, sent_at",
    ),
}


def _migrate(conn: sqlite3.Connection):
    """조직 하나짜리 옛 파일(`daily`·`weekly`에 org_id가 없다)을 깨지 않고 끌어올린다.

    옛 행은 org_id=0으로 옮긴다 — 그 파일은 애초에 조직 하나만 담았으므로 잃는 정보는 없다.
    `daily`는 하루 1회 문턱이라 재생성해도 그날 다시 열리는 것뿐이고, `weekly`는 이미 보낸
    기록이라 다시 안 보낸다(period_start가 같다).
    """
    for table, (create, new_cols, old_cols) in _NEW_SCHEMA.items():
        existing = {r["name"] for r in conn.execute(f"PRAGMA table_info({table})")}
        if not existing or "org_id" in existing:
            continue  # 테이블이 아직 없거나(새 설치) 이미 새 스키마다
        conn.execute(f"ALTER TABLE {table} RENAME TO {table}_old")
        conn.execute(create)
        conn.execute(f"INSERT INTO {table}({new_cols}) SELECT 0, {old_cols} FROM {table}_old")
        conn.execute(f"DROP TABLE {table}_old")


class Store:
    def __init__(self, path: str):
        self.path = path
        with self._conn() as c:
            _migrate(c)
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

    # --- 하루 1회 작업. org_id로 조직끼리 자리가 섞이지 않는다 ---
    def claim_daily(self, org_id: int, kind: str, date: str) -> bool:
        with self._conn() as c:
            cur = c.execute(
                "INSERT OR IGNORE INTO daily(org_id, kind, date) VALUES(?,?,?)",
                (org_id, kind, date),
            )
            return cur.rowcount == 1

    def release_daily(self, org_id: int, kind: str, date: str):
        with self._conn() as c:
            c.execute(
                "DELETE FROM daily WHERE org_id=? AND kind=? AND date=?", (org_id, kind, date)
            )

    # --- 주간 ---
    def weekly_sent(self, org_id: int, period_start: str) -> bool:
        with self._conn() as c:
            row = c.execute(
                "SELECT sent_status FROM weekly WHERE org_id=? AND period_start=?",
                (org_id, period_start),
            ).fetchone()
            return row is not None and row["sent_status"] == "sent"

    def save_weekly(
        self,
        org_id: int,
        period_start: str,
        data_json: str,
        summary: str,
        source: str,
        sent_status: str,
    ):
        with self._conn() as c:
            c.execute(
                "INSERT OR REPLACE INTO weekly"
                "(org_id, period_start, data_json, summary, source, sent_status, sent_at) "
                "VALUES(?,?,?,?,?,?,?)",
                (
                    org_id,
                    period_start,
                    data_json,
                    summary,
                    source,
                    sent_status,
                    _now() if sent_status == "sent" else None,
                ),
            )

    # --- 사건 감지 메모(channels_post) ---
    def seen_status(self, org_id: int, task_id: int) -> str | None:
        with self._conn() as c:
            row = c.execute(
                "SELECT status FROM seen_status WHERE org_id=? AND task_id=?", (org_id, task_id)
            ).fetchone()
            return row["status"] if row else None

    def mark_seen(self, org_id: int, task_id: int, status: str):
        with self._conn() as c:
            c.execute(
                "INSERT OR REPLACE INTO seen_status(org_id, task_id, status, seen_at) VALUES(?,?,?,?)",
                (org_id, task_id, status, _now()),
            )

    # --- 자동 관리가 넣은 멤버 덮어쓰기 ---
    def grants(self, channel_id: str) -> set[str]:
        with self._conn() as c:
            rows = c.execute(
                "SELECT discord_user_id FROM grants WHERE channel_id=?", (str(channel_id),)
            )
            return {r["discord_user_id"] for r in rows}

    def grant_channels(self) -> set[str]:
        with self._conn() as c:
            return {r["channel_id"] for r in c.execute("SELECT DISTINCT channel_id FROM grants")}

    def add_grant(self, channel_id: str, discord_user_id: str):
        with self._conn() as c:
            c.execute(
                "INSERT OR IGNORE INTO grants(channel_id, discord_user_id) VALUES(?,?)",
                (str(channel_id), str(discord_user_id)),
            )

    def drop_grant(self, channel_id: str, discord_user_id: str):
        with self._conn() as c:
            c.execute(
                "DELETE FROM grants WHERE channel_id=? AND discord_user_id=?",
                (str(channel_id), str(discord_user_id)),
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
                    "SELECT org_id, period_start, source, sent_status, sent_at FROM weekly "
                    "ORDER BY period_start DESC LIMIT 5"
                )
            ]
        return {"runs": runs, "sent": sent, "weekly": weekly}
