"""데이터 버전: DB에 쓰기가 커밋될 때마다 바뀌는 값. Postgres 전용(그 밖에서는 None).

태스크 패널 ETag가 패널을 그리지 않고 "그사이 바뀐 게 있나"만 묻는 데 쓴다.
- 모든 표에 문장 단위 트리거를 걸어, 쓰기가 있었던 트랜잭션마다 기록 표에 한 줄(xid)을 넣는다.
  데이터와 같은 트랜잭션이라 함께 보이기 시작한다 — "버전은 그대로인데 데이터만 바뀐" 순간이 없다.
- 공유 행을 갱신하지 않고 새 줄만 넣으므로 잠금 대기가 없다(교착 없음). TRUNCATE도 잡는다.
- 버전은 (최소 id, 최대 id, 줄 수)다. 최대 id만 보면 먼저 번호를 받은 트랜잭션이 늦게 커밋될 때 놓친다.
  줄 수는 커밋마다 늘고, 오래된 줄을 지우면 최소 id가 오르므로 지난 값으로 돌아가지 않는다.
- 같은 트랜잭션의 두 번째 문장부터는 이미 넣은 줄을 보고 그냥 끝난다(트랜잭션당 한 줄, 번호도 한 번만 쓴다).
- 오래된 줄은 하루 한 번 정리 작업(purge_expired → prune)이 업무 트랜잭션 밖에서 지운다.
  업무 트랜잭션 안에서 지우면 지우는 쪽끼리 행 잠금을 기다리다 교착될 수 있다(교차 검토에서 재현).
- 트리거는 migrate가 끝날 때마다(post_migrate) 모든 표에 다시 건다(CREATE OR REPLACE). 새 표도 저절로 걸린다.
- queryset.update()·bulk 연산·다른 컨테이너(정리 작업 등)의 쓰기도 DB 단에서 잡힌다.
"""

from django.db import DatabaseError, connection, transaction

TABLE = "udally_data_version"
TRIGGER = "udally_data_version"
# 패널에 나오지 않는 표. 빠뜨려도 틀리지는 않고 다시 그리는 일만 는다.
SKIP = {TABLE, "django_session", "django_migrations"}


_installed = False


def install(**kwargs) -> None:
    """post_migrate는 모델 있는 앱마다 한 번씩 오므로 프로세스당 한 번만 건다."""
    global _installed
    if _installed or connection.vendor != "postgresql":
        return
    _installed = True
    with connection.cursor() as c:
        c.execute(
            f"CREATE TABLE IF NOT EXISTS {TABLE} (id bigserial PRIMARY KEY, xid bigint NOT NULL UNIQUE)"
        )
        c.execute(
            f"""CREATE OR REPLACE FUNCTION {TRIGGER}() RETURNS trigger AS $$
            BEGIN
              IF EXISTS (SELECT 1 FROM {TABLE} WHERE xid = txid_current()) THEN RETURN NULL; END IF;
              INSERT INTO {TABLE} (xid) VALUES (txid_current());
              RETURN NULL;
            END $$ LANGUAGE plpgsql"""
        )
        c.execute(
            "SELECT c.relname FROM pg_class c JOIN pg_namespace s ON s.oid = c.relnamespace "
            "WHERE s.nspname = current_schema() AND c.relkind = 'r'"
        )
        for (name,) in c.fetchall():
            if name in SKIP:
                continue
            c.execute(
                f'CREATE OR REPLACE TRIGGER {TRIGGER} AFTER INSERT OR UPDATE OR DELETE OR TRUNCATE ON "{name}" '
                f"FOR EACH STATEMENT EXECUTE FUNCTION {TRIGGER}()"
            )


def current() -> str | None:
    if connection.vendor != "postgresql":
        return None
    try:
        with connection.cursor() as c:
            c.execute(f"SELECT min(id), max(id), count(*) FROM {TABLE}")
            row = c.fetchone()
    except DatabaseError:  # migrate 전이라 표가 없다 → 그려서 비교하는 쪽으로
        return None
    return "{}-{}-{}".format(*row)


def prune(keep: int = 5000) -> int | None:
    """기록 표를 최근 keep줄만 남긴다. 업무 트랜잭션 밖에서 혼자 돈다(purge_expired)."""
    if connection.vendor != "postgresql":
        return None
    with transaction.atomic(), connection.cursor() as c:
        c.execute("SET LOCAL lock_timeout = '5s'")
        c.execute(f"DELETE FROM {TABLE} WHERE id < (SELECT max(id) FROM {TABLE}) - %s", [keep])
        return c.rowcount
