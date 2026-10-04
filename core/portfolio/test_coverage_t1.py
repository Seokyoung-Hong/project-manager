"""포트폴리오(T1): 출처 조회·초안 서비스·API의 권한, 비공개 프로젝트 제외, 입력 검증."""

from datetime import date, timedelta

import pytest
from django.contrib.auth.models import AnonymousUser
from django.core.exceptions import ValidationError
from django.utils import timezone

from accounts.models import ApiToken, User
from common.errors import ConflictError, ServiceError
from orgs.models import OrgMembership
from orgs.services import create_org
from portfolio import drafts, sources
from portfolio.models import PortfolioDraft
from projects.models import Project
from tasks.models import TaskDecisionRecord

pytestmark = pytest.mark.django_db


def rec(task, user, **kw):
    """DB에 직접 심는다. 기본은 user가 본인 것으로 수집한 요구."""
    kw.setdefault("kind", "user_input")
    if kw["kind"] == "user_input":
        kw.setdefault("input_type", "requirement")
        kw.setdefault("evidence_basis", "explicit_reply")
        kw.setdefault("status", "captured")
        kw.setdefault("subject_user", user)
        if kw["status"] == "confirmed":
            kw.setdefault("confirmed_by", user)
            kw.setdefault("confirmed_at", timezone.now())
    else:
        kw.setdefault("status", "recorded")
    return TaskDecisionRecord.objects.create(
        task=task, summary=kw.pop("summary", "요지"), recorded_by=user, source="web", **kw
    )


def hide(project):
    """공개 범위를 담당 팀만으로 바꾼다. member는 담당 팀이 아니라 볼 수 없다."""
    Project.objects.filter(pk=project.pk).update(visibility="teams")


# ---------- sources ----------


def test_sources_only_own_user_inputs_plus_ai_context(task, member, admin):
    mine = rec(task, member, summary="내 요구")
    theirs = rec(task, admin, summary="남의 요구")
    ai = rec(task, admin, kind="ai_judgment", summary="AI 판단")
    out = sources.list_portfolio_sources(member)
    ids = {i["id"] for i in out["items"]}
    assert ids == {mine.pk, ai.pk} and theirs.pk not in ids
    roles = {i["id"]: i["portfolio_role"] for i in out["items"]}
    assert roles == {mine.pk: "user_decision", ai.pk: "context"}


def test_sources_confirmed_by_user_counts_but_other_statuses_do_not(task, member, admin):
    conf = rec(task, admin, status="confirmed", confirmed_by=member, summary="내가 확인")
    for st in ("proposed", "rejected", "superseded"):
        rec(task, member, status=st)
    rec(task, member, kind="ai_judgment", status="superseded")
    ids = [i["id"] for i in sources.list_portfolio_sources(member)["items"]]
    assert ids == [conf.pk]


def test_sources_never_expose_verbatim_text(task, member):
    rec(task, member, verbatim_text="원문 비밀 대화")
    item = sources.list_portfolio_sources(member)["items"][0]
    assert "verbatim_text" not in item and "원문" not in str(item)


def test_sources_exclude_private_project_and_other_orgs(task, project, member, admin):
    rec(task, member)
    assert sources.list_portfolio_sources(member)["total"] == 1
    hide(project)
    assert sources.list_portfolio_sources(member)["total"] == 0
    # 조직 관리자는 계속 본다
    rec(task, admin)
    assert sources.list_portfolio_sources(admin)["total"] == 1
    # 다른 조직 사용자에게는 새지 않는다
    other_org = create_org("다른 조직", "", User.objects.create_user("zed", password="pw12345678"))
    zed = other_org.memberships.first().user
    assert sources.list_portfolio_sources(zed)["total"] == 0


def test_sources_empty_for_anonymous_and_inactive_users(task, member):
    rec(task, member)
    assert sources.list_portfolio_sources(AnonymousUser())["total"] == 0
    User.objects.filter(pk=member.pk).update(is_active=False)
    member.refresh_from_db()
    assert sources.list_portfolio_sources(member)["total"] == 0


