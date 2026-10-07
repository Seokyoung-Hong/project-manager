"""GitHub 화면. 업무 규칙은 전부 github/services.py에 있다 — 여기서는 부르기만 한다."""

import hmac
import json
import secrets
from urllib.parse import urlencode

from django.conf import settings
from django.contrib import messages
from django.contrib.auth.decorators import login_required
from django.core.exceptions import PermissionDenied
from django.http import Http404
from django.shortcuts import redirect, render
from django.urls import reverse
from django.utils.http import url_has_allowed_host_and_scheme
from django.views.decorators.http import require_POST

from accounts.auth import login_user
from common.errors import ConflictError, ServiceError
from github import client
from github import hooks as gh_hooks
from github import services as gh_services
from github import writes as gh_writes
from github.client import GitHubError
from github.crypto import decrypt, encrypt
from github.models import GitHubIdentity, RepoConnection, RepoIssue, TaskGitLink
from projects.services import visible_projects
from tasks import services as ts
from tasks.models import Task

from .common import (
    CONFLICT_MSG,
    can_admin,
    not_admin,
    org_or_404,
    project_or_404,
    task_or_404,
    version_of,
)
from .integrations import clear_problem, record_problem
from .projects import _can_edit_project_settings
from .tasks import _panel


def _gh_enabled_or_404():
    if not settings.GITHUB_ENABLED:
        raise Http404


def _state_ok(request, key) -> bool:
    """세션에 넣어 둔 state와 같은가. 세션 값이 없으면(None == None) 통과시키지 않는다."""
    expected = request.session.pop(key, None)
    got = request.GET.get("state", "")
    return bool(expected) and hmac.compare_digest(got.encode(), expected.encode())


def _viewable_repo(user, project):
    """API의 _repo_or_error와 같은 검사. 저장소가 없으면 404, 볼 수 없으면 403."""
    state = gh_services.repo_state(user, project)
    if state["state"] == "none":
        raise Http404
    if state["state"] != "ok":
        raise PermissionDenied
    return state["conn"]


# ---------- 조직: 앱 설치 ----------


CAP_FEATURES = [  # (app_capabilities 키, 기능, 꺼지면 사라지는 것)
    ("ci", "CI 배지 · Checks", "태스크 패널의 CI 통과/실패 배지와 실패 알림"),
    ("ci_status", "CI 배지 · Commit statuses", "외부 CI(status API)의 결과 배지"),
    ("review", "PR 리뷰 상태", "리뷰 '승인 n · 변경 요청 n' 요약과 변경 요청 → 진행 중"),
    ("milestone", "마일스톤 동기화", "GitHub 마일스톤 → 로드맵 마일스톤"),
    ("release", "릴리스", "결과 선반의 릴리스 띠와 로드맵 릴리스 칩"),
]


def _cap_rows(org) -> list[dict] | None:
    """조직 GitHub 탭의 앱 권한·이벤트 점검 표. GitHub에 물을 수 없으면 None(화면은 '확인 불가')."""
    caps = gh_services.app_capabilities(org)
    if caps is None:
        return None
    rows = [
        {"label": label, "effect": effect, **caps.get(key, {"ok": False, "missing": []})}
        for key, label, effect in CAP_FEATURES
    ]
    hooks_ok = gh_hooks.app_can_write_hooks(org)
    rows.append(
        {
            "label": "GitHub 알림 → Discord 채널 · Webhooks",
            "effect": "프로젝트 GitHub 탭의 [GitHub 알림을 Discord 채널로 받기]",
            "ok": bool(hooks_ok),
            "missing": [] if hooks_ok else ["Webhooks 쓰기 권한"],
        }
    )
    return rows


@login_required
def org_github(request, org_id):
    _gh_enabled_or_404()
    org = org_or_404(request.user, org_id)
    if denied := not_admin(request, org, "GitHub 연동"):
        return denied
    projects = org.projects.filter(is_archived=False).select_related("repo").order_by("name")
    install = getattr(org, "github", None)
    caps = _cap_rows(org) if install else None
    return render(
        request,
        "orgs/github.html",
        {
            "org": org,
            "install": install,
            "caps": caps,
            "caps_off": bool(caps) and any(not c["ok"] for c in caps),
            "identity": getattr(request.user, "github", None),
            "projects": projects,
            "is_admin": True,
            "tab": "github",
        },
    )


