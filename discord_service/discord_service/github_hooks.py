"""GitHub 알림 웹훅의 Discord 쪽(IMPL-PLAN-8 §10-2). core는 봇 토큰이 없어 이 일을 봇이 맡는다.

create: 프로젝트 채널에 웹훅을 만들고 id·토큰을 core에 넘긴다. core가 GitHub 등록에 실패하면 지운다.
delete: core가 GitHub 훅을 이미 지웠다. Discord 웹훅만 지우고 보고한다.
웹훅 토큰은 core로만 간다 — 로그·store에 남기지 않는다.
"""

import logging

log = logging.getLogger(__name__)


def run_github_hooks(core, bot) -> int:
    try:
        jobs = list(core.github_hook_jobs())
    except Exception:  # noqa: BLE001
        log.warning("GitHub 웹훅 작업 목록을 못 읽었다, 이번 틱은 건너뛴다")
        return 0
    for job in jobs:
        pid = job["project_id"]
        try:
            if job["action"] == "create":
                _create(core, bot, pid, job["channel_id"])
            else:
                if job.get("webhook_id"):
                    bot.delete_webhook(job["webhook_id"])
                core.github_hook_removed(pid)
        except Exception:  # noqa: BLE001
            log.exception("GitHub 웹훅 작업 실패(project=%s, action=%s)", pid, job["action"])
    return len(jobs)


def _create(core, bot, pid: int, channel_id: str):
    try:
        hook = bot.create_webhook(channel_id)
    except Exception as e:  # noqa: BLE001 — 권한 없음(50013)·없는 채널 등. 이유를 core 화면에 남긴다
        core.github_hook_failed(pid, str(e)[:200])
        return
    try:
        res = core.github_hook_created(pid, str(hook["id"]), hook["token"])
    except Exception:
        # ponytail: 보고가 실패하면 만든 웹훅을 지운다. 다음 틱에 새로 만든다.
        bot.delete_webhook(str(hook["id"]))
        raise
    if res.get("delete_webhook"):
        bot.delete_webhook(str(hook["id"]))
