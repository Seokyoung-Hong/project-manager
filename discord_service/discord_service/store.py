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
-- channels_post의 폴링 차이 감지용. 중복 방지(sent 표)와는 다른 관심사라 따로 둔다.
CREATE TABLE IF NOT EXISTS seen(task_id INTEGER PRIMARY KEY, status TEXT NOT NULL);
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

    # --- 채널 게시 사건 감지 ---
    def seen_status(self, task_id: int) -> str | None:
        with self._conn() as c:
            row = c.execute("SELECT status FROM seen WHERE task_id=?", (task_id,)).fetchone()
            return row["status"] if row else None

    def set_seen(self, task_id: int, status: str):
        with self._conn() as c:
            c.execute(
                "INSERT INTO seen(task_id, status) VALUES(?,?) "
                "ON CONFLICT(task_id) DO UPDATE SET status=excluded.status",
                (task_id, status),
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
