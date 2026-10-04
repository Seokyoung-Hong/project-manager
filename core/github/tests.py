"""GitHub 연동의 보안 경계 테스트.

여기 있는 것은 틀리면 조용히 뚫리는 자리다. 화면·규칙 테스트와 섞지 않는다.
"""

import hashlib
import hmac
import json
import subprocess
from datetime import timedelta
from pathlib import Path

import pytest
from cryptography.fernet import Fernet
from cryptography.hazmat.primitives import serialization
from cryptography.hazmat.primitives.asymmetric import rsa
from django.utils import timezone

from common.errors import ServiceError
from github import services as ghs
from github.client import GitHubError
from github.conftest import signed
from github.crypto import decrypt, encrypt
from github.models import (
    GitEvent,
    GitHubIdentity,
    GitHubInstallation,
    RepoConnection,
    RepoIssue,
    TaskGitLink,
)

pytestmark = pytest.mark.django_db


def _key_pem() -> str:
    key = rsa.generate_private_key(public_exponent=65537, key_size=2048)
    return key.private_bytes(
        encoding=serialization.Encoding.PEM,
        format=serialization.PrivateFormat.TraditionalOpenSSL,
        encryption_algorithm=serialization.NoEncryption(),
    ).decode()


@pytest.fixture
def conn(gh, project, admin):
    return RepoConnection.objects.create(
        project=project, url="https://github.com/o/r.git", full_name="o/r", created_by=admin
    )


# ---------- 웹훅 인증 ----------


def test_webhook_rejects_bad_signature(gh, client, conn):
    body = json.dumps({"repository": {"full_name": "o/r"}}).encode()
    bad = "sha256=" + hmac.new(b"wrong", body, hashlib.sha256).hexdigest()
    r = client.post(
        "/api/integrations/github/webhook",
        body,
        content_type="application/json",
        headers={"X-Hub-Signature-256": bad, "X-GitHub-Event": "push", "X-GitHub-Delivery": "d"},
    )
    assert r.status_code == 401
    assert not GitEvent.objects.exists()


def test_webhook_rejects_missing_signature(gh, client, conn):
    r = client.post(
        "/api/integrations/github/webhook",
        json.dumps({"repository": {"full_name": "o/r"}}),
        content_type="application/json",
        headers={"X-GitHub-Event": "push", "X-GitHub-Delivery": "d"},
    )
    assert r.status_code == 401


def test_webhook_rejects_when_secret_unset(settings, client, conn):
    """비밀이 비어 있으면 전부 거부한다. 열어 두면 인증 없는 공개 쓰기 경로가 된다."""
    settings.GITHUB_WEBHOOK_SECRET = ""
    body = json.dumps({"repository": {"full_name": "o/r"}}).encode()
    sig = "sha256=" + hmac.new(b"", body, hashlib.sha256).hexdigest()
    r = client.post(
        "/api/integrations/github/webhook",
        body,
        content_type="application/json",
        headers={"X-Hub-Signature-256": sig, "X-GitHub-Event": "push", "X-GitHub-Delivery": "d"},
    )
    assert r.status_code == 401


def test_webhook_rejects_session_and_token(gh, client, admin, write_token, conn):
    """세션 쿠키도 API 토큰도 이 경로에 들어오지 못한다."""
    client.force_login(admin)
    payload = json.dumps({"repository": {"full_name": "o/r"}})
    r = client.post("/api/integrations/github/webhook", payload, content_type="application/json")
    assert r.status_code == 401
    r = client.post(
        "/api/integrations/github/webhook",
        payload,
        content_type="application/json",
        headers={"Authorization": f"Bearer {write_token[1]}"},
    )
    assert r.status_code == 401


def test_webhook_accepts_good_signature(gh, client, conn):
    r = signed(client, {"repository": {"full_name": "o/r"}}, "membership", "d-ok")
    assert r.status_code == 202


def test_webhook_ignores_unconnected_repo(gh, client):
    r = signed(client, {"repository": {"full_name": "other/repo"}}, "push", "d-x")
    assert r.status_code == 202
    assert not GitEvent.objects.exists()


def test_webhook_not_throttled(gh, client, conn):
    """전역 분당 60건 한도에 웹훅이 묶이면 push가 몰릴 때 429가 난다."""
    codes = {
        signed(client, {"repository": {"full_name": "o/r"}}, "membership", f"t-{i}").status_code
        for i in range(70)
    }
    assert 429 not in codes


