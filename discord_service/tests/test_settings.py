"""조직·개인 설정(IMPL-PLAN-4 §4.5·§4.6)이 discord_service 쪽에서 지켜지는지."""

from datetime import date, datetime, timedelta, timezone

from conftest import CHANNEL, FakeCore, member, task

from discord_service.channels_post import run_channel_posts
from discord_service.config import Config
from discord_service.escalate import run_escalations
from discord_service.scheduler import tick

TODAY = date(2026, 9, 9)  # 수요일
SATURDAY = date(2026, 9, 12)
KST = timezone(timedelta(hours=9))


def _cfg(tmp_path, send_hour=9):
    return Config(
        core_url="http://core",
        core_token="pm_test",
        org_id=1,
        bot_token="botsecret",
        channel_id=CHANNEL,
        tz=KST,
        send_hour=send_hour,
        weekly_weekday=0,
        weekly_hour=9,
        llm_provider="",
        db_path=str(tmp_path / "s.sqlite"),
        site_name="산돌이 업무",
    )


def _core(fake):
    from conftest import make_core

    return make_core(fake)


def test_org_setting_overrides_env_send_hour(tmp_path, store, fake_bot, bot):
    """조직이 notify.send_hour를 정하지 않으면 cfg.send_hour(env)를 쓴다."""
    fake = FakeCore([task(1, "2026-09-10")])
    cfg = _cfg(tmp_path, send_hour=9)
    # env는 9시. 8시에는 아직 아무도 못 받는다(조직 시각도 없으므로 env 그대로 9시).
    r = tick(cfg, _core(fake), bot, store, datetime(2026, 9, 9, 8, tzinfo=KST))
    assert fake_bot.messages == []
    r = tick(cfg, _core(fake), bot, store, datetime(2026, 9, 9, 9, tzinfo=KST))
    assert r[0]["sent"] == 1


def test_org_setting_send_hour_wins_over_env(tmp_path, store, fake_bot, bot):
    """조직이 notify.send_hour=11을 정하면 env(9시)를 무시하고 11시에 보낸다."""
    fake = FakeCore([task(1, "2026-09-10")])
    fake.org_settings_values["notify.send_hour"] = 11
    cfg = _cfg(tmp_path, send_hour=9)
    r = tick(cfg, _core(fake), bot, store, datetime(2026, 9, 9, 9, tzinfo=KST))
    # 조직 시각이 아직 안 됐다(9 < 11) — job은 돌지만 아무에게도 안 보낸다
    assert r[0]["sent"] == 0
    assert fake_bot.messages == []
    r = tick(cfg, _core(fake), bot, store, datetime(2026, 9, 9, 11, tzinfo=KST))
    assert r[0]["sent"] == 1


def test_opted_out_member_is_not_sent_and_counted_separately(tmp_path, store, fake_bot, bot):
    """notify.dm=False인 사람은 opted_out으로 세고 unlinked·failed에는 넣지 않는다."""
    fake = FakeCore([task(1, "2026-09-10")])
    fake.org_members_data = [
        {**member(), "notify": {"dm": False, "kinds": ["d1"], "hour": None}},
    ]
    cfg = _cfg(tmp_path, send_hour=9)
    r = tick(cfg, _core(fake), bot, store, datetime(2026, 9, 9, 9, tzinfo=KST))
    assert r[0]["opted_out"] == 1
    assert r[0]["sent"] == 0 and r[0]["unlinked"] == 0 and r[0]["failed"] == 0
    assert fake_bot.messages == []


