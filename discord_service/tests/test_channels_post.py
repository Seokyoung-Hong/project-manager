"""프로젝트 채널 사건 게시 (§4.5 notify.project_channel_events)."""

from conftest import FakeCore, make_core, task

from discord_service.channels_post import run_channel_events

DAY = "2026-09-09"
SINCE = "2026-09-09T00:00:00+09:00"
CH_PROJECT = {"id": 1, "name": "학식 API", "org_id": 1, "discord_channel_id": "chan-1"}
NO_CH_PROJECT = {"id": 2, "name": "미연결 프로젝트", "org_id": 1, "discord_channel_id": ""}


def test_no_events_configured_does_nothing(store, fake_bot, bot):
    core = make_core(FakeCore([task(1, "2026-09-10", project=CH_PROJECT)]))
    r = run_channel_events(core, bot, store, 1, DAY, SINCE, events=set())
    assert r == {"posted": 0, "skipped": 0, "failed": 0}
    assert fake_bot.messages == []


def test_new_task_posts_created_to_its_project_channel(store, fake_bot, bot):
    core = make_core(FakeCore([task(1, "2026-09-10", project=CH_PROJECT)]))
    r = run_channel_events(core, bot, store, 1, DAY, SINCE, events={"created"})
    assert r["posted"] == 1
    assert fake_bot.to("chan-1") == fake_bot.sent
    assert "새 태스크" in fake_bot.sent[0] and "TASK-1" in fake_bot.sent[0]
    assert "팀원" in fake_bot.sent[0]  # 담당자 표시 이름까지만
    assert "http" not in fake_bot.sent[0]  # 링크는 올리지 않는다


def test_unconnected_project_is_skipped_silently(store, fake_bot, bot):
    core = make_core(FakeCore([task(1, "2026-09-10", project=NO_CH_PROJECT)]))
    r = run_channel_events(core, bot, store, 1, DAY, SINCE, events={"created"})
    assert r == {"posted": 0, "skipped": 0, "failed": 0}
    assert fake_bot.messages == []


def test_status_transition_to_done_is_detected(store, fake_bot, bot):
    fake = FakeCore([task(1, "2026-09-10", project=CH_PROJECT)])
    core = make_core(fake)
    # 1차: 처음 본다 → "created"만 켜져 있으니 그 사건이 나가고 상태(todo)를 기억해 둔다
    run_channel_events(core, bot, store, 1, DAY, SINCE, events={"created"})
    assert store.seen_status(1, 1) == "todo"
    fake.tasks[1]["status"] = "done"
    r = run_channel_events(core, bot, store, 1, DAY, SINCE, events={"done"})
    assert r["posted"] == 1
    assert "완료" in fake_bot.sent[-1]


def test_status_transition_to_blocked_is_detected(store, fake_bot, bot):
    """맨 처음 보는 태스크는 상태가 뭐든 'created'다 — 진짜 전이만 'blocked'로 잡는다."""
    fake = FakeCore([task(1, "2026-09-10", status="doing", project=CH_PROJECT)])
    core = make_core(fake)
    run_channel_events(core, bot, store, 1, DAY, SINCE, events={"created"})
    fake.tasks[1]["status"] = "blocked"
    r = run_channel_events(core, bot, store, 1, DAY, SINCE, events={"blocked"})
    assert r["posted"] == 1
    assert "막힘" in fake_bot.sent[-1]


def test_first_sighting_is_always_created_not_the_current_status(store, fake_bot, bot):
    core = make_core(FakeCore([task(1, "2026-09-10", status="blocked", project=CH_PROJECT)]))
    r = run_channel_events(core, bot, store, 1, DAY, SINCE, events={"blocked"})
    assert r["posted"] == 0  # 'created'가 events에 없으니 아무것도 안 올라간다
    assert fake_bot.messages == []


def test_event_not_in_the_configured_set_is_ignored(store, fake_bot, bot):
    core = make_core(FakeCore([task(1, "2026-09-10", status="blocked", project=CH_PROJECT)]))
    r = run_channel_events(core, bot, store, 1, DAY, SINCE, events={"created"})
    assert r["posted"] == 1  # 'created'는 켜져 있다(처음 본 태스크라서)
    assert "새 태스크" in fake_bot.sent[0]


def test_overdue_daily_lists_open_overdue_tasks(store, fake_bot, bot):
    core = make_core(
        FakeCore(
            [
                task(1, "2026-09-01", project=CH_PROJECT),  # 지났다
                task(2, "2026-09-20", project=CH_PROJECT),  # 안 지났다
            ]
        )
    )
    r = run_channel_events(core, bot, store, 1, DAY, SINCE, events={"overdue_daily"})
    assert r["posted"] == 1
    assert "TASK-1" in fake_bot.sent[0] and "TASK-2" not in fake_bot.sent[0]


def test_same_event_is_not_posted_twice_in_one_day(store, fake_bot, bot):
    """하루 1건: 이미 오늘 올라간 자리는(사건 재판정과 별개로) 다시 올리지 않는다."""
    store.claim(0, "1:chan:created:1", DAY)  # 이미 올라간 것처럼 자리를 미리 잡아 둔다
    core = make_core(FakeCore([task(1, "2026-09-10", project=CH_PROJECT)]))
    r = run_channel_events(core, bot, store, 1, DAY, SINCE, events={"created"})
    assert r == {"posted": 0, "skipped": 1, "failed": 0}
    assert fake_bot.messages == []


def test_two_orgs_do_not_mix_seen_status_or_channels(store, fake_bot, bot):
    """조직 둘이 같은 task_id를 쓰더라도(다른 조직이니 우연) 사건이 섞이지 않는다(§8.4)."""
    proj_a = {"id": 1, "name": "A", "org_id": 1, "discord_channel_id": "chan-a"}
    proj_b = {"id": 1, "name": "B", "org_id": 2, "discord_channel_id": "chan-b"}
    core_a = make_core(FakeCore([task(1, "2026-09-10", project=proj_a)]))
    core_b = make_core(FakeCore([task(1, "2026-09-10", project=proj_b)]))
    run_channel_events(core_a, bot, store, 1, DAY, SINCE, events={"created"})
    run_channel_events(core_b, bot, store, 2, DAY, SINCE, events={"created"})
    assert sorted(m["channel"] for m in fake_bot.messages) == ["chan-a", "chan-b"]
    assert store.seen_status(1, 1) == "todo" and store.seen_status(2, 1) == "todo"


def test_first_sighting_of_an_old_task_is_a_change_not_created(store, fake_bot, bot):
    """created_at이 조회 창 밖이면 처음 봐도 '새 태스크'가 아니라 상태 변경으로 다룹니다."""
    t = task(1, "2026-09-10", status="blocked", project=CH_PROJECT)
    t["created_at"] = "2026-09-01T09:00:00+09:00"
    core = make_core(FakeCore([t]))
    r = run_channel_events(core, bot, store, 1, DAY, SINCE, events={"created", "blocked"})
    assert r["posted"] == 1
    assert "막힘" in fake_bot.sent[-1] and "새 태스크" not in fake_bot.sent[-1]
