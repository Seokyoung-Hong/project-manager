from .messages import by_project, mention


def fixed_summary(data: dict) -> str:
    """LLM 없이 만드는 고정 형식 보고서."""
    c = data["counts"]
    head = (
        f"📊 주간 업데이트 · {data['org']['name']} · "
        f"{data['period_start']} ~ {data['period_end']} (직전 주)"
    )
    quiet = (
        c["completed"] == 0
        and c["reopened"] == 0
        and c["overdue"] == 0
        and c["blocked"] == 0
        and c["due_this_week"] == 0
    )
    if quiet:
        return head + f"\n특이 사항이 없습니다. 미완료는 {c['open']}건입니다."

    today = data.get("today") or data["period_end"]

    def section(title, items):
        if not items:
            return ""
        body = by_project(items, today, who=mention, reason=False)
        return f"__**{title}**__ ({len(items)})\n{body}\n"

    body = [
        head,
        "",
        section("지난주 완료", data["completed"]),
        section("지난주 재개", data["reopened"]),
        section("이번 주 마감", data["due_this_week"]),
        section("기한 초과", data["overdue"]),
        section("막힘", data["blocked"]),
    ]
    proj = [
        f"• {p['project']['name']}: 완료 {p['completed']} · 미완료 {p['open']} · "
        f"초과 {p['overdue']} · 막힘 {p['blocked']}"
        for p in data["by_project"]
    ]
    if proj:
        body.append("**프로젝트별**\n" + "\n".join(proj))
    body.append(f"검토 대기 {c['review']}건 · 기한 미정 {c['no_due']}건")
    # /ops는 staff만 보지만 이 보고는 당사자가 본다. 연결을 안 한 사람이 스스로 알게 한다.
    unlinked = [m["display_name"] for m in data.get("members", []) if not m.get("discord_user_id")]
    if unlinked:
        body.append(
            "⚠️ Discord 미연결: "
            + ", ".join(unlinked)
            + " — 개인 DM 마감 알림을 받을 수 없습니다. 웹 설정에서 Discord를 연결해 주세요."
        )
    return "\n".join(b for b in body if b is not None)


def summarize(data: dict, provider: str) -> tuple[str, str]:
    """(요약문, source). provider가 비어 있거나 실패하면 고정 형식."""
    if not provider:
        return fixed_summary(data), "fixed"
    try:
        text = _llm(data, provider)
        if not text or not text.strip():
            raise RuntimeError("empty")
        return text.strip(), "llm"
    except Exception:  # noqa: BLE001
        return fixed_summary(data), "fixed"


def _llm(data: dict, provider: str) -> str:
    # ponytail: 제공업체 미정(미구현). LLM_PROVIDER를 넣어도 고정 형식으로 돌아간다(README 참고).
    # 정해지면 여기 분기 하나만 추가한다. 다른 파일은 손대지 않는다.
    raise NotImplementedError(f"LLM provider not configured: {provider}")
