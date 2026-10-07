"""Sol 교차 검토(R-sol-review-r11-12.md) 문서 영역 재현: R1·R2·R6·R9. R3는 notes/test_migrate_doc.py."""

import io
import zipfile

import pytest
from django.core.files.uploadedfile import SimpleUploadedFile

from accounts.models import ApiToken, User
from common.errors import ServiceError
from orgs.models import OrgMembership
from orgs.services import delete_team
from projects import docs as svc
from projects.models import Doc
from projects.services import archive_project, create_project, delete_project, set_visibility
from tasks.models import Attachment
from tasks.services import approve_link, create_task, link_project

pytestmark = pytest.mark.django_db
PNG = b"\x89PNG\r\n\x1a\n" + b"0" * 64


@pytest.fixture(autouse=True)
def _media(settings, tmp_path):
    settings.MEDIA_ROOT = tmp_path


@pytest.fixture
def viewer(org):
    """비공개 프로젝트를 못 보는 일반 멤버."""
    u = User.objects.create_user("viewer1", password="pw12345678", display_name="열람자")
    OrgMembership.objects.create(org=org, user=u, role="member")
    return u


def _auth(user):
    _, raw = ApiToken.issue(user, "t", "write", for_ai=False)
    return {"Authorization": f"Bearer {raw}"}


@pytest.fixture
def linked(org, admin):
    """비공개 P의 태스크 T를 공개 Q에 연결(승인). P 문서 D는 T에 걸고, E는 걸지 않는다."""
    p = create_project(org=org, name="비밀 P", actor=admin, owners=[admin])
    set_visibility(p, "teams", actor=admin)
    q = create_project(org=org, name="공개 Q", actor=admin, owners=[admin])
    t = create_task(project=p, title="연결 태스크", actor=admin, source="web", no_due_reason="미정")
    approve_link(link_project(t, q, actor=admin, confirm_widening=True), actor=admin)
    d = svc.create_doc(project=p, actor=admin, title="비밀 설계 D")
    svc.create_doc(project=p, actor=admin, title="비밀 메모 E")
    svc.link_task(d, t, admin)
    return t, d


# ---------- R1 ----------


def test_r1_linked_task_hides_private_doc_titles(client, linked, viewer):
    t, d = linked
    assert not svc.can_view_doc(viewer, d)
    r = client.get(f"/api/tasks/{t.pk}", headers=_auth(viewer))
    assert r.status_code == 200 and r.json()["docs"] == []
    client.force_login(viewer)
    html = client.get(f"/tasks/{t.pk}").content.decode()
    assert "비밀 설계 D" not in html and "비밀 메모 E" not in html


def test_r1_doc_as_output_refused_when_task_viewers_cannot_see_doc(linked, admin):
    t, _ = linked
    other = svc.create_doc(project=t.project, actor=admin, title="산출물 후보")
    with pytest.raises(ServiceError):
        svc.link_task(other, t, admin, as_output=True)
    assert not t.links.filter(title="산출물 후보").exists()


# ---------- R2 ----------


def test_r2_deleting_private_team_keeps_docs_private(org, admin, member, viewer, team):
    team.is_private = True
    team.save()
    d = svc.create_doc(org=org, team=team, actor=member, title="팀 비밀")
    with pytest.raises(ServiceError):
        delete_team(team, actor=admin)  # 문서가 있으면 먼저 옮기라고 막는다
    d.refresh_from_db()
    assert d.team == team and not svc.can_view_doc(viewer, d)


def test_r2_deleting_private_project_removes_docs(client, org, admin, viewer):
    p = create_project(org=org, name="지울 P", actor=admin, owners=[admin])
    set_visibility(p, "teams", actor=admin)
    d = svc.create_doc(project=p, actor=admin, title="프로젝트 비밀", body_md="본문")
    from tasks import attachments as at

    att = at.add_attachment(actor=admin, upload=SimpleUploadedFile("a.png", PNG), doc=d)
    archive_project(p, actor=admin)
    delete_project(p, actor=admin)
    assert not Doc.objects.filter(pk=d.pk).exists()
    assert not Attachment.objects.filter(pk=att.pk).exists()
    client.force_login(viewer)
    assert client.get(f"/docs/{d.pk}").status_code == 404
    assert "프로젝트 비밀" not in client.get(f"/orgs/{org.pk}/docs").content.decode()


# ---------- R6 ----------


def test_r6_doc_and_note_task_ids_only_visible(client, org, admin, viewer):
    from notes.services import create_note, link_task

    p = create_project(org=org, name="숨은 P", actor=admin, owners=[admin])
    set_visibility(p, "teams", actor=admin)
    hidden = create_task(
        project=p, title="숨은 일", actor=admin, source="web", no_due_reason="미정"
    )
    d = svc.create_doc(org=org, actor=admin)
    svc.link_task(d, hidden, admin)
    n = create_note(org=org, actor=admin)
    link_task(n, hidden, admin)
    h = _auth(viewer)
    assert client.get(f"/api/project-docs/{d.pk}", headers=h).json()["task_ids"] == []
    items = client.get(f"/api/project-docs?org={org.pk}", headers=h).json()["items"]
    assert all(i["task_ids"] == [] for i in items)
    assert client.get(f"/api/notes/{n.pk}", headers=h).json()["task_ids"] == []
    r = client.patch(
        f"/api/project-docs/{d.pk}",
        {"version": 99, "title": "x"},
        content_type="application/json",
        headers=h,
    )
    assert r.status_code == 409 and r.json()["latest"]["task_ids"] == []


# ---------- R9 ----------


def _zip(n, size=10, prefix="a"):
    buf = io.BytesIO()
    with zipfile.ZipFile(buf, "w") as zf:
        for i in range(n):
            zf.writestr(f"{prefix}{i}.md", "x" * size)
    return buf.getvalue()


def test_r9_file_count_rejected_before_reading(org, member, monkeypatch):
    big = _zip(501)  # 만들기(쓰기용 open)는 감시 전에 끝낸다
    reads = []
    real_open = zipfile.ZipFile.open

    def spy(self, *a, **k):
        reads.append(a[0])
        return real_open(self, *a, **k)

    def spy_read(self, *a, **k):
        reads.append(a[0])
        raise AssertionError("read 금지")

    monkeypatch.setattr(zipfile.ZipFile, "open", spy)
    monkeypatch.setattr(zipfile.ZipFile, "read", spy_read)
    with pytest.raises(ServiceError):
        svc.import_md(org=org, actor=member, files=[("big.zip", big)])
    assert reads == []


def test_r9_total_size_is_per_request(org, member, monkeypatch):
    monkeypatch.setattr(svc, "ZIP_MAX_TOTAL", 1000)
    files = [("a.zip", _zip(1, 600, "a")), ("b.zip", _zip(1, 600, "b"))]
    with pytest.raises(ServiceError):
        svc.import_md(org=org, actor=member, files=files)
    assert not Doc.objects.filter(org=org, origin="import").exists()


def test_r9_lying_header_is_capped_while_streaming(org, member):
    buf = io.BytesIO()
    with zipfile.ZipFile(buf, "w") as zf:
        zf.writestr("big.md", "가" * 200_000)  # 600KB > 256KB
    with pytest.raises(ServiceError):
        svc.import_md(org=org, actor=member, files=[("x.zip", buf.getvalue())])