def test_personal_hour_gates_the_dm(tmp_path, store, fake_bot, bot):
    """개인 시각 11시인 사람은 9시엔 못 받고, 11시엔 받고, 12시엔 또 받지 않는다(중복 없음)."""
    fake = FakeCore([task(1, "2026-09-10")])
    fake.org_members_data = [
        {**member(), "notify": {"dm": True, "kinds": ["d3", "d1", "d0", "overdue"], "hour": 11}},
    ]
    cfg = _cfg(tmp_path, send_hour=9)
    core = _core(fake)

    r9 = tick(cfg, core, bot, store, datetime(2026, 9, 9, 9, tzinfo=KST))
    assert r9[0]["sent"] == 0
    assert fake_bot.messages == []

    r11 = tick(cfg, core, bot, store, datetime(2026, 9, 9, 11, tzinfo=KST))
    assert r11[0]["sent"] == 1
    assert len(fake_bot.messages) == 1

    r12 = tick(cfg, core, bot, store, datetime(2026, 9, 9, 12, tzinfo=KST))
    assert r12[0]["sent"] == 0
    assert len(fake_bot.messages) == 1  # 중복 발송 없음


def test_overdue_repeat_never_skips_overdue_kind(tmp_path, store, fake_bot, bot):
    fake = FakeCore([task(1, "2026-09-01")])  # overdue
    fake.org_settings_values["notify.overdue_repeat"] = "never"
    cfg = _cfg(tmp_path, send_hour=9)
    r = tick(cfg, _core(fake), bot, store, datetime(2026, 9, 9, 9, tzinfo=KST))
    assert r[0]["sent"] == 0
    assert fake_bot.messages == []


def test_quiet_weekend_skips_the_whole_deadline_job(tmp_path, store, fake_bot, bot):
    fake = FakeCore([task(1, "2026-09-10")])
    fake.org_settings_values["notify.quiet_weekend"] = True
    cfg = _cfg(tmp_path, send_hour=9)
    r = tick(cfg, _core(fake), bot, store, datetime(2026, 9, 12, 9, tzinfo=KST))  # 토요일
    assert not any(j["job"] == "deadline" for j in r)
    assert fake_bot.messages == []


def test_escalation_sent_once_per_project_owner_per_day(tmp_path, store, fake_bot, bot):
    fake = FakeCore(
        [
            task(
                1,
                None,
                status="blocked",
                stop_reason="서류 대기",
            )
        ]
    )
    fake.tasks[1]["stopped_at"] = "2026-09-01T00:00:00+00:00"
    fake.org_members_data = [{"id": 9, "display_name": "관리자", "discord_user_id": "555"}]
    fake.projects_by_id[1] = {
        "id": 1,
        "name": "학식 API",
        "owners": [{"id": 9, "display_name": "관리자", "discord_user_id": "555"}],
    }
    st = {"notify.blocked_escalate_days": 3, "notify.review_nudge_days": 0}
    core = _core(fake)

    r1 = run_escalations(core, bot, store, 1, TODAY, st)
    assert r1["sent"] == 1
    assert fake_bot.dm("555")

    r2 = run_escalations(core, bot, store, 1, TODAY, st)
    assert r2["sent"] == 0  # 하루 1건, 두 번째 호출은 중복 없음
    assert len(fake_bot.messages) == 1


def test_channel_post_fires_once_per_status_change(store, fake_bot, bot):
    t = task(1, "2026-09-20", status="todo")
    fake = FakeCore([t])
    fake.org_projects_data = [
        {"id": 1, "name": "학식 API", "discord_channel_id": "777", "teams": []}
    ]
    st = {"notify.project_channel_events": ["created", "done", "blocked"]}
    core = _core(fake)

    r1 = run_channel_posts(core, bot, store, 1, st)
    assert r1["posted"] == 1  # created
    r2 = run_channel_posts(core, bot, store, 1, st)
    assert r2["posted"] == 0  # 상태 그대로면 다시 안 올린다
    assert len(fake_bot.to("777")) == 1

    fake.tasks[1]["status"] = "done"
    r3 = run_channel_posts(core, bot, store, 1, st)
    assert r3["posted"] == 1  # 상태가 바뀌면 한 건 더
    assert len(fake_bot.to("777")) == 2
