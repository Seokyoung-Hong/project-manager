"""칸 등록표(IMPL-PLAN-12 §7.2·§8.1). 칸 키·종류(shape)·대상 종류는 A0가 확정했다 — 템플릿은 이 키만 쓴다.

등록표 밖 키는 작업을 만들지 않는다(서버 400). 맥락 함수·프롬프트는 A 갈래가 채운다.
- shape: line(후보 3개 중 고르기) · text(Markdown 미리보기) · list(체크 항목 여러 개)
- targets: data-ai-target="<종류>:<id>"로 받을 수 있는 대상 종류. 첫 번째가 기본.
- phase: 1 = 이번 라운드 템플릿에 붙임, 2 = 키만 예약(후속 갈래가 속성만 붙인다)
"""

from dataclasses import dataclass


@dataclass(frozen=True)
class Field:
    shape: str  # line | text | list
    targets: tuple[str, ...]
    max_out: int  # 출력 상한(글자). 모델 칸 길이를 따른다(tasks/models.py)
    phase: int = 1
    context: object = (
        None  # ctx(user, target) -> list[(label, text)]. 요청자 가시성으로 거른다(§10.1)
    )
    prompt: str = ""


def _f(shape, targets, max_out, phase=1):
    return Field(shape=shape, targets=targets, max_out=max_out, phase=phase)


FIELDS: dict[str, Field] = {
    # ---- 1차: 태스크 ----
    "task.title": _f("line", ("task",), 200),
    "task.next_action": _f("line", ("task",), 200),
    "task.notes": _f("text", ("task",), 2000),
    "task.done_when": _f("text", ("task",), 300),
    "task.description": _f("text", ("task",), 2000),
    "task.checklist": _f("list", ("task",), 200),  # 항목 하나 상한
    "subtask.title": _f("line", ("task",), 200),  # 대상 = 상위 태스크
    "subtask.done_when": _f("line", ("task",), 300),
    "task.no_due_reason": _f("line", ("task", "project"), 200),
    "task.stop_reason": _f("text", ("task",), 300),
    "task.extend_reason": _f("line", ("task",), 200),
    "newtask.title": _f("line", ("project", "org"), 200),  # 빠른 추가에 프로젝트가 없으면 org
    "newtask.done_when": _f("line", ("project", "org"), 300),
    # ---- 1차: 문서·회의록 ----
    "doc.title": _f("line", ("doc",), 200),
    "newdoc.title": _f("line", ("project", "org"), 200),
    # ---- 1차: 프로젝트 ----
    "project.name": _f("line", ("project", "org"), 100),  # 새 프로젝트면 org
    "project.purpose": _f("text", ("project", "org"), 200),
    "milestone.name": _f("line", ("project",), 100),
    "governance.project": _f("text", ("project",), 2000),
    # ---- 1차: 요청 ----
    "request.title": _f("line", ("task", "project"), 200),
    "request.body": _f("text", ("task", "project"), 2000),
    "request.note": _f("line", ("request",), 300),
    # ---- 2차(키만 예약) ----
    "link.title": _f("line", ("task", "project"), 200, phase=2),
    "attachment.note": _f("line", ("task",), 200, phase=2),
    "dependency.note": _f("line", ("project",), 200, phase=2),
    "team.name": _f("line", ("org",), 100, phase=2),
    "team.purpose": _f("line", ("org",), 200, phase=2),
    "change.reason": _f("line", ("org",), 500, phase=2),
    "governance.org": _f("text", ("org",), 2000, phase=2),
    "portfolio.title": _f("line", ("user",), 200, phase=2),
    "portfolio.body": _f("text", ("user",), 4000, phase=2),
}

# 칸이 아닌 모드(§7.3·§7.4). 값 = (AiJob.kind, 대상 종류). AiJob.field에 그대로 들어간다.
MODES: dict[str, tuple[str, str]] = {
    "doc.fill": ("doc", "doc"),
    "doc.continue": ("doc", "doc"),
    "doc.template": ("doc", "doc"),  # options={"template_id": n}
    "meeting.minutes": ("meeting", "doc"),
    "extract.meeting": ("extract", "doc"),
    "extract.issue": ("extract", "issue"),
}


def kind_of(key: str) -> str | None:
    """칸 키·모드 → AiJob.kind. 등록표 밖이면 None(뷰가 400)."""
    if key in FIELDS:
        return "field"
    mode = MODES.get(key)
    return mode[0] if mode else None
