"""대상 풀기·볼 수 있는 범위(IMPL-PLAN-12 §10.1). 몸체는 A 갈래."""


def resolve_target(user, target: str):
    """ "task:12" 같은 문자열 → (종류, 객체). 요청자가 볼 수 없거나 모르는 종류면 Http404."""
    raise NotImplementedError


def visible_issue(user, issue_id: int):
    """RepoIssue: connection.project가 visible_projects(user)에 있고 can_view_repo(user, full_name)일 때만. 아니면 Http404."""
    raise NotImplementedError
