from datetime import timedelta

import pytest
from django.core.cache import cache
from django.utils import timezone

from accounts.models import ApiToken, User
from common.dates import today_kst
from orgs.models import OrgMembership
from orgs.services import add_team_member, create_org, create_team
from projects.services import create_project
from tasks.services import create_task


@pytest.fixture(autouse=True)
def _clear_throttle_cache():
    """테스트마다 처리량 제한 카운터를 비운다.

    `UserRateThrottle("60/m")`은 사용자 pk로 locmem 캐시에 센다. 캐시는 테스트 사이에
    살아남고 SQLite는 롤백으로 pk를 되돌려 쓰므로, 서로 다른 테스트의 `member`가 같은
    분당 버킷을 공유해 스위트가 커지면 엉뚱한 테스트가 429로 깨진다.
    """
    cache.clear()
    yield


@pytest.fixture
def admin(db):
    return User.objects.create_user("admin1", password="pw12345678", display_name="관리자")


@pytest.fixture
def member(db):
    """Discord 연결이 끝난 팀원.

    UI로는 snowflake를 심을 수 없지만(코드 교환만) 픽스처는 DB를 시드해도 된다.
    `discord_linked_at`을 같이 채운다 — 연결 시각이 없는 행은 `user_by_discord_id()`가
    돌려주지 않으므로, id만 있는 반쪽 행은 어떤 코드 경로도 만들 수 없는 상태다.
    """
    return User.objects.create_user(
        "member1",
        password="pw12345678",
        display_name="팀원",
        discord_user_id="111",
        discord_linked_at=timezone.now(),
    )


@pytest.fixture
def outsider(db):
    return User.objects.create_user("outsider", password="pw12345678", display_name="외부인")


@pytest.fixture
def org(admin, member):
    o = create_org("산돌이", "학생 챗봇 서비스", admin)
    OrgMembership.objects.create(org=o, user=member, role="member")
    return o


@pytest.fixture
def team(org, admin, member):
    t = create_team(org=org, name="백엔드", actor=admin)
    add_team_member(t, member, admin)
    return t


@pytest.fixture
def project(org, admin):
    return create_project(org=org, name="학식 API", actor=admin, owners=[admin], status="active")


@pytest.fixture
def task(project, member):
    return create_task(
        project=project,
        title="메뉴 누락 개선",
        actor=member,
        source="web",
        due_date=today_kst() + timedelta(days=3),
    )


@pytest.fixture
def write_token(member):
    # 사람용. AI 시나리오는 테스트 안에서 ApiToken.issue(...)로 AI용(기본값)을 따로 만든다.
    _, raw = ApiToken.issue(member, "t", "write", for_ai=False)
    return raw


@pytest.fixture
def read_token(member):
    _, raw = ApiToken.issue(member, "r", "read", for_ai=False)
    return raw


@pytest.fixture
def api(client, write_token):
    """Bearer 인증이 붙은 간단한 API 클라이언트."""

    class Api:
        def _h(self, extra=None):
            h = {"Authorization": f"Bearer {write_token}"}
            h.update(extra or {})
            return h

        def get(self, url, **kw):
            return client.get(url, headers=self._h(kw.pop("headers", None)), **kw)

        def post(self, url, data=None, **kw):
            return client.post(
                url,
                data=data,
                content_type="application/json",
                headers=self._h(kw.pop("headers", None)),
                **kw,
            )

        def patch(self, url, data=None, **kw):
            return client.patch(
                url,
                data=data,
                content_type="application/json",
                headers=self._h(kw.pop("headers", None)),
                **kw,
            )

        def delete(self, url, **kw):
            return client.delete(url, headers=self._h(kw.pop("headers", None)), **kw)

    return Api()


@pytest.fixture
def pg_flushable():
    """Postgres에서 transaction=True 테스트가 끝날 때 표를 TRUNCATE하는데, 감사 로그의 append-only 트리거
    (ops 0001)가 이를 막는다. **테스트 DB에서만** 정리 직전에 끈다. SQLite에서는 아무것도 하지 않는다.
    테스트 인자로 받으면 DB 정리보다 먼저 내려간다."""
    from django.db import connection

    yield
    if connection.vendor == "postgresql":
        with connection.cursor() as c:
            c.execute("ALTER TABLE ops_opsauditlog DISABLE TRIGGER ops_audit_no_truncate")