@login_required
def github_install(request, org_id):
    _gh_enabled_or_404()
    org = org_or_404(request.user, org_id)
    if denied := not_admin(request, org, "GitHub 연동"):
        return denied
    if getattr(request.user, "github", None) is None:
        # 돌아왔을 때 GET /user/installations로 설치 소유를 확인하므로 계정 연결이 먼저다.
        messages.error(request, "먼저 GitHub 계정을 연결하세요.")
        return redirect("org_github", org_id=org.pk)
    request.session["gh_install_org"] = org.pk
    state = secrets.token_urlsafe(16)
    request.session["gh_state"] = state
    url = f"https://github.com/apps/{settings.GITHUB_APP_SLUG}/installations/new?state={state}"
    return redirect(url)


@login_required
def github_installed(request):
    """GitHub가 되돌려 주는 곳(앱 설정의 Setup URL). ?installation_id=&setup_action=&state="""
    _gh_enabled_or_404()
    if not _state_ok(request, "gh_state"):
        raise Http404
    org_id = request.session.pop("gh_install_org", None)
    org = org_or_404(request.user, org_id)
    if denied := not_admin(request, org, "GitHub 연동"):
        return denied
    iid = request.GET.get("installation_id", "")
    if not iid.isdecimal():
        messages.error(request, "설치를 확인하지 못했습니다.")
        return redirect("org_github", org_id=org.pk)
    try:
        gh_services.save_installation(org, int(iid), actor=request.user)
        messages.success(request, "GitHub 앱을 설치했습니다.")
    except (ServiceError, GitHubError) as e:
        msg = " ".join(e.errors.values()) if isinstance(e, ServiceError) else e.message
        messages.error(request, msg or "설치를 확인하지 못했습니다.")
    return redirect("org_github", org_id=org.pk)


# ---------- 사용자: 계정 연결 ----------


def _authorize(request):
    state = secrets.token_urlsafe(16)
    request.session["gh_oauth_state"] = state
    q = urlencode(
        {
            "client_id": settings.GITHUB_CLIENT_ID,
            "state": state,
            "redirect_uri": f"{settings.SITE_URL}/settings/github/callback",
        }
    )
    return redirect(f"https://github.com/login/oauth/authorize?{q}")


@login_required
def github_connect(request):
    _gh_enabled_or_404()
    return _authorize(request)


def github_login(request):
    """GitHub로 로그인·가입. 콜백은 계정 연결과 같은 주소를 쓴다(GitHub에 등록한 주소 하나)."""
    _gh_enabled_or_404()
    if request.user.is_authenticated:
        return redirect("today")
    nxt = request.GET.get("next", "")
    if url_has_allowed_host_and_scheme(nxt, allowed_hosts={request.get_host()}):
        request.session["gh_login_next"] = nxt  # 초대 링크(/join/…)로 온 사람이 그대로 참여하게
    return _authorize(request)


def _finish_login(request, data: dict, info: dict):
    try:
        identity, created = gh_services.login_with_github(info, data)
    except ServiceError as e:
        messages.error(request, " ".join(e.errors.values()))
        return redirect("login")
    try:
        gh_services.sync_repos(identity)
    except (GitHubError, ServiceError):
        pass  # 저장소 목록은 프로필에서 다시 확인할 수 있다. 로그인은 막지 않는다.
    login_user(request, identity.user, "github")
    nxt = request.session.pop("gh_login_next", "")
    if created:
        messages.info(request, "가입되었습니다. 조직을 만들거나 초대 링크로 참여하세요.")
    # 갓 가입한 사람은 조직이 없다 — signup과 같이 조직 목록으로 보낸다.
    return redirect(nxt or ("org_list" if created else "today"))


