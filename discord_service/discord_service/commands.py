"""DM 평문 명령 해석. core를 부르고 한국어 답장 문자열을 돌려준다.

여기에는 업무 규칙이 없다. 파싱과 문구뿐이고, 판단은 전부 core의 services가 한다.
`*_reply` 함수들은 슬래시 명령(slash.py)도 그대로 쓴다 — 파싱만 다르고 문구·오류 변환은 하나다.
"""

import logging
from datetime import date

import httpx

from .core_client import CoreClient
from .messages import HELP, STATUS, group_tag, linked_line, today_message

log = logging.getLogger(__name__)

NEED_NUMBER = '태스크 번호가 필요해요. 예: `완료 12` (마감 알림의 "TASK-12"에서 숫자만)'
NEED_CODE = "연결 코드가 필요해요. 웹 설정 → 프로필에서 [Discord 연결]을 누르면 나옵니다."
NEED_EXTEND = "예: `연장 12 2026-09-20 QA 지연` (번호, 새 목표일, 사유)"
BAD_DATE = "날짜 형식은 `2026-09-20` 처럼 보내 주세요."
BUSY = "지금은 처리할 수 없습니다. 잠시 뒤 다시 보내 주세요."
TOO_FAST = "요청이 많습니다. 1분 뒤 다시 보내 주세요."

# 발신자별 분당 한도. core의 처리량 제한(60/m)은 봇 계정 하나로 세므로 한 사람이
# 다 쓰면 다른 사람 명령까지 429가 된다. DM과 슬래시가 같은 통을 쓴다.
RATE = 20


def too_fast(seen: dict[str, list[float]], uid: str, now: float) -> bool:
    recent = [t for t in seen.get(uid, []) if now - t < 60]
    recent.append(now)
    seen[uid] = recent
    return len(recent) > RATE


def task_number(token: str) -> int | None:
    """`12`와 `TASK-12`를 모두 받는다(검색 화면과 같은 방식)."""
    t = (token or "").upper().replace("TASK-", "").strip()
    return int(t) if t.isdecimal() else None


def parse_date(text: str) -> date | None:
    try:
        return date.fromisoformat((text or "").strip())
    except ValueError:
        return None


def guarded(fn, *args) -> str:
    """core 호출을 답장 문자열로 바꾼다. HTTP 오류는 한국어 문구로, 나머지는 재시도 안내로."""
    try:
        return fn(*args)
    except httpx.HTTPStatusError as e:
        return _error_reply(e.response)
    except httpx.HTTPError as e:
        log.warning("core 호출 실패: %s", e)
        return BUSY


def handle(core: CoreClient, author_id: str, text: str) -> str:
    parts = (text or "").strip().split()
    if not parts:
        return HELP
    cmd, args = parts[0], parts[1:]
    return guarded(_dispatch, core, author_id, cmd, args)


def _dispatch(core: CoreClient, author_id: str, cmd: str, args: list[str]) -> str:
    if cmd in ("연결", "link"):
        if not args:
            return NEED_CODE
        return link_reply(core, author_id, args[0])
    if cmd in ("연결해제", "unlink"):
        return unlink_reply(core, author_id)
    if cmd in ("오늘", "today"):
        return today_reply(core, author_id)
    if cmd in ("완료", "done"):
        num = task_number(args[0]) if args else None
        if num is None:
            return NEED_NUMBER
        return done_reply(core, author_id, num)
    if cmd in ("연장", "extend"):
        num = task_number(args[0]) if args else None
        if num is None or len(args) < 2:
            return NEED_EXTEND
        due = parse_date(args[1])
        if due is None:
            return BAD_DATE
        return extend_reply(core, author_id, num, due, " ".join(args[2:]))
    return HELP


# --- 답장 문구. DM과 슬래시가 공유한다 ---


def _head(t: dict) -> str:
    return f"**{t['number']}** {t['title']}{group_tag(t)}"


def link_reply(core: CoreClient, did: str, code: str) -> str:
    name = core.link(code, did).get("display_name", "")
    return f"{name} 계정과 연결했습니다. `오늘` 을 보내 보세요."


def unlink_reply(core: CoreClient, did: str) -> str:
    core.unlink(did)
    return "연결을 끊었습니다. 마감 알림 DM도 멈춥니다."


def today_reply(core: CoreClient, did: str) -> str:
    view = core.today(did)
    # DM은 그 사람의 모든 조직을 본다(§8.4). 조직이 둘 이상 섞여 있을 때만 줄마다 조직 이름을
    # 붙인다 — 조직이 하나면(대부분) 지금까지와 문구가 완전히 같다.
    org_ids = {t["project"]["org_id"] for t in view["items"] if t.get("project")}
    org_names = None
    if len(org_ids) > 1:
        org_names = {o["org_id"]: o["name"] for o in core.orgs()}
    return today_message(view, org_names)


def done_reply(core: CoreClient, did: str, num: int) -> str:
    r = core.done(did, num)
    return f"{_head(r['task'])} — {r['was']} → 완료로 바꿨습니다."


def extend_reply(core: CoreClient, did: str, num: int, due: date, reason: str) -> str:
    t = core.extend(did, num, due.isoformat(), reason)["task"]
    return f"{_head(t)} — 목표일을 {t['due_date']}로 미뤘습니다."


