"""GitHub에 쓰는 동작. **여기 있는 함수는 전부 누른 사람의 토큰을 쓴다.**

설치 토큰으로 쓰지 않는 이유가 셋이다.

- GitHub 쪽 기록이 그 사람 이름으로 남는다. 봇 이름으로 남지 않는다.
- 그 사람이 GitHub에서 못 하는 일은 GitHub가 거부한다. PM이 권한 규칙을 따로 구현하지 않는다.
- 설치 토큰이 유출돼도 쓰기에 쓰이지 않는다.

`client.installation_token`을 이 파일에서 부르지 않는다. 테스트가 그것을 고정한다.

두 번째 원칙은 **PM이 먼저, GitHub는 그 다음**이다. PM 데이터를 먼저 바꾸고 GitHub에 반영하되,
GitHub가 거부하면 PM 변경은 그대로 두고 경고만 보여 준다. 되돌리기 애매한 절반 성공을
만들지 않는다.
"""

from django.utils import timezone
from django.utils.text import slugify

from common.errors import ServiceError

from . import client
from .client import GitHubError
from .models import TaskGitLink
from .services import user_token


def _org_login(org) -> str:
    inst = getattr(org, "github", None)
    if inst is None:
        raise ServiceError({"github": "이 조직에 GitHub 앱이 설치되어 있지 않습니다."})
    if inst.account_type == "User":
        # 개인 계정에는 /orgs/*가 없다(404). 부르기 전에 막는다 — 팀·멤버 함수가 전부 여기를 지난다.
        raise ServiceError({"github": "개인 계정 설치에서는 GitHub 조직·팀 기능을 쓸 수 없습니다."})
    return inst.account_login


def _actor_token(actor) -> str:
    """누른 사람의 토큰. 없으면 아무것도 하지 않는다."""
    identity = getattr(actor, "github", None)
    if identity is None:
        raise ServiceError({"github": "GitHub를 연결해야 할 수 있습니다."})
    return user_token(identity)


def _login_of(user) -> str:
    identity = getattr(user, "github", None)
    return identity.login if identity else ""


def try_write(fn, *args, **kwargs) -> str:
    """GitHub 반영을 시도하고 실패하면 사람이 읽을 경고 문자열을 돌려준다.

    PM 변경은 이미 끝났다. 여기서 예외를 올리면 절반만 바뀐 상태가 된다.
    """
    try:
        fn(*args, **kwargs)
        return ""
    except GitHubError as e:
        status = f"HTTP {e.status}" if e.status else "네트워크 연결 실패"
        return f"GitHub에 반영하지 못했습니다 ({status}). PM에만 적용됐습니다. PM 작업을 반복하지 말고 연동 문제 해결에서 복구 방법을 확인하세요."
    except ServiceError as e:
        return " ".join(str(v) for v in e.errors.values()) + " PM에만 적용됐습니다."


# ---------- 조직과 팀 ----------


def invite_to_org(org, login: str, *, actor):
    client.request(
        "PUT",
        f"/orgs/{_org_login(org)}/memberships/{login}",
        _actor_token(actor),
        body={"role": "member"},
    )


def remove_from_org(org, login: str, *, actor):
    client.request("DELETE", f"/orgs/{_org_login(org)}/members/{login}", _actor_token(actor))


def list_org_teams(org, *, actor) -> list[dict]:
    return client.request("GET", f"/orgs/{_org_login(org)}/teams?per_page=100", _actor_token(actor))


def create_gh_team(team, *, actor) -> dict:
    return client.request(
        "POST",
        f"/orgs/{_org_login(team.org)}/teams",
        _actor_token(actor),
        body={"name": team.name, "description": team.purpose, "privacy": "closed"},
    )


def rename_gh_team(link, team, *, actor):
    data = client.request(
        "PATCH",
        f"/orgs/{_org_login(team.org)}/teams/{link.slug}",
        _actor_token(actor),
        body={"name": team.name, "description": team.purpose},
    )
    if data and data.get("slug"):
        link.slug = data["slug"]
        link.name = data.get("name", team.name)
        link.save(update_fields=["slug", "name"])


def set_gh_team_member(link, org, login: str, *, actor, add: bool):
    path = f"/orgs/{_org_login(org)}/teams/{link.slug}/memberships/{login}"
    token = _actor_token(actor)
    if add:
        try:
            membership = client.request("GET", path, token)
        except GitHubError as error:
            if error.status != 404:
                raise
        else:
            if membership and membership.get("state") in ("active", "pending"):
                return
        client.request("PUT", path, token, body={"role": "member"})
    else:
        client.request("DELETE", path, token)


