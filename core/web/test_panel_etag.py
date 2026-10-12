"""태스크 패널 ETag: 내용이 같으면 304, 바뀌면 새 본문."""

import pytest

from tasks import services as ts

pytestmark = pytest.mark.django_db
HX = {"HX-Request": "true"}


def test_panel_etag_304_until_task_changes(client, member, task):
    client.force_login(member)
    url = f"/tasks/{task.pk}/panel"
    first = client.get(url, headers=HX)
    etag = first["ETag"]
    assert first.status_code == 200 and etag
    # CSRF 값은 매번 달라도 같은 내용이면 304, 약한 ETag로 와도 같다
    assert client.get(url, headers={**HX, "If-None-Match": etag}).status_code == 304
    assert client.get(url, headers={**HX, "If-None-Match": "W/" + etag}).status_code == 304
    ts.update_task(task, {"priority": 1}, actor=member, source="web", expected_version=task.version)
    changed = client.get(url, headers={**HX, "If-None-Match": etag})
    assert changed.status_code == 200 and changed["ETag"] != etag


def test_panel_etag_by_data_version_skips_render(client, member, task, monkeypatch):
    """Postgres 경로: 데이터 버전이 같으면 패널을 그리지 않고 304, 버전이 바뀌면 다시 그린다."""
    from web import data_version
    from web.views import tasks as views

    version = {"v": "1-5-5"}
    renders = []
    real_panel = views._panel
    monkeypatch.setattr(data_version, "current", lambda: version["v"])
    monkeypatch.setattr(views, "_panel", lambda *a, **k: renders.append(1) or real_panel(*a, **k))
    client.force_login(member)
    url = f"/tasks/{task.pk}/panel"
    etag = client.get(url, headers=HX)["ETag"]
    assert len(renders) == 1
    assert client.get(url, headers={**HX, "If-None-Match": etag}).status_code == 304
    assert len(renders) == 1  # 그리지 않았다
    # 다른 사람·다른 주소는 같은 버전이어도 다른 ETag
    assert client.get(url + "?block=1", headers={**HX, "If-None-Match": etag}).status_code == 200
    version["v"] = "1-6-6"
    assert client.get(url, headers={**HX, "If-None-Match": etag}).status_code == 200
