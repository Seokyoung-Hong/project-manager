"""마감 알림. 태스크당이 아니라 (종류, 담당자)당 개인 DM 1건이다."""

from datetime import date, datetime, timedelta, timezone

from conftest import CHANNEL, FakeBot, FakeCore, make_bot, make_core, member, task

from discord_service.config import Config
from discord_service.notify import run_deadlines
from discord_service.scheduler import tick

TODAY = date(2026, 9, 9)
# tzdata가 없는 환경(Windows)에서도 돌도록 고정 오프셋을 쓴다. 운영은 ZoneInfo("Asia/Seoul").
KST = timezone(timedelta(hours=9))
OTHER = member(3, "222", "다른 팀원")
UNLINKED = member(4, "", "미연결")


def _cfg(tmp_path):
    return Config(
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


def _kinds(store) -> list[str]:
    return sorted(r["kind"] for r in store.recent()["sent"])


def _org_kind(kind: str) -> str:
    """notify.py는 org를 앞에 붙인다(§8.4) — 태스크에 안 매인 키(kind:uid)만 그렇다."""
    return f"1:{kind}"


def test_only_tasks_core_selected_are_sent(store, fake_bot, bot):
    """알림 설정 거르기는 core 몫이다. core가 목록에서 뺀 태스크는 DM에 들어가지 않는다."""
    fake = FakeCore([task(1, "2026-09-10"), task(2, "2026-09-10")])
    fake.filtered_out = {2}
    r = run_deadlines(make_core(fake), bot, store, 1, TODAY)
    assert r["sent"] == 1
    assert "TASK-1" in fake_bot.sent[0] and "TASK-2" not in fake_bot.sent[0]


def test_deadline_dm_shows_title_project_due_status_and_link(store, fake_bot, bot):
    """번호만으로는 무슨 일인지 모른다. 제목·프로젝트·D-n·상태·웹 링크가 다 있어야 한다."""
    other = {"id": 2, "name": "산돌이 봇", "org_id": 1, "discord_channel_id": ""}
    core = make_core(
        FakeCore(
            [
                task(1, "2026-09-07", status="doing"),
                task(2, "2026-09-08", status="blocked", stop_reason="서류 대기", project=other),
            ]
        )
    )
    run_deadlines(core, bot, store, 1, TODAY)
    (msg,) = fake_bot.sent
    assert msg.splitlines()[1] == "담당하신 태스크 2건의 기한이 지났습니다."
    lines = msg.splitlines()
    assert lines[2:6] == [
        "**학식 API**",
        "• [TASK-1 할 일 1](<http://pm/tasks/1>) · 2일 초과 (9월 7일) · 진행 중",
        "**산돌이 봇**",
        "• [TASK-2 할 일 2](<http://pm/tasks/2>) · 1일 초과 (9월 8일) · 막힘(서류 대기)",
    ]
    assert "했어" not in msg and "해요" not in msg


def test_many_tasks_split_under_discord_limit(store, fake_bot, bot):
    """한 사람에게 같은 종류가 많아도 2000자 제한 안에서 여러 메시지로 나뉜다."""
    tasks = [task(i, "2026-09-10") for i in range(1, 61)]
    for t in tasks:
        t["title"] = "아주 긴 제목 " * 8
    run_deadlines(make_core(FakeCore(tasks)), bot, store, 1, TODAY)
    assert len(fake_bot.sent) > 1
    assert all(len(m) <= 2000 for m in fake_bot.sent)
    joined = "".join(fake_bot.sent)
    assert all(f"TASK-{i} " in joined for i in range(1, 61))


def test_dm_goes_to_the_assignee_only(store, fake_bot, bot):
    """DM 1건 = 채널 개설 1회 + 발송 1회. 본문에 멘션도 담당자 칼럼도 없다."""
    core = make_core(FakeCore([task(1, "2026-09-10")]))
    r = run_deadlines(core, bot, store, 1, TODAY)
    assert r["sent"] == 1
    assert fake_bot.opened == ["111"]
    assert fake_bot.dm("111") == fake_bot.sent
    msg = fake_bot.messages[0]
    assert msg["allowed_mentions"] == {"parse": []}
    assert "<@" not in msg["content"]
    assert "TASK-1" in msg["content"]
    assert all(c["auth"] == "Bot botsecret" for c in fake_bot.calls)
    assert all(c["ua"].startswith("DiscordBot (") for c in fake_bot.calls)


def test_same_kind_same_assignee_is_one_dm(store, fake_bot, bot):
    """묶기: 같은 담당자·같은 종류 2건 → DM 1건, 자리는 (종류, 담당자) 하나."""
    core = make_core(FakeCore([task(1, "2026-09-10"), task(2, "2026-09-10")]))
    r = run_deadlines(core, bot, store, 1, TODAY)
    assert r["sent"] == 1
    assert len(fake_bot.messages) == 1
    assert "TASK-1" in fake_bot.sent[0] and "TASK-2" in fake_bot.sent[0]
    assert _kinds(store) == [_org_kind("d1:2")]


def test_each_assignee_gets_their_own_dm(store, fake_bot, bot):
    """담당자별 분리. 같은 날 두 번째 실행은 아무것도 보내지 않는다."""
    core = make_core(
        FakeCore([task(1, "2026-09-01"), task(2, "2026-09-02", assignee=OTHER)]),
    )
    r = run_deadlines(core, bot, store, 1, TODAY)
    assert r["sent"] == 2
    assert fake_bot.dm("111") and fake_bot.dm("222")
    assert _kinds(store) == [_org_kind("overdue:2"), _org_kind("overdue:3")]

    r2 = run_deadlines(core, bot, store, 1, TODAY)
    assert r2["sent"] == 0
    assert r2["skipped"] == 2
    assert len(fake_bot.messages) == 2


def test_sends_each_kind_once(store, fake_bot, bot):
    core = make_core(
        FakeCore(
            [
                task(1, "2026-09-12"),
                task(2, "2026-09-10"),
                task(3, "2026-09-09"),
                task(4, "2026-09-01"),
                task(5, "2026-09-02"),
            ]
        )
    )
    r = run_deadlines(core, bot, store, 1, TODAY)
    assert r["sent"] == 4  # 사람당 하루 최대 4건(D-3·D-1·당일·기한 초과)
    assert len(fake_bot.messages) == 4
    assert fake_bot.opened == ["111"]  # 채널은 캐시된다
    overdue_msg = [m for m in fake_bot.sent if "기한 초과" in m][0]
    assert "TASK-4" in overdue_msg and "TASK-5" in overdue_msg

    r2 = run_deadlines(core, bot, store, 1, TODAY)
    assert r2["sent"] == 0
    assert r2["skipped"] >= 4


def test_unlinked_assignee_is_counted_not_claimed(store, fake_bot, bot):
    """미연결이면 DM도 자리도 없다 — 연결한 뒤 그 다음 알림부터 정상으로 받는다."""
    core = make_core(FakeCore([task(1, "2026-09-10", assignee=UNLINKED)]))
    r = run_deadlines(core, bot, store, 1, TODAY)
    assert fake_bot.calls == []
    assert store.recent()["sent"] == []
    assert r["sent"] == 0 and r["failed"] == 0
    assert r["unlinked"] == 1
    assert r["unlinked_names"] == ["미연결"]


def test_blocked_dm_fails_once_and_notifies_channel(store, fake_bot, bot):
    """50007: 그 행만 failed, HTTP 1회, 팀 채널 통보 1건(태스크 내용 없음)."""
    fake_bot.errors["dm-111"] = [(403, {"code": 50007})]
    core = make_core(
        FakeCore([task(1, "2026-09-10"), task(2, "2026-09-10", assignee=OTHER)]),
    )
    r = run_deadlines(core, bot, store, 1, TODAY)
    assert r["failed"] == 1 and r["sent"] == 1
    assert fake_bot.attempts("dm-111") == 1  # 재시도하지 않는다
    assert fake_bot.dm("222")  # 다른 담당자는 정상
    rows = {row["kind"]: row for row in store.recent()["sent"]}
    assert rows[_org_kind("d1:2")]["status"] == "failed"
    assert "50007" in rows[_org_kind("d1:2")]["last_error"]

    notices = fake_bot.to(CHANNEL)
    assert len(notices) == 1
    assert "<@111>" in notices[0]
    assert "할 일" not in notices[0] and "http" not in notices[0]

    fake_bot.errors["dm-111"] = [(403, {"code": 50007})]
    r2 = run_deadlines(core, bot, store, 1, TODAY)
    assert r2["sent"] == 0 and r2["failed"] == 0
    assert fake_bot.attempts("dm-111") == 1  # 다음 틱에 재발송하지 않는다
    assert fake_bot.to(CHANNEL) == notices  # 통보도 하루 1회


def test_due_changed_before_send_not_sent(store, fake_bot, bot, monkeypatch):
    core = make_core(FakeCore([task(1, "2026-09-12")]))
    monkeypatch.setattr(type(core), "task", lambda self, tid: task(tid, "2026-09-20"), raising=True)
    r = run_deadlines(core, bot, store, 1, TODAY)
    assert r["sent"] == 0
    assert r["skipped"] == 1
    assert store.recent()["sent"] == []  # 자리를 놓아준다


def test_completed_before_send_not_sent(store, fake_bot, bot, monkeypatch):
    core = make_core(FakeCore([task(1, "2026-09-12")]))
    monkeypatch.setattr(
        type(core), "task", lambda self, tid: task(tid, "2026-09-12", status="done"), raising=True
    )
    assert run_deadlines(core, bot, store, 1, TODAY)["sent"] == 0
    assert fake_bot.messages == []


def test_recheck_failure_releases_the_claim(store, fake_bot, bot, monkeypatch):
    """발송 직전 재확인이 실패하면 자리를 놓아주고 skipped와 따로 센다.

    skipped(이미 보냄·더 이상 해당 없음)에 섞으면 손실이 /ops에서 안 보인다.
    """

    def boom(self, tid):
        raise RuntimeError("core down")

    core = make_core(FakeCore([task(1, "2026-09-10")]))
    monkeypatch.setattr(type(core), "task", boom, raising=True)
    r = run_deadlines(core, bot, store, 1, TODAY)
    assert r["sent"] == 0 and r["recheck_failed"] == 1 and r["skipped"] == 0
    assert store.recent()["sent"] == []
    assert fake_bot.messages == []


def test_blocked_task_included(store, fake_bot, bot):
    core = make_core(
        FakeCore(
            [
                task(1, "2026-09-09", status="blocked", stop_reason="서류 대기"),
                task(2, "2026-09-10", status="paused"),
            ]
        )
    )
    r = run_deadlines(core, bot, store, 1, TODAY)
    assert r["sent"] == 2
    joined = "\n".join(fake_bot.sent)
    assert "막힘" in joined
    assert "서류 대기" in joined
    assert "일시정지" in joined


def test_no_backfill_for_missed_days(store, fake_bot, bot):
    core = make_core(FakeCore([task(1, "2026-09-11")]))
    r = run_deadlines(core, bot, store, 1, TODAY)
    assert r["sent"] == 0
    assert fake_bot.messages == []


def test_failed_send_recorded(store, fake_bot, bot):
    fake_bot.errors["*"] = [400]
    core = make_core(FakeCore([task(1, "2026-09-12")]))
    r = run_deadlines(core, bot, store, 1, TODAY)
    assert r["failed"] == 1
    assert store.recent()["sent"][0]["status"] == "failed"


def test_exhausted_5xx_releases_the_claim_for_a_later_tick(store, fake_bot, bot):
    """429·5xx 3회 실패는 failed로 굳히지 않고 놓아줍니다. 다음 실행이 다시 보냅니다."""
    fake_bot.errors["*"] = [500, 500, 500]
    core = make_core(FakeCore([task(1, "2026-09-12")]))
    r = run_deadlines(core, bot, store, 1, TODAY)
    assert r["send_retry"] == 1 and r["failed"] == 0
    assert store.recent()["sent"] == []
    assert run_deadlines(core, bot, store, 1, TODAY)["sent"] == 1


def test_retry_on_429_then_success(store, fake_bot, bot):
    fake_bot.errors["*"] = [429]
    core = make_core(FakeCore([task(1, "2026-09-12")]))
    r = run_deadlines(core, bot, store, 1, TODAY)
    assert r["sent"] == 1
    assert fake_bot.attempts("dm-111") == 2


def test_failure_is_reported_to_core_as_not_ok(tmp_path, store, fake_bot, bot):
    """DM 거부 하나라도 있으면 /ops가 ok로 보이지 않아야 한다."""
    fake_bot.errors["dm-111"] = [(403, {"code": 50007})]
    fake = FakeCore([task(1, "2026-09-12")])
    cfg = _cfg(tmp_path)
    r = tick(cfg, make_core(fake), bot, store, datetime(2026, 9, 9, 10, tzinfo=KST))
    assert r[0]["failed"] == 1
    assert fake.status_reports[-1]["ok"] is False


def test_unlinked_alone_is_still_ok(tmp_path, store, fake_bot, bot):
    """미연결 한 명으로 /ops가 영구 빨강이 되면 그 신호를 아무도 안 본다."""
    fake = FakeCore([task(1, "2026-09-12", assignee=UNLINKED)])
    cfg = _cfg(tmp_path)
    r = tick(cfg, make_core(fake), bot, store, datetime(2026, 9, 9, 10, tzinfo=KST))
    assert r[0]["unlinked"] == 1 and r[0]["failed"] == 0
    assert fake.status_reports[-1]["ok"] is True


def test_status_reported_to_core(tmp_path, store, fake_bot, bot):
    fake = FakeCore([task(1, "2026-09-12")])
    cfg = _cfg(tmp_path)
    tick(cfg, make_core(fake), bot, store, datetime(2026, 9, 9, 10, 0, tzinfo=KST))
    assert fake.status_reports[-1]["ok"] is True


def test_channel_open_failure_releases_the_claim(store, monkeypatch):
    """DM 채널을 못 열면 자리를 놓아준다. 그날 알림을 조용히 잃지 않는다."""
    from discord_service.discord import ChannelOpenFailed

    fake = FakeBot()
    bot = make_bot(fake, store)

    def boom(did):
        raise ChannelOpenFailed("timeout")

    monkeypatch.setattr(bot, "dm_channel", boom)
    core = make_core(FakeCore([task(1, "2026-09-10")]))
    r = run_deadlines(core, bot, store, 1, TODAY)
    assert r["sent"] == 0 and r["open_failed"] == 1 and r["failed"] == 0
    assert store.recent()["sent"] == []  # 자리가 남지 않는다 = 다음 틱에 재시도
    assert fake.messages == []


def test_released_alerts_reopen_the_day_and_are_retried(
    tmp_path, store, fake_bot, bot, monkeypatch
):
    """놓아준 자리는 그날 문턱을 다시 열어야 실제로 재시도된다.

    `claim_daily("deadline", 날짜)`가 하루 1회로 막으므로, release()만 하면 그 사람은
    그날 알림을 못 받는다 — /ops는 초록인 채로.
    """
    calls = {"n": 0}
    real = type(make_core(FakeCore([]))).task

    def flaky(self, tid):
        calls["n"] += 1
        if calls["n"] == 1:
            raise RuntimeError("core down")
        return real(self, tid)

    fake_core = FakeCore([task(1, "2026-09-10")])
    core = make_core(fake_core)
    monkeypatch.setattr(type(core), "task", flaky, raising=True)
    cfg = _cfg(tmp_path)
    now = datetime(2026, 9, 9, 9, 0, tzinfo=KST)

    first = tick(cfg, core, bot, store, now)[0]
    assert first["recheck_failed"] == 1 and first["sent"] == 0
    assert first["reopened"] is True
    assert fake_core.status_reports[-1]["ok"] is False  # /ops가 빨강이다
    assert fake_bot.messages == []

    second = tick(cfg, core, bot, store, now)[0]  # 같은 날 다시 훑는다
    assert second["sent"] == 1
    assert fake_bot.dm("111")


def test_opted_out_member_is_not_sent_and_not_counted_as_skipped(store, fake_bot, bot):
    """notify_dm이 꺼진 사람은 실패도 skipped도 아니라 opted_out이다(§4.5)."""
    core = make_core(FakeCore([task(1, "2026-09-10")]))
    r = run_deadlines(core, bot, store, 1, TODAY, notify={"111": {"notify_dm": False}})
    assert r["sent"] == 0 and r["skipped"] == 0 and r["opted_out"] == 1
    assert fake_bot.messages == []


def test_personal_hour_overrides_org_default(store, fake_bot, bot):
    """user.notify_hour가 있으면 그 사람 묶음은 그 시각에만 나간다(§4.6)."""
    core = make_core(FakeCore([task(1, "2026-09-10")]))
    notify = {"111": {"notify_dm": True, "notify_hour": 14}}
    r9 = run_deadlines(core, bot, store, 1, TODAY, hour=9, org_hour=9, notify=notify)
    assert r9["sent"] == 0 and fake_bot.messages == []  # 아직 이 사람의 시각이 아니다
    r14 = run_deadlines(core, bot, store, 1, TODAY, hour=14, org_hour=9, notify=notify)
    assert r14["sent"] == 1


def test_two_orgs_scheduled_together_do_not_mix_deadline_dms(tmp_path, store, fake_bot, bot):
    """조직 둘이 같은 봇에 붙어도 마감 DM이 섞이지 않는다(§8.4)."""
    from conftest import org

    fake = FakeCore(
        [
            task(1, "2026-09-10"),  # org 1, 담당자 111
            task(
                2,
                "2026-09-10",
                assignee=OTHER,
                project={"id": 2, "name": "다른 조직 일", "org_id": 2, "discord_channel_id": ""},
            ),
        ],
        orgs=[org(1, "산돌이", channel_id="111ch"), org(2, "이웃 조직", channel_id="222ch")],
    )
    cfg = _cfg(tmp_path)
    now = datetime(2026, 9, 9, 10, tzinfo=KST)
    results = tick(cfg, make_core(fake), bot, store, now)

    by_org = {r["org_id"]: r for r in results if r["job"] == "deadline"}
    assert by_org[1]["sent"] == 1 and by_org[2]["sent"] == 1
    assert sorted(fake_bot.dm("111") + fake_bot.dm("222")) == sorted(fake_bot.sent)
    # 자리도 조직마다 따로다
    assert _org_kind("d1:2") in _kinds(store)  # org 1
    assert "2:d1:3" in _kinds(store)  # org 2, 담당자 id=3(OTHER)


def test_reopening_the_day_is_bounded(tmp_path, store, fake_bot, bot, monkeypatch):
    """core가 계속 아프면 매 분 전체 스캔을 반복하지 않는다(하루 3회까지)."""

    def boom(self, tid):
        raise RuntimeError("core down")

    core = make_core(FakeCore([task(1, "2026-09-10")]))
    monkeypatch.setattr(type(core), "task", boom, raising=True)
    cfg = _cfg(tmp_path)
    now = datetime(2026, 9, 9, 9, 0, tzinfo=KST)

    reopened = []
    for _ in range(6):
        r = tick(cfg, core, bot, store, now)
        if r:
            reopened.append(r[0]["reopened"])
    assert reopened == [True, True, True, False]  # 첫 훑기 + 재훑기 3회로 끝
    assert fake_bot.messages == []


def test_cli_deadlines_passes_the_same_notify_map(tmp_path, monkeypatch):
    """CLI `deadlines --org`도 스케줄러처럼 DM 거부자 맵을 넘깁니다."""
    import sys

    from conftest import notify_member

    from discord_service import __main__ as cli

    fake = FakeCore([])
    fake.org_members_data = {1: [notify_member(did="111", notify_dm=False)]}
    got = {}
    monkeypatch.setattr(cli.Config, "from_env", classmethod(lambda c: _cfg(tmp_path)))
    monkeypatch.setattr(cli, "CoreClient", lambda *a: make_core(fake))
    monkeypatch.setattr(cli, "run_deadlines", lambda *a, **k: got.update(k))
    monkeypatch.setattr(sys, "argv", ["x", "deadlines", "--org", "1", "--date", "2026-09-09"])
    cli.main()
    assert got["notify"]["111"]["notify_dm"] is False


def test_first_tick_reads_orgs_right_after_boot(monkeypatch):
    """부팅 직후(monotonic이 캐시 TTL보다 작을 때)에도 첫 틱은 조직 목록을 읽는다."""
    from discord_service import scheduler

    monkeypatch.setattr(scheduler.time, "monotonic", lambda: 1.0)
    core = make_core(FakeCore([task(1, "2026-09-12")]))
    assert scheduler.TickCache().orgs(core) != []