# ---------- 토큰 ----------


def test_encrypt_roundtrip_and_bad_key(gh):
    token = encrypt("ghu_secret")
    assert decrypt(token) == "ghu_secret"
    # 키를 갈면 옛 토큰은 못 읽는다. 예외가 아니라 빈 문자열이어야 로그인이 막히지 않는다.
    gh.CREDENTIAL_KEY = Fernet.generate_key().decode()
    assert decrypt(token) == ""
    assert decrypt("not-a-token") == ""


def test_user_token_refreshes_when_expired(gh, admin, monkeypatch):
    identity = GitHubIdentity.objects.create(user=admin, github_id=1, login="a")
    gh_store(identity, "old", "refresh-me", expired=True)
    called = {}

    def fake_refresh(token):
        called["token"] = token
        return {"access_token": "new-token", "expires_in": 28800}

    monkeypatch.setattr("github.client.refresh_user_token", fake_refresh)
    assert gh_token(identity) == "new-token"
    assert called["token"] == "refresh-me"


def test_user_token_raises_when_refresh_dead(gh, admin):
    identity = GitHubIdentity.objects.create(user=admin, github_id=2, login="b")
    gh_store(identity, "old", "", expired=True)
    with pytest.raises(ServiceError):
        gh_token(identity)


def gh_store(identity, access, refresh, *, expired=False):
    identity.token_enc = encrypt(access)
    identity.refresh_enc = encrypt(refresh) if refresh else ""
    identity.token_expires_at = timezone.now() - timedelta(minutes=5 if expired else -60)
    identity.refresh_expires_at = timezone.now() + timedelta(days=30)
    identity.save()
    return None


def gh_token(identity):
    return ghs.user_token(identity)


def test_app_jwt_is_rs256_and_signed(gh):
    """PyJWT 없이 만든 JWT가 실제로 RS256 서명인지 공개키로 확인한다."""
    import base64

    from cryptography.hazmat.primitives import hashes
    from cryptography.hazmat.primitives.asymmetric import padding

    pem = _key_pem()
    gh.GITHUB_APP_PRIVATE_KEY = pem
    token = gh_app_jwt()
    header_b64, payload_b64, sig_b64 = token.split(".")

    def unb64(s):
        return base64.urlsafe_b64decode(s + "=" * (-len(s) % 4))

    assert json.loads(unb64(header_b64))["alg"] == "RS256"
    assert json.loads(unb64(payload_b64))["iss"] == "1"
    private = serialization.load_pem_private_key(pem.encode(), password=None)
    private.public_key().verify(
        unb64(sig_b64),
        f"{header_b64}.{payload_b64}".encode(),
        padding.PKCS1v15(),
        hashes.SHA256(),
    )


def gh_app_jwt():
    from github.client import app_jwt

    return app_jwt()


# ---------- 권한 필터 ----------


def test_repo_state_four_cases(gh, project, admin, member, conn):
    from github.services import repo_state

    project.repo = conn
    # 저장소는 있는데 GitHub 미연결
    assert repo_state(member, project)["state"] == "unlinked"
    # 연결은 했지만 그 저장소가 목록에 없다
    GitHubIdentity.objects.create(user=member, github_id=9, login="m", repos=["other/repo"])
    member.refresh_from_db()
    assert repo_state(member, project)["state"] == "denied"
    # 목록에 있으면 ok
    member.github.repos = ["o/r"]
    member.github.save()
    assert repo_state(member, project)["state"] == "ok"
    # 저장소 연결 자체가 없으면 none
    conn.delete()
    project.refresh_from_db()
    assert repo_state(member, project)["state"] == "none"


def test_can_view_repo_needs_identity(gh, member):
    from github.services import can_view_repo

    assert can_view_repo(member, "o/r") is False
    assert can_view_repo(member, "") is False


def test_connect_repo_requires_access(gh, project, member, org):
    """볼 수 없는 저장소는 연결할 수 없다."""
    # 저장소 연결은 프로젝트 관리자 등급이다 — 여기서 보는 건 GitHub 접근 쪽이다
    project.owners.add(member)
    with pytest.raises(ServiceError):
        ghs.connect_repo(project=project, url="https://github.com/o/r.git", actor=member)
    GitHubIdentity.objects.create(user=member, github_id=5, login="m", repos=["o/r"])
    member.refresh_from_db()
    conn = ghs.connect_repo(project=project, url="https://github.com/o/r.git", actor=member)
    assert conn.full_name == "o/r"


