"""실시간 알림 키 사전과 행 트리거(설계 DESIGN-v2 2절, 표 → 키는 table-map.md 2·4절).

- 쓰기가 커밋되면 Postgres가 `pg_notify('udally_rt', '<키>|<섹션>')`을 낸다. 내용·사용자 정보는 싣지 않는다.
- 키: `T:<task>` `P:<project>` `O:<org>` `U:<user>`(구독용), `A`(권한 바뀜 → 허브가 전체 재검사),
  `S:<세션 키 sha256 앞 16자>`(세션 삭제 = 로그아웃·만료), `X:U:<user>`(비밀번호·활성 변경 → 세션 재인증).
- 행 트리거가 NEW와 OLD 둘 다로 키를 낸다(project_id가 바뀌면 옛 P·새 P 모두). 같은 트랜잭션의 같은
  페이로드는 Postgres가 하나로 합친다.
- KEYS 항목 = (키 SQL식, 섹션). 식에서 `r`은 NEW 또는 OLD 행이다. NULL이면 내지 않는다.
  식이 SELECT로 시작하면 여러 줄을 낸다(역조회).
- 열은 `to_jsonb(행)->>'열'`로 읽는다(생성 때 `r.x`·`OLD.x`·`NEW.x`를 바꿔 넣는다). 마이그레이션 중이라
  열이 아직 없거나 지워졌어도 NULL이 될 뿐 쓰기가 실패하지 않는다. 다른 표를 읽는 식은 표·열이 없으면
  건너뛴다. 값은 text라 다른 표의 id와 비교할 때는 `r.x::bigint`로 쓴다.
- AUTH = 그 표의 쓰기가 열람 권한을 바꿀 수 있는 조건(TG_OP·OLD·NEW). 참이면 `A`를 낸다.
- data_version과 같이 post_migrate 때 CREATE OR REPLACE로 건다. 사전에 없는 표의 옛 트리거는 지운다.
"""

import re

from django.db import connection

CHANNEL = "udally_rt"
TRIGGER = "udally_rt"
# 문서 하나가 이보다 많은 태스크에 연결돼 있으면 T 대신 P 하나만 낸다.
DOC_FANOUT = 20


def _changed(*cols):
    old = ", ".join(f"OLD.{c}" for c in cols)
    new = ", ".join(f"NEW.{c}" for c in cols)
    return f"TG_OP = 'DELETE' OR (TG_OP = 'UPDATE' AND ROW({old}) IS DISTINCT FROM ROW({new}))"


T_OR_P = [
    ("'T:'||r.task_id", "refs"),
    ("CASE WHEN r.task_id IS NULL THEN 'P:'||r.project_id END", None),
]

