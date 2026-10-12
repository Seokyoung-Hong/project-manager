"""조직별 구성원 정보: 정의·입력, 웹·API 차단과 예외."""

import pytest

from common.errors import ServiceError
from tasks.models import ChangeLog

from .member_info import missing, rows, save, set_definition
from .models import OrgMembership
from .services import create_org

pytestmark = pytest.mark.django_db

PHONE = {"label": "연락처", "kind": "text", "required": True, "help": "", "choices": []}
NOTE = {"label": "메모", "kind": "long", "required": False}


def _m(org, user):
    return OrgMembership.objects.select_related("org").get(org=org, user=user)


def _fid(org, label):
    org.refresh_from_db()
    return next(f["id"] for f in org.member_fields["fields"] if f["label"] == label)


def test_definition_and_input(org, admin, member):
    with pytest.raises(ServiceError):
        set_definition(org, "required", [PHONE], member)  # 관리자만
    with pytest.raises(ServiceError):
        set_definition(org, "required", [{"label": "역할", "kind": "choice"}], admin)  # 선택지 없음
    set_definition(
        org,
        "required",
        [PHONE, {"label": "역할", "kind": "choice", "choices": ["가", "나"]}],
        admin,
    )
    log = ChangeLog.objects.get(target_type="org", target_id=org.pk, field="member_fields")
    assert "실명 필수" in log.new_value and "연락처 (필수)" in log.new_value
    pid, rid = _fid(org, "연락처"), _fid(org, "역할")
    m = _m(org, member)
    assert missing(m)
    with pytest.raises(ServiceError) as e:
        save(m, "", {pid: "010", rid: "다"})
    assert set(e.value.errors) == {"real_name", rid}
    save(m, "김팀원", {pid: "010", rid: "가"})
    assert not missing(_m(org, member))
    # 라벨을 바꿔도 값은 id로 남고, 지운 항목 값은 화면에 안 나온다
    org.refresh_from_db()
    fields = org.member_fields["fields"]
    set_definition(org, "required", [{**fields[0], "label": "전화"}], admin)
    assert [(r["label"], r["value"]) for r in rows(_m(org, member))] == [("전화", "010")]


def test_web_block_and_exceptions(client, org, admin, member):
    set_definition(org, "optional", [PHONE], admin)
    client.force_login(member)
    url = f"/orgs/{org.pk}/member-info"
    r = client.get("/today")
    assert r.status_code == 302 and r["Location"] == url
    r = client.get(f"/orgs/{org.pk}", headers={"HX-Request": "true"})
    assert r.status_code == 204 and r["HX-Redirect"] == url
    for path in (url, "/orgs", "/settings/profile"):
        r = client.get(path)
        assert r.status_code in (200, 302) and r.get("Location") != url
    # 다른 조직은 막히지 않는다
    other = create_org("다른 조직", "", member)
    assert client.get(f"/orgs/{other.pk}").status_code == 200
    # 입력하면 풀린다
    r = client.post(url, {f"v-{_fid(org, '연락처')}": "010"})
    assert r.status_code == 302 and client.get(f"/orgs/{org.pk}").status_code == 200


def test_admin_is_target_but_can_open_settings(client, org, admin):
    client.force_login(admin)
    r = client.post(
        f"/orgs/{org.pk}/member-fields",
        {
            "real_name": "required",
            "f0-label": "연락처",
            "f0-kind": "text",
            "f0-required": "on",
            "f0-order": "1",
        },
    )
    assert r.status_code == 302
    assert client.get(f"/orgs/{org.pk}/settings").status_code == 200
    assert client.get(f"/orgs/{org.pk}/teams")["Location"] == f"/orgs/{org.pk}/member-info"


def test_api_403_and_other_org(client, api, org, admin, member, project, task):
    assert api.get(f"/api/tasks/{task.pk}").status_code == 200
    set_definition(
        org, "required", [], admin
    )  # 필수를 새로 넣으면 기존 구성원도 다음 요청부터 막힌다
    for r in (
        api.get(f"/api/tasks/{task.pk}"),
        api.get(f"/api/orgs/{org.pk}/members"),
        api.get(f"/api/tasks?project={project.pk}"),
        api.post("/api/tasks", {"project_id": project.pk, "title": "새 일"}),
    ):
        assert r.status_code == 403
        body = r.json()
        assert body["error"] == "profile_required"
        assert body["url"].endswith(f"/orgs/{org.pk}/member-info") and body["url"] in body["detail"]
    assert api.get("/api/me").status_code == 200  # 조직을 정할 수 없는 요청은 그대로
    other = create_org("다른 조직", "", member)
    assert api.get(f"/api/orgs/{other.pk}").status_code == 200
    save(_m(org, member), "김팀원", {})
    assert api.get(f"/api/tasks/{task.pk}").status_code == 200


def test_optional_only_does_not_block(client, api, org, admin, member, task):
    set_definition(org, "optional", [NOTE], admin)
    client.force_login(member)
    assert client.get("/today").status_code == 200
    assert api.get(f"/api/tasks/{task.pk}").status_code == 200