def test_connect_repo_requires_membership(gh, project, outsider):
    GitHubIdentity.objects.create(user=outsider, github_id=6, login="o", repos=["o/r"])
    outsider.refresh_from_db()
    with pytest.raises(ServiceError):
        ghs.connect_repo(project=project, url="https://github.com/o/r.git", actor=outsider)


def test_connect_repo_settings_by_admin_blocks_project_owner(gh, org, admin, member, project):
    """저장소 연결은 project.settings_by 등급을 탄다 — admin으로 잠그면 프로젝트 관리자도 막힌다."""
    project.owners.set([member])
    GitHubIdentity.objects.create(user=member, github_id=7, login="m", repos=["o/r"])
    GitHubIdentity.objects.create(user=admin, github_id=17, login="ad", repos=["o/r"])
    member.refresh_from_db()
    admin.refresh_from_db()
    org.settings = {"project.settings_by": "admin"}
    org.save(update_fields=["settings"])
    with pytest.raises(ServiceError):
        ghs.connect_repo(project=project, url="https://github.com/o/r.git", actor=member)
    conn = ghs.connect_repo(project=project, url="https://github.com/o/r.git", actor=admin)
    assert conn.full_name == "o/r"


def test_connect_repo_ai_gate(gh, org, admin, project):
    """source=mcp일 때만 ai.manage_repo를 본다. web 경로는 그대로 통과한다."""
    GitHubIdentity.objects.create(user=admin, github_id=8, login="a", repos=["o/r"])
    admin.refresh_from_db()
    org.settings = {"ai.manage_repo": "deny"}
    org.save(update_fields=["settings"])
    with pytest.raises(ServiceError):
        ghs.connect_repo(
            project=project, url="https://github.com/o/r.git", actor=admin, source="mcp"
        )
    conn = ghs.connect_repo(
        project=project, url="https://github.com/o/r.git", actor=admin, source="web"
    )
    assert conn.full_name == "o/r"


@pytest.mark.parametrize(
    "url",
    [
        "https://github.com/owner/repo",
        "https://github.com/owner/repo.git",
        "git@github.com:owner/repo.git",
        "https://github.com/owner/repo/",
    ],
)
def test_parse_repo_url_variants(url):
    assert ghs.parse_repo_url(url) == "owner/repo"


def test_parse_repo_url_rejects_other_hosts():
    with pytest.raises(ServiceError):
        ghs.parse_repo_url("https://gitlab.com/owner/repo.git")


def test_sync_repos_only_own_orgs(gh, admin, org, monkeypatch, member):
    """다른 조직의 설치는 묻지 않는다."""
    from orgs.services import create_org

    other = create_org("남의 조직", "", member)
    GitHubInstallation.objects.create(
        org=org, installation_id=11, account_login="mine", installed_by=admin
    )
    GitHubInstallation.objects.create(
        org=other, installation_id=22, account_login="theirs", installed_by=member
    )
    identity = GitHubIdentity.objects.create(user=admin, github_id=3, login="a")
    gh_store(identity, "tok", "ref")
    asked = []

    def fake_request(method, path, token, **kw):
        asked.append(path)
        return {"repositories": [{"full_name": "mine/repo"}]}

    monkeypatch.setattr("github.client.request", fake_request)
    repos = ghs.sync_repos(identity)
    assert repos == ["mine/repo"]
    assert any("/11/" in p for p in asked)
    assert not any("/22/" in p for p in asked)


def test_sync_repos_keeps_cache_when_github_hiccups(gh, admin, org, monkeypatch):
    """일시적 오류로 목록을 비우지 않는다. 비우면 repo_state가 denied가 되어 화면이 사라진다."""
    GitHubInstallation.objects.create(
        org=org, installation_id=11, account_login="mine", installed_by=admin
    )
    identity = GitHubIdentity.objects.create(
        user=admin, github_id=3, login="a", repos=["mine/repo"]
    )
    gh_store(identity, "tok", "ref")

    def boom(method, path, token, **kw):
        raise GitHubError(502, "Bad gateway")

    monkeypatch.setattr("github.client.request", boom)
    with pytest.raises(GitHubError):
        ghs.sync_repos(identity)
    identity.refresh_from_db()
    assert identity.repos == ["mine/repo"]


