"""첨부 파일·산출물. IMPL-PLAN-7 §3 — 보안 점검표(§3.5)를 테스트로 고정한다."""

import hashlib
import logging
import re

import pytest
from django.core.files.uploadedfile import SimpleUploadedFile

from common.errors import ServiceError
from projects.models import ProjectDoc
from tasks import attachments as at
from tasks.models import Attachment

pytestmark = pytest.mark.django_db
HX = {"HX-Request": "true"}
PNG = b"\x89PNG\r\n\x1a\n" + b"0" * 64


@pytest.fixture(autouse=True)
def _media(settings, tmp_path):
    settings.MEDIA_ROOT = tmp_path


def _f(name="시안.png", data=PNG, content_type="image/png"):
    return SimpleUploadedFile(name, data, content_type=content_type)


def _add(task, user, **kw):
    kw.setdefault("upload", _f())
    return at.add_attachment(actor=user, task=task, **kw)


def test_upload_stores_uuid_name_and_server_content_type(task, member, settings):
    # 헤더는 text/html이라 주장해도 저장 content_type은 확장자 표에서 정한다.
    att = _add(task, member, upload=_f("../../시안 v1.PNG", content_type="text/html"))
    assert att.name == "시안 v1.PNG"  # 경로 부분은 버린다
    assert re.fullmatch(rf"att/{task.project.org_id}/[0-9a-f]{{32}}\.png", att.file.name)
    assert (att.size, att.content_type) == (len(PNG), "image/png")
    assert att.sha256 == hashlib.sha256(PNG).hexdigest()
    assert (settings.MEDIA_ROOT / att.file.name).read_bytes() == PNG


def test_size_checked_before_reading(task, member):
    class Huge:
        name = "big.png"
        size = at.MAX_BYTES + 1

        def chunks(self):
            raise AssertionError("크기 초과 파일을 읽었다")

    with pytest.raises(ServiceError) as e:
        _add(task, member, upload=Huge())
    assert "25MB" in e.value.errors["file"]


@pytest.mark.parametrize("name", ["x.svg", "x.html", "x.exe", "noext"])
def test_extension_allowlist(task, member, name):
    with pytest.raises(ServiceError):
        _add(task, member, upload=_f(name))
    assert not Attachment.objects.exists()


def test_count_limit_and_quota(task, member, org, monkeypatch):
    monkeypatch.setattr(at, "MAX_PER_TARGET", 2)
    _add(task, member)
    _add(task, member)
    with pytest.raises(ServiceError) as e:
        _add(task, member)
    assert "2개" in e.value.errors["file"]
    org.settings = {"org.attachment_quota_mb": 0}
    org.save()
    with pytest.raises(ServiceError) as e:
        at.add_attachment(actor=member, project=task.project, upload=_f())
    assert "용량" in e.value.errors["file"]


def test_version_chain(task, member):
    v1 = _add(task, member, kind="out")
    v2 = _add(task, member, kind="out", replaces=v1, note="색 수정")
    assert v2.version == 2
    latest = at.attachments_of(task)
    assert latest == [v2] and latest[0].history == [v1]
    with pytest.raises(ServiceError):  # 옛 버전에서 또 갈라지지 않는다
        _add(task, member, replaces=v1)
    other = at.add_attachment(actor=member, project=task.project, upload=_f())
    with pytest.raises(ServiceError):  # 다른 대상의 파일은 잇지 못한다
        _add(task, member, replaces=other)


def test_delete_permission_and_file_removed(
    task, member, admin, org, settings, django_capture_on_commit_callbacks
):
    from accounts.models import User
    from orgs.models import OrgMembership

    other = User.objects.create_user("other1", password="pw12345678", display_name="다른 사람")
    OrgMembership.objects.create(org=org, user=other, role="member")
    att = _add(task, member)
    path = settings.MEDIA_ROOT / att.file.name
    with pytest.raises(ServiceError):
        at.delete_attachment(att, actor=other)
    with django_capture_on_commit_callbacks(execute=True):
        at.delete_attachment(att, actor=admin)
    assert not path.exists() and not Attachment.objects.exists()


