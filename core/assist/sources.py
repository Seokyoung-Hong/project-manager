"""사용 순서 결정(IMPL-PLAN-12 §5.1). 몸체는 A 갈래."""

from dataclasses import dataclass


@dataclass(frozen=True)
class Attempt:
    """시도할 항목 하나. route = direct | pc | org. 키는 실행 직전에 복호화한다(여기 담지 않는다)."""

    route: str
    source: object = None  # AiSource | None(조직 AI 행이 없어 맨 뒤에 붙인 조직 AI)
    server: object = None  # route=pc일 때 SttServer


def plan(user, org) -> list[Attempt]:
    """사용자 AiSource(enabled) position 순 + 조직 AI. 스위치가 꺼져 있으면 빈 목록."""
    raise NotImplementedError