def reconcile_team(team, *, actor, on_result=None) -> tuple[int, list[str]]:
    """PM 팀 멤버를 GitHub 팀에 맞춘다. 뺄 사람은 건드리지 않는다."""
    if not team.dev_tools:
        raise ServiceError({"team": "개발 도구를 끈 팀입니다."})
    link = getattr(team, "github", None)
    if link is None:
        raise ServiceError({"github": "연결된 GitHub 팀이 없습니다."})
    done, warns = 0, []
    for user in team.members.filter(is_active=True):
        login = _login_of(user)
        if not login:
            warns.append(f"{user.display_name}: GitHub 미연결")
            continue
        w = try_write(set_gh_team_member, link, team.org, login, actor=actor, add=True)
        if on_result is not None:
            on_result(user, login, w)
        if w:
            warns.append(f"{user.display_name}: {w}")
        else:
            done += 1
    link.synced_at = timezone.now()
    link.save(update_fields=["synced_at"])
    return done, warns


# ---------- 이슈와 브랜치 ----------


def _task_conn(task):
    """연동 프로젝트의 저장소(§3.3). 연결 프로젝트가 있는데 고르지 않았으면 쓰기를 거절한다."""
    from .services import task_repo

    conn = task_repo(task)
    if conn is None:
        raise ServiceError({"github": "연동 프로젝트를 먼저 선택하세요."})
    return conn


def create_issue(task, *, actor, body="") -> dict:
    conn = _task_conn(task)
    data = client.request(
        "POST",
        f"/repos/{conn.full_name}/issues",
        _actor_token(actor),
        body={"title": f"{task.title} ({task.number})", "body": body or task.description},
    )
    link, _ = TaskGitLink.objects.get_or_create(task=task, defaults={"connection": conn})
    link.issue_number, link.issue_title, link.issue_state = data["number"], data["title"], "open"
    link.save(update_fields=["issue_number", "issue_title", "issue_state"])
    return data


def close_issue(task, *, actor):
    """PM에서 손으로 완료했을 때만 쓴다. 머지로 닫히는 건 GitHub가 Closes #N으로 한다."""
    link = task.git
    client.request(
        "PATCH",
        f"/repos/{link.connection.full_name}/issues/{link.issue_number}",
        _actor_token(actor),
        body={"state": "closed"},
    )
    link.issue_state = "closed"
    link.save(update_fields=["issue_state"])


def create_branch(task, name: str, *, actor) -> str:
    """기본 브랜치 끝에서 새 브랜치를 만든다.

    이름에 태스크 번호가 들어가므로 나중에 push·PR이 자동으로 이 태스크에 붙는다.
    """
    conn = _task_conn(task)
    token = _actor_token(actor)
    name = (name or "").strip().lstrip("/")
    if not name or ".." in name or name.endswith("/") or " " in name:
        raise ServiceError({"branch": "쓸 수 없는 브랜치 이름입니다."})
    repo = client.request("GET", f"/repos/{conn.full_name}", token)
    ref = client.request(
        "GET", f"/repos/{conn.full_name}/git/ref/heads/{repo['default_branch']}", token
    )
    client.request(
        "POST",
        f"/repos/{conn.full_name}/git/refs",
        token,
        body={"ref": f"refs/heads/{name}", "sha": ref["object"]["sha"]},
    )
    link, _ = TaskGitLink.objects.get_or_create(task=task, defaults={"connection": conn})
    link.branch = name
    link.save(update_fields=["branch"])
    return name


def default_branch_name(task) -> str:
    """`feat/<제목 슬러그>(TASK-147)`.

    앞부분은 사람이 읽으라고 채워 두는 것이고 화면에서 고칠 수 있다. 태스크에 자동으로
    붙는 근거는 괄호 안의 번호뿐이다. 제목이 전부 기호라 슬러그가 비면 번호만 남긴다.
    """
    slug = slugify(task.title, allow_unicode=True)[:60].strip("-")
    return f"feat/{slug}({task.number})" if slug else f"feat/{task.number}"


# ---------- 마일스톤 ----------


def _milestone_body(ms) -> dict:
    # 정오(UTC)로 보낸다. 자정이면 시간대 변환에서 하루 밀릴 수 있다. 되읽을 때는 앞 10자(날짜)만 쓴다.
    return {
        "title": ms.name,
        "due_on": f"{ms.target_date.isoformat()}T12:00:00Z",
        "state": "closed" if ms.status == "done" else "open",
    }


def create_gh_milestone(ms, *, actor) -> dict:
    """PM 마일스톤을 GitHub에 만든다. 번호를 저장해 되돌아온 created 웹훅이 '변경 없음'이 되게 한다."""
    conn = ms.project.repo
    data = client.request(
        "POST", f"/repos/{conn.full_name}/milestones", _actor_token(actor), body=_milestone_body(ms)
    )
    ms.gh_number = data["number"]
    ms.save(update_fields=["gh_number"])
    return data


def update_gh_milestone(ms, *, actor):
    conn = ms.project.repo
    client.request(
        "PATCH",
        f"/repos/{conn.full_name}/milestones/{ms.gh_number}",
        _actor_token(actor),
        body=_milestone_body(ms),
    )
