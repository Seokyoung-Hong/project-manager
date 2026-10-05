"""GitHub 알림 웹훅의 Discord 쪽(IMPL-PLAN-8 §10-2). core는 봇 토큰이 없어 이 일을 봇이 맡는다.

create: 프로젝트 채널에 웹훅을 만들고 작업 세대(job)·id·토큰을 core에 보고한다.
delete: core가 GitHub 훅을 이미 지웠다(해제·취소 보상). Discord 웹훅만 지우고 보고한다.

보고가 실패하면(응답 유실 포함) 웹훅을 지우지 않는다. core가 이미 GitHub에 등록했을 수 있기 때문이다.
대신 기억해 두었다가 다음 틱에 같은 job으로 다시 보고한다. core의 보고 처리는 멱등이라 결과가 같고,
지워야 할 웹훅이면 core가 정리 목록에 올려 delete 작업으로 돌려준다.
웹훅 토큰은 core로만 간다 — 로그·store에 남기지 않는다.
"""

import logging

log = logging.getLogger(__name__)

# job → {"project_id", "id", "token"}. core에 아직 보고하지 못한 웹훅.
# ponytail: 메모리에만 둔다(토큰을 디스크에 쓰지 않는다). 봇이 재시작하면 잃고, 그 웹훅은 채널에 남는다.
_UNREPORTED: dict[str, dict] = {}


def run_github_hooks(core, bot, unreported: dict | None = None) -> int:
    unreported = _UNREPORTED if unreported is None else unreported
    try:
        jobs = list(core.github_hook_jobs())
    except Exception:  # noqa: BLE001
        log.warning("GitHub 웹훅 작업 목록을 못 읽었다, 이번 틱은 건너뛴다")
        return 0
    for job in jobs:
        pid = job["project_id"]
        try:
            if job["action"] == "create":
                if job["job"] not in unreported:
                    _create(core, bot, pid, job, unreported)
            else:
                if job.get("webhook_id"):
                    bot.delete_webhook(job["webhook_id"])
                core.github_hook_removed(pid, job.get("webhook_id", ""))
        except Exception:  # noqa: BLE001
            log.exception("GitHub 웹훅 작업 실패(project=%s, action=%s)", pid, job["action"])
    _report(core, bot, unreported)
    return len(jobs)


def _create(core, bot, pid: int, job: dict, unreported: dict):
    try:
        hook = bot.create_webhook(job["channel_id"])
    except Exception as e:  # noqa: BLE001 — 권한 없음(50013)·없는 채널 등. 이유를 core 화면에 남긴다
        core.github_hook_failed(pid, job["job"], str(e)[:200])
        return
    unreported[job["job"]] = {"project_id": pid, "id": str(hook["id"]), "token": hook["token"]}


def _report(core, bot, unreported: dict):
    """기억한 웹훅을 전부 보고한다. 취소돼 목록에서 사라진 작업의 웹훅도 보고해야 core가 정리한다."""
    for key, item in list(unreported.items()):
        try:
            res = core.github_hook_created(item["project_id"], key, item["id"], item["token"])
        except Exception:  # noqa: BLE001
            log.warning(
                "GitHub 웹훅 보고 실패(project=%s), 다음 틱에 다시 보고한다", item["project_id"]
            )
            continue
        unreported.pop(key)
        if res.get("delete_webhook"):  # 연결 행이 사라져 core가 정리할 곳이 없을 때만
            try:
                bot.delete_webhook(item["id"])
            except Exception:  # noqa: BLE001
                log.exception("Discord 웹훅 삭제 실패(project=%s)", item["project_id"])
