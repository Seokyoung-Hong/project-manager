import json
from datetime import timedelta

import pytest

from accounts.models import User
from common.dates import today_kst
from common.errors import ConflictError, ServiceError
from orgs.models import OrgMembership
from orgs.services import create_org
from projects.docs import (
    create_doc,
    delete_doc,
    project_docs,
    update_doc,
    upload_doc,
)
from projects.services import (
    archive_project,
    create_dependency,
    create_milestone,
    create_project,
    delete_project,
    fetch_spec,
    is_owner,
    parse_spec,
    project_stats,
    restore_project,
    roadmap,
    set_api_spec,
    set_governance_extra,
    set_project_settings,
    spec_view,
    update_project,
)
from reports.services import org_status
from tasks.models import ChangeLog, Task
from tasks.services import create_task, transition

pytestmark = pytest.mark.django_db


def test_project_without_owner_allowed(org, admin):
    p = create_project(org=org, name="기타", actor=admin)
    assert p.owners.count() == 0
    names = [row["name"] for row in org_status(org)["projects_without_owner"]]
    assert "기타" in names


def test_owner_must_be_member(org, admin, outsider):
    with pytest.raises(ServiceError) as e:
        create_project(org=org, name="외부", actor=admin, owners=[outsider])
    assert "owners" in e.value.errors


def test_owners_many_and_logged(org, admin, member):
    p = create_project(org=org, name="여럿", actor=admin, owners=[admin, member])
    assert p.owners.count() == 2
    p = update_project(p, {"owners": [member]}, actor=admin, expected_version=1)
    assert [u.pk for u in p.owners.all()] == [member.pk]
    assert (
        ChangeLog.objects.filter(target_type="project", target_id=p.pk, field="owners").count() == 1
    )
    assert p.version == 2


def test_duplicate_name_in_org_rejected(org, admin, project):
    with pytest.raises(ServiceError) as e:
        create_project(org=org, name=project.name, actor=admin)
    assert "name" in e.value.errors


def test_invalid_status_rejected(org, admin):
    with pytest.raises(ServiceError) as e:
        create_project(org=org, name="상태오류", actor=admin, status="closed")
    assert "status" in e.value.errors


def test_archive_blocked_by_open_tasks(project, admin, task):
    with pytest.raises(ServiceError) as e:
        archive_project(project, actor=admin)
    assert task.number in e.value.errors["tasks"]


def test_archive_and_restore(project, admin, member, task):
    transition(task, "done", actor=member, source="web", expected_version=task.version)
    p = archive_project(project, actor=admin)
    assert p.is_archived
    assert (
        ChangeLog.objects.filter(target_type="project", target_id=p.pk, field="is_archived").count()
        == 1
    )
    p = restore_project(p, actor=admin)
    assert not p.is_archived


def test_delete_project_requires_archived_and_admin(project, admin, member):
    with pytest.raises(ServiceError) as e:
        delete_project(project, actor=admin)
    assert "project" in e.value.errors  # 아직 보관하지 않았다
    archive_project(project, actor=admin)
    with pytest.raises(ServiceError):
        delete_project(project, actor=member)  # 일반 멤버는 막힌다
    pid, org, name = project.pk, project.org, project.name
    delete_project(project, actor=admin)
    from projects.models import Project

    assert not Project.objects.filter(pk=pid).exists()
    log = ChangeLog.objects.get(target_type="org", target_id=org.pk, field="delete")
    assert name in log.new_value and str(pid) in log.new_value


def test_delete_project_removes_tasks(project, admin, member):
    t = create_task(
        project=project, title="지워질 태스크", actor=member, source="web", due_date=today_kst()
    )
    t = transition(t, "done", actor=member, source="web", expected_version=t.version)
    archive_project(project, actor=admin)
    delete_project(project, actor=admin)
    assert not Task.objects.filter(pk=t.pk).exists()