def github_login_confirm(request):
    """같은 아이디·이메일의 기존 계정이 있을 때 신규 가입을 한 번 더 확인한다."""
    _gh_enabled_or_404()
    raw = request.session.get("gh_pending")
    if request.user.is_authenticated or not raw:
        return redirect("login")
    if request.method == "POST":
        text = decrypt(request.session.pop("gh_pending"))
        if not text:  # 키를 갈아 복호화가 안 되면 처음부터 다시
            return redirect("login")
        pending = json.loads(text)
        return _finish_login(request, pending["data"], pending["info"])
    return render(request, "auth/github_confirm.html")


def github_callback(request):
    _gh_enabled_or_404()
    failed = "profile" if request.user.is_authenticated else "login"
    if not _state_ok(request, "gh_oauth_state"):
        record_problem(request, "oauth", "콜백 상태 검증 실패")
        messages.error(
            request,
            "GitHub 인증 확인 세션이 만료됐거나 일치하지 않습니다. 인증을 다시 시작하거나 해결 절차를 확인하세요.",
            extra_tags="integration-help",
        )
        return redirect(failed)
    code = request.GET.get("code", "")
    failed = "profile" if request.user.is_authenticated else "login"
    try:
        if not code:
            raise GitHubError(400, "코드가 없습니다.")
        data = client.exchange_code(code)
        info = client.request("GET", "/user", data["access_token"])
    except GitHubError as error:
        record_problem(request, "oauth", "승인 코드 확인" if not code else "계정 인증", error)
        messages.error(
            request,
            "GitHub 계정 인증을 완료하지 못했습니다. 연결을 다시 시작하거나 해결 절차를 확인하세요.",
            extra_tags="integration-help",
        )
        return redirect(failed)
    if not request.user.is_authenticated:
        info["email"] = gh_services.github_email(info, data["access_token"])
        new = not GitHubIdentity.objects.filter(github_id=info["id"]).exists()
        if new and gh_services.lookalike_exists(info["login"], info["email"]):
            # 기존 계정 주인이 실수로 새 계정을 만들지 않게 한 번 묻는다. 토큰이 있으니 암호화해 둔다.
            request.session["gh_pending"] = encrypt(json.dumps({"data": data, "info": info}))
            return redirect("github_login_confirm")
        return _finish_login(request, data, info)
    if GitHubIdentity.objects.filter(github_id=info["id"]).exclude(user=request.user).exists():
        messages.error(request, "이 GitHub 계정은 이미 다른 사용자에게 연결되어 있습니다.")
        return redirect("profile")
    identity, _ = GitHubIdentity.objects.update_or_create(
        user=request.user,
        defaults={"github_id": info["id"], "login": info["login"][:100]},
    )
    gh_services._store_tokens(identity, data)
    try:
        gh_services.sync_repos(identity)
    except (GitHubError, ServiceError) as error:
        record_problem(request, "oauth", "연결 후 저장소 목록 조회", error)
        messages.warning(
            request,
            "GitHub 계정은 연결됐지만 저장소 목록을 확인하지 못했습니다. 프로필에서 접근 가능한 저장소를 다시 확인하세요.",
            extra_tags="integration-help",
        )
    else:
        clear_problem(request, "oauth")
    gh_services.backfill_actor(identity)
    messages.success(request, "GitHub를 연결했습니다.")
    return redirect("profile")


@login_required
@require_POST
def github_refresh(request):
    _gh_enabled_or_404()
    identity = getattr(request.user, "github", None)
    if identity is None:
        raise Http404
    try:
        gh_services.sync_repos(identity)
        clear_problem(request, "oauth")
        messages.success(request, "접근 가능 저장소를 다시 확인했습니다.")
    except (GitHubError, ServiceError) as error:
        record_problem(request, "oauth", "접근 가능한 저장소 다시 확인", error)
        messages.error(
            request,
            "접근 가능한 저장소를 다시 확인하지 못했습니다. 기존 목록은 유지됩니다. 해결 절차를 확인하세요.",
            extra_tags="integration-help",
        )
    return redirect("profile")


@login_required
@require_POST
def github_unlink(request):
    _gh_enabled_or_404()
    GitHubIdentity.objects.filter(user=request.user).delete()
    messages.success(request, "GitHub 연결을 끊었습니다.")
    return redirect("profile")


# ---------- 프로젝트: 저장소 연결 탭 ----------


