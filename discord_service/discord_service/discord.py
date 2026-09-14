import logging
import time

import httpx

log = logging.getLogger(__name__)

API = "https://discord.com/api/v10"
MAX_LEN = 1900  # Discord content 한도 2000자, 여유
# Discord는 봇 요청에 User-Agent를 요구한다. 없으면 Cloudflare가 40333으로 막는다.
UA = "DiscordBot (https://github.com/sandol-pm, 0.1)"
STALE_CHANNEL = 10003  # 캐시해 둔 DM 채널이 사라졌다. 한 번 다시 열면 된다.
# 3회 루프에 넣지 않고 즉시 포기할 코드들. 50007·50278·10013은 그 사용자에 대해 영구적이고,
# 재시도하면 10분당 1만 invalid-request 예산만 태운다(LXC는 egress IP가 하나다).
NO_RETRY_CODES = {50007, 50278, 10013, STALE_CHANNEL}


def chunk(text: str) -> list[str]:
    """줄 단위로 1900자 이하 조각으로 나눈다."""
    parts, buf = [], ""
    for line in text.splitlines(keepends=True):
        if len(buf) + len(line) > MAX_LEN and buf:
            parts.append(buf)
            buf = ""
        buf += line
    if buf:
        parts.append(buf)
    return parts or [""]


class UnknownResult(Exception):
    """응답을 못 받아 성공 여부를 모른다."""


class DmBlocked(Exception):
    """그 사람에게는 DM을 보낼 수 없다. 재시도해도 달라지지 않는다."""

    def __init__(self, code: int):
        super().__init__(f"discord {code}")
        self.code = code


class ChannelOpenFailed(Exception):
    """DM 채널을 여는 데 실패했다. 아직 아무것도 보내지 않았으므로 다음 실행에서 다시 하면 된다.

    채널 열기는 멱등이다(이미 있으면 그 채널을 돌려준다). 그래서 '결과 불명확'이 아니라
    '재시도 가능'이다 — 보낸 것으로 표시해 버리면 그 사람은 그날 알림을 못 받는다.
    """


class Bot:
    """Discord 봇 REST. 개인 DM과 채널 게시 두 가지만 한다.

    게이트웨이(수신)는 listener.py가 discord.py로 맡는다. 여기는 발송 전용이라
    httpx 동기 호출로 충분하다.
    """

    def __init__(
        self, token: str, channel_id: str = "", store=None, transport=None, sleep=time.sleep
    ):
        self.http = httpx.Client(
            base_url=API,
            timeout=15,
            headers={"Authorization": f"Bot {token}", "User-Agent": UA},
            transport=transport,
        )
        # 팀 채널: 주간 보고와 'DM을 못 보냈다' 통보가 가는 곳. 배포당 하나다.
        self.channel_id = str(channel_id)
        self.store = store
        self.sleep = sleep

    # ---------- 개인 DM ----------

    def dm_channel(self, discord_user_id: str) -> str:
        """(봇, 사용자) 쌍의 DM 채널 id. 봇 전체가 한 버킷을 쓰므로 캐시한다.

        매번 열면 `40003 You are opening direct messages too fast`가 나고, 문서도
        새 DM을 여는 것 자체가 제한된다고 경고한다.
        """
        if self.store is not None:
            cached = self.store.dm_channel(discord_user_id)
            if cached:
                return cached
        try:
            data = self._request(
                "POST", "/users/@me/channels", {"recipient_id": str(discord_user_id)}
            )
        except DmBlocked:
            raise  # 그 사람에게는 열 수 없다(50007·50278·10013). 영구 실패다.
        except Exception as e:  # noqa: BLE001  타임아웃·5xx·3회 실패
            raise ChannelOpenFailed(str(e)) from e
        channel_id = str(data["id"])
        if self.store is not None:
            self.store.save_dm_channel(discord_user_id, channel_id)
        return channel_id

    def send_dm(self, discord_user_id: str, text: str) -> str:
        """받는 사람 본인에게만 가므로 멘션을 만들지 않는다."""
        channel_id = self.dm_channel(discord_user_id)
        for part in chunk(text):
            try:
                self._post(channel_id, part, parse=[])
            except DmBlocked as e:
                if e.code != STALE_CHANNEL:
                    raise
                # 캐시한 채널이 사라졌다. 한 번만 다시 열고 **이 조각부터** 이어 보낸다.
                # 본문 전체를 다시 보내면 앞 조각이 두 번 도착한다.
                if self.store is not None:
                    self.store.forget_dm_channel(discord_user_id)
                channel_id = self.dm_channel(discord_user_id)
                self._post(channel_id, part, parse=[])
        return "sent"

    # ---------- 채널 ----------

    def send_channel(self, text: str) -> str:
        """팀 채널 게시(주간 보고 등). 멘션이 목적이라 사용자 멘션만 허용한다."""
        if not self.channel_id:
            raise RuntimeError("DISCORD_CHANNEL_ID가 없습니다.")
        self._send(self.channel_id, text, parse=["users"])
        return "sent"

    def send_channel_to(self, channel_id: str, text: str) -> str:
        """프로젝트·팀별 채널 게시. 멘션은 만들지 않는다(개인 DM과 같은 원칙)."""
        self._send(str(channel_id), text, parse=[])
        return "sent"

    # ---------- 내부 ----------

    def _send(self, channel_id: str, text: str, *, parse: list[str]) -> None:
        for part in chunk(text):
            self._post(channel_id, part, parse=parse)

    def _post(self, channel_id: str, content: str, *, parse: list[str]) -> None:
        self._request(
            "POST",
            f"/channels/{channel_id}/messages",
            {"content": content, "allowed_mentions": {"parse": parse}},
        )

    def _request(self, method: str, path: str, json_body: dict) -> dict:
        """3회까지. 429·5xx는 백오프, DM 불가 코드는 즉시 포기."""
        delay = 2.0
        last = None
        for _ in range(3):
            try:
                r = self.http.request(method, path, json=json_body)
            except httpx.TimeoutException as e:
                raise UnknownResult(str(e)) from e
            except httpx.HTTPError as e:
                last = e
                self.sleep(delay)
                delay *= 2
                continue
            if r.status_code in (200, 201, 204):
                return r.json() if r.content else {}
            code = _error_code(r)
            if code in NO_RETRY_CODES:
                raise DmBlocked(code)
            if r.status_code == 429 or r.status_code >= 500:
                # retry_after는 초 단위(v8+). 숫자를 하드코딩하지 않고 헤더/본문을 따른다.
                retry_after = _retry_after(r, delay)
                last = RuntimeError(f"HTTP {r.status_code}")
                self.sleep(max(retry_after, delay))
                delay *= 2
                continue
            raise RuntimeError(f"HTTP {r.status_code}: {r.text[:200]}")
        raise RuntimeError(f"3회 실패: {last}")


def _error_code(r: httpx.Response) -> int | None:
    try:
        return r.json().get("code")
    except Exception:  # noqa: BLE001  본문이 JSON이 아닐 수 있다
        return None


def _retry_after(r: httpx.Response, default: float) -> float:
    for value in (r.headers.get("Retry-After"), _body_retry_after(r)):
        try:
            return float(value)
        except (TypeError, ValueError):
            continue
    return default


def _body_retry_after(r: httpx.Response):
    try:
        return r.json().get("retry_after")
    except Exception:  # noqa: BLE001
        return None