def test_sources_filters(task, project, member, org):
    a = rec(task, member, input_type="steer")
    b = rec(task, member, kind="ai_judgment")
    # 기간(포함 경계)
    d = timezone.localdate(a.created_at)
    f = sources.list_portfolio_sources
    assert f(member, from_date=d, to_date=d)["total"] == 2
    assert f(member, from_date=d + timedelta(days=1))["total"] == 0
    assert f(member, to_date=d - timedelta(days=1))["total"] == 0
    assert f(member, project_id=project.pk)["total"] == 2
    assert f(member, project_id=project.pk + 99)["total"] == 0
    assert f(member, org_id=org.pk + 99)["total"] == 0
    # input_type은 사용자 입력만 남긴다
    got = [i["id"] for i in f(member, input_type="steer")["items"]]
    assert got == [a.pk] and b.pk not in got


def test_sources_pagination_and_validation(task, member):
    ids = [rec(task, member, summary=f"요구 {i}").pk for i in range(3)]
    out = sources.list_portfolio_sources(member, limit=2, offset=1)
    assert [i["id"] for i in out["items"]] == ids[1:] and out["total"] == 3
    assert sources.list_portfolio_sources(member, limit=1000)["limit"] == sources.MAX_PAGE_SIZE
    assert sources.list_portfolio_sources(member, offset=10)["items"] == []
    for kw in ({"limit": 0}, {"offset": -1}, {"limit": "x"}, {"offset": None}):
        with pytest.raises(ValidationError):
            sources.list_portfolio_sources(member, **kw)


def test_get_allowed_records_order_dedupe_and_all_or_nothing(task, member, admin):
    a, b = rec(task, member), rec(task, member)
    foreign = rec(task, admin)
    assert [r.pk for r in sources.get_allowed_records(member, [b.pk, a.pk, b.pk])] == [b.pk, a.pk]
    assert sources.get_allowed_records(member, []) == []
    assert [r.pk for r in sources.get_allowed_records(member, [str(a.pk)])] == [a.pk]
    for bad in ([a.pk, foreign.pk], [a.pk, 999999], ["x"], None):
        with pytest.raises(ValidationError):
            sources.get_allowed_records(member, bad)


# ---------- drafts: create ----------


@pytest.fixture
def two(task, member):
    return rec(task, member, summary="첫째"), rec(task, member, summary="둘째")


def mkdraft(user, org, ids, **kw):
    kw.setdefault("title", "내 포트폴리오")
    kw.setdefault("body_md", "본문")
    return drafts.create_draft(user, org_id=org.pk, source_ids=ids, **kw)


def test_create_draft_snapshots_sources(org, member, two, task, project):
    d = mkdraft(member, org, [two[1].pk, two[0].pk, two[0].pk], title="  제목  ")
    assert d.title == "제목" and d.version == 1 and d.owner_id == member.pk
    assert d.sources.count() == 2 and d.stale_source_ids == []
    s = d.sources.get(decision_record=two[0])
    assert (s.record_summary, s.task_number, s.project_name) == (
        "첫째",
        task.number,
        project.name,
    )


def test_create_draft_requires_org_membership(org, outsider, member, two):
    with pytest.raises(ServiceError) as e:
        mkdraft(outsider, org, [two[0].pk])
    assert "org" in e.value.errors
    with pytest.raises(ServiceError):
        drafts.create_draft(member, org_id=999999, title="t", body_md="", source_ids=[two[0].pk])
    with pytest.raises(ServiceError):
        mkdraft(AnonymousUser(), org, [two[0].pk])
    assert not PortfolioDraft.objects.exists()


def test_create_draft_rejects_other_users_hidden_and_cross_org_sources(
    org, member, admin, two, task, project
):
    foreign = rec(task, admin)
    with pytest.raises(ServiceError) as e:
        mkdraft(member, org, [two[0].pk, foreign.pk])
    assert "source_ids" in e.value.errors
    hide(project)
    with pytest.raises(ServiceError):
        mkdraft(member, org, [two[0].pk])
    # 다른 조직 기록은 소속 조직이 달라 거부
    Project.objects.filter(pk=project.pk).update(visibility="org")
    org2 = create_org("둘째 조직", "", member)
    with pytest.raises(ServiceError) as e:
        mkdraft(member, org2, [two[0].pk])
    assert "같은 조직" in e.value.errors["source_ids"]