def _pending(t: dict) -> str:
    """팀원이 남에게 맡긴 태스크는 받는 사람이 수락해야 바뀐다."""
    p = t.get("pending_assignee")
    return f"\n{p['display_name']}님 수락 대기" if p else ""


SPLIT_HINT = "담당자는 한 명입니다. 사람별로 나누려면 웹에서 [사람별로 나누기]를 누르세요."


def create_reply(core: CoreClient, did: str, fields: dict) -> str:
    r = core.create_task(did, fields)
    t = r["task"]
    due = t["due_date"] or "기한 미정"
    hint = f"\n{SPLIT_HINT}" if r.get("multi_assignee") else ""
    return f"{_head(t)} 을(를) 만들었습니다 — {t['project']['name']} · {due}{linked_line(t)}\n{t['url']}{_pending(t)}{hint}"


def update_reply(core: CoreClient, did: str, num: int, changes: dict) -> str:
    if not changes:
        return "바꿀 항목을 하나 이상 넣어 주세요."
    t = core.update_task(did, num, changes)["task"]
    return f"{_head(t)} — 수정했습니다.\n{t['url']}{_pending(t)}"


def set_org_channel_reply(core: CoreClient, did: str, guild_id: str, channel_id: str) -> str:
    """`/알림채널`이 부른다. core가 PM 조직 관리자 여부를 판정한다(길드 권한은 호출 전에 확인됨)."""
    core.set_org_channel(did, guild_id, channel_id)
    return f"이 채널(<#{channel_id}>)을 이 서버 조직의 알림 채널로 저장했습니다."


def note_reply(core: CoreClient, did: str, num: int, text: str) -> str:
    t = core.note(did, num, text)["task"]
    return f"{_head(t)} — 진행 메모에 덧붙였습니다."


def status_reply(core: CoreClient, did: str, num: int, status: str, reason: str) -> str:
    r = core.status(did, num, status, reason)
    label = STATUS.get(status, status)
    return f"{_head(r['task'])} — {r['was']} → {label}(으)로 바꿨습니다."


# --- 요청. 번호는 REQ-N이고 core 경로는 id다 ---


def _rhead(r: dict) -> str:
    return f"**{r['number']}** {r['title']}"


def request_reply(core: CoreClient, did: str, fields: dict) -> tuple[str, str | None]:
    """(요청자에게 보이는 답, 팀 채널에 공개할 안내). 사람에게 보낸 요청은 공개하지 않는다."""
    r = core.create_request(did, fields)
    to = r["to_user"]["display_name"] if r["to_user"] else r["team"]["name"]
    private = f"{_rhead(r)} 요청을 {to}에게 보냈습니다.\n{r['url']}"
    if not r.get("announce_here"):
        return private, None  # 사람에게 보냈거나, 받는 팀의 채널이 아닌 곳에서 쳤다
    public = (
        f"📨 {_rhead(r)} — {r['kind_label']} 요청 · 요청자 {r['requested_by']['display_name']}"
        f" → {r['team']['name']} 팀\n받을 수 있는 분은 `/요청수락` 에서 {r['number']} 을(를) 골라 주세요."
    )
    return private, public


def accept_request_reply(core: CoreClient, did: str, rid: int, fields: dict) -> str:
    out = core.accept_request(did, rid, fields)
    r, t = out["request"], out.get("task")
    tail = f"\n{_head(t)}\n{t['url']}{_pending(t)}" if t else ""
    return f"{_rhead(r)} 요청을 수락했습니다.{tail}"


def decline_request_reply(core: CoreClient, did: str, rid: int, note: str) -> str:
    return f"{_rhead(core.decline_request(did, rid, note))} 요청을 거절했습니다."


def done_request_reply(core: CoreClient, did: str, rid: int, note: str) -> str:
    return f"{_rhead(core.done_request(did, rid, note))} 요청을 완료로 처리했습니다."


def request_list_reply(core: CoreClient, did: str) -> str:
    mine = core.my_requests(did)
    if not (mine["received"] or mine["sent"]):
        return "대기 중인 요청이 없습니다."
    parts = []
    for title, rows in (("받은 요청", mine["received"]), ("보낸 요청", mine["sent"])):
        if rows:
            lines = [f"• {_rhead(r)} — {r['status_label']}\n  {r['url']}" for r in rows[:15]]
            parts.append(f"{title} {len(rows)}건\n" + "\n".join(lines))
    return "\n\n".join(parts)


def _error_reply(r: httpx.Response) -> str:
    detail = _detail(r)
    if r.status_code == 404:
        return detail or "찾을 수 없습니다. `연결`이 필요할 수 있습니다."
    if r.status_code == 403:
        return "권한이 없습니다."
    if r.status_code == 409:
        return "방금 다른 곳에서 변경되었습니다. 다시 보내 주세요."
    if r.status_code == 429:
        return TOO_FAST
    if r.status_code == 400:
        return detail or "입력을 다시 확인해 주세요."
    log.warning("core %s: %s", r.status_code, detail)
    return BUSY


def _detail(r: httpx.Response) -> str:
    """`{"detail": "문구"}`(HttpError)와 `{"detail": {필드: 문구}}`(ServiceError) 둘 다."""
    try:
        d = r.json().get("detail")
    except Exception:  # noqa: BLE001
        return ""
    if isinstance(d, str):
        return d
    if isinstance(d, dict):
        return " ".join(str(v) for v in d.values())
    return ""
