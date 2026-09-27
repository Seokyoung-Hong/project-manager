"""조직 경로 태스크 목록. 조직 안에서 보는 쪽은 그 조직 것만 받는다."""

import pytest

from accounts.models import ApiToken
from orgs.services import create_org
from projects.services import create_project
from tasks.services import create_task

pytestmark = pytest.mark.django_db


def _h(token):
    return {"Authorization": f"Bearer {token}"}


def test_only_that_orgs_tasks(client, org, project, task, member, write_token):
    other = create_org("다른 조직", "", member)
    other_project = create_project(org=other, name="다른 프로젝트", actor=member, owners=[member])
    create_task(project=other_project, title="남의 조직 일", actor=member, source="web", no_due_reason="x")

    everything = client.get("/api/tasks", headers=_h(write_token)).json()
    assert everything["total"] == 2  # 전체 보기는 그대로 조직을 가로지른다

    r = client.get(f"/api/orgs/{org.pk}/tasks", headers=_h(write_token))
    assert r.status_code == 200
    assert [t["id"] for t in r.json()["items"]] == [task.pk]

    scoped = client.get(f"/api/orgs/{org.pk}/tasks?project={project.pk}&status=todo", headers=_h(write_token))
    assert scoped.json()["total"] == 1

    wrong = client.get(f"/api/orgs/{org.pk}/tasks?project={other_project.pk}", headers=_h(write_token))
    assert wrong.status_code == 404


def test_outsider_cannot_see_org(client, org, task, outsider):
    _, raw = ApiToken.issue(outsider, "o", "read")
    assert client.get(f"/api/orgs/{org.pk}/tasks", headers=_h(raw)).status_code == 404
