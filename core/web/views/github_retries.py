"""현재 로그인 세션의 부분 실패를 PM 변경 없이 재시도한다."""

import re
import secrets

from django.conf import settings
from django.contrib import messages
from django.contrib.auth.decorators import login_required
from django.http import Http404
from django.shortcuts import redirect
from django.utils import timezone
from django.views.decorators.http import require_POST

from accounts.models import User
from common.errors import ServiceError
from github import client, writes
from github.client import GitHubError
from orgs.models import Invite, OrgMembership, Team

from .common import can_admin, org_or_404
from .integrations import record_problem

LABELS = {
    "invite": "GitHub 조직 초대",
    "remove": "GitHub 조직에서 제거",
    "rename": "GitHub 팀 이름·설명 반영",
    "member": "GitHub 팀 멤버 반영",
}


def attempt(request, fn, *args, retry, **kwargs):
    warning = writes.try_write(fn, *args, **kwargs)
    org = (
        args[0]
        if retry["kind"] in ("invite", "remove")
        else args[1].org
        if retry["kind"] == "rename"
        else args[1]
    )
    remember_result(request, org, retry, warning)
    return warning


def remember_result(request, org, retry, warning):
    queue = list(request.session.get("github_write_retries", []))

    def same(row):
        return all(
            row.get(key) == retry.get(key)
            for key in ("kind", "org_id", "team_id", "user_id", "login")
        )

    queue = [row for row in queue if not same(row)]
    if warning:
        inst = getattr(org, "github", None)
        queue.append(
            {
                **retry,
                "id": secrets.token_urlsafe(16),
                "installation_id": inst.installation_id if inst else None,
                "at": timezone.now().isoformat(),
                "label": LABELS[retry["kind"]],
            }
        )
        match = re.search(r"HTTP (\d+)", warning)
        error = (
            GitHubError(int(match[1]), "")
            if match
            else GitHubError(0, "")
            if "네트워크 연결 실패" in warning
            else None
        )
        record_problem(request, "writes", LABELS[retry["kind"]], error, target=retry["target"])
    request.session["github_write_retries"] = queue[-20:]


def visible_retries(request):
    org_ids = set(
        OrgMembership.objects.filter(user=request.user, role="admin").values_list(
            "org_id", flat=True
        )
    )
    return [
        row for row in request.session.get("github_write_retries", []) if row["org_id"] in org_ids
    ]


def _stale(message):
    raise ServiceError({"retry": "상태가 변경되어 오래된 재시도를 취소했습니다. " + message})


def _apply(request, row, org):
    inst = getattr(org, "github", None)
    if (inst.installation_id if inst else None) != row["installation_id"]:
        _stale("앱 설치 정보를 다시 확인하세요.")
    if inst.account_type == "User":
        _stale("개인 계정 설치에서는 GitHub 조직·팀 기능을 쓸 수 없습니다.")
    kind = row["kind"]
    actor = request.user
    if kind == "invite":
        invite = Invite.objects.filter(pk=row["invite_id"], org=org).first()
        if (
            invite is None
            or not invite.is_usable
            or (invite.max_uses and invite.use_count >= invite.max_uses)
        ):
            _stale("PM 초대가 만료되거나 폐기됐습니다.")
        # 이미 가입했거나 초대가 대기 중이면 역할을 member로 덮어쓰지 않는다.
        try:
            client.request(
                "GET",
                f"/orgs/{writes._org_login(org)}/memberships/{row['login']}",
                writes._actor_token(actor),
            )
            return
        except GitHubError as error:
            if error.status != 404:
                raise
        writes.invite_to_org(org, row["login"], actor=actor)
        return
    if kind == "remove":
        user = User.objects.filter(pk=row["user_id"]).first()
        if (
            user is None
            or writes._login_of(user) != row["login"]
            or OrgMembership.objects.filter(org=org, user=user).exists()
        ):
            _stale("대상 계정이 바뀌었거나 PM 조직에 다시 가입했습니다.")
        writes.remove_from_org(org, row["login"], actor=actor)
        return
    team = Team.objects.filter(pk=row["team_id"], org=org).first()
    link = getattr(team, "github", None) if team else None
    if link is None or link.github_team_id != row["github_team_id"]:
        _stale("팀 또는 GitHub 팀 연결이 바뀌었습니다.")
    if kind == "member":
        user = User.objects.filter(pk=row["user_id"]).first()
        if (
            user is None
            or writes._login_of(user) != row["login"]
            or team.members.filter(pk=user.pk).exists() != row["add"]
        ):
            _stale("대상 계정 또는 PM 팀 멤버 상태가 바뀌었습니다.")
    # 이름 변경으로 slug가 바뀌어도 변하지 않는 GitHub 팀 ID로 다시 찾는다.
    teams = list(
        client.paginate(f"/orgs/{writes._org_login(org)}/teams", writes._actor_token(actor))
    )
    remote = next((item for item in teams if item["id"] == link.github_team_id), None)
    if remote is None:
        raise ServiceError({"github": "연결된 GitHub 팀을 현재 계정으로 찾지 못했습니다."})
    link.slug = remote["slug"]
    link.save(update_fields=["slug"])
    if kind == "rename":
        writes.rename_gh_team(link, team, actor=actor)
    elif kind == "member":
        if row["add"]:
            try:
                client.request(
                    "GET",
                    f"/orgs/{writes._org_login(org)}/teams/{link.slug}/memberships/{row['login']}",
                    writes._actor_token(actor),
                )
                return
            except GitHubError as error:
                if error.status != 404:
                    raise
        writes.set_gh_team_member(link, org, row["login"], actor=actor, add=row["add"])
    else:
        raise Http404


@login_required
@require_POST
def retry_write(request, retry_id):
    if not settings.GITHUB_ENABLED:
        raise Http404
    queue = list(request.session.get("github_write_retries", []))
    row = next((item for item in queue if item["id"] == retry_id), None)
    if row is None:
        raise Http404
    org = org_or_404(request.user, row["org_id"])
    if not can_admin(request.user, org):
        raise Http404
    completed = False
    try:
        _apply(request, row, org)
        completed = True
        messages.success(request, "GitHub 반영을 완료했습니다. PM 작업은 반복하지 않았습니다.")
    except (ServiceError, GitHubError) as error:
        completed = isinstance(error, ServiceError) and "retry" in error.errors
        record_problem(request, "writes", row["label"], error, target=row["target"])
        text = (
            " ".join(error.errors.values())
            if completed
            else "GitHub 재시도에 실패했습니다. PM 변경은 유지됩니다. 해결 절차에서 조회 상태를 확인하세요."
        )
        messages.warning(request, text, extra_tags="integration-help")
    if completed:
        request.session["github_write_retries"] = [item for item in queue if item["id"] != retry_id]
    return redirect("/help/integrations#writes")
