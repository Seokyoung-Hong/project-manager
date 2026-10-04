"""결정 기록(T1): 서비스·API의 권한, 입력 검증, 멱등성, 대체 규칙."""

import uuid

import pytest

from accounts.models import ApiToken
from common.errors import ConflictError, ServiceError
from orgs.services import set_org_settings
from tasks.decision_services import (
    confirm_record,
    create_record,
    effective_records,
    list_records,
    reject_record,
)
from tasks.models import TaskDecisionRecord

pytestmark = pytest.mark.django_db


def mk(task, actor, **kw):
    kw.setdefault("source", "web")
    kw.setdefault("kind", "user_input")
    kw.setdefault("input_type", "requirement")
    kw.setdefault("evidence_basis", "explicit_reply")
    kw.setdefault("summary", "로그인은 학교 계정만 허용")
    return create_record(task, actor=actor, **kw)


def ai_judgment(task, actor, **kw):
    kw.update(kind="ai_judgment", input_type="", evidence_basis="")
    kw.setdefault("summary", "캐시를 쓰기로 판단")
    return mk(task, actor, **kw)


def err(exc):
    return exc.value.errors


# ---------- create_record ----------


def test_create_explicit_is_captured_and_inferred_is_proposed(task, member):
    a = mk(task, member)
    b = mk(task, member, evidence_basis="inferred", summary="추론한 요구")
    assert (a.status, a.subject_user_id, a.recorded_by_id) == ("captured", member.pk, member.pk)
    assert b.status == "proposed"


def test_create_ai_judgment_has_no_subject_and_is_recorded(task, member):
    r = ai_judgment(task, member)
    assert (r.status, r.subject_user_id, r.input_type, r.evidence_basis) == (
        "recorded",
        None,
        None,
        None,
    )


@pytest.mark.parametrize(
    "kw,field",
    [
        ({"kind": "other"}, "kind"),
        ({"input_type": "nope"}, "input_type"),
        ({"evidence_basis": "nope"}, "evidence_basis"),
        ({"status": "confirmed"}, "status"),
        ({"evidence_basis": "inferred", "status": "captured"}, "status"),
        ({"status": "proposed"}, "status"),  # 명시적 입력은 captured만
        ({"source": "cli"}, "source"),
        ({"summary": "   "}, "summary"),
        ({"summary": "x" * 801}, "summary"),
        ({"question_summary": "x" * 301}, "question_summary"),
        ({"reason_summary": "x" * 501}, "reason_summary"),
        ({"alternatives": "하나"}, "alternatives"),
        ({"alternatives": ["a"] * 11}, "alternatives"),
        ({"alternatives": [""]}, "alternatives"),
        ({"alternatives": [3]}, "alternatives"),
        ({"client_request_id": "not-a-uuid"}, "client_request_id"),
        ({"client_name": "x" * 81}, "client_name"),
    ],
)
def test_create_rejects_invalid_input(task, member, kw, field):
    with pytest.raises(ServiceError) as e:
        mk(task, member, **kw)
    assert field in err(e)


def test_create_summary_boundaries_and_whitespace_collapse(task, member):
    assert len(mk(task, member, summary="x" * 800).summary) == 800
    assert mk(task, member, summary=" 가\n\n나\x00 다 ").summary == "가 나 다"
    assert len(mk(task, member, alternatives=["a"] * 10).alternatives) == 10


@pytest.mark.parametrize(
    "secret",
    [
        "-----BEGIN PRIVATE KEY-----",
        "Authorization header Bearer abcdefghijklmnopqrstuv",
        "pm_" + "A" * 24,
        "AKIA" + "A" * 16,
        "eyJhbGciOiJI.eyJzdWIiOiIx.abcdefghijk",
        "password: hunter2hunter2",
        "api_key=abcd1234efgh",
        "https://user:secret@example.com/x",
    ],
)
def test_create_rejects_secret_like_text(task, member, secret):
    with pytest.raises(ServiceError) as e:
        mk(task, member, summary=secret)
    assert "summary" in err(e)
    assert not TaskDecisionRecord.objects.exists()


def test_create_rejects_secret_in_alternatives_and_reason(task, member):
    with pytest.raises(ServiceError):
        mk(task, member, alternatives=["password=abcdefgh12"])
    with pytest.raises(ServiceError):
        mk(task, member, reason_summary="access_token: abcdefghij")


