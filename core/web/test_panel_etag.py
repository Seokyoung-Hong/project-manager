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