def test_delete_project_ai_delete_default_deny_then_allow(project, admin):
    archive_project(project, actor=admin)
    with pytest.raises(ServiceError):
        delete_project(project, actor=admin, source="mcp")  # 기본값(deny)
    # archive_project가 project.refresh_from_db()로 project.org 캐시를 새로 채워 뒀으므로
    # 그 인스턴스에 바로 써야 다음 호출이 최신 설정을 본다.
    _set_settings(project.org, **{"ai.delete": "allow"})
    delete_project(project, actor=admin, source="mcp")
    from projects.models import Project

    assert not Project.objects.filter(pk=project.pk).exists()


def test_update_project_conflict(project, admin):
    update_project(project, {"purpose": "a"}, actor=admin, expected_version=1)
    with pytest.raises(ConflictError):
        update_project(project, {"purpose": "b"}, actor=admin, expected_version=1)


def test_member_cannot_archive(project, member):
    with pytest.raises(ServiceError):
        archive_project(project, actor=member)


def test_project_stats_total_excludes_cancelled(project, member):
    due = today_kst() + timedelta(days=1)
    t1 = create_task(project=project, title="a", actor=member, source="web", due_date=due)
    create_task(project=project, title="b", actor=member, source="web", due_date=due)
    t3 = create_task(project=project, title="c", actor=member, source="web", due_date=due)
    transition(t1, "done", actor=member, source="web", expected_version=t1.version)
    transition(t3, "cancelled", actor=member, source="web", expected_version=t3.version)
    st = project_stats(project)
    assert st["total"] == 2
    assert st["done"] == 1
    assert st["open"] == 1


def test_project_name_and_purpose_truncated_to_column_length(org, admin):
    """name varchar(100) / purpose varchar(200). 자르지 않으면 Postgres에서 DataError."""
    p = create_project(org=org, name="N" * 150, purpose="P" * 300, actor=admin)
    assert len(p.name) == 100
    assert len(p.purpose) == 200
    p = update_project(
        p, {"name": "M" * 150, "purpose": "Q" * 300}, actor=admin, expected_version=p.version
    )
    assert len(p.name) == 100
    assert len(p.purpose) == 200


def test_duplicate_check_uses_truncated_name(org, admin):
    """중복 검사와 저장이 같은 값을 써야 한다. 앞 100자가 같은 두 이름이 unique 제약을 때리면 500이 된다."""
    create_project(org=org, name="B" * 100, actor=admin)
    with pytest.raises(ServiceError) as e:
        create_project(org=org, name="B" * 150, actor=admin)
    assert "name" in e.value.errors


def test_removed_member_does_not_freeze_their_projects(org, admin, member, outsider):
    """관리자로 지정된 멤버를 조직에서 제거해도 그 프로젝트의 이름·상태는 고칠 수 있어야 한다."""
    from orgs.models import OrgMembership
    from orgs.services import remove_member

    p = create_project(org=org, name="백엔드", actor=admin, owners=[admin, member])
    remove_member(OrgMembership.objects.get(org=org, user=member), admin)

    p = update_project(p, {"status": "active"}, actor=admin, expected_version=p.version)
    assert p.status == "active"
    assert {u.pk for u in p.owners.all()} == {admin.pk, member.pk}  # 명단은 그대로

    with pytest.raises(ServiceError):  # 새로 넣는 사람은 여전히 조직의 활성 멤버여야 한다
        update_project(p, {"owners": [admin, outsider]}, actor=admin, expected_version=p.version)
    p = update_project(p, {"owners": [admin]}, actor=admin, expected_version=p.version)
    assert [u.pk for u in p.owners.all()] == [admin.pk]


# ---------- 로드맵: 마일스톤 · 프로젝트 의존성 ----------


def test_milestone_validation(project, admin):
    with pytest.raises(ServiceError) as e:
        create_milestone(project=project, name="", target_date=None, actor=admin)
    assert "name" in e.value.errors
    assert "target_date" in e.value.errors

    with pytest.raises(ServiceError) as e:
        create_milestone(
            project=project,
            name="alpha",
            target_date=today_kst(),
            start_date=today_kst() + timedelta(days=1),
            actor=admin,
        )
    assert "start_date" in e.value.errors


