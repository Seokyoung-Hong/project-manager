import os
from dataclasses import dataclass
from zoneinfo import ZoneInfo


@dataclass(frozen=True)
class Config:
    core_url: str
    core_token: str
    bot_token: str
    tz: ZoneInfo
    llm_provider: str
    db_path: str
    site_name: str
    # 조직 설정(notify.send_hour 등)이 없을 때의 기본값(폴백)이다. 조직마다 다르게 정할 수
    # 있으므로 실제 값은 scheduler가 매 틱 core.orgs()의 settings에서 우선 읽는다.
    send_hour: int = 9
    weekly_weekday: int = 0
    weekly_hour: int = 9
    # Server Members 특권 인텐트(IMPL-PLAN-5 B). 포털에서 먼저 켠 뒤에 1로 둔다 — 포털이 꺼진 채
    # 요청하면 게이트웨이가 접속을 거부해 알림·명령이 모두 멈춘다. 꺼져 있으면 채널 감시·조정을 건너뛴다.
    members_intent: bool = False

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
            bot_token=need("DISCORD_BOT_TOKEN"),
            tz=ZoneInfo(os.environ.get("TZ", "Asia/Seoul")),
            send_hour=int(os.environ.get("SEND_HOUR", "9")),
            weekly_weekday=int(os.environ.get("WEEKLY_WEEKDAY", "0")),
            weekly_hour=int(os.environ.get("WEEKLY_HOUR", "9")),
            llm_provider=os.environ.get("LLM_PROVIDER", "").strip().lower(),
            db_path=os.environ.get("DB_PATH", "/data/discord.sqlite"),
            site_name=os.environ.get("SITE_NAME", "유달리"),
            members_intent=os.environ.get("DISCORD_MEMBERS_INTENT", "").strip().lower()
            in ("1", "true", "yes", "on"),
        )
