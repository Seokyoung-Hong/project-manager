"""모든 서버발 AI 호출의 관문(IMPL-PLAN-12 §11.1·§6.1). 몸체는 A 갈래.

IP 고정·리다이렉트 거부·1MB 상한. 기존 _stt_call·validate_stt_url은 쓰지 않는다.
실패는 NetError(code), code는 assist.models.ERROR_CODES 중 하나.
"""

from urllib.parse import urlsplit


class NetError(Exception):
    def __init__(self, code: str):
        self.code = code
        super().__init__(code)


def classify(url: str) -> str:
    """개인 AI 주소 판정: "direct"(모두 공개 IP, https만) | "pc"(PC 안·사설). 쓸 수 없으면 ServiceError."""
    raise NotImplementedError


def check_org_url(url: str) -> str:
    """조직 AI 주소 검사(조직 설정 validate). 오류 문구, ""면 통과.

    A0 임시 구현: 형식만 본다. A 갈래가 해석·허용 호스트(AllowedHost) 판정으로 바꾼다.
    """
    if not url:
        return ""
    try:
        parts = urlsplit(url)
        _ = parts.port
    except ValueError:
        return "주소 형식이 올바르지 않습니다."  # COPY:assist_url_invalid
    if parts.scheme not in ("http", "https") or not parts.hostname:
        return "http:// 또는 https://로 시작하는 주소여야 합니다."  # COPY:assist_url_scheme
    if parts.username or parts.password or parts.query or parts.fragment:
        return "사용자 정보·쿼리가 없는 주소여야 합니다."  # COPY:assist_url_extra
    return ""


def list_models(
    base_url: str, *, api_key: str = "", org: bool = False, timeout_s: int = 5
) -> list[str]:
    """GET {base_url}/models → 모델 id 목록. [연결 시험]·[모델 불러오기]가 쓴다. org=True면 허용 호스트를 본다."""
    raise NotImplementedError


def chat(
    base_url: str, payload: dict, *, api_key: str = "", org: bool = False, timeout_s: int = 30
) -> dict:
    """POST {base_url}/chat/completions → 응답 JSON. 워커가 쓴다."""
    raise NotImplementedError