def test_log_has_name_only(task, member, caplog, settings):
    with caplog.at_level(logging.INFO, logger="tasks.attachments"):
        att = _add(task, member)
    text = caplog.text
    assert att.name in text and str(settings.MEDIA_ROOT) not in text and att.file.name not in text


def test_download_headers_and_visibility(client, task, member, outsider):
    png = _add(task, member)
    zipf = _add(task, member, upload=_f("원본.zip", b"PK\x03\x04", "application/zip"))
    client.force_login(member)
    r = client.get(f"/attachments/{png.pk}/whatever.html")  # URL의 이름은 무시한다
    assert r.status_code == 200 and b"".join(r.streaming_content) == PNG
    assert r["Content-Type"] == "image/png" and r["X-Content-Type-Options"] == "nosniff"
    assert (
        r["Content-Disposition"].startswith("inline") and r["Content-Security-Policy"] == "sandbox"
    )
    r = client.get(f"/attachments/{zipf.pk}/x")
    assert (
        r["Content-Disposition"].startswith("attachment")
        and r["X-Content-Type-Options"] == "nosniff"
    )
    client.force_login(outsider)
    assert client.get(f"/attachments/{png.pk}/x").status_code == 404
    client.logout()
    assert client.get(f"/attachments/{png.pk}/x").status_code == 302  # 로그인으로


def test_access_check_is_can_view_task(task, member, monkeypatch):
    """태스크 첨부는 tasks.services.can_view_task 한 곳을 따른다(열람 = 주 ∪ 연결, IMPL-PLAN-11 §3.4)."""
    from tasks import services as ts

    att = _add(task, member)
    monkeypatch.setattr(ts, "can_view_task", lambda user, task: False)
    assert at.can_download(member, att) is False
    with pytest.raises(ServiceError):
        _add(task, member)


def test_panel_upload_and_delete(client, task, member):
    client.force_login(member)
    r = client.post(
        f"/tasks/{task.pk}/attachments",
        {"file": _f("최종.pdf", b"%PDF-1.4", "application/pdf"), "kind": "out", "note": "최종"},
        headers=HX,
    )
    body = r.content.decode()
    assert r.status_code == 200 and "최종.pdf" in body and "산출물" in body
    att = Attachment.objects.get()
    r = client.post(f"/attachments/{att.pk}/delete", headers=HX)
    assert r.status_code == 200 and not Attachment.objects.exists()
    r = client.post(f"/tasks/{task.pk}/attachments", {"file": _f("x.svg")}, headers=HX)
    assert "올릴 수 없는 형식" in r.content.decode()


def test_project_files_section(client, project, member):
    client.force_login(member)
    r = client.post(f"/projects/{project.pk}/attachments", {"file": _f("브랜드.pdf", b"%PDF")})
    assert r.status_code == 302
    body = client.get(f"/projects/{project.pk}/docs").content.decode()
    assert "브랜드.pdf" in body and "파일" in body


def test_doc_as_output(client, task, member):
    doc = ProjectDoc.objects.create(project=task.project, title="보도자료", created_by=member)
    client.force_login(member)
    r = client.post(f"/tasks/{task.pk}/docs/link", {"doc": doc.pk, "as_output": "1"}, headers=HX)
    assert r.status_code == 200
    out = task.links.get(kind="out")
    assert out.title == "보도자료" and out.url.endswith(
        f"/projects/{task.project_id}/docs?doc={doc.pk}"
    )
    assert doc in task.docs.all()


