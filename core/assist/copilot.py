"""개인 AI "GitHub Copilot(내 구독)". 사용자 본인 Copilot 구독으로 유달리 서버가 요청한다(PC 불필요).

토큰은 따로 받지 않는다 — 이미 연결된 GitHub App 사용자 토큰(GitHubIdentity, enc:+Fernet·refresh 갱신)을
github.services.user_token으로 실행 직전에 꺼내 세션마다 넘긴다(Copilot SDK github_token, 공식 문서
copilot-sdk/setup/github-oauth·multi-tenancy). 런타임은 compose의 copilot 서비스 하나(copilot --headless)를
모든 사용자가 같이 쓴다. 세션은 요청 한 번마다 만들고 지운다. 도구는 하나도 주지 않는다(mode="empty").

로그·화면에는 오류 코드만 남긴다(§11.4) — 토큰·본문·런타임 오류 원문 금지.
"""

import asyncio
import logging

from django.conf import settings

from .net import NetError

URL = "copilot:"  # AiSource.base_url 표식(route=direct, 마이그레이션 없이 표현). 키 칸은 비워 둔다

# SDK가 실패를 traceback(런타임 오류 원문 포함)으로 남긴다 — 우리는 코드만 남긴다.
logging.getLogger("copilot").setLevel(logging.CRITICAL)


def enabled() -> bool:
    """켜짐 = 플래그(ASSIST_COPILOT_ENABLED) + 런타임 주소. 꺼지면 버튼·실행 모두 없다."""
    return settings.ASSIST_COPILOT_ENABLED and bool(settings.COPILOT_RUNTIME_URL)


def models() -> list[str]:
    """고를 수 있는 모델. 첫째가 기본값."""
    return settings.COPILOT_MODELS


def token_for(user) -> str:
    """이 사람 자신의 GitHub 사용자 토큰(만료면 갱신). 없거나 갱신 실패·동의 멈춤이면 auth_failed."""
    from common.errors import ServiceError
    from github.client import GitHubError
    from github.models import GitHubIdentity
    from github.services import user_token

    identity = GitHubIdentity.objects.filter(user=user).first()
    if identity is None:
        raise NetError("auth_failed")
    try:
        token = user_token(identity)
    except (ServiceError, GitHubError):
        raise NetError("auth_failed") from None
    if not token:
        raise NetError("auth_failed")
    return token


def _prompt(messages) -> tuple[str, str]:
    """OpenAI 형식 messages → (시스템 지시, 한 번에 보낼 글). 재질문(assistant+user)은 대화 기록으로 붙인다."""
    system = "\n\n".join(m["content"] for m in messages if m["role"] == "system")
    rest = [m for m in messages if m["role"] != "system"]
    if len(rest) == 1:
        return system, rest[0]["content"]
    label = {"user": "사용자", "assistant": "AI"}
    return system, "\n\n".join(f"[{label.get(m['role'], m['role'])}]\n{m['content']}" for m in rest)


def _code(e: BaseException) -> str:
    if isinstance(e, TimeoutError):
        return "timeout"
    text = str(e).lower()
    # 런타임에 연결 못 함(SDK가 RuntimeError로 감싼다) 또는 연결 비밀 불일치(-32002) — 사용자 탓이 아니다
    if isinstance(e, OSError) or isinstance(e.__context__, OSError) or "-32002" in text:
        return "connect_failed"
    if any(
        w in text for w in ("401", "403", "unauthorized", "bad credentials", "token validation")
    ):
        return "auth_failed"  # 토큰 무효·Copilot 구독 없음·앱 권한 부족
    if "model" in text and ("not" in text or "unknown" in text or "unsupported" in text):
        return "model_not_found"
    if "429" in text or "rate" in text:
        return "http_4xx"
    return "http_5xx"


async def _chat(system, prompt, *, token, model, timeout_s):
    from copilot import CopilotClient, RuntimeConnection

    client = CopilotClient(
        connection=RuntimeConnection.for_uri(
            settings.COPILOT_RUNTIME_URL,
            connection_token=settings.COPILOT_CONNECTION_TOKEN or None,
        ),
        mode="empty",
    )
    await client.start()
    try:
        session = await client.create_session(
            model=model,
            github_token=token,
            available_tools=[],  # 도구 없음: 글만 쓴다
            system_message={"mode": "replace", "content": system} if system else None,
        )
        try:
            event = await session.send_and_wait(prompt, timeout=timeout_s)
        finally:
            try:
                await client.delete_session(session.session_id)  # 런타임 메모리를 붙잡지 않게
            except Exception:  # noqa: BLE001 — 정리 실패는 결과에 영향 없음(런타임 idle-timeout이 치운다)
                pass
    finally:
        await client.stop()
    content = getattr(getattr(event, "data", None), "content", None)
    if not isinstance(content, str):
        raise NetError("bad_output")
    return content


def chat(messages, *, token: str, model: str, timeout_s: int) -> str:
    """한 번 묻고 내용 글. 실패는 NetError(코드). 워커 스레드에서 부른다(스레드마다 새 이벤트 루프)."""
    if not enabled():
        raise NetError("no_source")
    system, prompt = _prompt(messages)
    try:
        return asyncio.run(
            _chat(system, prompt, token=token, model=model or models()[0], timeout_s=timeout_s)
        )
    except NetError:
        raise
    except Exception as e:  # noqa: BLE001 — SDK·JSON-RPC 오류를 코드로만 바꾼다
        raise NetError(_code(e)) from None