def _repo_teams(conn):
    """설치 토큰으로 저장소 접근 팀을 읽는다. 권한이 없으면 표 대신 안내만 보인다."""
    inst = getattr(conn.project.org, "github", None)
    if inst is None:
        return {"teams": None, "status": "앱 설치 정보 없음"}
    try:
        token = client.installation_token(inst.installation_id)
        return {
            "teams": list(client.paginate(f"/repos/{conn.full_name}/teams", token)),
            "status": "조회 성공",
        }
    except GitHubError as error:
        status = f"HTTP {error.status}" if error.status else "네트워크 연결 실패"
        return {"teams": None, "status": status}


@login_required
def project_repo(request, project_id):
    _gh_enabled_or_404()
    project = project_or_404(request.user, project_id)
    error = shared_warning = None
    if request.method == "POST":
        try:
            gh_services.connect_repo(
                project=project,
                url=request.POST.get("url", ""),
                actor=request.user,
                confirm_shared=request.POST.get("confirm_shared") == "1",
            )
            return redirect("project_repo", project_id=project.pk)
        except ServiceError as e:
            if "confirm_shared" in e.errors:
                shared_warning = e.errors["confirm_shared"]
            else:
                error = " ".join(e.errors.values())
    state = gh_services.repo_state(request.user, project)
    ctx = {
        "project": project,
        "tab": "repo",
        "state": state,
        "is_admin": can_admin(request.user, project.org),
        "can_settings": _can_edit_project_settings(request.user, project),
        "error": error,
        "shared_warning": shared_warning,
        "pending_url": request.POST.get("url", "") if shared_warning else "",
        "user_install": gh_services.is_user_install(project.org),
    }
    if state["state"] == "none":
        if getattr(project.org, "github", None) is None:
            ctx["repo_choices_status"] = (
                "이 조직에 GitHub 앱이 설치되지 않았습니다. 조직 관리자에게 설치를 요청하세요."
            )
            ctx["org_repos"] = []
        else:
            try:
                ctx["org_repos"] = _pickable_repos(project, request.user, strict=True)
                ctx["repo_choices_status"] = (
                    "저장소 목록을 확인했습니다."
                    if ctx["org_repos"]
                    else "조회는 성공했지만 앱에 보이는 저장소가 없습니다. 설치 대상 저장소를 확인하세요."
                )
                clear_problem(request, "repositories")
            except GitHubError as error:
                ctx["org_repos"] = []
                ctx["repo_choices_status"] = (
                    "저장소 후보 조회에 실패했습니다. 주소를 직접 입력할 수 있지만 연결 시 접근 권한을 다시 확인합니다."
                )
                record_problem(
                    request, "repositories", "저장소 후보 조회", error, target=project.name
                )
    if state["state"] == "ok":
        conn = state["conn"]
        gh_services.sync_issues_if_stale(conn)
        ctx["issues"] = conn.issues.filter(state="open")[:50]
        ctx["events"] = conn.events.select_related("task")[:50]
        ctx["open_tasks"] = project.tasks.filter(status__in=Task.OPEN).order_by("-id")[:50]
        ctx["hook"] = gh_hooks.status(project)
        if ctx["can_settings"] and ctx["hook"].get("state") in (None, "error"):
            ctx["hook_blockers"] = gh_hooks.blockers(request.user, project)
        # 개인 계정 저장소에는 팀이 없다. 조회하지 않고 화면에서도 접근 팀 칸을 숨긴다.
        if not ctx["user_install"]:
            team_result = _repo_teams(conn)
            ctx["repo_teams"] = team_result["teams"]
            ctx["repo_teams_status"] = team_result["status"]
            ctx["repo_teams_prompt"] = (
                f"ProjectManager의 GitHub 접근 팀 조회를 확인해 주세요. 저장소: {conn.full_name}. "
                f"조회 결과: {team_result['status']}. "
                "GET /repos/{owner}/{repo}/teams는 Repository Administration 읽기 권한이 필요합니다. "
                "현재 앱의 권한, 설치 승인 상태, 저장소 선택 범위와 조직 정책을 확인하고, "
                "권한을 유지할 때의 대안과 읽기 권한을 추가할 때의 절차를 설명해 주세요. "
                "HTTP 상태만으로 원인을 단정하지 말아 주세요. 토큰이나 개인키는 공유하지 않겠습니다."
            )
    return render(request, "projects/repo.html", ctx)


