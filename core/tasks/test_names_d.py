"""IMPL-PLAN-13 갈래 D: 서비스 문자열·AI·전사 용어집의 이름은 그 조직 표시 이름.

계정 실명은 "실명으로 표시" 조직에서만 AI·용어집으로 간다(끈 조직에는 섞이지 않는다).
"""

import json

import pytest
from cryptography.fernet import Fernet

from assist import services as assist
from assist.tests.test_worker import (
    fake,  # noqa: F401
    org_ai,
    run_once,
)
from notes.models import VoiceRecording
from notes.services import glossary_terms, start_recording
from orgs.models import OrgMembership
from orgs.services import set_org_settings
from projects.docs import create_doc
from tasks.split import looks_multi_assignee, split_by_assignees
from tasks.work_requests import notify_assigned

pytestmark = pytest.mark.django_db


@pytest.fixture(autouse=True)
def _cred(settings):
    settings.CREDENTIAL_KEY = Fernet.generate_key().decode()


def _names(org, member, *, show_real_name):
    org.member_fields = {"show_real_name": show_real_name, "fields": []}
    org.save()
    OrgMembership.objects.filter(org=org, user=member).update(nickname="별명팀원")


def test_glossary_uses_org_names_and_real_name_only_when_shown(org, admin, member):
    org.discord_guild_id = "g1"
    org.save()
    set_org_settings(org, {"meeting.recording_enabled": True}, admin)
    org.refresh_from_db()
    _names(org, member, show_real_name=False)
    rec = start_recording(org=org, actor=member, guild_id="g1", voice_channel_id="v1")
    terms = glossary_terms(rec)[0]
    assert terms[0] == "별명팀원" and "관리자" in terms
    assert not {"김팀원", "김관리", "팀원"} & set(terms)

    _names(org, member, show_real_name=True)
    terms = glossary_terms(rec)[0]
    assert {"김팀원", "김관리"} <= set(terms) and "별명팀원" not in terms


@pytest.mark.parametrize("show", [False, True])
def test_ai_context_and_assignee_match(org, admin, member, project, fake, show):  # noqa: F811
    _names(org, member, show_real_name=show)
    org_ai(org)
    d = create_doc(org=org, actor=member, kind="meeting", project=project)
    VoiceRecording.objects.create(
        note=d,
        guild_id="g",
        voice_channel_id="v",
        started_by=member,
        host=member,
        transcript_md="회의",
    )
    said = ["별명팀원", "팀원", "member1", "김팀원"]
    f = fake(
        json.dumps({"tasks": [{"title": f"일{i}", "assignee": n} for i, n in enumerate(said)]})
    )
    job = assist.create_job(member, org, field="extract.meeting", target=f"doc:{d.pk}")
    run_once()
    job.refresh_from_db()
    sent = json.dumps(f.calls[0][1]["messages"], ensure_ascii=False)
    rows = json.loads(job.result)["tasks"]
    got = [r["assignee_id"] for r in rows]
    if show:
        assert "김팀원" in sent and "별명팀원" not in sent.split("구성원 표시 이름")[1]
        assert got == [member.pk] * 4
    else:
        assert "별명팀원" in sent and "김팀원" not in sent and "김관리" not in sent
        assert got == [member.pk, member.pk, member.pk, None]  # 끈 조직은 실명으로 찾지 않는다


def test_split_finds_both_names_and_labels_with_account_name(org, admin, member, task):
    _names(org, member, show_real_name=False)
    assert looks_multi_assignee("별명팀원과 관리자", "", org) == [member, admin]
    assert looks_multi_assignee("팀원과 관리자", "", org) == [member, admin]
    # 실명 표시 조직에서도 제목(GitHub 이슈 제목이 될 수 있음)에는 계정 표시 이름만
    _names(org, member, show_real_name=True)
    assert looks_multi_assignee("김팀원과 김관리", "", org) == [member, admin]
    subs = split_by_assignees(task, [member, admin], actor=admin, source="web")
    titles = [s.title for s in subs]
    assert [t.rsplit(" — ", 1)[1] for t in titles] == ["팀원", "관리자"]
    assert not any(n in t for t in titles for n in ("김팀원", "김관리", "별명팀원"))


def test_notice_uses_org_name(org, admin, member, task, monkeypatch):
    _names(org, admin, show_real_name=False)
    sent = []
    monkeypatch.setattr("tasks.work_requests.notify", lambda org, text, **kw: sent.append(text))
    OrgMembership.objects.filter(org=org, user=admin).update(nickname="별명관리")
    notify_assigned(task, admin)
    assert sent[0].startswith("별명관리님이")