def test_ai_judgment_cannot_carry_user_input_fields(task, member):
    with pytest.raises(ServiceError):
        mk(task, member, kind="ai_judgment", input_type="requirement", evidence_basis="")
    with pytest.raises(ServiceError):
        mk(task, member, kind="ai_judgment", input_type="", evidence_basis="inferred")
    with pytest.raises(ServiceError):
        ai_judgment(task, member, status="captured")


def test_non_member_cannot_create_or_list(task, outsider):
    with pytest.raises(ServiceError) as e:
        mk(task, outsider)
    assert "org" in err(e)
    with pytest.raises(ServiceError):
        list_records(task, actor=outsider)
    with pytest.raises(ServiceError):
        effective_records(task, actor=None)


def test_idempotent_retry_returns_same_and_conflict_on_change(task, member):
    key = str(uuid.uuid4())
    a = mk(task, member, client_request_id=key)
    assert mk(task, member, client_request_id=key).pk == a.pk
    assert TaskDecisionRecord.objects.count() == 1
    with pytest.raises(ConflictError) as e:
        mk(task, member, client_request_id=key, summary="다른 내용")
    assert e.value.latest.pk == a.pk


def test_idempotent_retry_survives_confirmation(task, member):
    key = str(uuid.uuid4())
    a = mk(task, member, evidence_basis="inferred", client_request_id=key)
    confirm_record(task, a.pk, actor=member, source="web")
    again = mk(task, member, evidence_basis="inferred", client_request_id=key)
    assert again.pk == a.pk and again.status == "confirmed"


def test_supersede_marks_prior_and_validates(task, member, admin):
    old = mk(task, member)
    new = mk(task, member, summary="학교·동문 계정 허용", supersedes_id=old.pk)
    old.refresh_from_db()
    assert old.status == "superseded" and new.supersedes_id == old.pk
    # 이미 대체된 기록, 없는 기록, 다른 종류, 남의 기록은 대체할 수 없다.
    for target, kw in [
        (old.pk, {}),
        (999999, {}),
        (new.pk, {"kind": "ai_judgment", "input_type": "", "evidence_basis": ""}),
    ]:
        with pytest.raises(ServiceError) as e:
            mk(task, member, supersedes_id=target, **kw)
        assert "supersedes_id" in err(e)
    with pytest.raises(ServiceError) as e:
        mk(task, admin, supersedes_id=new.pk)
    assert "supersedes_id" in err(e)


def test_supersede_rejected_record_is_refused(task, member):
    r = mk(task, member)
    reject_record(task, r.pk, actor=member, source="web")
    with pytest.raises(ServiceError):
        mk(task, member, supersedes_id=r.pk)


def test_supersede_other_task_record_is_refused(task, project, member):
    from tasks.services import create_task

    other = create_task(
        project=project, title="다른 태스크", actor=member, source="web", no_due_reason="미정"
    )
    r = mk(other, member)
    with pytest.raises(ServiceError):
        mk(task, member, supersedes_id=r.pk)


# ---------- AI(토큰) 쓰기 정책 ----------


def test_token_write_requires_own_write_token_and_policy(org, admin, task, member):
    _, ai = ApiToken.issue(member, "ai", "write")
    ai_tok = ApiToken.authenticate(ai)
    # 정책 허용(기본): 본인 쓰기 토큰이면 통과
    assert mk(task, member, source="mcp", token=ai_tok).source == "mcp"
    # 토큰 없이 mcp 출처
    with pytest.raises(ServiceError) as e:
        mk(task, member, source="mcp")
    assert "token" in err(e)
    # 남의 토큰 거부
    _, other = ApiToken.issue(admin, "o", "write")
    with pytest.raises(ServiceError):
        mk(task, member, source="api", token=ApiToken.authenticate(other))
    # 읽기 토큰 거부
    _, rd = ApiToken.issue(member, "r", "read")
    with pytest.raises(ServiceError):
        mk(task, member, source="mcp", token=ApiToken.authenticate(rd))
    # 정책 차단
    set_org_settings(org, {"ai.record_work": "deny"}, admin)
    with pytest.raises(ServiceError) as e:
        mk(task, member, source="mcp", token=ai_tok)
    assert "ai" in err(e)
    set_org_settings(org, {"ai.record_work": "allow", "ai.enabled": False}, admin)
    with pytest.raises(ServiceError):
        mk(task, member, source="mcp", token=ai_tok)


# ---------- list / effective ----------