def test_api_upload_list_download(client, write_token, task, member):
    h = {"Authorization": f"Bearer {write_token}"}
    r = client.post(
        f"/api/tasks/{task.pk}/attachments",
        {"file": _f("카드뉴스.png"), "kind": "out", "note": "1주차"},
        headers=h,
    )
    assert r.status_code == 201, r.content
    att = r.json()
    assert (att["kind"], att["version"], att["content_type"]) == ("out", 1, "image/png")
    r = client.post(
        f"/api/tasks/{task.pk}/attachments",
        {"file": _f("카드뉴스.png"), "kind": "out", "replaces": att["id"]},
        headers=h,
    )
    assert r.json()["version"] == 2
    listed = client.get(f"/api/tasks/{task.pk}/attachments", headers=h).json()
    assert [a["version"] for a in listed] == [2]
    assert len(client.get(f"/api/tasks/{task.pk}/attachments?all=true", headers=h).json()) == 2
    assert [
        a["version"] for a in client.get(f"/api/tasks/{task.pk}", headers=h).json()["attachments"]
    ] == [2]
    r = client.get(f"/api/attachments/{att['id']}/download", headers=h)
    assert r.status_code == 200 and b"".join(r.streaming_content) == PNG
    assert r["X-Content-Type-Options"] == "nosniff"
    r = client.post(f"/api/tasks/{task.pk}/attachments", {"file": _f("a.html")}, headers=h)
    assert r.status_code == 400
    assert client.delete(f"/api/attachments/{att['id']}", headers=h).status_code == 204


# ---------- 동시 업로드 경쟁 — 검사와 저장 사이에 다른 요청을 끼워 넣어 결정적으로 재현한다 ----------


class _Racing(SimpleUploadedFile):
    """검사를 모두 통과한 뒤 내용을 읽는 순간(해시 계산) 다른 요청 `other()`를 한 번 끝까지 실행한다.

    한 연결에서 돌리므로 끼어든 요청의 행은 바깥 요청이 롤백될 때 같이 사라진다(실제로는 별도
    트랜잭션이라 남는다). 그래서 DB 행 수가 아니라 "바깥 요청이 거부되는가"와 디스크의 파일을 본다.
    수정 전에는 바깥 요청이 그대로 저장돼 1,433,600 bytes·2개·v2 둘이 됐다."""

    def __init__(self, other, name="b.png", data=PNG):
        super().__init__(name, data, content_type="image/png")
        self.other = other

    def chunks(self, chunk_size=None):
        if self.other is not None:
            other, self.other = self.other, None
            other()
        return super().chunks(chunk_size)


def _stored(settings):
    return sorted(p for p in settings.MEDIA_ROOT.rglob("*") if p.is_file())


def test_quota_race_does_not_overshoot(task, member, org, settings):
    org.settings = {"org.attachment_quota_mb": 1}
    org.save()
    big = b"0" * (700 * 1024)

    def other():
        _add(task, member, upload=_f("a.png", big))

    with pytest.raises(ServiceError) as e:
        _add(task, member, upload=_Racing(other, data=big))
    assert "용량" in e.value.errors["file"]
    assert [p.stat().st_size for p in _stored(settings)] == [700 * 1024]  # 거부된 쪽 파일은 지운다


def test_count_race_does_not_overshoot(task, member, monkeypatch, settings):
    monkeypatch.setattr(at, "MAX_PER_TARGET", 1)
    with pytest.raises(ServiceError) as e:
        _add(task, member, upload=_Racing(lambda: _add(task, member)))
    assert "1개" in e.value.errors["file"]
    assert len(_stored(settings)) == 1


def test_version_race_keeps_single_successor(task, member, settings):
    v1 = _add(task, member)
    with pytest.raises(ServiceError) as e:
        _add(task, member, upload=_Racing(lambda: _add(task, member, replaces=v1)), replaces=v1)
    assert "새 버전" in e.value.errors["replaces"]
    assert len(_stored(settings)) == 2  # v1과 먼저 올라간 v2만


def test_single_successor_constraint(task, member):
    """잠금을 비켜 가도 DB가 두 번째 v2를 막는다."""
    from django.db import IntegrityError, transaction

    v1 = _add(task, member)
    _add(task, member, replaces=v1)
    with pytest.raises(IntegrityError), transaction.atomic():
        Attachment.objects.create(
            task=task,
            name="x.png",
            size=1,
            content_type="image/png",
            sha256="0",
            file="att/x.png",
            replaces=v1,
            created_by=member,
        )