def test_sync_repos_skips_installs_we_cannot_see(gh, admin, org, monkeypatch):
    """403·404는 진짜로 권한이 없다는 뜻이다 — 그 설치만 건너뛴다."""
    GitHubInstallation.objects.create(
        org=org, installation_id=11, account_login="mine", installed_by=admin
    )
    identity = GitHubIdentity.objects.create(
        user=admin, github_id=3, login="a", repos=["mine/repo"]
    )
    gh_store(identity, "tok", "ref")

    def denied(method, path, token, **kw):
        raise GitHubError(403, "Forbidden")

    monkeypatch.setattr("github.client.request", denied)
    assert ghs.sync_repos(identity) == []


# ---------- actor=None 경계 ----------


def test_actor_none_only_from_github_services():
    """actor=None을 tasks.services에 넘기는 코드가 github/ 밖에 없다."""
    root = Path(__file__).resolve().parent.parent
    hits = subprocess.run(
        ["git", "grep", "-n", "actor=None", "--", "*.py"],
        cwd=root,
        capture_output=True,
        text=True,
        encoding="utf-8",
        errors="replace",  # Windows 기본 코덱(cp949)이 한글 줄에서 터진다
    ).stdout.splitlines()
    outside = [
        h
        for h in hits
        if not h.startswith("github/") and "tests.py" not in h and "/tests/" not in h
    ]
    assert outside == [], outside


# ---------- 검증: 개인 계정(User) 설치 · 저장소 하나 ----------
# 결함은 xfail(strict=True)로 재현한다. 고치면 XPASS가 실패로 떠서 표시를 떼라고 알려 준다.


def _user_install(org, admin):
    from github.test_writes import _identity

    GitHubInstallation.objects.create(
        org=org,
        installation_id=99,
        account_login="solo-dev",
        account_type="User",
        repo_selection="selected",
        installed_by=admin,
    )
    _identity(admin, "solo-dev")
    org.refresh_from_db()
    admin.refresh_from_db()


@pytest.fixture
def fake_user_github(monkeypatch):
    """개인 계정 설치를 흉내 낸다. /orgs/* 는 GitHub처럼 404를 낸다(계정이 조직이 아니다)."""
    calls = []

    def fake(method, path, token, *, body=None, **kw):
        calls.append((method, path))
        if path.startswith("/app/installations/"):
            return {
                "account": {"login": "solo-dev", "type": "User"},
                "repository_selection": "selected",
            }
        if "/repositories" in path:  # 설치 목록과 /user/installations/{id}/repositories
            return {"repositories": [{"full_name": "solo-dev/app", "private": True}]}
        if path.startswith("/orgs/") or path.startswith("/repos/solo-dev/app/teams"):
            raise GitHubError(404, "Not Found")
        return []

    monkeypatch.setattr("github.client.request", fake)
    monkeypatch.setattr("github.client.app_jwt", lambda: "jwt")
    monkeypatch.setattr("github.client.installation_token", lambda iid: "tok")
    return calls


def _login(client):
    client.login(username="admin1", password="pw12345678")
    return client


def test_user_account_install_and_single_repo_flow(
    gh, client, org, admin, project, task, fake_user_github
):
    """개인 계정 설치 저장 → 후보 1개 → 연결 → 저장소 탭 200 → 웹훅 규칙 동작."""
    from github.test_writes import _identity

    inst = ghs.save_installation(org, 99, actor=admin)
    assert (inst.account_login, inst.account_type) == ("solo-dev", "User")
    identity = _identity(admin, "solo-dev")
    identity.repos = ["solo-dev/app"]
    identity.save(update_fields=["repos"])
    _login(client)
    r = client.get(f"/projects/{project.pk}/repo")
    assert r.status_code == 200 and "solo-dev/app" in r.content.decode()
    r = client.post(f"/projects/{project.pk}/repo", {"url": "https://github.com/solo-dev/app"})
    assert r.status_code == 302
    conn = RepoConnection.objects.get(project=project)
    # /repos/{repo}/teams는 개인 저장소에서 404다. 화면은 깨지지 않아야 한다.
    assert client.get(f"/projects/{project.pk}/repo").status_code == 200
    payload = {
        "repository": {"full_name": "solo-dev/app"},
        "ref_type": "branch",
        "ref": f"feat/x({task.number})",
    }
    assert signed(client, payload, "create", "user-1").status_code == 200
    task.refresh_from_db()
    assert task.status == "doing"
    assert task.git.connection_id == conn.pk