def _pickable_repos(project, user, *, strict=False):
    """조직 설치가 접근할 수 있는 저장소 + 이미 다른 프로젝트에 연결됐으면 그 표시.

    같은 저장소를 두 프로젝트에 붙일지는 connect_repo가 판단한다 — 여기서는 고르지 못하게
    막지 않고 이미 연결됐다는 사실만 보여 준다.
    """
    repos = gh_services.installation_repos(project.org, user, strict=strict)
    taken = dict(
        RepoConnection.objects.filter(project__org=project.org)
        .exclude(project=project)
        .values_list("full_name", "project__name")
    )
    for r in repos:
        other = taken.get(r["full_name"])
        r["label"] = f"{r['full_name']} (이미 연결됨 · {other})" if other else r["full_name"]
    return repos


@login_required
@require_POST
def repo_disconnect(request, project_id):
    _gh_enabled_or_404()
    project = project_or_404(request.user, project_id)
    conn = getattr(project, "repo", None)
    had_hook = conn is not None and (conn.discord_hook or {}).get("state") == "active"
    try:
        if gh_services.disconnect_repo(project=project, actor=request.user):
            messages.success(request, "저장소 연결을 해제했습니다.")
            if had_hook:
                messages.info(
                    request,
                    "GitHub 저장소의 Discord 알림 웹훅도 지웠습니다. Discord 채널에 남은 웹훅은 더 이상 "
                    "알림을 받지 않습니다. 필요하면 채널 설정 → 연동에서 지워 주세요.",
                )
    except ServiceError as e:
        messages.error(request, " ".join(e.errors.values()))
    return redirect("project_repo", project_id=project.pk)


@login_required
@require_POST
def repo_settings(request, project_id):
    _gh_enabled_or_404()
    project = project_or_404(request.user, project_id)
    conn = getattr(project, "repo", None)
    if conn is None:
        raise Http404
    changes = {"import_label": request.POST.get("import_label", "")[:50]}
    for field in gh_services.REPO_SETTING_FIELDS[1:]:
        changes[field] = request.POST.get(field) == "on"
    try:
        gh_services.update_repo_settings(conn, changes, actor=request.user)
        messages.success(request, "저장소 설정을 저장했습니다.")
    except ServiceError as e:
        messages.error(request, " ".join(e.errors.values()))
    return redirect("project_repo", project_id=project.pk)


@login_required
@require_POST
def repo_discord_hook(request, project_id):
    """GitHub 알림을 Discord 프로젝트 채널로: 설정·이벤트 수정·해제(github/hooks.py)."""
    _gh_enabled_or_404()
    project = project_or_404(request.user, project_id)
    action = request.POST.get("action", "")
    events = request.POST.getlist("events")
    try:
        if action == "setup":
            gh_hooks.request_setup(project, events, actor=request.user)
            messages.success(
                request, "요청했습니다. 봇이 1분 안에 Discord 웹훅을 만들고 GitHub에 등록합니다."
            )
        elif action == "events":
            gh_hooks.update_events(project, events, actor=request.user)
            messages.success(request, "웹훅 이벤트를 저장했습니다.")
        elif action == "remove":
            gh_hooks.remove(project, actor=request.user)
            messages.success(request, "GitHub 알림 웹훅을 해제했습니다.")
        else:
            raise Http404
    except ServiceError as e:
        messages.error(request, " ".join(e.errors.values()))
    return redirect("project_repo", project_id=project.pk)


@login_required
@require_POST
def repo_issues_sync(request, project_id):
    _gh_enabled_or_404()
    project = project_or_404(request.user, project_id)
    conn = _viewable_repo(request.user, project)
    try:
        n = gh_services.sync_issues(conn)
        messages.success(request, f"열린 이슈 {n}건을 확인했습니다.")
    except (ServiceError, GitHubError) as error:
        record_problem(request, "issues", "프로젝트 이슈 동기화", error, target=conn.full_name)
        messages.error(
            request,
            "이슈 동기화에 실패했습니다. 기존 태스크는 유지됩니다. 설치·저장소 범위와 조회 상태를 확인한 뒤 다시 시도하세요.",
            extra_tags="integration-help",
        )
    return redirect("project_repo", project_id=project.pk)


