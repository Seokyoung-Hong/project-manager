"""IMPL-PLAN-11 D1: 문서(Doc) — 범위·트리·이전 버전·백링크·내보내기·md 가져오기·API."""

import io
import zipfile
from datetime import timedelta

import pytest
from django.utils import timezone

from accounts.models import User
from common.errors import ConflictError, ServiceError
from orgs.models import OrgMembership
from projects import docs as svc
from projects.models import Doc, DocRevision
from projects.services import set_visibility

pytestmark = pytest.mark.django_db

HEX = "0123456789abcdef0123456789abcdef"
HEX2 = "fedcba9876543210fedcba9876543210"


@pytest.fixture
def other(org):
    u = User.objects.create_user("other1", password="pw12345678", display_name="다른 멤버")
    OrgMembership.objects.create(org=org, user=u, role="member")
    return u


# ---------- 템플릿·범위·가시성 ----------


def test_create_org_seeds_two_templates(org):
    titles = set(Doc.objects.filter(org=org, is_template=True).values_list("title", flat=True))
    assert titles == {"회의록", "설계 문서"}  # 개발일지 템플릿은 없다


def test_template_body_is_copied(org, member):
    tpl = Doc.objects.get(org=org, is_template=True, title="설계 문서")
    d = svc.create_doc(org=org, actor=member, template=tpl)
    assert d.body_md.startswith("## 배경") and not d.is_template
    assert d in svc.search_docs(member, "")  # 템플릿은 목록에 섞이지 않는다
    assert tpl not in svc.search_docs(member, "")


def test_private_project_and_team_docs_hidden(org, admin, member, other, project, team):
    set_visibility(project, "teams", actor=admin)  # 담당 팀 없음 → 관리자만
    team.is_private = True
    team.save()
    pdoc = svc.create_doc(project=project, actor=admin, title="비공개 프로젝트")
    tdoc = svc.create_doc(org=org, team=team, actor=member, title="비공개 팀")
    odoc = svc.create_doc(org=org, actor=member, title="조직 공통")
    seen = set(svc.visible_docs(other))
    assert odoc in seen and pdoc not in seen and tdoc not in seen
    assert tdoc in set(svc.visible_docs(member))  # 팀원
    assert {pdoc, tdoc} <= set(svc.visible_docs(admin))  # 조직 관리자
    with pytest.raises(ServiceError):
        svc.update_doc(tdoc, "body_md", "x", actor=other, expected_version=tdoc.version)
    with pytest.raises(ServiceError):
        svc.create_doc(org=org, team=team, actor=other)


def test_outsider_sees_nothing(org, member, outsider):
    svc.create_doc(org=org, actor=member)
    assert not svc.visible_docs(outsider).exists()
    with pytest.raises(ServiceError):
        svc.create_doc(org=org, actor=outsider)


def test_draft_meeting_only_host_and_admin(org, admin, member, other):
    from notes.models import VoiceRecording

    d = svc.create_doc(org=org, actor=member, kind="meeting")
    assert d.created_on is not None and d.title == "제목 없는 회의록"
    Doc.objects.filter(pk=d.pk).update(status="draft")
    rec = VoiceRecording.objects.create(
        note=d, guild_id="g", voice_channel_id="v", started_by=member, host=other
    )
    # 초안은 지금 진행자와 조직 관리자만. 작성자라도 진행자를 넘겼으면 못 본다.
    assert svc.can_view_doc(other, d) and svc.can_view_doc(admin, d)
    assert not svc.can_view_doc(member, d)
    rec.host = member
    rec.save()
    assert svc.can_view_doc(member, d) and not svc.can_view_doc(other, d)


def test_scope_is_project_or_team_not_both(org, member, project, team):
    with pytest.raises(ServiceError):
        svc.create_doc(org=org, actor=member, project=project, team=team)


# ---------- 트리 ----------


def test_children_inherit_scope_and_move_rewrites(org, admin, member, project, team):
    root = svc.create_doc(project=project, actor=member, title="뿌리")
    child = svc.create_doc(actor=member, parent=root, title="하위", team=team)
    grand = svc.create_doc(actor=member, parent=child, title="손자")
    assert child.project == project and child.team is None and grand.project == project
    svc.move_doc(root, actor=member, team=team)
    grand.refresh_from_db()
    assert grand.team == team and grand.project is None
    with pytest.raises(ServiceError):  # 하위는 범위를 직접 못 바꾼다
        svc.move_doc(child, actor=member, project=project)


