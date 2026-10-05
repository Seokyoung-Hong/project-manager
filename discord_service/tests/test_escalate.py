"""막힘·검토 대기 에스컬레이션 (§4.5 notify.blocked_escalate_days·review_nudge_days)."""

from datetime import date

from conftest import FakeCore, make_bot, make_core, member, task

from discord_service.escalate import run_escalations

TODAY = date(2026, 9, 9)
OWNER = member(5, "555", "프로젝트 관리자")
ADMIN = member(6, "666", "조직 관리자")


def test_off_by_default_does_nothing(store, fake_bot, bot):
    core = make_core(FakeCore([task(1, "2026-09-01", status="blocked", stopped_at="2026-08-01")]))
    r = run_escalations(core, bot, store, 1, TODAY)
    assert r == {"sent": 0, "failed": 0, "skipped": 0}
    assert fake_bot.messages == []


def test_blocked_past_threshold_notifies_project_owners(store, fake_bot, bot):
    fake = FakeCore(
        [
            task(1, "2026-09-01", status="blocked", stopped_at="2026-08-30"),  # 10일째
            task(2, "2026-09-01", status="blocked", stopped_at="2026-09-08"),  # 1일째, 문턱 아래
        ]
    )
    fake.project_owners_data[1] = [OWNER]
    core = make_core(fake)
    r = run_escalations(core, bot, store, 1, TODAY, blocked_days=5)
    assert r["sent"] == 1 and r["failed"] == 0
    dm = fake_bot.dm("555")
    assert len(dm) == 1
    assert "TASK-1" in dm[0] and "TASK-2" not in dm[0]  # 문턱 아래는 빠진다
    assert "막힘" in dm[0]


def test_no_project_owners_falls_back_to_org_admins(store, fake_bot, bot):
    fake = FakeCore([task(1, "2026-09-01", status="blocked", stopped_at="2026-08-01")])
    fake.org_admins_data[1] = [ADMIN]
    core = make_core(fake)
    r = run_escalations(core, bot, store, 1, TODAY, blocked_days=3)
    assert r["sent"] == 1
    assert fake_bot.dm("666")


def test_no_recipients_sends_nothing_and_retries_later(store, fake_bot, bot):
    core = make_core(FakeCore([task(1, "2026-09-01", status="blocked", stopped_at="2026-08-01")]))
    r = run_escalations(core, bot, store, 1, TODAY, blocked_days=3)
    assert r == {"sent": 0, "failed": 0, "skipped": 0}
    assert fake_bot.messages == []
    # 자리를 남기지 않았으니 관리자가 생기면 다음 실행에서 곧바로 알린다(release 확인)
    fake2 = FakeCore([task(1, "2026-09-01", status="blocked", stopped_at="2026-08-01")])
    fake2.project_owners_data[1] = [OWNER]
    r2 = run_escalations(make_core(fake2), bot, store, 1, TODAY, blocked_days=3)
    assert r2["sent"] == 1


def test_one_dm_per_project_per_day_even_with_multiple_blocked_tasks(store, fake_bot, bot):
    """하루 1건·프로젝트별 묶음 — 태스크 여러 개가 막혀 있어도 관리자에게 DM 한 통."""
    fake = FakeCore(
        [
            task(1, "2026-09-01", status="blocked", stopped_at="2026-08-01"),
            task(2, "2026-09-02", status="blocked", stopped_at="2026-08-05"),
        ]
    )
    fake.project_owners_data[1] = [OWNER]
    core = make_core(fake)
    r = run_escalations(core, bot, store, 1, TODAY, blocked_days=3)
    assert r["sent"] == 1
    dm = fake_bot.dm("555")
    assert len(dm) == 1
    assert "TASK-1" in dm[0] and "TASK-2" in dm[0]

    r2 = run_escalations(core, bot, store, 1, TODAY, blocked_days=3)
    assert r2 == {"sent": 0, "failed": 0, "skipped": 1}  # 오늘 다시 부르면 건너뛴다
    assert len(fake_bot.dm("555")) == 1