def test_roadmap_bar_clipping(project, admin):
    start = today_kst().replace(day=1)
    create_milestone(
        project=project,
        name="걸침",
        start_date=start - timedelta(days=10),
        target_date=start + timedelta(days=5),
        actor=admin,
    )
    data = roadmap(project.org, today=today_kst())
    row = data["rows"][0]
    assert row["left"] == 0
    assert 0 <= row["left"] + row["width"] <= 100


def test_roadmap_hides_out_of_window(project, admin):
    start = today_kst().replace(day=1)
    create_milestone(
        project=project, name="지난달", target_date=start - timedelta(days=1), actor=admin
    )
    data = roadmap(project.org, today=today_kst())
    assert data["hidden"] == 1
    assert data["rows"] == []


def test_roadmap_progress_from_project_stats(project, admin, member):
    t1 = create_task(project=project, title="a", actor=member, source="web", due_date=today_kst())
    t2 = create_task(project=project, title="b", actor=member, source="web", due_date=today_kst())
    transition(t1, "done", actor=member, source="web", expected_version=t1.version)
    create_milestone(
        project=project, name="진행", target_date=today_kst() + timedelta(days=5), actor=admin
    )
    data = roadmap(project.org, today=today_kst())
    st = project_stats(project)
    assert data["rows"][0]["pct"] == round(st["done"] / st["total"] * 100)
    assert t2.status == "todo"  # 완료가 아닌 태스크도 total에는 잡힌다


def test_dependency_same_org_and_not_self(org, admin, project):
    other_org = create_org("다른조직", "", admin)
    other_project = create_project(org=other_org, name="다른", actor=admin)
    with pytest.raises(ServiceError) as e:
        create_dependency(from_project=project, to_project=other_project, actor=admin)
    assert "to_project" in e.value.errors

    with pytest.raises(ServiceError) as e:
        create_dependency(from_project=project, to_project=project, actor=admin)
    assert "to_project" in e.value.errors


def test_dependency_duplicate_rejected(org, admin, project):
    p2 = create_project(org=org, name="두번째", actor=admin)
    create_dependency(from_project=project, to_project=p2, actor=admin)
    with pytest.raises(ServiceError) as e:
        create_dependency(from_project=project, to_project=p2, actor=admin)
    assert "to_project" in e.value.errors


# ---------- 설정·권한 (IMPL-PLAN-4 §3.1·§4.2) ----------


def _plain_member(org, name="plain"):
    """조직 멤버지만 어떤 프로젝트의 관리자도 아닌 사람."""
    u = User.objects.create_user(name, password="pw12345678", display_name="일반멤버")
    OrgMembership.objects.create(org=org, user=u, role="member")
    return u


def _set_settings(org, **kv):
    org.settings = kv
    org.save(update_fields=["settings"])


def test_is_owner(project, admin, member):
    assert is_owner(admin, project)
    assert not is_owner(member, project)


@pytest.mark.parametrize(
    "key, act",
    [
        (
            "project.edit_by",
            lambda p, a: update_project(p, {"purpose": "x"}, actor=a, expected_version=p.version),
        ),
        (
            "project.status_by",
            lambda p, a: update_project(p, {"status": "done"}, actor=a, expected_version=p.version),
        ),
        ("project.archive_by", lambda p, a: archive_project(p, actor=a)),
        (
            "project.roadmap_by",
            lambda p, a: create_milestone(project=p, name="m", target_date=today_kst(), actor=a),
        ),
    ],
)
def test_require_level_three_tiers(org, admin, project, key, act):
    """member|owner|admin 세 등급이 대표 강제 지점 4곳에서 그대로 먹혀야 한다."""
    plain = _plain_member(org, f"plain-{key}")
    owner = _plain_member(org, f"owner-{key}")
    project.owners.set([owner])

    _set_settings(org, **{key: "member"})
    act(project, plain)  # 멤버 누구나 통과
    project.refresh_from_db()

    _set_settings(org, **{key: "owner"})
    with pytest.raises(ServiceError):
        act(project, plain)
    act(project, owner)  # 프로젝트 관리자는 통과
    project.refresh_from_db()

    _set_settings(org, **{key: "admin"})
    with pytest.raises(ServiceError):
        act(project, owner)
    act(project, admin)  # 조직 관리자는 언제나 통과