def test_list_records_pagination_and_validation(task, member):
    ids = [mk(task, member, summary=f"요구 {i}").pk for i in range(3)]
    page, total = list_records(task, actor=member, limit=2, offset=1)
    assert total == 3 and [r.pk for r in page] == ids[1:]
    assert list_records(task, actor=member, limit="1", offset="0")[1] == 3
    for kw in [
        {"limit": 0},
        {"limit": 101},
        {"offset": -1},
        {"limit": "x"},
        {"offset": None},
    ]:
        with pytest.raises(ServiceError) as e:
            list_records(task, actor=member, **kw)
        assert "pagination" in err(e)
    assert list_records(task, actor=member, limit=100)[1] == 3


def test_effective_records_filters_status_and_kind(task, member):
    cap = mk(task, member, summary="수집")
    prop = mk(task, member, evidence_basis="inferred", summary="제안")
    rej = mk(task, member, summary="제외될 것")
    reject_record(task, rej.pk, actor=member, source="web")
    old = mk(task, member, summary="옛것")
    mk(task, member, summary="새것", supersedes_id=old.pk)
    ai = ai_judgment(task, member)
    got = {r.pk for r in effective_records(task, actor=member)}
    assert cap.pk in got and ai.pk in got
    assert not ({prop.pk, rej.pk, old.pk} & got)


# ---------- confirm / reject ----------


def test_confirm_flow_and_idempotence(task, member):
    r = mk(task, member, evidence_basis="inferred")
    c = confirm_record(task, r.pk, actor=member, source="web")
    assert c.status == "confirmed" and c.confirmed_by_id == member.pk and c.confirmed_at
    first = c.confirmed_at
    assert confirm_record(task, r.pk, actor=member, source="web").confirmed_at == first


def test_confirm_rejects_non_web_token_other_user_ai_and_wrong_status(task, member, admin):
    r = mk(task, member, evidence_basis="inferred")
    _, raw = ApiToken.issue(member, "t", "write", for_ai=False)
    tok = ApiToken.authenticate(raw)
    with pytest.raises(ServiceError) as e:
        confirm_record(task, r.pk, actor=member, source="mcp")
    assert "source" in err(e)
    with pytest.raises(ServiceError):
        confirm_record(task, r.pk, actor=member, source="web", token=tok)
    with pytest.raises(ServiceError):  # 본인 귀속이 아님
        confirm_record(task, r.pk, actor=admin, source="web")
    ai = ai_judgment(task, member)
    with pytest.raises(ServiceError):
        confirm_record(task, ai.pk, actor=member, source="web")
    with pytest.raises(ServiceError) as e:
        confirm_record(task, 999999, actor=member, source="web")
    assert "record" in err(e)
    rej = mk(task, member)
    reject_record(task, rej.pk, actor=member, source="web")
    with pytest.raises(ServiceError):
        confirm_record(task, rej.pk, actor=member, source="web")


def test_confirm_non_member_is_refused(task, member, outsider):
    r = mk(task, member, evidence_basis="inferred")
    with pytest.raises(ServiceError) as e:
        confirm_record(task, r.pk, actor=outsider, source="web")
    assert "org" in err(e)


def test_reject_records_reason_and_guards(task, member, admin):
    r = mk(task, member, evidence_basis="inferred")
    out = reject_record(task, r.pk, actor=member, source="web", reason="  내 의도가\n아님 ")
    assert out.status == "rejected" and out.rejection_reason == "내 의도가 아님"
    with pytest.raises(ServiceError):  # 이미 제외됨
        reject_record(task, r.pk, actor=member, source="web")
    r2 = mk(task, member)
    with pytest.raises(ServiceError):
        reject_record(task, r2.pk, actor=member, source="mcp")
    with pytest.raises(ServiceError):
        reject_record(task, r2.pk, actor=admin, source="web")
    with pytest.raises(ServiceError):
        reject_record(task, r2.pk, actor=member, source="web", reason="x" * 301)
    with pytest.raises(ServiceError):
        reject_record(task, r2.pk, actor=member, source="web", reason="password=abcdefgh12")
    r2.refresh_from_db()
    assert r2.status == "captured"


def test_confirmed_record_cannot_be_rejected(task, member):
    r = mk(task, member, evidence_basis="inferred")
    confirm_record(task, r.pk, actor=member, source="web")
    with pytest.raises(ServiceError):
        reject_record(task, r.pk, actor=member, source="web")


# ---------- API ----------

BODY = {
    "kind": "user_input",
    "input_type": "requirement",
    "evidence_basis": "explicit_reply",
    "summary": "배포는 금요일 피함",
}


