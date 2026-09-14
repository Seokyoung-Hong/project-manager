import time

import httpx

SETTINGS_TTL = 300  # 5분


def setting(values: dict, key: str, env_default=None):
    """조직 설정값, 없으면(None 포함) env_default로."""
    v = values.get(key)
    return v if v is not None else env_default


class CoreClient:
    def __init__(self, base_url: str, token: str, transport=None):
        self.http = httpx.Client(
            base_url=base_url,
            timeout=20,
            headers={"Authorization": f"Bearer {token}", "X-Source": "api"},
            transport=transport,
        )
        # ponytail: 인스턴스 레벨 캐시 하나, TTL 5분. 프로세스가 하나뿐이라 이걸로 충분하다.
        self._settings_cache: dict[int, tuple[float, dict]] = {}

    def org_settings(self, org_id: int) -> dict:
        """조직 설정의 유효값(값이 없는 키는 기본값). 5분 캐시.

        `send_hour`·`weekly_weekday`·`weekly_hour`는 기본값이 null이라 여기서는 None
        그대로 돌려준다 — env로 대체하는 것은 호출자(`setting()`)의 몫이다.
        """
        cached = self._settings_cache.get(org_id)
        now = time.monotonic()
        if cached and now - cached[0] < SETTINGS_TTL:
            return cached[1]
        r = self.http.get(f"/api/orgs/{org_id}/settings")
        r.raise_for_status()
        data = r.json()
        merged = {**data.get("defaults", {}), **data.get("values", {})}
        self._settings_cache[org_id] = (now, merged)
        return merged

    def org_members(self, org_id: int) -> list[dict]:
        r = self.http.get(f"/api/orgs/{org_id}/members")
        r.raise_for_status()
        return r.json()

    def org_teams(self, org_id: int) -> list[dict]:
        r = self.http.get(f"/api/orgs/{org_id}/teams")
        r.raise_for_status()
        return r.json()

    def org_projects(self, org_id: int) -> list[dict]:
        r = self.http.get("/api/projects", params={"org": org_id})
        r.raise_for_status()
        return r.json()

    def project(self, project_id: int) -> dict | None:
        r = self.http.get(f"/api/projects/{project_id}")
        if r.status_code == 404:
            return None
        r.raise_for_status()
        return r.json()

    def tasks_by_status(
        self, org_id: int, status: str, project_id: int | None = None
    ) -> list[dict]:
        """페이지 순회. `status`는 core가 받는 그대로(쉼표 구분 가능)."""
        items, offset = [], 0
        while True:
            params = {"org": org_id, "status": status, "limit": 200, "offset": offset}
            if project_id is not None:
                params["project"] = project_id
            r = self.http.get("/api/tasks", params=params)
            r.raise_for_status()
            data = r.json()
            items.extend(data["items"])
            offset += data["limit"]
            if offset >= data["total"]:
                return items

    def blocked_tasks(self, org_id: int) -> list[dict]:
        return self.tasks_by_status(org_id, "blocked")

    def review_tasks(self, org_id: int) -> list[dict]:
        return self.tasks_by_status(org_id, "review")

    def open_tasks(self, org_id: int, due_to: str | None = None) -> list[dict]:
        """미완료 태스크 전부 (페이지 순회). due_to는 'YYYY-MM-DD'."""
        items, offset = [], 0
        while True:
            params = {
                "org": org_id,
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

    def weekly(self, org_id: int, week_start: str) -> dict:
        r = self.http.get("/api/reports/weekly", params={"org": org_id, "week_start": week_start})
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

    # --- 슬래시 명령 (IMPL-PLAN-3). 자동완성 목록도 행위자 범위로만 온다 ---

    def projects(self, did: str) -> list[dict]:
        return self._bot("/projects", {"discord_user_id": did})

    def teams(self, did: str) -> list[dict]:
        return self._bot("/teams", {"discord_user_id": did})

    def members(self, did: str) -> list[dict]:
        return self._bot("/members", {"discord_user_id": did})

    def mytasks(self, did: str) -> list[dict]:
        return self._bot("/mytasks", {"discord_user_id": did})

    def create_task(self, did: str, fields: dict) -> dict:
        return self._bot("/tasks", {"discord_user_id": did, **fields})

    def update_task(self, did: str, task_id: int, changes: dict) -> dict:
        return self._bot(f"/tasks/{task_id}/update", {"discord_user_id": did, **changes})

    def note(self, did: str, task_id: int, text: str) -> dict:
        return self._bot(f"/tasks/{task_id}/note", {"discord_user_id": did, "text": text})

    def status(self, did: str, task_id: int, status: str, reason: str) -> dict:
        return self._bot(
            f"/tasks/{task_id}/status",
            {"discord_user_id": did, "status": status, "reason": reason},
        )

    def set_team_channel(self, did: str, team_id: int, channel_id: str) -> dict:
        return self._bot(
            f"/teams/{team_id}/channel", {"discord_user_id": did, "channel_id": channel_id}
        )

    def set_project_channel(self, did: str, project_id: int, channel_id: str) -> dict:
        return self._bot(
            f"/projects/{project_id}/channel",
            {"discord_user_id": did, "channel_id": channel_id},
        )

    def report_status(self, ok: bool, detail: dict):
        try:
            self.http.post("/api/integrations/discord/status", json={"ok": ok, "detail": detail})
        except httpx.HTTPError:
            pass  # 상태 보고 실패는 본 작업을 막지 않는다