KEYS: dict[str, list[tuple[str, str | None]]] = {
    "tasks_task": [
        ("'T:'||r.id", "head"),
        ("'P:'||r.project_id", None),
        ("'T:'||r.group_id", "subtasks"),
        ("'T:'||r.parent_id", "series"),
        ("'U:'||r.assignee_id", None),  # 남이 나에게 맡기면 내 오늘 화면에 바로 뜬다(OLD·NEW 모두)
    ],
    "tasks_taskproject": [
        ("'T:'||r.task_id", "projects"),
        ("'T:'||r.task_id", "github"),
        ("'P:'||r.project_id", None),
    ],
    "tasks_checklistitem": [
        ("'T:'||r.task_id", "checklist"),
        # 보드 카드의 "n/m"은 P(project-changed)로만 다시 그려진다 — 주·연결 프로젝트 모두
        (
            "SELECT 'P:'||t.project_id FROM tasks_task t WHERE t.id = r.task_id::bigint "
            "UNION SELECT 'P:'||tp.project_id FROM tasks_taskproject tp "
            "WHERE tp.task_id = r.task_id::bigint",
            None,
        ),
    ],
    "tasks_todayitem": [("'U:'||r.user_id", None), ("'T:'||r.task_id", None)],
    "tasks_link": T_OR_P,
    "tasks_attachment": T_OR_P,  # doc_id만 있으면 둘 다 NULL → 내지 않는다
    "tasks_changelog": [
        (
            "CASE r.target_type WHEN 'task' THEN 'T:' WHEN 'project' THEN 'P:' WHEN 'org' THEN 'O:' END"
            "||r.target_id",
            "history",
        ),
        (
            "CASE WHEN r.new_value ~ '^TASK-[0-9]+$' THEN 'T:'||substr(r.new_value, 6) END",
            "history",
        ),
        (
            "CASE WHEN r.field = 'reopened_as' AND r.target_type = 'task' THEN 'T:'||r.target_id END",
            "github",
        ),
    ],
    "tasks_taskdecisionrecord": [("'T:'||r.task_id", "decisions")],
    "tasks_workrequest": [
        ("'T:'||r.task_id", "fields"),
        ("CASE WHEN r.task_id IS NULL THEN 'O:'||r.org_id END", None),
    ],
    "projects_project": [("'P:'||r.id", "fields"), ("'O:'||r.org_id", None)],
    "projects_project_teams": [("'P:'||r.project_id", None)],
    "projects_project_owners": [("'P:'||r.project_id", None)],
    "projects_doc_tasks": [("'T:'||r.task_id", "refs")],
    # 문서는 자동 저장으로 자주 바뀐다. 연결 태스크만 알린다(P·O까지 내면 보드가 저장마다 다시 그린다).
    "projects_doc": [
        (
            f"SELECT CASE WHEN count(*) OVER () > {DOC_FANOUT} THEN 'P:'||r.project_id "
            "ELSE 'T:'||d.task_id END FROM projects_doc_tasks d WHERE d.doc_id = r.id::bigint",
            "refs",
        )
    ],
    "github_taskgitlink": [("'T:'||r.task_id", "github")],
    "github_repoissue": [
        ("'T:'||r.task_id", "github"),
        (
            "(SELECT 'P:'||c.project_id FROM github_repoconnection c WHERE c.id = r.connection_id::bigint)",
            "github",
        ),
    ],
    "github_repoconnection": [("'P:'||r.project_id", "github")],
    "github_githubidentity": [("'U:'||r.user_id", "github")],
    "orgs_orgmembership": [("'O:'||r.org_id", None), ("'U:'||r.user_id", None)],
    "orgs_organization": [("'O:'||r.id", "fields")],
    "accounts_user": [
        ("'U:'||r.id", None),
        ("SELECT 'O:'||m.org_id FROM orgs_orgmembership m WHERE m.user_id = r.id::bigint", None),
        # 비밀번호 변경은 다른 기기 세션을 행은 남긴 채 무효로 만든다 → 허브가 그 사람 연결을 재인증한다.
        (
            "CASE WHEN TG_OP = 'UPDATE' AND ROW(OLD.password, OLD.is_active) IS DISTINCT FROM "
            "ROW(NEW.password, NEW.is_active) THEN 'X:U:'||r.id END",
            None,
        ),
    ],
    # 로그아웃(flush)·만료 정리(clearsessions)가 모두 행 삭제다.
    "django_session": [
        (
            "CASE WHEN TG_OP = 'DELETE' THEN "
            "'S:'||left(encode(sha256(convert_to(r.session_key, 'UTF8')), 'hex'), 16) END",
            None,
        )
    ],
}

# table-map.md 4절. 키 없이 A만 내는 표도 있다.
AUTH: dict[str, str] = {
    "orgs_orgmembership": "TRUE",
    "orgs_teammembership": "TRUE",
    "orgs_team": _changed("is_private"),
    "projects_project": _changed("visibility", "org_id"),
    "projects_project_teams": "TRUE",
    "projects_project_owners": "TRUE",
    "tasks_taskproject": "TRUE",
    "tasks_task": "TG_OP = 'UPDATE' AND OLD.project_id IS DISTINCT FROM NEW.project_id",
    "projects_doc": _changed("project_id", "team_id", "status"),
    "projects_doc_tasks": "TRUE",
    "notes_voicerecording": _changed("host_id"),
    "accounts_user": _changed("is_active"),
    "github_githubidentity": _changed("repos"),
    "github_repoconnection": "TRUE",
}