@login_required
@require_POST
def repo_issue_import(request, project_id, number):
    _gh_enabled_or_404()
    project = project_or_404(request.user, project_id)
    conn = _viewable_repo(request.user, project)
    issue = conn.issues.filter(number=number).first()
    if issue is None:
        raise Http404
    if issue.task_id is None:
        task = gh_services.import_issue(issue, request.user)
        messages.success(request, f"태스크 {task.number}로 가져왔습니다.")
    return redirect("project_repo", project_id=project.pk)


@login_required
def org_issues(request, org_id):
    """조직 이슈 뷰어. 연결된 저장소 전부의 열린 이슈를 한 화면에서 보고 내 태스크로 가져간다.

    저장소 탭은 저장소 하나만 보여 준다 — "지금 내가 집을 수 있는 일"은 조직 단위로 봐야 보인다.
    """
    _gh_enabled_or_404()
    org = org_or_404(request.user, org_id)
    repo_id = request.GET.get("repo") or ""
    state = request.GET.get("state") or "todo"  # todo=아직 안 가져온 것 | done | all
    query = (request.GET.get("q") or "").strip()
    imported = {"todo": False, "done": True}.get(state)
    # GitHub에서 온 것은 GitHub 권한으로 본다 — 볼 수 없는 저장소의 이슈는 목록에서 뺀다.
    repos = [
        c
        for c in RepoConnection.objects.filter(project__org=org).select_related("project")
        if gh_services.can_view_repo(request.user, c.full_name)
    ]
    issues = gh_services.org_issues(
        org, repo_id=int(repo_id) if repo_id.isdecimal() else None, imported=imported, query=query
    ).filter(connection__in=repos)
    return render(
        request,
        "github/issues.html",
        {
            "org": org,
            "tab": "issues",
            "issues": issues,
            "repos": repos,
            "repo_id": repo_id,
            "state": state,
            "q": query,
            "is_admin": can_admin(request.user, org),
        },
    )


@login_required
@require_POST
def org_issues_sync(request, org_id):
    _gh_enabled_or_404()
    org = org_or_404(request.user, org_id)
    failures = []
    n, failed = gh_services.sync_org_issues(org, failures=failures)
    if failures:
        names = ", ".join(
            f"{item['repo']} ({'HTTP ' + str(item['status']) if item['status'] else '설치·연결 상태 확인 필요'})"
            for item in failures
        )
        record_problem(request, "issues", "조직 이슈 동기화 일부 또는 전체 실패", target=names)
        messages.warning(
            request,
            "확인하지 못한 저장소: " + names + ". 해당 프로젝트에서 다시 동기화하세요.",
            extra_tags="integration-help",
        )
    if failed:
        total = RepoConnection.objects.filter(project__org=org).count()
        if failed >= total:
            messages.error(
                request, f"연결된 저장소 {failed}곳 모두에서 이슈를 확인하지 못했습니다."
            )
        else:
            messages.warning(
                request,
                f"일부 저장소만 확인했습니다. 열린 이슈 {n}건을 확인했고, {failed}곳은 확인하지 못했습니다.",
            )
    else:
        messages.success(request, f"열린 이슈 {n}건을 확인했습니다.")
    return redirect(f"{reverse('org_issues', args=[org.pk])}?{request.POST.get('back', '')}")


@login_required
@require_POST
def org_issue_import(request, org_id, issue_id):
    """이슈 하나를 내 태스크로. 담당자는 누른 사람이다."""
    _gh_enabled_or_404()
    org = org_or_404(request.user, org_id)
    issue = RepoIssue.objects.filter(pk=issue_id, connection__project__org=org).first()
    if issue is None or not gh_services.can_view_repo(request.user, issue.connection.full_name):
        raise Http404
    if issue.task_id is None:
        task = gh_services.import_issue(issue, request.user)
        messages.success(request, f"태스크 {task.number}로 가져왔습니다.")
    else:
        messages.info(request, f"이미 태스크 {issue.task.number}로 가져온 이슈입니다.")
    return redirect(f"{reverse('org_issues', args=[org.pk])}?{request.POST.get('back', '')}")


