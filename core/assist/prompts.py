"""프롬프트·메시지 조립(IMPL-PLAN-12 §8). 몸체는 A 갈래."""

MAX_INPUT_CHARS = 12000  # 맥락 합계 상한(§8.4). 넘는 전사문은 조각별 요약

# 문서·회의록 모드별 system 프롬프트(§7.3). 키는 assist.fields.MODES의 doc·meeting 모드.
DOC_PROMPTS: dict[str, str] = {
    "doc.fill": "",
    "doc.continue": "",
    "doc.template": "",
    "meeting.minutes": "",
}


def build_messages(job, user) -> list[dict]:
    """실행 직전에 요청자 권한으로 messages를 조립한다(§10.2). 저장하지 않는다."""
    raise NotImplementedError
