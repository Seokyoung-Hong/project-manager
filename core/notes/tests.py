import pytest

from common.errors import ConflictError, ServiceError
from orgs.services import create_org
from projects.services import create_project

from .services import (
    create_note,
    delete_note,
    update_note,
    upload_note,
)

pytestmark = pytest.mark.django_db


def test_note_project_must_be_same_org(org, admin, member):
    other_org = create_org("다른 조직", "", admin)
    other_project = create_project(
        org=other_org, name="다른 프로젝트", actor=admin, owners=[admin], status="active"
    )
    with pytest.raises(ServiceError):
        create_note(org=org, actor=member, project=other_project)


def test_note_title_defaults_when_blank(org, member):
    note = create_note(org=org, actor=member, title="   ")
    assert note.title == "제목 없는 회의록"


def test_note_body_size_cap(org, member):
    note = create_note(org=org, actor=member)
    with pytest.raises(ServiceError):
        update_note(
            note, "body_md", "a" * (256 * 1024 + 1), actor=member, expected_version=note.version
        )


def test_note_save_bumps_version(org, member):
    note = create_note(org=org, actor=member)
    updated = update_note(note, "title", "새 제목", actor=member, expected_version=note.version)
    assert updated.version == 2
    assert updated.title == "새 제목"


def test_note_save_conflict_returns_409(org, member):
    note = create_note(org=org, actor=member)
    stale_version = note.version
    update_note(note, "title", "첫 수정", actor=member, expected_version=stale_version)
    with pytest.raises(ConflictError):
        update_note(note, "title", "낡은 버전 수정", actor=member, expected_version=stale_version)


def test_upload_md_only(org, member):
    with pytest.raises(ServiceError):
        upload_note(org=org, actor=member, filename="회의.txt", raw=b"hello")
    note = upload_note(org=org, actor=member, filename="회의.md", raw="# 안녕".encode())
    assert note.body_md == "# 안녕"


def test_upload_rejects_non_utf8(org, member):
    with pytest.raises(ServiceError):
        upload_note(org=org, actor=member, filename="회의.md", raw="가".encode("euc-kr"))


def test_upload_title_from_filename(org, member):
    note = upload_note(org=org, actor=member, filename="주간 회의.md", raw=b"body")
    assert note.title == "주간 회의"


def test_note_delete_author_or_admin(org, admin, member, outsider):
    from orgs.models import OrgMembership

    OrgMembership.objects.create(org=org, user=outsider, role="member")
    note = create_note(org=org, actor=member)
    with pytest.raises(ServiceError):
        delete_note(note, outsider)
    delete_note(note, admin)
    assert not org.docs.filter(pk=note.pk).exists()


def test_note_is_a_meeting_doc_with_revisions_and_backlinks(org, member, team, project):
    """회의록은 문서(kind=meeting)라 이전 버전·되돌리기·백링크가 같이 된다. 템플릿은 목록에서 빠진다."""
    from notes.services import visible_notes
    from projects import docs
    from projects.models import Doc

    note = create_note(org=org, actor=member, title="주간 회의", body_md="처음")
    assert note.kind == "meeting" and note.source == "web"
    assert list(visible_notes(member)) == [note]  # 조직 템플릿 "회의록"은 빠진다
    note = update_note(note, "body_md", "고침", actor=member, expected_version=note.version)
    first = note.revisions.get(version=1)
    note = docs.revert_doc(note, first, actor=member, expected_version=note.version)
    assert note.body_md == "처음"
    ref = docs.create_doc(org=org, actor=member, body_md=f"[회의](/docs/{note.pk})")
    assert docs.backlinks(note, member)["docs"] == [ref]

    # 팀 회의록에 프로젝트를 고르면 팀은 비워진다(공개 범위는 하나만).
    Doc.objects.filter(pk=note.pk).update(team=team)
    note.refresh_from_db()
    note = update_note(note, "project", project, actor=member, expected_version=note.version)
    assert (note.project, note.team) == (project, None)