def test_api_create_list_and_effective(api, task):
    url = f"/api/tasks/{task.pk}/decisions"
    r = api.post(url, BODY)
    assert r.status_code == 201 and r.json()["source"] == "api"
    api.post(
        url,
        {**BODY, "evidence_basis": "inferred", "summary": "추론", "input_type": "steer"},
    )
    lst = api.get(url).json()
    assert lst["total"] == 2 and lst["limit"] == 50
    eff = api.get(url + "?effective_only=true").json()
    assert eff["total"] == 1
    page = api.get(url + "?limit=1&offset=1").json()
    assert len(page["items"]) == 1 and page["offset"] == 1
    assert api.get(url + "?limit=500").json()["limit"] == 100


def test_api_create_validation(api, task):
    url = f"/api/tasks/{task.pk}/decisions"
    assert api.post(url, {**BODY, "extra_field": 1}).status_code == 422
    assert api.post(url, {**BODY, "summary": ""}).status_code == 422
    assert api.post(url, {**BODY, "summary": "password=abcdefgh12"}).status_code == 400
    assert api.post(url, {**BODY, "supersedes_id": 0}).status_code == 422


def test_api_idempotency_conflict_returns_409(api, task):
    url = f"/api/tasks/{task.pk}/decisions"
    key = str(uuid.uuid4())
    assert api.post(url, {**BODY, "client_request_id": key}).status_code == 201
    assert api.post(url, {**BODY, "client_request_id": key}).status_code == 201
    r = api.post(url, {**BODY, "client_request_id": key, "summary": "달라짐"})
    assert r.status_code == 409 and r.json()["latest"]["summary"] == BODY["summary"]


def test_api_read_token_cannot_write_and_outsider_gets_404(client, task, read_token, outsider):
    url = f"/api/tasks/{task.pk}/decisions"
    h = {"Authorization": f"Bearer {read_token}"}
    assert client.post(url, BODY, content_type="application/json", headers=h).status_code == 403
    assert client.get(url, headers=h).status_code == 200
    _, raw = ApiToken.issue(outsider, "o", "write")
    r = client.get(url, headers={"Authorization": f"Bearer {raw}"})
    assert r.status_code == 404


def test_api_confirm_requires_browser_session(client, api, task, member):
    url = f"/api/tasks/{task.pk}/decisions"
    rid = api.post(url, {**BODY, "evidence_basis": "inferred"}).json()["id"]
    confirm = f"{url}/{rid}/confirm"
    assert api.post(confirm).status_code == 403  # 토큰은 확인할 수 없다
    client.force_login(member)
    for h in ({"X-Source": "ai"}, {"X-Source": "mcp"}):
        assert client.post(confirm, headers=h).status_code == 403
    ok = client.post(confirm)
    assert ok.status_code == 200 and ok.json()["status"] == "confirmed"
    assert ok.json()["confirmed_by_id"] == member.pk


def test_api_reject_via_session_only(client, api, task, member, admin):
    url = f"/api/tasks/{task.pk}/decisions"
    rid = api.post(url, {**BODY, "evidence_basis": "inferred"}).json()["id"]
    reject = f"{url}/{rid}/reject"
    payload = {"reason_summary": "의도와 다름"}
    assert api.post(reject, payload).status_code == 403
    client.force_login(admin)  # 본인에게 귀속된 기록이 아님
    assert client.post(reject, payload, content_type="application/json").status_code == 400
    client.force_login(member)
    r = client.post(reject, payload, content_type="application/json")
    assert r.status_code == 200
    assert (r.json()["status"], r.json()["rejection_reason"]) == ("rejected", "의도와 다름")


def test_api_supersede_path_and_body_must_agree(api, task):
    url = f"/api/tasks/{task.pk}/decisions"
    rid = api.post(url, BODY).json()["id"]
    bad = api.post(f"{url}/{rid}/supersede", {**BODY, "supersedes_id": rid + 1})
    assert bad.status_code == 400
    ok = api.post(f"{url}/{rid}/supersede", {**BODY, "summary": "수정본"})
    assert ok.status_code == 201 and ok.json()["supersedes_id"] == rid
    again = api.post(f"{url}/{rid}/supersede", {**BODY, "summary": "또 수정"})
    assert again.status_code == 400  # 이미 대체됨
    key = str(uuid.uuid4())
    rid2 = ok.json()["id"]
    p = {**BODY, "summary": "셋째", "client_request_id": key}
    assert api.post(f"{url}/{rid2}/supersede", p).status_code == 201
    r = api.post(f"{url}/{rid2}/supersede", {**p, "summary": "변경"})
    assert r.status_code == 409
