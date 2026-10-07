"""IMPL-PLAN-11 D2: 문서 화면·회의록 편집 통합·검색·문서 첨부."""

import io
import zipfile

import pytest
from django.core.files.uploadedfile import SimpleUploadedFile

from accounts.models import User
from notes.models import VoiceRecording
from notes.services import create_note
from orgs.models import OrgMembership
from projects import docs as svc
from projects.models import Doc
from tasks.models import Attachment

pytestmark = pytest.mark.django_db
PNG = b"\x89PNG\r\n\x1a\n" + b"0" * 64


@pytest.fixture(autouse=True)
def _media(settings, tmp_path):
    settings.MEDIA_ROOT = tmp_path


@pytest.fixture
def logged(client, member):
    client.force_login(member)
    return client


@pytest.fixture
def other(org):
    u = User.objects.create_user("other9", password="pw12345678", display_name="다른 멤버")
    OrgMembership.objects.create(org=org, user=u, role="member")
    return u


def test_org_tab_tree_and_template_new(logged, org, member):
    tpl = Doc.objects.get(org=org, is_template=True, title="설계 문서")
    r = logged.post(
        f"/orgs/{org.pk}/docs/new",
        {"title": "결제 설계", "template": tpl.pk, "scope": "", "next": f"/orgs/{org.pk}/docs"},
    )
    root = Doc.objects.get(title="결제 설계")
    assert r.status_code == 302 and r["Location"].endswith(f"?doc={root.pk}")
    assert root.body_md.startswith("## 배경")
    logged.post(f"/orgs/{org.pk}/docs/new", {"title": "환불", "parent": root.pk})
    body = logged.get(f"/orgs/{org.pk}/docs?doc={root.pk}").content.decode()
    assert 'aria-label="문서 트리"' in body and "환불" in body and ">문서</a>" in body
    assert "이전 버전" in body and "백링크" in body and 'data-url="/docs/' in body


def test_hidden_team_doc_stays_hidden(logged, client, org, admin, member, other, team):
    team.is_private = True
    team.save()
    d = svc.create_doc(org=org, team=team, actor=member, title="팀 비밀")
    assert logged.get(f"/docs/{d.pk}").status_code == 302
    client.force_login(other)
    assert client.get(f"/docs/{d.pk}").status_code == 404
    assert "팀 비밀" not in client.get(f"/orgs/{org.pk}/docs").content.decode()
    assert "팀 비밀" not in client.get("/search?q=팀").content.decode()


def test_import_md_files_from_dialog(logged, org, member, project):
    files = [
        SimpleUploadedFile("가이드 0123456789abcdef0123456789abcdef.md", "# 가이드\n본문".encode()),
        SimpleUploadedFile("메모.md", "그냥 메모".encode()),
    ]
    r = logged.post(f"/projects/{project.pk}/docs/upload", {"file": files}, follow=True)
    body = r.content.decode()
    assert "문서 2개를 가져왔습니다." in body
    assert set(project.docs.values_list("title", flat=True)) == {"가이드", "메모"}


def test_revert_move_export_from_screen(logged, org, member, project):
    d = svc.create_doc(org=org, actor=member, title="절차", body_md="처음")
    d = svc.update_doc(d, "body_md", "고침", actor=member, expected_version=1)
    first = d.revisions.get(version=1)
    logged.post(f"/docs/{d.pk}/revert", {"revision": first.pk, "version": d.version})
    d.refresh_from_db()
    assert d.body_md == "처음"
    r = logged.post(f"/docs/{d.pk}/revert", {"revision": first.pk, "version": 1}, follow=True)
    assert "다른 사람이 먼저 수정했습니다" in r.content.decode()  # 버전 충돌 안내

    logged.post(f"/docs/{d.pk}/move", {"parent": "", "scope": f"p{project.pk}"})
    d.refresh_from_db()
    assert d.project == project
    r = logged.get(f"/orgs/{org.pk}/docs/export.zip")
    assert zipfile.ZipFile(io.BytesIO(r.content)).namelist() == ["절차.md"]
    assert logged.get(f"/docs/{d.pk}/export.md").content == "처음".encode()


def test_doc_attachment_follows_doc_visibility(logged, client, org, admin, member, other, team):
    team.is_private = True
    team.save()
    d = svc.create_doc(org=org, team=team, actor=member)
    logged.post(f"/docs/{d.pk}/attachments", {"file": SimpleUploadedFile("그림.png", PNG)})
    att = Attachment.objects.get(doc=d)
    body = logged.get(f"/orgs/{org.pk}/docs?doc={d.pk}").content.decode()
    assert "본문에 넣기" in body and f"/attachments/{att.pk}/" in body
    assert logged.get(f"/attachments/{att.pk}/그림.png").status_code == 200
    client.force_login(other)
    assert client.get(f"/attachments/{att.pk}/그림.png").status_code == 404


def test_meeting_screen_uses_doc_editor_and_finalize(logged, client, org, admin, member, other):
    n = create_note(org=org, actor=member, title="주간", body_md="안건")
    Doc.objects.filter(pk=n.pk).update(status="draft", origin="voice")
    VoiceRecording.objects.create(
        note=n,
        guild_id="g",
        voice_channel_id="v",
        started_by=member,
        host=member,
        status="draft",
        transcript_md="전사 내용",
    )
    body = logged.get(f"/orgs/{org.pk}/notes?note={n.pk}").content.decode()
    assert "초안 — 진행자와 조직 관리자만 봅니다." in body
    assert "이전 버전" in body and "전사 내용" in body and "note_finalize" not in body
    client.force_login(other)
    assert "주간" not in client.get(f"/orgs/{org.pk}/notes").content.decode()

    client.force_login(member)  # logged와 client는 같은 객체다
    logged.post(f"/notes/{n.pk}/finalize", {"scope": ""})
    n.refresh_from_db()
    assert n.status == "final"
    client.force_login(other)
    assert "주간" in client.get(f"/orgs/{org.pk}/notes").content.decode()


def test_search_shows_three_groups(logged, org, member):
    svc.create_doc(org=org, actor=member, title="배포 절차", body_md="롤백 방법")
    create_note(org=org, actor=member, title="롤백 회의")
    body = logged.get("/search?q=롤백").content.decode()
    assert "배포 절차" in body and "롤백 회의" in body and "회의록 <span" in body
