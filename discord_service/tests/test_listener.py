"""발신자별 쿨다운. core의 처리량 제한은 봇 계정 하나로 세므로 한 사람이 다 쓰면 안 된다."""

from discord_service.listener import RATE, too_fast


def test_rate_limit_per_sender():
    seen = {}
    assert all(too_fast(seen, "111", 100.0) is False for _ in range(RATE))
    assert too_fast(seen, "111", 100.0) is True  # 21번째
    assert too_fast(seen, "222", 100.0) is False  # 다른 사람은 영향 없다


def test_window_resets_after_60s():
    seen = {}
    for _ in range(RATE + 1):
        too_fast(seen, "111", 100.0)
    assert too_fast(seen, "111", 161.0) is False
    assert len(seen["111"]) == 1  # 지난 창은 버린다


def test_one_guild_sync_failure_does_not_crash_setup_hook(monkeypatch, tmp_path):
    """길드 하나의 tree.sync 거절은 로그만 남기고 다음 길드·제어 서버 기동으로 넘어갑니다."""
    import asyncio
    from types import SimpleNamespace

    import discord
    from discord import app_commands

    from discord_service import listener

    synced, holder = [], {}

    async def sync(self, *, guild=None):
        if guild.id == 1:
            raise discord.Forbidden(SimpleNamespace(status=403, reason="Forbidden"), "x")
        synced.append(guild.id)

    async def control(*_, **kwargs):
        return "runner"

    monkeypatch.setattr(app_commands.CommandTree, "sync", sync)
    monkeypatch.setattr(discord.Client, "run", lambda self, *a, **k: holder.setdefault("c", self))
    monkeypatch.setattr(listener, "start_control_server", control)
    core = SimpleNamespace(orgs=lambda: [{"guild_id": "1"}, {"guild_id": "2"}])
    listener.run(
        SimpleNamespace(
            bot_token="t",
            core_url="http://core",
            site_name="x",
            members_intent=False,
            db_path=str(tmp_path / "bot.sqlite"),
            core_token="bot",
        ),
        core,
    )
    asyncio.run(holder["c"].setup_hook())
    assert synced == [2] and holder["c"].control_runner == "runner"
