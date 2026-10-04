from datetime import date, datetime, timedelta, timezone

from conftest import CHANNEL, FakeCore, make_bot, make_core, member, org, task, weekly_data

from discord_service.config import Config
from discord_service.scheduler import tick
from discord_service.summarize import fixed_summary, summarize
from discord_service.weekly import last_monday, run_weekly

WS = date(2026, 8, 31)
KST = timezone(timedelta(hours=9))


def test_fixed_summary_quiet():
    data = weekly_data()
    assert "특이 사항 없음" in fixed_summary(data)


def test_fixed_summary_sections():
    data = weekly_data(completed=[task(1, "2026-09-02")], overdue=[task(2, "2026-09-01")])
    text = fixed_summary(data)
    assert "지난주 완료" in text
    assert "기한 초과" in text
    assert "TASK-1" in text and "TASK-2" in text
    assert "<@111>" in text


def test_summarize_falls_back_when_provider_fails():
    _, source = summarize(weekly_data(), "bogus")
    assert source == "fixed"


def test_run_weekly_goes_to_the_team_channel(store, fake_bot, bot):
    """주간 보고는 팀 채널에 게시한다(멘션이 목적이라 users만 허용)."""
    data = weekly_data(
        completed=[task(1, "2026-09-02")],
        members=[member(), member(4, "", "미연결")],
    )
    core = make_core(FakeCore([], weekly=data))
    assert run_weekly(core, bot, store, 1, WS, "")["status"] == "sent"
    assert [m["channel"] for m in fake_bot.messages] == [CHANNEL]
    assert fake_bot.messages[0]["allowed_mentions"] == {"parse": ["users"]}
    # /ops는 staff만 보지만 이 보고는 당사자가 본다.
    assert "⚠️ Discord 미연결: 미연결" in fake_bot.messages[0]["content"]


def test_run_weekly_once_per_period(store, fake_bot, bot):
    core = make_core(FakeCore([], weekly=weekly_data(completed=[task(1, "2026-09-02")])))
    assert run_weekly(core, bot, store, 1, WS, "")["status"] == "sent"
    assert run_weekly(core, bot, store, 1, WS, "")["status"] == "skipped"
    assert run_weekly(core, bot, store, 1, WS, "", force=True)["status"] == "sent"
    assert len(fake_bot.messages) == 2


def test_run_weekly_marks_failed_but_saves(store):
    from conftest import FakeBot

    fake = FakeBot(errors={"*": [500, 500, 500]})
    core = make_core(FakeCore([], weekly=weekly_data(completed=[task(1, "2026-09-02")])))
    r = run_weekly(core, make_bot(fake, store), store, 1, WS, "")
    assert r["status"] == "failed"
    assert store.recent()["weekly"][0]["sent_status"] == "failed"


def test_last_monday():
    assert last_monday(date(2026, 9, 9)) == date(2026, 8, 31)


def test_disabled_org_does_not_send_or_mark(store, fake_bot, bot):
    """`notify.weekly_enabled=off`이면 만들지도 보내지도 않는다(§4.5)."""
    core = make_core(FakeCore([], weekly=weekly_data(completed=[task(1, "2026-09-02")])))
    assert run_weekly(core, bot, store, 1, WS, "", enabled=False)["status"] == "disabled"
    assert fake_bot.messages == []
    assert store.recent()["weekly"] == []


def test_two_orgs_scheduled_together_post_to_their_own_channel(tmp_path, store, fake_bot, bot):
    """조직 둘의 주간 보고가 서로 다른 채널에 가고 store에도 섞이지 않는다(§8.4)."""
    fake = FakeCore(
        [],
        orgs=[org(1, "산돌이", channel_id="111ch"), org(2, "이웃 조직", channel_id="222ch")],
    )
    fake.weekly_by_org = {
        1: weekly_data(completed=[task(1, "2026-09-02")]),
        2: weekly_data(completed=[task(2, "2026-09-02")]),
    }
    cfg = Config(
        core_url="http://core",
        core_token="pm_test",
        bot_token="botsecret",
        tz=KST,
        send_hour=9,
        weekly_weekday=0,
        weekly_hour=9,
        llm_provider="",
        db_path=str(tmp_path / "s.sqlite"),
        site_name="산돌이 업무",
    )
    # 8/31은 월요일이라(last_monday 기준) weekly_weekday=0과 맞는 날을 고른다.
    monday = datetime(2026, 8, 31, 10, tzinfo=KST)
    results = tick(cfg, make_core(fake), bot, store, monday)

    weekly_results = {r["org_id"]: r for r in results if r["job"] == "weekly"}
    assert weekly_results[1]["status"] == "sent" and weekly_results[2]["status"] == "sent"
    assert sorted(m["channel"] for m in fake_bot.messages) == ["111ch", "222ch"]
    assert store.weekly_sent(1, last_monday(monday.date()).isoformat())
    assert store.weekly_sent(2, last_monday(monday.date()).isoformat())


def test_unknown_weekly_is_not_reposted_on_the_next_tick(tmp_path, store, bot, monkeypatch):
    """결과를 모르는(unknown) 주간 보고는 매 분 다시 게시하지 않습니다 — 하루 1회 자리 잡기."""
    from discord_service.discord import UnknownResult

    calls = []

    def unknown(text, channel_id=None):
        calls.append(channel_id)
        raise UnknownResult("timeout")

    monkeypatch.setattr(bot, "send_channel", unknown)
    fake = FakeCore([], weekly=weekly_data(), orgs=[org(1, channel_id="111ch")])
    cfg = Config(
        core_url="http://core",
        core_token="pm_test",
        bot_token="botsecret",
        tz=KST,
        send_hour=9,
        weekly_weekday=0,
        weekly_hour=9,
        llm_provider="",
        db_path=str(tmp_path / "s.sqlite"),
        site_name="산돌이 업무",
    )
    monday = datetime(2026, 8, 31, 10, tzinfo=KST)
    tick(cfg, make_core(fake), bot, store, monday)
    tick(cfg, make_core(fake), bot, store, monday + timedelta(minutes=1))
    assert calls == ["111ch"]