def test_settings_by_admin_blocks_project_owner(org, admin, member, project):
    project.owners.set([member])
    _set_settings(org, **{"project.settings_by": "admin"})
    with pytest.raises(ServiceError):
        set_project_settings(project, {"task.priority_cap": 3}, actor=member)
    set_project_settings(project, {"task.priority_cap": 3}, actor=admin)
    project.refresh_from_db()
    assert project.settings.get("task.priority_cap") == 3


def test_settings_rejects_locked_key(org, admin, project):
    _set_settings(org, _locked=["task.priority_cap"])
    with pytest.raises(ServiceError) as e:
        set_project_settings(project, {"task.priority_cap": 3}, actor=admin)
    assert "task.priority_cap" in e.value.errors


def test_settings_logs_changes(org, admin, project):
    set_project_settings(project, {"task.priority_cap": 4}, actor=admin)
    assert (
        ChangeLog.objects.filter(
            target_type="project", target_id=project.pk, field="task.priority_cap"
        ).count()
        == 1
    )


def test_governance_extra_permission_and_ceiling(org, admin, member, project):
    project.owners.set([member])
    p = set_governance_extra(project, "짧은 문단", actor=member)
    assert p.governance_extra == "짧은 문단"
    with pytest.raises(ServiceError):
        set_governance_extra(project, "가" * 5001, actor=member)
    plain = _plain_member(org)
    with pytest.raises(ServiceError):
        set_governance_extra(project, "x", actor=plain)


def test_owner_required_blocks_create_and_reduce_but_not_existing(org, admin):
    _set_settings(org, **{"project.owner_required": True})
    with pytest.raises(ServiceError) as e:
        create_project(org=org, name="빈관리자", actor=admin)
    assert "owners" in e.value.errors

    p = create_project(org=org, name="관리자있음", actor=admin, owners=[admin])
    with pytest.raises(ServiceError) as e:
        update_project(p, {"owners": []}, actor=admin, expected_version=p.version)
    assert "owners" in e.value.errors

    # 이미 관리자가 0명인 기존 프로젝트는 그대로 둔다 — owners를 건드리지 않는 수정은 통과한다
    _set_settings(org)
    p0 = create_project(org=org, name="관리자없음", actor=admin)
    _set_settings(org, **{"project.owner_required": True})
    p0 = update_project(
        p0, {"purpose": "여전히 고칠 수 있다"}, actor=admin, expected_version=p0.version
    )
    assert p0.purpose == "여전히 고칠 수 있다"


# ---- V2-06: API 문서 ----

SAMPLE_SPEC = {
    "openapi": "3.0.3",
    "info": {"title": "학식 API", "version": "1.0.0", "description": "설명"},
    "servers": [{"url": "https://api.example.com"}],
    "tags": [{"name": "tasks", "description": "태스크"}],
    "paths": {
        "/tasks": {
            "get": {
                "tags": ["tasks"],
                "summary": "목록",
                "parameters": [
                    {
                        "name": "limit",
                        "in": "query",
                        "required": False,
                        "schema": {"type": "integer", "default": 50},
                    }
                ],
                "responses": {"200": {"description": "ok"}},
            },
            "post": {
                "tags": ["tasks"],
                "summary": "생성",
                "security": [{"bearer": []}],
                "requestBody": {"content": {"application/json": {"example": {"title": "a"}}}},
                "responses": {"201": {"description": "created"}, "400": {"description": "bad"}},
            },
        }
    },
}


def test_spec_rejects_without_paths():
    with pytest.raises(ServiceError) as e:
        parse_spec(json.dumps({"info": {}}).encode(), source="x")
    assert "spec" in e.value.errors


def test_spec_rejects_non_json():
    with pytest.raises(ServiceError) as e:
        parse_spec(b"not json", source="x")
    assert "spec" in e.value.errors


