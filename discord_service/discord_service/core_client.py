import httpx


class CoreClient:
    def __init__(self, base_url: str, token: str, transport=None):
        self.http = httpx.Client(
            base_url=base_url,
            timeout=20,
            headers={"Authorization": f"Bearer {token}", "X-Source": "api"},
            transport=transport,
        )

    def open_tasks(self, org_id: int, due_to: str | None = None) -> list[dict]:
        """미완료 태스크 전부 (페이지 순회). due_to는 'YYYY-MM-DD'."""
        items, offset = [], 0
        while True:
            params = {
                "status": "todo,doing,paused,blocked,review",
                "limit": 200,
                "offset": offset,
            }
            if due_to:
                params["due_to"] = due_to
            r = self.http.get(f"/api/orgs/{org_id}/tasks", params=params)
            r.raise_for_status()
            data = r.json()
            items.extend(data["items"])
            offset += data["limit"]
            if offset >= data["total"]:
                return items

    def deadlines(self, org_id: int, day: str) -> list[dict]:
        """그날 보낼 마감 DM 대상. 항목은 태스크 요약 + `alert_kind`(d3·d1·d0·overdue).
        알림 설정(종류·반복·주말·유예)은 core가 이미 적용했다."""
        r = self.http.get(
            f"/api/integrations/discord/orgs/{org_id}/deadlines", params={"date": day}
        )
        r.raise_for_status()
        return r.json()

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

    def updated_tasks(self, org_id: int, since: str) -> list[dict]:
        """`since`(ISO datetime) 뒤로 `updated_at`이 바뀐 태스크 전부. 상태·완료 여부를 가리지
        않는다(open_tasks와 달리 done·cancelled로 막 넘어간 것도 봐야 channels_post가 '완료'
        사건을 만들 수 있다)."""
        items, offset = [], 0
        while True:
            params = {"updated_since": since, "limit": 200, "offset": offset}
            r = self.http.get(f"/api/orgs/{org_id}/tasks", params=params)
            r.raise_for_status()
            data = r.json()
            items.extend(data["items"])
            offset += data["limit"]
            if offset >= data["total"]:
                return items

    def project_owners(self, project_id: int) -> list[dict]:
        """그 프로젝트의 프로젝트 관리자(`Project.owners`) 목록. escalate.py가 DM 대상을 정할 때 쓴다."""
        r = self.http.get(f"/api/integrations/discord/projects/{project_id}/owners")
        r.raise_for_status()
        return r.json()

    def org_admins(self, org_id: int) -> list[dict]:
        """조직 관리자 목록. 프로젝트 관리자가 0명일 때 escalate.py의 대체 수신자."""
        r = self.http.get(f"/api/integrations/discord/orgs/{org_id}/admins")
        r.raise_for_status()
        return r.json()

    # --- 다중 조직(§8.4). 행위자 없이 봇 토큰(CORE_TOKEN) 자체로 인가된다 ---

    def orgs(self) -> list[dict]:
        """이 봇에 바인딩된 조직 전부. 길드·채널·실효 알림 설정(settings)을 함께 받는다.

        `[{"org_id": 1, "name": "산돌이", "guild_id": "123", "channel_id": "456",
          "settings": {"notify.send_hour": 9, ...}}]`. 캐시(5분)는 scheduler의 몫이다.
        """
        r = self.http.get("/api/integrations/discord/orgs")
        r.raise_for_status()
        return r.json()

    def org_members(self, org_id: int) -> list[dict]:
        """그 조직 멤버 + 개인 알림 설정. `{"discord_user_id", "notify_dm", "notify_kinds",
        "notify_hour"}`가 항목마다 실린다(연결 안 한 사람은 discord_user_id가 없다).
        """
        r = self.http.get(f"/api/integrations/discord/orgs/{org_id}/members")
        r.raise_for_status()
        return r.json()

    def set_org_channel(self, did: str, guild_id: str, channel_id: str) -> dict:
        """`/알림채널`이 부른다. 실행자가 그 길드에 바인딩된 조직의 관리자가 아니면 core가 거절한다."""
        return self._bot(
            "/orgs/channel",
            {"discord_user_id": did, "guild_id": guild_id, "channel_id": channel_id},
        )

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

    # --- 채널 관리(IMPL-PLAN-5 B). core는 Discord로 나가지 않고 봇이 올린 값만 비교한다 ---

    def channel_targets(self) -> list[dict]:
        """감시·조정 대상 전부(연결 안 된 팀·프로젝트 포함). `allowed_ids`는 권한 밖 비교용,
        `grant_ids`는 자동 관리가 덮어쓰기를 넣을 계정이다."""
        r = self.http.get("/api/integrations/discord/channels")
        r.raise_for_status()
        return r.json()

    def channel_check(
        self,
        did: str,
        kind: str,
        target_id: int,
        channel_id: str,
        viewers: list[dict] | None,
        allow_outsiders: bool = False,
        managed: bool | None = None,
        created: bool = False,
        guild_id: str = "",
    ) -> dict:
        """채널 연결의 유일한 문. `viewers=None`은 보는 사람을 알 수 없다는 뜻(확인 불가).
        `{"linked": bool, "unknown": bool, "outsiders": [{"id","name"}]}`."""
        return self._bot(
            "/channel-check",
            {
                "discord_user_id": did,
                "kind": kind,
                "target_id": target_id,
                "channel_id": channel_id,
                "viewers": viewers,
                "allow_outsiders": allow_outsiders,
                "managed": managed,
                "created": created,
                "guild_id": guild_id,
            },
        )

    def channel_alerts(self, guild_id: str, channels: list[dict]) -> dict:
        return self._bot("/channel-alerts", {"guild_id": guild_id, "channels": channels})

    def guild_report(
        self, guild_id: str, permissions: int | None, watching: bool, intent_denied: bool = False
    ) -> dict:
        return self._bot(
            "/guild-report",
            {
                "guild_id": guild_id,
                "permissions": permissions,
                "watching": watching,
                "intent_denied": intent_denied,
            },
        )

    def member_permissions(self, guild_id: str, members: list[dict]) -> dict:
        """Discord를 연결한 PM 사용자들의 서버 권한 비트(`{"discord_user_id", "permissions"}`).
        core가 웹의 Discord 관리 동작을 판정하는 근거다(15분이 지나면 못 쓴다)."""
        return self._bot("/member-permissions", {"guild_id": guild_id, "members": members})

    # --- 요청(팀·사람에게 보내는 일). 행위자는 연결된 사람 ---

    def create_request(self, did: str, fields: dict) -> dict:
        return self._bot("/requests", {"discord_user_id": did, **fields})["request"]

    def my_requests(self, did: str) -> dict:
        """`{"received": [...], "sent": [...]}`. received = 내가 답할 대기 + 내가 끝낼 수락한 일반 요청."""
        return self._bot("/requests/mine", {"discord_user_id": did})

    def received_requests(self, did: str) -> list[dict]:
        return self.my_requests(did)["received"]

    def request_projects(self, did: str, request_id: int) -> list[dict]:
        return self._bot(f"/requests/{request_id}/projects", {"discord_user_id": did})

    def accept_request(self, did: str, request_id: int, fields: dict) -> dict:
        return self._bot(f"/requests/{request_id}/accept", {"discord_user_id": did, **fields})

    def decline_request(self, did: str, request_id: int, note: str) -> dict:
        return self._bot(f"/requests/{request_id}/decline", {"discord_user_id": did, "note": note})[
            "request"
        ]

    def done_request(self, did: str, request_id: int, note: str) -> dict:
        return self._bot(f"/requests/{request_id}/done", {"discord_user_id": did, "note": note})[
            "request"
        ]

    # --- 알림 발송함. 행위자 없이 봇 토큰으로 ---

    def notices(self) -> list[dict]:
        r = self.http.get("/api/integrations/discord/notices")
        r.raise_for_status()
        return r.json()

    def ack_notices(self, ids: list[int]) -> dict:
        return self._bot("/notices/ack", {"ids": ids})

    def report_status(self, ok: bool, detail: dict):
        try:
            self.http.post("/api/integrations/discord/status", json={"ok": ok, "detail": detail})
        except httpx.HTTPError:
            pass  # 상태 보고 실패는 본 작업을 막지 않는다