def test_move_rejects_cycle_depth_and_meeting(org, member):
    chain = [svc.create_doc(org=org, actor=member, title="1")]
    for n in range(2, 7):
        chain.append(svc.create_doc(actor=member, parent=chain[-1], title=str(n)))
    with pytest.raises(ServiceError):  # 7단계
        svc.create_doc(actor=member, parent=chain[-1])
    with pytest.raises(ServiceError):  # 순환
        svc.move_doc(chain[0], actor=member, parent=chain[2])
    lone = svc.create_doc(org=org, actor=member)
    sub = svc.create_doc(actor=member, parent=lone)
    with pytest.raises(ServiceError):  # 2단계짜리를 5단계 아래 → 7
        svc.move_doc(lone, actor=member, parent=chain[4])
    svc.move_doc(sub, actor=member, parent=None)
    sub.refresh_from_db()
    assert sub.parent is None
    meeting = svc.create_doc(org=org, actor=member, kind="meeting")
    with pytest.raises(ServiceError):
        svc.move_doc(meeting, actor=member, parent=lone)
    with pytest.raises(ServiceError):
        svc.create_doc(actor=member, kind="meeting", parent=lone)


def test_delete_parent_takes_children_and_logs(org, admin, member):
    from tasks.models import ChangeLog

    root = svc.create_doc(org=org, actor=member, title="지울 것")
    svc.create_doc(actor=member, parent=root)
    assert svc.delete_doc(root, admin) == 1
    assert not Doc.objects.filter(org=org, is_template=False).exists()
    assert ChangeLog.objects.filter(field="doc_deleted", note="지울 것").exists()


# ---------- 이전 버전·되돌리기 ----------


def test_revisions_bundle_cap_and_revert(org, admin, member):
    d = svc.create_doc(org=org, actor=member, body_md="처음")
    d = svc.update_doc(d, "body_md", "둘", actor=member, expected_version=d.version)
    d = svc.update_doc(d, "body_md", "셋", actor=member, expected_version=d.version)
    # 같은 사람·10분 안 → 처음(v1) + 묶음 1개(v3)
    assert list(d.revisions.values_list("version", "body_md")) == [(3, "셋"), (1, "처음")]
    d = svc.update_doc(d, "body_md", "넷", actor=admin, expected_version=d.version)
    assert d.revisions.count() == 3  # 다른 사람은 새 행

    first = d.revisions.get(version=1)
    with pytest.raises(ConflictError):
        svc.revert_doc(d, first, actor=member, expected_version=1)
    d = svc.revert_doc(d, first, actor=member, expected_version=d.version)
    assert d.body_md == "처음" and d.version == 5
    assert d.revisions.first().version == 5 and d.revisions.filter(version=4).exists()

    DocRevision.objects.filter(doc=d).update(saved_at=timezone.now() - timedelta(hours=1))
    for i in range(60):
        DocRevision.objects.create(
            doc=d,
            version=100 + i,
            title="t",
            body_md=str(i),
            saved_by=admin,
            saved_at=timezone.now(),
        )
    d = svc.update_doc(d, "body_md", "끝", actor=member, expected_version=d.version)
    assert d.revisions.count() == svc.MAX_REVISIONS


def test_revert_rejects_other_docs_revision(org, member):
    a = svc.create_doc(org=org, actor=member)
    b = svc.create_doc(org=org, actor=member)
    with pytest.raises(ServiceError):
        svc.revert_doc(a, b.revisions.first(), actor=member, expected_version=a.version)


# ---------- 백링크·연결 ----------


def test_backlinks_respect_visibility_and_exact_id(org, admin, member, other, project, task):
    target = svc.create_doc(org=org, actor=member, title="대상")
    near = svc.create_doc(org=org, actor=member, body_md=f"[x](/docs/{target.pk}0)")  # 다른 id
    src = svc.create_doc(org=org, actor=member, body_md=f"참고: [대상](/docs/{target.pk})")
    hidden = svc.create_doc(project=project, actor=admin, body_md=f"/docs/{target.pk}")
    set_visibility(project, "teams", actor=admin)
    task.description = f"문서 {svc.doc_url(target)}"
    task.save()
    got = svc.backlinks(target, other)
    assert got["docs"] == [src] and near not in got["docs"] and hidden not in got["docs"]
    assert got["tasks"] == []  # 태스크도 비공개 프로젝트 소속
    assert hidden in svc.backlinks(target, admin)["docs"]
    assert task in svc.backlinks(target, admin)["tasks"]


def test_org_doc_links_any_task_in_org(org, member, task):
    d = svc.create_doc(org=org, actor=member)
    svc.link_task(d, task, member)
    assert list(task.docs.all()) == [d]


# ---------- 내보내기·가져오기 ----------