@pytest.mark.xfail(
    strict=True, reason="결함: 개인 계정 설치의 'GitHub에서 설정' 링크가 /organizations/ 경로라 404"
)
def test_user_install_settings_link_points_to_user_settings(
    gh, client, org, admin, fake_user_github
):
    _user_install(org, admin)
    body = _login(client).get(f"/orgs/{org.pk}/github").content.decode()
    assert "https://github.com/settings/installations/99" in body


def test_user_install_team_page_does_not_500(gh, client, org, admin, team, fake_user_github):
    _user_install(org, admin)
    assert _login(client).get(f"/teams/{team.pk}").status_code == 200


@pytest.mark.xfail(strict=True, reason="결함: 개인 계정 설치에서도 GitHub 팀 연결·생성 UI가 보인다")
def test_user_install_hides_github_team_ui(gh, client, org, admin, team, fake_user_github):
    _user_install(org, admin)
    body = _login(client).get(f"/teams/{team.pk}").content.decode()
    assert "GitHub 팀 만들고 연결" not in body


@pytest.mark.xfail(
    strict=True, reason="결함: 개인 계정 설치에서도 /orgs/{login}/memberships 초대를 부른다"
)
def test_user_install_invite_skips_org_api(gh, client, org, admin, fake_user_github):
    _user_install(org, admin)
    _login(client).post(
        f"/orgs/{org.pk}/invites", {"days": 7, "gh_invite": "on", "gh_login": "new-hire"}
    )
    assert not [p for _, p in fake_user_github if p.startswith("/orgs/")]


@pytest.mark.xfail(
    strict=True, reason="결함: 개인 계정 설치에서도 멤버 제거 때 /orgs/{login}/members를 부른다"
)
def test_user_install_member_remove_skips_org_api(gh, client, org, admin, member, fake_user_github):
    from github.test_writes import _identity
    from orgs.models import OrgMembership

    _user_install(org, admin)
    _identity(member, "member-gh")
    m = OrgMembership.objects.get(org=org, user=member)
    _login(client).post(f"/orgs/memberships/{m.pk}/remove")
    assert not OrgMembership.objects.filter(pk=m.pk).exists()
    assert not [p for _, p in fake_user_github if p.startswith("/orgs/")]


# ---------- 검증: 저장소 하나에 프로젝트 여럿 ----------


@pytest.fixture
def shared(gh, org, admin, project, conn):
    """같은 저장소를 두 프로젝트에 잇는다. 두 번째는 대소문자만 다르게 적었다."""
    from projects.services import create_project

    p2 = create_project(org=org, name="P2", actor=admin, owners=[admin], status="active")
    conn2 = RepoConnection.objects.create(
        project=p2, url="https://github.com/O/R.git", full_name="O/R", created_by=admin
    )
    return conn, conn2


def _repo(**kw):
    return {"repository": {"full_name": "o/r"}, **kw}


def test_shared_repo_task_ref_moves_only_own_project(gh, client, shared, task):
    conn, conn2 = shared
    branch = f"feat/x({task.number})"
    signed(client, _repo(ref_type="branch", ref=branch), "create", "sh-1")
    pr = {"number": 3, "title": "fix", "body": "", "head": {"ref": branch}}
    signed(client, _repo(action="opened", pull_request=pr), "pull_request", "sh-2")
    # 재전송은 두 연결 모두 중복으로 본다. IntegrityError 없이 200.
    r = signed(client, _repo(ref_type="branch", ref=branch), "create", "sh-1")
    assert r.status_code == 200 and r.json().get("duplicate")
    task.refresh_from_db()
    assert task.status == "review"
    assert task.git.connection_id == conn.pk and task.git.pr_number == 3
    assert GitEvent.objects.filter(connection=conn).count() == 2
    results = set(GitEvent.objects.filter(connection=conn2).values_list("result", flat=True))
    assert results == {"연결 안 됨"}
    assert GitEvent.objects.filter(delivery_id__startswith="sh-1:").count() == 2