def test_review_nudge_uses_its_own_threshold(store, fake_bot, bot):
    fake = FakeCore([task(1, "2026-09-01", status="review", stopped_at="2026-09-01")])  # 8일째
    fake.project_owners_data[1] = [OWNER]
    core = make_core(fake)
    r = run_escalations(core, bot, store, 1, TODAY, blocked_days=0, review_days=5)
    assert r["sent"] == 1
    assert "검토 대기" in fake_bot.dm("555")[0]


def test_review_nudge_counts_from_status_since_then_review_request(store, fake_bot, bot):
    """core는 review에 stopped_at을 찍지 않는다. status_since·review_requested_at으로 잰다."""
    by_status = task(1, "2026-09-01", status="review")
    by_status["status_since"] = "2026-09-02T10:00:00+09:00"  # 7일째
    rerequested = task(2, "2026-09-01", status="review")
    rerequested["status_since"] = "2026-09-01T10:00:00+09:00"
    rerequested["review_requested_at"] = "2026-09-08T10:00:00+09:00"  # 리뷰 다시 요청 → 1일째
    fake = FakeCore([by_status, rerequested])
    fake.project_owners_data[1] = [OWNER]
    r = run_escalations(make_core(fake), bot, store, 1, TODAY, review_days=5)
    assert r["sent"] == 1
    sent = fake_bot.dm("555")[0]
    assert "TASK-1" in sent and "7일째" in sent and "TASK-2" not in sent


def test_review_nudge_goes_to_reviewer_first_then_owners_for_the_rest(store, fake_bot, bot):
    reviewed = task(1, "2026-09-01", status="review", stopped_at="2026-09-01")
    reviewed["reviewer"] = member(7, "777", "검토자")
    plain = task(2, "2026-09-01", status="review", stopped_at="2026-09-01")
    fake = FakeCore([reviewed, plain])
    fake.project_owners_data[1] = [OWNER]
    r = run_escalations(make_core(fake), bot, store, 1, TODAY, review_days=5)
    assert r["sent"] == 2
    to_reviewer, to_owner = fake_bot.dm("777"), fake_bot.dm("555")
    assert "TASK-1" in to_reviewer[0] and "TASK-2" not in to_reviewer[0]
    assert "TASK-2" in to_owner[0] and "TASK-1" not in to_owner[0]


def test_escalation_message_has_title_due_status_link(store, fake_bot, bot):
    fake = FakeCore(
        [task(1, "2026-09-12", status="blocked", stop_reason="서류 대기", stopped_at="2026-09-01")]
    )
    fake.project_owners_data[1] = [OWNER]
    run_escalations(make_core(fake), bot, store, 1, TODAY, blocked_days=3)
    assert fake_bot.dm("555")[0].splitlines() == [
        "⏰ **학식 API** · 막힘 1건이 오래 머물러 있습니다. 확인해 주세요.",
        "• [TASK-1 할 일 1](<http://pm/tasks/1>) · D-3 (9월 12일) · 막힘(서류 대기) · 팀원 · 8일째",
    ]


def test_two_orgs_do_not_share_the_daily_claim(store, fake_bot):
    """조직 둘이 같은 store를 쓰더라도 에스컬레이션 자리는 섞이지 않는다(§8.4)."""
    dm_bot = make_bot(fake_bot, store)
    proj2 = {"id": 1, "name": "학식 API", "org_id": 2, "discord_channel_id": ""}
    fake1 = FakeCore([task(1, "2026-09-01", status="blocked", stopped_at="2026-08-01")])
    fake1.project_owners_data[1] = [OWNER]
    fake2 = FakeCore(
        [task(1, "2026-09-01", status="blocked", stopped_at="2026-08-01", project=proj2)]
    )
    fake2.project_owners_data[1] = [ADMIN]
    r1 = run_escalations(make_core(fake1), dm_bot, store, 1, TODAY, blocked_days=3)
    r2 = run_escalations(make_core(fake2), dm_bot, store, 2, TODAY, blocked_days=3)
    assert r1["sent"] == 1 and r2["sent"] == 1