@login_required
@require_POST
def repo_event_link(request, project_id, event_id):
    """미매칭 이벤트(예: 번호 없는 커밋)를 손으로 태스크에 연결한다."""
    _gh_enabled_or_404()
    project = project_or_404(request.user, project_id)
    conn = _viewable_repo(request.user, project)
    event = conn.events.filter(pk=event_id).first()
    if event is None:
        raise Http404
    task_id = request.POST.get("task_id", "")
    task = project.tasks.filter(pk=task_id).first() if task_id.isdecimal() else None
    if task is None:
        messages.error(request, "연결할 태스크를 고르세요.")
    else:
        try:
            gh_services.link_event(event, task, actor=request.user)
        except ServiceError as e:
            messages.error(request, " ".join(e.errors.values()))
    return redirect("project_repo", project_id=project.pk)


@login_required
def project_issues(request, project_id):
    """프로젝트 이슈 뷰어. 조직 이슈 뷰어와 같은 템플릿을 쓰되 이 프로젝트의 저장소로만 좁힌다.

    저장소 선택 드롭다운은 의미가 없으므로(프로젝트에는 저장소가 하나뿐이다) 템플릿이
    `project`가 있으면 숨긴다. 필터링은 `org_issues`에 이 저장소의 연결 pk를 repo_id로
    넘겨 재사용한다 — 새 조회 함수를 만들지 않는다.
    """
    _gh_enabled_or_404()
    project = project_or_404(request.user, project_id)
    conn = _viewable_repo(request.user, project)
    state = request.GET.get("state") or "todo"  # todo=아직 안 가져온 것 | done | all
    query = (request.GET.get("q") or "").strip()
    imported = {"todo": False, "done": True}.get(state)
    issues = gh_services.org_issues(project.org, repo_id=conn.pk, imported=imported, query=query)
    return render(
        request,
        "github/issues.html",
        {
            "org": project.org,
            "project": project,
            "tab": "issues",
            "issues": issues,
            "repo_id": "",
            "state": state,
            "q": query,
            "is_admin": can_admin(request.user, project.org),
        },
    )


@login_required
@require_POST
def project_issues_sync(request, project_id):
    _gh_enabled_or_404()
    project = project_or_404(request.user, project_id)
    conn = _viewable_repo(request.user, project)
    try:
        n = gh_services.sync_issues(conn)
        messages.success(request, f"열린 이슈 {n}건을 확인했습니다.")
    except (ServiceError, GitHubError) as error:
        record_problem(request, "issues", "프로젝트 이슈 동기화", error, target=conn.full_name)
        messages.error(
            request,
            "이슈 동기화에 실패했습니다. 기존 태스크는 유지됩니다. 설치·저장소 범위와 조회 상태를 확인한 뒤 다시 시도하세요.",
            extra_tags="integration-help",
        )
    back = f"{reverse('project_issues', args=[project.pk])}?{request.POST.get('back', '')}"
    return redirect(back)


@login_required
@require_POST
def project_issue_import(request, project_id, issue_id):
    """이슈 하나를 내 태스크로. 담당자는 누른 사람이다."""
    _gh_enabled_or_404()
    project = project_or_404(request.user, project_id)
    conn = _viewable_repo(request.user, project)
    issue = conn.issues.filter(pk=issue_id).first()
    if issue is None:
        raise Http404
    if issue.task_id is None:
        task = gh_services.import_issue(issue, request.user)
        messages.success(request, f"태스크 {task.number}로 가져왔습니다.")
    else:
        messages.info(request, f"이미 태스크 {issue.task.number}로 가져온 이슈입니다.")
    back = f"{reverse('project_issues', args=[project.pk])}?{request.POST.get('back', '')}"
    return redirect(back)


# ---------- 태스크 패널: GitHub 블록 ----------