def test_shared_repo_issues_are_per_project(gh, client, shared, admin):
    from github.pr_context import build_pr_context
    from github.test_writes import _identity

    conn, conn2 = shared
    issue = {"number": 9, "title": "버그", "state": "open", "labels": [], "assignee": None}
    signed(client, _repo(action="opened", issue=issue), "issues", "is-1")
    a = RepoIssue.objects.get(connection=conn, number=9)
    b = RepoIssue.objects.get(connection=conn2, number=9)
    task = ghs.import_issue(b, admin)
    assert task.project_id == conn2.project_id and task.git.connection_id == conn2.pk
    a.refresh_from_db()
    assert a.task_id is None  # 다른 프로젝트 사본은 그대로 남는다
    assert ghs.org_issues(conn.project.org).count() == 2  # 조직 뷰어에는 프로젝트별로 두 줄
    # PR 맥락은 그 태스크 프로젝트의 연결을 기준으로 만든다.
    identity = _identity(admin, "admin-gh")
    identity.repos = ["O/R"]
    identity.save(update_fields=["repos"])
    admin.refresh_from_db()
    ctx = build_pr_context(task, actor=admin)
    assert ctx["issue"]["url"] == "https://github.com/O/R/issues/9"
    issue["state"] = "closed"
    signed(client, _repo(action="closed", issue=issue), "issues", "is-2")
    task.refresh_from_db()
    assert task.status == "done"
    a.refresh_from_db()
    assert a.state == "closed"


def test_shared_repo_auto_import_creates_a_task_in_each_project(gh, client, shared, member):
    """현재 동작 기록(정책 미정): 두 연결 모두 자동 가져오기면 같은 이슈가 태스크 둘이 된다."""
    from github.test_writes import _identity

    for c in shared:
        c.auto_import = True
        c.save(update_fields=["auto_import"])
    _identity(member, "member-gh")
    issue = {
        "number": 5,
        "title": "공유",
        "state": "open",
        "labels": [],
        "assignee": {"login": "member-gh"},
    }
    r = signed(client, _repo(action="opened", issue=issue), "issues", "ai-1")
    assert r.status_code == 200
    assert RepoIssue.objects.filter(number=5, task__isnull=False).count() == 2


@pytest.mark.xfail(
    strict=True,
    reason="결함: 한 연결의 create_task가 ServiceError를 내면 웹훅 전체가 400 — "
    "앞 연결만 반영되고 재전송은 중복으로 버려진다",
)
def test_shared_repo_archived_project_does_not_break_delivery(gh, client, shared, member):
    from github.test_writes import _identity
    from projects.models import Project

    conn, conn2 = shared
    for c in shared:
        c.auto_import = True
        c.save(update_fields=["auto_import"])
    Project.objects.filter(pk=conn2.project_id).update(is_archived=True)
    _identity(member, "member-gh")
    issue = {
        "number": 6,
        "title": "보관",
        "state": "open",
        "labels": [],
        "assignee": {"login": "member-gh"},
    }
    r = signed(client, _repo(action="opened", issue=issue), "issues", "ar-1")
    assert r.status_code == 200
    assert GitEvent.objects.filter(connection=conn2, delivery_id__startswith="ar-1:").exists()


def test_shared_repo_create_branch_and_disconnect(gh, shared, admin, monkeypatch):
    from github import writes
    from github.test_writes import _identity
    from tasks.services import create_task

    conn, conn2 = shared
    _identity(admin, "admin-gh")
    t2 = create_task(project=conn2.project, title="B", actor=admin, source="web", no_due_reason="x")
    seen = []

    def fake(method, path, token, **kw):
        seen.append(path)
        return {"default_branch": "main", "object": {"sha": "abc"}}

    monkeypatch.setattr("github.client.request", fake)
    writes.create_branch(t2, "feat/b", actor=admin)
    assert seen[-1] == "/repos/O/R/git/refs"
    assert TaskGitLink.objects.get(task=t2).connection_id == conn2.pk
    # 한 프로젝트 연결을 끊어도 다른 프로젝트 연결·링크는 남는다.
    assert ghs.disconnect_repo(project=conn.project, actor=admin)
    assert RepoConnection.objects.filter(pk=conn2.pk).exists()
    assert TaskGitLink.objects.filter(task=t2).exists()