def test_spec_rejects_bad_scheme():
    with pytest.raises(ServiceError) as e:
        fetch_spec("file:///etc/passwd")
    assert "spec" in e.value.errors
    with pytest.raises(ServiceError):
        fetch_spec("ftp://example.com/openapi.json")


@pytest.mark.parametrize(
    "url",
    [
        "http://127.0.0.1:8000/api/openapi.json",  # 이 서버 자신
        "http://localhost:8080/",
        "http://169.254.169.254/latest/meta-data/",  # 클라우드 메타데이터
        "http://10.0.0.5/openapi.json",
        "http://192.168.1.1/openapi.json",
        "http://[::1]:8000/openapi.json",
    ],
)
def test_spec_rejects_internal_addresses(url):
    """서버가 대신 받아 주는 요청이라 사내 주소로 가면 안 된다."""
    with pytest.raises(ServiceError) as e:
        fetch_spec(url)
    assert "spec" in e.value.errors


def test_spec_rejects_redirect_to_internal(monkeypatch):
    """공개 주소가 사내로 되돌리는 것도 막는다."""
    from projects.services import _SafeRedirect

    handler = _SafeRedirect()
    with pytest.raises(ServiceError):
        handler.redirect_request(None, None, 302, "Found", {}, "http://127.0.0.1:8000/x")


def test_spec_rejects_oversize():
    with pytest.raises(ServiceError) as e:
        parse_spec(b"x" * (5 * 1024 * 1024 + 1), source="x")
    assert "spec" in e.value.errors


def test_spec_saved_and_replaced(project, admin):
    obj = set_api_spec(project, SAMPLE_SPEC, source_url="a.json", actor=admin)
    assert obj.project_id == project.pk
    obj2 = set_api_spec(project, SAMPLE_SPEC, source_url="b.json", actor=admin)
    assert obj2.pk == obj.pk
    from projects.models import ApiSpec

    assert ApiSpec.objects.filter(project=project).count() == 1
    assert obj2.source_url == "b.json"


def test_spec_view_groups_by_tag():
    v = spec_view(SAMPLE_SPEC)
    assert v["title"] == "학식 API"
    assert v["version"] == "v1.0.0"
    assert v["count"] == 2
    assert [g["tag"] for g in v["groups"]] == ["tasks"]
    ops = {op["method"]: op for op in v["groups"][0]["ops"]}
    assert ops["POST"]["auth"] is True
    assert ops["POST"]["body"]["example"]
    assert ops["GET"]["params"][0]["name"] == "limit"


def test_spec_view_search_filters():
    v = spec_view(SAMPLE_SPEC, q="생성")
    assert v["count"] == 1
    assert v["groups"][0]["ops"][0]["method"] == "POST"
    v2 = spec_view(SAMPLE_SPEC, q="없는말")
    assert v2["count"] == 0


def test_spec_view_method_colors():
    v = spec_view(SAMPLE_SPEC)
    ops = {op["method"]: op for op in v["groups"][0]["ops"]}
    assert ops["GET"]["color"] == "#1F6F82"
    assert ops["POST"]["color"] == "#12793F"


def test_spec_view_handles_missing_fields():
    v = spec_view({"paths": {"/x": {"get": {}}}})
    assert v["title"] == "제목 없는 API"
    assert v["version"] == "버전 없음"
    assert v["server"] == "서버 정보 없음"
    assert v["count"] == 1


# ---------- 프로젝트 문서 (GitHub 없이도 남기는 기록) ----------


def test_doc_create_and_edit(project, member):
    d = create_doc(project=project, actor=member, title="설계 결정")
    assert d.version == 1 and d.project == project
    d = update_doc(d, "body_md", "# 배경\r\n한 줄", actor=member, expected_version=1)
    assert d.body_md == "# 배경\n한 줄"  # CRLF는 저장 시 정리한다
    assert d.version == 2


def test_doc_title_falls_back_when_blank(project, member):
    d = create_doc(project=project, actor=member, title="   ")
    assert d.title == "제목 없는 문서"
    d = update_doc(d, "title", "  ", actor=member, expected_version=d.version)
    assert d.title == "제목 없는 문서"


