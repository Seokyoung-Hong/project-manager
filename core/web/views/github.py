"""GitHub 화면. 업무 규칙은 전부 github/services.py에 있다 — 여기서는 부르기만 한다."""

import secrets
from urllib.parse import urlencode

from django.conf import settings
from django.contrib import messages
from django.contrib.auth.decorators import login_required
from django.http import Http404
from django.shortcuts import redirect, render
from django.views.decorators.http import require_POST

from common.errors import ServiceError
from github import client
from github import services as gh_services
from github import writes as gh_writes
from github.client import GitHubError
from github.models import GitHubIdentity, TaskGitLink
from tasks import services as ts
from tasks.models import Task

from .common import can_admin, not_admin, org_or_404, project_or_404, task_or_404
from .tasks import _panel


def _gh_enabled_or_404():
    if not settings.GITHUB_ENABLED:
        raise Http404


# ---------- 조직: 앱 설치 ----------


@login_required
def org_github(request, org_id):
    _gh_enabled_or_404()
    org = org_or_404(request.user, org_id)
    if denied := not_admin(request, org):
        return denied
    projects = org.projects.filter(is_archived=False).select_related("repo").order_by("name")
    return render(
        request,
        "orgs/github.html",
        {
            "org": org,
            "install": getattr(org, "github", None),
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
    if denied := not_admin(request, org):
        return denied
    request.session["gh_install_org"] = org.pk
    state = secrets.token_urlsafe(16)
    request.session["gh_state"] = state
    url = f"https://github.com/apps/{settings.GITHUB_APP_SLUG}/installations/new?state={state}"
    return redirect(url)


@login_required
def github_installed(request):
    """GitHub가 되돌려 주는 곳(앱 설정의 Setup URL). ?installation_id=&setup_action=&state="""
    _gh_enabled_or_404()
    if request.GET.get("state") != request.session.pop("gh_state", None):
        raise Http404
    org_id = request.session.pop("gh_install_org", None)
    org = org_or_404(request.user, org_id)
    if denied := not_admin(request, org):
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


@login_required
def github_connect(request):
    _gh_enabled_or_404()
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
def github_callback(request):
    _gh_enabled_or_404()
    if request.GET.get("state") != request.session.pop("gh_oauth_state", None):
        raise Http404
    code = request.GET.get("code", "")
    try:
        if not code:
            raise GitHubError(400, "코드가 없습니다.")
        data = client.exchange_code(code)
        info = client.request("GET", "/user", data["access_token"])
    except GitHubError:
        messages.error(request, "GitHub 연결에 실패했습니다.")
        return redirect("profile")
    identity, _ = GitHubIdentity.objects.update_or_create(
        user=request.user,
        defaults={"github_id": info["id"], "login": info["login"][:100]},
    )
    gh_services._store_tokens(identity, data)
    try:
        gh_services.sync_repos(identity)
    except (GitHubError, ServiceError):
        pass
    gh_services.backfill_actor(identity)
    messages.success(request, "GitHub를 연결했습니다.")
    return redirect("profile")


@login_required
@require_POST
def github_refresh(request):
    identity = getattr(request.user, "github", None)
    if identity is None:
        raise Http404
    try:
        gh_services.sync_repos(identity)
        messages.success(request, "접근 가능 저장소를 다시 확인했습니다.")
    except (GitHubError, ServiceError):
        messages.error(request, "다시 확인하지 못했습니다.")
    return redirect("profile")


@login_required
@require_POST
def github_unlink(request):
    GitHubIdentity.objects.filter(user=request.user).delete()
    messages.success(request, "GitHub 연결을 끊었습니다.")
    return redirect("profile")


# ---------- 프로젝트: 저장소 연결 탭 ----------


def _repo_teams(conn):
    """설치 토큰으로 저장소 접근 팀을 읽는다. 권한이 없으면 표 대신 안내만 보인다."""
    inst = getattr(conn.project.org, "github", None)
    if inst is None:
        return None
    try:
        token = client.installation_token(inst.installation_id)
        return client.request("GET", f"/repos/{conn.full_name}/teams", token)
    except GitHubError:
        return None


@login_required
def project_repo(request, project_id):
    project = project_or_404(request.user, project_id)
    error = None
    if request.method == "POST":
        try:
            gh_services.connect_repo(
                project=project, url=request.POST.get("url", ""), actor=request.user
            )
            return redirect("project_repo", project_id=project.pk)
        except ServiceError as e:
            error = " ".join(e.errors.values())
    state = gh_services.repo_state(request.user, project)
    ctx = {
        "project": project,
        "tab": "repo",
        "state": state,
        "is_admin": can_admin(request.user, project.org),
        "error": error,
    }
    if state["state"] == "ok":
        conn = state["conn"]
        gh_services.sync_issues_if_stale(conn)
        ctx["issues"] = conn.issues.filter(state="open")[:50]
        ctx["events"] = conn.events.select_related("task")[:50]
        ctx["repo_teams"] = _repo_teams(conn)
        ctx["open_tasks"] = project.tasks.filter(status__in=Task.OPEN).order_by("-id")[:50]
    return render(request, "projects/repo.html", ctx)


@login_required
@require_POST
def repo_disconnect(request, project_id):
    project = project_or_404(request.user, project_id)
    conn = getattr(project, "repo", None)
    if conn is not None:
        conn.delete()
        messages.success(request, "저장소 연결을 해제했습니다.")
    return redirect("project_repo", project_id=project.pk)


@login_required
@require_POST
def repo_settings(request, project_id):
    project = project_or_404(request.user, project_id)
    conn = getattr(project, "repo", None)
    if conn is None:
        raise Http404
    conn.import_label = request.POST.get("import_label", "")[:50]
    conn.auto_import = request.POST.get("auto_import") == "on"
    for field in ("rule_issue", "rule_branch", "rule_commit", "rule_pr", "rule_merge"):
        setattr(conn, field, request.POST.get(field) == "on")
    conn.save()
    messages.success(request, "저장소 설정을 저장했습니다.")
    return redirect("project_repo", project_id=project.pk)


@login_required
@require_POST
def repo_issues_sync(request, project_id):
    project = project_or_404(request.user, project_id)
    conn = getattr(project, "repo", None)
    if conn is None:
        raise Http404
    try:
        n = gh_services.sync_issues(conn)
        messages.success(request, f"열린 이슈 {n}건을 확인했습니다.")
    except (ServiceError, GitHubError):
        messages.error(request, "이슈를 가져오지 못했습니다.")
    return redirect("project_repo", project_id=project.pk)


@login_required
@require_POST
def repo_issue_import(request, project_id, number):
    project = project_or_404(request.user, project_id)
    conn = getattr(project, "repo", None)
    if conn is None:
        raise Http404
    issue = conn.issues.filter(number=number).first()
    if issue is None:
        raise Http404
    if issue.task_id is None:
        task = ts.create_task(
            project=project,
            title=issue.title[:200],
            actor=request.user,
            source="web",
            assignee=request.user,
            no_due_reason="GitHub 이슈로 가져옴",
        )
        issue.task = task
        issue.save(update_fields=["task"])
        link, _ = TaskGitLink.objects.get_or_create(task=task, defaults={"connection": conn})
        link.connection = conn
        link.issue_number = issue.number
        link.issue_title = issue.title
        link.issue_state = issue.state
        link.save(update_fields=["connection", "issue_number", "issue_title", "issue_state"])
        messages.success(request, f"태스크 {task.number}로 가져왔습니다.")
    return redirect("project_repo", project_id=project.pk)


@login_required
@require_POST
def repo_event_link(request, project_id, event_id):
    """미매칭 이벤트(예: 번호 없는 커밋)를 손으로 태스크에 연결한다."""
    project = project_or_404(request.user, project_id)
    conn = getattr(project, "repo", None)
    if conn is None:
        raise Http404
    event = conn.events.filter(pk=event_id).first()
    if event is None:
        raise Http404
    task = project.tasks.filter(pk=request.POST.get("task_id")).first()
    if task is not None:
        event.task = task
        event.save(update_fields=["task"])
    return redirect("project_repo", project_id=project.pk)


# ---------- 태스크 패널: GitHub 블록 ----------


@login_required
@require_POST
def git_issue(request, task_id):
    task = task_or_404(request.user, task_id)
    if gh_services.repo_state(request.user, task.project)["state"] != "ok":
        raise Http404
    conn = task.project.repo
    issue = conn.issues.filter(number=request.POST.get("number")).first()
    if issue is not None:
        link, _ = TaskGitLink.objects.get_or_create(task=task, defaults={"connection": conn})
        link.connection = conn
        link.issue_number = issue.number
        link.issue_title = issue.title
        link.issue_state = issue.state
        link.save()
        issue.task = task
        issue.save(update_fields=["task"])
    return _panel(request, task)


@login_required
@require_POST
def git_branch(request, task_id):
    task = task_or_404(request.user, task_id)
    if gh_services.repo_state(request.user, task.project)["state"] != "ok":
        raise Http404
    conn = task.project.repo
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
    """what=issue|branch|pr이면 그 단계만, 없으면 전부 끊는다."""
    task = task_or_404(request.user, task_id)
    if gh_services.repo_state(request.user, task.project)["state"] != "ok":
        raise Http404
    gh_services.unlink(task, request.POST.get("what") or "all")
    return _panel(request, task)


def _gh_write_error(e) -> str:
    return e.message if isinstance(e, GitHubError) else " ".join(e.errors.values())


@login_required
@require_POST
def git_issue_create(request, task_id):
    task = task_or_404(request.user, task_id)
    if gh_services.repo_state(request.user, task.project)["state"] != "ok":
        raise Http404
    try:
        gh_writes.create_issue(task, actor=request.user)
    except (ServiceError, GitHubError) as e:
        return _panel(request, task, error=_gh_write_error(e))
    return _panel(request, task)


@login_required
@require_POST
def git_branch_create(request, task_id):
    task = task_or_404(request.user, task_id)
    if gh_services.repo_state(request.user, task.project)["state"] != "ok":
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
    task = task_or_404(request.user, task_id)
    if gh_services.repo_state(request.user, task.project)["state"] != "ok":
        raise Http404
    # 버튼은 완료·열린 이슈일 때만 그려지지만, 패널이 열린 채 다른 곳에서 상태가 바뀌면
    # 여기로 올 수 있다. 404로 패널을 깨지 말고 왜 못 닫는지 알려준다.
    link = getattr(task, "git", None)
    if link is None or not link.issue_number:
        return _panel(request, task, error="연결된 이슈가 없어요.")
    if task.status != "done":
        return _panel(request, task, error="태스크가 완료되기 전에는 이슈를 닫을 수 없어요.")
    if link.issue_state != "open":
        return _panel(request, task, error="이미 닫힌 이슈예요.")
    try:
        gh_writes.close_issue(task, actor=request.user)
    except (ServiceError, GitHubError) as e:
        return _panel(request, task, error=_gh_write_error(e))
    return _panel(request, task)