# 화면 갱신과 무관한 표(table-map.md 2절 "무시" + Django 내부).
IGNORE = {
    "django_admin_log", "django_content_type", "auth_permission", "auth_group",
    "auth_group_permissions", "accounts_user_groups", "accounts_user_user_permissions",
    "accounts_apitoken", "accounts_idempotencykey", "accounts_oauthclient", "accounts_oauthcode",
    "accounts_loginlock", "accounts_consent",
    "orgs_invite", "orgs_changerequest",
    "projects_milestone", "projects_apispec", "projects_docrevision", "projects_projectdependency",
    "projects_doc_attendees",
    "tasks_notice",
    "notes_voicetrack", "notes_transcriptionjob",  # 회의 녹음 내부(패널·목록에 안 나온다)
    "github_githubinstallation", "github_gitrelease", "github_gitevent", "github_githubteamlink",
    "api_integrationstatus", "ops_opsauditlog",
}  # fmt: skip
IGNORE_PREFIXES = ("portfolio_", "orgs_discord")


def ignored(table: str) -> bool:
    return table in IGNORE or table.startswith(IGNORE_PREFIXES)


_COL = re.compile(r"\b(r|OLD|NEW)\.(\w+)")
_VAR = {"r": "j", "OLD": "o", "NEW": "n"}


def _jsonb(sql: str) -> str:
    return _COL.sub(lambda m: f"({_VAR[m[1]]}->>'{m[2]}')", sql)


def _emit(expr: str, section: str | None) -> str:
    expr = _jsonb(expr)
    send = f"IF k IS NOT NULL THEN PERFORM pg_notify('{CHANNEL}', k || '|{section or ''}'); END IF;"
    if expr.lstrip().upper().startswith("SELECT"):
        sql = f"FOR k IN {expr} LOOP {send} END LOOP;"
    else:
        sql = f"k := {expr}; {send}"
    if "SELECT" in expr.upper():  # 다른 표를 읽는다 → 마이그레이션 중 표·열이 없으면 건너뛴다
        sql = f"BEGIN {sql} EXCEPTION WHEN undefined_table OR undefined_column THEN NULL; END;"
    return sql


def function_sql(table: str) -> str:
    body = "\n".join(_emit(e, s) for e, s in KEYS.get(table, []))
    auth = AUTH.get(table)
    auth_sql = (
        f"IF {_jsonb(auth)} THEN PERFORM pg_notify('{CHANNEL}', 'A|'); END IF;" if auth else ""
    )
    rows = (
        f"IF TG_OP <> 'DELETE' THEN j := n;\n{body}\nEND IF;\n"
        f"IF TG_OP <> 'INSERT' THEN j := o;\n{body}\nEND IF;"
        if body
        else ""
    )
    return (
        f"CREATE OR REPLACE FUNCTION {TRIGGER}_{table}() RETURNS trigger AS $$\n"
        "DECLARE o jsonb := to_jsonb(OLD); n jsonb := to_jsonb(NEW); j jsonb; k text;\n"
        f"BEGIN\n{rows}\n{auth_sql}\nRETURN NULL;\nEND $$ LANGUAGE plpgsql"
    )


_installed = False


def install(**kwargs) -> None:
    """post_migrate는 앱마다 오므로 프로세스당 한 번. 사전 표에만 걸고, 빠진 표의 옛 트리거는 지운다."""
    global _installed
    if _installed or connection.vendor != "postgresql":
        return
    _installed = True
    tables = set(KEYS) | set(AUTH)
    with connection.cursor() as c:
        c.execute(
            "SELECT c.relname FROM pg_trigger t JOIN pg_class c ON c.oid = t.tgrelid "
            "WHERE t.tgname = %s",
            [TRIGGER],
        )
        for (name,) in c.fetchall():
            if name not in tables:
                c.execute(f'DROP TRIGGER {TRIGGER} ON "{name}"')
        for table in sorted(tables):
            c.execute(function_sql(table))
            c.execute(
                f'CREATE OR REPLACE TRIGGER {TRIGGER} AFTER INSERT OR UPDATE OR DELETE ON "{table}" '
                f"FOR EACH ROW EXECUTE FUNCTION {TRIGGER}_{table}()"
            )
