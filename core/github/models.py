from django.conf import settings
from django.db import models


class GitHubInstallation(models.Model):
    """조직 하나에 설치 하나. 비밀은 없고 설치 번호만 있다."""

    org = models.OneToOneField("orgs.Organization", on_delete=models.CASCADE, related_name="github")
    installation_id = models.BigIntegerField(unique=True)
    account_login = models.CharField(max_length=100)  # GitHub 조직 이름
    account_type = models.CharField(max_length=20, blank=True)
    repo_selection = models.CharField(max_length=10, blank=True)  # all | selected
    installed_by = models.ForeignKey(
        settings.AUTH_USER_MODEL, on_delete=models.PROTECT, related_name="+"
    )
    installed_at = models.DateTimeField(auto_now_add=True)
    suspended_at = models.DateTimeField(null=True, blank=True)

    def __str__(self):
        return f"{self.account_login} ({self.installation_id})"


class GitHubIdentity(models.Model):
    """사용자의 GitHub 계정. 토큰은 Fernet으로 암호화해 저장한다.

    토큰을 버리지 않는 이유: 그 사람이 접속하지 않은 동안에도 접근 가능 저장소를
    다시 확인해야 하기 때문이다(GitHub에서 권한이 바뀌면 PM이 알 길이 없다).
    """

    user = models.OneToOneField(
        settings.AUTH_USER_MODEL, on_delete=models.CASCADE, related_name="github"
    )
    github_id = models.BigIntegerField(unique=True)
    login = models.CharField(max_length=100)
    token_enc = models.TextField(blank=True)
    refresh_enc = models.TextField(blank=True)
    token_expires_at = models.DateTimeField(null=True, blank=True)
    refresh_expires_at = models.DateTimeField(null=True, blank=True)
    repos = models.JSONField(default=list, blank=True)  # ["owner/repo", ...]
    repos_checked_at = models.DateTimeField(null=True, blank=True)
    connected_at = models.DateTimeField(auto_now_add=True)

    def __str__(self):
        return f"@{self.login}"


class RepoConnection(models.Model):
    project = models.OneToOneField(
        "projects.Project", on_delete=models.CASCADE, related_name="repo"
    )
    url = models.CharField(max_length=300)  # 사용자가 넣은 원문
    full_name = models.CharField(max_length=200)  # owner/repo
    # 기본값은 비움 = 라벨로 거르지 않는다. "task"가 기본이면 그 라벨을 안 쓰는
    # 저장소에서 이슈가 하나도 안 보인다.
    import_label = models.CharField(max_length=50, blank=True, default="")
    # ponytail: 더 이상 읽지 않는 열이다. 자동 가져오기는 배정된 멤버만 담당자로 삼으므로 선택지가
    # 없어졌다. 설정 라운드(IMPL-PLAN-4)에서 마이그레이션과 함께 지운다.
    assignee_default = models.CharField(max_length=5, default="issue")  # issue | none
    auto_import = models.BooleanField(default=False)
    rule_issue = models.BooleanField(default=True)
    rule_branch = models.BooleanField(default=True)
    rule_commit = models.BooleanField(default=True)
    rule_pr = models.BooleanField(default=True)
    rule_merge = models.BooleanField(default=True)
    last_event_at = models.DateTimeField(null=True, blank=True)
    issues_synced_at = models.DateTimeField(null=True, blank=True)
    created_by = models.ForeignKey(
        settings.AUTH_USER_MODEL, on_delete=models.PROTECT, related_name="+"
    )
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        indexes = [models.Index(fields=["full_name"])]

    def __str__(self):
        return self.full_name


class RepoIssue(models.Model):
    connection = models.ForeignKey(RepoConnection, on_delete=models.CASCADE, related_name="issues")
    number = models.PositiveIntegerField()
    title = models.CharField(max_length=300)
    state = models.CharField(max_length=6, default="open")  # open | closed
    assignee_login = models.CharField(max_length=100, blank=True)
    author_login = models.CharField(max_length=100, blank=True)
    # 이슈 뷰어에서 본문을 읽고 판단할 수 있게 담는다. 길면 잘라 둔다 — 전문은 GitHub 링크로 간다.
    body = models.TextField(blank=True)
    labels = models.JSONField(default=list, blank=True)
    task = models.ForeignKey(
        "tasks.Task", on_delete=models.SET_NULL, null=True, blank=True, related_name="+"
    )
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        ordering = ["-number"]
        constraints = [
            models.UniqueConstraint(fields=["connection", "number"], name="repoissue_conn_number"),
        ]

    def __str__(self):
        return f"#{self.number} {self.title}"


class TaskGitLink(models.Model):
    """네 단계(이슈·브랜치·PR·머지)는 모두 선택적이다. 없는 단계는 빈 값으로 둔다."""

    task = models.OneToOneField("tasks.Task", on_delete=models.CASCADE, related_name="git")
    connection = models.ForeignKey(RepoConnection, on_delete=models.CASCADE, related_name="links")
    issue_number = models.PositiveIntegerField(null=True, blank=True)
    issue_title = models.CharField(max_length=300, blank=True)
    issue_state = models.CharField(max_length=6, blank=True)
    branch = models.CharField(max_length=200, blank=True)
    pr_number = models.PositiveIntegerField(null=True, blank=True)
    pr_title = models.CharField(max_length=300, blank=True)
    pr_state = models.CharField(max_length=6, blank=True)  # open | merged | closed
    merged_at = models.DateTimeField(null=True, blank=True)
    commits = models.JSONField(default=list, blank=True)  # [{sha, message, item, at}]

    def __str__(self):
        return f"{self.connection.full_name} ← {self.task_id}"


class GitEvent(models.Model):
    connection = models.ForeignKey(RepoConnection, on_delete=models.CASCADE, related_name="events")
    delivery_id = models.CharField(max_length=64, unique=True)
    occurred_at = models.DateTimeField()
    kind = models.CharField(max_length=20)
    actor_login = models.CharField(max_length=100, blank=True)
    actor_user = models.ForeignKey(
        settings.AUTH_USER_MODEL, on_delete=models.SET_NULL, null=True, blank=True, related_name="+"
    )
    summary = models.CharField(max_length=200)
    task = models.ForeignKey(
        "tasks.Task", on_delete=models.SET_NULL, null=True, blank=True, related_name="+"
    )
    result = models.CharField(max_length=100, blank=True)

    class Meta:
        ordering = ["-occurred_at", "-id"]

    def __str__(self):
        return f"{self.kind} {self.summary}"


class GitHubTeamLink(models.Model):
    """PM 팀 하나와 GitHub 팀 하나를 잇는다. 연결하지 않는 팀이 더 많다.

    PM 팀을 지워도 GitHub 팀은 남긴다(CASCADE로 이 링크만 사라진다). GitHub 팀에는
    PM이 모르는 저장소 권한이 붙어 있을 수 있어, 지우면 사람들이 접근을 잃는다.
    """

    team = models.OneToOneField("orgs.Team", on_delete=models.CASCADE, related_name="github")
    github_team_id = models.BigIntegerField()
    slug = models.CharField(max_length=100)
    name = models.CharField(max_length=100, blank=True)
    synced_at = models.DateTimeField(null=True, blank=True)

    class Meta:
        constraints = [
            models.UniqueConstraint(fields=["github_team_id"], name="githubteamlink_team_id"),
        ]

    def __str__(self):
        return f"@{self.slug}"
