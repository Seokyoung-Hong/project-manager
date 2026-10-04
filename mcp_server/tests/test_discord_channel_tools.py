"""채널 연결 도구는 권한 밖 인원 허용을 기본으로 끄고, 켜는 인자는 사용자 확인 뒤에만 쓰게 안내한다."""

from mcp_server import server as s


def test_assign_defaults_to_not_allowing_outsiders(monkeypatch):
    sent = {}
    monkeypatch.setattr(
        s, "_discord_control", lambda m, p, b=None: sent.update(path=p, body=b) or {}
    )
    s.assign_project_channel(1, 2, "555")
    assert sent["body"]["allow_outsiders"] is False and sent["body"]["managed"] is None
    s.assign_project_channel(1, 2, "555", allow_outsiders=True, managed=True)
    assert sent["body"]["allow_outsiders"] is True and sent["body"]["managed"] is True
    assert "사용자 확인 후" in s.assign_project_channel.__doc__
