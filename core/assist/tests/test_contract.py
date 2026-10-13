"""A0 계약(IMPL-PLAN-12 §13.1): 다른 갈래가 기대는 이름·제약·설정 기본값."""

import pytest
from django.db import IntegrityError
from django.urls import reverse

from assist import context, extract, fields, net, pc, prompts, services, sources, worker
from assist.models import AiJob, AiSource, AllowedHost
from assist.services import ai_on
from common.errors import ServiceError
from orgs.settings import SPECS, clean, effective
from projects.docs import create_doc, update_doc


def test_models_and_org_row_unique(org, member):
    AiSource.objects.create(user=member, kind="org", position=1)
    AiSource.objects.create(user=member, name="내 Ollama", base_url="http://localhost:11434/v1")
    AiSource.objects.create(user=member, name="둘째", base_url="https://a.example/v1")
    job = AiJob.objects.create(user=member, org=org, kind="field", field="task.title")
    assert job.status == "queued" and job.tried == [] and job.options == {}
    AllowedHost.objects.create(host="llm.lan")
    with pytest.raises(IntegrityError):
        AiSource.objects.create(user=member, kind="org")  # 조직 AI 행은 사람당 하나


def test_settings_defaults_and_switch(org, member):
    assert effective("assist.enabled", org=org) is True
    assert effective("assist.org_level", org=org) == "member"
    assert effective("assist.org_daily_limit", org=org) == 30
    assert SPECS["assist.org_api_key"].kind == "secret"
    assert ai_on(member, org) is True
    org.settings = {"assist.enabled": False}
    assert ai_on(member, org) is False
    assert ai_on(member, None) is False


def test_org_url_format_check():
    assert clean("org", {"assist.org_url": "https://api.example.com/v1"})
    for bad in ("ftp://x.example", "https://u:p@x.example/v1", "https://x.example/v1?a=1"):
        with pytest.raises(ServiceError):
            clean("org", {"assist.org_url": bad})


def test_field_keys_and_modes():
    assert {f.shape for f in fields.FIELDS.values()} == {"line", "text", "list"}
    assert fields.kind_of("task.description") == "field"
    assert fields.kind_of("meeting.minutes") == "meeting"
    assert fields.kind_of("extract.issue") == "extract"
    assert fields.kind_of("secret.token") is None
    assert set(prompts.DOC_PROMPTS) == {
        k for k, (kind, _) in fields.MODES.items() if kind in ("doc", "meeting")
    }


def test_stub_names_exist():
    for fn in (
        services.create_job,
        services.get_job,
        services.cancel_job,
        services.apply_job,
        services.today_org_count,
        sources.plan,
        net.classify,
        net.list_models,
        net.chat,
        prompts.build_messages,
        extract.create_from_candidates,
        worker.start,
        worker.sweep,
        context.resolve_target,
        context.visible_issue,
        pc.on_heartbeat,
        pc.report,
    ):
        assert callable(fn)
    for name in (
        "assist_job_create",
        "settings_ai",
        "org_assist_test",
        "ops_assist",
    ):
        assert reverse(name, kwargs={"org_id": 1} if name.startswith("org_") else None)


def test_update_doc_force_new(org, member):
    d = create_doc(actor=member, org=org, title="문서")
    d = update_doc(d, "body_md", "하나", actor=member, expected_version=d.version)
    d = update_doc(d, "body_md", "둘", actor=member, expected_version=d.version)
    n = d.revisions.count()  # 10분 안 같은 사람 → 마지막 행 덮어쓰기
    update_doc(d, "body_md", "AI", actor=member, expected_version=d.version, force_new=True)
    assert d.revisions.count() == n + 1
