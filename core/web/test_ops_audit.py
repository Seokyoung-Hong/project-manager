"""운영 콘솔 감사 기록 화면·CSV(IMPL-PLAN-10 O3)."""

import csv
import io
from datetime import timedelta

import pytest
from django.utils import timezone

from accounts.models import User
from ops.models import OpsAuditLog

pytestmark = pytest.mark.django_db

HEADER = [
    "id", "created_at", "actor_username", "action", "target_type", "target_id",
    "target_label", "reason", "detail", "ip",
]  # fmt: skip


@pytest.fixture
def staff(db):
    return User.objects.create_user("staff1", password="pw12345678", is_staff=True)


def _log(actor="staff1", action="user.suspend", label="member1", **kw):
    return OpsAuditLog.objects.create(
        actor_username=actor, action=action, target_type="user", target_label=label, **kw
    )


def _csv(r):
    text = b"".join(r.streaming_content).decode("utf-8-sig")
    return list(csv.DictReader(io.StringIO(text)))


def test_only_operators(client, member):
    assert client.get("/ops/audit").status_code == 302
    client.force_login(member)
    assert client.get("/ops/audit").status_code == 404
    assert client.get("/ops/audit.csv").status_code == 404
    assert not OpsAuditLog.objects.filter(action="audit.export").exists()


def test_list_filters(client, staff):
    _log(reason="스팸 가입 정지")
    _log(actor="staff2", action="token.revoke", label="abc…")
    client.force_login(staff)
    body = client.get("/ops/audit").content.decode()
    assert "스팸 가입 정지" in body and "토큰 폐기" in body
    body = client.get("/ops/audit", {"actor": "staff2"}).content.decode()
    assert "abc…" in body and "스팸 가입 정지" not in body
    body = client.get("/ops/audit", {"action": "user.suspend", "target": "member"}).content.decode()
    assert "스팸 가입 정지" in body and "abc…" not in body
    tomorrow = (timezone.localdate() + timedelta(days=1)).isoformat()
    assert "스팸 가입 정지" not in client.get("/ops/audit", {"from": tomorrow}).content.decode()
    today = timezone.localdate().isoformat()
    assert (
        "스팸 가입 정지" in client.get("/ops/audit", {"from": today, "to": today}).content.decode()
    )
    assert client.get("/ops/audit", {"from": "엉터리", "action": "x"}).status_code == 200


def test_pagination_and_read_only(client, staff):
    OpsAuditLog.objects.bulk_create(
        [
            OpsAuditLog(actor_username="s", action="user.suspend", target_label=f"t{i}")
            for i in range(120)
        ]
    )
    client.force_login(staff)
    body = client.get("/ops/audit").content.decode()
    assert "1 / 2쪽" in body and "총 120건" in body
    assert 'method="post"' not in body.split('class="table-scroll"')[1]  # 수정·삭제 UI 없음
    assert OpsAuditLog.objects.count() == 120


def test_csv_content_filter_and_self_record(client, staff):
    _log(reason="=HYPERLINK(1)")
    _log(actor="staff2", action="token.revoke", label="abc…")
    client.force_login(staff)
    r = client.get("/ops/audit.csv", {"actor": "staff1"})
    assert r["Content-Type"].startswith("text/csv")
    rows = _csv(r)
    assert [x["actor_username"] for x in rows] == ["staff1"]
    assert rows[0]["reason"] == "'=HYPERLINK(1)"  # 수식 주입 방지
    assert list(rows[0]) == HEADER
    rec = OpsAuditLog.objects.get(action="audit.export")
    assert rec.actor_username == "staff1" and rec.target_type == "audit"
    assert rec.detail["rows"] == 1 and rec.detail["filter"] == {"actor": "staff1"}
    assert len(_csv(client.get("/ops/audit.csv"))) == 3  # 첫 내보내기 기록까지, 자기 자신은 제외
    assert OpsAuditLog.objects.filter(action="audit.export").count() == 2


def test_design_page_has_ops_samples(client, staff):
    client.force_login(staff)
    body = client.get("/ops/design").content.decode()
    assert 'id="sg-ops"' in body and "감사 기록 행" in body and "사유·재입력 확인 대화상자" in body
