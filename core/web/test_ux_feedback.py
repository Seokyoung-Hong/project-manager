from datetime import date

import pytest
from django.core.files.uploadedfile import SimpleUploadedFile

from common.errors import ServiceError
from orgs.models import Invite
from projects.docs import create_doc
from web.forms import QuickTaskForm, TaskInlineForm, suggested_due_date

pytestmark = pytest.mark.django_db


@pytest.fixture
def signed(client, member):
    client.force_login(member)
    return client


@pytest.mark.parametrize("days", ["0", "91", "invalid", ""])
def test_invalid_invite_period_never_creates_link(client, org, admin, days):
    client.force_login(admin)
    response = client.post(f"/orgs/{org.pk}/invites", {"days": days}, follow=True)
    assert not Invite.objects.filter(org=org).exists()
    assert "초대 링크는 만들지 않았습니다" in response.content.decode()


@pytest.mark.parametrize("kind,action", [("doc", "new"), ("doc", "upload"), ("doc", "delete"), ("note", "new"), ("note", "upload"), ("note", "delete")])
def test_document_failures_survive_redirect(signed, project, member, monkeypatch, kind, action):
    from notes import services as notes
    from projects import docs

    if kind == "doc":
        obj = docs.create_doc(project=project, actor=member)
        service = docs
        url = f"/docs/{obj.pk}/delete" if action == "delete" else f"/projects/{project.pk}/docs/{action}"
    else:
        obj = notes.create_note(org=project.org, actor=member)
        service = notes
        url = f"/notes/{obj.pk}/delete" if action == "delete" else f"/orgs/{project.org_id}/notes/{action}"

    def reject(*args, **kwargs):
        raise ServiceError({"body": "검증용 구체적인 실패 이유"})

    monkeypatch.setattr(service, f"{'create' if action == 'new' else action}_{kind}", reject)
    response = signed.post(url, {"file": SimpleUploadedFile("test.md", b"hello")}, follow=True)
    assert "검증용 구체적인 실패 이유" in response.content.decode()
    assert service.get_visible_doc(member, obj.pk) if kind == "doc" else service.get_visible_note(member, obj.pk)


def test_doc_save_error_and_conflict_are_machine_readable(signed, project, member):
    doc = create_doc(project=project, actor=member)
    error = signed.post(f"/docs/{doc.pk}/save", {"field": "unknown", "value": "", "version": doc.version})
    assert error.status_code == 400
    assert error.json()["error"]
    success = signed.post(f"/docs/{doc.pk}/save", {"field": "title", "value": "수정", "version": doc.version})
    assert success.status_code == 204
    conflict = signed.post(f"/docs/{doc.pk}/save", {"field": "title", "value": "충돌", "version": doc.version})
    assert conflict.status_code == 409
    assert "먼저 수정" in conflict.json()["error"]


@pytest.mark.parametrize("target", ["project", "task"])
def test_link_field_errors_preserve_input(signed, project, task, target):
    url = f"/projects/{project.pk}/links" if target == "project" else f"/tasks/{task.pk}/links"
    response = signed.post(url, {"title": "유지할 제목", "url": "bad-url", "kind": "doc"})
    assert response.status_code == 200
    assert 'value="유지할 제목"' in response.content.decode()
    assert 'value="bad-url"' in response.content.decode()
    assert response.context["link_form"].errors["url"]
    assert not (project.links if target == "project" else task.links).exists()


def test_due_suggestion_skips_weekends_and_never_sets_input(org, project, member, monkeypatch):
    monkeypatch.setattr("common.dates.today_kst", lambda: date(2026, 10, 2))  # 금요일
    org.settings = {"task.default_due_days": 3}
    org.save()
    assert suggested_due_date(org=org, project=project) == "2026-10-07"
    form = TaskInlineForm(org=org, project=project)
    assert form.suggested_due_date == "2026-10-07"
    assert form["due_date"].value() is None
    quick = QuickTaskForm(user=member)
    assert list(quick.fields["project"].queryset)[0].suggested_due_date == "2026-10-07"
    assert quick["due_date"].value() is None
    org.settings = {}
    assert suggested_due_date(org=org, project=project) == ""


def test_notification_choices_keep_integer_mapping(client, admin, org):
    from orgs.settings import SPECS, display

    assert dict(SPECS["user.notify_hour"].input_choices)[-1] == "조직 설정 따름"
    assert dict(SPECS["notify.weekly_weekday"].input_choices)[0] == "월요일"
    assert display("notify.send_hour", 0) == "00:00"
    assert display("task.doing_limit", 0) == "제한 없음"
    client.force_login(admin)
    response = client.post(f"/orgs/{org.pk}/settings", {"notify.weekly_weekday": "0", "notify.send_hour": "23"})
    assert response.status_code == 302
    org.refresh_from_db()
    assert org.settings["notify.send_hour"] == 23


@pytest.mark.parametrize("failed,expected", [(0, "열린 이슈 7건을 확인했습니다"), (1, "일부 저장소만 확인했습니다"), (2, "모두에서 이슈를 확인하지 못했습니다")])
def test_issue_sync_reports_complete_partial_and_total_failure(signed, project, member, monkeypatch, settings, failed, expected):
    from github.models import RepoConnection
    from projects.services import create_project

    settings.GITHUB_ENABLED = True
    other = create_project(org=project.org, name="다른 저장소", actor=member)
    for index, item in enumerate((project, other)):
        RepoConnection.objects.create(project=item, url=f"https://github.com/local/{index}", full_name=f"local/{index}", created_by=member)
    monkeypatch.setattr("github.services.sync_org_issues", lambda org: (7 if failed < 2 else 0, failed))
    response = signed.post(f"/orgs/{project.org_id}/issues/sync", follow=True)
    body = response.content.decode()
    assert expected in body
    if failed:
        assert "열린 이슈 7건을 확인했습니다" not in body