@pytest.mark.parametrize(
    "ids",
    [None, "1", b"1", [], ["a"], [0], [-3], list(range(1, 502))],
)
def test_create_draft_rejects_bad_source_ids(org, member, ids):
    with pytest.raises(ServiceError) as e:
        mkdraft(member, org, ids)
    assert "source_ids" in e.value.errors


@pytest.mark.parametrize(
    "kw,field",
    [
        ({"title": "   "}, "title"),
        ({"title": None}, "title"),
        ({"title": "x" * 201}, "title"),
        ({"body_md": None}, "body_md"),
        ({"body_md": "가" * (256 * 1024 // 3 + 1)}, "body_md"),
        ({"scope_json": []}, "scope_json"),
        ({"scope_json": {"a": float("nan")}}, "scope_json"),
        ({"scope_json": {"a": object()}}, "scope_json"),
        ({"scope_json": {"a": "x" * (16 * 1024)}}, "scope_json"),
        ({"prompt_version": "v" * 41}, "prompt_version"),
        ({"prompt_version": 3}, "prompt_version"),
    ],
)
def test_create_draft_validation(org, member, two, kw, field):
    with pytest.raises(ServiceError) as e:
        mkdraft(member, org, [two[0].pk], **kw)
    assert field in e.value.errors
    assert not PortfolioDraft.objects.exists()  # 실패하면 만들어지지 않는다


def test_create_draft_boundaries_and_newline_normalisation(org, member, two):
    d = mkdraft(member, org, [two[0].pk], title="x" * 200, body_md="a\r\nb\rc", scope_json=None)
    assert len(d.title) == 200 and d.body_md == "a\nb\nc" and d.scope_json == {}
    full = mkdraft(member, org, [two[0].pk], body_md="a" * drafts.MAX_BODY_BYTES)
    assert len(full.body_md) == drafts.MAX_BODY_BYTES


# ---------- drafts: read / stale / revocation ----------


def test_get_draft_is_owner_only(org, member, admin, two):
    d = mkdraft(member, org, [two[0].pk])
    assert drafts.get_draft(member, d.pk).pk == d.pk
    with pytest.raises(ServiceError):
        drafts.get_draft(admin, d.pk)  # 조직 관리자도 남의 개인 초안은 못 본다
    with pytest.raises(ServiceError):
        drafts.get_draft(member, 999999)


def test_get_draft_flags_changed_source_stale_but_keeps_snapshot(org, member, two):
    d = mkdraft(member, org, [two[0].pk, two[1].pk])
    TaskDecisionRecord.objects.filter(pk=two[0].pk).update(summary="바뀐 요지")
    got = drafts.get_draft(member, d.pk)
    assert got.stale_source_ids == [two[0].pk]
    assert {s.decision_record_id: s.is_stale for s in got.portfolio_sources} == {
        two[0].pk: True,
        two[1].pk: False,
    }
    assert got.sources.get(decision_record=two[0]).record_summary == "첫째"


def test_superseded_source_stays_readable_and_stale(org, member, two):
    d = mkdraft(member, org, [two[0].pk])
    TaskDecisionRecord.objects.filter(pk=two[0].pk).update(status="superseded")
    assert drafts.get_draft(member, d.pk).stale_source_ids == [two[0].pk]


@pytest.mark.parametrize("status", ["rejected", "proposed"])
def test_withdrawn_source_revokes_draft_access(org, member, two, status):
    d = mkdraft(member, org, [two[0].pk])
    TaskDecisionRecord.objects.filter(pk=two[0].pk).update(status=status)
    with pytest.raises(ServiceError) as e:
        drafts.get_draft(member, d.pk)
    assert "source_ids" in e.value.errors
    with pytest.raises(ServiceError):
        drafts.export_markdown(member, d.pk)
    with pytest.raises(ServiceError):
        drafts.update_draft(member, d.pk, version=1, title="새 제목")


def test_source_subject_change_revokes_access(org, member, admin, two):
    d = mkdraft(member, org, [two[0].pk])
    TaskDecisionRecord.objects.filter(pk=two[0].pk).update(subject_user=admin)
    with pytest.raises(ServiceError):
        drafts.get_draft(member, d.pk)


def test_ai_source_superseded_is_stale_not_revoked(org, member, task, admin):
    ai = rec(task, admin, kind="ai_judgment")
    d = mkdraft(member, org, [ai.pk])
    TaskDecisionRecord.objects.filter(pk=ai.pk).update(status="superseded")
    assert drafts.get_draft(member, d.pk).stale_source_ids == [ai.pk]


def test_project_made_private_hides_draft_sources(org, project, member, two):
    d = mkdraft(member, org, [two[0].pk])
    hide(project)
    with pytest.raises(ServiceError):
        drafts.get_draft(member, d.pk)
    assert drafts.list_drafts(member) == []


def test_draft_inaccessible_after_membership_removed(org, member, two):
    d = mkdraft(member, org, [two[0].pk])
    OrgMembership.objects.filter(org=org, user=member).delete()
    with pytest.raises(ServiceError) as e:
        drafts.get_draft(member, d.pk)
    assert "org" in e.value.errors
    with pytest.raises(ServiceError):
        drafts.update_draft(member, d.pk, version=1, title="x")
    assert drafts.list_drafts(member) == []


def test_inactive_owner_cannot_read_draft(org, member, two):
    d = mkdraft(member, org, [two[0].pk])
    User.objects.filter(pk=member.pk).update(is_active=False)
    member.refresh_from_db()
    with pytest.raises(ServiceError):
        drafts.get_draft(member, d.pk)
    assert drafts.list_drafts(member) == []


# ---------- drafts: list ----------


def test_list_drafts_metadata_limit_and_org_scope(org, member, outsider, two):
    d1 = mkdraft(member, org, [two[0].pk], title="하나")
    d2 = mkdraft(member, org, [two[0].pk, two[1].pk], title="둘")
    out = drafts.list_drafts(member)
    assert [x["id"] for x in out] == [d2.pk, d1.pk]
    assert out[0]["source_count"] == 2 and "body_md" not in out[0]
    assert [x["id"] for x in drafts.list_drafts(member, limit=1)] == [d2.pk]
    assert drafts.list_drafts(member, org_id=org.pk + 99) == []
    assert len(drafts.list_drafts(member, org_id=org.pk)) == 2
    assert drafts.list_drafts(outsider) == []
    assert drafts.list_drafts(AnonymousUser()) == []
    for bad in (0, 101, "x"):
        with pytest.raises(ServiceError) as e:
            drafts.list_drafts(member, limit=bad)
        assert "limit" in e.value.errors


def test_list_drafts_skips_revoked_but_keeps_others(org, member, two):
    keep = mkdraft(member, org, [two[1].pk], title="유지")
    mkdraft(member, org, [two[0].pk], title="폐기")
    TaskDecisionRecord.objects.filter(pk=two[0].pk).update(status="rejected")
    assert [x["id"] for x in drafts.list_drafts(member)] == [keep.pk]


# ---------- drafts: update ----------


def test_update_draft_increments_version_and_conflicts_on_stale(org, member, two):
    d = mkdraft(member, org, [two[0].pk])
    u = drafts.update_draft(member, d.pk, version=1, title="새 제목", body_md="새 본문")
    assert (u.version, u.title, u.body_md) == (2, "새 제목", "새 본문")
    with pytest.raises(ConflictError) as e:
        drafts.update_draft(member, d.pk, version=1, title="늦은 수정")
    assert e.value.latest.pk == d.pk
    d.refresh_from_db()
    assert d.title == "새 제목"


def test_update_draft_version_validation(org, member, two):
    d = mkdraft(member, org, [two[0].pk])
    for bad in ("x", None):
        with pytest.raises(ServiceError) as e:
            drafts.update_draft(member, d.pk, version=bad)
        assert "version" in e.value.errors
    assert drafts.update_draft(member, d.pk, version="1").version == 2


def test_update_draft_replaces_sources_and_validates(org, member, admin, two, task):
    d = mkdraft(member, org, [two[0].pk])
    u = drafts.update_draft(member, d.pk, version=1, source_ids=[two[1].pk])
    assert [s.decision_record_id for s in u.portfolio_sources] == [two[1].pk]
    assert u.sources.count() == 1 and u.body_md == "본문"  # 본문은 건드리지 않는다
    with pytest.raises(ServiceError):
        drafts.update_draft(member, d.pk, version=2, source_ids=[rec(task, admin).pk])
    with pytest.raises(ServiceError):
        drafts.update_draft(member, d.pk, version=2, source_ids=[])
    d.refresh_from_db()
    assert d.version == 2 and d.sources.count() == 1  # 실패는 아무것도 바꾸지 않는다


def test_update_draft_validation_does_not_bump_version(org, member, two):
    d = mkdraft(member, org, [two[0].pk])
    with pytest.raises(ServiceError):
        drafts.update_draft(member, d.pk, version=1, title=" ")
    with pytest.raises(ServiceError):
        drafts.update_draft(member, d.pk, version=1, body_md="가" * 100_000)
    d.refresh_from_db()
    assert d.version == 1


def test_update_draft_owner_only_and_not_found(org, member, admin, two):
    d = mkdraft(member, org, [two[0].pk])
    for user, pk in ((admin, d.pk), (member, 999999)):
        with pytest.raises(ServiceError):
            drafts.update_draft(user, pk, version=1, title="x")


def test_update_draft_flags_stale_without_rewriting_markdown(org, member, two):
    d = mkdraft(member, org, [two[0].pk], body_md="내가 쓴 글")
    TaskDecisionRecord.objects.filter(pk=two[0].pk).update(summary="바뀜")
    u = drafts.update_draft(member, d.pk, version=1, title="제목만")
    assert u.stale_source_ids == [two[0].pk] and u.body_md == "내가 쓴 글"


# ---------- export ----------


@pytest.mark.parametrize(
    "title,body,expected",
    [
        ("T", "본문", "# T\n\n본문"),
        ("T", "# T\n본문", "# T\n본문"),
        ("T", "", "# T\n"),
        ("T", "  \n ", "# T\n"),
        ("T", "# 다른 제목\n본문", "# T\n\n# 다른 제목\n본문"),
    ],
)
def test_export_markdown_heading_rules(org, member, two, title, body, expected):
    d = mkdraft(member, org, [two[0].pk], title=title, body_md=body)
    assert drafts.export_markdown(member, d.pk) == expected


# ---------- API ----------


def test_api_sources_list_and_validation(api, task, member, admin):
    rec(task, member, summary="내 요구")
    rec(task, admin, summary="남의 요구")
    r = api.get("/api/me/portfolio-sources")
    assert r.status_code == 200
    body = r.json()
    assert body["total"] == 1 and body["items"][0]["summary"] == "내 요구"
    assert "verbatim_text" not in body["items"][0]
    assert api.get("/api/me/portfolio-sources?limit=0").status_code == 400
    assert api.get("/api/me/portfolio-sources?offset=-1").status_code == 400
    assert api.get("/api/me/portfolio-sources?limit=101").json()["limit"] == 100
    assert api.get("/api/me/portfolio-sources?from_date=nope").status_code == 422
    d = date.today().isoformat()
    assert api.get(f"/api/me/portfolio-sources?from_date={d}&to_date={d}").json()["total"] == 1
    assert api.get("/api/me/portfolio-sources?input_type=steer").json()["total"] == 0


def test_api_requires_authentication(client, task):
    assert client.get("/api/me/portfolio-sources").status_code == 401
    assert client.get("/api/me/portfolio-drafts/1").status_code == 401


def test_api_draft_lifecycle(api, org, task, member):
    rid = rec(task, member).pk
    payload = {"org_id": org.pk, "title": "포트폴리오", "source_ids": [rid], "body_md": "본문"}
    c = api.post("/api/me/portfolio-drafts", payload)
    assert c.status_code == 201
    did = c.json()["id"]
    assert c.json()["sources"][0]["decision_record_id"] == rid
    assert api.get(f"/api/me/portfolio-drafts/{did}").json()["version"] == 1
    p = api.patch(f"/api/me/portfolio-drafts/{did}", {"version": 1, "title": "수정"})
    assert p.status_code == 200 and p.json()["version"] == 2
    md = api.get(f"/api/me/portfolio-drafts/{did}/markdown").json()
    assert md["markdown"].startswith("# 수정") and md["version"] == 2
    assert md["stale_source_ids"] == []


def test_api_patch_conflict_returns_409_with_latest(api, org, task, member):
    rid = rec(task, member).pk
    did = api.post(
        "/api/me/portfolio-drafts", {"org_id": org.pk, "title": "t", "source_ids": [rid]}
    ).json()["id"]
    api.patch(f"/api/me/portfolio-drafts/{did}", {"version": 1, "title": "둘째"})
    r = api.patch(f"/api/me/portfolio-drafts/{did}", {"version": 1, "title": "늦음"})
    assert r.status_code == 409 and r.json()["latest"]["title"] == "둘째"


def test_api_create_rejects_bad_payloads(api, org, task, member, admin):
    rid = rec(task, member).pk
    good = {"org_id": org.pk, "title": "t", "source_ids": [rid]}
    assert api.post("/api/me/portfolio-drafts", {**good, "messages": []}).status_code == 422
    assert api.post("/api/me/portfolio-drafts", {**good, "source_ids": []}).status_code == 422
    assert api.post("/api/me/portfolio-drafts", {**good, "title": ""}).status_code == 422
    assert api.post("/api/me/portfolio-drafts", {**good, "org_id": 0}).status_code == 422
    foreign = rec(task, admin).pk
    r = api.post("/api/me/portfolio-drafts", {**good, "source_ids": [foreign]})
    assert r.status_code == 400


def test_api_other_users_draft_is_404_everywhere(client, api, org, task, member, admin):
    rid = rec(task, member).pk
    did = api.post(
        "/api/me/portfolio-drafts", {"org_id": org.pk, "title": "t", "source_ids": [rid]}
    ).json()["id"]
    _, raw = ApiToken.issue(admin, "a", "write", for_ai=False)
    h = {"Authorization": f"Bearer {raw}"}
    base = f"/api/me/portfolio-drafts/{did}"
    assert client.get(base, headers=h).status_code == 404
    assert client.get(base + "/markdown", headers=h).status_code == 404
    patch = client.patch(
        base, {"version": 1, "title": "x"}, content_type="application/json", headers=h
    )
    assert patch.status_code == 400  # 존재 여부를 알리지 않는 서비스 오류
    assert api.get(base).status_code == 200


def test_api_read_token_cannot_create_draft(client, org, task, member, read_token):
    rid = rec(task, member).pk
    r = client.post(
        "/api/me/portfolio-drafts",
        {"org_id": org.pk, "title": "t", "source_ids": [rid]},
        content_type="application/json",
        headers={"Authorization": f"Bearer {read_token}"},
    )
    assert r.status_code == 403


def test_api_draft_becomes_404_when_project_hidden(api, org, project, task, member):
    rid = rec(task, member).pk
    did = api.post(
        "/api/me/portfolio-drafts", {"org_id": org.pk, "title": "t", "source_ids": [rid]}
    ).json()["id"]
    hide(project)
    assert api.get(f"/api/me/portfolio-drafts/{did}").status_code == 404
    assert api.get(f"/api/me/portfolio-drafts/{did}/markdown").status_code == 404
    assert api.get("/api/me/portfolio-sources").json()["total"] == 0