def test_doc_rejects_stale_version(project, member):
    d = create_doc(project=project, actor=member)
    update_doc(d, "body_md", "먼저", actor=member, expected_version=1)
    with pytest.raises(ConflictError):
        update_doc(d, "body_md", "나중", actor=member, expected_version=1)


def test_doc_rejects_unknown_field_and_outsider(project, member, outsider):
    d = create_doc(project=project, actor=member)
    with pytest.raises(ServiceError):
        update_doc(d, "project", 1, actor=member, expected_version=d.version)
    with pytest.raises(ServiceError):
        update_doc(d, "body_md", "x", actor=outsider, expected_version=d.version)
    with pytest.raises(ServiceError):
        create_doc(project=project, actor=outsider)


def test_doc_body_has_a_ceiling(project, member):
    d = create_doc(project=project, actor=member)
    with pytest.raises(ServiceError):
        update_doc(d, "body_md", "가" * 300_000, actor=member, expected_version=d.version)


def test_doc_upload_reads_markdown_only(project, member):
    d = upload_doc(project=project, actor=member, filename="README.md", raw=b"# hi")
    assert d.title == "README" and d.body_md == "# hi"
    with pytest.raises(ServiceError):
        upload_doc(project=project, actor=member, filename="a.txt", raw=b"x")
    with pytest.raises(ServiceError):
        upload_doc(project=project, actor=member, filename="a.md", raw=b"\xff\xfe")


def test_doc_delete_is_author_or_org_admin(project, member, admin, outsider):
    d = create_doc(project=project, actor=member)
    with pytest.raises(ServiceError):
        delete_doc(d, outsider)
    delete_doc(d, admin)  # 조직 관리자
    d2 = create_doc(project=project, actor=member)
    delete_doc(d2, member)  # 작성자 본인


def test_docs_keep_creation_order(project, member):
    first = create_doc(project=project, actor=member, title="개요")
    second = create_doc(project=project, actor=member, title="운영")
    update_doc(first, "body_md", "나중에 고쳐도", actor=member, expected_version=first.version)
    # 수정해도 목록이 뒤집히지 않아야 문서를 다시 찾을 수 있다
    assert [d.title for d in project_docs(project)] == [first.title, second.title]
    assert second.pk in [d.pk for d in project_docs(project)]


def test_doc_links_only_same_project_tasks(project, org, admin, member, task):
    from projects.docs import link_task, unlink_task
    from projects.services import create_project
    from tasks.services import create_task

    doc = create_doc(project=project, actor=member, title="설계")
    link_task(doc, task, member)
    assert list(doc.tasks.all()) == [task]
    assert list(task.docs.all()) == [doc]

    other_project = create_project(org=org, name="다른 프로젝트", actor=admin, owners=[admin])
    other_task = create_task(
        project=other_project, title="남의 일", actor=admin, source="web", no_due_reason="미정"
    )
    with pytest.raises(ServiceError):
        link_task(doc, other_task, member)

    unlink_task(doc, task, member)
    assert not doc.tasks.exists()


def test_doc_link_rejects_outsider(project, member, task, outsider):
    from projects.docs import link_task

    doc = create_doc(project=project, actor=member)
    with pytest.raises(ServiceError):
        link_task(doc, task, outsider)


def test_doc_records_who_edited_and_how(project, member, admin):
    """AI가 고친 문서를 사람이 알아볼 수 있어야 한다."""
    d = create_doc(project=project, actor=member, title="개요")
    assert d.updated_by == member and d.updated_source == "web"
    d = update_doc(d, "body_md", "AI가 고침", actor=admin, expected_version=d.version, source="mcp")
    assert d.updated_by == admin and d.updated_source == "mcp"
    assert d.created_by == member  # 만든 사람은 그대로


def test_doc_create_has_body_ceiling(project, member):
    with pytest.raises(ServiceError):
        create_doc(project=project, actor=member, body_md="가" * 300_000)