def test_export_zip_keeps_tree_and_hides_private(org, admin, member, other, project):
    root = svc.create_doc(org=org, actor=member, title="안내", body_md="뿌리")
    svc.create_doc(actor=member, parent=root, title="하위/문서", body_md="자식")
    svc.create_doc(project=project, actor=admin, title="비밀", body_md="x")
    set_visibility(project, "teams", actor=admin)
    names = set(zipfile.ZipFile(io.BytesIO(svc.export_zip(org, other))).namelist())
    assert names == {"안내.md", "안내/하위_문서.md"}
    name, data = svc.export_md(root)
    assert name == "안내.md" and data == "뿌리".encode()


def test_export_then_import_round_trip(org, member):
    root = svc.create_doc(org=org, actor=member, title="가이드", body_md="본문\n")
    svc.create_doc(actor=member, parent=root, title="설치", body_md="설치 방법\n")
    raw = svc.export_zip(org, member)
    Doc.objects.filter(org=org, is_template=False).delete()
    out = svc.import_md(org=org, actor=member, files=[("docs.zip", raw)])
    got = {d.title: d for d in out["created"]}
    assert set(got) == {"가이드", "설치"} and got["설치"].parent == got["가이드"]
    assert got["가이드"].body_md == "본문\n" and got["가이드"].origin == "import"


def _notion_zip():
    buf = io.BytesIO()
    with zipfile.ZipFile(buf, "w") as zf:
        zf.writestr(
            f"회의 정리 {HEX}.md",
            "# 회의 정리\n\n상태: 진행 중\n날짜: October 5, 2026 → October 6, 2026\n\n"
            f"[하위](%ED%9A%8C%EC%9D%98%20%EC%A0%95%EB%A6%AC%20{HEX}/%EC%84%B8%EB%B6%80%20{HEX2}.md)"
            " · [밖](다른%20페이지%20aaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaa.md)"
            f" · ![그림](%ED%9A%8C%EC%9D%98%20%EC%A0%95%EB%A6%AC%20{HEX}/image.png)"
            " · [웹](https://example.com)\n",
        )
        zf.writestr(f"회의 정리 {HEX}/세부 {HEX2}.md", "# 세부 사항\n\n내용\n")
    return buf.getvalue()


def test_import_cleans_notion_export(org, member, project):
    out = svc.import_md(
        org=org, actor=member, files=[("export.zip", _notion_zip())], project=project
    )
    top, sub = sorted(out["created"], key=lambda d: d.pk)
    assert top.title == "회의 정리" and sub.title == "세부 사항"  # id 해시 제거, 첫 # 줄이 제목
    assert sub.parent == top and sub.project == project
    assert "- **상태**: 진행 중" in top.body_md  # 속성 줄은 목록으로
    assert f"[하위](/docs/{sub.pk})" in top.body_md  # 같은 묶음 → 유달리 문서 링크
    assert "[밖]" not in top.body_md and " 밖 " in top.body_md  # 묶음 밖 → 텍스트
    assert "이미지 — 첨부로 다시 올려 주세요" in top.body_md and out["images"] == 1
    assert "[웹](https://example.com)" in top.body_md
    assert top.revisions.first().body_md == top.body_md

    again = svc.import_md(org=org, actor=member, files=[("export.zip", _notion_zip())])
    assert again["created"] == [] and len(again["skipped"]) == 2  # 같은 것을 다시 올리면 건너뛴다


def test_import_plain_md_files_and_limits(org, member):
    out = svc.import_md(
        org=org, actor=member, files=[("README.md", b"# Hello\nbody"), ("notes.md", b"plain")]
    )
    assert sorted(d.title for d in out["created"]) == ["Hello", "notes"]
    again = svc.import_md(org=org, actor=member, files=[("notes.md", b"plain")])
    assert again["skipped"] == ["notes"]
    with pytest.raises(ServiceError):
        svc.import_md(org=org, actor=member, files=[("a.txt", b"x")])
    with pytest.raises(ServiceError):
        svc.import_md(org=org, actor=member, files=[("a.zip", b"not zip")])


# ---------- API ----------


