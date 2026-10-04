from datetime import timedelta

from django import forms
from django.contrib.auth.forms import UserCreationForm

from accounts.models import User
from orgs.models import Team
from projects.models import Project
from tasks.models import Link

PRIORITY_CHOICES = [(n, str(n)) for n in range(10, 0, -1)]


def suggested_due_date(*, org, project=None):
    """설정의 영업일은 월~금이다. 날짜를 강제하지 않고 생성 폼에 제안만 한다."""
    from common.dates import today_kst
    from orgs.settings import effective

    remaining = effective("task.default_due_days", org=org, project=project)
    if not remaining:
        return ""
    day = today_kst()
    while remaining:
        day += timedelta(days=1)
        if day.weekday() < 5:
            remaining -= 1
    return day.isoformat()


class LoginForm(forms.Form):
    """입력만 받는다. AuthenticationForm은 clean에서 먼저 인증해 버려 잠금 확인 순서를 어긴다.

    인증은 뷰가 accounts.auth.authenticate_password로 한다.
    """

    username = forms.CharField(
        label="아이디",
        max_length=150,
        widget=forms.TextInput(attrs={"autofocus": True, "autocomplete": "username"}),
    )
    password = forms.CharField(
        label="비밀번호",
        strip=False,
        widget=forms.PasswordInput(attrs={"autocomplete": "current-password"}),
    )


class SignupForm(UserCreationForm):
    class Meta:
        model = User
        fields = ("username", "display_name")
        labels = {"username": "아이디", "display_name": "표시 이름"}
        help_texts = {"username": "영문·숫자와 @ . + - _ 만, 150자 이하"}


class OrgForm(forms.Form):
    name = forms.CharField(label="조직 이름", max_length=100)
    purpose = forms.CharField(label="목적 한 줄", max_length=200, required=False)


class InviteForm(forms.Form):
    days = forms.IntegerField(label="만료(일)", min_value=1, max_value=90, initial=7)
    gh_invite = forms.BooleanField(label="GitHub 조직에도 초대", required=False)
    gh_login = forms.CharField(label="GitHub 로그인", max_length=100, required=False)


class TeamForm(forms.Form):
    # 빈 이름 검사는 services.create_team/update_team이 한다(업무 규칙은 services에만).
    name = forms.CharField(label="이름", max_length=100, required=False)
    purpose = forms.CharField(label="목적", max_length=200, required=False)
    dev_tools = forms.BooleanField(label="개발 도구(GitHub 팀)", required=False, initial=True)
    is_private = forms.BooleanField(label="팀 화면 비공개", required=False)


class ProjectForm(forms.Form):
    """프로젝트 모달. 관리자는 체크 칩, 상태는 카드형 라디오로 템플릿이 직접 그린다."""

    # 빈 이름 검사는 services.create_project/update_project가 한다(업무 규칙은 services에만).
    name = forms.CharField(label="이름", max_length=100, required=False)
    purpose = forms.CharField(
        label="목적", max_length=200, required=False, widget=forms.Textarea(attrs={"rows": 2})
    )
    owners = forms.ModelMultipleChoiceField(
        label="관리자", queryset=User.objects.none(), required=False
    )
    teams = forms.ModelMultipleChoiceField(
        label="담당 팀", queryset=Team.objects.none(), required=False
    )
    status = forms.ChoiceField(label="상태", choices=Project.STATUSES, initial="preparing")
    # 조직 관리자에게만 그린다. 비어 오면(그리지 않은 경우) 바꾸지 않는다.
    visibility = forms.ChoiceField(label="공개 범위", choices=Project.VISIBILITIES, required=False)
    version = forms.IntegerField(widget=forms.HiddenInput, required=False)
    # 생성 대화상자에서만 그린다. 수정은 설정 탭(project.dev_tools)과 GitHub 탭이 맡는다.
    dev_tools = forms.BooleanField(label="개발 도구 사용", required=False)
    repo_url = forms.CharField(label="GitHub 저장소", max_length=300, required=False)

    def __init__(self, *args, org, **kwargs):
        super().__init__(*args, **kwargs)
        self.fields["owners"].queryset = org.members.filter(is_active=True).order_by("display_name")
        self.fields["teams"].queryset = org.teams.all()