def test_archive_can_cancel_leftover_tasks(org, project, admin, member):
    """그만두기로 한 프로젝트에는 손대지 않은 태스크가 남는다. 그것 때문에 숨길 수 없으면
    보관이 쓸모없어진다 — 취소로 닫고 보관한다(지우지 않는다)."""
    from tasks.models import Task
    from tasks.services import create_task

    from .services import archive_project

    task = create_task(
        project=project,
        title="남은 일",
        actor=admin,
        source="web",
        assignee=member,
        no_due_reason="미정",
    )
    with pytest.raises(ServiceError) as e:
        archive_project(project, actor=admin)
    assert task.number in e.value.errors["tasks"]

    archive_project(project, actor=admin, cancel_open=True)
    project.refresh_from_db()
    task.refresh_from_db()
    assert project.is_archived
    assert task.status == "cancelled"
    assert Task.objects.filter(pk=task.pk).exists()  # 지우지 않았다


# ---------- 비개발 프로젝트(project.dev_tools) — IMPL-PLAN-7 F1 ----------


def _connect(project):
    from github.models import RepoConnection

    return RepoConnection.objects.create(
        project=project,
        url="https://github.com/o/r.git",
        full_name="o/r",
        created_by=project.created_by,
    )


def test_dev_tools_org_default_and_project_override(org, admin, project):
    assert project.dev_tools is True
    org.settings = {"project.dev_tools": False}
    org.save()
    project = type(project).objects.get(pk=project.pk)
    assert project.dev_tools is False
    # 조직이 끈 값을 프로젝트가 레지스트리 기본값(켬)으로 되돌릴 수 있다.
    set_project_settings(project, {"project.dev_tools": True}, actor=admin)
    project = type(project).objects.get(pk=project.pk)
    assert project.settings == {"project.dev_tools": True} and project.dev_tools is True
    # 조직 값과 같은 값은 남기지 않는다(조직 값을 따른다).
    set_project_settings(project, {"project.dev_tools": False}, actor=admin)
    project = type(project).objects.get(pk=project.pk)
    assert project.settings == {} and project.dev_tools is False


def test_dev_tools_forced_on_with_repo(org, admin, project):
    set_project_settings(project, {"project.dev_tools": False}, actor=admin)
    _connect(project)
    project = type(project).objects.get(pk=project.pk)
    assert project.dev_tools is True  # 설정은 끔이지만 저장소가 있으면 보인다
    with pytest.raises(ServiceError) as e:
        set_project_settings(project, {"project.dev_tools": False}, actor=admin)
    assert "project.dev_tools" in e.value.errors


def test_create_project_saves_dev_tools_only_when_differs(org, admin):
    p = create_project(org=org, name="홍보", actor=admin, dev_tools=False)
    assert p.settings == {"project.dev_tools": False} and p.dev_tools is False
    p = create_project(org=org, name="앱", actor=admin, dev_tools=True)
    assert p.settings == {}  # 조직 기본값과 같으면 남기지 않는다
    org.settings = {"project.dev_tools": False}
    org.save()
    p = create_project(org=org, name="서버", actor=admin, dev_tools=True)
    assert p.settings == {"project.dev_tools": True}
    p = create_project(org=org, name="디자인", actor=admin)
    assert p.settings == {} and p.dev_tools is False


def test_project_can_restore_registry_default_over_org(org, admin, project):
    """조직이 기본값이 아닌 값으로 바꾼 규칙을 프로젝트가 기본값으로 되돌릴 수 있다."""
    from orgs.settings import effective

    org.settings = {"task.review_required": True, "task.default_priority": 7}
    org.save()
    project = type(project).objects.get(pk=project.pk)
    set_project_settings(
        project, {"task.review_required": False, "task.default_priority": 5}, actor=admin
    )
    project = type(project).objects.get(pk=project.pk)
    assert effective("task.review_required", project=project) is False
    assert effective("task.default_priority", project=project) == 5
    # 이력도 "켬 → 끔"으로 남는다(없던 값의 표시는 조직 값).
    log = ChangeLog.objects.get(target_type="project", field="task.review_required")
    assert (log.old_value, log.new_value) == ("켬", "끔")