@login_required
@require_POST
def git_issue(request, task_id):
    _gh_enabled_or_404()
    task = task_or_404(request.user, task_id)
    if gh_services.task_repo_state(request.user, task)["state"] != "ok":
        raise Http404
    conn = gh_services.task_repo(task)
    number = request.POST.get("number", "")
    issue = conn.issues.filter(number=number).first() if number.isdecimal() else None
    if issue is not None:
        try:
            gh_services.link_issue(task, issue)
        except ServiceError as e:
            return _panel(request, task, error=_gh_write_error(e))
    return _panel(request, task)


@login_required
@require_POST
def git_branch(request, task_id):
    _gh_enabled_or_404()
    task = task_or_404(request.user, task_id)
    if gh_services.task_repo_state(request.user, task)["state"] != "ok":
        raise Http404
    conn = gh_services.task_repo(task)
    branch = request.POST.get("branch", "").strip()[:200]
    if branch:
        link, _ = TaskGitLink.objects.get_or_create(task=task, defaults={"connection": conn})
        link.connection = conn
        link.branch = branch
        link.save()
    return _panel(request, task)


@login_required
@require_POST
def git_unlink(request, task_id):
    _gh_enabled_or_404()
    task = task_or_404(request.user, task_id)
    if gh_services.task_repo_state(request.user, task)["state"] != "ok":
        raise Http404
    gh_services.unlink(task, request.POST.get("what") or "all")
    return _panel(request, task)


def _gh_write_error(e) -> str:
    return e.message if isinstance(e, GitHubError) else " ".join(e.errors.values())


@login_required
@require_POST
def git_issue_create(request, task_id):
    _gh_enabled_or_404()
    task = task_or_404(request.user, task_id)
    if gh_services.task_repo_state(request.user, task)["state"] != "ok":
        raise Http404
    try:
        gh_writes.create_issue(task, actor=request.user)
    except (ServiceError, GitHubError) as e:
        return _panel(request, task, error=_gh_write_error(e))
    return _panel(request, task)


@login_required
@require_POST
def git_branch_create(request, task_id):
    _gh_enabled_or_404()
    task = task_or_404(request.user, task_id)
    if gh_services.task_repo_state(request.user, task)["state"] != "ok":
        raise Http404
    name = request.POST.get("name", "").strip() or gh_writes.default_branch_name(task)
    try:
        gh_writes.create_branch(task, name, actor=request.user)
    except (ServiceError, GitHubError) as e:
        return _panel(request, task, error=_gh_write_error(e))
    return _panel(request, task)


@login_required
@require_POST
def git_issue_close(request, task_id):
    _gh_enabled_or_404()
    task = task_or_404(request.user, task_id)
    if gh_services.task_repo_state(request.user, task)["state"] != "ok":
        raise Http404
    # 버튼은 완료·열린 이슈일 때만 그려지지만, 패널이 열린 채 다른 곳에서 상태가 바뀌면
    # 여기로 올 수 있다. 404로 패널을 깨지 말고 왜 못 닫는지 알려준다.
    link = getattr(task, "git", None)
    if link is None or not link.issue_number:
        return _panel(request, task, error="연결된 이슈가 없습니다.")
    if task.status != "done":
        return _panel(request, task, error="태스크를 완료하기 전에는 이슈를 닫을 수 없습니다.")
    if link.issue_state != "open":
        return _panel(request, task, error="이미 닫힌 이슈입니다.")
    try:
        gh_writes.close_issue(task, actor=request.user)
    except (ServiceError, GitHubError) as e:
        return _panel(request, task, error=_gh_write_error(e))
    return _panel(request, task)


@login_required
@require_POST
def git_project(request, task_id):
    """연동 프로젝트 고르기(§3.3). 연결 프로젝트가 있는 태스크만 뜻이 있다. 빈 값이면 연동 끔."""
    _gh_enabled_or_404()
    task = task_or_404(request.user, task_id)
    pid = request.POST.get("project", "")
    project = None
    if pid:
        project = visible_projects(request.user, task.project.org).filter(pk=pid).first()
        if project is None:
            raise Http404
    try:
        task = ts.update_task(
            task,
            {"git_project": project},
            actor=request.user,
            source="web",
            expected_version=version_of(request),
        )
    except ServiceError as e:
        return _panel(request, task, error=" ".join(e.errors.values()))
    except ConflictError as e:
        return _panel(request, e.latest, error=CONFLICT_MSG)
    return _panel(request, task)