class TaskInlineForm(forms.Form):
    """프로젝트 화면의 태스크 만들기 인라인 폼."""

    title = forms.CharField(max_length=200)
    assignee = forms.ModelChoiceField(queryset=User.objects.none())
    priority = forms.TypedChoiceField(choices=PRIORITY_CHOICES, coerce=int, initial=5)
    due_date = forms.DateField(required=False, widget=forms.DateInput(attrs={"type": "date"}))
    no_due_reason = forms.CharField(max_length=200, required=False)
    # 필수 여부는 services.create_task가 task.require_done_when으로 판단한다. 폼은 칸만 연다.
    done_when = forms.CharField(label="완료 조건", max_length=300, required=False)
    # IdempotencyKey.key는 varchar(100)이다. 클라이언트가 보내는 값이므로 폼에서 막는다.
    idem = forms.CharField(widget=forms.HiddenInput, required=False, max_length=100)

    def __init__(self, *args, org, project=None, **kwargs):
        from orgs.settings import effective

        super().__init__(*args, **kwargs)
        self.fields["assignee"].queryset = org.members.filter(is_active=True).order_by(
            "display_name"
        )
        self.suggested_due_date = suggested_due_date(org=org, project=project)
        self.require_done_when = effective("task.require_done_when", org=org, project=project)


class QuickTaskForm(forms.Form):
    """오늘 화면의 빠른 추가: 제목·프로젝트·중요도·기한(없으면 사유). 담당자는 본인."""

    title = forms.CharField(max_length=200)
    project = forms.ModelChoiceField(queryset=Project.objects.none())
    priority = forms.TypedChoiceField(choices=PRIORITY_CHOICES, coerce=int, initial=5)
    due_date = forms.DateField(required=False, widget=forms.DateInput(attrs={"type": "date"}))
    no_due_reason = forms.CharField(max_length=200, required=False)
    done_when = forms.CharField(label="완료 조건", max_length=300, required=False)
    # IdempotencyKey.key는 varchar(100)이다. 클라이언트가 보내는 값이므로 폼에서 막는다.
    idem = forms.CharField(widget=forms.HiddenInput, required=False, max_length=100)

    def __init__(self, *args, user, **kwargs):
        super().__init__(*args, **kwargs)
        from projects.services import visible_projects

        self.fields["project"].queryset = (
            visible_projects(user)
            .filter(is_archived=False)
            .select_related("org")
            .order_by("org__name", "name")
        )
        # 선택한 프로젝트의 설정에 맞는 제안을 제공한다. 날짜 입력은 사용자가 결정한다.
        from orgs.settings import effective

        self.require_done_when = False
        for project in self.fields["project"].queryset:
            project.suggested_due_date = suggested_due_date(org=project.org, project=project)
            # ponytail: 프로젝트별로 칸을 켜고 끄지 않고, 하나라도 요구하면 칸을 연다.
            if effective("task.require_done_when", org=project.org, project=project):
                self.require_done_when = True


class LinkForm(forms.Form):
    title = forms.CharField(label="제목", max_length=100)
    url = forms.URLField(label="URL", max_length=500)
    kind = forms.ChoiceField(label="종류", initial="doc")

    def __init__(self, *args, dev_tools: bool = True, **kwargs):
        super().__init__(*args, **kwargs)
        # 비개발 프로젝트에는 "이슈" 종류를 보이지 않는다. PR·저장소는 GitHub 연결이 붙인다.
        kinds = (
            ("doc", "out", "issue", "dash", "other")
            if dev_tools
            else ("doc", "out", "dash", "other")
        )
        self.fields["kind"].choices = [(c, label) for c, label in Link.KINDS if c in kinds]


class ProfileForm(forms.Form):
    """Discord 사용자 ID 입력칸은 없다 — 연결은 코드 교환으로만 이뤄진다(GUIDE-00 §3)."""

    display_name = forms.CharField(label="표시 이름", max_length=50)


class TokenForm(forms.Form):
    name = forms.CharField(label="이름", max_length=50)
    scope = forms.ChoiceField(
        label="범위", choices=[("read", "읽기"), ("write", "읽기·쓰기")], initial="read"
    )
    # 조직의 AI 정책(ai.*)이 걸리는지를 정한다. 발급 뒤에는 바꿀 수 없다.
    purpose = forms.ChoiceField(
        label="용도",
        choices=[("ai", "AI 도구(Claude·Codex 등)"), ("person", "사람이 쓰는 스크립트·자동화")],
        initial="ai",
    )
    person_ack = forms.BooleanField(label="이 토큰을 AI 도구에 넣지 않겠습니다", required=False)

    def clean(self):
        data = super().clean()
        # 사람용 토큰을 AI에 주면 조직의 AI 정책(ai.*)이 전부 풀린다. 실수로 고르지 않게 한 번 더 받는다.
        if data.get("purpose") == "person" and not data.get("person_ack"):
            self.add_error("person_ack", "사람용 토큰은 AI 도구에 넣지 않겠다는 확인이 필요합니다.")
        return data