def test_api_scopes_tree_revisions_and_conflict(api, org, member, team):
    r = api.post("/api/project-docs", {"org_id": org.pk, "title": "조직 문서"})
    assert r.status_code == 201, r.content
    root = r.json()
    assert root["org_id"] == org.pk and root["kind"] == "doc" and root["project_id"] is None
    r = api.post("/api/project-docs", {"parent_id": root["id"], "title": "하위"})
    child = r.json()
    assert child["parent_id"] == root["id"]
    items = api.get(f"/api/orgs/{org.pk}/docs").json()["items"]
    assert {d["id"] for d in items} == {root["id"], child["id"]}  # 템플릿은 빠진다
    tpls = api.get(f"/api/project-docs?template=true&kind=all&org={org.pk}").json()
    assert tpls["total"] == 2

    r = api.patch(f"/api/project-docs/{root['id']}", {"version": 1, "body_md": "새 본문"})
    assert r.status_code == 200 and r.json()["version"] == 2
    r = api.patch(f"/api/project-docs/{root['id']}", {"version": 1, "body_md": "늦음"})
    assert r.status_code == 409
    revs = api.get(f"/api/project-docs/{root['id']}/revisions").json()
    first = revs[-1]
    assert first["version"] == 1
    r = api.post(
        f"/api/project-docs/{root['id']}/revert", {"version": 2, "revision_id": first["id"]}
    )
    assert r.status_code == 200 and r.json()["body_md"] == ""

    r = api.post(f"/api/project-docs/{root['id']}/move", {"team_id": team.pk})
    assert r.status_code == 200 and r.json()["team_id"] == team.pk
    assert api.get(f"/api/project-docs/{child['id']}").json()["team_id"] == team.pk
    r = api.get(f"/api/project-docs/{root['id']}/backlinks")
    assert r.json() == {"docs": [], "tasks": []}


def test_api_export_import_and_404(api, client, org, member, outsider):
    from accounts.models import ApiToken

    d = api.post("/api/project-docs", {"org_id": org.pk, "title": "가이드"}).json()
    r = api.get(f"/api/project-docs/{d['id']}/export.md")
    assert r.status_code == 200 and "attachment" in r["Content-Disposition"]
    r = api.get(f"/api/orgs/{org.pk}/docs/export.zip")
    assert zipfile.ZipFile(io.BytesIO(r.content)).namelist() == ["가이드.md"]
    r = api.post(
        f"/api/orgs/{org.pk}/docs/import",
        {"files": [{"name": f"새 문서 {HEX}.md", "content": "# 새 문서\n본문"}]},
    )
    assert r.status_code == 201 and r.json()["created"][0]["title"] == "새 문서"

    _, raw = ApiToken.issue(outsider, "o", "write", for_ai=False)
    h = {"Authorization": f"Bearer {raw}"}
    assert client.get(f"/api/project-docs/{d['id']}", headers=h).status_code == 404
    assert client.get(f"/api/orgs/{org.pk}/docs", headers=h).status_code == 404


def test_api_ai_cannot_delete(client, org, member):
    from accounts.models import ApiToken

    d = svc.create_doc(org=org, actor=member)
    _, raw = ApiToken.issue(member, "ai", "write")  # AI용 토큰(기본)
    r = client.delete(f"/api/project-docs/{d.pk}", headers={"Authorization": f"Bearer {raw}"})
    assert r.status_code == 403
    _, raw = ApiToken.issue(member, "p", "write", for_ai=False)
    r = client.delete(f"/api/project-docs/{d.pk}", headers={"Authorization": f"Bearer {raw}"})
    assert r.status_code == 200 and not Doc.objects.filter(pk=d.pk).exists()


# ---------- 마이그레이션(기존 ProjectDoc 보존) ----------


@pytest.mark.django_db(transaction=True)
def test_migration_0012_keeps_project_docs(pg_flushable):
    from django.db import connection
    from django.db.migrations.executor import MigrationExecutor

    before = [("projects", "0011_milestone_gh_number")]
    after = [("projects", "0015_doc_seed")]
    ex = MigrationExecutor(connection)
    ex.migrate(before)
    old = ex.loader.project_state(before).apps
    # 다른 앱 표는 최신 상태 그대로라 지금 모델로 만든다. 옛 모델은 ProjectDoc만.
    from orgs.models import Organization
    from projects.models import Project

    user = User.objects.create_user("m0", password="pw12345678", display_name="m0")
    o = Organization.objects.create(name="옛 조직", created_by=user)
    p = Project.objects.create(org=o, name="P", created_by=user)
    d = old.get_model("projects", "ProjectDoc").objects.create(
        project_id=p.pk, title="옛 문서", body_md="옛 본문", version=3, created_by_id=user.pk
    )
    try:
        ex = MigrationExecutor(connection)
        ex.migrate(after)
        new = ex.loader.project_state(after).apps
        Doc = new.get_model("projects", "Doc")
        doc = Doc.objects.get(pk=d.pk)
        assert (doc.org_id, doc.project_id, doc.title, doc.version) == (o.pk, p.pk, "옛 문서", 3)
        rev = new.get_model("projects", "DocRevision").objects.get(doc_id=d.pk)
        assert (rev.version, rev.body_md) == (3, "옛 본문")
        assert Doc.objects.filter(org_id=o.pk, is_template=True).count() == 2
    finally:
        ex = MigrationExecutor(connection)
        ex.migrate(ex.loader.graph.leaf_nodes())
