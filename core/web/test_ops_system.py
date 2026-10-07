"""운영 콘솔 O2: 조직·연동·시스템 카드·개요 타일. 서비스 운영자 전용, 집계만 보인다."""

from datetime import timedelta
from unittest.mock import patch

import pytest
from django.core.files.base import ContentFile
from django.db import connection
from django.test import override_settings
from django.test.utils import CaptureQueriesContext
from django.utils import timezone

from accounts.models import ApiToken, User
from api.models import IntegrationStatus
from github.models import GitHubInstallation
from orgs.models import Organization
from tasks.models import Attachment, Notice, Task

URLS = ("/ops", "/ops/orgs", "/ops/integrations", "/ops/system")


@pytest.fixture
def staff(db):
    return User.objects.create_user(
        "staff1", password="pw12345678", display_name="운영자", is_staff=True
    )


def test_only_staff_reaches_screens(client, member, staff):
    for u in URLS:
        assert client.get(u).status_code == 302
    client.force_login(member)
    for u in URLS:
        assert client.get(u).status_code == 404, u
    client.force_login(staff)
    for u in URLS:
        assert client.get(u).status_code == 200, u


def test_screens_show_no_work_content(client, staff, org, project, task, member):
    Task.objects.filter(pk=task.pk).update(description="비밀설명문장")
    a = Attachment(
        project=project,
        name="기밀파일이름.pdf",
        size=2048,
        content_type="a/b",
        sha256="x",
        created_by=member,
    )
    a.file.save("f.pdf", ContentFile(b"x"), save=False)
    a.save()
    Notice.objects.create(org=org, user=member, text="알림비밀문구")
    ApiToken.issue(member, "토큰비밀라벨", "write", for_ai=False)
    client.force_login(staff)
    for u in URLS:
        body = client.get(u).content.decode()
        for secret in (
            task.title,
            "비밀설명문장",
            project.name,
            "기밀파일이름",
            "알림비밀문구",
            "토큰비밀라벨",
        ):
            assert secret not in body, (u, secret)
    assert org.name in client.get("/ops/orgs").content.decode()


def test_orgs_counts_constant_queries_and_inactive(client, staff, org, project, task, admin):
    client.force_login(staff)
    body = client.get("/ops/orgs").content.decode()
    assert "비활성" not in body and admin.display_name in body
    Task.objects.filter(pk=task.pk).update(updated_at=timezone.now() - timedelta(days=91))
    assert "비활성" in client.get("/ops/orgs").content.decode()
    with CaptureQueriesContext(connection) as a:
        client.get("/ops/orgs")
    for i in range(5):
        Organization.objects.create(name=f"조직{i}", created_by=admin)
    with CaptureQueriesContext(connection) as b:
        client.get("/ops/orgs")
    assert len(a) == len(b)


def test_discord_watch_states(client, staff, org):
    client.force_login(staff)
    assert "연결 안 됨" in client.get("/ops/orgs").content.decode()
    org.discord_guild_id = "123456"
    org.discord_watch_at = timezone.now() - timedelta(minutes=11)
    org.save()
    assert "감시 꺼짐" in client.get("/ops/orgs").content.decode()
    org.discord_watch_at = timezone.now()
    org.save()
    body = client.get("/ops/integrations").content.decode()
    assert "123456" in body and "감시 꺼짐" not in body
    org.discord_intent_denied = True
    org.save()
    assert "인텐트 거부" in client.get("/ops/orgs").content.decode()


def test_integrations_github_and_notices(client, staff, org, member):
    client.force_login(staff)
    with override_settings(GITHUB_ENABLED=False):
        body = client.get("/ops/integrations").content.decode()
        assert "GitHub 앱이 설정되지 않았습니다." in body
    Notice.objects.create(org=org, user=member, text="x")
    Notice.objects.create(org=org, user=member, text="y", sent_at=timezone.now())
    GitHubInstallation.objects.create(
        org=org, installation_id=7, account_login="sandol-gh", installed_by=member
    )
    with (
        override_settings(GITHUB_ENABLED=True),
        patch("web.views.ops_integrations.app_capabilities", return_value=None),
    ):
        body = client.get("/ops/integrations").content.decode()
    assert "sandol-gh" in body and "확인 불가" in body
    assert "<b>1</b><span>대기</span>" in body


def test_backup_card_and_tiles(client, staff):
    client.force_login(staff)
    body = client.get("/ops/system").content.decode()
    assert "기록 없음" in body and "마지막 백업 성공 시각" in body
    old = (timezone.now() - timedelta(hours=27)).isoformat()
    IntegrationStatus.objects.create(
        name="backup", last_run_at=timezone.now(), ok=True, detail={"last_ok_at": old}
    )
    assert "26시간 넘게" in client.get("/ops/system").content.decode()
    assert "27시간" in client.get("/ops").content.decode()
    IntegrationStatus.objects.filter(name="backup").update(
        detail={"last_ok_at": timezone.now().isoformat()}
    )
    assert "26시간 넘게" not in client.get("/ops/system").content.decode()


def test_system_cards(client, staff, project, member):
    a = Attachment(
        project=project,
        name="f.txt",
        size=4096,
        content_type="text/plain",
        sha256="x",
        created_by=member,
    )
    a.file.save("f.txt", ContentFile(b"x"), save=False)
    a.save()
    client.force_login(staff)
    body = client.get("/ops/system").content.decode()
    for card in (
        "서비스 상태",
        "백업",
        "저장소",
        "데이터베이스·마이그레이션",
        "회의 녹음",
        "Django 관리 화면",
    ):
        assert f"<h2>{card}</h2>" in body, card
    assert "모두 적용됨" in body and "mcp: 보고 없음" in body and "1개 · 4.0" in body
    assert "운영 데이터 내보내기" not in body
    with override_settings(DJANGO_ADMIN_ENABLED=False):
        assert "꺼져 있어" in client.get("/ops/system").content.decode()
